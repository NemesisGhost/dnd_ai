"""dnd_ai.commands.local_auth — local accounts, browser sessions, and
platform-administrator authorization (docs/PLAN.md §23.1, §23.4, Phase 11R
workstream A/B).

Every test but the one true concurrency test below uses the function-
scoped, always-rolled-back `db_connection` fixture together with each
command's composable `_..._impl(connection, ...)` form — never the public
`Engine`-based wrapper, which opens and commits its *own* independent
transaction and would therefore leak committed rows past `db_connection`'s
rollback (see `dnd_ai.commands.local_auth._create_local_account_impl`'s
own docstring for why both forms exist). The one test that genuinely needs
two independent, concurrently-committing transactions
(`test_concurrent_activation_of_the_same_token_succeeds_exactly_once`) uses
`postgres_engine` and the public wrappers instead, by necessity — matching
`tests/database/test_api_campaigns.py`'s identical pattern for its own
concurrency tests.

`bootstrap_initial_admin`'s own *success* path (creating the very first
user against a genuinely empty `security.users` table) is not exercised
here: this file shares the session-scoped `postgres_engine` database with
every other `tests/database` module, which has already committed users by
the time any test in this file runs, so `security.users` is never actually
empty. Its *fail-closed* behavior (`AlreadyBootstrappedError` once any
user exists) is exercised directly below — that is the security-relevant
half of "fails closed after use," and it holds unconditionally once at
least one user exists, which this shared database always satisfies. The
success path reuses the identical `_create_user_with_activation_token`
helper `create_local_account`/`_create_local_account_impl` also call,
which *is* fully exercised below — see this workstream's own completion
notes for the deliberate scope boundary this leaves (a real empty-database
bootstrap run belongs to `scripts/bootstrap_admin.py`'s own manual/CI-image
verification, not this shared-database suite).
"""

import concurrent.futures
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Connection, Engine, text

from dnd_ai.commands.local_auth import (
    ActivationNotAcceptableError,
    AlreadyBootstrappedError,
    ForeignBrowserSessionError,
    LastActivePlatformAdministratorError,
    LocalAccountNotFoundError,
    LoginNameAlreadyTakenError,
    LoginNameFormatError,
    NotPlatformAdministratorError,
    PasswordResetNotAcceptableError,
    _activate_local_account_impl,
    _admin_revoke_all_browser_sessions_impl,
    _create_local_account_impl,
    _disable_local_account_impl,
    _issue_password_reset_token_impl,
    _reactivate_local_account_impl,
    _reset_password_with_token_impl,
    activate_local_account,
    authenticate_local_user,
    bootstrap_initial_admin,
    change_password,
    create_browser_session,
    create_local_account,
    list_browser_sessions,
    resolve_browser_session_csrf_token,
    resolve_local_session_principal,
    revoke_all_browser_sessions,
    revoke_browser_session,
    revoke_browser_session_by_token,
)
from dnd_ai.domain.access import LOCAL_SESSION_AUTH_METHOD
from dnd_ai.domain.errors import AuthenticationError
from dnd_ai.domain.passwords import PasswordPolicyError
from tests.factories import make_platform_administrator, make_user, status_id

pytestmark = pytest.mark.database

_VALID_PASSWORD = "a genuinely random passphrase 1"
_OTHER_VALID_PASSWORD = "a different random passphrase 2"


@pytest.fixture
def admin_user_id(db_connection: Connection) -> uuid.UUID:
    return make_platform_administrator(db_connection)


@pytest.fixture
def plain_user_id(db_connection: Connection) -> uuid.UUID:
    return make_user(db_connection)


def _issue_activation(
    db_connection: Connection, admin_user_id: uuid.UUID, *, login_name: str | None = None
) -> tuple[uuid.UUID, str, str]:
    """Creates a fresh account + activation token, returns
    (user_id, raw_token, login_name)."""
    result = _create_local_account_impl(
        db_connection,
        created_by_user_id=admin_user_id,
        login_name=login_name or f"user-{uuid.uuid4().hex[:8]}",
        display_name="Test Account",
    )
    return result.user_id, result.raw_token, result.login_name


# ---------------------------------------------------------------------------
# bootstrap_initial_admin
# ---------------------------------------------------------------------------


def test_bootstrap_fails_closed_once_any_user_exists(postgres_engine: Engine) -> None:
    # A committed user, via postgres_engine directly — not the rolled-back
    # db_connection fixture, and not relying on other test files/fixtures
    # having already committed one by the time this test happens to run:
    # bootstrap_initial_admin opens its own transaction on postgres_engine,
    # which only ever sees committed rows from other transactions.
    with postgres_engine.begin() as setup:
        make_user(setup)
    with pytest.raises(AlreadyBootstrappedError):
        bootstrap_initial_admin(
            postgres_engine, login_name="should-never-work", display_name="Should Never Work"
        )


# ---------------------------------------------------------------------------
# create_local_account
# ---------------------------------------------------------------------------


def test_create_local_account_requires_platform_administrator(
    db_connection: Connection, plain_user_id: uuid.UUID
) -> None:
    with pytest.raises(NotPlatformAdministratorError):
        _create_local_account_impl(
            db_connection,
            created_by_user_id=plain_user_id,
            login_name="someone",
            display_name="Someone",
        )


def test_create_local_account_succeeds_for_platform_administrator(
    db_connection: Connection, admin_user_id: uuid.UUID
) -> None:
    result = _create_local_account_impl(
        db_connection,
        created_by_user_id=admin_user_id,
        login_name="New.User_1",
        display_name="New User",
        email="new-user@example.com",
    )
    assert result.login_name == "new.user_1"  # normalized: lowercased
    assert result.raw_token

    row = (
        db_connection.execute(
            text("SELECT display_name, email FROM security.users WHERE user_id = :u"),
            {"u": result.user_id},
        )
        .mappings()
        .one()
    )
    assert row["display_name"] == "New User"
    assert row["email"] == "new-user@example.com"


def test_create_local_account_rejects_a_malformed_login_name(
    db_connection: Connection, admin_user_id: uuid.UUID
) -> None:
    with pytest.raises(LoginNameFormatError):
        _create_local_account_impl(
            db_connection,
            created_by_user_id=admin_user_id,
            login_name="x",  # too short
            display_name="Too Short",
        )


# ---------------------------------------------------------------------------
# activate_local_account
# ---------------------------------------------------------------------------


def test_activate_local_account_succeeds_and_creates_identity_and_credential(
    db_connection: Connection, admin_user_id: uuid.UUID
) -> None:
    user_id, raw_token, login_name = _issue_activation(db_connection, admin_user_id)

    result = _activate_local_account_impl(
        db_connection, raw_activation_token=raw_token, raw_password=_VALID_PASSWORD
    )
    assert result.user_id == user_id
    assert result.login_name == login_name

    credential = db_connection.execute(
        text("SELECT password_hash FROM security.local_credentials WHERE user_id = :u"),
        {"u": user_id},
    ).scalar()
    assert credential is not None
    assert credential.startswith("$argon2id$")

    identity = db_connection.execute(
        text(
            "SELECT 1 FROM security.external_identities "
            "WHERE issuer = 'local' AND subject = :s AND revoked_at IS NULL"
        ),
        {"s": login_name},
    ).scalar()
    assert identity == 1


def test_activate_local_account_rejects_weak_password(
    db_connection: Connection, admin_user_id: uuid.UUID
) -> None:
    _user_id, raw_token, _login_name = _issue_activation(db_connection, admin_user_id)
    with pytest.raises(PasswordPolicyError):
        _activate_local_account_impl(
            db_connection, raw_activation_token=raw_token, raw_password="too short"
        )


def test_activate_local_account_rejects_unknown_token(db_connection: Connection) -> None:
    with pytest.raises(ActivationNotAcceptableError):
        _activate_local_account_impl(
            db_connection,
            raw_activation_token="not-a-real-token",
            raw_password=_VALID_PASSWORD,
        )


def test_activate_local_account_rejects_already_consumed_token(
    db_connection: Connection, admin_user_id: uuid.UUID
) -> None:
    _user_id, raw_token, _login_name = _issue_activation(db_connection, admin_user_id)
    _activate_local_account_impl(
        db_connection, raw_activation_token=raw_token, raw_password=_VALID_PASSWORD
    )
    with pytest.raises(ActivationNotAcceptableError):
        _activate_local_account_impl(
            db_connection, raw_activation_token=raw_token, raw_password=_OTHER_VALID_PASSWORD
        )


def test_activate_local_account_rejects_expired_token(
    db_connection: Connection, admin_user_id: uuid.UUID
) -> None:
    _user_id, raw_token, _login_name = _issue_activation(db_connection, admin_user_id)
    db_connection.execute(
        text(
            "UPDATE security.user_activation_tokens SET expires_at = now() - interval '1 minute' "
            "WHERE token_hash = encode(sha256(convert_to(:token, 'UTF8')), 'hex')"
        ),
        {"token": raw_token},
    )
    with pytest.raises(ActivationNotAcceptableError):
        _activate_local_account_impl(
            db_connection, raw_activation_token=raw_token, raw_password=_VALID_PASSWORD
        )


def test_activate_local_account_rejects_a_login_name_already_claimed(
    db_connection: Connection, admin_user_id: uuid.UUID
) -> None:
    shared_login_name = f"shared-{uuid.uuid4().hex[:8]}"
    _user_a, token_a, _ = _issue_activation(
        db_connection, admin_user_id, login_name=shared_login_name
    )
    _user_b, token_b, _ = _issue_activation(
        db_connection, admin_user_id, login_name=shared_login_name
    )
    _activate_local_account_impl(
        db_connection, raw_activation_token=token_a, raw_password=_VALID_PASSWORD
    )
    with pytest.raises(LoginNameAlreadyTakenError):
        _activate_local_account_impl(
            db_connection, raw_activation_token=token_b, raw_password=_OTHER_VALID_PASSWORD
        )


def test_concurrent_activation_of_the_same_token_succeeds_exactly_once(
    postgres_engine: Engine,
) -> None:
    with postgres_engine.begin() as setup:
        admin_id = make_platform_administrator(setup)
    # create_local_account opens its own independent transaction — must run
    # only after admin_id's own transaction above has actually committed,
    # or that second transaction cannot see the still-uncommitted admin row
    # and NotPlatformAdministratorError fires spuriously.
    result = create_local_account(
        postgres_engine,
        created_by_user_id=admin_id,
        login_name=f"race-{uuid.uuid4().hex[:8]}",
        display_name="Race Account",
    )
    raw_token = result.raw_token

    def _attempt() -> str:
        try:
            activate_local_account(
                postgres_engine, raw_activation_token=raw_token, raw_password=_VALID_PASSWORD
            )
        except ActivationNotAcceptableError:
            return "rejected"
        return "accepted"

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = [f.result() for f in [pool.submit(_attempt), pool.submit(_attempt)]]

    assert sorted(outcomes) == ["accepted", "rejected"]

    with postgres_engine.connect() as verify:
        count = verify.execute(
            text("SELECT count(*) FROM security.local_credentials WHERE user_id = :u"),
            {"u": result.user_id},
        ).scalar_one()
        assert count == 1


# ---------------------------------------------------------------------------
# authenticate_local_user
# ---------------------------------------------------------------------------


@pytest.fixture
def activated_account(
    db_connection: Connection, admin_user_id: uuid.UUID
) -> Iterator[tuple[uuid.UUID, str]]:
    user_id, raw_token, login_name = _issue_activation(db_connection, admin_user_id)
    _activate_local_account_impl(
        db_connection, raw_activation_token=raw_token, raw_password=_VALID_PASSWORD
    )
    yield user_id, login_name


def test_authenticate_local_user_succeeds_with_correct_credentials(
    db_connection: Connection, activated_account: tuple[uuid.UUID, str]
) -> None:
    user_id, login_name = activated_account
    resolved = authenticate_local_user(
        db_connection, login_name=login_name, raw_password=_VALID_PASSWORD
    )
    assert resolved == user_id


def test_authenticate_local_user_rejects_wrong_password(
    db_connection: Connection, activated_account: tuple[uuid.UUID, str]
) -> None:
    _user_id, login_name = activated_account
    resolved = authenticate_local_user(
        db_connection, login_name=login_name, raw_password="totally wrong password"
    )
    assert resolved is None


def test_authenticate_local_user_rejects_unknown_login_name(db_connection: Connection) -> None:
    resolved = authenticate_local_user(
        db_connection, login_name="no-such-login-name", raw_password=_VALID_PASSWORD
    )
    assert resolved is None


def test_authenticate_local_user_login_name_is_case_insensitive(
    db_connection: Connection, activated_account: tuple[uuid.UUID, str]
) -> None:
    user_id, login_name = activated_account
    resolved = authenticate_local_user(
        db_connection, login_name=login_name.upper(), raw_password=_VALID_PASSWORD
    )
    assert resolved == user_id


def test_authenticate_local_user_rejects_inactive_account(
    db_connection: Connection, activated_account: tuple[uuid.UUID, str]
) -> None:
    user_id, login_name = activated_account
    db_connection.execute(
        text("UPDATE security.users SET lifecycle_status_id = :status WHERE user_id = :u"),
        {"status": status_id(db_connection, "lifecycle_statuses", "inactive"), "u": user_id},
    )
    resolved = authenticate_local_user(
        db_connection, login_name=login_name, raw_password=_VALID_PASSWORD
    )
    assert resolved is None


def test_authenticate_local_user_updates_last_login_at(
    db_connection: Connection, activated_account: tuple[uuid.UUID, str]
) -> None:
    user_id, login_name = activated_account
    before = db_connection.execute(
        text("SELECT last_login_at FROM security.users WHERE user_id = :u"), {"u": user_id}
    ).scalar()
    assert before is None
    authenticate_local_user(db_connection, login_name=login_name, raw_password=_VALID_PASSWORD)
    after = db_connection.execute(
        text("SELECT last_login_at FROM security.users WHERE user_id = :u"), {"u": user_id}
    ).scalar()
    assert after is not None


# ---------------------------------------------------------------------------
# Browser sessions
# ---------------------------------------------------------------------------


def test_create_and_resolve_browser_session(
    db_connection: Connection, activated_account: tuple[uuid.UUID, str]
) -> None:
    user_id, _login_name = activated_account
    session = create_browser_session(db_connection, user_id=user_id)

    principal = resolve_local_session_principal(
        db_connection, raw_session_token=session.raw_session_token
    )
    assert principal is not None
    assert principal.user_id == user_id
    assert principal.auth_method == LOCAL_SESSION_AUTH_METHOD
    assert principal.local_session_id == session.browser_session_id


def test_resolve_local_session_principal_rejects_unknown_token(db_connection: Connection) -> None:
    assert resolve_local_session_principal(db_connection, raw_session_token="bogus") is None


def test_resolve_local_session_principal_rejects_revoked_session(
    db_connection: Connection, activated_account: tuple[uuid.UUID, str]
) -> None:
    user_id, _login_name = activated_account
    session = create_browser_session(db_connection, user_id=user_id)
    revoke_browser_session_by_token(db_connection, raw_session_token=session.raw_session_token)
    assert (
        resolve_local_session_principal(db_connection, raw_session_token=session.raw_session_token)
        is None
    )


def test_resolve_local_session_principal_rejects_idle_expired_session(
    db_connection: Connection, activated_account: tuple[uuid.UUID, str]
) -> None:
    user_id, _login_name = activated_account
    session = create_browser_session(db_connection, user_id=user_id)
    db_connection.execute(
        text(
            "UPDATE security.browser_sessions SET idle_expires_at = now() - interval '1 minute' "
            "WHERE browser_session_id = :s"
        ),
        {"s": session.browser_session_id},
    )
    assert (
        resolve_local_session_principal(db_connection, raw_session_token=session.raw_session_token)
        is None
    )


def test_resolve_local_session_principal_rejects_absolute_expired_session(
    db_connection: Connection, activated_account: tuple[uuid.UUID, str]
) -> None:
    """`ck_browser_sessions_expiry_order` (migration 099) enforces
    `idle_expires_at <= absolute_expires_at` at all times, so a session
    whose absolute expiry has passed necessarily has an equally-or-more
    past idle expiry too — both columns must move together to stay
    constraint-valid, which is exactly the "idle can never outlive
    absolute" invariant that constraint exists to guarantee."""
    user_id, _login_name = activated_account
    session = create_browser_session(db_connection, user_id=user_id)
    db_connection.execute(
        text(
            "UPDATE security.browser_sessions "
            "SET idle_expires_at = now() - interval '2 minutes', "
            "    absolute_expires_at = now() - interval '1 minute' "
            "WHERE browser_session_id = :s"
        ),
        {"s": session.browser_session_id},
    )
    assert (
        resolve_local_session_principal(db_connection, raw_session_token=session.raw_session_token)
        is None
    )


def test_resolve_local_session_principal_extends_idle_expiry(
    db_connection: Connection, activated_account: tuple[uuid.UUID, str]
) -> None:
    user_id, _login_name = activated_account
    session = create_browser_session(db_connection, user_id=user_id)
    db_connection.execute(
        text(
            "UPDATE security.browser_sessions SET idle_expires_at = now() + interval '1 second' "
            "WHERE browser_session_id = :s"
        ),
        {"s": session.browser_session_id},
    )
    resolve_local_session_principal(db_connection, raw_session_token=session.raw_session_token)
    new_idle_expires_at = db_connection.execute(
        text("SELECT idle_expires_at FROM security.browser_sessions WHERE browser_session_id = :s"),
        {"s": session.browser_session_id},
    ).scalar()
    assert new_idle_expires_at is not None
    assert new_idle_expires_at > datetime.now(UTC) + timedelta(minutes=5)


def test_resolve_browser_session_csrf_token_matches_created_value(
    db_connection: Connection, activated_account: tuple[uuid.UUID, str]
) -> None:
    user_id, _login_name = activated_account
    session = create_browser_session(db_connection, user_id=user_id)
    stored = resolve_browser_session_csrf_token(
        db_connection, browser_session_id=session.browser_session_id
    )
    assert stored == session.csrf_token


def test_revoke_browser_session_by_token_is_a_no_op_for_unknown_token(
    db_connection: Connection,
) -> None:
    revoke_browser_session_by_token(db_connection, raw_session_token="never-existed")


def test_revoke_browser_session_rejects_a_different_users_session(
    db_connection: Connection, activated_account: tuple[uuid.UUID, str]
) -> None:
    user_id, _login_name = activated_account
    other_user_id = make_user(db_connection)
    session = create_browser_session(db_connection, user_id=user_id)
    with pytest.raises(ForeignBrowserSessionError):
        revoke_browser_session(
            db_connection, user_id=other_user_id, browser_session_id=session.browser_session_id
        )


def test_revoke_browser_session_revokes_own_session(
    db_connection: Connection, activated_account: tuple[uuid.UUID, str]
) -> None:
    user_id, _login_name = activated_account
    session = create_browser_session(db_connection, user_id=user_id)
    revoke_browser_session(
        db_connection, user_id=user_id, browser_session_id=session.browser_session_id
    )
    assert (
        resolve_local_session_principal(db_connection, raw_session_token=session.raw_session_token)
        is None
    )


def test_list_browser_sessions_excludes_revoked_and_marks_current(
    db_connection: Connection, activated_account: tuple[uuid.UUID, str]
) -> None:
    user_id, _login_name = activated_account
    kept = create_browser_session(db_connection, user_id=user_id)
    revoked = create_browser_session(db_connection, user_id=user_id)
    revoke_browser_session_by_token(db_connection, raw_session_token=revoked.raw_session_token)

    summaries = list_browser_sessions(
        db_connection, user_id=user_id, current_browser_session_id=kept.browser_session_id
    )
    ids = {s.browser_session_id for s in summaries}
    assert kept.browser_session_id in ids
    assert revoked.browser_session_id not in ids
    current = next(s for s in summaries if s.browser_session_id == kept.browser_session_id)
    assert current.is_current is True


def test_revoke_all_browser_sessions_revokes_every_active_session(
    db_connection: Connection, activated_account: tuple[uuid.UUID, str]
) -> None:
    user_id, _login_name = activated_account
    a = create_browser_session(db_connection, user_id=user_id)
    b = create_browser_session(db_connection, user_id=user_id)
    revoke_all_browser_sessions(db_connection, user_id=user_id)
    assert (
        resolve_local_session_principal(db_connection, raw_session_token=a.raw_session_token)
        is None
    )
    assert (
        resolve_local_session_principal(db_connection, raw_session_token=b.raw_session_token)
        is None
    )


# ---------------------------------------------------------------------------
# change_password
# ---------------------------------------------------------------------------


def test_change_password_requires_correct_current_password(
    db_connection: Connection, activated_account: tuple[uuid.UUID, str]
) -> None:
    user_id, _login_name = activated_account
    with pytest.raises(AuthenticationError):
        change_password(
            db_connection,
            user_id=user_id,
            current_raw_password="wrong current password",
            new_raw_password=_OTHER_VALID_PASSWORD,
        )


def test_change_password_succeeds_and_new_password_authenticates(
    db_connection: Connection, activated_account: tuple[uuid.UUID, str]
) -> None:
    user_id, login_name = activated_account
    change_password(
        db_connection,
        user_id=user_id,
        current_raw_password=_VALID_PASSWORD,
        new_raw_password=_OTHER_VALID_PASSWORD,
    )
    assert (
        authenticate_local_user(db_connection, login_name=login_name, raw_password=_VALID_PASSWORD)
        is None
    )
    assert (
        authenticate_local_user(
            db_connection, login_name=login_name, raw_password=_OTHER_VALID_PASSWORD
        )
        == user_id
    )


def test_change_password_rejects_a_weak_new_password(
    db_connection: Connection, activated_account: tuple[uuid.UUID, str]
) -> None:
    user_id, _login_name = activated_account
    with pytest.raises(PasswordPolicyError):
        change_password(
            db_connection,
            user_id=user_id,
            current_raw_password=_VALID_PASSWORD,
            new_raw_password="too short",
        )


# ---------------------------------------------------------------------------
# issue_password_reset_token / reset_password_with_token
# ---------------------------------------------------------------------------


def test_issue_password_reset_token_requires_platform_administrator(
    db_connection: Connection, plain_user_id: uuid.UUID, activated_account: tuple[uuid.UUID, str]
) -> None:
    target_user_id, _login_name = activated_account
    with pytest.raises(NotPlatformAdministratorError):
        _issue_password_reset_token_impl(
            db_connection, requested_by_user_id=plain_user_id, target_user_id=target_user_id
        )


def test_reset_password_with_token_sets_new_password_and_revokes_sessions_by_default(
    db_connection: Connection, admin_user_id: uuid.UUID, activated_account: tuple[uuid.UUID, str]
) -> None:
    user_id, login_name = activated_account
    session = create_browser_session(db_connection, user_id=user_id)

    issued = _issue_password_reset_token_impl(
        db_connection, requested_by_user_id=admin_user_id, target_user_id=user_id
    )
    result = _reset_password_with_token_impl(
        db_connection, raw_reset_token=issued.raw_token, new_raw_password=_OTHER_VALID_PASSWORD
    )
    assert result.user_id == user_id
    assert result.sessions_revoked is True

    assert (
        authenticate_local_user(
            db_connection, login_name=login_name, raw_password=_OTHER_VALID_PASSWORD
        )
        == user_id
    )
    assert (
        resolve_local_session_principal(db_connection, raw_session_token=session.raw_session_token)
        is None
    )


def test_reset_password_with_token_can_opt_out_of_revoking_sessions(
    db_connection: Connection, admin_user_id: uuid.UUID, activated_account: tuple[uuid.UUID, str]
) -> None:
    user_id, _login_name = activated_account
    session = create_browser_session(db_connection, user_id=user_id)

    issued = _issue_password_reset_token_impl(
        db_connection,
        requested_by_user_id=admin_user_id,
        target_user_id=user_id,
        revoke_sessions=False,
    )
    result = _reset_password_with_token_impl(
        db_connection, raw_reset_token=issued.raw_token, new_raw_password=_OTHER_VALID_PASSWORD
    )
    assert result.sessions_revoked is False
    assert (
        resolve_local_session_principal(db_connection, raw_session_token=session.raw_session_token)
        is not None
    )


def test_reset_password_with_token_rejects_reuse(
    db_connection: Connection, admin_user_id: uuid.UUID, activated_account: tuple[uuid.UUID, str]
) -> None:
    user_id, _login_name = activated_account
    issued = _issue_password_reset_token_impl(
        db_connection, requested_by_user_id=admin_user_id, target_user_id=user_id
    )
    _reset_password_with_token_impl(
        db_connection, raw_reset_token=issued.raw_token, new_raw_password=_OTHER_VALID_PASSWORD
    )
    with pytest.raises(PasswordResetNotAcceptableError):
        _reset_password_with_token_impl(
            db_connection, raw_reset_token=issued.raw_token, new_raw_password=_VALID_PASSWORD
        )


# ---------------------------------------------------------------------------
# Administrative account lifecycle: disable, reactivate, revoke-all-sessions
# (Phase 13B blocker 3)
# ---------------------------------------------------------------------------


def test_disable_local_account_requires_platform_administrator(
    db_connection: Connection, plain_user_id: uuid.UUID, activated_account: tuple[uuid.UUID, str]
) -> None:
    user_id, _login_name = activated_account
    with pytest.raises(NotPlatformAdministratorError):
        _disable_local_account_impl(
            db_connection, admin_user_id=plain_user_id, target_user_id=user_id
        )


def test_disable_local_account_raises_for_missing_target(
    db_connection: Connection, admin_user_id: uuid.UUID
) -> None:
    with pytest.raises(LocalAccountNotFoundError):
        _disable_local_account_impl(
            db_connection, admin_user_id=admin_user_id, target_user_id=uuid.uuid4()
        )


def test_disable_local_account_sets_inactive_and_revokes_sessions(
    db_connection: Connection, admin_user_id: uuid.UUID, activated_account: tuple[uuid.UUID, str]
) -> None:
    user_id, _login_name = activated_account
    session = create_browser_session(db_connection, user_id=user_id)

    result = _disable_local_account_impl(
        db_connection, admin_user_id=admin_user_id, target_user_id=user_id
    )

    assert result.previous_lifecycle_status_code == "active"
    assert result.new_lifecycle_status_code == "inactive"
    assert (
        resolve_local_session_principal(db_connection, raw_session_token=session.raw_session_token)
        is None
    )


def test_disable_local_account_prevents_further_login(
    db_connection: Connection, admin_user_id: uuid.UUID, activated_account: tuple[uuid.UUID, str]
) -> None:
    user_id, login_name = activated_account
    _disable_local_account_impl(db_connection, admin_user_id=admin_user_id, target_user_id=user_id)
    assert (
        authenticate_local_user(db_connection, login_name=login_name, raw_password=_VALID_PASSWORD)
        is None
    )


def test_disable_local_account_is_idempotent(
    db_connection: Connection, admin_user_id: uuid.UUID, activated_account: tuple[uuid.UUID, str]
) -> None:
    user_id, _login_name = activated_account
    _disable_local_account_impl(db_connection, admin_user_id=admin_user_id, target_user_id=user_id)
    result = _disable_local_account_impl(
        db_connection, admin_user_id=admin_user_id, target_user_id=user_id
    )
    assert result.previous_lifecycle_status_code == "inactive"
    assert result.new_lifecycle_status_code == "inactive"


def test_reactivate_local_account_requires_platform_administrator(
    db_connection: Connection, plain_user_id: uuid.UUID, activated_account: tuple[uuid.UUID, str]
) -> None:
    user_id, _login_name = activated_account
    with pytest.raises(NotPlatformAdministratorError):
        _reactivate_local_account_impl(
            db_connection, admin_user_id=plain_user_id, target_user_id=user_id
        )


def test_reactivate_local_account_raises_for_missing_target(
    db_connection: Connection, admin_user_id: uuid.UUID
) -> None:
    with pytest.raises(LocalAccountNotFoundError):
        _reactivate_local_account_impl(
            db_connection, admin_user_id=admin_user_id, target_user_id=uuid.uuid4()
        )


def test_reactivate_local_account_restores_login_but_not_old_sessions(
    db_connection: Connection, admin_user_id: uuid.UUID, activated_account: tuple[uuid.UUID, str]
) -> None:
    user_id, login_name = activated_account
    session = create_browser_session(db_connection, user_id=user_id)
    _disable_local_account_impl(db_connection, admin_user_id=admin_user_id, target_user_id=user_id)

    result = _reactivate_local_account_impl(
        db_connection, admin_user_id=admin_user_id, target_user_id=user_id
    )

    assert result.previous_lifecycle_status_code == "inactive"
    assert result.new_lifecycle_status_code == "active"
    # Login works again...
    assert (
        authenticate_local_user(db_connection, login_name=login_name, raw_password=_VALID_PASSWORD)
        is not None
    )
    # ...but the session that was active before disablement stays revoked.
    assert (
        resolve_local_session_principal(db_connection, raw_session_token=session.raw_session_token)
        is None
    )


def test_reactivate_local_account_is_idempotent(
    db_connection: Connection, admin_user_id: uuid.UUID, activated_account: tuple[uuid.UUID, str]
) -> None:
    user_id, _login_name = activated_account
    result = _reactivate_local_account_impl(
        db_connection, admin_user_id=admin_user_id, target_user_id=user_id
    )
    assert result.previous_lifecycle_status_code == "active"
    assert result.new_lifecycle_status_code == "active"


def test_admin_revoke_all_browser_sessions_requires_platform_administrator(
    db_connection: Connection, plain_user_id: uuid.UUID, activated_account: tuple[uuid.UUID, str]
) -> None:
    user_id, _login_name = activated_account
    with pytest.raises(NotPlatformAdministratorError):
        _admin_revoke_all_browser_sessions_impl(
            db_connection, admin_user_id=plain_user_id, target_user_id=user_id
        )


def test_admin_revoke_all_browser_sessions_raises_for_missing_target(
    db_connection: Connection, admin_user_id: uuid.UUID
) -> None:
    with pytest.raises(LocalAccountNotFoundError):
        _admin_revoke_all_browser_sessions_impl(
            db_connection, admin_user_id=admin_user_id, target_user_id=uuid.uuid4()
        )


def test_admin_revoke_all_browser_sessions_revokes_every_session_for_the_target(
    db_connection: Connection, admin_user_id: uuid.UUID, activated_account: tuple[uuid.UUID, str]
) -> None:
    user_id, _login_name = activated_account
    session_a = create_browser_session(db_connection, user_id=user_id)
    session_b = create_browser_session(db_connection, user_id=user_id)

    result = _admin_revoke_all_browser_sessions_impl(
        db_connection, admin_user_id=admin_user_id, target_user_id=user_id
    )

    assert result.revoked_count == 2
    assert (
        resolve_local_session_principal(
            db_connection, raw_session_token=session_a.raw_session_token
        )
        is None
    )
    assert (
        resolve_local_session_principal(
            db_connection, raw_session_token=session_b.raw_session_token
        )
        is None
    )


def test_admin_revoke_all_browser_sessions_does_not_affect_other_users(
    db_connection: Connection, admin_user_id: uuid.UUID, activated_account: tuple[uuid.UUID, str]
) -> None:
    user_id, _login_name = activated_account
    other_user_id = make_user(db_connection)
    other_session = create_browser_session(db_connection, user_id=other_user_id)
    create_browser_session(db_connection, user_id=user_id)

    _admin_revoke_all_browser_sessions_impl(
        db_connection, admin_user_id=admin_user_id, target_user_id=user_id
    )

    assert (
        resolve_local_session_principal(
            db_connection, raw_session_token=other_session.raw_session_token
        )
        is not None
    )


def test_admin_revoke_all_browser_sessions_is_idempotent(
    db_connection: Connection, admin_user_id: uuid.UUID, activated_account: tuple[uuid.UUID, str]
) -> None:
    user_id, _login_name = activated_account
    result = _admin_revoke_all_browser_sessions_impl(
        db_connection, admin_user_id=admin_user_id, target_user_id=user_id
    )
    assert result.revoked_count == 0


# ---------------------------------------------------------------------------
# The last-active-platform-administrator invariant (security review
# follow-up: a sole administrator could disable themselves, or two
# administrators could disable each other concurrently, leaving zero
# principals able to reactivate anyone).
# ---------------------------------------------------------------------------


def _neutralize_other_active_administrators(
    db_connection: Connection, *, keep: set[uuid.UUID]
) -> None:
    """Marks every `is_platform_administrator` user other than `keep`
    inactive, *on this connection's own uncommitted transaction only* —
    `db_connection` is always rolled back at the end of the test that
    calls this, so this never durably affects the shared `postgres_engine`
    database other tests in the same session rely on. Needed because the
    last-active-administrator invariant is a genuinely global count
    (`security.users.is_platform_administrator` has no campaign/tenant
    scoping), and this shared session database routinely already has other
    committed administrators from earlier tests/fixtures by the time any
    one test runs — without neutralizing them first, a test cannot reduce
    the *effective* global count to a specific, known value like 1."""
    inactive_status = status_id(db_connection, "lifecycle_statuses", "inactive")
    db_connection.execute(
        text("""
            UPDATE security.users
            SET lifecycle_status_id = :status
            WHERE is_platform_administrator AND NOT (user_id = ANY(:keep))
        """),
        {"status": inactive_status, "keep": list(keep)},
    )


def _active_administrator_count(connection: Connection) -> int:
    return connection.execute(
        text("""
            SELECT count(*)
            FROM security.users u
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = u.lifecycle_status_id
            WHERE u.is_platform_administrator AND ls.code = 'active'
        """)
    ).scalar_one()


def test_disable_rejects_self_disable_of_the_sole_active_administrator(
    db_connection: Connection,
) -> None:
    admin_id = make_platform_administrator(db_connection)
    _neutralize_other_active_administrators(db_connection, keep={admin_id})

    with pytest.raises(LastActivePlatformAdministratorError):
        _disable_local_account_impl(db_connection, admin_user_id=admin_id, target_user_id=admin_id)


def test_disable_of_the_only_other_active_administrator_succeeds_when_actor_remains(
    db_connection: Connection,
) -> None:
    """Two active administrators, A and B. A disables B. A itself remains
    active, so the platform never has zero active administrators — this
    must succeed, not be rejected merely because only one would remain
    afterward."""
    admin_a = make_platform_administrator(db_connection, display_name="Admin A")
    admin_b = make_platform_administrator(db_connection, display_name="Admin B")
    _neutralize_other_active_administrators(db_connection, keep={admin_a, admin_b})

    result = _disable_local_account_impl(
        db_connection, admin_user_id=admin_a, target_user_id=admin_b
    )
    assert result.new_lifecycle_status_code == "inactive"
    assert _active_administrator_count(db_connection) == 1


def test_disabling_the_resulting_sole_administrator_is_then_rejected(
    db_connection: Connection,
) -> None:
    """Following on from the previous scenario: once disabling B leaves A
    as the only active administrator, disabling A next — even though A
    and B were, a moment ago, two independent administrators — is
    rejected. One administrator must never be able to disable the only
    other active administrator when doing so leaves none."""
    admin_a = make_platform_administrator(db_connection, display_name="Admin A")
    admin_b = make_platform_administrator(db_connection, display_name="Admin B")
    _neutralize_other_active_administrators(db_connection, keep={admin_a, admin_b})

    _disable_local_account_impl(db_connection, admin_user_id=admin_a, target_user_id=admin_b)

    with pytest.raises(LastActivePlatformAdministratorError):
        _disable_local_account_impl(db_connection, admin_user_id=admin_a, target_user_id=admin_a)


def test_self_disable_succeeds_when_another_active_administrator_remains(
    db_connection: Connection,
) -> None:
    admin_a = make_platform_administrator(db_connection, display_name="Admin A")
    admin_b = make_platform_administrator(db_connection, display_name="Admin B")
    _neutralize_other_active_administrators(db_connection, keep={admin_a, admin_b})

    result = _disable_local_account_impl(
        db_connection, admin_user_id=admin_a, target_user_id=admin_a
    )
    assert result.new_lifecycle_status_code == "inactive"
    assert _active_administrator_count(db_connection) == 1


def test_disable_of_non_administrator_account_succeeds_regardless_of_administrator_count(
    db_connection: Connection,
) -> None:
    admin_id = make_platform_administrator(db_connection)
    _neutralize_other_active_administrators(db_connection, keep={admin_id})
    plain_user_id = make_user(db_connection)

    result = _disable_local_account_impl(
        db_connection, admin_user_id=admin_id, target_user_id=plain_user_id
    )
    assert result.new_lifecycle_status_code == "inactive"
    # The sole administrator is completely unaffected.
    assert _active_administrator_count(db_connection) == 1


def test_failed_invariant_check_rolls_back_lifecycle_and_session_changes(
    db_connection: Connection,
) -> None:
    admin_id = make_platform_administrator(db_connection)
    _neutralize_other_active_administrators(db_connection, keep={admin_id})
    session = create_browser_session(db_connection, user_id=admin_id)

    with pytest.raises(LastActivePlatformAdministratorError):
        _disable_local_account_impl(db_connection, admin_user_id=admin_id, target_user_id=admin_id)

    # Lifecycle status is unchanged...
    row = (
        db_connection.execute(
            text("""
                SELECT ls.code
                FROM security.users u
                JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = u.lifecycle_status_id
                WHERE u.user_id = :u
            """),
            {"u": admin_id},
        )
        .mappings()
        .one()
    )
    assert row["code"] == "active"
    # ...and the session that would have been revoked as part of a
    # successful disable was never touched, since
    # _disable_local_account_impl's own revoke_all_browser_sessions call
    # is never reached once the invariant check raises first.
    assert (
        resolve_local_session_principal(db_connection, raw_session_token=session.raw_session_token)
        is not None
    )


def test_concurrent_disable_cannot_leave_zero_active_administrators(
    postgres_engine: Engine,
) -> None:
    """The exact race the advisory lock exists to close: two
    administrators, each attempting to disable the other, submitted at
    (as close as this test can arrange to) the same moment. Without
    serialization, both transactions could independently read "the other
    one is still active" before either commits, and both then proceed,
    leaving zero. Uses `postgres_engine` and two genuinely independent,
    concurrently-committing transactions — by necessity, matching this
    file's own established pattern (see
    `test_concurrent_activation_of_the_same_token_succeeds_exactly_once`)
    — with the shared session database's other already-committed active
    administrators neutralized first and restored afterward so this
    test's own count check is deterministic."""
    with postgres_engine.begin() as setup:
        previously_active_admin_ids = [
            row[0]
            for row in setup.execute(
                text("""
                    SELECT u.user_id
                    FROM security.users u
                    JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = u.lifecycle_status_id
                    WHERE u.is_platform_administrator AND ls.code = 'active'
                """)
            )
        ]
        if previously_active_admin_ids:
            inactive_status = status_id(setup, "lifecycle_statuses", "inactive")
            setup.execute(
                text(
                    "UPDATE security.users SET lifecycle_status_id = :status "
                    "WHERE user_id = ANY(:ids)"
                ),
                {"status": inactive_status, "ids": previously_active_admin_ids},
            )
        admin_a = make_platform_administrator(setup, display_name="Concurrent Admin A")
        admin_b = make_platform_administrator(setup, display_name="Concurrent Admin B")

    try:

        def _disable(admin_user_id: uuid.UUID, target_user_id: uuid.UUID) -> str:
            try:
                with postgres_engine.begin() as connection:
                    _disable_local_account_impl(
                        connection, admin_user_id=admin_user_id, target_user_id=target_user_id
                    )
            except LastActivePlatformAdministratorError:
                return "rejected"
            return "accepted"

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = [
                f.result()
                for f in [
                    pool.submit(_disable, admin_b, admin_a),
                    pool.submit(_disable, admin_a, admin_b),
                ]
            ]

        # Exactly one of the two mutually-exclusive disables must have won
        # — never both (which would leave zero), and, since each admin
        # started active, never neither.
        assert sorted(outcomes) == ["accepted", "rejected"]
        with postgres_engine.connect() as verify:
            count = verify.execute(
                text("""
                    SELECT count(*)
                    FROM security.users u
                    JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = u.lifecycle_status_id
                    WHERE u.is_platform_administrator AND ls.code = 'active'
                      AND u.user_id IN (:a, :b)
                """),
                {"a": admin_a, "b": admin_b},
            ).scalar_one()
        assert count == 1
    finally:
        with postgres_engine.begin() as cleanup:
            if previously_active_admin_ids:
                active_status = status_id(cleanup, "lifecycle_statuses", "active")
                cleanup.execute(
                    text(
                        "UPDATE security.users SET lifecycle_status_id = :status "
                        "WHERE user_id = ANY(:ids)"
                    ),
                    {"status": active_status, "ids": previously_active_admin_ids},
                )

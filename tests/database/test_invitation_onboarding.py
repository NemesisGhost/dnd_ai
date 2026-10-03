"""Tests for `dnd_ai.commands.invitation_onboarding` and `dnd_ai.commands.
local_auth._register_invited_local_account_impl` — Phase 13E checkpoint 8a,
the command-layer half of the single-link campaign-invitation onboarding
flow (no HTTP surface yet; that is checkpoint 8b).

Covers: begin/status/complete/cancel happy paths for both an already-
signed-in visitor and a brand-new registrant, the shared non-disclosing
`OnboardingNotAvailableError` for every rejection cause (expired
invitation, revoked invitation, already-accepted invitation, consumed
session, cancelled session, expired session), the S-2 "replace, never
merge" behavior for a pre-existing live session, the P-7 window-clamping
rule, the P-3 reactivation-restores-nothing invariant re-proved through
this path, the P-5 zero-orphan-rows guarantee on a policy rejection, and
the D-11 reserved-login-name denylist plus the database-level
`ck_users_display_name_length` bound.
"""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from dnd_ai.commands.campaign_invitations import (
    create_campaign_invitation,
    revoke_campaign_invitation,
)
from dnd_ai.commands.invitation_onboarding import (
    OnboardingNotAvailableError,
    begin_invitation_onboarding,
    cancel_invitation_onboarding,
    complete_invitation_onboarding,
    resolve_invitation_onboarding_status,
)
from dnd_ai.commands.local_auth import (
    LoginNameFormatError,
    _register_invited_local_account_impl,
)
from dnd_ai.domain.passwords import PasswordPolicyError
from tests.factories import (
    lookup_id,
    make_campaign,
    make_campaign_membership,
    make_membership_role,
    make_role,
    make_role_capability,
    make_timeline,
    make_user,
    make_world,
)

pytestmark = pytest.mark.database

_VALID_PASSWORD = "correct-onboarding-password-15"


class _Fixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.campaign_id = make_campaign(
            connection, self.timeline_id, "Onboarding Campaign", lifecycle_status_code="pending"
        )
        access_manage_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "access.manage"
        )
        manager_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"manager_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, manager_role_id, access_manage_id)
        self.manager_user_id = make_user(connection, "Onboarding Manager")
        self.manager_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.manager_user_id
        )
        make_membership_role(connection, self.manager_membership_id, manager_role_id)

    def invite(self, connection: Connection, *, ttl: timedelta = timedelta(days=7)) -> str:
        return create_campaign_invitation(
            connection,
            campaign_id=self.campaign_id,
            invited_by_membership_id=self.manager_membership_id,
            ttl=ttl,
        ).token


def _unique_login_name() -> str:
    return f"onboard{uuid.uuid4().hex[:12]}"


def test_begin_then_status_reports_campaign_and_expiries(db_connection: Connection) -> None:
    fixture = _Fixture(db_connection, "onb-begin-status")
    raw_token = fixture.invite(db_connection)

    begun = begin_invitation_onboarding(db_connection, invitation_token=raw_token)
    assert begun.campaign_display_name == "Onboarding Campaign"
    assert begun.onboarding_expires_at <= begun.invitation_expires_at

    status = resolve_invitation_onboarding_status(
        db_connection, onboarding_token=begun.raw_onboarding_token
    )
    assert status.campaign_display_name == "Onboarding Campaign"
    assert status.onboarding_expires_at == begun.onboarding_expires_at


def test_begin_rejects_nonexistent_token(db_connection: Connection) -> None:
    with pytest.raises(OnboardingNotAvailableError):
        begin_invitation_onboarding(db_connection, invitation_token="not-a-real-token")


def test_begin_rejects_revoked_invitation(db_connection: Connection) -> None:
    fixture = _Fixture(db_connection, "onb-begin-revoked")
    raw_token = fixture.invite(db_connection)
    invitation_id = db_connection.execute(
        text(
            "SELECT campaign_invitation_id FROM security.campaign_invitations "
            "WHERE campaign_id = :c"
        ),
        {"c": fixture.campaign_id},
    ).scalar_one()
    revoke_campaign_invitation(
        db_connection, campaign_id=fixture.campaign_id, campaign_invitation_id=invitation_id
    )
    with pytest.raises(OnboardingNotAvailableError):
        begin_invitation_onboarding(db_connection, invitation_token=raw_token)


def test_begin_rejects_expired_invitation(db_connection: Connection) -> None:
    fixture = _Fixture(db_connection, "onb-begin-expired")
    raw_token = fixture.invite(db_connection, ttl=timedelta(seconds=-1))
    with pytest.raises(OnboardingNotAvailableError):
        begin_invitation_onboarding(db_connection, invitation_token=raw_token)


def test_begin_rejects_already_accepted_invitation(db_connection: Connection) -> None:
    from dnd_ai.commands.campaign_invitations import accept_campaign_invitation

    fixture = _Fixture(db_connection, "onb-begin-accepted")
    raw_token = fixture.invite(db_connection)
    other_user_id = make_user(db_connection, "Other Accepter")
    accept_campaign_invitation(db_connection, token=raw_token, accepting_user_id=other_user_id)
    with pytest.raises(OnboardingNotAvailableError):
        begin_invitation_onboarding(db_connection, invitation_token=raw_token)


def test_begin_window_clamps_to_invitation_expiry(db_connection: Connection) -> None:
    """P-7: the onboarding window never outlives the invitation, even when
    the invitation's own TTL is shorter than the default 20-minute window."""
    fixture = _Fixture(db_connection, "onb-clamp")
    raw_token = fixture.invite(db_connection, ttl=timedelta(minutes=5))
    begun = begin_invitation_onboarding(db_connection, invitation_token=raw_token)
    assert begun.onboarding_expires_at == begun.invitation_expires_at


def test_begin_replaces_a_pre_existing_live_session_for_the_same_browser(
    db_connection: Connection,
) -> None:
    """S-2: `start` must replace, never merge, a pre-existing live session."""
    fixture = _Fixture(db_connection, "onb-replace")
    raw_token = fixture.invite(db_connection)
    first = begin_invitation_onboarding(db_connection, invitation_token=raw_token)

    second = begin_invitation_onboarding(
        db_connection,
        invitation_token=raw_token,
        existing_onboarding_token=first.raw_onboarding_token,
    )
    assert second.invitation_onboarding_session_id != first.invitation_onboarding_session_id

    # The first session is now cancelled -- unusable even though it never expired.
    with pytest.raises(OnboardingNotAvailableError):
        resolve_invitation_onboarding_status(
            db_connection, onboarding_token=first.raw_onboarding_token
        )
    # The second (replacement) session is still live.
    resolve_invitation_onboarding_status(
        db_connection, onboarding_token=second.raw_onboarding_token
    )


def test_complete_binds_invitation_to_the_signed_in_user(db_connection: Connection) -> None:
    fixture = _Fixture(db_connection, "onb-complete")
    raw_token = fixture.invite(db_connection)
    begun = begin_invitation_onboarding(db_connection, invitation_token=raw_token)
    signed_in_user_id = make_user(db_connection, "Already Signed In")

    result = complete_invitation_onboarding(
        db_connection, onboarding_token=begun.raw_onboarding_token, user_id=signed_in_user_id
    )
    assert result.campaign_id == fixture.campaign_id
    assert result.campaign_display_name == "Onboarding Campaign"

    membership_row = db_connection.execute(
        text(
            "SELECT ended_at FROM security.campaign_memberships WHERE campaign_membership_id = :m"
        ),
        {"m": result.campaign_membership_id},
    ).one()
    assert membership_row.ended_at is None

    # The session is now consumed -- a second complete call fails generically.
    with pytest.raises(OnboardingNotAvailableError):
        complete_invitation_onboarding(
            db_connection, onboarding_token=begun.raw_onboarding_token, user_id=signed_in_user_id
        )


def test_complete_rejects_an_expired_onboarding_session(db_connection: Connection) -> None:
    fixture = _Fixture(db_connection, "onb-session-expired")
    raw_token = fixture.invite(db_connection)
    begun = begin_invitation_onboarding(db_connection, invitation_token=raw_token)
    db_connection.execute(
        text(
            "UPDATE security.invitation_onboarding_sessions "
            "SET created_at = now() - interval '30 minutes', "
            "    expires_at = now() - interval '1 second' "
            "WHERE invitation_onboarding_session_id = :s"
        ),
        {"s": begun.invitation_onboarding_session_id},
    )
    signed_in_user_id = make_user(db_connection, "Too Slow")
    with pytest.raises(OnboardingNotAvailableError):
        complete_invitation_onboarding(
            db_connection, onboarding_token=begun.raw_onboarding_token, user_id=signed_in_user_id
        )


def test_cancel_is_idempotent_and_blocks_completion(db_connection: Connection) -> None:
    fixture = _Fixture(db_connection, "onb-cancel")
    raw_token = fixture.invite(db_connection)
    begun = begin_invitation_onboarding(db_connection, invitation_token=raw_token)

    first_cancel = cancel_invitation_onboarding(
        db_connection, onboarding_token=begun.raw_onboarding_token
    )
    assert first_cancel.cancelled is True

    second_cancel = cancel_invitation_onboarding(
        db_connection, onboarding_token=begun.raw_onboarding_token
    )
    assert second_cancel.cancelled is False

    with pytest.raises(OnboardingNotAvailableError):
        resolve_invitation_onboarding_status(
            db_connection, onboarding_token=begun.raw_onboarding_token
        )


def test_cancel_rejects_unknown_token(db_connection: Connection) -> None:
    with pytest.raises(OnboardingNotAvailableError):
        cancel_invitation_onboarding(db_connection, onboarding_token="never-issued")


class _InvitedRegistration:
    """Small factory closure so multiple tests can register with one line
    while varying login_name/display_name/password independently."""

    def __init__(self, connection: Connection, fixture: _Fixture) -> None:
        self.connection = connection
        self.fixture = fixture

    def register(
        self,
        *,
        onboarding_token: str,
        login_name: str | None = None,
        display_name: str = "New Registrant",
        password: str = _VALID_PASSWORD,
    ):
        return _register_invited_local_account_impl(
            self.connection,
            onboarding_token=onboarding_token,
            login_name=login_name or _unique_login_name(),
            display_name=display_name,
            raw_password=password,
        )


def test_register_creates_account_and_accepts_invitation(db_connection: Connection) -> None:
    fixture = _Fixture(db_connection, "onb-register")
    raw_token = fixture.invite(db_connection)
    begun = begin_invitation_onboarding(db_connection, invitation_token=raw_token)

    login_name = _unique_login_name()
    result = _InvitedRegistration(db_connection, fixture).register(
        onboarding_token=begun.raw_onboarding_token, login_name=login_name
    )
    assert result.login_name == login_name
    assert result.campaign_id == fixture.campaign_id
    assert result.campaign_display_name == "Onboarding Campaign"
    assert result.session.raw_session_token

    membership_row = db_connection.execute(
        text(
            "SELECT ended_at FROM security.campaign_memberships WHERE campaign_membership_id = :m"
        ),
        {"m": result.campaign_membership_id},
    ).one()
    assert membership_row.ended_at is None

    identity_count = db_connection.execute(
        text(
            "SELECT count(*) FROM security.external_identities "
            "WHERE user_id = :u AND revoked_at IS NULL"
        ),
        {"u": result.user_id},
    ).scalar_one()
    assert identity_count == 1

    # Onboarding session consumed -- a retry fails generically.
    with pytest.raises(OnboardingNotAvailableError):
        _InvitedRegistration(db_connection, fixture).register(
            onboarding_token=begun.raw_onboarding_token
        )


def test_register_rolls_back_entirely_on_password_policy_rejection(
    db_connection: Connection,
) -> None:
    """P-5: a rejected registration leaves zero new security.users rows and
    the onboarding session still consumable by a subsequent, valid attempt."""
    fixture = _Fixture(db_connection, "onb-register-weak-password")
    raw_token = fixture.invite(db_connection)
    begun = begin_invitation_onboarding(db_connection, invitation_token=raw_token)

    users_before = db_connection.execute(text("SELECT count(*) FROM security.users")).scalar_one()

    savepoint = db_connection.begin_nested()
    with pytest.raises(PasswordPolicyError):
        _InvitedRegistration(db_connection, fixture).register(
            onboarding_token=begun.raw_onboarding_token, password="too-short"
        )
    savepoint.rollback()

    users_after = db_connection.execute(text("SELECT count(*) FROM security.users")).scalar_one()
    assert users_after == users_before

    # The onboarding session is unaffected by the rolled-back attempt --
    # a fresh, valid registration against the same session still succeeds.
    result = _InvitedRegistration(db_connection, fixture).register(
        onboarding_token=begun.raw_onboarding_token
    )
    assert result.campaign_id == fixture.campaign_id


def test_register_rejects_reserved_login_names(db_connection: Connection) -> None:
    """D-11: the reserved-login-name denylist applies to invited
    registration, not only administrator-created accounts."""
    fixture = _Fixture(db_connection, "onb-register-reserved")
    raw_token = fixture.invite(db_connection)
    begun = begin_invitation_onboarding(db_connection, invitation_token=raw_token)

    savepoint = db_connection.begin_nested()
    with pytest.raises(LoginNameFormatError):
        _InvitedRegistration(db_connection, fixture).register(
            onboarding_token=begun.raw_onboarding_token, login_name="admin"
        )
    savepoint.rollback()


def test_reactivation_through_onboarding_restores_no_prior_access(
    db_connection: Connection,
) -> None:
    """P-3, re-proved through the onboarding path: a departed member who
    re-joins via a fresh invitation regains an open membership but none of
    the role assignments their prior membership held."""
    fixture = _Fixture(db_connection, "onb-reactivation")

    returning_user_id = make_user(db_connection, "Returning Player")
    old_membership_id = make_campaign_membership(
        db_connection, fixture.campaign_id, returning_user_id
    )
    # now() is frozen for the whole test transaction (see make_campaign_membership's
    # own comment) -- backdate joined_at so end_campaign_membership's ended_at = now()
    # satisfies ck_campaign_memberships_ended_after_joined's strict ">".
    db_connection.execute(
        text(
            "UPDATE security.campaign_memberships SET joined_at = now() - interval '1 minute' "
            "WHERE campaign_membership_id = :m"
        ),
        {"m": old_membership_id},
    )
    player_role_id = make_role(
        db_connection, campaign_id=fixture.campaign_id, code=f"player_{uuid.uuid4().hex[:8]}"
    )
    make_membership_role(db_connection, old_membership_id, player_role_id)

    from dnd_ai.commands.memberships import end_campaign_membership

    end_campaign_membership(
        db_connection,
        campaign_membership_id=old_membership_id,
        campaign_id=fixture.campaign_id,
        ended_by_membership_id=fixture.manager_membership_id,
    )

    raw_token = fixture.invite(db_connection)
    begun = begin_invitation_onboarding(db_connection, invitation_token=raw_token)
    result = complete_invitation_onboarding(
        db_connection, onboarding_token=begun.raw_onboarding_token, user_id=returning_user_id
    )
    assert result.campaign_membership_id == old_membership_id

    active_roles = db_connection.execute(
        text(
            "SELECT count(*) FROM security.membership_roles "
            "WHERE campaign_membership_id = :m AND revoked_at IS NULL"
        ),
        {"m": old_membership_id},
    ).scalar_one()
    assert active_roles == 0

    membership_row = db_connection.execute(
        text(
            "SELECT ended_at FROM security.campaign_memberships WHERE campaign_membership_id = :m"
        ),
        {"m": old_membership_id},
    ).one()
    assert membership_row.ended_at is None


def test_display_name_length_is_bounded_at_the_database(db_connection: Connection) -> None:
    """D-11: ck_users_display_name_length rejects an out-of-bounds value at
    the database, independent of any future API-layer Field bound."""
    active_status_id = lookup_id(
        db_connection, "core", "lifecycle_statuses", "lifecycle_status_id", "active"
    )
    with pytest.raises(IntegrityError):
        db_connection.execute(
            text(
                "INSERT INTO security.users (display_name, lifecycle_status_id) "
                "VALUES (:name, :status)"
            ),
            {"name": "x" * 101, "status": active_status_id},
        )

# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""R01 S5-D: the two invitation routes as keyed pre-write plans, over real HTTP on the migrated app.

`POST .../invitations` and `POST .../invitations/{id}/revoke` write no table the authority reader reads, but
they are the first *pre-write* routes: the reservation's campaign foreign key is deferred, every lock is
taken before `plan.finalize`, and the invitation, audit row and receipt are declared steps after it
(`dnd_ai.commands.campaign_invitation_plans`). Both routes accept an optional `Idempotency-Key`, so each has
a keyed and an unkeyed execution, and a keyed one is either a fresh reservation or a replay.

Evidence classes (labelled in each docstring):

- **route**: a real HTTP request through the guard on a one-connection pool.
- **sql**: the recorded statement stream of such a request (`Recorder`).
- **race**: a route request on one side and an application *command* (`end_campaign_membership`,
  `accept_campaign_invitation`) on the other, each parked on a named statement; every wait is observed
  through `pg_blocking_pids`, never assumed.
- **legacy**: the pre-S5-D order reproduced from the unchanged direct commands, to show what the redesign
  removes.
"""

import json
import re
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from dnd_ai.api.idempotency import begin_idempotent_request
from dnd_ai.commands.campaign_invitations import (
    InvitationNotAcceptableError,
    _hash_invitation_token,
    accept_campaign_invitation,
    revoke_campaign_invitation,
)
from dnd_ai.commands.invitation_onboarding import (
    begin_invitation_onboarding,
    complete_invitation_onboarding,
)
from dnd_ai.commands.memberships import end_campaign_membership
from dnd_ai.domain.authorization import AuthorizationPlan, StepOutcome
from tests.database.test_r01_s2_profile_routes import (  # noqa: F401 - fixtures used by name
    FINAL,
    FINAL_RE,
    Recorder,
    idle_in_transaction,
    pooled,
    pooled_factory,
)
from tests.database.test_r01_s3_authoring_routes import (  # noqa: F401 - fixtures used by name
    World,
    code,
    error_of,
    w,
)
from tests.factories import (
    make_campaign_invitation,
    make_campaign_membership,
    make_user,
)
from tests.http_race_support import (
    StatementGate,
    deadlock_count,
    new_key,
    run_in_thread,
    wait_for_deadlock_count,
)
from tests.lock_race_support import LockRace
from tests.r01_s5d_support import (
    Managers,
    make_managers,
    revoke_role,
    run_with_role_lapsing_before_final,
)

pytestmark = pytest.mark.database

Factory = Callable[[uuid.UUID], TestClient]

KEY_LOCK = r"pg_advisory_xact_lock"
MEMBERSHIP_KS = r"FROM security\.campaign_memberships WHERE .* FOR KEY SHARE$"
CAMPAIGN_KS = r"FROM campaign\.campaigns WHERE campaign\.campaigns\.campaign_id = \S+ FOR KEY SHARE"
INVITATION_U = (
    r"FROM security\.campaign_invitations WHERE security\.campaign_invitations\.campaign_invitation_id"
    r" = \S+ AND .* FOR UPDATE$"
)
RECEIPT_U = r"FROM security\.idempotent_requests WHERE .*idempotent_request_id = %\(receipt\)s::UUID FOR UPDATE"
INSERT_INVITATION = r"^INSERT INTO security\.campaign_invitations"
UPDATE_INVITATION_ACCEPT = r"^UPDATE security\.campaign_invitations SET accepted_by_user_id"
END_CAMPAIGN_U = r"^SELECT 1 FROM campaign\.campaigns WHERE campaign_id = \S+ FOR UPDATE"
FIRST_LOCK = {"create": MEMBERSHIP_KS, "revoke": INVITATION_U}


@pytest.fixture
def m(w: World) -> Managers:
    return make_managers(w.engine, w.campaign_id, label="S5D Invitation")


@pytest.fixture(autouse=True)
def _tidy(w: World) -> Iterator[None]:
    yield
    with w.engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        cleanup.execute(
            text("DELETE FROM security.campaign_invitations WHERE campaign_id = :c"),
            {"c": w.campaign_id},
        )
        cleanup.execute(
            text(
                "DELETE FROM audit.change_log WHERE world_id = :w AND table_name = 'campaign_invitations'"
            ),
            {"w": w.world_id},
        )


# --- helpers ------------------------------------------------------------------------------------------------------


def create(
    factory: Factory,
    w: World,
    user: uuid.UUID,
    *,
    key: str | None,
    email: str | None = "guest@example.test",
) -> Any:
    headers = {"Idempotency-Key": key} if key else {}
    with factory(user) as client:
        return client.post(f"{w.base}/invitations", json={"invited_email": email}, headers=headers)


def revoke(
    factory: Factory, w: World, user: uuid.UUID, invitation: uuid.UUID, *, key: str | None
) -> Any:
    headers = {"Idempotency-Key": key} if key else {}
    with factory(user) as client:
        return client.post(f"{w.base}/invitations/{invitation}/revoke", headers=headers)


def invite(w: World, by: uuid.UUID, *, token: str | None = None) -> tuple[uuid.UUID, str]:
    """A committed invitation of the campaign and its raw token."""
    token = token or f"s5d-{uuid.uuid4().hex}"
    with w.engine.begin() as setup:
        invitation = make_campaign_invitation(
            setup, w.campaign_id, by, token_hash=_hash_invitation_token(token)
        )
    return invitation, token


def invitation_row(w: World, invitation: uuid.UUID) -> tuple[Any, ...]:
    with w.engine.connect() as c:
        row = c.execute(
            text(
                "SELECT revoked_at IS NOT NULL, accepted_by_user_id, accepted_at IS NOT NULL "
                "FROM security.campaign_invitations WHERE campaign_invitation_id = :i"
            ),
            {"i": invitation},
        ).one_or_none()
    return tuple(row) if row is not None else ()


def counts(w: World, key: str | None = None) -> dict[str, int]:
    """Everything either route can persist, for the campaign: invitations, audit rows, receipts."""
    with w.engine.connect() as c:
        return {
            "invitations": c.execute(
                text("SELECT count(*) FROM security.campaign_invitations WHERE campaign_id = :c"),
                {"c": w.campaign_id},
            ).scalar_one(),
            "revoked": c.execute(
                text(
                    "SELECT count(*) FROM security.campaign_invitations "
                    "WHERE campaign_id = :c AND revoked_at IS NOT NULL"
                ),
                {"c": w.campaign_id},
            ).scalar_one(),
            "audit": c.execute(
                text(
                    "SELECT count(*) FROM audit.change_log WHERE world_id = :w "
                    "AND table_name = 'campaign_invitations'"
                ),
                {"w": w.world_id},
            ).scalar_one(),
            "receipts": c.execute(
                text(
                    "SELECT count(*) FROM security.idempotent_requests "
                    "WHERE campaign_id = :c AND idempotency_key = :k"
                ),
                {"c": w.campaign_id, "k": key or ""},
            ).scalar_one(),
        }


def receipt(w: World, key: str) -> tuple[Any, ...]:
    """(status, body, completed?) of the campaign's receipt for `key`, or `()` when there is none."""
    with w.engine.connect() as c:
        row = c.execute(
            text(
                "SELECT response_status_code, response_body, completed_at IS NOT NULL "
                "FROM security.idempotent_requests WHERE campaign_id = :c AND idempotency_key = :k"
            ),
            {"c": w.campaign_id, "k": key},
        ).one_or_none()
    return tuple(row) if row is not None else ()


def waiting_statement(engine: Engine, holder_pid: int) -> str:
    """The statement of a session waiting on a lock `holder_pid` holds, once there is one."""
    import time

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        with engine.connect() as connection:
            rows = (
                connection.execute(
                    text(
                        r"SELECT regexp_replace(query, '\s+', ' ', 'g') FROM pg_stat_activity "
                        "WHERE datname = current_database() AND wait_event_type = 'Lock' "
                        "AND :p = ANY(pg_blocking_pids(pid))"
                    ),
                    {"p": holder_pid},
                )
                .scalars()
                .all()
            )
        if rows:
            return str(rows[0])
        time.sleep(0.02)
    raise AssertionError(f"nothing waits on pid {holder_pid}")


# --- success, no-op and refusal outcomes --------------------------------------------------------------------------


@pytest.mark.parametrize("keyed", (True, False), ids=("keyed", "unkeyed"))
def test_a_manager_creates_an_invitation_with_its_audit_row_and_receipt(
    keyed: bool, w: World, m: Managers, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: 201 with the one-time token; one invitation, one audit row; a receipt only for a keyed
    request, whose stored body carries the invitation id and **never the token**."""
    key = new_key() if keyed else None
    before = counts(w, key)
    response = create(pooled_factory, w, m.manager_user, key=key)
    assert code(response) == 201, response.text
    body = response.json()
    token = body["token"]
    assert token and uuid.UUID(body["campaign_invitation_id"])
    after = counts(w, key)
    assert after["invitations"] == before["invitations"] + 1
    assert after["audit"] == before["audit"] + 1
    assert after["receipts"] == (1 if keyed else 0)
    with w.engine.connect() as c:
        row = c.execute(
            text(
                "SELECT invitation_token_hash, invited_by_membership_id, invited_email, "
                "expires_at > now() + interval '6 days' FROM security.campaign_invitations "
                "WHERE campaign_invitation_id = :i"
            ),
            {"i": body["campaign_invitation_id"]},
        ).one()
    assert row[0] == _hash_invitation_token(token) and row[0] != token
    assert row[1:] == (m.manager_membership, "guest@example.test", True)
    if keyed:
        stored = receipt(w, key or "")
        assert stored == (201, {"campaign_invitation_id": body["campaign_invitation_id"]}, True)
        assert token not in json.dumps(stored[1])
    assert idle_in_transaction(w.engine) == 0


@pytest.mark.parametrize("keyed", (True, False), ids=("keyed", "unkeyed"))
def test_a_manager_revokes_an_outstanding_invitation_once_and_a_second_revoke_is_a_no_op(
    keyed: bool, w: World, m: Managers, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: the first request sets `revoked_at` and writes one audit row; revoking an already revoked
    invitation is a documented success that writes **no** audit row and no business change, and a keyed
    no-op still completes its receipt (a receipt is required on every fresh keyed request)."""
    invitation, _ = invite(w, m.manager_membership)
    key = new_key() if keyed else None
    first = revoke(pooled_factory, w, m.manager_user, invitation, key=key)
    assert code(first) == 200 and first.json() == {"campaign_invitation_id": str(invitation)}
    assert invitation_row(w, invitation)[0] is True
    c1 = counts(w, key)
    assert c1["audit"] == 1 and c1["receipts"] == (1 if keyed else 0)
    key2 = new_key() if keyed else None
    second = revoke(pooled_factory, w, m.manager_user, invitation, key=key2)
    assert code(second) == 200 and second.json() == first.json()
    c2 = counts(w, key2)
    assert c2["audit"] == 1, "a no-op writes no audit row"
    assert c2["revoked"] == 1
    assert c2["receipts"] == (1 if keyed else 0), "a fresh keyed no-op completes its receipt"
    if keyed:
        assert receipt(w, key2 or "") == (200, first.json(), True)


@pytest.mark.parametrize("keyed", (True, False), ids=("keyed", "unkeyed"))
def test_refused_revocations_keep_their_errors_and_write_nothing(
    keyed: bool, w: World, m: Managers, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: an accepted invitation (409), an expired one (409), an absent one and one of another campaign
    (the same 404) are refused with the errors they always had; nothing persists, no key is consumed, the
    pooled connection is clean."""
    accepted, _ = invite(w, m.manager_membership)
    expired, _ = invite(w, m.manager_membership)
    with w.engine.begin() as c:
        accepted_by = make_user(c, "S5D Acceptor")
        c.execute(
            text(
                "UPDATE security.campaign_invitations SET accepted_by_user_id = :u, accepted_at = now() "
                "WHERE campaign_invitation_id = :i"
            ),
            {"u": accepted_by, "i": accepted},
        )
        c.execute(
            text(
                "UPDATE security.campaign_invitations SET expires_at = now() - interval '1 day', "
                "created_at = now() - interval '2 days' WHERE campaign_invitation_id = :i"
            ),
            {"i": expired},
        )
    keys = {name: (new_key() if keyed else None) for name in ("accepted", "expired", "absent")}
    before = counts(w)
    codes = {
        "accepted": revoke(pooled_factory, w, m.manager_user, accepted, key=keys["accepted"]),
        "expired": revoke(pooled_factory, w, m.manager_user, expired, key=keys["expired"]),
        "absent": revoke(pooled_factory, w, m.manager_user, uuid.uuid4(), key=keys["absent"]),
    }
    assert code(codes["accepted"]) == 409 and code(codes["expired"]) == 409
    assert code(codes["absent"]) == 404
    assert counts(w) == before
    for name, key in keys.items():
        assert counts(w, key)["receipts"] == 0, name
    assert invitation_row(w, accepted)[2] is True and invitation_row(w, expired)[0] is False
    assert idle_in_transaction(w.engine) == 0
    # a refused request's key is reusable: the same key now revokes a real invitation
    if keyed:
        fresh, _ = invite(w, m.manager_membership)
        again = revoke(pooled_factory, w, m.manager_user, fresh, key=keys["absent"])
        assert code(again) == 200 and invitation_row(w, fresh)[0] is True


# --- replay, fingerprint conflict and key reuse --------------------------------------------------------------------


def test_an_authorized_create_replay_returns_the_receipt_without_the_token_and_writes_nothing(
    w: World, m: Managers, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route* and *sql*: the replay returns the stored, sanitized body (the id, never the token); it takes
    no lock of the command's declaration, writes no invitation, audit row or receipt, and its last statement
    before COMMIT is the one final authority statement (the receipt does not leave before the check)."""
    key = new_key()
    first = create(pooled_factory, w, m.manager_user, key=key)
    assert code(first) == 201
    stored = counts(w, key)
    with Recorder(pooled) as recorded:
        replay = create(pooled_factory, w, m.manager_user, key=key)
    assert code(replay) == 201
    assert replay.json() == {
        "campaign_invitation_id": first.json()["campaign_invitation_id"],
        "token": None,
    }
    assert counts(w, key) == stored
    finals = [s for s in recorded.events if FINAL_RE.search(s)]
    assert len(finals) == 1 and recorded.events[-2:] == [finals[0], "COMMIT"]
    assert not [
        s for s in recorded.events if re.search(r"FOR (KEY SHARE|SHARE|UPDATE|NO KEY UPDATE)", s)
    ], "a replay takes no row lock of the command"
    writes = [s for s in recorded.events if s.startswith(("INSERT", "UPDATE", "DELETE"))]
    assert all("idempotent_requests" in s and "ON CONFLICT" in s for s in writes), writes


def test_an_authorized_revoke_replay_returns_the_stored_receipt_and_changes_nothing(
    w: World, m: Managers, pooled: Engine, pooled_factory: Factory
) -> None:
    invitation, _ = invite(w, m.manager_membership)
    key = new_key()
    first = revoke(pooled_factory, w, m.manager_user, invitation, key=key)
    assert code(first) == 200
    stored = counts(w, key)
    replay = revoke(pooled_factory, w, m.manager_user, invitation, key=key)
    assert code(replay) == 200 and replay.json() == first.json()
    assert counts(w, key) == stored


@pytest.mark.parametrize("route", ("create", "revoke"))
def test_a_replay_after_authority_loss_is_refused_and_returns_nothing_from_the_receipt(
    route: str, w: World, m: Managers, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: R-D4. The receipt is judged by the route's requirements before it leaves: a manager whose
    role is gone gets the early refusal, and the body of the stored receipt is not in the response."""
    invitation, _ = invite(w, m.manager_membership)
    key = new_key()
    if route == "create":
        first = create(pooled_factory, w, m.manager_user, key=key)
    else:
        first = revoke(pooled_factory, w, m.manager_user, invitation, key=key)
    assert code(first) in (200, 201)
    stored = counts(w, key)
    revoke_role(w.engine, m.manager_role)
    again = (
        create(pooled_factory, w, m.manager_user, key=key)
        if route == "create"
        else revoke(pooled_factory, w, m.manager_user, invitation, key=key)
    )
    assert code(again) in (403, 404), again.text
    assert str(invitation) not in again.text and "campaign_invitation_id" not in again.text
    assert counts(w, key) == stored
    assert idle_in_transaction(w.engine) == 0


def test_a_replay_whose_authority_lapses_during_its_key_lock_wait_is_refused_at_the_final_statement(
    w: World, m: Managers, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route* (race): the replay is parked at its key lock, the role then lapses (a DATABASE condition), and
    the replay is refused by the final statement: `bind_reservation(REPLAY)` leaves the route's requirements
    in force, so the stored receipt is not returned to a lapsed caller."""
    key = new_key()
    first = create(pooled_factory, w, m.manager_user, key=key)
    assert code(first) == 201
    stored = counts(w, key)
    response = run_with_role_lapsing_before_final(
        w.engine,
        pooled,
        m.manager_role,
        lambda: create(pooled_factory, w, m.manager_user, key=key),
        first_gate=KEY_LOCK,
    )
    assert code(response) in (403, 404), response.text
    assert "campaign_invitation_id" not in response.text
    assert counts(w, key) == stored


def test_a_reused_key_with_another_payload_or_another_route_is_the_same_conflict(
    w: World, m: Managers, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: a fingerprint mismatch (another body, or another command or invitation under the same key)
    is the fixed 409 before any lock of the command's declaration; it persists nothing new."""
    key = new_key()
    first = create(pooled_factory, w, m.manager_user, key=key, email="a@example.test")
    assert code(first) == 201
    stored = counts(w, key)
    other_body = create(pooled_factory, w, m.manager_user, key=key, email="b@example.test")
    assert code(other_body) == 409
    invitation, _ = invite(w, m.manager_membership)
    other_route = revoke(pooled_factory, w, m.manager_user, invitation, key=key)
    assert code(other_route) == 409
    after = counts(w, key)
    assert after["invitations"] == stored["invitations"] + 1  # only the one `invite` above
    assert after["audit"] == stored["audit"] and after["receipts"] == 1
    assert invitation_row(w, invitation)[0] is False
    assert idle_in_transaction(w.engine) == 0


# --- authority loss and expiry ------------------------------------------------------------------------------------


@pytest.mark.parametrize("keyed", (True, False), ids=("keyed", "unkeyed"))
@pytest.mark.parametrize("route", ("create", "revoke"))
def test_a_role_that_lapses_before_the_final_statement_refuses_the_route_and_rolls_everything_back(
    route: str, keyed: bool, w: World, m: Managers, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route* (race): the manager's role is valid for every early check and has lapsed (a DATABASE
    condition, polled) when the final authority statement runs. The route's locks are already held, so this
    is the pre-write refusal the plan promises: no invitation, no revocation, no audit row, no receipt, the
    pooled connection returns clean and the key is reusable."""
    invitation, _ = invite(w, m.manager_membership)
    key = new_key() if keyed else None

    def call() -> Any:
        if route == "create":
            return create(pooled_factory, w, m.manager_user, key=key)
        return revoke(pooled_factory, w, m.manager_user, invitation, key=key)

    before = counts(w, key)
    response = run_with_role_lapsing_before_final(
        w.engine,
        pooled,
        m.manager_role,
        call,
        first_gate=KEY_LOCK if keyed else FIRST_LOCK[route],
    )
    assert code(response) in (403, 404), (route, keyed, response.text)
    assert counts(w, key) == before
    assert invitation_row(w, invitation)[0] is False
    assert idle_in_transaction(w.engine) == 0
    # the next request on the same pool commits only its own work, and the key is reusable
    with w.engine.begin() as c:
        c.execute(
            text(
                "UPDATE security.membership_roles SET expires_at = NULL WHERE membership_role_id = :r"
            ),
            {"r": m.manager_role},
        )
    again = call()
    assert code(again) in (200, 201), again.text
    assert idle_in_transaction(w.engine) == 0


@pytest.mark.parametrize("route", ("create", "revoke"))
def test_a_role_revoked_before_the_request_is_refused_early_and_writes_nothing(
    route: str, w: World, m: Managers, pooled: Engine, pooled_factory: Factory
) -> None:
    invitation, _ = invite(w, m.manager_membership)
    revoke_role(w.engine, m.manager_role)
    key = new_key()
    before = counts(w, key)
    response = (
        create(pooled_factory, w, m.manager_user, key=key)
        if route == "create"
        else revoke(pooled_factory, w, m.manager_user, invitation, key=key)
    )
    assert code(response) in (403, 404), response.text
    assert counts(w, key) == before
    assert idle_in_transaction(w.engine) == 0


# --- ordering and the lock sequence ---------------------------------------------------------------------------------


def _index(events: list[str], pattern: str) -> int:
    matches = [i for i, s in enumerate(events) if re.search(pattern, s)]
    assert matches, f"no statement matches {pattern!r}: {events}"
    return matches[0]


def test_the_keyed_create_runs_its_statements_in_the_documented_order(
    w: World, m: Managers, pooled: Engine, pooled_factory: Factory
) -> None:
    """*sql*: key lock, deferral, reservation, the inviting membership `FOR KEY SHARE`, the campaign `FOR KEY
    SHARE`, our reservation row `FOR UPDATE`, then the one final authority statement, and only after it the
    invitation insert, the audit insert and the receipt update, with COMMIT last and no row lock after the
    final statement."""
    with Recorder(pooled) as recorded:
        response = create(pooled_factory, w, m.manager_user, key=new_key())
    assert code(response) == 201
    e = recorded.events
    order = [
        _index(e, KEY_LOCK),
        _index(e, r"SET CONSTRAINTS security\.idempotent_requests_campaign_id_fkey DEFERRED"),
        _index(e, r"^INSERT INTO security\.idempotent_requests"),
        _index(e, MEMBERSHIP_KS),
        _index(e, CAMPAIGN_KS),
        _index(e, RECEIPT_U),
        _index(e, FINAL),
        _index(e, INSERT_INVITATION),
        _index(e, r"^INSERT INTO audit\.change_log"),
        _index(e, r"^UPDATE security\.idempotent_requests"),
    ]
    # the deferral is issued before the key lock only in the sense of "no lock": it is a plain SET, and the
    # key lock is the first *lock* of the request
    first_lock = min(
        i for i, s in enumerate(e) if re.search(r"FOR (KEY SHARE|SHARE|UPDATE)|pg_advisory", s)
    )
    assert first_lock == order[0], e[: order[0] + 1]
    assert order[1:] == sorted(order[1:]) and order[0] < order[2]
    assert e[-1] == "COMMIT"
    assert not [
        s for s in e[order[6] :] if re.search(r"\bFOR (KEY SHARE|SHARE|UPDATE|NO KEY UPDATE)\b", s)
    ]


def test_the_keyed_revoke_takes_the_invitation_before_the_campaign_and_both_before_the_final_statement(
    w: World, m: Managers, pooled: Engine, pooled_factory: Factory
) -> None:
    """*sql*: the one exception to the global order. The invitation row `FOR UPDATE` is the first row lock,
    the campaign `FOR KEY SHARE` the second; the reservation's own campaign check is deferred, so nothing
    takes the campaign earlier."""
    invitation, _ = invite(w, m.manager_membership)
    with Recorder(pooled) as recorded:
        response = revoke(pooled_factory, w, m.manager_user, invitation, key=new_key())
    assert code(response) == 200
    e = recorded.events
    reservation = _index(e, r"^INSERT INTO security\.idempotent_requests")
    invitation_lock = _index(e, INVITATION_U)
    campaign_lock = _index(e, CAMPAIGN_KS)
    final = _index(e, FINAL)
    update = _index(e, r"^UPDATE security\.campaign_invitations SET revoked_at")
    assert reservation < invitation_lock < campaign_lock < final < update
    assert not [s for s in e[:invitation_lock] if re.search(r"FROM campaign\.campaigns .* FOR", s)]
    assert e[-1] == "COMMIT"


def test_an_unkeyed_create_takes_the_same_locks_without_a_key_lock_or_receipt(
    w: World, m: Managers, pooled: Engine, pooled_factory: Factory
) -> None:
    with Recorder(pooled) as recorded:
        response = create(pooled_factory, w, m.manager_user, key=None)
    assert code(response) == 201
    e = recorded.events
    assert not [s for s in e if re.search(r"pg_advisory|idempotent_requests|SET CONSTRAINTS", s)]
    assert (
        _index(e, MEMBERSHIP_KS)
        < _index(e, CAMPAIGN_KS)
        < _index(e, FINAL)
        < _index(e, INSERT_INVITATION)
    )
    assert e[-1] == "COMMIT"


@pytest.mark.parametrize("route", ("create", "revoke"))
@pytest.mark.parametrize("keyed", (True, False), ids=("keyed", "unkeyed"))
def test_a_handler_that_forgets_to_finalize_is_a_sanitized_500_that_persists_nothing(
    route: str,
    keyed: bool,
    w: World,
    m: Managers,
    pooled: Engine,
    pooled_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """*route*: with `finalize` a no-op the plan never finalizes: the declared writes are refused (a pre-write
    plan accepts none before `finalize`), nothing persists, and the response is the sanitized 500."""
    invitation, _ = invite(w, m.manager_membership)
    key = new_key() if keyed else None
    before = counts(w, key)
    monkeypatch.setattr(AuthorizationPlan, "finalize", lambda self, connection: None)
    response = (
        create(pooled_factory, w, m.manager_user, key=key)
        if route == "create"
        else revoke(pooled_factory, w, m.manager_user, invitation, key=key)
    )
    monkeypatch.undo()
    assert code(response) == 500 and error_of(response) == "internal_error"
    assert counts(w, key) == before and invitation_row(w, invitation)[0] is False
    assert idle_in_transaction(w.engine) == 0


@pytest.mark.parametrize("route", ("create", "revoke", "revoke_no_op"))
def test_a_keyed_request_whose_receipt_step_is_skipped_is_refused_at_commit_and_persists_nothing(
    route: str,
    w: World,
    m: Managers,
    pooled: Engine,
    pooled_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """*route*: the receipt is `Exactly(1)` in the reserved declaration, so a fresh keyed request that never
    completes it (a business write, an audit row, or on the no-op path nothing else at all) cannot commit:
    the COMMIT guard refuses an incomplete plan, the whole transaction rolls back and the key is reusable."""
    invitation, _ = invite(w, m.manager_membership)
    if route == "revoke_no_op":
        with w.engine.begin() as c:
            c.execute(
                text(
                    "UPDATE security.campaign_invitations SET revoked_at = now() WHERE campaign_invitation_id = :i"
                ),
                {"i": invitation},
            )
    key = new_key()
    before = counts(w, key)
    original = AuthorizationPlan.execute

    def skip_receipt(
        self: AuthorizationPlan, connection: Any, step: Any, params: Any
    ) -> StepOutcome:
        if step.name == "receipt":
            return StepOutcome(step="receipt", keys=())
        return original(self, connection, step, params)

    monkeypatch.setattr(AuthorizationPlan, "execute", skip_receipt)
    response = (
        create(pooled_factory, w, m.manager_user, key=key)
        if route == "create"
        else revoke(pooled_factory, w, m.manager_user, invitation, key=key)
    )
    monkeypatch.undo()
    assert code(response) == 500, response.text
    assert counts(w, key) == before
    assert idle_in_transaction(w.engine) == 0
    ok = (
        create(pooled_factory, w, m.manager_user, key=key)
        if route == "create"
        else revoke(pooled_factory, w, m.manager_user, invitation, key=key)
    )
    assert code(ok) in (200, 201), ok.text


def test_a_create_whose_invitation_insert_is_skipped_is_refused_at_commit_and_persists_nothing(
    w: World,
    m: Managers,
    pooled: Engine,
    pooled_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The business step is `Exactly(1)` on create, so an omitted insert cannot commit either (on revoke the
    business step and its audit row are `Between(0, 1)` because the no-op attempts neither: omitting them on
    a real revocation is **not** detected by the plan; that limit is recorded in the plan section 6.25)."""
    original = AuthorizationPlan.execute

    def skip(self: AuthorizationPlan, connection: Any, step: Any, params: Any) -> StepOutcome:
        if step.name == "audit_created":
            return StepOutcome(step="audit_created", keys=())
        return original(self, connection, step, params)

    key = new_key()
    before = counts(w, key)
    monkeypatch.setattr(AuthorizationPlan, "execute", skip)
    response = create(pooled_factory, w, m.manager_user, key=key)
    monkeypatch.undo()
    assert code(response) == 500
    assert counts(w, key) == before


# --- the inviting manager's end against a create (the cycle the early reservation lock used to make) ---------------


def _end_manager(w: World, m: Managers) -> Callable[[Any], Any]:
    return lambda c: end_campaign_membership(
        c,
        campaign_membership_id=m.manager_membership,
        campaign_id=w.campaign_id,
        ended_by_membership_id=m.keeper_membership,
    )


def _membership_ended(w: World, membership: uuid.UUID) -> bool:
    with w.engine.connect() as c:
        return bool(
            c.execute(
                text(
                    "SELECT ended_at IS NOT NULL FROM security.campaign_memberships "
                    "WHERE campaign_membership_id = :m"
                ),
                {"m": membership},
            ).scalar_one()
        )


def test_an_end_of_the_inviting_manager_that_holds_the_membership_first_refuses_the_create(
    w: World, m: Managers, pooled: Engine, pooled_factory: Factory
) -> None:
    """*race* (**legacy-command evidence**: the end is `end_campaign_membership`, not the migrated route; the route is
    raced in `test_r01_s5f_invitation_end_race.py`), committed before authorization: the end holds the manager's membership `FOR UPDATE` and is
    parked before its campaign lock. The keyed create queues at its membership lock holding only the actor's
    account `FOR KEY SHARE` (nothing the end wants), then, once the end commits, its lock finds no open
    membership and `finalize` refuses it. Nothing persists, the key is reusable, and no deadlock occurs."""
    key = new_key()
    deadlocks = deadlock_count(w.engine)
    before = counts(w, key)
    with LockRace(w.engine) as race:
        pause = race.pause(thread_name="end", pattern=END_CAMPAIGN_U)
        end = race.start("end", _end_manager(w, m))
        pause.wait_reached(end)
        request = run_in_thread(
            "create", lambda: create(pooled_factory, w, m.manager_user, key=key)
        )
        race.wait_blocked_by(pause, expected=1)
        assert re.search(MEMBERSHIP_KS, waiting_statement(w.engine, pause.pid))
        assert not request.finished()
        pause.release()
        race.wait_done(end, why="the end finishes once released")
        response = request.wait("the create finishes after the end commits")
        race.join_all()
    assert end.error is None and _membership_ended(w, m.manager_membership)
    assert code(response) in (403, 404), response.text
    assert counts(w, key) == before
    assert wait_for_deadlock_count(w.engine, deadlocks) == deadlocks
    assert idle_in_transaction(w.engine) == 0


def test_a_create_that_holds_the_membership_first_makes_the_end_wait_and_both_commit(
    w: World, m: Managers, pooled: Engine, pooled_factory: Factory
) -> None:
    """*race* (**legacy-command evidence**: the end is `end_campaign_membership`, not the migrated route; the route is
    raced in `test_r01_s5f_invitation_end_race.py`), serialized revocation of authority: the create is parked at its final statement holding the
    membership and the campaign `FOR KEY SHARE`. The end queues at the membership (`FOR UPDATE`), holding
    only role rows nobody else wants; the create commits (its invitation exists), then the end commits."""
    key = new_key()
    deadlocks = deadlock_count(w.engine)
    with StatementGate(pooled, FINAL) as gate:
        request = run_in_thread(
            "create", lambda: create(pooled_factory, w, m.manager_user, key=key)
        )
        gate.wait_reached()
        assert gate.pid is not None
        with LockRace(w.engine) as race:
            end = race.start("end", _end_manager(w, m))
            race.wait_blocked_by(gate, expected=1)
            assert "campaign_memberships" in waiting_statement(w.engine, gate.pid)
            assert not end.done
            gate.release()
            response = request.wait("the create finishes")
            race.join_all()
    assert code(response) == 201, response.text
    assert end.error is None and _membership_ended(w, m.manager_membership)
    assert counts(w, key)["invitations"] == 1 and counts(w, key)["audit"] == 1
    assert wait_for_deadlock_count(w.engine, deadlocks) == deadlocks


def test_legacy_the_immediate_reservation_lock_deadlocked_with_the_end_of_the_inviting_manager(
    w: World, m: Managers
) -> None:
    """*legacy*: the pre-S5-D order, from the unchanged direct commands. The reservation's immediate campaign
    FK holds the campaign `FOR KEY SHARE`; the invitation insert then wants the membership `FOR KEY SHARE`;
    the end holds the membership `FOR UPDATE` and wants the campaign `FOR UPDATE`. Exactly one is the
    deadlock victim. This is what deferring the FK and taking the membership first removes."""
    from dnd_ai.commands.campaign_invitations import create_campaign_invitation

    key = new_key()
    deadlocks = deadlock_count(w.engine)

    def legacy(c: Any) -> Any:
        begin_idempotent_request(
            c,
            actor_user_id=m.manager_user,
            campaign_id=w.campaign_id,
            idempotency_key=key,
            command_name="create_campaign_invitation",
            payload={"campaign_id": str(w.campaign_id)},
            correlation_id=None,
        )
        return create_campaign_invitation(
            c, campaign_id=w.campaign_id, invited_by_membership_id=m.manager_membership
        )

    with LockRace(w.engine) as race:
        pause = race.pause(
            thread_name="legacy", pattern=r"^INSERT INTO security\.campaign_invitations"
        )
        creating = race.start("legacy", legacy)
        pause.wait_reached(creating)
        end = race.start("end", _end_manager(w, m))
        race.wait_blocked_by(pause, expected=1)
        pause.release()
        race.join_all()
    errors = [worker.error for worker in (creating, end) if worker.error is not None]
    assert len(errors) == 1, (creating.describe(), end.describe())
    assert getattr(getattr(errors[0], "orig", errors[0]), "sqlstate", None) == "40P01", errors
    assert wait_for_deadlock_count(w.engine, deadlocks + 1) == deadlocks + 1


# --- revocation against acceptance and onboarding -------------------------------------------------------------------


@dataclass
class Reopener:
    user: uuid.UUID
    membership: uuid.UUID
    invitation: uuid.UUID
    token: str


@pytest.fixture
def reopener(w: World, m: Managers) -> Reopener:
    """A user whose earlier membership has ended, with an outstanding invitation: acceptance reopens that
    membership in place, which queues the retention trigger's campaign `FOR UPDATE` at COMMIT."""
    with w.engine.begin() as c:
        user = make_user(c, "S5D Reopener")
        membership = make_campaign_membership(c, w.campaign_id, user, ended=True)
    invitation, token = invite(w, m.manager_membership)
    return Reopener(user, membership, invitation, token)


def _accept(r: Reopener) -> Callable[[Any], Any]:
    return lambda c: accept_campaign_invitation(c, token=r.token, accepting_user_id=r.user)


def _open_memberships(w: World, user: uuid.UUID) -> int:
    with w.engine.connect() as c:
        return int(
            c.execute(
                text(
                    "SELECT count(*) FROM security.campaign_memberships "
                    "WHERE campaign_id = :c AND user_id = :u AND ended_at IS NULL"
                ),
                {"c": w.campaign_id, "u": user},
            ).scalar_one()
        )


@pytest.mark.parametrize("keyed", (True, False), ids=("keyed", "unkeyed"))
def test_a_reopening_acceptance_that_holds_the_invitation_first_makes_the_revoke_wait_then_refuses_it(
    keyed: bool, w: World, m: Managers, reopener: Reopener, pooled: Engine, pooled_factory: Factory
) -> None:
    """*race*, serialized (acceptance first): the acceptance has reopened the membership and is parked before
    its last statement, holding the invitation `FOR UPDATE`, the membership and the campaign `FOR SHARE`,
    and owing the campaign `FOR UPDATE` at COMMIT. The revoke queues at the **invitation** holding no campaign
    lock (its reservation FK is deferred), so the acceptance's COMMIT upgrade finds nothing to wait for. The
    acceptance commits; the revoke then sees an accepted invitation and is refused (409)."""
    key = new_key() if keyed else None
    deadlocks = deadlock_count(w.engine)
    with LockRace(w.engine) as race:
        pause = race.pause(thread_name="accept", pattern=UPDATE_INVITATION_ACCEPT)
        accept = race.start("accept", _accept(reopener))
        pause.wait_reached(accept)
        request = run_in_thread(
            "revoke",
            lambda: revoke(pooled_factory, w, m.manager_user, reopener.invitation, key=key),
        )
        race.wait_blocked_by(pause, expected=1)
        assert re.search(INVITATION_U, waiting_statement(w.engine, pause.pid))
        assert not request.finished()
        pause.release()
        race.wait_done(accept, why="the acceptance commits without waiting for the revoke")
        response = request.wait("the revoke finishes after the acceptance commits")
        race.join_all()
    assert accept.error is None, accept.describe()
    assert code(response) == 409, response.text
    assert invitation_row(w, reopener.invitation) == (False, reopener.user, True)
    assert _open_memberships(w, reopener.user) == 1
    assert counts(w, key)["receipts"] == 0
    assert wait_for_deadlock_count(w.engine, deadlocks) == deadlocks
    assert idle_in_transaction(w.engine) == 0


@pytest.mark.parametrize("keyed", (True, False), ids=("keyed", "unkeyed"))
def test_a_revoke_that_holds_the_invitation_first_makes_the_acceptance_wait_then_refuses_it(
    keyed: bool, w: World, m: Managers, reopener: Reopener, pooled: Engine, pooled_factory: Factory
) -> None:
    """*race*, serialized revocation (revoke first): the revoke is parked at its final statement holding the
    invitation `FOR UPDATE` and the campaign `FOR KEY SHARE`. The acceptance queues at the invitation, its
    first statement, holding nothing; the revoke commits and the acceptance is refused with the one
    non-disclosing error. The ended membership is not reopened."""
    key = new_key() if keyed else None
    deadlocks = deadlock_count(w.engine)
    with StatementGate(pooled, FINAL) as gate:
        request = run_in_thread(
            "revoke",
            lambda: revoke(pooled_factory, w, m.manager_user, reopener.invitation, key=key),
        )
        gate.wait_reached()
        assert gate.pid is not None
        with LockRace(w.engine) as race:
            accept = race.start("accept", _accept(reopener))
            race.wait_blocked_by(gate, expected=1)
            assert "invitation_token_hash" in waiting_statement(w.engine, gate.pid)
            gate.release()
            response = request.wait("the revoke finishes")
            race.join_all()
    assert code(response) == 200, response.text
    assert isinstance(accept.error, InvitationNotAcceptableError), accept.describe()
    assert invitation_row(w, reopener.invitation) == (True, None, False)
    assert _open_memberships(w, reopener.user) == 0
    assert wait_for_deadlock_count(w.engine, deadlocks) == deadlocks


def test_a_revocation_committed_before_the_acceptance_starts_refuses_it_without_waiting(
    w: World, m: Managers, reopener: Reopener, pooled: Engine, pooled_factory: Factory
) -> None:
    """*race*, revocation committed before authorization: no blocking relationship at all."""
    assert (
        code(revoke(pooled_factory, w, m.manager_user, reopener.invitation, key=new_key())) == 200
    )
    with LockRace(w.engine) as race:
        accept = race.start("accept", _accept(reopener))
        race.wait_done(accept, why="a revoked invitation is refused at once")
        race.join_all()
    assert isinstance(accept.error, InvitationNotAcceptableError)
    assert _open_memberships(w, reopener.user) == 0


def test_an_onboarding_completion_that_holds_the_invitation_first_makes_the_revoke_wait_then_refuses_it(
    w: World, m: Managers, reopener: Reopener, pooled: Engine, pooled_factory: Factory
) -> None:
    """*race*: the onboarding confirm step reaches the same acceptance tail after locking its session row and
    the invitation. Same graph as above, through the other entry point."""
    with w.engine.begin() as c:
        onboarding = begin_invitation_onboarding(
            c, invitation_token=reopener.token
        ).raw_onboarding_token
    deadlocks = deadlock_count(w.engine)
    with LockRace(w.engine) as race:
        pause = race.pause(thread_name="complete", pattern=UPDATE_INVITATION_ACCEPT)
        completing = race.start(
            "complete",
            lambda c: complete_invitation_onboarding(
                c, onboarding_token=onboarding, user_id=reopener.user
            ),
        )
        pause.wait_reached(completing)
        request = run_in_thread(
            "revoke",
            lambda: revoke(pooled_factory, w, m.manager_user, reopener.invitation, key=new_key()),
        )
        race.wait_blocked_by(pause, expected=1)
        pause.release()
        race.wait_done(completing, why="the completion commits without waiting for the revoke")
        response = request.wait("the revoke finishes")
        race.join_all()
    assert completing.error is None, completing.describe()
    assert code(response) == 409
    assert _open_memberships(w, reopener.user) == 1
    assert wait_for_deadlock_count(w.engine, deadlocks) == deadlocks


def test_legacy_the_immediate_reservation_lock_deadlocked_with_a_reopening_acceptance(
    w: World, m: Managers, reopener: Reopener
) -> None:
    """*legacy*: the pre-S5-D order from the unchanged direct commands. A keyed revoke held the campaign
    `FOR KEY SHARE` (immediate reservation FK) while queued at the invitation; the acceptance's COMMIT
    upgrade to `FOR UPDATE` then waited for it: one deadlock victim. This is the cycle the correction design
    named, and what taking the invitation before any campaign lock removes."""
    key = new_key()
    deadlocks = deadlock_count(w.engine)

    def legacy(c: Any) -> Any:
        begin_idempotent_request(
            c,
            actor_user_id=m.manager_user,
            campaign_id=w.campaign_id,
            idempotency_key=key,
            command_name="revoke_campaign_invitation",
            payload={"campaign_id": str(w.campaign_id)},
            correlation_id=None,
        )
        return revoke_campaign_invitation(
            c, campaign_id=w.campaign_id, campaign_invitation_id=reopener.invitation
        )

    with LockRace(w.engine) as race:
        pause = race.pause(thread_name="accept", pattern=UPDATE_INVITATION_ACCEPT)
        accept = race.start("accept", _accept(reopener))
        pause.wait_reached(accept)
        revoking = race.start("legacy", legacy)
        race.wait_blocked_by(pause, expected=1)
        pause.release()
        race.join_all()
    errors = [worker.error for worker in (accept, revoking) if worker.error is not None]
    assert len(errors) == 1, (accept.describe(), revoking.describe())
    assert getattr(getattr(errors[0], "orig", errors[0]), "sqlstate", None) == "40P01", errors
    assert wait_for_deadlock_count(w.engine, deadlocks + 1) == deadlocks + 1


def test_a_create_does_not_deadlock_with_a_reopening_acceptance_of_another_invitation(
    w: World, m: Managers, reopener: Reopener, pooled: Engine, pooled_factory: Factory
) -> None:
    """*race*, the creator path: the create holds the campaign `FOR KEY SHARE` and the manager's membership at
    its final statement; a reopening acceptance of a different invitation then owes the campaign `FOR
    UPDATE` at COMMIT and waits for the create, which wants nothing the acceptance holds. Both commit."""
    deadlocks = deadlock_count(w.engine)
    with StatementGate(pooled, FINAL) as gate:
        request = run_in_thread(
            "create", lambda: create(pooled_factory, w, m.manager_user, key=new_key())
        )
        gate.wait_reached()
        assert gate.pid is not None
        with LockRace(w.engine) as race:
            accept = race.start("accept", _accept(reopener))
            race.wait_blocked_by(gate, expected=1)
            assert (
                waiting_statement(w.engine, gate.pid) == "COMMIT"
            )  # the retention trigger's upgrade
            gate.release()
            response = request.wait("the create finishes")
            race.join_all()
    assert code(response) == 201, response.text
    assert accept.error is None, accept.describe()
    assert _open_memberships(w, reopener.user) == 1
    assert wait_for_deadlock_count(w.engine, deadlocks) == deadlocks


# --- competitors against what the route holds, and the waits it still has after the final statement -----------------


@pytest.mark.parametrize("route", ("create", "revoke"))
def test_the_locks_the_route_holds_at_its_final_statement_exclude_every_conflicting_competitor(
    route: str, w: World, m: Managers, pooled: Engine, pooled_factory: Factory
) -> None:
    """*race*: at the final statement a keyed request holds the actor's account (`FOR KEY SHARE`), the
    campaign (`FOR KEY SHARE`) and, for create, the manager's membership; for revoke, the invitation
    (`FOR UPDATE`). A competitor taking any of them `FOR UPDATE` (account administration, an archive, an
    end, an acceptance) queues behind the request, so the post-finalization foreign-key re-checks and the
    deferred campaign check at COMMIT can never wait for it; the request still commits with those
    competitors queued."""
    invitation, _ = invite(w, m.manager_membership)
    targets = [
        ("account", "SELECT 1 FROM security.users WHERE user_id = :id FOR UPDATE", m.manager_user),
        (
            "campaign",
            "SELECT 1 FROM campaign.campaigns WHERE campaign_id = :id FOR UPDATE",
            w.campaign_id,
        ),
    ]
    if route == "create":
        targets.append(
            (
                "membership",
                "SELECT 1 FROM security.campaign_memberships WHERE campaign_membership_id = :id FOR UPDATE",
                m.manager_membership,
            )
        )
    else:
        targets.append(
            (
                "invitation",
                "SELECT 1 FROM security.campaign_invitations WHERE campaign_invitation_id = :id FOR UPDATE",
                invitation,
            )
        )
    with StatementGate(pooled, FINAL) as gate:
        request = run_in_thread(
            route,
            lambda: (
                create(pooled_factory, w, m.manager_user, key=new_key())
                if route == "create"
                else revoke(pooled_factory, w, m.manager_user, invitation, key=new_key())
            ),
        )
        gate.wait_reached()
        assert gate.pid is not None
        with LockRace(w.engine) as race:
            competitors = [
                race.start(
                    name, lambda c, sql=sql, ident=ident: c.execute(text(sql), {"id": ident}).all()
                )
                for name, sql, ident in targets
            ]
            race.wait_blocked_by(gate, expected=len(targets))
            assert all(not c.done for c in competitors)
            gate.release()
            response = request.wait("the request commits with its competitors queued")
            race.join_all()
    assert code(response) in (200, 201), response.text
    assert all(c.error is None for c in competitors)


def test_a_competing_equal_token_hash_is_a_unique_wait(
    w: World, m: Managers, pooled: Engine, pooled_factory: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """*race*: the declared `UniqueWait` of `ux_campaign_invitations_token_hash`. A transaction that has
    inserted (not committed) the same hash makes the plan's insert wait; if it rolls back the create
    commits; if it commits the create is a unique violation, rolled back whole (no audit row, no receipt),
    and the key is reusable. A random 256-bit token makes this unreachable in practice."""
    current = {"token": ""}

    def hold_equal_hash(c: Any) -> Any:
        return make_campaign_invitation(
            c,
            w.campaign_id,
            m.manager_membership,
            token_hash=_hash_invitation_token(current["token"]),
        )

    for outcome in ("rollback", "commit"):
        fixed = f"s5d-fixed-token-{outcome}"
        current["token"] = fixed
        monkeypatch.setattr(
            "dnd_ai.commands.campaign_invitation_plans.secrets.token_urlsafe", lambda _n, f=fixed: f
        )
        key = new_key()
        before = counts(w, key)
        with LockRace(w.engine) as race:
            hold = race.hold(hold_equal_hash)
            request = run_in_thread(
                "create", lambda key=key: create(pooled_factory, w, m.manager_user, key=key)
            )
            race.wait_blocked_by(hold, expected=1)
            assert re.search(INSERT_INVITATION, waiting_statement(w.engine, hold.pid))
            if outcome == "commit":
                hold.commit()
            else:
                hold.close()
            response = request.wait("the create finishes")
        if outcome == "rollback":
            assert code(response) == 201, response.text
            assert counts(w, key)["invitations"] == before["invitations"] + 1
        else:
            assert code(response) in (409, 500), response.text
            after = counts(w, key)
            assert after["invitations"] == before["invitations"] + 1  # only the competitor's row
            assert after["audit"] == before["audit"] and after["receipts"] == 0
            with w.engine.begin() as c:
                c.execute(
                    text(
                        "DELETE FROM security.campaign_invitations WHERE invitation_token_hash = :h"
                    ),
                    {"h": _hash_invitation_token(fixed)},
                )
            monkeypatch.setattr(
                "dnd_ai.commands.campaign_invitation_plans.secrets.token_urlsafe",
                lambda _n: f"s5d-{uuid.uuid4().hex}",
            )
            assert code(create(pooled_factory, w, m.manager_user, key=key)) == 201
        assert idle_in_transaction(w.engine) == 0


def test_the_audit_insert_waits_for_a_competitor_holding_its_lookup_row_and_then_commits(
    w: World, m: Managers, pooled: Engine, pooled_factory: Factory
) -> None:
    """*race*, a reviewed *unlocked* foreign-key target: `audit.change_actions` is seed data the plan does
    not lock. A transaction holding its `created` row `FOR UPDATE` (nothing in the application does) makes
    the post-finalization audit insert wait; that wait is bounded by the holder, ends when it commits, and
    the request then succeeds. Recorded so the unlocked-target review has evidence of what it accepts."""
    with LockRace(w.engine) as race:
        hold = race.hold(
            lambda c: c.execute(
                text("SELECT 1 FROM audit.change_actions WHERE code = 'created' FOR UPDATE")
            ).all()
        )
        request = run_in_thread(
            "create", lambda: create(pooled_factory, w, m.manager_user, key=new_key())
        )
        race.wait_blocked_by(hold, expected=1)
        assert "audit.change_log" in waiting_statement(w.engine, hold.pid)
        hold.commit()
        response = request.wait("the create finishes")
    assert code(response) == 201, response.text


# --- the declared steps match the live catalogue --------------------------------------------------------------------


def test_the_declarations_hold_against_the_live_catalogue(w: World) -> None:
    """The S1 catalogue helper checks every assumption a declaration makes about the database it runs on
    (triggers pinned by function-source hash, unique waits, FK match type and order, defaults, CHECK
    expressions). An empty list is the only passing answer."""
    from dnd_ai.commands.campaign_invitation_plans import CREATE_DECLARATIONS, REVOKE_DECLARATIONS
    from tests.r01_pre_write_catalogue import check_declaration

    problems: list[str] = []
    with w.engine.connect() as connection:
        for name, declarations in (
            ("create", CREATE_DECLARATIONS),
            ("revoke", REVOKE_DECLARATIONS),
        ):
            for kind, declaration in (
                ("reserved", declarations.reserved),
                ("unkeyed", declarations.unkeyed),
            ):
                assert declaration is not None
                problems += [
                    f"{name}/{kind}: {p}" for p in check_declaration(connection, declaration)
                ]
    assert problems == []


# --- protected data -------------------------------------------------------------------------------------------------


def test_the_raw_token_reaches_nothing_but_the_creating_response(
    w: World, m: Managers, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: the token is in the 201 only. The receipt, the audit row, the replay and the recorded
    statement parameters carry the invitation id or the hash, never the raw value."""
    key = new_key()
    first = create(pooled_factory, w, m.manager_user, key=key)
    token = first.json()["token"]
    replay = create(pooled_factory, w, m.manager_user, key=key)
    assert token not in replay.text
    assert token not in json.dumps(receipt(w, key)[1])
    with w.engine.connect() as c:
        dump = c.execute(
            text(
                "SELECT coalesce(string_agg(to_jsonb(cl)::text, ' '), '') FROM audit.change_log cl "
                "WHERE cl.world_id = :w"
            ),
            {"w": w.world_id},
        ).scalar_one()
    assert token not in dump


# --- S5-D correction: the revoke update is required exactly when the invitation is outstanding -------------------------


def _revoke_statements(events: list[str]) -> tuple[int, int]:
    """(invitation updates, audit inserts) in a recorded request."""
    updates = [
        e for e in events if e.startswith("UPDATE security.campaign_invitations SET revoked_at")
    ]
    audits = [e for e in events if e.startswith("INSERT INTO audit.change_log")]
    return len(updates), len(audits)


def _outstanding(w: World, m: Managers, *, revoked: bool) -> uuid.UUID:
    invitation, _ = invite(w, m.manager_membership)
    if revoked:
        with w.engine.begin() as c:
            c.execute(
                text(
                    "UPDATE security.campaign_invitations SET revoked_at = now() "
                    "WHERE campaign_invitation_id = :i"
                ),
                {"i": invitation},
            )
    return invitation


@pytest.mark.parametrize("keyed", (True, False), ids=("keyed", "unkeyed"))
def test_a_genuine_revoke_runs_exactly_one_update_and_one_audit_insert_and_a_no_op_runs_neither(
    keyed: bool, w: World, m: Managers, pooled: Engine, pooled_factory: Factory
) -> None:
    """*sql*: outcome-specific behavior. The outstanding invitation: one update, one audit insert. The
    already-revoked one: neither (a keyed no-op still completes its receipt)."""
    genuine = _outstanding(w, m, revoked=False)
    with Recorder(pooled) as recorded:
        response = revoke(
            pooled_factory, w, m.manager_user, genuine, key=new_key() if keyed else None
        )
    assert code(response) == 200
    assert _revoke_statements(recorded.events) == (1, 1)
    noop = _outstanding(w, m, revoked=True)
    with Recorder(pooled) as recorded:
        response = revoke(pooled_factory, w, m.manager_user, noop, key=new_key() if keyed else None)
    assert code(response) == 200
    assert _revoke_statements(recorded.events) == (0, 0)
    receipts = [e for e in recorded.events if e.startswith("UPDATE security.idempotent_requests")]
    assert len(receipts) == (1 if keyed else 0)


@pytest.mark.parametrize("keyed", (True, False), ids=("keyed", "unkeyed"))
def test_omitting_the_required_revoke_update_is_refused_at_commit_and_rolls_everything_back(
    keyed: bool,
    w: World,
    m: Managers,
    pooled: Engine,
    pooled_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """*route* (omission mutation, test-side only): the invitation is outstanding, so the update is
    `EachLockedRow(complete=True)` over the outstanding-row lock's evidence. A request that never runs it
    cannot commit: the guard refuses the incomplete plan (sanitized 500); the invitation, the audit row and
    the receipt all roll back; the key is reusable; the pooled connection is clean."""
    invitation = _outstanding(w, m, revoked=False)
    key = new_key() if keyed else None
    before = counts(w, key)
    original = AuthorizationPlan.execute

    def skip(self: AuthorizationPlan, connection: Any, step: Any, params: Any) -> StepOutcome:
        if step.name == "revoke_invitation":
            return StepOutcome(step="revoke_invitation", keys=())
        return original(self, connection, step, params)

    monkeypatch.setattr(AuthorizationPlan, "execute", skip)
    response = revoke(pooled_factory, w, m.manager_user, invitation, key=key)
    monkeypatch.undo()
    assert code(response) == 500 and error_of(response) == "internal_error", response.text
    assert counts(w, key) == before and invitation_row(w, invitation)[0] is False
    assert idle_in_transaction(w.engine) == 0
    again = revoke(pooled_factory, w, m.manager_user, invitation, key=key)
    assert code(again) == 200 and invitation_row(w, invitation)[0] is True


@pytest.mark.parametrize("keyed", (True, False), ids=("keyed", "unkeyed"))
def test_attempting_the_update_for_an_already_revoked_invitation_is_refused_and_persists_nothing(
    keyed: bool,
    w: World,
    m: Managers,
    pooled: Engine,
    pooled_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """*route* (commission mutation, test-side only): the handler is made to believe the revoked invitation
    is outstanding. The outstanding-row lock returned no key (database state under the invitation lock), so
    the update's target is not locked and the guard refuses it: no write, no audit row, no receipt."""
    import dnd_ai.api.campaign_invitations as api_module
    from dnd_ai.commands.campaign_invitation_plans import PreparedRevoke

    invitation = _outstanding(w, m, revoked=True)
    key = new_key() if keyed else None
    before = counts(w, key)
    real = api_module.prepare_revoke_invitation

    def lie(*args: Any, **kwargs: Any) -> PreparedRevoke:
        prepared = real(*args, **kwargs)
        return PreparedRevoke(will_revoke=True, change_action_id=prepared.change_action_id)

    monkeypatch.setattr(api_module, "prepare_revoke_invitation", lie)
    response = revoke(pooled_factory, w, m.manager_user, invitation, key=key)
    monkeypatch.undo()
    assert code(response) == 500, response.text
    assert counts(w, key) == before
    assert idle_in_transaction(w.engine) == 0
    ok = revoke(pooled_factory, w, m.manager_user, invitation, key=key)
    assert code(ok) == 200


@pytest.mark.parametrize("keyed", (True, False), ids=("keyed", "unkeyed"))
def test_omitting_the_required_audit_insert_of_a_genuine_revoke_is_refused_at_commit(
    keyed: bool,
    w: World,
    m: Managers,
    pooled: Engine,
    pooled_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """*route* (omission mutation, test-side only): the audit insert is `PerEvidence` over the outstanding-row
    lock, which returned one row, so exactly one is required: the request cannot commit without it. The
    invitation update, the (absent) audit row and the receipt all roll back and the key is reusable."""
    invitation = _outstanding(w, m, revoked=False)
    key = new_key() if keyed else None
    before = counts(w, key)
    original = AuthorizationPlan.execute

    def skip(self: AuthorizationPlan, connection: Any, step: Any, params: Any) -> StepOutcome:
        if step.name == "audit_revoked":
            return StepOutcome(step="audit_revoked", keys=())
        return original(self, connection, step, params)

    monkeypatch.setattr(AuthorizationPlan, "execute", skip)
    response = revoke(pooled_factory, w, m.manager_user, invitation, key=key)
    monkeypatch.undo()
    assert code(response) == 500 and error_of(response) == "internal_error", response.text
    assert counts(w, key) == before and invitation_row(w, invitation)[0] is False
    assert idle_in_transaction(w.engine) == 0
    again = revoke(pooled_factory, w, m.manager_user, invitation, key=key)
    assert code(again) == 200 and counts(w, key)["audit"] == 1


@pytest.mark.parametrize("keyed", (True, False), ids=("keyed", "unkeyed"))
def test_an_audit_insert_attempted_for_an_already_revoked_invitation_is_refused_before_the_driver(
    keyed: bool,
    w: World,
    m: Managers,
    pooled: Engine,
    pooled_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """*route* (commission mutation, test-side only): the invitation is already revoked, so the outstanding-row
    lock returned no row. The handler is made to claim a genuine revoke but to skip the update, so only the
    audit insert is attempted: it is refused before the driver call (no audit statement is recorded), and
    nothing persists."""
    import dnd_ai.api.campaign_invitations as api_module
    from dnd_ai.commands.campaign_invitation_plans import PreparedRevoke

    invitation = _outstanding(w, m, revoked=True)
    key = new_key() if keyed else None
    before = counts(w, key)
    real = api_module.prepare_revoke_invitation

    def lie(*args: Any, **kwargs: Any) -> PreparedRevoke:
        prepared = real(*args, **kwargs)
        return PreparedRevoke(will_revoke=True, change_action_id=prepared.change_action_id)

    monkeypatch.setattr(api_module, "prepare_revoke_invitation", lie)
    monkeypatch.setattr(api_module, "write_revoke_invitation", lambda *a, **k: None)
    with Recorder(pooled) as recorded:
        response = revoke(pooled_factory, w, m.manager_user, invitation, key=key)
    monkeypatch.undo()
    assert code(response) == 500, response.text
    assert _revoke_statements(recorded.events) == (0, 0), "neither write reached the driver"
    assert counts(w, key) == before
    assert idle_in_transaction(w.engine) == 0


@pytest.mark.parametrize("keyed", (True, False), ids=("keyed", "unkeyed"))
def test_a_duplicate_audit_insert_is_refused_and_the_whole_request_rolls_back(
    keyed: bool,
    w: World,
    m: Managers,
    pooled: Engine,
    pooled_factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """*route* (commission mutation, test-side only): a second audit insert on one evidence row is refused
    (`COUNT`, before the driver); the first is rolled back with the invitation update and the receipt."""
    invitation = _outstanding(w, m, revoked=False)
    key = new_key() if keyed else None
    before = counts(w, key)
    original = AuthorizationPlan.execute

    def twice(self: AuthorizationPlan, connection: Any, step: Any, params: Any) -> StepOutcome:
        outcome = original(self, connection, step, params)
        if step.name == "audit_revoked":
            original(self, connection, step, params)
        return outcome

    monkeypatch.setattr(AuthorizationPlan, "execute", twice)
    with Recorder(pooled) as recorded:
        response = revoke(pooled_factory, w, m.manager_user, invitation, key=key)
    monkeypatch.undo()
    assert code(response) == 500, response.text
    assert _revoke_statements(recorded.events)[1] == 1, (
        "only the first audit insert reached the driver"
    )
    assert counts(w, key) == before and invitation_row(w, invitation)[0] is False
    assert idle_in_transaction(w.engine) == 0
    again = revoke(pooled_factory, w, m.manager_user, invitation, key=key)
    assert code(again) == 200 and counts(w, key)["audit"] == 1


def test_a_keyed_no_op_completes_its_receipt_and_replays_it_until_authority_is_lost(
    w: World, m: Managers, pooled: Engine, pooled_factory: Factory
) -> None:
    """*route*: the already-revoked request's receipt is complete, replays unchanged (no write), and a
    replay after the manager's role is revoked is refused without returning the stored body."""
    invitation = _outstanding(w, m, revoked=True)
    key = new_key()
    first = revoke(pooled_factory, w, m.manager_user, invitation, key=key)
    assert code(first) == 200 and receipt(w, key) == (200, first.json(), True)
    stored = counts(w, key)
    with Recorder(pooled) as recorded:
        replay = revoke(pooled_factory, w, m.manager_user, invitation, key=key)
    assert code(replay) == 200 and replay.json() == first.json()
    assert _revoke_statements(recorded.events) == (0, 0) and counts(w, key) == stored
    revoke_role(w.engine, m.manager_role)
    refused = revoke(pooled_factory, w, m.manager_user, invitation, key=key)
    assert code(refused) in (403, 404) and "campaign_invitation_id" not in refused.text
    assert counts(w, key) == stored

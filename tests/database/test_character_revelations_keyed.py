# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""Keyed HTTP regressions for the revelation routes and the concurrency matrix (P03-A A3a,
plan sections 10.8 and 10.9).

Every race is real: the A3 commands and the competing commands run on the migrated schema, the HTTP
cases through the real request transaction (`get_connection`, then P3's commit before the response).
A request is held in flight by a row lock or the audit-action row that this test owns in its own
uncommitted transaction; the intended wait is observed through `pg_locks` and `pg_blocking_pids`
before anything is released. Each case asserts HTTP outcomes, persisted business state, the audit
rows and the idempotency receipts.
"""

import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

import dnd_ai.api.memberships as memberships_api
from dnd_ai.api.idempotency import idempotency_key_lock_scope
from dnd_ai.commands.access_grants import create_resource_grant
from dnd_ai.commands.character_public_profile import (
    release_character_public_profile,
    save_character_public_profile_draft,
)
from dnd_ai.commands.character_reveal import revoke_character_reveal_delegation
from dnd_ai.commands.character_revelations import (
    create_character_revelation,
    revoke_character_revelation,
)
from dnd_ai.commands.memberships import end_campaign_membership
from tests.database.test_campaign_owner_gate import (  # noqa: F401 - fixtures used by name
    Gate,
    client_factory,
    g,
)
from tests.database.test_campaign_owner_lock_order import (  # noqa: F401 - autouse fixture
    _WAIT_SECONDS,
    _release_everything,
    _Request,
    _status,
)
from tests.database.test_character_reveal_delegation import (  # noqa: F401 - fixtures used by name
    Members,
    m,
)
from tests.database.test_character_reveal_delegation_deadlocks import _blocked_by, _PidHold
from tests.database.test_character_revelations import (  # noqa: F401 - fixtures used by name
    CREATE_COMMAND,
    REVOKE_COMMAND,
    Rev,
    audit,
    campaign_body,
    error_code,
    member_body,
    rev,
    revelations,
    snapshot,
    url,
)
from tests.database.test_idempotency_key_lock import _key_lock_state
from tests.lock_race_support import Budget, LockRace

pytestmark = pytest.mark.database

Factory = Callable[[uuid.UUID], TestClient]


# --- helpers ----------------------------------------------------------------------------------


def start(
    factory: Factory, user: uuid.UUID, path: str, body: dict[str, object], key: str | None
) -> _Request:
    request = _Request(thread=threading.Thread())
    headers = {"Idempotency-Key": key} if key else {}

    def run() -> None:
        try:
            with factory(user) as client:
                request.response = client.post(path, json=body, headers=headers)
        except BaseException as exc:  # noqa: BLE001 - surfaced to the test
            request.error = exc

    request.thread = threading.Thread(target=run, daemon=True)
    request.thread.start()
    return request


def hold_audit_action(engine: Engine, code: str) -> _PidHold:
    """Holds `audit.change_actions` for `code` FOR UPDATE, so a request stops at its audit insert,
    after its reservation and its writes, still holding its key lock."""
    return _PidHold(
        engine, "SELECT 1 FROM audit.change_actions WHERE code = :code FOR UPDATE", {"code": code}
    )


def key_ids(engine: Engine, actor: uuid.UUID, g: Gate, key: str) -> tuple[int, int]:
    scope = idempotency_key_lock_scope(
        actor_user_id=actor, campaign_id=g.campaign_id, idempotency_key=key
    )
    with engine.connect() as connection:
        value = int(
            connection.execute(text("SELECT hashtextextended(:s, 0)"), {"s": scope}).scalar_one()
        )
    unsigned = value & 0xFFFFFFFFFFFFFFFF
    return unsigned >> 32, unsigned & 0xFFFFFFFF


def wait_until(predicate: Callable[[], bool], what: str) -> None:
    budget = Budget(_WAIT_SECONDS)
    while not budget.expired():
        if predicate():
            return
        time.sleep(0.02)
    if predicate():  # the last look is after the budget, not before it
        return
    raise AssertionError(f"timed out waiting for {what}{budget.note()}")


def wait_blocked(engine: Engine, hold: _PidHold, request: _Request) -> None:
    wait_until(
        lambda: _blocked_by(engine, hold.pid) >= 1 or request.done,
        "the request to block on the held row",
    )
    assert not request.done, getattr(request.response, "text", request.error)


def wait_key_queue(
    engine: Engine, ids: tuple[int, int], first: _Request, second: _Request, hold: _PidHold
) -> None:
    """`first` holds the key lock and waits on `hold`; `second` waits at the key lock behind it."""

    def queued() -> bool:
        assert not first.done and not second.done, (first.error, second.error)
        state = _key_lock_state(engine, ids)
        granted = [pid for pid, ok, _ in state if ok]
        waiting = [(pid, blockers) for pid, ok, blockers in state if not ok]
        return (
            len(granted) == 1
            and len(waiting) == 1
            and granted[0] in waiting[0][1]
            and _blocked_by(engine, hold.pid) >= 1
        )

    wait_until(queued, "the key-lock queue to form")


def receipts(engine: Engine, g: Gate, actor: uuid.UUID, key: str) -> list[tuple[Any, ...]]:
    with engine.connect() as connection:
        return [
            tuple(r)
            for r in connection.execute(
                text("""
                    SELECT response_status_code, response_body::text, completed_at
                    FROM security.idempotent_requests
                    WHERE campaign_id = :c AND actor_user_id = :u AND idempotency_key = :k
                """),
                {"c": g.campaign_id, "u": actor, "k": key},
            )
        ]


def membership_open(engine: Engine, membership: uuid.UUID) -> bool:
    with engine.connect() as connection:
        return bool(
            connection.execute(
                text(
                    "SELECT ended_at IS NULL FROM security.campaign_memberships "
                    "WHERE campaign_membership_id = :m"
                ),
                {"m": membership},
            ).scalar_one()
        )


def end_url(g: Gate, membership: uuid.UUID) -> str:
    return f"/campaigns/{g.campaign_id}/memberships/{membership}/end"


def make_revelation(
    factory: Factory, g: Gate, character: uuid.UUID, target: uuid.UUID
) -> uuid.UUID:
    with factory(g.o1_user_id) as client:
        response = client.post(url(g, character), json=member_body(target))
    assert response.status_code == 201, response.text
    return uuid.UUID(response.json()["character_revelation_id"])


def live_role_ids(engine: Engine, membership: uuid.UUID) -> list[uuid.UUID]:
    """The `role_id` of every assignment of `membership` that is in force now: not revoked and not
    expired (judged at the database clock). One entry per live assignment, so a duplicated
    assignment shows twice."""
    with engine.connect() as connection:
        return sorted(
            connection.execute(
                text("""
                    SELECT role_id FROM security.membership_roles
                    WHERE campaign_membership_id = :m AND revoked_at IS NULL
                      AND (expires_at IS NULL OR expires_at > clock_timestamp())
                """),
                {"m": membership},
            ).scalars()
        )


def role_rows(engine: Engine, membership: uuid.UUID) -> list[tuple[Any, ...]]:
    """Every assignment row of `membership`, live or not, with its state: used to show that a race
    changed none of a caller's assignments."""
    with engine.connect() as connection:
        return [
            tuple(row)
            for row in connection.execute(
                text("""
                    SELECT membership_role_id, role_id, revoked_at, expires_at
                    FROM security.membership_roles
                    WHERE campaign_membership_id = :m
                    ORDER BY membership_role_id
                """),
                {"m": membership},
            )
        ]


def default_roles(g: Gate) -> dict[uuid.UUID, set[uuid.UUID]]:
    """The live role set each Gate member starts with: the owners the **built-in** owner role, the
    manager its campaign-scoped custom role, the player the built-in player role. (`Gate` also holds
    `lookalike_role_id`, a campaign-scoped role that reuses the code `campaign_owner`; nobody holds
    it, and comparing role ids, not codes, is what tells it from the built-in one.)"""
    return {
        g.o1: {g.owner_role_id},
        g.o2: {g.owner_role_id},
        g.manager: {g.custom_manager_role_id},
        g.player: {g.player_role_id},
    }


def assert_roles(
    engine: Engine,
    g: Gate,
    *,
    ended: tuple[uuid.UUID, ...] = (),
    roles: dict[uuid.UUID, set[uuid.UUID]] | None = None,
) -> None:
    """The exact final role state of a membership-end race. Every ended membership is closed and
    has **no** live assignment. Every other Gate member is open and its live assignments are
    exactly the expected role ids: the defaults of `default_roles` unless `roles` names the set
    (recovery or a transfer adding the built-in owner role, a relinquisher left with none). Live
    means unrevoked and unexpired, and each live assignment counts once, so a duplicate fails."""
    for membership in ended:
        assert not membership_open(engine, membership), membership
        assert live_role_ids(engine, membership) == [], membership
    expected = default_roles(g) | (roles or {})
    for membership, wanted in expected.items():
        if membership in ended:
            continue
        assert membership_open(engine, membership), membership
        assert live_role_ids(engine, membership) == sorted(wanted), (
            membership,
            live_role_ids(engine, membership),
            sorted(wanted),
        )
    # The built-in owner role is the template (no campaign); the look-alike is campaign-scoped.
    with engine.connect() as connection:
        scopes = dict(
            connection.execute(
                text("SELECT role_id, campaign_id FROM security.roles WHERE role_id = ANY(:ids)"),
                {"ids": [g.owner_role_id, g.player_role_id, g.lookalike_role_id]},
            ).all()
        )
    assert scopes[g.owner_role_id] is None and scopes[g.player_role_id] is None
    assert scopes[g.lookalike_role_id] == g.campaign_id


def live_roles(engine: Engine, membership: uuid.UUID) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text(
                    "SELECT count(*) FROM security.membership_roles "
                    "WHERE campaign_membership_id = :m AND revoked_at IS NULL"
                ),
                {"m": membership},
            ).scalar_one()
        )


# --- 1. authority or a deny lost after the pre-check: no replay -------------------------------


@pytest.mark.parametrize("route", ["create", "revoke"])
@pytest.mark.parametrize("cause", ["delegation", "deny"])
def test_authority_or_a_deny_lost_after_the_precheck_is_refused_without_a_replay(
    client_factory: Factory,
    postgres_engine: Engine,
    g: Gate,
    m: Members,
    rev: Rev,
    route: str,
    cause: str,
) -> None:
    c = rev.character_id
    target = g.player
    existing = make_revelation(client_factory, g, c, target)
    key = f"loss-{route}-{cause}-{uuid.uuid4().hex[:8]}"
    if route == "create":
        path, body = url(g, c), campaign_body("campaign_current_and_future")
    else:
        path, body = url(g, c, f"/{existing}/revoke"), {"reason": "No longer needed"}
    first = start(client_factory, m.gm_user_id, path, body, key)
    first.thread.join(timeout=_WAIT_SECONDS)
    assert _status(first.response) in (200, 201), first.response.text  # type: ignore[attr-defined]
    stored = receipts(postgres_engine, g, m.gm_user_id, key)
    before_audit = len(audit(postgres_engine, g, CREATE_COMMAND, REVOKE_COMMAND))
    before_rows = revelations(postgres_engine, g, c)
    before_snapshot = {
        r["character_revelation_id"]: snapshot(postgres_engine, r["character_revelation_id"])
        for r in before_rows
    }
    assert len(stored) == 1

    with LockRace(postgres_engine) as race:
        if cause == "delegation":
            held = race.hold(
                lambda cn: revoke_character_reveal_delegation(
                    cn,
                    campaign_id=g.campaign_id,
                    actor_membership_id=g.o1,
                    grantee_campaign_membership_id=m.gm,
                    reason="Lost it",
                )
            )
        else:
            # Writing the deny directly would not hold anything; the real command holds the
            # caller's membership row, which the request needs at step 3.
            held = race.hold(
                lambda cn: create_resource_grant(
                    cn,
                    campaign_id=g.campaign_id,
                    grantee_campaign_membership_id=m.gm,
                    grantee_access_group_id=None,
                    capability_code="campaign.view",
                    effect="deny",
                    expected_world_id=g.world_id,
                    granted_by_membership_id=g.o1,
                    entity_id=c,
                )
            )
        second = race.start(
            "retry", lambda _cn: client_factory_call(client_factory, m.gm_user_id, path, body, key)
        )
        race.wait_blocked_by(held, second)
        held.commit()
        race.join_all()
    response = second.result
    expected = (403, "character_reveal_required") if cause == "delegation" else (404, "not_found")
    assert response.status_code == expected[0], response.text  # type: ignore[attr-defined]
    assert error_code(response) == expected[1]
    assert "character_revelation_id" not in response.text  # type: ignore[attr-defined]  # no receipt fields
    assert receipts(postgres_engine, g, m.gm_user_id, key) == stored  # same completed_at
    assert len(audit(postgres_engine, g, CREATE_COMMAND, REVOKE_COMMAND)) == before_audit
    after_rows = revelations(postgres_engine, g, c)
    assert after_rows == before_rows
    assert {
        r["character_revelation_id"]: snapshot(postgres_engine, r["character_revelation_id"])
        for r in after_rows
    } == before_snapshot


def client_factory_call(
    factory: Factory, user: uuid.UUID, path: str, body: dict[str, object], key: str
) -> Any:
    with factory(user) as client:
        return client.post(path, json=body, headers={"Idempotency-Key": key})


# --- 2. an authorized key reused with a different payload conflicts ---------------------------


@pytest.mark.parametrize("route", ["create", "revoke"])
def test_an_authorized_key_reused_with_another_payload_character_or_route_conflicts(
    client_factory: Factory, postgres_engine: Engine, g: Gate, rev: Rev, route: str
) -> None:
    c = rev.character_id
    existing = make_revelation(client_factory, g, c, g.manager)
    other = make_revelation(client_factory, g, c, g.o2)
    key = f"conflict-{route}-{uuid.uuid4().hex[:8]}"
    if route == "create":
        first_path, first_body = url(g, c), member_body(g.player)
        variants = [
            (url(g, c), member_body(g.o2)),  # another target
            (url(g, c), campaign_body("campaign_current")),  # another kind
            (url(g, rev.unreleased_id), member_body(g.player)),  # another character
            (url(g, c, f"/{existing}/revoke"), {"reason": "Because"}),  # the other route
        ]
    else:
        first_path, first_body = url(g, c, f"/{existing}/revoke"), {"reason": "Because"}
        variants = [
            (url(g, c, f"/{existing}/revoke"), {"reason": "A different reason"}),
            (url(g, c, f"/{other}/revoke"), {"reason": "Because"}),  # another target
            (url(g, c), member_body(g.player)),  # the other route
        ]
    first = client_factory_call(client_factory, g.o1_user_id, first_path, first_body, key)
    assert first.status_code in (200, 201), first.text
    stored = receipts(postgres_engine, g, g.o1_user_id, key)
    rows = revelations(postgres_engine, g, c)
    audited = len(audit(postgres_engine, g, CREATE_COMMAND, REVOKE_COMMAND))
    for path, body in variants:
        response = client_factory_call(client_factory, g.o1_user_id, path, body, key)
        assert response.status_code == 409, (path, response.text)
    if route == "revoke":
        # Another character's path cannot name this revelation at all: a non-disclosing 404, not a
        # key conflict (the revelation lookup precedes the reservation).
        elsewhere = client_factory_call(
            client_factory,
            g.o1_user_id,
            url(g, rev.unreleased_id, f"/{existing}/revoke"),
            first_body,
            key,
        )
        assert elsewhere.status_code == 404
    assert receipts(postgres_engine, g, g.o1_user_id, key) == stored
    assert revelations(postgres_engine, g, c) == rows
    assert len(audit(postgres_engine, g, CREATE_COMMAND, REVOKE_COMMAND)) == audited


# --- 3. concurrent same-key requests: one mutation, one audit row, one receipt ----------------


@pytest.mark.parametrize("route", ["create", "revoke"])
def test_concurrent_same_key_requests_make_one_mutation_one_audit_row_and_one_receipt(
    client_factory: Factory, postgres_engine: Engine, g: Gate, rev: Rev, route: str
) -> None:
    c = rev.character_id
    existing = make_revelation(client_factory, g, c, g.manager)
    key = f"concurrent-{route}-{uuid.uuid4().hex[:8]}"
    if route == "create":
        path, body, action = url(g, c), campaign_body("campaign_current"), "created"
    else:
        path, body, action = url(g, c, f"/{existing}/revoke"), {"reason": "Because"}, "updated"
    hold = hold_audit_action(postgres_engine, action)
    first = start(client_factory, g.o1_user_id, path, body, key)
    wait_blocked(postgres_engine, hold, first)  # stopped at its audit insert, key lock held
    second = start(client_factory, g.o1_user_id, path, body, key)
    wait_key_queue(
        postgres_engine, key_ids(postgres_engine, g.o1_user_id, g, key), first, second, hold
    )
    hold.release()
    one, two = first.join(), second.join()
    assert _status(one) == _status(two) and one.json() == two.json()  # type: ignore[attr-defined]
    assert _status(one) == (201 if route == "create" else 200)
    rows = revelations(postgres_engine, g, c)
    if route == "create":
        current = [r for r in rows if r["kind"] == "campaign_current"]
        assert (
            len(current) == 1
            and len(snapshot(postgres_engine, current[0]["character_revelation_id"])) == 7
        )
        assert len(audit(postgres_engine, g, CREATE_COMMAND)) == 2  # the setup revelation, plus one
    else:
        assert [r for r in rows if r["end_reason"] == "revoked"] != []
        assert len(audit(postgres_engine, g, REVOKE_COMMAND)) == 1
    assert len(receipts(postgres_engine, g, g.o1_user_id, key)) == 1


# --- 4. a rollback frees the key --------------------------------------------------------------


def test_a_refusal_after_the_reservation_leaves_no_receipt_and_the_key_then_works(
    client_factory: Factory, postgres_engine: Engine, g: Gate, rev: Rev
) -> None:
    c = rev.unreleased_id
    key = f"rollback-{uuid.uuid4().hex[:8]}"
    body = campaign_body("campaign_current")
    refused = client_factory_call(client_factory, g.o1_user_id, url(g, c), body, key)
    assert refused.status_code == 409 and error_code(refused) == "public_profile_not_released"
    assert receipts(postgres_engine, g, g.o1_user_id, key) == []  # rolled back with the request
    assert revelations(postgres_engine, g, c) == []
    assert audit(postgres_engine, g, CREATE_COMMAND) == []
    with postgres_engine.begin() as connection:  # the cause is removed: a release is made
        save_character_public_profile_draft(
            connection,
            campaign_id=g.campaign_id,
            character_id=c,
            actor_user_id=g.o1_user_id,
            expected_row_version=None,
            fields={"public_appearance": "Now released"},
        )
    with postgres_engine.begin() as connection:
        release_character_public_profile(
            connection,
            campaign_id=g.campaign_id,
            character_id=c,
            actor_membership_id=g.o1,
            expected_draft_row_version=1,
            release_note=None,
        )
    again = client_factory_call(client_factory, g.o1_user_id, url(g, c), body, key)
    assert again.status_code == 201, again.text
    assert len(receipts(postgres_engine, g, g.o1_user_id, key)) == 1
    assert len(audit(postgres_engine, g, CREATE_COMMAND)) == 1


def test_an_ended_target_rolls_back_and_a_reopen_lets_the_same_key_and_body_succeed(
    client_factory: Factory, postgres_engine: Engine, g: Gate, rev: Rev
) -> None:
    c = rev.character_id
    with postgres_engine.begin() as connection:
        end_campaign_membership(
            connection,
            campaign_membership_id=g.player,
            campaign_id=g.campaign_id,
            ended_by_membership_id=g.o1,
        )
    key = f"reopen-{uuid.uuid4().hex[:8]}"
    body = member_body(g.player)
    refused = client_factory_call(client_factory, g.o1_user_id, url(g, c), body, key)
    assert refused.status_code == 409 and error_code(refused) == "revelation_target_not_active"
    assert receipts(postgres_engine, g, g.o1_user_id, key) == []
    with postgres_engine.begin() as connection:  # the invitation reopen keeps the membership id
        connection.execute(
            text("""
                UPDATE security.campaign_memberships
                SET ended_at = NULL, ended_by_membership_id = NULL,
                    membership_status_id = (SELECT membership_status_id
                        FROM security.membership_statuses WHERE code = 'active')
                WHERE campaign_membership_id = :m
            """),
            {"m": g.player},
        )
    again = client_factory_call(client_factory, g.o1_user_id, url(g, c), body, key)
    assert again.status_code == 201, again.text
    assert len(receipts(postgres_engine, g, g.o1_user_id, key)) == 1
    assert len(audit(postgres_engine, g, CREATE_COMMAND)) == 1


# --- 5. the same key across routes (requires P2) ----------------------------------------------


@pytest.mark.parametrize("a3_route", ["create", "revoke"])
@pytest.mark.parametrize("ends", ["actor", "other"])
def test_xr1_an_a3_request_first_then_a_keyed_end_with_the_same_key_gets_409(
    client_factory: Factory, postgres_engine: Engine, g: Gate, rev: Rev, a3_route: str, ends: str
) -> None:
    c = rev.character_id
    existing = make_revelation(client_factory, g, c, g.manager)
    key = f"xr1-{a3_route}-{ends}-{uuid.uuid4().hex[:8]}"
    if a3_route == "create":
        path, body, action = url(g, c), campaign_body("campaign_current"), "created"
    else:
        path, body, action = url(g, c, f"/{existing}/revoke"), {"reason": "Because"}, "updated"
    victim = g.o1 if ends == "actor" else g.player
    hold = hold_audit_action(postgres_engine, action)
    first = start(client_factory, g.o1_user_id, path, body, key)
    wait_blocked(postgres_engine, hold, first)
    second = start(client_factory, g.o1_user_id, end_url(g, victim), {}, key)
    wait_key_queue(
        postgres_engine, key_ids(postgres_engine, g.o1_user_id, g, key), first, second, hold
    )
    hold.release()
    assert _status(first.join()) in (200, 201)  # type: ignore[arg-type]
    assert _status(second.join()) == 409  # type: ignore[arg-type]
    assert membership_open(postgres_engine, victim)
    assert audit(postgres_engine, g, "end_campaign_membership") == []
    assert len(receipts(postgres_engine, g, g.o1_user_id, key)) == 1


@pytest.mark.parametrize("a3_route", ["create", "revoke"])
@pytest.mark.parametrize("ends", ["actor", "other"])
def test_xr2_a_keyed_end_first_then_an_a3_request_with_the_same_key_is_refused_or_conflicts(
    client_factory: Factory, postgres_engine: Engine, g: Gate, rev: Rev, a3_route: str, ends: str
) -> None:
    c = rev.character_id
    existing = make_revelation(client_factory, g, c, g.manager)
    key = f"xr2-{a3_route}-{ends}-{uuid.uuid4().hex[:8]}"
    if a3_route == "create":
        path, body = url(g, c), campaign_body("campaign_current")
    else:
        path, body = url(g, c, f"/{existing}/revoke"), {"reason": "Because"}
    victim = g.o1 if ends == "actor" else g.player
    victim_role = g.o1_role if ends == "actor" else g.player_role
    hold = _PidHold(
        postgres_engine,
        "SELECT 1 FROM security.membership_roles WHERE membership_role_id = :r FOR SHARE",
        {"r": victim_role},
    )
    first = start(client_factory, g.o1_user_id, end_url(g, victim), {}, key)
    wait_blocked(postgres_engine, hold, first)  # the end reserved K, then waits on the role row
    second = start(client_factory, g.o1_user_id, path, body, key)
    wait_key_queue(
        postgres_engine, key_ids(postgres_engine, g.o1_user_id, g, key), first, second, hold
    )
    hold.release()
    assert _status(first.join()) == 200  # type: ignore[arg-type]
    answer = second.join()
    if ends == "actor":
        # The owner ended themself: their owner row is revoked, so step 7 refuses.
        assert _status(answer) == 403 and error_code(answer) == "character_reveal_required"
    else:
        assert _status(answer) == 409  # K holds the end's receipt
    assert not membership_open(postgres_engine, victim)
    assert live_roles(postgres_engine, victim) == 0
    assert len(audit(postgres_engine, g, "end_campaign_membership")) == 1
    assert len(audit(postgres_engine, g, CREATE_COMMAND, REVOKE_COMMAND)) == 1  # the setup row
    assert len(receipts(postgres_engine, g, g.o1_user_id, key)) == 1


def test_xr3_the_first_request_rolls_back_and_the_waiting_create_runs_fresh(
    client_factory: Factory,
    postgres_engine: Engine,
    g: Gate,
    rev: Rev,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c = rev.character_id
    key = f"xr3-{uuid.uuid4().hex[:8]}"
    real = memberships_api.record_change_log

    def fail_once(*args: Any, **kwargs: Any) -> Any:
        if not getattr(fail_once, "failed", False):
            fail_once.failed = True  # type: ignore[attr-defined]
            raise ValueError("the end fails after its reservation")
        return real(*args, **kwargs)

    monkeypatch.setattr(memberships_api, "record_change_log", fail_once)
    hold = _PidHold(
        postgres_engine,
        "SELECT 1 FROM security.membership_roles WHERE membership_role_id = :r FOR SHARE",
        {"r": g.player_role},
    )
    first = start(client_factory, g.o1_user_id, end_url(g, g.player), {}, key)
    wait_blocked(postgres_engine, hold, first)
    second = start(client_factory, g.o1_user_id, url(g, c), campaign_body("campaign_current"), key)
    wait_key_queue(
        postgres_engine, key_ids(postgres_engine, g.o1_user_id, g, key), first, second, hold
    )
    hold.release()
    assert _status(first.join()) == 400  # type: ignore[arg-type]
    created = second.join()
    assert _status(created) == 201  # type: ignore[arg-type]
    assert membership_open(postgres_engine, g.player)
    assert audit(postgres_engine, g, "end_campaign_membership") == []
    receipt = receipts(postgres_engine, g, g.o1_user_id, key)
    assert len(receipt) == 1 and "character_revelation_id" in receipt[0][1]
    assert len(revelations(postgres_engine, g, c)) == 1


def test_xr5_a_create_and_a_revoke_with_one_key_conflict_in_both_orders(
    client_factory: Factory, postgres_engine: Engine, g: Gate, rev: Rev
) -> None:
    c = rev.character_id
    existing = make_revelation(client_factory, g, c, g.manager)
    revoke_path, revoke_body = url(g, c, f"/{existing}/revoke"), {"reason": "Because"}
    create_path, create_body = url(g, c), campaign_body("campaign_current")
    for first_route, second_route in (("create", "revoke"), ("revoke", "create")):
        key = f"xr5-{first_route}-{uuid.uuid4().hex[:8]}"
        specs = {
            "create": (create_path, create_body, "created"),
            "revoke": (revoke_path, revoke_body, "updated"),
        }
        hold = hold_audit_action(postgres_engine, specs[first_route][2])
        first = start(
            client_factory, g.o1_user_id, specs[first_route][0], specs[first_route][1], key
        )
        wait_blocked(postgres_engine, hold, first)
        second = start(
            client_factory, g.o1_user_id, specs[second_route][0], specs[second_route][1], key
        )
        wait_key_queue(
            postgres_engine, key_ids(postgres_engine, g.o1_user_id, g, key), first, second, hold
        )
        hold.release()
        assert _status(first.join()) in (200, 201)  # type: ignore[arg-type]
        assert _status(second.join()) == 409  # type: ignore[arg-type]
        assert len(receipts(postgres_engine, g, g.o1_user_id, key)) == 1


# --- snapshot creation versus membership changes (real commands) ------------------------------


def _create_current(g: Gate, c: uuid.UUID) -> Callable[[Any], Any]:
    return lambda cn: create_character_revelation(
        cn,
        campaign_id=g.campaign_id,
        character_id=c,
        actor_membership_id=g.o1,
        audience_kind="campaign_current",
        target_campaign_membership_id=None,
        target_access_group_id=None,
        reason="Race",
        reserve=lambda: False,
    )


def _end(g: Gate, membership: uuid.UUID, by: uuid.UUID | None = None) -> Callable[[Any], Any]:
    return lambda cn: end_campaign_membership(
        cn, campaign_membership_id=membership, campaign_id=g.campaign_id,
        ended_by_membership_id=by or g.o1,
    )  # fmt: skip


def test_creation_that_reaches_a_member_first_keeps_them_in_the_snapshot_and_the_end_then_removes_them(
    postgres_engine: Engine, g: Gate, rev: Rev
) -> None:
    """Plan 10.8.4 (A3-F1/F4): step 4a locks N `FOR KEY SHARE`; the end waits at N, then closes N's
    snapshot row in a fresh statement after its own campaign lock."""
    c = rev.character_id
    with LockRace(postgres_engine) as race:
        pause = race.pause(
            thread_name="create",
            pattern=r"FROM campaign\.campaigns WHERE campaign_id = .* FOR KEY SHARE",
            after=r"FROM security\.campaign_memberships WHERE campaign_id = .* FOR KEY SHARE",
        )
        create = race.start("create", _create_current(g, c))
        pause.wait_reached(create)
        end = race.start("end", _end(g, g.player))
        race.wait_blocked_by(pause, end)
        pause.release()
        race.join_all()
    assert create.error is None and end.error is None, (create.error, end.error)
    [row] = revelations(postgres_engine, g, c)
    members = snapshot(postgres_engine, row["character_revelation_id"])
    assert g.player in members and members[g.player][0] is not None
    assert members[g.player][1] == "membership_ended"
    assert members[g.o2][0] is None
    assert_roles(postgres_engine, g, ended=(g.player,))


def test_an_end_that_reaches_the_member_first_keeps_them_out_of_the_snapshot(
    postgres_engine: Engine, g: Gate, rev: Rev
) -> None:
    """Plan 10.8.4 (A3-F2/F3): the end holds N `FOR UPDATE`; step 4a waits for it and re-reads N as
    ended, so N is not a candidate."""
    c = rev.character_id
    with LockRace(postgres_engine) as race:
        pause = race.pause(
            thread_name="end",
            pattern=r"FROM campaign\.campaigns WHERE campaign_id = .* FOR UPDATE",
        )
        end = race.start("end", _end(g, g.player))
        pause.wait_reached(end)
        create = race.start("create", _create_current(g, c))
        race.wait_blocked_by(pause, create)
        pause.release()
        race.join_all()
    assert create.error is None and end.error is None, (create.error, end.error)
    [row] = revelations(postgres_engine, g, c)
    members = snapshot(postgres_engine, row["character_revelation_id"])
    assert g.player not in members and g.o2 in members
    assert_roles(postgres_engine, g, ended=(g.player,))


def test_a_revoke_and_the_end_of_the_target_meet_at_the_campaign_row_in_either_order(
    client_factory: Factory, postgres_engine: Engine, g: Gate, rev: Rev
) -> None:
    """Plan 10.8.4 (A3-V1/V2): both commit; whichever closes the member-target revelation first
    decides its end reason, and the other is a no-op."""
    c = rev.character_id

    def revoke_it(revelation: uuid.UUID) -> Callable[[Any], Any]:
        return lambda cn: revoke_character_revelation(
            cn,
            campaign_id=g.campaign_id,
            character_id=c,
            character_revelation_id=revelation,
            actor_membership_id=g.o1,
            reason="Race",
            reserve=lambda: False,
        )

    # V1: the revoke first, paused holding the campaign `KEY SHARE`; the end waits for the campaign.
    first = make_revelation(client_factory, g, c, g.player)
    with LockRace(postgres_engine) as race:
        pause = race.pause(
            thread_name="revoke",
            pattern=r"SELECT 1 FROM security\.users WHERE user_id = .* FOR KEY SHARE",
        )
        revoke = race.start("revoke", revoke_it(first))
        pause.wait_reached(revoke)
        end = race.start("end", _end(g, g.player))
        race.wait_blocked_by(pause, end)
        pause.release()
        race.join_all()
    assert revoke.error is None and end.error is None, (revoke.error, end.error)
    row = next(
        r for r in revelations(postgres_engine, g, c) if r["character_revelation_id"] == first
    )
    assert row["end_reason"] == "revoked" and row["ended_by_membership_id"] == g.o1

    # V2: the end first, paused holding the campaign row; the revoke waits and finds it closed.
    with postgres_engine.begin() as connection:  # the player rejoins (a reopen keeps the id)
        connection.execute(
            text("""
                UPDATE security.campaign_memberships
                SET ended_at = NULL, ended_by_membership_id = NULL,
                    membership_status_id = (SELECT membership_status_id
                        FROM security.membership_statuses WHERE code = 'active')
                WHERE campaign_membership_id = :m
            """),
            {"m": g.player},
        )
    second = make_revelation(client_factory, g, c, g.player)
    with LockRace(postgres_engine) as race:
        pause = race.pause(
            thread_name="end",
            pattern=r"UPDATE security\.character_revelations SET ended_at",
        )
        end = race.start("end", _end(g, g.player))
        pause.wait_reached(end)
        revoke = race.start("revoke", revoke_it(second))
        race.wait_blocked_by(pause, revoke)
        pause.release()
        race.join_all()
    assert revoke.error is None and end.error is None, (revoke.error, end.error)
    assert revoke.result.revoked is False  # type: ignore[union-attr]
    row = next(
        r for r in revelations(postgres_engine, g, c) if r["character_revelation_id"] == second
    )
    assert row["end_reason"] == "target_membership_ended"


@pytest.mark.parametrize("end_first", [True, False])
def test_the_explicit_actor_lock_meets_a_grant_to_the_actor_without_a_deadlock(
    postgres_engine: Engine, g: Gate, rev: Rev, end_first: bool
) -> None:
    """Plan 10.8.5 (A3-X1/X2): ending N by actor O2 against a resource grant to O2, in both orders.
    The end locks the actor `FOR KEY SHARE` before the campaign `FOR UPDATE`, as today's status
    UPDATE did, so the grant (which holds O2 `FOR UPDATE` and waits for the campaign) cannot form a
    cycle with it."""
    grant = lambda cn: create_resource_grant(  # noqa: E731
        cn,
        campaign_id=g.campaign_id,
        grantee_campaign_membership_id=g.o2,
        grantee_access_group_id=None,
        capability_code="character.view_summary",
        effect="allow",
        expected_world_id=g.world_id,
        granted_by_membership_id=g.o1,
        character_id=rev.character_id,
    )
    with LockRace(postgres_engine) as race:
        if end_first:
            pause = race.pause(
                thread_name="end",
                pattern=r"FROM campaign\.campaigns WHERE campaign_id = .* FOR UPDATE",
            )
            end = race.start("end", _end(g, g.player, by=g.o2))
            pause.wait_reached(end)
            granted = race.start("grant", grant)
            race.wait_blocked_by(pause, granted)
            pause.release()
        else:
            held = race.hold(grant)
            end = race.start("end", _end(g, g.player, by=g.o2))
            race.wait_blocked_by(held, end)
            held.commit()
            granted = None
        race.join_all()
    assert end.error is None and (granted is None or granted.error is None), (end.error, granted)
    assert not membership_open(postgres_engine, g.player)
    with postgres_engine.connect() as connection:
        assert (
            connection.execute(
                text(
                    "SELECT count(*) FROM security.resource_grants WHERE grantee_campaign_membership_id = :m "
                    "AND revoked_at IS NULL"
                ),
                {"m": g.o2},
            ).scalar_one()
            == 1
        )

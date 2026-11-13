# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""HTTP equivalents of the §10.8.4 command races (P03-A A3a, plan section 10.9 "HTTP races").

Each case runs the A3 route, the end route, or the other membership route through `TestClient`, in
its own request transaction (`get_connection`, then P3's commit before the response), against a real
competitor. The competitor is either another HTTP request held in flight at its audit insert (the
test owns the `audit.change_actions` row, so the request stops *after* its locks and writes, still
holding them), or a real command left uncommitted in its own transaction (`LockRace.hold`) where the
operation has no route or must be held before its audit. The intended blocker is observed through
`pg_blocking_pids` before anything is released, and the cases that name both winners test both.

Every case asserts the HTTP responses, the receipts, the command-specific audit rows, and the
revelation, snapshot, membership and role state as applicable. The command-level versions of the same
rows are in test_character_revelations_matrix.py; the mapping is in plan section 10.9.
"""

import json
import sys
import threading
import time
import traceback
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from dnd_ai.commands.character_revelations import revoke_character_revelation
from dnd_ai.commands.local_auth import _disable_local_account_impl
from dnd_ai.commands.memberships import (
    transfer_campaign_ownership,
)
from dnd_ai.domain.access import LOCAL_AUTH_ISSUER
from dnd_ai.domain.data_classification import replay_body
from tests.database.test_campaign_owner_gate import (  # noqa: F401 - fixtures used by name
    Gate,
    client_factory,
    g,
)
from tests.database.test_campaign_owner_lock_order import (  # noqa: F401 - autouse fixture
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
from tests.database.test_character_revelations_keyed import (
    assert_roles,
    end_url,
    hold_audit_action,
    live_role_ids,
    make_revelation,
    receipts,
    role_rows,
    start,
    wait_blocked,
    wait_until,
)
from tests.database.test_character_revelations_matrix import (  # noqa: F401 - fixtures by name
    _account_active,
    _owner_role_live,
    _recover,
    admin,
    create_as,
    end_of,
    stranded,
)
from tests.factories import make_external_identity
from tests.lock_race_support import Budget, LockRace
from tests.r01_support import fixture_plan

pytestmark = pytest.mark.database

Factory = Callable[[uuid.UUID], TestClient]
END = "end_campaign_membership"
TRANSFER = "transfer_campaign_ownership"
GRANT = "create_resource_grant"
ADD = "add_campaign_member"


# --- helpers ----------------------------------------------------------------------------------


def key(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def blocked_pid(engine: Engine, holder_pid: int) -> int:
    """The backend directly blocked by `holder_pid`: the HTTP request waiting on the hold."""
    holder: list[int] = []

    def waiting() -> bool:
        with engine.connect() as connection:
            rows = connection.execute(
                text("""
                    SELECT pid FROM pg_stat_activity
                    WHERE datname = current_database() AND :h = ANY(pg_blocking_pids(pid))
                """),
                {"h": holder_pid},
            ).scalars()
            holder[:] = [int(row) for row in rows]
        return len(holder) >= 1

    wait_until(waiting, "a request to wait on the held transaction")
    return holder[0]


def _sessions(engine: Engine) -> list[tuple[object, ...]]:
    """Every backend of this database, for failure messages: pid, state, wait event, blockers,
    transaction age, backend age and the head of its last statement."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(r"""
                SELECT pid, state, wait_event_type, wait_event, pg_blocking_pids(pid),
                       now() - xact_start AS xact_age, now() - backend_start AS backend_age,
                       left(regexp_replace(query, '\s+', ' ', 'g'), 110)
                FROM pg_stat_activity
                WHERE datname = current_database() AND pid <> pg_backend_pid()
                ORDER BY pid
            """)
        ).all()
    return [tuple(row) for row in rows]


def _recent_commits(engine: Engine) -> dict[str, object]:
    """What committed in the last two minutes, so a failure says whether the request ever reached
    the database (a revelation or a receipt) and when, against the holder's transaction age."""
    with engine.connect() as connection:
        return dict(
            connection.execute(
                text("""
                    SELECT
                      (SELECT count(*) FROM security.character_revelations
                         WHERE created_at > now() - interval '120 seconds') AS revelations,
                      (SELECT count(*) FROM security.idempotent_requests
                         WHERE created_at > now() - interval '120 seconds') AS receipts,
                      (SELECT count(*) FROM security.idempotent_requests
                         WHERE completed_at > now() - interval '120 seconds') AS completed
                """)
            )
            .mappings()
            .one()
        )


def _thread_stacks(request: _Request) -> str:
    """Where the request's thread, and every thread it started, is right now: a request that is not
    waiting in the database is somewhere else, and this says where."""
    frames = sys._current_frames()
    named = {thread.ident: thread.name for thread in threading.enumerate()}
    out = []
    for ident, frame in frames.items():
        if ident == threading.get_ident():
            continue
        stack = "".join(traceback.format_stack(frame, limit=6))
        mine = ident == request.thread.ident
        out.append(f"--- thread {named.get(ident, ident)} (request thread: {mine})\n{stack}")
    return "\n".join(out)


def wait_waiting_on(engine: Engine, pid: int, request: _Request, seconds: float = 15.0) -> None:
    """`request` is blocked (directly or in the queue) by the backend `pid`.

    A request that finishes first is reported as it finished (an early 201 means it was never
    held). A wait that expires reports every backend, so which session the request is really
    waiting on, and whether the holder is still open, is in the failure rather than a bare timeout.
    The budget is not charged for time the whole process did not run (`Budget`): a freeze right
    after the hold otherwise ends the wait the instant the process resumes, before the request,
    frozen with it, has been scheduled to reach the database."""
    budget = Budget(seconds)
    while not budget.expired():
        if request.done:
            raise AssertionError(
                f"the request finished before it waited on backend {pid}: "
                f"{getattr(request.response, 'status_code', None)} "
                f"{getattr(request.response, 'text', request.error)}; "
                f"committed={_recent_commits(engine)} sessions={_sessions(engine)}"
            )
        if _blocked_by(engine, pid) >= 1:
            return
        time.sleep(0.02)
    if _blocked_by(engine, pid) >= 1:  # the last look is after the deadline, not before it
        return
    raise AssertionError(
        f"the request never waited on backend {pid} (request done={request.done}){budget.note()}; "
        f"committed={_recent_commits(engine)} sessions={_sessions(engine)}\n"
        f"threads:\n{_thread_stacks(request)}"
    )


def in_flight(
    engine: Engine,
    factory: Factory,
    user: uuid.UUID,
    path: str,
    body: dict[str, object],
    request_key: str,
    action: str,
) -> tuple[_PidHold, _Request, int]:
    """An HTTP request stopped at its audit insert (so holding every lock it takes), with the pid of
    its backend."""
    hold = hold_audit_action(engine, action)
    request = start(factory, user, path, body, request_key)
    wait_blocked(engine, hold, request)
    return hold, request, blocked_pid(engine, hold.pid)


def post(
    factory: Factory, user: uuid.UUID, path: str, body: dict[str, object], request_key: str
) -> _Request:
    return start(factory, user, path, body, request_key)


def one_receipt(
    engine: Engine, g: Gate, user: uuid.UUID, request_key: str, request: _Request
) -> None:
    """Exactly one receipt for the key, completed, with the response's status and the minimal body
    the documented sanitizer (`replay_body`: ids, flags, numbers and short codes only) makes of the
    response. A replay is allowed to omit the metadata the sanitizer drops, so the stored body must
    equal the sanitized response, and may hold nothing the response did not."""
    response = request.response
    stored = receipts(engine, g, user, request_key)
    assert len(stored) == 1, stored
    status, body_text, completed_at = stored[0]
    assert status == response.status_code, (status, response.status_code)  # type: ignore[attr-defined]
    assert completed_at is not None  # the reservation was completed, not left pending
    body = json.loads(body_text)
    assert body == replay_body(response.json()), (body, response.json())  # type: ignore[attr-defined]
    assert set(body) <= set(response.json())  # type: ignore[attr-defined]


def no_receipt(engine: Engine, g: Gate, user: uuid.UUID, request_key: str) -> None:
    assert receipts(engine, g, user, request_key) == []


def current(engine: Engine, g: Gate, character: uuid.UUID) -> dict[str, Any]:
    [row] = [r for r in revelations(engine, g, character) if r["kind"] == "campaign_current"]
    return row


def revoke_it(g: Gate, character: uuid.UUID, revelation: uuid.UUID) -> Callable[[Any], Any]:
    return lambda cn: revoke_character_revelation(
        cn,
        campaign_id=g.campaign_id,
        character_id=character,
        character_revelation_id=revelation,
        actor_membership_id=g.o1,
        reason="Race",
        reserve=lambda: False,
        plan=fixture_plan(cn, g.campaign_id),
    )


# --- M1 and M2: a member-target creation against the end of its target, both winners -----------


@pytest.mark.parametrize("winner", ["create", "end"])
def test_m1_m2_a_member_revelation_and_the_end_of_its_target(
    client_factory: Factory, postgres_engine: Engine, g: Gate, rev: Rev, winner: str
) -> None:
    c = rev.character_id
    create_key, end_key = key("m-create"), key("m-end")
    with LockRace(postgres_engine) as race:
        if winner == "create":
            # M1: the creation holds the target first; the end waits at it, then closes the row.
            held = race.hold(create_as(g, c, g.o1, "member", member=g.player))
            ended = post(client_factory, g.o2_user_id, end_url(g, g.player), {}, end_key)
            wait_waiting_on(postgres_engine, held.pid, ended)
            held.commit()
            response = ended.join()
            assert _status(response) == 200  # type: ignore[arg-type]
            row = revelations(postgres_engine, g, c)[0]
            assert row["end_reason"] == "target_membership_ended" and row["ended_at"] is not None
            [entry] = audit(postgres_engine, g, END)
            assert str(row["character_revelation_id"]) in entry["changed_fields"]
            one_receipt(postgres_engine, g, g.o2_user_id, end_key, ended)
            assert audit(postgres_engine, g, CREATE_COMMAND) == []  # the held create had no route
        else:
            # M2: the end holds the target first; the creation waits, then finds it ended.
            held = race.hold(end_of(g, g.player, g.o2))
            created = post(
                client_factory, g.o1_user_id, url(g, c), member_body(g.player), create_key
            )
            wait_waiting_on(postgres_engine, held.pid, created)
            held.commit()
            response = created.join()
            assert _status(response) == 409  # type: ignore[arg-type]
            assert error_code(response) == "revelation_target_not_active"
            assert revelations(postgres_engine, g, c) == []
            no_receipt(postgres_engine, g, g.o1_user_id, create_key)  # rolled back: the key is free
            assert audit(postgres_engine, g, CREATE_COMMAND) == []
        race.join_all()
    assert_roles(postgres_engine, g, ended=(g.player,))


# --- M3 and M3': the creator's own end, both winners ----------------------------------------------


@pytest.mark.parametrize("winner", ["create", "end"])
def test_m3_the_end_of_the_creator_against_the_creation(
    client_factory: Factory, postgres_engine: Engine, g: Gate, rev: Rev, winner: str
) -> None:
    c = rev.character_id
    create_key, end_key = key("m3-create"), key("m3-end")
    with LockRace(postgres_engine) as race:
        if winner == "create":
            # M3: the creation holds the creator's owner row; the end of the creator waits, then
            # commits; the committed revelation survives its creator (D9-f).
            held = race.hold(create_as(g, c, g.o2, "member", member=g.player))
            ended = post(client_factory, g.o1_user_id, end_url(g, g.o2), {}, end_key)
            wait_waiting_on(postgres_engine, held.pid, ended)
            held.commit()
            assert _status(ended.join()) == 200  # type: ignore[arg-type]
            row = revelations(postgres_engine, g, c)[0]
            assert row["ended_at"] is None and row["created_by_membership_id"] == g.o2
            assert len(audit(postgres_engine, g, END)) == 1
            one_receipt(postgres_engine, g, g.o1_user_id, end_key, ended)
        else:
            # M3': the end of the creator holds their role rows; the creation waits, then its
            # fresh authority check refuses it and nothing is written.
            held = race.hold(end_of(g, g.o2, g.o1))
            created = post(
                client_factory, g.o2_user_id, url(g, c), member_body(g.player), create_key
            )
            wait_waiting_on(postgres_engine, held.pid, created)
            held.commit()
            response = created.join()
            assert _status(response) == 403 and error_code(response) == "character_reveal_required"  # type: ignore[arg-type]
            assert revelations(postgres_engine, g, c) == []
            no_receipt(postgres_engine, g, g.o2_user_id, create_key)
            assert audit(postgres_engine, g, CREATE_COMMAND) == []
        race.join_all()
    assert_roles(postgres_engine, g, ended=(g.o2,))


# --- S1 and S2: the snapshot against the end of a member, both winners ----------------------------


@pytest.mark.parametrize("winner", ["create", "end"])
def test_s1_s2_the_snapshot_and_the_end_of_a_member(
    client_factory: Factory, postgres_engine: Engine, g: Gate, rev: Rev, winner: str
) -> None:
    c = rev.character_id
    create_key, end_key = key("s-create"), key("s-end")
    if winner == "create":
        # S1: the creation reaches the member first (held at its audit insert, past step 4a): the
        # snapshot holds them, and the end then marks that row removed.
        hold, first, pid = in_flight(
            postgres_engine, client_factory, g.o1_user_id, url(g, c),
            campaign_body("campaign_current"), create_key, "created",
        )  # fmt: skip
        ended = post(client_factory, g.o2_user_id, end_url(g, g.player), {}, end_key)
        wait_waiting_on(postgres_engine, pid, ended)
        hold.release()
        assert _status(first.join()) == 201 and _status(ended.join()) == 200  # type: ignore[arg-type]
        members = snapshot(
            postgres_engine, current(postgres_engine, g, c)["character_revelation_id"]
        )
        removed, reason = members[g.player]
        assert removed is not None and reason == "membership_ended"
        [entry] = audit(postgres_engine, g, END)
        assert "removed_character_revelation_member_ids" in entry["changed_fields"]
        one_receipt(postgres_engine, g, g.o1_user_id, create_key, first)
        one_receipt(postgres_engine, g, g.o2_user_id, end_key, ended)
    else:
        # S2: the end holds the member first: the snapshot is taken without them.
        with LockRace(postgres_engine) as race:
            held = race.hold(end_of(g, g.player, g.o2))
            created = post(
                client_factory, g.o1_user_id, url(g, c), campaign_body("campaign_current"),
                create_key,
            )  # fmt: skip
            wait_waiting_on(postgres_engine, held.pid, created)
            held.commit()
            assert _status(created.join()) == 201  # type: ignore[arg-type]
            race.join_all()
        members = snapshot(
            postgres_engine, current(postgres_engine, g, c)["character_revelation_id"]
        )
        assert g.player not in members and g.o2 in members
        one_receipt(postgres_engine, g, g.o1_user_id, create_key, created)
    assert len(audit(postgres_engine, g, CREATE_COMMAND)) == 1
    assert_roles(postgres_engine, g, ended=(g.player,))


# --- S3 and S4: the snapshot against recovery, both winners ---------------------------------------


@pytest.mark.parametrize("winner", ["create", "recovery"])
def test_s3_s4_the_snapshot_and_administrative_recovery_of_a_member(
    client_factory: Factory,
    postgres_engine: Engine,
    g: Gate,
    rev: Rev,
    stranded: uuid.UUID,
    winner: str,
) -> None:
    c = rev.character_id
    create_key = key("rec-create")
    body = campaign_body("campaign_current")
    if winner == "create":
        # S3: the creation holds the member (step 4a, held at its audit insert); recovery waits.
        hold, first, pid = in_flight(
            postgres_engine, client_factory, g.o1_user_id, url(g, c), body, create_key, "created"
        )
        creation = first
        with LockRace(postgres_engine) as race:
            recovery = race.start("recovery", _recover(g, stranded, g.player_user_id))
            wait_until(
                lambda: _blocked_by(postgres_engine, pid) >= 1 or recovery.done,
                "recovery to wait on the creation",
            )
            assert not recovery.done
            hold.release()
            assert _status(first.join()) == 201  # type: ignore[arg-type]
            race.join_all()
        assert recovery.error is None, recovery.error
    else:
        # S4: recovery holds the member and the campaign (NO KEY UPDATE) first; the creation waits.
        with LockRace(postgres_engine) as race:
            held = race.hold(_recover(g, stranded, g.player_user_id))
            created = post(client_factory, g.o1_user_id, url(g, c), body, create_key)
            creation = created
            wait_waiting_on(postgres_engine, held.pid, created)
            held.commit()
            assert _status(created.join()) == 201  # type: ignore[arg-type]
            race.join_all()
    row = current(postgres_engine, g, c)
    assert g.player in snapshot(postgres_engine, row["character_revelation_id"])
    assert _owner_role_live(postgres_engine, g.player)
    assert len(audit(postgres_engine, g, CREATE_COMMAND)) == 1
    one_receipt(postgres_engine, g, g.o1_user_id, create_key, creation)
    # Recovery added the built-in owner role to the player's own role.
    assert_roles(postgres_engine, g, roles={g.player: {g.player_role_id, g.owner_role_id}})


# --- S5 and S6: the snapshot against a relinquishing transfer, both winners -----------------------


@pytest.mark.parametrize("winner", ["create", "transfer"])
def test_s5_s6_the_snapshot_and_a_relinquishing_transfer_to_a_member(
    client_factory: Factory, postgres_engine: Engine, g: Gate, rev: Rev, winner: str
) -> None:
    c = rev.character_id
    create_key, transfer_key = key("tr-create"), key("tr-transfer")
    body = campaign_body("campaign_current")
    transfer_body: dict[str, object] = {
        "target_campaign_membership_id": str(g.player),
        "relinquish_own_ownership": True,
    }
    transfer_path = f"/campaigns/{g.campaign_id}/ownership-transfer"
    if winner == "create":
        # S5: the creation (by the other owner) holds the recipient first; the transfer waits.
        hold, first, pid = in_flight(
            postgres_engine, client_factory, g.o2_user_id, url(g, c), body, create_key, "created"
        )
        transfer = post(client_factory, g.o1_user_id, transfer_path, transfer_body, transfer_key)
        wait_waiting_on(postgres_engine, pid, transfer)
        hold.release()
        assert _status(first.join()) == 201 and _status(transfer.join()) == 200  # type: ignore[arg-type]
        creation = first
    else:
        # S6: the transfer holds the recipient and the campaign first; the creation waits at step 4a.
        with LockRace(postgres_engine) as race:
            held = race.hold(
                lambda cn: transfer_campaign_ownership(
                    cn,
                    campaign_id=g.campaign_id,
                    actor_membership_id=g.o1,
                    target_campaign_membership_id=g.player,
                    relinquish_own_ownership=True,
                )
            )
            created = post(client_factory, g.o2_user_id, url(g, c), body, create_key)
            creation = created
            wait_waiting_on(postgres_engine, held.pid, created)
            held.commit()
            assert _status(created.join()) == 201  # type: ignore[arg-type]
            race.join_all()
    row = current(postgres_engine, g, c)
    assert g.player in snapshot(postgres_engine, row["character_revelation_id"])
    assert _owner_role_live(postgres_engine, g.player) and not _owner_role_live(
        postgres_engine, g.o1
    )
    assert len(audit(postgres_engine, g, CREATE_COMMAND)) == 1
    one_receipt(postgres_engine, g, g.o2_user_id, create_key, creation)
    # The recipient holds the owner role as well as their own; the relinquisher lost theirs.
    assert_roles(
        postgres_engine,
        g,
        roles={g.player: {g.player_role_id, g.owner_role_id}, g.o1: set()},
    )
    if winner == "create":
        assert len(audit(postgres_engine, g, TRANSFER)) == 1  # the transfer route is not keyed


# --- S7: a resource grant to a member against the snapshot ---------------------------------------


def test_s7_a_resource_grant_to_a_member_waits_for_the_creation_and_both_commit(
    client_factory: Factory, postgres_engine: Engine, g: Gate, rev: Rev
) -> None:
    c = rev.character_id
    create_key, grant_key = key("g-create"), key("g-grant")
    hold, first, pid = in_flight(
        postgres_engine, client_factory, g.o1_user_id, url(g, c),
        campaign_body("campaign_current"), create_key, "created",
    )  # fmt: skip
    granted = post(
        client_factory,
        g.o2_user_id,
        f"/campaigns/{g.campaign_id}/resource-grants",
        {
            "capability_code": "character.view_summary",
            "effect": "allow",
            "grantee_campaign_membership_id": str(g.player),
            "character_id": str(c),
        },
        grant_key,
    )
    wait_waiting_on(postgres_engine, pid, granted)  # the grant needs the member FOR UPDATE
    hold.release()
    assert _status(first.join()) == 201 and _status(granted.join()) == 201  # type: ignore[arg-type]
    row = current(postgres_engine, g, c)
    assert g.player in snapshot(postgres_engine, row["character_revelation_id"])
    with postgres_engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT count(*) FROM security.resource_grants "
                     "WHERE grantee_campaign_membership_id = :m AND revoked_at IS NULL"),
                {"m": g.player},
            ).scalar_one()
            == 1
        )  # fmt: skip
    assert len(audit(postgres_engine, g, CREATE_COMMAND)) == 1
    assert len(audit(postgres_engine, g, GRANT)) == 1
    one_receipt(postgres_engine, g, g.o1_user_id, create_key, first)
    one_receipt(postgres_engine, g, g.o2_user_id, grant_key, granted)
    assert_roles(postgres_engine, g)  # a grant adds no role


# --- S8: adding a member against the snapshot, both winners ---------------------------------------


@pytest.mark.parametrize("winner", ["create", "add"])
def test_s8_a_member_being_added_is_after_the_cutoff_whoever_commits_first(
    client_factory: Factory, postgres_engine: Engine, g: Gate, rev: Rev, winner: str
) -> None:
    c = rev.character_id
    create_key, add_key = key("a-create"), key("a-add")
    create_body = campaign_body("campaign_current")
    add_path = f"/campaigns/{g.campaign_id}/memberships"
    add_body: dict[str, object] = {
        "user_id": str(g.new_user_id),
        "role_id": str(g.player_role_id),
    }
    if winner == "create":
        hold, first, pid = in_flight(
            postgres_engine, client_factory, g.o1_user_id, url(g, c), create_body, create_key,
            "created",
        )  # fmt: skip
        added = post(client_factory, g.o2_user_id, add_path, add_body, add_key)
        wait_waiting_on(postgres_engine, pid, added)  # the add needs the campaign FOR UPDATE
        hold.release()
        creation, addition = first.join(), added.join()
        creation_request, addition_request = first, added
    else:
        # The add holds the campaign FOR UPDATE (stopped at its audit insert, its membership and
        # role inserted but uncommitted); the creation waits at step 5, past its snapshot.
        hold, first, pid = in_flight(
            postgres_engine, client_factory, g.o2_user_id, add_path, add_body, add_key, "created"
        )
        created = post(client_factory, g.o1_user_id, url(g, c), create_body, create_key)
        wait_waiting_on(postgres_engine, pid, created)
        hold.release()
        creation, addition = created.join(), first.join()
        creation_request, addition_request = created, first
    assert _status(creation) == 201 and _status(addition) == 201  # type: ignore[arg-type]
    row = current(postgres_engine, g, c)
    members = snapshot(postgres_engine, row["character_revelation_id"])
    with postgres_engine.connect() as connection:
        new_membership = connection.execute(
            text("SELECT campaign_membership_id FROM security.campaign_memberships "
                 "WHERE campaign_id = :c AND user_id = :u"),
            {"c": g.campaign_id, "u": g.new_user_id},
        ).scalar_one()  # fmt: skip
    assert new_membership not in members  # committed after the cutoff (D9-a)
    assert g.player in members and g.o1 in members
    assert len(audit(postgres_engine, g, CREATE_COMMAND)) == 1
    assert len(audit(postgres_engine, g, ADD)) >= 1
    one_receipt(postgres_engine, g, g.o1_user_id, create_key, creation_request)
    one_receipt(postgres_engine, g, g.o2_user_id, add_key, addition_request)
    assert_roles(postgres_engine, g)
    assert live_role_ids(postgres_engine, new_membership) == [g.player_role_id]  # the role added


# --- AC1 to AC3: the caller's account ---------------------------------------------------------------


def test_ac1_adding_an_existing_member_waits_for_the_creation_then_is_refused(
    client_factory: Factory, postgres_engine: Engine, g: Gate, rev: Rev
) -> None:
    c = rev.character_id
    create_key, add_key = key("ac1-create"), key("ac1-add")
    with (
        postgres_engine.begin() as connection
    ):  # eligible to be added, so only the open membership refuses
        make_external_identity(
            connection,
            g.o1_user_id,
            issuer=LOCAL_AUTH_ISSUER,
            subject=f"ac1-{uuid.uuid4().hex[:8]}",
        )
    hold, first, pid = in_flight(
        postgres_engine, client_factory, g.o1_user_id, url(g, c),
        campaign_body("campaign_current"), create_key, "created",
    )  # fmt: skip
    added = post(
        client_factory,
        g.o2_user_id,
        f"/campaigns/{g.campaign_id}/memberships",
        {"user_id": str(g.o1_user_id), "role_id": str(g.player_role_id)},  # already a member
        add_key,
    )
    wait_waiting_on(postgres_engine, pid, added)  # the add needs the campaign FOR UPDATE
    hold.release()
    assert _status(first.join()) == 201
    response = added.join()
    assert _status(response) == 409, response.text  # type: ignore[attr-defined]  # ux_campaign_memberships_open
    assert len(revelations(postgres_engine, g, c)) == 1
    no_receipt(postgres_engine, g, g.o2_user_id, add_key)  # the refused add rolled back entirely
    assert audit(postgres_engine, g, ADD) == []
    with postgres_engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT count(*) FROM security.campaign_memberships "
                     "WHERE campaign_id = :c AND user_id = :u AND ended_at IS NULL"),
                {"c": g.campaign_id, "u": g.o1_user_id},
            ).scalar_one()
            == 1
        )  # fmt: skip
    assert live_role_ids(postgres_engine, g.o1) == [g.owner_role_id]  # A's roles are unchanged
    one_receipt(postgres_engine, g, g.o1_user_id, create_key, first)
    assert_roles(postgres_engine, g)  # nobody gained or lost a role


@pytest.mark.parametrize("winner", ["create", "deactivation"])
def test_ac2_ac3_account_deactivation_against_the_creation(
    client_factory: Factory,
    postgres_engine: Engine,
    g: Gate,
    rev: Rev,
    admin: uuid.UUID,
    winner: str,
) -> None:
    c = rev.character_id
    create_key = key("ac-create")
    body = campaign_body("campaign_current")
    assignments = role_rows(postgres_engine, g.o1)
    if winner == "deactivation":
        # AC2: the deactivation holds the caller's account first; the creation waits at step 5a and
        # is then refused at step 7 (the owner predicate needs an active account).
        with LockRace(postgres_engine) as race:
            held = race.hold(
                lambda cn: _disable_local_account_impl(
                    cn, admin_user_id=admin, target_user_id=g.o1_user_id
                )
            )
            created = post(client_factory, g.o1_user_id, url(g, c), body, create_key)
            wait_waiting_on(postgres_engine, held.pid, created)
            held.commit()
            response = created.join()
            assert _status(response) == 403 and error_code(response) == "character_reveal_required"  # type: ignore[arg-type]
            race.join_all()
        assert revelations(postgres_engine, g, c) == []
        no_receipt(postgres_engine, g, g.o1_user_id, create_key)
        assert audit(postgres_engine, g, CREATE_COMMAND) == []
        assert role_rows(postgres_engine, g.o1) == assignments  # the refusal changed none
    else:
        # AC3: the creation is past the account lock (held at its audit insert); the deactivation
        # waits for it, then commits.
        hold, first, pid = in_flight(
            postgres_engine, client_factory, g.o1_user_id, url(g, c), body, create_key, "created"
        )
        disabled = post(
            client_factory, admin, f"/admin/accounts/{g.o1_user_id}/disable", {}, key("ac3-disable")
        )
        wait_waiting_on(postgres_engine, pid, disabled)
        hold.release()
        assert _status(first.join()) == 201 and _status(disabled.join()) == 200  # type: ignore[arg-type]
        assert len(revelations(postgres_engine, g, c)) == 1
        assert len(audit(postgres_engine, g, CREATE_COMMAND)) == 1
        one_receipt(postgres_engine, g, g.o1_user_id, create_key, first)
    assert_roles(postgres_engine, g)  # deactivating an account changes no membership or role
    assert not _account_active(postgres_engine, g.o1_user_id)


# --- V1 and V2: a revoke against the end of the revelation's target, both winners ------------------


@pytest.mark.parametrize("winner", ["revoke", "end"])
def test_v1_v2_a_revoke_and_the_end_of_the_target(
    client_factory: Factory, postgres_engine: Engine, g: Gate, rev: Rev, winner: str
) -> None:
    c = rev.character_id
    revelation = make_revelation(client_factory, g, c, g.player)
    end_key, revoke_key = key("v-end"), key("v-revoke")
    with LockRace(postgres_engine) as race:
        if winner == "revoke":
            # V1: the revoke holds the campaign row and the revelation first; the end waits at the
            # campaign row, and its closure is then a no-op.
            held = race.hold(revoke_it(g, c, revelation))
            ended = post(client_factory, g.o2_user_id, end_url(g, g.player), {}, end_key)
            wait_waiting_on(postgres_engine, held.pid, ended)
            held.commit()
            assert _status(ended.join()) == 200  # type: ignore[arg-type]
            row = revelations(postgres_engine, g, c)[0]
            assert row["end_reason"] == "revoked" and row["ended_by_membership_id"] == g.o1
            [entry] = audit(postgres_engine, g, END)
            assert str(revelation) not in entry["changed_fields"]  # no closed revelation id
            one_receipt(postgres_engine, g, g.o2_user_id, end_key, ended)
        else:
            # V2: the end holds the campaign row first and closes the revelation; the revoke waits,
            # then reports `revoked: false` and writes nothing.
            held = race.hold(end_of(g, g.player, g.o2))
            revoked = post(
                client_factory, g.o1_user_id, url(g, c, f"/{revelation}/revoke"),
                {"reason": "Race"}, revoke_key,
            )  # fmt: skip
            wait_waiting_on(postgres_engine, held.pid, revoked)
            held.commit()
            response = revoked.join()
            assert _status(response) == 200 and response.json()["revoked"] is False  # type: ignore[attr-defined]
            row = revelations(postgres_engine, g, c)[0]
            assert row["end_reason"] == "target_membership_ended"
            assert audit(postgres_engine, g, REVOKE_COMMAND) == []
            one_receipt(postgres_engine, g, g.o1_user_id, revoke_key, revoked)
        race.join_all()
    assert_roles(postgres_engine, g, ended=(g.player,))


# --- the harness's own waits (the 2026-11 intermittent M2 failure) -------------------------------
#
# Under load the whole test process has been seen to stop for tens of seconds right after a hold was
# taken, and the 15 second wait then expired the instant the process resumed, before the request had
# run. These pin the behaviours that stand between that and a misleading failure.


def test_an_early_completion_is_reported_as_it_finished(
    client_factory: Factory, postgres_engine: Engine, g: Gate, rev: Rev
) -> None:
    """An early completion is a diagnosis (with the committed rows and the backends), not a timeout."""
    with LockRace(postgres_engine) as race:
        held = race.hold(lambda cn: cn.execute(text("SELECT 1")).all())  # holds no row at all
        created = post(
            client_factory, g.o1_user_id, url(g, rev.character_id), member_body(g.player),
            key("early"),
        )  # fmt: skip
        try:
            created.thread.join(15)
            with pytest.raises(AssertionError) as raised:
                wait_waiting_on(postgres_engine, held.pid, created, seconds=5.0)
            message = str(raised.value)
            assert "finished before it waited" in message and "201" in message
            assert "committed=" in message and "sessions=" in message
        finally:
            held.commit()
            created.thread.join(15)
        race.join_all()


def test_a_wait_that_expires_says_where_the_request_is(
    client_factory: Factory, postgres_engine: Engine, g: Gate, rev: Rev
) -> None:
    """The expiry reports the backends, what committed and the threads, and (the request being held
    by a different session than the one asked about) is a failure, not a pass."""
    with LockRace(postgres_engine) as race:
        held = race.hold(end_of(g, g.player, g.o2))
        created = post(
            client_factory, g.o1_user_id, url(g, rev.character_id), member_body(g.player),
            key("expire"),
        )  # fmt: skip
        try:
            with pytest.raises(AssertionError) as raised:
                wait_waiting_on(postgres_engine, held.pid + 1, created, seconds=1.0)
            message = str(raised.value)
            assert "never waited on backend" in message
            assert "sessions=" in message and "committed=" in message and "threads:" in message
            assert "request thread: True" in message
        finally:  # the held end is released and the request joined, whatever the assertions did
            held.commit()
            created.thread.join(15)
        created.join()
        race.join_all()


def _frozen_start(factory: Factory, seconds: float) -> Factory:
    """A client factory that does not return for `seconds`: the request thread stopped with the rest
    of a frozen process, before it builds its application and posts."""

    def make(user: uuid.UUID) -> TestClient:
        time.sleep(seconds)
        return factory(user)

    return make


def test_a_frozen_process_is_not_charged_to_the_wait(
    client_factory: Factory,
    postgres_engine: Engine,
    g: Gate,
    rev: Rev,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The failure as it happened, reproduced: the waiter is frozen for longer than the whole
    budget at its first look (as the whole process was), the request is held at its target the
    whole time, and the wait still observes it blocked instead of expiring when it resumes. The
    request is delayed by the same freeze (a stopped process stops both), so it reaches its lock only
    after the waiter is running again; without the compensation the wait has already expired."""
    real = _blocked_by
    frozen = []

    def freeze_once(engine: Engine, pid: int) -> int:
        if not frozen:
            frozen.append(True)
            time.sleep(1.6)  # longer than the budget below, and than STALL_SECONDS
        return real(engine, pid)

    monkeypatch.setattr(sys.modules[__name__], "_blocked_by", freeze_once)
    with LockRace(postgres_engine) as race:
        held = race.hold(end_of(g, g.player, g.o2))
        created = post(
            _frozen_start(client_factory, 1.6), g.o1_user_id, url(g, rev.character_id),
            member_body(g.player), key("frozen"),
        )  # fmt: skip
        try:
            wait_waiting_on(postgres_engine, held.pid, created, seconds=1.0)
            assert frozen
        finally:
            held.commit()
            created.thread.join(15)
        response = created.join()
        assert _status(response) == 409  # type: ignore[arg-type]
        assert error_code(response) == "revelation_target_not_active"
        race.join_all()

# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""R01 S5-B (invitation acceptance): a first acceptance locks the accepting user's membership before the campaign.

Lock sequence. Before: campaign `FOR SHARE`, then the user's latest membership `FOR UPDATE`. After: the
user's membership `FOR NO KEY UPDATE` (the open one, otherwise the latest ended one), then the campaign
`FOR SHARE`, then the same lookup again under the campaign lock; only the second result is acted on. This
is the membership-then-campaign order `end_campaign_membership`, the grants, the group add and (since the
recovery reorder) campaign recovery use. With recovery reordered and acceptance not, a member redeeming an
invitation to their own campaign while recovery promoted them deadlocked (SQLSTATE 40P01).

Evidence classes. Every scenario here is **command evidence** (both sides are `dnd_ai.commands.*` on their
own connections, parked with `LockRace` on a named statement) except the last two tests, which put a real
HTTP `POST /campaign-invitations/accept` on one side. Campaign recovery has no HTTP route, so it is always
the command.

Gates are checked, not assumed. `_blocked_on` waits until the second command's backend is waiting on a
lock whose holder list (`pg_blocking_pids`) names the gate's own backend, and returns the waiting statement
and both pids, which the test asserts against the statement it expects. A gate that merely paused its own
thread without holding the lock a test relies on would show up as the second command *not* waiting there.

Pause statements mean the same thing on the parent and after the change: `ACCEPT_CAMPAIGN_SHARE` is the
acceptance's campaign statement, and the pause named `after=ACCEPT_CAMPAIGN_SHARE` stops before the
acceptance's *next* membership statement, so acceptance then holds the campaign `FOR SHARE` (parent) or the
campaign and the membership (after).

Errors are reported as what they are: `_diagnose` names the underlying exception type and SQLSTATE of a
worker, so a deadlock (40P01) is told apart from a unique violation (23505) or anything else, and a test
that expects one specific refusal fails on every other error.
"""

import os
import re
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.exc import IntegrityError

from dnd_ai.api.app import create_app
from dnd_ai.api.auth import get_authenticated_user_id
from dnd_ai.api.deps import get_engine
from dnd_ai.api.local_auth import get_token_consumption_rate_limiter
from dnd_ai.commands.access_grants import create_resource_grant
from dnd_ai.commands.campaign_invitations import (
    InvitationNotAcceptableError,
    _hash_invitation_token,
    accept_campaign_invitation,
)
from dnd_ai.commands.invitation_onboarding import (
    begin_invitation_onboarding,
    complete_invitation_onboarding,
)
from dnd_ai.commands.memberships import add_campaign_member, end_campaign_membership
from dnd_ai.domain.authorization import install_authorization_guard
from dnd_ai.domain.rate_limit import RateLimiter
from tests.database.test_authoring_scope_recovery_locks import (  # noqa: F401 - fixtures by name
    CAMPAIGN_NKU,
    RECOVERY_MEMBERSHIP,
    _membership_of,
    _owner_roles,
    _recover,
    editor,
    stranded,
)
from tests.database.test_content_authoring_concurrency import (  # noqa: F401 - fixtures by name
    Fixture,
    fx,
)
from tests.database.test_r01_s5b_recovery_lock_order import (  # noqa: F401 - fixture by name
    END_ACTOR_LOCK,
    MEMBERSHIP_INSERT,
    newcomer,
)
from tests.factories import make_campaign_invitation, make_character, oidc_principal
from tests.http_race_support import StatementGate, run_in_thread
from tests.lock_race_support import WAIT_SECONDS, LockRace, Pause, Worker

pytestmark = pytest.mark.database

# The acceptance's campaign statement (`_require_campaign_accepts_members`).
ACCEPT_CAMPAIGN_SHARE = r"FROM campaign\.campaigns WHERE campaign_id = \S+ FOR SHARE"
# The acceptance's membership lookup, whichever lock mode and whichever ordering it names, so the same
# pause means the same thing on the parent (one lookup, `FOR UPDATE`) and after (two, `FOR NO KEY UPDATE`).
ACCEPT_MEMBERSHIP = (
    r"FROM security\.campaign_memberships WHERE campaign_id = \S+ AND user_id = \S+ "
    r"ORDER BY .* LIMIT 1 FOR (NO KEY )?UPDATE"
)
ACCEPT_MEMBERSHIP_NKU = r"ORDER BY \(ended_at IS NULL\) DESC, .* LIMIT 1 FOR NO KEY UPDATE"
# What a command's waiting statement looks like in `pg_stat_activity`.
WAIT_RECOVERY_MEMBERSHIP = (
    r"FROM security\.campaign_memberships WHERE campaign_id = \S+ AND user_id = \S+ "
    r"AND ended_at IS NULL FOR UPDATE"
)
WAIT_CAMPAIGN_NKU = r"FROM campaign\.campaigns WHERE campaign_id = \S+ FOR NO KEY UPDATE"
WAIT_CAMPAIGN_SHARE = r"FROM campaign\.campaigns WHERE campaign_id = \S+ FOR SHARE"
WAIT_END_MEMBERSHIP = (
    r"FROM security\.campaign_memberships WHERE campaign_membership_id = \S+ FOR UPDATE"
)
WAIT_GRANT_MEMBERSHIP = r"FROM security\.campaign_memberships cm .* FOR UPDATE OF cm"
GRANT_CAMPAIGN_LOCK = r"FROM campaign\.campaigns c JOIN .* FOR UPDATE OF c"
ADD_CAMPAIGN_LOCK = r"FROM campaign\.campaigns c JOIN .* FOR UPDATE OF c"

DEADLOCK = "40P01"
UNIQUE_VIOLATION = "23505"


# --- helpers: errors, gates, observation ----------------------------------------------------------------------


def _sqlstate(error: BaseException | None) -> str | None:
    """The SQLSTATE of the underlying driver error, found by following `orig` and the cause chain."""
    seen: set[int] = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        state = getattr(error, "sqlstate", None)
        if isinstance(state, str):
            return state
        error = getattr(error, "orig", None) or error.__cause__ or error.__context__
    return None


def _diagnose(worker: Worker) -> str:
    error = worker.error
    if error is None:
        return f"{worker.name}: ok (result={worker.result!r})"
    root: BaseException = getattr(error, "orig", None) or error
    return (
        f"{worker.name}: {type(error).__name__}"
        f" (underlying {type(root).__module__}.{type(root).__name__}, SQLSTATE {_sqlstate(error)}): "
        f"{str(root).splitlines()[0] if str(root) else ''}"
    )


def _ok(*workers: Worker) -> None:
    problems = [_diagnose(worker) for worker in workers if worker.error is not None]
    assert not problems, "; ".join(problems)


def _expect(worker: Worker, error_class: type[BaseException], sqlstate: str | None = None) -> None:
    """The worker failed with exactly this class (and SQLSTATE, when given); anything else, a deadlock
    included, is reported as what it was."""
    assert isinstance(worker.error, error_class), _diagnose(worker)
    if sqlstate is not None:
        assert _sqlstate(worker.error) == sqlstate, _diagnose(worker)


@dataclass
class Blocked:
    waiter_pid: int
    blockers: list[int]
    query: str


def _trace(line: str) -> None:
    path = os.environ.get("S5B_TRACE_FILE")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def _blocked_on(
    engine: Engine, holder_pid: int, *, waiting: str, label: str, waiter_pid: int | None = None
) -> Blocked:
    """Waits until a backend (the one named `waiter_pid`, or any) is waiting on a lock that
    `holder_pid` holds, directly per `pg_blocking_pids`, and returns it. The waiting statement must
    match `waiting`, so the test proves *where* the second command is queued, not merely that it is."""
    deadline = time.monotonic() + WAIT_SECONDS
    seen: list[tuple[int, list[int], str]] = []
    while time.monotonic() < deadline:
        with engine.connect() as connection:
            rows = connection.execute(
                text(r"""
                    SELECT pid, pg_blocking_pids(pid), regexp_replace(query, '\s+', ' ', 'g')
                    FROM pg_stat_activity
                    WHERE datname = current_database() AND wait_event_type = 'Lock'
                      AND pid <> pg_backend_pid()
                """)
            ).all()
        seen = [(int(r[0]), [int(p) for p in r[1]], str(r[2])) for r in rows]
        for pid, blockers, query in seen:
            if holder_pid in blockers and (waiter_pid is None or pid == waiter_pid):
                assert re.search(waiting, query), (
                    f"{label}: pid {pid} waits on pid {holder_pid} but at `{query}`, not `{waiting}`"
                )
                _trace(f"{label}: waiter pid {pid} blocked by {blockers}: {query}")
                return Blocked(pid, blockers, query)
        time.sleep(0.02)
    raise AssertionError(
        f"{label}: nothing was waiting on gate pid {holder_pid} for a lock; waiting sessions: {seen}"
    )


def _finishes_while_parked(
    race: LockRace, worker: Worker, *, why: str, seconds: float = 5.0
) -> None:
    """The worker must finish on its own while the other command stays parked. The budget is shorter than
    the pause's own timeout (`WAIT_SECONDS`), so a worker that queues behind the parked command fails here,
    naming the session it waits on, instead of finishing only when the pause times out."""
    deadline = time.monotonic() + seconds
    while not worker.done and time.monotonic() < deadline:
        time.sleep(0.02)
    assert worker.done, f"{why}; waiting sessions: {race.waiting_sessions()}"


def _gate_pid(pause: Pause) -> int:
    assert pause.pid, "the pause recorded no backend pid"
    return pause.pid


def _accept(token: str, user: uuid.UUID) -> Callable[[Connection], Any]:
    return lambda c: accept_campaign_invitation(c, token=token, accepting_user_id=user)


def _invite(fx: Fixture, *, by: uuid.UUID | None = None) -> str:
    token = f"s5b-acc-{uuid.uuid4().hex}"
    with fx.engine.begin() as setup:
        make_campaign_invitation(
            setup,
            fx.campaign_id,
            by or _membership_of(fx, fx.owner),
            token_hash=_hash_invitation_token(token),
        )
    return token


def _accepted(fx: Fixture, token: str) -> bool:
    return bool(
        fx.count(
            "SELECT count(*) FROM security.campaign_invitations "
            "WHERE invitation_token_hash = :h AND accepted_at IS NOT NULL",
            h=_hash_invitation_token(token),
        )
    )


def _memberships(fx: Fixture, user: uuid.UUID) -> list[tuple[uuid.UUID, bool, str]]:
    """Every membership of the user in the campaign: (id, open?, status code), oldest first."""
    with fx.engine.connect() as connection:
        rows = connection.execute(
            text("""
                SELECT cm.campaign_membership_id, cm.ended_at IS NULL, ms.code
                FROM security.campaign_memberships cm
                JOIN security.membership_statuses ms ON ms.membership_status_id = cm.membership_status_id
                WHERE cm.campaign_id = :c AND cm.user_id = :u
                ORDER BY cm.created_at, cm.campaign_membership_id
            """),
            {"c": fx.campaign_id, "u": user},
        ).all()
    return [(r[0], bool(r[1]), str(r[2])) for r in rows]


def _open(fx: Fixture, user: uuid.UUID) -> list[uuid.UUID]:
    return [m for m, is_open, _ in _memberships(fx, user) if is_open]


def _set_status(fx: Fixture, membership: uuid.UUID, code: str) -> None:
    with fx.engine.begin() as connection:
        connection.execute(
            text("""
                UPDATE security.campaign_memberships
                SET membership_status_id =
                    (SELECT membership_status_id FROM security.membership_statuses WHERE code = :code)
                WHERE campaign_membership_id = :m
            """),
            {"code": code, "m": membership},
        )


def _end_directly(fx: Fixture, user: uuid.UUID) -> uuid.UUID:
    membership = _membership_of(fx, user)
    with fx.engine.begin() as connection:
        end_campaign_membership(
            connection,
            campaign_membership_id=membership,
            campaign_id=fx.campaign_id,
            ended_by_membership_id=_membership_of(fx, fx.owner),
        )
    return membership


def _end_op(fx: Fixture, target: uuid.UUID) -> Callable[[Connection], Any]:
    by = _membership_of(fx, fx.owner)
    return lambda c: end_campaign_membership(
        c, campaign_membership_id=target, campaign_id=fx.campaign_id, ended_by_membership_id=by
    )


def _add_op(
    fx: Fixture, user: uuid.UUID, *, by: uuid.UUID | None = None
) -> Callable[[Connection], Any]:
    with fx.engine.connect() as connection:
        role = connection.execute(
            text("SELECT role_id FROM security.roles WHERE code = 'gm' AND campaign_id IS NULL")
        ).scalar_one()
    actor = by or _membership_of(fx, fx.owner)
    return lambda c: add_campaign_member(
        c, campaign_id=fx.campaign_id, user_id=user, role_id=role, added_by_membership_id=actor
    )


def _grant_op(fx: Fixture, member: uuid.UUID) -> Callable[[Connection], Any]:
    with fx.engine.begin() as setup:
        character = make_character(setup, fx.world_id, name="Acceptance Grant Target")
    return lambda c: create_resource_grant(
        c,
        campaign_id=fx.campaign_id,
        grantee_campaign_membership_id=member,
        grantee_access_group_id=None,
        capability_code="character.view_full",
        effect="allow",
        expected_world_id=fx.world_id,
        granted_by_membership_id=_membership_of(fx, fx.owner),
        character_id=character,
    )


# --- T1. acceptance against recovery, four membership states, both orderings -----------------------------------

STATES = ["active", "suspended", "ended", "absent"]
ORDERS = ["acceptance_first", "recovery_first"]


@dataclass
class Subject:
    user: uuid.UUID
    before: list[tuple[uuid.UUID, bool, str]]


def _subject(fx: Fixture, state: str, editor: uuid.UUID, newcomer: uuid.UUID) -> Subject:
    if state == "absent":
        return Subject(newcomer, [])
    if state == "ended":
        _end_directly(fx, editor)
    if state == "suspended":
        _set_status(fx, _membership_of(fx, editor), "suspended")
    return Subject(editor, _memberships(fx, editor))


@pytest.mark.parametrize("order", ORDERS)
@pytest.mark.parametrize("state", STATES)
def test_acceptance_and_recovery_serialize_in_both_orders(
    fx: Fixture,
    editor: uuid.UUID,
    stranded: uuid.UUID,
    newcomer: uuid.UUID,
    state: str,
    order: str,
) -> None:
    """T1. A user whose membership is `state` redeems an invitation to their own campaign while recovery
    promotes them.

    acceptance_first: acceptance is parked under the campaign `FOR SHARE` (and the membership `FOR NO KEY
    UPDATE` when there is one), before its second lookup. Recovery must queue at the membership when the
    member is open (active, suspended), and at the campaign otherwise (an ended or absent membership is
    not what recovery's first lookup looks for), holding nothing in both cases.
    Parent (open member): acceptance held only the campaign `FOR SHARE`; recovery locked the member's
    membership (free) and queued for the campaign `FOR NO KEY UPDATE`; released, acceptance asked for the
    membership recovery held: SQLSTATE 40P01. This test names the waiting statement, so on the parent it
    fails earlier, at "recovery waits at the campaign, not at the membership".

    recovery_first: recovery is parked under its locks (the membership and the campaign, or the campaign
    alone), before its second lookup. Acceptance must queue at its first membership lookup for an open
    member, and at the campaign for an ended or absent one; recovery commits first; acceptance then
    looks again and acts on what it finds.

    Both: no deadlock, one open membership, the owner role given, the invitation consumed, and the
    acceptance returned the one open membership."""
    subject = _subject(fx, state, editor, newcomer)
    user = subject.user
    token = _invite(fx)
    open_member = state in ("active", "suspended")
    with LockRace(fx.engine) as race:
        if order == "acceptance_first":
            pause = race.pause(
                thread_name="accept", pattern=ACCEPT_MEMBERSHIP, after=ACCEPT_CAMPAIGN_SHARE
            )
            accept = race.start("accept", _accept(token, user))
            pause.wait_reached(accept)
            recovery = race.start("recovery", _recover(fx, stranded, user))
            seen = _blocked_on(
                fx.engine,
                _gate_pid(pause),
                waiting=WAIT_RECOVERY_MEMBERSHIP if open_member else WAIT_CAMPAIGN_NKU,
                label=f"{state}/{order}: recovery",
                waiter_pid=recovery.pid,
            )
            assert seen.waiter_pid == recovery.pid
            pause.release()
        else:
            pause = race.pause(
                thread_name="recovery", pattern=RECOVERY_MEMBERSHIP, after=CAMPAIGN_NKU
            )
            recovery = race.start("recovery", _recover(fx, stranded, user))
            pause.wait_reached(recovery)
            accept = race.start("accept", _accept(token, user))
            seen = _blocked_on(
                fx.engine,
                _gate_pid(pause),
                waiting=ACCEPT_MEMBERSHIP_NKU if open_member else WAIT_CAMPAIGN_SHARE,
                label=f"{state}/{order}: acceptance",
                waiter_pid=accept.pid,
            )
            assert seen.waiter_pid == accept.pid
            pause.release()
        race.join_all()
    _ok(accept, recovery)
    memberships = _memberships(fx, user)
    assert len(_open(fx, user)) == 1, memberships
    assert accept.result.campaign_membership_id == _open(fx, user)[0]
    assert _owner_roles(fx, user) == 1
    assert _accepted(fx, token)
    if state == "ended":
        # recovery-first creates a new membership and acceptance then uses it; acceptance-first reopens
        # the ended one and recovery then promotes that same row.
        assert len(memberships) == (2 if order == "recovery_first" else 1), memberships
    elif state == "absent":
        assert len(memberships) == 1, memberships
    else:
        assert [m[0] for m in memberships] == [m[0] for m in subject.before]
        assert memberships[0][2] == "active"  # recovery flips a suspended membership either way


# --- T2. onboarding completion against recovery -----------------------------------------------------------------


def _onboarding_token(fx: Fixture, token: str) -> str:
    with fx.engine.begin() as connection:
        began = begin_invitation_onboarding(connection, invitation_token=token)
    return began.raw_onboarding_token


@pytest.mark.parametrize("order", ORDERS)
@pytest.mark.parametrize("state", ["active", "absent"])
def test_onboarding_completion_and_recovery_serialize_in_both_orders(
    fx: Fixture,
    editor: uuid.UUID,
    stranded: uuid.UUID,
    newcomer: uuid.UUID,
    state: str,
    order: str,
) -> None:
    """T2. `complete_invitation_onboarding` (the signed-in visitor's confirm step) reaches the same
    `_accept_locked_invitation` as the token route, after it has locked the onboarding session and the
    invitation. It must serialize with recovery of that user the same way, in both orderings."""
    user = editor if state == "active" else newcomer
    onboarding = _onboarding_token(fx, _invite(fx))
    open_member = state == "active"
    complete = lambda c: complete_invitation_onboarding(  # noqa: E731
        c, onboarding_token=onboarding, user_id=user
    )
    with LockRace(fx.engine) as race:
        if order == "acceptance_first":
            pause = race.pause(
                thread_name="complete", pattern=ACCEPT_MEMBERSHIP, after=ACCEPT_CAMPAIGN_SHARE
            )
            completing = race.start("complete", complete)
            pause.wait_reached(completing)
            recovery = race.start("recovery", _recover(fx, stranded, user))
            _blocked_on(
                fx.engine,
                _gate_pid(pause),
                waiting=WAIT_RECOVERY_MEMBERSHIP if open_member else WAIT_CAMPAIGN_NKU,
                label=f"complete/{state}/{order}: recovery",
                waiter_pid=recovery.pid,
            )
        else:
            pause = race.pause(
                thread_name="recovery", pattern=RECOVERY_MEMBERSHIP, after=CAMPAIGN_NKU
            )
            recovery = race.start("recovery", _recover(fx, stranded, user))
            pause.wait_reached(recovery)
            completing = race.start("complete", complete)
            _blocked_on(
                fx.engine,
                _gate_pid(pause),
                waiting=ACCEPT_MEMBERSHIP_NKU if open_member else WAIT_CAMPAIGN_SHARE,
                label=f"complete/{state}/{order}: acceptance",
                waiter_pid=completing.pid,
            )
        pause.release()
        race.join_all()
    _ok(completing, recovery)
    assert len(_open(fx, user)) == 1
    assert completing.result.campaign_membership_id == _open(fx, user)[0]
    assert _owner_roles(fx, user) == 1


# --- T3. archive refusal and complete rollback ----------------------------------------------------------------


def _archive_campaign_sql(connection: Connection, campaign_id: uuid.UUID) -> None:
    connection.execute(
        text("SELECT 1 FROM campaign.campaigns WHERE campaign_id = :c FOR UPDATE"),
        {"c": campaign_id},
    )
    connection.execute(
        text("""
            UPDATE campaign.campaigns
            SET lifecycle_status_id =
                (SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'archived')
            WHERE campaign_id = :c
        """),
        {"c": campaign_id},
    )


def _restore_campaign(fx: Fixture) -> None:
    with fx.engine.begin() as connection:
        connection.execute(
            text("""
                UPDATE campaign.campaigns
                SET lifecycle_status_id =
                    (SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'active')
                WHERE campaign_id = :c
            """),
            {"c": fx.campaign_id},
        )


@pytest.mark.parametrize("state", ["ended", "active"])
def test_an_archive_that_wins_the_campaign_wait_refuses_the_acceptance_and_rolls_it_back_whole(
    fx: Fixture, editor: uuid.UUID, state: str
) -> None:
    """T3. The acceptance has taken its first membership lock and queues for the campaign `FOR SHARE`
    behind an archive that holds the campaign `FOR UPDATE`. The archive commits; the acceptance is refused
    with the same non-disclosing `InvitationNotAcceptableError` as every other refusal (an `ended`
    membership is *not* reopened, an `active` one is untouched), its invitation is not consumed, and the
    membership row lock it held is gone (a competing `FOR UPDATE NOWAIT` on that row succeeds at once)."""
    target = _end_directly(fx, editor) if state == "ended" else _membership_of(fx, editor)
    token = _invite(fx)
    before = _memberships(fx, editor)
    try:
        with LockRace(fx.engine) as race:
            hold = race.hold(lambda c: _archive_campaign_sql(c, fx.campaign_id))
            accept = race.start("accept", _accept(token, editor))
            _blocked_on(
                fx.engine,
                hold.pid,
                waiting=WAIT_CAMPAIGN_SHARE,
                label=f"archive/{state}: acceptance",
                waiter_pid=accept.pid,
            )
            hold.commit()
            race.join_all()
        _expect(accept, InvitationNotAcceptableError)
        assert not _accepted(fx, token)
        assert _memberships(fx, editor) == before
        with fx.engine.begin() as connection:  # the early lock was released with the rollback
            connection.execute(text("SET LOCAL lock_timeout = '2s'"))
            connection.execute(
                text(
                    "SELECT 1 FROM security.campaign_memberships "
                    "WHERE campaign_membership_id = :m FOR UPDATE NOWAIT"
                ),
                {"m": target},
            ).all()
    finally:
        _restore_campaign(fx)


# --- T4. creation or reopening during the campaign wait: the second lookup is load-bearing ------------------------


def test_a_membership_created_while_acceptance_waits_for_the_campaign_is_found_by_the_second_lookup(
    fx: Fixture, newcomer: uuid.UUID
) -> None:
    """T4a. The first lookup finds nothing (the user is absent), so it locks nothing. An add of the same
    user holds the campaign `FOR UPDATE`, parked before inserting the membership; the acceptance queues
    for the campaign. The add inserts and commits. The acceptance then holds the campaign and looks again:
    it finds the new open membership and reuses it. Without the second lookup it would insert a second
    open membership and fail on `ux_campaign_memberships_open` (23505): mutation check 1 of this change."""
    token = _invite(fx)
    with LockRace(fx.engine) as race:
        pause = race.pause(thread_name="add", pattern=MEMBERSHIP_INSERT)
        add = race.start("add", _add_op(fx, newcomer))
        pause.wait_reached(add)
        accept = race.start("accept", _accept(token, newcomer))
        _blocked_on(
            fx.engine,
            _gate_pid(pause),
            waiting=WAIT_CAMPAIGN_SHARE,
            label="creation wait: acceptance",
            waiter_pid=accept.pid,
        )
        pause.release()
        race.join_all()
    _ok(add, accept)
    assert len(_memberships(fx, newcomer)) == 1
    assert accept.result.campaign_membership_id == add.result.campaign_membership_id
    assert _accepted(fx, token)


def test_an_open_membership_created_while_acceptance_holds_an_ended_one_is_used_not_the_ended_one(
    fx: Fixture, newcomer: uuid.UUID
) -> None:
    """T4b. The user's only membership has ended: the first lookup locks that ended row and the acceptance
    queues for the campaign behind an add that is creating a *new* open membership for the same user (the
    add never touches the ended row). Under the campaign lock the second lookup prefers the open row: the
    acceptance reuses it and the ended row stays ended. Acting on the first result (the ended row) would
    reopen it beside the new open one and fail on `ux_campaign_memberships_open`."""
    with fx.engine.begin() as connection:  # a member who has since left
        _add_op(fx, newcomer)(connection)
    ended = _end_directly(fx, newcomer)
    token = _invite(fx)
    with LockRace(fx.engine) as race:
        pause = race.pause(thread_name="add", pattern=MEMBERSHIP_INSERT)
        add = race.start("add", _add_op(fx, newcomer))
        pause.wait_reached(add)
        accept = race.start("accept", _accept(token, newcomer))
        _blocked_on(
            fx.engine,
            _gate_pid(pause),
            waiting=WAIT_CAMPAIGN_SHARE,
            label="ended-row wait: acceptance",
            waiter_pid=accept.pid,
        )
        pause.release()
        race.join_all()
    _ok(add, accept)
    new = add.result.campaign_membership_id
    assert accept.result.campaign_membership_id == new != ended
    assert _open(fx, newcomer) == [new]
    assert {m: o for m, o, _ in _memberships(fx, newcomer)}[ended] is False


# --- T5. an open membership with an older created_at than an ended row ------------------------------------------


def test_an_open_membership_older_than_an_ended_row_is_chosen_and_the_ended_row_is_not_reopened(
    fx: Fixture, editor: uuid.UUID
) -> None:
    """T5. The user has an open membership and an *ended* row with a later `created_at` (a state the
    schema permits). The lookup orders open rows first, so acceptance reuses the open membership as a
    no-op; ordering by `created_at` alone would pick the ended row and reopen it beside the open one
    (`ux_campaign_memberships_open`, 23505): mutation check 2 of this change."""
    open_row = _membership_of(fx, editor)
    with fx.engine.begin() as connection:
        ended_row = connection.execute(
            text("""
                INSERT INTO security.campaign_memberships
                    (campaign_id, user_id, membership_status_id, joined_at, ended_at, created_at)
                VALUES (:c, :u,
                        (SELECT membership_status_id FROM security.membership_statuses
                         WHERE code = 'departed'),
                        now() - interval '2 hours', now() - interval '1 hour', now() + interval '1 hour')
                RETURNING campaign_membership_id
            """),
            {"c": fx.campaign_id, "u": editor},
        ).scalar_one()
    token = _invite(fx)
    with fx.engine.begin() as connection:
        result = accept_campaign_invitation(connection, token=token, accepting_user_id=editor)
    assert result.campaign_membership_id == open_row
    assert _open(fx, editor) == [open_row]
    assert {m: o for m, o, _ in _memberships(fx, editor)}[ended_row] is False
    assert _accepted(fx, token)


# --- T6. acceptance against an end and against a resource grant to the same member ----------------------------------


@pytest.mark.parametrize("order", ORDERS)
def test_acceptance_and_an_end_of_the_same_member_serialize_in_both_orders(
    fx: Fixture, editor: uuid.UUID, order: str
) -> None:
    """T6a. The end takes the member's role rows, then the membership `FOR UPDATE`, then the campaign
    `FOR UPDATE`.

    acceptance_first: acceptance holds the membership `FOR NO KEY UPDATE` and the campaign `FOR SHARE`,
    parked before its second lookup; the end queues at the membership holding nothing. Acceptance
    commits (a no-op on the open member), then the end closes the membership. Parent: acceptance held
    only the campaign when the end locked the membership, and then wanted the membership the end held
    while the end wanted the campaign (40P01).

    end_first: the end holds the membership and is parked before its campaign lock; acceptance queues at
    its first lookup, holding nothing. The end commits; acceptance then sees the ended row, takes the
    campaign and reopens that row in place. Parent: acceptance held the campaign `FOR SHARE` while it
    waited for the membership: the end's campaign `FOR UPDATE` then deadlocked with it (40P01)."""
    member = _membership_of(fx, editor)
    token = _invite(fx)
    with LockRace(fx.engine) as race:
        if order == "acceptance_first":
            pause = race.pause(
                thread_name="accept", pattern=ACCEPT_MEMBERSHIP, after=ACCEPT_CAMPAIGN_SHARE
            )
            accept = race.start("accept", _accept(token, editor))
            pause.wait_reached(accept)
            end = race.start("end", _end_op(fx, member))
            _blocked_on(
                fx.engine,
                _gate_pid(pause),
                waiting=WAIT_END_MEMBERSHIP,
                label="end vs acceptance: end",
                waiter_pid=end.pid,
            )
        else:
            pause = race.pause(thread_name="end", pattern=END_ACTOR_LOCK)
            end = race.start("end", _end_op(fx, member))
            pause.wait_reached(end)
            accept = race.start("accept", _accept(token, editor))
            _blocked_on(
                fx.engine,
                _gate_pid(pause),
                waiting=ACCEPT_MEMBERSHIP_NKU,
                label="end vs acceptance: acceptance",
                waiter_pid=accept.pid,
            )
        pause.release()
        race.join_all()
    _ok(accept, end)
    assert accept.result.campaign_membership_id == member
    assert _accepted(fx, token)
    if order == "acceptance_first":
        assert _open(fx, editor) == []  # the end ran last
    else:
        assert _open(fx, editor) == [member]  # acceptance ran last and reopened the same row


@pytest.mark.parametrize("order", ORDERS)
def test_acceptance_and_a_resource_grant_to_the_same_member_serialize_in_both_orders(
    fx: Fixture, editor: uuid.UUID, order: str
) -> None:
    """T6b. A resource grant to the member locks the grantee's membership `FOR UPDATE OF cm` and then the
    campaign `FOR UPDATE OF c`: the same membership-then-campaign order as the end, so the same two
    orderings serialize (the later command queues at the membership holding nothing) and both commit."""
    member = _membership_of(fx, editor)
    token = _invite(fx)
    grant_op = _grant_op(fx, member)
    with LockRace(fx.engine) as race:
        if order == "acceptance_first":
            pause = race.pause(
                thread_name="accept", pattern=ACCEPT_MEMBERSHIP, after=ACCEPT_CAMPAIGN_SHARE
            )
            accept = race.start("accept", _accept(token, editor))
            pause.wait_reached(accept)
            grant = race.start("grant", grant_op)
            _blocked_on(
                fx.engine,
                _gate_pid(pause),
                waiting=WAIT_GRANT_MEMBERSHIP,
                label="grant vs acceptance: grant",
                waiter_pid=grant.pid,
            )
        else:
            pause = race.pause(thread_name="grant", pattern=GRANT_CAMPAIGN_LOCK)
            grant = race.start("grant", grant_op)
            pause.wait_reached(grant)
            accept = race.start("accept", _accept(token, editor))
            _blocked_on(
                fx.engine,
                _gate_pid(pause),
                waiting=ACCEPT_MEMBERSHIP_NKU,
                label="grant vs acceptance: acceptance",
                waiter_pid=accept.pid,
            )
        pause.release()
        race.join_all()
    _ok(accept, grant)
    assert accept.result.campaign_membership_id == member
    assert (
        fx.count(
            "SELECT count(*) FROM security.resource_grants WHERE grantee_campaign_membership_id = :m",
            m=member,
        )
        == 1
    )


# --- T7. the same actor: NO KEY UPDATE is compatible with a foreign key's KEY SHARE ----------------------------------


def test_a_member_accepting_an_invitation_does_not_block_an_add_the_same_member_performs(
    fx: Fixture, newcomer: uuid.UUID
) -> None:
    """T7. The owner accepts an invitation to their own campaign (an open member: the first lookup locks
    their membership `FOR NO KEY UPDATE`) and is parked before the campaign statement. In the meantime the
    same owner adds a member: the add takes the campaign `FOR UPDATE` and inserts a role row whose
    `granted_by_membership_id` foreign key takes `FOR KEY SHARE` on the owner's membership. That must not
    queue behind the acceptance's `FOR NO KEY UPDATE`, so the add finishes and commits while the
    acceptance is parked. (`FOR UPDATE` there would make the add wait at the membership while holding the
    campaign, and the released acceptance wait for the campaign while holding the membership: 40P01,
    mutation check 3 of this change.)"""
    owner_membership = _membership_of(fx, fx.owner)
    token = _invite(fx, by=owner_membership)
    with LockRace(fx.engine) as race:
        pause = race.pause(thread_name="accept", pattern=ACCEPT_CAMPAIGN_SHARE)
        accept = race.start("accept", _accept(token, fx.owner))
        pause.wait_reached(accept)
        add = race.start("add", _add_op(fx, newcomer, by=owner_membership))
        _finishes_while_parked(
            race, add, why="the add queued behind the acceptance's membership lock"
        )
        _ok(add)
        pause.release()
        race.join_all()
    _ok(accept, add)
    assert accept.result.campaign_membership_id == owner_membership
    assert len(_open(fx, newcomer)) == 1


# --- T8. two invitations accepted by the same user -----------------------------------------------------------------


def test_two_invitations_accepted_by_the_same_open_member_serialize_at_the_membership(
    fx: Fixture, editor: uuid.UUID
) -> None:
    """T8a. The same user redeems two different invitations to the campaign at once. The first holds the
    membership `FOR NO KEY UPDATE` (parked before the campaign statement); the second queues at its own
    first lookup, holding only its invitation row; both commit with the same membership."""
    first_token, second_token = _invite(fx), _invite(fx)
    with LockRace(fx.engine) as race:
        pause = race.pause(thread_name="first", pattern=ACCEPT_CAMPAIGN_SHARE)
        first = race.start("first", _accept(first_token, editor))
        pause.wait_reached(first)
        second = race.start("second", _accept(second_token, editor))
        _blocked_on(
            fx.engine,
            _gate_pid(pause),
            waiting=ACCEPT_MEMBERSHIP_NKU,
            label="two invitations: second",
            waiter_pid=second.pid,
        )
        pause.release()
        race.join_all()
    _ok(first, second)
    assert first.result.campaign_membership_id == second.result.campaign_membership_id
    assert _accepted(fx, first_token) and _accepted(fx, second_token)
    assert len(_memberships(fx, editor)) == 1


def test_two_invitations_for_an_absent_user_where_the_first_commits_before_the_second_looks_again(
    fx: Fixture, newcomer: uuid.UUID
) -> None:
    """T8b. Neither lookup finds a membership. The first is parked under the campaign `FOR SHARE`, before
    its second lookup; the second runs through (the campaign `FOR SHARE` is shared), inserts the
    membership and commits. The first then looks again, finds it open and reuses it: one membership, both
    invitations consumed (the second lookup is what prevents a second insert)."""
    first_token, second_token = _invite(fx), _invite(fx)
    with LockRace(fx.engine) as race:
        pause = race.pause(
            thread_name="first", pattern=ACCEPT_MEMBERSHIP, after=ACCEPT_CAMPAIGN_SHARE
        )
        first = race.start("first", _accept(first_token, newcomer))
        pause.wait_reached(first)
        second = race.start("second", _accept(second_token, newcomer))
        _finishes_while_parked(
            race, second, why="the second acceptance queued behind the first for an absent user"
        )
        _ok(second)
        pause.release()
        race.join_all()
    _ok(first, second)
    assert first.result.campaign_membership_id == second.result.campaign_membership_id
    assert len(_memberships(fx, newcomer)) == 1
    assert _accepted(fx, first_token) and _accepted(fx, second_token)


def test_two_acceptances_that_both_see_no_membership_until_the_insert_end_in_one_unique_violation(
    fx: Fixture, newcomer: uuid.UUID
) -> None:
    """T8c, a characterization of an unchanged limit (identical on the parent). Both acceptances for an
    absent user get through both lookups (neither row exists yet; the campaign `FOR SHARE` is shared) and
    race at the insert: the first to commit wins and the other fails on `ux_campaign_memberships_open`
    (23505, an `IntegrityError`; the route's 409), rolling back whole. No lock order can serialize two
    inserts of a row that does not exist yet, and the change adds no retry, advisory lock or savepoint, so
    this is recorded, not fixed."""
    first_token, second_token = _invite(fx), _invite(fx)
    with LockRace(fx.engine) as race:
        pause = race.pause(thread_name="first", pattern=MEMBERSHIP_INSERT)
        first = race.start("first", _accept(first_token, newcomer))
        pause.wait_reached(first)
        second = race.start("second", _accept(second_token, newcomer))
        _finishes_while_parked(race, second, why="the second acceptance's insert did not complete")
        _ok(second)
        pause.release()
        race.join_all()
    _ok(second)
    _expect(first, IntegrityError, UNIQUE_VIOLATION)
    assert len(_memberships(fx, newcomer)) == 1
    assert _accepted(fx, second_token) and not _accepted(fx, first_token)


# --- T9. one real HTTP acceptance against the recovery command -------------------------------------------------------


def _generous() -> RateLimiter:
    return RateLimiter(max_attempts=10_000, window=timedelta(minutes=15))


@pytest.fixture
def app_engine(fx: Fixture) -> Iterator[Engine]:
    """The application's engine: several connections, READ COMMITTED enforced and the real guard
    installed, as `get_engine` does."""
    engine = create_engine(
        fx.engine.url, pool_size=4, max_overflow=4, isolation_level="READ COMMITTED"
    )
    install_authorization_guard(engine)
    try:
        yield engine
    finally:
        engine.dispose()


def _http_accept(engine: Engine, user: uuid.UUID, token: str) -> Callable[[], Any]:
    def call() -> Any:
        app = create_app()
        app.dependency_overrides[get_engine] = lambda: engine
        app.dependency_overrides[get_authenticated_user_id] = lambda: oidc_principal(user)
        app.dependency_overrides[get_token_consumption_rate_limiter] = _generous
        with TestClient(app, raise_server_exceptions=False) as client:
            return client.post("/campaign-invitations/accept", json={"token": token})

    return call


def test_http_evidence_an_acceptance_request_holding_the_membership_makes_recovery_queue_and_both_commit(
    fx: Fixture, editor: uuid.UUID, stranded: uuid.UUID, app_engine: Engine
) -> None:
    """T9a, HTTP evidence. A real `POST /campaign-invitations/accept` by an open member is stopped before
    its campaign statement, holding the membership `FOR NO KEY UPDATE` (the gate's backend pid is
    recorded). Recovery of the same member, a command on its own connection, queues at the membership
    holding nothing. Released, the request answers 200 and recovery commits. On the parent the same pair
    deadlocked once the request held the campaign `FOR SHARE` and recovery held the membership (40P01;
    the former strict `xfail`); the request is gated on its first membership lookup there. The request is
    finished before the gate's listener is removed: removing it under a running request raised `deque
    mutated during iteration`."""
    token = _invite(fx)
    with StatementGate(app_engine, ACCEPT_CAMPAIGN_SHARE) as gate:
        request = run_in_thread("http-accept", _http_accept(app_engine, editor, token))
        try:
            gate.wait_reached()
            assert gate.pid is not None
            with LockRace(fx.engine) as race:
                recovery = race.start("recovery", _recover(fx, stranded, editor))
                _blocked_on(
                    fx.engine,
                    gate.pid,
                    waiting=WAIT_RECOVERY_MEMBERSHIP,
                    label="http acceptance: recovery",
                    waiter_pid=recovery.pid,
                )
                gate.release()
                race.join_all()
        finally:
            # whatever happened above, the request ends before the gate removes its listener
            gate.release()
            request.done.wait(WAIT_SECONDS)
        response = request.wait("the acceptance request finishes")
    assert response.status_code == 200, f"{response.status_code} {response.text}"
    _ok(recovery)
    assert response.json()["campaign_membership_id"] == str(_membership_of(fx, editor))
    assert _owner_roles(fx, editor) == 1
    assert _accepted(fx, token)


def test_http_evidence_recovery_holding_the_membership_makes_an_acceptance_request_queue_and_both_commit(
    fx: Fixture, editor: uuid.UUID, stranded: uuid.UUID, app_engine: Engine
) -> None:
    """T9b, HTTP evidence, the other ordering. Recovery holds the member's membership `FOR UPDATE` and the
    campaign `FOR NO KEY UPDATE` and is parked before its second lookup. The request queues at its first
    membership lookup, holding nothing but the invitation row. Released, recovery commits and the request
    answers 200."""
    token = _invite(fx)
    with LockRace(fx.engine) as race:
        pause = race.pause(thread_name="recovery", pattern=RECOVERY_MEMBERSHIP, after=CAMPAIGN_NKU)
        recovery = race.start("recovery", _recover(fx, stranded, editor))
        pause.wait_reached(recovery)
        request = run_in_thread("http-accept", _http_accept(app_engine, editor, token))
        _blocked_on(
            fx.engine,
            _gate_pid(pause),
            waiting=ACCEPT_MEMBERSHIP_NKU,
            label="http acceptance behind recovery: request",
        )
        pause.release()
        response = request.wait("the acceptance request finishes")
        race.join_all()
    assert response.status_code == 200, f"{response.status_code} {response.text}"
    _ok(recovery)
    assert response.json()["campaign_membership_id"] == str(_membership_of(fx, editor))
    assert _owner_roles(fx, editor) == 1

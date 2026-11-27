# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""P15-C11-S02 correction S02-R1: the control read judges authority, the clock and the history in ONE statement.

Plan section 3.1 ("Read": same authority, no locks, one snapshot). The finding: the read judged the caller's
assign-control authority in one statement, resolved the displayed clock in others, and read the history and its
statuses in yet another, all under `READ COMMITTED`, so a role revocation or a clock change committed between them
produced a response no single snapshot could give.

The contract these cases pin is **statement coherence**, not commit-time serialization:

- the response is what one statement saw: the authority decision, the displayed clock, the statuses and the history
  all come from the same MVCC snapshot (`test_r1_one_statement_carries_authority_clock_and_history`);
- a revocation committed **before** that statement runs refuses the read (`..._revoked_before_...`);
- a revocation committed **after** that statement ran does not make the already-read response wrong
  (`test_r1_control_a_revocation_after_the_statement_does_not_retract_the_response`, a baseline-passing control);
- a clock change committed before the statement is seen by both the display and the statuses together
  (`..._clock_moved_before_...`).

Synchronization is observable: the request is parked by a statement gate (`StatementGate`, before the statement runs)
or by an after-execute gate (the control), and the competing change is committed while it is parked. No sleeps.

Test-first record: at the correction baseline (`7339d3e`) the two race cases and the one-statement case fail
(the read returns 200 after the revocation; the display and the statuses disagree; four statements carry the read).
The control and the clock-display parity case pass at the baseline (guards).
"""

import re
import threading
import uuid
from typing import Any

import pytest
from sqlalchemy import Engine, event, text

from tests.database.test_control_assignment_commands import (  # noqa: F401 - fixtures used by name
    Env,
    Factory,
    Person,
    _person,
    _tidy,
    assign_path,
    env,
    get,
    seed,
    set_clock,
)
from tests.database.test_r01_s2_profile_routes import (  # noqa: F401 - fixtures used by name
    ROW_LOCK_RE,
    pooled,
    pooled_factory,
)
from tests.database.test_r01_s3_authoring_routes import (  # noqa: F401 - fixtures used by name
    World,
    code,
    error_of,
    w,
)
from tests.database.test_r01_s5e2_membership_routes import (  # noqa: F401 - fixtures used by name
    Scene,
    m,
    s,
)
from tests.factories import (
    make_campaign,
    make_campaign_membership,
    make_membership_role,
    make_timeline,
    make_timeline_clock,
    make_user,
    make_world_time,
    system_role_id,
)
from tests.http_race_support import StatementGate, run_in_thread

pytestmark = pytest.mark.database

#: The statement that reads the history (its alias `h` is the read's own); before the correction it is a statement of
#: its own, after it the one statement of the read.
HISTORY = r"FROM security\.membership_character_relationships h\b"
#: The assign-control authority component of the authority statement.
AUTHORITY = r"\bac_live AS\b"
SECRET = "R1 revocation reason that only a holder may read"


def gm_with_view(sc: Scene) -> tuple[Person, uuid.UUID]:
    """A member holding the built-in `gm` role and, beside it, a player role, so that revoking the `gm` row leaves the
    route requirement (`campaign.view`) passing and the refusal under test is the operation's own. Returns the person
    and the `gm` role row."""
    with sc.w.engine.begin() as c:
        person = _person(c, sc, "R1 GM", sc.player)
        gm_row = make_membership_role(c, person.membership, system_role_id(c, "gm"))
    return person, gm_row


def revoke_role_row(sc: Scene, row: uuid.UUID) -> None:
    with sc.w.engine.begin() as c:
        c.execute(text("SET LOCAL lock_timeout = '5s'"))
        moved = c.execute(
            text(
                "UPDATE security.membership_roles SET revoked_at = now() "
                "WHERE membership_role_id = :r AND revoked_at IS NULL"
            ),
            {"r": row},
        ).rowcount
        assert moved == 1


def move_clock(sc: Scene, e: Env, to: uuid.UUID) -> None:
    with sc.w.engine.begin() as c:
        c.execute(text("SET LOCAL lock_timeout = '5s'"))
        c.execute(
            text("DELETE FROM campaign.timeline_clocks WHERE timeline_id = :t"),
            {"t": e.timeline_id},
        )
        make_timeline_clock(c, e.timeline_id, to)


def display_of(sc: Scene, world_time: uuid.UUID) -> str:
    from dnd_ai.queries.campaign_clock import clock_display

    with sc.w.engine.connect() as c:
        return clock_display(c, world_time)


class AfterGate:
    """Parks the request right AFTER the first statement matching `pattern` has executed (its snapshot taken and its
    result read), until the test releases it. Observable: `reached` is set by the request's own thread."""

    def __init__(self, engine: Engine, pattern: str) -> None:
        self.engine = engine
        self.pattern = re.compile(pattern)
        self.reached = threading.Event()
        self.resume = threading.Event()
        self._fired = False

    def _hook(self, _conn: Any, _cursor: Any, statement: Any, *_: Any) -> None:
        if self._fired or not self.pattern.search(" ".join(str(statement).split())):
            return
        self._fired = True
        self.reached.set()
        if not self.resume.wait(30):
            raise AssertionError("the after-gate was never released")

    def __enter__(self) -> "AfterGate":
        event.listen(self.engine, "after_cursor_execute", self._hook)
        return self

    def __exit__(self, *_: Any) -> None:
        self.resume.set()
        event.remove(self.engine, "after_cursor_execute", self._hook)


# --- the race cases (fail at the baseline) ---------------------------------------------------------------------------


def test_r1_a_role_revoked_before_the_statement_that_reads_the_history_refuses_the_read(
    s: Scene, env: Env, pooled: Engine, pooled_factory: Factory
) -> None:
    """The request is parked before the statement that reads the history; the caller's `gm` row is revoked and
    committed; the parked statement then runs. Its snapshot no longer holds the authority, so the read is the fixed
    403 and discloses no history (before the correction: 200 with the history, judged by an earlier statement)."""
    gm, gm_row = gm_with_view(s)
    seed(
        s,
        env.p1,
        env.character,
        "co_controller",
        "ongoing",
        revoked=True,
        revocation_reason=SECRET,
    )
    with StatementGate(pooled, HISTORY, strict=True) as gate:
        request = gate.track(
            run_in_thread(
                "read", lambda: get(pooled_factory, gm.user, assign_path(s, env.character))
            )
        )
        gate.wait_reached()
        revoke_role_row(s, gm_row)
        gate.release()
        response = request.wait("the read finishes")
    assert code(response) == 403, response.text
    assert error_of(response) == "character_assign_control_required"
    assert SECRET not in response.text


def test_r1_a_clock_moved_before_the_statement_that_reads_the_history_is_seen_by_display_and_status(
    s: Scene, env: Env, pooled: Engine, pooled_factory: Factory
) -> None:
    """A dated co-controller `[t10, t20)` with the clock at t10 (in effect). The request is parked before the statement
    that reads the history; the clock is moved to t20 and committed. The displayed clock and every status must come from
    one snapshot: either (t10, in effect, listed as co-controller) or (t20, ended, not listed). Before the correction
    the display was resolved by earlier statements (t10) and the statuses by the later one (ended)."""
    dated = seed(
        s, env.p2, env.character, "co_controller", "dated", from_time=env.t10, to_time=env.t20
    )
    set_clock(s, env, env.t10)
    at_10, at_20 = display_of(s, env.t10), display_of(s, env.t20)
    with StatementGate(pooled, HISTORY, strict=True) as gate:
        request = gate.track(
            run_in_thread(
                "read", lambda: get(pooled_factory, env.owner.user, assign_path(s, env.character))
            )
        )
        gate.wait_reached()
        move_clock(s, env, env.t20)
        gate.release()
        response = request.wait("the read finishes")
    assert code(response) == 200, response.text
    data = response.json()
    status = {a["control_assignment_id"]: a["status"] for a in data["assignments"]}[str(dated)]
    listed = str(env.p2.membership) in {c["campaign_membership_id"] for c in data["co_controllers"]}
    observed = (data["clock"]["display"], status, listed)
    assert observed in {(at_10, "in_effect", True), (at_20, "ended", False)}, observed
    # the parked statement ran after the commit, so it is the later snapshot
    assert observed == (at_20, "ended", False), observed


# --- the baseline-passing control --------------------------------------------------------------------------------


def test_r1_control_a_revocation_after_the_statement_does_not_retract_the_response(
    s: Scene, env: Env, pooled: Engine, pooled_factory: Factory
) -> None:
    """*control*: the request is parked right AFTER the statement that read the history (its snapshot taken); the
    caller's `gm` row is then revoked and committed. The response is what that statement saw: 200 with the history.
    The contract is statement coherence, not commit-time serialization, so this is not a failure. Passes before and
    after the correction (ongoing rows only, so no later display statement exists before the correction either)."""
    gm, gm_row = gm_with_view(s)
    seed(s, env.p1, env.character, "co_controller", "ongoing")
    with AfterGate(pooled, HISTORY) as gate:
        request = run_in_thread(
            "read", lambda: get(pooled_factory, gm.user, assign_path(s, env.character))
        )
        assert gate.reached.wait(30), "the read never reached its history statement"
        revoke_role_row(s, gm_row)
        gate.resume.set()
        response = request.wait("the read finishes")
    assert code(response) == 200, response.text
    assert {c["campaign_membership_id"] for c in response.json()["co_controllers"]} == {
        str(env.p1.membership)
    }


def test_r1_control_a_clock_moved_after_the_statement_leaves_display_and_status_coherent(
    s: Scene, env: Env, pooled: Engine, pooled_factory: Factory
) -> None:
    """*control*: the request is parked right AFTER the statement that read the history; the clock is then moved from
    t10 to t20 and committed. The response is that statement's snapshot, display and status together: (t10, in
    effect). A display read by any later statement would pair t20 with "in effect". Passes before the correction (the
    display was read before the history) and after it (one statement)."""
    dated = seed(
        s, env.p2, env.character, "co_controller", "dated", from_time=env.t10, to_time=env.t20
    )
    set_clock(s, env, env.t10)
    at_10 = display_of(s, env.t10)
    with AfterGate(pooled, HISTORY) as gate:
        request = run_in_thread(
            "read", lambda: get(pooled_factory, env.owner.user, assign_path(s, env.character))
        )
        assert gate.reached.wait(30), "the read never reached its history statement"
        move_clock(s, env, env.t20)
        gate.resume.set()
        response = request.wait("the read finishes")
    assert code(response) == 200, response.text
    data = response.json()
    status = {a["control_assignment_id"]: a["status"] for a in data["assignments"]}[str(dated)]
    assert (data["clock"]["display"], status) == (at_10, "in_effect")


# --- the one-statement contract (replaces F28's boundary argument) ---------------------------------------------


def test_r1_one_statement_carries_authority_clock_and_history(
    s: Scene, env: Env, pooled: Engine, pooled_factory: Factory
) -> None:
    """Every statement the read runs after the route's own campaign gate: exactly one carries the assign-control
    authority, and it is the same statement that reads the effective clock (the `campaign_clock` CTE the status test
    shares with the resolver), the clock's display row (`core.world_times`) and the history; nothing runs after it;
    no statement takes a row lock. (F28's boundary cases pin the statuses; they never showed the read was one
    snapshot.)"""
    seed(s, env.p2, env.character, "co_controller", "dated", from_time=env.t10, to_time=env.t20)
    seed(s, env.p1, env.character, "primary_controller", "ongoing")
    set_clock(s, env, env.t10)
    seen: list[str] = []

    def record(_c: Any, _cur: Any, statement: Any, *_: Any) -> None:
        seen.append(" ".join(str(statement).split()))

    # Nothing else uses the application engine during the call (the fixtures write through their own engine), so
    # every recorded statement is the request's: the route's campaign gate first, then the read itself.
    event.listen(pooled, "before_cursor_execute", record)
    try:
        response = get(pooled_factory, env.owner.user, assign_path(s, env.character))
    finally:
        event.remove(pooled, "before_cursor_execute", record)
    assert code(response) == 200, response.text
    assert seen, "no statement was recorded on the application engine"
    carrying = [i for i, sql in enumerate(seen) if re.search(AUTHORITY, sql)]
    assert len(carrying) == 1, [sql[:120] for sql in seen]
    one = seen[carrying[0]]
    assert re.search(HISTORY, one), "the authority statement does not read the history"
    assert "campaign_clock AS" in one and "core.world_times" in one
    assert carrying[0] == len(seen) - 1, [sql[:120] for sql in seen[carrying[0] + 1 :]]
    assert [sql[:120] for sql in seen if ROW_LOCK_RE.search(sql)] == []


# --- the displayed clock across clock shapes (guard) -------------------------------------------------------------


@pytest.mark.parametrize(
    "shape",
    [
        "root_own_clock",
        "root_no_clock",
        "branch_inherits_parent_before_branch_point",
        "branch_bounded_at_branch_point",
        "branch_with_unset_parent",
        "branch_own_clock_wins",
    ],
)
def test_r1_the_displayed_clock_equals_the_effective_clock_resolver(
    s: Scene, env: Env, pooled_factory: Factory, shape: str
) -> None:
    """*guard*: the read's displayed clock equals `resolve_membership_clock` (the Python effective-clock resolver,
    with the bounded branch fallback) for every clock shape, on a campaign of its own timeline."""
    from dnd_ai.queries.party_membership_period import resolve_membership_clock

    with s.w.engine.begin() as c:
        wt = {key: make_world_time(c, s.w.world_id, key) for key in (5, 50, 100, 150)}
        root = make_timeline(c, s.w.world_id, f"R1 root {shape}")
        timeline = root
        if shape == "root_own_clock":
            make_timeline_clock(c, root, wt[50])
        elif shape != "root_no_clock":
            parent_key = {
                "branch_inherits_parent_before_branch_point": 50,
                "branch_bounded_at_branch_point": 150,
                "branch_with_unset_parent": None,
                "branch_own_clock_wins": 150,
            }[shape]
            if parent_key is not None:
                make_timeline_clock(c, root, wt[parent_key])
            timeline = make_timeline(
                c,
                s.w.world_id,
                f"R1 branch {shape}",
                parent_timeline_id=root,
                branch_world_time_id=wt[100],
            )
            if shape == "branch_own_clock_wins":
                make_timeline_clock(c, timeline, wt[5])
        campaign = make_campaign(c, timeline, f"R1 campaign {shape}")
        owner = make_user(c, f"R1 owner {shape}")
        membership = make_campaign_membership(c, campaign, owner)
        make_membership_role(c, membership, s.owner)
        expected = resolve_membership_clock(c, timeline_id=timeline)
    response = get(
        pooled_factory,
        owner,
        f"/campaigns/{campaign}/characters/{env.character}/control-assignments",
    )
    assert code(response) == 200, response.text
    clock = response.json()["clock"]
    assert (clock["set"], clock["display"]) == (expected.is_set, expected.display), shape

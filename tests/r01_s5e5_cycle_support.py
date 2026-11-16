"""Support for the group/role three-party cycle tests (R01 S5-E5 correction, NF-1; correction design section 5).

The three parties, all through the real routes over real connections:

* **X**: the S5-E4 create grant to an access group (group grantee), by an owner X;
* **C**: revelation creation for the same group, by an owner C (authority role rows `FOR SHARE`, then the group `FOR KEY SHARE`);
* **V**: the S5-E2 role revoke of **X's** role row, by C (one ordered statement `FOR UPDATE` over C's rows and X's row).

Nothing here assumes how many sessions are queued. A party is started only after the previous one is **observed** waiting
(`observe_waiter`): on which backend (`pg_blocking_pids`) and on which statement. Row ownership is proven by `NOWAIT` probes from
an independent connection. Every failure is reported with its SQLSTATE; the deadlock counter is read before and after.
"""

import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Engine

from dnd_ai.commands.character_public_profile import (
    release_character_public_profile,
    save_character_public_profile_draft,
)
from tests.database.test_r01_s3_authoring_routes import code, error_of
from tests.database.test_r01_s5e2_lock_order import (
    PATIENCE,
    ROLE_ROW,
    Cast,
    NthGate,
    Pool,
    cast_two,
    deadlocks_now,
    finish,
    held_mode,
    post,
    rows,
    settled_deadlock_delta,
)
from tests.factories import make_access_group, make_character
from tests.http_race_support import activity_report, run_in_thread
from tests.r01_support import fixture_plan

GROUP_KEY_SHARE = r"FROM security\.access_groups WHERE .* FOR KEY SHARE"
ROLE_FOR_SHARE = r"FROM security\.membership_roles WHERE .* FOR SHARE$"
ROLE_FOR_UPDATE = r"FROM security\.membership_roles WHERE .* FOR UPDATE"
MEMBERSHIP_FOR_SHARE = r"FROM security\.campaign_memberships WHERE .* FOR SHARE$"
#: Revelation creation's authority statement (`resolve_reveal_authority(lock="share")`): a joined `FOR SHARE OF mr` (the locking clause lies past `pg_stat_activity`'s 1024-character cut, so the pattern names the join).
AUTHORITY_ROLES_SHARE = r"FROM security\.membership_roles mr JOIN security\.roles r"
V_DELEGATIONS = (
    r"FROM security\.character_reveal_delegations WHERE security\.character_reveal_delegations\."
    r"gm_membership_role_id = "
)
WAIT_SECONDS = 30.0
GROUP_LOCK_STATEMENT = r"FROM security\.access_groups WHERE .* FOR UPDATE"


class AfterStatementGate(NthGate):
    """Parks a request at the **first statement that follows** the statement matching `after`, on the same backend, whatever that
    next statement is. It names a *logical* point (right after the group lock) instead of a statement text, so one schedule is
    meaningful for both lock orders: with the actor's role rows first the next statement is the actor's membership lock (the
    request then holds its role rows `FOR SHARE` and the group); with the group first (the mutation) it is the role-row lock (the
    request holds only the group)."""

    def __init__(self, engine: Engine, after: str) -> None:
        super().__init__(
            engine, r"^\b$", 1
        )  # the base pattern never matches; `_hook` below decides
        self.after = re.compile(after)
        self._armed_pid: int | None = None

    def _hook(self, conn: Any, cursor: Any, statement: Any, *rest: Any) -> None:
        if self._fired:
            return
        flat = " ".join(str(statement).split())
        pid = conn.connection.driver_connection.info.backend_pid
        if self._armed_pid is None:
            if self.after.search(flat):
                self._armed_pid = pid
            return
        if pid != self._armed_pid:
            return
        self._fired = True
        self.pid = pid
        self.matched = flat[:150]
        self.reached_at = time.monotonic()
        self.reached.set()
        self.resume.wait(PATIENCE)


@dataclass
class Waiter:
    pid: int
    blockers: list[int]
    query: str


def observe_waiter(
    admin: Engine,
    *,
    pattern: str,
    exclude: set[int],
    blockers_are: set[int] | None = None,
    blockers_within: set[int] | None = None,
    what: str,
) -> Waiter:
    """Wait (bounded) until a session **not already accounted for** is waiting on a lock with a statement matching `pattern` and
    with exactly the expected direct blockers (`blockers_are`) or a non-empty subset of `blockers_within`. A wait that never
    appears raises with the backend activity, so an incompatible gate is reported as a setup failure, never as a product outcome."""
    deadline = time.monotonic() + WAIT_SECONDS
    regex = re.compile(pattern)
    while time.monotonic() < deadline:
        for row in rows(
            admin,
            r"SELECT pid, pg_blocking_pids(pid) AS blockers, regexp_replace(query, '\s+', ' ', 'g') AS query "
            "FROM pg_stat_activity WHERE datname = current_database() AND wait_event_type = 'Lock'",
        ):
            if row["pid"] in exclude or not regex.search(row["query"]):
                continue
            blockers = set(row["blockers"])
            if blockers_are is not None and blockers != blockers_are:
                continue
            if blockers_within is not None and not (blockers and blockers <= blockers_within):
                continue
            return Waiter(row["pid"], sorted(blockers), row["query"])
        time.sleep(0.02)
    raise AssertionError(
        f"SETUP: {what}: no session matching {pattern!r} waited on blockers "
        f"{blockers_are or blockers_within} within {WAIT_SECONDS}s\n{activity_report(admin)}"
    )


@dataclass
class Scene:
    cast: Cast
    group: uuid.UUID
    character: uuid.UUID
    order: str
    r_x: uuid.UUID = field(init=False)
    r_c: uuid.UUID = field(init=False)

    def __post_init__(self) -> None:
        self.r_x, self.r_c = self.cast.ids["r_x"], self.cast.ids["r_c"]


def build_scene(
    w: Any, owner_user: uuid.UUID, owner_membership: uuid.UUID, order: str, label: str
) -> Scene:
    """Two owners X and C with fixed role-row id orders, a group, and a character **with a released public profile** (so a
    successful revelation is a 201 and not a masking 409)."""
    low_x = order == "x_row_below_c_rows"
    cast = cast_two(
        w,
        label=label,
        roles={
            "r_x": ("x", "campaign_owner", "low:a1" if low_x else "high:a1"),
            "r_c": ("c", "campaign_owner", "high:a1" if low_x else "low:a1"),
        },
    )
    with w.engine.begin() as c:
        group = make_access_group(c, w.campaign_id, name=f"{label} group")
        character = make_character(c, w.world_id, name=f"{label} character")
        save_character_public_profile_draft(
            c,
            campaign_id=w.campaign_id,
            character_id=character,
            actor_user_id=owner_user,
            expected_row_version=None,
            fields={"public_appearance": "A released face"},
            plan=fixture_plan(c, w.campaign_id),
        )
    with w.engine.begin() as c:
        release_character_public_profile(
            c,
            campaign_id=w.campaign_id,
            character_id=character,
            actor_membership_id=owner_membership,
            expected_draft_row_version=1,
            release_note=None,
            plan=fixture_plan(c, w.campaign_id),
        )
    return Scene(cast, group, character, order)


def x_request(w: Any, pool: Pool, sc: Scene) -> Any:
    return post(
        pool,
        sc.cast.x_user,
        f"{w.base}/resource-grants",
        {
            "capability_code": "character.view_summary",
            "grantee_access_group_id": str(sc.group),
            "character_id": str(sc.character),
        },
    )


def c_request(w: Any, pool: Pool, sc: Scene) -> Any:
    return post(
        pool,
        sc.cast.c_user,
        f"{w.base}/characters/{sc.character}/revelations",
        {
            "audience_kind": "access_group",
            "target_access_group_id": str(sc.group),
            "reason": "cycle",
        },
    )


def v_request(w: Any, pool: Pool, sc: Scene) -> Any:
    return post(pool, sc.cast.c_user, f"{w.base}/memberships/roles/{sc.r_x}/revoke", {})


@dataclass
class Result:
    statuses: dict[str, tuple[int, str | None]]
    ended: dict[str, float]
    failures: list[tuple[str | None, str]]
    delta: int
    arrivals: dict[str, Waiter]
    modes: dict[str, str]
    state: dict[str, Any]
    pids: dict[str, int] = field(default_factory=dict)

    def summary(self) -> str:
        return (
            f"statuses={self.statuses} failures={self.failures} delta={self.delta} "
            f"arrivals={ {k: (v.blockers, v.query[:110]) for k, v in self.arrivals.items()} } modes={self.modes} state={self.state}"
        )


def durable_state(w: Any, sc: Scene) -> dict[str, Any]:
    q = lambda sql, **p: rows(w.engine, sql, **p)[0]["n"]  # noqa: E731
    return {
        "group_grants": q(
            "SELECT count(*) AS n FROM security.resource_grants WHERE grantee_access_group_id = :g",
            g=sc.group,
        ),
        "revelations": q(
            "SELECT count(*) AS n FROM security.character_revelations WHERE target_access_group_id = :g",
            g=sc.group,
        ),
        "x_row_revoked": bool(
            q(
                "SELECT count(*) AS n FROM security.membership_roles WHERE membership_role_id = :r "
                "AND revoked_at IS NOT NULL",
                r=sc.r_x,
            )
        ),
    }


def run_cycle_schedule(
    w: Any,
    pool: Pool,
    sc: Scene,
    *,
    gate_pattern: str | None = None,
    park_after: str | None = None,
    v_blockers_within: set[str],
) -> Result:
    """X parked (`gate_pattern`) -> C started, observed waiting at the group on **X's** pid -> V started, observed waiting at
    its ordered role statement -> NOWAIT probes of both X's and C's role rows -> X released.

    `v_blockers_within` names which of `"x"`, `"c"` V may be waiting on (the corrected tree: whichever of the two holds the
    row V reaches first; at HEAD: C only)."""
    admin = w.engine
    before = deadlocks_now(admin)
    arrivals: dict[str, Waiter] = {}
    gate_ctx = (
        AfterStatementGate(pool.engine, park_after)
        if park_after is not None
        else NthGate(pool.engine, gate_pattern or "")
    )
    with gate_ctx as gate:
        x = run_in_thread("x", lambda: x_request(w, pool, sc))
        assert gate.reached.wait(WAIT_SECONDS), "SETUP: X never reached its gate"
        assert gate.pid is not None
        x_pid = gate.pid
        c = run_in_thread("c", lambda: c_request(w, pool, sc))
        arrivals["c"] = observe_waiter(
            admin,
            pattern=GROUP_KEY_SHARE,
            exclude={x_pid},
            blockers_are={x_pid},
            what="C waiting at the group behind X",
        )
        c_pid = arrivals["c"].pid
        v = run_in_thread("v", lambda: v_request(w, pool, sc))
        within = {x_pid if name == "x" else c_pid for name in v_blockers_within}
        arrivals["v"] = observe_waiter(
            admin,
            pattern=ROLE_FOR_UPDATE,
            exclude={x_pid, c_pid},
            blockers_within=within,
            what="V waiting at its ordered role statement",
        )
        modes = {
            "x_row": held_mode(admin, ROLE_ROW, sc.r_x),
            "c_row": held_mode(admin, ROLE_ROW, sc.r_c),
        }
        gate.release()
        results = {
            "x": finish(x, "x finishes"),
            "c": finish(c, "c finishes"),
            "v": finish(v, "v finishes"),
        }
        ended = {"x": x.ended or 0.0, "c": c.ended or 0.0, "v": v.ended or 0.0}
    delta = settled_deadlock_delta(admin, pool, before)
    return Result(
        {k: (code(r), error_of(r)) for k, r in results.items()},
        ended,
        list(pool.failures),
        delta,
        arrivals,
        modes,
        durable_state(w, sc),
        {"x": x_pid, "c": c_pid},
    )


def run_v_first_schedule(w: Any, pool: Pool, sc: Scene) -> Result:
    """T-1c: V parked after its role statements (holding X's and C's rows `FOR UPDATE`) -> X started, observed waiting at X's role
    `FOR SHARE` behind V -> C started, observed waiting at its authority role statement behind V -> V released."""
    admin = w.engine
    before = deadlocks_now(admin)
    arrivals: dict[str, Waiter] = {}
    with NthGate(pool.engine, V_DELEGATIONS) as gate:
        v = run_in_thread("v", lambda: v_request(w, pool, sc))
        assert gate.reached.wait(WAIT_SECONDS), "SETUP: V never reached its gate"
        assert gate.pid is not None
        v_pid = gate.pid
        modes = {
            "x_row": held_mode(admin, ROLE_ROW, sc.r_x),
            "c_row": held_mode(admin, ROLE_ROW, sc.r_c),
        }
        x = run_in_thread("x", lambda: x_request(w, pool, sc))
        arrivals["x"] = observe_waiter(
            admin,
            pattern=ROLE_FOR_SHARE,
            exclude={v_pid},
            blockers_are={v_pid},
            what="X waiting for its role rows behind V",
        )
        c = run_in_thread("c", lambda: c_request(w, pool, sc))
        arrivals["c"] = observe_waiter(
            admin,
            pattern=AUTHORITY_ROLES_SHARE,
            exclude={v_pid, arrivals["x"].pid},
            blockers_are={v_pid},
            what="C waiting for its authority role rows behind V",
        )
        gate.release()
        results = {
            "v": finish(v, "v finishes"),
            "x": finish(x, "x finishes"),
            "c": finish(c, "c finishes"),
        }
        ended = {"x": x.ended or 0.0, "c": c.ended or 0.0, "v": v.ended or 0.0}
    delta = settled_deadlock_delta(admin, pool, before)
    return Result(
        {k: (code(r), error_of(r)) for k, r in results.items()},
        ended,
        list(pool.failures),
        delta,
        arrivals,
        modes,
        durable_state(w, sc),
    )


#: The recorded failure statement is truncated by the harness to 150 characters, so the cycle-edge test names the table the
#: statement locks: X's and V's role rows, or C's group row.
CYCLE_EDGE = re.compile(r"membership_roles|access_groups")


def assert_one_deadlock(res: Result) -> str:
    """T-1a at HEAD: exactly one 40P01 at a cycle-edge statement, delta 1, the victim's response 500 and its writes absent; the two
    others reach their schedule outcomes. Returns the victim's name."""
    assert len(res.failures) == 1 and res.failures[0][0] == "40P01", res.summary()
    assert CYCLE_EDGE.search(res.failures[0][1]), res.summary()
    assert res.delta == 1, res.summary()
    victims = [k for k, (status, _) in res.statuses.items() if status == 500]
    assert len(victims) == 1, res.summary()
    victim = victims[0]
    state = res.state
    # the victim's writes are absent; every party that answered with its success status has its write
    assert (res.statuses["x"][0] == 201) == (state["group_grants"] == 1), res.summary()
    assert (res.statuses["c"][0] == 201) == (state["revelations"] == 1), res.summary()
    assert (res.statuses["v"][0] == 200) == state["x_row_revoked"], res.summary()
    return victim


def assert_clean_in_order_x_c_v(res: Result) -> None:
    assert res.failures == [] and res.delta == 0, res.summary()
    assert res.statuses == {"x": (201, None), "c": (201, None), "v": (200, None)}, res.summary()
    assert res.ended["x"] <= res.ended["c"] <= res.ended["v"], res.summary()
    assert res.state == {"group_grants": 1, "revelations": 1, "x_row_revoked": True}, res.summary()


def assert_v_first_clean(res: Result) -> None:
    assert res.failures == [] and res.delta == 0, res.summary()
    assert res.statuses["v"] == (200, None) and res.statuses["c"] == (201, None), res.summary()
    assert res.statuses["x"][0] in (403, 404), (
        res.summary()
    )  # X's authority was revoked by V before X resumed
    assert res.state == {"group_grants": 0, "revelations": 1, "x_row_revoked": True}, res.summary()
    assert res.modes == {"x_row": "U", "c_row": "U"}, (
        res.summary()
    )  # V held both rows when it was parked


@dataclass
class Pair:
    statuses: dict[str, tuple[int, str | None]]
    ended: dict[str, float]
    failures: list[tuple[str | None, str]]
    delta: int
    arrival: Waiter
    parked_pid: int


def run_pair(
    w: Any,
    pool: Pool,
    *,
    parked: Any,
    gate_pattern: str,
    second: Any,
    second_pattern: str,
    names: tuple[str, str],
) -> Pair:
    """Two parties: `parked` is stopped at `gate_pattern` (holding what it holds there); `second` starts only then and is
    **observed** waiting on the parked backend, on a statement matching `second_pattern`; then `parked` is released."""
    admin = w.engine
    before = deadlocks_now(admin)
    with NthGate(pool.engine, gate_pattern) as gate:
        first = run_in_thread(names[0], parked)
        assert gate.reached.wait(WAIT_SECONDS), (
            f"SETUP: {names[0]} never reached its gate {gate_pattern!r}"
        )
        assert gate.pid is not None
        later = run_in_thread(names[1], second)
        arrival = observe_waiter(
            admin,
            pattern=second_pattern,
            exclude={gate.pid},
            blockers_are={gate.pid},
            what=f"{names[1]} waiting on {names[0]}",
        )
        gate.release()
        results = {
            names[0]: finish(first, "parked finishes"),
            names[1]: finish(later, "second finishes"),
        }
        ended = {names[0]: first.ended or 0.0, names[1]: later.ended or 0.0}
        parked_pid = gate.pid
    delta = settled_deadlock_delta(admin, pool, before)
    return Pair(
        {k: (code(r), error_of(r)) for k, r in results.items()},
        ended,
        list(pool.failures),
        delta,
        arrival,
        parked_pid,
    )


def assert_no_deadlock(res: Result) -> None:
    """The regression detector, asserted **first**: no driver exception and the deadlock counter unmoved."""
    assert res.failures == [] and res.delta == 0, res.summary()

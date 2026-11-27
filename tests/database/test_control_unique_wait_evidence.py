# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""P15-C11-S02 correction S02-R3: discriminating evidence for the competing `UniqueWait` entries of the C11 INSERTs.

The declarations (`control_assignment_plans._COMPETING_ASSIGNMENT_WAITS` and
`assign_control_delegation_plans._INSERT_LIVE_DELEGATION_INDEX`) say each INSERT step may wait on a named live partial
unique index for a competing uncommitted key. The original race tests observed only "the competitor is blocked by the
request's pid, then fails with a unique violation". That observation does not name the wait's source: the request
holds parent rows (`campaign.campaigns`, the character, the assignee membership, the `assistant_gm` row) in modes that
conflict with a competitor's foreign-key `FOR KEY SHARE`, so a competitor can be blocked by the request for a reason
unrelated to the index (`test_r3_control_a_same_parents_competitor_outside_the_index_is_blocked_at_its_foreign_key*`
shows exactly that observation for a key the index does not cover).

**Mechanism this file relies on, and checks.** PostgreSQL inserts the heap tuple and its index entries (the unique check
happens there) before the AFTER triggers that run the foreign-key checks. A foreign-key check takes a `RowShareLock` on
the parent relation and, when it must wait for a row lock, holds a heavyweight `tuple` lock on the parent row. So a
waiting session that holds neither has not started any foreign-key check: its wait is earlier, at the index.
`fk_checks_started` reads exactly that from `pg_locks`; the controls show it is `True` for a real foreign-key wait.

**Evidence classes.**

- *Statement isolation* (`test_r3_<index>_*_statement_waits_on_the_named_index_alone`): the step's own compiled
  statement runs on connection A against connection B's uncommitted competing row. B holds only `FOR KEY SHARE` on the
  shared parents (its own foreign-key checks), which never conflicts with A's, and the same-parents control shows A does
  not wait when B's row is outside the index predicate. A waits for B's transaction id with no foreign-key check
  started; when B commits, A fails with a unique violation **naming the index**; when B rolls back, A succeeds. This is
  the declared wait itself: the step's statement waiting on the named index.
- *Same-parents control* (`..._control_same_parents_outside_the_index_never_waits`): identical parents, B's row
  outside that index's predicate (another role, or revoked): A completes under `lock_timeout` with no wait.
- *Route controls* (`test_r3_control_a_same_parents_competitor_outside_the_index_is_blocked_at_its_foreign_key*`): a
  request parked at its audit insert and a competitor whose key no index covers. It is blocked by the request's pid (the
  old tests' assertion holds), with `fk_checks_started` true; it then completes. These pass before and after the
  correction: they show why the old observation was not discriminating.

**Limits.** A route request cannot itself be shown waiting on these indexes with an outside competitor: an uncommitted
competitor holds `FOR KEY SHARE` on the campaign, so the request queues at its campaign `FOR UPDATE` first; inside the
application every writer of these rows takes that campaign lock, so the index wait is a declared, conservative wait that
statement isolation demonstrates and route traffic serializes before. The discriminator relies on the documented order
of index insertion and AFTER-trigger foreign-key checks and on `pg_locks`' lock vocabulary; it does not inspect the
server's wait at the index page level.
"""

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import IntegrityError

from tests.database.test_assign_control_delegation import (  # noqa: F401 - fixtures used by name
    DELEGATION_COMMANDS,
    _tidy_delegation_audit,
    assistant_row,
    grant,
)
from tests.database.test_control_assignment_commands import (  # noqa: F401 - fixtures used by name
    Env,
    Factory,
    _tidy,
    assign_body,
    assign_path,
    env,
    post,
    seed,
)
from tests.database.test_r01_s2_profile_routes import (  # noqa: F401 - fixtures used by name
    pooled,
    pooled_factory,
)
from tests.database.test_r01_s3_authoring_routes import (  # noqa: F401 - fixtures used by name
    World,
    code,
    w,
)
from tests.database.test_r01_s5e2_membership_routes import (  # noqa: F401 - fixtures used by name
    Scene,
    m,
    s,
)
from tests.factories import make_control_assignment, relationship_type_id
from tests.http_race_support import StatementGate, run_in_thread
from tests.lock_race_support import LockRace

pytestmark = pytest.mark.database

LIVE_PRIMARY = "ux_membership_character_relationships_live_primary"
LIVE_ASSIGNMENT = "ux_membership_character_relationships_live_assignment"
LIVE_DELEGATION = "ux_character_assign_control_delegations_live"
AUDIT_INSERT = r"^INSERT INTO audit\.change_log"


# --- the discriminator ---------------------------------------------------------------------------------------------


def fk_checks_started(engine: Engine, pid: int) -> bool:
    """Whether session `pid` has begun a foreign-key check: it holds a `RowShareLock` on some relation (the RI
    `SELECT ... FOR KEY SHARE` of a parent) or a heavyweight `tuple` lock (held while it waits for a row lock)."""
    with engine.connect() as c:
        return bool(
            c.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE pid = :p "
                    "AND (mode = 'RowShareLock' OR locktype = 'tuple'))"
                ),
                {"p": pid},
            ).scalar_one()
        )


def waits_for_transaction_of(engine: Engine, waiter: int, holder: int) -> bool:
    """Whether `waiter`'s one ungranted lock is a `transactionid` lock on `holder`'s transaction."""
    with engine.connect() as c:
        return bool(
            c.execute(
                text(
                    "SELECT l.locktype = 'transactionid' AND l.transactionid = a.backend_xid "
                    "FROM pg_locks l, pg_stat_activity a "
                    "WHERE l.pid = :w AND NOT l.granted AND a.pid = :h"
                ),
                {"w": waiter, "h": holder},
            ).scalar()
        )


def constraint_of(error: BaseException | None) -> str | None:
    assert isinstance(error, IntegrityError), error
    return getattr(getattr(error.orig, "diag", None), "constraint_name", None)


class _RolledBack(Exception):
    """Ends a worker's transaction with a rollback after its statement succeeded (the result is kept)."""


# --- the steps under test ------------------------------------------------------------------------------------------


def _assignment_step(name: str) -> Any:
    from dnd_ai.commands import control_assignment_plans as plans

    return getattr(plans, name)


def _run_assignment_step(
    step_name: str, sc: Scene, membership: uuid.UUID, character: uuid.UUID, role: str
) -> Callable[[Connection], Any]:
    step = _assignment_step(step_name)

    def run(c: Connection) -> Any:
        binds = {
            "campaign": sc.w.campaign_id,
            "membership": membership,
            "character": character,
            "type": relationship_type_id(c, role),
            "kind": "ongoing",
            "time_from": None,
            "time_to": None,
            "granted_by": None,
            "notes": None,
        }
        names = set(step.statement.compile().params)
        return c.execute(step.statement, {k: v for k, v in binds.items() if k in names}).all()

    return run


def _run_delegation_step(sc: Scene, e: Env) -> Callable[[Connection], Any]:
    from dnd_ai.commands.assign_control_delegation_plans import INSERT_DELEGATION

    role = assistant_row(sc, e.assistant)

    def run(c: Connection) -> Any:
        return c.execute(
            INSERT_DELEGATION.statement,
            {
                "campaign": sc.w.campaign_id,
                "grantee": e.assistant.membership,
                "role": role,
                "actor_membership": e.owner.membership,
                "reason": "R3 step under test",
            },
        ).all()

    return run


def _competing_delegation(sc: Scene, e: Env, *, live: bool) -> Callable[[Connection], Any]:
    role = assistant_row(sc, e.assistant)
    closed = (
        ", revoked_at, revoked_by_membership_id, revocation_reason, end_reason" if not live else ""
    )
    closed_values = ", clock_timestamp(), :by, 'R3 closed', 'revoked'" if not live else ""

    def run(c: Connection) -> Any:
        return c.execute(
            text(
                "INSERT INTO security.character_assign_control_delegations "
                "(campaign_id, grantee_campaign_membership_id, assistant_gm_membership_role_id, "
                f"granted_by_membership_id, reason{closed}) VALUES (:c, :g, :r, :by, 'R3 competitor'{closed_values})"
            ),
            {
                "c": sc.w.campaign_id,
                "g": e.assistant.membership,
                "r": role,
                "by": e.owner.membership,
            },
        )

    return run


def _case(sc: Scene, e: Env, case: str, *, conflicting: bool) -> tuple[Callable[..., Any], ...]:
    """(B's competing row, A's step statement, the index) for one case. `conflicting=False` is the same-parents
    control: B's row is outside the index's predicate."""
    if case in ("assign-live-primary", "replace-live-primary"):
        step = "ASSIGN_INSERT" if case.startswith("assign") else "REPLACE_INSERT"
        b_role = "primary_controller" if conflicting else "co_controller"

        def b(c: Connection) -> Any:
            return make_control_assignment(
                c, e.p2.membership, e.character, b_role, "ongoing", campaign_id=sc.w.campaign_id
            )

        return (
            b,
            _run_assignment_step(step, sc, e.p1.membership, e.character, "primary_controller"),
            (lambda: LIVE_PRIMARY),
        )
    if case in ("assign-live-assignment", "replace-live-assignment"):
        step = "ASSIGN_INSERT" if case.startswith("assign") else "REPLACE_INSERT"
        a_role = "co_controller" if step == "ASSIGN_INSERT" else "primary_controller"

        def b(c: Connection) -> Any:
            return make_control_assignment(
                c,
                e.p1.membership,
                e.character,
                "co_controller",
                "ongoing",
                campaign_id=sc.w.campaign_id,
                revoked=not conflicting,
            )

        return (
            b,
            _run_assignment_step(step, sc, e.p1.membership, e.character, a_role),
            (lambda: LIVE_ASSIGNMENT),
        )
    assert case == "delegation-live"
    return (
        _competing_delegation(sc, e, live=conflicting),
        _run_delegation_step(sc, e),
        (lambda: LIVE_DELEGATION),
    )


CASES = [
    "assign-live-primary",
    "replace-live-primary",
    "assign-live-assignment",
    "replace-live-assignment",
    "delegation-live",
]


# --- statement isolation -------------------------------------------------------------------------------------------


@pytest.mark.parametrize("ending", ["competitor-commits", "competitor-rolls-back"])
@pytest.mark.parametrize("case", CASES)
def test_r3_each_insert_statement_waits_on_the_named_index_alone(
    s: Scene, env: Env, case: str, ending: str
) -> None:
    """A's step statement against B's uncommitted competing key: A waits for B's transaction with no foreign-key check
    started; B commits -> A's unique violation names the index; B rolls back -> A succeeds (then A rolls back)."""
    b_op, a_op, index = _case(s, env, case, conflicting=True)

    def a_then_roll_back(c: Connection) -> Any:
        rows = a_op(c)
        raise _RolledBack(rows)

    with LockRace(s.w.engine) as race:
        holder = race.hold(b_op)
        a = race.start("step", a_then_roll_back)
        race.wait_blocked_by(holder, a)
        assert a.pid is not None
        assert waits_for_transaction_of(s.w.engine, a.pid, holder.pid)
        assert fk_checks_started(s.w.engine, a.pid) is False, (
            "the step's statement waits after starting a foreign-key check: not the index wait"
        )
        if ending == "competitor-commits":
            holder.commit()
        else:
            holder.close()
        race.join_all()
    if ending == "competitor-commits":
        assert constraint_of(a.error) == index()
    else:
        assert isinstance(a.error, _RolledBack), a.error
        assert len(a.error.args[0]) == 1


@pytest.mark.parametrize("case", CASES)
def test_r3_each_insert_statement_control_same_parents_outside_the_index_never_waits(
    s: Scene, env: Env, case: str
) -> None:
    """*control*: B holds an uncommitted row on the same parents whose key is outside the index's predicate; A's step
    statement completes under a lock timeout. The shared parents (B's `FOR KEY SHARE`) do not make A wait, so in the
    conflicting case above the wait is the index."""
    b_op, a_op, _index = _case(s, env, case, conflicting=False)
    with LockRace(s.w.engine) as race:
        holder = race.hold(b_op)
        with s.w.engine.connect() as c:
            tx = c.begin()
            c.execute(text("SET LOCAL lock_timeout = '5s'"))
            rows = a_op(c)
            tx.rollback()
        holder.close()
    assert len(rows) == 1


# --- route controls: why "blocked by the request, then a unique violation" did not name the source --------------


def test_r3_control_a_same_parents_competitor_outside_the_index_is_blocked_at_its_foreign_key(
    s: Scene, env: Env, pooled: Engine, pooled_factory: Factory
) -> None:
    """*control* (passes before and after the correction): an assign parked at its audit insert, and a competitor
    inserting a co-controller of another member on the same character (no live index covers that key). The old
    observation holds (blocked by the request's pid), yet the competitor's wait is its foreign-key check
    (`fk_checks_started`); it completes once the request commits."""
    path, body = assign_path(s, env.character), assign_body(env.p1, "primary_controller")
    with StatementGate(pooled, AUDIT_INSERT, strict=True) as gate:
        request = gate.track(
            run_in_thread("assign", lambda: post(pooled_factory, env.owner.user, path, body))
        )
        gate.wait_reached()
        assert gate.pid is not None
        with LockRace(s.w.engine) as race:
            queued = race.start(
                "insert",
                lambda c: make_control_assignment(
                    c,
                    env.p2.membership,
                    env.character,
                    "co_controller",
                    "ongoing",
                    campaign_id=s.w.campaign_id,
                ),
            )
            race.wait_blocked_by(gate, expected=1)
            assert queued.pid is not None
            assert fk_checks_started(s.w.engine, queued.pid) is True
            gate.release()
            response = request.wait("the writer finishes")
            race.join_all()
    assert code(response) == 201, response.text
    assert queued.error is None


def test_r3_control_a_same_parents_competitor_outside_the_index_is_blocked_at_its_foreign_key_delegation(
    s: Scene, env: Env, pooled: Engine, pooled_factory: Factory
) -> None:
    """*control* for the delegation INSERT: a grant parked at its audit insert, and a competitor inserting a **closed**
    delegation for the same grantee (outside the live index). It is blocked by the request's pid at its foreign-key
    check (on the `assistant_gm` row the grant holds `FOR UPDATE`, or the campaign), and completes after the commit."""
    with StatementGate(pooled, AUDIT_INSERT, strict=True) as gate:
        request = gate.track(
            run_in_thread("grant", lambda: grant(pooled_factory, s, env.owner.user, env.assistant))
        )
        gate.wait_reached()
        assert gate.pid is not None
        with LockRace(s.w.engine) as race:
            queued = race.start("insert", _competing_delegation(s, env, live=False))
            race.wait_blocked_by(gate, expected=1)
            assert queued.pid is not None
            assert fk_checks_started(s.w.engine, queued.pid) is True
            gate.release()
            response = request.wait("the grant finishes")
            race.join_all()
    assert code(response) == 201, response.text
    assert queued.error is None

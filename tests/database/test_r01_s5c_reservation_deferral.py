# ruff: noqa: F811, SIM117, S608 - the imported fixture `w` is used by name; nested `with` keeps each expected failure separate; scratch DDL
"""R01 S5-C: the opt-in deferral of the reservation's campaign FK, the server-derived reservation outcome,
the declaration chosen by outcome, and the campaign-evidence obligation (plan section 6.21.4).

NO production route opts in. These tests drive `AuthorizationPlan` directly, against the real migrated
`security.idempotent_requests` and `campaign.campaigns` tables, with a scratch `marker` table standing in
for a command's business write. Evidence classes are labelled in each docstring:

- **mechanism**: raw SQL on the real tables, no plan. It shows what PostgreSQL does (the deferred check
  takes `FOR KEY SHARE` on the campaign row *at COMMIT*), so a "commit succeeded" can be told apart from
  a proven re-acquisition.
- **plan**: the S5-C API on a real connection and transaction.
- **route**: one real keyed route, unchanged, to show the default stays immediate.

Every wait is observed through `pg_blocking_pids` (`sessions_blocked_by`); no scenario relies on a
timeout or on sampling. [source] marks a statement that rests on PostgreSQL's source, not on a test.
"""

import asyncio
import contextlib
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import (
    Column,
    Connection,
    Engine,
    Identity,
    Integer,
    MetaData,
    Table,
    Text,
    bindparam,
    create_engine,
    func,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.exc import IntegrityError

from dnd_ai.api.app import create_app
from dnd_ai.api.auth import get_authenticated_user_id
from dnd_ai.api.deps import get_engine
from dnd_ai.api.errors import ConflictError
from dnd_ai.api.idempotency import (
    IdempotentReplay,
    IdempotentReservation,
    begin_idempotent_request,
)
from dnd_ai.commands._content import canon_edit_requirement
from dnd_ai.commands.campaigns import create_campaign
from dnd_ai.domain import authorization
from dnd_ai.domain.authoring import CampaignNotAuthorizedError
from dnd_ai.domain.authorization import (
    REPLAY_DECLARATION,
    AuthorizationPlan,
    AuthorizationPlanBindingError,
    AuthorizationPlanNotFinalizedError,
    AuthorizationPlanStateError,
    AuthorizationPlanViolationError,
    PlanMode,
    Requirement,
    ReservationDeclarations,
    ViolationReason,
)
from dnd_ai.domain.authorization_steps import (
    Between,
    DeclarationError,
    Exactly,
    KeyBind,
    PreLock,
    PreWriteDeclaration,
    WriteStep,
)
from dnd_ai.persistence.tables.campaign import campaigns as cp
from dnd_ai.persistence.tables.security import idempotent_requests as ir
from tests.database.test_r01_s3_authoring_routes import World, w  # noqa: F401 - fixture by name
from tests.factories import oidc_principal
from tests.http_race_support import (
    new_key,
    run_in_thread,
    sessions_blocked_by,
    wait_until_pid_blocks,
)

pytestmark = pytest.mark.database

R = ViolationReason
SCHEMA = "r01_s5c"
FK = "security.idempotent_requests_campaign_id_fkey"

# --- declarations over the real tables ---------------------------------------------------------------

_meta = MetaData()
marker = Table(
    "marker",
    _meta,
    Column("marker_id", Integer, Identity(), primary_key=True),
    Column("note", Text, nullable=False),
    schema=SCHEMA,
)

campaign_ks = PreLock(
    "campaign_ks",
    select(cp.c.campaign_id)
    .where(cp.c.campaign_id == bindparam("c"))
    .with_for_update(read=True, key_share=True),
)
campaign_share = PreLock(
    "campaign_share",
    select(cp.c.campaign_id).where(cp.c.campaign_id == bindparam("c")).with_for_update(read=True),
)
campaign_nku = PreLock(
    "campaign_nku",
    select(cp.c.campaign_id)
    .where(cp.c.campaign_id == bindparam("c"))
    .with_for_update(key_share=True),
)
campaign_upd = PreLock(
    "campaign_upd",
    select(cp.c.campaign_id).where(cp.c.campaign_id == bindparam("c")).with_for_update(),
)
receipt_lock = PreLock(
    "receipt_lock",
    select(ir.c.idempotent_request_id)
    .where(ir.c.idempotent_request_id == bindparam("r"))
    .with_for_update(),
)


def ins_marker(cardinality: Any = None) -> WriteStep:
    return WriteStep(
        name="ins_marker",
        statement=insert(marker).values(note=bindparam("note")).returning(marker.c.marker_id),
        cardinality=cardinality or Between(0, 1),
        value_binds=frozenset({"note"}),
    )


def receipt_step(cardinality: Any = None) -> WriteStep:
    return WriteStep(
        name="receipt",
        statement=update(ir)
        .where(ir.c.idempotent_request_id == bindparam("r"))
        .values(
            response_status_code=bindparam("s"),
            response_body=bindparam("b"),
            completed_at=func.pg_catalog.now(),
        )
        .returning(ir.c.idempotent_request_id),
        cardinality=cardinality or Exactly(1),
        target=(KeyBind(ir.c.idempotent_request_id, "r"),),
        target_lock=receipt_lock,
        value_binds=frozenset({"s", "b"}),
    )


def declarations(
    campaign_lock: PreLock | None = campaign_ks, *, business: Any = None
) -> ReservationDeclarations:
    locks = tuple(lock for lock in (campaign_lock, receipt_lock) if lock is not None)
    return ReservationDeclarations(
        reserved=PreWriteDeclaration(locks=locks, steps=(ins_marker(business), receipt_step())),
        unkeyed=PreWriteDeclaration(locks=(), steps=(ins_marker(Exactly(1)),)),
    )


# --- scaffolding -------------------------------------------------------------------------------------


_OPEN: list[Connection] = []


def track(connection: Connection) -> Connection:
    _OPEN.append(connection)
    return connection


def _close_open_connections() -> None:
    """A failing test must not leave a transaction open: the fixture teardown would then wait for it."""
    while _OPEN:
        connection = _OPEN.pop()
        with contextlib.suppress(Exception):
            connection.invalidate()
        with contextlib.suppress(Exception):
            connection.close()


@pytest.fixture
def scratch(w: World) -> Iterator[World]:
    admin = w.engine.execution_options(isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))
        connection.execute(text(f"CREATE SCHEMA {SCHEMA}"))
        connection.execute(
            text(
                f"CREATE TABLE {SCHEMA}.marker (marker_id int GENERATED ALWAYS AS IDENTITY PRIMARY KEY, "
                "note text NOT NULL)"
            )
        )
    try:
        yield w
    finally:
        _close_open_connections()
        with admin.connect() as connection:
            connection.execute(text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))


@pytest.fixture
def campaign_b(scratch: World) -> uuid.UUID:
    """A second campaign (same timeline), for wrong-campaign evidence and outcomes."""
    with scratch.engine.begin() as setup:
        campaign = setup.execute(
            text(
                "SELECT timeline_id, ruleset_version_id FROM campaign.campaigns WHERE campaign_id = :c"
            ),
            {"c": scratch.campaign_id},
        ).one()
        return create_campaign(
            setup,
            timeline_id=campaign.timeline_id,
            ruleset_version_id=campaign.ruleset_version_id,
            name="S5-C Campaign B",
            creator_user_id=scratch.owner,
        ).campaign_id


@pytest.fixture
def one(scratch: World) -> Iterator[Engine]:
    """A one-connection pool: the next request reuses the connection the previous one left."""
    engine = create_engine(scratch.engine.url, pool_size=1, max_overflow=0)
    try:
        yield engine
    finally:
        engine.dispose()


def open_plan(
    engine: Engine,
    w: World,
    decls: ReservationDeclarations | None,
    *,
    campaign_id: uuid.UUID | None = None,
    patient: bool = False,
) -> tuple[Connection, AuthorizationPlan]:
    """A pre-write plan on a fresh transaction. Unless `patient`, the transaction cannot wait for a row
    lock for more than two seconds (set before the plan exists: the guard polices every statement after
    `finalize`), so a request that unexpectedly waits fails loudly instead of hanging."""
    connection = engine.connect()
    _OPEN.append(connection)
    connection.begin()
    if not patient:
        no_wait(connection)
    plan = AuthorizationPlan.begin(
        connection,
        actor_user_id=w.gm_user,
        campaign_id=campaign_id or w.campaign_id,
        mode=PlanMode.PRE_WRITE,
        by_outcome=decls,
    )
    return connection, plan


def reserve(
    connection: Connection,
    w: World,
    key: str,
    *,
    payload: dict[str, Any] | None = None,
    campaign_id: uuid.UUID | None = None,
) -> IdempotentReservation | IdempotentReplay:
    return begin_idempotent_request(
        connection,
        actor_user_id=w.gm_user,
        campaign_id=campaign_id or w.campaign_id,
        idempotency_key=key,
        command_name="s5c",
        payload=payload or {"n": 1},
        correlation_id=None,
    )


def pid_of(connection: Connection) -> int:
    return int(connection.execute(text("SELECT pg_backend_pid()")).scalar_one())


def fresh(
    engine: Engine,
    w: World,
    key: str,
    decls: ReservationDeclarations | None = None,
    *,
    defer: bool = True,
    evidence: bool | uuid.UUID = True,
    lock: PreLock = campaign_ks,
) -> tuple[Connection, AuthorizationPlan, IdempotentReservation]:
    """Steps 1-6 of the keyed pre-write sequence, up to and including `finalize`'s inputs: defer, reserve,
    bind, lock the campaign (evidence) and the receipt row. Stops before `require` / `finalize`."""
    connection, plan = open_plan(engine, w, decls or declarations(lock))
    if defer:
        plan.defer_reservation_campaign_fk(connection)
    reservation = reserve(connection, w, key)
    assert isinstance(reservation, IdempotentReservation)
    plan.bind_reservation(connection, reservation)
    if evidence:
        target = w.campaign_id if evidence is True else evidence
        plan.lock(connection, lock, {"c": target})
    plan.lock(connection, receipt_lock, {"r": reservation.idempotent_request_id})
    return connection, plan, reservation


def finish(
    connection: Connection,
    plan: AuthorizationPlan,
    w: World,
    reservation: IdempotentReservation,
    *,
    write: bool = True,
    receipt: bool = True,
) -> None:
    plan.require(connection, canon_edit_requirement(w.gm_user, w.campaign_id))
    plan.finalize(connection)
    if write:
        plan.execute(connection, _step(plan, "ins_marker"), {"note": "n"})
    if receipt:
        plan.execute(
            connection,
            _step(plan, "receipt"),
            {"r": reservation.idempotent_request_id, "s": 201, "b": {"ok": True}},
        )


def _step(plan: AuthorizationPlan, name: str) -> WriteStep:
    declaration = plan._declaration
    assert declaration is not None
    return next(step for step in declaration.steps if step.name == name)


def commit_refused(connection: Connection) -> None:
    with pytest.raises(AuthorizationPlanNotFinalizedError):
        connection.commit()


def rows(engine: Engine, sql: str, **params: Any) -> int:
    with engine.connect() as connection:
        return int(connection.execute(text(sql), params).scalar_one())


def markers(engine: Engine) -> int:
    return rows(engine, f"SELECT count(*) FROM {SCHEMA}.marker")


def reservations(engine: Engine, key: str) -> int:
    return rows(
        engine,
        "SELECT count(*) FROM security.idempotent_requests WHERE idempotency_key = :k",
        k=key,
    )


def completed(engine: Engine, key: str) -> int:
    return rows(
        engine,
        "SELECT count(*) FROM security.idempotent_requests "
        "WHERE idempotency_key = :k AND completed_at IS NOT NULL",
        k=key,
    )


def hold_campaign(
    engine: Engine, campaign_id: uuid.UUID, mode: str = "UPDATE"
) -> tuple[Connection, int]:
    """An independent session holding the campaign row `FOR <mode>` until it is closed."""
    connection = engine.connect()
    _OPEN.append(connection)
    connection.begin()
    connection.execute(
        text(f"SELECT 1 FROM campaign.campaigns WHERE campaign_id = :c FOR {mode}"),
        {"c": campaign_id},
    ).all()
    return connection, pid_of(connection)


def release(connection: Connection) -> None:
    connection.rollback()
    connection.close()


def no_wait(connection: Connection) -> None:
    """A lock that cannot be granted at once fails instead of waiting (a wait would hang the test)."""
    connection.execute(text("SET LOCAL lock_timeout = '2s'"))


def complete_first(engine: Engine, w: World, key: str) -> None:
    """A finished request under `key` (committed receipt), so later calls can replay it."""
    connection, plan, reservation = fresh(engine, w, key)
    finish(connection, plan, w, reservation)
    connection.commit()
    connection.close()


# =====================================================================================================
# 1. Default behaviour is unchanged
# =====================================================================================================


def test_the_campaign_fk_is_checked_at_the_insert_by_default(scratch: World) -> None:
    """mechanism: an unopted reservation for a campaign that does not exist fails at the INSERT."""
    with scratch.engine.connect() as connection:
        with connection.begin():
            with pytest.raises(IntegrityError, match="idempotent_requests_campaign_id_fkey"):
                connection.execute(
                    text(
                        "INSERT INTO security.idempotent_requests "
                        "(actor_user_id, campaign_id, idempotency_key, request_fingerprint) "
                        "VALUES (:u, :c, :k, 'f')"
                    ),
                    {"u": scratch.gm_user, "c": uuid.uuid4(), "k": new_key()},
                )


def test_by_default_the_reservation_waits_for_a_campaign_row_lock_at_the_insert(
    scratch: World,
) -> None:
    """mechanism: a held campaign `FOR UPDATE` blocks the reservation INSERT itself (the existing
    behaviour every accepted route has), not the COMMIT."""
    holder, holder_pid = hold_campaign(scratch.engine, scratch.campaign_id)
    key = new_key()

    def insert_reservation() -> None:
        with scratch.engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO security.idempotent_requests "
                    "(actor_user_id, campaign_id, idempotency_key, request_fingerprint) "
                    "VALUES (:u, :c, :k, 'f')"
                ),
                {"u": scratch.gm_user, "c": scratch.campaign_id, "k": key},
            )

    request = run_in_thread("immediate", insert_reservation)
    try:
        wait_until_pid_blocks(scratch.engine, holder_pid)
        assert not request.finished()
    finally:
        release(holder)
    request.wait("the INSERT proceeds once the campaign row is free")
    assert reservations(scratch.engine, key) == 1


def test_a_keyed_plan_that_does_not_opt_in_stays_immediate_and_needs_no_evidence(
    scratch: World, one: Engine
) -> None:
    """plan: no deferral, a RESERVED outcome, no campaign lock: it finalizes and commits, and its
    reservation INSERT waits on a held campaign `FOR UPDATE` exactly as before."""
    key = new_key()
    holder, holder_pid = hold_campaign(scratch.engine, scratch.campaign_id)
    connection, plan = open_plan(one, scratch, declarations(None), patient=True)
    request = run_in_thread("insert", lambda: reserve(connection, scratch, key))
    try:
        wait_until_pid_blocks(scratch.engine, holder_pid)
    finally:
        release(holder)
    reservation = request.wait("reserved after the holder released")
    assert not plan.deferred
    plan.bind_reservation(connection, reservation)
    plan.lock(connection, receipt_lock, {"r": reservation.idempotent_request_id})
    finish(connection, plan, scratch, reservation)
    connection.commit()
    connection.close()
    assert completed(scratch.engine, key) == 1
    assert markers(scratch.engine) == 1


def test_a_post_write_or_unkeyed_plan_cannot_defer(scratch: World, one: Engine) -> None:
    """plan: only a keyed pre-write plan may opt in."""
    connection = track(one.connect())
    connection.begin()
    post = AuthorizationPlan.begin(
        connection, actor_user_id=scratch.gm_user, campaign_id=scratch.campaign_id
    )
    with pytest.raises(AuthorizationPlanStateError):
        post.defer_reservation_campaign_fk(connection)
    assert post.violation is R.DEFERRAL
    commit_refused(connection)
    connection.close()

    connection = track(one.connect())
    connection.begin()
    plain = AuthorizationPlan.begin(
        connection,
        actor_user_id=scratch.gm_user,
        campaign_id=scratch.campaign_id,
        mode=PlanMode.PRE_WRITE,
        pre_write=PreWriteDeclaration(locks=(receipt_lock,), steps=(receipt_step(),)),
    )
    with pytest.raises(AuthorizationPlanStateError):
        plain.defer_reservation_campaign_fk(connection)
    assert plain.violation is R.DEFERRAL
    connection.close()


# =====================================================================================================
# 2. Explicit deferral: what it does and when it is allowed
# =====================================================================================================


def test_deferral_moves_the_campaign_wait_from_the_insert_to_the_commit(scratch: World) -> None:
    """mechanism: with the constraint deferred, the INSERT does not wait on a held campaign
    `FOR UPDATE` (so it holds no campaign lock), and the COMMIT then waits for it: the deferred check
    re-acquires `FOR KEY SHARE` at COMMIT. This is the proof that a later successful commit is a
    re-acquisition and not an absence of a check."""
    holder, holder_pid = hold_campaign(scratch.engine, scratch.campaign_id)
    key = new_key()
    connection = track(scratch.engine.connect())
    connection.begin()
    connection.execute(text(f"SET CONSTRAINTS {FK} DEFERRED"))
    connection.execute(
        text(
            "INSERT INTO security.idempotent_requests "
            "(actor_user_id, campaign_id, idempotency_key, request_fingerprint) "
            "VALUES (:u, :c, :k, 'f')"
        ),
        {"u": scratch.gm_user, "c": scratch.campaign_id, "k": key},
    )  # returned at once: no wait
    assert sessions_blocked_by(scratch.engine, holder_pid) == 0
    request = run_in_thread("commit", connection.commit)
    try:
        wait_until_pid_blocks(scratch.engine, holder_pid)  # the COMMIT is the waiter
        assert not request.finished()
    finally:
        release(holder)
    request.wait("commit completes once the holder released")
    connection.close()
    assert reservations(scratch.engine, key) == 1


def test_a_deferred_violation_is_reported_at_commit_not_at_the_insert(scratch: World) -> None:
    """mechanism: the other face of the same setting: a missing campaign passes the INSERT and fails
    the COMMIT."""
    connection = track(scratch.engine.connect())
    connection.begin()
    connection.execute(text(f"SET CONSTRAINTS {FK} DEFERRED"))
    connection.execute(
        text(
            "INSERT INTO security.idempotent_requests "
            "(actor_user_id, campaign_id, idempotency_key, request_fingerprint) "
            "VALUES (:u, :c, :k, 'f')"
        ),
        {"u": scratch.gm_user, "c": uuid.uuid4(), "k": new_key()},
    )
    with pytest.raises(IntegrityError, match="idempotent_requests_campaign_id_fkey"):
        connection.commit()
    connection.close()


def test_the_plan_issues_the_deferral_and_takes_no_lock_for_it(scratch: World, one: Engine) -> None:
    """plan: the plan's own SET CONSTRAINTS defers the check (a held campaign `FOR UPDATE` no longer
    blocks the reservation INSERT), and deferring itself waits for nothing, so the advisory key lock
    that `begin_idempotent_request` takes first keeps its place."""
    holder, holder_pid = hold_campaign(scratch.engine, scratch.campaign_id)
    key = new_key()
    connection, plan = open_plan(one, scratch, declarations())
    try:
        plan.defer_reservation_campaign_fk(connection)  # does not wait for the holder
        assert plan.deferred
        reservation = reserve(connection, scratch, key)  # nor does the reservation
        assert isinstance(reservation, IdempotentReservation)
        assert sessions_blocked_by(scratch.engine, holder_pid) == 0
        assert (
            connection.execute(
                text(
                    "SELECT count(*) FROM pg_locks WHERE pid = pg_backend_pid() AND locktype = 'advisory'"
                )
            ).scalar_one()
            == 1
        )
    finally:
        release(holder)
        connection.close()


def test_deferral_is_refused_inside_a_savepoint(scratch: World, one: Engine) -> None:
    """plan: `SET CONSTRAINTS` inside a rolled-back savepoint is undone, so it is refused up front."""
    connection, plan = open_plan(one, scratch, declarations())
    with connection.begin_nested():
        with pytest.raises(AuthorizationPlanStateError):
            plan.defer_reservation_campaign_fk(connection)
    assert plan.violation is R.DEFERRAL
    assert not plan.deferred
    commit_refused(connection)
    connection.close()


def test_deferral_happens_exactly_once_before_the_reservation_and_before_finalize(
    scratch: World, one: Engine
) -> None:
    """plan: a duplicate, a deferral after the reservation is bound and a deferral after finalize each
    latch and refuse the commit."""
    for case in ("twice", "after_bind", "after_finalize"):
        key = new_key()
        connection, plan = open_plan(one, scratch, declarations())
        if case == "twice":
            plan.defer_reservation_campaign_fk(connection)
            with pytest.raises(AuthorizationPlanStateError):
                plan.defer_reservation_campaign_fk(connection)
        else:
            reservation = reserve(connection, scratch, key)
            plan.bind_reservation(connection, reservation)
            if case == "after_finalize":
                plan.lock(connection, campaign_ks, {"c": scratch.campaign_id})
                plan.lock(connection, receipt_lock, {"r": reservation.idempotent_request_id})  # type: ignore[union-attr]
                plan.finalize(connection)
            with pytest.raises(AuthorizationPlanStateError):
                plan.defer_reservation_campaign_fk(connection)
        assert plan.violation is R.DEFERRAL, case
        commit_refused(connection)
        connection.close()
        assert reservations(scratch.engine, key) == 0


def test_deferral_refuses_when_the_catalogue_does_not_show_the_constraint(
    scratch: World, one: Engine
) -> None:
    """plan: the plan checks that the constraint it is about to defer is the reservation's deferrable
    campaign FK. A non-deferrable one (DDL is transactional, rolled back here) is refused."""
    connection, plan = open_plan(one, scratch, declarations())
    connection.execute(
        text(
            "ALTER TABLE security.idempotent_requests "
            "ALTER CONSTRAINT idempotent_requests_campaign_id_fkey NOT DEFERRABLE"
        )
    )
    with pytest.raises(AuthorizationPlanViolationError):
        plan.defer_reservation_campaign_fk(connection)
    assert plan.violation is R.DEFERRAL
    connection.rollback()
    connection.close()


def test_a_plan_with_no_by_outcome_declarations_is_unchanged(scratch: World, one: Engine) -> None:
    """plan: constructing keyed/by-outcome plans is only valid for pre-write mode; the replay
    declaration is never supplied by a caller."""
    connection = track(one.connect())
    connection.begin()
    with pytest.raises(ValueError, match="post-write"):
        AuthorizationPlan.begin(
            connection,
            actor_user_id=scratch.gm_user,
            campaign_id=scratch.campaign_id,
            by_outcome=declarations(),
        )
    with pytest.raises(ValueError, match="never supplied"):
        AuthorizationPlan.begin(
            connection,
            actor_user_id=scratch.gm_user,
            campaign_id=scratch.campaign_id,
            mode=PlanMode.PRE_WRITE,
            pre_write=REPLAY_DECLARATION,
        )
    connection.close()


# =====================================================================================================
# 3. Reservation outcome: bound once, from the server
# =====================================================================================================


def test_the_outcome_comes_from_the_database_result(scratch: World, one: Engine) -> None:
    """plan: a new key is `reserved`; the same key and payload after the first request committed is
    `replay`; the plan derives the kind from the record `begin_idempotent_request` wrote."""
    key = new_key()
    connection, plan, reservation = fresh(one, scratch, key)
    assert plan.reservation_kind == "reserved"
    finish(connection, plan, scratch, reservation)
    connection.commit()
    connection.close()

    connection, plan = open_plan(one, scratch, declarations())
    plan.defer_reservation_campaign_fk(connection)
    replay = reserve(connection, scratch, key)
    assert isinstance(replay, IdempotentReplay)
    plan.bind_reservation(connection, replay)
    assert plan.reservation_kind == "replay"
    connection.rollback()
    connection.close()


def test_a_forged_or_borrowed_outcome_is_refused(
    scratch: World, one: Engine, campaign_b: uuid.UUID
) -> None:
    """plan: a hand-built reservation (no record), a record from another transaction, and a record for
    another campaign are all refused; none of them chooses a declaration."""
    # hand-built
    connection, plan = open_plan(one, scratch, declarations())
    with pytest.raises(AuthorizationPlanViolationError):
        plan.bind_reservation(connection, IdempotentReservation(idempotent_request_id=uuid.uuid4()))
    assert plan.violation is R.OUTCOME
    assert plan.reservation_kind is None
    connection.close()

    # a real record, but made in an earlier transaction of the same pooled connection
    connection = track(one.connect())
    connection.begin()
    stale = reserve(connection, scratch, new_key())
    connection.rollback()
    connection.begin()
    plan = AuthorizationPlan.begin(
        connection,
        actor_user_id=scratch.gm_user,
        campaign_id=scratch.campaign_id,
        mode=PlanMode.PRE_WRITE,
        by_outcome=declarations(),
    )
    with pytest.raises(AuthorizationPlanViolationError):
        plan.bind_reservation(connection, stale)
    assert plan.violation is R.OUTCOME
    connection.close()

    # a real record for another campaign
    connection, plan = open_plan(one, scratch, declarations())
    other = reserve(connection, scratch, new_key(), campaign_id=campaign_b)
    with pytest.raises(AuthorizationPlanViolationError):
        plan.bind_reservation(connection, other)
    assert plan.violation is R.OUTCOME
    connection.close()


def test_the_outcome_binds_exactly_once_and_in_order(scratch: World, one: Engine) -> None:
    """plan: a second bind, a bind after finalize, an unkeyed bind after deferral or after an outcome,
    and a lock before any outcome each latch."""
    # second bind
    connection, plan, reservation = fresh(one, scratch, new_key())
    with pytest.raises(AuthorizationPlanStateError):
        plan.bind_reservation(connection, reservation)
    assert plan.violation is R.OUTCOME
    commit_refused(connection)
    connection.close()

    # unkeyed after deferral
    connection, plan = open_plan(one, scratch, declarations())
    plan.defer_reservation_campaign_fk(connection)
    with pytest.raises(AuthorizationPlanStateError):
        plan.bind_unkeyed(connection)
    assert plan.violation is R.OUTCOME
    connection.close()

    # unkeyed after an outcome
    connection, plan = open_plan(one, scratch, declarations())
    plan.bind_reservation(connection, reserve(connection, scratch, new_key()))
    with pytest.raises(AuthorizationPlanStateError):
        plan.bind_unkeyed(connection)
    connection.close()

    # a lock before any declaration was chosen
    connection, plan = open_plan(one, scratch, declarations())
    with pytest.raises(AuthorizationPlanStateError):
        plan.lock(connection, campaign_ks, {"c": scratch.campaign_id})
    assert plan.violation is R.SEQUENCE
    connection.close()

    # finalize before any declaration was chosen
    connection, plan = open_plan(one, scratch, declarations())
    with pytest.raises(AuthorizationPlanViolationError):
        plan.finalize(connection)
    assert plan.violation is R.DECLARATION
    connection.close()


def test_a_bind_inside_a_savepoint_is_refused(scratch: World, one: Engine) -> None:
    """plan: the reservation made in a savepoint would be undone by its rollback while the outcome
    stayed bound, so the bind is refused there."""
    connection, plan = open_plan(one, scratch, declarations())
    with connection.begin_nested():
        reservation = reserve(connection, scratch, new_key())
        with pytest.raises(AuthorizationPlanStateError):
            plan.bind_reservation(connection, reservation)
    assert plan.violation is R.OUTCOME
    commit_refused(connection)
    connection.close()


def test_a_fingerprint_conflict_and_an_incomplete_reservation_keep_their_errors(
    scratch: World, one: Engine
) -> None:
    """plan: the existing refusals are unchanged and leave no state behind: a different payload under a
    completed key, and a key whose reservation never completed, both raise `ConflictError`; nothing is
    bound; the abandoned transaction leaves the pooled connection immediate."""
    key = new_key()
    complete_first(one, scratch, key)

    connection, plan = open_plan(one, scratch, declarations())
    plan.defer_reservation_campaign_fk(connection)
    with pytest.raises(ConflictError, match="different command or payload"):
        reserve(connection, scratch, key, payload={"n": 2})
    assert plan.reservation_kind is None
    connection.rollback()
    connection.close()

    incomplete = new_key()
    with scratch.engine.begin() as setup:
        setup.execute(
            text(
                "INSERT INTO security.idempotent_requests "
                "(actor_user_id, campaign_id, idempotency_key, request_fingerprint) "
                "VALUES (:u, :c, :k, 'f')"
            ),
            {"u": scratch.gm_user, "c": scratch.campaign_id, "k": incomplete},
        )
    connection, plan = open_plan(one, scratch, declarations())
    plan.defer_reservation_campaign_fk(connection)
    with pytest.raises(ConflictError):
        reserve(connection, scratch, incomplete)
    connection.rollback()
    connection.close()

    assert_next_transaction_is_immediate(one, scratch)


# =====================================================================================================
# 4. Declarations by outcome
# =====================================================================================================


def test_replay_chooses_the_empty_declaration_and_writes_nothing(
    scratch: World, one: Engine
) -> None:
    """plan: a replay commits with no step, no business write and no new reservation, and it can neither
    lock nor execute anything from the command's declaration."""
    key = new_key()
    complete_first(one, scratch, key)
    before = (
        markers(scratch.engine),
        rows(scratch.engine, "SELECT count(*) FROM security.idempotent_requests"),
    )

    connection, plan = open_plan(one, scratch, declarations())
    plan.defer_reservation_campaign_fk(connection)
    replay = reserve(connection, scratch, key)
    plan.bind_reservation(connection, replay)
    assert plan._declaration is REPLAY_DECLARATION
    with pytest.raises(AuthorizationPlanViolationError):
        plan.lock(connection, campaign_ks, {"c": scratch.campaign_id})
    assert plan.violation is R.IDENTITY
    connection.rollback()
    connection.close()

    connection, plan = open_plan(one, scratch, declarations())
    plan.defer_reservation_campaign_fk(connection)
    plan.bind_reservation(connection, reserve(connection, scratch, key))
    plan.require(connection, canon_edit_requirement(scratch.gm_user, scratch.campaign_id))
    plan.finalize(connection)
    with pytest.raises(AuthorizationPlanViolationError):
        plan.execute(connection, ins_marker(), {"note": "no"})
    assert plan.violation is R.IDENTITY
    commit_refused(connection)
    connection.close()

    connection, plan = open_plan(one, scratch, declarations())
    plan.defer_reservation_campaign_fk(connection)
    replay = reserve(connection, scratch, key)
    plan.bind_reservation(connection, replay)
    plan.require(connection, canon_edit_requirement(scratch.gm_user, scratch.campaign_id))
    plan.finalize(connection)
    connection.commit()  # empty declaration: nothing is incomplete
    connection.close()
    assert (
        markers(scratch.engine),
        rows(scratch.engine, "SELECT count(*) FROM security.idempotent_requests"),
    ) == before


def test_replay_queues_no_campaign_check_so_a_held_campaign_lock_does_not_matter(
    scratch: World, one: Engine
) -> None:
    """plan + mechanism: even deferred, a replay inserted no row, so no campaign check is queued for
    COMMIT: the commit completes while another session holds the campaign `FOR UPDATE`. (The same held
    lock blocks a *new* reservation's commit: see the first mechanism test.) It takes no command target
    lock either: `plan.lock` is refused for a replay (above)."""
    key = new_key()
    complete_first(one, scratch, key)
    connection, plan = open_plan(one, scratch, declarations())
    plan.defer_reservation_campaign_fk(connection)
    plan.bind_reservation(connection, reserve(connection, scratch, key))
    plan.require(connection, canon_edit_requirement(scratch.gm_user, scratch.campaign_id))
    plan.finalize(connection)
    holder, holder_pid = hold_campaign(scratch.engine, scratch.campaign_id)
    try:
        connection.commit()  # would fail with lock_timeout if a campaign check were queued
        assert sessions_blocked_by(scratch.engine, holder_pid) == 0
    finally:
        release(holder)
        connection.close()


def test_replay_keeps_the_receipt_only_authorization_semantics(scratch: World, one: Engine) -> None:
    """plan: a replay is still judged by the route's requirements at `finalize`. After the actor's role
    is revoked, the replay is refused with the same error a fresh request gets, and nothing changes."""
    key = new_key()
    complete_first(one, scratch, key)
    with scratch.engine.begin() as setup:
        setup.execute(
            text(
                "UPDATE security.membership_roles SET revoked_at = now() WHERE membership_role_id = :r"
            ),
            {"r": scratch.gm_role},
        )
    connection, plan = open_plan(one, scratch, declarations())
    plan.defer_reservation_campaign_fk(connection)
    plan.bind_reservation(connection, reserve(connection, scratch, key))
    plan.require(connection, canon_edit_requirement(scratch.gm_user, scratch.campaign_id))
    with pytest.raises(CampaignNotAuthorizedError):
        plan.finalize(connection)
    commit_refused(connection)
    connection.close()


def test_a_new_reservation_that_finds_nothing_to_write_still_completes_the_receipt(
    scratch: World, one: Engine
) -> None:
    """plan: a no-op command has zero business writes (`Between(0, 1)`) and still must complete the
    receipt, which it does; skipping the receipt as well leaves the plan incomplete."""
    key = new_key()
    connection, plan, reservation = fresh(one, scratch, key)
    finish(connection, plan, scratch, reservation, write=False)
    connection.commit()
    connection.close()
    assert markers(scratch.engine) == 0
    assert completed(scratch.engine, key) == 1

    key = new_key()
    connection, plan, reservation = fresh(one, scratch, key)
    finish(connection, plan, scratch, reservation, write=False, receipt=False)
    commit_refused(connection)
    assert plan.violation is R.INCOMPLETE
    connection.close()
    assert reservations(scratch.engine, key) == 0


def test_the_empty_replay_declaration_does_not_weaken_a_fresh_command(
    scratch: World, one: Engine
) -> None:
    """plan: only `REPLAY_DECLARATION` may be empty; every other declaration still needs a step, a
    command with a required step still fails when it skips it, and the reserved declaration must carry
    the receipt exactly once."""
    with pytest.raises(DeclarationError):
        PreWriteDeclaration(locks=(), steps=())
    with pytest.raises(DeclarationError):
        PreWriteDeclaration(locks=(receipt_lock,), steps=(), replay=True)
    with pytest.raises(ValueError, match="replay"):
        ReservationDeclarations(reserved=REPLAY_DECLARATION)
    with pytest.raises(ValueError, match="receipt"):
        ReservationDeclarations(
            reserved=PreWriteDeclaration(locks=(), steps=(ins_marker(Exactly(1)),))
        )
    with pytest.raises(ValueError, match="receipt"):
        ReservationDeclarations(
            reserved=PreWriteDeclaration(
                locks=(receipt_lock,), steps=(ins_marker(), receipt_step(Between(0, 1)))
            )
        )
    with pytest.raises(ValueError, match="unkeyed"):
        ReservationDeclarations(
            reserved=PreWriteDeclaration(
                locks=(receipt_lock,), steps=(ins_marker(), receipt_step())
            ),
            unkeyed=PreWriteDeclaration(locks=(receipt_lock,), steps=(receipt_step(),)),
        )
    key = new_key()
    connection, plan, reservation = fresh(
        one, scratch, key, declarations(campaign_ks, business=Exactly(1))
    )
    plan.require(connection, canon_edit_requirement(scratch.gm_user, scratch.campaign_id))
    plan.finalize(connection)
    with pytest.raises(
        AuthorizationPlanViolationError
    ):  # the receipt cannot jump the required step
        plan.execute(
            connection,
            _step(plan, "receipt"),
            {"r": reservation.idempotent_request_id, "s": 201, "b": {"ok": True}},
        )
    assert plan.violation is R.ORDER
    commit_refused(connection)
    connection.close()
    assert completed(scratch.engine, key) == 0


def test_the_unkeyed_declaration_has_no_receipt_and_no_deferral(
    scratch: World, one: Engine
) -> None:
    """plan: a request without a key chooses the unkeyed declaration, writes its business step and
    commits; it needs no campaign evidence and a plan created without one refuses `bind_unkeyed`."""
    connection, plan = open_plan(one, scratch, declarations())
    plan.bind_unkeyed(connection)
    assert plan.reservation_kind == "unkeyed"
    plan.require(connection, canon_edit_requirement(scratch.gm_user, scratch.campaign_id))
    plan.finalize(connection)
    plan.execute(connection, _step(plan, "ins_marker"), {"note": "unkeyed"})
    connection.commit()
    connection.close()
    assert markers(scratch.engine) == 1

    connection, plan = open_plan(
        one,
        scratch,
        ReservationDeclarations(
            reserved=PreWriteDeclaration(
                locks=(receipt_lock,), steps=(ins_marker(), receipt_step())
            )
        ),
    )
    with pytest.raises(AuthorizationPlanStateError):
        plan.bind_unkeyed(connection)
    connection.close()


# =====================================================================================================
# 5. Campaign evidence for a new deferred reservation
# =====================================================================================================


def _spy_on_snapshot(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls: list[int] = []
    real = authorization.read_authority_snapshot

    def spy(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(authorization, "read_authority_snapshot", spy)
    return calls


def test_a_new_deferred_reservation_without_campaign_evidence_cannot_finalize(
    scratch: World, one: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """plan: refused before the authorization snapshot is read; the commit is refused; nothing persists."""
    snapshots = _spy_on_snapshot(monkeypatch)
    key = new_key()
    connection, plan, reservation = fresh(one, scratch, key, evidence=False)
    plan.require(connection, canon_edit_requirement(scratch.gm_user, scratch.campaign_id))
    with pytest.raises(AuthorizationPlanViolationError):
        plan.finalize(connection)
    assert plan.violation is R.CAMPAIGN_EVIDENCE
    assert snapshots == []
    commit_refused(connection)
    connection.close()
    assert reservations(scratch.engine, key) == 0


@pytest.mark.parametrize("lock", [campaign_ks, campaign_share, campaign_nku, campaign_upd])
def test_every_lock_mode_from_key_share_up_counts_as_evidence(
    scratch: World, one: Engine, lock: PreLock
) -> None:
    """plan: `FOR KEY SHARE` and each stronger mode release the obligation."""
    key = new_key()
    connection, plan, reservation = fresh(one, scratch, key, declarations(lock), lock=lock)
    finish(connection, plan, scratch, reservation)
    connection.commit()
    connection.close()
    assert completed(scratch.engine, key) == 1


def test_evidence_for_another_campaign_does_not_count(
    scratch: World, one: Engine, campaign_b: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    """plan: a real lock on campaign B's row, through `plan.lock`, is not evidence for campaign A."""
    snapshots = _spy_on_snapshot(monkeypatch)
    connection, plan, reservation = fresh(one, scratch, new_key(), evidence=campaign_b)
    assert plan.evidence(campaign_ks) == {(campaign_b,)}
    plan.require(connection, canon_edit_requirement(scratch.gm_user, scratch.campaign_id))
    with pytest.raises(AuthorizationPlanViolationError):
        plan.finalize(connection)
    assert plan.violation is R.CAMPAIGN_EVIDENCE
    assert snapshots == []
    connection.close()


def test_a_lock_on_another_table_or_a_mode_outside_the_accepted_set_does_not_count(
    scratch: World, one: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """plan: only a PreLock on `campaign.campaigns` keyed by `campaign_id` counts (the receipt row lock is
    taken in every test and never satisfies it), and the accepted modes are an explicit set: narrowed to
    `FOR UPDATE`, a `FOR KEY SHARE` lock stops counting."""
    connection, plan, reservation = fresh(one, scratch, new_key(), evidence=False)
    assert plan.evidence(receipt_lock) == {(reservation.idempotent_request_id,)}
    plan.require(connection, canon_edit_requirement(scratch.gm_user, scratch.campaign_id))
    with pytest.raises(AuthorizationPlanViolationError):
        plan.finalize(connection)
    assert plan.violation is R.CAMPAIGN_EVIDENCE
    connection.close()

    monkeypatch.setattr(
        authorization, "_KEY_SHARE_OR_STRONGER", frozenset({authorization.LockMode.UPDATE})
    )
    connection, plan, reservation = fresh(one, scratch, new_key())
    plan.require(connection, canon_edit_requirement(scratch.gm_user, scratch.campaign_id))
    with pytest.raises(AuthorizationPlanViolationError):
        plan.finalize(connection)
    assert plan.violation is R.CAMPAIGN_EVIDENCE
    connection.close()


def test_evidence_from_another_transaction_or_connection_does_not_count(
    scratch: World, one: Engine
) -> None:
    """plan: a campaign lock taken in an earlier transaction of the same pooled connection is gone with
    that transaction (the new plan holds no evidence), and a lock call through another connection is a
    binding error that records nothing."""
    connection = track(one.connect())
    connection.begin()
    connection.execute(
        text("SELECT 1 FROM campaign.campaigns WHERE campaign_id = :c FOR KEY SHARE"),
        {"c": scratch.campaign_id},
    ).all()
    connection.rollback()
    connection.close()
    connection, plan, reservation = fresh(one, scratch, new_key(), evidence=False)
    assert plan.evidence(campaign_ks) == frozenset()
    plan.require(connection, canon_edit_requirement(scratch.gm_user, scratch.campaign_id))
    with pytest.raises(AuthorizationPlanViolationError):
        plan.finalize(connection)
    assert plan.violation is R.CAMPAIGN_EVIDENCE
    connection.close()

    other = track(scratch.engine.connect())
    other.begin()
    connection, plan, reservation = fresh(one, scratch, new_key(), evidence=False)
    with pytest.raises(AuthorizationPlanBindingError):
        plan.lock(other, campaign_ks, {"c": scratch.campaign_id})
    assert plan.violation is R.BINDING
    assert plan.evidence(campaign_ks) == frozenset()
    other.close()
    connection.close()


def test_evidence_cannot_be_added_after_finalize(scratch: World, one: Engine) -> None:
    """plan: `LOCK_AFTER_FINALIZE` applies to the campaign lock as to every other."""
    connection, plan, reservation = fresh(
        one, scratch, new_key(), declarations(campaign_ks), evidence=False
    )
    plan.require(connection, canon_edit_requirement(scratch.gm_user, scratch.campaign_id))
    with pytest.raises(AuthorizationPlanViolationError):
        plan.finalize(connection)
    with pytest.raises(AuthorizationPlanViolationError):
        plan.lock(connection, campaign_ks, {"c": scratch.campaign_id})  # violated plan: refused
    connection.close()

    connection, plan = open_plan(one, scratch, declarations(campaign_ks))
    plan.bind_unkeyed(connection)
    plan.finalize(connection)
    with pytest.raises(AuthorizationPlanStateError):
        plan.lock(connection, campaign_ks, {"c": scratch.campaign_id})
    assert plan.violation is R.SEQUENCE or plan.violation is R.LOCK_AFTER_FINALIZE
    connection.close()


def test_held_evidence_means_the_commit_needs_nothing_new(scratch: World, one: Engine) -> None:
    """plan + mechanism: with the campaign `FOR KEY SHARE` held from `plan.lock`, a competitor's
    `FOR UPDATE` queues behind the request (the request waits for nobody), the receipt UPDATE and the
    COMMIT complete while the competitor is still queued, and the competitor proceeds afterwards. The
    deferred check at COMMIT is the re-acquisition the first mechanism test proved exists."""
    key = new_key()
    connection, plan, reservation = fresh(one, scratch, key)
    own_pid = pid_of(connection)
    plan.require(connection, canon_edit_requirement(scratch.gm_user, scratch.campaign_id))
    plan.finalize(connection)
    competitor = run_in_thread("competitor", lambda: _lock_campaign_update_and_commit(scratch))
    wait_until_pid_blocks(scratch.engine, own_pid)  # the competitor waits for the request
    plan.execute(connection, _step(plan, "ins_marker"), {"note": "n"})
    plan.execute(
        connection,
        _step(plan, "receipt"),
        {"r": reservation.idempotent_request_id, "s": 201, "b": {"ok": True}},
    )
    connection.commit()
    competitor.wait("the competitor proceeds after the request committed")
    connection.close()
    assert completed(scratch.engine, key) == 1


def _lock_campaign_update_and_commit(w: World) -> None:
    with w.engine.begin() as connection:
        connection.execute(
            text("SELECT 1 FROM campaign.campaigns WHERE campaign_id = :c FOR UPDATE"),
            {"c": w.campaign_id},
        ).all()


def test_the_receipt_update_and_commit_do_not_wait_on_the_held_actor_and_campaign_rows(
    scratch: World, one: Engine
) -> None:
    """plan + mechanism: the receipt UPDATE re-checks the actor FK (immediate) and queues another
    campaign check (deferred) because the reservation row was inserted by this very transaction
    [source: `RI_FKey_fk_upd_check_required` always fires for a row the current transaction inserted].
    Competitors queued `FOR UPDATE` on the actor's user row and on the campaign row wait for the request;
    the UPDATE and the COMMIT pass `lock_timeout` while they are queued, so neither re-check waited."""
    key = new_key()
    connection, plan, reservation = fresh(one, scratch, key)
    own_pid = pid_of(connection)
    plan.require(connection, canon_edit_requirement(scratch.gm_user, scratch.campaign_id))
    plan.finalize(connection)

    def lock_user() -> None:
        with scratch.engine.begin() as other:
            other.execute(
                text("SELECT 1 FROM security.users WHERE user_id = :u FOR UPDATE"),
                {"u": scratch.gm_user},
            ).all()

    users = run_in_thread("user", lock_user)
    campaigns = run_in_thread("campaign", lambda: _lock_campaign_update_and_commit(scratch))
    wait_until_pid_blocks(scratch.engine, own_pid, expected=2)
    plan.execute(connection, _step(plan, "ins_marker"), {"note": "n"})
    plan.execute(
        connection,
        _step(plan, "receipt"),
        {"r": reservation.idempotent_request_id, "s": 201, "b": {"ok": True}},
    )
    connection.commit()
    users.wait("user competitor")
    campaigns.wait("campaign competitor")
    connection.close()
    assert completed(scratch.engine, key) == 1


def test_deferral_with_no_bound_outcome_does_not_commit(scratch: World, one: Engine) -> None:
    """plan: a deferred plan that never reserved is refused at COMMIT (and at finalize), whatever else it
    did; the connection is left immediate."""
    connection, plan = open_plan(one, scratch, declarations())
    plan.defer_reservation_campaign_fk(connection)
    commit_refused(connection)
    assert plan.violation is R.OUTCOME
    connection.close()

    connection, plan = open_plan(one, scratch, declarations())
    plan.defer_reservation_campaign_fk(connection)
    with pytest.raises(AuthorizationPlanViolationError):
        plan.finalize(connection)
    assert plan.violation is R.DECLARATION  # no outcome means no declaration: refused first
    connection.close()
    assert_next_transaction_is_immediate(one, scratch)


def test_the_commit_guard_repeats_the_obligation_check(scratch: World, one: Engine) -> None:
    """plan (tamper test): a RESERVED deferred plan whose evidence is removed after `finalize` (which
    only a defect or hostile code can do) is refused at COMMIT, and so is one never finalized."""
    key = new_key()
    connection, plan, reservation = fresh(one, scratch, key)
    finish(connection, plan, scratch, reservation)
    plan._evidence.clear()
    commit_refused(connection)
    assert plan.violation is R.CAMPAIGN_EVIDENCE
    connection.close()
    assert reservations(scratch.engine, key) == 0

    connection, plan, reservation = fresh(one, scratch, new_key())
    commit_refused(connection)  # reserved, evidence held, never finalized
    connection.close()


# =====================================================================================================
# 6. Savepoints, rollback, cancellation, pooled reuse
# =====================================================================================================


def assert_next_transaction_is_immediate(engine: Engine, w: World) -> None:
    """The pooled connection is back at the default: a missing campaign fails at the INSERT."""
    with engine.connect() as connection:
        with connection.begin():
            with pytest.raises(IntegrityError, match="idempotent_requests_campaign_id_fkey"):
                connection.execute(
                    text(
                        "INSERT INTO security.idempotent_requests "
                        "(actor_user_id, campaign_id, idempotency_key, request_fingerprint) "
                        "VALUES (:u, :c, :k, 'f')"
                    ),
                    {"u": w.gm_user, "c": uuid.uuid4(), "k": new_key()},
                )


def test_a_savepoint_rollback_after_deferral_or_an_outcome_latches(
    scratch: World, one: Engine
) -> None:
    """plan: once the plan holds the deferral, a bound outcome or lock evidence, rolling a savepoint back
    latches `SAVEPOINT_ROLLBACK` and refuses the commit, so none of them can vanish unnoticed."""
    # after deferral
    connection, plan = open_plan(one, scratch, declarations())
    plan.defer_reservation_campaign_fk(connection)
    with contextlib.suppress(RuntimeError):
        with connection.begin_nested() as savepoint:
            savepoint.rollback()
    assert plan.violation is R.SAVEPOINT_ROLLBACK
    connection.close()

    # after the outcome (a replay would carry the same state)
    connection, plan = open_plan(one, scratch, declarations())
    plan.bind_reservation(connection, reserve(connection, scratch, new_key()))
    with connection.begin_nested() as savepoint:
        savepoint.rollback()
    assert plan.violation is R.SAVEPOINT_ROLLBACK
    commit_refused(connection)
    connection.close()

    # after evidence (the S1-C rule, unchanged)
    connection, plan, reservation = fresh(one, scratch, new_key())
    with connection.begin_nested() as savepoint:
        savepoint.rollback()
    assert plan.violation is R.SAVEPOINT_ROLLBACK
    commit_refused(connection)
    connection.close()


def test_a_released_savepoint_is_not_a_violation(scratch: World, one: Engine) -> None:
    """plan: a savepoint that is released (not rolled back) discards nothing, so it does not latch."""
    key = new_key()
    connection, plan, reservation = fresh(one, scratch, key)
    with connection.begin_nested():
        connection.execute(text("SELECT 1")).all()
    assert plan.violation is None
    finish(connection, plan, scratch, reservation)
    connection.commit()
    connection.close()
    assert completed(scratch.engine, key) == 1


def test_the_connection_is_immediate_again_after_commit_rollback_error_and_cancellation(
    scratch: World, one: Engine
) -> None:
    """plan: after a committed deferred request, a rolled-back one, a failed `finalize`, a database error
    and a cancellation, the same pooled connection (same backend pid) is at the immediate default."""
    pids: set[int] = set()

    def request(
        then: Callable[[Connection, AuthorizationPlan, IdempotentReservation], None],
    ) -> None:
        connection, plan, reservation = fresh(one, scratch, new_key())
        pids.add(pid_of(connection))
        try:
            then(connection, plan, reservation)
        finally:
            connection.close()

    def commit(
        connection: Connection, plan: AuthorizationPlan, reservation: IdempotentReservation
    ) -> None:
        finish(connection, plan, scratch, reservation)
        connection.commit()

    request(commit)
    assert_next_transaction_is_immediate(one, scratch)

    request(lambda connection, plan, reservation: connection.rollback())
    assert_next_transaction_is_immediate(one, scratch)

    def refuse(
        connection: Connection, plan: AuthorizationPlan, reservation: IdempotentReservation
    ) -> None:
        plan.require(
            connection,
            Requirement(
                name="deny",
                predicate=lambda snapshot: False,
                refusal=lambda: CampaignNotAuthorizedError("denied"),
            ),
        )
        with pytest.raises(CampaignNotAuthorizedError):
            plan.finalize(connection)

    request(refuse)
    assert_next_transaction_is_immediate(one, scratch)

    def db_error(
        connection: Connection, plan: AuthorizationPlan, reservation: IdempotentReservation
    ) -> None:
        plan.require(connection, canon_edit_requirement(scratch.gm_user, scratch.campaign_id))
        plan.finalize(connection)
        with pytest.raises(Exception):  # noqa: B017, PT011 - any driver error from the failed statement
            plan.execute(connection, _step(plan, "ins_marker"), {"note": None})

    request(db_error)
    assert_next_transaction_is_immediate(one, scratch)

    def cancelled(
        connection: Connection, plan: AuthorizationPlan, reservation: IdempotentReservation
    ) -> None:
        with pytest.raises(asyncio.CancelledError):
            raise asyncio.CancelledError

    request(cancelled)  # the request's transaction is abandoned, as T0's exit does
    assert_next_transaction_is_immediate(one, scratch)
    assert len(pids) == 1  # all of them ran on the one pooled connection


# =====================================================================================================
# 7. A real route: the default stays immediate
# =====================================================================================================


def test_a_keyed_authoring_route_still_waits_at_the_reservation_for_a_held_campaign_lock(
    scratch: World,
) -> None:
    """route: `POST .../authoring/locations` (accepted, unchanged by S5-C) blocks at its reservation INSERT
    while another session holds the campaign `FOR UPDATE`, completes after the release, and creates the
    location once: its constraint mode is the default (immediate) and no plan on it opts in."""
    key = new_key()
    name = f"S5-C {uuid.uuid4().hex[:6]}"
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: scratch.engine
    app.dependency_overrides[get_authenticated_user_id] = lambda: oidc_principal(scratch.gm_user)

    def call() -> Any:
        with TestClient(app, raise_server_exceptions=False) as client:
            return client.post(
                f"{scratch.base}/authoring/locations",
                json={"category": "region", "name": name},
                headers={"Idempotency-Key": key},
            )

    holder, holder_pid = hold_campaign(scratch.engine, scratch.campaign_id)
    request = run_in_thread("route", call)
    try:
        wait_until_pid_blocks(scratch.engine, holder_pid)
        assert not request.finished()
    finally:
        release(holder)
    response = request.wait("the route completes after the holder released")
    assert response.status_code == 201, response.text
    assert reservations(scratch.engine, key) == 1
    assert completed(scratch.engine, key) == 1

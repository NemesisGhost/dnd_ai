"""R01 authorization plans: the fail-closed final check (docs/R01_FRESH_AUTHORIZATION_PLAN_2026-11-12.md,
sections 6.2, 6.5 and 6.9-6.11).

A protected write registers **requirements** (a fact captured under lock, an authority predicate over
one `AuthoritySnapshot`, and the exact error its early counterpart raises today) in an
`AuthorizationPlan`, then runs `plan.finalize(connection)` as its last decision statement. The snapshot is
read by ONE statement at one `t_auth`, so every predicate judges one coherent state.

**The guard.** One set of listeners on the application engine (`install_authorization_guard`) makes the
plan fail closed:

- COMMIT is refused while a plan bound to the connection is *open* (registered and never finalised,
  and not explicitly pending), *violated*, or (pre-write) *incomplete*;
- every statement after `finalize` is checked against the plan's **mode**, fixed when the plan is
  created and never changeable:
  - `PlanMode.POST_WRITE`: no statement at all may follow the final one (not even a `SELECT`);
  - `PlanMode.PRE_WRITE`: only statements issued through `plan.execute` may follow, each one a declared
    `WriteStep` run with a validated, frozen parameter snapshot (see below). Row locks are taken before
    `finalize`, through `plan.lock`, and only those are lock evidence.
- the refusal rolls the DBAPI connection back before it raises `AuthorizationPlanNotFinalizedError`
  (defence in depth: the request path does not rely on it, T0's exit abandons the transaction itself).

**Pre-write guarantees** (plan 6.11.8, as bounded by the S1 correction):

1. What reaches the driver is the declared statement with the validated snapshot. The snapshot is an
   immutable copy; the mutable mapping handed to SQLAlchemy is a thawed input nobody reads as evidence.
   The guard compares the statement string and every driver value with the snapshot at the last hop
   (`do_execute`) and dispatches the statement itself.
2. Session assumptions are enforced on the bound connection, before lock evidence and before
   `finalize`: `session_replication_role = origin`, no explicit `pg_catalog` in `search_path`, no
   lookalike comparison operators for the key types.
3. Event registrations are fixed from the plan's creation until the plan ends. The guard compares a
   listener fingerprint with the one taken at creation; a change is refused before the driver call when
   the guard still runs first, and is otherwise **detected after execution** (C4): rollback cannot reverse
   a sequence advance or any other non-transactional effect, so detection is not prevention. Arbitrary
   hostile in-process Python (rewriting the guard's own state, `object.__setattr__`, another thread on
   the same connection) is outside the supported guarantee.
4. An `UPDATE` touches only a locked target row, confirmed by the validated `RETURNING` primary key.
   A repeated target key within one declared step is refused for every cardinality; attempts and
   confirmed results are separate state.
5. Every attempted execution that reaches a guard-observable event is admitted or refused by the guard;
   failures inside `plan.execute` / `plan.lock` latch. A direct Python/SQLAlchemy call rejected before
   its first event is not observed or latched and sends no database execution. If required steps remain
   incomplete, commit is refused. If all required steps already completed, that rejected call does not by
   itself prevent commit.

Nothing here proves that a statement cannot block: trigger callees, dynamic SQL, unique-index waits and
business-rule lock completeness remain S5 obligations.

`AuthorizationPlanNotFinalizedError` and `AuthorizationPlanViolationError` are **direct** `RuntimeError`
subclasses. They must never derive from `ValueError`, `SafeMessageError` or `ApiError`: those map to a 4xx,
and a refused commit is a 5xx.

`R01_PENDING` is the explicit marker a scope helper receives where its family has not been migrated to
a plan yet. Passing it protects nothing; a unit test pins the exact call sites that still pass it.
"""

import enum
import threading
import uuid
import weakref
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final, NoReturn, Self

from sqlalchemy import Connection, Engine, event, text
from sqlalchemy.engine.interfaces import ExecuteStyle

from .access import FRESH_INSTANT, AuthoritySnapshot, read_authority_snapshot
from .authorization_steps import (
    REVIEWED_EXECUTION_OPTIONS,
    Between,
    BindSpec,
    Exactly,
    Kind,
    ParameterError,
    PreLock,
    PreWriteDeclaration,
    RowExpectation,
    WriteStep,
    freeze_value,
    kind_of,
    matches_driver,
    matches_extracted,
    thaw_value,
)


class AuthorizationPlanNotFinalizedError(RuntimeError):
    """The commit guard's refusal: a plan bound to the connection is open, violated or incomplete.

    A **direct** `RuntimeError` subclass, pinned by a unit test (MRO) and an HTTP test (fixed 500
    body): the API maps `RuntimeError` to the fixed 5xx, whereas a `ValueError`, `SafeMessageError` or
    `ApiError` would surface as a 4xx on an unfinalised write (R01 S0, finding F-3). The message is
    fixed and carries no identifier."""

    def __init__(self, reason: str = "an authorization plan was not finalized") -> None:
        super().__init__(reason)


class AuthorizationPlanViolationError(RuntimeError):
    """The guard refused a statement, or a controlled execution failed validation. A direct
    `RuntimeError` subclass with a fixed message (a fixed 5xx); `plan.violation` carries the reason for
    tests and diagnostics, never for a client."""

    def __init__(self) -> None:
        super().__init__("an authorization plan refused a statement")


class AuthorizationPlanBindingError(RuntimeError):
    """A plan was used on a connection or transaction other than the one it is bound to (plan section
    6.5, rule 2). A direct `RuntimeError` subclass: a programming error, a fixed 5xx."""

    def __init__(self) -> None:
        super().__init__("an authorization plan is bound to a different connection or transaction")


class AuthorizationPlanStateError(RuntimeError):
    """A plan was used out of sequence (a requirement registered after `finalize`)."""

    def __init__(self) -> None:
        super().__init__("an authorization plan was used out of sequence")


class PlanMode(enum.Enum):
    """How the guard polices statements after `finalize`. Fixed when the plan is created."""

    POST_WRITE = "post_write"
    PRE_WRITE = "pre_write"


class ViolationReason(enum.Enum):
    """The first latched reason a plan is violated. Never sent to a client."""

    POST_WRITE_STATEMENT = "post_write_statement"
    UNCONTROLLED = "uncontrolled"
    NO_IDENTITY = "no_identity"
    IDENTITY = "identity"
    EXECUTEMANY = "executemany"
    RENDERING = "rendering"
    PARAMETERS = "parameters"
    EXECUTION_OPTIONS = "execution_options"
    ORDER = "order"
    COUNT = "count"
    DUPLICATE_TARGET = "duplicate_target"
    TARGET_NOT_LOCKED = "target_not_locked"
    FK_NOT_LOCKED = "fk_not_locked"
    FK_PARTIAL_NULL = "fk_partial_null"
    EXECUTION_FAILED = "execution_failed"
    LOCK_FAILED = "lock_failed"
    LOCK_AFTER_FINALIZE = "lock_after_finalize"
    SAVEPOINT_ROLLBACK = "savepoint_rollback"
    INCOMPLETE = "incomplete"
    ROWCOUNT = "rowcount"
    REENTRANT = "reentrant"
    SIDE_EXECUTION = "side_execution"
    LISTENER_ORDER = "listener_order"
    LISTENER_TOPOLOGY = "listener_topology"
    DISPATCH_BYPASSED = "dispatch_bypassed"
    SESSION = "session"
    BINDING = "binding"
    SEQUENCE = "sequence"
    INTERNAL = "internal"


class _Pending:
    """The type of `R01_PENDING`."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "R01_PENDING"


#: What a scope helper receives where its family has not been migrated to an `AuthorizationPlan`.
#: It protects nothing and registers nothing. `tests/unit/test_r01_pending_call_sites.py` pins every
#: call site that passes it; that set only shrinks.
R01_PENDING: Final = _Pending()


@dataclass(frozen=True)
class Requirement:
    """One authority requirement of a decision.

    - `name`: a label for tests and diagnostics (never sent to a client).
    - `predicate`: judged over the one `AuthoritySnapshot`; it must read only sources the requirement
      declares through `world_id` / `reveal`.
    - `refusal`: builds the exact error the early check raises today; the plan raises it unchanged.
    - `world_id`: the world whose authority the snapshot must carry, if any.
    - `reveal`: whether the snapshot must carry the caller's reveal authority.

    Facts captured under lock earlier (origins, restriction state, the reveal source...) are closed
    over by `predicate`; the final check never re-derives operation facts from post-write rows."""

    name: str
    predicate: Callable[[AuthoritySnapshot], bool]
    refusal: Callable[[], BaseException]
    world_id: uuid.UUID | None = None
    reveal: bool = False


@dataclass(frozen=True)
class StepOutcome:
    """What `plan.execute` returns: the primary keys of the rows the API confirmed the step wrote,
    validated and immutable. No other `RETURNING` payload exists, and the live `CursorResult` is closed
    inside the API and never returned. Empty only for a `ZERO_OR_ONE` step that wrote nothing."""

    step: str
    keys: tuple[tuple[Any, ...], ...]


# -- controlled execution state ---------------------------------------------------------------------


@dataclass(frozen=True)
class _Canon:
    """The framework's own compilation of a declared statement for the connection's dialect."""

    string: str
    keys: frozenset[str]
    embedded: Mapping[str, object]


_CANON: "weakref.WeakKeyDictionary[Any, dict[tuple[type, tuple[str, ...]], _Canon]]" = (
    weakref.WeakKeyDictionary()
)


def _canon_for(subject: WriteStep | PreLock, dialect: Any, names: tuple[str, ...]) -> _Canon:
    cache = _CANON.setdefault(subject, {})
    key = (type(dialect), names)
    canon = cache.get(key)
    if canon is None:
        compiled = subject.statement.compile(dialect=dialect, column_keys=list(names))
        canon = _Canon(
            string=compiled.string,
            keys=frozenset(compiled.binds),
            embedded=MappingProxyType(
                {k: b.value for k, b in compiled.binds.items() if not b.required}
            ),
        )
        cache[key] = canon
    return canon


@dataclass(eq=False)
class _Flight:
    """The one-use token (a step) or permit (a lock) for exactly one controlled execution."""

    kind: str
    subject: WriteStep | PreLock
    names: tuple[str, ...]
    specs: Mapping[str, BindSpec]
    frozen: Mapping[str, object]
    call_params: dict[str, object]
    canon: _Canon
    topology: tuple[object, ...]
    before_events: int = 0
    cursor_events: int = 0
    dispatched: bool = False
    completed: bool = False


_CONNECTION_EVENTS: Final = (
    "before_execute",
    "after_execute",
    "before_cursor_execute",
    "after_cursor_execute",
    "rollback_savepoint",
    "commit",
    "rollback",
)
_DIALECT_EVENTS: Final = ("do_execute", "do_executemany", "do_execute_no_params", "handle_error")


def _topology(connection: Connection) -> tuple[object, ...]:
    """A fingerprint of every listener collection the guard's guarantees depend on, as the connection
    sees them (engine-level, class-level and connection-level listeners)."""
    parts: list[object] = []
    dispatch = connection.dispatch
    for name in _CONNECTION_EVENTS:
        parts.append(tuple(getattr(dispatch, name)))
    dialect_dispatch = connection.dialect.dispatch
    for name in _DIALECT_EVENTS:
        parts.append(tuple(getattr(dialect_dispatch, name)))
    return tuple(parts)


_SESSION_SQL: Final = text(
    "SELECT pg_catalog.current_setting('search_path'), "
    "pg_catalog.current_setting('session_replication_role'), "
    "EXISTS (SELECT 1 FROM pg_catalog.pg_operator o "
    "JOIN pg_catalog.pg_namespace n ON n.oid = o.oprnamespace "
    "WHERE n.nspname <> 'pg_catalog' "
    "AND o.oprname IN ('=', '<>', '<', '<=', '>', '>=') "
    "AND (o.oprleft = ANY (ARRAY['pg_catalog.uuid'::pg_catalog.regtype, "
    "'pg_catalog.int2'::pg_catalog.regtype, 'pg_catalog.int4'::pg_catalog.regtype, "
    "'pg_catalog.int8'::pg_catalog.regtype]) "
    "OR o.oprright = ANY (ARRAY['pg_catalog.uuid'::pg_catalog.regtype, "
    "'pg_catalog.int2'::pg_catalog.regtype, 'pg_catalog.int4'::pg_catalog.regtype, "
    "'pg_catalog.int8'::pg_catalog.regtype])))"
)


def _search_path_lists_pg_catalog(value: str) -> bool:
    return any(part.strip().strip('"').lower() == "pg_catalog" for part in value.split(","))


def _validate_key(kinds: tuple[Kind, ...], row: object) -> tuple[Any, ...] | None:
    """The row as a key tuple if its arity and exact types are those of `kinds` and nothing is NULL."""
    if not isinstance(row, (tuple, list)) or len(row) != len(kinds):
        return None
    for kind, value in zip(kinds, row, strict=True):
        if kind is Kind.UUID:
            if type(value) is not uuid.UUID:
                return None
        elif kind is Kind.INT:
            if type(value) is not int:
                return None
        else:
            return None
    return tuple(row)


class AuthorizationPlan:
    """The requirements of one request's protected write, bound to one connection and one
    transaction. See the module docstring. Create it with `begin`; register requirements with
    `require`; end the decision with `finalize`."""

    __slots__ = (
        "__weakref__",
        "_actor_user_id",
        "_attempted_keys",
        "_attempts",
        "_baseline",
        "_campaign_id",
        "_confirmed",
        "_connection",
        "_cursor",
        "_declaration",
        "_evidence",
        "_finalised",
        "_flight",
        "_mode",
        "_pending",
        "_reading",
        "_requirements",
        "_snapshot",
        "_transaction",
        "_violated",
        "_violation",
    )

    def __init__(
        self,
        connection: Connection,
        *,
        actor_user_id: uuid.UUID,
        campaign_id: uuid.UUID,
        mode: PlanMode,
        pre_write: PreWriteDeclaration | None,
        pending: bool,
    ) -> None:
        transaction = connection.get_transaction()
        if transaction is None:
            raise AuthorizationPlanBindingError()
        if mode is PlanMode.POST_WRITE and pre_write is not None:
            raise ValueError("a post-write plan declares no pre-write steps")
        if mode is PlanMode.PRE_WRITE and pre_write is None:
            raise ValueError("a pre-write plan must declare its pre-write steps")
        self._connection = connection
        self._transaction = transaction
        self._actor_user_id = actor_user_id
        self._campaign_id = campaign_id
        self._mode = mode
        self._declaration = pre_write
        self._pending = pending
        self._requirements: list[Requirement] = []
        self._finalised = False
        self._violated = False
        self._violation: ViolationReason | None = None
        self._reading = False
        self._snapshot: AuthoritySnapshot | None = None
        self._flight: _Flight | None = None
        self._baseline: tuple[object, ...] | None = None
        self._evidence: dict[PreLock, set[tuple[Any, ...]]] = {}
        step_count = len(pre_write.steps) if pre_write is not None else 0
        self._attempts = [0] * step_count
        self._attempted_keys: list[set[tuple[Any, ...]]] = [set() for _ in range(step_count)]
        self._confirmed: list[list[tuple[Any, ...]]] = [[] for _ in range(step_count)]
        self._cursor = 0

    @classmethod
    def begin(
        cls,
        connection: Connection,
        *,
        actor_user_id: uuid.UUID,
        campaign_id: uuid.UUID,
        mode: PlanMode = PlanMode.POST_WRITE,
        pre_write: PreWriteDeclaration | None = None,
        pending: bool = False,
    ) -> Self:
        """Open a plan on `connection`'s current transaction and register it with the commit guard
        (installing the guard on the connection's engine if it is not installed yet). `pending`
        marks a route whose handler has not migrated: the guard admits it while unfinalised.

        A pre-write plan records the listener fingerprint here: registrations must be fixed from now
        until the plan ends."""
        install_authorization_guard(connection.engine)
        plan = cls(
            connection,
            actor_user_id=actor_user_id,
            campaign_id=campaign_id,
            mode=mode,
            pre_write=pre_write,
            pending=pending,
        )
        if mode is PlanMode.PRE_WRITE:
            plan._baseline = _topology(connection)
        with _LOCK:
            _BOUND.setdefault(connection, []).append(plan)
        return plan

    # -- read-only state -------------------------------------------------------------------------

    @property
    def mode(self) -> PlanMode:
        return self._mode

    @property
    def pending(self) -> bool:
        return self._pending

    @property
    def finalised(self) -> bool:
        return self._finalised

    @property
    def violated(self) -> bool:
        return self._violated

    @property
    def violation(self) -> ViolationReason | None:
        """The first latched reason, for tests and diagnostics only."""
        return self._violation

    @property
    def actor_user_id(self) -> uuid.UUID:
        return self._actor_user_id

    @property
    def campaign_id(self) -> uuid.UUID:
        return self._campaign_id

    @property
    def snapshot(self) -> AuthoritySnapshot | None:
        """The snapshot `finalize` judged, once it succeeded."""
        return self._snapshot

    @property
    def requirements(self) -> tuple[Requirement, ...]:
        return tuple(self._requirements)

    def evidence(self, lock: PreLock) -> frozenset[tuple[Any, ...]]:
        """The key tuples a successful `plan.lock` of `lock` returned (a union over calls)."""
        return frozenset(self._evidence.get(lock, ()))

    def confirmed(self, step: WriteStep) -> tuple[tuple[Any, ...], ...]:
        """The key tuples the API confirmed `step` wrote, in order."""
        assert self._declaration is not None
        index = self._declaration.index_of_step(step)
        return tuple(self._confirmed[index]) if index is not None else ()

    def attempts(self, step: WriteStep) -> int:
        assert self._declaration is not None
        index = self._declaration.index_of_step(step)
        return self._attempts[index] if index is not None else 0

    # -- latching --------------------------------------------------------------------------------

    def _latch(self, reason: ViolationReason) -> None:
        """Record the first reason. Later failures never overwrite it."""
        self._violated = True
        if self._violation is None:
            self._violation = reason

    def _refuse(self, reason: ViolationReason) -> NoReturn:
        self._latch(reason)
        raise AuthorizationPlanViolationError()

    # -- use -------------------------------------------------------------------------------------

    def _check_bound(self, connection: Connection) -> None:
        if connection is not self._connection or connection.get_transaction() is not (
            self._transaction
        ):
            raise AuthorizationPlanBindingError()

    def require(self, connection: Connection, requirement: Requirement) -> None:
        """Register `requirement`, in early-check order. Raises if `connection` or its transaction is
        not the one this plan is bound to, or after `finalize`."""
        self._check_bound(connection)
        if self._finalised:
            self._latch(ViolationReason.SEQUENCE)
            raise AuthorizationPlanStateError()
        declared = {r.world_id for r in self._requirements if r.world_id is not None}
        if requirement.world_id is not None and declared - {requirement.world_id}:
            raise ValueError("a plan's requirements name one world")
        self._requirements.append(requirement)

    def _verify_session(self, connection: Connection) -> None:
        """Enforce the session assumptions on the actual bound connection (plan 6.11.6): replication
        role `origin`, `pg_catalog` not listed explicitly in `search_path`, and no lookalike comparison
        operator for the key types. Run before lock evidence and before `finalize`."""
        try:
            search_path, role, lookalike = connection.execute(_SESSION_SQL).one()
        except BaseException:
            self._latch(ViolationReason.SESSION)
            raise
        if (
            role != "origin"
            or _search_path_lists_pg_catalog(str(search_path))
            or lookalike is not False
        ):
            self._refuse(ViolationReason.SESSION)

    def _check_listeners(self, connection: Connection) -> None:
        """C0: the guard's `do_execute` listener runs first, and the registrations are those recorded
        when the plan was created."""
        dispatch = list(connection.dialect.dispatch.do_execute)
        if not dispatch or dispatch[0] is not _on_do_execute:
            self._refuse(ViolationReason.LISTENER_ORDER)
        if _topology(connection) != self._baseline:
            self._refuse(ViolationReason.LISTENER_TOPOLOGY)

    def finalize(self, connection: Connection) -> AuthoritySnapshot | None:
        """The final check: read every declared source in one statement at one `t_auth`, then judge
        the requirements in registration order, raising the first failing requirement's own error.
        On success the plan is finalised and the guard polices what follows (the module docstring).

        A plan with no requirement has nothing to judge: it reads nothing and returns `None`. A second
        `finalize` violates the plan (it would be a statement after the final one) and raises.

        A pre-write plan first verifies the session assumptions and the listener registrations."""
        self._check_bound(connection)
        if self._finalised:
            self._latch(ViolationReason.SEQUENCE)
            raise AuthorizationPlanNotFinalizedError("an authorization plan was finalized twice")
        if self._mode is PlanMode.PRE_WRITE:
            if self._flight is not None:
                self._refuse(ViolationReason.REENTRANT)
            if self._violated:
                raise AuthorizationPlanViolationError()
            self._check_listeners(connection)
            self._verify_session(connection)
        if not self._requirements:
            self._finalised = True
            return None
        world_ids = {r.world_id for r in self._requirements if r.world_id is not None}
        self._reading = True
        try:
            snapshot = read_authority_snapshot(
                connection,
                user_id=self._actor_user_id,
                campaign_id=self._campaign_id,
                world_id=next(iter(world_ids)) if world_ids else None,
                with_reveal=any(r.reveal for r in self._requirements),
                as_of=FRESH_INSTANT,
            )
        finally:
            self._reading = False
        for requirement in self._requirements:
            if not requirement.predicate(snapshot):
                raise requirement.refusal()
        self._snapshot = snapshot
        self._finalised = True
        return snapshot

    # -- controlled pre-write execution ------------------------------------------------------------

    def _begin_call(self, connection: Connection, *, locking: bool) -> PreWriteDeclaration:
        """Entry checks shared by `lock` and `execute`, before any SQLAlchemy call."""
        try:
            self._check_bound(connection)
        except AuthorizationPlanBindingError:
            self._latch(ViolationReason.BINDING)
            raise
        if self._mode is not PlanMode.PRE_WRITE or self._declaration is None:
            self._latch(ViolationReason.SEQUENCE)
            raise AuthorizationPlanStateError()
        if self._flight is not None:
            self._refuse(ViolationReason.REENTRANT)
        if locking and self._finalised:
            self._latch(ViolationReason.LOCK_AFTER_FINALIZE)
            raise AuthorizationPlanStateError()
        if not locking and not self._finalised:
            self._latch(ViolationReason.SEQUENCE)
            raise AuthorizationPlanStateError()
        if self._violated:
            raise AuthorizationPlanViolationError()
        self._check_listeners(connection)
        return self._declaration

    def _build_snapshot(
        self, specs: Mapping[str, BindSpec], params: object
    ) -> tuple[Mapping[str, object], dict[str, object]]:
        """Validate the caller's mapping once, and return the immutable snapshot and a fresh thawed
        dict for SQLAlchemy. The caller's mapping and everything inside it is never passed on."""
        if not isinstance(params, Mapping):
            self._refuse(ViolationReason.PARAMETERS)
        try:
            copied = dict(params)
        except Exception:
            self._refuse(ViolationReason.PARAMETERS)
        if any(type(key) is not str for key in copied) or set(copied) != set(specs):
            self._refuse(ViolationReason.PARAMETERS)
        try:
            frozen = {name: freeze_value(specs[name], copied[name]) for name in sorted(specs)}
        except ParameterError:
            self._refuse(ViolationReason.PARAMETERS)
        call_params = {name: thaw_value(specs[name], value) for name, value in frozen.items()}
        return MappingProxyType(frozen), call_params

    def _issue(
        self,
        connection: Connection,
        kind: str,
        subject: WriteStep | PreLock,
        frozen: Mapping[str, object],
        call_params: dict[str, object],
    ) -> _Flight:
        names = tuple(sorted(frozen))
        canon = _canon_for(subject, connection.dialect, names)
        flight = _Flight(
            kind=kind,
            subject=subject,
            names=names,
            specs=subject.specs,
            frozen=frozen,
            call_params=call_params,
            canon=canon,
            topology=_topology(connection),
        )
        self._flight = flight
        return flight

    def lock(
        self, connection: Connection, prelock: PreLock, params: Mapping[str, object]
    ) -> tuple[tuple[Any, ...], ...]:
        """Run the declared `prelock` itself, before `finalize`, and record the keys it returned as
        lock evidence. Evidence exists only for rows a successful, validated call returned; a failed,
        refused or interrupted call records nothing and latches."""
        declaration = self._begin_call(connection, locking=True)
        if not declaration.has_lock(prelock):
            self._refuse(ViolationReason.IDENTITY)
        self._verify_session(connection)
        frozen, call_params = self._build_snapshot(prelock.specs, params)
        flight = self._issue(connection, "lock", prelock, frozen, call_params)
        kinds = tuple(kind_of(column)[0] for column in prelock.key)
        result = None
        failed = False
        try:
            try:
                result = connection.execute(prelock.statement, call_params)
                rows = tuple(tuple(row) for row in result.all())
            finally:
                if result is not None:
                    failed = self._close(result)
            if self._violated:
                raise AuthorizationPlanViolationError()
            keys: list[tuple[Any, ...]] = []
            for row in rows:
                key = _validate_key(kinds, row)
                if key is None:
                    self._refuse(ViolationReason.LOCK_FAILED)
                keys.append(key)
            if len(set(keys)) != len(keys):
                self._refuse(ViolationReason.LOCK_FAILED)
            if flight.cursor_events != 1 or not flight.dispatched or not flight.completed:
                self._refuse(ViolationReason.LOCK_FAILED)
            if failed:
                self._refuse(ViolationReason.INTERNAL)
            self._evidence.setdefault(prelock, set()).update(keys)
            return tuple(keys)
        except BaseException:
            self._latch(ViolationReason.LOCK_FAILED)
            raise
        finally:
            self._flight = None

    @staticmethod
    def _close(result: Any) -> bool:
        """Close the CursorResult. A close failure never masks an exception in flight; it is reported
        so the success path can latch it."""
        try:
            result.close()
        except Exception:
            return True
        return False

    def _skippable(self, index: int) -> bool:
        assert self._declaration is not None
        step = self._declaration.steps[index]
        cardinality = step.cardinality
        if isinstance(cardinality, Exactly):
            return False
        if isinstance(cardinality, Between):
            return cardinality.low == 0
        if cardinality.complete:
            return not self._evidence.get(step.target_lock, ()) if step.target_lock else True
        return True

    def _lower_bound_met(self, index: int) -> bool:
        assert self._declaration is not None
        step = self._declaration.steps[index]
        cardinality = step.cardinality
        confirmed = self._confirmed[index]
        if isinstance(cardinality, Exactly):
            return len(confirmed) == cardinality.n
        if isinstance(cardinality, Between):
            return len(confirmed) >= cardinality.low
        if not cardinality.complete:
            return True
        assert step.target_lock is not None
        required = self._evidence.get(step.target_lock, set())
        return len(confirmed) == len(set(confirmed)) and set(confirmed) == required

    def _incomplete(self) -> bool:
        if self._mode is not PlanMode.PRE_WRITE or not self._finalised or self._declaration is None:
            return False
        return not all(self._lower_bound_met(i) for i in range(len(self._declaration.steps)))

    def execute(
        self, connection: Connection, step: WriteStep, params: Mapping[str, object]
    ) -> StepOutcome:
        """Run the declared `step` itself, after `finalize`, with a validated and frozen parameter
        snapshot, and return the primary keys the API confirmed. Every refusal latches before it
        raises; a failure inside the call latches and re-raises the original exception unchanged."""
        declaration = self._begin_call(connection, locking=False)
        index = declaration.index_of_step(step)
        if index is None:
            self._refuse(ViolationReason.IDENTITY)
        frozen, call_params = self._build_snapshot(step.specs, params)
        target = self._check_admission(step, index, frozen)
        # consume: attempts are never refunded
        self._attempts[index] += 1
        if target is not None:
            self._attempted_keys[index].add(target)
        self._cursor = index
        flight = self._issue(connection, "step", step, frozen, call_params)
        result = None
        failed = False
        try:
            try:
                result = connection.execute(step.statement, call_params)
                rowcount = result.rowcount
                rows = tuple(tuple(row) for row in result.all())
            finally:
                if result is not None:
                    failed = self._close(result)
            if self._violated:
                raise AuthorizationPlanViolationError()
            keys = self._validate_rows(step, frozen, target, rowcount, rows)
            if flight.cursor_events != 1 or not flight.dispatched or not flight.completed:
                self._refuse(ViolationReason.INTERNAL)
            if failed:
                self._refuse(ViolationReason.INTERNAL)
            self._confirmed[index].extend(keys)
            return StepOutcome(step=step.name, keys=keys)
        except BaseException:
            self._latch(ViolationReason.EXECUTION_FAILED)
            raise
        finally:
            self._flight = None

    def _check_admission(
        self, step: WriteStep, index: int, frozen: Mapping[str, object]
    ) -> tuple[Any, ...] | None:
        """Order, count, target evidence, duplicate-target and FK checks, before SQLAlchemy."""
        assert self._declaration is not None
        target: tuple[Any, ...] | None = None
        if step.is_update:
            values = tuple(frozen[kb.bind] for kb in step.target)
            if any(value is None for value in values):
                self._refuse(ViolationReason.PARAMETERS)
            target = values
        if index < self._cursor:
            self._refuse(ViolationReason.ORDER)
        for j in range(self._cursor, index):
            if self._attempts[j] == 0 and not self._skippable(j):
                self._refuse(ViolationReason.ORDER)
        cardinality = step.cardinality
        attempts = self._attempts[index]
        if isinstance(cardinality, Exactly) and attempts >= cardinality.n:
            self._refuse(ViolationReason.COUNT)
        if isinstance(cardinality, Between) and attempts >= cardinality.high:
            self._refuse(ViolationReason.COUNT)
        if target is not None:
            # A repeated target key within one declared step is refused for every cardinality.
            if target in self._attempted_keys[index]:
                self._refuse(ViolationReason.DUPLICATE_TARGET)
            assert step.target_lock is not None
            if target not in self._evidence.get(step.target_lock, ()):
                self._refuse(ViolationReason.TARGET_NOT_LOCKED)
        for binding in step.fks:
            values = tuple(frozen[kb.bind] for kb in binding.binds)
            nulls = sum(value is None for value in values)
            if nulls == len(values):
                continue
            if nulls:
                self._refuse(ViolationReason.FK_PARTIAL_NULL)
            if binding.lock is not None and values not in self._evidence.get(binding.lock, ()):
                self._refuse(ViolationReason.FK_NOT_LOCKED)
        return target

    def _validate_rows(
        self,
        step: WriteStep,
        frozen: Mapping[str, object],
        target: tuple[Any, ...] | None,
        rowcount: int,
        rows: tuple[tuple[Any, ...], ...],
    ) -> tuple[tuple[Any, ...], ...]:
        if rowcount != len(rows):
            self._refuse(ViolationReason.ROWCOUNT)
        keys: list[tuple[Any, ...]] = []
        for row in rows:
            key = _validate_key(step.pk_kinds, row)
            if key is None:
                self._refuse(ViolationReason.ROWCOUNT)
            keys.append(key)
        if step.is_update:
            if step.rows is RowExpectation.ZERO_OR_ONE and not keys:
                return ()  # attempted, never confirmed
            if len(keys) != 1 or keys[0] != target:
                self._refuse(ViolationReason.ROWCOUNT)
            return (keys[0],)
        if len(keys) != 1:
            self._refuse(ViolationReason.ROWCOUNT)
        key = keys[0]
        for position, bind in enumerate(step.pk_binds):
            if bind is not None and frozen[bind] != key[position]:
                self._refuse(ViolationReason.ROWCOUNT)
        if step.identity_pk and not all(value > 0 for value in key):
            self._refuse(ViolationReason.ROWCOUNT)
        return (key,)

    # -- guard internals -------------------------------------------------------------------------

    def _is_current(self, connection: Connection) -> bool:
        return connection is self._connection and connection.get_transaction() is self._transaction

    def _refuses_commit(self) -> bool:
        if self._violated:
            return True
        if self._flight is not None:
            self._latch(ViolationReason.INTERNAL)
            return True
        if self._incomplete():
            self._latch(ViolationReason.INCOMPLETE)
            return True
        return not self._finalised and not self._pending

    def _controlled(self) -> bool:
        """Whether this plan's pre-write statement rules apply right now."""
        return (
            self._mode is PlanMode.PRE_WRITE
            and not self._reading
            and (self._finalised or self._flight is not None)
        )

    def _observe_statement(self) -> None:
        """Post-write: every statement after `finalize` violates the plan. Statements before it and
        the final statement itself are free. (Behaviour unchanged from S1.)"""
        if self._reading or not self._finalised or self._violated:
            return
        if self._mode is PlanMode.POST_WRITE:
            self._latch(ViolationReason.POST_WRITE_STATEMENT)

    def _guard_flight(self) -> _Flight:
        """The flight a pre-write statement must belong to, or an `UNCONTROLLED` refusal."""
        if self._flight is None:
            self._refuse(ViolationReason.UNCONTROLLED)
        return self._flight

    def _on_before_execute(
        self,
        connection: Connection,
        element: object,
        multiparams: object,
        params: object,
        options: object,
    ) -> None:
        if not self._controlled():
            return
        if self._violated:
            raise AuthorizationPlanViolationError()
        flight = self._guard_flight()
        flight.before_events += 1
        if flight.before_events > 1:
            self._refuse(ViolationReason.SIDE_EXECUTION)
        if element is not flight.subject.statement:
            self._refuse(ViolationReason.IDENTITY)
        if multiparams != [] or params is not flight.call_params:
            self._refuse(ViolationReason.PARAMETERS)
        if dict(options) != dict(REVIEWED_EXECUTION_OPTIONS):  # type: ignore[call-overload]
            self._refuse(ViolationReason.EXECUTION_OPTIONS)
        if _topology(connection) != flight.topology:
            self._refuse(ViolationReason.LISTENER_TOPOLOGY)
        if not self._values_match(flight, params, driver=False):
            self._refuse(ViolationReason.PARAMETERS)

    def _on_before_cursor_execute(
        self,
        connection: Connection,
        statement: str,
        context: Any,
        executemany: bool,
    ) -> None:
        if self._reading:
            return
        if self._mode is PlanMode.POST_WRITE:
            self._observe_statement()
            return
        if not self._controlled():
            return
        if self._violated:
            raise AuthorizationPlanViolationError()
        flight = self._guard_flight()
        flight.cursor_events += 1
        if flight.cursor_events > 1:
            self._refuse(ViolationReason.SIDE_EXECUTION)
        if context is None or context.isddl or context.invoked_statement is None:
            self._refuse(ViolationReason.NO_IDENTITY)
        if context.invoked_statement is not flight.subject.statement:
            self._refuse(ViolationReason.IDENTITY)
        if (
            executemany
            or context.execute_style is not ExecuteStyle.EXECUTE
            or len(context.compiled_parameters) != 1
        ):
            self._refuse(ViolationReason.EXECUTEMANY)
        if dict(context.execution_options) != dict(REVIEWED_EXECUTION_OPTIONS):
            self._refuse(ViolationReason.EXECUTION_OPTIONS)
        if statement != flight.canon.string:
            self._refuse(ViolationReason.RENDERING)
        if _topology(connection) != flight.topology:
            self._refuse(ViolationReason.LISTENER_TOPOLOGY)
        if not self._values_match(flight, context.compiled_parameters[0], driver=False):
            self._refuse(ViolationReason.PARAMETERS)

    def _values_match(self, flight: _Flight, mapping: object, *, driver: bool) -> bool:
        """The mapping has exactly the canonical key set, the supplied values equal the snapshot (in the
        extracted or the driver form), and the embedded literals are the declared ones."""
        if not isinstance(mapping, Mapping) or set(mapping) != flight.canon.keys:
            return False
        compare = matches_driver if driver else matches_extracted
        for name in flight.names:
            if not compare(flight.specs[name], flight.frozen[name], mapping[name]):
                return False
        for key, expected in flight.canon.embedded.items():
            actual = mapping[key]
            if type(actual) is not type(expected) or actual != expected:
                return False
        return True

    def _on_do_execute(
        self, connection: Connection, cursor: Any, statement: str, parameters: object, context: Any
    ) -> bool:
        if not self._controlled():
            return False
        if self._violated:
            raise AuthorizationPlanViolationError()
        flight = self._guard_flight()
        if statement != flight.canon.string:
            self._refuse(ViolationReason.RENDERING)
        if _topology(connection) != flight.topology:
            self._refuse(ViolationReason.LISTENER_TOPOLOGY)
        if not self._values_match(flight, parameters, driver=True):
            self._refuse(ViolationReason.PARAMETERS)
        flight.dispatched = True
        context.dialect.do_execute(cursor, statement, parameters, context)
        return True

    def _on_after_cursor_execute(self, connection: Connection) -> None:
        flight = self._flight
        if flight is None or not self._controlled():
            return
        # C4: detection AFTER execution. The statement has already run; this latches, so COMMIT is
        # refused, but it cannot undo a sequence advance or any other non-transactional effect.
        if not flight.dispatched:
            self._latch(ViolationReason.DISPATCH_BYPASSED)
        if _topology(connection) != flight.topology:
            self._latch(ViolationReason.LISTENER_TOPOLOGY)

    def _on_after_execute(self, element: object) -> None:
        flight = self._flight
        if flight is not None and element is flight.subject.statement:
            flight.completed = True

    def _on_handle_error(self) -> None:
        if self._mode is PlanMode.PRE_WRITE and (self._finalised or self._flight is not None):
            self._latch(ViolationReason.EXECUTION_FAILED)

    def _on_savepoint_rollback(self) -> None:
        if self._mode is PlanMode.PRE_WRITE and any(self._evidence.values()):
            self._latch(ViolationReason.SAVEPOINT_ROLLBACK)

    def _on_unsupported_dispatch(self, reason: ViolationReason) -> bool:
        """`executemany` and no-parameter dispatch: refused for a controlled pre-write plan."""
        if not self._controlled():
            return False
        self._refuse(reason)


# -- the commit guard ----------------------------------------------------------------------------

_LOCK = threading.RLock()
_BOUND: "weakref.WeakKeyDictionary[Connection, list[AuthorizationPlan]]" = (
    weakref.WeakKeyDictionary()
)


def _plans_for(connection: Connection) -> list[AuthorizationPlan]:
    with _LOCK:
        return [plan for plan in _BOUND.get(connection, ()) if plan._is_current(connection)]


def _forget(connection: Connection) -> None:
    with _LOCK:
        _BOUND.pop(connection, None)


def _on_commit(connection: Connection) -> None:
    plans = _plans_for(connection)
    if not any(plan._refuses_commit() for plan in plans):
        with _LOCK:
            _BOUND.pop(connection, None)
        return
    # Defence in depth: end the server-side transaction before refusing, so a refusal outside the
    # request path (a direct caller, an engine-side `engine.begin()`) cannot leave the session in a
    # transaction. The request path does not rely on it; T0's exit abandons it itself.
    try:
        driver = connection.connection.driver_connection
        if driver is not None:
            driver.rollback()
    except Exception:  # the refusal below is what matters; T0's cleanup invalidates if needed
        pass
    _forget(connection)
    raise AuthorizationPlanNotFinalizedError()


def _on_rollback(connection: Connection) -> None:
    _forget(connection)


def _on_before_execute(
    connection: Connection,
    clauseelement: object,
    multiparams: object,
    params: object,
    execution_options: object,
) -> None:
    for plan in _plans_for(connection):
        plan._on_before_execute(connection, clauseelement, multiparams, params, execution_options)


def _on_before_cursor_execute(
    connection: Connection,
    _cursor: object,
    statement: str,
    _parameters: object,
    context: Any,
    executemany: bool,
) -> None:
    for plan in _plans_for(connection):
        plan._on_before_cursor_execute(connection, statement, context, executemany)


def _on_do_execute(cursor: Any, statement: str, parameters: object, context: Any) -> bool:
    connection = context.root_connection
    handled = False
    for plan in _plans_for(connection):
        if plan._on_do_execute(connection, cursor, statement, parameters, context):
            handled = True
    return handled


def _on_do_executemany(_cursor: Any, _statement: str, _parameters: object, context: Any) -> bool:
    for plan in _plans_for(context.root_connection):
        plan._on_unsupported_dispatch(ViolationReason.EXECUTEMANY)
    return False


def _on_do_execute_no_params(_cursor: Any, _statement: str, context: Any) -> bool:
    for plan in _plans_for(context.root_connection):
        plan._on_unsupported_dispatch(ViolationReason.UNCONTROLLED)
    return False


def _on_after_cursor_execute(
    connection: Connection,
    _cursor: object,
    _statement: str,
    _parameters: object,
    _context: object,
    _executemany: bool,
) -> None:
    for plan in _plans_for(connection):
        plan._on_after_cursor_execute(connection)


def _on_after_execute(
    connection: Connection,
    clauseelement: object,
    _multiparams: object,
    _params: object,
    _execution_options: object,
    _result: object,
) -> None:
    for plan in _plans_for(connection):
        plan._on_after_execute(clauseelement)


def _on_handle_error(exception_context: Any) -> None:
    connection = exception_context.connection
    if connection is None:
        return
    for plan in _plans_for(connection):
        plan._on_handle_error()


def _on_rollback_savepoint(connection: Connection, _name: str, _context: object) -> None:
    for plan in _plans_for(connection):
        plan._on_savepoint_rollback()


def install_authorization_guard(engine: Engine) -> None:
    """Register the guard's listeners on `engine`, once. Idempotent. The guard is the only `commit`
    listener the application registers (a structural test pins it), and registrations are fixed from the
    first request: a pre-write plan refuses to run if they change."""
    with _LOCK:
        if event.contains(engine, "commit", _on_commit):
            return
        event.listen(engine, "do_execute", _on_do_execute, insert=True)
        event.listen(engine, "do_executemany", _on_do_executemany)
        event.listen(engine, "do_execute_no_params", _on_do_execute_no_params)
        event.listen(engine, "commit", _on_commit)
        event.listen(engine, "rollback", _on_rollback)
        event.listen(engine, "before_execute", _on_before_execute)
        event.listen(engine, "before_cursor_execute", _on_before_cursor_execute)
        event.listen(engine, "after_cursor_execute", _on_after_cursor_execute)
        event.listen(engine, "after_execute", _on_after_execute)
        event.listen(engine, "handle_error", _on_handle_error)
        event.listen(engine, "rollback_savepoint", _on_rollback_savepoint)


type PlanArgument = AuthorizationPlan | _Pending

__all__ = [
    "R01_PENDING",
    "PlanArgument",
    "AuthorizationPlan",
    "AuthorizationPlanBindingError",
    "AuthorizationPlanNotFinalizedError",
    "AuthorizationPlanStateError",
    "AuthorizationPlanViolationError",
    "PlanMode",
    "Requirement",
    "StepOutcome",
    "ViolationReason",
    "install_authorization_guard",
]

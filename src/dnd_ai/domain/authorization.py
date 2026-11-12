"""R01 authorization plans: the fail-closed final check (docs/R01_FRESH_AUTHORIZATION_PLAN_2026-11-12.md,
sections 6.2 and 6.5).

A protected write registers **requirements** (a fact captured under lock, an authority predicate over
one `AuthoritySnapshot`, and the exact error its early counterpart raises today) in an
`AuthorizationPlan`, then runs `plan.finalize(connection)` as its last statement. The snapshot is read
by ONE statement at one `t_auth` (`dnd_ai.domain.access.read_authority_snapshot`), so every predicate
judges one coherent state.

**The guard.** One set of listeners on the application engine (`install_authorization_guard`) makes the
plan fail closed:

- COMMIT is refused while a plan bound to the connection is *open* (registered and never finalised,
  and not explicitly pending) or *violated*;
- every statement after `finalize` is checked against the plan's **mode**, fixed when the plan is
  created and never changeable:
  - `PlanMode.POST_WRITE`: no statement at all may follow the final one (not even a `SELECT`);
  - `PlanMode.PRE_WRITE`: only the plan's declared `PostAuthorizationSteps` may follow, each within
    its count (and in order, when the declaration says order matters).
- the refusal rolls the DBAPI connection back before it raises `AuthorizationPlanNotFinalizedError`
  (defence in depth: the request path does not rely on it, T0's exit abandons the transaction itself).

`AuthorizationPlanNotFinalizedError` is a **direct** `RuntimeError` subclass. It must never derive from
`ValueError`, `SafeMessageError` or `ApiError`: those map to a 4xx, and a refused commit is a 5xx.

`R01_PENDING` is the explicit marker a scope helper receives where its family has not been migrated to
a plan yet. Passing it protects nothing; a unit test pins the exact call sites that still pass it.
"""

import enum
import re
import threading
import uuid
import weakref
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, Self

from sqlalchemy import Connection, Engine, event, text

from .access import FRESH_INSTANT, AuthoritySnapshot, read_authority_snapshot


class AuthorizationPlanNotFinalizedError(RuntimeError):
    """The commit guard's refusal: a plan bound to the connection is open or violated.

    A **direct** `RuntimeError` subclass, pinned by a unit test (MRO) and an HTTP test (fixed 500
    body): the API maps `RuntimeError` to the fixed 5xx, whereas a `ValueError`, `SafeMessageError` or
    `ApiError` would surface as a 4xx on an unfinalised write (R01 S0, finding F-3). The message is
    fixed and carries no identifier."""

    def __init__(self, reason: str = "an authorization plan was not finalized") -> None:
        super().__init__(reason)


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


_FOR_LOCK_CLAUSE = re.compile(r"\bFOR\s+(?:NO\s+KEY\s+UPDATE|UPDATE|SHARE|KEY\s+SHARE)\b", re.I)
_ADVISORY = re.compile(r"\bpg_(?:try_)?advisory", re.I)
_FORBIDDEN_LEADING = ("SELECT", "SET", "SHOW", "LOCK", "RESET", "DO")


@dataclass(frozen=True)
class PostAuthorizationStep:
    """One SQL statement a pre-write plan admits after `finalize`: the statement text itself (the
    constant the command executes through `text(...)`), and how many times it may run.

    A declaration is reviewed with its command's lock order. Statements that could wait, or read, are
    refused at construction: a leading `SELECT`/`SET`/`SHOW`/`LOCK`, any `FOR UPDATE`/`SHARE`-style
    clause, and any advisory-lock call. Triggers run server-side and are invisible to the guard; the
    review records them."""

    sql: str
    max_count: int = 1

    def __post_init__(self) -> None:
        stripped = self.sql.strip()
        if not stripped:
            raise ValueError("a post-authorization step needs a statement")
        if self.max_count < 1:
            raise ValueError("a post-authorization step runs at least once")
        if stripped.upper().startswith(_FORBIDDEN_LEADING):
            raise ValueError("a post-authorization step may not start with a read or a SET")
        if _FOR_LOCK_CLAUSE.search(stripped) or _ADVISORY.search(stripped):
            raise ValueError("a post-authorization step may not take a row or advisory lock")


@dataclass(frozen=True)
class PostAuthorizationSteps:
    """A pre-write command's reviewed post-authorization step list. There is no wildcard and no
    method to add a step: a change is a code change reviewed with the command. `ordered=True` admits
    the steps only in declared order (a step may be skipped, never revisited)."""

    steps: tuple[PostAuthorizationStep, ...]
    ordered: bool = True


class AuthorizationPlan:
    """The requirements of one request's protected write, bound to one connection and one
    transaction. See the module docstring. Create it with `begin`; register requirements with
    `require`; end the decision with `finalize`."""

    __slots__ = (
        "__weakref__",
        "_actor_user_id",
        "_campaign_id",
        "_connection",
        "_finalised",
        "_mode",
        "_pending",
        "_reading",
        "_requirements",
        "_snapshot",
        "_step_index",
        "_step_used",
        "_steps",
        "_transaction",
        "_unordered",
        "_violated",
    )

    def __init__(
        self,
        connection: Connection,
        *,
        actor_user_id: uuid.UUID,
        campaign_id: uuid.UUID,
        mode: PlanMode,
        steps: PostAuthorizationSteps | None,
        pending: bool,
    ) -> None:
        transaction = connection.get_transaction()
        if transaction is None:
            raise AuthorizationPlanBindingError()
        if mode is PlanMode.POST_WRITE and steps is not None:
            raise ValueError("a post-write plan declares no post-authorization steps")
        if mode is PlanMode.PRE_WRITE and steps is None:
            raise ValueError("a pre-write plan must declare its post-authorization steps")
        self._connection = connection
        self._transaction = transaction
        self._actor_user_id = actor_user_id
        self._campaign_id = campaign_id
        self._mode = mode
        self._steps = steps
        self._pending = pending
        self._requirements: list[Requirement] = []
        self._finalised = False
        self._violated = False
        self._reading = False
        self._snapshot: AuthoritySnapshot | None = None
        self._step_index = 0
        self._step_used = 0
        self._unordered: dict[int, int] = {}

    @classmethod
    def begin(
        cls,
        connection: Connection,
        *,
        actor_user_id: uuid.UUID,
        campaign_id: uuid.UUID,
        mode: PlanMode = PlanMode.POST_WRITE,
        post_authorization_steps: PostAuthorizationSteps | None = None,
        pending: bool = False,
    ) -> Self:
        """Open a plan on `connection`'s current transaction and register it with the commit guard
        (installing the guard on the connection's engine if it is not installed yet). `pending`
        marks a route whose handler has not migrated: the guard admits it while unfinalised."""
        install_authorization_guard(connection.engine)
        plan = cls(
            connection,
            actor_user_id=actor_user_id,
            campaign_id=campaign_id,
            mode=mode,
            steps=post_authorization_steps,
            pending=pending,
        )
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
            self._violated = True
            raise AuthorizationPlanStateError()
        declared = {r.world_id for r in self._requirements if r.world_id is not None}
        if requirement.world_id is not None and declared - {requirement.world_id}:
            raise ValueError("a plan's requirements name one world")
        self._requirements.append(requirement)

    def finalize(self, connection: Connection) -> AuthoritySnapshot | None:
        """The final check: read every declared source in one statement at one `t_auth`, then judge
        the requirements in registration order, raising the first failing requirement's own error.
        On success the plan is finalised and the guard polices what follows (the module docstring).

        A plan with no requirement has nothing to judge: it reads nothing and returns `None`. A second
        `finalize` violates the plan (it would be a statement after the final one) and raises."""
        self._check_bound(connection)
        if self._finalised:
            self._violated = True
            raise AuthorizationPlanNotFinalizedError("an authorization plan was finalized twice")
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

    # -- guard internals -------------------------------------------------------------------------

    def _is_current(self, connection: Connection) -> bool:
        return connection is self._connection and connection.get_transaction() is self._transaction

    def _refuses_commit(self) -> bool:
        if self._violated:
            return True
        return not self._finalised and not self._pending

    def _observe_statement(self, statement: str, dialect: object) -> None:
        """Called for every statement the connection executes. Statements before `finalize` and the
        final statement itself are free; every statement after it is judged by the plan's mode."""
        if self._reading or not self._finalised or self._violated:
            return
        if self._mode is PlanMode.POST_WRITE or self._steps is None:
            self._violated = True
            return
        if not self._admit_step(statement, dialect):
            self._violated = True

    def _admit_step(self, statement: str, dialect: object) -> bool:
        assert self._steps is not None
        declared = self._steps.steps
        compiled = [_compile_step(step.sql, dialect) for step in declared]
        text_in = statement.strip()
        if not self._steps.ordered:
            for index, candidate in enumerate(compiled):
                if candidate == text_in and self._unordered.get(index, 0) < (
                    declared[index].max_count
                ):
                    self._unordered[index] = self._unordered.get(index, 0) + 1
                    return True
            return False
        for index in range(self._step_index, len(compiled)):
            if compiled[index] != text_in:
                continue
            used = self._step_used if index == self._step_index else 0
            if used >= declared[index].max_count:
                return False
            self._step_index = index
            self._step_used = used + 1
            return True
        return False


_STEP_CACHE: dict[tuple[str, str], str] = {}


def _compile_step(sql: str, dialect: object) -> str:
    key = (getattr(dialect, "name", ""), sql)
    cached = _STEP_CACHE.get(key)
    if cached is None:
        cached = str(text(sql).compile(dialect=dialect)).strip()  # type: ignore[arg-type]
        _STEP_CACHE[key] = cached
    return cached


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
    # transaction. The request path does not rely on this; T0's exit abandons it itself.
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


def _on_before_cursor_execute(
    connection: Connection,
    _cursor: object,
    statement: str,
    _parameters: object,
    _context: object,
    _executemany: bool,
) -> None:
    for plan in _plans_for(connection):
        plan._observe_statement(statement, connection.dialect)


def install_authorization_guard(engine: Engine) -> None:
    """Register the guard's three listeners on `engine`, once. Idempotent. This is the only `commit`
    listener the application registers (a structural test pins it)."""
    with _LOCK:
        if event.contains(engine, "commit", _on_commit):
            return
        event.listen(engine, "commit", _on_commit)
        event.listen(engine, "rollback", _on_rollback)
        event.listen(engine, "before_cursor_execute", _on_before_cursor_execute)


type PlanArgument = AuthorizationPlan | _Pending

__all__ = [
    "R01_PENDING",
    "PlanArgument",
    "AuthorizationPlan",
    "AuthorizationPlanBindingError",
    "AuthorizationPlanNotFinalizedError",
    "AuthorizationPlanStateError",
    "PlanMode",
    "PostAuthorizationStep",
    "PostAuthorizationSteps",
    "Requirement",
    "install_authorization_guard",
]

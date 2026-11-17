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

**Keyed pre-write plans** (R01 S5-C; plan section 6.21.4; DATABASE_CONVENTIONS section 20.3.1). A plan
created with `by_outcome=ReservationDeclarations(...)` does not know its declaration until the database has
answered for the idempotency key. The two invitation routes (R01 S5-D, `api/r01_pre_write_routes.py`) are the only
production users so far.

- `defer_reservation_campaign_fk(connection)`: optional, exactly once, before the reservation and before
  `finalize`, top-level transaction only. The plan checks the catalogue and issues
  `SET CONSTRAINTS security.idempotent_requests_campaign_id_fkey DEFERRED` itself. It takes no lock, so
  the advisory key lock `begin_idempotent_request` takes first keeps its place in the lock order.
- `bind_reservation(connection, reservation)`: exactly once, with the value `begin_idempotent_request`
  returned. The plan accepts only the outcome record that function wrote on this connection, in this
  transaction, for this actor and campaign (`dnd_ai.domain.reservation_outcome`); a hand-built value, a
  stale record or another campaign's is refused. `REPLAY` chooses `REPLAY_DECLARATION` (no lock, no step);
  `RESERVED` chooses the command's declaration, which must contain the receipt `UPDATE` with
  `Exactly(1)`. `bind_unkeyed` chooses the unkeyed declaration (no receipt) and cannot follow a deferral.
- Obligation: a `RESERVED` plan that deferred must hold `plan.lock` evidence for **this campaign's**
  `campaign.campaigns` row at `KEY SHARE` or stronger. It is checked in `finalize` before the snapshot is
  read, and again by the COMMIT guard; a deferral with no bound outcome never commits. Replay inserts no
  row, queues no campaign check and needs no evidence; it is judged by the route's requirements alone.
- **Who may change the reservation FK's constraint mode (enforced at run time).** Only the plan's own
  `defer_reservation_campaign_fk`. The guard classifies every statement of the application engine that
  mentions CONSTRAINTS (`changes_reservation_fk_mode`: `SET CONSTRAINTS ALL`, the FK by bare, schema-
  qualified or quoted name, either mode; comments between the keywords, several statements in one string
  or unparseable names are treated as affecting it). Any such statement other than the plan's own is
  refused before it reaches the driver and latches every keyed plan on the connection
  (`CONSTRAINT_MODE`); a refusal caught by the caller stays latched. A change made before a keyed plan
  exists cannot be refused, so it marks the transaction and a keyed plan opened in it starts latched.
  Supported-code contract: statements go through the application engine, and the guard is installed
  when the engine is created (`api/deps.py`). Not covered: a raw DBAPI cursor, `SET CONSTRAINTS` assembled
  by dynamic SQL, hostile in-process code. `SET CONSTRAINTS` on other constraints is untouched.
- `bind_unkeyed` is refused (and latches) when the server has already recorded a reservation outcome
  for this plan's connection, transaction, actor and campaign, even before `bind_reservation`; the record
  is left in place.
- A savepoint rollback once the plan holds the deferral, an outcome or evidence latches
  `SAVEPOINT_ROLLBACK`. `SET CONSTRAINTS` is transaction-scoped: the next transaction on a pooled
  connection is immediate again. Not covered: code that issues `SET CONSTRAINTS` itself before
  `finalize` (statements before `finalize` are not policed); undoing the deferral only costs the early
  campaign lock, never an authorization check.

**Keyed post-write plans** (R01 O-1, AM-1; design `R01_AUTHORING_OPT_IN_DESIGN_2026-11-16.md` section 2.3).
`AuthorizationPlan.begin(..., keyed_post_write=True)` (only a route in `R01_DEFERRED_RESERVATION_ROUTES`, which is
empty in O-1) extends the keyed mechanism above to a plan whose final authorization stays **post-write**. It
declares nothing and has no pre-write steps; every rule below is the S5-C rule, reused.

- Immediate by default: a registered plan that does not call `defer_reservation_campaign_fk` (an unkeyed request)
  owes nothing and behaves as an ordinary post-write plan.
- `defer_reservation_campaign_fk` and `bind_reservation` are admitted, with the same identity, sequence and
  transaction checks; `bind_reservation` only after a deferral, and it installs no declaration. `bind_unkeyed` is
  refused. `REPLAY` owes nothing; `RESERVED` owes campaign evidence.
- `lock_campaign_evidence(connection)` first verifies the session assumptions (as `lock` does), then takes
  `CAMPAIGN_EVIDENCE_LOCK` (this plan's own campaign row, `FOR KEY SHARE`) on the lock path and records evidence only on success. Callers test `owes_campaign_evidence`;
  a call in any other state latches `SEQUENCE`. During that one flight the plan is *controlled*: statement
  identity, rendering, parameter snapshot, one cursor event, completion, and the listener topology **of that flight**
  (not a lifetime baseline: a post-write plan's guarantee does not rest on statement admission, so registering a
  gate after the plan opens stays allowed). Outside a flight, and after `finalize`, the post-write rule is
  unchanged: no statement may follow the final one.
- `finalize` checks the obligations before the snapshot (a deferral with no outcome: `OUTCOME`; `RESERVED` with no
  evidence for this campaign: `CAMPAIGN_EVIDENCE`); the COMMIT guard repeats them. A savepoint rollback once the plan
  holds a deferral, an outcome or evidence latches `SAVEPOINT_ROLLBACK`. Constraint-mode policing covers it as it
  covers a keyed pre-write plan.

**Evidence-conditioned INSERTs** (`PerEvidence`, R01 S5-D amendment; plan section 6.25.5). An INSERT may
declare `cardinality=PerEvidence(lock)`, where `lock` is one of the declaration's own `PreLock`s. What it owes
is read from the evidence that lock produced **in this plan, in this transaction, before `finalize`**:

- the lock returned **one** row: exactly one INSERT is required (omission is refused at COMMIT as an incomplete
  plan; a second INSERT is refused before the driver call, `COUNT`);
- the lock was successfully executed and returned **zero** rows: no INSERT is permitted (an attempt is refused
  before the driver call, `EVIDENCE`) and none is owed;
- the lock returned **more than one** row (also as the union of several calls): unsupported, so the INSERT is
  refused (`EVIDENCE`) and the plan cannot complete: the rule is zero-or-one, never silently widened;
- the lock was **never successfully executed** (not run, refused or failed, or run through another plan, lock
  object or transaction): that is not empty evidence. Nothing is permitted and the plan cannot complete.

Any refusal latches. A savepoint rollback after *any* lock call, including one that returned no row, latches
`SAVEPOINT_ROLLBACK`, so evidence of absence cannot survive the rollback of the lock behind it. Existing
`Exactly`, `Between` and `EachLockedRow` bounds are unchanged. The condition is the lock's *evidence*, never a
caller-supplied flag, and the declaration is still chosen once, by the reservation outcome.

**Absence- and change-conditioned INSERTs** (`PerAbsence`, `AnyConfirmed`; R01 S5-E2 ownership-transfer amendment,
T1-T3; plan section 6.27.4). Both apply to an INSERT only and are validated per declaration.

- `PerAbsence(lock)`: the converse of `PerEvidence`. The lock must have been successfully executed before `finalize`.
  **Zero rows**: exactly one INSERT is required (omission is refused at COMMIT; a second is refused, `COUNT`).
  **One row**: the INSERT is refused (`EVIDENCE`) and none is owed. **More than one row** (also as a union of calls)
  or a lock that **never ran**, failed or ran through another plan, lock object or transaction: missing, not empty,
  evidence; nothing is permitted and the plan cannot complete. The mechanism trusts that the declaration also holds a
  lock that protects the absence; it does not prove every other writer is excluded.
- `AnyConfirmed(steps)`: exactly one INSERT is owed iff any named step has confirmed a returned key; otherwise it is
  forbidden (`EVIDENCE`); a second is `COUNT`. A named step attempted but unconfirmed (`ZERO_OR_ONE`) does not count.
  The named steps are distinct, strictly earlier, by identity, not the receipt and not `AnyConfirmed`; as they lie
  earlier they can no longer run once the cursor reaches this step, so the set is final then.
- A savepoint rollback also latches once any step has been attempted (T3), because a confirmed key is an
  obligation input.

**Per-key INSERTs** (`PerEvidenceRow`, `PerConfirmedRow`; R01 S5-E5, I-1 and I-2; design sections 4.1-4.2). `PerEvidence`
owes zero-or-one INSERT; these owe *one INSERT per key*, so a route can insert one link per locked member (1-100) and one
audit row per inserted link. *Evidence* is the keys recorded by successful `plan.lock` calls of one exact `PreLock` object,
through this plan, before `finalize`, merged across calls. A lock that never ran, failed (it latches `LOCK_FAILED`), ran
through another plan, connection, transaction or lock object, ran after `finalize` or inside a rolled-back savepoint is
*missing* evidence and fails closed; a lock that ran and returned nothing is *empty* evidence, a different state.

- `PerEvidenceRow(lock, via)` (INSERT only; `via` is one of the step's own `FkBinding`s and is bound to `lock`; there is no
  count-only form): evidence missing or empty -> `EVIDENCE`; the carried FK value is not an evidence key -> `FK_NOT_LOCKED`;
  the value was already attempted -> `DUPLICATE_TARGET`; attempts >= |evidence| -> `COUNT`. Skippable only on evidence that
  exists and is empty. Complete at COMMIT when the set of carried values attempted equals the evidence and exactly
  |evidence| rows are confirmed (`INCOMPLETE` otherwise); missing evidence never satisfies it. The handler is responsible
  for calling the lock once per requested id.
- `PerConfirmedRow(step, bind)` (INSERT only; `step` is a strictly earlier `PerEvidenceRow` INSERT with a single UUID
  primary key; `bind` is one of the step's value binds of the same kind): the source lock's evidence missing, or the bound
  value (a 1-tuple) not among the keys `step` confirmed -> `EVIDENCE` (the wrong-identity refusal); the value already used
  -> `DUPLICATE_TARGET`; attempts >= the number `step` confirmed -> `COUNT`. Skippable exactly when `step` is. Complete when
  the set of values used equals the set of keys `step` confirmed and the confirmed counts are equal. It guarantees audit
  *identity* (member -> exactly one link -> exactly one audit row naming that link), not the content of a JSON payload.

**`GREATEST` value form** (I-3; `authorization_steps._check_greatest`): an UPDATE may set a timestamptz column to
`greatest(pg_catalog.<time function>(), <column>)`, the column being a NOT NULL, non-key, non-FK timestamptz column of the
updated table, different from the one set. It adds no bind parameter, so the statement-snapshot and driver checks are
unchanged. Nothing else is accepted (no literal, bind, other table, nesting, or INSERT).

`AuthorizationPlanNotFinalizedError` and `AuthorizationPlanViolationError` are **direct** `RuntimeError`
subclasses. They must never derive from `ValueError`, `SafeMessageError` or `ApiError`: those map to a 4xx,
and a refused commit is a 5xx.

`R01_PENDING` is the explicit marker a scope helper receives where its family has not been migrated to
a plan yet. Passing it protects nothing; a unit test pins the exact call sites that still pass it.
"""

import enum
import re
import threading
import uuid
import weakref
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final, NoReturn, Self

from sqlalchemy import Connection, Engine, bindparam, event, select, text
from sqlalchemy.engine.interfaces import ExecuteStyle

from dnd_ai.persistence.tables.campaign import campaigns as _campaigns

from .access import FRESH_INSTANT, AuthoritySnapshot, read_authority_snapshot
from .authorization_steps import (
    REPLAY_DECLARATION,
    REVIEWED_EXECUTION_OPTIONS,
    AnyConfirmed,
    Between,
    BindSpec,
    Exactly,
    Kind,
    LockMode,
    ParameterError,
    PerAbsence,
    PerConfirmedRow,
    PerEvidence,
    PerEvidenceRow,
    PreLock,
    PreWriteDeclaration,
    RowExpectation,
    WriteStep,
    freeze_value,
    kind_and_pg_type,
    kind_of,
    matches_driver,
    matches_extracted,
    thaw_value,
)
from .reservation_outcome import (
    ReservationKind,
    clear_reservation_outcome,
    recorded_reservation_outcome,
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
    EVIDENCE = "evidence"
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
    DEFERRAL = "deferral"
    CONSTRAINT_MODE = "constraint_mode"
    OUTCOME = "outcome"
    DECLARATION = "declaration"
    CAMPAIGN_EVIDENCE = "campaign_evidence"
    INTERNAL = "internal"


_RECEIPT_SCHEMA: Final = "security"
_RECEIPT_TABLE: Final = "idempotent_requests"
_CAMPAIGN_FK: Final = "idempotent_requests_campaign_id_fkey"


def _is_receipt_step(step: WriteStep) -> bool:
    return step.table.schema == _RECEIPT_SCHEMA and step.table.name == _RECEIPT_TABLE


@dataclass(frozen=True, eq=False)
class ReservationDeclarations:
    """The declarations a keyed pre-write plan chooses from, fixed when the plan is created.

    - `reserved`: the command's declaration for a newly inserted reservation. It must complete the
      receipt: exactly one step, an `UPDATE` of `security.idempotent_requests` with cardinality
      `Exactly(1)`, and no other step on that table.
    - `unkeyed`: the declaration for a request that carries no key (optional). It has no receipt step.
    - Replay is always `REPLAY_DECLARATION` (empty). It is not a field: a route cannot supply its own.

    The plan picks one of them exactly once, from the database's answer (`bind_reservation`) or from the
    absence of a key (`bind_unkeyed`); a route never picks by flag."""

    reserved: PreWriteDeclaration
    unkeyed: PreWriteDeclaration | None = None

    def __post_init__(self) -> None:
        if self.reserved.replay or (self.unkeyed is not None and self.unkeyed.replay):
            raise ValueError("the replay declaration is not a command declaration")
        receipts = [step for step in self.reserved.steps if _is_receipt_step(step)]
        if (
            len(receipts) != 1
            or not receipts[0].is_update
            or not isinstance(receipts[0].cardinality, Exactly)
            or receipts[0].cardinality.n != 1
        ):
            raise ValueError("the reserved declaration needs exactly one Exactly(1) receipt UPDATE")
        if self.unkeyed is not None and any(_is_receipt_step(s) for s in self.unkeyed.steps):
            raise ValueError("the unkeyed declaration has no receipt step")


class _Bound(enum.Enum):
    """How a keyed plan's declaration was chosen."""

    REPLAY = "replay"
    RESERVED = "reserved"
    UNKEYED = "unkeyed"


#: Row-lock modes that count as campaign evidence: each conflicts with `FOR UPDATE`, so a held one
#: means the deferred reservation FK's COMMIT-time `FOR KEY SHARE` re-acquires, never waits.
_KEY_SHARE_OR_STRONGER: Final = frozenset(
    {LockMode.KEY_SHARE, LockMode.SHARE, LockMode.NO_KEY_UPDATE, LockMode.UPDATE}
)

#: The deferral is only issued once the catalogue shows exactly the constraint the plan means to defer:
#: one constraint of that name in `security`, the reservation's campaign FK, deferrable and immediate.
_DEFERRAL_SQL: Final = text(
    "SELECT pg_catalog.count(*) OPERATOR(pg_catalog.=) 1 "
    "AND pg_catalog.bool_and(c.contype OPERATOR(pg_catalog.=) 'f' "
    "AND c.conrelid OPERATOR(pg_catalog.=) pg_catalog.to_regclass('security.idempotent_requests') "
    "AND c.confrelid OPERATOR(pg_catalog.=) pg_catalog.to_regclass('campaign.campaigns') "
    "AND c.condeferrable AND NOT c.condeferred) "
    "FROM pg_catalog.pg_constraint c "
    f"WHERE c.conname::pg_catalog.text OPERATOR(pg_catalog.=) '{_CAMPAIGN_FK}' "
    "AND c.connamespace OPERATOR(pg_catalog.=) 'security'::pg_catalog.regnamespace"
)
_SET_DEFERRED: Final = text(f"SET CONSTRAINTS security.{_CAMPAIGN_FK} DEFERRED")
_SET_DEFERRED_STRING: Final = f"SET CONSTRAINTS security.{_CAMPAIGN_FK} DEFERRED"

# -- who may change the reservation FK's constraint mode (R01 S5-C correction) ----------------------
#
# `SET CONSTRAINTS` is transaction state the plan's deferral obligation depends on. The guard sees every
# statement the application engine executes (`before_cursor_execute`: `text()`, `exec_driver_sql`, ORM) and
# classifies the ones that mention the word CONSTRAINTS:
#
# - a clean single statement `SET CONSTRAINTS <names> DEFERRED|IMMEDIATE` is parsed; it affects the
#   reservation FK when the list is `ALL` or any name, qualified or quoted or not, ends in the FK's name;
# - anything else that mentions CONSTRAINTS (comments between the keywords, several statements in one
#   string, dynamic SQL spelled out, unparseable names) is treated as affecting it: the guard fails closed.
#
# A statement that affects it is allowed only as the plan's own `_SET_DEFERRED`, issued inside
# `defer_reservation_campaign_fk`. Anything else latches every keyed plan on the connection
# (`CONSTRAINT_MODE`) and is refused before it reaches the driver. When no keyed plan exists yet the
# statement cannot be refused (there is nothing to protect), so the transaction is marked and a keyed plan
# opened later in that transaction starts latched. Statements that do not mention CONSTRAINTS, and
# SET CONSTRAINTS on other constraints, are untouched.
_CONSTRAINTS_WORD: Final = re.compile(r"\bconstraints\b", re.IGNORECASE)
_SET_CONSTRAINTS: Final = re.compile(
    r"\A\s*SET\s+CONSTRAINTS\s+(?P<names>.+?)\s+(?:DEFERRED|IMMEDIATE)\s*;?\s*\Z",
    re.IGNORECASE | re.DOTALL,
)
_FK_MODE_MARK: Final = "reservation_fk_mode_changed"


def _split_names(names: str) -> list[list[str]] | None:
    """The comma-separated, dot-qualified, optionally double-quoted identifiers of a `SET CONSTRAINTS`
    list, case-folded as PostgreSQL does; `None` when anything is not a plain identifier."""
    result: list[list[str]] = []
    position = 0
    length = len(names)
    while True:
        parts: list[str] = []
        while True:
            while position < length and names[position].isspace():
                position += 1
            if position >= length:
                return None
            if names[position] == '"':
                end = position + 1
                buffer: list[str] = []
                while True:
                    if end >= length:
                        return None
                    if names[end] == '"':
                        if end + 1 < length and names[end + 1] == '"':
                            buffer.append('"')
                            end += 2
                            continue
                        break
                    buffer.append(names[end])
                    end += 1
                parts.append("".join(buffer))
                position = end + 1
            else:
                match = re.compile(r"[A-Za-z_\u0080-\uffff][A-Za-z0-9_$\u0080-\uffff]*").match(
                    names, position
                )
                if match is None:
                    return None
                parts.append(match.group(0).lower())
                position = match.end()
            while position < length and names[position].isspace():
                position += 1
            if position < length and names[position] == ".":
                position += 1
                continue
            break
        result.append(parts)
        if position >= length:
            return result
        if names[position] != ",":
            return None
        position += 1


def changes_reservation_fk_mode(statement: str) -> bool:
    """Whether `statement` may change the constraint mode of the reservation's campaign FK (see above)."""
    if _CONSTRAINTS_WORD.search(statement) is None:
        return False
    match = _SET_CONSTRAINTS.match(statement)
    if match is None:
        return True
    names = _split_names(match.group("names"))
    if names is None:
        return True
    return any(parts == ["all"] or parts[-1] == _CAMPAIGN_FK for parts in names)


def _is_campaign_lock(lock: PreLock) -> bool:
    return (
        lock.table.schema == "campaign"
        and lock.table.name == "campaigns"
        and len(lock.key) == 1
        and lock.key[0].name == "campaign_id"
        and lock.mode in _KEY_SHARE_OR_STRONGER
    )


#: The campaign row, `FOR KEY SHARE`, bound `campaign`. The one lock a keyed *post-write* plan runs as
#: campaign evidence (`AuthorizationPlan.lock_campaign_evidence`; R01 O-1, AM-1.4). It is a domain-level
#: constant so a post-write plan, which declares no locks, still has an exact object to run and to
#: recognise; `commands._pre_write_steps.CAMPAIGN_KEY_SHARE_LOCK` is an alias of this very object.
CAMPAIGN_EVIDENCE_LOCK = PreLock(
    "campaign_key_share",
    select(_campaigns.c.campaign_id)
    .where(_campaigns.c.campaign_id == bindparam("campaign"))
    .with_for_update(read=True, key_share=True),
)


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
    - `gm_subject`: a membership of this campaign whose live built-in `gm` assignment the snapshot must carry
      (R01 S5-E6, the recipient of a reveal delegation), read in the same statement at the same instant.

    Facts captured under lock earlier (origins, restriction state, the reveal source...) are closed
    over by `predicate`; the final check never re-derives operation facts from post-write rows."""

    name: str
    predicate: Callable[[AuthoritySnapshot], bool]
    refusal: Callable[[], BaseException]
    world_id: uuid.UUID | None = None
    reveal: bool = False
    gm_subject: uuid.UUID | None = None


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
            keys=frozenset(compiled.bind_names.values()),
            embedded=MappingProxyType(
                {
                    name: bind.value
                    for bind, name in compiled.bind_names.items()
                    if not bind.required
                }
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


#: Built-in types the supported predicates compare (authorization_steps._COMPARABLE_KINDS), plus the
#: types the driver may send a value as (numeric for an integer, bpchar/name beside text/varchar,
#: timestamp beside timestamptz). A user-defined comparison operator touching any of them is refused.
_COMPARED_TYPES: Final = (
    "uuid",
    "int2",
    "int4",
    "int8",
    "numeric",
    "bool",
    "text",
    "varchar",
    "bpchar",
    "name",
    "timestamptz",
    "timestamp",
    "date",
)
_COMPARED_ARRAY: Final = (
    "ARRAY["
    + ", ".join(f"'pg_catalog.{name}'::pg_catalog.regtype" for name in _COMPARED_TYPES)
    + "]"
)
_SESSION_SQL: Final = text(
    "SELECT pg_catalog.current_setting('search_path'), "
    "pg_catalog.current_setting('session_replication_role'), "
    "EXISTS (SELECT 1 FROM pg_catalog.pg_operator o "
    "JOIN pg_catalog.pg_namespace n ON n.oid = o.oprnamespace "
    "WHERE n.nspname <> 'pg_catalog' "
    "AND o.oprname IN ('=', '<>', '<', '<=', '>', '>=') "
    f"AND (o.oprleft = ANY ({_COMPARED_ARRAY}) OR o.oprright = ANY ({_COMPARED_ARRAY})))"
)


#: The actual PostgreSQL type of every compared column is the one built-in type its declared class
#: stands for: not a domain, not a composite, not another type (plan 6.14). Qualified operators only,
#: so a shadowing operator cannot change this statement.
_TYPE_SQL: Final = text(
    "SELECT pg_catalog.count(*) FROM ROWS FROM ("
    "pg_catalog.unnest(CAST(:rels AS pg_catalog.text[])), "
    "pg_catalog.unnest(CAST(:cols AS pg_catalog.text[])), "
    "pg_catalog.unnest(CAST(:types AS pg_catalog.text[]))) AS e(rel, col, typ) "
    "WHERE NOT EXISTS (SELECT 1 FROM pg_catalog.pg_attribute a "
    "JOIN pg_catalog.pg_type t ON t.oid OPERATOR(pg_catalog.=) a.atttypid "
    "WHERE a.attrelid OPERATOR(pg_catalog.=) pg_catalog.to_regclass(e.rel) "
    "AND a.attname::pg_catalog.text OPERATOR(pg_catalog.=) e.col "
    "AND a.attnum OPERATOR(pg_catalog.>) 0 AND NOT a.attisdropped "
    "AND t.typtype OPERATOR(pg_catalog.=) 'b' "
    "AND t.typnamespace OPERATOR(pg_catalog.=) 'pg_catalog'::pg_catalog.regnamespace "
    "AND t.typname::pg_catalog.text OPERATOR(pg_catalog.=) e.typ)"
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
        "_bound",
        "_by_outcome",
        "_campaign_id",
        "_confirmed",
        "_connection",
        "_cursor",
        "_declaration",
        "_deferred",
        "_evidence",
        "_finalised",
        "_flight",
        "_keyed_post_write",
        "_mode",
        "_pending",
        "_reading",
        "_requirements",
        "_set_flight",
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
        by_outcome: ReservationDeclarations | None = None,
        keyed_post_write: bool = False,
    ) -> None:
        transaction = connection.get_transaction()
        if transaction is None:
            raise AuthorizationPlanBindingError()
        if keyed_post_write and (
            mode is not PlanMode.POST_WRITE
            or pending
            or pre_write is not None
            or by_outcome is not None
        ):
            raise ValueError("a keyed post-write plan is post-write, final, and declares nothing")
        if mode is PlanMode.POST_WRITE and (pre_write is not None or by_outcome is not None):
            raise ValueError("a post-write plan declares no pre-write steps")
        if by_outcome is not None:
            if pre_write is not None or pending:
                raise ValueError("a keyed plan chooses its declaration by outcome")
        elif mode is PlanMode.PRE_WRITE and pre_write is None:
            raise ValueError("a pre-write plan must declare its pre-write steps")
        if pre_write is not None and pre_write.replay:
            raise ValueError("the replay declaration is chosen by the plan, never supplied")
        self._connection = connection
        self._transaction = transaction
        self._actor_user_id = actor_user_id
        self._campaign_id = campaign_id
        self._mode = mode
        self._declaration: PreWriteDeclaration | None = None
        self._by_outcome = by_outcome
        self._keyed_post_write = keyed_post_write
        self._bound: _Bound | None = None
        self._deferred = False
        self._set_flight = False
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
        self._attempts: list[int] = []
        self._attempted_keys: list[set[tuple[Any, ...]]] = []
        self._confirmed: list[list[tuple[Any, ...]]] = []
        self._cursor = 0
        if pre_write is not None:
            self._install_declaration(pre_write)

    def _install_declaration(self, declaration: PreWriteDeclaration) -> None:
        """Fix the declaration and size the step accounting. Called once: from the constructor, or
        from the one outcome binding of a keyed plan."""
        count = len(declaration.steps)
        self._declaration = declaration
        self._attempts = [0] * count
        self._attempted_keys = [set() for _ in range(count)]
        self._confirmed = [[] for _ in range(count)]

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
        by_outcome: ReservationDeclarations | None = None,
        keyed_post_write: bool = False,
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
            by_outcome=by_outcome,
            keyed_post_write=keyed_post_write,
        )
        if mode is PlanMode.PRE_WRITE:
            plan._baseline = _topology(connection)
        if plan._is_keyed() and connection.info.get(_FK_MODE_MARK) is plan._transaction:
            # the reservation FK's mode was changed by other code earlier in this transaction
            plan._latch(ViolationReason.CONSTRAINT_MODE)
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
    def keyed_post_write(self) -> bool:
        """Whether this is a keyed post-write plan (R01 O-1): it may defer the reservation's campaign FK and
        then owes campaign evidence, while its final authorization stays post-write."""
        return self._keyed_post_write

    @property
    def owes_campaign_evidence(self) -> bool:
        """Whether `lock_campaign_evidence` is the right call now: a keyed post-write plan that deferred, was
        bound `RESERVED`, is not finalised and not violated. A caller checks this and skips the call
        otherwise; the call itself never silently skips."""
        return (
            self._keyed_post_write
            and self._deferred
            and self._bound is _Bound.RESERVED
            and not self._finalised
            and not self._violated
        )

    def _is_keyed(self) -> bool:
        return self._by_outcome is not None or self._keyed_post_write

    @property
    def deferred(self) -> bool:
        """Whether this plan deferred the reservation's campaign FK check to COMMIT."""
        return self._deferred

    @property
    def reservation_kind(self) -> str | None:
        """How the keyed plan's declaration was chosen (`replay`, `reserved`, `unkeyed`), or `None`."""
        return self._bound.value if self._bound is not None else None

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
        subjects = {r.gm_subject for r in self._requirements if r.gm_subject is not None}
        if requirement.gm_subject is not None and subjects - {requirement.gm_subject}:
            raise ValueError("a plan's requirements name one gm subject")
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
        checks = self._declaration.type_checks if self._declaration is not None else ()
        if not checks:
            return
        try:
            mismatches = connection.execute(
                _TYPE_SQL,
                {
                    "rels": [c[0] for c in checks],
                    "cols": [c[1] for c in checks],
                    "types": [c[2] for c in checks],
                },
            ).scalar_one()
        except BaseException:
            self._latch(ViolationReason.SESSION)
            raise
        if mismatches != 0:
            self._refuse(ViolationReason.SESSION)

    def _check_listeners(self, connection: Connection) -> None:
        """C0: the guard's `do_execute` listener runs first, and the registrations are those recorded
        when the plan was created."""
        dispatch = list(connection.dialect.dispatch.do_execute)
        if not dispatch or dispatch[0] is not _on_do_execute:
            self._refuse(ViolationReason.LISTENER_ORDER)
        if not self._keyed_post_write and _topology(connection) != self._baseline:
            # a keyed post-write plan keeps no lifetime baseline: its flights compare per flight (AM-1.9)
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
            self._check_obligations()
            self._check_listeners(connection)
            self._verify_session(connection)
        if self._keyed_post_write:
            if self._flight is not None:
                self._refuse(ViolationReason.REENTRANT)
            if self._violated:
                raise AuthorizationPlanViolationError()
            self._check_obligations()
        if not self._requirements:
            self._finalised = True
            return None
        world_ids = {r.world_id for r in self._requirements if r.world_id is not None}
        gm_subjects = {r.gm_subject for r in self._requirements if r.gm_subject is not None}
        self._reading = True
        try:
            snapshot = read_authority_snapshot(
                connection,
                user_id=self._actor_user_id,
                campaign_id=self._campaign_id,
                world_id=next(iter(world_ids)) if world_ids else None,
                with_reveal=any(r.reveal for r in self._requirements),
                subject_gm_membership_id=next(iter(gm_subjects)) if gm_subjects else None,
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

    # -- keyed plans: deferral, reservation outcome, declaration (R01 S5-C) ------------------------

    def _keyed_entry(
        self, connection: Connection, reason: ViolationReason
    ) -> ReservationDeclarations | None:
        """Entry checks shared by the three keyed-plan calls. Every refusal latches first. Returns the
        declarations of a keyed pre-write plan, `None` for a keyed post-write plan (it has none)."""
        try:
            self._check_bound(connection)
        except AuthorizationPlanBindingError:
            self._latch(ViolationReason.BINDING)
            raise
        if not self._is_keyed():
            self._latch(reason)
            raise AuthorizationPlanStateError()
        if self._flight is not None:
            self._refuse(ViolationReason.REENTRANT)
        if self._violated:
            raise AuthorizationPlanViolationError()
        if self._finalised or self._declaration is not None or self._bound is not None:
            self._latch(reason)
            raise AuthorizationPlanStateError()
        return self._by_outcome

    def defer_reservation_campaign_fk(self, connection: Connection) -> None:
        """Opt in to deferring the reservation's campaign foreign key check to COMMIT (J-1').

        Keyed pre-write and registered keyed post-write plans only; before the reservation (so before `bind_reservation`), before
        `finalize`, exactly once, and never inside a savepoint (`SET CONSTRAINTS` made there is undone by
        its rollback). The plan issues `SET CONSTRAINTS` itself, after the catalogue shows the one
        constraint it means to defer. Nothing here takes a lock, so the advisory key lock that
        `begin_idempotent_request` takes first keeps its place. An out-of-sequence call, a failure or a
        refusal latches. The COMMIT guard refuses a deferred plan with no bound outcome, and a
        `RESERVED` plan with no campaign lock evidence."""
        self._keyed_entry(connection, ViolationReason.DEFERRAL)
        if self._deferred or self._outcome_bound():
            self._latch(ViolationReason.DEFERRAL)
            raise AuthorizationPlanStateError()
        if connection.in_nested_transaction():
            self._latch(ViolationReason.DEFERRAL)
            raise AuthorizationPlanStateError()
        self._check_listeners(connection)
        self._deferred = (
            True  # set first: an attempt that fails midway still has to be answered for
        )
        try:
            if connection.execute(_DEFERRAL_SQL).scalar_one() is not True:
                self._refuse(ViolationReason.DEFERRAL)
            self._set_flight = True  # the guard authorizes exactly this statement object, only now
            try:
                connection.execute(_SET_DEFERRED)
            finally:
                self._set_flight = False
        except BaseException:
            self._latch(ViolationReason.DEFERRAL)
            raise

    def _outcome_bound(self) -> bool:
        return self._bound is not None

    def bind_reservation(self, connection: Connection, reservation: object) -> None:
        """Bind the database's answer for the idempotency key, once, and choose the declaration from it.

        `reservation` is the value `begin_idempotent_request` returned. Its `outcome` must be the very
        record that function wrote on this connection, in this transaction, for this actor and
        campaign: a caller cannot supply an outcome, a flag or a copy. `REPLAY` chooses
        `REPLAY_DECLARATION` (no lock, no step); `RESERVED` chooses the command's reserved declaration
        (receipt included). A second call, a call after `finalize` or inside a savepoint, or any
        mismatch latches."""
        declarations = self._keyed_entry(connection, ViolationReason.OUTCOME)
        if connection.in_nested_transaction() or (self._keyed_post_write and not self._deferred):
            # a keyed post-write plan binds only after its deferral: an immediate reservation owes nothing
            self._latch(ViolationReason.OUTCOME)
            raise AuthorizationPlanStateError()
        recorded = recorded_reservation_outcome(connection)
        if recorded is None:
            self._latch(ViolationReason.OUTCOME)
            raise AuthorizationPlanViolationError()
        supplied_is_recorded = getattr(reservation, "outcome", None) is recorded
        if (
            not supplied_is_recorded
            or recorded.transaction is not self._transaction
            or recorded.actor_user_id != self._actor_user_id
            or recorded.campaign_id != self._campaign_id
        ):
            self._refuse(ViolationReason.OUTCOME)
        clear_reservation_outcome(connection)
        if recorded.kind is ReservationKind.REPLAY:
            self._bound = _Bound.REPLAY
            if declarations is not None:
                self._install_declaration(REPLAY_DECLARATION)
        else:
            self._bound = _Bound.RESERVED
            if declarations is not None:  # a post-write plan has no declaration to install
                self._install_declaration(declarations.reserved)

    def bind_unkeyed(self, connection: Connection) -> None:
        """Choose the unkeyed declaration for a request that carries no idempotency key. It cannot
        follow a deferral (nothing would be reserved to defer), a bound outcome or `finalize`, and the
        plan must have been created with an unkeyed declaration."""
        declarations = self._keyed_entry(connection, ViolationReason.OUTCOME)
        if (
            declarations is None
        ):  # a keyed post-write plan: an unkeyed request simply does not defer
            self._latch(ViolationReason.OUTCOME)
            raise AuthorizationPlanStateError()
        pending = recorded_reservation_outcome(connection)
        if (
            pending is not None
            and pending.transaction is self._transaction
            and pending.actor_user_id == self._actor_user_id
            and pending.campaign_id == self._campaign_id
        ):
            # the server already answered for a key in this plan's transaction: the request is keyed.
            # The record is left in place (never cleared to make room for this call).
            self._latch(ViolationReason.OUTCOME)
            raise AuthorizationPlanStateError()
        if self._deferred or declarations.unkeyed is None:
            self._latch(ViolationReason.OUTCOME)
            raise AuthorizationPlanStateError()
        self._bound = _Bound.UNKEYED
        self._install_declaration(declarations.unkeyed)

    def _authorizes_fk_mode(self, statement: str, context: Any) -> bool:
        """Whether this plan is, right now, issuing its own deferral statement."""
        return (
            self._set_flight
            and context is not None
            and context.invoked_statement is _SET_DEFERRED
            and statement == _SET_DEFERRED_STRING
        )

    def _has_campaign_evidence(self) -> bool:
        """Actual `plan.lock` evidence, taken through this plan (hence on its connection and in its
        transaction), for **this request's** campaign row at `KEY SHARE` or stronger."""
        key = (self._campaign_id,)
        if self._keyed_post_write:
            return key in self._evidence.get(CAMPAIGN_EVIDENCE_LOCK, ()) and _is_campaign_lock(
                CAMPAIGN_EVIDENCE_LOCK
            )
        declaration = self._declaration
        if declaration is None:
            return False
        return any(
            declaration.has_lock(lock) and _is_campaign_lock(lock) and key in keys
            for lock, keys in self._evidence.items()
        )

    def _obligation_failure(self, *, finalising: bool) -> ViolationReason | None:
        """The keyed plan's unmet obligation, if any. At `finalize` (`finalising`) the declaration must
        have been chosen; at COMMIT the plan must also be finalised for a `RESERVED` opt-in."""
        if not self._is_keyed():
            return None
        if finalising and self._declaration is None and not self._keyed_post_write:
            return ViolationReason.DECLARATION
        if not self._deferred:
            return None
        if self._bound is None or self._bound is _Bound.UNKEYED:
            return ViolationReason.OUTCOME
        if self._bound is _Bound.RESERVED and (
            (not finalising and not self._finalised) or not self._has_campaign_evidence()
        ):
            return ViolationReason.CAMPAIGN_EVIDENCE
        return None

    def _check_obligations(self) -> None:
        reason = self._obligation_failure(finalising=True)
        if reason is not None:
            self._refuse(reason)

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

    def _verify_evidence_session(self, connection: Connection) -> None:
        """The session assumptions `lock` enforces before it takes a lock, for the evidence lock: the
        replication role, `search_path` and operator resolution (`_verify_session`), and the actual type
        of every column the statement compares. A post-write plan has no declaration to carry the type
        checks, so they are derived from `CAMPAIGN_EVIDENCE_LOCK` itself. Run before the evidence flight;
        a failure latches `SESSION`. (R01 O-1 correction: Luna's session-validation finding.)"""
        self._verify_session(connection)
        preparer = connection.dialect.identifier_preparer
        checks = sorted(
            {
                (
                    preparer.format_table(column.table),
                    column.name,
                    kind_and_pg_type(column)[2],
                )
                for column in CAMPAIGN_EVIDENCE_LOCK.compared
            }
        )
        try:
            mismatches = connection.execute(
                _TYPE_SQL,
                {
                    "rels": [c[0] for c in checks],
                    "cols": [c[1] for c in checks],
                    "types": [c[2] for c in checks],
                },
            ).scalar_one()
        except BaseException:
            self._latch(ViolationReason.SESSION)
            raise
        if mismatches != 0:
            self._refuse(ViolationReason.SESSION)

    def lock_campaign_evidence(self, connection: Connection) -> None:
        """Take this request's campaign row `FOR KEY SHARE` as the evidence a deferred reservation owes
        (R01 O-1, AM-1.4). Keyed post-write plans only, once deferred and bound `RESERVED`, before
        `finalize`. The statement is `CAMPAIGN_EVIDENCE_LOCK` and the campaign id is the plan's own; the
        caller supplies nothing. The session assumptions are verified first (replication role, `search_path`,
        operator resolution, the compared column's actual type; failure latches `SESSION`). It runs on the lock path (statement identity, rendering, parameter
        snapshot, one cursor event, completion, validated keys) and records evidence only on success.
        A failure latches `LOCK_FAILED`; a call in any other state latches `SEQUENCE` and is refused,
        never skipped (callers test `owes_campaign_evidence`)."""
        try:
            self._check_bound(connection)
        except AuthorizationPlanBindingError:
            self._latch(ViolationReason.BINDING)
            raise
        if self._flight is not None:
            self._refuse(ViolationReason.REENTRANT)
        if self._violated:
            raise AuthorizationPlanViolationError()
        if not self.owes_campaign_evidence or connection.in_nested_transaction():
            self._latch(ViolationReason.SEQUENCE)
            raise AuthorizationPlanStateError()
        dispatch = list(connection.dialect.dispatch.do_execute)
        if not dispatch or dispatch[0] is not _on_do_execute:
            self._refuse(ViolationReason.LISTENER_ORDER)
        prelock = CAMPAIGN_EVIDENCE_LOCK
        self._verify_evidence_session(connection)
        frozen, call_params = self._build_snapshot(prelock.specs, {"campaign": self._campaign_id})
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
        if isinstance(cardinality, PerEvidence):
            # skippable only on *proven* empty evidence: a lock that never ran is not empty evidence
            keys = self._evidence.get(cardinality.lock)
            return keys is not None and not keys
        if isinstance(cardinality, PerAbsence):
            # skippable only on *proven* single-row evidence: missing or multi-row evidence is never skippable
            keys = self._evidence.get(cardinality.lock)
            return keys is not None and len(keys) == 1
        if isinstance(cardinality, AnyConfirmed):
            return not self._any_confirmed(cardinality)
        if isinstance(cardinality, PerEvidenceRow):
            # skippable only on *proven* empty evidence (I-1)
            keys = self._evidence.get(cardinality.lock)
            return keys is not None and not keys
        if isinstance(cardinality, PerConfirmedRow):
            # exactly when its source step is (I-2)
            source = self._declaration.index_of_step(cardinality.step)
            return source is not None and self._skippable(source)
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
        if isinstance(cardinality, PerEvidence):
            keys = self._evidence.get(cardinality.lock)
            return keys is not None and len(keys) <= 1 and len(confirmed) == len(keys)
        if isinstance(cardinality, PerAbsence):
            keys = self._evidence.get(cardinality.lock)
            return keys is not None and len(keys) <= 1 and len(confirmed) == 1 - len(keys)
        if isinstance(cardinality, AnyConfirmed):
            return len(confirmed) == (1 if self._any_confirmed(cardinality) else 0)
        if isinstance(cardinality, PerEvidenceRow):
            keys = self._evidence.get(cardinality.lock)
            return (
                keys is not None
                and self._attempted_keys[index] == keys
                and len(confirmed) == len(keys)
            )
        if isinstance(cardinality, PerConfirmedRow):
            source = self._declaration.index_of_step(cardinality.step)
            assert source is not None  # validated when the declaration was built
            source_lock = cardinality.step.cardinality
            assert isinstance(source_lock, PerEvidenceRow)
            source_confirmed = set(self._confirmed[source])
            return (
                self._evidence.get(source_lock.lock) is not None
                and self._attempted_keys[index] == source_confirmed
                and len(confirmed) == len(self._confirmed[source])
            )
        if not cardinality.complete:
            return True
        assert step.target_lock is not None
        required = self._evidence.get(step.target_lock, set())
        return len(confirmed) == len(set(confirmed)) and set(confirmed) == required

    def _any_confirmed(self, cardinality: AnyConfirmed) -> bool:
        """Whether any step named by an `AnyConfirmed` INSERT has confirmed a returned key."""
        assert self._declaration is not None
        for named in cardinality.steps:
            index = self._declaration.index_of_step(named)
            assert index is not None  # validated when the declaration was built
            if self._confirmed[index]:
                return True
        return False

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
        if isinstance(cardinality, PerEvidence):
            # one row of successfully executed evidence permits exactly one INSERT; none, more than one (the
            # rule is zero-or-one) or a lock that never ran permits nothing. Refused before the driver call.
            keys = self._evidence.get(cardinality.lock)
            if keys is None or len(keys) != 1:
                self._refuse(ViolationReason.EVIDENCE)
            if attempts >= 1:
                self._refuse(ViolationReason.COUNT)
        if isinstance(cardinality, PerAbsence):
            # zero rows of successfully executed evidence owe and permit exactly one INSERT; one row forbids it;
            # more than one (the rule is zero-or-one) or a lock that never ran permits nothing.
            keys = self._evidence.get(cardinality.lock)
            if keys is None or len(keys) != 0:
                self._refuse(ViolationReason.EVIDENCE)
            if attempts >= 1:
                self._refuse(ViolationReason.COUNT)
        if isinstance(cardinality, AnyConfirmed):
            # owed once iff a named (strictly earlier, therefore final) step confirmed a key; else forbidden
            if not self._any_confirmed(cardinality):
                self._refuse(ViolationReason.EVIDENCE)
            if attempts >= 1:
                self._refuse(ViolationReason.COUNT)
        tracked: tuple[Any, ...] | None = None
        if isinstance(cardinality, PerEvidenceRow):
            # one INSERT per evidence key (I-1): missing or empty evidence permits nothing, the carried value must be
            # an evidence key and is attempted at most once, and attempts never exceed the evidence
            keys = self._evidence.get(cardinality.lock)
            if not keys:
                self._refuse(ViolationReason.EVIDENCE)
            tracked = tuple(frozen[kb.bind] for kb in cardinality.via.binds)
            if any(value is None for value in tracked) or tracked not in keys:
                self._refuse(ViolationReason.FK_NOT_LOCKED)
            if tracked in self._attempted_keys[index]:
                self._refuse(ViolationReason.DUPLICATE_TARGET)
            if attempts >= len(keys):
                self._refuse(ViolationReason.COUNT)
        if isinstance(cardinality, PerConfirmedRow):
            # one INSERT per row the source step confirmed (I-2), identity-bound
            source = self._declaration.index_of_step(cardinality.step)
            assert source is not None  # validated when the declaration was built
            source_lock = cardinality.step.cardinality
            assert isinstance(source_lock, PerEvidenceRow)
            if self._evidence.get(source_lock.lock) is None:
                self._refuse(ViolationReason.EVIDENCE)
            source_confirmed = set(self._confirmed[source])
            tracked = (frozen[cardinality.bind],)
            if tracked not in source_confirmed:
                self._refuse(ViolationReason.EVIDENCE)
            if tracked in self._attempted_keys[index]:
                self._refuse(ViolationReason.DUPLICATE_TARGET)
            if attempts >= len(source_confirmed):
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
        return target if target is not None else tracked

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
        reason = self._obligation_failure(finalising=False)
        if reason is not None:
            self._latch(reason)
            return True
        if self._incomplete():
            self._latch(ViolationReason.INCOMPLETE)
            return True
        return not self._finalised and not self._pending

    def _controlled(self) -> bool:
        """Whether this plan's pre-write statement rules apply right now."""
        if self._keyed_post_write:
            # AM-1.9: only the evidence flight is controlled; after `finalize` a post-write plan is policed
            # by `_observe_statement` as ever
            return self._flight is not None and not self._finalised and not self._reading
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
        if not self._values_match(flight, params, driver=False, embedded=False):
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
        if self._mode is PlanMode.POST_WRITE and not self._controlled():
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

    def _values_match(
        self, flight: _Flight, mapping: object, *, driver: bool, embedded: bool = True
    ) -> bool:
        """The mapping has exactly the canonical key set, the supplied values equal the snapshot (in the
        extracted or the driver form), and the embedded literals are the declared ones."""
        keys = flight.canon.keys if embedded else set(flight.names)
        if not isinstance(mapping, Mapping) or set(mapping) != keys:
            return False
        compare = matches_driver if driver else matches_extracted
        for name in flight.names:
            if not compare(flight.specs[name], flight.frozen[name], mapping[name]):
                return False
        for key, expected in flight.canon.embedded.items() if embedded else ():
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
        if (self._mode is PlanMode.PRE_WRITE and (self._finalised or self._flight is not None)) or (
            self._keyed_post_write and self._flight is not None
        ):
            self._latch(ViolationReason.EXECUTION_FAILED)

    def _on_savepoint_rollback(self) -> None:
        # A rolled-back savepoint can discard lock evidence, **including evidence that a lock returned no row**
        # (a `PerEvidence` INSERT is forbidden on that, so it must not survive a rollback unnoticed), and, were it
        # allowed inside one, the deferral or the outcome. Once the plan holds any of them, a savepoint rollback cannot be told apart
        # from losing them silently, so it latches.
        # (T3, S5-E2 transfer amendment) An attempted step also latches: `AnyConfirmed` reads confirmed keys, and a
        # rolled-back savepoint could have discarded the write behind one.
        if self._mode is PlanMode.PRE_WRITE and (
            bool(self._evidence) or self._deferred or self._bound is not None or any(self._attempts)
        ):
            self._latch(ViolationReason.SAVEPOINT_ROLLBACK)
        if self._keyed_post_write and (
            bool(self._evidence) or self._deferred or self._bound is not None
        ):
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
    plans = _plans_for(connection)
    if changes_reservation_fk_mode(statement):
        _on_fk_mode_statement(connection, plans, statement, context)
    for plan in plans:
        plan._on_before_cursor_execute(connection, statement, context, executemany)


def _on_fk_mode_statement(
    connection: Connection, plans: list[AuthorizationPlan], statement: str, context: Any
) -> None:
    """A statement that may change the reservation FK's mode: only a plan's own deferral passes."""
    if any(plan._authorizes_fk_mode(statement, context) for plan in plans):
        return
    connection.info[_FK_MODE_MARK] = connection.get_transaction()
    keyed = [plan for plan in plans if plan._is_keyed()]
    for plan in keyed:
        plan._latch(ViolationReason.CONSTRAINT_MODE)
    if keyed:
        raise AuthorizationPlanViolationError()


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
    "CAMPAIGN_EVIDENCE_LOCK",
    "PlanArgument",
    "AuthorizationPlan",
    "AuthorizationPlanBindingError",
    "AuthorizationPlanNotFinalizedError",
    "AuthorizationPlanStateError",
    "AuthorizationPlanViolationError",
    "PlanMode",
    "REPLAY_DECLARATION",
    "changes_reservation_fk_mode",
    "Requirement",
    "ReservationDeclarations",
    "StepOutcome",
    "ViolationReason",
    "install_authorization_guard",
]

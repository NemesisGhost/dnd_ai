"""R01 shared pre-write declarations for keyed routes (plan sections 6.21 and 6.25).

A keyed pre-write route declares, per route, the row locks it takes before `plan.finalize` and the writes
it runs after it. Three of those pieces are the same for every keyed route and live here, as **module-level
constants** (a declaration is built only as a module-level constant, `tests/unit/
test_r01_authorization_structure.py`; the objects are immutable and each plan keeps its own evidence and
attempt counts, so routes share them):

- `CAMPAIGN_KEY_SHARE_LOCK`: the campaign row `FOR KEY SHARE`. It is the lock *evidence* the reservation
  opt-in needs (`plan.defer_reservation_campaign_fk`, plan 6.21.4 item 2) and the lock an insert's campaign
  FK is bound to.
- `RECEIPT_LOCK` and `RECEIPT_STEP`: the reservation row this request inserted, locked `FOR UPDATE`, and
  the one `UPDATE` that completes it (`Exactly(1)`).
- `CHANGE_LOG_ACTION_FK` and `CHANGE_LOG_ACTOR_FK`: the two foreign keys an `audit.change_log` insert
  writes. The insert itself is declared by each route (its table and command are literals of the step).

The change-log FK to `security.users` and `audit.change_actions` is declared an *unlocked FK target*
(reviewed): `change_actions` is seed data nobody updates, and an account row is only ever locked
`FOR UPDATE` by account administration, which holds nothing in the campaign domain afterwards (plan 6.21.5,
"Why KEY SHARE is enough"). A keyed request already holds the actor's account `FOR KEY SHARE` through the
reservation's actor FK.
"""

from typing import Any

from sqlalchemy import ForeignKeyConstraint, Table, bindparam, func, select, update

from dnd_ai.domain.authorization import CAMPAIGN_EVIDENCE_LOCK
from dnd_ai.domain.authorization_steps import (
    Exactly,
    FkBinding,
    KeyBind,
    PreLock,
    WriteStep,
)
from dnd_ai.persistence.tables.audit import change_actions, change_log
from dnd_ai.persistence.tables.security import idempotent_requests, users


def fk_of(table: Table, column: str) -> ForeignKeyConstraint:
    """The single-column foreign key constraint of `table.column` (for a step's `FkBinding`)."""
    for constraint in table.foreign_key_constraints:
        if [c.name for c in constraint.columns] == [column]:
            return constraint
    raise LookupError(f"{table.fullname}.{column} has no single-column foreign key")


#: The FK targets a change-log insert leaves unlocked (see the module docstring).
CHANGE_LOG_UNLOCKED_FK_TARGETS = frozenset({users, change_actions})

#: The campaign row, `FOR KEY SHARE`, bound `campaign`: the domain-level `CAMPAIGN_EVIDENCE_LOCK` itself
#: (R01 O-1), so a keyed post-write plan and a pre-write declaration run and recognise the same object.
CAMPAIGN_KEY_SHARE_LOCK = CAMPAIGN_EVIDENCE_LOCK

#: The reservation row this request inserted, `FOR UPDATE`, bound `receipt`.
RECEIPT_LOCK = PreLock(
    "receipt_row",
    select(idempotent_requests.c.idempotent_request_id)
    .where(idempotent_requests.c.idempotent_request_id == bindparam("receipt"))
    .with_for_update(),
)

#: Completes the reservation: status, body and completion time, exactly once.
RECEIPT_STEP = WriteStep(
    name="receipt",
    statement=update(idempotent_requests)
    .where(idempotent_requests.c.idempotent_request_id == bindparam("receipt"))
    .values(
        response_status_code=bindparam("status"),
        response_body=bindparam("body"),
        completed_at=func.pg_catalog.now(),
    )
    .returning(idempotent_requests.c.idempotent_request_id),
    cardinality=Exactly(1),
    target=(KeyBind(idempotent_requests.c.idempotent_request_id, "receipt"),),
    target_lock=RECEIPT_LOCK,
    value_binds=frozenset({"status", "body"}),
)

CHANGE_LOG_ACTION_FK = FkBinding(
    fk_of(change_log, "change_action_id"), (KeyBind(change_log.c.change_action_id, "action"),), None
)
CHANGE_LOG_ACTOR_FK = FkBinding(
    fk_of(change_log, "actor_user_id"), (KeyBind(change_log.c.actor_user_id, "actor"),), None
)


def receipt_params(receipt_id: Any, status: int, body: dict[str, Any]) -> dict[str, Any]:
    """The bind mapping of `RECEIPT_STEP`."""
    return {"receipt": receipt_id, "status": status, "body": body}

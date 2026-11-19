"""The server-derived outcome of an idempotency reservation (R01 S5-C, plan section 6.21.4 item 1).

`dnd_ai.api.idempotency.begin_idempotent_request` is the only code that records an outcome, and it does
so from what the database returned: the `INSERT ... ON CONFLICT DO NOTHING RETURNING` row (a new
reservation) or the matching, completed row it then read (a replay). The record lives on the
connection, names the transaction it was made in, and the `AuthorizationPlan` binds it exactly once.
A request, a caller flag or a cached claim cannot supply one: the plan accepts only the very object this
module recorded on its own connection in its own transaction.

This is a guard against mistakes, not against hostile in-process code (the same bound the authorization
guard states in its module docstring).
"""

import enum
import uuid
from dataclasses import dataclass
from typing import Final

from sqlalchemy import Connection

_INFO_KEY: Final = "reservation_outcome"


class ReservationKind(enum.Enum):
    """What the database said about the key."""

    REPLAY = "replay"
    RESERVED = "reserved"


@dataclass(frozen=True, eq=False)
class ReservationOutcome:
    """One reservation result, tied to one connection's transaction, actor and campaign. Compared by
    identity: the plan accepts the recorded object itself."""

    kind: ReservationKind
    transaction: object
    actor_user_id: uuid.UUID
    campaign_id: uuid.UUID


def record_reservation_outcome(
    connection: Connection,
    kind: ReservationKind,
    *,
    actor_user_id: uuid.UUID,
    campaign_id: uuid.UUID,
) -> ReservationOutcome:
    """Record the outcome the database just produced. Called only by `begin_idempotent_request`."""
    outcome = ReservationOutcome(
        kind=kind,
        transaction=connection.get_transaction(),
        actor_user_id=actor_user_id,
        campaign_id=campaign_id,
    )
    connection.info[_INFO_KEY] = outcome
    return outcome


def recorded_reservation_outcome(connection: Connection) -> ReservationOutcome | None:
    """The latest outcome recorded on `connection` (the plan still checks the transaction)."""
    value = connection.info.get(_INFO_KEY)
    return value if isinstance(value, ReservationOutcome) else None


def clear_reservation_outcome(connection: Connection) -> None:
    """Forget the record (the plan clears it once bound, so it cannot be bound twice)."""
    connection.info.pop(_INFO_KEY, None)

"""Character movement through `enter_location`.

`campaign.character_location_history` (revision 042/043) already carries
the full ADR 0010 interval contract for "where a character has been" — the
row with `departed_at_world_time_id IS NULL` is the character's current
location, enforced by `campaign.sync_character_location_period()` together
with the `ex_character_location_history_no_overlap` exclusion constraint.
No command populated it through the application at all until now: Phase 5
built the schema, but no command layer (or Phase 10 API endpoint) ever
wrote to it — the query side (`dnd_ai.queries.character.get_character_view`,
Phase 10 workstream 13) already reads `current_location` from it, assuming
a write path existed that, in fact, did not.

`enter_location()` is deliberately unconditional — it is not a check-gated
interaction the way discovering a hidden connection or disarming a trap is
(`dnd_ai.commands.interactions`); ordinary movement needs no roll
(docs/PLAN.md §25 step 7 names no check for it, unlike steps 8-11). A
caller that does need a gated transition (e.g. a still-locked door)
resolves that through `dnd_ai.commands.interactions` first —
`enter_location` only ever records where the character now stands, never
whether it was entitled to get there.

Idempotent by construction: entering the character's own current location
again is a no-op (no new event, no new history row) rather than an error
or a spurious departure/arrival pair at the identical `world_time_id`,
which `campaign.sync_character_location_period()`'s own ordering check
("departure must be later than arrival") would otherwise reject outright.

`character_id`/`location_id` are pre-checked against `timeline_id`'s own
world before anything is written — `campaign.sync_character_location_
period()` performs the identical checks itself, but (like every other
`BEFORE INSERT/UPDATE` trigger in this codebase) raises the bare `ERRCODE
= 'integrity_constraint_violation'` (SQLSTATE `23000`), unrecognized by
the generic `IntegrityError` handler, which would otherwise surface an
ordinary cross-world mistake as an unclassified 500 instead of the
intended 404. `world_id` itself is never caller-supplied — always resolved
from `timeline_id`, the same "never trust a caller-supplied world/timeline
pairing" rule every other command in this codebase applies.
"""

import json
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, Engine, text

from dnd_ai.domain.errors import DomainAuthorizationError

from ._shared import validate_session_campaign
from .events import EventParticipant, _insert_event_row


class CharacterNotInWorldError(DomainAuthorizationError):
    """Raised by `enter_location()` when `character_id` does not belong to
    `timeline_id`'s own world — including a nonexistent character,
    identically. The supplied ids are included only in the constructor's
    `detail` argument (`str(self)`), never in `safe_message`."""


class LocationNotInWorldError(DomainAuthorizationError):
    """Raised by `enter_location()` when `location_id` does not belong to
    `timeline_id`'s own world — including a nonexistent location,
    identically. The supplied ids are included only in the constructor's
    `detail` argument (`str(self)`), never in `safe_message`."""


@dataclass(frozen=True)
class EnterLocationResult:
    character_location_history_id: uuid.UUID
    event_id: uuid.UUID | None
    moved: bool


def _current_location_row(
    connection: Connection, *, timeline_id: uuid.UUID, character_id: uuid.UUID
) -> dict[str, Any] | None:
    """Locks the character's current open history row, if any, so a
    concurrent `enter_location()` for the same character can't race this
    one to decide "already here" or to close/open rows out of order."""
    row = (
        connection.execute(
            text("""
                SELECT character_location_history_id, location_id
                FROM campaign.character_location_history
                WHERE timeline_id = :timeline AND character_id = :character
                    AND departed_at_world_time_id IS NULL
                FOR UPDATE
            """),
            {"timeline": timeline_id, "character": character_id},
        )
        .mappings()
        .one_or_none()
    )
    return dict(row) if row is not None else None


def _enter_location_impl(
    connection: Connection,
    *,
    timeline_id: uuid.UUID,
    world_time_id: uuid.UUID,
    character_id: uuid.UUID,
    location_id: uuid.UUID,
    campaign_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    details: str | None = None,
) -> EnterLocationResult:
    """The actual work of `enter_location()`, on a connection the caller
    already has open — see `dnd_ai.commands.encounters._resolve_combat_
    turn_impl`'s docstring for the composable-implementation/public-wrapper
    pattern this mirrors. Validates `session_id`/`campaign_id` agreement
    (`dnd_ai.commands._shared.validate_session_campaign`) before writing
    anything, the same guard every other command in this package applies
    to its own caller-supplied `session_id`."""
    validate_session_campaign(connection, campaign_id=campaign_id, session_id=session_id)

    world_id = connection.execute(
        text("SELECT world_id FROM campaign.timelines WHERE timeline_id = :timeline"),
        {"timeline": timeline_id},
    ).scalar()
    assert isinstance(world_id, uuid.UUID)

    character_world_id = connection.execute(
        text("SELECT world_id FROM core.entities WHERE entity_id = :character"),
        {"character": character_id},
    ).scalar()
    if character_world_id is None or character_world_id != world_id:
        raise CharacterNotInWorldError(
            f"character {character_id} does not exist in world {world_id} "
            f"(actual world: {character_world_id})"
        )

    location_world_id = connection.execute(
        text("SELECT world_id FROM core.entities WHERE entity_id = :location"),
        {"location": location_id},
    ).scalar()
    if location_world_id is None or location_world_id != world_id:
        raise LocationNotInWorldError(
            f"location {location_id} does not exist in world {world_id} "
            f"(actual world: {location_world_id})"
        )

    current = _current_location_row(connection, timeline_id=timeline_id, character_id=character_id)
    if current is not None and current["location_id"] == location_id:
        history_id = current["character_location_history_id"]
        assert isinstance(history_id, uuid.UUID)
        return EnterLocationResult(
            character_location_history_id=history_id, event_id=None, moved=False
        )

    if current is not None:
        connection.execute(
            text("""
                UPDATE campaign.character_location_history
                SET departed_at_world_time_id = :world_time
                WHERE character_location_history_id = :history
            """),
            {"world_time": world_time_id, "history": current["character_location_history_id"]},
        )

    event_id = _insert_event_row(
        connection,
        world_id=world_id,
        timeline_id=timeline_id,
        world_time_id=world_time_id,
        event_type_code="other",
        name="Character entered a new location",
        details=details,
        campaign_id=campaign_id,
        session_id=session_id,
        participants=(EventParticipant(entity_id=character_id, role_code="actor"),),
    )

    history_id = connection.execute(
        text("""
            INSERT INTO campaign.character_location_history
                (timeline_id, character_id, location_id, arrived_at_world_time_id)
            VALUES (:timeline, :character, :location, :world_time)
            RETURNING character_location_history_id
        """),
        {
            "timeline": timeline_id,
            "character": character_id,
            "location": location_id,
            "world_time": world_time_id,
        },
    ).scalar()
    assert isinstance(history_id, uuid.UUID)

    connection.execute(
        text("""
            INSERT INTO narrative.event_effects
                (event_id, target_entity_id, target_component, previous_value, new_value,
                 effective_world_time_id)
            VALUES (:event, :character, 'current_location_id', :previous, :new, :world_time)
        """),
        {
            "event": event_id,
            "character": character_id,
            "previous": json.dumps(str(current["location_id"])) if current is not None else None,
            "new": json.dumps(str(location_id)),
            "world_time": world_time_id,
        },
    )

    return EnterLocationResult(
        character_location_history_id=history_id, event_id=event_id, moved=True
    )


def enter_location(
    engine: Engine,
    *,
    timeline_id: uuid.UUID,
    world_time_id: uuid.UUID,
    character_id: uuid.UUID,
    location_id: uuid.UUID,
    campaign_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    details: str | None = None,
) -> EnterLocationResult:
    """Records `character_id`'s arrival at `location_id`, closing out its
    previous open `campaign.character_location_history` row (if any) and
    recording the transition as a narrative event. Public convenience API:
    opens and commits its own transaction. See `_enter_location_impl()` for
    the composable form a caller with its own transaction (e.g. an API
    command endpoint) uses instead."""
    with engine.begin() as connection:
        return _enter_location_impl(
            connection,
            timeline_id=timeline_id,
            world_time_id=world_time_id,
            character_id=character_id,
            location_id=location_id,
            campaign_id=campaign_id,
            session_id=session_id,
            details=details,
        )

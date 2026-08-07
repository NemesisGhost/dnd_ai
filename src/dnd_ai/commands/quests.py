"""AdvanceObjective — the command that lets a dungeon event advance or fail a
quest objective, atomically (docs/PLAN.md Phase 7 exit criterion, CLAUDE.md
rule 6).

Mirrors dnd_ai.commands.interactions.resolve_check's shape: lock the
timeline-scoped state row first (so two concurrent advancements of the same
objective serialize rather than race), record the causing narrative.events
row, update campaign.objective_state to match, and link the two through a
narrative.event_effects row — all in one transaction.
"""

import json
import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, Engine, text

from ._shared import lookup_id
from .events import EventParticipant, _insert_event_row

_TERMINAL_OBJECTIVE_STATUSES = frozenset({"completed", "failed", "skipped", "superseded"})
_ADVANCEABLE_STATUSES = frozenset({"completed", "failed"})


@dataclass(frozen=True)
class AdvanceObjectiveResult:
    objective_state_id: uuid.UUID
    event_id: uuid.UUID
    previous_status_code: str | None
    new_status_code: str


def _quest_objective_world(connection: Connection, quest_objective_id: uuid.UUID) -> uuid.UUID:
    world_id = connection.execute(
        text("""
            SELECT e.world_id
            FROM narrative.quest_objectives qo
            JOIN narrative.quest_stages qs ON qs.quest_stage_id = qo.quest_stage_id
            JOIN narrative.quests q ON q.quest_id = qs.quest_id
            JOIN core.entities e ON e.entity_id = q.quest_id
            WHERE qo.quest_objective_id = :objective
        """),
        {"objective": quest_objective_id},
    ).scalar()
    if world_id is None:
        raise ValueError(f"quest objective {quest_objective_id} does not exist")
    assert isinstance(world_id, uuid.UUID)
    return world_id


def _lock_objective_state(
    connection: Connection,
    *,
    timeline_id: uuid.UUID,
    quest_objective_id: uuid.UUID,
    party_id: uuid.UUID | None,
) -> tuple[uuid.UUID, str] | None:
    """Row-lock the current campaign.objective_state row for this
    (timeline, objective[, party]), if one exists, so a concurrent
    advancement of the same objective serializes rather than both reading
    the same "not yet terminal" state — the exact race Phase 6's
    correction pass (revision 067/068) had to retrofit onto resolve_check();
    this command acquires the lock up front instead."""
    row = connection.execute(
        text("""
            SELECT objective_state_id,
                   (SELECT code FROM campaign.objective_statuses
                    WHERE objective_status_id = os.objective_status_id) AS status_code
            FROM campaign.objective_state os
            WHERE os.timeline_id = :timeline AND os.quest_objective_id = :objective
              AND os.party_id IS NOT DISTINCT FROM :party
            FOR UPDATE
        """),
        {"timeline": timeline_id, "objective": quest_objective_id, "party": party_id},
    ).one_or_none()
    if row is None:
        return None
    objective_state_id, status_code = row
    assert isinstance(objective_state_id, uuid.UUID)
    assert isinstance(status_code, str)
    return objective_state_id, status_code


def advance_objective(
    engine: Engine,
    *,
    quest_objective_id: uuid.UUID,
    timeline_id: uuid.UUID,
    world_time_id: uuid.UUID,
    new_status_code: str,
    party_id: uuid.UUID | None = None,
    actor_entity_id: uuid.UUID | None = None,
    campaign_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    cause_interaction_id: uuid.UUID | None = None,
    cause_event_id: uuid.UUID | None = None,
    event_details: str | None = None,
) -> AdvanceObjectiveResult:
    """Record the narrative.events row that advances or fails a quest
    objective and update campaign.objective_state to match, atomically. Only
    'completed' and 'failed' are accepted — the only two transitions a
    dungeon event actually drives (docs/PLAN.md's exit criterion names
    "advance or fail"); other objective_status values (hidden, available,
    active, skipped, superseded) are administrative/GM-driven and have no
    causing event to record.

    Rejects advancing an objective whose current state is already terminal
    (completed, failed, skipped, superseded) — there is no application-level
    guard preventing this at the database level yet (unlike interaction.
    interactions' status irreversibility, Phase 6 revisions 070-072); this
    command enforces it itself as the one path that currently writes
    campaign.objective_state.
    """
    if new_status_code not in _ADVANCEABLE_STATUSES:
        raise ValueError(
            f"new_status_code must be one of {sorted(_ADVANCEABLE_STATUSES)}, got {new_status_code!r}"
        )

    with engine.begin() as connection:
        world_id = _quest_objective_world(connection, quest_objective_id)

        existing = _lock_objective_state(
            connection,
            timeline_id=timeline_id,
            quest_objective_id=quest_objective_id,
            party_id=party_id,
        )
        previous_status_code = existing[1] if existing is not None else None

        if previous_status_code in _TERMINAL_OBJECTIVE_STATUSES:
            raise ValueError(
                f"objective {quest_objective_id} has status {previous_status_code!r} and cannot "
                "be advanced further — completed, failed, skipped, and superseded are terminal"
            )

        event_type_code = (
            "objective_completed" if new_status_code == "completed" else "objective_failed"
        )
        event_id = _insert_event_row(
            connection,
            world_id=world_id,
            timeline_id=timeline_id,
            world_time_id=world_time_id,
            event_type_code=event_type_code,
            name=f"Quest objective {new_status_code}",
            details=event_details,
            campaign_id=campaign_id,
            session_id=session_id,
            participants=(
                (EventParticipant(entity_id=actor_entity_id, role_code="actor"),)
                if actor_entity_id is not None
                else ()
            ),
            cause_interaction_id=cause_interaction_id,
            cause_event_id=cause_event_id,
        )

        new_status_id = lookup_id(
            connection, "campaign", "objective_statuses", "objective_status_id", new_status_code
        )

        if existing is None:
            objective_state_id = connection.execute(
                text("""
                    INSERT INTO campaign.objective_state
                        (timeline_id, quest_objective_id, party_id, objective_status_id, last_event_id)
                    VALUES (:timeline, :objective, :party, :status, :event)
                    RETURNING objective_state_id
                """),
                {
                    "timeline": timeline_id,
                    "objective": quest_objective_id,
                    "party": party_id,
                    "status": new_status_id,
                    "event": event_id,
                },
            ).scalar()
            assert isinstance(objective_state_id, uuid.UUID)
        else:
            objective_state_id = existing[0]
            connection.execute(
                text("""
                    UPDATE campaign.objective_state
                    SET objective_status_id = :status, last_event_id = :event, updated_at = now()
                    WHERE objective_state_id = :id
                """),
                {"status": new_status_id, "event": event_id, "id": objective_state_id},
            )

        connection.execute(
            text("""
                INSERT INTO narrative.event_effects
                    (event_id, target_quest_objective_id, target_component, previous_value,
                     new_value, effective_world_time_id)
                VALUES (:event, :objective, 'objective_status_id', :previous, :new, :world_time)
            """),
            {
                "event": event_id,
                "objective": quest_objective_id,
                "previous": json.dumps(previous_status_code),
                "new": json.dumps(new_status_code),
                "world_time": world_time_id,
            },
        )

    return AdvanceObjectiveResult(
        objective_state_id=objective_state_id,
        event_id=event_id,
        previous_status_code=previous_status_code,
        new_status_code=new_status_code,
    )

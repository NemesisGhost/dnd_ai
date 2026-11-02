"""Quest runtime commands (Phase 15 checkpoint 15.2E-2b, decision D-16).

`change_quest_status` runs the explicit GM actions (activate, complete, fail, suspend,
resume, abandon) and `set_objective_status` moves one objective. Each records one causal
event with its effect and updates `campaign.quest_state` / `campaign.objective_state` in
the same transaction. Progress is scoped to the campaign's own timeline and optionally to
one party (`party_id` NULL is campaign-wide progress).

Lock order: operation scope (world, membership, account, campaign `FOR SHARE`), the quest
entity `FOR SHARE` (a published definition, so a structural edit, which takes it `FOR
UPDATE`, cannot interleave), a per-(timeline, quest, party) advisory lock that serializes
the first write of a scope and every later quest or objective change in it, the quest
state row `FOR UPDATE`, then (objectives) the objective row and its state row. The legacy
`advance_objective` calls `lock_quest_runtime` too, so it shares the order.

The optimistic token is the status the caller saw (`expected_status`, `None` when it saw
no state row); a mismatch is a stale write.
"""

import json
import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, text

from dnd_ai.domain.authoring import StaleWriteError, normalize_description
from dnd_ai.domain.data_classification import audit_change
from dnd_ai.domain.quest_runtime import (
    OBJECTIVE_TARGETS,
    QUEST_ACTIONS,
    ObjectiveTransitionInvalidError,
    QuestNotActiveError,
    QuestTransitionInvalidError,
)
from dnd_ai.domain.session_authoring import SessionTimeRequiredError
from dnd_ai.domain.world_time import WorldTimeReferenceInvalidError
from dnd_ai.queries.campaign_clock import resolve_effective_clock

from ._operations import OperationScope, lock_operation_scope
from ._shared import EntityNotTargetableError, lookup_id, require_state_targetable
from ._shared import validate_campaign_party as _validate_campaign_party
from .events import _insert_event_row


@dataclass(frozen=True)
class RuntimeResult:
    quest_id: uuid.UUID
    world_id: uuid.UUID
    state_id: uuid.UUID
    event_id: uuid.UUID
    previous_status: str | None
    new_status: str
    changed_fields: dict[str, object]
    quest_objective_id: uuid.UUID | None = None


def time_or_clock(
    connection: Connection, scope: OperationScope, world_time_id: uuid.UUID | None
) -> uuid.UUID:
    """The explicit world time, checked to be in the world, or the campaign clock's."""
    if world_time_id is not None:
        found = connection.execute(
            text("SELECT 1 FROM core.world_times WHERE world_time_id = :t AND world_id = :w"),
            {"t": world_time_id, "w": scope.world_id},
        ).scalar()
        if found is None:
            raise WorldTimeReferenceInvalidError(f"world time {world_time_id} is not in the world")
        return world_time_id
    clock = resolve_effective_clock(connection, timeline_id=scope.timeline_id)
    if clock is None:
        raise SessionTimeRequiredError("the campaign clock is not set")
    return clock.world_time_id


def lock_quest_runtime(
    connection: Connection,
    *,
    timeline_id: uuid.UUID,
    quest_id: uuid.UUID,
    party_id: uuid.UUID | None,
) -> tuple[uuid.UUID, str] | None:
    """Serialize on the (timeline, quest, party) scope and lock its state row, if any.

    The advisory lock is what makes a first write safe (there is no row to lock yet) and
    makes a quest change wait for an objective change in the same scope, and the reverse.
    Returns `(quest_state_id, status_code)` or `None` when the scope has no state row."""
    connection.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"campaign.quest_state:{timeline_id}:{quest_id}:{party_id}"},
    )
    row = connection.execute(
        text("""
            SELECT quest_state_id,
                   (SELECT code FROM campaign.quest_statuses
                    WHERE quest_status_id = qs.quest_status_id) AS status_code
            FROM campaign.quest_state qs
            WHERE qs.timeline_id = :t AND qs.quest_id = :q AND qs.party_id IS NOT DISTINCT FROM :p
            FOR UPDATE
        """),
        {"t": timeline_id, "q": quest_id, "p": party_id},
    ).one_or_none()
    if row is None:
        return None
    assert isinstance(row.quest_state_id, uuid.UUID)
    assert isinstance(row.status_code, str)
    return row.quest_state_id, row.status_code


def _require_expected(current: str | None, expected: str | None, what: str) -> None:
    if current != expected:
        raise StaleWriteError(f"{what} is {current!r}, not {expected!r}")


def _effect(
    connection: Connection,
    *,
    event_id: uuid.UUID,
    world_time_id: uuid.UUID,
    component: str,
    previous: str | None,
    new: str,
    quest_id: uuid.UUID | None = None,
    quest_objective_id: uuid.UUID | None = None,
) -> None:
    connection.execute(
        text("""
            INSERT INTO narrative.event_effects
                (event_id, target_entity_id, target_quest_objective_id, target_component,
                 previous_value, new_value, effective_world_time_id)
            VALUES (:e, :q, :o, :c, CAST(:previous AS jsonb), CAST(:new AS jsonb), :t)
        """),
        {
            "e": event_id,
            "q": quest_id,
            "o": quest_objective_id,
            "c": component,
            "previous": json.dumps(previous),
            "new": json.dumps(new),
            "t": world_time_id,
        },
    )


def _lock_published_quest(
    connection: Connection, scope: OperationScope, quest_id: uuid.UUID
) -> None:
    """The quest must be a published, active definition of this world."""
    row = connection.execute(
        text("""
            SELECT et.code FROM core.entities e
            JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
            WHERE e.entity_id = :q AND e.world_id = :w
        """),
        {"q": quest_id, "w": scope.world_id},
    ).one_or_none()
    if row is None or row.code != "quest":
        raise EntityNotTargetableError(f"quest {quest_id} is not in this world")
    require_state_targetable(connection, quest_id)


def change_quest_status(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    quest_id: uuid.UUID,
    action: str,
    expected_status: str | None,
    party_id: uuid.UUID | None = None,
    world_time_id: uuid.UUID | None = None,
    note: str | None = None,
) -> RuntimeResult:
    starts, new_status, event_type = QUEST_ACTIONS[action]
    details = normalize_description(note)
    scope = lock_operation_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    _validate_campaign_party(
        connection, campaign_id=campaign_id, party_id=party_id, lock=True, require_active=True
    )
    _lock_published_quest(connection, scope, quest_id)
    state = lock_quest_runtime(
        connection, timeline_id=scope.timeline_id, quest_id=quest_id, party_id=party_id
    )
    previous = state[1] if state is not None else None
    _require_expected(previous, expected_status, "the quest")
    if previous not in starts:
        raise QuestTransitionInvalidError(f"cannot {action} a quest that is {previous!r}")

    time_id = time_or_clock(connection, scope, world_time_id)
    event_id = _insert_event_row(
        connection,
        world_id=scope.world_id,
        timeline_id=scope.timeline_id,
        world_time_id=time_id,
        event_type_code=event_type,
        name=f"Quest {new_status}" if action != "resume" else "Quest resumed",
        details=details,
        campaign_id=campaign_id,
    )
    status_id = lookup_id(connection, "campaign", "quest_statuses", "quest_status_id", new_status)
    if state is None:
        state_id = connection.execute(
            text("""
                INSERT INTO campaign.quest_state
                    (timeline_id, quest_id, party_id, quest_status_id, last_event_id)
                VALUES (:t, :q, :p, :s, :e) RETURNING quest_state_id
            """),
            {"t": scope.timeline_id, "q": quest_id, "p": party_id, "s": status_id, "e": event_id},
        ).scalar()
        assert isinstance(state_id, uuid.UUID)
    else:
        state_id = state[0]
        connection.execute(
            text(
                "UPDATE campaign.quest_state SET quest_status_id = :s, last_event_id = :e, "
                "updated_at = now() WHERE quest_state_id = :id"
            ),
            {"s": status_id, "e": event_id, "id": state_id},
        )
    _effect(
        connection,
        event_id=event_id,
        world_time_id=time_id,
        component="quest_status_id",
        previous=previous,
        new=new_status,
        quest_id=quest_id,
    )
    return RuntimeResult(
        quest_id=quest_id,
        world_id=scope.world_id,
        state_id=state_id,
        event_id=event_id,
        previous_status=previous,
        new_status=new_status,
        changed_fields={"quest_status": audit_change("quest_status", previous, new_status)},
    )


def set_objective_status(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    quest_objective_id: uuid.UUID,
    new_status: str,
    expected_status: str | None,
    party_id: uuid.UUID | None = None,
    world_time_id: uuid.UUID | None = None,
    note: str | None = None,
) -> RuntimeResult:
    starts, event_type = OBJECTIVE_TARGETS[new_status]
    details = normalize_description(note)
    scope = lock_operation_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    _validate_campaign_party(
        connection, campaign_id=campaign_id, party_id=party_id, lock=True, require_active=True
    )
    quest_id = _objective_quest(connection, scope, quest_objective_id)
    _lock_published_quest(connection, scope, quest_id)
    quest_state = lock_quest_runtime(
        connection, timeline_id=scope.timeline_id, quest_id=quest_id, party_id=party_id
    )
    if quest_state is None or quest_state[1] != "active":
        raise QuestNotActiveError(f"quest {quest_id} is not active")
    # An edit that removed the objective while this waited leaves nothing to change.
    if _objective_quest(connection, scope, quest_objective_id) != quest_id:
        raise EntityNotTargetableError(f"objective {quest_objective_id} is gone")
    connection.execute(
        text("SELECT 1 FROM narrative.quest_objectives WHERE quest_objective_id = :o FOR UPDATE"),
        {"o": quest_objective_id},
    )
    row = connection.execute(
        text("""
            SELECT objective_state_id,
                   (SELECT code FROM campaign.objective_statuses
                    WHERE objective_status_id = os.objective_status_id) AS status_code
            FROM campaign.objective_state os
            WHERE os.timeline_id = :t AND os.quest_objective_id = :o
              AND os.party_id IS NOT DISTINCT FROM :p
            FOR UPDATE
        """),
        {"t": scope.timeline_id, "o": quest_objective_id, "p": party_id},
    ).one_or_none()
    previous = None if row is None else str(row.status_code)
    _require_expected(previous, expected_status, "the objective")
    if previous not in starts:
        raise ObjectiveTransitionInvalidError(f"cannot make a {previous!r} objective {new_status}")

    time_id = time_or_clock(connection, scope, world_time_id)
    event_id = _insert_event_row(
        connection,
        world_id=scope.world_id,
        timeline_id=scope.timeline_id,
        world_time_id=time_id,
        event_type_code=event_type,
        name=f"Quest objective {new_status}",
        details=details,
        campaign_id=campaign_id,
    )
    status_id = lookup_id(
        connection, "campaign", "objective_statuses", "objective_status_id", new_status
    )
    if row is None:
        state_id = connection.execute(
            text("""
                INSERT INTO campaign.objective_state
                    (timeline_id, quest_objective_id, party_id, objective_status_id, last_event_id)
                VALUES (:t, :o, :p, :s, :e) RETURNING objective_state_id
            """),
            {
                "t": scope.timeline_id,
                "o": quest_objective_id,
                "p": party_id,
                "s": status_id,
                "e": event_id,
            },
        ).scalar()
        assert isinstance(state_id, uuid.UUID)
    else:
        state_id = row.objective_state_id
        connection.execute(
            text(
                "UPDATE campaign.objective_state SET objective_status_id = :s, "
                "last_event_id = :e, updated_at = now() WHERE objective_state_id = :id"
            ),
            {"s": status_id, "e": event_id, "id": state_id},
        )
    _effect(
        connection,
        event_id=event_id,
        world_time_id=time_id,
        component="objective_status_id",
        previous=previous,
        new=new_status,
        quest_objective_id=quest_objective_id,
    )
    return RuntimeResult(
        quest_id=quest_id,
        world_id=scope.world_id,
        state_id=state_id,
        event_id=event_id,
        previous_status=previous,
        new_status=new_status,
        changed_fields={"objective_status": audit_change("objective_status", previous, new_status)},
        quest_objective_id=quest_objective_id,
    )


def _objective_quest(
    connection: Connection, scope: OperationScope, quest_objective_id: uuid.UUID
) -> uuid.UUID:
    quest_id = connection.execute(
        text("""
            SELECT qs.quest_id FROM narrative.quest_objectives qo
            JOIN narrative.quest_stages qs ON qs.quest_stage_id = qo.quest_stage_id
            JOIN core.entities e ON e.entity_id = qs.quest_id
            WHERE qo.quest_objective_id = :o AND e.world_id = :w
        """),
        {"o": quest_objective_id, "w": scope.world_id},
    ).scalar()
    if not isinstance(quest_id, uuid.UUID):
        raise EntityNotTargetableError(f"objective {quest_objective_id} is not in this world")
    return quest_id

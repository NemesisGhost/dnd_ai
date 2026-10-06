"""The GM's quest progress read model (Phase 15 checkpoint 15.2E-2b, decision D-16).

For one quest on the campaign's own timeline: the campaign-wide scope and one scope per
party that has state or could be given some, each with the quest's status, its objectives
and their statuses, the actions the GM may take now, and whether every required objective
is complete (a hint only; D-16 option a never completes a quest by itself). Hidden
objectives are shown to this reader because it is the `canon.edit` read; the player-facing
quest read model is unchanged.
"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import Connection, text

from dnd_ai.domain.quest_runtime import objective_targets_from, quest_actions_from


@dataclass(frozen=True)
class ObjectiveProgress:
    quest_objective_id: uuid.UUID
    name: str
    stage_name: str
    requirement_level: str
    status: str | None
    next_statuses: list[str]


@dataclass(frozen=True)
class ScopeProgress:
    party_id: uuid.UUID | None
    party_name: str | None
    status: str | None
    actions: list[str]
    all_required_complete: bool
    objectives: list[ObjectiveProgress] = field(default_factory=list)


@dataclass(frozen=True)
class QuestProgress:
    quest_id: uuid.UUID
    name: str
    published: bool
    scopes: list[ScopeProgress]


def get_quest_progress(
    connection: Connection,
    *,
    world_id: uuid.UUID,
    campaign_id: uuid.UUID,
    timeline_id: uuid.UUID,
    quest_id: uuid.UUID,
) -> QuestProgress | None:
    """`None` when the quest is not a quest of this world."""
    quest = connection.execute(
        text("""
            SELECT e.canonical_name, cs.code AS canon, ls.code AS lifecycle
            FROM core.entities e
            JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
            JOIN core.canon_statuses cs ON cs.canon_status_id = e.canon_status_id
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = e.lifecycle_status_id
            WHERE e.entity_id = :q AND e.world_id = :w AND et.code = 'quest'
        """),
        {"q": quest_id, "w": world_id},
    ).one_or_none()
    if quest is None:
        return None
    published = quest.canon == "canon" and quest.lifecycle == "active"

    objectives = connection.execute(
        text("""
            SELECT qo.quest_objective_id, qo.name, qs.name AS stage_name, qo.requirement_level
            FROM narrative.quest_objectives qo
            JOIN narrative.quest_stages qs ON qs.quest_stage_id = qo.quest_stage_id
            WHERE qs.quest_id = :q
            ORDER BY qs.sequence_number, qo.created_at, qo.quest_objective_id
        """),
        {"q": quest_id},
    ).all()
    quest_states = {
        row.party_id: str(row.status)
        for row in connection.execute(
            text("""
                SELECT qs.party_id, st.code AS status FROM campaign.quest_state qs
                JOIN campaign.quest_statuses st ON st.quest_status_id = qs.quest_status_id
                WHERE qs.timeline_id = :t AND qs.quest_id = :q
            """),
            {"t": timeline_id, "q": quest_id},
        )
    }
    objective_states: dict[tuple[uuid.UUID | None, uuid.UUID], str] = {
        (row.party_id, row.quest_objective_id): str(row.status)
        for row in connection.execute(
            text("""
                SELECT os.party_id, os.quest_objective_id, st.code AS status
                FROM campaign.objective_state os
                JOIN campaign.objective_statuses st
                  ON st.objective_status_id = os.objective_status_id
                WHERE os.timeline_id = :t AND os.quest_objective_id = ANY(CAST(:o AS uuid[]))
            """),
            {"t": timeline_id, "o": [str(o.quest_objective_id) for o in objectives]},
        )
    }
    parties = connection.execute(
        text("""
            SELECT p.party_id, p.name FROM campaign.parties p
            JOIN campaign.campaign_parties cp ON cp.party_id = p.party_id
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = p.lifecycle_status_id
            WHERE cp.campaign_id = :c AND ls.code = 'active'
            ORDER BY lower(p.name), p.party_id
        """),
        {"c": campaign_id},
    ).all()

    scope_keys: list[tuple[uuid.UUID | None, str | None]] = [(None, None)]
    scope_keys += [(p.party_id, str(p.name)) for p in parties]
    scopes: list[ScopeProgress] = []
    for party_id, party_name in scope_keys:
        status = quest_states.get(party_id)
        rows = [
            ObjectiveProgress(
                quest_objective_id=o.quest_objective_id,
                name=str(o.name),
                stage_name=str(o.stage_name),
                requirement_level=str(o.requirement_level),
                status=objective_states.get((party_id, o.quest_objective_id)),
                next_statuses=(
                    objective_targets_from(objective_states.get((party_id, o.quest_objective_id)))
                    if status == "active"
                    else []
                ),
            )
            for o in objectives
        ]
        required = [o for o in rows if o.requirement_level == "required"]
        scopes.append(
            ScopeProgress(
                party_id=party_id,
                party_name=party_name,
                status=status,
                actions=quest_actions_from(status) if published else [],
                all_required_complete=bool(required)
                and all(o.status == "completed" for o in required),
                objectives=rows,
            )
        )
    return QuestProgress(
        quest_id=quest_id, name=str(quest.canonical_name), published=published, scopes=scopes
    )

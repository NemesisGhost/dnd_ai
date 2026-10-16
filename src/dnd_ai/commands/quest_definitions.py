"""Typed Quest definition authoring commands (Phase 15.1, ADR 0015).

A quest definition is one aggregate: the quest entity, its stages, and their
objectives. Nine intent-specific commands -- `create_quest`, `update_quest`,
`add_quest_stage`, `update_quest_stage`, `reorder_quest_stages`,
`remove_quest_stage`, `add_quest_objective`, `update_quest_objective`,
`remove_quest_objective` -- write **definition** rows only. Quest progress
(`campaign.quest_state`, `objective_state`), outcomes, rewards, participants, and
dependencies are timeline state or Phase 15.2 work.

Every command takes the quest's `expected_row_version` and bumps it (the root
version covers the whole aggregate, so two editors of different stages still
serialize). Lock order: authority scope, then entities by ascending id -- the
quest `FOR UPDATE`, an objective's target `FOR SHARE`.

**Progress freeze.** Once the quest has recorded progress in any timeline
(`quest_has_progress`), removing a stage or objective, reordering stages, and
changing an objective's type, target, completion mode, requirement level, or
quantity (or a stage's type) are refused with `quest_has_progress`: editing them
would rewrite what the recorded state means. Wording and visibility stay
editable; structural change after progress is supersession. The progress writers
(`advance_objective`) take the quest entity `FOR SHARE`, so the check below
cannot race the first progress write.
"""

import uuid

from sqlalchemy import Connection, text

from dnd_ai.domain.authoring import (
    AuthoringValidationError,
    ObjectiveTargetInvalidError,
    QuestHasProgressError,
    normalize_description,
    normalize_name,
    normalize_reason,
)
from dnd_ai.domain.content_authoring import diff_fields, initial_fields
from dnd_ai.domain.quest_authoring import (
    OBJECTIVE_TARGET_TYPE_CODES,
    STRUCTURAL_OBJECTIVE_FIELDS,
    STRUCTURAL_STAGE_FIELDS,
    normalize_gm_notes,
    normalize_objective_fields,
    normalize_stage_fields,
)

from ._content import (
    AuthoringScope,
    ContentWriteResult,
    EntityNotFoundError,
    LockedContent,
    editable_target,
    insert_draft_entity,
    insert_gm_source,
    lock_authoring_scope,
    lock_entities,
    touch_entity,
    usable_reference,
)

_QUEST = frozenset({"quest"})


class _Unset:
    """Marks an optional argument as not supplied (`None` means clear)."""


UNSET = _Unset()
MAX_STAGES = 100
MAX_OBJECTIVES_PER_STAGE = 100


# --- helpers ----------------------------------------------------------------------------------


def quest_has_progress(connection: Connection, quest_id: uuid.UUID) -> bool:
    """Whether recorded state or history refers to this quest or its objectives,
    in any timeline: quest or objective progress, or event effects that target an
    objective. (Objective dependencies are definition since checkpoint 15.2E-2a, so
    they no longer count as progress.)"""
    return bool(
        connection.execute(
            text("""
                SELECT EXISTS (SELECT 1 FROM campaign.quest_state WHERE quest_id = :q)
                    OR EXISTS (
                        SELECT 1
                        FROM narrative.quest_stages qs
                        JOIN narrative.quest_objectives qo ON qo.quest_stage_id = qs.quest_stage_id
                        WHERE qs.quest_id = :q
                          AND (
                              EXISTS (SELECT 1 FROM campaign.objective_state os
                                      WHERE os.quest_objective_id = qo.quest_objective_id)
                              OR EXISTS (SELECT 1 FROM narrative.event_effects ee
                                         WHERE ee.target_quest_objective_id = qo.quest_objective_id)
                          )
                    )
            """),
            {"q": quest_id},
        ).scalar()
    )


def _lock_quest(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    quest_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int,
    target_ids: tuple[uuid.UUID | None, ...] = (),
) -> tuple[AuthoringScope, LockedContent, dict[uuid.UUID, LockedContent]]:
    scope = lock_authoring_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    locked = lock_entities(
        connection,
        world_id=scope.world_id,
        update_ids=[quest_id],
        share_ids=[t for t in target_ids if t is not None and t != quest_id],
    )
    quest = editable_target(
        locked, entity_id=quest_id, type_codes=_QUEST, expected_row_version=expected_row_version
    )
    return scope, quest, locked


def _text_id(value: uuid.UUID | None) -> str | None:
    return None if value is None else str(value)


def _require_objective_type(connection: Connection, code: str) -> uuid.UUID:
    value = connection.execute(
        text("SELECT objective_type_id FROM narrative.objective_types WHERE code = :c"),
        {"c": code},
    ).scalar()
    if value is None:
        raise AuthoringValidationError("objective_type is not an allowed choice")
    assert isinstance(value, uuid.UUID)
    return value


def _require_stage(connection: Connection, quest_id: uuid.UUID, stage_id: uuid.UUID) -> None:
    found = connection.execute(
        text("SELECT 1 FROM narrative.quest_stages WHERE quest_stage_id = :s AND quest_id = :q"),
        {"s": stage_id, "q": quest_id},
    ).scalar()
    if found is None:
        raise EntityNotFoundError(f"stage {stage_id} is not part of quest {quest_id}")


def _require_objective(
    connection: Connection, quest_id: uuid.UUID, stage_id: uuid.UUID, objective_id: uuid.UUID
) -> None:
    found = connection.execute(
        text("""
            SELECT 1 FROM narrative.quest_objectives qo
            JOIN narrative.quest_stages qs ON qs.quest_stage_id = qo.quest_stage_id
            WHERE qo.quest_objective_id = :o AND qs.quest_stage_id = :s AND qs.quest_id = :q
        """),
        {"o": objective_id, "s": stage_id, "q": quest_id},
    ).scalar()
    if found is None:
        raise EntityNotFoundError(f"objective {objective_id} is not part of stage {stage_id}")


def _bump(connection: Connection, quest: LockedContent) -> int:
    """Move the aggregate's root version (and `updated_at`) without changing it."""
    return touch_entity(
        connection, entity_id=quest.entity_id, name=quest.canonical_name, summary=quest.summary
    )


def _child_result(
    quest: LockedContent,
    *,
    scope: AuthoringScope,
    row_version: int,
    table: str,
    record_id: uuid.UUID,
    action: str,
    fields: dict[str, object],
) -> ContentWriteResult:
    return ContentWriteResult(
        entity_id=quest.entity_id,
        world_id=scope.world_id,
        entity_type_code="quest",
        row_version=row_version,
        created=action == "created",
        changed=True,
        changed_fields=fields,
        record_schema="narrative",
        record_table=table,
        record_id=record_id,
        action=action,
    )


def _noop(quest: LockedContent, scope: AuthoringScope) -> ContentWriteResult:
    return ContentWriteResult(
        entity_id=quest.entity_id,
        world_id=scope.world_id,
        entity_type_code="quest",
        row_version=quest.row_version,
        created=False,
        changed=False,
    )


# --- the quest root ----------------------------------------------------------------------------


def create_quest(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    name: str | None,
    summary: str | None,
) -> ContentWriteResult:
    clean_name = normalize_name(name)
    clean_summary = normalize_description(summary)
    scope = lock_authoring_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    source_id = insert_gm_source(connection, world_id=scope.world_id, actor_user_id=actor_user_id)
    entity_id, row_version = insert_draft_entity(
        connection,
        world_id=scope.world_id,
        entity_type_code="quest",
        name=clean_name,
        summary=clean_summary,
        source_id=source_id,
        actor_user_id=actor_user_id,
    )
    connection.execute(
        text("INSERT INTO narrative.quests (quest_id) VALUES (:q)"), {"q": entity_id}
    )
    return ContentWriteResult(
        entity_id=entity_id,
        world_id=scope.world_id,
        entity_type_code="quest",
        row_version=row_version,
        created=True,
        changed=True,
        changed_fields=initial_fields({"name": clean_name, "summary": clean_summary}),
        source_id=source_id,
    )


def update_quest(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    quest_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int,
    name: str | None,
    summary: str | None,
    change_note: str | None = None,
    gm_notes: str | None | _Unset = UNSET,
) -> ContentWriteResult:
    normalize_reason(change_note)
    scope, quest, _ = _lock_quest(
        connection,
        campaign_id=campaign_id,
        quest_id=quest_id,
        actor_user_id=actor_user_id,
        expected_row_version=expected_row_version,
    )
    clean_name = normalize_name(name)
    clean_summary = normalize_description(summary)
    current_notes = connection.execute(
        text("SELECT gm_notes FROM narrative.quests WHERE quest_id = :q"), {"q": quest_id}
    ).scalar()
    # An omitted `gm_notes` keeps the current notes (older clients never send it).
    clean_notes = current_notes if isinstance(gm_notes, _Unset) else normalize_gm_notes(gm_notes)
    changed = diff_fields(
        {"name": quest.canonical_name, "summary": quest.summary, "gm_notes": current_notes},
        {"name": clean_name, "summary": clean_summary, "gm_notes": clean_notes},
    )
    if not changed:
        return _noop(quest, scope)
    new_version = touch_entity(
        connection, entity_id=quest_id, name=clean_name, summary=clean_summary
    )
    if "gm_notes" in changed:
        connection.execute(
            text("UPDATE narrative.quests SET gm_notes = :n WHERE quest_id = :q"),
            {"n": clean_notes, "q": quest_id},
        )
    return ContentWriteResult(
        entity_id=quest_id,
        world_id=scope.world_id,
        entity_type_code="quest",
        row_version=new_version,
        created=False,
        changed=True,
        changed_fields=dict(changed),
    )


# --- stages ------------------------------------------------------------------------------------


def add_quest_stage(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    quest_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int,
    name: str | None,
    description: str | None,
    stage_type: str | None,
) -> ContentWriteResult:
    fields = normalize_stage_fields(name=name, description=description, stage_type=stage_type)
    scope, quest, _ = _lock_quest(
        connection,
        campaign_id=campaign_id,
        quest_id=quest_id,
        actor_user_id=actor_user_id,
        expected_row_version=expected_row_version,
    )
    count, highest = connection.execute(
        text(
            "SELECT count(*), COALESCE(max(sequence_number), 0) "
            "FROM narrative.quest_stages WHERE quest_id = :q"
        ),
        {"q": quest_id},
    ).one()
    if count >= MAX_STAGES:
        raise AuthoringValidationError(f"a quest holds at most {MAX_STAGES} stages")
    stage_id = connection.execute(
        text("""
            INSERT INTO narrative.quest_stages
                (quest_id, name, description, sequence_number, stage_type)
            VALUES (:q, :name, :description, :seq, :type)
            RETURNING quest_stage_id
        """),
        {
            "q": quest_id,
            "name": fields.name,
            "description": fields.description,
            "seq": int(highest) + 1,
            "type": fields.stage_type,
        },
    ).scalar()
    assert isinstance(stage_id, uuid.UUID)
    return _child_result(
        quest,
        scope=scope,
        row_version=_bump(connection, quest),
        table="quest_stages",
        record_id=stage_id,
        action="created",
        fields=initial_fields(
            {
                "name": fields.name,
                "description": fields.description,
                "stage_type": fields.stage_type,
                "sequence_number": int(highest) + 1,
            }
        ),
    )


def update_quest_stage(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    quest_id: uuid.UUID,
    quest_stage_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int,
    name: str | None,
    description: str | None,
    stage_type: str | None,
) -> ContentWriteResult:
    fields = normalize_stage_fields(name=name, description=description, stage_type=stage_type)
    scope, quest, _ = _lock_quest(
        connection,
        campaign_id=campaign_id,
        quest_id=quest_id,
        actor_user_id=actor_user_id,
        expected_row_version=expected_row_version,
    )
    _require_stage(connection, quest_id, quest_stage_id)
    current = connection.execute(
        text(
            "SELECT name, description, stage_type FROM narrative.quest_stages "
            "WHERE quest_stage_id = :s"
        ),
        {"s": quest_stage_id},
    ).one()
    changed = diff_fields(
        {
            "name": current.name,
            "description": current.description,
            "stage_type": current.stage_type,
        },
        {"name": fields.name, "description": fields.description, "stage_type": fields.stage_type},
    )
    if not changed:
        return _noop(quest, scope)
    if STRUCTURAL_STAGE_FIELDS & set(changed) and quest_has_progress(connection, quest_id):
        raise QuestHasProgressError(f"quest {quest_id} has progress")
    connection.execute(
        text("""
            UPDATE narrative.quest_stages
            SET name = :name, description = :description, stage_type = :type
            WHERE quest_stage_id = :s
        """),
        {
            "name": fields.name,
            "description": fields.description,
            "type": fields.stage_type,
            "s": quest_stage_id,
        },
    )
    return _child_result(
        quest,
        scope=scope,
        row_version=_bump(connection, quest),
        table="quest_stages",
        record_id=quest_stage_id,
        action="updated",
        fields=dict(changed),
    )


def reorder_quest_stages(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    quest_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int,
    ordered_stage_ids: list[uuid.UUID],
) -> ContentWriteResult:
    scope, quest, _ = _lock_quest(
        connection,
        campaign_id=campaign_id,
        quest_id=quest_id,
        actor_user_id=actor_user_id,
        expected_row_version=expected_row_version,
    )
    current = list(
        connection.execute(
            text(
                "SELECT quest_stage_id FROM narrative.quest_stages WHERE quest_id = :q "
                "ORDER BY sequence_number, created_at, quest_stage_id"
            ),
            {"q": quest_id},
        ).scalars()
    )
    if len(set(ordered_stage_ids)) != len(ordered_stage_ids) or set(ordered_stage_ids) != set(
        current
    ):
        raise AuthoringValidationError("the new order must name every stage exactly once")
    if ordered_stage_ids == current:
        return _noop(quest, scope)
    if quest_has_progress(connection, quest_id):
        raise QuestHasProgressError(f"quest {quest_id} has progress")
    connection.execute(
        text("""
            UPDATE narrative.quest_stages qs
            SET sequence_number = ordering.position
            FROM unnest(CAST(:ids AS uuid[])) WITH ORDINALITY AS ordering(stage_id, position)
            WHERE qs.quest_stage_id = ordering.stage_id AND qs.quest_id = :q
        """),
        {"ids": ordered_stage_ids, "q": quest_id},
    )
    return _child_result(
        quest,
        scope=scope,
        row_version=_bump(connection, quest),
        table="quests",
        record_id=quest_id,
        action="updated",
        fields={
            "stage_order": {
                "from": [str(i) for i in current],
                "to": [str(i) for i in ordered_stage_ids],
            }
        },
    )


def remove_quest_stage(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    quest_id: uuid.UUID,
    quest_stage_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int,
) -> ContentWriteResult:
    scope, quest, _ = _lock_quest(
        connection,
        campaign_id=campaign_id,
        quest_id=quest_id,
        actor_user_id=actor_user_id,
        expected_row_version=expected_row_version,
    )
    _require_stage(connection, quest_id, quest_stage_id)
    if quest_has_progress(connection, quest_id):
        raise QuestHasProgressError(f"quest {quest_id} has progress")
    current = connection.execute(
        text(
            "SELECT name, (SELECT count(*) FROM narrative.quest_objectives "
            "WHERE quest_stage_id = :s) AS objectives "
            "FROM narrative.quest_stages WHERE quest_stage_id = :s"
        ),
        {"s": quest_stage_id},
    ).one()
    connection.execute(
        text("DELETE FROM narrative.quest_stages WHERE quest_stage_id = :s"), {"s": quest_stage_id}
    )
    return _child_result(
        quest,
        scope=scope,
        row_version=_bump(connection, quest),
        table="quest_stages",
        record_id=quest_stage_id,
        action="deleted",
        fields=initial_fields(
            {"name": current.name, "objectives_removed": int(current.objectives)}
        ),
    )


# --- objectives --------------------------------------------------------------------------------


def _validate_target(
    locked: dict[uuid.UUID, LockedContent], target_entity_id: uuid.UUID | None
) -> None:
    usable_reference(
        locked,
        target_entity_id,
        type_codes=OBJECTIVE_TARGET_TYPE_CODES,
        error=ObjectiveTargetInvalidError,
    )


def add_quest_objective(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    quest_id: uuid.UUID,
    quest_stage_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int,
    name: str | None,
    description: str | None,
    objective_type: str | None,
    requirement_level: str | None,
    completion_mode: str | None,
    visibility_policy: str | None,
    quantity_required: int | None,
    target_entity_id: uuid.UUID | None,
) -> ContentWriteResult:
    fields = normalize_objective_fields(
        name=name,
        description=description,
        objective_type=objective_type,
        requirement_level=requirement_level,
        completion_mode=completion_mode,
        visibility_policy=visibility_policy,
        quantity_required=quantity_required,
    )
    scope, quest, locked = _lock_quest(
        connection,
        campaign_id=campaign_id,
        quest_id=quest_id,
        actor_user_id=actor_user_id,
        expected_row_version=expected_row_version,
        target_ids=(target_entity_id,),
    )
    _require_stage(connection, quest_id, quest_stage_id)
    _validate_target(locked, target_entity_id)
    type_id = _require_objective_type(connection, fields.objective_type)
    count = connection.execute(
        text("SELECT count(*) FROM narrative.quest_objectives WHERE quest_stage_id = :s"),
        {"s": quest_stage_id},
    ).scalar()
    if (count or 0) >= MAX_OBJECTIVES_PER_STAGE:
        raise AuthoringValidationError(
            f"a stage holds at most {MAX_OBJECTIVES_PER_STAGE} objectives"
        )
    objective_id = connection.execute(
        text("""
            INSERT INTO narrative.quest_objectives
                (quest_stage_id, objective_type_id, name, description, requirement_level,
                 completion_mode, visibility_policy, quantity_required, target_entity_id)
            VALUES (:s, :type, :name, :description, :requirement, :mode, :visibility,
                    :quantity, :target)
            RETURNING quest_objective_id
        """),
        {
            "s": quest_stage_id,
            "type": type_id,
            "name": fields.name,
            "description": fields.description,
            "requirement": fields.requirement_level,
            "mode": fields.completion_mode,
            "visibility": fields.visibility_policy,
            "quantity": fields.quantity_required,
            "target": target_entity_id,
        },
    ).scalar()
    assert isinstance(objective_id, uuid.UUID)
    return _child_result(
        quest,
        scope=scope,
        row_version=_bump(connection, quest),
        table="quest_objectives",
        record_id=objective_id,
        action="created",
        fields=initial_fields(
            {
                "name": fields.name,
                "description": fields.description,
                "objective_type": fields.objective_type,
                "requirement_level": fields.requirement_level,
                "completion_mode": fields.completion_mode,
                "visibility_policy": fields.visibility_policy,
                "quantity_required": fields.quantity_required,
                "target_entity_id": _text_id(target_entity_id),
            }
        ),
    )


def update_quest_objective(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    quest_id: uuid.UUID,
    quest_stage_id: uuid.UUID,
    quest_objective_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int,
    name: str | None,
    description: str | None,
    objective_type: str | None,
    requirement_level: str | None,
    completion_mode: str | None,
    visibility_policy: str | None,
    quantity_required: int | None,
    target_entity_id: uuid.UUID | None,
) -> ContentWriteResult:
    fields = normalize_objective_fields(
        name=name,
        description=description,
        objective_type=objective_type,
        requirement_level=requirement_level,
        completion_mode=completion_mode,
        visibility_policy=visibility_policy,
        quantity_required=quantity_required,
    )
    current_target = connection.execute(
        text(
            "SELECT target_entity_id FROM narrative.quest_objectives WHERE quest_objective_id = :o"
        ),
        {"o": quest_objective_id},
    ).scalar()
    scope, quest, locked = _lock_quest(
        connection,
        campaign_id=campaign_id,
        quest_id=quest_id,
        actor_user_id=actor_user_id,
        expected_row_version=expected_row_version,
        target_ids=(target_entity_id if target_entity_id != current_target else None,),
    )
    _require_stage(connection, quest_id, quest_stage_id)
    _require_objective(connection, quest_id, quest_stage_id, quest_objective_id)
    current = connection.execute(
        text("""
            SELECT qo.name, qo.description, ot.code AS objective_type, qo.requirement_level,
                   qo.completion_mode, qo.visibility_policy, qo.quantity_required,
                   qo.target_entity_id
            FROM narrative.quest_objectives qo
            JOIN narrative.objective_types ot ON ot.objective_type_id = qo.objective_type_id
            WHERE qo.quest_objective_id = :o
        """),
        {"o": quest_objective_id},
    ).one()
    changed = diff_fields(
        {
            "name": current.name,
            "description": current.description,
            "objective_type": current.objective_type,
            "requirement_level": current.requirement_level,
            "completion_mode": current.completion_mode,
            "visibility_policy": current.visibility_policy,
            "quantity_required": current.quantity_required,
            "target_entity_id": _text_id(current.target_entity_id),
        },
        {
            "name": fields.name,
            "description": fields.description,
            "objective_type": fields.objective_type,
            "requirement_level": fields.requirement_level,
            "completion_mode": fields.completion_mode,
            "visibility_policy": fields.visibility_policy,
            "quantity_required": fields.quantity_required,
            "target_entity_id": _text_id(target_entity_id),
        },
    )
    if not changed:
        return _noop(quest, scope)
    if STRUCTURAL_OBJECTIVE_FIELDS & set(changed) and quest_has_progress(connection, quest_id):
        raise QuestHasProgressError(f"quest {quest_id} has progress")
    if "target_entity_id" in changed:
        _validate_target(locked, target_entity_id)
    type_id = _require_objective_type(connection, fields.objective_type)
    connection.execute(
        text("""
            UPDATE narrative.quest_objectives
            SET name = :name, description = :description, objective_type_id = :type,
                requirement_level = :requirement, completion_mode = :mode,
                visibility_policy = :visibility, quantity_required = :quantity,
                target_entity_id = :target
            WHERE quest_objective_id = :o
        """),
        {
            "name": fields.name,
            "description": fields.description,
            "type": type_id,
            "requirement": fields.requirement_level,
            "mode": fields.completion_mode,
            "visibility": fields.visibility_policy,
            "quantity": fields.quantity_required,
            "target": target_entity_id,
            "o": quest_objective_id,
        },
    )
    return _child_result(
        quest,
        scope=scope,
        row_version=_bump(connection, quest),
        table="quest_objectives",
        record_id=quest_objective_id,
        action="updated",
        fields=dict(changed),
    )


def remove_quest_objective(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    quest_id: uuid.UUID,
    quest_stage_id: uuid.UUID,
    quest_objective_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int,
) -> ContentWriteResult:
    scope, quest, _ = _lock_quest(
        connection,
        campaign_id=campaign_id,
        quest_id=quest_id,
        actor_user_id=actor_user_id,
        expected_row_version=expected_row_version,
    )
    _require_stage(connection, quest_id, quest_stage_id)
    _require_objective(connection, quest_id, quest_stage_id, quest_objective_id)
    if quest_has_progress(connection, quest_id):
        raise QuestHasProgressError(f"quest {quest_id} has progress")
    name = connection.execute(
        text("SELECT name FROM narrative.quest_objectives WHERE quest_objective_id = :o"),
        {"o": quest_objective_id},
    ).scalar()
    connection.execute(
        text("DELETE FROM narrative.quest_objectives WHERE quest_objective_id = :o"),
        {"o": quest_objective_id},
    )
    return _child_result(
        quest,
        scope=scope,
        row_version=_bump(connection, quest),
        table="quest_objectives",
        record_id=quest_objective_id,
        action="deleted",
        fields=initial_fields({"name": name}),
    )

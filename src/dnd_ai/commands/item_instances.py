"""Item instance authoring commands (Phase 15 checkpoint 15.3B-1b).

An item instance (`world.item_instances`) is a lifecycle-managed definition of one particular
object: its name, summary, origin notes and the item definition it is an example of. Where it is,
who owns and carries it, and its condition are timeline state, written only by
`commands.item_operations`. `create_item_instance` makes a draft; a draft cannot be targeted by
any operation until it is published.

- The item definition must be a published (canon) one this campaign can use: ruleset-wide on the
  campaign's ruleset version, or homebrew owned by the campaign's world. It is fixed after
  creation (a different kind of object is a different item), so an update changes only the name,
  summary and origin notes.

Lock order: authority scope, the item definition `FOR SHARE` (so it cannot be unpublished
between the check and the insert), then for an update the item entity `FOR UPDATE`.
"""

import uuid

from sqlalchemy import Connection, text

from dnd_ai.domain.authoring import normalize_description, normalize_name, normalize_reason
from dnd_ai.domain.content_authoring import diff_fields, initial_fields
from dnd_ai.domain.item_runtime import ItemDefinitionInvalidError, normalize_origin_notes

from ._content import (
    ContentWriteResult,
    editable_target,
    insert_draft_entity,
    insert_gm_source,
    lock_authoring_scope,
    lock_entities,
    touch_entity,
)

ITEM_TYPE = "item_instance"
_ITEM = frozenset({ITEM_TYPE})


def _require_usable_definition(
    connection: Connection, *, campaign_id: uuid.UUID, world_id: uuid.UUID, definition_id: uuid.UUID
) -> None:
    found = connection.execute(
        text("""
            SELECT 1
            FROM rules.item_definitions d
            JOIN campaign.campaigns c ON c.ruleset_version_id = d.ruleset_version_id
            JOIN core.canon_statuses cs ON cs.canon_status_id = d.canon_status_id
            WHERE d.item_definition_id = :d AND c.campaign_id = :c
              AND (d.owning_world_id IS NULL OR d.owning_world_id = :w)
              AND cs.code = 'canon'
            FOR SHARE OF d
        """),
        {"d": definition_id, "c": campaign_id, "w": world_id},
    ).scalar()
    if found is None:
        raise ItemDefinitionInvalidError(f"item definition {definition_id} is not usable")


def create_item_instance(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    name: str | None,
    summary: str | None,
    item_definition_id: uuid.UUID,
    origin_notes: str | None = None,
) -> ContentWriteResult:
    clean_name = normalize_name(name)
    clean_summary = normalize_description(summary)
    clean_notes = normalize_origin_notes(origin_notes)
    scope = lock_authoring_scope(
        connection,
        campaign_id=campaign_id,
        actor_user_id=actor_user_id,
        # D8/E2: item instances are created when loot is awarded; campaign authority
        # alone suffices (no world capability).
        world_capability=None,
    )
    _require_usable_definition(
        connection,
        campaign_id=campaign_id,
        world_id=scope.world_id,
        definition_id=item_definition_id,
    )
    source_id = insert_gm_source(connection, world_id=scope.world_id, actor_user_id=actor_user_id)
    entity_id, row_version = insert_draft_entity(
        connection,
        world_id=scope.world_id,
        entity_type_code=ITEM_TYPE,
        name=clean_name,
        summary=clean_summary,
        source_id=source_id,
        actor_user_id=actor_user_id,
    )
    connection.execute(
        text("""
            INSERT INTO world.item_instances (item_instance_id, item_definition_id, origin_notes)
            VALUES (:i, :d, :n)
        """),
        {"i": entity_id, "d": item_definition_id, "n": clean_notes},
    )
    return ContentWriteResult(
        entity_id=entity_id,
        world_id=scope.world_id,
        entity_type_code=ITEM_TYPE,
        row_version=row_version,
        created=True,
        changed=True,
        changed_fields=initial_fields(
            {
                "name": clean_name,
                "summary": clean_summary,
                "item_definition_id": str(item_definition_id),
                "origin_notes": clean_notes,
            }
        ),
        source_id=source_id,
    )


def update_item_instance(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    item_instance_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int,
    name: str | None,
    summary: str | None,
    origin_notes: str | None = None,
    change_note: str | None = None,
) -> ContentWriteResult:
    normalize_reason(change_note)
    scope = lock_authoring_scope(
        connection,
        campaign_id=campaign_id,
        actor_user_id=actor_user_id,
        # D8/E2: item instances are created when loot is awarded; campaign authority
        # alone suffices (no world capability).
        world_capability=None,
    )
    locked = lock_entities(connection, world_id=scope.world_id, update_ids=[item_instance_id])
    target = editable_target(
        locked,
        entity_id=item_instance_id,
        type_codes=_ITEM,
        expected_row_version=expected_row_version,
    )
    clean_name = normalize_name(name)
    clean_summary = normalize_description(summary)
    clean_notes = normalize_origin_notes(origin_notes)
    current_notes = connection.execute(
        text("SELECT origin_notes FROM world.item_instances WHERE item_instance_id = :i"),
        {"i": item_instance_id},
    ).scalar()
    changed_fields = diff_fields(
        {"name": target.canonical_name, "summary": target.summary, "origin_notes": current_notes},
        {"name": clean_name, "summary": clean_summary, "origin_notes": clean_notes},
    )
    if not changed_fields:
        return ContentWriteResult(
            entity_id=item_instance_id,
            world_id=scope.world_id,
            entity_type_code=ITEM_TYPE,
            row_version=target.row_version,
            created=False,
            changed=False,
        )
    new_version = touch_entity(
        connection, entity_id=item_instance_id, name=clean_name, summary=clean_summary
    )
    if "origin_notes" in changed_fields:
        connection.execute(
            text("UPDATE world.item_instances SET origin_notes = :n WHERE item_instance_id = :i"),
            {"n": clean_notes, "i": item_instance_id},
        )
    return ContentWriteResult(
        entity_id=item_instance_id,
        world_id=scope.world_id,
        entity_type_code=ITEM_TYPE,
        row_version=new_version,
        created=False,
        changed=True,
        changed_fields=dict(changed_fields),
    )

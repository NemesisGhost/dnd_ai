"""Typed Religion authoring commands (Phase 15.1, ADR 0015).

A religion is a belief system (`world.religions`: `pantheon_structure`), distinct
from the religious organizations that serve it. `create_religion` and
`update_religion` write definition rows only. A religion refers to no other
record, so the only lock after the authority scope is the target itself.
"""

import uuid

from sqlalchemy import Connection, text

from dnd_ai.domain.authoring import normalize_description, normalize_name, normalize_reason
from dnd_ai.domain.content_authoring import diff_fields, initial_fields
from dnd_ai.domain.organization_authoring import (
    DESCRIPTION_FIELD_MAX_LENGTH,
    normalize_optional_text,
)

from ._content import (
    ContentWriteResult,
    editable_target,
    insert_draft_entity,
    insert_gm_source,
    lock_authoring_scope,
    lock_entities,
    touch_entity,
)

_RELIGION = frozenset({"religion"})


def _pantheon(value: str | None) -> str | None:
    return normalize_optional_text(
        value, field="pantheon_structure", max_length=DESCRIPTION_FIELD_MAX_LENGTH
    )


def create_religion(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    name: str | None,
    summary: str | None,
    pantheon_structure: str | None = None,
) -> ContentWriteResult:
    clean_name = normalize_name(name)
    clean_summary = normalize_description(summary)
    clean_pantheon = _pantheon(pantheon_structure)
    scope = lock_authoring_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    source_id = insert_gm_source(connection, world_id=scope.world_id, actor_user_id=actor_user_id)
    entity_id, row_version = insert_draft_entity(
        connection,
        world_id=scope.world_id,
        entity_type_code="religion",
        name=clean_name,
        summary=clean_summary,
        source_id=source_id,
        actor_user_id=actor_user_id,
    )
    connection.execute(
        text("INSERT INTO world.religions (religion_id, pantheon_structure) VALUES (:id, :p)"),
        {"id": entity_id, "p": clean_pantheon},
    )
    return ContentWriteResult(
        entity_id=entity_id,
        world_id=scope.world_id,
        entity_type_code="religion",
        row_version=row_version,
        created=True,
        changed=True,
        changed_fields=initial_fields(
            {"name": clean_name, "summary": clean_summary, "pantheon_structure": clean_pantheon}
        ),
        source_id=source_id,
    )


def update_religion(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    religion_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int,
    name: str | None,
    summary: str | None,
    pantheon_structure: str | None = None,
    change_note: str | None = None,
) -> ContentWriteResult:
    normalize_reason(change_note)
    scope = lock_authoring_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    locked = lock_entities(connection, world_id=scope.world_id, update_ids=[religion_id])
    target = editable_target(
        locked,
        entity_id=religion_id,
        type_codes=_RELIGION,
        expected_row_version=expected_row_version,
    )
    clean_name = normalize_name(name)
    clean_summary = normalize_description(summary)
    clean_pantheon = _pantheon(pantheon_structure)
    current_pantheon = connection.execute(
        text("SELECT pantheon_structure FROM world.religions WHERE religion_id = :id"),
        {"id": religion_id},
    ).scalar()
    changed_fields = diff_fields(
        {
            "name": target.canonical_name,
            "summary": target.summary,
            "pantheon_structure": current_pantheon,
        },
        {"name": clean_name, "summary": clean_summary, "pantheon_structure": clean_pantheon},
    )
    if not changed_fields:
        return ContentWriteResult(
            entity_id=religion_id,
            world_id=scope.world_id,
            entity_type_code="religion",
            row_version=target.row_version,
            created=False,
            changed=False,
        )
    new_version = touch_entity(
        connection, entity_id=religion_id, name=clean_name, summary=clean_summary
    )
    if "pantheon_structure" in changed_fields:
        connection.execute(
            text("UPDATE world.religions SET pantheon_structure = :p WHERE religion_id = :id"),
            {"p": clean_pantheon, "id": religion_id},
        )
    return ContentWriteResult(
        entity_id=religion_id,
        world_id=scope.world_id,
        entity_type_code="religion",
        row_version=new_version,
        created=False,
        changed=True,
        changed_fields=dict(changed_fields),
    )

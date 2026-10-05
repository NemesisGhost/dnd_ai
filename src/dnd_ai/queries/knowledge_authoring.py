"""Knowledge-item definition authoring read models (Phase 15.1).

For `canon.edit` holders only -- the route dependency enforces it first. The view
is the *claim* (statement, type, truth status, sensitivity, subject); who knows
it is per-knower state and never selected here.
"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import Connection, text

from dnd_ai.domain.content_authoring import evaluate_content_actions
from dnd_ai.domain.entity_lifecycle import BlockedAction
from dnd_ai.queries.content_preconditions import type_specific_blocks
from dnd_ai.queries.organization_authoring import ReferenceSummary, _reference


def list_knowledge_catalogs(
    connection: Connection,
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """(knowledge types, truth statuses) as `(code, label)` from the lookup
    tables, in their display order."""
    types = connection.execute(
        text("SELECT code, display_name FROM knowledge.knowledge_types ORDER BY sort_order, code")
    ).all()
    truths = connection.execute(
        text("SELECT code, display_name FROM knowledge.truth_statuses ORDER BY sort_order, code")
    ).all()
    return (
        [(str(r.code), str(r.display_name)) for r in types],
        [(str(r.code), str(r.display_name)) for r in truths],
    )


@dataclass(frozen=True)
class KnowledgeAuthoringView:
    knowledge_item_id: uuid.UUID
    statement: str
    knowledge_type: str
    truth_status: str
    sensitivity: str
    subject: ReferenceSummary | None
    in_use: bool
    canon_status: str
    lifecycle_status: str
    row_version: int
    available_actions: list[str]
    blocked_actions: list[BlockedAction]
    field_locks: list[str] = field(default_factory=list)


def get_knowledge_authoring(
    connection: Connection, *, world_id: uuid.UUID, knowledge_item_id: uuid.UUID
) -> KnowledgeAuthoringView | None:
    """The authoring view of a claim in `world_id`, or `None` if it does not exist
    there. `in_use` and `field_locks` tell the form which fields are frozen."""
    from dnd_ai.commands.knowledge_definitions import knowledge_item_in_use

    row = connection.execute(
        text("""
            SELECT e.row_version, cs.code AS canon_status, ls.code AS lifecycle_status,
                   ki.canonical_statement, kt.code AS knowledge_type, ts.code AS truth_status,
                   ki.sensitivity, ki.subject_entity_id
            FROM core.entities e
            JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
            JOIN core.canon_statuses cs ON cs.canon_status_id = e.canon_status_id
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = e.lifecycle_status_id
            JOIN knowledge.knowledge_items ki ON ki.knowledge_item_id = e.entity_id
            JOIN knowledge.knowledge_types kt ON kt.knowledge_type_id = ki.knowledge_type_id
            JOIN knowledge.truth_statuses ts ON ts.truth_status_id = ki.truth_status_id
            WHERE e.entity_id = :k AND e.world_id = :w AND et.code = 'knowledge_item'
        """),
        {"k": knowledge_item_id, "w": world_id},
    ).one_or_none()
    if row is None:
        return None
    extra_blocked = type_specific_blocks(
        connection, entity_id=knowledge_item_id, entity_type_code="knowledge_item"
    )
    available, blocked = evaluate_content_actions(
        entity_type_code="knowledge_item",
        canon_status=str(row.canon_status),
        lifecycle_status=str(row.lifecycle_status),
        extra_blocked=extra_blocked or None,
    )
    in_use = knowledge_item_in_use(connection, knowledge_item_id)
    return KnowledgeAuthoringView(
        knowledge_item_id=knowledge_item_id,
        statement=str(row.canonical_statement),
        knowledge_type=str(row.knowledge_type),
        truth_status=str(row.truth_status),
        sensitivity=str(row.sensitivity),
        subject=_reference(connection, row.subject_entity_id),
        in_use=in_use,
        canon_status=str(row.canon_status),
        lifecycle_status=str(row.lifecycle_status),
        row_version=int(row.row_version),
        available_actions=available,
        blocked_actions=blocked,
        field_locks=["statement", "knowledge_type", "subject"] if in_use else [],
    )


def knowledge_definition_states(
    connection: Connection, *, world_id: uuid.UUID, knowledge_item_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[str, str]]:
    """`(canon_status, lifecycle_status)` for claims in `world_id`, for editors'
    list rows only."""
    if not knowledge_item_ids:
        return {}
    rows = connection.execute(
        text("""
            SELECT e.entity_id, cs.code AS canon_status, ls.code AS lifecycle_status
            FROM core.entities e
            JOIN core.canon_statuses cs ON cs.canon_status_id = e.canon_status_id
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = e.lifecycle_status_id
            WHERE e.world_id = :w AND e.entity_id = ANY(CAST(:ids AS uuid[]))
        """),
        {"w": world_id, "ids": knowledge_item_ids},
    ).all()
    return {r.entity_id: (str(r.canon_status), str(r.lifecycle_status)) for r in rows}

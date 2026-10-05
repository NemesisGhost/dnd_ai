"""Typed Knowledge-item definition authoring commands (Phase 15.1, ADR 0015).

`create_knowledge_item` / `update_knowledge_item` author a *claim*: its
statement, `knowledge_type`, `truth_status`, sensitivity, and optional subject.
They write the definition only (`core.entities` + `knowledge.knowledge_items`);
who knows, believes, or has discovered a claim is per-knower state, and revealing
it is Phase 15.2.

**Statement freeze.** Once any per-knower, party, discovery, public-knowledge,
version, or event-effect row refers to the claim (`knowledge_item_in_use`),
changing its statement, type, or subject is refused with
`knowledge_already_known`: it would silently rewrite what knowers learned.
`truth_status` and `sensitivity` stay editable (audited): the GM may revise
objective truth, and per-knower belief is a separate fact. The reveal writer
takes the claim's entity row `FOR SHARE` (`require_state_targetable`), so the
check below cannot race the first reveal.

Lock order: authority scope, then entities by ascending id -- the claim
`FOR UPDATE`, a changed subject `FOR SHARE`.
"""

import uuid

from sqlalchemy import Connection, text

from dnd_ai.domain.authoring import (
    AuthoringValidationError,
    KnowledgeAlreadyKnownError,
    KnowledgeSubjectInvalidError,
    normalize_reason,
)
from dnd_ai.domain.content_authoring import diff_fields, initial_fields
from dnd_ai.domain.knowledge_authoring import (
    KNOWLEDGE_SUBJECT_TYPE_CODES,
    normalize_knowledge_fields,
    statement_to_name,
)

from ._content import (
    ContentWriteResult,
    editable_target,
    insert_draft_entity,
    insert_gm_source,
    lock_authoring_scope,
    lock_entities,
    touch_entity,
    usable_reference,
)

_KNOWLEDGE_ITEM = frozenset({"knowledge_item"})


def knowledge_item_in_use(connection: Connection, knowledge_item_id: uuid.UUID) -> bool:
    """Whether anything records that someone knows this claim, or refers to it
    from history."""
    return bool(
        connection.execute(
            text("""
                SELECT EXISTS (SELECT 1 FROM knowledge.entity_knowledge WHERE knowledge_item_id = :k)
                    OR EXISTS (SELECT 1 FROM campaign.party_knowledge WHERE knowledge_item_id = :k)
                    OR EXISTS (SELECT 1 FROM knowledge.party_discoveries WHERE knowledge_item_id = :k)
                    OR EXISTS (SELECT 1 FROM knowledge.public_knowledge WHERE knowledge_item_id = :k)
                    OR EXISTS (SELECT 1 FROM knowledge.knowledge_versions WHERE knowledge_item_id = :k)
                    OR EXISTS (SELECT 1 FROM narrative.event_effects
                               WHERE target_knowledge_item_id = :k)
            """),
            {"k": knowledge_item_id},
        ).scalar()
    )


def _lookup(connection: Connection, table: str, pk: str, code: str | None, field: str) -> uuid.UUID:
    value = connection.execute(
        text(f"SELECT {pk} FROM knowledge.{table} WHERE code = :c"), {"c": code}
    ).scalar()
    if value is None:
        raise AuthoringValidationError(f"{field} is not an allowed choice")
    assert isinstance(value, uuid.UUID)
    return value


def _text_id(value: uuid.UUID | None) -> str | None:
    return None if value is None else str(value)


def create_knowledge_item(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    statement: str | None,
    knowledge_type: str | None,
    truth_status: str | None,
    sensitivity: str | None,
    subject_entity_id: uuid.UUID | None = None,
) -> ContentWriteResult:
    fields = normalize_knowledge_fields(statement=statement, sensitivity=sensitivity)
    scope = lock_authoring_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    locked = lock_entities(
        connection,
        world_id=scope.world_id,
        share_ids=[subject_entity_id] if subject_entity_id is not None else [],
    )
    usable_reference(
        locked,
        subject_entity_id,
        type_codes=KNOWLEDGE_SUBJECT_TYPE_CODES,
        error=KnowledgeSubjectInvalidError,
    )
    type_id = _lookup(
        connection, "knowledge_types", "knowledge_type_id", knowledge_type, "knowledge_type"
    )
    truth_id = _lookup(
        connection, "truth_statuses", "truth_status_id", truth_status, "truth_status"
    )

    source_id = insert_gm_source(connection, world_id=scope.world_id, actor_user_id=actor_user_id)
    entity_id, row_version = insert_draft_entity(
        connection,
        world_id=scope.world_id,
        entity_type_code="knowledge_item",
        name=statement_to_name(fields.statement),
        summary=None,
        source_id=source_id,
        actor_user_id=actor_user_id,
    )
    connection.execute(
        text("""
            INSERT INTO knowledge.knowledge_items
                (knowledge_item_id, knowledge_type_id, truth_status_id, canonical_statement,
                 sensitivity, subject_entity_id)
            VALUES (:id, :type, :truth, :statement, :sensitivity, :subject)
        """),
        {
            "id": entity_id,
            "type": type_id,
            "truth": truth_id,
            "statement": fields.statement,
            "sensitivity": fields.sensitivity,
            "subject": subject_entity_id,
        },
    )
    return ContentWriteResult(
        entity_id=entity_id,
        world_id=scope.world_id,
        entity_type_code="knowledge_item",
        row_version=row_version,
        created=True,
        changed=True,
        changed_fields=initial_fields(
            {
                "statement": fields.statement,
                "knowledge_type": knowledge_type,
                "truth_status": truth_status,
                "sensitivity": fields.sensitivity,
                "subject_entity_id": _text_id(subject_entity_id),
            }
        ),
        source_id=source_id,
    )


def update_knowledge_item(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    knowledge_item_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int,
    statement: str | None,
    knowledge_type: str | None,
    truth_status: str | None,
    sensitivity: str | None,
    subject_entity_id: uuid.UUID | None = None,
    change_note: str | None = None,
) -> ContentWriteResult:
    normalize_reason(change_note)
    scope = lock_authoring_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    current_subject = connection.execute(
        text(
            "SELECT subject_entity_id FROM knowledge.knowledge_items WHERE knowledge_item_id = :k"
        ),
        {"k": knowledge_item_id},
    ).scalar()
    share_ids = (
        [subject_entity_id]
        if subject_entity_id is not None and subject_entity_id != current_subject
        else []
    )
    locked = lock_entities(
        connection, world_id=scope.world_id, update_ids=[knowledge_item_id], share_ids=share_ids
    )
    target = editable_target(
        locked,
        entity_id=knowledge_item_id,
        type_codes=_KNOWLEDGE_ITEM,
        expected_row_version=expected_row_version,
    )
    fields = normalize_knowledge_fields(statement=statement, sensitivity=sensitivity)
    current = connection.execute(
        text("""
            SELECT ki.canonical_statement, kt.code AS knowledge_type, ts.code AS truth_status,
                   ki.sensitivity, ki.subject_entity_id
            FROM knowledge.knowledge_items ki
            JOIN knowledge.knowledge_types kt ON kt.knowledge_type_id = ki.knowledge_type_id
            JOIN knowledge.truth_statuses ts ON ts.truth_status_id = ki.truth_status_id
            WHERE ki.knowledge_item_id = :k
        """),
        {"k": knowledge_item_id},
    ).one()
    changed = diff_fields(
        {
            "statement": current.canonical_statement,
            "knowledge_type": current.knowledge_type,
            "truth_status": current.truth_status,
            "sensitivity": current.sensitivity,
            "subject_entity_id": _text_id(current.subject_entity_id),
        },
        {
            "statement": fields.statement,
            "knowledge_type": knowledge_type,
            "truth_status": truth_status,
            "sensitivity": fields.sensitivity,
            "subject_entity_id": _text_id(subject_entity_id),
        },
    )
    if not changed:
        return ContentWriteResult(
            entity_id=knowledge_item_id,
            world_id=scope.world_id,
            entity_type_code="knowledge_item",
            row_version=target.row_version,
            created=False,
            changed=False,
        )
    if {"statement", "knowledge_type", "subject_entity_id"} & set(
        changed
    ) and knowledge_item_in_use(connection, knowledge_item_id):
        raise KnowledgeAlreadyKnownError(f"knowledge item {knowledge_item_id} is already known")
    if "subject_entity_id" in changed and subject_entity_id is not None:
        if subject_entity_id not in locked:
            locked.update(
                lock_entities(connection, world_id=scope.world_id, share_ids=[subject_entity_id])
            )
        usable_reference(
            locked,
            subject_entity_id,
            type_codes=KNOWLEDGE_SUBJECT_TYPE_CODES,
            error=KnowledgeSubjectInvalidError,
        )
    type_id = _lookup(
        connection, "knowledge_types", "knowledge_type_id", knowledge_type, "knowledge_type"
    )
    truth_id = _lookup(
        connection, "truth_statuses", "truth_status_id", truth_status, "truth_status"
    )

    new_version = touch_entity(
        connection,
        entity_id=knowledge_item_id,
        name=statement_to_name(fields.statement),
        summary=target.summary,
    )
    connection.execute(
        text("""
            UPDATE knowledge.knowledge_items
            SET knowledge_type_id = :type, truth_status_id = :truth,
                canonical_statement = :statement, sensitivity = :sensitivity,
                subject_entity_id = :subject
            WHERE knowledge_item_id = :k
        """),
        {
            "type": type_id,
            "truth": truth_id,
            "statement": fields.statement,
            "sensitivity": fields.sensitivity,
            "subject": subject_entity_id,
            "k": knowledge_item_id,
        },
    )
    return ContentWriteResult(
        entity_id=knowledge_item_id,
        world_id=scope.world_id,
        entity_type_code="knowledge_item",
        row_version=new_version,
        created=False,
        changed=True,
        changed_fields=dict(changed),
    )

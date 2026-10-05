"""Shared canon-lifecycle commands for entity definitions (Phase 14).

Nine intent-specific commands over `core.entities` — `submit_entity_for_review`,
`return_entity_to_draft`, `approve_entity`, `reject_entity`,
`publish_entity_as_canon`, `supersede_entity`, `archive_entity`,
`restore_entity`, and `delete_draft_entity` — for the entity types in
`dnd_ai.domain.entity_lifecycle.ENTITY_LIFECYCLE_ELIGIBLE_TYPE_CODES` only.
They change *status columns* and nothing else: creating or revising a
definition is a subtype-specific command (Phase 15), deliberately not shared.

Every command:

1. locks the campaign's **world `FOR SHARE`** (so the world cannot be archived
   underneath it), then the **entity row `FOR UPDATE`** (both as bare-row locks,
   with the status codes resolved by separate queries — see
   `dnd_ai.commands._shared.lifecycle_code`);
2. **binds the target**: an entity of another world, or no such entity, is the
   same non-disclosing 404 (`EntityNotFoundError`);
3. rejects an ineligible type (`LifecycleNotSupportedError`);
4. re-resolves `canon.edit` under those locks (the route dependency is only the
   first check; `created_by_user_id` is never read for authorization);
5. compares `expected_row_version` (`StaleWriteError`) — *approving or
   publishing binds to the version the reviewer saw*, so a draft edited after
   review cannot be approved by mistake — and only then
6. checks the transition against the shared pure policy
   (`dnd_ai.domain.entity_lifecycle`) that the read model also uses.

`supersede_entity` locks both entities in `entity_id` order. `delete_draft_entity`
physically deletes only a never-canon, unreferenced draft; what counts as a
*reference* is the reviewed `ENTITY_REFERENCE_CLASSIFICATION` below, backed by a
catalog test that fails when a new foreign key appears unclassified, so a new FK
can never silently become a cascade that destroys history. Restore and publish
additionally require the entity's subtype chain to be complete.
"""

import re
import uuid
from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import Connection, text

from dnd_ai.domain.authoring import (
    CharacterHasUserRelationshipsError,
    EntityReferencedError,
    QuestDefinitionIncompleteError,
    ReferenceNotPublishedError,
    StaleWriteError,
    SubtypeIncompleteError,
    SupersessionTargetInvalidError,
    normalize_reason,
)
from dnd_ai.domain.entity_lifecycle import (
    APPROVE,
    ARCHIVE,
    CANON_APPROVED,
    CANON_CANON,
    DELETE_DRAFT,
    PUBLISH,
    REJECT,
    RESTORE,
    RETURN_TO_DRAFT,
    SUBMIT_FOR_REVIEW,
    SUPERSEDE,
    require_lifecycle_eligible,
    require_transition,
    target_canon_status,
)
from dnd_ai.queries.content_preconditions import (
    archive_blocked_reason,
    publish_blocked_reason,
    publish_reference_ids,
    replacement_publish_blocked_reason,
)

from ._content import EntityNotFoundError as EntityNotFoundError
from ._content import LockedContent, lock_authoring_scope, lock_entities

_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")

OWNED_CASCADE: Literal["owned_cascade"] = "owned_cascade"
BLOCKING: Literal["blocking"] = "blocking"

# Every foreign key that references `core.entities.entity_id` or the primary key
# of an eligible type's subtype table, keyed by the REFERENCING
# (schema, table, column), classified once by review:
#
# - OWNED_CASCADE: rows that *belong to* the definition and may go with it (the
#   subtype chain, names, tags);
# - BLOCKING: anything else — a historical, relational, or state row that would
#   be destroyed or orphaned. A referenced draft cannot be deleted.
#
# `tests/database/test_entity_reference_classification.py` reads `pg_constraint`
# and fails when any referencing foreign key is missing here.
ENTITY_REFERENCE_CLASSIFICATION: dict[tuple[str, str, str], str] = {
    # --- owned: the definition's own rows -----------------------------------
    ("core", "entity_names", "entity_id"): OWNED_CASCADE,
    ("core", "entity_tags", "entity_id"): OWNED_CASCADE,
    # Canonical revision history (Phase 15, revision 117): removed with a deleted draft.
    ("core", "entity_revisions", "entity_id"): OWNED_CASCADE,
    ("world", "locations", "location_id"): OWNED_CASCADE,
    ("world", "settlements", "settlement_id"): OWNED_CASCADE,
    ("world", "buildings", "building_id"): OWNED_CASCADE,
    ("world", "organizations", "organization_id"): OWNED_CASCADE,
    ("world", "businesses", "business_id"): OWNED_CASCADE,
    ("world", "governments", "government_id"): OWNED_CASCADE,
    ("world", "military_units", "military_unit_id"): OWNED_CASCADE,
    ("world", "political_factions", "political_faction_id"): OWNED_CASCADE,
    ("world", "religions", "religion_id"): OWNED_CASCADE,
    ("world", "religious_organizations", "religious_organization_id"): OWNED_CASCADE,
    # --- blocking: references to core.entities -------------------------------
    ("ai", "agent_assignments", "entity_id"): BLOCKING,
    ("campaign", "inventory_entries", "holder_entity_id"): BLOCKING,
    ("campaign", "item_ownership", "owner_entity_id"): BLOCKING,
    ("campaign", "party_memberships", "member_entity_id"): BLOCKING,
    # A character that has taken part in a session keeps that history (15.2D-2).
    ("campaign", "session_participants", "character_id"): BLOCKING,
    ("campaign", "relationship_state", "perspective_holder_entity_id"): BLOCKING,
    ("integration", "external_identifiers", "entity_id"): BLOCKING,
    ("integration", "sync_jobs", "target_entity_id"): BLOCKING,
    ("integration", "sync_state", "target_entity_id"): BLOCKING,
    ("interaction", "actions", "actor_entity_id"): BLOCKING,
    ("interaction", "check_requests", "actor_entity_id"): BLOCKING,
    ("interaction", "targets", "target_entity_id"): BLOCKING,
    ("knowledge", "entity_knowledge", "knower_entity_id"): BLOCKING,
    ("knowledge", "information_transfers", "recipient_entity_id"): BLOCKING,
    ("knowledge", "item_identification", "knower_entity_id"): BLOCKING,
    ("knowledge", "knowledge_items", "subject_entity_id"): BLOCKING,
    ("knowledge", "party_discoveries", "knower_entity_id"): BLOCKING,
    ("narrative", "encounter_participants", "participant_entity_id"): BLOCKING,
    ("narrative", "event_effects", "target_entity_id"): BLOCKING,
    ("narrative", "event_observations", "observer_entity_id"): BLOCKING,
    ("narrative", "event_participants", "participant_entity_id"): BLOCKING,
    ("narrative", "events", "event_id"): BLOCKING,
    ("narrative", "quest_objectives", "target_entity_id"): BLOCKING,
    ("narrative", "quest_participants", "participant_entity_id"): BLOCKING,
    ("security", "resource_grants", "entity_id"): BLOCKING,
    ("world", "employment_relationships", "employee_entity_id"): BLOCKING,
    ("world", "employment_relationships", "employer_entity_id"): BLOCKING,
    ("world", "item_instances", "item_instance_id"): BLOCKING,
    ("world", "organization_memberships", "member_entity_id"): BLOCKING,
    ("world", "ownership_relationships", "owned_entity_id"): BLOCKING,
    ("world", "ownership_relationships", "owner_entity_id"): BLOCKING,
    ("world", "relationship_participants", "entity_id"): BLOCKING,
    ("world", "relationship_perspectives", "perspective_holder_entity_id"): BLOCKING,
    ("core", "entities", "superseded_by_entity_id"): BLOCKING,
    # --- blocking: references to eligible subtype tables ---------------------
    ("campaign", "character_location_history", "location_id"): BLOCKING,
    ("campaign", "inventory_entries", "location_id"): BLOCKING,
    ("campaign", "location_state", "location_id"): BLOCKING,
    ("character", "characters", "origin_location_id"): BLOCKING,
    ("knowledge", "public_knowledge", "location_id"): BLOCKING,
    ("narrative", "encounters", "location_id"): BLOCKING,
    ("narrative", "event_locations", "location_id"): BLOCKING,
    ("world", "dungeon_areas", "dungeon_area_id"): BLOCKING,
    ("world", "dungeons", "dungeon_id"): BLOCKING,
    ("world", "locations", "parent_location_id"): BLOCKING,
    ("world", "organizations", "headquarters_location_id"): BLOCKING,
    ("campaign", "organization_state", "organization_id"): BLOCKING,
    ("world", "organization_memberships", "organization_id"): BLOCKING,
    ("world", "organizations", "parent_organization_id"): BLOCKING,
    ("character", "character_religious_affiliations", "religion_id"): BLOCKING,
    ("world", "religious_organizations", "religion_id"): BLOCKING,
    # --- Phase 15.1: knowledge-item definitions -------------------------------
    # The claim's own row goes with a deleted draft; anything that records who
    # knows it, or refers to it from history, blocks the delete.
    ("knowledge", "knowledge_items", "knowledge_item_id"): OWNED_CASCADE,
    ("campaign", "party_knowledge", "knowledge_item_id"): BLOCKING,
    ("knowledge", "entity_knowledge", "knowledge_item_id"): BLOCKING,
    ("knowledge", "party_discoveries", "knowledge_item_id"): BLOCKING,
    ("knowledge", "public_knowledge", "knowledge_item_id"): BLOCKING,
    ("knowledge", "knowledge_versions", "knowledge_item_id"): BLOCKING,
    ("narrative", "event_effects", "target_knowledge_item_id"): BLOCKING,
    ("narrative", "quest_rewards", "reward_knowledge_item_id"): BLOCKING,
    ("security", "resource_grants", "knowledge_item_id"): BLOCKING,
    # --- Phase 15.1: quest definitions ----------------------------------------
    # A quest's own definition rows go with a deleted draft; recorded progress,
    # grants, and the objectives' event references block it.
    ("narrative", "quests", "quest_id"): OWNED_CASCADE,
    ("narrative", "quest_stages", "quest_id"): OWNED_CASCADE,
    ("narrative", "quest_participants", "quest_id"): OWNED_CASCADE,
    ("narrative", "quest_outcomes", "quest_id"): OWNED_CASCADE,
    ("campaign", "quest_state", "quest_id"): BLOCKING,
    ("security", "resource_grants", "quest_id"): BLOCKING,
    # --- Phase 15.1: NPC identity (an NPC is a character) ----------------------
    # The NPC's own identity rows go with a deleted draft ...
    ("character", "characters", "character_id"): OWNED_CASCADE,
    ("character", "npcs", "npc_id"): OWNED_CASCADE,
    ("character", "character_descriptions", "character_id"): OWNED_CASCADE,
    ("character", "character_languages", "character_id"): OWNED_CASCADE,
    ("character", "character_movements", "character_id"): OWNED_CASCADE,
    ("character", "character_senses", "character_id"): OWNED_CASCADE,
    # ... anything historical, mechanical, or access-granting blocks it.
    ("ai", "context_requests", "requesting_character_id"): BLOCKING,
    ("campaign", "character_conditions", "character_id"): BLOCKING,
    ("campaign", "character_location_history", "character_id"): BLOCKING,
    ("campaign", "character_resources", "character_id"): BLOCKING,
    ("campaign", "character_state", "character_id"): BLOCKING,
    ("campaign", "character_state", "transformed_into_id"): BLOCKING,
    ("campaign", "item_attunements", "character_id"): BLOCKING,
    ("character", "character_builds", "character_id"): BLOCKING,
    ("character", "character_religious_affiliations", "character_id"): BLOCKING,
    # A player character's marker row is part of its identity (Phase 15.2B-1).
    ("character", "player_characters", "player_character_id"): OWNED_CASCADE,
    ("knowledge", "character_expertise", "character_id"): BLOCKING,
    ("security", "membership_character_relationships", "character_id"): BLOCKING,
    ("security", "resource_grants", "character_id"): BLOCKING,
}

for _schema, _table, _column in ENTITY_REFERENCE_CLASSIFICATION:
    assert all(_IDENT.match(part) for part in (_schema, _table, _column))

_BLOCKING_REFERENCES = tuple(
    key for key, kind in ENTITY_REFERENCE_CLASSIFICATION.items() if kind == BLOCKING
)


@dataclass(frozen=True)
class EntityTransitionResult:
    entity_id: uuid.UUID
    world_id: uuid.UUID
    entity_type_code: str
    canon_status: str
    lifecycle_status: str
    row_version: int
    previous_canon_status: str
    previous_lifecycle_status: str
    deleted: bool = False
    changed_fields: dict[str, object] = field(default_factory=dict)
    # Set only by supersede: the replacement's own transition, if it changed.
    replacement: "EntityTransitionResult | None" = None


def _publish_reference_ids(
    connection: Connection, *, world_id: uuid.UUID, entity_id: uuid.UUID
) -> list[uuid.UUID]:
    """Records the entity must see published before it can be published, read
    without a lock so they can be locked in `entity_id` order with the target."""
    type_code = connection.execute(
        text("""
            SELECT et.code FROM core.entities e
            JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
            WHERE e.entity_id = :e AND e.world_id = :w
        """),
        {"e": entity_id, "w": world_id},
    ).scalar()
    if not isinstance(type_code, str):
        return []
    return publish_reference_ids(connection, entity_id=entity_id, entity_type_code=type_code)


def _prepare(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    entity_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int,
    action: str | None = None,
) -> tuple[uuid.UUID, LockedContent]:
    """Lock and authorize (scope, then entities in `entity_id` order: the target
    `FOR UPDATE`, and for publish the records it refers to `FOR SHARE`), bind the
    target to the campaign's world, and compare the version."""
    scope = lock_authoring_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    world_id = scope.world_id
    reference_ids = (
        _publish_reference_ids(connection, world_id=world_id, entity_id=entity_id)
        if action == PUBLISH
        else []
    )
    locked = lock_entities(
        connection, world_id=world_id, update_ids=[entity_id], share_ids=reference_ids
    )
    entity = locked.get(entity_id)
    if entity is None:
        raise EntityNotFoundError(f"entity {entity_id} is not in campaign {campaign_id}'s world")
    require_lifecycle_eligible(entity.entity_type_code)
    if entity.row_version != expected_row_version:
        raise StaleWriteError(f"entity {entity_id} is at {entity.row_version}")
    if action == PUBLISH:
        # The target is locked, so its references are now stable; lock any the
        # unlocked read missed (rare: the entity was edited in between).
        missing = [
            r
            for r in publish_reference_ids(
                connection, entity_id=entity_id, entity_type_code=entity.entity_type_code
            )
            if r not in locked
        ]
        if missing:
            lock_entities(connection, world_id=world_id, share_ids=missing)
    return world_id, entity


def _subtype_chain(connection: Connection, entity_type_id: uuid.UUID) -> list[tuple[str, str]]:
    """`(table, pk_column)` for the entity type and every ancestor that
    requires a subtype row, from the catalog (never from request data)."""
    rows = connection.execute(
        text("""
            WITH RECURSIVE chain AS (
                SELECT entity_type_id, parent_entity_type_id, required_subtype_table,
                       required_subtype_pk_column
                FROM core.entity_types WHERE entity_type_id = :t
                UNION ALL
                SELECT p.entity_type_id, p.parent_entity_type_id, p.required_subtype_table,
                       p.required_subtype_pk_column
                FROM core.entity_types p JOIN chain c ON p.entity_type_id = c.parent_entity_type_id
            )
            SELECT required_subtype_table, required_subtype_pk_column
            FROM chain WHERE required_subtype_table IS NOT NULL
        """),
        {"t": entity_type_id},
    ).all()
    return [(str(r.required_subtype_table), str(r.required_subtype_pk_column)) for r in rows]


def _quoted(schema_table: str, column: str) -> tuple[str, str]:
    parts = schema_table.split(".")
    if len(parts) != 2 or not all(_IDENT.match(p) for p in (*parts, column)):
        raise ValueError(f"unsafe catalog identifier {schema_table}.{column}")
    return f'"{parts[0]}"."{parts[1]}"', f'"{column}"'


def _require_subtype_complete(
    connection: Connection, *, entity_id: uuid.UUID, entity_type_id: uuid.UUID
) -> None:
    """Every subtype row the type's ancestry requires must exist. The database
    checks a subtype row matches its entity's type but never that one exists, so
    publishing or restoring a bare `core.entities` root would otherwise be
    accepted."""
    for table, pk in _subtype_chain(connection, entity_type_id):
        quoted_table, quoted_pk = _quoted(table, pk)
        present = connection.execute(
            text(f"SELECT EXISTS (SELECT 1 FROM {quoted_table} WHERE {quoted_pk} = :e)"),
            {"e": entity_id},
        ).scalar()
        if not present:
            raise SubtypeIncompleteError(f"entity {entity_id} lacks its {table} row")


def _has_blocking_references(connection: Connection, *, entity_id: uuid.UUID) -> bool:
    clauses = []
    for schema, table, column in _BLOCKING_REFERENCES:
        clauses.append(f'EXISTS (SELECT 1 FROM "{schema}"."{table}" WHERE "{column}" = :e)')
    return bool(
        connection.execute(text("SELECT " + " OR ".join(clauses)), {"e": entity_id}).scalar()
    )


def _result(
    entity: LockedContent,
    *,
    canon_status: str,
    lifecycle_status: str,
    row_version: int,
    **extra: object,
) -> EntityTransitionResult:
    return EntityTransitionResult(
        entity_id=entity.entity_id,
        world_id=entity.world_id,
        entity_type_code=entity.entity_type_code,
        canon_status=canon_status,
        lifecycle_status=lifecycle_status,
        row_version=row_version,
        previous_canon_status=entity.canon_status,
        previous_lifecycle_status=entity.lifecycle_status,
        **extra,  # type: ignore[arg-type]
    )


def _set_canon_status(connection: Connection, entity_id: uuid.UUID, status_code: str) -> int:
    new_version = connection.execute(
        text("""
            UPDATE core.entities
            SET canon_status_id =
                (SELECT canon_status_id FROM core.canon_statuses WHERE code = :code)
            WHERE entity_id = :e RETURNING row_version
        """),
        {"code": status_code, "e": entity_id},
    ).scalar()
    assert isinstance(new_version, int)
    return new_version


def _canon_transition(
    connection: Connection,
    *,
    action: str,
    campaign_id: uuid.UUID,
    entity_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int,
    reason: str | None = None,
) -> EntityTransitionResult:
    normalize_reason(reason)
    _world_id, entity = _prepare(
        connection,
        campaign_id=campaign_id,
        entity_id=entity_id,
        actor_user_id=actor_user_id,
        expected_row_version=expected_row_version,
        action=action,
    )
    require_transition(action, entity.canon_status, entity.lifecycle_status)
    target = target_canon_status(action, entity.canon_status)
    assert target is not None
    if action == PUBLISH:
        reason_code = publish_blocked_reason(
            connection, entity_id=entity_id, entity_type_code=entity.entity_type_code
        )
        if reason_code == "quest_definition_incomplete":
            raise QuestDefinitionIncompleteError(f"quest {entity_id} has no objective")
        if reason_code is not None:
            raise ReferenceNotPublishedError(f"entity {entity_id} refers to an unpublished record")
        _require_subtype_complete(
            connection, entity_id=entity_id, entity_type_id=entity.entity_type_id
        )
    new_version = _set_canon_status(connection, entity_id, target)
    return _result(
        entity,
        canon_status=target,
        lifecycle_status=entity.lifecycle_status,
        row_version=new_version,
    )


def submit_entity_for_review(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    entity_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int,
) -> EntityTransitionResult:
    """draft -> proposed."""
    return _canon_transition(
        connection,
        action=SUBMIT_FOR_REVIEW,
        campaign_id=campaign_id,
        entity_id=entity_id,
        actor_user_id=actor_user_id,
        expected_row_version=expected_row_version,
    )


def return_entity_to_draft(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    entity_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int,
    reason: str | None = None,
) -> EntityTransitionResult:
    """proposed | approved | rejected -> draft."""
    return _canon_transition(
        connection,
        action=RETURN_TO_DRAFT,
        campaign_id=campaign_id,
        entity_id=entity_id,
        actor_user_id=actor_user_id,
        expected_row_version=expected_row_version,
        reason=reason,
    )


def approve_entity(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    entity_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int,
) -> EntityTransitionResult:
    """proposed -> approved, bound to the reviewed `row_version`."""
    return _canon_transition(
        connection,
        action=APPROVE,
        campaign_id=campaign_id,
        entity_id=entity_id,
        actor_user_id=actor_user_id,
        expected_row_version=expected_row_version,
    )


def reject_entity(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    entity_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int,
    reason: str | None = None,
) -> EntityTransitionResult:
    """draft | proposed -> rejected."""
    return _canon_transition(
        connection,
        action=REJECT,
        campaign_id=campaign_id,
        entity_id=entity_id,
        actor_user_id=actor_user_id,
        expected_row_version=expected_row_version,
        reason=reason,
    )


def publish_entity_as_canon(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    entity_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int,
) -> EntityTransitionResult:
    """approved -> canon; the subtype chain must be complete."""
    return _canon_transition(
        connection,
        action=PUBLISH,
        campaign_id=campaign_id,
        entity_id=entity_id,
        actor_user_id=actor_user_id,
        expected_row_version=expected_row_version,
    )


def supersede_entity(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    entity_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int,
    replacement_entity_id: uuid.UUID,
    replacement_expected_row_version: int,
) -> EntityTransitionResult:
    """canon -> superseded, atomically linking the replacement. The replacement
    must be an active `approved` or `canon` entity of the same world and type
    (it is published to canon in the same transaction if still `approved`).
    Nonexistent, other-world, wrong-type, and wrong-status replacements are the
    same `SupersessionTargetInvalidError`. References to the old entity keep
    resolving: nothing is moved, deleted, or rewritten."""
    scope = lock_authoring_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    # The replacement may be published by this call, so the records it refers to
    # are locked `FOR SHARE` together with the pair, in ascending id order, exactly
    # as an ordinary publish does (read unlocked first, then any the read missed).
    reference_ids = _publish_reference_ids(
        connection, world_id=scope.world_id, entity_id=replacement_entity_id
    )
    locked = lock_entities(
        connection,
        world_id=scope.world_id,
        update_ids=sorted({entity_id, replacement_entity_id}),
        share_ids=reference_ids,
    )
    entity = locked.get(entity_id)
    if entity is None:
        raise EntityNotFoundError(f"entity {entity_id} is not in campaign {campaign_id}'s world")
    require_lifecycle_eligible(entity.entity_type_code)
    if entity.row_version != expected_row_version:
        raise StaleWriteError(f"entity {entity_id} is at {entity.row_version}")
    require_transition(SUPERSEDE, entity.canon_status, entity.lifecycle_status)

    replacement = locked.get(replacement_entity_id)
    if (
        replacement_entity_id == entity_id
        or replacement is None
        or replacement.entity_type_id != entity.entity_type_id
        or replacement.canon_status not in (CANON_APPROVED, CANON_CANON)
        or replacement.lifecycle_status != "active"
    ):
        raise SupersessionTargetInvalidError(f"replacement {replacement_entity_id} is not valid")
    if replacement.row_version != replacement_expected_row_version:
        raise StaleWriteError(
            f"replacement {replacement_entity_id} is at {replacement.row_version}"
        )

    replacement_result: EntityTransitionResult | None = None
    if replacement.canon_status == CANON_APPROVED:
        missing = [
            r
            for r in publish_reference_ids(
                connection,
                entity_id=replacement_entity_id,
                entity_type_code=replacement.entity_type_code,
            )
            if r not in locked
        ]
        if missing:
            lock_entities(connection, world_id=scope.world_id, share_ids=missing)
        reason_code = replacement_publish_blocked_reason(
            connection,
            superseded_id=entity_id,
            replacement_id=replacement_entity_id,
            replacement_type_code=replacement.entity_type_code,
            replacement_canon_status=replacement.canon_status,
        )
        if reason_code == "quest_definition_incomplete":
            raise QuestDefinitionIncompleteError(f"quest {replacement_entity_id} has no objective")
        if reason_code is not None:
            raise ReferenceNotPublishedError(
                f"replacement {replacement_entity_id} refers to an unpublished record"
            )
        _require_subtype_complete(
            connection, entity_id=replacement.entity_id, entity_type_id=replacement.entity_type_id
        )
        replacement_version = _set_canon_status(connection, replacement.entity_id, CANON_CANON)
        replacement_result = _result(
            replacement,
            canon_status=CANON_CANON,
            lifecycle_status=replacement.lifecycle_status,
            row_version=replacement_version,
        )

    new_version = connection.execute(
        text("""
            UPDATE core.entities
            SET canon_status_id =
                    (SELECT canon_status_id FROM core.canon_statuses WHERE code = 'superseded'),
                superseded_by_entity_id = :r
            WHERE entity_id = :e RETURNING row_version
        """),
        {"r": replacement_entity_id, "e": entity_id},
    ).scalar()
    assert isinstance(new_version, int)
    return _result(
        entity,
        canon_status="superseded",
        lifecycle_status=entity.lifecycle_status,
        row_version=new_version,
        changed_fields={"superseded_by_entity_id": str(replacement_entity_id)},
        replacement=replacement_result,
    )


def _set_lifecycle(
    connection: Connection, entity_id: uuid.UUID, status_code: str, *, archived: bool
) -> int:
    new_version = connection.execute(
        text("""
            UPDATE core.entities
            SET lifecycle_status_id =
                    (SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = :code),
                archived_at = CASE WHEN :archived THEN now() ELSE NULL END
            WHERE entity_id = :e RETURNING row_version
        """),
        {"code": status_code, "archived": archived, "e": entity_id},
    ).scalar()
    assert isinstance(new_version, int)
    return new_version


def archive_entity(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    entity_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int,
    reason: str | None = None,
) -> EntityTransitionResult:
    """Archive an active entity that is not in review. Canon status is kept."""
    normalize_reason(reason)
    _world_id, entity = _prepare(
        connection,
        campaign_id=campaign_id,
        entity_id=entity_id,
        actor_user_id=actor_user_id,
        expected_row_version=expected_row_version,
    )
    require_transition(ARCHIVE, entity.canon_status, entity.lifecycle_status)
    if (
        archive_blocked_reason(
            connection, entity_id=entity_id, entity_type_code=entity.entity_type_code
        )
        is not None
    ):
        raise CharacterHasUserRelationshipsError(f"entity {entity_id} is linked to a user")
    new_version = _set_lifecycle(connection, entity_id, "archived", archived=True)
    return _result(
        entity,
        canon_status=entity.canon_status,
        lifecycle_status="archived",
        row_version=new_version,
    )


def restore_entity(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    entity_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int,
    reason: str,
) -> EntityTransitionResult:
    """Restore an archived entity to active. A reason is required; canon status
    is unchanged (a superseded entity restores to superseded); the subtype chain
    must be complete."""
    normalize_reason(reason, required=True)
    _world_id, entity = _prepare(
        connection,
        campaign_id=campaign_id,
        entity_id=entity_id,
        actor_user_id=actor_user_id,
        expected_row_version=expected_row_version,
    )
    require_transition(RESTORE, entity.canon_status, entity.lifecycle_status)
    _require_subtype_complete(connection, entity_id=entity_id, entity_type_id=entity.entity_type_id)
    new_version = _set_lifecycle(connection, entity_id, "active", archived=False)
    return _result(
        entity, canon_status=entity.canon_status, lifecycle_status="active", row_version=new_version
    )


def delete_draft_entity(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    entity_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int,
    reason: str,
) -> EntityTransitionResult:
    """Physically delete a never-canon (`draft`/`rejected`), unreferenced draft.
    A reason is required. Only the reviewed owned rows (subtype chain, names,
    tags) go with it; anything else referencing it blocks the delete
    (`EntityReferencedError`). The audit row, written by the route from this
    result, survives the delete."""
    normalize_reason(reason, required=True)
    _world_id, entity = _prepare(
        connection,
        campaign_id=campaign_id,
        entity_id=entity_id,
        actor_user_id=actor_user_id,
        expected_row_version=expected_row_version,
    )
    require_transition(DELETE_DRAFT, entity.canon_status, entity.lifecycle_status)
    if _has_blocking_references(connection, entity_id=entity_id):
        raise EntityReferencedError(f"entity {entity_id} is referenced")
    connection.execute(text("DELETE FROM core.entities WHERE entity_id = :e"), {"e": entity_id})
    return _result(
        entity,
        canon_status=entity.canon_status,
        lifecycle_status=entity.lifecycle_status,
        row_version=entity.row_version,
        deleted=True,
        changed_fields={
            "canonical_name": entity.canonical_name,
            "entity_type_code": entity.entity_type_code,
        },
    )

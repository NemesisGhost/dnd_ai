"""Type-specific publish and archive preconditions (Phase 15.1, ADR 0015).

The hook the plan places "beside the eligibility registry": each authored type
names the records its definition refers to, and publishing is blocked while any
of them is not yet published (`canon` and `active`) -- otherwise a canon child
could sit under a draft parent and break breadcrumbs for readers who cannot see
the draft. Read-only SQL, called by **both** the lifecycle commands (after they
have locked the referenced rows `FOR SHARE`) and the read models that report
`blocked_actions`, so a preview cannot disagree with enforcement.
"""

import uuid

from sqlalchemy import Connection, text

from dnd_ai.domain.content_authoring import (
    AUTHORABLE_LOCATION_CATEGORIES,
    is_publish_reference_ready,
)
from dnd_ai.domain.organization_authoring import ORGANIZATION_ENTITY_TYPE_CODES

REFERENCE_NOT_PUBLISHED = "reference_not_published"
CHARACTER_HAS_USER_RELATIONSHIPS = "character_has_user_relationships"
QUEST_DEFINITION_INCOMPLETE = "quest_definition_incomplete"

# Characters whose identity is authored (NPC and player character): both reference an
# origin location and both are guarded against archive while a user is linked.
CHARACTER_IDENTITY_TYPE_CODES = frozenset({"npc", "player_character"})


def publish_reference_ids(
    connection: Connection, *, entity_id: uuid.UUID, entity_type_code: str
) -> list[uuid.UUID]:
    """The entities a definition must see published before it can be published.
    Empty for a type with no such references."""
    ids: list[uuid.UUID] = []
    if entity_type_code in AUTHORABLE_LOCATION_CATEGORIES:
        parent = connection.execute(
            text("SELECT parent_location_id FROM world.locations WHERE location_id = :e"),
            {"e": entity_id},
        ).scalar()
        if parent is not None:
            ids.append(parent)
    elif entity_type_code in CHARACTER_IDENTITY_TYPE_CODES:
        origin = connection.execute(
            text("SELECT origin_location_id FROM character.characters WHERE character_id = :e"),
            {"e": entity_id},
        ).scalar()
        if origin is not None:
            ids.append(origin)
    elif entity_type_code == "knowledge_item":
        subject = connection.execute(
            text(
                "SELECT subject_entity_id FROM knowledge.knowledge_items "
                "WHERE knowledge_item_id = :e"
            ),
            {"e": entity_id},
        ).scalar()
        if subject is not None:
            ids.append(subject)
    elif entity_type_code == "quest":
        ids.extend(
            connection.execute(
                text("""
                    SELECT DISTINCT qo.target_entity_id
                    FROM narrative.quest_stages qs
                    JOIN narrative.quest_objectives qo ON qo.quest_stage_id = qs.quest_stage_id
                    WHERE qs.quest_id = :e AND qo.target_entity_id IS NOT NULL
                """),
                {"e": entity_id},
            ).scalars()
        )
    elif entity_type_code in ORGANIZATION_ENTITY_TYPE_CODES:
        row = connection.execute(
            text("""
                SELECT o.parent_organization_id, o.headquarters_location_id, ro.religion_id
                FROM world.organizations o
                LEFT JOIN world.religious_organizations ro
                  ON ro.religious_organization_id = o.organization_id
                WHERE o.organization_id = :e
            """),
            {"e": entity_id},
        ).one_or_none()
        if row is not None:
            ids.extend(r for r in (row[0], row[1], row[2]) if r is not None)
    return ids


def publish_blocked_reason(
    connection: Connection, *, entity_id: uuid.UUID, entity_type_code: str
) -> str | None:
    """`quest_definition_incomplete` for a quest with no stage that has an
    objective; otherwise `reference_not_published` while any referenced record is
    not `canon` and `active`; otherwise `None`."""
    if entity_type_code == "quest":
        has_objective = connection.execute(
            text("""
                SELECT EXISTS (
                    SELECT 1
                    FROM narrative.quest_stages qs
                    JOIN narrative.quest_objectives qo ON qo.quest_stage_id = qs.quest_stage_id
                    WHERE qs.quest_id = :e
                )
            """),
            {"e": entity_id},
        ).scalar()
        if not has_objective:
            return QUEST_DEFINITION_INCOMPLETE
    for reference_id in publish_reference_ids(
        connection, entity_id=entity_id, entity_type_code=entity_type_code
    ):
        row = connection.execute(
            text("""
                SELECT cs.code AS canon_status, ls.code AS lifecycle_status
                FROM core.entities e
                JOIN core.canon_statuses cs ON cs.canon_status_id = e.canon_status_id
                JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = e.lifecycle_status_id
                WHERE e.entity_id = :r
            """),
            {"r": reference_id},
        ).one_or_none()
        if row is None or not is_publish_reference_ready(
            str(row.canon_status), str(row.lifecycle_status)
        ):
            return REFERENCE_NOT_PUBLISHED
    return None


def replacement_publish_blocked_reason(
    connection: Connection,
    *,
    superseded_id: uuid.UUID,
    replacement_id: uuid.UUID,
    replacement_type_code: str,
    replacement_canon_status: str,
) -> str | None:
    """Why `replacement_id` cannot take over from `superseded_id`. A `canon`
    replacement is already published and is valid under the existing-reference
    policy. An `approved` one is published by the supersession itself, so it must
    pass the ordinary publish preconditions, and must not depend on the record
    being superseded (that record stops being a valid reference in the same
    transaction)."""
    if replacement_canon_status != "approved":
        return None
    reason = publish_blocked_reason(
        connection, entity_id=replacement_id, entity_type_code=replacement_type_code
    )
    if reason is not None:
        return reason
    if superseded_id in publish_reference_ids(
        connection, entity_id=replacement_id, entity_type_code=replacement_type_code
    ):
        return REFERENCE_NOT_PUBLISHED
    return None


def archive_blocked_reason(
    connection: Connection, *, entity_id: uuid.UUID, entity_type_code: str
) -> str | None:
    """Type-specific archive blocks. An NPC or player character that a player or account is linked to
    through a current `security.membership_character_relationships` row cannot be
    archived: `resolve_access_context` stops honoring a relationship to an archived
    character, so archiving would silently revoke what the link grants."""
    if entity_type_code not in CHARACTER_IDENTITY_TYPE_CODES:
        return None
    linked = connection.execute(
        text("""
            SELECT EXISTS (
                SELECT 1 FROM security.membership_character_relationships mcr
                WHERE mcr.character_id = :e
                  AND mcr.revoked_at IS NULL
                  AND (mcr.expires_at IS NULL OR mcr.expires_at > now())
                  AND mcr.effective_to_world_time_id IS NULL
            )
        """),
        {"e": entity_id},
    ).scalar()
    return CHARACTER_HAS_USER_RELATIONSHIPS if linked else None


def type_specific_blocks(
    connection: Connection, *, entity_id: uuid.UUID, entity_type_code: str
) -> dict[str, str]:
    """`{action: reason}` for every lifecycle action this type blocks beyond the
    shared state table. The read models pass it to the pure action evaluation;
    the commands call the individual reasons above, so the two cannot differ."""
    blocks: dict[str, str] = {}
    publish = publish_blocked_reason(
        connection, entity_id=entity_id, entity_type_code=entity_type_code
    )
    if publish is not None:
        blocks["publish"] = publish
    archive = archive_blocked_reason(
        connection, entity_id=entity_id, entity_type_code=entity_type_code
    )
    if archive is not None:
        blocks["archive"] = archive
    return blocks

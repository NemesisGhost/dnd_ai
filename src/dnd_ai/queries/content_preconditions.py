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

REFERENCE_NOT_PUBLISHED = "reference_not_published"


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
    return ids


def publish_blocked_reason(
    connection: Connection, *, entity_id: uuid.UUID, entity_type_code: str
) -> str | None:
    """`reference_not_published` while any referenced record is not `canon` and
    `active`; otherwise `None`."""
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

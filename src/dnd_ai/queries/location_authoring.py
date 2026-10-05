"""Location authoring read models (Phase 15.1).

For `canon.edit` holders only (the route dependency enforces it before any of
this runs). The view is the **definition** -- never timeline state -- with the
server-computed `available_actions` / `blocked_actions` from the shared pure
policy (`dnd_ai.domain.content_authoring.evaluate_content_actions`) that the
commands also use.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, text

from dnd_ai.domain.content_authoring import (
    AUTHORABLE_LOCATION_CATEGORIES,
    LOCATION_CATEGORIES,
    LocationCategory,
    evaluate_content_actions,
    location_category,
)
from dnd_ai.domain.entity_lifecycle import BlockedAction
from dnd_ai.queries.content_preconditions import type_specific_blocks


@dataclass(frozen=True)
class ParentSummary:
    location_id: uuid.UUID
    name: str
    canon_status: str
    lifecycle_status: str


@dataclass(frozen=True)
class LocationAuthoringView:
    location_id: uuid.UUID
    name: str
    summary: str | None
    category: LocationCategory
    parent: ParentSummary | None
    population: int | None
    building_use: str | None
    canon_status: str
    lifecycle_status: str
    row_version: int
    available_actions: list[str]
    blocked_actions: list[BlockedAction]
    field_locks: list[str]


def list_location_categories() -> tuple[LocationCategory, ...]:
    return LOCATION_CATEGORIES


def get_location_authoring(
    connection: Connection, *, world_id: uuid.UUID, location_id: uuid.UUID
) -> LocationAuthoringView | None:
    """The authoring view of a location in `world_id`, or `None` if it does not
    exist there or is not an authorable place category (target binding)."""
    row = connection.execute(
        text("""
            SELECT e.canonical_name, e.summary, e.row_version, et.code AS type_code,
                   cs.code AS canon_status, ls.code AS lifecycle_status,
                   l.parent_location_id, s.population, b.building_use,
                   p.canonical_name AS parent_name,
                   pcs.code AS parent_canon_status, pls.code AS parent_lifecycle_status
            FROM core.entities e
            JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
            JOIN core.canon_statuses cs ON cs.canon_status_id = e.canon_status_id
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = e.lifecycle_status_id
            JOIN world.locations l ON l.location_id = e.entity_id
            LEFT JOIN world.settlements s ON s.settlement_id = e.entity_id
            LEFT JOIN world.buildings b ON b.building_id = e.entity_id
            LEFT JOIN core.entities p ON p.entity_id = l.parent_location_id
            LEFT JOIN core.canon_statuses pcs ON pcs.canon_status_id = p.canon_status_id
            LEFT JOIN core.lifecycle_statuses pls ON pls.lifecycle_status_id = p.lifecycle_status_id
            WHERE e.entity_id = :l AND e.world_id = :w
        """),
        {"l": location_id, "w": world_id},
    ).one_or_none()
    if row is None or row.type_code not in AUTHORABLE_LOCATION_CATEGORIES:
        return None
    extra_blocked = type_specific_blocks(
        connection, entity_id=location_id, entity_type_code=str(row.type_code)
    )
    available, blocked = evaluate_content_actions(
        entity_type_code=str(row.type_code),
        canon_status=str(row.canon_status),
        lifecycle_status=str(row.lifecycle_status),
        extra_blocked=extra_blocked or None,
    )
    parent = (
        None
        if row.parent_location_id is None
        else ParentSummary(
            location_id=row.parent_location_id,
            name=str(row.parent_name),
            canon_status=str(row.parent_canon_status),
            lifecycle_status=str(row.parent_lifecycle_status),
        )
    )
    return LocationAuthoringView(
        location_id=location_id,
        name=str(row.canonical_name),
        summary=row.summary,
        category=location_category(str(row.type_code)),
        parent=parent,
        population=row.population,
        building_use=row.building_use,
        canon_status=str(row.canon_status),
        lifecycle_status=str(row.lifecycle_status),
        row_version=int(row.row_version),
        available_actions=available,
        blocked_actions=blocked,
        field_locks=[],
    )


@dataclass(frozen=True)
class ParentOption:
    location_id: uuid.UUID
    name: str
    category: LocationCategory
    canon_status: str
    name_sort: str


def list_location_parent_options(
    connection: Connection,
    *,
    world_id: uuid.UUID,
    for_location_id: uuid.UUID | None,
    query_text: str | None,
    limit: int,
    after: tuple[str, uuid.UUID] | None,
) -> list[ParentOption]:
    """Locations that may be chosen as a parent: same world, an authorable
    place category, `active`, canon status in draft/proposed/approved/canon
    (`is_reference_eligible`), excluding `for_location_id` and everything it
    contains (choosing one would form a cycle). Fetches `limit + 1` rows ordered
    `(lower(name), id)` for keyset paging."""
    like = None
    if query_text:
        escaped = query_text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{escaped}%"
    rows = connection.execute(
        text("""
            WITH RECURSIVE excluded AS (
                SELECT l.location_id FROM world.locations l
                WHERE CAST(:for_id AS uuid) IS NOT NULL AND l.location_id = CAST(:for_id AS uuid)
                UNION
                SELECT c.location_id FROM world.locations c
                JOIN excluded x ON c.parent_location_id = x.location_id
            )
            SELECT e.entity_id, e.canonical_name, et.code AS type_code, cs.code AS canon_status,
                   lower(left(e.canonical_name, 200)) AS name_sort
            FROM core.entities e
            JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
            JOIN core.canon_statuses cs ON cs.canon_status_id = e.canon_status_id
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = e.lifecycle_status_id
            WHERE e.world_id = :w
              AND et.code = ANY(CAST(:categories AS text[]))
              AND ls.code = 'active'
              AND cs.code IN ('draft', 'proposed', 'approved', 'canon')
              AND e.entity_id NOT IN (SELECT location_id FROM excluded)
              AND (CAST(:like AS text) IS NULL
                   OR e.canonical_name ILIKE CAST(:like AS text) ESCAPE '\\')
              AND (CAST(:after_name AS text) IS NULL
                   OR (lower(left(e.canonical_name, 200)), e.entity_id)
                      > (CAST(:after_name AS text), CAST(:after_id AS uuid)))
            ORDER BY lower(left(e.canonical_name, 200)), e.entity_id
            LIMIT :limit
        """),
        {
            "w": world_id,
            "for_id": for_location_id,
            "categories": sorted(AUTHORABLE_LOCATION_CATEGORIES),
            "like": like,
            "after_name": None if after is None else after[0],
            "after_id": None if after is None else after[1],
            "limit": limit + 1,
        },
    ).all()
    return [
        ParentOption(
            location_id=row.entity_id,
            name=str(row.canonical_name),
            category=location_category(str(row.type_code)),
            canon_status=str(row.canon_status),
            name_sort=str(row.name_sort),
        )
        for row in rows
    ]

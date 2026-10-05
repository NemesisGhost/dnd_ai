"""Server-side option lists for the authoring forms' reference pickers
(Phase 15.1).

One keyset-paged query for "records this form may newly refer to": same world,
one of a closed set of entity types, `active`, and canon status draft / proposed
/ approved / canon -- exactly `dnd_ai.domain.content_authoring.
is_reference_eligible`, so the options offered and the references accepted agree.
The caller (a route behind `canon.edit`) supplies the closed `type_codes`; a
request never names a type.
"""

import uuid
from collections.abc import Collection
from dataclasses import dataclass

from sqlalchemy import Connection, text


@dataclass(frozen=True)
class ReferenceOptionRow:
    entity_id: uuid.UUID
    name: str
    entity_type_code: str
    canon_status: str
    name_sort: str


def descendant_ids(
    connection: Connection, *, table: str, pk: str, parent_column: str, root_id: uuid.UUID
) -> set[uuid.UUID]:
    """`root_id` and everything beneath it in a parent/child hierarchy, so an
    option list can omit choices that would form a cycle. `table`, `pk`, and
    `parent_column` are closed constants supplied by the calling query."""
    rows = connection.execute(
        text(f"""
            WITH RECURSIVE tree AS (
                SELECT {pk} AS node_id FROM {table} WHERE {pk} = :root
                UNION
                SELECT c.{pk} FROM {table} c JOIN tree t ON c.{parent_column} = t.node_id
            )
            SELECT node_id FROM tree
        """),
        {"root": root_id},
    ).scalars()
    return set(rows)


def list_reference_options(
    connection: Connection,
    *,
    world_id: uuid.UUID,
    type_codes: Collection[str],
    query_text: str | None,
    limit: int,
    after: tuple[str, uuid.UUID] | None,
    exclude_ids: Collection[uuid.UUID] = (),
) -> list[ReferenceOptionRow]:
    """Fetches `limit + 1` rows ordered `(lower(name), entity_id)` for keyset
    paging."""
    like = None
    if query_text:
        escaped = query_text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{escaped}%"
    rows = connection.execute(
        text("""
            SELECT e.entity_id, e.canonical_name, et.code AS type_code, cs.code AS canon_status,
                   lower(left(e.canonical_name, 200)) AS name_sort
            FROM core.entities e
            JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
            JOIN core.canon_statuses cs ON cs.canon_status_id = e.canon_status_id
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = e.lifecycle_status_id
            WHERE e.world_id = :w
              AND et.code = ANY(CAST(:types AS text[]))
              AND ls.code = 'active'
              AND cs.code IN ('draft', 'proposed', 'approved', 'canon')
              AND NOT (e.entity_id = ANY(CAST(:excluded AS uuid[])))
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
            "types": sorted(type_codes),
            "excluded": sorted(exclude_ids),
            "like": like,
            "after_name": None if after is None else after[0],
            "after_id": None if after is None else after[1],
            "limit": limit + 1,
        },
    ).all()
    return [
        ReferenceOptionRow(
            entity_id=row.entity_id,
            name=str(row.canonical_name),
            entity_type_code=str(row.type_code),
            canon_status=str(row.canon_status),
            name_sort=str(row.name_sort),
        )
        for row in rows
    ]

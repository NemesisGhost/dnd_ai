"""Entity canon-lifecycle read models and read-side visibility (Phase 14).

Two jobs:

1. **Read-side visibility** (`lifecycle_hidden_entity_ids`). The World Explorer's
   existing filters are built around a set of entity IDs the caller must not
   see (`dnd_ai.api.world_explorer`'s `denied_entity_ids`). Draft/published
   separation reuses that mechanism instead of duplicating predicates in every
   query: for entities of lifecycle-managed types
   (`ENTITY_LIFECYCLE_ELIGIBLE_TYPE_CODES`) the API adds the IDs this function
   returns to the denied set, so lists, search, detail routes, relationship
   participants, and event participants/locations all agree by construction.

   - **Reference mode** (detail routes, participants): a caller without
     `canon.edit` sees `canon`, `superseded`, and `deprecated` entities in any
     lifecycle except `deleted`, so archived and superseded definitions stay
     referenceable from history; a `canon.edit` caller sees everything except
     `deleted`.
   - **Browse mode** (lists and search): `canon` and `active` only, for every
     caller, unless a `canon.edit` caller opts into `include_noncanon` and/or
     `include_archived`. A non-`canon.edit` caller's flags are ignored
     silently, which discloses nothing.

2. **The lifecycle panel read model** (`get_entity_lifecycle`,
   `list_replacement_candidates`), with server-computed `available_actions` /
   `blocked_actions` from the same pure policy the commands enforce.
"""

import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import Connection, text

from dnd_ai.domain.entity_lifecycle import (
    ENTITY_LIFECYCLE_ELIGIBLE_TYPE_CODES,
    BlockedAction,
    evaluate_actions,
    is_lifecycle_eligible,
)
from dnd_ai.queries.content_preconditions import type_specific_blocks

REFERENCE_VISIBLE_CANON_STATUSES = ("canon", "superseded", "deprecated")


def lifecycle_hidden_entity_ids(
    connection: Connection,
    *,
    world_id: uuid.UUID,
    mode: Literal["reference", "browse"],
    can_edit_canon: bool,
    include_noncanon: bool = False,
    include_archived: bool = False,
) -> frozenset[uuid.UUID]:
    """IDs of lifecycle-managed entities in `world_id` the caller must not see
    in `mode`. Bounded by the number of non-published/archived definitions in
    one world; one query per request."""
    rows = connection.execute(
        text("""
            SELECT e.entity_id
            FROM core.entities e
            JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
            JOIN core.canon_statuses cs ON cs.canon_status_id = e.canon_status_id
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = e.lifecycle_status_id
            WHERE e.world_id = :world_id
              AND et.code = ANY(CAST(:eligible AS text[]))
              AND (
                    ls.code = 'deleted'
                    OR (
                        :mode = 'reference'
                        AND NOT CAST(:can_edit AS boolean)
                        AND NOT (cs.code = ANY(CAST(:reference_visible AS text[])))
                    )
                    OR (
                        :mode = 'browse'
                        AND NOT (
                            (cs.code = 'canon'
                             OR (CAST(:can_edit AS boolean) AND CAST(:inc_noncanon AS boolean)))
                            AND (ls.code = 'active'
                                 OR (CAST(:can_edit AS boolean) AND CAST(:inc_archived AS boolean)))
                        )
                    )
                  )
        """),
        {
            "world_id": world_id,
            "eligible": sorted(ENTITY_LIFECYCLE_ELIGIBLE_TYPE_CODES),
            "mode": mode,
            "can_edit": can_edit_canon,
            "inc_noncanon": include_noncanon,
            "inc_archived": include_archived,
            "reference_visible": list(REFERENCE_VISIBLE_CANON_STATUSES),
        },
    ).scalars()
    return frozenset(rows)


@dataclass(frozen=True)
class EntityLifecycleView:
    entity_id: uuid.UUID
    entity_type_code: str
    canonical_name: str
    canon_status: str
    lifecycle_status: str
    row_version: int
    lifecycle_managed: bool
    superseded_by_entity_id: uuid.UUID | None
    superseded_by_name: str | None
    available_actions: list[str]
    blocked_actions: list[BlockedAction]


def get_entity_lifecycle(
    connection: Connection, *, world_id: uuid.UUID, entity_id: uuid.UUID
) -> EntityLifecycleView | None:
    """The lifecycle panel's read model, only for an entity *in `world_id`*
    (target binding); `None` otherwise. `superseded_by` is included only when
    the replacement is itself in the same world (it always is, by trigger) and
    not deleted."""
    row = connection.execute(
        text("""
            SELECT e.entity_id, et.code AS entity_type_code, e.canonical_name,
                   cs.code AS canon_status, ls.code AS lifecycle_status, e.row_version,
                   e.superseded_by_entity_id, r.canonical_name AS replacement_name
            FROM core.entities e
            JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
            JOIN core.canon_statuses cs ON cs.canon_status_id = e.canon_status_id
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = e.lifecycle_status_id
            LEFT JOIN core.entities r ON r.entity_id = e.superseded_by_entity_id
            WHERE e.entity_id = :e AND e.world_id = :w
        """),
        {"e": entity_id, "w": world_id},
    ).one_or_none()
    if row is None:
        return None
    extra_blocked = type_specific_blocks(
        connection, entity_id=entity_id, entity_type_code=str(row.entity_type_code)
    )
    available, blocked = evaluate_actions(
        entity_type_code=str(row.entity_type_code),
        canon_status=str(row.canon_status),
        lifecycle_status=str(row.lifecycle_status),
        extra_blocked=extra_blocked or None,
    )
    return EntityLifecycleView(
        entity_id=row.entity_id,
        entity_type_code=str(row.entity_type_code),
        canonical_name=str(row.canonical_name),
        canon_status=str(row.canon_status),
        lifecycle_status=str(row.lifecycle_status),
        row_version=int(row.row_version),
        lifecycle_managed=is_lifecycle_eligible(str(row.entity_type_code)),
        superseded_by_entity_id=row.superseded_by_entity_id,
        superseded_by_name=row.replacement_name,
        available_actions=available,
        blocked_actions=blocked,
    )


@dataclass(frozen=True)
class ReplacementCandidate:
    entity_id: uuid.UUID
    canonical_name: str
    canon_status: str
    row_version: int
    name_sort: str


def list_replacement_candidates(
    connection: Connection,
    *,
    world_id: uuid.UUID,
    entity_id: uuid.UUID,
    query_text: str | None,
    limit: int,
    after: tuple[str, uuid.UUID] | None,
) -> list[ReplacementCandidate]:
    """Entities that could replace `entity_id`: same world, same entity type,
    `approved` or `canon`, active, excluding itself. Fetches `limit + 1` rows
    ordered `(lower(name), entity_id)` for keyset paging."""
    like = None
    if query_text:
        escaped = query_text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{escaped}%"
    rows = connection.execute(
        text("""
            SELECT c.entity_id, c.canonical_name, cs.code AS canon_status, c.row_version,
                   lower(left(c.canonical_name, 200)) AS name_sort
            FROM core.entities self
            JOIN core.entities c ON c.world_id = self.world_id
                                AND c.entity_type_id = self.entity_type_id
                                AND c.entity_id <> self.entity_id
            JOIN core.canon_statuses cs ON cs.canon_status_id = c.canon_status_id
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = c.lifecycle_status_id
            WHERE self.entity_id = :e AND self.world_id = :w
              AND cs.code IN ('approved', 'canon')
              AND ls.code = 'active'
              AND (CAST(:like AS text) IS NULL
                   OR c.canonical_name ILIKE CAST(:like AS text) ESCAPE '\\')
              AND (CAST(:after_name AS text) IS NULL
                   OR (lower(left(c.canonical_name, 200)), c.entity_id)
                      > (CAST(:after_name AS text), CAST(:after_id AS uuid)))
            ORDER BY lower(left(c.canonical_name, 200)), c.entity_id
            LIMIT :limit
        """),
        {
            "e": entity_id,
            "w": world_id,
            "like": like,
            "after_name": None if after is None else after[0],
            "after_id": None if after is None else after[1],
            "limit": limit + 1,
        },
    ).all()
    return [
        ReplacementCandidate(
            entity_id=row.entity_id,
            canonical_name=str(row.canonical_name),
            canon_status=str(row.canon_status),
            row_version=int(row.row_version),
            name_sort=str(row.name_sort),
        )
        for row in rows
    ]


@dataclass(frozen=True)
class EntityStatusSummary:
    canon_status: str
    lifecycle_status: str
    superseded_by_entity_id: uuid.UUID | None
    superseded_by_name: str | None


def get_entity_status_summary(
    connection: Connection, *, entity_id: uuid.UUID, hidden_entity_ids: frozenset[uuid.UUID]
) -> EntityStatusSummary:
    """Status fields a World Explorer detail response adds (Phase 14). The
    replacement of a superseded entity is named only when it is itself visible
    to the caller (`hidden_entity_ids` is the caller's reference-mode set)."""
    row = connection.execute(
        text("""
            SELECT cs.code AS canon_status, ls.code AS lifecycle_status,
                   e.superseded_by_entity_id, r.canonical_name AS replacement_name
            FROM core.entities e
            JOIN core.canon_statuses cs ON cs.canon_status_id = e.canon_status_id
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = e.lifecycle_status_id
            LEFT JOIN core.entities r ON r.entity_id = e.superseded_by_entity_id
            WHERE e.entity_id = :e
        """),
        {"e": entity_id},
    ).one()
    visible = (
        row.superseded_by_entity_id is not None
        and row.superseded_by_entity_id not in hidden_entity_ids
    )
    return EntityStatusSummary(
        canon_status=str(row.canon_status),
        lifecycle_status=str(row.lifecycle_status),
        superseded_by_entity_id=row.superseded_by_entity_id if visible else None,
        superseded_by_name=row.replacement_name if visible else None,
    )

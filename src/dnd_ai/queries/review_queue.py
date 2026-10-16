"""The review queue and revision history (Phase 15 checkpoint 15.3C-2, decision D-25).

`canon.edit` only; reads only. The queue lists the lifecycle-managed definitions of one world by
where they stand: drafts, in review (`proposed`), approved, rejected, or archived (the default,
`pending`, is every one of those that is still active and not yet canon). Each row says who made
its latest change, so a reviewer sees when they would be approving their own work (allowed and
audited under D-25). History lists an entity's revisions; a comparison reads the authored
snapshot at each version (a lifecycle revision only holds statuses, so it resolves to the latest
authored snapshot at or before its version).
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, text

from dnd_ai.domain.entity_lifecycle import ENTITY_LIFECYCLE_ELIGIBLE_TYPE_CODES
from dnd_ai.domain.revision_compare import Change, diff_snapshots

from .world_explorer import WORLD_CATEGORY_TYPE_CODES

STATUS_FILTERS = ("pending", "draft", "in_review", "approved", "rejected", "archived")

_CATEGORY_BY_TYPE = {
    code: category for category, codes in WORLD_CATEGORY_TYPE_CODES.items() for code in codes
}

# status filter -> SQL predicate over (cs = canon status, ls = lifecycle status)
_PREDICATES = {
    "pending": "ls.code = 'active' AND cs.code IN ('draft', 'proposed', 'approved', 'rejected')",
    "draft": "ls.code = 'active' AND cs.code = 'draft'",
    "in_review": "ls.code = 'active' AND cs.code = 'proposed'",
    "approved": "ls.code = 'active' AND cs.code = 'approved'",
    "rejected": "ls.code = 'active' AND cs.code = 'rejected'",
    "archived": "ls.code = 'archived'",
}


@dataclass(frozen=True)
class QueueRow:
    entity_id: uuid.UUID
    name: str
    entity_type_code: str
    category: str | None
    canon_status: str
    lifecycle_status: str
    row_version: int
    updated_at: datetime
    last_change_by: str | None
    last_change_by_me: bool


@dataclass(frozen=True)
class RevisionRow:
    row_version: int
    kind: str
    created_at: datetime
    created_by_name: str | None
    canon_status: str | None
    lifecycle_status: str | None


@dataclass(frozen=True)
class RevisionHistory:
    entity_id: uuid.UUID
    name: str
    entity_type_code: str
    canon_status: str
    lifecycle_status: str
    row_version: int
    revisions: list[RevisionRow] = field(default_factory=list)


@dataclass(frozen=True)
class Comparison:
    entity_id: uuid.UUID
    name: str
    from_version: int
    to_version: int
    from_authored_version: int | None
    to_authored_version: int | None
    changes: list[Change]


def review_status_counts(connection: Connection, *, world_id: uuid.UUID) -> dict[str, int]:
    counts: dict[str, int] = {}
    for status, predicate in _PREDICATES.items():
        if status == "pending":
            continue
        counts[status] = int(
            connection.execute(
                text(  # noqa: S608 - the predicate comes from the fixed table above
                    "SELECT count(*) FROM core.entities e "
                    "JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id "
                    "JOIN core.canon_statuses cs ON cs.canon_status_id = e.canon_status_id "
                    "JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = e.lifecycle_status_id "
                    "WHERE e.world_id = :w AND et.code = ANY(:types) AND " + predicate
                ),
                {"w": world_id, "types": sorted(ENTITY_LIFECYCLE_ELIGIBLE_TYPE_CODES)},
            ).scalar()
            or 0
        )
    return counts


def list_review_queue(
    connection: Connection,
    *,
    world_id: uuid.UUID,
    viewer_user_id: uuid.UUID,
    status: str,
    type_code: str | None,
    after: tuple[str, uuid.UUID] | None,
    limit: int,
) -> list[QueueRow]:
    """Newest change first; fetches `limit + 1` rows so the caller can tell there is more."""
    predicate = _PREDICATES[status]
    types = (
        [type_code]
        if type_code is not None and type_code in ENTITY_LIFECYCLE_ELIGIBLE_TYPE_CODES
        else sorted(ENTITY_LIFECYCLE_ELIGIBLE_TYPE_CODES)
    )
    if type_code is not None and type_code not in ENTITY_LIFECYCLE_ELIGIBLE_TYPE_CODES:
        return []
    keyset = ""
    params: dict[str, Any] = {"w": world_id, "types": types, "limit": limit + 1}
    if after is not None:
        keyset = "AND (e.updated_at, e.entity_id) < (CAST(:after_at AS timestamptz), :after_id)"
        params["after_at"], params["after_id"] = after
    rows = connection.execute(
        text(  # noqa: S608 - the predicate comes from the fixed table above
            """
            SELECT e.entity_id, e.canonical_name, et.code AS type_code, cs.code AS canon,
                   ls.code AS lifecycle, e.row_version, e.updated_at,
                   r.created_by_user_id AS changed_by, u.display_name AS changed_by_name
            FROM core.entities e
            JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
            JOIN core.canon_statuses cs ON cs.canon_status_id = e.canon_status_id
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = e.lifecycle_status_id
            LEFT JOIN core.entity_revisions r
                   ON r.entity_id = e.entity_id AND r.row_version = e.row_version
            LEFT JOIN security.users u ON u.user_id = r.created_by_user_id
            WHERE e.world_id = :w AND et.code = ANY(:types) AND """
            + predicate
            + " "
            + keyset
            + """
            ORDER BY e.updated_at DESC, e.entity_id DESC
            LIMIT :limit
            """
        ),
        {**params, "types": types},
    ).all()
    return [
        QueueRow(
            entity_id=r.entity_id,
            name=str(r.canonical_name),
            entity_type_code=str(r.type_code),
            category=_CATEGORY_BY_TYPE.get(str(r.type_code)),
            canon_status=str(r.canon),
            lifecycle_status=str(r.lifecycle),
            row_version=int(r.row_version),
            updated_at=r.updated_at,
            last_change_by=None if r.changed_by_name is None else str(r.changed_by_name),
            last_change_by_me=r.changed_by == viewer_user_id,
        )
        for r in rows
    ]


def get_revision_history(
    connection: Connection, *, world_id: uuid.UUID, entity_id: uuid.UUID
) -> RevisionHistory | None:
    head = connection.execute(
        text("""
            SELECT e.canonical_name, et.code AS type_code, cs.code AS canon, ls.code AS lifecycle,
                   e.row_version
            FROM core.entities e
            JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
            JOIN core.canon_statuses cs ON cs.canon_status_id = e.canon_status_id
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = e.lifecycle_status_id
            WHERE e.entity_id = :e AND e.world_id = :w
        """),
        {"e": entity_id, "w": world_id},
    ).one_or_none()
    if head is None:
        return None
    rows = connection.execute(
        text("""
            SELECT r.row_version, r.revision_kind, r.created_at, u.display_name,
                   r.snapshot ->> 'canon_status' AS canon,
                   r.snapshot ->> 'lifecycle_status' AS lifecycle
            FROM core.entity_revisions r
            LEFT JOIN security.users u ON u.user_id = r.created_by_user_id
            WHERE r.entity_id = :e AND r.world_id = :w
            ORDER BY r.row_version DESC
        """),
        {"e": entity_id, "w": world_id},
    ).all()
    return RevisionHistory(
        entity_id=entity_id,
        name=str(head.canonical_name),
        entity_type_code=str(head.type_code),
        canon_status=str(head.canon),
        lifecycle_status=str(head.lifecycle),
        row_version=int(head.row_version),
        revisions=[
            RevisionRow(
                row_version=int(r.row_version),
                kind=str(r.revision_kind),
                created_at=r.created_at,
                created_by_name=None if r.display_name is None else str(r.display_name),
                canon_status=r.canon if r.revision_kind == "lifecycle" else None,
                lifecycle_status=r.lifecycle if r.revision_kind == "lifecycle" else None,
            )
            for r in rows
        ],
    )


def _authored_snapshot(
    connection: Connection, *, world_id: uuid.UUID, entity_id: uuid.UUID, version: int
) -> tuple[int, dict[str, Any]] | None:
    """The latest created or updated snapshot at or before `version`, with its own version."""
    row = connection.execute(
        text("""
            SELECT row_version, snapshot FROM core.entity_revisions
            WHERE entity_id = :e AND world_id = :w AND row_version <= :v
              AND revision_kind IN ('created', 'updated')
            ORDER BY row_version DESC LIMIT 1
        """),
        {"e": entity_id, "w": world_id, "v": version},
    ).one_or_none()
    if row is None:
        return None
    snapshot = row.snapshot
    return int(row.row_version), dict(snapshot) if isinstance(snapshot, dict) else {}


def compare_revisions(
    connection: Connection,
    *,
    world_id: uuid.UUID,
    entity_id: uuid.UUID,
    from_version: int,
    to_version: int,
) -> Comparison | None:
    """`None` when the entity is not in the world or either version has no revision at all."""
    head = get_revision_history(connection, world_id=world_id, entity_id=entity_id)
    if head is None:
        return None
    existing = {r.row_version for r in head.revisions}
    if from_version not in existing or to_version not in existing:
        return None
    before = _authored_snapshot(
        connection, world_id=world_id, entity_id=entity_id, version=from_version
    )
    after = _authored_snapshot(
        connection, world_id=world_id, entity_id=entity_id, version=to_version
    )
    changes = diff_snapshots(
        {} if before is None else before[1],
        {} if after is None else after[1],
    )
    return Comparison(
        entity_id=entity_id,
        name=head.name,
        from_version=from_version,
        to_version=to_version,
        from_authored_version=None if before is None else before[0],
        to_authored_version=None if after is None else after[0],
        changes=changes,
    )

"""Review queue and revision history endpoints (Phase 15 checkpoint 15.3C-2, decision D-25).

    GET /campaigns/{id}/review-queue?status=&type=&cursor=&limit=
    GET /campaigns/{id}/entities/{eid}/revisions
    GET /campaigns/{id}/entities/{eid}/revisions/compare?from=&to=

All reads, all `canon.edit`, all scoped to the campaign's world; a record of another world is
indistinguishable from a missing one. The queue pages by keyset (newest change first). The
authored snapshots are GM-only and are shown here only because the caller can edit canon; no
audit field is returned. Self-approval is allowed and audited (see the lifecycle approve route).
"""

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Connection

from dnd_ai.domain.access import AccessContext
from dnd_ai.domain.entity_lifecycle import ENTITY_LIFECYCLE_ELIGIBLE_TYPE_CODES
from dnd_ai.domain.world_authority import WORLD_CANON_READ_PRIVATE
from dnd_ai.queries.review_queue import (
    STATUS_FILTERS,
    compare_revisions,
    get_revision_history,
    list_review_queue,
    review_status_counts,
)

from ._shared import timeline_world_id
from .access import require_campaign_capability
from .deps import get_connection
from .errors import InvalidCursorError, NotFoundError
from .pagination import build_page, decode_typed_cursor

router = APIRouter(tags=["review"])

_Access = Annotated[AccessContext, Depends(require_campaign_capability("canon.edit"))]
# Reads of the private side of shared world canon (drafts, GM-only prep, revisions,
# provenance, sources, the review queue) also need `world.canon.read_private`
# (docs/adr/0020-scoped-system-world-and-campaign-roles.md, D6).
_PrivateRead = Annotated[
    AccessContext,
    Depends(require_campaign_capability("canon.edit", world_capability=WORLD_CANON_READ_PRIVATE)),
]
_Conn = Annotated[Connection, Depends(get_connection)]

_KEYSET = "review_queue"
_DEFAULT_LIMIT = 25
_MAX_LIMIT = 100

_STATUS_LABELS = {
    "pending": "Needs attention",
    "draft": "Drafts",
    "in_review": "In review",
    "approved": "Approved, not yet published",
    "rejected": "Rejected",
    "archived": "Archived",
}


@router.get("/campaigns/{campaign_id}/review-queue")
def review_queue_endpoint(
    access: _PrivateRead,
    connection: _Conn,
    status: Annotated[
        Literal["pending", "draft", "in_review", "approved", "rejected", "archived"], Query()
    ] = "pending",
    type: Annotated[str | None, Query(max_length=60)] = None,  # noqa: A002 - the query name
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
    limit: Annotated[int, Query(ge=1, le=_MAX_LIMIT)] = _DEFAULT_LIMIT,
) -> dict[str, Any]:
    world_id = timeline_world_id(connection, access.timeline_id)
    decoded = decode_typed_cursor(cursor, keyset=_KEYSET, fields=["str", "uuid"])
    after: tuple[str, uuid.UUID] | None = None
    if decoded is not None:
        stamp, entity_id = decoded
        if not isinstance(stamp, str) or not isinstance(entity_id, uuid.UUID):
            raise InvalidCursorError()
        after = (stamp, entity_id)
    rows = list_review_queue(
        connection,
        world_id=world_id,
        viewer_user_id=access.user_id,
        status=status,
        type_code=type,
        after=after,
        limit=limit,
    )
    page = build_page(
        rows,
        limit=limit,
        keyset=_KEYSET,
        cursor_key=lambda r: (r.updated_at.isoformat(), r.entity_id),
    )
    return {
        "items": [
            {
                "entity_id": str(r.entity_id),
                "name": r.name,
                "entity_type_code": r.entity_type_code,
                "category": r.category,
                "canon_status": r.canon_status,
                "lifecycle_status": r.lifecycle_status,
                "row_version": r.row_version,
                "updated_at": r.updated_at.isoformat(),
                "last_change_by": r.last_change_by,
                "last_change_by_me": r.last_change_by_me,
            }
            for r in page.items
        ],
        "next_cursor": page.next_cursor,
        "status": status,
        "statuses": [{"value": s, "label": _STATUS_LABELS[s]} for s in STATUS_FILTERS],
        "types": sorted(ENTITY_LIFECYCLE_ELIGIBLE_TYPE_CODES),
        "counts": review_status_counts(connection, world_id=world_id),
    }


@router.get("/campaigns/{campaign_id}/entities/{entity_id}/revisions")
def revisions_endpoint(
    entity_id: uuid.UUID, access: _PrivateRead, connection: _Conn
) -> dict[str, Any]:
    history = get_revision_history(
        connection, world_id=timeline_world_id(connection, access.timeline_id), entity_id=entity_id
    )
    if history is None:
        raise NotFoundError()
    return {
        "entity_id": str(history.entity_id),
        "name": history.name,
        "entity_type_code": history.entity_type_code,
        "canon_status": history.canon_status,
        "lifecycle_status": history.lifecycle_status,
        "row_version": history.row_version,
        "revisions": [
            {
                "row_version": r.row_version,
                "kind": r.kind,
                "created_at": r.created_at.isoformat(),
                "created_by_name": r.created_by_name,
                "canon_status": r.canon_status,
                "lifecycle_status": r.lifecycle_status,
            }
            for r in history.revisions
        ],
    }


@router.get("/campaigns/{campaign_id}/entities/{entity_id}/revisions/compare")
def compare_endpoint(
    entity_id: uuid.UUID,
    access: _PrivateRead,
    connection: _Conn,
    from_version: Annotated[int, Query(alias="from", ge=1)],
    to_version: Annotated[int, Query(alias="to", ge=1)],
) -> dict[str, Any]:
    comparison = compare_revisions(
        connection,
        world_id=timeline_world_id(connection, access.timeline_id),
        entity_id=entity_id,
        from_version=from_version,
        to_version=to_version,
    )
    if comparison is None:
        raise NotFoundError()
    return {
        "entity_id": str(comparison.entity_id),
        "name": comparison.name,
        "from_version": comparison.from_version,
        "to_version": comparison.to_version,
        "from_authored_version": comparison.from_authored_version,
        "to_authored_version": comparison.to_authored_version,
        "changes": [
            {
                "path": c.path,
                "kind": c.kind,
                "before": c.before,
                "after": c.after,
                "truncated": c.truncated,
            }
            for c in comparison.changes
        ],
    }

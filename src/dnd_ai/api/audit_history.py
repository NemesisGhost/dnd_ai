"""`GET /campaigns/{campaign_id}/audit-history` — the campaign-scoped,
access-controlled, read-only audit-history endpoint backing a future
Access-page "Audit history" panel (Phase 13E-B audit-history workstream;
see `docs/AUDIT_HISTORY_API.md` for the full contract and
`dnd_ai.queries.audit_history` for the query itself, including why this is
scoped to a curated `command_name` allowlist rather than every
`audit.change_log` row touching the campaign's world).

Authorization: `access.manage` — the identical capability every other
campaign-access-management route in `dnd_ai.api.access_overview`/
`.memberships`/`.access_grants` already requires
(`docs/PHASE13E_ACCESS_CONTRACT.md` confirms no dedicated audit-viewing
capability exists yet, and that this endpoint itself did not exist before
this workstream — §5, "Any audit-history read endpoint ... no route reads
them back"). A non-member, or a member who does not hold `access.manage`,
gets the identical non-disclosing 404 `require_campaign_capability`
already gives `access-overview` (an authenticated member without the
capability gets 403 instead — see that dependency's own docstring for the
"404 vs 403" split this route inherits unchanged).

This is a pure read: no idempotency key, no `audit.change_log` row of its
own, no mutation of anything. Never returns raw `audit.change_log` JSON —
every field is drawn from `dnd_ai.queries.audit_history.AuditHistoryItem`,
itself a server-generated, reviewed projection (see that module's
docstring for the exact safe/unsafe field split)."""

import uuid
from datetime import datetime
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import Connection

from dnd_ai.domain.access import AccessContext
from dnd_ai.queries.audit_history import (
    KEYSET,
    list_campaign_audit_history,
)

from .access import require_campaign_capability
from .deps import get_connection
from .pagination import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    build_page,
    decode_typed_cursor,
)

router = APIRouter(tags=["audit-history"])

_AUDIT_HISTORY_CAPABILITY = "access.manage"

AuditHistoryCategory = Literal[
    "membership", "role", "character_relationship", "resource_grant", "invitation", "campaign"
]
AuditActorType = Literal["user", "service", "unknown"]
AuditTargetType = Literal["account", "character", "access_group"]


class AuditHistoryItemResponse(BaseModel):
    change_log_id: int
    """Identity only, for a React list key — never rendered as page text."""
    occurred_at: datetime
    category: AuditHistoryCategory
    action_label: str
    actor_label: str
    actor_type: AuditActorType
    target_label: str | None
    target_type: AuditTargetType | None
    change_summary: str | None
    outcome: str | None


class AuditHistoryListResponse(BaseModel):
    items: list[AuditHistoryItemResponse]
    next_cursor: str | None


@router.get(
    "/campaigns/{campaign_id}/audit-history",
    response_model=AuditHistoryListResponse,
    status_code=200,
)
def list_campaign_audit_history_endpoint(
    campaign_id: uuid.UUID,
    access: Annotated[  # noqa: ARG001 — required only to enforce the access.manage capability
        AccessContext, Depends(require_campaign_capability(_AUDIT_HISTORY_CAPABILITY))
    ],
    connection: Annotated[Connection, Depends(get_connection)],
    category: Annotated[AuditHistoryCategory | None, Query()] = None,
    actor_user_id: Annotated[uuid.UUID | None, Query()] = None,
    occurred_from: Annotated[datetime | None, Query()] = None,
    occurred_to: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    cursor: Annotated[str | None, Query()] = None,
) -> AuditHistoryListResponse:
    """Newest-first (`occurred_at DESC`, `change_log_id` tie-breaker),
    cursor-paginated, bounded-page-size campaign audit history. `category`
    restricts to one of `dnd_ai.queries.audit_history.AUDIT_CATEGORIES`; a
    value outside that closed set is rejected by FastAPI's own `Literal`
    validation (422) before this handler ever runs — the malformed-filter
    contract the workstream spec requires. `occurred_from`/`occurred_to`
    accept any ISO-8601 datetime FastAPI/pydantic parses; a non-ISO value
    is likewise a 422 before this handler runs. An empty campaign history,
    or a request whose filters simply match nothing, returns `{"items":
    [], "next_cursor": null}` — never an error."""
    keyset = decode_typed_cursor(cursor, keyset=KEYSET, fields=("str", "int_or_none"))
    after_recorded_at: datetime | None = None
    after_change_log_id: int | None = None
    if keyset is not None:
        after_recorded_at = datetime.fromisoformat(cast(str, keyset[0]))
        raw_id = keyset[1]
        after_change_log_id = int(cast(int, raw_id)) if raw_id is not None else None

    items = list_campaign_audit_history(
        connection,
        campaign_id=campaign_id,
        category=category,
        actor_user_id=actor_user_id,
        occurred_from=occurred_from,
        occurred_to=occurred_to,
        limit=limit,
        after_recorded_at=after_recorded_at,
        after_change_log_id=after_change_log_id,
    )

    page = build_page(
        items,
        limit=limit,
        keyset=KEYSET,
        cursor_key=lambda item: [item.occurred_at.isoformat(), item.change_log_id],
    )

    return AuditHistoryListResponse(
        items=[
            AuditHistoryItemResponse(
                change_log_id=item.change_log_id,
                occurred_at=item.occurred_at,
                category=cast(AuditHistoryCategory, item.category),
                action_label=item.action_label,
                actor_label=item.actor_label,
                actor_type=cast(AuditActorType, item.actor_type),
                target_label=item.target_label,
                target_type=cast("AuditTargetType | None", item.target_type),
                change_summary=item.change_summary,
                outcome=item.outcome,
            )
            for item in page.items
        ],
        next_cursor=page.next_cursor,
    )

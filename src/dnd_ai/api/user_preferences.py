"""Self-service portal preference endpoints (docs/UI_DESIGN.md §4.7).

Both are `PUT` set operations on the caller's own `security.
user_portal_preferences` row, reachable by any human auth method
(`require_human_user_id`). For cookie sessions the central
`get_authenticated_user_id` dependency already enforces the CSRF token and
allowed `Origin` on every `PUT`; nothing here re-implements that.

Status/error behavior: 204 on success; 401 without a valid session; 403 on a
CSRF/Origin failure; 404 — one fixed, non-disclosing body — for a campaign
that is unknown or not currently accessible to the caller (see
`dnd_ai.commands.user_preferences`); 422 for a malformed body.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy import Connection

from dnd_ai.commands.user_preferences import (
    record_last_visited_campaign,
    set_campaign_startup_preference,
)

from .auth import require_human_user_id
from .deps import get_connection

router = APIRouter(tags=["user_preferences"])


class CampaignStartupPreferenceRequest(BaseModel):
    """`preferred_campaign_id` is required but nullable: `null` clears the
    fixed choice ("Resume my last visited campaign")."""

    preferred_campaign_id: uuid.UUID | None


class LastVisitedCampaignRequest(BaseModel):
    campaign_id: uuid.UUID


@router.put("/auth/preferences/campaign-startup", status_code=204)
def set_campaign_startup_preference_endpoint(
    body: CampaignStartupPreferenceRequest,
    user_id: Annotated[uuid.UUID, Depends(require_human_user_id)],
    connection: Annotated[Connection, Depends(get_connection)],
) -> Response:
    set_campaign_startup_preference(
        connection, user_id=user_id, preferred_campaign_id=body.preferred_campaign_id
    )
    return Response(status_code=204)


@router.put("/auth/preferences/last-visited-campaign", status_code=204)
def record_last_visited_campaign_endpoint(
    body: LastVisitedCampaignRequest,
    user_id: Annotated[uuid.UUID, Depends(require_human_user_id)],
    connection: Annotated[Connection, Depends(get_connection)],
) -> Response:
    record_last_visited_campaign(connection, user_id=user_id, campaign_id=body.campaign_id)
    return Response(status_code=204)

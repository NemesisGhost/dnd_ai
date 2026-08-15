"""Query endpoint over `dnd_ai.queries.summary` — Phase 10 workstream 22,
the first slice of "deterministic, audience-filtered summary and detail
query services for current campaign/session state, active quests, recent
events, locations, characters, NPCs/factions, inventory, knowledge, and
the prior-session recap" (docs/PLAN.md Phase 10 deliverable list, §25 step
15). Exposes `dnd_ai.queries.summary.get_campaign_summary_view` over HTTP
as `GET /campaigns/{campaign_id}/summary`, on the same already-delivered
OIDC authentication, transaction management, and access resolution every
other query router uses.

Scope: current session, recent events, and the prior-session recap — see
`dnd_ai.queries.summary`'s own docstring for why active quests, locations,
characters, NPCs/factions, inventory, and knowledge are deliberately left
to their own already-built, already-audience-filtered endpoints
(`dnd_ai.api.quests`/`.characters`/`.knowledge`) rather than re-aggregated
here.

Authorization: requires only `campaign.view` (the same base gate every
other Phase 10 read endpoint uses). A caller additionally holding
`canon.edit` (a GM) also sees `draft` (not-yet-finalized) events; everyone
else sees only `recorded`/`corrected` ones — see `dnd_ai.queries.summary`'s
own docstring for why this is the one genuinely audience-split piece of
this read. This `canon.edit` check (`access.has_capability(
_DRAFT_EVENTS_CAPABILITY)`) is deliberately untargeted: it gates a *list*
of recent events, decided before the query runs and with no single
`event_id` to check against, so there is no `security.resource_grants`
target to consult here — a genuinely campaign-wide capability check,
unlike the resource-scoped `canon.edit` checks in
`dnd_ai.api.characters`/`.knowledge`/`.quests`/`.dungeon`/`.relationships`.
This route is a read: no idempotency key, no `audit.change_log` row, for
the same reasons every other Phase 10 read endpoint has neither.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import Connection

from dnd_ai.domain.access import AccessContext
from dnd_ai.queries.summary import get_campaign_summary_view

from .access import require_campaign_capability
from .deps import get_connection

router = APIRouter(tags=["summary"])

_SUMMARY_VIEW_CAPABILITY = "campaign.view"
_DRAFT_EVENTS_CAPABILITY = "canon.edit"


# ---------------------------------------------------------------------------
# Response contracts
# ---------------------------------------------------------------------------


class SessionSummaryResponse(BaseModel):
    session_id: uuid.UUID
    session_number: int
    title: str | None
    status_code: str
    started_at: datetime | None
    ended_at: datetime | None


class RecentEventResponse(BaseModel):
    event_id: uuid.UUID
    name: str
    summary: str | None
    event_type_code: str
    event_status_code: str
    world_time_id: uuid.UUID
    details: str | None


class CampaignSummaryResponse(BaseModel):
    current_session: SessionSummaryResponse | None
    previous_session_recap: str | None
    recent_events: list[RecentEventResponse]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/campaigns/{campaign_id}/summary",
    response_model=CampaignSummaryResponse,
    status_code=200,
)
def get_campaign_summary_endpoint(
    campaign_id: uuid.UUID,
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_SUMMARY_VIEW_CAPABILITY))
    ],
    connection: Annotated[Connection, Depends(get_connection)],
) -> CampaignSummaryResponse:
    view = get_campaign_summary_view(
        connection,
        campaign_id=campaign_id,
        include_draft_events=access.has_capability(_DRAFT_EVENTS_CAPABILITY),
    )

    return CampaignSummaryResponse(
        current_session=(
            None
            if view.current_session is None
            else SessionSummaryResponse(
                session_id=view.current_session.session_id,
                session_number=view.current_session.session_number,
                title=view.current_session.title,
                status_code=view.current_session.status_code,
                started_at=view.current_session.started_at,
                ended_at=view.current_session.ended_at,
            )
        ),
        previous_session_recap=view.previous_session_recap,
        recent_events=[
            RecentEventResponse(
                event_id=e.event_id,
                name=e.name,
                summary=e.summary,
                event_type_code=e.event_type_code,
                event_status_code=e.event_status_code,
                world_time_id=e.world_time_id,
                details=e.details,
            )
            for e in view.recent_events
        ],
    )

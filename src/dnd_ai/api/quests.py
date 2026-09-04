"""Quest-objective command and query endpoints.

Exposes `advance_objective` over HTTP, on the shared OIDC
authentication (`dnd_ai.api.auth`), transaction management
(`dnd_ai.api.deps`), and access resolution (`dnd_ai.api.access`,
`dnd_ai.domain.access`) `dnd_ai.api.encounters`/`.items` use.

The route runs on the request's own `get_connection` transaction and calls
the connection-taking `_advance_objective_impl` form of the command (never
the public engine-based wrapper, which would open a second, nested
transaction) — identical to every route in `dnd_ai.api.encounters`/`.items`.

Authorization: requires the `canon.edit` role capability in the target
campaign (`dnd_ai.api.access.require_campaign_capability`), the same
capability `dnd_ai.api.encounters`/`.items` use — quest-objective
advancement is treated as GM/adapter-level canon mutation for this first
cut, the same deliberate scoping those modules' own docstrings record.

Cross-campaign session/party integrity: the route passes the URL's own
(already-authorized) `campaign_id` and the request body's caller-supplied
`session_id`/`party_id` straight through to `_advance_objective_impl`,
which validates each against `campaign_id` before mutating anything —
`dnd_ai.commands._shared.validate_session_campaign` for `session_id`,
`dnd_ai.commands.quests._validate_campaign_party` for `party_id` — raising
`SessionNotInCampaignError`/`PartyNotInCampaignError` (both
`DomainAuthorizationError`s the existing generic handler maps to a fixed,
non-disclosing 404) for a nonexistent or foreign-campaign session/party.
See those functions' docstrings for why neither check can be caught by
`require_campaign_capability` alone, or by `campaign.campaign_parties`'
own world-agreement trigger, which a same-world/different-campaign party
passes cleanly.

Like `dnd_ai.api.items`, there is no encounter-style "does this resource
belong to my campaign" ownership check here: neither
`narrative.quest_objectives` nor `campaign.objective_state` carries a
`campaign_id` at all — they are scoped by `timeline_id`, taken from the
resolved `AccessContext` (the campaign's own pinned timeline), never from
the request body.

Idempotency: durable, PostgreSQL-backed, via `dnd_ai.api.idempotency` and
`security.idempotent_requests` (migration 082) — identical mechanism to
`dnd_ai.api.items`, see that module's docstring for the full concurrency
argument. Both new validation checks run inside `_advance_objective_impl`,
before any row is mutated, so a rejected call — with or without an
`Idempotency-Key` — leaves no `campaign.objective_state` row, no
`narrative.events`/`.event_effects` row, no `audit.change_log` row, and no
completed `security.idempotent_requests` reservation: an unhandled
exception rolls back the whole request transaction
(`dnd_ai.api.deps.get_connection`), including the idempotency key's own
reservation `INSERT`.

Auditing: every successful call inserts one `audit.change_log` row
(`dnd_ai.api.audit.record_change_log`) identifying the authenticated
`actor_user_id`, the request's correlation ID, the command name, and the
resulting `event_id` — on the same connection, so it commits atomically
with the command it describes. `entity_id` is the owning quest's
`quest_id` (`AdvanceObjectiveResult.quest_id`,
`dnd_ai.commands.quests._quest_objective_context`) — the `core.entities`
row this change concerns (`audit.change_log.entity_id`'s documented
contract, migration 007) — never `quest_objective_id`, which is a
`narrative.quest_objectives` row with no entity identity of its own.

Phase 10 workstream 14 added the read side over the same URL prefix:
`GET /campaigns/{campaign_id}/quests/{quest_id}`
(`dnd_ai.queries.quest.get_quest_view`), requiring only `campaign.view`
(the read-only counterpart to every command route's `canon.edit`, matching
`dnd_ai.api.dungeon`/`.characters`). Audience filtering — a caller holding
`canon.edit` for this exact `quest_id` (`access.has_capability(...,
quest_id=quest_id)` — never checked without a target, which would skip
any quest-scoped `security.resource_grants` deny and let a role-derived
GM bypass an explicit, targeted restriction) sees every objective
regardless of `visibility_policy` — and party-perspective authorization
(`dnd_ai.api.access.resolve_party_perspective`, optional
`character_id`/`party_id` query parameters) mirror `dnd_ai.api.dungeon`'s
exactly — see `dnd_ai.queries.quest`'s own docstring for how
`narrative.quest_objectives.visibility_policy` drives it. This route is a
read: no idempotency key, no `audit.change_log` row, for the same reasons
`dnd_ai.api.dungeon`'s read endpoint has neither.

Phase 13D backend-readiness workstream added `GET /campaigns/
{campaign_id}/quests` (`dnd_ai.queries.quest.list_campaign_quests`) — the
list the portal's Home dashboard ("active quests") and a Quests screen
need, since the detail route above requires already knowing a `quest_id`.
Same `campaign.view` gate and the same optional `character_id`/`party_id`
perspective parameters as the detail route; see `list_campaign_quests`'s
own docstring for why it needs no separate `include_hidden` handling.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import Connection

from dnd_ai.commands.quests import _advance_objective_impl
from dnd_ai.domain.access import AccessContext
from dnd_ai.queries.quest import get_quest_view, list_campaign_quests

from ._shared import timeline_world_id
from .access import require_campaign_capability, resolve_party_perspective
from .audit import record_change_log
from .correlation import get_request_correlation_id
from .deps import get_connection, get_idempotency_key
from .idempotency import IdempotentReplay, begin_idempotent_request, complete_idempotent_request

router = APIRouter(tags=["quests"])

# Quest objective advancement is a canon-affecting mutation (docs/
# architecture/DATABASE_MODEL.md §12.3) — see this module's docstring for
# why this route requires it rather than a narrower, character-scoped
# capability.
_QUEST_MANAGE_CAPABILITY = "canon.edit"

# The read-only counterpart to _QUEST_MANAGE_CAPABILITY — see this
# module's docstring.
_QUEST_VIEW_CAPABILITY = "campaign.view"

# audit.change_log.command_name / the idempotency store's fingerprinted
# command_name — one literal per route, never derived from request data.
_ADVANCE_OBJECTIVE_COMMAND_NAME = "advance_objective"

# audit.change_actions.code (revision 007 seed): each call updates an
# existing conceptual resource's objective state, whether or not a
# campaign.objective_state row already existed — "updated" fits a first
# transition too, the same way dnd_ai.api.items treats "insert vs. update
# the state row" as an implementation detail of one logical operation.
_UPDATED_CHANGE_ACTION = "updated"


# ---------------------------------------------------------------------------
# Request/response contracts
# ---------------------------------------------------------------------------


class AdvanceObjectiveRequest(BaseModel):
    world_time_id: uuid.UUID
    new_status_code: str
    party_id: uuid.UUID | None = None
    actor_entity_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    cause_interaction_id: uuid.UUID | None = None
    cause_event_id: uuid.UUID | None = None
    event_details: str | None = None


class AdvanceObjectiveResponse(BaseModel):
    objective_state_id: uuid.UUID
    event_id: uuid.UUID
    previous_status_code: str | None
    new_status_code: str


class QuestObjectiveResponse(BaseModel):
    quest_objective_id: uuid.UUID
    name: str
    description: str | None
    requirement_level: str
    completion_mode: str
    visibility_policy: str
    quantity_required: int | None
    status_code: str | None


class QuestStageResponse(BaseModel):
    quest_stage_id: uuid.UUID
    name: str
    description: str | None
    sequence_number: int
    stage_type: str
    objectives: list[QuestObjectiveResponse]


class QuestResponse(BaseModel):
    quest_id: uuid.UUID
    name: str
    status_code: str | None
    stages: list[QuestStageResponse]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post(
    "/campaigns/{campaign_id}/quests/objectives/{quest_objective_id}/advance",
    response_model=AdvanceObjectiveResponse,
    status_code=200,
)
def advance_objective_endpoint(
    campaign_id: uuid.UUID,
    quest_objective_id: uuid.UUID,
    body: AdvanceObjectiveRequest,
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_QUEST_MANAGE_CAPABILITY))
    ],
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> AdvanceObjectiveResponse:
    reservation_id: uuid.UUID | None = None
    if idempotency_key is not None:
        fingerprint_payload: dict[str, Any] = {
            "quest_objective_id": str(quest_objective_id),
            **body.model_dump(mode="json"),
        }
        outcome = begin_idempotent_request(
            connection,
            actor_user_id=access.user_id,
            campaign_id=campaign_id,
            idempotency_key=idempotency_key,
            command_name=_ADVANCE_OBJECTIVE_COMMAND_NAME,
            payload=fingerprint_payload,
            correlation_id=correlation_id,
        )
        if isinstance(outcome, IdempotentReplay):
            return AdvanceObjectiveResponse.model_validate(outcome.response_body)
        reservation_id = outcome.idempotent_request_id

    result = _advance_objective_impl(
        connection,
        quest_objective_id=quest_objective_id,
        timeline_id=access.timeline_id,
        world_time_id=body.world_time_id,
        new_status_code=body.new_status_code,
        party_id=body.party_id,
        actor_entity_id=body.actor_entity_id,
        campaign_id=campaign_id,
        session_id=body.session_id,
        cause_interaction_id=body.cause_interaction_id,
        cause_event_id=body.cause_event_id,
        event_details=body.event_details,
    )

    record_change_log(
        connection,
        change_action_code=_UPDATED_CHANGE_ACTION,
        schema_name="campaign",
        table_name="objective_state",
        record_id=result.objective_state_id,
        entity_id=result.quest_id,
        world_id=result.world_id,
        actor_user_id=access.user_id,
        correlation_id=correlation_id,
        command_name=_ADVANCE_OBJECTIVE_COMMAND_NAME,
        event_id=result.event_id,
    )

    response = AdvanceObjectiveResponse(
        objective_state_id=result.objective_state_id,
        event_id=result.event_id,
        previous_status_code=result.previous_status_code,
        new_status_code=result.new_status_code,
    )

    if reservation_id is not None:
        complete_idempotent_request(
            connection,
            idempotent_request_id=reservation_id,
            response_status_code=200,
            response_body=response.model_dump(mode="json"),
        )

    return response


@router.get(
    "/campaigns/{campaign_id}/quests/{quest_id}",
    response_model=QuestResponse,
    status_code=200,
)
def get_quest_endpoint(
    campaign_id: uuid.UUID,
    quest_id: uuid.UUID,
    access: Annotated[AccessContext, Depends(require_campaign_capability(_QUEST_VIEW_CAPABILITY))],
    connection: Annotated[Connection, Depends(get_connection)],
    character_id: uuid.UUID | None = None,
    party_id: uuid.UUID | None = None,
) -> QuestResponse:
    include_hidden = access.has_capability(_QUEST_MANAGE_CAPABILITY, quest_id=quest_id)
    authorized_party_id = (
        None
        if include_hidden
        else resolve_party_perspective(
            connection,
            access=access,
            campaign_id=campaign_id,
            character_id=character_id,
            party_id=party_id,
        )
    )

    view = get_quest_view(
        connection,
        quest_id=quest_id,
        timeline_id=access.timeline_id,
        expected_world_id=timeline_world_id(connection, access.timeline_id),
        party_id=authorized_party_id,
        include_hidden=include_hidden,
    )

    return QuestResponse(
        quest_id=view.quest_id,
        name=view.name,
        status_code=view.status_code,
        stages=[
            QuestStageResponse(
                quest_stage_id=stage.quest_stage_id,
                name=stage.name,
                description=stage.description,
                sequence_number=stage.sequence_number,
                stage_type=stage.stage_type,
                objectives=[
                    QuestObjectiveResponse(
                        quest_objective_id=o.quest_objective_id,
                        name=o.name,
                        description=o.description,
                        requirement_level=o.requirement_level,
                        completion_mode=o.completion_mode,
                        visibility_policy=o.visibility_policy,
                        quantity_required=o.quantity_required,
                        status_code=o.status_code,
                    )
                    for o in stage.objectives
                ],
            )
            for stage in view.stages
        ],
    )


class QuestListItemResponse(BaseModel):
    quest_id: uuid.UUID
    name: str
    status_code: str | None


@router.get(
    "/campaigns/{campaign_id}/quests",
    response_model=list[QuestListItemResponse],
    status_code=200,
)
def list_quests_endpoint(
    campaign_id: uuid.UUID,
    access: Annotated[AccessContext, Depends(require_campaign_capability(_QUEST_VIEW_CAPABILITY))],
    connection: Annotated[Connection, Depends(get_connection)],
    character_id: uuid.UUID | None = None,
    party_id: uuid.UUID | None = None,
) -> list[QuestListItemResponse]:
    # A caller holding baseline canon.edit (a GM) never needs a party
    # perspective for status — campaign-wide status applies uniformly, the
    # same "GM sees canonical truth, not one party's subjective view"
    # reasoning get_quest_endpoint's own include_hidden branch already
    # applies (there, to skip resolving a perspective at all rather than
    # requiring the caller to additionally hold character.view_knowledge
    # for some named character just to view a list). No per-quest
    # resource-grant target exists here (a list has no single quest_id to
    # check against), so this is the baseline check only, matching
    # dnd_ai.api.summary's own has_capability(_DRAFT_EVENTS_CAPABILITY)
    # (no target) precedent for a list endpoint's broader default.
    is_gm = access.has_capability(_QUEST_MANAGE_CAPABILITY)
    authorized_party_id = (
        None
        if is_gm
        else resolve_party_perspective(
            connection,
            access=access,
            campaign_id=campaign_id,
            character_id=character_id,
            party_id=party_id,
        )
    )

    items = list_campaign_quests(
        connection, timeline_id=access.timeline_id, party_id=authorized_party_id
    )

    return [
        QuestListItemResponse(quest_id=item.quest_id, name=item.name, status_code=item.status_code)
        for item in items
    ]

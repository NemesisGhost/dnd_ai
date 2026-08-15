"""Command endpoints over `dnd_ai.commands.relationships` — Phase 10
workstream 8, continuing "command endpoints over the existing
command/application services" (docs/PLAN.md Phase 10) into the
relationship/organization domain after workstream 5's encounter endpoints
(`dnd_ai.api.encounters`), workstream 6's item endpoints
(`dnd_ai.api.items`), and workstream 7's quest endpoint
(`dnd_ai.api.quests`). Exposes `evolve_relationship_reaction` and
`update_organization_status` (docs/PHASE8_VERIFICATION.md) over HTTP, on
the same already-delivered OIDC authentication (`dnd_ai.api.auth`),
transaction management (`dnd_ai.api.deps`), and access resolution
(`dnd_ai.api.access`, `dnd_ai.domain.access`) every other command router
uses.

Both routes run on the request's own `get_connection` transaction and call
the connection-taking `_..._impl` form of their command (never the public
engine-based wrapper, which would open a second, nested transaction) —
identical to every route in `dnd_ai.api.encounters`/`.items`/`.quests`.

Authorization: both routes require the `canon.edit` role capability in the
target campaign (`dnd_ai.api.access.require_campaign_capability`), the same
capability every other command router uses. Relationship reaction/
organization status changes are treated as GM/adapter-level canon
mutations for this first cut, the same deliberate scoping every other
command router's own docstring records.

Cross-campaign session integrity: both routes pass the URL's own (already-
authorized) `campaign_id` and the request body's caller-supplied
`session_id` straight through to their respective `_..._impl` function,
which validates the two agree
(`dnd_ai.commands._shared.validate_session_campaign`) before mutating
anything, raising `SessionNotInCampaignError` — a `SafeMessageError` the
existing generic handler maps to a fixed, non-disclosing 404 — for a
nonexistent or foreign-campaign session.

Like `dnd_ai.api.items`/`.quests`, there is no encounter-style "does this
resource belong to my campaign" ownership check here: neither
`world.relationships`/`campaign.relationship_state` nor
`world.organizations`/`campaign.organization_state` carries a `campaign_id`
at all — they are scoped by `timeline_id`, always taken from the resolved
`AccessContext` (the campaign's own pinned timeline), never from the
request body.

Auditing: `entity_id` differs deliberately between the two routes.
`world.organizations` rows are `core.entities` rows (class-table
inheritance, CLAUDE.md rule 4 — `organization_id` *is* the entity_id), so
`update_organization_status_endpoint` records `entity_id=organization_id`
directly. `world.relationships` rows are not `core.entities` rows at all —
a relationship connects entities but has no entity identity of its own,
the same reason `dnd_ai.commands.quests`' workstream 7 correction pass
resolved `quest_objective_id` (also not an entity) to its *owning* quest's
`entity_id` instead. A relationship has no single owning entity to resolve
to (it may connect two or more participants of equal standing), so
`evolve_relationship_reaction_endpoint` records `entity_id=None` — matching
`audit.change_log.entity_id`'s own documented contract, "the core.entities
row this change concerns, *when there is one*" (migration 007).

Idempotency: durable, PostgreSQL-backed, via `dnd_ai.api.idempotency` and
`security.idempotent_requests` (migration 082) — identical mechanism to
every other command router; see `dnd_ai.api.items`'s module docstring for
the full concurrency argument.

Phase 10 workstream 15 added the read side over the same URL prefix:
`GET /campaigns/{campaign_id}/relationships/{relationship_id}`
(`dnd_ai.queries.relationship.get_relationship_view`), requiring only
`campaign.view` (the read-only counterpart to every command route's
`canon.edit`, matching `dnd_ai.api.dungeon`/`.characters`/`.quests`'s own
read endpoints). Participants and the shared, objective
`campaign.relationship_state` row are always returned to any authorized
caller; each participant's own *subjective* state row (affinity, trust,
private interpretation, ...) is returned only to a caller holding
`canon.edit` — see `dnd_ai.queries.relationship`'s own docstring for why
this first cut is conservative rather than guessing a per-holder
character-relationship rule. This route is a read: no idempotency key, no
`audit.change_log` row, for the same reasons `dnd_ai.api.dungeon`'s read
endpoint has neither.

Phase 10 workstream 19 added the organization read side, a sibling to
workstream 15's relationship read over the other half of this module's
own command domain: `GET /campaigns/{campaign_id}/organizations/
{organization_id}` (`dnd_ai.queries.organization.get_organization_view`),
also requiring only `campaign.view`. Unlike the relationship read, the
audience split here follows the schema's own column names directly:
`world.organizations.internal_description` is returned only to a caller
holding `canon.edit`, `None` otherwise — see `dnd_ai.queries.
organization`'s own docstring. Also a read: no idempotency key, no
`audit.change_log` row.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import Connection

from dnd_ai.commands.relationships import (
    _evolve_relationship_reaction_impl,
    _update_organization_status_impl,
)
from dnd_ai.domain.access import AccessContext
from dnd_ai.queries.organization import get_organization_view
from dnd_ai.queries.relationship import get_relationship_view

from ._shared import timeline_world_id
from .access import require_campaign_capability
from .audit import record_change_log
from .correlation import get_request_correlation_id
from .deps import get_connection, get_idempotency_key
from .idempotency import IdempotentReplay, begin_idempotent_request, complete_idempotent_request

router = APIRouter(tags=["relationships"])

# Relationship reaction/organization status changes are canon-affecting
# mutations (docs/architecture/DATABASE_MODEL.md §12.3) — see this module's
# docstring for why every route here requires it rather than a narrower,
# character-scoped capability.
_RELATIONSHIP_MANAGE_CAPABILITY = "canon.edit"

# The read-only counterpart to _RELATIONSHIP_MANAGE_CAPABILITY — see this
# module's docstring. Also the capability that additionally unlocks
# subjective relationship-state rows for the GET route below.
_RELATIONSHIP_VIEW_CAPABILITY = "campaign.view"

# audit.change_log.command_name / the idempotency store's fingerprinted
# command_name — one literal per route, never derived from request data.
_EVOLVE_REACTION_COMMAND_NAME = "evolve_relationship_reaction"
_UPDATE_ORGANIZATION_STATUS_COMMAND_NAME = "update_organization_status"

# audit.change_actions.code (revision 007 seed): each call updates an
# existing conceptual resource's relationship/organization state, whether
# or not a campaign.relationship_state/.organization_state row already
# existed — "updated" fits a first transition too, the same way every
# other command router in this codebase treats "insert vs. update the
# state row" as an implementation detail of one logical operation.
_UPDATED_CHANGE_ACTION = "updated"


# ---------------------------------------------------------------------------
# Request/response contracts
# ---------------------------------------------------------------------------


class EvolveRelationshipReactionRequest(BaseModel):
    world_time_id: uuid.UUID
    new_status_code: str
    perspective_holder_entity_id: uuid.UUID | None = None
    affinity: int | None = None
    trust: int | None = None
    respect: int | None = None
    fear: int | None = None
    obligation: int | None = None
    emotional_tone: str | None = None
    private_interpretation: str | None = None
    actor_entity_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    cause_interaction_id: uuid.UUID | None = None
    cause_event_id: uuid.UUID | None = None
    event_details: str | None = None


class EvolveRelationshipReactionResponse(BaseModel):
    relationship_state_id: uuid.UUID
    event_id: uuid.UUID
    previous_status_code: str | None
    new_status_code: str


class UpdateOrganizationStatusRequest(BaseModel):
    world_time_id: uuid.UUID
    new_status_code: str
    actor_entity_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    cause_interaction_id: uuid.UUID | None = None
    cause_event_id: uuid.UUID | None = None
    event_details: str | None = None


class UpdateOrganizationStatusResponse(BaseModel):
    organization_state_id: uuid.UUID
    event_id: uuid.UUID
    previous_status_code: str | None
    new_status_code: str


class RelationshipParticipantResponse(BaseModel):
    entity_id: uuid.UUID
    role_code: str


class RelationshipStateResponse(BaseModel):
    perspective_holder_entity_id: uuid.UUID | None
    status_code: str
    affinity: int | None
    trust: int | None
    respect: int | None
    fear: int | None
    obligation: int | None
    emotional_tone: str | None
    private_interpretation: str | None


class RelationshipResponse(BaseModel):
    relationship_id: uuid.UUID
    relationship_type_code: str
    description: str | None
    participants: list[RelationshipParticipantResponse]
    shared_state: RelationshipStateResponse | None
    # Empty for a caller who does not hold canon.edit — see this module's
    # docstring; never partially populated.
    subjective_states: list[RelationshipStateResponse]


class OrganizationResponse(BaseModel):
    organization_id: uuid.UUID
    organization_type_code: str
    parent_organization_id: uuid.UUID | None
    founded_world_time_id: uuid.UUID | None
    dissolved_world_time_id: uuid.UUID | None
    headquarters_location_id: uuid.UUID | None
    public_description: str | None
    # None for a caller who does not hold canon.edit — see this module's
    # docstring.
    internal_description: str | None
    status_code: str | None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post(
    "/campaigns/{campaign_id}/relationships/{relationship_id}/evolve",
    response_model=EvolveRelationshipReactionResponse,
    status_code=200,
)
def evolve_relationship_reaction_endpoint(
    campaign_id: uuid.UUID,
    relationship_id: uuid.UUID,
    body: EvolveRelationshipReactionRequest,
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_RELATIONSHIP_MANAGE_CAPABILITY))
    ],
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> EvolveRelationshipReactionResponse:
    reservation_id: uuid.UUID | None = None
    if idempotency_key is not None:
        fingerprint_payload: dict[str, Any] = {
            "relationship_id": str(relationship_id),
            **body.model_dump(mode="json"),
        }
        outcome = begin_idempotent_request(
            connection,
            actor_user_id=access.user_id,
            campaign_id=campaign_id,
            idempotency_key=idempotency_key,
            command_name=_EVOLVE_REACTION_COMMAND_NAME,
            payload=fingerprint_payload,
            correlation_id=correlation_id,
        )
        if isinstance(outcome, IdempotentReplay):
            return EvolveRelationshipReactionResponse.model_validate(outcome.response_body)
        reservation_id = outcome.idempotent_request_id

    result = _evolve_relationship_reaction_impl(
        connection,
        relationship_id=relationship_id,
        timeline_id=access.timeline_id,
        world_time_id=body.world_time_id,
        new_status_code=body.new_status_code,
        perspective_holder_entity_id=body.perspective_holder_entity_id,
        affinity=body.affinity,
        trust=body.trust,
        respect=body.respect,
        fear=body.fear,
        obligation=body.obligation,
        emotional_tone=body.emotional_tone,
        private_interpretation=body.private_interpretation,
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
        table_name="relationship_state",
        record_id=result.relationship_state_id,
        # world.relationships rows have no core.entities identity of their
        # own — see this module's docstring for why entity_id is None here,
        # unlike update_organization_status_endpoint below.
        entity_id=None,
        world_id=result.world_id,
        actor_user_id=access.user_id,
        correlation_id=correlation_id,
        command_name=_EVOLVE_REACTION_COMMAND_NAME,
        event_id=result.event_id,
    )

    response = EvolveRelationshipReactionResponse(
        relationship_state_id=result.relationship_state_id,
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
    "/campaigns/{campaign_id}/relationships/{relationship_id}",
    response_model=RelationshipResponse,
    status_code=200,
)
def get_relationship_endpoint(
    relationship_id: uuid.UUID,
    # campaign_id is not otherwise used in this body — require_campaign_
    # capability's own returned dependency callable declares campaign_id
    # itself and binds it from the URL path independently, the same way
    # dnd_ai.api.characters' identical read endpoint already does.
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_RELATIONSHIP_VIEW_CAPABILITY))
    ],
    connection: Annotated[Connection, Depends(get_connection)],
) -> RelationshipResponse:
    include_subjective = access.has_capability(_RELATIONSHIP_MANAGE_CAPABILITY)

    view = get_relationship_view(
        connection,
        relationship_id=relationship_id,
        timeline_id=access.timeline_id,
        expected_world_id=timeline_world_id(connection, access.timeline_id),
        include_subjective=include_subjective,
    )

    return RelationshipResponse(
        relationship_id=view.relationship_id,
        relationship_type_code=view.relationship_type_code,
        description=view.description,
        participants=[
            RelationshipParticipantResponse(entity_id=p.entity_id, role_code=p.role_code)
            for p in view.participants
        ],
        shared_state=(
            None
            if view.shared_state is None
            else RelationshipStateResponse(
                perspective_holder_entity_id=view.shared_state.perspective_holder_entity_id,
                status_code=view.shared_state.status_code,
                affinity=view.shared_state.affinity,
                trust=view.shared_state.trust,
                respect=view.shared_state.respect,
                fear=view.shared_state.fear,
                obligation=view.shared_state.obligation,
                emotional_tone=view.shared_state.emotional_tone,
                private_interpretation=view.shared_state.private_interpretation,
            )
        ),
        subjective_states=[
            RelationshipStateResponse(
                perspective_holder_entity_id=s.perspective_holder_entity_id,
                status_code=s.status_code,
                affinity=s.affinity,
                trust=s.trust,
                respect=s.respect,
                fear=s.fear,
                obligation=s.obligation,
                emotional_tone=s.emotional_tone,
                private_interpretation=s.private_interpretation,
            )
            for s in view.subjective_states
        ],
    )


@router.post(
    "/campaigns/{campaign_id}/organizations/{organization_id}/status",
    response_model=UpdateOrganizationStatusResponse,
    status_code=200,
)
def update_organization_status_endpoint(
    campaign_id: uuid.UUID,
    organization_id: uuid.UUID,
    body: UpdateOrganizationStatusRequest,
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_RELATIONSHIP_MANAGE_CAPABILITY))
    ],
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> UpdateOrganizationStatusResponse:
    reservation_id: uuid.UUID | None = None
    if idempotency_key is not None:
        fingerprint_payload: dict[str, Any] = {
            "organization_id": str(organization_id),
            **body.model_dump(mode="json"),
        }
        outcome = begin_idempotent_request(
            connection,
            actor_user_id=access.user_id,
            campaign_id=campaign_id,
            idempotency_key=idempotency_key,
            command_name=_UPDATE_ORGANIZATION_STATUS_COMMAND_NAME,
            payload=fingerprint_payload,
            correlation_id=correlation_id,
        )
        if isinstance(outcome, IdempotentReplay):
            return UpdateOrganizationStatusResponse.model_validate(outcome.response_body)
        reservation_id = outcome.idempotent_request_id

    result = _update_organization_status_impl(
        connection,
        organization_id=organization_id,
        timeline_id=access.timeline_id,
        world_time_id=body.world_time_id,
        new_status_code=body.new_status_code,
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
        table_name="organization_state",
        record_id=result.organization_state_id,
        # world.organizations rows are core.entities rows (class-table
        # inheritance) — organization_id is the entity_id directly.
        entity_id=organization_id,
        world_id=result.world_id,
        actor_user_id=access.user_id,
        correlation_id=correlation_id,
        command_name=_UPDATE_ORGANIZATION_STATUS_COMMAND_NAME,
        event_id=result.event_id,
    )

    response = UpdateOrganizationStatusResponse(
        organization_state_id=result.organization_state_id,
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
    "/campaigns/{campaign_id}/organizations/{organization_id}",
    response_model=OrganizationResponse,
    status_code=200,
)
def get_organization_endpoint(
    organization_id: uuid.UUID,
    # campaign_id is not otherwise used in this body — require_campaign_
    # capability's own returned dependency callable declares campaign_id
    # itself and binds it from the URL path independently, the same way
    # dnd_ai.api.characters' identical read endpoint already does.
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_RELATIONSHIP_VIEW_CAPABILITY))
    ],
    connection: Annotated[Connection, Depends(get_connection)],
) -> OrganizationResponse:
    include_internal_description = access.has_capability(_RELATIONSHIP_MANAGE_CAPABILITY)

    view = get_organization_view(
        connection,
        organization_id=organization_id,
        timeline_id=access.timeline_id,
        expected_world_id=timeline_world_id(connection, access.timeline_id),
        include_internal_description=include_internal_description,
    )

    return OrganizationResponse(
        organization_id=view.organization_id,
        organization_type_code=view.organization_type_code,
        parent_organization_id=view.parent_organization_id,
        founded_world_time_id=view.founded_world_time_id,
        dissolved_world_time_id=view.dissolved_world_time_id,
        headquarters_location_id=view.headquarters_location_id,
        public_description=view.public_description,
        internal_description=view.internal_description,
        status_code=view.status_code,
    )

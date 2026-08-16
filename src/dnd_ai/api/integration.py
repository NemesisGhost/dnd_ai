"""World-scoped external-system and identifier-mapping endpoints.

Exposes
`register_external_system` and `map_external_identifier` over HTTP, on the
same already-delivered OIDC authentication (`dnd_ai.api.auth`), transaction
management (`dnd_ai.api.deps`), and access resolution (`dnd_ai.api.access`,
`dnd_ai.domain.access`) every other command router uses.

`apply_foundry_combat_sync` deliberately has no endpoint here — see
`dnd_ai.commands.integration`'s own module docstring ("HTTP exposure")
for why: it has no authoritative campaign_id to authorize against until
Phase 11 maps Foundry users to platform users, and its three-transaction,
advisory-lock design is deliberately incompatible with the one-
transaction-per-request model this module's two routes (and every other
command router) rely on for atomic auditing.

Both routes run on the request's own `get_connection` transaction and call
the connection-taking `_..._impl` form of their command (never the public
engine-based wrapper, which would open a second, nested transaction) —
identical to every route in `dnd_ai.api.encounters`/`.items`/`.quests`/
`.relationships`/`.events`/`.interactions`.

Authorization: both routes require the `canon.edit` role capability in the
target campaign (`dnd_ai.api.access.require_campaign_capability`), the same
first-cut GM/adapter-level scoping every other command router uses.
Neither `integration.external_systems` nor `.external_identifiers` carries
a `campaign_id` — both are world-scoped (`dnd_ai.commands.integration`'s
own module docstring) — so, exactly like `dnd_ai.api.items`/`.quests`/
`.relationships`, the campaign named in the URL exists purely to authorize
the request; `world_id` is always resolved server-side from the campaign's
own pinned timeline (`dnd_ai.api._shared.timeline_world_id`), never
accepted from the request body.

Cross-world integrity: `map_external_identifier_endpoint` passes the URL's
own (already-authorized) campaign's resolved `world_id` as
`_map_external_identifier_impl`'s `expected_world_id` argument, which
asserts the path's `external_system_id` actually belongs to that world
before writing anything (`dnd_ai.commands.integration.
_external_system_world`), raising `ExternalSystemNotFoundError` (a fixed,
non-disclosing 404) otherwise. Without this, a caller authorized only for
one campaign/world could target an `external_system_id` belonging to a
different world entirely: `integration.enforce_external_identifier_world()`
(revision 079) only guarantees `external_system_id` and the mapped
`entity_id` agree with *each other*, never with the caller's own
authorized world.

Idempotency: `register_external_system` has no natural dedup key of its
own — each call always inserts a new row, so a naive retry (a dropped
response, a proxy timeout) would create a duplicate `external_systems` row
— so `register_external_system_endpoint` wires the same durable,
PostgreSQL-backed `Idempotency-Key` mechanism
(`dnd_ai.api.idempotency`/`security.idempotent_requests`, migration 082)
every other command router uses; see `dnd_ai.api.items`'s module docstring
for the full concurrency argument. `map_external_identifier` needs no such
wiring: it already upserts on `ux_external_identifiers_system_kind_external`
(its own docstring — "re-registering the same external object is
idempotent"), the same reasoning `dnd_ai.api.encounters` used to skip a
bespoke idempotency store for its own naturally-deduplicated routes.

Auditing: `integration.external_systems` rows are not `core.entities` rows
(no class-table inheritance — this is adapter-facing infrastructure, not a
world entity), so `register_external_system_endpoint` records
`entity_id=None`. `integration.external_identifiers` rows are also not
entities themselves, but the `entity_id` they map to *is* a real
`core.entities` row the change genuinely concerns, so
`map_external_identifier_endpoint` records `entity_id=body.entity_id`
directly — unlike the owning-entity indirection
`dnd_ai.commands.quests`'/`.interactions`' own workstreams needed, this one
requires no extra lookup since the caller already supplies the entity
being mapped.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import Connection

from dnd_ai.commands.integration import (
    _map_external_identifier_impl,
    _register_external_system_impl,
)
from dnd_ai.domain.access import AccessContext

from ._shared import timeline_world_id
from .access import require_campaign_capability
from .audit import record_change_log
from .correlation import get_request_correlation_id
from .deps import get_connection, get_idempotency_key
from .idempotency import IdempotentReplay, begin_idempotent_request, complete_idempotent_request

router = APIRouter(tags=["integration"])

# Registering an external system or mapping an entity to it is treated as a
# GM/adapter-level administrative action for this first cut — see this
# module's docstring for why every route here requires it rather than a
# narrower capability.
_INTEGRATION_MANAGE_CAPABILITY = "canon.edit"

# audit.change_log.command_name / the idempotency store's fingerprinted
# command_name — one literal per route, never derived from request data.
_REGISTER_EXTERNAL_SYSTEM_COMMAND_NAME = "register_external_system"
_MAP_EXTERNAL_IDENTIFIER_COMMAND_NAME = "map_external_identifier"

# audit.change_actions.code (revision 007 seed): register_external_system
# always creates a brand-new row; map_external_identifier upserts an
# existing mapping in place just as often as it creates one, the same
# "insert vs. update is an implementation detail of one logical operation"
# reasoning dnd_ai.api.items already applies to its own upserts.
_CREATED_CHANGE_ACTION = "created"
_UPDATED_CHANGE_ACTION = "updated"


# ---------------------------------------------------------------------------
# Request/response contracts
# ---------------------------------------------------------------------------


class RegisterExternalSystemRequest(BaseModel):
    system_type: str
    display_name: str
    external_reference: str | None = None


class RegisterExternalSystemResponse(BaseModel):
    external_system_id: uuid.UUID


class MapExternalIdentifierRequest(BaseModel):
    entity_id: uuid.UUID
    external_kind: str
    external_id: str


class MapExternalIdentifierResponse(BaseModel):
    external_identifier_id: uuid.UUID


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post(
    "/campaigns/{campaign_id}/integration/external-systems",
    response_model=RegisterExternalSystemResponse,
    status_code=201,
)
def register_external_system_endpoint(
    campaign_id: uuid.UUID,
    body: RegisterExternalSystemRequest,
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_INTEGRATION_MANAGE_CAPABILITY))
    ],
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> RegisterExternalSystemResponse:
    reservation_id: uuid.UUID | None = None
    if idempotency_key is not None:
        fingerprint_payload: dict[str, Any] = body.model_dump(mode="json")
        outcome = begin_idempotent_request(
            connection,
            actor_user_id=access.user_id,
            campaign_id=campaign_id,
            idempotency_key=idempotency_key,
            command_name=_REGISTER_EXTERNAL_SYSTEM_COMMAND_NAME,
            payload=fingerprint_payload,
            correlation_id=correlation_id,
        )
        if isinstance(outcome, IdempotentReplay):
            return RegisterExternalSystemResponse.model_validate(outcome.response_body)
        reservation_id = outcome.idempotent_request_id

    world_id = timeline_world_id(connection, access.timeline_id)

    result = _register_external_system_impl(
        connection,
        world_id=world_id,
        system_type=body.system_type,
        display_name=body.display_name,
        external_reference=body.external_reference,
    )

    record_change_log(
        connection,
        change_action_code=_CREATED_CHANGE_ACTION,
        schema_name="integration",
        table_name="external_systems",
        record_id=result.external_system_id,
        # integration.external_systems rows have no core.entities identity
        # of their own — adapter-facing infrastructure, not a world entity.
        entity_id=None,
        world_id=world_id,
        actor_user_id=access.user_id,
        correlation_id=correlation_id,
        command_name=_REGISTER_EXTERNAL_SYSTEM_COMMAND_NAME,
        event_id=None,
    )

    response = RegisterExternalSystemResponse(external_system_id=result.external_system_id)

    if reservation_id is not None:
        complete_idempotent_request(
            connection,
            idempotent_request_id=reservation_id,
            response_status_code=201,
            response_body=response.model_dump(mode="json"),
        )

    return response


@router.post(
    "/campaigns/{campaign_id}/integration/external-systems/{external_system_id}/identifiers",
    response_model=MapExternalIdentifierResponse,
    status_code=200,
)
def map_external_identifier_endpoint(
    # campaign_id is required in the signature to bind the URL's own path
    # parameter (require_campaign_capability's own dependency already
    # consumes it for authorization); unlike every other route, this one has
    # no idempotency scope or command argument of its own to also pass it to.
    campaign_id: uuid.UUID,  # noqa: ARG001
    external_system_id: uuid.UUID,
    body: MapExternalIdentifierRequest,
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_INTEGRATION_MANAGE_CAPABILITY))
    ],
    connection: Annotated[Connection, Depends(get_connection)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> MapExternalIdentifierResponse:
    world_id = timeline_world_id(connection, access.timeline_id)

    result = _map_external_identifier_impl(
        connection,
        external_system_id=external_system_id,
        entity_id=body.entity_id,
        external_kind=body.external_kind,
        external_id=body.external_id,
        expected_world_id=world_id,
    )

    record_change_log(
        connection,
        change_action_code=_UPDATED_CHANGE_ACTION,
        schema_name="integration",
        table_name="external_identifiers",
        record_id=result.external_identifier_id,
        # The entity_id the mapping concerns is a real core.entities row —
        # unlike register_external_system_endpoint above, this needs no
        # owning-entity indirection since the caller supplies it directly.
        entity_id=body.entity_id,
        world_id=result.world_id,
        actor_user_id=access.user_id,
        correlation_id=correlation_id,
        command_name=_MAP_EXTERNAL_IDENTIFIER_COMMAND_NAME,
        event_id=None,
    )

    return MapExternalIdentifierResponse(external_identifier_id=result.external_identifier_id)

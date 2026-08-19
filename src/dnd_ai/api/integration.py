"""World-scoped external-system, identifier-mapping, Foundry-identity,
Foundry combat-sync (Phase 11 workstream 3), and sync-state (Phase 11
workstream 4) endpoints.

Exposes
`register_external_system`, `map_external_identifier`, (Phase 11
workstream 1) `link_foundry_identity`, (Phase 11 workstream 2)
`issue_foundry_system_key`, (Phase 11 workstream 3)
`apply_foundry_combat_sync`, and (Phase 11 workstream 4)
`dnd_ai.queries.integration.get_sync_state_view`, over HTTP, on the same
already-delivered OIDC authentication (`dnd_ai.api.auth`), transaction
management (`dnd_ai.api.deps`), and access resolution
(`dnd_ai.api.access`, `dnd_ai.domain.access`) every other command router
uses.

The first four routes (all writes) and `sync_state_endpoint` (a read) run
on the request's own `get_connection` transaction and call the
connection-taking `_..._impl` form of their command, or a plain query
function for the read, on that same connection — never the public
engine-based command wrapper, which would open a second, nested
transaction — identical to every route in `dnd_ai.api.encounters`/
`.items`/`.quests`/`.relationships`/`.events`/`.interactions`.
`apply_foundry_combat_sync_endpoint` is the one deliberate exception — see
its own section below and `dnd_ai.commands.integration`'s own module
docstring ("HTTP exposure") for why.

Authorization: `register_external_system_endpoint` and
`map_external_identifier_endpoint` require the `canon.edit` role
capability in the target campaign (`dnd_ai.api.access.
require_campaign_capability`), the same first-cut GM/adapter-level scoping
every other command router uses. `link_foundry_identity_endpoint` and
`issue_foundry_system_key_endpoint` instead require `access.manage` —
deliberately narrower in kind, not degree: both mint or reassign
identity/credential material (who a Foundry user *is*; what a Foundry
system can authenticate *as*), the same "who can act" class of decision
`dnd_ai.commands.memberships`/`.campaign_invitations` already gate on
`access.manage` for, distinct from `canon.edit`'s "what is canonically
true" scope the other two routes here administer. None of
`integration.external_systems`/`.external_identifiers`/
`security.external_identities` carries a `campaign_id` — the first two are
world-scoped (`dnd_ai.commands.integration`'s own module docstring) and the
third is not scoped to a campaign or world at all — so, exactly like
`dnd_ai.api.items`/`.quests`/`.relationships`, the campaign named in the
URL exists purely to authorize the request; `world_id` is always resolved
server-side from the campaign's own pinned timeline
(`dnd_ai.api._shared.timeline_world_id`), never accepted from the request
body.

Cross-world integrity: `map_external_identifier_endpoint`,
`link_foundry_identity_endpoint`, and `issue_foundry_system_key_endpoint`
all pass the URL's own (already-authorized) campaign's resolved `world_id`
as their command's `expected_world_id` argument, which asserts the path's
`external_system_id` actually belongs to that world before writing
anything (`dnd_ai.commands.integration._external_system_world`), raising
`ExternalSystemNotFoundError` (a fixed, non-disclosing 404) otherwise.
Without this, a caller authorized only for one campaign/world could target
an `external_system_id` belonging to a different world entirely:
`integration.enforce_external_identifier_world()` (revision 079) only
guarantees `external_system_id` and the mapped `entity_id` agree with
*each other*, never with the caller's own authorized world — and neither
`security.external_identities` nor `integration.external_systems.
system_key_hash` carries any world scoping of its own beyond
`external_systems.world_id` itself, so `link_foundry_identity_endpoint`/
`issue_foundry_system_key_endpoint` rely entirely on this same
`external_system_id` check to keep one campaign's GM from linking
identities or minting credentials under a different world's Foundry
registration.

Idempotency: `register_external_system` has no natural dedup key of its
own — each call always inserts a new row, so a naive retry (a dropped
response, a proxy timeout) would create a duplicate `external_systems` row
— so `register_external_system_endpoint` wires the same durable,
PostgreSQL-backed `Idempotency-Key` mechanism
(`dnd_ai.api.idempotency`/`security.idempotent_requests`, migration 082)
every other command router uses; see `dnd_ai.api.items`'s module docstring
for the full concurrency argument. `issue_foundry_system_key_endpoint`
wires the identical mechanism for the same reason, in the opposite
direction from `register_external_system`'s "would create a duplicate
row": every call mints a genuinely new random key and overwrites
`system_key_hash` in place, so a naive retry after a dropped response
would silently rotate the credential a second time and return a
*different* raw key than the one the (never-received) first response
actually issued — `Idempotency-Key` makes a retry replay the exact same
response, including the same raw key, instead. `map_external_identifier`
and `link_foundry_identity` need no such wiring: both already upsert — on
`ux_external_identifiers_system_kind_external` and on `security.
external_identities`' own `(issuer, subject) WHERE revoked_at IS NULL`
partial unique index respectively (each command's own docstring —
"re-registering ... is idempotent") — the same reasoning
`dnd_ai.api.encounters` used to skip a bespoke idempotency store for its
own naturally-deduplicated routes.

Auditing: `integration.external_systems` rows are not `core.entities` rows
(no class-table inheritance — this is adapter-facing infrastructure, not a
world entity), so `register_external_system_endpoint` and
`issue_foundry_system_key_endpoint` (which updates a column on that same
row) both record `entity_id=None`. `integration.external_identifiers` rows
are also not entities themselves, but the `entity_id` they map to *is* a
real `core.entities` row the change genuinely concerns, so
`map_external_identifier_endpoint` records `entity_id=body.entity_id`
directly — unlike the owning-entity indirection
`dnd_ai.commands.quests`'/`.interactions`' own workstreams needed, this one
requires no extra lookup since the caller already supplies the entity
being mapped. `security.external_identities` rows are not `core.entities`
rows either, and the `user_id` they map to is a `security.users` row, not
one — so `link_foundry_identity_endpoint` also records `entity_id=None`,
the same as `register_external_system_endpoint`.

`apply_foundry_combat_sync_endpoint` (Phase 11 workstream 3): unlike the
four routes above, this one takes `Depends(get_engine)`, not
`Depends(get_connection)` — see `dnd_ai.commands.integration`'s own module
docstring for why `apply_foundry_combat_sync`'s three-transaction,
advisory-lock design cannot run inside a caller-supplied connection/
transaction the way every other command here does. `require_campaign_
capability` (used for authorization only) still injects its own
`Depends(get_connection)` internally, so a request to this route holds
two separate pooled connections briefly rather than one — an idle
authorization-check connection alongside `apply_foundry_combat_sync`'s own
`lock_connection` — never two connections contending with each other, so
this introduces no new deadlock risk beyond what `dnd_ai.commands.
integration`'s own docstring already analyzes for `lock_connection` alone.
Authorized via `canon.edit`, matching `dnd_ai.api.encounters.
resolve_combat_turn_endpoint` exactly (see `dnd_ai.commands.integration`'s
own docstring, "Foundry combat-sync endpoint", for the full reasoning).
No `Idempotency-Key` wiring: `apply_foundry_combat_sync` already provides
exactly-once semantics via the request's own `external_operation_id`
(`dnd_ai.commands.integration`'s own module docstring) — the same
reasoning `map_external_identifier`/`link_foundry_identity` already use to
skip it above. No `record_change_log` call either — see `dnd_ai.commands.
integration`'s own docstring for why a combat turn's durable record is
`narrative.events`/`interaction.combat_actions`/`integration.sync_jobs`,
not `audit.change_log`, mirroring `resolve_combat_turn_endpoint`'s
identical omission.

`sync_state_endpoint` (Phase 11 workstream 4, "restore synchronized state
after reopening or reconnecting"): `GET /campaigns/{campaign_id}/
integration/external-systems/{external_system_id}/sync-state`, taking
exactly one of `target_entity_id`/`target_encounter_id` as a query
parameter (`dnd_ai.queries.integration.get_sync_state_view`'s own
`InvalidSyncStateTargetError`, mapped to a 400 by the existing generic
`ValueError` handler, rejects both or neither). Authorized on
`campaign.view` — the read-only counterpart to this module's write
capabilities, matching `dnd_ai.api.encounters._ENCOUNTER_VIEW_CAPABILITY`
exactly, since a sync-status check is no more sensitive than reading the
encounter/character state it summarizes.

Ownership check, before the query even runs: `target_entity_id` must
belong to a `core.entities` row whose `world_id` matches the campaign's
own resolved world (`timeline_world_id`); `target_encounter_id` must
belong to a `narrative.encounters` row whose `campaign_id` matches the
URL's own campaign directly. Either failure, and a target genuinely never
synced (`get_sync_state_view` returning `None`), all raise the identical
`NotFoundError` — a caller authorized only for one campaign must never be
able to distinguish "this target belongs to someone else" from "it was
never synced," the same non-disclosure reasoning every cross-campaign/
cross-world check in this module already applies (see, e.g., `map_
external_identifier_endpoint`'s own "Cross-world integrity" section
above).
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import Connection, Engine, text

from dnd_ai.commands.integration import (
    ApplyFoundryCombatSyncResult,
    _issue_foundry_system_key_impl,
    _link_foundry_identity_impl,
    _map_external_identifier_impl,
    _register_external_system_impl,
    apply_foundry_combat_sync,
)
from dnd_ai.domain.access import AccessContext
from dnd_ai.queries.integration import InvalidSyncStateTargetError, get_sync_state_view

from ._shared import timeline_world_id
from .access import require_campaign_capability
from .audit import record_change_log
from .correlation import get_request_correlation_id
from .deps import get_connection, get_engine, get_idempotency_key
from .errors import NotFoundError
from .idempotency import IdempotentReplay, begin_idempotent_request, complete_idempotent_request

router = APIRouter(tags=["integration"])

# Registering an external system, mapping an entity to it, or resolving a
# Foundry combat turn are all treated as GM/adapter-level administrative
# actions for this first cut — see this module's docstring for why every
# route here requires it rather than a narrower capability, and
# `dnd_ai.commands.integration`'s own docstring ("Foundry combat-sync
# endpoint") for why the combat-sync route specifically mirrors
# `dnd_ai.api.encounters._ENCOUNTER_MANAGE_CAPABILITY` rather than
# inventing a distinct value that happens to be identical.
_INTEGRATION_MANAGE_CAPABILITY = "canon.edit"

# Linking a Foundry user id to a platform user, or minting the system-level
# credential a Foundry adapter authenticates with, are both identity/access
# decisions, not canon-editing ones — see this module's docstring
# ("Authorization") for why these deliberately differ from
# _INTEGRATION_MANAGE_CAPABILITY above.
_FOUNDRY_IDENTITY_MANAGE_CAPABILITY = "access.manage"

# The read-only counterpart to _INTEGRATION_MANAGE_CAPABILITY, for
# sync_state_endpoint — see this module's docstring ("sync_state_endpoint")
# for why this mirrors dnd_ai.api.encounters._ENCOUNTER_VIEW_CAPABILITY.
_INTEGRATION_VIEW_CAPABILITY = "campaign.view"

# audit.change_log.command_name / the idempotency store's fingerprinted
# command_name — one literal per route, never derived from request data.
_REGISTER_EXTERNAL_SYSTEM_COMMAND_NAME = "register_external_system"
_MAP_EXTERNAL_IDENTIFIER_COMMAND_NAME = "map_external_identifier"
_LINK_FOUNDRY_IDENTITY_COMMAND_NAME = "link_foundry_identity"
_ISSUE_FOUNDRY_SYSTEM_KEY_COMMAND_NAME = "issue_foundry_system_key"

# audit.change_actions.code (revision 007 seed): register_external_system
# always creates a brand-new row; map_external_identifier and
# link_foundry_identity each upsert an existing mapping in place just as
# often as they create one, the same "insert vs. update is an
# implementation detail of one logical operation" reasoning
# dnd_ai.api.items already applies to its own upserts.
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


class LinkFoundryIdentityRequest(BaseModel):
    # Bounded to match security.external_identities.subject's own
    # CHECK (char_length(subject) BETWEEN 1 AND 255) — validated here so a
    # violation surfaces as a clean 422, not a raw IntegrityError.
    foundry_user_id: str = Field(min_length=1, max_length=255)
    user_id: uuid.UUID


class LinkFoundryIdentityResponse(BaseModel):
    external_identity_id: uuid.UUID


class IssueFoundrySystemKeyResponse(BaseModel):
    external_system_id: uuid.UUID
    # Returned exactly once — see this module's docstring ("Idempotency")
    # for why a dropped-response retry still returns this same value
    # rather than a newly rotated one. Never persisted anywhere in plain
    # text by this codebase outside security.idempotent_requests.
    # response_body, the same durable-replay store
    # dnd_ai.api.campaign_invitations already accepts storing its own raw
    # invitation token in.
    raw_key: str


class ApplyFoundryCombatSyncRequest(BaseModel):
    # Bounded to match integration.sync_jobs.external_operation_id's own
    # role as a caller-supplied idempotency key — the same character-set/
    # length discipline dnd_ai.api.deps.get_idempotency_key already applies
    # to the generic Idempotency-Key header, even though this one arrives
    # in the request body rather than a header.
    external_system_id: uuid.UUID
    external_operation_id: str = Field(min_length=1, max_length=255)
    encounter_id: uuid.UUID
    round_number: int = Field(ge=1)
    turn_order: int = Field(ge=0)
    actor_entity_id: uuid.UUID
    world_time_id: uuid.UUID
    action_kind: str = "attack"
    target_entity_id: uuid.UUID | None = None
    item_instance_id: uuid.UUID | None = None
    spell_id: uuid.UUID | None = None
    hit: bool | None = None
    damage_amount: int | None = Field(default=None, ge=0)
    damage_type_id: uuid.UUID | None = None
    resulting_condition_id: uuid.UUID | None = None
    interaction_type_code: str = "attack"
    session_id: uuid.UUID | None = None
    event_details: str | None = None
    raw_payload: dict[str, Any] | None = None


class ApplyFoundryCombatSyncResponse(BaseModel):
    sync_job_id: uuid.UUID
    encounter_turn_id: uuid.UUID
    combat_action_id: uuid.UUID
    event_id: uuid.UUID | None
    previous_hit_points: int | None
    new_hit_points: int | None
    replayed: bool

    @classmethod
    def from_result(cls, result: ApplyFoundryCombatSyncResult) -> "ApplyFoundryCombatSyncResponse":
        return cls(
            sync_job_id=result.sync_job_id,
            encounter_turn_id=result.combat_result.encounter_turn_id,
            combat_action_id=result.combat_result.combat_action_id,
            event_id=result.combat_result.event_id,
            previous_hit_points=result.combat_result.previous_hit_points,
            new_hit_points=result.combat_result.new_hit_points,
            replayed=result.replayed,
        )


class SyncStateResponse(BaseModel):
    sync_state_id: uuid.UUID
    external_system_id: uuid.UUID
    target_entity_id: uuid.UUID | None
    target_encounter_id: uuid.UUID | None
    sync_status: str
    last_synced_at: datetime | None
    last_sync_job_id: uuid.UUID | None
    last_sync_job_status: str | None
    last_sync_job_error_message: str | None


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


@router.post(
    "/campaigns/{campaign_id}/integration/external-systems/{external_system_id}/foundry-identities",
    response_model=LinkFoundryIdentityResponse,
    status_code=200,
)
def link_foundry_identity_endpoint(
    # campaign_id is required in the signature to bind the URL's own path
    # parameter (require_campaign_capability's own dependency already
    # consumes it for authorization) — same reasoning as
    # map_external_identifier_endpoint above.
    campaign_id: uuid.UUID,  # noqa: ARG001
    external_system_id: uuid.UUID,
    body: LinkFoundryIdentityRequest,
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_FOUNDRY_IDENTITY_MANAGE_CAPABILITY))
    ],
    connection: Annotated[Connection, Depends(get_connection)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> LinkFoundryIdentityResponse:
    world_id = timeline_world_id(connection, access.timeline_id)

    result = _link_foundry_identity_impl(
        connection,
        external_system_id=external_system_id,
        foundry_user_id=body.foundry_user_id,
        user_id=body.user_id,
        expected_world_id=world_id,
    )

    record_change_log(
        connection,
        change_action_code=_UPDATED_CHANGE_ACTION,
        schema_name="security",
        table_name="external_identities",
        record_id=result.external_identity_id,
        # security.external_identities rows have no core.entities identity
        # of their own — the same reasoning register_external_system_endpoint
        # applies to integration.external_systems above.
        entity_id=None,
        world_id=result.world_id,
        actor_user_id=access.user_id,
        correlation_id=correlation_id,
        command_name=_LINK_FOUNDRY_IDENTITY_COMMAND_NAME,
        event_id=None,
    )

    return LinkFoundryIdentityResponse(external_identity_id=result.external_identity_id)


@router.post(
    "/campaigns/{campaign_id}/integration/external-systems/{external_system_id}/foundry-system-key",
    response_model=IssueFoundrySystemKeyResponse,
    status_code=201,
)
def issue_foundry_system_key_endpoint(
    campaign_id: uuid.UUID,
    external_system_id: uuid.UUID,
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_FOUNDRY_IDENTITY_MANAGE_CAPABILITY))
    ],
    connection: Annotated[Connection, Depends(get_connection)],
    idempotency_key: Annotated[str | None, Depends(get_idempotency_key)],
    correlation_id: Annotated[str | None, Depends(get_request_correlation_id)],
) -> IssueFoundrySystemKeyResponse:
    reservation_id: uuid.UUID | None = None
    if idempotency_key is not None:
        # No request body of its own — external_system_id (the URL path
        # parameter) is the only input, so it is the fingerprint payload,
        # the same "include every path parameter that isn't already part
        # of the reservation's own scope" shape
        # dnd_ai.api.interactions.resolve_check_endpoint uses for
        # check_request_id. security.idempotent_requests' own uniqueness
        # scope is (actor_user_id, campaign_id, idempotency_key) — it does
        # NOT include external_system_id — so an empty payload here would
        # let the same Idempotency-Key reused against a *different*
        # external_system_id in the same campaign incorrectly replay the
        # first call's response instead of being rejected as a fingerprint
        # mismatch.
        fingerprint_payload: dict[str, Any] = {"external_system_id": str(external_system_id)}
        outcome = begin_idempotent_request(
            connection,
            actor_user_id=access.user_id,
            campaign_id=campaign_id,
            idempotency_key=idempotency_key,
            command_name=_ISSUE_FOUNDRY_SYSTEM_KEY_COMMAND_NAME,
            payload=fingerprint_payload,
            correlation_id=correlation_id,
        )
        if isinstance(outcome, IdempotentReplay):
            return IssueFoundrySystemKeyResponse.model_validate(outcome.response_body)
        reservation_id = outcome.idempotent_request_id

    world_id = timeline_world_id(connection, access.timeline_id)

    result = _issue_foundry_system_key_impl(
        connection, external_system_id=external_system_id, expected_world_id=world_id
    )

    record_change_log(
        connection,
        change_action_code=_UPDATED_CHANGE_ACTION,
        schema_name="integration",
        table_name="external_systems",
        record_id=result.external_system_id,
        # integration.external_systems rows have no core.entities identity
        # of their own — the same reasoning register_external_system_endpoint
        # applies.
        entity_id=None,
        world_id=result.world_id,
        actor_user_id=access.user_id,
        correlation_id=correlation_id,
        command_name=_ISSUE_FOUNDRY_SYSTEM_KEY_COMMAND_NAME,
        event_id=None,
    )

    response = IssueFoundrySystemKeyResponse(
        external_system_id=result.external_system_id, raw_key=result.raw_key
    )

    if reservation_id is not None:
        complete_idempotent_request(
            connection,
            idempotent_request_id=reservation_id,
            response_status_code=201,
            response_body=response.model_dump(mode="json"),
        )

    return response


@router.post(
    "/campaigns/{campaign_id}/integration/foundry/combat-sync",
    response_model=ApplyFoundryCombatSyncResponse,
    status_code=201,
)
def apply_foundry_combat_sync_endpoint(
    campaign_id: uuid.UUID,
    body: ApplyFoundryCombatSyncRequest,
    # Authorization only — this route does not otherwise use the resolved
    # AccessContext, and deliberately does not depend on get_connection for
    # its own work. See this module's docstring
    # ("apply_foundry_combat_sync_endpoint") for why.
    _access: Annotated[
        AccessContext, Depends(require_campaign_capability(_INTEGRATION_MANAGE_CAPABILITY))
    ],
    engine: Annotated[Engine, Depends(get_engine)],
) -> ApplyFoundryCombatSyncResponse:
    result = apply_foundry_combat_sync(
        engine,
        external_system_id=body.external_system_id,
        external_operation_id=body.external_operation_id,
        encounter_id=body.encounter_id,
        round_number=body.round_number,
        turn_order=body.turn_order,
        actor_entity_id=body.actor_entity_id,
        world_time_id=body.world_time_id,
        action_kind=body.action_kind,
        target_entity_id=body.target_entity_id,
        item_instance_id=body.item_instance_id,
        spell_id=body.spell_id,
        hit=body.hit,
        damage_amount=body.damage_amount,
        damage_type_id=body.damage_type_id,
        resulting_condition_id=body.resulting_condition_id,
        interaction_type_code=body.interaction_type_code,
        session_id=body.session_id,
        event_details=body.event_details,
        raw_payload=body.raw_payload,
        campaign_id=campaign_id,
    )
    return ApplyFoundryCombatSyncResponse.from_result(result)


def _assert_sync_state_target_owned_by_campaign(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    world_id: uuid.UUID,
    target_entity_id: uuid.UUID | None,
    target_encounter_id: uuid.UUID | None,
) -> None:
    """Raises `NotFoundError` unless the named target actually belongs to
    the caller's own already-authorized campaign/world — see this module's
    docstring ("sync_state_endpoint") for why this runs before the
    sync-state query itself, and why it raises the identical error a
    genuinely-never-synced target would also produce.

    Validates the same "exactly one of target_entity_id/
    target_encounter_id" invariant `get_sync_state_view` itself enforces
    (raising the identical `InvalidSyncStateTargetError`) before touching
    either branch below — without this, a caller supplying both would
    silently have `target_encounter_id` ignored (only the entity branch
    runs), and a caller supplying neither would hit an `AssertionError`
    (a 500) instead of the clean 400 this mirrors."""
    if (target_entity_id is None) == (target_encounter_id is None):
        raise InvalidSyncStateTargetError(
            "exactly one of target_entity_id/target_encounter_id must be supplied "
            f"(entity={target_entity_id!r}, encounter={target_encounter_id!r})"
        )

    if target_entity_id is not None:
        owned = connection.execute(
            text("SELECT 1 FROM core.entities WHERE entity_id = :entity AND world_id = :world"),
            {"entity": target_entity_id, "world": world_id},
        ).scalar()
    else:
        owned = connection.execute(
            text(
                "SELECT 1 FROM narrative.encounters "
                "WHERE encounter_id = :encounter AND campaign_id = :campaign"
            ),
            {"encounter": target_encounter_id, "campaign": campaign_id},
        ).scalar()
    if owned is None:
        raise NotFoundError()


@router.get(
    "/campaigns/{campaign_id}/integration/external-systems/{external_system_id}/sync-state",
    response_model=SyncStateResponse,
    status_code=200,
)
def sync_state_endpoint(
    campaign_id: uuid.UUID,
    external_system_id: uuid.UUID,
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_INTEGRATION_VIEW_CAPABILITY))
    ],
    connection: Annotated[Connection, Depends(get_connection)],
    target_entity_id: uuid.UUID | None = None,
    target_encounter_id: uuid.UUID | None = None,
) -> SyncStateResponse:
    world_id = timeline_world_id(connection, access.timeline_id)
    _assert_sync_state_target_owned_by_campaign(
        connection,
        campaign_id=campaign_id,
        world_id=world_id,
        target_entity_id=target_entity_id,
        target_encounter_id=target_encounter_id,
    )

    view = get_sync_state_view(
        connection,
        external_system_id=external_system_id,
        target_entity_id=target_entity_id,
        target_encounter_id=target_encounter_id,
    )
    if view is None:
        raise NotFoundError()

    return SyncStateResponse(
        sync_state_id=view.sync_state_id,
        external_system_id=view.external_system_id,
        target_entity_id=view.target_entity_id,
        target_encounter_id=view.target_encounter_id,
        sync_status=view.sync_status,
        last_synced_at=view.last_synced_at,
        last_sync_job_id=view.last_sync_job_id,
        last_sync_job_status=view.last_sync_job_status,
        last_sync_job_error_message=view.last_sync_job_error_message,
    )

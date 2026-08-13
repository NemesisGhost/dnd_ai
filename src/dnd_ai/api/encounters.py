"""Command endpoints over `dnd_ai.commands.encounters` — the first slice of
Phase 10's "command endpoints over the existing command/application
services" deliverable (docs/PLAN.md Phase 10). Exposes `start_encounter`,
`resolve_combat_turn`, and `end_encounter` (docs/PHASE9_VERIFICATION.md)
over HTTP, on top of the already-delivered OIDC authentication
(`dnd_ai.api.auth`), transaction management (`dnd_ai.api.deps`), and access
resolution (`dnd_ai.api.access`, `dnd_ai.domain.access`).

Every route runs on the request's own `get_connection` transaction and calls
the connection-taking `_..._impl` form of its command (never the public
engine-based wrapper, which would open a second, nested transaction) — this
is the "API layer, not the command, now owns [the transaction] boundary"
`dnd_ai.api.deps.get_connection` documents.

Authorization: all three routes require the `canon.edit` role capability in
the target campaign (`dnd_ai.api.access.require_campaign_capability`).
Encounter management is treated as a GM/adapter-level action for this first
cut, deliberately narrower than the full character-relationship-derived
access `resolve_combat_turn` could in principle support (a player submitting
their own character's turn) — extending that is future scope once a caller
actually needs it, not invented speculatively here.

Idempotency: `narrative.encounter_turns` carries
`ux_encounter_turns_round_participant UNIQUE (encounter_round_id,
participant_id)` (revision 078), so a naive client retry of the same
round/participant turn is rejected as a 409 conflict by the existing
`IntegrityError` handler rather than silently applying damage twice — no
bespoke idempotency-key store is needed for this endpoint yet, consistent
with `dnd_ai.api.deps.get_idempotency_key`'s own "most commands already
derive their own idempotency from domain state" scoping note.

Lifecycle: `_lock_encounter()` (shared by `_resolve_combat_turn_impl` and
`_end_encounter_impl`) requires the locked encounter to be `'active'`,
raising `dnd_ai.commands.encounters.EncounterNotActiveError` — a
`SafeMessageError` the existing generic handler maps to a fixed,
non-disclosing 409 — otherwise. This also covers a repeated or genuinely
concurrent `end` request: the second caller only proceeds past the shared
`FOR UPDATE` lock once the first has committed, observes the already-
`'completed'` status, and is rejected before touching any other row, so
at most one completion event/`resulting_event_id` is ever recorded per
encounter. `end`'s outcomes list is validated the same way, before any
mutation: every `participant_entity_id` must already be a participant in
the encounter, and duplicates are rejected — both raise a plain
`ValueError`, mapped by the existing generic handler to a fixed, non-
disclosing 400, exactly like every other unclassified domain validation
failure in this codebase.

Cross-campaign session integrity: `start_encounter_endpoint` passes the
URL's own (already-authorized) `campaign_id` and the request body's
caller-supplied `session_id` straight through to `_start_encounter_impl`,
which validates the two agree (`dnd_ai.commands.encounters.
_validate_session_campaign`) before inserting anything, raising
`SessionNotInCampaignError` — a `SafeMessageError` the existing generic
handler maps to a fixed, non-disclosing 404 — for a nonexistent or
foreign-campaign session. See that function's docstring for why this
can't be caught by `require_campaign_capability` alone: `campaign_id` is
trusted (from the URL, already authorized), but `session_id` is ordinary
caller-supplied request data with no authorization check of its own.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import Connection, text

from dnd_ai.commands.encounters import (
    _end_encounter_impl,
    _resolve_combat_turn_impl,
    _start_encounter_impl,
)
from dnd_ai.domain.access import AccessContext

from .access import require_campaign_capability
from .deps import get_connection
from .errors import NotFoundError

router = APIRouter(tags=["encounters"])

# Encounter management is a canon-affecting mutation (docs/architecture/
# DATABASE_MODEL.md §12.3) — see this module's docstring for why every
# route here requires it rather than a narrower, character-scoped
# capability.
_ENCOUNTER_MANAGE_CAPABILITY = "canon.edit"


# ---------------------------------------------------------------------------
# Request/response contracts
# ---------------------------------------------------------------------------


class StartEncounterRequest(BaseModel):
    world_time_id: uuid.UUID
    participant_entity_ids: list[uuid.UUID] = Field(min_length=1)
    session_id: uuid.UUID | None = None
    location_id: uuid.UUID | None = None
    summary: str | None = None


class EncounterResponse(BaseModel):
    encounter_id: uuid.UUID


class ResolveCombatTurnRequest(BaseModel):
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


class ResolveCombatTurnResponse(BaseModel):
    encounter_turn_id: uuid.UUID
    combat_action_id: uuid.UUID
    event_id: uuid.UUID | None
    previous_hit_points: int | None
    new_hit_points: int | None


class EncounterOutcome(BaseModel):
    participant_entity_id: uuid.UUID
    outcome: str


class EndEncounterRequest(BaseModel):
    world_time_id: uuid.UUID
    outcomes: list[EncounterOutcome] = Field(default_factory=list)
    summary: str | None = None
    session_id: uuid.UUID | None = None


class EndEncounterResponse(BaseModel):
    event_id: uuid.UUID


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _verify_encounter_in_campaign(
    connection: Connection, *, encounter_id: uuid.UUID, campaign_id: uuid.UUID
) -> None:
    """Raises NotFoundError unless `encounter_id` both exists and belongs to
    `campaign_id` — a caller already authorized for one campaign must never
    be able to target an encounter that belongs to a different one (or to
    none) merely by guessing its ID."""
    row = connection.execute(
        text("SELECT campaign_id FROM narrative.encounters WHERE encounter_id = :e"),
        {"e": encounter_id},
    ).first()
    if row is None or row.campaign_id != campaign_id:
        raise NotFoundError()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post(
    "/campaigns/{campaign_id}/encounters",
    response_model=EncounterResponse,
    status_code=201,
)
def start_encounter_endpoint(
    campaign_id: uuid.UUID,
    body: StartEncounterRequest,
    access: Annotated[
        AccessContext, Depends(require_campaign_capability(_ENCOUNTER_MANAGE_CAPABILITY))
    ],
    connection: Annotated[Connection, Depends(get_connection)],
) -> EncounterResponse:
    result = _start_encounter_impl(
        connection,
        timeline_id=access.timeline_id,
        world_time_id=body.world_time_id,
        participant_entity_ids=tuple(body.participant_entity_ids),
        campaign_id=campaign_id,
        session_id=body.session_id,
        location_id=body.location_id,
        summary=body.summary,
    )
    return EncounterResponse(encounter_id=result.encounter_id)


@router.post(
    "/campaigns/{campaign_id}/encounters/{encounter_id}/turns",
    response_model=ResolveCombatTurnResponse,
    status_code=201,
)
def resolve_combat_turn_endpoint(
    campaign_id: uuid.UUID,
    encounter_id: uuid.UUID,
    body: ResolveCombatTurnRequest,
    # Enforces canon.edit; the resolved AccessContext itself isn't needed —
    # unlike start_encounter_endpoint, this route derives no value from it
    # (encounter_id, not the campaign's timeline, is what's already trusted).
    _access: Annotated[
        AccessContext, Depends(require_campaign_capability(_ENCOUNTER_MANAGE_CAPABILITY))
    ],
    connection: Annotated[Connection, Depends(get_connection)],
) -> ResolveCombatTurnResponse:
    _verify_encounter_in_campaign(connection, encounter_id=encounter_id, campaign_id=campaign_id)
    result = _resolve_combat_turn_impl(
        connection,
        encounter_id=encounter_id,
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
        campaign_id=campaign_id,
        session_id=body.session_id,
        event_details=body.event_details,
    )
    return ResolveCombatTurnResponse(
        encounter_turn_id=result.encounter_turn_id,
        combat_action_id=result.combat_action_id,
        event_id=result.event_id,
        previous_hit_points=result.previous_hit_points,
        new_hit_points=result.new_hit_points,
    )


@router.post(
    "/campaigns/{campaign_id}/encounters/{encounter_id}/end",
    response_model=EndEncounterResponse,
    status_code=200,
)
def end_encounter_endpoint(
    campaign_id: uuid.UUID,
    encounter_id: uuid.UUID,
    body: EndEncounterRequest,
    # See resolve_combat_turn_endpoint's identical parameter for why the
    # resolved AccessContext itself is unused here.
    _access: Annotated[
        AccessContext, Depends(require_campaign_capability(_ENCOUNTER_MANAGE_CAPABILITY))
    ],
    connection: Annotated[Connection, Depends(get_connection)],
) -> EndEncounterResponse:
    _verify_encounter_in_campaign(connection, encounter_id=encounter_id, campaign_id=campaign_id)
    result = _end_encounter_impl(
        connection,
        encounter_id=encounter_id,
        world_time_id=body.world_time_id,
        outcomes=tuple((o.participant_entity_id, o.outcome) for o in body.outcomes),
        summary=body.summary,
        campaign_id=campaign_id,
        session_id=body.session_id,
    )
    return EndEncounterResponse(event_id=result.event_id)

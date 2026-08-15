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

Cross-campaign encounter ownership: `turns` and `end` pass the URL's own
(already-authorized) `campaign_id` straight through to
`_resolve_combat_turn_impl`/`_end_encounter_impl`, which require it to
match the *locked* encounter's own `campaign_id`
(`dnd_ai.commands.encounters._lock_encounter`'s `expected_campaign_id`),
atomically with acquiring the encounter's `FOR UPDATE` lock — never via a
separate, earlier, unlocked "does this encounter belong to my campaign"
query. An earlier version of this module ran exactly that kind of
separate check (`_verify_encounter_in_campaign`, since removed) before
calling into the command layer at all; since `narrative.encounters.
campaign_id` is mutable, that left a TOCTOU window open — a concurrent
transaction could reparent the encounter to a different, same-timeline
campaign between the unlocked check and the command's own later lock, and
the caller (still only authorized for the *original* campaign) would then
mutate an encounter it no longer owned. `_lock_encounter` now checks
ownership against the row its own lock holds, which a concurrent
reparenting `UPDATE` must also wait behind — see that function's and
`EncounterNotFoundError`'s own docstrings for the full account. A
nonexistent encounter and a campaign mismatch both raise
`EncounterNotFoundError` — a `SafeMessageError` the existing generic
handler maps to a fixed, non-disclosing 404 — identically, so a caller
can never distinguish "doesn't exist" from "belongs to someone else."

Lifecycle: only once ownership passes does `_lock_encounter()` (shared by
`_resolve_combat_turn_impl` and `_end_encounter_impl`) also require the
locked encounter to be `'active'`, raising `dnd_ai.commands.encounters.
EncounterNotActiveError` — a `SafeMessageError` the existing generic
handler maps to a fixed, non-disclosing 409 — otherwise. This also covers
a repeated or genuinely concurrent `end` request: the second caller only
proceeds past the shared `FOR UPDATE` lock once the first has committed,
observes the already-`'completed'` status, and is rejected before
touching any other row, so at most one completion event/
`resulting_event_id` is ever recorded per encounter. `end`'s outcomes
list is validated the same way, after ownership and lifecycle but before
any mutation: every `participant_entity_id` must already be a participant
in the encounter, and duplicates are rejected — both raise a plain
`ValueError`, mapped by the existing generic handler to a fixed, non-
disclosing 400, exactly like every other unclassified domain validation
failure in this codebase.

Cross-campaign session integrity: all three routes pass the URL's own
(already-authorized) `campaign_id` and the request body's caller-supplied
`session_id` straight through to their respective `_..._impl` function,
each of which validates the two agree
(`dnd_ai.commands.encounters._validate_session_campaign`) before mutating
anything, raising `SessionNotInCampaignError` — a `SafeMessageError` the
existing generic handler maps to a fixed, non-disclosing 404 — for a
nonexistent or foreign-campaign session. See that function's docstring
for why this can't be caught by `require_campaign_capability` alone:
`campaign_id` is trusted (from the URL, already authorized), but
`session_id` is ordinary caller-supplied request data with no
authorization check of its own — true for `start`'s `session_id` (lands
on `narrative.encounters` itself), `turns`' `session_id` (lands on the
`interaction.interactions` row that turn creates), and `end`'s
`session_id` (lands on the completion `narrative.events` row) alike.

Phase 10 workstream 17 added the read side over the same URL prefix:
`GET /campaigns/{campaign_id}/encounters/{encounter_id}`
(`dnd_ai.queries.encounter.get_encounter_view`), requiring only
`campaign.view` (the read-only counterpart to every command route's
`canon.edit`). Unlike every other Phase 10 query, there is no audience
filtering here at all — see `dnd_ai.queries.encounter`'s own docstring for
why a resolved combat outcome carries no GM-only/undiscovered content the
way a dungeon secret or a hidden quest objective does. Ownership reuses
the same `campaign_id`-column check every command route above performs,
via the same `EncounterNotFoundError` (re-exported by `dnd_ai.queries.
encounter`, not duplicated). This route is a read: no idempotency key, no
`audit.change_log` row, for the same reasons `dnd_ai.api.dungeon`'s read
endpoint has neither.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import Connection

from dnd_ai.commands.encounters import (
    _end_encounter_impl,
    _resolve_combat_turn_impl,
    _start_encounter_impl,
)
from dnd_ai.domain.access import AccessContext
from dnd_ai.queries.encounter import get_encounter_view

from .access import require_campaign_capability
from .deps import get_connection

router = APIRouter(tags=["encounters"])

# Encounter management is a canon-affecting mutation (docs/architecture/
# DATABASE_MODEL.md §12.3) — see this module's docstring for why every
# route here requires it rather than a narrower, character-scoped
# capability.
_ENCOUNTER_MANAGE_CAPABILITY = "canon.edit"

# The read-only counterpart to _ENCOUNTER_MANAGE_CAPABILITY — see this
# module's docstring.
_ENCOUNTER_VIEW_CAPABILITY = "campaign.view"


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


class EncounterParticipantResponse(BaseModel):
    encounter_participant_id: uuid.UUID
    participant_entity_id: uuid.UUID
    side: str
    initiative: int | None
    outcome: str | None


class CombatActionResponse(BaseModel):
    action_kind: str
    item_instance_id: uuid.UUID | None
    spell_id: uuid.UUID | None
    hit: bool | None
    damage_amount: int | None
    damage_type_code: str | None
    resulting_condition_code: str | None


class EncounterTurnResponse(BaseModel):
    encounter_turn_id: uuid.UUID
    participant_id: uuid.UUID
    turn_order: int
    notes: str | None
    combat_action: CombatActionResponse | None


class EncounterRoundResponse(BaseModel):
    encounter_round_id: uuid.UUID
    round_number: int
    turns: list[EncounterTurnResponse]


class EncounterDetailResponse(BaseModel):
    encounter_id: uuid.UUID
    status: str
    current_round: int
    summary: str | None
    location_id: uuid.UUID | None
    world_time_id: uuid.UUID
    resulting_event_id: uuid.UUID | None
    participants: list[EncounterParticipantResponse]
    rounds: list[EncounterRoundResponse]


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


@router.get(
    "/campaigns/{campaign_id}/encounters/{encounter_id}",
    response_model=EncounterDetailResponse,
    status_code=200,
)
def get_encounter_endpoint(
    campaign_id: uuid.UUID,
    encounter_id: uuid.UUID,
    # Enforces campaign.view; the resolved AccessContext itself isn't
    # needed — this route applies no audience filtering (see this
    # module's docstring), so no further AccessContext field is used the
    # way other read endpoints use access.timeline_id/has_capability.
    _access: Annotated[
        AccessContext, Depends(require_campaign_capability(_ENCOUNTER_VIEW_CAPABILITY))
    ],
    connection: Annotated[Connection, Depends(get_connection)],
) -> EncounterDetailResponse:
    view = get_encounter_view(connection, encounter_id=encounter_id, campaign_id=campaign_id)

    return EncounterDetailResponse(
        encounter_id=view.encounter_id,
        status=view.status,
        current_round=view.current_round,
        summary=view.summary,
        location_id=view.location_id,
        world_time_id=view.world_time_id,
        resulting_event_id=view.resulting_event_id,
        participants=[
            EncounterParticipantResponse(
                encounter_participant_id=p.encounter_participant_id,
                participant_entity_id=p.participant_entity_id,
                side=p.side,
                initiative=p.initiative,
                outcome=p.outcome,
            )
            for p in view.participants
        ],
        rounds=[
            EncounterRoundResponse(
                encounter_round_id=r.encounter_round_id,
                round_number=r.round_number,
                turns=[
                    EncounterTurnResponse(
                        encounter_turn_id=t.encounter_turn_id,
                        participant_id=t.participant_id,
                        turn_order=t.turn_order,
                        notes=t.notes,
                        combat_action=(
                            None
                            if t.combat_action is None
                            else CombatActionResponse(
                                action_kind=t.combat_action.action_kind,
                                item_instance_id=t.combat_action.item_instance_id,
                                spell_id=t.combat_action.spell_id,
                                hit=t.combat_action.hit,
                                damage_amount=t.combat_action.damage_amount,
                                damage_type_code=t.combat_action.damage_type_code,
                                resulting_condition_code=t.combat_action.resulting_condition_code,
                            )
                        ),
                    )
                    for t in r.turns
                ],
            )
            for r in view.rounds
        ],
    )

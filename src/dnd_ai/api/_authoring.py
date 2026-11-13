"""Shared plumbing for the Phase 14 authoring routes.

Two small pieces every authoring router repeats:

- `ActorIdempotency` — the begin/replay/complete dance for the actor-scoped
  store (`security.actor_idempotent_requests`), used by `/worlds…` routes.
  Authorization has already run (route dependencies resolve first), so a
  caller who lost authority can never reach a stored response; a replay is
  answered *before* the command runs, so it also precedes any
  `expected_row_version` check (a retried success is not a false
  `stale_write`).
- `BaseAuthoringRequest` — Pydantic base forbidding unknown fields.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Connection

from dnd_ai.commands._content import register_authoring_requirements
from dnd_ai.domain.access import AccessContext
from dnd_ai.domain.authorization import AuthorizationPlan
from dnd_ai.domain.data_classification import replay_body

from ._shared import timeline_world_id
from .idempotency import (
    IdempotentReplay,
    begin_actor_idempotent_request,
    begin_idempotent_request,
    complete_actor_idempotent_request,
    complete_idempotent_request,
)


class BaseAuthoringRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def require_authoring_decisions(
    connection: Connection,
    plan: AuthorizationPlan,
    access: AccessContext,
    *,
    world_capability: str | None,
) -> None:
    """Register the route's definition-authoring decisions (campaign `canon.edit`, then
    `world_capability`) on the plan **before** the idempotency start (R01 plan 6.6, R-D4).

    A replay finalizes the plan before the command runs, so every decision the command would register
    must already be in it, or a caller who lost the world capability would be handed the stored receipt.
    `world_capability` is the one the route's command passes to `lock_authoring_scope`: `None` only for
    the campaign-originated records (player-character identity, item instances). The only statement is
    the unlocked world lookup; no row lock is taken. The command later registers the same requirements
    once (`register_authoring_requirements` skips what is present)."""
    register_authoring_requirements(
        connection,
        plan,
        actor_user_id=access.user_id,
        campaign_id=access.campaign_id,
        world_id=timeline_world_id(connection, access.timeline_id),
        world_capability=world_capability,
    )


def _judge_replay(connection: Connection, plan: AuthorizationPlan | None) -> None:
    """R-D4: judge the plan's requirements, then finalize it, before a stored receipt leaves."""
    if plan is not None:
        plan.finalize(connection)


@dataclass
class ActorIdempotency:
    reservation_id: uuid.UUID | None = None
    replay: JSONResponse | None = None


def start_actor_idempotency(
    connection: Connection,
    *,
    actor_user_id: uuid.UUID,
    idempotency_key: str | None,
    command_name: str,
    payload: dict[str, Any],
    correlation_id: str | None,
) -> ActorIdempotency:
    """No key means no deduplication (matching every other command route)."""
    if idempotency_key is None:
        return ActorIdempotency()
    outcome = begin_actor_idempotent_request(
        connection,
        actor_user_id=actor_user_id,
        idempotency_key=idempotency_key,
        command_name=command_name,
        payload=payload,
        correlation_id=correlation_id,
    )
    if isinstance(outcome, IdempotentReplay):
        return ActorIdempotency(
            replay=JSONResponse(
                status_code=outcome.response_status_code, content=outcome.response_body
            )
        )
    return ActorIdempotency(reservation_id=outcome.actor_idempotent_request_id)


def finish_actor_idempotency(
    connection: Connection,
    state: ActorIdempotency,
    *,
    status_code: int,
    body: dict[str, Any],
) -> None:
    if state.reservation_id is not None:
        complete_actor_idempotent_request(
            connection,
            actor_idempotent_request_id=state.reservation_id,
            response_status_code=status_code,
            response_body=body,
        )


@dataclass
class CampaignIdempotency:
    reservation_id: uuid.UUID | None = None
    replay: JSONResponse | None = None


def start_campaign_idempotency(
    connection: Connection,
    *,
    actor_user_id: uuid.UUID,
    campaign_id: uuid.UUID,
    idempotency_key: str | None,
    command_name: str,
    payload: dict[str, Any],
    correlation_id: str | None,
    plan: AuthorizationPlan | None = None,
) -> CampaignIdempotency:
    """The campaign-scoped twin of `start_actor_idempotency` (content authoring
    has a campaign). No key means no deduplication. The fingerprint covers the
    command name and the normalized payload (route target ids and
    `expected_row_version` included), so the same key with a different body is
    the existing idempotency conflict, never a silent replay.

    `plan` (R01 plan section 6.6, R-D4): a migrated route passes its `AuthorizationPlan`. A replay is
    answered after the key-lock wait, so the stored receipt is returned only after the plan's
    registered requirements hold in a fresh snapshot: a refusal raises the route's own error and
    returns nothing from the receipt, and the replay then finalizes the plan (a replay writes no row, so
    no statement follows). A route not yet migrated passes none and behaves as before."""
    if idempotency_key is None:
        return CampaignIdempotency()
    outcome = begin_idempotent_request(
        connection,
        actor_user_id=actor_user_id,
        campaign_id=campaign_id,
        idempotency_key=idempotency_key,
        command_name=command_name,
        payload=payload,
        correlation_id=correlation_id,
    )
    if isinstance(outcome, IdempotentReplay):
        _judge_replay(connection, plan)
        return CampaignIdempotency(
            replay=JSONResponse(
                status_code=outcome.response_status_code, content=outcome.response_body
            )
        )
    return CampaignIdempotency(reservation_id=outcome.idempotent_request_id)


def finish_campaign_idempotency(
    connection: Connection,
    state: CampaignIdempotency,
    *,
    status_code: int,
    body: dict[str, Any],
) -> None:
    """Store the response for replay. Only the minimal receipt part is stored (`replay_body`,
    checkpoint 15.2A-4), so a replay of any authoring write returns ids, flags and codes and
    never a name, summary or GM-only text; the client refetches the record."""
    if state.reservation_id is not None:
        complete_idempotent_request(
            connection,
            idempotent_request_id=state.reservation_id,
            response_status_code=status_code,
            response_body=replay_body(body),
        )

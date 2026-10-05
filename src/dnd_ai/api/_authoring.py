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

from .idempotency import (
    IdempotentReplay,
    begin_actor_idempotent_request,
    begin_idempotent_request,
    complete_actor_idempotent_request,
    complete_idempotent_request,
)


class BaseAuthoringRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


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
) -> CampaignIdempotency:
    """The campaign-scoped twin of `start_actor_idempotency` (content authoring
    has a campaign). No key means no deduplication. The fingerprint covers the
    command name and the normalized payload (route target ids and
    `expected_row_version` included), so the same key with a different body is
    the existing idempotency conflict, never a silent replay."""
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
    if state.reservation_id is not None:
        complete_idempotent_request(
            connection,
            idempotent_request_id=state.reservation_id,
            response_status_code=status_code,
            response_body=body,
        )

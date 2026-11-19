"""Party definition endpoints (Phase 15 checkpoint 15.2C-1, decision D-30).

    GET  /campaigns/{id}/parties                          (campaign.view)
    POST /campaigns/{id}/parties                          (canon.edit)
    GET  /campaigns/{id}/parties/{party_id}               (campaign.view)
    POST /campaigns/{id}/parties/{party_id}/update        (canon.edit)
    POST /campaigns/{id}/parties/{party_id}/archive       (canon.edit)
    POST /campaigns/{id}/parties/{party_id}/restore       (canon.edit)

    GET  /campaigns/{id}/parties/{party_id}/roster        (campaign.view)
    GET  /campaigns/{id}/parties/{party_id}/members       (canon.edit)
    POST /campaigns/{id}/parties/{party_id}/members       (canon.edit)
    POST /campaigns/{id}/parties/{party_id}/members/{membership_id}/end   (canon.edit)

A party is reachable only through a campaign it is attached to. Archived parties
are hidden from everyone except editors who ask for them (`include_archived`);
a non-editor gets the same 404 for an archived party as for a missing one. Writes
use the campaign idempotency store, re-check authority under lock, answer with an
id-only receipt, and write one audit row (name is structural, description redacted).
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import Connection, text

from dnd_ai.commands.parties import (
    PartyResult,
    archive_party,
    create_party,
    restore_party,
    update_party,
)
from dnd_ai.commands.party_members import (
    MembershipResult,
    add_party_member,
    end_party_membership,
)
from dnd_ai.domain.access import AccessContext
from dnd_ai.domain.authoring import DESCRIPTION_MAX_LENGTH, NAME_MAX_LENGTH, REASON_MAX_LENGTH
from dnd_ai.domain.authorization import AuthorizationPlan
from dnd_ai.domain.data_classification import content_receipt
from dnd_ai.queries.entity_lifecycle import lifecycle_hidden_entity_ids
from dnd_ai.queries.parties import PartyView, get_campaign_party, list_campaign_parties
from dnd_ai.queries.party_members import list_party_members
from dnd_ai.queries.party_membership_period import (
    CURRENT_PARTY_MEMBERSHIP_SQL,
    MembershipClock,
    membership_clock_params,
    resolve_membership_clock,
)
from dnd_ai.queries.world_explorer import discoverable_entity_ids

from ._authoring import (
    BaseAuthoringRequest,
    finish_campaign_idempotency,
    start_campaign_idempotency,
)
from ._content_support import clean_note
from ._shared import timeline_world_id
from .access import require_campaign_capability
from .audit import record_change_log
from .correlation import get_request_correlation_id
from .deps import get_connection, get_idempotency_key
from .errors import NotFoundError
from .r01_route_plans import get_authorization_plan
from .world_explorer import resolve_world_entity_visibility

router = APIRouter(tags=["parties"])

_Conn = Annotated[Connection, Depends(get_connection)]
_Plan = Annotated[AuthorizationPlan, Depends(get_authorization_plan)]
_Key = Annotated[str | None, Depends(get_idempotency_key)]
_Corr = Annotated[str | None, Depends(get_request_correlation_id)]
_View = Annotated[AccessContext, Depends(require_campaign_capability("campaign.view"))]
_Edit = Annotated[AccessContext, Depends(require_campaign_capability("canon.edit"))]

_BASE = "/campaigns/{campaign_id}/parties"


class PartyFields(BaseAuthoringRequest):
    name: str = Field(min_length=1, max_length=NAME_MAX_LENGTH)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)


class UpdatePartyRequest(PartyFields):
    expected_row_version: int = Field(ge=1)


class ArchivePartyRequest(BaseAuthoringRequest):
    expected_row_version: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=REASON_MAX_LENGTH)


class RestorePartyRequest(BaseAuthoringRequest):
    expected_row_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=REASON_MAX_LENGTH)


def _json(view: PartyView, *, editor: bool) -> dict[str, Any]:
    body: dict[str, Any] = {
        "party_id": str(view.party_id),
        "name": view.name,
        "description": view.description,
        "lifecycle_status": view.lifecycle_status,
        "row_version": view.row_version,
    }
    if editor:
        body["available_actions"] = (
            ["update", "archive"] if view.lifecycle_status == "active" else ["restore"]
        )
    return body


@router.get(_BASE)
def list_parties_endpoint(
    access: _View,
    connection: _Conn,
    include_archived: Annotated[bool, Query()] = False,
) -> dict[str, Any]:
    editor = access.has_capability("canon.edit")
    items = list_campaign_parties(
        connection,
        campaign_id=access.campaign_id,
        include_archived=include_archived and editor,
    )
    return {"can_create": editor, "items": [_json(i, editor=editor) for i in items]}


@router.get(_BASE + "/{party_id}")
def get_party_endpoint(party_id: uuid.UUID, access: _View, connection: _Conn) -> dict[str, Any]:
    editor = access.has_capability("canon.edit")
    view = get_campaign_party(
        connection, campaign_id=access.campaign_id, party_id=party_id, include_archived=editor
    )
    if view is None:
        raise NotFoundError()
    return _json(view, editor=editor)


# Relationship types that make a reader a current controller of a character (decision D4-C). No
# relationship type confers `character.control` today, so the type codes are the test; after P03-B a
# live, in-effect assignment qualifies instead and this set is retired with the legacy rows (ADR
# 0021 section 2.10).
_PARTY_CONTROLLER_RELATIONSHIP_TYPES = ("owner", "primary_controller", "co_controller")


def party_roster_controller_qualifies(
    connection: Connection,
    access: AccessContext,
    *,
    party_id: uuid.UUID,
    membership_clock: MembershipClock,
) -> bool:
    """Decision D4-C (P03-A A3b, plan section 10.13): whether the caller currently controls a
    character that is a current member of this party, in this campaign. Such a caller may see that
    one party's current members on the roster, by id and canonical name, and nothing more.

    All of these hold, per request: the party's membership is judged against the campaign's
    effective clock (no clock, nobody qualifies); the caller holds a live `owner`,
    `primary_controller` or `co_controller` relationship to the character, resolved on this
    campaign membership and timeline exactly as `resolve_access_context` resolves relationships
    (not revoked or expired, no closed fictional interval, type active, character active and
    canon); the character is a current member of this party on this timeline; and the character is
    not under a whole-character `campaign.view` deny for the caller, so a controller denied their
    own character does not qualify through it.

    This is a second, named audience for one response and is not discovery: its result is never
    written to, or read into, `AccessContext`, the discovery bundle or any other consumer, and it
    confers no capability. `get_party_roster_endpoint` is its only caller (a structural test pins
    that)."""
    if not membership_clock.is_set:
        return False
    controlled = connection.execute(
        text(f"""
            SELECT DISTINCT mcr.character_id
            FROM security.membership_character_relationships mcr
            JOIN security.character_relationship_types crt
              ON crt.character_relationship_type_id = mcr.character_relationship_type_id
            JOIN core.entities e ON e.entity_id = mcr.character_id
            JOIN core.lifecycle_statuses cls ON cls.lifecycle_status_id = e.lifecycle_status_id
            JOIN core.canon_statuses ccs ON ccs.canon_status_id = e.canon_status_id
            JOIN campaign.party_memberships pm
              ON pm.member_entity_id = mcr.character_id
             AND pm.timeline_id = :timeline_id
             AND pm.party_id = :party_id
            WHERE mcr.campaign_membership_id = :membership_id
              AND mcr.revoked_at IS NULL
              AND (mcr.expires_at IS NULL OR mcr.expires_at > now())
              AND mcr.effective_to_world_time_id IS NULL
              AND (mcr.timeline_id IS NULL OR mcr.timeline_id = :timeline_id)
              AND crt.is_active
              AND crt.code = ANY(CAST(:controller_types AS text[]))
              AND cls.code = 'active'
              AND ccs.code = 'canon'
              AND {CURRENT_PARTY_MEMBERSHIP_SQL}
        """),
        {
            "membership_id": access.campaign_membership_id,
            "timeline_id": access.timeline_id,
            "party_id": party_id,
            "controller_types": list(_PARTY_CONTROLLER_RELATIONSHIP_TYPES),
            **membership_clock_params(membership_clock),
        },
    ).scalars()
    return any(
        access.has_capability("campaign.view", entity_id=character_id)
        for character_id in controlled
    )


@router.get(_BASE + "/{party_id}/roster")
def get_party_roster_endpoint(
    party_id: uuid.UUID, access: _View, connection: _Conn
) -> dict[str, Any]:
    """Read-only roster for anyone with `campaign.view`: the party and who is a member now on the
    campaign's own timeline, by character id and name only. Join/leave reasons, history and times
    are management data and stay on the `canon.edit` members read. `member_count` counts only what
    is listed. Archived parties are the same 404 as a missing one for a non-editor.

    Who is listed (P03-A A3b, decisions D4-C and D12): a caller who currently controls a character
    that is a current member of this party sees every current member, because a party's own
    controllers know the people their character travels with; everyone else sees the current
    members shared discovery lets them see (a GM sees all of them). In both cases a member is left
    out when it is hidden from the caller as an unpublished definition, when the caller holds a
    whole-character `campaign.view` deny on it, or when the caller holds a `character.discover`
    deny on it. The controller exception is roster visibility only: no summary, profile, inventory,
    sheet or detail tier, no link, and no discovery anywhere else. Reading grants nothing."""
    editor = access.has_capability("canon.edit")
    party = get_campaign_party(
        connection, campaign_id=access.campaign_id, party_id=party_id, include_archived=editor
    )
    if party is None:
        raise NotFoundError()
    clock = resolve_membership_clock(connection, timeline_id=access.timeline_id)
    current = [
        m
        for m in list_party_members(
            connection, timeline_id=access.timeline_id, party_id=party_id, membership_clock=clock
        )
        if m.is_current
    ]
    world_id = timeline_world_id(connection, access.timeline_id)
    if party_roster_controller_qualifies(
        connection, access, party_id=party_id, membership_clock=clock
    ):
        hidden = lifecycle_hidden_entity_ids(
            connection,
            world_id=world_id,
            mode="reference",
            viewer_user_id=access.user_id,
            can_edit_canon=editor,
        )
        discover_denied, _ = access.resource_grant_targets("character.discover", "character_id")
        members = [
            m
            for m in current
            if m.character_id not in hidden
            and m.character_id not in discover_denied
            and access.has_capability("campaign.view", entity_id=m.character_id)
        ]
    else:
        visible = discoverable_entity_ids(
            connection,
            [m.character_id for m in current],
            world_id=world_id,
            timeline_id=access.timeline_id,
            visibility=resolve_world_entity_visibility(access, connection),
        )
        members = [m for m in current if m.character_id in visible]
    return {
        "party": _json(party, editor=editor),
        "member_count": len(members),
        "members": [
            {"character_id": str(m.character_id), "character_name": m.character_name}
            for m in members
        ],
        "as_of": clock.display,
        "clock_unset": not clock.is_set,
    }


def _run(
    *,
    command_name: str,
    access: AccessContext,
    connection: Connection,
    idempotency_key: str | None,
    correlation_id: str | None,
    payload: dict[str, Any],
    command: Any,
    status_code: int,
    reason: str | None = None,
    lifecycle_action: str | None = None,
    plan: AuthorizationPlan,
) -> Any:
    idem = start_campaign_idempotency(
        connection,
        actor_user_id=access.user_id,
        campaign_id=access.campaign_id,
        idempotency_key=idempotency_key,
        command_name=command_name,
        payload=payload,
        correlation_id=correlation_id,
        plan=plan,
    )
    if idem.replay is not None:
        return idem.replay
    result: PartyResult = command()
    if result.changed:
        record_change_log(
            connection,
            change_action_code=lifecycle_action or ("created" if result.created else "updated"),
            schema_name="campaign",
            table_name="parties",
            record_id=result.party_id,
            entity_id=None,
            world_id=result.world_id,
            actor_user_id=access.user_id,
            correlation_id=correlation_id,
            command_name=command_name,
            event_id=None,
            previous_status=result.previous_lifecycle_status if lifecycle_action else None,
            new_status=result.lifecycle_status if lifecycle_action else None,
            changed_fields=result.changed_fields or None,
            reason=clean_note(reason),
        )
    receipt = content_receipt(
        id_field="party_id",
        entity_id=result.party_id,
        row_version=result.row_version,
        created=result.created,
        changed=result.changed,
    )
    finish_campaign_idempotency(connection, idem, status_code=status_code, body=receipt)
    plan.finalize(connection)  # R01: the last statement
    return JSONResponse(status_code=status_code, content=receipt)


@router.post(_BASE, status_code=201)
def create_party_endpoint(
    body: PartyFields,
    access: _Edit,
    plan: _Plan,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _run(
        command_name="create_party",
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload=body.model_dump(mode="json"),
        status_code=201,
        command=lambda: create_party(
            connection,
            campaign_id=access.campaign_id,
            actor_user_id=access.user_id,
            name=body.name,
            description=body.description,
            plan=plan,
        ),
        plan=plan,
    )


@router.post(_BASE + "/{party_id}/update")
def update_party_endpoint(
    party_id: uuid.UUID,
    body: UpdatePartyRequest,
    access: _Edit,
    plan: _Plan,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _run(
        command_name="update_party",
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload={"party_id": str(party_id), **body.model_dump(mode="json")},
        status_code=200,
        command=lambda: update_party(
            connection,
            campaign_id=access.campaign_id,
            actor_user_id=access.user_id,
            party_id=party_id,
            expected_row_version=body.expected_row_version,
            name=body.name,
            description=body.description,
            plan=plan,
        ),
        plan=plan,
    )


@router.post(_BASE + "/{party_id}/archive")
def archive_party_endpoint(
    party_id: uuid.UUID,
    body: ArchivePartyRequest,
    access: _Edit,
    plan: _Plan,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _run(
        command_name="archive_party",
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload={"party_id": str(party_id), **body.model_dump(mode="json")},
        status_code=200,
        reason=body.reason,
        lifecycle_action="archived",
        command=lambda: archive_party(
            connection,
            campaign_id=access.campaign_id,
            actor_user_id=access.user_id,
            party_id=party_id,
            expected_row_version=body.expected_row_version,
            reason=body.reason,
            plan=plan,
        ),
        plan=plan,
    )


@router.post(_BASE + "/{party_id}/restore")
def restore_party_endpoint(
    party_id: uuid.UUID,
    body: RestorePartyRequest,
    access: _Edit,
    plan: _Plan,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _run(
        command_name="restore_party",
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload={"party_id": str(party_id), **body.model_dump(mode="json")},
        status_code=200,
        reason=body.reason,
        lifecycle_action="restored",
        command=lambda: restore_party(
            connection,
            campaign_id=access.campaign_id,
            actor_user_id=access.user_id,
            party_id=party_id,
            expected_row_version=body.expected_row_version,
            reason=body.reason,
            plan=plan,
        ),
        plan=plan,
    )


class AddMemberRequest(BaseAuthoringRequest):
    character_id: uuid.UUID
    effective_from_world_time_id: uuid.UUID
    expected_party_row_version: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=REASON_MAX_LENGTH)


class EndMembershipRequest(BaseAuthoringRequest):
    effective_to_world_time_id: uuid.UUID
    expected_party_row_version: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=REASON_MAX_LENGTH)


@router.get(_BASE + "/{party_id}/members")
def list_members_endpoint(party_id: uuid.UUID, access: _Edit, connection: _Conn) -> dict[str, Any]:
    party = get_campaign_party(
        connection, campaign_id=access.campaign_id, party_id=party_id, include_archived=True
    )
    if party is None:
        raise NotFoundError()
    clock = resolve_membership_clock(connection, timeline_id=access.timeline_id)
    members = list_party_members(
        connection, timeline_id=access.timeline_id, party_id=party_id, membership_clock=clock
    )
    return {
        "party": _json(party, editor=True),
        "as_of": clock.display,
        "clock_unset": not clock.is_set,
        "members": [
            {
                "party_membership_id": str(m.party_membership_id),
                "character_id": str(m.character_id),
                "character_name": m.character_name,
                "joined_at": m.joined_at,
                "left_at": m.left_at,
                "joined_reason": m.joined_reason,
                "left_reason": m.left_reason,
                "is_current": m.is_current,
                "period_status": m.period_status,
            }
            for m in members
        ],
    }


def _run_member(
    *,
    command_name: str,
    access: AccessContext,
    connection: Connection,
    idempotency_key: str | None,
    correlation_id: str | None,
    payload: dict[str, Any],
    command: Any,
    status_code: int,
    reason: str | None,
    plan: AuthorizationPlan,
) -> Any:
    idem = start_campaign_idempotency(
        connection,
        actor_user_id=access.user_id,
        campaign_id=access.campaign_id,
        idempotency_key=idempotency_key,
        command_name=command_name,
        payload=payload,
        correlation_id=correlation_id,
        plan=plan,
    )
    if idem.replay is not None:
        return idem.replay
    result: MembershipResult = command()
    record_change_log(
        connection,
        change_action_code="created" if result.created else "updated",
        schema_name="campaign",
        table_name="party_memberships",
        record_id=result.party_membership_id,
        entity_id=result.character_id,
        world_id=result.world_id,
        actor_user_id=access.user_id,
        correlation_id=correlation_id,
        command_name=command_name,
        event_id=result.event_id,
        changed_fields=result.changed_fields,
        reason=clean_note(reason),
    )
    receipt = {
        "party_id": str(result.party_id),
        "party_membership_id": str(result.party_membership_id),
        "row_version": result.party_row_version,
        "event_id": str(result.event_id),
        "created": result.created,
        "changed": True,
    }
    finish_campaign_idempotency(connection, idem, status_code=status_code, body=receipt)
    plan.finalize(connection)  # R01: the last statement
    return JSONResponse(status_code=status_code, content=receipt)


@router.post(_BASE + "/{party_id}/members", status_code=201)
def add_member_endpoint(
    party_id: uuid.UUID,
    body: AddMemberRequest,
    access: _Edit,
    plan: _Plan,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _run_member(
        command_name="add_party_member",
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload={"party_id": str(party_id), **body.model_dump(mode="json")},
        status_code=201,
        reason=body.reason,
        command=lambda: add_party_member(
            connection,
            campaign_id=access.campaign_id,
            actor_user_id=access.user_id,
            party_id=party_id,
            character_id=body.character_id,
            effective_from_world_time_id=body.effective_from_world_time_id,
            expected_party_row_version=body.expected_party_row_version,
            reason=body.reason,
            plan=plan,
        ),
        plan=plan,
    )


@router.post(_BASE + "/{party_id}/members/{party_membership_id}/end")
def end_membership_endpoint(
    party_id: uuid.UUID,
    party_membership_id: uuid.UUID,
    body: EndMembershipRequest,
    access: _Edit,
    plan: _Plan,
    connection: _Conn,
    idempotency_key: _Key,
    correlation_id: _Corr,
) -> Any:
    return _run_member(
        command_name="end_party_membership",
        access=access,
        connection=connection,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
        payload={
            "party_id": str(party_id),
            "party_membership_id": str(party_membership_id),
            **body.model_dump(mode="json"),
        },
        status_code=200,
        reason=body.reason,
        command=lambda: end_party_membership(
            connection,
            campaign_id=access.campaign_id,
            actor_user_id=access.user_id,
            party_id=party_id,
            party_membership_id=party_membership_id,
            effective_to_world_time_id=body.effective_to_world_time_id,
            expected_party_row_version=body.expected_party_row_version,
            reason=body.reason,
            plan=plan,
        ),
        plan=plan,
    )

"""Add and end party members (Phase 15 checkpoint 15.2C-2).

Membership is typed timeline state on the campaign's own timeline, so each change
records a causal event and an `narrative.event_effects` row in the same
transaction: `party_member_joined` (previous NULL -> party id) and
`party_member_left` (party id -> NULL), each at the membership's own effective world
time and citing the character as its participant. The membership row cites them
(`joined_event_id` / `left_event_id`). The party's `row_version` is bumped by every
membership change and is the optimistic token (`expected_party_row_version`).

Rules: the party must be active (decision D-30; ending a membership is allowed on an
archived party), the member must be a published, active NPC or player character of
the world, and a character cannot have two overlapping memberships of one party on a
timeline: the command checks under the party row lock and reports
`party_membership_overlap`; the database exclusion constraint stays the backstop and
its violation is classified the same way. A membership ends once, strictly after it
began. Corrections to joins and leaves arrive with checkpoint 15.2E-1.

Lock order: operation scope (world, membership rows, account, campaign `FOR
SHARE`), the party row `FOR UPDATE`, the member's `core.entities` row `FOR SHARE`,
then the membership rows.
"""

import json
import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from dnd_ai.domain.authoring import StaleWriteError, normalize_reason
from dnd_ai.domain.data_classification import audit_change, audit_initial
from dnd_ai.domain.party_authoring import (
    PARTY_ACTIVE,
    PARTY_MEMBER_JOINED,
    PARTY_MEMBER_LEFT,
    PARTY_MEMBERSHIP_COMPONENT,
    PartyMemberInvalidError,
    PartyMembershipEndInvalidError,
    PartyMembershipNotOpenError,
    PartyMembershipOverlapError,
    PartyNotActiveError,
)
from dnd_ai.domain.world_time import WorldTimeReferenceInvalidError

from ._content import lock_entities
from ._operations import lock_operation_scope
from ._shared import PartyNotInCampaignError
from .events import EventParticipant, _insert_event_row
from .parties import lock_campaign_party

_MEMBERS = frozenset({"npc", "player_character"})
_EXCLUSION_VIOLATION = "23P01"


@dataclass(frozen=True)
class MembershipResult:
    party_id: uuid.UUID
    party_membership_id: uuid.UUID
    world_id: uuid.UUID
    party_row_version: int
    event_id: uuid.UUID
    character_id: uuid.UUID
    created: bool
    changed_fields: dict[str, object]


def _sort_key(connection: Connection, *, world_id: uuid.UUID, world_time_id: uuid.UUID) -> int:
    key = connection.execute(
        text("SELECT sort_key FROM core.world_times WHERE world_time_id = :t AND world_id = :w"),
        {"t": world_time_id, "w": world_id},
    ).scalar()
    if key is None:
        raise WorldTimeReferenceInvalidError(f"world time {world_time_id} is not in {world_id}")
    assert isinstance(key, int)
    return key


def _effect(
    connection: Connection,
    *,
    event_id: uuid.UUID,
    character_id: uuid.UUID,
    previous: uuid.UUID | None,
    new: uuid.UUID | None,
    world_time_id: uuid.UUID,
) -> None:
    connection.execute(
        text("""
            INSERT INTO narrative.event_effects
                (event_id, target_entity_id, target_component, previous_value, new_value,
                 effective_world_time_id)
            VALUES (:e, :c, :component, CAST(:previous AS jsonb), CAST(:new AS jsonb), :time)
        """),
        {
            "e": event_id,
            "c": character_id,
            "component": PARTY_MEMBERSHIP_COMPONENT,
            "previous": None if previous is None else json.dumps(str(previous)),
            "new": None if new is None else json.dumps(str(new)),
            "time": world_time_id,
        },
    )


def _bump_party(connection: Connection, party_id: uuid.UUID) -> int:
    version = connection.execute(
        text(
            "UPDATE campaign.parties SET updated_at = now() WHERE party_id = :p RETURNING row_version"
        ),
        {"p": party_id},
    ).scalar()
    assert isinstance(version, int)
    return version


def add_party_member(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    party_id: uuid.UUID,
    character_id: uuid.UUID,
    effective_from_world_time_id: uuid.UUID,
    expected_party_row_version: int,
    reason: str | None = None,
) -> MembershipResult:
    clean_reason = normalize_reason(reason)
    scope = lock_operation_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    party = lock_campaign_party(connection, campaign_id=campaign_id, party_id=party_id)
    if party.row_version != expected_party_row_version:
        raise StaleWriteError(f"party {party_id} is at {party.row_version}")
    if party.lifecycle_status != PARTY_ACTIVE:
        raise PartyNotActiveError(f"party {party_id} is {party.lifecycle_status}")
    locked = lock_entities(connection, world_id=scope.world_id, share_ids=[character_id])
    member = locked.get(character_id)
    if (
        member is None
        or member.entity_type_code not in _MEMBERS
        or member.canon_status != "canon"
        or member.lifecycle_status != "active"
    ):
        raise PartyMemberInvalidError(f"{character_id} cannot join {party_id}")
    start_key = _sort_key(
        connection, world_id=scope.world_id, world_time_id=effective_from_world_time_id
    )
    overlap = connection.execute(
        text("""
            SELECT 1 FROM campaign.party_memberships
            WHERE timeline_id = :t AND party_id = :p AND member_entity_id = :m
              AND effective_period && int8range(:start, NULL, '[)')
            LIMIT 1
        """),
        {"t": scope.timeline_id, "p": party_id, "m": character_id, "start": start_key},
    ).scalar()
    if overlap is not None:
        raise PartyMembershipOverlapError(f"{character_id} overlaps in {party_id}")

    event_id = _insert_event_row(
        connection,
        world_id=scope.world_id,
        timeline_id=scope.timeline_id,
        world_time_id=effective_from_world_time_id,
        event_type_code=PARTY_MEMBER_JOINED,
        name="A character joined a party",
        campaign_id=campaign_id,
        participants=(EventParticipant(entity_id=character_id, role_code="actor"),),
    )
    _effect(
        connection,
        event_id=event_id,
        character_id=character_id,
        previous=None,
        new=party_id,
        world_time_id=effective_from_world_time_id,
    )
    try:
        membership_id = connection.execute(
            text("""
                INSERT INTO campaign.party_memberships
                    (timeline_id, party_id, member_entity_id, effective_from_world_time_id,
                     joined_reason, joined_event_id)
                VALUES (:t, :p, :m, :from, :reason, :event)
                RETURNING party_membership_id
            """),
            {
                "t": scope.timeline_id,
                "p": party_id,
                "m": character_id,
                "from": effective_from_world_time_id,
                "reason": clean_reason,
                "event": event_id,
            },
        ).scalar()
    except IntegrityError as exc:
        if getattr(exc.orig, "sqlstate", None) == _EXCLUSION_VIOLATION:
            raise PartyMembershipOverlapError(f"{character_id} overlaps in {party_id}") from exc
        raise
    assert isinstance(membership_id, uuid.UUID)
    return MembershipResult(
        party_id=party_id,
        party_membership_id=membership_id,
        world_id=scope.world_id,
        party_row_version=_bump_party(connection, party_id),
        event_id=event_id,
        character_id=character_id,
        created=True,
        changed_fields=audit_initial(
            {
                "party_id": str(party_id),
                "member_entity_id": str(character_id),
                "effective_from_world_time_id": str(effective_from_world_time_id),
                "joined_reason": clean_reason,
            }
        ),
    )


def end_party_membership(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    party_id: uuid.UUID,
    party_membership_id: uuid.UUID,
    effective_to_world_time_id: uuid.UUID,
    expected_party_row_version: int,
    reason: str | None = None,
) -> MembershipResult:
    clean_reason = normalize_reason(reason)
    scope = lock_operation_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    party = lock_campaign_party(connection, campaign_id=campaign_id, party_id=party_id)
    if party.row_version != expected_party_row_version:
        raise StaleWriteError(f"party {party_id} is at {party.row_version}")
    row = connection.execute(
        text("""
            SELECT member_entity_id, effective_to_world_time_id,
                   lower(effective_period) AS start_key
            FROM campaign.party_memberships
            WHERE party_membership_id = :m AND party_id = :p AND timeline_id = :t
            FOR UPDATE
        """),
        {"m": party_membership_id, "p": party_id, "t": scope.timeline_id},
    ).one_or_none()
    if row is None:
        raise PartyNotInCampaignError(f"membership {party_membership_id} is not in {party_id}")
    if row.effective_to_world_time_id is not None:
        raise PartyMembershipNotOpenError(f"membership {party_membership_id} has ended")
    end_key = _sort_key(
        connection, world_id=scope.world_id, world_time_id=effective_to_world_time_id
    )
    if end_key <= int(row.start_key):
        raise PartyMembershipEndInvalidError(f"{end_key} <= {row.start_key}")

    character_id = row.member_entity_id
    event_id = _insert_event_row(
        connection,
        world_id=scope.world_id,
        timeline_id=scope.timeline_id,
        world_time_id=effective_to_world_time_id,
        event_type_code=PARTY_MEMBER_LEFT,
        name="A character left a party",
        campaign_id=campaign_id,
        participants=(EventParticipant(entity_id=character_id, role_code="actor"),),
    )
    _effect(
        connection,
        event_id=event_id,
        character_id=character_id,
        previous=party_id,
        new=None,
        world_time_id=effective_to_world_time_id,
    )
    connection.execute(
        text("""
            UPDATE campaign.party_memberships
            SET effective_to_world_time_id = :to, left_event_id = :event, left_reason = :reason
            WHERE party_membership_id = :m
        """),
        {
            "to": effective_to_world_time_id,
            "event": event_id,
            "reason": clean_reason,
            "m": party_membership_id,
        },
    )
    return MembershipResult(
        party_id=party_id,
        party_membership_id=party_membership_id,
        world_id=scope.world_id,
        party_row_version=_bump_party(connection, party_id),
        event_id=event_id,
        character_id=character_id,
        created=False,
        changed_fields={
            "effective_to_world_time_id": audit_change(
                "effective_to_world_time_id", None, str(effective_to_world_time_id)
            ),
            "left_reason": audit_change("left_reason", None, clean_reason),
        },
    )

"""Character-relationship and typed-resource-grant commands.

These commands operate over the two `security.*` tables
that let a human actually see or act as something beyond a bare campaign
role: `security.membership_character_relationships` (a membership's
relationship to a character — control, viewing, portrayal) and `security.
resource_grants` (a targeted allow/deny override beyond role/relationship
defaults). Every read path this codebase has already built —
`dnd_ai.domain.access.AccessContext.has_capability`'s `character_id`
target, `dnd_ai.api.access.resolve_party_perspective`/
`resolve_character_view_tier` — has depended on these two tables since
workstream 12, with no command able to populate either through the API
until now.

`create_resource_grant` supports all six `security.resource_grants`
target kinds (`character_id`, `entity_id`, `knowledge_item_id`, `quest_id`,
`session_id`, `event_id`) and `grant_character_relationship` supports
`security.membership_character_relationships`' full temporal scope
(`timeline_id`, `effective_from_world_time_id`/`effective_to_world_time_id`
— the ADR 0010 fictional-time-bounded variant), each pre-checked the same
way `security.enforce_resource_grant_scope()`/`.enforce_membership_
character_relationship_scope()` (migration 080) validate them at the
database layer — see `_validate_resource_grant_target()`'s and `grant_
character_relationship()`'s own docstrings for the exact rules mirrored
and why relying on either trigger's raw `IntegrityError` alone would
surface as an unclassified 500 instead of the intended 400/404.

Every function here is framework-free and trusts its `campaign_id`
argument as already authorized by the API layer
(`require_campaign_capability("access.manage")`) — the same split
`dnd_ai.commands.memberships` follows, including its own reasoning for
why cross-scope invariants are pre-checked here rather than left to
`security.enforce_membership_character_relationship_scope()`/`.
enforce_resource_grant_scope()`'s own `ERRCODE =
'integrity_constraint_violation'` (SQLSTATE `23000`, unrecognized by the
existing generic `IntegrityError` handler, which would otherwise map an
ordinary validation failure to an unclassified 500). The "exactly one
grantee"/"exactly one target" `CHECK` constraints on `security.
resource_grants` are, by contrast, left unduplicated: a violation raises
SQLSTATE `23514`, already correctly classified to a fixed 400.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, text

from dnd_ai.domain.errors import DomainAuthorizationError

from ._shared import lookup_id, validate_session_campaign


class MembershipNotInCampaignError(DomainAuthorizationError):
    """Raised when a caller-supplied `campaign_membership_id` (the subject
    of a character relationship, or the membership grantee of a resource
    grant) does not belong to the already-authorized `campaign_id` —
    including a nonexistent membership, identically, so a caller can never
    distinguish "doesn't exist" from "belongs to a different campaign."
    The supplied ids are included only in the constructor's `detail`
    argument (`str(self)`), never in `safe_message`."""


class AccessGroupNotInCampaignError(DomainAuthorizationError):
    """Raised when a caller-supplied `grantee_access_group_id` does not
    belong to the already-authorized `campaign_id` — including a
    nonexistent access group, identically. The supplied ids are included
    only in the constructor's `detail` argument (`str(self)`), never in
    `safe_message`."""


class ResourceGrantNotInCampaignError(DomainAuthorizationError):
    """Raised by `revoke_resource_grant()` when a caller-supplied
    `resource_grant_id` does not belong to the already-authorized
    `campaign_id` — including a nonexistent grant, identically. The
    supplied ids are included only in the constructor's `detail` argument
    (`str(self)`), never in `safe_message`."""


class TargetNotInCampaignWorldError(DomainAuthorizationError):
    """Raised when a caller-supplied resource-grant target, relationship
    `timeline_id`, or relationship `effective_from_world_time_id`/
    `effective_to_world_time_id` does not belong to the already-authorized
    campaign's own world — including a nonexistent id, identically. Also
    raised for a `session_id`/`event_id` resource-grant target that exists
    and is in the right world but belongs to a different campaign (`dnd_ai.
    commands._shared.validate_session_campaign`'s identical reasoning
    applies here too — a same-world, different-campaign target is exactly
    as much a disclosure risk as a different-world one). The supplied ids
    are included only in the constructor's `detail` argument (`str(self)`),
    never in `safe_message`."""


class InvalidRelationshipPeriodError(ValueError):
    """Raised by `grant_character_relationship()` when `effective_to_
    world_time_id` is supplied without `effective_from_world_time_id` (an
    end with no start), or when the resolved end `sort_key` does not fall
    after the start `sort_key` — mirroring `security.enforce_membership_
    character_relationship_scope()`'s own ordering check (migration 080),
    pre-checked here for the same unclassified-SQLSTATE reason this
    module's docstring gives."""


@dataclass(frozen=True)
class GrantCharacterRelationshipResult:
    membership_character_relationship_id: uuid.UUID


def _resolve_world_time_sort_key(
    connection: Connection, *, world_time_id: uuid.UUID, expected_world_id: uuid.UUID
) -> int:
    row = (
        connection.execute(
            text("SELECT world_id, sort_key FROM core.world_times WHERE world_time_id = :wt"),
            {"wt": world_time_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None or row["world_id"] != expected_world_id:
        raise TargetNotInCampaignWorldError(
            f"world time {world_time_id} does not exist in world {expected_world_id} "
            f"(actual world: {row['world_id'] if row is not None else None})"
        )
    sort_key = row["sort_key"]
    assert isinstance(sort_key, int)
    return sort_key


def grant_character_relationship(
    connection: Connection,
    *,
    campaign_membership_id: uuid.UUID,
    character_id: uuid.UUID,
    relationship_type_code: str,
    campaign_id: uuid.UUID,
    expected_world_id: uuid.UUID,
    granted_by_membership_id: uuid.UUID,
    timeline_id: uuid.UUID | None = None,
    effective_from_world_time_id: uuid.UUID | None = None,
    effective_to_world_time_id: uuid.UUID | None = None,
) -> GrantCharacterRelationshipResult:
    """Grants `campaign_membership_id` a relationship of type `relationship_
    type_code` to `character_id`, unbounded and campaign-wide by default,
    or timeline-scoped and/or fictional-time-bounded (ADR 0010) when
    `timeline_id`/`effective_from_world_time_id`/`effective_to_world_
    time_id` are supplied. Raises `MembershipNotInCampaignError` for a
    `campaign_membership_id` outside `campaign_id`; `TargetNotInCampaignWorldError`
    for a `character_id`, `timeline_id`, or world-time id whose world does
    not match `expected_world_id`; `InvalidRelationshipPeriodError` for an
    `effective_to_world_time_id` supplied without `effective_from_world_
    time_id`, or one that does not resolve to a later `sort_key` — all
    before any row is written, mirroring `security.enforce_membership_
    character_relationship_scope()`'s own checks (see this module's
    docstring for why relying on that trigger's raw `IntegrityError` alone
    would surface as an unclassified 500). `effective_period` itself is
    left for that same trigger to derive from the two world-time ids on
    `INSERT` — never computed or passed here — since it is documented as
    "derived, never client-authoritative." A retry granting the same
    still-active relationship type again is rejected as a 409 by `ux_
    membership_character_relationships_active_type` (existing
    `IntegrityError` handler)."""
    membership_campaign_id = connection.execute(
        text(
            "SELECT campaign_id FROM security.campaign_memberships "
            "WHERE campaign_membership_id = :membership"
        ),
        {"membership": campaign_membership_id},
    ).scalar()
    if membership_campaign_id is None or membership_campaign_id != campaign_id:
        raise MembershipNotInCampaignError(
            f"membership {campaign_membership_id} does not belong to campaign {campaign_id} "
            f"(actual campaign: {membership_campaign_id})"
        )

    character_world_id = connection.execute(
        text("SELECT world_id FROM core.entities WHERE entity_id = :character"),
        {"character": character_id},
    ).scalar()
    if character_world_id is None or character_world_id != expected_world_id:
        raise TargetNotInCampaignWorldError(
            f"character {character_id} does not exist in world {expected_world_id} "
            f"(actual world: {character_world_id})"
        )

    if timeline_id is not None:
        timeline_world_id = connection.execute(
            text("SELECT world_id FROM campaign.timelines WHERE timeline_id = :timeline"),
            {"timeline": timeline_id},
        ).scalar()
        if timeline_world_id is None or timeline_world_id != expected_world_id:
            raise TargetNotInCampaignWorldError(
                f"timeline {timeline_id} does not exist in world {expected_world_id} "
                f"(actual world: {timeline_world_id})"
            )

    if effective_to_world_time_id is not None and effective_from_world_time_id is None:
        raise InvalidRelationshipPeriodError(
            "effective_to_world_time_id requires effective_from_world_time_id"
        )

    if effective_from_world_time_id is not None:
        from_sort_key = _resolve_world_time_sort_key(
            connection,
            world_time_id=effective_from_world_time_id,
            expected_world_id=expected_world_id,
        )
        if effective_to_world_time_id is not None:
            to_sort_key = _resolve_world_time_sort_key(
                connection,
                world_time_id=effective_to_world_time_id,
                expected_world_id=expected_world_id,
            )
            if to_sort_key <= from_sort_key:
                raise InvalidRelationshipPeriodError(
                    f"relationship end (sort_key {to_sort_key}) must be later than its start "
                    f"(sort_key {from_sort_key})"
                )

    relationship_type_id = lookup_id(
        connection,
        "security",
        "character_relationship_types",
        "character_relationship_type_id",
        relationship_type_code,
    )
    membership_character_relationship_id = connection.execute(
        text("""
            INSERT INTO security.membership_character_relationships
                (campaign_membership_id, character_id, character_relationship_type_id,
                 timeline_id, effective_from_world_time_id, effective_to_world_time_id,
                 granted_by_membership_id)
            VALUES (:membership, :character, :relationship_type, :timeline, :from_time,
                    :to_time, :granted_by)
            RETURNING membership_character_relationship_id
        """),
        {
            "membership": campaign_membership_id,
            "character": character_id,
            "relationship_type": relationship_type_id,
            "timeline": timeline_id,
            "from_time": effective_from_world_time_id,
            "to_time": effective_to_world_time_id,
            "granted_by": granted_by_membership_id,
        },
    ).scalar()
    assert isinstance(membership_character_relationship_id, uuid.UUID)
    return GrantCharacterRelationshipResult(
        membership_character_relationship_id=membership_character_relationship_id
    )


def revoke_character_relationship(
    connection: Connection,
    *,
    membership_character_relationship_id: uuid.UUID,
    campaign_id: uuid.UUID,
) -> None:
    """Revokes `membership_character_relationship_id` (sets
    `revoked_at`), or does nothing if it was already revoked — a retry is
    a harmless no-op, needing no idempotency-key store. Raises
    `MembershipNotInCampaignError` for a nonexistent
    `membership_character_relationship_id` or one belonging to a
    membership outside `campaign_id`. Unlike `dnd_ai.commands.memberships.
    revoke_membership_role`, there is no retention invariant to re-check
    here — a character relationship never carries `access.manage`
    (character-scoped capabilities and the campaign-wide `access.manage`
    capability are disjoint concerns)."""
    row = (
        connection.execute(
            text("""
                SELECT cm.campaign_id
                FROM security.membership_character_relationships mcr
                JOIN security.campaign_memberships cm
                    ON cm.campaign_membership_id = mcr.campaign_membership_id
                WHERE mcr.membership_character_relationship_id = :relationship
                FOR UPDATE OF mcr
            """),
            {"relationship": membership_character_relationship_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None or row["campaign_id"] != campaign_id:
        raise MembershipNotInCampaignError(
            f"membership character relationship {membership_character_relationship_id} does not "
            f"belong to campaign {campaign_id} "
            f"(actual campaign: {row['campaign_id'] if row is not None else None})"
        )

    connection.execute(
        text(
            "UPDATE security.membership_character_relationships SET revoked_at = now() "
            "WHERE membership_character_relationship_id = :relationship AND revoked_at IS NULL"
        ),
        {"relationship": membership_character_relationship_id},
    )


@dataclass(frozen=True)
class CreateResourceGrantResult:
    resource_grant_id: uuid.UUID


def _validate_resource_grant_target(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    expected_world_id: uuid.UUID,
    character_id: uuid.UUID | None,
    entity_id: uuid.UUID | None,
    knowledge_item_id: uuid.UUID | None,
    quest_id: uuid.UUID | None,
    session_id: uuid.UUID | None,
    event_id: uuid.UUID | None,
) -> None:
    """Pre-checks whichever one of the six target columns is non-`None`
    against `security.enforce_resource_grant_scope()`'s own rules
    (migration 080): `character_id`/`entity_id`/`knowledge_item_id`/
    `quest_id`/`event_id` are all `core.entities` rows via class-table
    inheritance, so each is checked identically, by world, against that
    one shared table; `session_id` is checked by campaign instead (`dnd_ai.
    commands._shared.validate_session_campaign` — a session has no
    `world_id` of its own, and campaign agreement is the stronger,
    directly-relevant check `campaign.sessions` supports); `event_id` is
    additionally checked by campaign when the event itself carries one
    (`narrative.events.campaign_id` is nullable — a world-level,
    campaign-less event has nothing further to check, matching the
    trigger's own `IF v_target_campaign IS NOT NULL` guard). If the
    caller's target is `None` for every one of the six kinds — or more
    than one is non-`None` — this function does nothing further; `security.
    resource_grants`' own `ck_resource_grants_exactly_one_target` `CHECK`
    constraint (SQLSTATE `23514`, already correctly classified to a fixed
    400) is the actual enforcement for that shape, exactly like `create_
    resource_grant`'s existing "exactly one grantee" reasoning."""
    entity_rooted_target = character_id or entity_id or knowledge_item_id or quest_id or event_id
    if entity_rooted_target is not None:
        target_world_id = connection.execute(
            text("SELECT world_id FROM core.entities WHERE entity_id = :target"),
            {"target": entity_rooted_target},
        ).scalar()
        if target_world_id is None or target_world_id != expected_world_id:
            raise TargetNotInCampaignWorldError(
                f"resource grant target {entity_rooted_target} does not exist in world "
                f"{expected_world_id} (actual world: {target_world_id})"
            )

    if event_id is not None:
        event_campaign_id = connection.execute(
            text("SELECT campaign_id FROM narrative.events WHERE event_id = :event"),
            {"event": event_id},
        ).scalar()
        if event_campaign_id is not None and event_campaign_id != campaign_id:
            raise TargetNotInCampaignWorldError(
                f"event {event_id} belongs to campaign {event_campaign_id}, not {campaign_id}"
            )

    if session_id is not None:
        validate_session_campaign(connection, campaign_id=campaign_id, session_id=session_id)


def create_resource_grant(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    grantee_campaign_membership_id: uuid.UUID | None,
    grantee_access_group_id: uuid.UUID | None,
    capability_code: str,
    effect: str,
    expected_world_id: uuid.UUID,
    granted_by_membership_id: uuid.UUID,
    character_id: uuid.UUID | None = None,
    entity_id: uuid.UUID | None = None,
    knowledge_item_id: uuid.UUID | None = None,
    quest_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    event_id: uuid.UUID | None = None,
    reason: str | None = None,
) -> CreateResourceGrantResult:
    """Creates a `security.resource_grants` row for exactly one of
    `grantee_campaign_membership_id`/`grantee_access_group_id` and exactly
    one of the six target kinds (`character_id`, `entity_id`, `knowledge_
    item_id`, `quest_id`, `session_id`, `event_id`) — the caller supplies
    exactly one of each pair/group; `security.resource_grants`' own `CHECK`
    constraints reject any other shape as a clean 400, needing no pre-check
    here (see this function's and `_validate_resource_grant_target()`'s own
    docstrings). Raises `MembershipNotInCampaignError`/
    `AccessGroupNotInCampaignError` for a grantee outside `campaign_id`, or
    `TargetNotInCampaignWorldError`/`SessionNotInCampaignError` for a
    target outside `expected_world_id`/`campaign_id` — all before any row
    is written. A retry creating the same still-active grant again is
    rejected as a 409 by `ux_resource_grants_active` (existing
    `IntegrityError` handler)."""
    if grantee_campaign_membership_id is not None:
        grantee_campaign_id = connection.execute(
            text(
                "SELECT campaign_id FROM security.campaign_memberships "
                "WHERE campaign_membership_id = :membership"
            ),
            {"membership": grantee_campaign_membership_id},
        ).scalar()
        if grantee_campaign_id is None or grantee_campaign_id != campaign_id:
            raise MembershipNotInCampaignError(
                f"membership {grantee_campaign_membership_id} does not belong to campaign "
                f"{campaign_id} (actual campaign: {grantee_campaign_id})"
            )
    elif grantee_access_group_id is not None:
        group_campaign_id = connection.execute(
            text("SELECT campaign_id FROM security.access_groups WHERE access_group_id = :group"),
            {"group": grantee_access_group_id},
        ).scalar()
        if group_campaign_id is None or group_campaign_id != campaign_id:
            raise AccessGroupNotInCampaignError(
                f"access group {grantee_access_group_id} does not belong to campaign "
                f"{campaign_id} (actual campaign: {group_campaign_id})"
            )

    _validate_resource_grant_target(
        connection,
        campaign_id=campaign_id,
        expected_world_id=expected_world_id,
        character_id=character_id,
        entity_id=entity_id,
        knowledge_item_id=knowledge_item_id,
        quest_id=quest_id,
        session_id=session_id,
        event_id=event_id,
    )

    capability_id = lookup_id(
        connection, "security", "capabilities", "capability_id", capability_code
    )
    resource_grant_id = connection.execute(
        text("""
            INSERT INTO security.resource_grants
                (campaign_id, grantee_campaign_membership_id, grantee_access_group_id,
                 capability_id, effect, character_id, entity_id, knowledge_item_id, quest_id,
                 session_id, event_id, granted_by_membership_id, reason)
            VALUES (:campaign, :grantee_membership, :grantee_group, :capability, :effect,
                    :character, :entity, :knowledge_item, :quest, :session, :event,
                    :granted_by, :reason)
            RETURNING resource_grant_id
        """),
        {
            "campaign": campaign_id,
            "grantee_membership": grantee_campaign_membership_id,
            "grantee_group": grantee_access_group_id,
            "capability": capability_id,
            "effect": effect,
            "character": character_id,
            "entity": entity_id,
            "knowledge_item": knowledge_item_id,
            "quest": quest_id,
            "session": session_id,
            "event": event_id,
            "granted_by": granted_by_membership_id,
            "reason": reason,
        },
    ).scalar()
    assert isinstance(resource_grant_id, uuid.UUID)
    return CreateResourceGrantResult(resource_grant_id=resource_grant_id)


def revoke_resource_grant(
    connection: Connection, *, resource_grant_id: uuid.UUID, campaign_id: uuid.UUID
) -> None:
    """Revokes `resource_grant_id` (sets `revoked_at`), or does nothing if
    it was already revoked — a retry is a harmless no-op, needing no
    idempotency-key store. Raises `ResourceGrantNotInCampaignError` for a
    nonexistent `resource_grant_id` or one belonging to a different
    campaign. `security.resource_grants.campaign_id` is a direct column
    (unlike `security.membership_roles`/
    `.membership_character_relationships`, which resolve it through their
    owning membership), so no join is needed to check it."""
    row_campaign_id = connection.execute(
        text(
            "SELECT campaign_id FROM security.resource_grants "
            "WHERE resource_grant_id = :grant FOR UPDATE"
        ),
        {"grant": resource_grant_id},
    ).scalar()
    if row_campaign_id is None or row_campaign_id != campaign_id:
        raise ResourceGrantNotInCampaignError(
            f"resource grant {resource_grant_id} does not belong to campaign {campaign_id} "
            f"(actual campaign: {row_campaign_id})"
        )

    connection.execute(
        text(
            "UPDATE security.resource_grants SET revoked_at = now() "
            "WHERE resource_grant_id = :grant AND revoked_at IS NULL"
        ),
        {"grant": resource_grant_id},
    )

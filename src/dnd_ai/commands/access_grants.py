"""Character-relationship and typed-resource-grant commands (docs/
architecture/DATABASE_MODEL.md §19.4, §19.6; docs/PLAN.md Phase 10
deliverable "many-to-many user-character relationships and resource-
access grants sufficient for the vertical slice"). A sibling workstream to
`dnd_ai.commands.memberships`, over the two remaining `security.*` tables
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

Scope: this first cut supports only `character_id` as the resource-grant
target (of the six `security.resource_grants` supports) — the one every
existing query workstream's own resource-scoped capability check already
resolves against, and the only one with a real caller yet.
`entity_id`/`knowledge_item_id`/`quest_id`/`session_id`/`event_id` targets
are deferred until a caller actually needs them, not invented
speculatively here — extending `create_resource_grant` to accept a second
target kind is additive, not a redesign. `security.
membership_character_relationships`' `effective_from_world_time_id`/
`effective_to_world_time_id` (the ADR 0010 fictional-time-bounded variant)
and `timeline_id` (narrower-than-campaign scoping) are similarly deferred
for `grant_character_relationship` — this first cut only creates an
unbounded, campaign-wide relationship, the simpler and more common case
(`resolve_access_context`'s own character-capability query already treats
`timeline_id IS NULL` as "applies to every timeline").

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

from ._shared import lookup_id


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
    """Raised when a caller-supplied `character_id` does not belong to the
    already-authorized campaign's own world — including a nonexistent
    character, identically. The supplied ids are included only in the
    constructor's `detail` argument (`str(self)`), never in
    `safe_message`."""


@dataclass(frozen=True)
class GrantCharacterRelationshipResult:
    membership_character_relationship_id: uuid.UUID


def grant_character_relationship(
    connection: Connection,
    *,
    campaign_membership_id: uuid.UUID,
    character_id: uuid.UUID,
    relationship_type_code: str,
    campaign_id: uuid.UUID,
    expected_world_id: uuid.UUID,
    granted_by_membership_id: uuid.UUID,
) -> GrantCharacterRelationshipResult:
    """Grants `campaign_membership_id` an unbounded, campaign-wide
    relationship of type `relationship_type_code` to `character_id`.
    Raises `MembershipNotInCampaignError` for a `campaign_membership_id`
    outside `campaign_id`, or `TargetNotInCampaignWorldError` for a
    `character_id` whose world does not match `expected_world_id` (always
    the caller's own resolved-timeline world — `dnd_ai.api._shared.
    timeline_world_id`, never caller-supplied) — both before any row is
    written. A retry granting the same still-active relationship type
    again is rejected as a 409 by `ux_membership_character_relationships_
    active_type` (existing `IntegrityError` handler)."""
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
                 granted_by_membership_id)
            VALUES (:membership, :character, :relationship_type, :granted_by)
            RETURNING membership_character_relationship_id
        """),
        {
            "membership": campaign_membership_id,
            "character": character_id,
            "relationship_type": relationship_type_id,
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


def create_resource_grant(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    grantee_campaign_membership_id: uuid.UUID | None,
    grantee_access_group_id: uuid.UUID | None,
    character_id: uuid.UUID,
    capability_code: str,
    effect: str,
    expected_world_id: uuid.UUID,
    granted_by_membership_id: uuid.UUID,
    reason: str | None = None,
) -> CreateResourceGrantResult:
    """Creates a `character_id`-scoped `security.resource_grants` row for
    exactly one of `grantee_campaign_membership_id`/
    `grantee_access_group_id` (the caller supplies exactly one; the other
    must be `None` — `security.resource_grants`' own `ck_resource_grants_
    exactly_one_grantee` `CHECK` constraint rejects both/neither as a
    clean 400, needing no pre-check here). Raises
    `MembershipNotInCampaignError`/`AccessGroupNotInCampaignError` for a
    grantee outside `campaign_id`, or `TargetNotInCampaignWorldError` for
    a `character_id` whose world does not match `expected_world_id` —
    before any row is written. A retry creating the same still-active
    grant again is rejected as a 409 by `ux_resource_grants_active`
    (existing `IntegrityError` handler)."""
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

    character_world_id = connection.execute(
        text("SELECT world_id FROM core.entities WHERE entity_id = :character"),
        {"character": character_id},
    ).scalar()
    if character_world_id is None or character_world_id != expected_world_id:
        raise TargetNotInCampaignWorldError(
            f"character {character_id} does not exist in world {expected_world_id} "
            f"(actual world: {character_world_id})"
        )

    capability_id = lookup_id(
        connection, "security", "capabilities", "capability_id", capability_code
    )
    resource_grant_id = connection.execute(
        text("""
            INSERT INTO security.resource_grants
                (campaign_id, grantee_campaign_membership_id, grantee_access_group_id,
                 capability_id, effect, character_id, granted_by_membership_id, reason)
            VALUES (:campaign, :grantee_membership, :grantee_group, :capability, :effect,
                    :character, :granted_by, :reason)
            RETURNING resource_grant_id
        """),
        {
            "campaign": campaign_id,
            "grantee_membership": grantee_campaign_membership_id,
            "grantee_group": grantee_access_group_id,
            "capability": capability_id,
            "effect": effect,
            "character": character_id,
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

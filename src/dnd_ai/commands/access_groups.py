"""Access-group lifecycle and membership commands (Phase 13E-B checkpoint 6).

`security.access_groups`/`.access_group_memberships` (revision 080) have
existed in schema since Phase 10 — read by `dnd_ai.domain.access.
resolve_access_context`'s own group-membership subquery, and writable as a
resource-grant grantee (`dnd_ai.commands.access_grants.
create_resource_grant`/`revoke_resource_grant`, both already accept
`grantee_access_group_id`) — but no command anywhere could create, list,
deactivate, reactivate, or manage the membership of a group itself
(`docs/PHASE13E_ACCESS_CONTRACT.md` §5). This module adds exactly that: the
complete safe lifecycle the existing model supports, never a parallel
authorization/grant system of its own. Group-owned resource grants continue
to go through `dnd_ai.commands.access_grants.create_resource_grant`/
`revoke_resource_grant` entirely unchanged in shape — hardened this
checkpoint to also require the grantee group currently be active
(`AccessGroupNotActiveError`, re-exported below; see that module's own
"Checkpoint-6 correction" note).

**Lifecycle.** `create_access_group()`/`update_access_group()` are the two
"the group still exists, just with different metadata" mutations.
`deactivate_access_group()`/`reactivate_access_group()` move `security.
access_groups.lifecycle_status_id` (revision 105) between `active`/
`archived` — the identical archive/restore pattern `docs/ENTITY_LIFECYCLE.md`
§12/§13 already documents for every other entity, applied here for the
first time to a security concept rather than a world one. Deactivation
closes every open `access_group_memberships` row and revokes every active,
group-owned `resource_grants` row in the same transaction as the status
change — the group's own `end_campaign_membership`-shaped cleanup — so
group-derived access disappears on the very next request (`resolve_access_
context`'s group-membership subquery only ever considers a currently open
`access_group_memberships` row; its resource-grant query already requires
`revoked_at IS NULL` for either grantee kind). Reactivation only ever flips
the status column back: it never reopens a membership deactivation closed
or un-revokes a grant it revoked, matching `docs/ENTITY_LIFECYCLE.md` §13
("Restoring... does not automatically reverse...") — a reactivated group
starts empty and powerless until a new `add_access_group_member()`/
`create_resource_grant()` call explicitly re-adds it. Nothing else in this
schema keys off `lifecycle_status_id`, so flipping it back alone opens no
access by itself.

**Membership.** `add_access_group_member()`/`remove_access_group_member()`
manage `security.access_group_memberships` rows for an existing, active
campaign membership — never a bare `user_id`
(`docs/PHASE13E_ACCESS_CONTRACT.md`'s own "never accept a user id as a
substitute for the authoritative campaign-membership id" instruction).
Removal closes the row (`removed_at = now()`), never deletes it, matching
every other temporal table in this schema. A departed member's group
memberships are already closed by `dnd_ai.commands.memberships.
end_campaign_membership`'s own checkpoint-5 correction — not duplicated
here.

**Lock ordering.** Each function locks its own primary target row(s)
first, then `campaign.campaigns` where campaign lifecycle actually matters
(only the widening actions — create/add/reactivate; the closing actions
here, like `revoke_resource_grant`/`end_campaign_membership`, deliberately
stay available regardless of campaign lifecycle so cleanup is never
blocked), then any secondary lookup (a target membership's owning user).
`add_access_group_member()` locks group, then membership, then campaign,
then the membership's owning user — group first (its own outer container),
then the membership being added (the row its own insert actually depends
on), then campaign, then owning user, mirroring `create_resource_grant()`'s
own "dependent-row-then-campaign-row-then-owning-user" relative order for
its own, disjoint row set, so the two can never deadlock against each
other. `reactivate_access_group()` locks its own group row before
`campaign.campaigns`, matching `create_resource_grant()`'s own group-
grantee branch (hardened this checkpoint to lock the group row too) rather
than inverting that relative order."""

import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, text

from dnd_ai.commands.access_grants import (
    AccessGroupNotActiveError,
    AccessGroupNotInCampaignError,
    MembershipNotActiveError,
    MembershipNotInCampaignError,
)
from dnd_ai.commands.memberships import CampaignNotActiveError
from dnd_ai.domain.errors import DomainAuthorizationError, SafeMessageError

from ._shared import lookup_id

__all__ = [
    "CampaignNotActiveError",
    "AccessGroupNotInCampaignError",
    "AccessGroupNotActiveError",
    "AccessGroupMembershipNotInCampaignError",
    "MembershipNotInCampaignError",
    "MembershipNotActiveError",
    "BlankAccessGroupNameError",
    "AccessGroupNameTooLongError",
    "AccessGroupDescriptionTooLongError",
    "AccessGroupUpdateNoOpError",
    "ACCESS_GROUP_NAME_MAX_LENGTH",
    "ACCESS_GROUP_DESCRIPTION_MAX_LENGTH",
    "CreateAccessGroupResult",
    "create_access_group",
    "UpdateAccessGroupResult",
    "update_access_group",
    "DeactivateAccessGroupResult",
    "deactivate_access_group",
    "ReactivateAccessGroupResult",
    "reactivate_access_group",
    "AddAccessGroupMemberResult",
    "add_access_group_member",
    "RemoveAccessGroupMemberResult",
    "remove_access_group_member",
]

_ACTIVE_LIFECYCLE_STATUS_CODE = "active"
_ARCHIVED_LIFECYCLE_STATUS_CODE = "archived"

# Checkpoint-6 correction: security.access_groups.name/.description had no
# application-layer length bound at all — name relies entirely on
# ck_access_groups_name_length (migration 080, 1-200 characters) surfacing
# as an unclassified-looking-but-actually-fine 400 IntegrityError, and
# description had no bound anywhere until revision 106's ck_access_groups_
# description_length added one. These constants are the single source of
# truth `dnd_ai.api.access_groups`' own Pydantic `Field(max_length=...)`
# imports rather than duplicating the numbers, so the API-layer rejection,
# this module's own pre-check below, and the database CHECK all agree.
ACCESS_GROUP_NAME_MAX_LENGTH = 200
ACCESS_GROUP_DESCRIPTION_MAX_LENGTH = 2000


class BlankAccessGroupNameError(SafeMessageError):
    """Raised by `create_access_group()`/`update_access_group()` when
    `name`, after trimming leading/trailing whitespace, is empty. Checked
    before any write; `security.access_groups`' own `ck_access_groups_
    name_length` `CHECK` constraint (1-200 characters, revision 080) does
    not by itself reject a whitespace-only name, since `char_length` counts
    the whitespace."""

    safe_status_code = 422
    safe_error_code = "invalid_access_group_name"
    safe_message = "The access group name must not be blank."


class AccessGroupNameTooLongError(SafeMessageError):
    """Raised by `create_access_group()`/`update_access_group()` when the
    trimmed `name` exceeds `ACCESS_GROUP_NAME_MAX_LENGTH` (200 —
    unchanged from `ck_access_groups_name_length`'s own pre-existing
    database bound, migration 080). Checked before any write, mirroring
    `BlankAccessGroupNameError`'s own reasoning — the database `CHECK`
    would otherwise reject this too (as a correctly-classified 400
    `IntegrityError`, not an unclassified 500), but pre-checking here gives
    a clearer, dedicated error code instead of relying solely on that
    generic mapping, exactly like the blank-name case above."""

    safe_status_code = 422
    safe_error_code = "access_group_name_too_long"
    safe_message = "The access group name must be 200 characters or fewer."


class AccessGroupDescriptionTooLongError(SafeMessageError):
    """Raised by `create_access_group()`/`update_access_group()` when the
    trimmed `description` exceeds `ACCESS_GROUP_DESCRIPTION_MAX_LENGTH`
    (2000 — `ck_access_groups_description_length`, migration 106).
    Checked before any write, the identical reasoning `AccessGroupNameTooLongError`
    applies for `name`."""

    safe_status_code = 422
    safe_error_code = "access_group_description_too_long"
    safe_message = "The access group description must be 2000 characters or fewer."


class AccessGroupUpdateNoOpError(SafeMessageError):
    """Raised by `update_access_group()` when the requested name and
    description already exactly match the group's current values —
    checked before any write, mirroring `dnd_ai.commands.memberships.
    ChangeMembershipRoleNoOpError`'s/`dnd_ai.commands.access_grants.
    ChangeCharacterRelationshipNoOpError`'s identical reasoning, including
    why this must never be durably cached as a successful idempotent-
    replay result. 422, never 409: this is not a race with anything
    external."""

    safe_status_code = 422
    safe_error_code = "invalid_access_group_update"
    safe_message = "The requested name and description are already this group's current values."


class AccessGroupMembershipNotInCampaignError(DomainAuthorizationError):
    """Raised by `remove_access_group_member()` when a caller-supplied
    `access_group_membership_id` does not resolve to a row whose owning
    group belongs to the already-authorized `campaign_id` — including a
    nonexistent one, identically."""


@dataclass(frozen=True)
class CreateAccessGroupResult:
    access_group_id: uuid.UUID
    name: str
    # Normalized (trimmed, blank-to-None) — never the raw request value.
    # `dnd_ai.api.access_groups.create_access_group_endpoint` records this,
    # not `body.description`, in `changed_fields` so a caller-supplied
    # description containing only whitespace (persisted as NULL) is never
    # misrepresented in the audit trail as some non-empty value.
    description: str | None


def create_access_group(
    connection: Connection, *, campaign_id: uuid.UUID, name: str, description: str | None
) -> CreateAccessGroupResult:
    """Creates a new, active `security.access_groups` row scoped to
    `campaign_id` — the portal Access page's "Create access group" action.

    `name` is trimmed of leading/trailing whitespace before validation and
    storage; a blank or whitespace-only name is rejected
    (`BlankAccessGroupNameError`, 422) before any write. `description` is
    likewise trimmed, with a blank result stored as `NULL` rather than an
    empty string. `security.access_groups`' own `ck_access_groups_
    name_length` `CHECK` constraint (1-200 characters) still applies to the
    trimmed name; a too-long name reaches that `CHECK` as an ordinary,
    already-classified 400 (SQLSTATE `23514`), not pre-checked here,
    matching this codebase's own "database-enforced invariants deliberately
    not duplicated" policy.

    Requires `campaign_id` to currently be `active` (`CampaignNotActiveError`,
    409) — the same "currently true" bar `add_campaign_member()`/
    `create_resource_grant()` already apply to every other campaign-scoped
    creation. Locks `campaign.campaigns` `FOR UPDATE` first — nothing else
    to lock beforehand, unlike a resource grant or character relationship,
    since creating a group depends on no pre-existing target/grantee row.

    A duplicate logical name (case-sensitive, matching `ux_access_groups_
    campaign_name`'s own plain-text comparison) is left to that unique
    constraint's own 409 `IntegrityError`, not pre-checked, exactly like
    every other uniqueness constraint in this codebase (`ux_campaign_
    memberships_open`, `ux_resource_grants_active`): two concurrent creates
    of the same name can never both succeed regardless of which one's
    pre-checks ran first, and neither ever leaves a duplicate group
    behind."""
    normalized_name = name.strip()
    if not normalized_name:
        raise BlankAccessGroupNameError("access group name must not be blank")
    if len(normalized_name) > ACCESS_GROUP_NAME_MAX_LENGTH:
        raise AccessGroupNameTooLongError("access group name exceeds the maximum length")
    normalized_description = description.strip() if description else None
    normalized_description = normalized_description or None
    if (
        normalized_description is not None
        and len(normalized_description) > ACCESS_GROUP_DESCRIPTION_MAX_LENGTH
    ):
        raise AccessGroupDescriptionTooLongError(
            "access group description exceeds the maximum length"
        )

    campaign_status_code = connection.execute(
        text("""
            SELECT ls.code FROM campaign.campaigns c
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = c.lifecycle_status_id
            WHERE c.campaign_id = :campaign
            FOR UPDATE OF c
        """),
        {"campaign": campaign_id},
    ).scalar()
    if campaign_status_code != "active":
        raise CampaignNotActiveError(f"campaign {campaign_id} is not currently active")

    active_lifecycle_status_id = lookup_id(
        connection,
        "core",
        "lifecycle_statuses",
        "lifecycle_status_id",
        _ACTIVE_LIFECYCLE_STATUS_CODE,
    )
    access_group_id = connection.execute(
        text("""
            INSERT INTO security.access_groups
                (campaign_id, name, description, lifecycle_status_id)
            VALUES (:campaign, :name, :description, :status)
            RETURNING access_group_id
        """),
        {
            "campaign": campaign_id,
            "name": normalized_name,
            "description": normalized_description,
            "status": active_lifecycle_status_id,
        },
    ).scalar()
    assert isinstance(access_group_id, uuid.UUID)
    return CreateAccessGroupResult(
        access_group_id=access_group_id, name=normalized_name, description=normalized_description
    )


@dataclass(frozen=True)
class UpdateAccessGroupResult:
    access_group_id: uuid.UUID
    previous_name: str
    name: str
    # Normalized (trimmed, blank-to-None) — never the raw request value; see
    # CreateAccessGroupResult.description's identical contract.
    description: str | None


def update_access_group(
    connection: Connection,
    *,
    access_group_id: uuid.UUID,
    campaign_id: uuid.UUID,
    name: str,
    description: str | None,
) -> UpdateAccessGroupResult:
    """Renames/redescribes an existing, active `security.access_groups`
    row — the portal's "Edit access group" action. Only `name`/
    `description` ever change here; `campaign_id`, `lifecycle_status_id`,
    membership, and grants are untouched — a generic patch accepting
    arbitrary columns is deliberately not offered.

    `name`/`description` are trimmed and validated exactly like
    `create_access_group()`'s own rule (`BlankAccessGroupNameError` for a
    blank/whitespace-only name).

    Requires the group to belong to `campaign_id`
    (`AccessGroupNotInCampaignError`) and currently be active
    (`AccessGroupNotActiveError`, 409) — an archived group's metadata is
    frozen; reactivate it first to rename it. Locks the group row `FOR
    UPDATE` first, this function's own sole target.

    Rejects a no-op request (`AccessGroupUpdateNoOpError`, 422, checked
    before any write so it can never consume an `Idempotency-Key`) when the
    normalized name and description both already exactly match the group's
    current values — mirrors `change_membership_role`'s/`change_character_
    relationship`'s own identical no-op rejection.

    A rename that collides with another group's name in the same campaign
    is left to `ux_access_groups_campaign_name`'s own 409 `IntegrityError`,
    not pre-checked, exactly like `create_access_group()`."""
    row = (
        connection.execute(
            text("""
                SELECT ag.campaign_id, ag.name, ag.description, ls.code AS lifecycle_status_code
                FROM security.access_groups ag
                JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = ag.lifecycle_status_id
                WHERE ag.access_group_id = :group
                FOR UPDATE OF ag
            """),
            {"group": access_group_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None or row["campaign_id"] != campaign_id:
        raise AccessGroupNotInCampaignError(
            f"access group {access_group_id} does not belong to campaign {campaign_id} "
            f"(actual campaign: {row['campaign_id'] if row is not None else None})"
        )
    if row["lifecycle_status_code"] != "active":
        raise AccessGroupNotActiveError(f"access group {access_group_id} is not currently active")

    normalized_name = name.strip()
    if not normalized_name:
        raise BlankAccessGroupNameError("access group name must not be blank")
    if len(normalized_name) > ACCESS_GROUP_NAME_MAX_LENGTH:
        raise AccessGroupNameTooLongError("access group name exceeds the maximum length")
    normalized_description = description.strip() if description else None
    normalized_description = normalized_description or None
    if (
        normalized_description is not None
        and len(normalized_description) > ACCESS_GROUP_DESCRIPTION_MAX_LENGTH
    ):
        raise AccessGroupDescriptionTooLongError(
            "access group description exceeds the maximum length"
        )

    if normalized_name == row["name"] and normalized_description == row["description"]:
        raise AccessGroupUpdateNoOpError(
            "the requested name/description already match this group's current values"
        )

    connection.execute(
        text("""
            UPDATE security.access_groups SET name = :name, description = :description
            WHERE access_group_id = :group
        """),
        {"name": normalized_name, "description": normalized_description, "group": access_group_id},
    )
    return UpdateAccessGroupResult(
        access_group_id=access_group_id,
        previous_name=row["name"],
        name=normalized_name,
        description=normalized_description,
    )


@dataclass(frozen=True)
class DeactivateAccessGroupResult:
    """`deactivated` is `True` only when this call transitioned the group
    from active to archived — `False` for the documented harmless no-op
    (already archived). `removed_access_group_membership_ids`/`revoked_
    resource_grant_ids` are empty for the no-op case and otherwise list
    every membership/grant row this call closed, for the caller's own
    audit `changed_fields`."""

    access_group_id: uuid.UUID
    deactivated: bool
    removed_access_group_membership_ids: tuple[uuid.UUID, ...] = ()
    revoked_resource_grant_ids: tuple[uuid.UUID, ...] = ()


def deactivate_access_group(
    connection: Connection, *, access_group_id: uuid.UUID, campaign_id: uuid.UUID
) -> DeactivateAccessGroupResult:
    """Archives an existing access group — the portal's "Deactivate access
    group" action. Never deletes the row (CLAUDE.md rule 9); moves
    `lifecycle_status_id` from `active` to `archived` and, in the same
    transaction, closes (`removed_at = now()`) every currently open
    `security.access_group_memberships` row and revokes (`revoked_at =
    now()`) every currently active `security.resource_grants` row this
    group owns — the group's own `end_campaign_membership`-shaped cleanup,
    so group-derived access disappears on the very next request.

    Raises `AccessGroupNotInCampaignError` for a group outside
    `campaign_id`. Returns `deactivated=False` (a harmless no-op, no
    further write) for a group that is already archived, mirroring
    `revoke_resource_grant()`'s/`end_campaign_membership()`'s own
    established "retry against already-closed state is a no-op" contract.

    Deliberately does not check campaign lifecycle status — like `revoke_
    resource_grant()`/`revoke_character_relationship()`/`end_campaign_
    membership()`, closing access must remain possible for cleanup even
    against an inactive campaign."""
    row = (
        connection.execute(
            text("""
                SELECT ag.campaign_id, ls.code AS lifecycle_status_code
                FROM security.access_groups ag
                JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = ag.lifecycle_status_id
                WHERE ag.access_group_id = :group
                FOR UPDATE OF ag
            """),
            {"group": access_group_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None or row["campaign_id"] != campaign_id:
        raise AccessGroupNotInCampaignError(
            f"access group {access_group_id} does not belong to campaign {campaign_id} "
            f"(actual campaign: {row['campaign_id'] if row is not None else None})"
        )
    if row["lifecycle_status_code"] != "active":
        return DeactivateAccessGroupResult(access_group_id=access_group_id, deactivated=False)

    archived_lifecycle_status_id = lookup_id(
        connection,
        "core",
        "lifecycle_statuses",
        "lifecycle_status_id",
        _ARCHIVED_LIFECYCLE_STATUS_CODE,
    )
    connection.execute(
        text("""
            UPDATE security.access_groups SET lifecycle_status_id = :status
            WHERE access_group_id = :group
        """),
        {"status": archived_lifecycle_status_id, "group": access_group_id},
    )

    removed_membership_ids = tuple(
        connection.execute(
            text("""
                UPDATE security.access_group_memberships SET removed_at = now()
                WHERE access_group_id = :group AND removed_at IS NULL
                RETURNING access_group_membership_id
            """),
            {"group": access_group_id},
        )
        .scalars()
        .all()
    )
    revoked_grant_ids = tuple(
        connection.execute(
            text("""
                UPDATE security.resource_grants SET revoked_at = now()
                WHERE grantee_access_group_id = :group AND revoked_at IS NULL
                RETURNING resource_grant_id
            """),
            {"group": access_group_id},
        )
        .scalars()
        .all()
    )

    return DeactivateAccessGroupResult(
        access_group_id=access_group_id,
        deactivated=True,
        removed_access_group_membership_ids=removed_membership_ids,
        revoked_resource_grant_ids=revoked_grant_ids,
    )


@dataclass(frozen=True)
class ReactivateAccessGroupResult:
    access_group_id: uuid.UUID
    reactivated: bool


def reactivate_access_group(
    connection: Connection, *, access_group_id: uuid.UUID, campaign_id: uuid.UUID
) -> ReactivateAccessGroupResult:
    """Restores an archived access group to active — the portal's
    "Reactivate access group" action, `docs/ENTITY_LIFECYCLE.md` §13's
    restoration pattern applied to a security concept. Flips only
    `lifecycle_status_id` back to `active`: never reopens a membership
    `deactivate_access_group()` closed, never un-revokes a grant it
    revoked — a reactivated group starts empty and powerless until a new
    `add_access_group_member()`/`create_resource_grant()` call explicitly
    re-adds it. This is safe because nothing else in this schema keys off
    `lifecycle_status_id` — flipping it back alone opens no access by
    itself.

    Locks the group row first (this module's own established "dependent-
    row-then-campaign-row" order), so the no-op case (already active)
    never needs to touch `campaign.campaigns` at all. Otherwise requires
    `campaign_id` to currently be `active` (`CampaignNotActiveError`, 409)
    — reactivating a group is a widening action (new add-member/grant
    calls could immediately follow), the same "currently true" bar every
    other campaign-scoped creation/widening command in this module
    applies.

    Returns `reactivated=False` (a harmless no-op) for a group that is
    already active."""
    row = (
        connection.execute(
            text("""
                SELECT ag.campaign_id, ls.code AS lifecycle_status_code
                FROM security.access_groups ag
                JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = ag.lifecycle_status_id
                WHERE ag.access_group_id = :group
                FOR UPDATE OF ag
            """),
            {"group": access_group_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None or row["campaign_id"] != campaign_id:
        raise AccessGroupNotInCampaignError(
            f"access group {access_group_id} does not belong to campaign {campaign_id} "
            f"(actual campaign: {row['campaign_id'] if row is not None else None})"
        )
    if row["lifecycle_status_code"] == "active":
        return ReactivateAccessGroupResult(access_group_id=access_group_id, reactivated=False)

    campaign_status_code = connection.execute(
        text("""
            SELECT ls.code FROM campaign.campaigns c
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = c.lifecycle_status_id
            WHERE c.campaign_id = :campaign
            FOR UPDATE OF c
        """),
        {"campaign": campaign_id},
    ).scalar()
    if campaign_status_code != "active":
        raise CampaignNotActiveError(f"campaign {campaign_id} is not currently active")

    active_lifecycle_status_id = lookup_id(
        connection,
        "core",
        "lifecycle_statuses",
        "lifecycle_status_id",
        _ACTIVE_LIFECYCLE_STATUS_CODE,
    )
    connection.execute(
        text("""
            UPDATE security.access_groups SET lifecycle_status_id = :status
            WHERE access_group_id = :group
        """),
        {"status": active_lifecycle_status_id, "group": access_group_id},
    )
    return ReactivateAccessGroupResult(access_group_id=access_group_id, reactivated=True)


@dataclass(frozen=True)
class AddAccessGroupMemberResult:
    access_group_membership_id: uuid.UUID


def add_access_group_member(
    connection: Connection,
    *,
    access_group_id: uuid.UUID,
    campaign_membership_id: uuid.UUID,
    campaign_id: uuid.UUID,
    added_by_membership_id: uuid.UUID,
) -> AddAccessGroupMemberResult:
    """Adds an existing, active campaign membership to an existing, active
    access group — the portal's "Add member to group" action. Always
    creates a new `security.access_group_memberships` row, never reopening
    an earlier, closed one for the same pair, mirroring `add_campaign_
    member()`'s own "re-entry always creates a new temporal row" policy. A
    membership already open in this group is left to `ux_access_group_
    memberships_open`'s own 409 `IntegrityError`, not pre-checked, exactly
    like every other uniqueness constraint in this codebase.

    Requires the group to belong to `campaign_id` and currently be active
    (`AccessGroupNotInCampaignError`/`AccessGroupNotActiveError`, 409) —
    adding a member to an archived group would have no effect and would be
    a confusing action to allow. Requires the target `campaign_membership_
    id` to belong to `campaign_id`, be open, in the `active` membership
    status, and its owning user account to currently be platform-active
    (`MembershipNotActiveError`, 409) — the identical "currently true" bar
    `create_resource_grant()`'s own membership-grantee branch already
    applies, reused rather than duplicated. Requires `campaign_id` itself
    to currently be active (`CampaignNotActiveError`, 409).

    Lock ordering: group, then membership, then campaign, then the
    membership's owning user — see this module's own docstring for the
    full deadlock-avoidance reasoning."""
    group_row = (
        connection.execute(
            text("""
                SELECT ag.campaign_id, ls.code AS lifecycle_status_code
                FROM security.access_groups ag
                JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = ag.lifecycle_status_id
                WHERE ag.access_group_id = :group
                FOR UPDATE OF ag
            """),
            {"group": access_group_id},
        )
        .mappings()
        .one_or_none()
    )
    if group_row is None or group_row["campaign_id"] != campaign_id:
        raise AccessGroupNotInCampaignError(
            f"access group {access_group_id} does not belong to campaign {campaign_id} "
            f"(actual campaign: {group_row['campaign_id'] if group_row is not None else None})"
        )
    if group_row["lifecycle_status_code"] != "active":
        raise AccessGroupNotActiveError(f"access group {access_group_id} is not currently active")

    membership_row = (
        connection.execute(
            text("""
                SELECT cm.campaign_id, cm.ended_at, cm.user_id,
                       ms.code AS membership_status_code,
                       ms.is_active AS membership_status_is_active
                FROM security.campaign_memberships cm
                JOIN security.membership_statuses ms
                    ON ms.membership_status_id = cm.membership_status_id
                WHERE cm.campaign_membership_id = :membership
                FOR UPDATE OF cm
            """),
            {"membership": campaign_membership_id},
        )
        .mappings()
        .one_or_none()
    )
    if membership_row is None or membership_row["campaign_id"] != campaign_id:
        raise MembershipNotInCampaignError(
            f"membership {campaign_membership_id} does not belong to campaign {campaign_id} "
            f"(actual campaign: "
            f"{membership_row['campaign_id'] if membership_row is not None else None})"
        )
    membership_is_eligible = (
        membership_row["ended_at"] is None
        and membership_row["membership_status_code"] == "active"
        and membership_row["membership_status_is_active"]
    )
    if not membership_is_eligible:
        raise MembershipNotActiveError(
            f"membership {campaign_membership_id} is not currently an eligible, open "
            "membership to add to an access group"
        )

    campaign_status_code = connection.execute(
        text("""
            SELECT ls.code FROM campaign.campaigns c
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = c.lifecycle_status_id
            WHERE c.campaign_id = :campaign
            FOR UPDATE OF c
        """),
        {"campaign": campaign_id},
    ).scalar()
    if campaign_status_code != "active":
        raise CampaignNotActiveError(f"campaign {campaign_id} is not currently active")

    user_lifecycle_status_code = connection.execute(
        text("""
            SELECT ls.code FROM security.users u
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = u.lifecycle_status_id
            WHERE u.user_id = :user
            FOR UPDATE OF u
        """),
        {"user": membership_row["user_id"]},
    ).scalar()
    if user_lifecycle_status_code != "active":
        raise MembershipNotActiveError(
            f"membership {campaign_membership_id}'s user {membership_row['user_id']} is not "
            "currently an active platform account"
        )

    access_group_membership_id = connection.execute(
        text("""
            INSERT INTO security.access_group_memberships
                (access_group_id, campaign_membership_id, added_by_membership_id)
            VALUES (:group, :membership, :added_by)
            RETURNING access_group_membership_id
        """),
        {
            "group": access_group_id,
            "membership": campaign_membership_id,
            "added_by": added_by_membership_id,
        },
    ).scalar()
    assert isinstance(access_group_membership_id, uuid.UUID)
    return AddAccessGroupMemberResult(access_group_membership_id=access_group_membership_id)


@dataclass(frozen=True)
class RemoveAccessGroupMemberResult:
    """`removed` is `True` only when this call transitioned the row from
    open to removed — `False` for the documented harmless no-op (already
    removed). `access_group_id`/`campaign_membership_id` are the removed
    row's own identifying columns, read server-side from the same locked
    row this function already reads to decide `removed` — never re-derived
    from caller-supplied input, since a caller only ever supplies `access_
    group_membership_id`. `dnd_ai.api.access_groups.
    remove_access_group_member_endpoint` uses these for a bounded audit
    `changed_fields` payload. Both `None` for the no-op case."""

    removed: bool
    access_group_id: uuid.UUID | None = None
    campaign_membership_id: uuid.UUID | None = None


def remove_access_group_member(
    connection: Connection, *, access_group_membership_id: uuid.UUID, campaign_id: uuid.UUID
) -> RemoveAccessGroupMemberResult:
    """Removes one member from one access group — the portal's "Remove
    from group" action. Closes the row (`removed_at = now()`), never
    deletes it, matching every other temporal table in this schema.

    Raises `AccessGroupMembershipNotInCampaignError` for an `access_group_
    membership_id` whose owning group does not belong to `campaign_id`,
    including a nonexistent one. Returns `removed=False` (a harmless
    no-op) for an already-removed row, matching `revoke_resource_grant()`'s
    /`revoke_character_relationship()`'s own established "retry against
    already-closed state is a no-op" contract.

    Deliberately checks none of `add_access_group_member()`'s own
    eligibility conditions (the group's own active status, the member's
    membership/account status, campaign lifecycle) — closing access must
    remain possible for cleanup, the same policy every other revoke/end/
    remove command in this codebase already follows. Self-removal is
    permitted, with no special-case check here — an access group carries
    no per-campaign retention invariant the way `access.manage` role/
    membership rows do. Does not touch the member's own `campaign_
    membership` row, roles, character relationships, or direct resource
    grants, and does not affect any other member's link to this same group
    or the group's own resource grants."""
    row = (
        connection.execute(
            text("""
                SELECT ag.campaign_id, agm.access_group_id, agm.campaign_membership_id,
                       agm.removed_at
                FROM security.access_group_memberships agm
                JOIN security.access_groups ag ON ag.access_group_id = agm.access_group_id
                WHERE agm.access_group_membership_id = :membership
                FOR UPDATE OF agm
            """),
            {"membership": access_group_membership_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None or row["campaign_id"] != campaign_id:
        raise AccessGroupMembershipNotInCampaignError(
            f"access group membership {access_group_membership_id} does not belong to campaign "
            f"{campaign_id} (actual campaign: {row['campaign_id'] if row is not None else None})"
        )
    if row["removed_at"] is not None:
        return RemoveAccessGroupMemberResult(removed=False)

    connection.execute(
        text("""
            UPDATE security.access_group_memberships SET removed_at = now()
            WHERE access_group_membership_id = :membership
        """),
        {"membership": access_group_membership_id},
    )
    return RemoveAccessGroupMemberResult(
        removed=True,
        access_group_id=row["access_group_id"],
        campaign_membership_id=row["campaign_membership_id"],
    )

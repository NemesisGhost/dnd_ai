"""Administrative recovery of stranded worlds and campaigns
(docs/adr/0020-scoped-system-world-and-campaign-roles.md, plan section 4.5).

Routine Administrator access grants no world or campaign read. These two commands
are the only overrides, and they are deliberately narrow:

- each is callable only by an active platform Administrator (a non-administrator
  gets the usual non-disclosing 404);
- each works only on an aggregate that is *actually* stranded: a world with no
  manageable Owner (an Owner needs an active account and the system `gm` role), a
  campaign with no access manager on an active account. Refusing otherwise means
  recovery can never be used to take over a healthy world or campaign;
- each needs a non-empty, bounded reason;
- each only *adds* an assignment for an eligible account. It reads no content,
  removes nobody, and leaves authorship untouched.

The commands write no audit row. The operator scripts that expose them
(`scripts/recover_world_ownership.py`, `scripts/recover_campaign_access_manager.py`)
record one `audit.change_log` row per recovery with the Administrator as actor and
the reason attached. No HTTP route exists (owner question Q11: scripts first).
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, text

from dnd_ai.domain.authoring import WorldNotAuthorizedError, normalize_reason
from dnd_ai.domain.errors import SafeMessageError
from dnd_ai.domain.system_authority import WORLD_ADMINISTER
from dnd_ai.domain.world_authority import WORLD_OWNER_ROLE
from dnd_ai.queries.stranded import campaign_has_active_access_manager, world_has_manageable_owner
from dnd_ai.queries.system_authority import has_system_capability

from ._shared import lookup_id
from .world_access import (
    TargetRequiresSystemGmError,
    WorldRoleTargetIneligibleError,
    _insert_membership,
)


class RecoveryNotNeededError(SafeMessageError):
    """The world or campaign is not stranded, so recovery is refused."""

    safe_status_code = 409
    safe_error_code = "recovery_not_needed"
    safe_message = "That world or campaign still has someone who can manage it."


@dataclass(frozen=True)
class WorldRecoveryResult:
    world_id: uuid.UUID
    new_owner_user_id: uuid.UUID
    world_membership_id: uuid.UUID | None


@dataclass(frozen=True)
class CampaignRecoveryResult:
    campaign_id: uuid.UUID
    new_manager_user_id: uuid.UUID
    campaign_membership_id: uuid.UUID
    membership_role_id: uuid.UUID | None


def _require_administrator(connection: Connection, admin_user_id: uuid.UUID) -> None:
    from dnd_ai.domain.access import is_platform_administrator

    from .local_auth import NotPlatformAdministratorError

    if not is_platform_administrator(connection, user_id=admin_user_id):
        raise NotPlatformAdministratorError(f"user {admin_user_id} is not a platform administrator")


def _active_user(connection: Connection, user_id: uuid.UUID) -> bool:
    return bool(
        connection.execute(
            text("""
                SELECT EXISTS (
                    SELECT 1 FROM security.users u
                    JOIN core.lifecycle_statuses ls
                      ON ls.lifecycle_status_id = u.lifecycle_status_id
                    WHERE u.user_id = :u AND ls.code = 'active'
                )
            """),
            {"u": user_id},
        ).scalar()
    )


def recover_world_ownership(
    connection: Connection,
    *,
    admin_user_id: uuid.UUID,
    world_id: uuid.UUID,
    new_owner_user_id: uuid.UUID,
    reason: str,
) -> WorldRecoveryResult:
    """Make `new_owner_user_id` an Owner of a stranded world. The new Owner must be
    an active account holding the system `gm` role."""
    clean_reason = normalize_reason(reason, required=True)
    assert clean_reason is not None
    _require_administrator(connection, admin_user_id)
    locked = connection.execute(
        text("SELECT 1 FROM core.worlds WHERE world_id = :w FOR UPDATE"), {"w": world_id}
    ).first()
    if locked is None:
        raise WorldNotAuthorizedError(f"world {world_id} does not exist")
    if world_has_manageable_owner(connection, world_id=world_id):
        raise RecoveryNotNeededError(f"world {world_id} has a manageable owner")
    if not _active_user(connection, new_owner_user_id):
        raise WorldRoleTargetIneligibleError(f"user {new_owner_user_id} is not active")
    if not has_system_capability(
        connection, user_id=new_owner_user_id, capability_code=WORLD_ADMINISTER
    ):
        raise TargetRequiresSystemGmError(f"user {new_owner_user_id} lacks world.administer")
    membership_id = _insert_membership(
        connection,
        world_id=world_id,
        user_id=new_owner_user_id,
        role_code=WORLD_OWNER_ROLE,
        granted_by_user_id=admin_user_id,
    )
    return WorldRecoveryResult(
        world_id=world_id, new_owner_user_id=new_owner_user_id, world_membership_id=membership_id
    )


def recover_campaign_access_manager(
    connection: Connection,
    *,
    admin_user_id: uuid.UUID,
    campaign_id: uuid.UUID,
    new_user_id: uuid.UUID,
    reason: str,
) -> CampaignRecoveryResult:
    """Give `new_user_id` the `campaign_owner` role in a campaign that has no
    access manager on an active account, creating their membership if needed."""
    clean_reason = normalize_reason(reason, required=True)
    assert clean_reason is not None
    _require_administrator(connection, admin_user_id)
    locked = connection.execute(
        text("SELECT 1 FROM campaign.campaigns WHERE campaign_id = :c FOR UPDATE"),
        {"c": campaign_id},
    ).first()
    if locked is None:
        raise WorldNotAuthorizedError(f"campaign {campaign_id} does not exist")
    if campaign_has_active_access_manager(connection, campaign_id=campaign_id):
        raise RecoveryNotNeededError(f"campaign {campaign_id} has an active access manager")
    if not _active_user(connection, new_user_id):
        raise WorldRoleTargetIneligibleError(f"user {new_user_id} is not active")

    active_status = lookup_id(
        connection, "security", "membership_statuses", "membership_status_id", "active"
    )
    membership_id = connection.execute(
        text("""
            SELECT campaign_membership_id FROM security.campaign_memberships
            WHERE campaign_id = :c AND user_id = :u AND ended_at IS NULL
            FOR UPDATE
        """),
        {"c": campaign_id, "u": new_user_id},
    ).scalar()
    if membership_id is None:
        membership_id = connection.execute(
            text("""
                INSERT INTO security.campaign_memberships
                    (campaign_id, user_id, membership_status_id, joined_at)
                VALUES (:c, :u, :s, now())
                RETURNING campaign_membership_id
            """),
            {"c": campaign_id, "u": new_user_id, "s": active_status},
        ).scalar()
    else:
        connection.execute(
            text(
                "UPDATE security.campaign_memberships SET membership_status_id = :s "
                "WHERE campaign_membership_id = :m"
            ),
            {"s": active_status, "m": membership_id},
        )
    assert isinstance(membership_id, uuid.UUID)
    role_id = connection.execute(
        text(
            "SELECT role_id FROM security.roles WHERE code = 'campaign_owner' AND campaign_id IS NULL"
        )
    ).scalar()
    assigned = connection.execute(
        text("""
            INSERT INTO security.membership_roles (campaign_membership_id, role_id)
            VALUES (:m, :r)
            ON CONFLICT (campaign_membership_id, role_id) WHERE revoked_at IS NULL DO NOTHING
            RETURNING membership_role_id
        """),
        {"m": membership_id, "r": role_id},
    ).scalar()
    return CampaignRecoveryResult(
        campaign_id=campaign_id,
        new_manager_user_id=new_user_id,
        campaign_membership_id=membership_id,
        membership_role_id=assigned,
    )

"""World sharing: role assignments, use grants and ownership transfer
(docs/adr/0020-scoped-system-world-and-campaign-roles.md).

Every command here is a world-scope operation. It locks the world row first (the
global lock order, docs/architecture/SYSTEM_ARCHITECTURE.md §7.1), then re-resolves
the caller's authority under that lock, so a role ended or a system GM revoked
between the route's check and the write is honoured. A caller who holds no
authority at all, or lacks the capability (including an Owner whose system GM was
revoked: `world.share` and `world.transfer` need `world.administer`), gets the one
fixed non-disclosing `WorldNotAuthorizedError`.

Targets are active accounts only. Nothing here touches a campaign, a campaign role,
or any authorship column (`core.entities.created_by_user_id`, revision authors,
`audit.change_log`): ownership transfer ends the previous Owner's *authority* and
nothing about their *attribution*.

The commands do not audit; the API layer writes the `audit.change_log` row for each
real change (and none for an idempotent no-op), as for every other command.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, text

from dnd_ai.domain.authoring import WorldNotAuthorizedError
from dnd_ai.domain.errors import SafeMessageError
from dnd_ai.domain.system_authority import WORLD_ADMINISTER
from dnd_ai.domain.world_authority import (
    WORLD_OWNER_ROLE,
    WORLD_ROLE_CODES,
    WORLD_SHARE,
    WORLD_TRANSFER,
)
from dnd_ai.queries.system_authority import has_system_capability
from dnd_ai.queries.world_access import ActiveAccount, find_active_account
from dnd_ai.queries.world_authority import resolve_world_authority

from ._shared import lookup_id


class WorldRoleTargetIneligibleError(SafeMessageError):
    """The named account does not exist, is not active, or is not a local
    account. The three cases are indistinguishable by design."""

    safe_status_code = 409
    safe_error_code = "world_role_target_ineligible"
    safe_message = "That account cannot be given this access."


class TargetRequiresSystemGmError(SafeMessageError):
    """A new Owner must hold the system `gm` role, because managing a world needs
    `world.administer` (decision D11); an Owner who could not manage it would
    strand the world."""

    safe_status_code = 409
    safe_error_code = "target_requires_system_gm"
    safe_message = "A world owner must hold the game master system role."


class WorldOwnerRequiredError(SafeMessageError):
    """Ending this assignment would leave the world with no Owner."""

    safe_status_code = 409
    safe_error_code = "world_owner_required"
    safe_message = "A world must keep at least one owner."


class WorldRoleAssignmentNotFoundError(WorldNotAuthorizedError):
    """No such open assignment or grant on this world (fixed 404)."""


class InvalidOwnershipTransferError(SafeMessageError):
    safe_status_code = 409
    safe_error_code = "invalid_ownership_transfer"
    safe_message = "Ownership cannot be transferred to the current owner."


@dataclass(frozen=True)
class WorldAccessChange:
    world_id: uuid.UUID
    target_user_id: uuid.UUID
    changed: bool
    # The membership or use-grant row written or ended (None for a no-op).
    record_id: uuid.UUID | None
    role_code: str | None = None


@dataclass(frozen=True)
class OwnershipTransferResult:
    world_id: uuid.UUID
    previous_owner_user_id: uuid.UUID
    new_owner_user_id: uuid.UUID
    new_owner_membership_id: uuid.UUID | None
    ended_membership_id: uuid.UUID
    retained_membership_id: uuid.UUID | None
    retained_role_code: str | None


def _lock_and_authorize(
    connection: Connection, *, world_id: uuid.UUID, actor_user_id: uuid.UUID, capability: str
) -> None:
    locked = connection.execute(
        text("SELECT 1 FROM core.worlds WHERE world_id = :w FOR UPDATE"), {"w": world_id}
    ).first()
    if locked is None:
        raise WorldNotAuthorizedError(f"world {world_id} does not exist")
    authority = resolve_world_authority(connection, user_id=actor_user_id, world_id=world_id)
    if authority is None or not authority.has_capability(capability):
        raise WorldNotAuthorizedError(f"user {actor_user_id} lacks {capability} on {world_id}")


def _target(connection: Connection, login_name: str) -> ActiveAccount:
    account = find_active_account(connection, login_name=login_name)
    if account is None:
        raise WorldRoleTargetIneligibleError(f"login {login_name!r} is not an active account")
    return account


def _insert_membership(
    connection: Connection,
    *,
    world_id: uuid.UUID,
    user_id: uuid.UUID,
    role_code: str,
    granted_by_user_id: uuid.UUID,
) -> uuid.UUID | None:
    """Open a membership unless the same (world, user, role) is already open."""
    row = connection.execute(
        text("""
            INSERT INTO security.world_memberships
                (world_id, user_id, world_role_id, membership_status_id, granted_by_user_id)
            VALUES (
                :w, :u,
                (SELECT world_role_id FROM security.world_roles WHERE code = :role),
                :status, :granted_by
            )
            ON CONFLICT (world_id, user_id, world_role_id) WHERE ended_at IS NULL DO NOTHING
            RETURNING world_membership_id
        """),
        {
            "w": world_id,
            "u": user_id,
            "role": role_code,
            "status": lookup_id(
                connection, "security", "membership_statuses", "membership_status_id", "active"
            ),
            "granted_by": granted_by_user_id,
        },
    ).first()
    return None if row is None else row.world_membership_id


def _other_open_owners(
    connection: Connection, *, world_id: uuid.UUID, excluding_user_id: uuid.UUID
) -> int:
    return int(
        connection.execute(
            text("""
                SELECT count(DISTINCT wm.user_id)
                FROM security.world_memberships wm
                JOIN security.world_roles wr ON wr.world_role_id = wm.world_role_id
                JOIN security.membership_statuses ms
                  ON ms.membership_status_id = wm.membership_status_id
                WHERE wm.world_id = :w AND wm.ended_at IS NULL AND wr.code = 'world_owner'
                  AND ms.code = 'active' AND ms.is_active AND wm.user_id <> :u
            """),
            {"w": world_id, "u": excluding_user_id},
        ).scalar_one()
    )


def assign_world_role(
    connection: Connection,
    *,
    actor_user_id: uuid.UUID,
    world_id: uuid.UUID,
    login_name: str,
    role_code: str,
) -> WorldAccessChange:
    """Give an active account a world role. Idempotent: a role already held is a
    no-op. `world.share` is required; assigning Owner additionally needs
    `world.transfer`, and the new Owner must hold system GM."""
    if role_code not in WORLD_ROLE_CODES:
        raise ValueError(f"unknown world role code {role_code!r}")
    _lock_and_authorize(
        connection, world_id=world_id, actor_user_id=actor_user_id, capability=WORLD_SHARE
    )
    if role_code == WORLD_OWNER_ROLE:
        _lock_and_authorize(
            connection, world_id=world_id, actor_user_id=actor_user_id, capability=WORLD_TRANSFER
        )
    target = _target(connection, login_name)
    if role_code == WORLD_OWNER_ROLE and not has_system_capability(
        connection, user_id=target.user_id, capability_code=WORLD_ADMINISTER
    ):
        raise TargetRequiresSystemGmError(f"user {target.user_id} lacks world.administer")
    membership_id = _insert_membership(
        connection,
        world_id=world_id,
        user_id=target.user_id,
        role_code=role_code,
        granted_by_user_id=actor_user_id,
    )
    return WorldAccessChange(
        world_id=world_id,
        target_user_id=target.user_id,
        changed=membership_id is not None,
        record_id=membership_id,
        role_code=role_code,
    )


def end_world_role(
    connection: Connection,
    *,
    actor_user_id: uuid.UUID,
    world_id: uuid.UUID,
    world_membership_id: uuid.UUID,
) -> WorldAccessChange:
    """End one open role assignment. Ending an Owner assignment needs
    `world.transfer` and is refused when it would leave the world with no Owner.
    The assignment row is kept as history; attribution is untouched."""
    _lock_and_authorize(
        connection, world_id=world_id, actor_user_id=actor_user_id, capability=WORLD_SHARE
    )
    row = connection.execute(
        text("""
            SELECT wm.user_id, wr.code AS role_code
            FROM security.world_memberships wm
            JOIN security.world_roles wr ON wr.world_role_id = wm.world_role_id
            WHERE wm.world_membership_id = :m AND wm.world_id = :w AND wm.ended_at IS NULL
            FOR UPDATE OF wm
        """),
        {"m": world_membership_id, "w": world_id},
    ).first()
    if row is None:
        raise WorldRoleAssignmentNotFoundError(
            f"no open assignment {world_membership_id} on world {world_id}"
        )
    if row.role_code == WORLD_OWNER_ROLE:
        _lock_and_authorize(
            connection, world_id=world_id, actor_user_id=actor_user_id, capability=WORLD_TRANSFER
        )
        if _other_open_owners(connection, world_id=world_id, excluding_user_id=row.user_id) == 0:
            raise WorldOwnerRequiredError(f"world {world_id} would be left with no owner")
    connection.execute(
        text("""
            UPDATE security.world_memberships
            SET ended_at = now(), ended_by_user_id = :actor
            WHERE world_membership_id = :m
        """),
        {"m": world_membership_id, "actor": actor_user_id},
    )
    return WorldAccessChange(
        world_id=world_id,
        target_user_id=row.user_id,
        changed=True,
        record_id=world_membership_id,
        role_code=str(row.role_code),
    )


def grant_world_use(
    connection: Connection,
    *,
    actor_user_id: uuid.UUID,
    world_id: uuid.UUID,
    login_name: str,
) -> WorldAccessChange:
    """Let an active account host campaigns on the world (nothing else).
    Idempotent."""
    _lock_and_authorize(
        connection, world_id=world_id, actor_user_id=actor_user_id, capability=WORLD_SHARE
    )
    target = _target(connection, login_name)
    row = connection.execute(
        text("""
            INSERT INTO security.world_use_grants (world_id, user_id, granted_by_user_id)
            VALUES (:w, :u, :actor)
            ON CONFLICT (world_id, user_id) WHERE revoked_at IS NULL DO NOTHING
            RETURNING world_use_grant_id
        """),
        {"w": world_id, "u": target.user_id, "actor": actor_user_id},
    ).first()
    return WorldAccessChange(
        world_id=world_id,
        target_user_id=target.user_id,
        changed=row is not None,
        record_id=None if row is None else row.world_use_grant_id,
    )


def revoke_world_use(
    connection: Connection,
    *,
    actor_user_id: uuid.UUID,
    world_id: uuid.UUID,
    world_use_grant_id: uuid.UUID,
) -> WorldAccessChange:
    """Revoke an open use grant. Stops *new* campaigns only; campaigns the holder
    already created are unaffected."""
    _lock_and_authorize(
        connection, world_id=world_id, actor_user_id=actor_user_id, capability=WORLD_SHARE
    )
    row = connection.execute(
        text("""
            UPDATE security.world_use_grants
            SET revoked_at = now(), revoked_by_user_id = :actor
            WHERE world_use_grant_id = :g AND world_id = :w AND revoked_at IS NULL
            RETURNING user_id
        """),
        {"g": world_use_grant_id, "w": world_id, "actor": actor_user_id},
    ).first()
    if row is None:
        raise WorldRoleAssignmentNotFoundError(
            f"no open use grant {world_use_grant_id} on world {world_id}"
        )
    return WorldAccessChange(
        world_id=world_id,
        target_user_id=row.user_id,
        changed=True,
        record_id=world_use_grant_id,
    )


def transfer_world_ownership(
    connection: Connection,
    *,
    actor_user_id: uuid.UUID,
    world_id: uuid.UUID,
    login_name: str,
    retain_previous_owner_as: str | None,
) -> OwnershipTransferResult:
    """Make an active GM account an Owner and end the caller's own Owner
    assignment, optionally keeping them on as Editor, Reviewer or Reader, in one
    transaction. Authorship is untouched. The caller must currently be an Owner
    with `world.transfer`."""
    if retain_previous_owner_as is not None and (
        retain_previous_owner_as not in WORLD_ROLE_CODES
        or retain_previous_owner_as == WORLD_OWNER_ROLE
    ):
        raise ValueError(f"cannot retain as {retain_previous_owner_as!r}")
    _lock_and_authorize(
        connection, world_id=world_id, actor_user_id=actor_user_id, capability=WORLD_TRANSFER
    )
    target = _target(connection, login_name)
    if target.user_id == actor_user_id:
        raise InvalidOwnershipTransferError(f"user {actor_user_id} already owns {world_id}")
    if not has_system_capability(
        connection, user_id=target.user_id, capability_code=WORLD_ADMINISTER
    ):
        raise TargetRequiresSystemGmError(f"user {target.user_id} lacks world.administer")
    new_owner_membership = _insert_membership(
        connection,
        world_id=world_id,
        user_id=target.user_id,
        role_code=WORLD_OWNER_ROLE,
        granted_by_user_id=actor_user_id,
    )
    ended = connection.execute(
        text("""
            UPDATE security.world_memberships wm
            SET ended_at = now(), ended_by_user_id = :actor
            FROM security.world_roles wr
            WHERE wr.world_role_id = wm.world_role_id AND wr.code = 'world_owner'
              AND wm.world_id = :w AND wm.user_id = :actor AND wm.ended_at IS NULL
            RETURNING wm.world_membership_id
        """),
        {"w": world_id, "actor": actor_user_id},
    ).first()
    if ended is None:  # authority came from somewhere other than an Owner row
        raise WorldNotAuthorizedError(f"user {actor_user_id} is not an owner of {world_id}")
    retained_membership: uuid.UUID | None = None
    if retain_previous_owner_as is not None:
        retained_membership = _insert_membership(
            connection,
            world_id=world_id,
            user_id=actor_user_id,
            role_code=retain_previous_owner_as,
            granted_by_user_id=actor_user_id,
        )
    return OwnershipTransferResult(
        world_id=world_id,
        previous_owner_user_id=actor_user_id,
        new_owner_user_id=target.user_id,
        new_owner_membership_id=new_owner_membership,
        ended_membership_id=ended.world_membership_id,
        retained_membership_id=retained_membership,
        retained_role_code=retain_previous_owner_as,
    )

"""Trusted-infrastructure world-membership changes
(docs/adr/0019-world-visibility-and-viewer-role.md).

World memberships have no HTTP route or portal control in the current product
scope: a world's first owner comes from `create_world` (or, for a legacy world,
`claim_unowned_world`), and every later change is an operator action through
`scripts/manage_world_membership.py`. These commands are what that script
calls. Framework-free: each takes a `Connection`, never commits, and returns
the membership rows it opened and closed so the caller can audit each one.

Rules shared by every command here:

- The world row is locked `FOR UPDATE` first — the head of the global lock
  order and the same lock `security.assert_world_retains_owner` takes — so two
  operators changing one world serialize.
- Rows are never deleted or edited in place except to close them
  (`ended_at = now()`): a role change closes the open row and opens a new one,
  so history keeps who held which role when.
- A world is never left without an active `world_owner`. That is pre-checked
  here (a clear `WorldMembershipChangeRefusedError`, nothing written) and is
  also the database's own deferred guarantee (revision 110).
- A new `world_owner` must satisfy the world-creation policy
  (`may_create_worlds`: an active platform administrator or an effective
  built-in `gm`, ADR 0018). Ownership is authoring authority; an operator
  cannot hand it to an account that could not have created the world itself.
  `world_viewer` needs only an active account.
- Nothing here reads or writes campaign memberships. Ending a user's world
  role never touches what their campaign roles let them see.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, text

from dnd_ai.domain.authoring import WorldMembershipChangeRefusedError
from dnd_ai.domain.world_authority import (
    WORLD_OWNER_ROLE,
    WORLD_ROLE_CAPABILITIES,
    WORLD_VIEWER_ROLE,
)
from dnd_ai.queries.world_authority import may_create_worlds


@dataclass(frozen=True)
class WorldMembershipChange:
    """One membership row this command closed or opened."""

    action: str  # "ended" or "created"
    world_membership_id: uuid.UUID
    world_id: uuid.UUID
    user_id: uuid.UUID
    role_code: str


@dataclass(frozen=True)
class _OpenMembership:
    world_membership_id: uuid.UUID
    role_code: str
    is_active: bool


def _lock_world(connection: Connection, world_id: uuid.UUID) -> None:
    found = connection.execute(
        text("SELECT 1 FROM core.worlds WHERE world_id = :w FOR UPDATE"), {"w": world_id}
    ).scalar()
    if found is None:
        raise WorldMembershipChangeRefusedError(f"world {world_id} does not exist")


def _require_active_user(connection: Connection, user_id: uuid.UUID) -> None:
    active = connection.execute(
        text("""
            SELECT 1 FROM security.users u
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = u.lifecycle_status_id
            WHERE u.user_id = :u AND ls.code = 'active'
        """),
        {"u": user_id},
    ).scalar()
    if active is None:
        raise WorldMembershipChangeRefusedError(f"user {user_id} does not exist or is not active")


def _open_membership(
    connection: Connection, *, world_id: uuid.UUID, user_id: uuid.UUID
) -> _OpenMembership | None:
    row = connection.execute(
        text("""
            SELECT wm.world_membership_id, wr.code, (ms.code = 'active' AND ms.is_active) AS active
            FROM security.world_memberships wm
            JOIN security.world_roles wr ON wr.world_role_id = wm.world_role_id
            JOIN security.membership_statuses ms
              ON ms.membership_status_id = wm.membership_status_id
            WHERE wm.world_id = :w AND wm.user_id = :u AND wm.ended_at IS NULL
        """),
        {"w": world_id, "u": user_id},
    ).one_or_none()
    if row is None:
        return None
    return _OpenMembership(
        world_membership_id=row.world_membership_id,
        role_code=str(row.code),
        is_active=bool(row.active),
    )


def _other_active_owner_exists(
    connection: Connection, *, world_id: uuid.UUID, excluding_user_id: uuid.UUID
) -> bool:
    return bool(
        connection.execute(
            text("""
                SELECT EXISTS (
                    SELECT 1
                    FROM security.world_memberships wm
                    JOIN security.membership_statuses ms
                      ON ms.membership_status_id = wm.membership_status_id
                    JOIN security.world_roles wr ON wr.world_role_id = wm.world_role_id
                    WHERE wm.world_id = :w
                      AND wm.user_id <> :u
                      AND wm.ended_at IS NULL
                      AND ms.code = 'active' AND ms.is_active
                      AND wr.code = :owner AND wr.is_active
                )
            """),
            {"w": world_id, "u": excluding_user_id, "owner": WORLD_OWNER_ROLE},
        ).scalar()
    )


def _close(
    connection: Connection, *, world_id: uuid.UUID, user_id: uuid.UUID, open_row: _OpenMembership
) -> WorldMembershipChange:
    connection.execute(
        text(
            "UPDATE security.world_memberships SET ended_at = now() WHERE world_membership_id = :m"
        ),
        {"m": open_row.world_membership_id},
    )
    return WorldMembershipChange(
        action="ended",
        world_membership_id=open_row.world_membership_id,
        world_id=world_id,
        user_id=user_id,
        role_code=open_row.role_code,
    )


def _open(
    connection: Connection, *, world_id: uuid.UUID, user_id: uuid.UUID, role_code: str
) -> WorldMembershipChange:
    membership_id = connection.execute(
        text("""
            INSERT INTO security.world_memberships
                (world_id, user_id, world_role_id, membership_status_id)
            VALUES (
                :w, :u,
                (SELECT world_role_id FROM security.world_roles WHERE code = :role),
                (SELECT membership_status_id FROM security.membership_statuses
                 WHERE code = 'active')
            )
            RETURNING world_membership_id
        """),
        {"w": world_id, "u": user_id, "role": role_code},
    ).scalar()
    assert isinstance(membership_id, uuid.UUID)
    return WorldMembershipChange(
        action="created",
        world_membership_id=membership_id,
        world_id=world_id,
        user_id=user_id,
        role_code=role_code,
    )


def _require_known_role(connection: Connection, role_code: str) -> None:
    if role_code not in WORLD_ROLE_CAPABILITIES:
        raise WorldMembershipChangeRefusedError(f"unknown world role {role_code!r}")
    active = connection.execute(
        text("SELECT 1 FROM security.world_roles WHERE code = :c AND is_active"),
        {"c": role_code},
    ).scalar()
    if active is None:
        raise WorldMembershipChangeRefusedError(f"world role {role_code!r} is not active")


def _set_role(
    connection: Connection, *, world_id: uuid.UUID, user_id: uuid.UUID, role_code: str
) -> list[WorldMembershipChange]:
    """Give `user_id` exactly `role_code` on an already-locked world. A no-op
    (empty list) when that is already their open, active role; an open row in
    another status (e.g. suspended) is replaced, since it authorizes nothing."""
    _require_known_role(connection, role_code)
    _require_active_user(connection, user_id)
    if role_code == WORLD_OWNER_ROLE and not may_create_worlds(connection, user_id=user_id):
        raise WorldMembershipChangeRefusedError(
            f"user {user_id} may not own worlds: not an active platform administrator "
            "or effective built-in gm (docs/adr/0018-world-creation-eligibility.md)"
        )
    current = _open_membership(connection, world_id=world_id, user_id=user_id)
    if current is not None and current.role_code == role_code and current.is_active:
        return []
    if (
        current is not None
        and current.role_code == WORLD_OWNER_ROLE
        and not _other_active_owner_exists(connection, world_id=world_id, excluding_user_id=user_id)
    ):
        raise WorldMembershipChangeRefusedError(
            f"world {world_id} would be left with no active world_owner; transfer ownership first"
        )
    changes: list[WorldMembershipChange] = []
    if current is not None:
        changes.append(_close(connection, world_id=world_id, user_id=user_id, open_row=current))
    changes.append(_open(connection, world_id=world_id, user_id=user_id, role_code=role_code))
    return changes


def set_world_role(
    connection: Connection, *, world_id: uuid.UUID, user_id: uuid.UUID, role_code: str
) -> list[WorldMembershipChange]:
    """Grant `role_code` on `world_id` to `user_id`, replacing any other open
    role they hold there (close + open). Refuses an ineligible new owner and
    demoting the world's last active owner."""
    _lock_world(connection, world_id)
    return _set_role(connection, world_id=world_id, user_id=user_id, role_code=role_code)


def end_world_membership(
    connection: Connection, *, world_id: uuid.UUID, user_id: uuid.UUID
) -> list[WorldMembershipChange]:
    """Close `user_id`'s open membership on `world_id`. Refuses when there is
    none, and when it is the world's last active owner."""
    _lock_world(connection, world_id)
    current = _open_membership(connection, world_id=world_id, user_id=user_id)
    if current is None:
        raise WorldMembershipChangeRefusedError(
            f"user {user_id} has no open membership on world {world_id}"
        )
    if current.role_code == WORLD_OWNER_ROLE and not _other_active_owner_exists(
        connection, world_id=world_id, excluding_user_id=user_id
    ):
        raise WorldMembershipChangeRefusedError(
            f"world {world_id} would be left with no active world_owner; transfer ownership first"
        )
    return [_close(connection, world_id=world_id, user_id=user_id, open_row=current)]


def transfer_world_ownership(
    connection: Connection,
    *,
    world_id: uuid.UUID,
    from_user_id: uuid.UUID,
    to_user_id: uuid.UUID,
    retain_viewer: bool,
) -> list[WorldMembershipChange]:
    """Make `to_user_id` an owner of `world_id`, then remove `from_user_id`'s
    ownership — leaving them `world_viewer` when `retain_viewer`, otherwise
    no world role at all. One transaction: the world is never ownerless and
    a refusal writes nothing. `from_user_id` must currently own the world."""
    if from_user_id == to_user_id:
        raise WorldMembershipChangeRefusedError("ownership cannot be transferred to the same user")
    _lock_world(connection, world_id)
    current = _open_membership(connection, world_id=world_id, user_id=from_user_id)
    if current is None or current.role_code != WORLD_OWNER_ROLE:
        raise WorldMembershipChangeRefusedError(
            f"user {from_user_id} does not own world {world_id}"
        )
    changes = _set_role(
        connection, world_id=world_id, user_id=to_user_id, role_code=WORLD_OWNER_ROLE
    )
    if retain_viewer:
        changes += _set_role(
            connection, world_id=world_id, user_id=from_user_id, role_code=WORLD_VIEWER_ROLE
        )
    else:
        changes.append(
            _close(connection, world_id=world_id, user_id=from_user_id, open_row=current)
        )
    return changes

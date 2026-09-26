"""World ownership scope commands — establishing and maintaining
`security.ownership_scopes` membership (ADR 0014,
docs/architecture/DATABASE_MODEL.md §19.9).

Deliberately narrow. This module does **not** include a `create_world`
command — worlds are still created by raw insert (migrations, the dev-data
script, test factories) until the broader missing-authoring-surface work
(`docs/PRODUCT_DIRECTION.md` §9) is scheduled. It also has no API route or
portal surface: wiring these commands to HTTP/UI is deferred so this change
stays a schema-and-command-layer foundation, not a new access-management
feature (see ADR 0014's "Explicitly not decided or built by this change").

Because no API route exists yet, each command here writes its own
`audit.change_log` row directly, on the same connection/transaction as its
other writes — mirroring `dnd_ai.api.audit.record_change_log`'s INSERT
shape and its own contract ("call once, after the command's own writes and
before the route returns, on the same connection/transaction the command
ran on") without importing from the `api` package, which would invert this
codebase's layering (`api` depends on `commands`, never the reverse). If an
API route for these commands is added later, it should call
`dnd_ai.api.audit.record_change_log` itself and this module's own audit
write should be removed to avoid a double-audit row — see that module's
docstring for the shared contract.

Final-owner invariant: `remove_ownership_scope_member` acquires a
scope-scoped `pg_advisory_xact_lock` before checking whether the
membership being removed is the scope's last active `owner`, mirroring
`dnd_ai.commands.local_auth`'s `_PLATFORM_ADMINISTRATOR_LIFECYCLE_LOCK_KEY`
pattern for the analogous "never leave zero active platform
administrators" invariant. This is deliberately lighter than
`security.campaign_has_access_manager()`'s `DEFERRABLE INITIALLY DEFERRED`
constraint-trigger machinery (migration `080_security_identity_and_access`)
— that heavier mechanism exists because a campaign's owner/access-manager
invariant must hold against direct-SQL or multi-statement mutation paths
that don't go through one command; an ownership scope has no such path yet
(no API, no UI, exactly these three commands), so an application-layer
check is sufficient today. See ADR 0014 for the full reasoning."""

import json
import uuid
from dataclasses import dataclass

from sqlalchemy import Connection, text

from dnd_ai.commands._shared import lookup_id
from dnd_ai.domain.errors import DomainAuthorizationError

_ACTIVE_LIFECYCLE_STATUS_CODE = "active"
_ACTIVE_MEMBERSHIP_STATUS_CODE = "active"
_OWNER_ROLE_CODE = "owner"

_CREATE_OWNERSHIP_SCOPE_COMMAND_NAME = "create_ownership_scope"
_ADD_OWNERSHIP_SCOPE_MEMBER_COMMAND_NAME = "add_ownership_scope_member"
_REMOVE_OWNERSHIP_SCOPE_MEMBER_COMMAND_NAME = "remove_ownership_scope_member"
_CREATED_CHANGE_ACTION = "created"
_REMOVED_CHANGE_ACTION = "archived"


class OwnershipScopeMembershipNotFoundError(DomainAuthorizationError):
    """Raised when a supplied `ownership_scope_membership_id` does not
    resolve to an open (`ended_at IS NULL`) row at all. Inherits
    `DomainAuthorizationError`'s fixed-404 contract deliberately — the
    supplied id is available via `str(self)` for local debugging only,
    never in `safe_message`."""


class LastActiveOwnerError(ValueError):
    """Raised by `remove_ownership_scope_member` when removing the named
    membership would leave zero active `owner`-role memberships in its
    ownership scope. A caller must add or promote a replacement owner
    first, or use a future transfer command (not implemented — ADR 0014)."""


def _record_ownership_audit(
    connection: Connection,
    *,
    change_action_code: str,
    record_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    command_name: str,
    changed_fields: dict[str, object] | None = None,
) -> None:
    """Writes one `audit.change_log` row for an ownership-scope command.
    See this module's own docstring for why this happens here rather than
    via `dnd_ai.api.audit.record_change_log` at a route layer. `world_id`
    is always `NULL`: an ownership scope may administer more than one
    world, so no single `world_id` describes the change."""
    change_action_id = lookup_id(
        connection, "audit", "change_actions", "change_action_id", change_action_code
    )
    connection.execute(
        text("""
            INSERT INTO audit.change_log
                (change_action_id, schema_name, table_name, record_id, entity_id, world_id,
                 actor_user_id, correlation_id, command_name, event_id, changed_fields)
            VALUES
                (:action, 'security', 'ownership_scope_memberships', :record, NULL, NULL,
                 :actor, NULL, :command, NULL, :changed_fields)
        """),
        {
            "action": change_action_id,
            "record": record_id,
            "actor": actor_user_id,
            "command": command_name,
            "changed_fields": json.dumps(changed_fields) if changed_fields is not None else None,
        },
    )


@dataclass(frozen=True)
class CreateOwnershipScopeResult:
    ownership_scope_id: uuid.UUID
    ownership_scope_membership_id: uuid.UUID


def create_ownership_scope(
    connection: Connection, *, name: str, owner_user_id: uuid.UUID
) -> CreateOwnershipScopeResult:
    """Creates `security.ownership_scopes` plus the creator's own `owner`
    membership, atomically — mirroring `dnd_ai.commands.campaigns.
    create_campaign`'s "never a two-step create-then-add-yourself sequence"
    shape, so a failure between the two writes can never leave an active
    scope with no owner."""
    active_lifecycle_status_id = lookup_id(
        connection,
        "core",
        "lifecycle_statuses",
        "lifecycle_status_id",
        _ACTIVE_LIFECYCLE_STATUS_CODE,
    )
    ownership_scope_id = connection.execute(
        text("""
            INSERT INTO security.ownership_scopes (name, lifecycle_status_id)
            VALUES (:name, :status)
            RETURNING ownership_scope_id
        """),
        {"name": name, "status": active_lifecycle_status_id},
    ).scalar()
    assert isinstance(ownership_scope_id, uuid.UUID)

    owner_role_id = lookup_id(
        connection, "security", "ownership_scope_roles", "ownership_scope_role_id", _OWNER_ROLE_CODE
    )
    active_membership_status_id = lookup_id(
        connection,
        "security",
        "membership_statuses",
        "membership_status_id",
        _ACTIVE_MEMBERSHIP_STATUS_CODE,
    )
    ownership_scope_membership_id = connection.execute(
        text("""
            INSERT INTO security.ownership_scope_memberships
                (ownership_scope_id, user_id, ownership_scope_role_id, membership_status_id,
                 joined_at)
            VALUES (:scope, :user, :role, :status, now())
            RETURNING ownership_scope_membership_id
        """),
        {
            "scope": ownership_scope_id,
            "user": owner_user_id,
            "role": owner_role_id,
            "status": active_membership_status_id,
        },
    ).scalar()
    assert isinstance(ownership_scope_membership_id, uuid.UUID)

    _record_ownership_audit(
        connection,
        change_action_code=_CREATED_CHANGE_ACTION,
        record_id=ownership_scope_membership_id,
        actor_user_id=owner_user_id,
        command_name=_CREATE_OWNERSHIP_SCOPE_COMMAND_NAME,
        changed_fields={"ownership_scope_id": str(ownership_scope_id), "role": _OWNER_ROLE_CODE},
    )

    return CreateOwnershipScopeResult(
        ownership_scope_id=ownership_scope_id,
        ownership_scope_membership_id=ownership_scope_membership_id,
    )


@dataclass(frozen=True)
class AddOwnershipScopeMemberResult:
    ownership_scope_membership_id: uuid.UUID


def add_ownership_scope_member(
    connection: Connection,
    *,
    ownership_scope_id: uuid.UUID,
    user_id: uuid.UUID,
    role_code: str,
    actor_user_id: uuid.UUID,
) -> AddOwnershipScopeMemberResult:
    """Adds `user_id` to `ownership_scope_id` with `role_code` (`owner` or
    `member`). Does not itself require `actor_user_id` to already be a
    member of the scope — the same way `scripts/claim_legacy_ownership_
    scope.py` uses this to seed the very first owner of a scope that
    otherwise has none (ADR 0014's "Existing-data migration"). A future
    API layer wiring this to a route is responsible for its own
    authorization check before calling this command."""
    role_id = lookup_id(
        connection, "security", "ownership_scope_roles", "ownership_scope_role_id", role_code
    )
    active_membership_status_id = lookup_id(
        connection,
        "security",
        "membership_statuses",
        "membership_status_id",
        _ACTIVE_MEMBERSHIP_STATUS_CODE,
    )
    ownership_scope_membership_id = connection.execute(
        text("""
            INSERT INTO security.ownership_scope_memberships
                (ownership_scope_id, user_id, ownership_scope_role_id, membership_status_id,
                 joined_at)
            VALUES (:scope, :user, :role, :status, now())
            RETURNING ownership_scope_membership_id
        """),
        {
            "scope": ownership_scope_id,
            "user": user_id,
            "role": role_id,
            "status": active_membership_status_id,
        },
    ).scalar()
    assert isinstance(ownership_scope_membership_id, uuid.UUID)

    _record_ownership_audit(
        connection,
        change_action_code=_CREATED_CHANGE_ACTION,
        record_id=ownership_scope_membership_id,
        actor_user_id=actor_user_id,
        command_name=_ADD_OWNERSHIP_SCOPE_MEMBER_COMMAND_NAME,
        changed_fields={"ownership_scope_id": str(ownership_scope_id), "role": role_code},
    )

    return AddOwnershipScopeMemberResult(
        ownership_scope_membership_id=ownership_scope_membership_id
    )


def _count_active_owners(connection: Connection, *, ownership_scope_id: uuid.UUID) -> int:
    value = connection.execute(
        text("""
            SELECT count(*)
            FROM security.ownership_scope_memberships osm
            JOIN security.ownership_scope_roles r
                ON r.ownership_scope_role_id = osm.ownership_scope_role_id
            JOIN security.membership_statuses ms
                ON ms.membership_status_id = osm.membership_status_id
            WHERE osm.ownership_scope_id = :scope
              AND osm.ended_at IS NULL
              AND ms.code = 'active'
              AND r.code = 'owner'
        """),
        {"scope": ownership_scope_id},
    ).scalar()
    assert isinstance(value, int)
    return value


def remove_ownership_scope_member(
    connection: Connection,
    *,
    ownership_scope_membership_id: uuid.UUID,
    actor_user_id: uuid.UUID,
) -> None:
    """Closes (`ended_at = now()`) the named membership, enforcing that the
    scope always keeps at least one active `owner`. See this module's own
    docstring for the advisory-lock pattern this follows and why a lighter
    mechanism than the campaign-owner retention trigger is sufficient here.

    Acquires the scope-scoped advisory lock *before* reading the target
    row, so two concurrent removal attempts against owners of the same
    scope serialize correctly under PostgreSQL's default READ COMMITTED
    isolation — the second call's own count check always reflects the
    first call's fully-committed (or fully-rolled-back) effect."""
    # ownership_scope_id is immutable for a membership row, so an unlocked
    # read of it alone (to know which advisory-lock key to acquire) cannot
    # go stale before the locked, authoritative read below.
    unlocked_scope_id = connection.execute(
        text(
            "SELECT ownership_scope_id FROM security.ownership_scope_memberships "
            "WHERE ownership_scope_membership_id = :membership"
        ),
        {"membership": ownership_scope_membership_id},
    ).scalar()
    if unlocked_scope_id is None:
        raise OwnershipScopeMembershipNotFoundError(
            f"ownership scope membership {ownership_scope_membership_id} does not exist"
        )

    connection.execute(
        text("SELECT pg_advisory_xact_lock(hashtext('ownership_scope:' || :scope::text))"),
        {"scope": str(unlocked_scope_id)},
    )

    row = (
        connection.execute(
            text("""
                SELECT osm.ownership_scope_id, osm.ended_at, r.code AS role_code
                FROM security.ownership_scope_memberships osm
                JOIN security.ownership_scope_roles r
                    ON r.ownership_scope_role_id = osm.ownership_scope_role_id
                WHERE osm.ownership_scope_membership_id = :membership
                FOR UPDATE OF osm
            """),
            {"membership": ownership_scope_membership_id},
        )
        .mappings()
        .one()
    )
    if row["ended_at"] is not None:
        raise OwnershipScopeMembershipNotFoundError(
            f"ownership scope membership {ownership_scope_membership_id} is not open"
        )
    ownership_scope_id = row["ownership_scope_id"]

    if (
        row["role_code"] == _OWNER_ROLE_CODE
        and _count_active_owners(connection, ownership_scope_id=ownership_scope_id) <= 1
    ):
        raise LastActiveOwnerError(
            f"removing membership {ownership_scope_membership_id} would leave ownership "
            f"scope {ownership_scope_id} with zero active owners"
        )

    connection.execute(
        text(
            "UPDATE security.ownership_scope_memberships SET ended_at = now() "
            "WHERE ownership_scope_membership_id = :membership"
        ),
        {"membership": ownership_scope_membership_id},
    )

    _record_ownership_audit(
        connection,
        change_action_code=_REMOVED_CHANGE_ACTION,
        record_id=ownership_scope_membership_id,
        actor_user_id=actor_user_id,
        command_name=_REMOVE_OWNERSHIP_SCOPE_MEMBER_COMMAND_NAME,
    )

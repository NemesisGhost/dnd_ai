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

Final-owner invariant: enforced at **two** independent layers, deliberately
redundant. `remove_ownership_scope_member` acquires a scope-scoped
`pg_advisory_xact_lock` before checking whether the membership being
removed is the scope's last active `owner`, mirroring `dnd_ai.commands.
local_auth`'s `_PLATFORM_ADMINISTRATOR_LIFECYCLE_LOCK_KEY` pattern. As of
migration `108_ownership_scope_integrity_guards`, `security.
ownership_scope_memberships` also carries a `DEFERRABLE INITIALLY DEFERRED`
constraint trigger (`security.enforce_ownership_scope_memberships_retain_
owner()`, mirroring `security.campaign_has_access_manager()`'s identical
campaign-owner retention shape) that rejects the same violation at the
database boundary regardless of caller — this command's own advisory-lock
check exists to fail with a specific, catchable `LastActiveOwnerError`
*before* hitting the database constraint's generic integrity error, not
because the database check alone would be insufficient.

**Ownership-management authorization policy (this module's correction
pass).** `add_ownership_scope_member` and `remove_ownership_scope_member`
both require `actor_user_id` to already hold an active, non-archived
`owner`-role membership of the *target* ownership scope — the only role
this module's own documented model (ADR 0014, `security.
ownership_scope_roles`: `owner`/`member`) treats as authorized to manage
scope membership; a `member`-role holder may not add or remove anyone,
matching how a `member` is a participant in the scope, not its
administrator. This check is independent of, and never satisfied by,
campaign roles (`security.roles`/`.campaign_memberships` — a campaign GM
has no bearing on world-ownership administration) or `security.users.
is_platform_administrator` (a platform administrator is never silently
treated as authorized for any specific ownership scope). An unauthorized
caller and a caller naming a nonexistent target both raise the same
`OwnershipScopeNotAuthorizedError` with the same fixed `safe_message`, so
neither response discloses which case occurred (`docs/architecture/
DATABASE_MODEL.md` §19.7's non-disclosure principle, applied here for the
first time to this schema). Authorization is checked *after* acquiring the
target scope's advisory lock, so a concurrent revocation of the actor's own
authority cannot race a call that read stale "still authorized" state.

`create_ownership_scope` requires no such check — like `dnd_ai.commands.
campaigns.create_campaign`, it is the one command in this module any
authenticated user may call unconditionally, since a to-be-created scope
has no existing owner to authorize against.

`claim_unclaimed_ownership_scope` is the one narrow, unauthorized exception
— a **DB-direct-only bootstrap path** for a scope that has **zero**
membership rows of any status (the shape migration `107_world_ownership_
scope`'s legacy scope, and only that shape, is in immediately after
upgrading a populated database — ADR 0014's "Existing-data migration").
It refuses unconditionally the moment the target scope has even one
membership row, active or not, so it can never be used to bypass the
ordinary authorization policy above for a scope anyone has ever
administered — it is not a general mutation bypass, only a one-time claim
of a scope nobody has ever claimed. `scripts/claim_legacy_ownership_
scope.py` is its only intended caller, run by an operator directly against
the database, exactly like `dnd_ai.commands.local_auth.
bootstrap_initial_admin`'s identical "never over HTTP, fails closed once
state already exists" posture."""

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
_CLAIM_UNCLAIMED_OWNERSHIP_SCOPE_COMMAND_NAME = "claim_unclaimed_ownership_scope"
_CREATED_CHANGE_ACTION = "created"
_REMOVED_CHANGE_ACTION = "archived"


class OwnershipScopeNotAuthorizedError(DomainAuthorizationError):
    """Raised by `add_ownership_scope_member`/`remove_ownership_scope_member`
    when `actor_user_id` does not hold an active, non-archived `owner`-role
    membership of the target ownership scope — including when the target
    scope does not exist at all. Deliberately left at
    `DomainAuthorizationError`'s own inherited `safe_message` rather than
    defining a more specific one — see this module's own docstring,
    "Ownership-management authorization policy": an unauthorized actor and
    a nonexistent target must be indistinguishable from outside this
    module, and `OwnershipScopeMembershipNotFoundError` below relies on
    sharing that exact same inherited string too."""


class OwnershipScopeMembershipNotFoundError(DomainAuthorizationError):
    """Raised when a supplied `ownership_scope_membership_id` does not
    resolve to an open (`ended_at IS NULL`) row at all. Inherits
    `DomainAuthorizationError`'s fixed-404 contract deliberately — the
    supplied id is available via `str(self)` for local debugging only,
    never in `safe_message`. Left at the same inherited `safe_message` as
    `OwnershipScopeNotAuthorizedError` for the identical non-disclosure
    reason — a missing target and an unauthorized actor must look
    identical from outside this module."""


class LastActiveOwnerError(ValueError):
    """Raised by `remove_ownership_scope_member` when removing the named
    membership would leave zero active `owner`-role memberships in its
    ownership scope. A caller must add or promote a replacement owner
    first, or use a future transfer command (not implemented — ADR 0014).
    `security.enforce_ownership_scope_memberships_retain_owner()` (migration
    `108_ownership_scope_integrity_guards`) enforces the identical invariant
    at the database boundary as a second, independent layer — this
    exception exists so a normal call gets a specific, catchable error
    before ever reaching that generic constraint violation."""


class AlreadyClaimedOwnershipScopeError(ValueError):
    """Raised by `claim_unclaimed_ownership_scope` when the target scope
    already has at least one membership row, of any status — including a
    revoked one. That scope has already been administered by someone at
    some point and must go through the ordinary authorized
    `add_ownership_scope_member` path (by an existing active owner) or a
    future transfer command, never this one-time bootstrap path again."""


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


def _lock_ownership_scope(connection: Connection, ownership_scope_id: uuid.UUID) -> None:
    """Acquires a transaction-scoped advisory lock keyed on
    `ownership_scope_id`, serializing every concurrent authorization check
    and mutation against the same scope's membership rows under
    PostgreSQL's default READ COMMITTED isolation. Call this *before*
    `_authorize_ownership_scope_owner` — otherwise a concurrent revocation
    of the actor's own authority could commit between an unlocked
    authorization read and this call's own mutation."""
    connection.execute(
        text("SELECT pg_advisory_xact_lock(hashtext('ownership_scope:' || :scope))"),
        {"scope": str(ownership_scope_id)},
    )


def _authorize_ownership_scope_owner(
    connection: Connection, *, ownership_scope_id: uuid.UUID, actor_user_id: uuid.UUID
) -> None:
    """Raises `OwnershipScopeNotAuthorizedError` unless `actor_user_id` holds
    an active, non-archived `owner`-role membership of `ownership_scope_id`
    — see this module's own docstring, "Ownership-management authorization
    policy". Call only while holding `ownership_scope_id`'s advisory lock
    (`_lock_ownership_scope`), so the read this performs cannot go stale
    before the caller's own mutation."""
    is_authorized_owner = connection.execute(
        text("""
            SELECT EXISTS (
                SELECT 1
                FROM security.ownership_scope_memberships osm
                JOIN security.ownership_scopes os
                    ON os.ownership_scope_id = osm.ownership_scope_id
                JOIN core.lifecycle_statuses scope_ls
                    ON scope_ls.lifecycle_status_id = os.lifecycle_status_id
                JOIN security.ownership_scope_roles r
                    ON r.ownership_scope_role_id = osm.ownership_scope_role_id
                JOIN security.membership_statuses ms
                    ON ms.membership_status_id = osm.membership_status_id
                WHERE osm.ownership_scope_id = :scope
                  AND osm.user_id = :actor
                  AND osm.ended_at IS NULL
                  AND scope_ls.code = 'active'
                  AND ms.code = 'active'
                  AND ms.is_active
                  AND r.code = 'owner'
                  AND r.is_active
            )
        """),
        {"scope": ownership_scope_id, "actor": actor_user_id},
    ).scalar()
    if not is_authorized_owner:
        raise OwnershipScopeNotAuthorizedError(
            f"user {actor_user_id} is not an authorized owner of ownership scope "
            f"{ownership_scope_id}"
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
    `member`) — requires `actor_user_id` to already hold an active
    `owner`-role membership of `ownership_scope_id` (see this module's own
    docstring, "Ownership-management authorization policy"). Seeding the
    very first owner of a scope that has none is `claim_unclaimed_
    ownership_scope`'s job, not this function's — this function always
    requires an already-authorized actor."""
    _lock_ownership_scope(connection, ownership_scope_id)
    _authorize_ownership_scope_owner(
        connection, ownership_scope_id=ownership_scope_id, actor_user_id=actor_user_id
    )

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
    """Closes (`ended_at = now()`) the named membership — requires
    `actor_user_id` to already hold an active `owner`-role membership of
    the *target's* ownership scope (see this module's own docstring,
    "Ownership-management authorization policy") — and enforces that the
    scope always keeps at least one active `owner`. See this module's own
    docstring for the advisory-lock pattern this follows and why a lighter
    mechanism than the campaign-owner retention trigger's database-level
    equivalent is still useful here.

    Acquires the scope-scoped advisory lock *before* authorizing or reading
    the target row, so two concurrent removal attempts against owners of
    the same scope — and a concurrent revocation of the actor's own
    authority — serialize correctly under PostgreSQL's default READ
    COMMITTED isolation: the second call's own checks always reflect the
    first call's fully-committed (or fully-rolled-back) effect."""
    # ownership_scope_id is immutable for a membership row (enforced at the
    # database boundary by migration 108_ownership_scope_integrity_guards),
    # so an unlocked read of it alone (to know which advisory-lock key to
    # acquire) cannot go stale before the locked, authoritative read below.
    # Deliberately not yet an authorization decision: a nonexistent target
    # and an unauthorized actor must raise the identical exception (see
    # OwnershipScopeNotAuthorizedError's own docstring), so this by itself
    # only decides which advisory lock to take, and both paths converge on
    # the same error type immediately below.
    unlocked_scope_id = connection.execute(
        text(
            "SELECT ownership_scope_id FROM security.ownership_scope_memberships "
            "WHERE ownership_scope_membership_id = :membership"
        ),
        {"membership": ownership_scope_membership_id},
    ).scalar()
    if unlocked_scope_id is None:
        raise OwnershipScopeNotAuthorizedError(
            f"ownership scope membership {ownership_scope_membership_id} does not exist"
        )

    _lock_ownership_scope(connection, unlocked_scope_id)
    _authorize_ownership_scope_owner(
        connection, ownership_scope_id=unlocked_scope_id, actor_user_id=actor_user_id
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


def claim_unclaimed_ownership_scope(
    connection: Connection, *, ownership_scope_id: uuid.UUID, user_id: uuid.UUID
) -> AddOwnershipScopeMemberResult:
    """DB-direct-only bootstrap path: adds `user_id` as `owner` of
    `ownership_scope_id`, **without** authorizing `actor_user_id` against
    it, but only when the scope currently has **zero** membership rows of
    any status. See this module's own docstring, "Ownership-management
    authorization policy", for why this is safe: a scope with zero
    membership rows has never been administered by anyone, so there is no
    existing authority for an ordinary caller to hold or lack, and this
    function can never be used against a scope that has ever had even one
    (including a since-revoked) membership row.

    `scripts/claim_legacy_ownership_scope.py` is this function's only
    intended caller. Not wired to any API route or portal surface — adding
    one would need its own, separate authorization design (likely
    `is_platform_administrator`-gated), which ADR 0014 explicitly defers."""
    _lock_ownership_scope(connection, ownership_scope_id)

    existing_membership_count = connection.execute(
        text(
            "SELECT count(*) FROM security.ownership_scope_memberships "
            "WHERE ownership_scope_id = :scope"
        ),
        {"scope": ownership_scope_id},
    ).scalar()
    if existing_membership_count:
        raise AlreadyClaimedOwnershipScopeError(
            f"ownership scope {ownership_scope_id} already has {existing_membership_count} "
            "membership row(s) and cannot be claimed through this bootstrap path"
        )

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
            "user": user_id,
            "role": owner_role_id,
            "status": active_membership_status_id,
        },
    ).scalar()
    assert isinstance(ownership_scope_membership_id, uuid.UUID)

    _record_ownership_audit(
        connection,
        change_action_code=_CREATED_CHANGE_ACTION,
        record_id=ownership_scope_membership_id,
        actor_user_id=user_id,
        command_name=_CLAIM_UNCLAIMED_OWNERSHIP_SCOPE_COMMAND_NAME,
        changed_fields={"ownership_scope_id": str(ownership_scope_id), "role": _OWNER_ROLE_CODE},
    )

    return AddOwnershipScopeMemberResult(
        ownership_scope_membership_id=ownership_scope_membership_id
    )

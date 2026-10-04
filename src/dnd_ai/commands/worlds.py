"""World authoring commands (Phase 14, docs/adr/0014-world-authoring-authority.md).

`create_world`, `update_world`, `archive_world`, `restore_world`, and the
trusted-infrastructure-only `claim_unowned_world`. Framework-free: each takes
a `Connection`, never commits (the request transaction does), and raises
domain errors. Routes own idempotency and audit (docs/architecture/
SYSTEM_ARCHITECTURE.md §5.3, "Authoring command conventions").

Every mutating command here:

1. locks the world row `FOR UPDATE` (the head of the global lock order,
   SYSTEM_ARCHITECTURE §7.1);
2. **re-resolves the caller's world authority under that lock** — nothing
   trusts the route's earlier lookup — and folds "no such world", "no
   authority", and "not enough capability" into one non-disclosing
   `WorldNotAuthorizedError`;
3. compares `expected_row_version` (`StaleWriteError` on mismatch), *before*
   any no-op detection, so a stale caller is told so even when nothing would
   change;
4. only then checks state preconditions and writes.

`create_world` makes the creator the first `world_owner` and creates the
world's **primary timeline** in the same transaction (a world without a
timeline cannot host a campaign). The slug is server-generated: client-chosen
global slugs would let any user probe for other users' worlds, so a collision
is resolved silently with a random suffix and is never reported.
"""

import secrets
import uuid
from dataclasses import dataclass, field

from sqlalchemy import Connection, text

from dnd_ai.domain.authoring import (
    RulesetNotAvailableError,
    StaleWriteError,
    WorldAlreadyClaimedError,
    WorldNotAuthorizedError,
    normalize_description,
    normalize_name,
    normalize_reason,
    slugify,
)
from dnd_ai.domain.authoring_policy import (
    WORLD_ARCHIVE,
    WORLD_RESTORE,
    WORLD_UPDATE,
    raise_for_reason,
    world_blocked_reason,
)
from dnd_ai.domain.world_authority import (
    WORLD_MANAGE,
    WORLD_OWNER_ROLE,
    WorldAuthority,
)
from dnd_ai.queries.world_authority import resolve_world_authority
from dnd_ai.queries.worlds import world_has_blocking_campaigns

from ._shared import lifecycle_code, lookup_id
from .timelines import insert_root_timeline

MAX_ALLOWED_RULESETS = 10
_SLUG_ATTEMPTS = 8


@dataclass(frozen=True)
class CreateWorldResult:
    world_id: uuid.UUID
    primary_timeline_id: uuid.UUID
    world_membership_id: uuid.UUID
    row_version: int
    timeline_row_version: int


@dataclass(frozen=True)
class WorldMutationResult:
    world_id: uuid.UUID
    row_version: int
    lifecycle_status: str
    changed: bool
    previous_lifecycle_status: str | None = None
    changed_fields: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ClaimWorldResult:
    world_id: uuid.UUID
    user_id: uuid.UUID
    world_membership_id: uuid.UUID


def _validated_rulesets(
    connection: Connection, *, ruleset_ids: list[uuid.UUID], default_ruleset_id: uuid.UUID
) -> list[uuid.UUID]:
    unique = list(dict.fromkeys(ruleset_ids))
    if not unique or len(unique) > MAX_ALLOWED_RULESETS or len(unique) != len(ruleset_ids):
        raise RulesetNotAvailableError("ruleset selection must be 1-10 unique rulesets")
    if default_ruleset_id not in unique:
        raise RulesetNotAvailableError("default ruleset must be one of the selected rulesets")
    usable = connection.execute(
        text("""
            SELECT count(*) FROM rules.rulesets r
            JOIN core.canon_statuses cs ON cs.canon_status_id = r.canon_status_id
            WHERE r.ruleset_id = ANY(:ids)
              AND cs.code = 'canon'
              AND EXISTS (SELECT 1 FROM rules.ruleset_versions rv
                          WHERE rv.ruleset_id = r.ruleset_id AND rv.is_current)
        """),
        {"ids": unique},
    ).scalar()
    if usable != len(unique):
        raise RulesetNotAvailableError(
            "a selected ruleset is unknown, not canon, or has no version"
        )
    return unique


def _insert_world_with_unique_slug(
    connection: Connection, *, name: str, description: str | None, lifecycle_status_id: uuid.UUID
) -> uuid.UUID:
    """Insert the world, resolving a slug collision with a random suffix.
    `ON CONFLICT DO NOTHING RETURNING` keeps a collision from aborting the
    transaction, and the bounded loop keeps it from spinning."""
    base = slugify(name)
    for attempt in range(_SLUG_ATTEMPTS):
        slug = base if attempt == 0 else f"{base[:53].rstrip('-')}-{secrets.token_hex(3)}"
        world_id = connection.execute(
            text("""
                INSERT INTO core.worlds (name, slug, description, lifecycle_status_id)
                VALUES (:name, :slug, :description, :status)
                ON CONFLICT (slug) DO NOTHING
                RETURNING world_id
            """),
            {"name": name, "slug": slug, "description": description, "status": lifecycle_status_id},
        ).scalar()
        if world_id is not None:
            assert isinstance(world_id, uuid.UUID)
            return world_id
    raise RuntimeError("could not allocate a unique world slug")  # pragma: no cover


def create_world(
    connection: Connection,
    *,
    creator_user_id: uuid.UUID,
    name: str,
    description: str | None,
    ruleset_ids: list[uuid.UUID],
    default_ruleset_id: uuid.UUID,
    primary_timeline_name: str,
    primary_timeline_description: str | None = None,
) -> CreateWorldResult:
    """Atomically create a world, its allowed rulesets and default, the
    creator's `world_owner` membership, and its primary timeline.

    `row_version` is read back after the default ruleset is set: the
    `core.worlds` default-ruleset trigger requires the allow-list to exist
    first, so the world is inserted, given its allow-list, and then updated —
    the returned version is the true current one, not an assumed 1."""
    clean_name = normalize_name(name)
    clean_description = normalize_description(description)
    clean_timeline_name = normalize_name(primary_timeline_name)
    clean_timeline_description = normalize_description(primary_timeline_description)
    rulesets = _validated_rulesets(
        connection, ruleset_ids=ruleset_ids, default_ruleset_id=default_ruleset_id
    )

    active_status = lookup_id(
        connection, "core", "lifecycle_statuses", "lifecycle_status_id", "active"
    )
    world_id = _insert_world_with_unique_slug(
        connection,
        name=clean_name,
        description=clean_description,
        lifecycle_status_id=active_status,
    )
    for ruleset_id in rulesets:
        connection.execute(
            text("INSERT INTO rules.world_rulesets (world_id, ruleset_id) VALUES (:w, :r)"),
            {"w": world_id, "r": ruleset_id},
        )
    connection.execute(
        text("UPDATE core.worlds SET default_ruleset_id = :r WHERE world_id = :w"),
        {"r": default_ruleset_id, "w": world_id},
    )

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
        {"w": world_id, "u": creator_user_id, "role": WORLD_OWNER_ROLE},
    ).scalar()
    assert isinstance(membership_id, uuid.UUID)

    timeline = insert_root_timeline(
        connection,
        world_id=world_id,
        name=clean_timeline_name,
        description=clean_timeline_description,
        is_primary=True,
    )
    row_version = connection.execute(
        text("SELECT row_version FROM core.worlds WHERE world_id = :w"), {"w": world_id}
    ).scalar()
    assert isinstance(row_version, int)
    return CreateWorldResult(
        world_id=world_id,
        primary_timeline_id=timeline.timeline_id,
        world_membership_id=membership_id,
        row_version=row_version,
        timeline_row_version=timeline.row_version,
    )


@dataclass(frozen=True)
class _LockedWorld:
    row_version: int
    name: str
    description: str | None
    lifecycle_status: str


def _lock_world_for_manage(
    connection: Connection, *, world_id: uuid.UUID, actor_user_id: uuid.UUID
) -> tuple[_LockedWorld, WorldAuthority]:
    """Lock the world row, then re-resolve and re-check authority under that
    lock. Every failure is the same non-disclosing error."""
    row = connection.execute(
        text("""
            SELECT w.row_version, w.name, w.description, w.lifecycle_status_id
            FROM core.worlds w
            WHERE w.world_id = :w
            FOR UPDATE OF w
        """),
        {"w": world_id},
    ).one_or_none()
    if row is None:
        raise WorldNotAuthorizedError(f"world {world_id} does not exist")
    authority = resolve_world_authority(connection, user_id=actor_user_id, world_id=world_id)
    if authority is None or not authority.has_capability(WORLD_MANAGE):
        raise WorldNotAuthorizedError(f"user {actor_user_id} lacks world.manage on {world_id}")
    return (
        _LockedWorld(
            row_version=int(row.row_version),
            name=str(row.name),
            description=row.description,
            lifecycle_status=lifecycle_code(connection, row.lifecycle_status_id),
        ),
        authority,
    )


def update_world(
    connection: Connection,
    *,
    world_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int,
    name: str,
    description: str | None,
) -> WorldMutationResult:
    """Replace the world's editable fields (name, description). A no-op (both
    unchanged) writes, bumps, and audits nothing."""
    clean_name = normalize_name(name)
    clean_description = normalize_description(description)
    world, _authority = _lock_world_for_manage(
        connection, world_id=world_id, actor_user_id=actor_user_id
    )
    if world.row_version != expected_row_version:
        raise StaleWriteError(f"world {world_id} is at {world.row_version}")
    _require_world_action(connection, world_id, WORLD_UPDATE, world.lifecycle_status)

    changed: dict[str, object] = {}
    if clean_name != world.name:
        changed["name"] = {"from": world.name, "to": clean_name}
    if clean_description != world.description:
        changed["description"] = {"from": world.description, "to": clean_description}
    if not changed:
        return WorldMutationResult(
            world_id=world_id,
            row_version=world.row_version,
            lifecycle_status=world.lifecycle_status,
            changed=False,
        )
    new_version = connection.execute(
        text("""
            UPDATE core.worlds SET name = :name, description = :description
            WHERE world_id = :w RETURNING row_version
        """),
        {"name": clean_name, "description": clean_description, "w": world_id},
    ).scalar()
    assert isinstance(new_version, int)
    return WorldMutationResult(
        world_id=world_id,
        row_version=new_version,
        lifecycle_status=world.lifecycle_status,
        changed=True,
        changed_fields=changed,
    )


def _require_world_action(
    connection: Connection, world_id: uuid.UUID, action: str, lifecycle_status: str
) -> None:
    """The shared state policy (`dnd_ai.domain.authoring_policy`) the read
    model also uses, so a preview cannot disagree with enforcement."""
    reason = world_blocked_reason(
        action,
        lifecycle_status=lifecycle_status,
        has_blocking_campaigns=(
            action == WORLD_ARCHIVE and world_has_blocking_campaigns(connection, world_id=world_id)
        ),
    )
    if reason is not None:
        raise_for_reason(reason, f"{action} blocked for world {world_id}: {reason}")


def _set_world_lifecycle(connection: Connection, *, world_id: uuid.UUID, status_code: str) -> int:
    new_version = connection.execute(
        text("""
            UPDATE core.worlds
            SET lifecycle_status_id =
                (SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = :code)
            WHERE world_id = :w RETURNING row_version
        """),
        {"code": status_code, "w": world_id},
    ).scalar()
    assert isinstance(new_version, int)
    return new_version


def archive_world(
    connection: Connection,
    *,
    world_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int,
    reason: str | None = None,
) -> WorldMutationResult:
    """Archive an active world. Refused while any non-archived campaign exists
    on any of its timelines (no count, name, or identifier is disclosed).
    Does not cascade to timelines or campaigns."""
    normalize_reason(reason)
    world, _authority = _lock_world_for_manage(
        connection, world_id=world_id, actor_user_id=actor_user_id
    )
    if world.row_version != expected_row_version:
        raise StaleWriteError(f"world {world_id} is at {world.row_version}")
    _require_world_action(connection, world_id, WORLD_ARCHIVE, world.lifecycle_status)
    new_version = _set_world_lifecycle(connection, world_id=world_id, status_code="archived")
    return WorldMutationResult(
        world_id=world_id,
        row_version=new_version,
        lifecycle_status="archived",
        changed=True,
        previous_lifecycle_status="active",
    )


def restore_world(
    connection: Connection,
    *,
    world_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int,
    reason: str | None = None,
) -> WorldMutationResult:
    """Restore an archived world. Touches no timeline or campaign."""
    normalize_reason(reason)
    world, _authority = _lock_world_for_manage(
        connection, world_id=world_id, actor_user_id=actor_user_id
    )
    if world.row_version != expected_row_version:
        raise StaleWriteError(f"world {world_id} is at {world.row_version}")
    _require_world_action(connection, world_id, WORLD_RESTORE, world.lifecycle_status)
    new_version = _set_world_lifecycle(connection, world_id=world_id, status_code="active")
    return WorldMutationResult(
        world_id=world_id,
        row_version=new_version,
        lifecycle_status="active",
        changed=True,
        previous_lifecycle_status="archived",
    )


def claim_unowned_world(
    connection: Connection, *, world_id: uuid.UUID, user_id: uuid.UUID
) -> ClaimWorldResult:
    """Trusted infrastructure only — never exposed over HTTP. Make `user_id`
    the first owner of a legacy world. Succeeds only while the world has **no
    `world_memberships` row of any status**, so it can never override an owned
    or previously owned world, and only for an active user."""
    exists = connection.execute(
        text("SELECT 1 FROM core.worlds WHERE world_id = :w FOR UPDATE"), {"w": world_id}
    ).scalar()
    if exists is None:
        raise WorldAlreadyClaimedError(f"world {world_id} does not exist")
    has_rows = connection.execute(
        text("SELECT EXISTS (SELECT 1 FROM security.world_memberships WHERE world_id = :w)"),
        {"w": world_id},
    ).scalar()
    if has_rows:
        raise WorldAlreadyClaimedError(f"world {world_id} already has (or had) an owner")
    active_user = connection.execute(
        text("""
            SELECT 1 FROM security.users u
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = u.lifecycle_status_id
            WHERE u.user_id = :u AND ls.code = 'active'
        """),
        {"u": user_id},
    ).scalar()
    if active_user is None:
        raise WorldAlreadyClaimedError(f"user {user_id} does not exist or is not active")
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
        {"w": world_id, "u": user_id, "role": WORLD_OWNER_ROLE},
    ).scalar()
    assert isinstance(membership_id, uuid.UUID)
    return ClaimWorldResult(world_id=world_id, user_id=user_id, world_membership_id=membership_id)

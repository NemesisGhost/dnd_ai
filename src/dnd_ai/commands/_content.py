"""Shared plumbing for the typed world-content commands (Phase 15.1, ADR 0015).

Not a generic entity writer: it holds only what every typed command must do the
same way, so no command can forget a step.

- `lock_authoring_scope` -- the head of the lock order and the authority
  re-check under lock (world `FOR SHARE`, the actor's membership and role rows
  `FOR SHARE`, the actor's account `FOR SHARE`, campaign `FOR SHARE`, then
  `canon.edit` re-resolved from committed state). The world is derived from the
  campaign, never from a request.
- `lock_entities` -- entities locked one at a time in `entity_id` order, in
  `FOR UPDATE` or `FOR SHARE` mode, only if they belong to the world (a foreign
  row is never locked).
- `insert_gm_source` / `insert_draft_entity` -- provenance and the
  `core.entities` root for a create.

The sequence is: scope, then entities by ascending id, then any per-world
advisory lock (see docs/architecture/SYSTEM_ARCHITECTURE.md §7.1).
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy import Connection, text

from dnd_ai.domain.access import resolve_access_context
from dnd_ai.domain.authoring import (
    CampaignArchivedError,
    CampaignNotAuthorizedError,
    ContentNotEditableError,
    StaleWriteError,
    WorldArchivedError,
    WorldAuthorityRequiredError,
    WorldNotAuthorizedError,
)
from dnd_ai.domain.content_authoring import content_edit_blocked_reason, is_reference_eligible
from dnd_ai.domain.errors import DomainAuthorizationError, SafeMessageError
from dnd_ai.queries.world_authority import resolve_world_authority

from ._shared import lifecycle_code, lookup_id

CANON_EDIT = "canon.edit"


class EntityNotFoundError(DomainAuthorizationError):
    """No such entity *in this campaign's world* (or not of the type this
    command handles) -- a nonexistent entity, one belonging to another world,
    and one of another type are indistinguishable (fixed 404)."""


@dataclass(frozen=True)
class AuthoringScope:
    world_id: uuid.UUID
    campaign_id: uuid.UUID


@dataclass(frozen=True)
class LockedContent:
    entity_id: uuid.UUID
    world_id: uuid.UUID
    entity_type_id: uuid.UUID
    entity_type_code: str
    canonical_name: str
    summary: str | None
    canon_status: str
    lifecycle_status: str
    row_version: int


@dataclass(frozen=True)
class ContentWriteResult:
    """What a typed create/update command returns. The route audits from it:
    `changed_fields` is the bounded initial values for a create and the
    `{field: {from, to}}` diff for an update."""

    entity_id: uuid.UUID
    world_id: uuid.UUID
    entity_type_code: str
    row_version: int
    created: bool
    changed: bool
    changed_fields: dict[str, object] = field(default_factory=dict)
    source_id: uuid.UUID | None = None
    # Audit identity of the record the command wrote. The default is the entity
    # root; a child-record command (a quest stage, an objective) names its own
    # table and row, with `entity_id` still the aggregate root so history groups
    # by quest. `action` overrides created/updated (e.g. a child `deleted`).
    record_schema: str = "core"
    record_table: str = "entities"
    record_id: uuid.UUID | None = None
    action: str | None = None


def lock_authoring_scope(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    world_capability: str | None,
) -> AuthoringScope:
    """Lock and re-authorize. Raises `CampaignNotAuthorizedError` (404) if the
    campaign does not exist or the actor no longer holds `canon.edit`,
    `WorldArchivedError`/`CampaignArchivedError` (409) if either is no longer
    active.

    `world_capability` is the world capability the operation needs on the
    campaign's world (docs/adr/0020-scoped-system-world-and-campaign-roles.md,
    D6): `world.canon.edit` for definition writes, `world.canon.review` for the
    canon lifecycle. It is required **in addition to** campaign `canon.edit`,
    and it is resolved here, under the world `FOR SHARE` lock (which a concurrent
    `end_world_role` / ownership transfer, taking the world `FOR UPDATE`,
    serializes against), so a role ended mid-command is honoured. A caller
    without it gets `WorldAuthorityRequiredError` (403 `world_authority_required`).

    `None` means campaign authority alone suffices. It is for the explicitly
    campaign-originated records that live in world tables (D8: world-time points,
    item instances, player-character identity) and for the campaign-state
    operations wrapped by `dnd_ai.commands._operations.lock_operation_scope`. It is
    required (no default) so no caller can omit the world check by accident."""
    world_id = connection.execute(
        text("""
            SELECT t.world_id FROM campaign.campaigns c
            JOIN campaign.timelines t ON t.timeline_id = c.timeline_id
            WHERE c.campaign_id = :c
        """),
        {"c": campaign_id},
    ).scalar()
    if world_id is None:
        raise CampaignNotAuthorizedError(f"campaign {campaign_id} does not exist")
    assert isinstance(world_id, uuid.UUID)

    world = connection.execute(
        text("SELECT lifecycle_status_id FROM core.worlds WHERE world_id = :w FOR SHARE"),
        {"w": world_id},
    ).one_or_none()
    if world is None:
        raise WorldNotAuthorizedError(f"world {world_id} does not exist")

    # Hold the actor's open membership and unrevoked role rows so a concurrent
    # `revoke_membership_role` / `end_campaign_membership` (which take FOR UPDATE
    # on these rows) serializes against this command. `mr` before `cm`, the same
    # order `change_membership_role` uses.
    #
    # These are locked BEFORE the campaign row, not after: a role revocation
    # writes the membership-role row and then, at commit, its deferred
    # access-manager retention trigger takes the campaign row FOR UPDATE. A
    # command holding the campaign FOR SHARE while waiting on the revoked row
    # would deadlock with it (found by the real-PostgreSQL race test).
    connection.execute(
        text("""
            SELECT mr.membership_role_id
            FROM security.membership_roles mr
            JOIN security.campaign_memberships cm
              ON cm.campaign_membership_id = mr.campaign_membership_id
            WHERE cm.campaign_id = :c AND cm.user_id = :u
              AND cm.ended_at IS NULL AND mr.revoked_at IS NULL
            ORDER BY mr.membership_role_id
            FOR SHARE OF mr, cm
        """),
        {"c": campaign_id, "u": actor_user_id},
    ).all()
    user = connection.execute(
        text("SELECT lifecycle_status_id FROM security.users WHERE user_id = :u FOR SHARE"),
        {"u": actor_user_id},
    ).one_or_none()

    campaign = connection.execute(
        text("SELECT lifecycle_status_id FROM campaign.campaigns WHERE campaign_id = :c FOR SHARE"),
        {"c": campaign_id},
    ).one_or_none()
    if campaign is None:
        raise CampaignNotAuthorizedError(f"campaign {campaign_id} does not exist")

    if lifecycle_code(connection, world.lifecycle_status_id) != "active":
        raise WorldArchivedError(f"world {world_id} is not active")
    if lifecycle_code(connection, campaign.lifecycle_status_id) != "active":
        raise CampaignArchivedError(f"campaign {campaign_id} is not active")
    if user is None or lifecycle_code(connection, user.lifecycle_status_id) != "active":
        raise CampaignNotAuthorizedError(f"user {actor_user_id} is not an active account")

    access = resolve_access_context(connection, user_id=actor_user_id, campaign_id=campaign_id)
    if access is None or not access.has_capability(CANON_EDIT):
        raise CampaignNotAuthorizedError(f"user {actor_user_id} lacks canon.edit on {campaign_id}")
    if world_capability is not None:
        authority = resolve_world_authority(connection, user_id=actor_user_id, world_id=world_id)
        if authority is None or not authority.has_capability(world_capability):
            raise WorldAuthorityRequiredError(
                f"user {actor_user_id} lacks {world_capability} on world {world_id}"
            )
    return AuthoringScope(world_id=world_id, campaign_id=campaign_id)


def lock_entities(
    connection: Connection,
    *,
    world_id: uuid.UUID,
    update_ids: Sequence[uuid.UUID] = (),
    share_ids: Sequence[uuid.UUID] = (),
) -> dict[uuid.UUID, LockedContent]:
    """Lock the named entities one at a time in ascending `entity_id` order:
    `FOR UPDATE` for `update_ids`, `FOR SHARE` for the rest. Only rows that
    belong to `world_id` are locked or returned; a nonexistent id and an id in
    another world are both simply absent. Status codes are resolved by separate
    queries, never a JOIN inside the locking statement (see `lifecycle_code`).
    """
    update_set = set(update_ids)
    locked: dict[uuid.UUID, LockedContent] = {}
    for entity_id in sorted(update_set | set(share_ids)):
        mode = "UPDATE" if entity_id in update_set else "SHARE"
        row = connection.execute(
            text(f"""
                SELECT e.entity_id, e.world_id, e.entity_type_id, e.canonical_name, e.summary,
                       e.canon_status_id, e.lifecycle_status_id, e.row_version
                FROM core.entities e
                WHERE e.entity_id = :id AND e.world_id = :w
                FOR {mode} OF e
            """),
            {"id": entity_id, "w": world_id},
        ).one_or_none()
        if row is None:
            continue
        type_code = connection.execute(
            text("SELECT code FROM core.entity_types WHERE entity_type_id = :t"),
            {"t": row.entity_type_id},
        ).scalar()
        canon_code = connection.execute(
            text("SELECT code FROM core.canon_statuses WHERE canon_status_id = :s"),
            {"s": row.canon_status_id},
        ).scalar()
        assert isinstance(type_code, str) and isinstance(canon_code, str)
        locked[entity_id] = LockedContent(
            entity_id=entity_id,
            world_id=row.world_id,
            entity_type_id=row.entity_type_id,
            entity_type_code=type_code,
            canonical_name=str(row.canonical_name),
            summary=row.summary,
            canon_status=canon_code,
            lifecycle_status=lifecycle_code(connection, row.lifecycle_status_id),
            row_version=int(row.row_version),
        )
    return locked


def insert_gm_source(
    connection: Connection, *, world_id: uuid.UUID, actor_user_id: uuid.UUID
) -> uuid.UUID:
    """The `gm_entry` provenance row a create cites (ENTITY_LIFECYCLE §21.1).
    Never an authorization input."""
    source_type_id = lookup_id(connection, "core", "source_types", "source_type_id", "gm_entry")
    source_id = connection.execute(
        text("""
            INSERT INTO core.sources (world_id, source_type_id, title, created_by_user_id)
            VALUES (:w, :t, 'GM entry', :u)
            RETURNING source_id
        """),
        {"w": world_id, "t": source_type_id, "u": actor_user_id},
    ).scalar()
    assert isinstance(source_id, uuid.UUID)
    return source_id


def insert_draft_entity(
    connection: Connection,
    *,
    world_id: uuid.UUID,
    entity_type_code: str,
    name: str,
    summary: str | None,
    source_id: uuid.UUID,
    actor_user_id: uuid.UUID,
) -> tuple[uuid.UUID, int]:
    """The `core.entities` root, `draft`/`active`, with provenance and creator
    attribution. The entity type id is resolved from the catalog by code, never
    taken from a request. Returns `(entity_id, row_version)`."""
    row = connection.execute(
        text("""
            INSERT INTO core.entities
                (world_id, entity_type_id, canonical_name, summary, canon_status_id,
                 lifecycle_status_id, source_id, created_by_user_id)
            VALUES (
                :w,
                (SELECT entity_type_id FROM core.entity_types WHERE code = :type),
                :name, :summary,
                (SELECT canon_status_id FROM core.canon_statuses WHERE code = 'draft'),
                (SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'active'),
                :source, :user
            )
            RETURNING entity_id, row_version
        """),
        {
            "w": world_id,
            "type": entity_type_code,
            "name": name,
            "summary": summary,
            "source": source_id,
            "user": actor_user_id,
        },
    ).one()
    return row.entity_id, int(row.row_version)


def touch_entity(
    connection: Connection, *, entity_id: uuid.UUID, name: str, summary: str | None
) -> int:
    """UPDATE the root row, which bumps `row_version` (the root version covers
    the whole aggregate, even when only subtype fields changed). Returns the new
    version."""
    version = connection.execute(
        text("""
            UPDATE core.entities SET canonical_name = :name, summary = :summary
            WHERE entity_id = :e RETURNING row_version
        """),
        {"name": name, "summary": summary, "e": entity_id},
    ).scalar()
    assert isinstance(version, int)
    return version


def editable_target(
    locked: dict[uuid.UUID, LockedContent],
    *,
    entity_id: uuid.UUID,
    type_codes: frozenset[str],
    expected_row_version: int,
) -> LockedContent:
    """The locked update target after the checks every typed `update_*` command
    makes, in this order: it is in the campaign's world and of one of this
    command's types (else `EntityNotFoundError`, the non-disclosing 404), its
    `row_version` matches (`StaleWriteError`), and its canon status and lifecycle
    allow editing (`ContentNotEditableError`). The version check precedes the
    edit policy so an editor who lost a race learns "stale", not "locked"."""
    target = locked.get(entity_id)
    if target is None or target.entity_type_code not in type_codes:
        raise EntityNotFoundError(f"entity {entity_id} is not an editable record in this world")
    if target.row_version != expected_row_version:
        raise StaleWriteError(f"entity {entity_id} is at {target.row_version}")
    reason = content_edit_blocked_reason(target.canon_status, target.lifecycle_status)
    if reason is not None:
        raise ContentNotEditableError(f"entity {entity_id} cannot be edited: {reason}")
    return target


def usable_reference(
    locked: dict[uuid.UUID, LockedContent],
    entity_id: uuid.UUID | None,
    *,
    type_codes: frozenset[str],
    error: type[SafeMessageError],
) -> LockedContent | None:
    """A *newly* referenced record, validated (`is_reference_eligible`: same
    world, expected type, active, draft/proposed/approved/canon). `None` for no
    reference. Every reason it can be unusable raises the same field-specific
    `error` -- nonexistent, other world, wrong type, archived, rejected, and
    superseded are indistinguishable to the caller."""
    if entity_id is None:
        return None
    reference = locked.get(entity_id)
    if (
        reference is None
        or reference.entity_type_code not in type_codes
        or not is_reference_eligible(reference.canon_status, reference.lifecycle_status)
    ):
        raise error("reference is not usable")
    return reference

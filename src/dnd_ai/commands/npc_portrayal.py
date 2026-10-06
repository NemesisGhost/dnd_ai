"""NPC detail level and portrayal profile commands (Phase 15 checkpoint 15.3A-3, decision D-21).

`update_npc_detail_level` changes how much authoring an NPC deserves (a GM planning aid) against
the NPC `row_version`, like any edit of the NPC own fields. `save_npc_portrayal_profile` appends
the next version of the NPC GM-only portrayal guidance; its optimistic token is the current
version number the editor saw (`0` when there is none), and saving what is already the current
version is a no-op. No version is ever changed or deleted.

Lock order: authority scope, then the NPC entity `FOR UPDATE` (a profile save also takes it,
which is what serializes two saves; it does not move the NPC `row_version`).
"""

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Connection, text

from dnd_ai.domain.authoring import (
    AuthoringValidationError,
    ContentNotEditableError,
    StaleWriteError,
    normalize_reason,
)
from dnd_ai.domain.content_authoring import content_edit_blocked_reason, diff_fields
from dnd_ai.domain.npc_portrayal import (
    PROFILE_FIELD_NAMES,
    normalize_detail_level,
    normalize_profile_field,
)

from ._content import (
    ContentWriteResult,
    EntityNotFoundError,
    editable_target,
    lock_authoring_scope,
    lock_entities,
    touch_entity,
)

_NPC = frozenset({"npc"})


@dataclass(frozen=True)
class ProfileResult:
    npc_id: uuid.UUID
    world_id: uuid.UUID
    version_number: int
    changed: bool
    profile_id: uuid.UUID | None = None
    changed_fields: dict[str, object] = field(default_factory=dict)


def update_npc_detail_level(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    npc_id: uuid.UUID,
    expected_row_version: int,
    detail_level: str,
) -> ContentWriteResult:
    level = normalize_detail_level(detail_level)
    scope = lock_authoring_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    locked = lock_entities(connection, world_id=scope.world_id, update_ids=[npc_id])
    target = editable_target(
        locked, entity_id=npc_id, type_codes=_NPC, expected_row_version=expected_row_version
    )
    current = connection.execute(
        text("SELECT detail_level FROM character.npcs WHERE npc_id = :n"), {"n": npc_id}
    ).scalar()
    if current == level:
        return ContentWriteResult(
            entity_id=npc_id,
            world_id=scope.world_id,
            entity_type_code="npc",
            row_version=target.row_version,
            created=False,
            changed=False,
        )
    connection.execute(
        text("UPDATE character.npcs SET detail_level = :l, updated_at = now() WHERE npc_id = :n"),
        {"l": level, "n": npc_id},
    )
    version = touch_entity(
        connection, entity_id=npc_id, name=target.canonical_name, summary=target.summary
    )
    return ContentWriteResult(
        entity_id=npc_id,
        world_id=scope.world_id,
        entity_type_code="npc",
        row_version=version,
        created=False,
        changed=True,
        changed_fields=dict(diff_fields({"detail_level": current}, {"detail_level": level})),
        record_schema="character",
        record_table="npcs",
        record_id=npc_id,
        action="updated",
    )


def save_npc_portrayal_profile(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    npc_id: uuid.UUID,
    expected_version: int,
    fields: dict[str, Any],
    change_note: str | None = None,
) -> ProfileResult:
    unknown = set(fields) - set(PROFILE_FIELD_NAMES)
    if unknown:
        raise AuthoringValidationError(f"unknown portrayal field(s) {sorted(unknown)}")
    clean = {
        name: normalize_profile_field(fields.get(name), field=name) for name in PROFILE_FIELD_NAMES
    }
    note = normalize_reason(change_note)
    scope = lock_authoring_scope(connection, campaign_id=campaign_id, actor_user_id=actor_user_id)
    locked = lock_entities(connection, world_id=scope.world_id, update_ids=[npc_id])
    npc = locked.get(npc_id)
    if npc is None or npc.entity_type_code != "npc":
        raise EntityNotFoundError(f"npc {npc_id} is not in this world")
    blocked = content_edit_blocked_reason(npc.canon_status, npc.lifecycle_status)
    if blocked is not None:
        raise ContentNotEditableError(f"npc {npc_id} cannot be edited: {blocked}")
    latest = (
        connection.execute(
            text(  # noqa: S608 - fixed column names
                "SELECT version_number, "
                + ", ".join(PROFILE_FIELD_NAMES)
                + " FROM character.npc_portrayal_profiles WHERE npc_id = :n "
                "ORDER BY version_number DESC LIMIT 1"
            ),
            {"n": npc_id},
        )
        .mappings()
        .one_or_none()
    )
    current = 0 if latest is None else int(latest["version_number"])
    if current != expected_version:
        raise StaleWriteError(f"portrayal of {npc_id} is at version {current}")
    before = {name: (None if latest is None else latest[name]) for name in PROFILE_FIELD_NAMES}
    changed = diff_fields(before, clean)
    if latest is not None and not changed:
        return ProfileResult(
            npc_id=npc_id, world_id=scope.world_id, version_number=current, changed=False
        )
    profile_id = connection.execute(
        text(  # noqa: S608 - fixed column names
            "INSERT INTO character.npc_portrayal_profiles (npc_id, version_number, "
            + ", ".join(PROFILE_FIELD_NAMES)
            + ", change_note, created_by_user_id) VALUES (:n, :v, "
            + ", ".join(f":f_{name}" for name in PROFILE_FIELD_NAMES)
            + ", :note, :user) RETURNING npc_portrayal_profile_id"
        ),
        {
            "n": npc_id,
            "v": current + 1,
            **{f"f_{name}": value for name, value in clean.items()},
            "note": note,
            "user": actor_user_id,
        },
    ).scalar()
    assert isinstance(profile_id, uuid.UUID)
    return ProfileResult(
        npc_id=npc_id,
        world_id=scope.world_id,
        version_number=current + 1,
        changed=True,
        profile_id=profile_id,
        changed_fields=dict(changed),
    )

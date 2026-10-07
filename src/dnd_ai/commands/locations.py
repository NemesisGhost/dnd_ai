"""Typed Location authoring commands (Phase 15.1, reference vertical slice).

`create_location` and `update_location` author the ten non-dungeon place
categories (`dnd_ai.domain.content_authoring.AUTHORABLE_LOCATION_CATEGORIES`).
They write **definition** rows only -- `core.entities`, `world.locations`, and a
`world.settlements` / `world.buildings` row where the category needs one --
never `campaign.location_state` (timeline state needs a causal event).

Transaction and lock policy (SYSTEM_ARCHITECTURE §7.1):

1. `lock_authoring_scope`: world `FOR SHARE`, campaign `FOR SHARE`, the actor's
   membership/role/account rows `FOR SHARE`, `canon.edit` re-resolved.
2. Entities in ascending `entity_id`: the target `FOR UPDATE`, a *changed*
   parent `FOR SHARE`.
3. The world's containment advisory lock (the same key the
   `tr_locations_enforce_no_cycle` trigger takes) before the ancestry walk.

Everything runs in the caller's transaction; a failure after the root insert
rolls back the source, the entity, every subtype row, and (in the route) the
audit and idempotency rows together.
"""

import uuid

from sqlalchemy import Connection, text

from dnd_ai.domain.authoring import (
    LocationHierarchyCycleError,
    ParentLocationInvalidError,
    normalize_reason,
)
from dnd_ai.domain.content_authoring import (
    AUTHORABLE_LOCATION_CATEGORIES,
    diff_fields,
    initial_fields,
    location_category,
    normalize_location_fields,
)
from dnd_ai.domain.world_authority import WORLD_CANON_EDIT

from ._content import (
    ContentWriteResult,
    LockedContent,
    editable_target,
    insert_draft_entity,
    insert_gm_source,
    lock_authoring_scope,
    lock_entities,
    touch_entity,
    usable_reference,
)


def _lock_parent(
    connection: Connection, *, world_id: uuid.UUID, parent_location_id: uuid.UUID
) -> LockedContent:
    """Lock a proposed parent `FOR SHARE` and validate it. Every reason it can
    be unusable (absent, other world, wrong category, archived, rejected,
    superseded) is the same non-disclosing `ParentLocationInvalidError`."""
    locked = lock_entities(connection, world_id=world_id, share_ids=[parent_location_id])
    return _require_usable_parent(locked, parent_location_id)


def _require_usable_parent(
    locked: dict[uuid.UUID, LockedContent], parent_location_id: uuid.UUID
) -> LockedContent:
    parent = usable_reference(
        locked,
        parent_location_id,
        type_codes=AUTHORABLE_LOCATION_CATEGORIES,
        error=ParentLocationInvalidError,
    )
    assert parent is not None
    return parent


def _insert_location_rows(
    connection: Connection,
    *,
    entity_id: uuid.UUID,
    category_code: str,
    parent_location_id: uuid.UUID | None,
    population: int | None,
    building_use: str | None,
) -> None:
    connection.execute(
        text("INSERT INTO world.locations (location_id, parent_location_id) VALUES (:l, :p)"),
        {"l": entity_id, "p": parent_location_id},
    )
    if category_code == "settlement":
        connection.execute(
            text("INSERT INTO world.settlements (settlement_id, population) VALUES (:l, :p)"),
            {"l": entity_id, "p": population},
        )
    elif category_code == "building":
        connection.execute(
            text("INSERT INTO world.buildings (building_id, building_use) VALUES (:l, :u)"),
            {"l": entity_id, "u": building_use},
        )


def create_location(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    category_code: str,
    name: str | None,
    summary: str | None,
    parent_location_id: uuid.UUID | None = None,
    population: int | None = None,
    building_use: str | None = None,
) -> ContentWriteResult:
    """Create a Location draft: source, `core.entities` root, `world.locations`,
    and the category's subtype row, in the caller's transaction."""
    category = location_category(category_code)
    clean_name, clean_summary, clean_population, clean_use = normalize_location_fields(
        category_code=category.code,
        name=name,
        summary=summary,
        population=population,
        building_use=building_use,
    )
    scope = lock_authoring_scope(
        connection,
        campaign_id=campaign_id,
        actor_user_id=actor_user_id,
        world_capability=WORLD_CANON_EDIT,
    )
    if parent_location_id is not None:
        _lock_parent(connection, world_id=scope.world_id, parent_location_id=parent_location_id)

    source_id = insert_gm_source(connection, world_id=scope.world_id, actor_user_id=actor_user_id)
    entity_id, row_version = insert_draft_entity(
        connection,
        world_id=scope.world_id,
        entity_type_code=category.code,
        name=clean_name,
        summary=clean_summary,
        source_id=source_id,
        actor_user_id=actor_user_id,
    )
    _insert_location_rows(
        connection,
        entity_id=entity_id,
        category_code=category.code,
        parent_location_id=parent_location_id,
        population=clean_population,
        building_use=clean_use,
    )
    return ContentWriteResult(
        entity_id=entity_id,
        world_id=scope.world_id,
        entity_type_code=category.code,
        row_version=row_version,
        created=True,
        changed=True,
        changed_fields=initial_fields(
            {
                "category": category.code,
                "name": clean_name,
                "summary": clean_summary,
                "parent_location_id": None
                if parent_location_id is None
                else str(parent_location_id),
                "population": clean_population,
                "building_use": clean_use,
            }
        ),
        source_id=source_id,
    )


def _current_location_fields(connection: Connection, location_id: uuid.UUID) -> dict[str, object]:
    row = connection.execute(
        text("""
            SELECT l.parent_location_id, s.population, b.building_use
            FROM world.locations l
            LEFT JOIN world.settlements s ON s.settlement_id = l.location_id
            LEFT JOIN world.buildings b ON b.building_id = l.location_id
            WHERE l.location_id = :l
        """),
        {"l": location_id},
    ).one()
    return {
        "parent_location_id": None
        if row.parent_location_id is None
        else str(row.parent_location_id),
        "population": row.population,
        "building_use": row.building_use,
    }


def _would_create_cycle(
    connection: Connection,
    *,
    world_id: uuid.UUID,
    location_id: uuid.UUID,
    new_parent_id: uuid.UUID,
) -> bool:
    """Whether `location_id` is `new_parent_id` or one of its ancestors. Takes
    the world's containment advisory lock first, serializing every containment
    change in the world (the trigger takes the same key), so the walk cannot
    race a concurrent reparent."""
    connection.execute(
        text(
            "SELECT pg_advisory_xact_lock(hashtextextended('world.locations.containment:' || :w, 0))"
        ),
        {"w": str(world_id)},
    )
    found = connection.execute(
        text("""
            WITH RECURSIVE ancestry AS (
                SELECT l.location_id, l.parent_location_id
                FROM world.locations l WHERE l.location_id = :start
                UNION ALL
                SELECT l.location_id, l.parent_location_id
                FROM world.locations l JOIN ancestry a ON l.location_id = a.parent_location_id
            )
            CYCLE location_id SET is_cycle USING path
            SELECT bool_or(location_id = :target) FROM ancestry
        """),
        {"start": new_parent_id, "target": location_id},
    ).scalar()
    return bool(found)


def update_location(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    location_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_row_version: int,
    name: str | None,
    summary: str | None,
    parent_location_id: uuid.UUID | None,
    population: int | None = None,
    building_use: str | None = None,
    change_note: str | None = None,
) -> ContentWriteResult:
    """Replace a Location's editable fields (name, summary, parent, and the
    category's typed fields). Category is immutable. An identical resubmission
    is a no-op: nothing is written and `row_version` does not move."""
    normalize_reason(change_note)
    scope = lock_authoring_scope(
        connection,
        campaign_id=campaign_id,
        actor_user_id=actor_user_id,
        world_capability=WORLD_CANON_EDIT,
    )

    current_parent_hint = connection.execute(
        text("SELECT parent_location_id FROM world.locations WHERE location_id = :l"),
        {"l": location_id},
    ).scalar()
    share_ids = (
        [parent_location_id]
        if parent_location_id is not None and parent_location_id != current_parent_hint
        else []
    )
    locked = lock_entities(
        connection, world_id=scope.world_id, update_ids=[location_id], share_ids=share_ids
    )
    target = editable_target(
        locked,
        entity_id=location_id,
        type_codes=AUTHORABLE_LOCATION_CATEGORIES,
        expected_row_version=expected_row_version,
    )

    clean_name, clean_summary, clean_population, clean_use = normalize_location_fields(
        category_code=target.entity_type_code,
        name=name,
        summary=summary,
        population=population,
        building_use=building_use,
    )

    current = _current_location_fields(connection, location_id)
    before = {"name": target.canonical_name, "summary": target.summary, **current}
    after = {
        "name": clean_name,
        "summary": clean_summary,
        "parent_location_id": None if parent_location_id is None else str(parent_location_id),
        "population": clean_population,
        "building_use": clean_use,
    }
    # A field that does not apply to this category is neither read nor written.
    applicable = {"name", "summary", "parent_location_id"} | {
        f.name for f in location_category(target.entity_type_code).fields
    }
    before = {k: v for k, v in before.items() if k in applicable}
    after = {k: v for k, v in after.items() if k in applicable}
    changed_fields = diff_fields(before, after)
    if not changed_fields:
        return ContentWriteResult(
            entity_id=location_id,
            world_id=scope.world_id,
            entity_type_code=target.entity_type_code,
            row_version=target.row_version,
            created=False,
            changed=False,
        )

    if "parent_location_id" in changed_fields and parent_location_id is not None:
        if parent_location_id not in locked:
            locked.update(
                lock_entities(connection, world_id=scope.world_id, share_ids=[parent_location_id])
            )
        _require_usable_parent(locked, parent_location_id)
        if parent_location_id == location_id or _would_create_cycle(
            connection,
            world_id=scope.world_id,
            location_id=location_id,
            new_parent_id=parent_location_id,
        ):
            raise LocationHierarchyCycleError(f"location {location_id} cannot be its own ancestor")

    new_version = touch_entity(
        connection, entity_id=location_id, name=clean_name, summary=clean_summary
    )
    if "parent_location_id" in changed_fields:
        connection.execute(
            text("UPDATE world.locations SET parent_location_id = :p WHERE location_id = :l"),
            {"p": parent_location_id, "l": location_id},
        )
    if "population" in changed_fields:
        connection.execute(
            text("UPDATE world.settlements SET population = :p WHERE settlement_id = :l"),
            {"p": clean_population, "l": location_id},
        )
    if "building_use" in changed_fields:
        connection.execute(
            text("UPDATE world.buildings SET building_use = :u WHERE building_id = :l"),
            {"u": clean_use, "l": location_id},
        )
    return ContentWriteResult(
        entity_id=location_id,
        world_id=scope.world_id,
        entity_type_code=target.entity_type_code,
        row_version=new_version,
        created=False,
        changed=True,
        changed_fields=dict(changed_fields),
    )

"""Shared test-data builders.

Lives here rather than in a test module so test modules never import from each
other — that coupling makes it unclear who owns a helper and breaks as soon as
the importing module is collected first.

These issue raw inserts. docs/DATABASE_CONVENTIONS.md §32.3 asks for test data
built through the same commands production uses, and those commands do not
exist yet — the application layer arrives in a later phase. Everything using
these builders is also specifically testing database enforcement, which is the
exception §32.3 allows. Replace these with command calls once the command layer
lands, rather than growing them into a parallel write path.
"""

import uuid

from sqlalchemy import Connection, text


def status_id(connection: Connection, table: str, code: str) -> uuid.UUID:
    """Look up a seeded status by code. Asserts rather than returning None."""
    pk = "canon_status_id" if table == "canon_statuses" else "lifecycle_status_id"
    value = connection.execute(
        text(f"SELECT {pk} FROM core.{table} WHERE code = :c"), {"c": code}
    ).scalar()
    assert isinstance(value, uuid.UUID), f"seeded {table} row {code!r} missing"
    return value


def lookup_id(connection: Connection, schema: str, table: str, pk: str, code: str) -> uuid.UUID:
    value = connection.execute(
        text(f"SELECT {pk} FROM {schema}.{table} WHERE code = :c"), {"c": code}
    ).scalar()
    assert isinstance(value, uuid.UUID), f"seeded {schema}.{table} row {code!r} missing"
    return value


def make_world(connection: Connection, slug: str = "test-world") -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO core.worlds (name, slug, lifecycle_status_id)
            VALUES ('Test World', :slug, :status)
            RETURNING world_id
        """),
        {"slug": slug, "status": status_id(connection, "lifecycle_statuses", "active")},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_entity_type(
    connection: Connection,
    code: str,
    *,
    parent_id: uuid.UUID | None = None,
    subtype_table: str | None = None,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO core.entity_types
                (code, display_name, parent_entity_type_id, required_subtype_table)
            VALUES (:code, :code, :parent, :subtype)
            RETURNING entity_type_id
        """),
        {"code": code, "parent": parent_id, "subtype": subtype_table},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_entity(
    connection: Connection,
    world_id: uuid.UUID,
    entity_type_id: uuid.UUID,
    name: str = "Test Entity",
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO core.entities
                (world_id, entity_type_id, canonical_name, canon_status_id, lifecycle_status_id)
            VALUES (:world, :etype, :name, :canon, :lifecycle)
            RETURNING entity_id
        """),
        {
            "world": world_id,
            "etype": entity_type_id,
            "name": name,
            "canon": status_id(connection, "canon_statuses", "draft"),
            "lifecycle": status_id(connection, "lifecycle_statuses", "active"),
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_user(connection: Connection, username: str = "tester") -> uuid.UUID:
    value = connection.execute(
        text(
            "INSERT INTO security.users (username, display_name) VALUES (:u, :u) RETURNING user_id"
        ),
        {"u": username},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_world_time(connection: Connection, world_id: uuid.UUID, sort_key: int) -> uuid.UUID:
    """A minimal point in a world's fictional chronology.

    sort_key is the only field that matters to interval logic, so callers pass
    it explicitly and everything else takes a default. year is supplied because
    ck_world_times_year_or_label requires a year or a label.
    """
    value = connection.execute(
        text("""
            INSERT INTO core.world_times
                (world_id, world_time_precision_id, year, sort_key)
            VALUES (
                :world,
                (SELECT world_time_precision_id FROM core.world_time_precisions
                 WHERE code = 'exact'),
                :year,
                :sort_key
            )
            RETURNING world_time_id
        """),
        {"world": world_id, "year": 1000 + sort_key, "sort_key": sort_key},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_timeline(
    connection: Connection,
    world_id: uuid.UUID,
    name: str = "Primary",
    *,
    is_primary: bool = False,
    parent_timeline_id: uuid.UUID | None = None,
    branch_world_time_id: uuid.UUID | None = None,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO campaign.timelines
                (world_id, name, is_primary, parent_timeline_id, branch_world_time_id,
                 lifecycle_status_id)
            VALUES (:world, :name, :primary, :parent, :branch, :status)
            RETURNING timeline_id
        """),
        {
            "world": world_id,
            "name": name,
            "primary": is_primary,
            "parent": parent_timeline_id,
            "branch": branch_world_time_id,
            "status": status_id(connection, "lifecycle_statuses", "active"),
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_party(connection: Connection, world_id: uuid.UUID, name: str = "The Company") -> uuid.UUID:
    value = connection.execute(
        text("INSERT INTO campaign.parties (world_id, name) VALUES (:w, :n) RETURNING party_id"),
        {"w": world_id, "n": name},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_ruleset_version(connection: Connection, code: str | None = None) -> uuid.UUID:
    """A bare ruleset + ruleset_version, with no world association.

    For content tests (species, classes, ...) that need a version to hang
    off but don't need a campaign or world_rulesets entry. Use
    make_ruleset_for_world instead when a campaign needs to reference the
    ruleset.
    """
    if code is None:
        code = f"ruleset_{uuid.uuid4().hex[:8]}"
    ruleset_id = connection.execute(
        text(
            "INSERT INTO rules.rulesets (code, display_name) VALUES (:c, :c) RETURNING ruleset_id"
        ),
        {"c": code},
    ).scalar()
    value = connection.execute(
        text("""
            INSERT INTO rules.ruleset_versions (ruleset_id, version_label)
            VALUES (:r, 'v1')
            RETURNING ruleset_version_id
        """),
        {"r": ruleset_id},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_species(
    connection: Connection, ruleset_version_id: uuid.UUID, code: str = "human"
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO rules.species (ruleset_version_id, code, display_name)
            VALUES (:v, :c, :c)
            RETURNING species_id
        """),
        {"v": ruleset_version_id, "c": code},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_character(
    connection: Connection,
    world_id: uuid.UUID,
    *,
    species_id: uuid.UUID | None = None,
    name: str = "Test Character",
    size_category: str = "medium",
    entity_type_code: str = "character",
) -> uuid.UUID:
    """A core.entities row plus its character.characters row. Returns the
    shared UUID (the character_id, same as the entity_id).

    species_id is auto-provisioned (a ruleset version associated with
    world_id, so the species passes character.enforce_character_species_
    ruleset_allowed() — revision 029) when omitted. entity_type_code defaults
    to the bare 'character' type; pass 'npc' or 'player_character' when the
    caller also needs to insert the corresponding character.npcs /
    character.player_characters row — core.enforce_entity_subtype() rejects
    that subtype row otherwise, since a bare 'character'-typed entity does
    not require one.
    """
    if species_id is None:
        species_id = make_species(connection, make_ruleset_version_for_world(connection, world_id))

    character_type_id = lookup_id(
        connection, "core", "entity_types", "entity_type_id", entity_type_code
    )
    character_id = make_entity(connection, world_id, character_type_id, name=name)
    connection.execute(
        text("""
            INSERT INTO character.characters (character_id, species_id, size_category)
            VALUES (:c, :s, :size)
        """),
        {"c": character_id, "s": species_id, "size": size_category},
    )
    return character_id


def make_ruleset_for_world(
    connection: Connection,
    world_id: uuid.UUID,
    code: str | None = None,
    *,
    is_default: bool | None = None,
) -> uuid.UUID:
    """A ruleset + current ruleset_version + world_rulesets association, ready
    for a campaign in this world to reference.

    code defaults to a random slug since rules.rulesets.code is unique across
    the whole database, not per world. is_default controls
    core.worlds.default_ruleset_id — the sole source of truth for a world's
    default ruleset since revision 027 removed rules.world_rulesets.is_default
    — and defaults to True only if the world has no default yet.
    """
    if code is None:
        code = f"ruleset_{uuid.uuid4().hex[:8]}"

    ruleset_id = connection.execute(
        text(
            "INSERT INTO rules.rulesets (code, display_name) VALUES (:c, :c) RETURNING ruleset_id"
        ),
        {"c": code},
    ).scalar()
    assert isinstance(ruleset_id, uuid.UUID)
    connection.execute(
        text("""
            INSERT INTO rules.ruleset_versions (ruleset_id, version_label, is_current)
            VALUES (:r, 'v1', true)
        """),
        {"r": ruleset_id},
    )
    connection.execute(
        text("INSERT INTO rules.world_rulesets (world_id, ruleset_id) VALUES (:w, :r)"),
        {"w": world_id, "r": ruleset_id},
    )

    if is_default is None:
        existing_default = connection.execute(
            text("SELECT default_ruleset_id FROM core.worlds WHERE world_id = :w"),
            {"w": world_id},
        ).scalar()
        is_default = existing_default is None

    if is_default:
        connection.execute(
            text("UPDATE core.worlds SET default_ruleset_id = :r WHERE world_id = :w"),
            {"r": ruleset_id, "w": world_id},
        )

    return ruleset_id


def make_ruleset_version_for_world(
    connection: Connection, world_id: uuid.UUID, code: str | None = None
) -> uuid.UUID:
    """A ruleset version associated with world_id via rules.world_rulesets,
    ready to hang content (species, conditions, resource_definitions, a
    character build, ...) off for a character or timeline in this world.

    Since revision 029, species/build/condition/resource references are
    checked against rules.world_rulesets for the owning world — a bare
    make_ruleset_version() has no such association and will be rejected.
    Does not touch core.worlds.default_ruleset_id (is_default=False).
    """
    ruleset_id = make_ruleset_for_world(connection, world_id, code, is_default=False)
    value = connection.execute(
        text(
            "SELECT ruleset_version_id FROM rules.ruleset_versions "
            "WHERE ruleset_id = :r AND is_current"
        ),
        {"r": ruleset_id},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_campaign(
    connection: Connection,
    timeline_id: uuid.UUID,
    name: str = "The Campaign",
    *,
    ruleset_version_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """A campaign on the given timeline.

    ruleset_version_id is auto-provisioned when omitted: looks up the
    timeline's world, reuses a ruleset already allowed there if one exists
    (pinning to its current version), otherwise creates one via
    make_ruleset_for_world. Callers testing ruleset-specific behavior should
    pass one explicitly.
    """
    if ruleset_version_id is None:
        world_id = connection.execute(
            text("SELECT world_id FROM campaign.timelines WHERE timeline_id = :t"),
            {"t": timeline_id},
        ).scalar()
        existing_ruleset_id = connection.execute(
            text("SELECT ruleset_id FROM rules.world_rulesets WHERE world_id = :w LIMIT 1"),
            {"w": world_id},
        ).scalar()
        if existing_ruleset_id is None:
            existing_ruleset_id = make_ruleset_for_world(connection, world_id)
        ruleset_version_id = connection.execute(
            text(
                "SELECT ruleset_version_id FROM rules.ruleset_versions "
                "WHERE ruleset_id = :r AND is_current"
            ),
            {"r": existing_ruleset_id},
        ).scalar()

    value = connection.execute(
        text("""
            INSERT INTO campaign.campaigns
                (timeline_id, name, lifecycle_status_id, ruleset_version_id)
            VALUES (:tl, :n, :status, :ruleset_version)
            RETURNING campaign_id
        """),
        {
            "tl": timeline_id,
            "n": name,
            "status": status_id(connection, "lifecycle_statuses", "active"),
            "ruleset_version": ruleset_version_id,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_session(
    connection: Connection,
    campaign_id: uuid.UUID,
    session_number: int,
    *,
    start_world_time_id: uuid.UUID | None = None,
    end_world_time_id: uuid.UUID | None = None,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO campaign.sessions
                (campaign_id, session_number, lifecycle_status_id,
                 start_world_time_id, end_world_time_id)
            VALUES (:c, :n, :status, :start, :end)
            RETURNING session_id
        """),
        {
            "c": campaign_id,
            "n": session_number,
            "status": status_id(connection, "lifecycle_statuses", "active"),
            "start": start_world_time_id,
            "end": end_world_time_id,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_location(
    connection: Connection,
    world_id: uuid.UUID,
    *,
    parent_location_id: uuid.UUID | None = None,
    entity_type_code: str = "location",
    name: str = "Test Location",
) -> uuid.UUID:
    """A core.entities row plus its world.locations row. Returns the shared
    UUID (the location_id, same as the entity_id).

    entity_type_code defaults to the bare 'location' type; pass 'settlement',
    'building', 'dungeon', or 'dungeon_area' when the caller also needs to
    insert the corresponding subtype row — core.enforce_entity_subtype()
    rejects that subtype row otherwise.
    """
    location_type_id = lookup_id(
        connection, "core", "entity_types", "entity_type_id", entity_type_code
    )
    location_id = make_entity(connection, world_id, location_type_id, name=name)
    connection.execute(
        text("""
            INSERT INTO world.locations (location_id, parent_location_id)
            VALUES (:l, :p)
        """),
        {"l": location_id, "p": parent_location_id},
    )
    return location_id


def make_dungeon(
    connection: Connection,
    world_id: uuid.UUID,
    *,
    parent_location_id: uuid.UUID | None = None,
    name: str = "Test Dungeon",
) -> uuid.UUID:
    """A location plus its world.dungeons row. Returns the shared UUID."""
    dungeon_id = make_location(
        connection,
        world_id,
        parent_location_id=parent_location_id,
        entity_type_code="dungeon",
        name=name,
    )
    connection.execute(
        text("INSERT INTO world.dungeons (dungeon_id) VALUES (:d)"), {"d": dungeon_id}
    )
    return dungeon_id


def make_dungeon_area(
    connection: Connection,
    dungeon_id: uuid.UUID,
    *,
    name: str = "Test Area",
) -> uuid.UUID:
    """A dungeon area belonging to the given dungeon. Returns the shared UUID.

    world_id is derived from the dungeon's own entity row.
    """
    world_id = connection.execute(
        text("SELECT world_id FROM core.entities WHERE entity_id = :d"), {"d": dungeon_id}
    ).scalar()
    assert isinstance(world_id, uuid.UUID)
    area_id = make_location(
        connection,
        world_id,
        parent_location_id=dungeon_id,
        entity_type_code="dungeon_area",
        name=name,
    )
    connection.execute(
        text("INSERT INTO world.dungeon_areas (dungeon_area_id) VALUES (:a)"), {"a": area_id}
    )
    return area_id


def make_area_connection(
    connection: Connection,
    from_dungeon_area_id: uuid.UUID,
    to_dungeon_area_id: uuid.UUID,
    *,
    connection_type_code: str = "door",
    is_hidden: bool = False,
    is_one_way: bool = False,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO world.area_connections
                (from_dungeon_area_id, to_dungeon_area_id, connection_type_id, is_hidden,
                 is_one_way)
            VALUES (:f, :t, :ct, :hidden, :one_way)
            RETURNING area_connection_id
        """),
        {
            "f": from_dungeon_area_id,
            "t": to_dungeon_area_id,
            "ct": lookup_id(
                connection,
                "world",
                "connection_types",
                "connection_type_id",
                connection_type_code,
            ),
            "hidden": is_hidden,
            "one_way": is_one_way,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_area_feature(
    connection: Connection, dungeon_area_id: uuid.UUID, *, is_hidden: bool = False
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO world.area_features (dungeon_area_id, feature_type, is_hidden)
            VALUES (:a, 'statue', :hidden)
            RETURNING area_feature_id
        """),
        {"a": dungeon_area_id, "hidden": is_hidden},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_area_hazard(
    connection: Connection, dungeon_area_id: uuid.UUID, *, is_hidden: bool = False
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO world.area_hazards (dungeon_area_id, hazard_type, is_hidden)
            VALUES (:a, 'trap', :hidden)
            RETURNING area_hazard_id
        """),
        {"a": dungeon_area_id, "hidden": is_hidden},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_area_interactable(
    connection: Connection, dungeon_area_id: uuid.UUID, *, is_hidden: bool = False
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO world.area_interactables (dungeon_area_id, interactable_type, is_hidden)
            VALUES (:a, 'lever', :hidden)
            RETURNING area_interactable_id
        """),
        {"a": dungeon_area_id, "hidden": is_hidden},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_knowledge_item(
    connection: Connection,
    world_id: uuid.UUID,
    *,
    knowledge_type_code: str = "secret",
    truth_status_code: str = "true",
    statement: str = "There is a secret door here.",
    subject_area_connection_id: uuid.UUID | None = None,
    subject_area_feature_id: uuid.UUID | None = None,
    subject_area_hazard_id: uuid.UUID | None = None,
    subject_area_interactable_id: uuid.UUID | None = None,
    subject_entity_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """A core.entities row plus its knowledge.knowledge_items row. Returns
    the shared UUID (the knowledge_item_id, same as the entity_id)."""
    knowledge_item_type_id = lookup_id(
        connection, "core", "entity_types", "entity_type_id", "knowledge_item"
    )
    knowledge_item_id = make_entity(connection, world_id, knowledge_item_type_id, name=statement)
    connection.execute(
        text("""
            INSERT INTO knowledge.knowledge_items
                (knowledge_item_id, knowledge_type_id, truth_status_id, canonical_statement,
                 subject_entity_id, subject_area_connection_id, subject_area_feature_id,
                 subject_area_hazard_id, subject_area_interactable_id)
            VALUES (
                :id,
                (SELECT knowledge_type_id FROM knowledge.knowledge_types WHERE code = :kt),
                (SELECT truth_status_id FROM knowledge.truth_statuses WHERE code = :ts),
                :statement, :subject_entity, :subject_connection, :subject_feature,
                :subject_hazard, :subject_interactable
            )
        """),
        {
            "id": knowledge_item_id,
            "kt": knowledge_type_code,
            "ts": truth_status_code,
            "statement": statement,
            "subject_entity": subject_entity_id,
            "subject_connection": subject_area_connection_id,
            "subject_feature": subject_area_feature_id,
            "subject_hazard": subject_area_hazard_id,
            "subject_interactable": subject_area_interactable_id,
        },
    )
    return knowledge_item_id


def make_world_entity(connection: Connection, slug: str) -> uuid.UUID:
    """A world plus a throwaway entity type plus one entity, for tests that need
    an entity but do not care about its world or type."""
    world = make_world(connection, slug=slug)
    entity_type = make_entity_type(connection, f"{slug.replace('-', '_')}_type")
    return make_entity(connection, world, entity_type)

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
    subtype_pk_column: str | None = None,
) -> uuid.UUID:
    """subtype_pk_column is required whenever subtype_table is set (revision
    048's ck_entity_types_subtype_pk_column_paired) — the primary-key column
    name of subtype_table, e.g. "npc_id" for "character.npcs". Left unset
    when a caller is deliberately testing an invalid/unqualified
    subtype_table and expects the INSERT to fail regardless."""
    value = connection.execute(
        text("""
            INSERT INTO core.entity_types
                (code, display_name, parent_entity_type_id, required_subtype_table,
                 required_subtype_pk_column)
            VALUES (:code, :code, :parent, :subtype, :pk_column)
            RETURNING entity_type_id
        """),
        {
            "code": code,
            "parent": parent_id,
            "subtype": subtype_table,
            "pk_column": subtype_pk_column,
        },
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
    branch_event_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """branch_event_id is omitted from the INSERT column list entirely when
    not given, rather than always sent as NULL — tests/database/
    test_phase5_populated_upgrade.py deliberately calls this against a
    database pinned at revision 042, before campaign.timelines.
    branch_event_id existed (revision 058); every other caller passing no
    branch_event_id must keep working unchanged there."""
    params = {
        "world": world_id,
        "name": name,
        "primary": is_primary,
        "parent": parent_timeline_id,
        "branch": branch_world_time_id,
        "status": status_id(connection, "lifecycle_statuses", "active"),
    }
    if branch_event_id is not None:
        query = """
            INSERT INTO campaign.timelines
                (world_id, name, is_primary, parent_timeline_id, branch_world_time_id,
                 branch_event_id, lifecycle_status_id)
            VALUES (:world, :name, :primary, :parent, :branch, :branch_event, :status)
            RETURNING timeline_id
        """
        params["branch_event"] = branch_event_id
    else:
        query = """
            INSERT INTO campaign.timelines
                (world_id, name, is_primary, parent_timeline_id, branch_world_time_id,
                 lifecycle_status_id)
            VALUES (:world, :name, :primary, :parent, :branch, :status)
            RETURNING timeline_id
        """
    value = connection.execute(text(query), params).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def set_timeline_branch_event(
    connection: Connection, timeline_id: uuid.UUID, branch_event_id: uuid.UUID | None
) -> None:
    """Set/clear branch_event_id on an already-created timeline — for tests
    that need to exercise campaign.enforce_timeline_branch()'s UPDATE path,
    not just the INSERT path make_timeline covers."""
    connection.execute(
        text("UPDATE campaign.timelines SET branch_event_id = :e WHERE timeline_id = :t"),
        {"e": branch_event_id, "t": timeline_id},
    )


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


def make_bare_ruleset(connection: Connection, code: str) -> uuid.UUID:
    """A ruleset row with no version at all — for tests that manage the
    ruleset_versions insert themselves (e.g. moving a version between two
    rulesets to prove ruleset_id is immutable)."""
    value = connection.execute(
        text(
            "INSERT INTO rules.rulesets (code, display_name) VALUES (:c, :c) RETURNING ruleset_id"
        ),
        {"c": code},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def current_ruleset_version_id(connection: Connection, ruleset_id: uuid.UUID) -> uuid.UUID:
    value = connection.execute(
        text(
            "SELECT ruleset_version_id FROM rules.ruleset_versions "
            "WHERE ruleset_id = :r AND is_current"
        ),
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


def make_ability(
    connection: Connection, ruleset_version_id: uuid.UUID, code: str = "strength"
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO rules.abilities (ruleset_version_id, code, display_name)
            VALUES (:v, :c, :c)
            RETURNING ability_id
        """),
        {"v": ruleset_version_id, "c": code},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_skill(
    connection: Connection,
    ruleset_version_id: uuid.UUID,
    ability_id: uuid.UUID,
    code: str = "stealth",
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO rules.skills (ruleset_version_id, ability_id, code, display_name)
            VALUES (:v, :a, :c, :c)
            RETURNING skill_id
        """),
        {"v": ruleset_version_id, "a": ability_id, "c": code},
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


def make_event(
    connection: Connection,
    world_id: uuid.UUID,
    timeline_id: uuid.UUID,
    world_time_id: uuid.UUID,
    *,
    campaign_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    event_type_code: str = "other",
    event_status_code: str = "recorded",
    details: str | None = None,
    name: str = "Test Event",
) -> uuid.UUID:
    """A core.entities row plus its narrative.events row. Returns the shared
    UUID (the event_id, same as the entity_id).

    world_time_id has no default — callers exercising branch/effective-history
    behavior need explicit control over ordering (sort_key), so guessing one
    here would hide bugs rather than catch them.
    """
    event_entity_type_id = lookup_id(connection, "core", "entity_types", "entity_type_id", "event")
    event_id = make_entity(connection, world_id, event_entity_type_id, name=name)
    connection.execute(
        text("""
            INSERT INTO narrative.events
                (event_id, timeline_id, campaign_id, session_id, event_type_id,
                 event_status_id, world_time_id, details)
            VALUES (
                :id, :timeline, :campaign, :session,
                (SELECT event_type_id FROM narrative.event_types WHERE code = :etc),
                (SELECT event_status_id FROM narrative.event_statuses WHERE code = :esc),
                :world_time, :details
            )
        """),
        {
            "id": event_id,
            "timeline": timeline_id,
            "campaign": campaign_id,
            "session": session_id,
            "etc": event_type_code,
            "esc": event_status_code,
            "world_time": world_time_id,
            "details": details,
        },
    )
    return event_id


def make_interaction(
    connection: Connection,
    timeline_id: uuid.UUID,
    world_time_id: uuid.UUID,
    *,
    campaign_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    interaction_type_code: str = "other",
    status: str = "initiated",
    resulting_event_id: uuid.UUID | None = None,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO interaction.interactions
                (timeline_id, campaign_id, session_id, interaction_type_id, world_time_id,
                 status, resulting_event_id)
            VALUES (
                :timeline, :campaign, :session,
                (SELECT interaction_type_id FROM interaction.interaction_types WHERE code = :itc),
                :world_time, :status, :resulting_event
            )
            RETURNING interaction_id
        """),
        {
            "timeline": timeline_id,
            "campaign": campaign_id,
            "session": session_id,
            "itc": interaction_type_code,
            "world_time": world_time_id,
            "status": status,
            "resulting_event": resulting_event_id,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_action(
    connection: Connection,
    interaction_id: uuid.UUID,
    actor_entity_id: uuid.UUID,
    *,
    sequence_number: int = 0,
    description: str | None = None,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO interaction.actions
                (interaction_id, actor_entity_id, sequence_number, description)
            VALUES (:interaction, :actor, :seq, :description)
            RETURNING action_id
        """),
        {
            "interaction": interaction_id,
            "actor": actor_entity_id,
            "seq": sequence_number,
            "description": description,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_target(
    connection: Connection,
    action_id: uuid.UUID,
    *,
    target_entity_id: uuid.UUID | None = None,
    target_area_connection_id: uuid.UUID | None = None,
    target_area_feature_id: uuid.UUID | None = None,
    target_area_hazard_id: uuid.UUID | None = None,
    target_area_interactable_id: uuid.UUID | None = None,
    target_component: str | None = None,
    target_description: str | None = None,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO interaction.targets
                (action_id, target_entity_id, target_area_connection_id, target_area_feature_id,
                 target_area_hazard_id, target_area_interactable_id, target_component,
                 target_description)
            VALUES (:action, :entity, :connection, :feature, :hazard, :interactable, :component,
                    :description)
            RETURNING target_id
        """),
        {
            "action": action_id,
            "entity": target_entity_id,
            "connection": target_area_connection_id,
            "feature": target_area_feature_id,
            "hazard": target_area_hazard_id,
            "interactable": target_area_interactable_id,
            "component": target_component,
            "description": target_description,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_check_request(
    connection: Connection,
    action_id: uuid.UUID,
    actor_entity_id: uuid.UUID,
    *,
    check_kind: str = "ability_check",
    ability_id: uuid.UUID | None = None,
    skill_id: uuid.UUID | None = None,
    difficulty: int = 10,
    advantage_state: str = "normal",
    stakes: str | None = None,
    target_id: uuid.UUID | None = None,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO interaction.check_requests
                (action_id, actor_entity_id, check_kind, ability_id, skill_id, difficulty,
                 advantage_state, stakes, target_id)
            VALUES (:action, :actor, :kind, :ability, :skill, :difficulty, :advantage, :stakes,
                    :target)
            RETURNING check_request_id
        """),
        {
            "action": action_id,
            "actor": actor_entity_id,
            "kind": check_kind,
            "ability": ability_id,
            "skill": skill_id,
            "difficulty": difficulty,
            "advantage": advantage_state,
            "stakes": stakes,
            "target": target_id,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_check_result(
    connection: Connection,
    check_request_id: uuid.UUID,
    *,
    roll: int | None = None,
    total_modifier: int | None = None,
    total: int | None = None,
    degree_of_success: str = "success",
    is_visible_to_players: bool = True,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO interaction.check_results
                (check_request_id, roll, total_modifier, total, degree_of_success,
                 is_visible_to_players)
            VALUES (:request, :roll, :total_modifier, :total, :degree, :visible)
            RETURNING check_result_id
        """),
        {
            "request": check_request_id,
            "roll": roll,
            "total_modifier": total_modifier,
            "total": total,
            "degree": degree_of_success,
            "visible": is_visible_to_players,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_consequence(
    connection: Connection,
    interaction_id: uuid.UUID,
    *,
    consequence_type: str = "observation",
    status: str = "proposed",
    resulting_event_id: uuid.UUID | None = None,
    resulting_party_discovery_id: uuid.UUID | None = None,
    description: str | None = None,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO interaction.consequences
                (interaction_id, consequence_type, status, resulting_event_id,
                 resulting_party_discovery_id, description)
            VALUES (:interaction, :type, :status, :event, :discovery, :description)
            RETURNING consequence_id
        """),
        {
            "interaction": interaction_id,
            "type": consequence_type,
            "status": status,
            "event": resulting_event_id,
            "discovery": resulting_party_discovery_id,
            "description": description,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_world_entity(connection: Connection, slug: str) -> uuid.UUID:
    """A world plus a throwaway entity type plus one entity, for tests that need
    an entity but do not care about its world or type."""
    world = make_world(connection, slug=slug)
    entity_type = make_entity_type(connection, f"{slug.replace('-', '_')}_type")
    return make_entity(connection, world, entity_type)


def make_story_arc(
    connection: Connection,
    world_id: uuid.UUID,
    *,
    name: str = "Test Story Arc",
    status: str = "active",
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO narrative.story_arcs (world_id, name, status)
            VALUES (:world, :name, :status)
            RETURNING story_arc_id
        """),
        {"world": world_id, "name": name, "status": status},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_quest(
    connection: Connection,
    world_id: uuid.UUID,
    *,
    story_arc_id: uuid.UUID | None = None,
    name: str = "Test Quest",
) -> uuid.UUID:
    """A core.entities row plus its narrative.quests row. Returns the shared
    UUID (the quest_id, same as the entity_id)."""
    quest_type_id = lookup_id(connection, "core", "entity_types", "entity_type_id", "quest")
    quest_id = make_entity(connection, world_id, quest_type_id, name=name)
    connection.execute(
        text("""
            INSERT INTO narrative.quests (quest_id, story_arc_id)
            VALUES (:id, :arc)
        """),
        {"id": quest_id, "arc": story_arc_id},
    )
    return quest_id


def make_quest_stage(
    connection: Connection,
    quest_id: uuid.UUID,
    *,
    name: str = "Test Stage",
    sequence_number: int = 0,
    stage_type: str = "sequential",
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO narrative.quest_stages (quest_id, name, sequence_number, stage_type)
            VALUES (:quest, :name, :seq, :type)
            RETURNING quest_stage_id
        """),
        {"quest": quest_id, "name": name, "seq": sequence_number, "type": stage_type},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_quest_objective(
    connection: Connection,
    quest_stage_id: uuid.UUID,
    *,
    objective_type_code: str = "other",
    name: str = "Test Objective",
    requirement_level: str = "required",
    completion_mode: str = "automatic",
    target_entity_id: uuid.UUID | None = None,
    target_area_connection_id: uuid.UUID | None = None,
    target_area_feature_id: uuid.UUID | None = None,
    target_area_hazard_id: uuid.UUID | None = None,
    target_area_interactable_id: uuid.UUID | None = None,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO narrative.quest_objectives
                (quest_stage_id, objective_type_id, name, requirement_level, completion_mode,
                 target_entity_id, target_area_connection_id, target_area_feature_id,
                 target_area_hazard_id, target_area_interactable_id)
            VALUES (
                :stage,
                (SELECT objective_type_id FROM narrative.objective_types WHERE code = :otc),
                :name, :requirement, :completion,
                :entity, :connection, :feature, :hazard, :interactable
            )
            RETURNING quest_objective_id
        """),
        {
            "stage": quest_stage_id,
            "otc": objective_type_code,
            "name": name,
            "requirement": requirement_level,
            "completion": completion_mode,
            "entity": target_entity_id,
            "connection": target_area_connection_id,
            "feature": target_area_feature_id,
            "hazard": target_area_hazard_id,
            "interactable": target_area_interactable_id,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_objective_dependency(
    connection: Connection,
    objective_id: uuid.UUID,
    depends_on_objective_id: uuid.UUID,
    *,
    dependency_type: str = "prerequisite",
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO narrative.objective_dependencies
                (objective_id, depends_on_objective_id, dependency_type)
            VALUES (:objective, :depends_on, :type)
            RETURNING objective_dependency_id
        """),
        {"objective": objective_id, "depends_on": depends_on_objective_id, "type": dependency_type},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_quest_outcome(
    connection: Connection,
    quest_id: uuid.UUID,
    *,
    code: str = "success",
    name: str = "Success",
    outcome_category: str = "success",
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO narrative.quest_outcomes (quest_id, code, name, outcome_category)
            VALUES (:quest, :code, :name, :category)
            RETURNING quest_outcome_id
        """),
        {"quest": quest_id, "code": code, "name": name, "category": outcome_category},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_quest_state(
    connection: Connection,
    timeline_id: uuid.UUID,
    quest_id: uuid.UUID,
    *,
    party_id: uuid.UUID | None = None,
    status_code: str = "active",
    last_event_id: uuid.UUID | None = None,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO campaign.quest_state
                (timeline_id, quest_id, party_id, quest_status_id, last_event_id)
            VALUES (
                :timeline, :quest, :party,
                (SELECT quest_status_id FROM campaign.quest_statuses WHERE code = :status),
                :event
            )
            RETURNING quest_state_id
        """),
        {
            "timeline": timeline_id,
            "quest": quest_id,
            "party": party_id,
            "status": status_code,
            "event": last_event_id,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_objective_state(
    connection: Connection,
    timeline_id: uuid.UUID,
    quest_objective_id: uuid.UUID,
    *,
    party_id: uuid.UUID | None = None,
    status_code: str = "active",
    last_event_id: uuid.UUID | None = None,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO campaign.objective_state
                (timeline_id, quest_objective_id, party_id, objective_status_id, last_event_id)
            VALUES (
                :timeline, :objective, :party,
                (SELECT objective_status_id FROM campaign.objective_statuses WHERE code = :status),
                :event
            )
            RETURNING objective_state_id
        """),
        {
            "timeline": timeline_id,
            "objective": quest_objective_id,
            "party": party_id,
            "status": status_code,
            "event": last_event_id,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value

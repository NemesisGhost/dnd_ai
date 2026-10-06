"""The draft-deletion reference catalog is complete (Phase 14, D18).

`delete_draft_entity` physically deletes a definition. Its safety rests on
`ENTITY_REFERENCE_CLASSIFICATION`: every foreign key that references
`core.entities` or an eligible type's subtype table is either an owned row that
may go with the definition or a blocking reference. A new foreign key added by a
later migration must be classified here, or this test fails — so it can never
silently become a cascade that destroys history.
"""

import pytest
from sqlalchemy import Connection, text

from dnd_ai.commands.entity_lifecycle import (
    BLOCKING,
    ENTITY_REFERENCE_CLASSIFICATION,
    OWNED_CASCADE,
)
from dnd_ai.domain.entity_lifecycle import ENTITY_LIFECYCLE_ELIGIBLE_TYPE_CODES

pytestmark = pytest.mark.database


def _eligible_subtype_tables(connection: Connection) -> set[str]:
    rows = connection.execute(
        text("""
            WITH RECURSIVE chain AS (
                SELECT entity_type_id, parent_entity_type_id, required_subtype_table
                FROM core.entity_types WHERE code = ANY(CAST(:codes AS text[]))
                UNION ALL
                SELECT p.entity_type_id, p.parent_entity_type_id, p.required_subtype_table
                FROM core.entity_types p JOIN chain c ON p.entity_type_id = c.parent_entity_type_id
            )
            SELECT DISTINCT required_subtype_table FROM chain
            WHERE required_subtype_table IS NOT NULL
        """),
        {"codes": sorted(ENTITY_LIFECYCLE_ELIGIBLE_TYPE_CODES)},
    ).scalars()
    return {str(r) for r in rows}


def _referencing_foreign_keys(
    connection: Connection, referenced: set[str]
) -> set[tuple[str, str, str]]:
    rows = connection.execute(
        text("""
            SELECT n2.nspname AS schema_name, c2.relname AS table_name, a.attname AS column_name
            FROM pg_constraint con
            JOIN pg_class c1 ON c1.oid = con.confrelid
            JOIN pg_namespace n1 ON n1.oid = c1.relnamespace
            JOIN pg_class c2 ON c2.oid = con.conrelid
            JOIN pg_namespace n2 ON n2.oid = c2.relnamespace
            JOIN LATERAL unnest(con.conkey) AS k(attnum) ON true
            JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.attnum
            WHERE con.contype = 'f' AND (n1.nspname || '.' || c1.relname) = ANY(CAST(:ref AS text[]))
        """),
        {"ref": sorted(referenced)},
    ).all()
    return {(str(r.schema_name), str(r.table_name), str(r.column_name)) for r in rows}


def test_every_foreign_key_to_a_deletable_definition_is_classified(
    db_connection: Connection,
) -> None:
    referenced = {"core.entities", *_eligible_subtype_tables(db_connection)}
    actual = _referencing_foreign_keys(db_connection, referenced)
    unclassified = sorted(actual - set(ENTITY_REFERENCE_CLASSIFICATION))
    assert not unclassified, (
        "new foreign keys reference an entity definition; classify each in "
        f"commands/entity_lifecycle.ENTITY_REFERENCE_CLASSIFICATION: {unclassified}"
    )


def test_the_catalog_has_no_stale_entries(db_connection: Connection) -> None:
    referenced = {"core.entities", *_eligible_subtype_tables(db_connection)}
    actual = _referencing_foreign_keys(db_connection, referenced)
    stale = sorted(set(ENTITY_REFERENCE_CLASSIFICATION) - actual)
    assert not stale, f"classified columns that no longer reference a definition: {stale}"


def test_only_the_reviewed_owned_rows_are_cascade_deleted(db_connection: Connection) -> None:
    owned = {k for k, v in ENTITY_REFERENCE_CLASSIFICATION.items() if v == OWNED_CASCADE}
    assert {t for _s, t, _c in owned} == {
        "entity_names",
        "entity_tags",
        # Phase 15.2R: the definition's canonical revision history.
        "entity_revisions",
        "locations",
        "settlements",
        "buildings",
        "organizations",
        "businesses",
        "governments",
        "military_units",
        "political_factions",
        "religions",
        "religious_organizations",
        # Phase 15.1: an NPC's own identity rows.
        "characters",
        "npcs",
        "character_descriptions",
        "character_languages",
        "character_movements",
        "character_senses",
        # Phase 15.3A-3: the NPC's versioned portrayal profile.
        "npc_portrayal_profiles",
        # Phase 15.1: a quest's own definition rows.
        "quests",
        "quest_stages",
        "quest_participants",
        "quest_outcomes",
        # Phase 15.1: a knowledge claim's own row.
        "knowledge_items",
        # Phase 15.2B-1: a player character's marker row is part of its identity.
        "player_characters",
        # Phase 15.3A-1: a dungeon aggregate's own structural rows.
        "area_connections",
        "area_features",
        "area_hazards",
        "area_interactables",
    }
    assert all(v in (OWNED_CASCADE, BLOCKING) for v in ENTITY_REFERENCE_CLASSIFICATION.values())


def test_eligible_registry_codes_exist_and_exclusions_are_absent(
    db_connection: Connection,
) -> None:
    from dnd_ai.domain.entity_lifecycle import ENTITY_LIFECYCLE_EXCLUDED_TYPE_CODES

    existing = set(db_connection.execute(text("SELECT code FROM core.entity_types")).scalars())
    assert existing >= ENTITY_LIFECYCLE_ELIGIBLE_TYPE_CODES
    assert set(ENTITY_LIFECYCLE_EXCLUDED_TYPE_CODES) <= existing
    assert not ENTITY_LIFECYCLE_ELIGIBLE_TYPE_CODES & set(ENTITY_LIFECYCLE_EXCLUDED_TYPE_CODES)

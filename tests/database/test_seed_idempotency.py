"""Seed idempotency and reproducibility — re-seeding must be a no-op, and
the structured content an already-applied migration seeded must never
silently change.

Required by docs/DATABASE_CONVENTIONS.md §25.4/§25.6 and listed as a
recurring obligation in docs/PLAN.md §23.1. Two distinct concerns:

  1. Flat platform lookups (SEEDED_LOOKUPS below) — covered against their
     YAML source since Phase 2, unchanged here.
  2. Phase 4's structured rules.* content (revision 022) — cross-referencing
     seed data (a skill resolves its ability by code, a subclass its class,
     ...) that apply_seed's flat-code idempotency test never exercised. The
     corrections review added: (a) a frozen-content check, so editing one of
     revision 022's already-consumed YAML files is caught rather than
     silently changing what a fresh database receives from that revision;
     (b) value- and cross-reference-level assertions, not just code-set
     membership; (c) re-invoking revision 022's own upgrade() function
     in-process, twice, to prove the actual migration code is idempotent —
     not a hand-rewritten approximation of it.
"""

import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Connection, text

from dnd_ai.persistence.seeds import load_seed_data, seed_statements

pytestmark = pytest.mark.database

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SEEDS_DIR = REPO_ROOT / "database" / "seeds"
MIGRATIONS_DIR = REPO_ROOT / "database" / "migrations" / "versions"

# Seeded lookup tables and their primary-key column.
SEEDED_LOOKUPS = [
    ("core", "canon_statuses", "canon_status_id"),
    ("core", "lifecycle_statuses", "lifecycle_status_id"),
    ("core", "source_types", "source_type_id"),
    ("core", "name_types", "name_type_id"),
    ("core", "world_time_precisions", "world_time_precision_id"),
    ("audit", "change_actions", "change_action_id"),
]


def _reseed(connection: Connection, schema: str, table: str) -> None:
    """Re-apply a seed file through the same statements a migration would use."""
    for statement in seed_statements(schema, table):
        connection.execute(statement)


def _snapshot(connection: Connection, schema: str, table: str, pk: str) -> list[tuple[object, ...]]:
    rows = connection.execute(
        text(
            f"SELECT {pk}, code, display_name, description, sort_order, is_active "
            f"FROM {schema}.{table} ORDER BY code"
        )
    ).fetchall()
    return [tuple(r) for r in rows]


@pytest.mark.parametrize(("schema", "table", "pk"), SEEDED_LOOKUPS)
def test_database_matches_seed_file(
    db_connection: Connection, schema: str, table: str, pk: str
) -> None:
    """Every code in the seed file is present, and nothing extra is."""
    expected = {row["code"] for row in load_seed_data(schema, table)}
    actual = {r[0] for r in db_connection.execute(text(f"SELECT code FROM {schema}.{table}"))}
    assert actual == expected


@pytest.mark.parametrize(("schema", "table", "pk"), SEEDED_LOOKUPS)
def test_reseeding_changes_nothing(
    db_connection: Connection, schema: str, table: str, pk: str
) -> None:
    """Applying the seed to an already-seeded table leaves every row untouched.

    Runs inside the fixture's transaction, so it rolls back regardless of outcome.
    """
    before = _snapshot(db_connection, schema, table, pk)
    _reseed(db_connection, schema, table)
    after = _snapshot(db_connection, schema, table, pk)

    assert after == before, (
        f"Re-seeding {schema}.{table} changed its contents. Seeds must be "
        "idempotent (conventions §25.6) — check the ON CONFLICT target."
    )


@pytest.mark.parametrize(("schema", "table", "pk"), SEEDED_LOOKUPS)
def test_reseeding_does_not_duplicate_rows(
    db_connection: Connection, schema: str, table: str, pk: str
) -> None:
    count_before = db_connection.execute(text(f"SELECT count(*) FROM {schema}.{table}")).scalar()
    _reseed(db_connection, schema, table)
    _reseed(db_connection, schema, table)
    count_after = db_connection.execute(text(f"SELECT count(*) FROM {schema}.{table}")).scalar()

    assert count_after == count_before


# ---------------------------------------------------------------------------
# Frozen-content check: revision 022's inputs must not have been edited since
# ---------------------------------------------------------------------------

FROZEN_MANIFEST_PATH = SEEDS_DIR / "frozen_manifest.json"


def _frozen_manifest() -> dict[str, str]:
    data = json.loads(FROZEN_MANIFEST_PATH.read_text(encoding="utf-8"))
    files: dict[str, str] = data["files"]
    return files


@pytest.mark.parametrize("filename", sorted(_frozen_manifest()))
def test_frozen_seed_file_is_unchanged(filename: str) -> None:
    """A pure file-content check — no database involved, but marked
    `database` alongside its siblings since it lives in the same module and
    guards the same concern.

    If this fails, do not edit the listed file to make it pass: create a new
    *.yaml file and a new migration for the changed content instead
    (frozen_manifest.json's own "policy" field explains why)."""
    expected_hash = _frozen_manifest()[filename]
    actual_hash = hashlib.sha256((SEEDS_DIR / filename).read_bytes()).hexdigest()
    assert actual_hash == expected_hash, (
        f"database/seeds/{filename} has changed since revision "
        f"{json.loads(FROZEN_MANIFEST_PATH.read_text(encoding='utf-8'))['revision']} consumed it. "
        "A fresh database migrated from scratch would now seed different content than an "
        "environment that already ran that revision. Add a new seed file and a new migration "
        "for the changed content instead, per docs/DATABASE_CONVENTIONS.md §25.4."
    )


# ---------------------------------------------------------------------------
# Structured content (revision 022): cross-references and values, and true
# in-process idempotency of the migration's own upgrade() function
# ---------------------------------------------------------------------------


def _load_migration_module(revision_filename: str) -> ModuleType:
    path = MIGRATIONS_DIR / revision_filename
    spec = importlib.util.spec_from_file_location(f"_migration_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SEED_RULESET_MODULE = _load_migration_module("022_seed_initial_ruleset.py")
# Two later revisions changed things 022's hardcoded upgrade() relies on, in
# ways that would otherwise confound a direct re-invocation against a
# HEAD-migrated connection (every later revision already applied) — not
# because 022 is non-idempotent, but because later revisions changed what it
# writes into or against:
#   - 024 renamed the seeded ruleset's own code ('dnd5e_2024' -> 'dnd5e'),
#     which is 022's ON CONFLICT target for rules.rulesets. Re-running 022
#     against the renamed row would miss the conflict entirely and insert a
#     second ruleset (and, transitively, duplicate every content row under
#     it) — not a bug in 022, a consequence of the rename it can't see.
#   - 029 added rules.proficiency_types.target_kind NOT NULL with no default
#     (deliberately — see that revision's docstring), which 022's bare
#     INSERT INTO proficiency_types does not populate.
# Real Alembic never replays 022 out of sequence like this — each revision
# fires exactly once, tracked by alembic_version — so the faithful way to
# test 022's own idempotency is to first undo both later changes, using
# their own downgrade() functions, re-run 022, then redo them (everything
# here runs inside db_connection's rolled-back transaction, so nothing
# outlives the test).
RULESET_VERSION_PIN_MODULE = _load_migration_module("024_campaign_ruleset_version.py")
PROFICIENCY_TARGET_KIND_MODULE = _load_migration_module("029_character_state_corrections.py")


def _rerun_seed_migration(connection: Connection) -> None:
    """Invoke revision 022's actual upgrade() function again, in-process, at
    the table/data shape it was originally written against — not a
    hand-written approximation of its logic. Operations.context() is the
    documented mechanism for exercising a migration module's
    `from alembic import op` calls outside of a real alembic upgrade run."""
    context = MigrationContext.configure(connection)
    operations = Operations(context)
    with Operations.context(operations):
        PROFICIENCY_TARGET_KIND_MODULE.downgrade()
        RULESET_VERSION_PIN_MODULE.downgrade()
        SEED_RULESET_MODULE.upgrade()
        RULESET_VERSION_PIN_MODULE.upgrade()
        PROFICIENCY_TARGET_KIND_MODULE.upgrade()


def test_rerunning_the_seed_migration_does_not_duplicate_rows(db_connection: Connection) -> None:
    tables = (
        "abilities",
        "species",
        "damage_types",
        "conditions",
        "creature_types",
        "languages",
        "proficiency_types",
        "resource_definitions",
        "skills",
        "classes",
        "subclasses",
        "feats",
        "spells",
        "features",
    )
    counts_before = {
        t: db_connection.execute(text(f"SELECT count(*) FROM rules.{t}")).scalar() for t in tables
    }

    # Run it twice in a row: idempotency must hold on the second re-run too,
    # not just the first (a bug that only manifests on a third application —
    # e.g. an accidental UPSERT that increments something — would slip past
    # a single re-run).
    _rerun_seed_migration(db_connection)
    _rerun_seed_migration(db_connection)

    counts_after = {
        t: db_connection.execute(text(f"SELECT count(*) FROM rules.{t}")).scalar() for t in tables
    }
    assert counts_after == counts_before, (
        "Re-running revision 022's upgrade() changed row counts — the seed migration is not "
        "idempotent."
    )


def test_seeded_ruleset_family_and_version_are_edition_neutral(db_connection: Connection) -> None:
    """Revision 034 (PHASE4_REMAINING_ISSUES.md §5, post-closeout §4): the
    family row is edition-neutral display data, and the edition-specific
    text moved to the version row it actually describes. No YAML file
    backs this — it's set inline by revisions 022/034 — so this is the
    directly-asserted structured-seed check for it.

    Second post-closeout review (PHASE4_REMAINING_ISSUES.md §4): asserting
    only "not the old edition-specific string" would still pass for any
    other incorrect wording, so this pins the exact revision-034
    FAMILY_DESCRIPTION text, not just its absence of the old one."""
    ruleset = db_connection.execute(
        text(
            "SELECT ruleset_id, code, display_name, description "
            "FROM rules.rulesets WHERE code = 'dnd5e'"
        )
    ).one()
    assert ruleset.code == "dnd5e"
    assert ruleset.display_name == "D&D 5e"
    assert "2024" not in ruleset.display_name
    assert ruleset.description == (
        "The fifth-edition Dungeons & Dragons ruleset family, spanning multiple "
        "published editions (e.g. 2014, 2024)."
    ), f"family description does not match revision 034's exact text: {ruleset.description!r}"

    version = db_connection.execute(
        text(
            "SELECT version_label, description FROM rules.ruleset_versions "
            "WHERE ruleset_id = :r AND version_label = '2024'"
        ),
        {"r": ruleset.ruleset_id},
    ).one()
    assert version.version_label == "2024"
    assert version.description == "The 2024 revision of the fifth-edition rules.", (
        f"version description should carry the edition-specific meaning, got: "
        f"{version.description!r}"
    )


def test_seeded_skills_resolve_the_correct_ability_by_code(db_connection: Connection) -> None:
    for row in load_seed_data("rules", "skills"):
        ability_code = db_connection.execute(
            text("""
                SELECT a.code FROM rules.skills s
                JOIN rules.abilities a ON a.ability_id = s.ability_id
                WHERE s.code = :code
            """),
            {"code": row["code"]},
        ).scalar()
        assert ability_code == row["ability_code"], (
            f"Seeded skill {row['code']!r} resolves to ability {ability_code!r}, "
            f"expected {row['ability_code']!r}"
        )


def test_seeded_classes_match_their_yaml_values(db_connection: Connection) -> None:
    for row in load_seed_data("rules", "classes"):
        result = db_connection.execute(
            text("""
                SELECT c.hit_die, a.code FROM rules.classes c
                LEFT JOIN rules.abilities a ON a.ability_id = c.primary_ability_id
                WHERE c.code = :code
            """),
            {"code": row["code"]},
        ).one()
        assert result.hit_die == row["hit_die"], (
            f"Seeded class {row['code']!r} has hit_die {result.hit_die}, expected {row['hit_die']}"
        )
        assert result.code == row["primary_ability_code"], (
            f"Seeded class {row['code']!r} resolves primary ability to {result.code!r}, "
            f"expected {row['primary_ability_code']!r}"
        )


def test_seeded_subclasses_resolve_the_correct_class_by_code(db_connection: Connection) -> None:
    for row in load_seed_data("rules", "subclasses"):
        class_code = db_connection.execute(
            text("""
                SELECT c.code FROM rules.subclasses s
                JOIN rules.classes c ON c.class_id = s.class_id
                WHERE s.code = :code
            """),
            {"code": row["code"]},
        ).scalar()
        assert class_code == row["class_code"], (
            f"Seeded subclass {row['code']!r} resolves to class {class_code!r}, "
            f"expected {row['class_code']!r}"
        )


def test_seeded_spells_match_their_yaml_values(db_connection: Connection) -> None:
    for row in load_seed_data("rules", "spells"):
        result = db_connection.execute(
            text("""
                SELECT s.level, s.school, d.code FROM rules.spells s
                LEFT JOIN rules.damage_types d ON d.damage_type_id = s.damage_type_id
                WHERE s.code = :code
            """),
            {"code": row["code"]},
        ).one()
        assert result.level == row["level"]
        assert result.school == row.get("school")
        assert result.code == row.get("damage_type_code")


def test_seeded_features_resolve_their_class_subclass_or_species(
    db_connection: Connection,
) -> None:
    for row in load_seed_data("rules", "features"):
        result = db_connection.execute(
            text("""
                SELECT c.code AS class_code, sc.code AS subclass_code, sp.code AS species_code,
                       f.granted_at_level
                FROM rules.features f
                LEFT JOIN rules.classes c ON c.class_id = f.class_id
                LEFT JOIN rules.subclasses sc ON sc.subclass_id = f.subclass_id
                LEFT JOIN rules.species sp ON sp.species_id = f.species_id
                WHERE f.code = :code
            """),
            {"code": row["code"]},
        ).one()
        assert result.class_code == row.get("class_code")
        assert result.subclass_code == row.get("subclass_code")
        assert result.species_code == row.get("species_code")
        assert result.granted_at_level == row.get("granted_at_level")


@pytest.mark.parametrize(
    "table",
    [
        "abilities",
        "species",
        "damage_types",
        "conditions",
        "creature_types",
        "languages",
        "proficiency_types",
        "resource_definitions",
        "feats",
    ],
)
def test_seeded_flat_rule_content_matches_its_yaml_file(
    db_connection: Connection, table: str
) -> None:
    """The flat rules.* lookups (no cross-references) — same code-set check
    apply_seed's siblings get, extended to every Phase 4 structured file."""
    expected = {row["code"] for row in load_seed_data("rules", table)}
    actual = {
        r[0]
        for r in db_connection.execute(
            text(
                f"SELECT rt.code FROM rules.{table} rt "
                f"JOIN rules.ruleset_versions rv ON rv.ruleset_version_id = rt.ruleset_version_id "
                f"JOIN rules.rulesets r ON r.ruleset_id = rv.ruleset_id "
                f"WHERE r.code = 'dnd5e'"
            )
        )
    }
    assert actual == expected

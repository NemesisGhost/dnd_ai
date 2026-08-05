"""Unit tests for the dnd_ai.persistence.tables package — pure metadata
reflection, no database.

src/dnd_ai/persistence/tables.py was split into a per-domain package
(DEVELOPMENT.md §2.1) to keep the file each schema change touches bounded
instead of one file every phase adds to. These tests guard that the split
stayed mechanical: every schema-qualified table exists, under the same
name, still reachable both from its owning domain module and from the
package's top-level re-export — so `from dnd_ai.persistence.tables
import worlds` (or `metadata`) keeps working exactly as it did against the
monolithic module. 85 tables at the split (Phase 6 entry gates); revision
057 added the narrative.* domain (9 tables) on top of that baseline.
"""

import importlib

import pytest

from dnd_ai.persistence import tables
from dnd_ai.persistence.tables import metadata

pytestmark = pytest.mark.unit

# One entry per table, as (owning domain module, schema-qualified name).
# Captured from the pre-split monolithic tables.py; changing a table's
# owning module here should only ever be a deliberate move, never a side
# effect of an unrelated change.
EXPECTED_TABLES = {
    "audit": ["audit.change_actions", "audit.change_log"],
    "campaign": [
        "campaign.area_connection_state",
        "campaign.area_feature_state",
        "campaign.campaign_parties",
        "campaign.campaigns",
        "campaign.character_conditions",
        "campaign.character_location_history",
        "campaign.character_resources",
        "campaign.character_state",
        "campaign.connection_statuses",
        "campaign.hazard_state",
        "campaign.hazard_statuses",
        "campaign.interactable_state",
        "campaign.interactable_statuses",
        "campaign.location_state",
        "campaign.parties",
        "campaign.party_memberships",
        "campaign.sessions",
        "campaign.timelines",
    ],
    "characters": [
        "character.character_ability_scores",
        "character.character_builds",
        "character.character_class_levels",
        "character.character_descriptions",
        "character.character_features",
        "character.character_known_spells",
        "character.character_languages",
        "character.character_movements",
        "character.character_prepared_spells",
        "character.character_proficiencies",
        "character.character_senses",
        "character.character_spellcasting_profiles",
        "character.characters",
        "character.npcs",
        "character.player_characters",
    ],
    "core": [
        "core.calendar_months",
        "core.calendars",
        "core.canon_statuses",
        "core.entities",
        "core.entity_names",
        "core.entity_tags",
        "core.entity_types",
        "core.lifecycle_statuses",
        "core.name_types",
        "core.source_types",
        "core.sources",
        "core.tags",
        "core.world_time_precisions",
        "core.world_times",
        "core.worlds",
    ],
    "knowledge": [
        "knowledge.entity_knowledge",
        "knowledge.knowledge_items",
        "knowledge.knowledge_types",
        "knowledge.party_discoveries",
        "knowledge.truth_statuses",
    ],
    "locations": [
        "world.area_connections",
        "world.area_features",
        "world.area_hazards",
        "world.area_interactables",
        "world.buildings",
        "world.connection_types",
        "world.dungeon_areas",
        "world.dungeons",
        "world.locations",
        "world.settlements",
    ],
    "narrative": [
        "narrative.event_causes",
        "narrative.event_effects",
        "narrative.event_locations",
        "narrative.event_observations",
        "narrative.event_participant_roles",
        "narrative.event_participants",
        "narrative.event_statuses",
        "narrative.event_types",
        "narrative.events",
    ],
    "rules": [
        "rules.abilities",
        "rules.classes",
        "rules.conditions",
        "rules.creature_types",
        "rules.damage_types",
        "rules.feats",
        "rules.features",
        "rules.languages",
        "rules.proficiency_types",
        "rules.resource_definitions",
        "rules.ruleset_versions",
        "rules.rulesets",
        "rules.skills",
        "rules.species",
        "rules.spells",
        "rules.subclasses",
        "rules.world_rulesets",
    ],
    "security": ["security.roles", "security.user_roles", "security.users"],
}

EXPECTED_ALL_NAMES = sorted(name for names in EXPECTED_TABLES.values() for name in names)


def test_metadata_has_exactly_the_expected_tables() -> None:
    actual = sorted(t.key for t in metadata.tables.values())
    assert actual == EXPECTED_ALL_NAMES


@pytest.mark.parametrize(
    ("domain_module", "qualified_names"),
    EXPECTED_TABLES.items(),
)
def test_each_table_lives_in_its_expected_domain_module(
    domain_module: str, qualified_names: list[str]
) -> None:
    mod = importlib.import_module(f"dnd_ai.persistence.tables.{domain_module}")
    for qualified_name in qualified_names:
        _, table_name = qualified_name.split(".", 1)
        table_obj = getattr(mod, table_name)
        assert table_obj.key == qualified_name


def test_package_reexports_every_table_by_its_local_name() -> None:
    for qualified_name in EXPECTED_ALL_NAMES:
        _, table_name = qualified_name.split(".", 1)
        assert hasattr(tables, table_name), (
            f"dnd_ai.persistence.tables has no top-level re-export for {table_name!r} "
            f"({qualified_name})"
        )
        assert getattr(tables, table_name).key == qualified_name


def test_all_matches_the_reexported_names() -> None:
    non_table_exports = {
        "metadata",
        "LOOKUP_CODE_COMMENT",
        "NONNEGATIVE_INTEGER",
        "PERCENTAGE_0_100",
        "RATING_1_10",
    }
    table_exports = sorted(set(tables.__all__) - non_table_exports)
    expected_local_names = sorted({name.split(".", 1)[1] for name in EXPECTED_ALL_NAMES})
    assert table_exports == expected_local_names

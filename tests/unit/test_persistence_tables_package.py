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
057 added the narrative.* domain (9 tables), and revision 061 added the
interaction.* domain (8 tables), on top of that baseline. Revision 073
added the Phase 7 quest domain (9 narrative.* tables plus 4 campaign.*
quest/objective state tables) and knowledge-domain expansion (5 new
knowledge.* tables), for 120 tables total. Revision 074 (a Phase 7
correction pass) added campaign.party_knowledge, for 121 tables total.
Revision 075 added the Phase 8 relationships/organizations domain (18
new world.* tables in a new relationships domain module, 4 new
campaign.* organization/relationship state tables, and 1 new
character.* table), for 144 tables total. Revisions 077-079 added the Phase 9
item, encounter, and integration domains. Revision 080 reshaped security.users
and replaced the old global security.roles/security.user_roles pair with the
Phase 10 campaign-scoped security schema (13 new tables, 1 table dropped).
Revision 082 (a Phase 10 workstream 6 correction pass) added
security.idempotent_requests. Revision 087 (Phase 10 workstream 32) added
security.timeline_bootstrap_grants. Revision 088 (Phase 10 workstream 33)
added security.campaign_creation_reservations. Revisions 093-094 (Phase 12)
added the ai.* agent/prompt/context/proposal domain (10 tables), the
ai.reference_* rules-corpus retrieval tables (4 tables), and
core.source_documents (1 table) — a same-phase correction pass, since the
original delivery never added them to this package's own metadata mirror at
all (caught only once alembic check was actually run against these
revisions). Revision 099 (Phase 11R workstream A/B) added the security.*
local-authentication domain (4 tables) plus security.users.
is_platform_administrator. Revision 100 (Phase 11R workstream D) added a
new foundry_pairing domain module (4 security.foundry_* tables) for hashed
pairing codes, per-device credentials, and access tokens.
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
    "ai": [
        "ai.agent_assignments",
        "ai.agent_roles",
        "ai.agents",
        "ai.change_reviews",
        "ai.context_requests",
        "ai.context_snapshots",
        "ai.generated_outputs",
        "ai.prompt_fragments",
        "ai.prompt_templates",
        "ai.proposed_changes",
        "ai.reference_passages",
        "ai.reference_retrieval_results",
        "ai.reference_retrievals",
        "ai.reference_source_campaigns",
    ],
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
        "campaign.objective_state",
        "campaign.objective_statuses",
        "campaign.organization_state",
        "campaign.organization_statuses",
        "campaign.parties",
        "campaign.party_knowledge",
        "campaign.party_memberships",
        "campaign.quest_state",
        "campaign.quest_statuses",
        "campaign.relationship_state",
        "campaign.relationship_statuses",
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
        "character.character_religious_affiliations",
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
        "core.source_documents",
        "core.source_types",
        "core.sources",
        "core.tags",
        "core.world_time_precisions",
        "core.world_times",
        "core.worlds",
    ],
    "encounters": [
        "interaction.combat_actions",
        "narrative.encounter_participants",
        "narrative.encounter_rounds",
        "narrative.encounter_turns",
        "narrative.encounters",
    ],
    "foundry_pairing": [
        "security.foundry_access_tokens",
        "security.foundry_connections",
        "security.foundry_devices",
        "security.foundry_pairing_codes",
    ],
    "integration": [
        "integration.delivery_attempts",
        "integration.external_identifiers",
        "integration.external_systems",
        "integration.sync_jobs",
        "integration.sync_state",
    ],
    "interaction": [
        "interaction.actions",
        "interaction.check_requests",
        "interaction.check_results",
        "interaction.consequences",
        "interaction.external_messages",
        "interaction.interaction_types",
        "interaction.interactions",
        "interaction.targets",
    ],
    "items": [
        "campaign.inventory_entries",
        "campaign.item_attunements",
        "campaign.item_ownership",
        "campaign.item_state",
        "knowledge.item_identification",
        "rules.item_categories",
        "rules.item_definitions",
        "world.item_containers",
        "world.item_instances",
    ],
    "knowledge": [
        "knowledge.character_expertise",
        "knowledge.entity_knowledge",
        "knowledge.expertise_domains",
        "knowledge.information_transfers",
        "knowledge.knowledge_items",
        "knowledge.knowledge_types",
        "knowledge.knowledge_versions",
        "knowledge.party_discoveries",
        "knowledge.public_knowledge",
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
        "narrative.objective_dependencies",
        "narrative.objective_types",
        "narrative.quest_objectives",
        "narrative.quest_outcomes",
        "narrative.quest_participants",
        "narrative.quest_rewards",
        "narrative.quest_stages",
        "narrative.quests",
        "narrative.story_arcs",
    ],
    "relationships": [
        "world.businesses",
        "world.employment_relationships",
        "world.family_relationships",
        "world.governments",
        "world.military_units",
        "world.organization_memberships",
        "world.organization_types",
        "world.organizations",
        "world.ownership_relationships",
        "world.political_factions",
        "world.political_relationships",
        "world.relationship_participant_roles",
        "world.relationship_participants",
        "world.relationship_perspectives",
        "world.relationship_types",
        "world.relationships",
        "world.religions",
        "world.religious_organizations",
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
    "security": [
        "security.access_group_memberships",
        "security.access_groups",
        "security.browser_sessions",
        "security.campaign_creation_reservations",
        "security.campaign_invitations",
        "security.campaign_memberships",
        "security.capabilities",
        "security.character_relationship_type_capabilities",
        "security.character_relationship_types",
        "security.external_identities",
        "security.idempotent_requests",
        "security.local_credentials",
        "security.membership_character_relationships",
        "security.membership_roles",
        "security.membership_statuses",
        "security.password_reset_tokens",
        "security.resource_grants",
        "security.role_capabilities",
        "security.roles",
        "security.service_accounts",
        "security.timeline_bootstrap_grants",
        "security.user_activation_tokens",
        "security.users",
    ],
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

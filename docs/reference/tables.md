# PostgreSQL table inventory

The imported [SQLAlchemy metadata](../../src/dnd_ai/persistence/tables/__init__.py) at `881786c` declares 228 tables in 12 populated schemas. Bootstrap also creates the reserved `import` schema. Alembic defines roles, triggers, functions, grants and revision history in addition to tables. The revision head is `149_reservation_fk_deferrable`. This is a source inventory. Compare a particular installation with Alembic on that database. [Logical model and invariants](../architecture/DATABASE_MODEL.md) · [Migrations](../../database/migrations/versions/)

## Declared tables

Names below are qualified by the schema in each heading.

### ai

`agent_assignments`, `agent_roles`, `agents`, `change_reviews`, `context_requests`, `context_snapshots`, `generated_outputs`, `prompt_fragments`, `prompt_templates`, `proposed_changes`, `reference_passages`, `reference_retrieval_results`, `reference_retrievals`, `reference_source_campaigns`.

### audit

`change_actions`, `change_log`.

### campaign

`area_connection_state`, `area_feature_state`, `campaign_parties`, `campaigns`, `character_conditions`, `character_location_history`, `character_player_profile_versions`, `character_player_profiles`, `character_public_profile_releases`, `character_public_profiles`, `character_resources`, `character_state`, `connection_statuses`, `hazard_state`, `hazard_statuses`, `interactable_state`, `interactable_statuses`, `inventory_entries`, `item_attunements`, `item_ownership`, `item_state`, `location_state`, `objective_state`, `objective_statuses`, `organization_state`, `organization_statuses`, `parties`, `party_knowledge`, `party_memberships`, `player_profile_fields`, `public_profile_field_origins`, `quest_state`, `quest_statuses`, `relationship_state`, `relationship_statuses`, `session_participants`, `sessions`, `timeline_clocks`, `timelines`.

### character

`character_ability_scores`, `character_builds`, `character_class_levels`, `character_descriptions`, `character_features`, `character_known_spells`, `character_languages`, `character_movements`, `character_prepared_spells`, `character_proficiencies`, `character_religious_affiliations`, `character_senses`, `character_spellcasting_profiles`, `characters`, `npc_portrayal_profiles`, `npcs`, `player_characters`.

### core

`calendar_months`, `calendars`, `canon_statuses`, `entities`, `entity_names`, `entity_revisions`, `entity_source_links`, `entity_tags`, `entity_types`, `lifecycle_statuses`, `name_types`, `source_documents`, `source_types`, `sources`, `tags`, `world_time_precisions`, `world_times`, `worlds`.

### integration

`delivery_attempts`, `external_identifiers`, `external_systems`, `sync_jobs`, `sync_state`.

### interaction

`actions`, `check_requests`, `check_results`, `combat_actions`, `consequences`, `external_messages`, `interaction_types`, `interactions`, `targets`.

### knowledge

`character_expertise`, `entity_knowledge`, `expertise_domains`, `information_transfers`, `item_identification`, `knowledge_items`, `knowledge_types`, `knowledge_versions`, `party_discoveries`, `public_knowledge`, `truth_statuses`.

### narrative

`clock_advance_details`, `encounter_participants`, `encounter_rounds`, `encounter_turns`, `encounters`, `event_causes`, `event_corrections`, `event_effects`, `event_locations`, `event_observations`, `event_participant_roles`, `event_participants`, `event_statuses`, `event_types`, `events`, `objective_dependencies`, `objective_types`, `quest_objectives`, `quest_outcomes`, `quest_participants`, `quest_rewards`, `quest_stages`, `quests`, `story_arcs`.

### rules

`abilities`, `classes`, `conditions`, `creature_types`, `damage_types`, `feats`, `features`, `item_categories`, `item_definitions`, `languages`, `proficiency_types`, `resource_definitions`, `ruleset_versions`, `rulesets`, `skills`, `species`, `spells`, `subclasses`, `world_rulesets`.

### security

`access_group_memberships`, `access_groups`, `actor_idempotent_requests`, `browser_sessions`, `campaign_creation_reservations`, `campaign_invitations`, `campaign_memberships`, `capabilities`, `character_relationship_type_capabilities`, `character_relationship_types`, `character_reveal_delegations`, `character_revelation_members`, `character_revelations`, `external_identities`, `foundry_access_tokens`, `foundry_connections`, `foundry_devices`, `foundry_pairing_codes`, `idempotent_requests`, `invitation_onboarding_sessions`, `local_credentials`, `membership_character_relationships`, `membership_roles`, `membership_statuses`, `password_reset_tokens`, `resource_grants`, `revelation_audience_kinds`, `role_capabilities`, `roles`, `service_accounts`, `system_roles`, `timeline_bootstrap_grants`, `user_activation_tokens`, `user_portal_preferences`, `user_system_roles`, `users`, `world_memberships`, `world_roles`, `world_use_grants`.

### world

`area_connections`, `area_features`, `area_hazards`, `area_interactables`, `buildings`, `businesses`, `connection_types`, `dungeon_areas`, `dungeons`, `employment_relationships`, `family_relationships`, `governments`, `item_containers`, `item_instances`, `locations`, `military_units`, `organization_memberships`, `organization_types`, `organizations`, `ownership_relationships`, `political_factions`, `political_relationships`, `relationship_participant_roles`, `relationship_participants`, `relationship_perspectives`, `relationship_types`, `relationships`, `religions`, `religious_organizations`, `route_relationships`, `settlements`.

## Design names absent from metadata

Fable D4 named these families. Its stated 24 differs from the **25 distinct** absent table names below. A design name describes future or superseded scope and cannot be queried as an installed table.

| Schema | Absent design names | Current disposition |
|---|---|---|
| `character` | `character_controllers`, `npc_agent_assignments`, `npc_boundaries`, `npc_characteristics`, `npc_disclosure_rules`, `npc_goals`, `npc_preferences`, `npc_routine_steps`, `npc_routines` | Historical controller proposal and planned NPC detail. Human access uses scoped membership relationships. ADR 0021 governs the future control model. |
| `campaign` | `entity_overrides`, `npc_emotional_state`, `npc_goal_state` | Planned typed state and overrides. Existing typed state tables have narrower scope. |
| `audit` | `state_transitions`, `approval_history`, `validation_failures`, `agent_activity` | Planned audit structures. Current changes use `audit.change_log` and `audit.change_actions`. |
| `import` | `import_jobs`, `import_sources`, `staged_entities`, `staged_relationships`, `staged_events`, `staged_knowledge`, `entity_matches`, `validation_results`, `promotion_batches` | Planned campaign import staging. Authorized AI reference retrieval uses the built `ai` schema. |

The declared inventory also includes lookup tables and `ai.reference_retrieval_results` omitted from the older logical lists. Planned creature templates, the rules engine and a transactional outbox have their own delivery gates. [Rules foundations](../delivery/rules-foundations.md)

At the audited head, comparison with the previous logical model found 16 declared tables whose fully qualified names were missing from its prose. Along with `ai.reference_retrieval_results`, these were the seven campaign status lookups (`connection_statuses`, `hazard_statuses`, `interactable_statuses`, `objective_statuses`, `organization_statuses`, `quest_statuses` and `relationship_statuses`), `interaction.interaction_types`, `knowledge.knowledge_types`, `knowledge.truth_statuses`, `narrative.event_participant_roles`, `narrative.event_statuses`, `narrative.objective_types`, `rules.item_categories` and `world.organization_types`. All appear in the declared inventory above.

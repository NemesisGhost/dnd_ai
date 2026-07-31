# Persistent World Platform Implementation Plan

## 1. Purpose

This document defines the implementation plan for a new PostgreSQL-backed persistent tabletop roleplaying world platform. The database is being designed from scratch. No existing production data needs to be migrated during the initial implementation.

The system must support:

- Persistent worlds that outlive any individual campaign.
- Multiple campaigns operating in the same world and, when configured, the same timeline.
- Branching timelines for alternate histories and isolated campaign outcomes.
- Player characters and NPCs using the same mechanical character model.
- Additional NPC-only information for portrayal, simulation, world management, and generative AI agents.
- Detailed management of geography, dungeons, quests, organizations, relationships, knowledge, events, items, encounters, and world state.
- Discord, FoundryVTT, API, import, and AI-agent integrations.
- Reliable provenance, approval, visibility, and audit tracking.
- Future import of existing campaign documents and legacy material without weakening the canonical model.

The implementation is intentionally structured around actual play. Every major subsystem must support the central gameplay loop:

```text
Entity definition
    -> effective timeline state
    -> interaction or decision
    -> rules resolution
    -> event
    -> state, knowledge, relationship, and quest changes
    -> updated context for players, GMs, and AI agents
```

---

## 2. Architectural decisions

### 2.1 PostgreSQL is the source of truth

PostgreSQL stores canonical world definitions, mutable timeline state, campaign participation, rules data, knowledge, relationships, quests, interactions, and audit records.

Vector indexes, caches, search services, and generated summaries are derived systems. They must never become the only authoritative copy of world facts.

### 2.2 Use class-table inheritance

Major domain objects use class-table inheritance rather than PostgreSQL native `INHERITS`.

```text
core.entities
    -> character.characters
        -> character.npcs
        -> character.player_characters
    -> world.locations
        -> world.dungeons
        -> world.dungeon_areas
    -> world.organizations
        -> world.businesses
        -> world.governments
    -> world.item_instances
    -> narrative.events
    -> narrative.quests
    -> knowledge.knowledge_items
```

Each subtype row reuses the parent entity UUID as its primary key and foreign key.

This approach provides:

- Normal foreign-key behavior.
- Predictable uniqueness constraints.
- Clear ORM mappings.
- Reliable migrations.
- Explicit subtype boundaries.
- Polymorphic references through `core.entities`.

PostgreSQL native inheritance may be used only for narrow append-only or operational tables after a documented design review.

### 2.3 Worlds, timelines, campaigns, and sessions are separate concepts

- A **world** contains persistent setting definitions.
- A **timeline** contains one evolving history and state of that world.
- A **campaign** is an organized game operating within one timeline.
- A **session** is a unit of play within a campaign.

Multiple campaigns may share a timeline. Events caused by one campaign can therefore affect another campaign.

A timeline may branch from another timeline at a defined event or world time. A branch inherits history up to the branch point and diverges afterward.

### 2.4 Definition and state are separate

The platform must distinguish:

- What an entity fundamentally is.
- Its current state in a timeline.
- What different characters or groups know about it.
- How it reached that state.

For example, a dungeon door definition describes the door and its mechanics. Timeline state records whether it is open, locked, damaged, hidden, or destroyed. Knowledge records whether the party has discovered it. Events explain why its state changed.

### 2.5 Event-assisted state model

The platform will not use pure event sourcing.

- Typed state tables provide fast current-state reads.
- Events provide causality and history.
- Important state changes must reference the event that caused them.
- Replaying every event must not be required for routine queries.

### 2.6 Structured data is authoritative; generated text is derived

AI prompts, summaries, embeddings, and generated descriptions must be derived from structured world data whenever possible.

AI-generated changes begin as proposals unless an explicit policy permits automatic application.

---

## 3. PostgreSQL schema organization

Create the following schemas:

```text
core
security
rules
character
world
campaign
narrative
knowledge
interaction
ai
audit
import
integration
```

### 3.1 Schema responsibilities

| Schema | Responsibility |
|---|---|
| `core` | Worlds, entities, names, sources, statuses, tags, calendars, world time |
| `security` | Users, roles, permissions, access-control policies |
| `rules` | Rulesets and reusable mechanical definitions |
| `character` | Shared character mechanics plus NPC and PC extensions |
| `world` | Locations, organizations, items, relationships, economies, religions |
| `campaign` | Timelines, campaigns, parties, sessions, effective mutable state |
| `narrative` | Events, quests, objectives, encounters, story arcs |
| `knowledge` | Facts, rumors, beliefs, discoveries, expertise, information transfer |
| `interaction` | Player, GM, Foundry, Discord, and AI actions and resolutions |
| `ai` | Agents, context assembly, prompt fragments, embeddings, proposals |
| `audit` | Change history, approvals, validation errors, agent activity |
| `import` | Staging and review for future campaign-data imports |
| `integration` | External-system identifiers, sync state, webhook or polling metadata |

---

## 4. Foundation implementation

### 4.1 PostgreSQL extensions

Initially enable:

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
```

Enable `vector` when the embedding subsystem is implemented:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

Do not require vector support for core gameplay operations.

### 4.2 Shared domains

Create reusable domains for common numeric constraints:

```sql
CREATE DOMAIN core.rating_1_10 AS smallint
CHECK (VALUE BETWEEN 1 AND 10);

CREATE DOMAIN core.percentage_0_100 AS smallint
CHECK (VALUE BETWEEN 0 AND 100);

CREATE DOMAIN core.nonnegative_integer AS integer
CHECK (VALUE >= 0);
```

Additional domains may be added for dice expressions, slugs, normalized codes, and world-time sort keys.

### 4.3 Foundation tables

Implement first:

- `core.worlds`
- `core.entity_types`
- `core.entities`
- `core.entity_names`
- `core.sources`
- `core.canon_statuses`
- `core.lifecycle_statuses`
- `core.tags`
- `core.entity_tags`
- `core.calendars`
- `core.calendar_months`
- `core.world_times`
- `security.users`
- `security.roles`
- `security.user_roles`
- `audit.change_log`

### 4.4 Canon lifecycle

Seed the following canon statuses:

- `draft`
- `proposed`
- `approved`
- `canon`
- `superseded`
- `rejected`
- `deprecated`

AI agents normally create `proposed` records or proposed changes. GM-authored records may be created directly as `canon` depending on permissions.

### 4.5 Provenance

Every meaningful authored record must reference a source where practical.

Source types include:

- GM entry
- Player entry
- Imported document
- Rulebook or SRD
- FoundryVTT
- Discord
- Session transcript
- AI-generated proposal
- Migration or seed data
- External API

---

## 5. World, timeline, campaign, party, and session implementation

### 5.1 Worlds

A world is the durable top-level setting container.

Required fields include:

- `world_id`
- name
- description
- default calendar
- default ruleset
- lifecycle status
- created and updated timestamps

### 5.2 Timelines

Implement `campaign.timelines` with:

- `timeline_id`
- `world_id`
- name
- optional parent timeline
- optional branch event
- optional branch world time
- primary-timeline flag
- status
- creation metadata

Rules:

- A timeline belongs to exactly one world.
- A branch must belong to the same world as its parent.
- A branch point cannot occur after the latest known point inherited from the parent.
- A timeline must not have multiple active primary flags for the same world.

### 5.3 Campaigns

Implement `campaign.campaigns` with:

- `campaign_id`
- `timeline_id`
- name
- description
- campaign status
- selected ruleset configuration
- start and end timestamps

Campaigns do not own world entities. They reference entities through participation, discovery, state, and event records.

### 5.4 Parties

Implement:

- `campaign.parties`
- `campaign.party_memberships`
- `campaign.campaign_parties`

A party may persist across campaigns. Memberships must be temporal so characters can join, leave, disappear, or return.

### 5.5 Sessions

Implement `campaign.sessions` with:

- campaign
- session number
- title
- real start and end timestamps
- starting and ending world times
- status
- summary
- source references

Session summaries are derived artifacts and may be revised without changing underlying events.

---

## 6. Ruleset implementation

### 6.1 Ruleset separation

Rule definitions must not be embedded directly in world instances.

Implement:

- `rules.rulesets`
- `rules.ruleset_versions`
- `rules.abilities`
- `rules.skills`
- `rules.classes`
- `rules.subclasses`
- `rules.features`
- `rules.feats`
- `rules.spells`
- `rules.conditions`
- `rules.damage_types`
- `rules.item_definitions`
- `rules.creature_types`
- `rules.languages`
- `rules.proficiency_types`

All rule definitions must identify their ruleset and version.

### 6.2 Homebrew support

Homebrew definitions must be first-class records with provenance and canon status. They must not require changes to core tables.

### 6.3 Derived calculations

Implement calculation services for:

- proficiency bonus
- ability modifiers
- armor class
- passive scores
- spell attack and save DC
- carrying capacity
- movement
- maximum hit points

Persist snapshots only when useful for performance, imports, or historical reconstruction. Store the calculation version with each snapshot.

---

## 7. Shared character implementation

### 7.1 Character hierarchy

Implement:

```text
core.entities
    -> character.characters
        -> character.npcs
        -> character.player_characters
```

Potential later character subtypes include companions, familiars, summons, and special creature actors. These should reuse `character.characters` when they require full character mechanics.

### 7.2 Shared character data

Implement:

- `character.characters`
- `character.character_descriptions`
- `character.character_builds`
- `character.character_ability_scores`
- `character.character_classes`
- `character.character_proficiencies`
- `character.character_features`
- `character.character_spellcasting_profiles`
- `character.character_known_spells`
- `character.character_prepared_spells`
- `character.character_languages`
- `character.character_senses`
- `character.character_movements`

### 7.3 Timeline state

Implement timeline-scoped mutable state:

- `campaign.character_state`
- `campaign.character_resources`
- `campaign.character_conditions`
- `campaign.character_location_history`
- `campaign.character_inventory`

Character state includes:

- current and maximum hit points
- temporary hit points
- death-save state where applicable
- exhaustion
- initiative state when in an encounter
- current location
- active conditions
- expended resources
- current form or transformation

### 7.4 Character control

Implement `character.character_controllers` to support:

- player-controlled characters
- GM-controlled characters
- AI-controlled NPCs
- temporary player control of companions
- session-specific control changes

Control assignments must be campaign- or timeline-aware.

---

## 8. NPC world-management implementation

NPCs use the full shared character model and add information required for portrayal and simulation.

Implement:

- `character.npcs`
- `character.npc_portrayal_profiles`
- `character.npc_characteristics`
- `character.npc_goals`
- `character.npc_routines`
- `character.npc_routine_steps`
- `character.npc_preferences`
- `character.npc_boundaries`
- `character.npc_emotional_state`
- `character.npc_agent_assignments`

### 8.1 Simulation levels

Seed simulation levels such as:

- background
- minor
- supporting
- major
- central
- fully simulated

Simulation level controls how much data is required and how often the system evaluates routines, goals, relationships, and reactions.

### 8.2 Portrayal profiles

Portrayal profiles are versioned and include:

- speech style
- voice description
- vocabulary
- mannerisms
- emotional baseline
- conversational habits
- topics avoided
- disclosure boundaries
- roleplay guidance

The AI context service assembles prompts from the current portrayal profile and current state rather than relying on one unstructured personality prompt.

### 8.3 Goals

Goals may be world-level or timeline-specific. Each goal includes:

- owner NPC
- description
- goal type
- priority
- status
- target entities
- progress
- secrecy or visibility policy
- initiating event
- completion or failure event
- dependencies

---

## 9. Geography and dungeon implementation

### 9.1 Location hierarchy

Implement:

```text
core.entities
    -> world.locations
        -> world.regions
        -> world.settlements
        -> world.districts
        -> world.buildings
        -> world.dungeons
        -> world.dungeon_areas
        -> world.geographic_features
```

`world.locations` includes a parent-location reference for containment. Universal relationships handle adjacency, claims, portals, trade routes, and disputed control.

### 9.2 Dungeon structures

Implement:

- `world.dungeons`
- `world.dungeon_areas`
- `world.area_connections`
- `world.area_features`
- `world.area_hazards`
- `world.area_interactables`
- `world.area_spawn_definitions`

Area connections support:

- normal doors
- secret doors
- passages
- portals
- stairs and ladders
- pits
- bridges
- one-way routes
- conditional routes

### 9.3 Dungeon timeline state

Implement:

- `campaign.location_state`
- `campaign.area_connection_state`
- `campaign.area_feature_state`
- `campaign.hazard_state`
- `campaign.interactable_state`

Examples of tracked state:

- door open, closed, locked, broken, or destroyed
- connection known or undiscovered
- trap armed, triggered, reset, bypassed, or disarmed
- room searched
- shrine activated
- bridge collapsed
- chamber flooded
- alarm level
- power-state transitions

### 9.4 Discovery versus existence

A hidden feature exists independently of whether a party knows about it.

Do not store `is_discovered` as a global property of a feature. Discovery belongs in the knowledge system and may differ by party or character.

---

## 10. Universal relationship implementation

Implement:

- `world.relationship_types`
- `world.relationships`
- `world.relationship_participants`
- `world.relationship_perspectives`

Relationships may connect any entities.

Examples:

- NPC parent of NPC
- NPC member of organization
- organization controls settlement
- item owned by NPC
- religion reveres deity
- city capital of nation
- dungeon area connected to dungeon area

### 10.1 Objective versus subjective data

The base relationship stores shared facts and history. Perspectives store how each participant perceives the relationship.

Perspective measurements may include:

- affinity
- trust
- respect
- fear
- obligation
- emotional tone
- private interpretation

### 10.2 Specialized relationship subtypes

Use class-table inheritance for relationship details when required:

- `world.organization_memberships`
- `world.employment_relationships`
- `world.ownership_relationships`
- `world.family_relationships`
- `world.political_relationships`

---

## 11. Organization, government, business, and religion implementation

### 11.1 Organization hierarchy

Implement:

```text
core.entities
    -> world.organizations
        -> world.businesses
        -> world.governments
        -> world.religious_organizations
        -> world.military_units
        -> world.political_factions
```

### 11.2 Organizations

Store:

- organization type
- founded and dissolved world times
- headquarters
- parent organization
- public description
- internal description
- status

Membership is represented as a specialized relationship and supports multiple roles, rejoining, secret membership, ranks, and historical periods.

### 11.3 Religion distinction

A religion is a belief system. A church, temple, order, or cult is an organization.

Implement:

- `world.religions`
- `world.religious_organizations`
- `character.character_religious_affiliations`

Personal belief, organizational rank, and employment must not be conflated.

---

## 12. Items, inventory, ownership, and treasure implementation

### 12.1 Definitions and instances

- `rules.item_definitions` stores reusable mechanical definitions.
- `world.item_instances` stores particular objects in the world.

A generic longsword is a definition. A named legendary sword is an entity and item instance.

### 12.2 Item state

Implement:

- `campaign.item_state`
- `campaign.character_inventory`
- `world.item_containers`
- `knowledge.item_identification`

Track:

- location
- possessor
- owner
- container
- quantity
- charges
- damage or condition
- attunement
- equipped state
- identification level
- hidden properties

Ownership and possession are distinct concepts.

---

## 13. Event implementation

### 13.1 Events as first-class entities

Implement:

- `narrative.events`
- `narrative.event_participants`
- `narrative.event_locations`
- `narrative.event_causes`
- `narrative.event_effects`
- `narrative.event_observations`

An event belongs to a timeline and may reference a campaign and session when produced during play.

### 13.2 Event effects

Effects identify:

- target entity
- affected component
- old value
- new value
- effective world time
- application status

Common effects should also update typed state tables in the same transaction.

### 13.3 Event granularity

Not every attack roll must become a permanent world event.

Use interaction and encounter logs for high-volume tactical actions. Promote meaningful outcomes to narrative events, such as:

- a character is killed
- a ward is disabled
- a room is flooded
- an artifact is destroyed
- an NPC is rescued
- a faction becomes hostile
- a quest stage is completed

---

## 14. Quest and narrative implementation

Implement:

- `narrative.story_arcs`
- `narrative.quests`
- `narrative.quest_stages`
- `narrative.quest_objectives`
- `narrative.objective_dependencies`
- `narrative.quest_participants`
- `narrative.quest_rewards`
- `narrative.quest_outcomes`
- `campaign.quest_state`
- `campaign.objective_state`

### 14.1 Quest definitions and progress

Quest definitions are persistent narrative content. Progress is timeline- or campaign-party-specific.

Objectives support:

- required, optional, and hidden status
- dependencies
- target entities
- quantities
- completion-rule metadata
- visibility policies
- automatic or GM-confirmed completion

### 14.2 Event-driven advancement

Events may advance objectives through explicitly defined mappings or rule evaluation.

Examples:

- entering an area completes a travel objective
- activating three pylons completes a restoration objective
- learning a confirmed fact completes an investigation objective
- an NPC death fails a protection objective

All automated objective transitions must record the triggering event.

---

## 15. Knowledge, belief, rumor, and discovery implementation

Implement:

- `knowledge.knowledge_items`
- `knowledge.knowledge_versions`
- `knowledge.entity_knowledge`
- `knowledge.information_transfers`
- `knowledge.expertise_domains`
- `knowledge.character_expertise`
- `campaign.party_knowledge`
- `campaign.knowledge_discoveries`

### 15.1 Knowledge types

Seed:

- fact
- rumor
- secret
- belief
- theory
- prophecy
- misconception
- instruction
- memory
- doctrine

### 15.2 Truth and belief

A knowledge item stores the canonical claim and truth status. Entity knowledge stores what a knower believes, confidence, interpretation, source, and willingness to share.

A false belief is valid game data and must not be overwritten merely because the canonical truth is known to the GM.

### 15.3 Discovery model

Searching, perception, dialogue, documents, and events produce discoveries.

Discovery may be recorded for:

- an individual character
- a party
- an organization
- the public within a location or region

### 15.4 Information propagation

Information transfers record:

- source knower
- recipient
- transferred knowledge
- modified interpretation
- interaction or event
- world time

This supports rumor propagation and misinformation.

---

## 16. Interaction and resolution implementation

Implement:

- `interaction.interactions`
- `interaction.actions`
- `interaction.targets`
- `interaction.check_requests`
- `interaction.check_results`
- `interaction.consequences`
- `interaction.external_messages`

Interactions include:

- searching
- movement
- lockpicking
- conversation
- attacks
- spellcasting
- resting
- travel
- using an item
- activating mechanisms
- reading inscriptions

### 16.1 Resolution flow

```text
Create interaction
    -> determine required checks
    -> resolve rules
    -> create observations and consequences
    -> create significant event where appropriate
    -> update state, knowledge, relationships, and quests
```

### 16.2 External integration

Discord and Foundry actions must create or reference interaction records rather than writing directly to arbitrary tables.

---

## 17. Encounter and combat implementation

Implement:

- `narrative.encounters`
- `narrative.encounter_participants`
- `narrative.encounter_turns`
- `narrative.encounter_rounds`
- `interaction.combat_actions`

FoundryVTT may remain the detailed tactical authority during live combat. The database should capture synchronized state and meaningful outcomes.

Persist enough detail to support:

- initiative and turn order
- current HP and conditions
- resource consumption
- encounter participants
- defeated, escaped, surrendered, or captured outcomes
- encounter summary
- resulting events

---

## 18. AI-agent implementation

Implement:

- `ai.agents`
- `ai.agent_roles`
- `ai.agent_assignments`
- `ai.prompt_templates`
- `ai.prompt_fragments`
- `ai.context_requests`
- `ai.context_snapshots`
- `ai.generated_outputs`
- `ai.proposed_changes`
- `ai.change_reviews`
- `ai.embedding_records`

### 18.1 Agent roles

Initial roles:

- NPC portrayal agent
- dungeon-state agent
- quest manager
- rules assistant
- world-state manager
- lore consistency checker
- session summarizer
- rumor propagation agent

### 18.2 Controlled mutation

Agents do not write directly to canonical tables.

They submit proposed commands or structured changes. A policy engine determines whether a proposal:

- may be applied automatically
- requires GM approval
- is rejected by validation

Low-risk automatic examples:

- marking an already-authored hidden feature as discovered
- recording conversational memory
- advancing a deterministic counter from 1/3 to 2/3

High-impact approval-required examples:

- character death
- settlement destruction
- faction-control changes
- permanent quest failure
- creation of major new canon

---

## 19. Effective-state resolution

### 19.1 Resolution order

For a requested entity and timeline:

1. Active typed timeline state.
2. Inherited state from parent timeline up to the branch point.
3. Canonical entity definition.
4. Ruleset defaults where applicable.

### 19.2 Typed state first

Use typed tables for frequently accessed state. Avoid placing all mutable values into a generic JSON override table.

A generic `campaign.entity_overrides` table may exist as an escape hatch for experimental or rarely queried properties, but must not replace typed designs.

### 19.3 Query services

Implement stable SQL functions or repository services such as:

- `get_effective_character_state`
- `get_effective_location_state`
- `get_effective_connection_state`
- `get_effective_item_state`
- `get_effective_quest_state`
- `get_entity_context_for_agent`

Do not expose inheritance and branch resolution logic separately in every application component.

---

## 20. Transaction and command model

Use application commands or PostgreSQL service functions for multi-table operations.

Initial commands include:

- `CreateWorld`
- `CreateTimeline`
- `BranchTimeline`
- `CreateCampaign`
- `CreateParty`
- `StartSession`
- `CreateCharacter`
- `CreateNpc`
- `CreateLocation`
- `CreateDungeon`
- `CreateQuest`
- `EnterLocation`
- `PerformInteraction`
- `ResolveCheck`
- `ApplyEvent`
- `AdvanceQuest`
- `RevealKnowledge`
- `EndSession`

Each command must:

1. Validate security and references.
2. Validate world and timeline consistency.
3. Open a transaction.
4. Create provenance and event records where required.
5. Update typed state.
6. Update knowledge, relationships, and quest state.
7. Write audit records.
8. Queue asynchronous AI, search, or integration work.
9. Commit atomically.

---

## 21. Audit and validation implementation

Implement:

- `audit.change_log`
- `audit.state_transitions`
- `audit.validation_failures`
- `audit.agent_activity`
- `audit.approval_history`

Required invariants include:

- Every subtype has a valid parent entity.
- The entity type matches the subtype.
- Cross-entity references remain within compatible worlds.
- Timeline state references entities from the timeline's world.
- Exactly one current state row exists for a typed entity/timeline combination where required.
- Timeline branch points are valid.
- Applied event effects and typed state updates remain consistent.
- Objective transitions follow allowed status transitions.
- AI-applied changes reference an approval policy and proposal.

Use constraints and triggers for local invariants. Use service-layer validation for complex cross-domain invariants.

---

## 22. Future import implementation

Although the initial database is empty, build import boundaries before importing existing campaign material.

Implement later:

- `import.import_jobs`
- `import.import_sources`
- `import.staged_entities`
- `import.staged_relationships`
- `import.staged_events`
- `import.staged_knowledge`
- `import.entity_matches`
- `import.validation_results`
- `import.approval_batches`

Import flow:

```text
Source documents
    -> extraction
    -> staged candidates
    -> entity matching and deduplication
    -> validation
    -> GM review
    -> approved commands
    -> canonical world records
```

Imported text must not directly create canon without review.

---

## 23. Delivery phases

### Phase 0: Documentation and decision records

Deliver:

- `plan.md`
- `DOMAIN_MODEL.md`
- `DATABASE_CONVENTIONS.md`
- later entity relationship diagrams
- command/API specifications
- state-resolution specification
- AI mutation-policy specification

Exit criteria:

- Major domain boundaries agreed.
- Naming and inheritance strategy agreed.
- Timeline semantics agreed.

### Phase 1: Database bootstrap

Deliver:

- PostgreSQL project structure
- migration framework
- schemas
- extensions
- shared domains
- seed infrastructure
- CI migration validation

Exit criteria:

- Empty database can be created reproducibly.
- Migrations can run up and down in development.
- Schema validation runs in CI.

### Phase 2: Core world platform

Deliver:

- worlds
- entity types
- entities
- names
- sources
- statuses
- tags
- calendars and world times
- users and basic security
- audit log

Exit criteria:

- A world and arbitrary entity can be created with provenance.
- Entity subtype consistency is enforceable.

### Phase 3: Timelines and campaigns

Deliver:

- timelines
- campaign branching metadata
- campaigns
- parties
- memberships
- sessions

Exit criteria:

- Two campaigns can share one timeline.
- A timeline can branch from another timeline.

### Phase 4: Rules and shared characters

Deliver:

- initial D&D ruleset definitions
- characters
- NPCs
- PCs
- builds
- abilities
- classes
- proficiencies
- combat state
- conditions
- resources

Exit criteria:

- NPC and PC use the same mechanical model.
- A character sheet can be assembled from structured data.

### Phase 5: Locations and dungeon play

Deliver:

- locations
- dungeons
- areas
- connections
- features
- hazards
- interactables
- location and feature state
- discovery records

Exit criteria:

- A party can enter and navigate a multi-room dungeon.
- Hidden connections remain distinct from party knowledge.
- Actions can alter dungeon state.

### Phase 6: Events and interactions

Deliver:

- interactions
- checks
- events
- effects
- current-state updates
- event causality

Exit criteria:

- A player action can resolve into an event and atomic state changes.
- Current state and event history remain consistent.

### Phase 7: Quests and knowledge

Deliver:

- quests
- stages
- objectives
- outcomes
- quest state
- knowledge items
- entity knowledge
- discoveries
- information transfer

Exit criteria:

- Dungeon events can advance or fail quest objectives.
- Party knowledge differs from canonical truth.

### Phase 8: Relationships and organizations

Deliver:

- universal relationships
- perspectives
- organizations
- memberships
- businesses
- governments
- religions

Exit criteria:

- NPC and faction reactions can evolve from events.
- Shared and subjective relationship data are separate.

### Phase 9: Items, inventory, encounters, and Foundry synchronization

Deliver:

- item definitions and instances
- inventory and ownership
- encounters
- combat outcome synchronization
- Foundry identifiers and sync records

Exit criteria:

- Foundry combat can update persistent character and world state.

### Phase 10: AI and Discord integration

Deliver:

- AI agents
- context assembly
- proposals and approvals
- embeddings
- Discord interaction mapping
- NPC dialogue context

Exit criteria:

- An NPC agent receives only appropriate knowledge and state.
- AI changes cannot bypass approval and validation rules.

### Phase 11: Import tools

Deliver:

- extraction staging
- deduplication
- review workflow
- import commands

Exit criteria:

- Existing campaign documents can be imported through a controlled review process.

---

## 24. Vertical-slice acceptance scenario

The first end-to-end vertical slice should implement the following scenario:

1. Create a world and primary timeline.
2. Create a campaign, party, session, two characters, and one NPC.
3. Create a dungeon with three connected areas.
4. Create a hidden door, trap, mechanism, and quest.
5. Move the party into the dungeon.
6. Search an area and discover the trap but not the hidden door.
7. Resolve a check that discovers the hidden door.
8. Trigger or disarm the trap.
9. Activate a mechanism.
10. Advance the quest objective.
11. Talk to the NPC and receive restricted knowledge.
12. End the session and generate a summary.
13. Open a second campaign on the same timeline and verify that it sees altered dungeon state but not the first party's private knowledge.
14. Branch a new timeline before the first campaign's dungeon entry and verify that the dungeon remains untouched there.

This scenario is the primary architectural test. A design that cannot support it cleanly must be revised before broader implementation.

---

## 25. Testing strategy

### 25.1 Database tests

Test:

- constraints
- subtype consistency
- same-world invariants
- timeline inheritance
- state uniqueness
- branch behavior
- event/state atomicity
- quest transition rules
- visibility rules

### 25.2 Service tests

Test commands as transactions, including rollback on partial failure.

### 25.3 Scenario tests

Use dungeon and quest scenarios to validate cross-domain behavior.

### 25.4 Property-based tests

Use property-based testing for:

- timeline resolution
- relationship participant combinations
- event-effect application
- quest dependency graphs
- world-time ordering

### 25.5 Performance tests

Measure:

- effective-state queries
- NPC context assembly
- dungeon-map retrieval
- session event ingestion
- knowledge filtering
- branch resolution

---

## 26. Operational strategy

### 26.1 Migrations

Use versioned migrations from the first commit. Alembic is recommended for the Python service, with explicit SQL migrations for PostgreSQL-specific features.

Never use destructive `DROP TABLE ... CASCADE` initialization scripts outside disposable development databases.

### 26.2 Environments

Maintain separate:

- local development
- automated test
- integration
- staging
- production

### 26.3 Backups

Before production use, configure:

- automated RDS backups
- point-in-time recovery
- periodic restore tests
- export of critical world and campaign records

### 26.4 Observability

Track:

- command failures
- transaction duration
- event throughput
- AI proposal approval rates
- integration sync errors
- slow effective-state queries
- import validation failures

---

## 27. Deferred decisions

The following should remain deferred until their dedicated design documents:

- exact REST or GraphQL API shape
- exact Foundry module protocol
- encounter-log retention policy
- whether every knowledge item is an entity
- materialized-view strategy
- physical partitioning strategy
- graph database replication
- economy simulation depth
- weather simulation depth
- procedural-content generation policy
- multi-world campaigns

Deferred decisions must not be implemented implicitly through ad hoc columns.

---

## 28. Definition of implementation success

The initial platform is successful when it can:

- Represent a persistent world independently of campaigns.
- Run multiple campaigns in the same timeline.
- Branch alternate timelines without copying the entire world.
- Represent NPCs and PCs with shared mechanics.
- Add NPC-specific portrayal and simulation data.
- Model a dungeon independently from its mutable state and discovery.
- Turn player actions into validated interactions, events, and state changes.
- Advance quests from world events.
- Distinguish truth from character and party knowledge.
- Preserve causality and audit history.
- Provide safe, structured context to AI agents.
- Prevent AI-generated content from silently becoming canon.
- Accept future imported campaign material through a controlled staging and review process.

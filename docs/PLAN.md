# Persistent World Platform Implementation Plan

## Table of Contents

- [1. Purpose](#1-purpose)
- [2. Architectural decisions](#2-architectural-decisions)
- [3. PostgreSQL schema organization](#3-postgresql-schema-organization)
- [4. Foundation implementation](#4-foundation-implementation)
- [5. World, timeline, campaign, party, and session implementation](#5-world-timeline-campaign-party-and-session-implementation)
- [6. Ruleset implementation](#6-ruleset-implementation)
- [7. Shared character implementation](#7-shared-character-implementation)
- [8. NPC world-management implementation](#8-npc-world-management-implementation)
- [9. Geography and dungeon implementation](#9-geography-and-dungeon-implementation)
- [10. Universal relationship implementation](#10-universal-relationship-implementation)
- [11. Organization, government, business, and religion implementation](#11-organization-government-business-and-religion-implementation)
- [12. Items, inventory, ownership, and treasure implementation](#12-items-inventory-ownership-and-treasure-implementation)
- [13. Event implementation](#13-event-implementation)
- [14. Quest and narrative implementation](#14-quest-and-narrative-implementation)
- [15. Knowledge, belief, rumor, and discovery implementation](#15-knowledge-belief-rumor-and-discovery-implementation)
- [16. Interaction and resolution implementation](#16-interaction-and-resolution-implementation)
- [17. Encounter and combat implementation](#17-encounter-and-combat-implementation)
- [18. AI-agent implementation](#18-ai-agent-implementation)
- [19. Effective-state resolution](#19-effective-state-resolution)
- [20. Transaction and command model](#20-transaction-and-command-model)
- [21. Audit and validation implementation](#21-audit-and-validation-implementation)
- [22. Future import implementation](#22-future-import-implementation)
- [23. Delivery phases](#23-delivery-phases)
- [24. Vertical-slice acceptance scenario](#24-vertical-slice-acceptance-scenario)
- [25. Testing strategy](#25-testing-strategy)
- [26. Operational strategy](#26-operational-strategy)
- [27. Deferred decisions](#27-deferred-decisions)
- [28. Definition of implementation success](#28-definition-of-implementation-success)
- [29. AWS Terraform deployment plan for PostgreSQL](#29-aws-terraform-deployment-plan-for-postgresql)
- [30. AWS deployment plan for application services](#30-aws-deployment-plan-for-application-services)

---

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

### 23.0 AWS verification policy

Every phase from Phase 1 onward is verified against the deployed AWS `dev` environment, not against a local or containerized stand-in. This applies to that phase's migrations and to its `tests/database`/`tests/scenario` suites. Local Docker PostgreSQL and testcontainers are permitted only when AWS is genuinely unreachable (no network, an account-wide outage) — not as the default inner loop. See [§29.9](#299-aws-first-verification-mechanism) for how this is achieved without weakening `staging`/`prod` isolation, and [DEVELOPMENT.md §6](DEVELOPMENT.md#6-testing) for the resulting test workflow.

`tests/unit` is unaffected — it uses no database at all, so there is nothing to verify against AWS.

The same rule applies to *running* code, not just schema: once a phase delivers a deployable — an API, the background worker, an adapter — that deployable runs on AWS in `dev` and is exercised there. The compute platform, deployment flow, and the per-phase table of which deployable is expected from when are in [§30](#30-aws-deployment-plan-for-application-services); the decision behind all of it is [ADR 0008](adr/0008-aws-first-deployment-and-verification.md).

A phase's exit criteria below are therefore necessary but not sufficient. A phase is done when, additionally:

1. Its migrations have run against the deployed `dev` database.
2. Its `tests/database`/`tests/scenario` suites pass against that database.
3. Its deployables (if any — see [§30.8](#308-per-phase-deployment-expectations)) are running in `dev` and exercised there.

"It passes locally" is not a verification claim this project accepts for anything touching the database or a deployable.

### Phase 0: Documentation and decision records

Deliver:

- `docs/PLAN.md`
- `docs/DOMAIN_MODEL.md`
- `docs/DATABASE_CONVENTIONS.md`
- `docs/ENTITY_LIFECYCLE.md`
- `docs/architecture/SYSTEM_ARCHITECTURE.md`, `DATABASE_MODEL.md`, `DUNGEON_FLOW.md`
- `docs/DEVELOPMENT.md` — toolchain, repository layout, migration and test workflow
- `docs/INFRASTRUCTURE.md` — operating the deployed infrastructure
- later entity relationship diagrams
- command/API specifications
- state-resolution specification
- AI mutation-policy specification
- `docs/adr/` records extracted from [§2](#2-architectural-decisions) (currently stubs)

Exit criteria:

- Major domain boundaries agreed.
- Naming and inheritance strategy agreed.
- Timeline semantics agreed.
- Toolchain and repository layout decided, so implementation does not have to invent them.

### Phase 1: Database bootstrap

Deliver:

- PostgreSQL project structure
- migration framework
- schemas
- extensions
- shared domains
- seed infrastructure
- CI migration validation
- AWS infrastructure to host and reach the database (see [§29](#29-aws-terraform-deployment-plan-for-postgresql))

Exit criteria:

- Empty database can be created reproducibly.
- Migrations can run up and down in development.
- Schema validation runs in CI.
- A migration can be applied end-to-end against a deployed AWS RDS instance using only Terraform-managed infrastructure (no manual console steps).

A step-by-step walkthrough of this phase — project skeleton, Alembic scaffold, bootstrap revision, shared domains, seed infrastructure, CI, migration runner — is in [DEVELOPMENT.md §5](DEVELOPMENT.md#5-phase-1-walkthrough).

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

Use versioned migrations from the first commit. Alembic is the decided tool (see [DATABASE_CONVENTIONS.md §25.1](DATABASE_CONVENTIONS.md#251-migration-tool) and [DEVELOPMENT.md §4](DEVELOPMENT.md#4-database-and-migrations)), with explicit SQL migrations for PostgreSQL-specific features.

Never use destructive `DROP TABLE ... CASCADE` initialization scripts outside disposable development databases.

See [§29.5–§29.7](#29-aws-terraform-deployment-plan-for-postgresql) for how migrations are actually executed against a private AWS RDS instance.

### 26.2 Environments

Maintain separate:

- `dev` (shared, always-on — automated test and day-to-day development both verify against this environment per [§23.0](#230-aws-verification-policy), not a local stand-in)
- staging
- production

Local PostgreSQL (Docker) is a fallback for when AWS is genuinely unreachable, not a maintained environment in its own right.

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

---

## 29. AWS Terraform deployment plan for PostgreSQL

### 29.1 Scope and current state

This section defines how the PostgreSQL database is provisioned, reached, and migrated in AWS, entirely through Terraform. It closes the gap left after the pre-restart Lambda-based deployment tooling was removed (see [README.md § Current Status](../README.md#current-status)).

This section is the **plan** — what the infrastructure should become. [INFRASTRUCTURE.md](INFRASTRUCTURE.md) documents what exists today and how to operate it.

`terraform/modules/database` and `terraform/modules/secrets` already exist and provide:

- An RDS PostgreSQL instance (version pinned via `postgres_version`, currently 15.4), encrypted at rest with a dedicated KMS key.
- A VPC with two private subnets across two availability zones (or reuse of an existing VPC/subnets), a security group scoped to `allowed_cidr_blocks` / `allowed_security_group_ids`, and VPC interface endpoints for Secrets Manager and KMS so private subnets don't need a NAT Gateway by default.
- An AWS-managed master user secret (`manage_master_user_password = true`) — no master password is ever stored in Terraform state or code.
- IAM database authentication enabled on the instance (`iam_database_authentication_enabled = true`), ready for use once application-level roles are created.
- Automated backups, deletion protection, enhanced monitoring, and Performance Insights, all on by default.
- A `secrets` module providing named (value-less) Secrets Manager entries for OpenAI/Discord credentials, sharing the same KMS key.

What this plan still needs to add, and what the rest of this section covers:

- A remote Terraform state backend (currently local state only).
- `staging` and `prod` environment directories (only `dev` exists today).
- A way to create the database roles, schemas, and extensions defined in [docs/DATABASE_CONVENTIONS.md](DATABASE_CONVENTIONS.md) §2–§3, §27 — Terraform provisions the RDS instance but cannot run SQL inside it.
- A way to run Alembic migrations against an RDS instance that has no public access, without a bastion host or committed SSH keys.
- Multi-AZ support in the database module for production.

### 29.2 Remote Terraform state

Local state is acceptable for the current single-developer `dev` exploration but not once `staging`/`prod` exist or more than one person applies changes.

Bootstrap once per AWS account, outside the normal module tree (a backend can't store the state that creates itself):

- A versioned, encrypted S3 bucket for state files.
- A DynamoDB table for state locking (or rely on native S3 conditional-write locking if the pinned Terraform version supports it).

Implementation: a small `terraform/bootstrap/` root module, applied manually once with local state, whose only job is to create the bucket and lock table. Every environment under `terraform/environments/<env>/` then configures:

```hcl
terraform {
  backend "s3" {
    bucket         = "dnd-ai-tfstate"
    key            = "<env>/database.tfstate"
    region         = "us-east-1"
    dynamodb_table = "dnd-ai-tfstate-lock"
    encrypt        = true
  }
}
```

### 29.3 Environments: dev, staging, prod

`terraform/environments/dev/` already exists. `staging/` and `prod/` should be created by copying its structure, not by parameterizing a single environment with conditionals — per-environment tfvars keep blast radius explicit.

| Setting | dev | staging | prod |
|---|---|---|---|
| `publicly_accessible` | optional (`enable_public_access`) | `false` | `false` |
| `instance_class` | `db.t3.micro` | `db.t3.small` or larger | sized after load testing |
| `deletion_protection` | `false` (fast teardown) | `true` | `true` (already the module default) |
| `skip_final_snapshot` | `true` | `false` | `false` (already the module default) |
| `backup_retention_period` | short (3–7 days) | 7 days | 14–30 days |
| Multi-AZ | no | optional | yes (module gap, see §29.8) |

### 29.4 Provisioning order

A `terraform apply` in a given environment builds, in dependency order:

1. VPC, subnets, route tables, security groups (`module.database`, `networking.tf`).
2. KMS key (`module.database`, `secrets.tf`).
3. RDS instance with its AWS-managed master secret (`module.database`, `rds.tf`).
4. Named Secrets Manager entries for external credentials (`module.secrets`).
5. Migration runner infrastructure (`module.db_migration_runner`, new — see §29.6).

### 29.5 Database role, schema, and extension bootstrap

The RDS instance boots with only the master role and an empty database. Terraform cannot reach inside PostgreSQL to run SQL, so a one-time (and re-runnable) bootstrap step must execute before `alembic upgrade head` takes over ongoing schema changes. Treat this bootstrap as the first Alembic revision, not a separate untracked script, so it's versioned the same way as everything else.

The bootstrap must be idempotent and cover:

- Extensions, per [DATABASE_CONVENTIONS.md §2.2](DATABASE_CONVENTIONS.md): `CREATE EXTENSION IF NOT EXISTS pgcrypto;` and `CREATE EXTENSION IF NOT EXISTS pg_trgm;` (`vector` deferred until the embedding subsystem exists).
- All thirteen schemas from [§3](#3-postgresql-schema-organization): `core`, `security`, `rules`, `character`, `world`, `campaign`, `narrative`, `knowledge`, `interaction`, `ai`, `audit`, `import`, `integration`.
- `REVOKE CREATE ON SCHEMA public FROM PUBLIC;` per [DATABASE_CONVENTIONS.md §3.1](DATABASE_CONVENTIONS.md).
- The five database roles from [DATABASE_CONVENTIONS.md §27.1](DATABASE_CONVENTIONS.md):
  - `migration_owner` — owns schema objects; only the migration runner uses it.
  - `app_read_write` — the application's runtime role; DML only, no DDL.
  - `app_read_only` — reporting and read-model queries.
  - `integration_worker` — scoped grants for Foundry/Discord/import-facing services.
  - `admin_maintenance` — break-glass, human use only.
- Each non-migration role created `WITH LOGIN` and `GRANT rds_iam TO <role>;` so applications authenticate with short-lived IAM tokens rather than static passwords — the instance already has `iam_database_authentication_enabled = true`, so no new Secrets Manager entries are needed for these roles (per rule 10 in [CLAUDE.md](../CLAUDE.md)).

### 29.6 Migration execution mechanism

**Problem**: the RDS instance is not publicly reachable (by design, in every environment except an explicit `dev` opt-in), so neither a developer's laptop nor Terraform itself can run `alembic upgrade head` against it directly, and there's no bastion host or committed SSH key in this project.

**Decision**: build a **migration runner** — the Alembic-oriented successor to the retired `db_runner` module — as a new `terraform/modules/db_migration_runner/`:

- A small EC2 instance (or an on-demand SSM-managed instance) inside the same private subnets as the database.
- Invoked via **AWS Systems Manager Run Command** — no bastion, no SSH keys, no public IP, consistent with how `db_runner` worked and with the least-privilege stance in [DATABASE_CONVENTIONS.md §27](DATABASE_CONVENTIONS.md).
- An IAM instance role scoped to `rds-db:connect` for the `migration_owner` database user only (IAM auth, not a stored password).
- Its own security group, attached to the RDS security group via an `aws_security_group_rule` granting itself ingress on 5432 (the same pattern `db_runner` used).
- An S3 bucket holding the versioned Alembic migrations package (`database/` — Alembic env plus revisions), synced by `build.ps1` or CI before each run.

Runtime behavior: `pip install -r requirements.txt && alembic upgrade head`, authenticating via an IAM auth token instead of a password.

This was originally chosen as the lowest-setup-cost option for the project's pre-implementation stage, reusing AWS primitives (EC2, SSM, S3, IAM) already understood from the deleted `db_runner` and requiring no container registry or CI/CD platform decision.

**That deferral is now resolved**: [§30](#30-aws-deployment-plan-for-application-services) commits the project to ECS Fargate, and migrations become a one-off task running the same image as every other service ([§30.2](#302-compute-ecs-fargate), [§30.6](#306-deployment-flow)). The standing EC2 runner described above is therefore a **transitional** mechanism — worth building only if `staging`/`prod` need migrating before the Fargate pipeline exists. If application deployment lands first, skip it entirely and go straight to the one-off task. Either way, `dev` does not need it: `dev` migrations run directly per [§29.9](#299-aws-first-verification-mechanism).

### 29.7 Deployment runbook

1. One-time per AWS account: apply `terraform/bootstrap/` to create the remote state bucket and lock table (§29.2).
2. `terraform init` (pointed at the remote backend) and `terraform apply` in `terraform/environments/<env>/` — provisions the VPC, RDS instance, KMS key, secrets, and migration runner.
3. Package and sync the Alembic migrations project to the migration runner's S3 bucket.
4. Trigger the migration runner via SSM Run Command (wrapped by `build.ps1` or CI) — runs the bootstrap revision (roles, schemas, extensions) followed by any pending `alembic upgrade head`.
5. Verify: connect using an IAM auth token as `app_read_only`, confirm all thirteen schemas exist and the Alembic version table reflects the expected head revision.
6. For every subsequent schema change: new Alembic revision → re-sync the package → re-trigger the runner. This manual loop is the seed of what should become an automated CI/CD pipeline once one is chosen.

### 29.8 Open items

Additional defects found in the current Terraform — notably that `dev` cannot be destroyed because `deletion_protection` is never overridden to `false`, and that `my_ip_cidr` defaults to `0.0.0.0/0` — are catalogued in [INFRASTRUCTURE.md §11](INFRASTRUCTURE.md#11-known-gaps-and-discrepancies).

- **Multi-AZ**: `terraform/modules/database` has no `multi_az` variable yet; add one before standing up `prod`.
- **Read replicas**: deferred until query load actually justifies one, per [DATABASE_CONVENTIONS.md §33](DATABASE_CONVENTIONS.md).
- **CloudWatch alarms**: CPU, storage, connection count, and (once applicable) replica lag are not yet defined anywhere in the module.
- **Cost**: with current `dev` defaults (`db.t3.micro`, 20GB gp3, VPC endpoints instead of NAT, an on-demand migration runner) expect roughly the same range the project saw before the restart (~$20/month for `dev`). `staging`/`prod` will cost more once Multi-AZ and larger instance classes are applied — measure rather than guess once those environments exist.

### 29.9 AWS-first verification mechanism

Per [§23.0](#230-aws-verification-policy), every phase's migrations and `tests/database`/`tests/scenario` suites run against the deployed `dev` RDS instance, not a local or containerized stand-in. This needs two things: a way in for CI and developers, and isolation so concurrent test runs on the one shared instance don't collide.

**Reachability — dev only, via temporary security-group ingress, not a new bridge module.** `dev` already supports `enable_public_access` (§29.3) with its security group ID exposed as the `database_security_group_id` output. Rather than standing up an SSM bastion/tunnel for routine test access, CI and developers manage a narrow, short-lived ingress rule directly against that security group with the AWS CLI, scoped to the caller's own current public IP, for the duration of the run only:

```bash
SG_ID=$(terraform -chdir=terraform/environments/dev output -raw database_security_group_id)
MY_IP=$(curl -s https://checkip.amazonaws.com)/32

aws ec2 authorize-security-group-ingress --group-id "$SG_ID" \
  --protocol tcp --port 5432 --cidr "$MY_IP"

# ... run migrations / pytest against the dev endpoint ...

aws ec2 revoke-security-group-ingress --group-id "$SG_ID" \
  --protocol tcp --port 5432 --cidr "$MY_IP"
```

This reuses infrastructure that already exists rather than adding a new module. It bypasses Terraform for the add/revoke (a `terraform plan` run mid-session will show the rule as drift and is expected to remove it on apply — harmless as long as CI always revokes at job end, including on failure). `enable_public_access` must be `true` for `dev`; `staging` and `prod` stay `publicly_accessible = false` per §29.3 and are never opened this way — their migrations continue to go through the SSM-based migration runner in §29.6, and there is currently no plan to run `tests/database`/`tests/scenario` against them at all (they exist to host real environments, not to be a shared test fixture).

**Isolation — an ephemeral database per test run, not per-schema.** Bootstrap-created roles (`migration_owner`, `app_read_write`, etc.) are cluster-wide in PostgreSQL and already exist on the instance; schemas, domains, and extensions are per-database. So each CI run or developer test session creates its own throwaway database on the shared instance (e.g. `dnd_ai_test_<run-id>`), runs `alembic upgrade head` inside it, runs tests against it, and drops it — real isolation on shared infrastructure without needing a database-per-environment. This requires a role with `CREATEDB` (the master user, or a narrowly-scoped `test_runner` role using IAM auth) — add this to the bootstrap revision's role list when this mechanism is implemented; it does not exist yet.

**What still needs building**: this section describes the target mechanism; as of this writing neither the CI IP-allowlist step nor the ephemeral-database fixture has been exercised against a live `dev` instance (no `dev` environment has been applied yet — see [INFRASTRUCTURE.md §1](INFRASTRUCTURE.md#1-current-state)). Treat both as an open task alongside the migration runner in §29.6, not as already-verified infrastructure.

---

## 30. AWS deployment plan for application services

### 30.1 Scope

[§29](#29-aws-terraform-deployment-plan-for-postgresql) covers the database. This section covers everything else that runs: the FastAPI application, the background worker that drains the outbox ([SYSTEM_ARCHITECTURE.md §10](architecture/SYSTEM_ARCHITECTURE.md#10-internal-event-dispatcher-and-outbox)), the Discord adapter, and one-off jobs including migrations.

It exists because [§23.0](#230-aws-verification-policy) requires every phase to be deployed and verified in AWS, and because the concrete deployment target was previously unrecorded — [SYSTEM_ARCHITECTURE.md §17](architecture/SYSTEM_ARCHITECTURE.md#17-deployment-topology) named vendor-neutral deployables and [§29.6](#296-migration-execution-mechanism) explicitly deferred the container-registry and CI/CD decision. That decision is now made and recorded in [ADR 0008](adr/0008-aws-first-deployment-and-verification.md).

Nothing in this section is built yet. It is the plan; [INFRASTRUCTURE.md §1](INFRASTRUCTURE.md#1-current-state) is what exists.

### 30.2 Compute: ECS Fargate

Application services run as ECS Fargate services in the same VPC and private subnets as the RDS instance. Rationale and the alternatives rejected (EC2 + systemd, App Runner) are in [ADR 0008](adr/0008-aws-first-deployment-and-verification.md).

| Deployable | ECS shape | Notes |
|---|---|---|
| Application API | Long-running service behind an ALB | The modular monolith from [SYSTEM_ARCHITECTURE.md §17](architecture/SYSTEM_ARCHITECTURE.md#17-deployment-topology); the only deployable with ingress from outside the VPC |
| Background worker | Long-running service, no load balancer | Outbox drain, integration delivery, AI proposal processing |
| Discord adapter | Long-running service, no load balancer | Outbound gateway connection; no inbound ingress needed |
| Migrations | One-off task, run to completion | Replaces the standing EC2 runner in [§29.6](#296-migration-execution-mechanism) — same image, different command |
| Import / batch jobs | One-off task, run to completion | Phase 11 |

All of these share one container image. The entrypoint selects the role, so there is one artifact to build, scan, and promote.

### 30.3 Image build and registry

- One **ECR** repository per environment account (or one shared repository with immutable tags — decide when `staging` exists, per [§29.3](#293-environments-dev-staging-prod)).
- Images are tagged with the Git commit SHA. Mutable tags like `latest` are not deployed; a task definition always references an immutable tag, so a rollback is a task-definition revision rather than a rebuild.
- CI builds and pushes on merge; on pull requests it builds only to prove the image still builds.
- Image scanning on push is enabled. A failing scan blocks promotion to `staging`/`prod`, not `dev`.

### 30.4 Networking

- Services run in the **private** subnets that already exist in `terraform/modules/database`. They reach AWS APIs through the existing Secrets Manager and KMS interface endpoints; ECR (plus S3, for image layers) endpoints have to be added, or a NAT Gateway accepted — this is the one place the current no-NAT design needs revisiting, and it is a cost tradeoff to measure rather than assume ([§30.9](#309-open-items)).
- The API service sits behind an **Application Load Balancer** in the public subnets. It is the only public entry point; the database itself is never reachable from the internet in `staging`/`prod`.
- Each service gets its own security group. Database ingress is granted by attaching those security groups to the RDS security group via `allowed_security_group_ids`, which `terraform/modules/database` already supports — not by widening any CIDR block.

### 30.5 Identity and secrets

- Each service gets its own **task role** (what the application may call) distinct from its **execution role** (what ECS may do to start the task).
- Database access uses **IAM database authentication** with the roles from [§29.5](#295-database-role-schema-and-extension-bootstrap): the API and worker task roles get `rds-db:connect` for `app_read_write`, read-model-only services get `app_read_only`, and the migration task gets `migration_owner`. No database password is stored for these roles.
- External credentials (OpenAI, Discord) come from the Secrets Manager entries the `secrets` module already creates, injected as ECS secrets rather than plaintext environment variables. Per rule 10 in [CLAUDE.md](../CLAUDE.md#5-non-negotiable-architectural-rules), no secret enters an image, a task definition, or source control.

### 30.6 Deployment flow

1. CI builds the image and pushes it to ECR tagged with the commit SHA.
2. CI registers a new task-definition revision pointing at that tag.
3. CI runs the migration task to completion and fails the deployment if it fails — schema changes land before the code that depends on them, which is what the expand-and-contract requirement in [DATABASE_CONVENTIONS.md §25.5](DATABASE_CONVENTIONS.md#255-backward-compatibility) exists for.
4. CI updates the API, worker, and adapter services to the new revision; ECS rolls them with health checks.
5. Rollback is redeploying the previous task-definition revision. Because migrations are expand-and-contract, the previous image is expected to run against the newer schema.

For `dev`, steps 3–4 run automatically on merge to `main`. For `staging`/`prod`, promotion is deliberate — the same image, a manual trigger. The SSM-based migration runner in [§29.6](#296-migration-execution-mechanism) is retired once step 3 works, since a one-off Fargate task in the private subnets reaches the database the same way without a standing instance.

### 30.7 Observability

The telemetry requirements are in [SYSTEM_ARCHITECTURE.md §19](architecture/SYSTEM_ARCHITECTURE.md#19-observability); this is where they land:

- Container logs to **CloudWatch Logs**, one log group per service, with retention set explicitly rather than left to never expire.
- The correlation, causation, and identity fields from §19 are emitted as structured JSON so they are queryable, not free text.
- Alarms on API 5xx rate and latency, task restart loops, outbox backlog depth, plus the database alarms still missing per [§29.8](#298-open-items).

### 30.8 Per-phase deployment expectations

Application services do not exist until there is application code to run. Phases 2–7 are predominantly schema and domain logic, so their AWS obligation is the one in [§23.0](#230-aws-verification-policy): migrations and tests verified against the deployed `dev` database.

The additional obligations in this section begin when the corresponding deployable first exists:

| From | Additionally deployed and verified in `dev` |
|---|---|
| The first phase that delivers a FastAPI endpoint | API service on Fargate behind the ALB, reachable and health-checked |
| The first phase that delivers outbox processing | Background worker service |
| Phase 9 (Foundry synchronization) | Whatever Foundry-facing surface that phase adds, through the API |
| Phase 10 (AI and Discord) | Discord adapter service; AI provider credentials resolved from Secrets Manager at runtime |
| Phase 11 (Import tools) | Import job as a one-off task |

A phase is not done when its code merges; it is done when its deployables are running in `dev` and the phase's tests pass against them.

### 30.9 Open items

- **ECR/S3 VPC endpoints vs. NAT Gateway** ([§30.4](#304-networking)) — the current design deliberately avoids a NAT Gateway; pulling images into private subnets forces one or the other. Measure both before choosing.
- **Terraform modules**: `ecr`, `ecs_cluster`, `ecs_service`, and `alb` do not exist. Follow the one-module-per-bounded-concern split already used by `database` and `secrets`.
- **CI/CD platform**: GitHub Actions is already used for CI ([DEVELOPMENT.md §8](DEVELOPMENT.md#8-continuous-integration)); deployment is assumed to extend it rather than introduce a second system, but the OIDC role and environment protection rules are unbuilt.
- **`staging`/`prod` environments** remain unbuilt per [§29.3](#293-environments-dev-staging-prod); everything above is specified for `dev` first.
- **Cost**: each always-on Fargate service adds to the ~$25–35/month database figure in [INFRASTRUCTURE.md §9](INFRASTRUCTURE.md#9-cost). Measure once the API service exists rather than guessing now.

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
- [22. World/campaign-data import implementation](#22-worldcampaign-data-import-implementation)
- [23. Identity, authorization, and web-portal implementation](#23-identity-authorization-and-web-portal-implementation)
- [24. Delivery phases](#24-delivery-phases)
- [25. Vertical-slice acceptance scenario](#25-vertical-slice-acceptance-scenario)
- [26. Testing strategy](#26-testing-strategy)
- [27. Operational strategy](#27-operational-strategy)
- [28. Deferred decisions](#28-deferred-decisions)
- [29. Definition of implementation success](#29-definition-of-implementation-success)
- [30. AWS Terraform deployment plan for PostgreSQL](#30-aws-terraform-deployment-plan-for-postgresql)
- [31. AWS deployment plan for application services](#31-aws-deployment-plan-for-application-services)
- [32. Local production deployment plan](#32-local-production-deployment-plan)

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
- A role-aware web portal, FoundryVTT, API, world/campaign-data import, reference-corpus ingestion, and AI-agent integrations.
- Authenticated player, GM, assistant-GM, and observer access with campaign-scoped roles and many-to-many resource relationships.
- Audience-filtered world browsing, summaries, and on-demand campaign questions without revealing inaccessible records.
- Reliable provenance, approval, visibility, and audit tracking.
- Future world/campaign-data import of existing campaign documents and legacy material without weakening the canonical model.

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

AI prompts, summaries, embeddings, and generated descriptions must be derived from structured world data and authorized, cited rules/reference-corpus passages whenever possible.

AI-generated changes begin as proposals unless an explicit policy permits automatic application.

### 2.7 Reference-corpus ingestion and campaign import are separate systems

Use qualified terminology because the two document paths have different destinations and authority:

| System | Purpose | Destination | Canonical-state effect |
|---|---|---|---|
| Rules/reference corpus | Supply authorized rules and reference passages to AI requests | Searchable source-document and passage index | None |
| World/campaign-data import | Establish or update world and campaign facts | Domain records created through approved application commands | Yes, after GM approval |

They may share low-level file handling and text-extraction utilities, but never promotion behavior. Reference passages become retrievable, cited request context; campaign import staging contains untrusted proposals that may become canonical only after validation, GM review, and application commands. The rules/reference corpus does not use canonical promotion batches, and campaign import staging does not double as the AI rules corpus.

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
| `interaction` | Player, GM, web-portal, Foundry, and AI actions and resolutions |
| `ai` | Agents, context assembly, rules/reference-corpus sources and passages, generated output, proposals |
| `audit` | Change history, approvals, validation errors, agent activity |
| `import` | Staging, matching, review, and promotion records for world/campaign-data import |
| `integration` | External-system identifiers, sync state, webhook or polling metadata |

---

## 4. Foundation implementation

### 4.1 PostgreSQL extensions

Initially enable:

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
```

Enable `btree_gist` in the Phase 3 migration that first creates a scalar-key/range exclusion constraint:

```sql
CREATE EXTENSION IF NOT EXISTS btree_gist;
```

It is not a Phase 1 bootstrap dependency, but it is required before the party-membership exclusion constraint described in [§5.4](#54-parties) and [ADR 0010](adr/0010-use-sort-key-ranges-for-fictional-time-intervals.md).

Enable `vector` only if Phase 12 or later demonstrates that structured queries, relational retrieval, and PostgreSQL full-text search are insufficient:

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
- `security.capabilities`
- `security.role_capabilities`
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
- World/campaign source document
- Rulebook or SRD
- FoundryVTT
- Web portal
- Discord, when a later integration exists
- Session transcript
- AI-generated proposal
- Migration or seed data
- External API

For rules/reference-corpus sources, provenance includes the immutable source/version and file hash plus chapter, section, page, and passage location needed for citation. It also records usage rights and whether the source may be indexed, quoted, summarized, exported, or considered for any separately authorized future training use. For accepted world/campaign-data proposals, provenance links each canonical effect to its source location, review decision, application command, and result.

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

`default_ruleset_id` remains part of the target world model but is not added until Phase 4 creates `rules.rulesets`; Phase 3 must not introduce it as an unconstrained UUID.

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
- A root timeline has neither a parent nor a branch point. In Phase 3, a branch has both a parent and a branch world time, and that world time belongs to the same world.
- Once events exist in Phase 6, the branch event must belong to the parent timeline and cannot occur after the branch world time. The effective-history query must ignore every parent event after the branch point.
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

The selected ruleset reference is added in Phase 4 together with `rules.rulesets`; Phase 3 omits it rather than storing an unconstrained UUID.

### 5.4 Parties

Implement:

- `campaign.parties`
- `campaign.party_memberships`
- `campaign.campaign_parties`

A party may persist across campaigns. `campaign.parties` therefore carries its own `party_id` and `world_id`; `campaign.campaign_parties` associates it with campaigns in that world. Memberships must be temporal so characters can join, leave, disappear, or return.

The party is a stable world-level identity; membership is timeline-scoped mutable state. `campaign.party_memberships` therefore includes `timeline_id`, `party_id`, `member_entity_id`, required `effective_from_world_time_id`, optional `effective_to_world_time_id`, and a database-maintained `INT8RANGE effective_period` derived from the endpoints' `core.world_times.sort_key` values.

Intervals are half-open `[from, to)`. The start must be finite; a missing end is an unbounded upper range representing current membership. A trigger enforces endpoint ordering and world agreement. A GiST exclusion constraint over `(timeline_id WITH =, party_id WITH =, member_entity_id WITH =, effective_period WITH &&)` prevents overlap while allowing adjacent periods. [ADR 0010](adr/0010-use-sort-key-ranges-for-fictional-time-intervals.md) records the full decision and correction policy.

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
- `rules.world_rulesets` — associates a world with its allowed rulesets and identifies its default
- `rules.abilities`
- `rules.skills`
- `rules.species`
- `rules.classes`
- `rules.subclasses`
- `rules.features`
- `rules.feats`
- `rules.spells`
- `rules.conditions`
- `rules.damage_types`
- `rules.creature_types`
- `rules.languages`
- `rules.proficiency_types`
- `rules.resource_definitions`

`rules.item_definitions` is deferred to Phase 9, which owns both item definitions and item instances together (see Phase 9's Deliver list).

All rule definitions must identify their ruleset and version.

Rules/reference-corpus retrieval must likewise filter by the campaign's selected game system, edition, sourcebooks, ruleset, and permissions. A retrieved passage is reference context, not a `rules.*` definition or campaign fact; ingesting a book never creates abilities, classes, species, spells, feats, items, monsters, or other domain records automatically.

### 6.2 Homebrew support

Homebrew definitions must be first-class records with provenance and canon status. They must not require changes to core tables. User-authored homebrew documents may also be registered in the rules/reference corpus, where campaign-specific house rules take retrieval precedence without silently changing canonical rule definitions.

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

Persist snapshots only when useful for performance, world/campaign-data import, or historical reconstruction. Store the calculation version with each snapshot.

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
- `character.character_class_levels`
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

`campaign.character_location_history` is deferred until `world.locations` exists in Phase 5, and `campaign.character_inventory` until item instances exist in Phase 9 — neither has anything to reference yet. Phase 4 delivers the three tables above only.

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

Phase 10 adds or evolves the user-facing semantic join described in [§23.2](#232-many-to-many-user-and-resource-relationships). A user can own, control, co-control, portray, or view multiple characters, and a character can have multiple simultaneous or historical user relationships. Mechanical control and general view/private-data access are separate capabilities.

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
- `character.npc_disclosure_rules`
- `character.npc_agent_assignments`

`campaign.npc_emotional_state` and `campaign.npc_goal_state` are timeline-scoped current mood, trust, and goal progress — `campaign` schema, not `character`, alongside the other timeline state in [§7.3](#73-timeline-state). The tables above are world-level portrayal definitions.

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
- `campaign.item_ownership` — who owns an instance
- `campaign.inventory_entries` — who currently possesses/carries it; distinct from ownership
- `campaign.item_attunements`
- `campaign.character_inventory` — character-centric read index over `item_ownership`/`inventory_entries`
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

A user can access any number of facts through character, party, campaign-role, group, or direct-user relationships, and one fact can be visible to many users through different derivations. Direct user visibility does not turn that user into an in-world knower, and character knowledge does not become universal player knowledge. Truth, belief, knowledge possession, and administrative access remain separate records resolved through [§23](#23-identity-authorization-and-web-portal-implementation).

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

Web-portal and Foundry actions must create or reference interaction records rather than writing directly to arbitrary tables. A later Discord client, if justified, follows the same boundary.

---

## 17. Encounter and combat implementation

Implement:

- `narrative.encounters`
- `narrative.encounter_participants`
- `narrative.encounter_turns`
- `narrative.encounter_rounds`
- `interaction.combat_actions`

FoundryVTT may remain the detailed tactical authority during live combat. Phase 9 provides records and contracts capable of storing synchronized state and meaningful outcomes; live synchronization itself begins in Phase 11 through the application API.

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

The following is a longer-term model, not the Phase 12 starting scope. Implement only the subset justified by the narrow NPC MVP:

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

### 18.3 Rules/reference-corpus ingestion and retrieval

The rules/reference corpus supplies retrieval-grounded context; it does not train or retrain the foundation model and has no canonical-state promotion path. It supports authorized SRDs; the Player's Handbook, Dungeon Master's Guide, Monster Manual, and setting books when the operator has usage rights; compatible third-party supplements; campaign-selected supplements; and user-authored homebrew references, including custom classes, species, backgrounds, spells, feats, items, and monsters.

```text
Authorized source
  -> register and validate usage rights
    -> retain immutable source and hash
      -> extract text and document structure
        -> preserve chapter/section/page provenance
          -> create retrievable passages
            -> index with PostgreSQL-native search
              -> retrieve relevant passages
                -> supply cited context to the AI request
```

Registered sources and passages record, as applicable:

- game system, rules edition and version, title, publisher or author
- official, third-party, SRD, or homebrew classification
- license or usage-rights status
- immutable file hash, source version, ingestion date, and supersession history
- chapter, section, page, and passage location sufficient for citation
- campaigns or rulesets permitted to retrieve the source
- whether indexing, quotation, summarization, export, or any future training use is permitted
- source-removal and index-rebuild status

Storage owned by this subsystem covers registered reference sources, source versions and hashes, extracted sections/passages, citation locations, PostgreSQL search indexes, ruleset/edition/sourcebook applicability, usage rights and retrieval permissions, and ingestion/removal history. These are reference-corpus records under the AI/context boundary, not `import.*` campaign-staging rows and not canonical domain entities.

Retrieval rules:

- Ingest only material the operator is authorized to store and use.
- Filter by campaign-selected game system, edition, sourcebooks, ruleset, and permissions; never silently mix D&D editions.
- Apply precedence in this order: campaign-specific house rules; campaign-selected sourcebooks and edition; general references for the selected system and edition; model background knowledge only when no authoritative selected source is available and the use case permits it.
- Surface conflicts instead of silently combining incompatible passages.
- Never expose or redistribute full imported books through public application APIs.
- Removing, disabling, or superseding a source makes its passages unavailable to later retrieval and triggers the required index update.
- Every retrieved passage retains source and location provenance, and retrieval and downstream AI use are audited.

The initial implementation uses structured metadata filters, PostgreSQL full-text search, deterministic passage selection where practical, citations, and retrieval auditing. Embeddings, if later justified, augment rather than replace metadata, edition and authorization filtering, citations, or deterministic precedence. Model training or fine-tuning requires a separate design, an explicitly authorized training dataset, appropriate licensing and privacy review, evaluation criteria, and demonstrated need; ingested material is never training data by default.

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
- `get_audience_filtered_campaign_summary`
- `get_audience_filtered_session_recap`
- `search_authorized_world_details`

Query services accept authenticated user, campaign, timeline, effective-time, and optional character-perspective context. They return only authorized records and fields and do not reveal inaccessible resources through counts, relationships, search results, or missing-versus-forbidden error differences. Do not expose inheritance, branch, or access-resolution logic separately in every application component.

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

1. Authenticate the actor and validate campaign membership, capabilities, resource relationships, and references.
2. Validate world and timeline consistency.
3. Open a transaction.
4. Create provenance and event records where required.
5. Update typed state.
6. Update knowledge, relationships, and quest state.
7. Write audit records.
8. Queue asynchronous AI, search, portal-notification, or integration work.
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
- Campaign memberships, role assignments, user-character relationships, and resource grants agree on campaign/timeline scope.
- Revoked or expired access cannot authorize later reads or writes.
- Access-control changes identify the granting actor and are audited.

Use constraints and triggers for local invariants. Use service-layer validation for complex cross-domain invariants.

---

## 22. World/campaign-data import implementation

World/campaign-data import is deferred until Phase 14, after canonical API commands and application services exist. It handles world-building and campaign-premise documents; locations, factions, organizations, religions, and lore; NPCs and relationships; character backgrounds; quests and rewards; session notes and transcripts; timelines and historical events; items, ownership, inventory, and treasure; discoveries, beliefs, secrets, knowledge, summaries, and current state. It is distinct from the Phase 12 rules/reference corpus.

Implement later:

- `import.import_jobs`
- `import.import_sources`
- `import.staged_entities`
- `import.staged_relationships`
- `import.staged_events`
- `import.staged_knowledge`
- `import.entity_matches`
- `import.validation_results`
- review decisions
- `import.promotion_batches`

World/campaign-data import flow:

```text
Campaign source
  -> retain source and provenance
    -> extract candidate entities, facts, relationships, events, and knowledge
      -> stage proposals
        -> match and deduplicate
          -> validate and detect conflicts
            -> GM review, edit, approve, or reject
              -> approved application commands
                -> canonical domain records
```

Required promotion behavior:

- Handle entity matching, ambiguous matches, duplicates, and conflicts with existing canon explicitly.
- Support per-proposal or appropriately grouped GM review, editing, approval, and rejection.
- Require application-command coverage for every promoted proposal; missing commands are an implementation gap, never permission for direct database writes.
- Apply the same validation, authorization, visibility, timeline-isolation, audit, idempotency, and transaction rules as normal operations.
- Promote related changes atomically where partial application would be inconsistent.
- Support idempotent reruns and resumable partial review and promotion.
- Link every accepted record or event to the source location, reviewer, decision, application command, and result.
- Never promote staged rows, extracted text, or AI output directly into arbitrary canonical tables.

Historical session notes require explicit separation between described historical events, resulting state, character or party knowledge, quest and relationship changes, and corrections or initial-state assertions. Prefer to:

1. Match or create the session, participants, locations, entities, and quests.
2. Propose historical events with appropriate in-world and recorded timing.
3. Apply resulting state changes through application commands.
4. Propose supported quest, relationship, inventory, and knowledge changes.
5. Preserve a source-note citation for every accepted proposal.
6. Avoid duplicate events or repeated state effects when reprocessing the same source.

When reliable causal history cannot be reconstructed, use an explicitly identified initial-state or reconciliation command with provenance. Do not fabricate an event merely to make history appear complete.

Phase 14 starts with a small campaign packet containing one world-building document, one quest description, and one set of session notes. One input format is sufficient initially. AI-assisted and deterministic extraction are both allowed, but all extracted content remains untrusted until validation and approval. A general PDF, DOCX, spreadsheet, transcript, or OCR framework is outside the initial scope.

---

## 23. Identity, authorization, and web-portal implementation

The web portal is the primary out-of-session client. Foundry remains the in-session tactical client. Discord is not an initial delivery priority and may be added later as a thin client only if demonstrated player demand justifies it.

### 23.1 Identity and campaign membership

Authentication establishes a user identity; application authorization determines what that user may do or discover. Use an OIDC-compatible identity provider for login, with the application database retaining campaign membership, roles, capabilities, resource relationships, and audit history.

Implement or evolve concepts equivalent to:

- `security.users`
- external identity-provider subjects linked many-to-one to a user
- campaign memberships joining users to campaigns
- membership roles joining memberships to one or more campaign-scoped roles
- configurable capabilities assigned to roles
- invitations, membership status, and revocation history

A user may belong to multiple campaigns and hold multiple roles in each. The same user may be a GM in one campaign, a player in another, and an observer in a third. Roles provide default capabilities; application services authorize capabilities rather than scattering hard-coded role-name checks.

Initial role templates are campaign owner, GM, assistant GM, player, observer, import reviewer, and rules curator. Observer is a curated, read-only role, not an alias for access to all player-visible or GM-visible data.

### 23.2 Many-to-many user and resource relationships

Do not add a single `owner_user_id` or one-user visibility flag to characters, facts, or other domain records. Details are many-to-many with users.

Keep semantic user-character relationships, including owner, primary controller, co-controller, viewer, portrayer, former controller, and observer-approved viewer. Store campaign/timeline scope, effective period, granting user, and audit metadata. A user may relate to many characters, and one character may relate to many users.

Provide a securable-resource and grant model, or equivalently typed access associations, for at least:

- characters
- canonical facts and knowledge records
- entities and locations
- quests
- sessions, summaries, and events
- items and documents
- AI and campaign-import proposals

Grants may target a user or access group and express capabilities such as `discover`, `view_summary`, `view_full`, `view_private`, `interact`, `control`, `edit`, `approve`, and `manage_access`. They record campaign/timeline scope, source, effect, optional effective period, granting user, and audit timestamps. Access may also derive from roles, character control, parties, knowledge holdings, or groups; resolution retains the derivation so the UI can explain why information is visible.

Canonical truth, a character's belief, a knowledge grant, and administrative permission remain distinct. For example, one fact may be true, known by several NPCs, suspected by one player character, directly shared with two users, and administratively visible to multiple GMs without duplicating the canonical fact.

### 23.3 Authorization and non-disclosure

For each request, the application layer:

1. Authenticates the user.
2. Confirms active campaign membership.
3. Resolves the campaign, timeline, role, and optional character perspective.
4. Resolves role capabilities, direct grants, group grants, and character/party/knowledge-derived access.
5. Applies explicit restrictions and temporal scope.
6. Filters rows, fields, relationships, counts, search results, summaries, and AI context.
7. Audits sensitive reads and every write or access-control change.

Inaccessible resources must be non-discoverable: clients must not infer them from identifiers, search suggestions, counts, relationship edges, error differences, or AI responses. Client-side hiding is presentation only; enforcement occurs in application services and query construction before data reaches a client or AI provider. AI answers are generated from already authorized context, never from a broader answer followed by redaction.

### 23.4 Web-portal experience

The portal provides a shared authenticated shell with campaign, timeline, viewing role, and optional character perspective always visible. Initial navigation covers Home, World, Characters, Quests, Sessions, Knowledge, Ask, GM Tools, and Access Management when permitted.

The MVP includes:

- a personalized dashboard with last-session recap, current situation, active quests, recent discoveries, relevant NPCs/factions, character reminders, and an Ask entry point
- a world explorer for permitted locations, NPCs, organizations, religions, items, events, relationships, and lore
- character workspaces honoring separate view, edit, control, private-history, character-knowledge, and access-management capabilities
- audience-aware knowledge, quest, session, and summary views
- an on-demand assistant for campaign summaries, details, rules questions, and GM preparation using authorized structured queries and cited rules/reference passages
- observer views built from explicitly published or granted resources
- GM tools for canon browsing, preparation, visibility preview, user invitations, role assignment, user-character relationships, resource grants, and audit history
- Phase 15 campaign-import review, editing, match resolution, approval, rejection, and promotion surfaces

The detailed interaction design, screen specifications, and authorization matrix are maintained in [UI_DESIGN.md](UI_DESIGN.md). The plan defines delivery boundaries; that document defines the product experience.

### 23.5 Audience-aware summaries and questions

Deterministic query services provide current campaign/session state, active quests/objectives, recent events, locations, characters, NPCs/factions, inventory, knowledge, and recaps. Phase 12 adds AI synthesis over those already-filtered results and the authorized rules/reference corpus. Phase 13 exposes both through the portal.

Every summary or answer records or returns its campaign, timeline, effective point in time, requesting user, viewing role/perspective, visibility scope, source records or citations, and whether it is deterministic, cached, or AI-synthesized. The same question may correctly produce different player, character, observer, GM, or session-preparation answers.

---

## 24. Delivery phases

The active plan keeps only compact stubs for completed Phases 0–5. Their detailed deliverables, exit criteria, first-time obligations, and closeout narrative are preserved in [PLAN_PHASES_0_5_ARCHIVE.md](PLAN_PHASES_0_5_ARCHIVE.md) and should be loaded only for historical or regression work. Phase verification files remain the evidence of what actually ran.

### 24.0 Verification policy

**Current policy ([ADR 0012](adr/0012-self-hosted-docker-deployment-and-ci-verification.md), 2026-08-11):** development happens locally or self-hosted; delivery is verified against a disposable, containerized PostgreSQL 18 — the same target the project's self-hosted deployment topology (`compose.yaml`) actually runs. These remain two different steps, a distinction [ADR 0011](adr/0011-local-first-development-aws-verified-delivery.md) first drew when the original AWS-first policy ([ADR 0008](adr/0008-aws-first-deployment-and-verification.md)) fused them; ADR 0012 keeps the two-tier shape but moves both tiers off AWS RDS. AWS RDS remains available as an optional, no-longer-CI-verified target for anyone who deploys `terraform/` themselves — see [§30](#30-aws-terraform-deployment-plan-for-postgresql)–[§31](#31-aws-deployment-plan-for-application-services).

**Tier 1 — the inner loop runs against a local or self-hosted PostgreSQL 18 server.** Writing a migration, iterating on a constraint or trigger, and running `tests/database`/`tests/scenario` all happen locally (natively installed or via `docker compose up -d db`), with no AWS credentials, no security-group rule, and no network dependency. This is the default and expected way to work, not a fallback. Setup is [DEVELOPMENT.md §3](DEVELOPMENT.md#3-local-setup).

The local/self-hosted server must be **PostgreSQL 18.x, matching what CI runs** ([DATABASE_CONVENTIONS.md §2.1](DATABASE_CONVENTIONS.md#21-supported-postgresql-version)). A server on a different major version is a defect, not a preference — it reintroduces exactly the divergence this policy exists to prevent.

**Tier 2 — CI verifies the same work against a disposable containerized PostgreSQL 18 instance.** `.github/workflows/ci.yml`'s `postgres-verification` job runs migrations from empty to head, the downgrade round trip, `alembic check`, seed idempotency, and the full test suite against a `postgres:18.4` GitHub Actions service container; a `docker-build` job additionally validates the `compose.yaml` topology itself. This is a **merge gate**, not advisory. It no longer catches AWS-RDS-specific defects — IAM authentication, `rds_superuser` boundaries, `rds.force_ssl`, parameter groups, managed-role behavior, the class of bug the ungated `GRANT rds_iam` in the bootstrap revision was — because the project no longer deploys there by default; that tradeoff is recorded deliberately in [ADR 0012](adr/0012-self-hosted-docker-deployment-and-ci-verification.md).

`tests/unit` is unaffected by either tier — it uses no database at all.

The self-hosted obligation applies to *running* code, not just schema: once a phase delivers a deployable — an API, portal, or adapter — it runs via `compose.yaml` and is exercised there. AWS deployment (§31) is optional, unbuilt planning material, not a current obligation.

A phase's exit criteria below are therefore necessary but not sufficient. A phase is done when, additionally:

1. Its migrations run cleanly — up, and down where supported — against a local/self-hosted PostgreSQL 18 database.
2. Its `tests/database`/`tests/scenario` suites pass locally.
3. A CI run on the phase's final head commit is green, and its run ID is recorded in `docs/PHASEn_VERIFICATION.md`.
4. Its deployables (if any) are running via `compose.yaml` and exercised there.

"It passes locally" is the expected *first* claim and is never the last one. A phase closes on item 3, not item 2.

**When local and CI disagree, CI is right.** A green local run followed by a red CI run is not flaky infrastructure to be re-run until it passes; it is a real defect, or local and CI have drifted apart (different PostgreSQL minor version, extension availability, etc.). Investigate before re-running. Phases 1–9 were verified under the earlier AWS-first and local-first/AWS-verified policies; a transient RDS connection fault during Phase 6 was diagnosed as such and re-run deliberately at the time — historical evidence of that judgment call, not a template for CI failures against the current containerized target.

### 24.1 Phase exit review

Every phase ends with a review, before the next one starts. Phase 1 produced six defects that no amount of offline checking would have found, and several of them were latent for days because the exit criteria could be marked done without evidence. This section is the correction.

**Write down what was actually verified.** Each phase produces `docs/PHASEn_VERIFICATION.md`, following the shape of [PHASE1_VERIFICATION.md](PHASE1_VERIFICATION.md): what was run and against what, the bugs found and fixed, and what remains outstanding. "Verified" means a command was run and its output observed — not that the code looks right. State the method next to the claim, so a reader can tell `alembic --sql` output from a live run.

Under [§24.0](#240-verification-policy) that record now has **two targets**, and the file must distinguish them: what was run against the local/self-hosted PostgreSQL 18 server, and the CI run ID that proved the same work against CI's containerized PostgreSQL 18 (AWS `dev` RDS for phases verified before [ADR 0012](adr/0012-self-hosted-docker-deployment-and-ci-verification.md)). A verification file that reports only local results has not recorded a closed phase.

**Re-check the recurring obligations.** These can regress silently in any phase that touches schema, and several are invisible until something downstream breaks:

| Obligation | Why it needs re-checking |
|---|---|
| Object ownership | Tables must end up owned by `migration_owner` ([ADR 0009](adr/0009-separate-owning-role-from-login-roles.md)). If `SET ROLE` stops holding, ownership silently moves to the connecting user |
| Default privileges | `ALTER DEFAULT PRIVILEGES` only fires for objects created *by* `migration_owner`. Verify by connecting as `app_read_write`/`app_read_only`, not by reading grant statements |
| Seed idempotency | Seeding twice must be a no-op ([DATABASE_CONVENTIONS.md §25.6](DATABASE_CONVENTIONS.md#256-migration-testing)) |
| Constraint tests | Positive *and* negative per [§32.1](DATABASE_CONVENTIONS.md#321-constraint-tests). An untested `CHECK` is an unverified rule |
| Comments and FK indexes | [§31](DATABASE_CONVENTIONS.md#31-documentation-conventions) and [§19.1](DATABASE_CONVENTIONS.md#191-foreign-key-indexes), in the same revision that creates the object |
| Downgrade | Round trip to `base` and back. Cheap to run locally now, so run it every phase — Phase 1's downgrade was broken for weeks while looking fine. CI repeats it against `dev` |
| Local/CI agreement | Same PostgreSQL major version, same extensions, same six bootstrap roles. Drift here shows up as a green local run and a red CI run ([§24.0](#240-verification-policy)) |
| CI green | On a real push, against CI's containerized PostgreSQL 18, on the phase's **final head** commit — not an earlier one, and not locally |

**Review the next phase before starting it.** Ask three questions and amend [§24](#24-delivery-phases) with the answers:

1. **What does this phase do for the first time?** First tables, first subtype, first seed content, first deployable, first cross-schema transaction. First-time mechanisms are where Phase 1's defects clustered, and they deserve an explicit exit criterion rather than an assumption.
2. **Which deferred items come due?** Deferrals recorded elsewhere ("add this when X exists") have to be swept up by whichever phase makes X exist, or they are never done.
3. **Are the exit criteria falsifiable?** "X is enforceable" is not checkable. "The constraint rejects Y, and a test proves it" is. Rewrite any criterion that could be marked done by inspection alone.

**Fold what you learned back into the conventions.** A bug caused by a convention being wrong or incomplete is a documentation defect, not just a code defect — fix both, in the same change. ADRs [0008](adr/0008-aws-first-deployment-and-verification.md) and [0009](adr/0009-separate-owning-role-from-login-roles.md) both came out of Phase 1 this way.

**Apply a proportionality check before opening or extending a phase blocker.** A review finding blocks the next phase when it concerns production correctness, data integrity, security, migration/deployment safety, a credible false test result, a persistent external-resource leak during normal failure handling, or demonstrated CI instability. A hypothetical failure inside a test-only helper does not block delivery merely because it can be fault-injected. Before requiring harness work, record:

1. The production or CI failure it could cause.
2. A realistic path to that failure, or an observed incident/reproduction under normal use.
3. Why existing containment and CI process isolation are insufficient.
4. The smallest correction and regression test that reduce the material risk.
5. The expected reuse and the cost relative to the current phase deliverables.

Do not recursively require a separately proven safety net for every layer of test cleanup. Standard-library primitives such as `Process.join()`, `is_alive()`, `Connection.close()`, or equivalent may be assumed to meet their documented contracts unless the project observes contrary behavior in a supported environment. Preserve a concrete original failure when cleanup also fails, but do not exhaustively simulate combinations of cleanup primitives failing.

**Stop-loss rule.** Once production exit criteria pass, the phase's realistic concurrency/integration scenarios pass, cleanup succeeds in ordinary success and failure paths, and final-head CI is green, close the phase. Record lower-risk test-harness limitations as non-blocking technical debt. Reopen the phase only for new evidence of production risk, a false pass/fail, a persistent external-resource leak, or repeatable CI instability. Test counts and review-pass counts are evidence, not goals.

### Phase 0: Documentation and decision records

**Complete.** Detailed historical plan: [Archived Delivery Plans: Phase 0](PLAN_PHASES_0_5_ARCHIVE.md#phase-0-documentation-and-decision-records).

### Phase 1: Database bootstrap

**Complete.** Detailed historical plan: [Archived Delivery Plans: Phase 1](PLAN_PHASES_0_5_ARCHIVE.md#phase-1-database-bootstrap). Verification evidence: [PHASE1_VERIFICATION.md](PHASE1_VERIFICATION.md).

### Phase 2: Core world platform

**Complete.** Detailed historical plan: [Archived Delivery Plans: Phase 2](PLAN_PHASES_0_5_ARCHIVE.md#phase-2-core-world-platform). Verification evidence: [PHASE2_VERIFICATION.md](PHASE2_VERIFICATION.md).

### Phase 3: Timelines and campaigns

**Complete.** Detailed historical plan: [Archived Delivery Plans: Phase 3](PLAN_PHASES_0_5_ARCHIVE.md#phase-3-timelines-and-campaigns). Verification evidence: [PHASE3_VERIFICATION.md](PHASE3_VERIFICATION.md).

### Phase 4: Rules and shared characters

**Complete.** Detailed historical plan: [Archived Delivery Plans: Phase 4](PLAN_PHASES_0_5_ARCHIVE.md#phase-4-rules-and-shared-characters). Verification evidence: [PHASE4_VERIFICATION.md](PHASE4_VERIFICATION.md); [PHASE4_REMAINING_ISSUES.md](PHASE4_REMAINING_ISSUES.md) is a closed historical record.

### Phase 5: Locations and dungeon play

**Complete.** The gameplay features and database invariants are merged and CI-verified. Revision 056 closes the last production race, and all five concurrency tests prove genuine waiter resumption with independent final-state assertions. The reusable test helper received major hardening through PR #15; GitHub Actions run [`30977657034`](https://github.com/NemesisGhost/dnd_ai/actions/runs/30977657034) passed both jobs and all 1,153 tests at implementation head `267ac1d`. Further hypothetical faults inside cleanup primitives are non-blocking under §24.1's proportionality and stop-loss rules. Detailed historical plan: [Archived Delivery Plans: Phase 5](PLAN_PHASES_0_5_ARCHIVE.md#phase-5-locations-and-dungeon-play). Verification evidence: [PHASE5_VERIFICATION.md](PHASE5_VERIFICATION.md); [PHASE5_REMAINING_ISSUES.md](PHASE5_REMAINING_ISSUES.md) is a closed historical record.

### Phase 6: Events and interactions

**Complete.** Delivered as five independently reviewed increments: `narrative.events` and branch-aware effective history (revision 057–060), the `interaction.*` domain (061–062), real knowledge-provenance references closing Phase 5's placeholders (063), conditional-route evaluation (064), and `src/dnd_ai/commands` — the first application-layer command handlers (`RecordEvent`, `PerformInteraction`, `ResolveCheck`). Four correction passes (revisions 065–072) followed a series of exit reviews, closing recorded-event immutability and deletion protection, `resolve_check()` concurrency control, interaction-resolution completeness, state-provenance timeline safety, ruleset/test-coverage guard gaps, and — in the final pass — moving the interaction status lifecycle (`initiated → resolving → resolved`) fully into the database as an `AFTER INSERT` trigger with matching `BEFORE INSERT` creation guards. [PR #16](https://github.com/NemesisGhost/dnd_ai/pull/16) merged to `main` (commit `2692f41`); that exact merge commit reached a confirmed green CI run (one transient AWS-RDS connection fault in the initial run was re-run, not a code defect). `alembic check` clean throughout, one Alembic head. Encounters/combat (§17's table shape) belongs to Phase 9, not this phase — see that phase's deliverable list. Verification evidence: [PHASE6_VERIFICATION.md](PHASE6_VERIFICATION.md).

<details>
<summary>Original entry-gate and planning detail (historical)</summary>

**Entry gates complete.** The repository-context modularization gate in [DEVELOPMENT.md §2.1](DEVELOPMENT.md#21-keep-source-and-tests-bounded-by-domain) is closed: the former `src/dnd_ai/persistence/tables.py` is now a domain-bounded package, and the two closed Phase 4 test monoliths are redistributed into invariant-oriented modules. Phase 5 production correctness and its five concurrency invariants are complete and CI-verified. No test-harness limitation currently meets §24.1's threshold for blocking Phase 6.

The Phase 6 entry gates are complete only once:

- table metadata was split into bounded domain modules behind a compatibility-preserving `dnd_ai.persistence.tables` package;
- the two closed Phase 4 test monoliths were redistributed into invariant/topic-oriented test modules (`test_session_chronology.py`, `test_ruleset_provenance.py`, `test_ruleset_version_consistency.py`, `test_immutable_identity.py`, `test_world_ruleset_dependency_and_concurrency.py`, `test_character_language_integrity.py`, `test_metadata_server_defaults.py`);
- no migration behavior, schema operation, revision identity, or chain topology changed (revision `036_remaining_rule_content_immutability` received a documentation-only docstring path correction — see [DEVELOPMENT.md §2.1](DEVELOPMENT.md#21-keep-source-and-tests-bounded-by-domain)), existing imports continue to work, and a metadata-completeness test (`tests/unit/test_persistence_tables_package.py`) plus `alembic check` proved the split behaviorally neutral (85 tables, identical names, before and after);
- the full quality and database test suite was green against AWS `dev` (366 tests collected from the split test files before and after, same as the two monoliths combined); and
- the Phase 5 dungeon-area creation/reparenting race, genuine waiting-statement behavior, and independent final-state assertions are closed and CI-verified; the shared helper safely contains ordinary success and failure paths. Hypothetical failures inside cleanup primitives are tracked as non-blocking limitations under §26.6.

Deliver:

- interactions
- checks
- events
- effects
- current-state updates
- event causality
- timeline branch-event references and branch-aware inherited history

Exit criteria:

- A player action can resolve into an event and atomic state changes.
- Current state and event history remain consistent.
- A branch inherits parent events only through its branch point; a parent event after that point is absent from the branch's effective history, with a scenario test proving the exclusion.
- A branch-event reference must identify an event from its parent timeline at or before the declared branch world time; cross-timeline and post-branch references are rejected by the database.
- A failure partway through a multi-domain command leaves no partial write — proven by a test that forces the failure, not by inspecting the transaction boundary.

First-time obligations (per [§24.1](#241-phase-exit-review)):

- **First full exercise of rule 6** (state changes need a causal event, committing atomically — [CLAUDE.md](../CLAUDE.md#5-non-negotiable-architectural-rules)) and of the transaction boundary in [SYSTEM_ARCHITECTURE.md §7](architecture/SYSTEM_ARCHITECTURE.md#7-transaction-boundary). Phase 2 records creation events; this is where the atomicity guarantee itself is on the line.
- **Close Phase 3's branch-history deferral.** Add `campaign.timelines.branch_event_id` with its foreign key and cross-row validation, then prove rule 7 with the effective-history scenario described in the exit criteria. Phase 3 verified branch structure only; do not treat that as evidence of isolation.
- **Close Phase 5's interaction/event placeholders.** `knowledge.entity_knowledge.learned_source` and `knowledge.party_discoveries.discovery_method` are free-text placeholders (revision 041) for "how this was learned/discovered" — replace with real references to `interaction.interactions`/`narrative.events` once both exist, per [DATABASE_MODEL.md §26](architecture/DATABASE_MODEL.md#26-reconciliation-notes-phase-5). Also extend `campaign.location_state`/`.area_connection_state`/`.area_feature_state`/`.hazard_state`/`.interactable_state` with a `last_event_id` provenance column, the same pattern Phase 4's character-state tables are already expected to receive here — see [DATABASE_MODEL.md §17](architecture/DATABASE_MODEL.md#17-typed-timeline-state).
- **Wire up conditional-route evaluation.** `world.area_connections.is_conditional`/`condition_description` (revision 047) record that a route is conditional and what the condition is, but nothing evaluates it — a party attempting to traverse a conditional route needs a check resolution against the interaction model this phase builds. Quest-gated conditions additionally need Phase 7's quest state; a route conditioned purely on interaction/check outcome (not quest progress) can be fully wired here.
- **Potential first deployable, not realized.** No Phase 6 exit criterion required post-commit async work, so no outbox processor was built. The earlier assumption that this would imply a standing Fargate service is superseded by [§31.2](#312-compute-principles): intermittent background work should prefer triggered execution, and persistent compute requires demonstrated need.

</details>

### Phase 7: Quests and knowledge

**Complete.** Revision 073 delivers the quest domain (`narrative.story_arcs`/`.quests`/`.quest_stages`/`.objective_types`/`.quest_objectives`/`.objective_dependencies`/`.quest_participants`/`.quest_outcomes`/`.quest_rewards`, `campaign.quest_state`/`.objective_state`) and the knowledge-domain expansion this phase inherits (below): temporal validity on `knowledge.knowledge_items`, `knowledge.knowledge_versions`, `.expertise_domains`/`.character_expertise`, `.information_transfers`, `.public_knowledge`. `src/dnd_ai/commands/quests.py`'s `advance_objective()` lets a dungeon event complete or fail a quest objective atomically, satisfying this phase's first exit criterion. A review of that work found six defects revision 073 missed — the second exit criterion's original test exercised an unrelated individual knower instead of party-level belief; `narrative.enforce_event_effect_target_world()`/`interaction.enforce_consequence_world()` were not extended for the new `target_quest_objective_id`/`resulting_quest_objective_state_id` columns; `knowledge.information_transfers`/`.public_knowledge` only checked world, not timeline, agreement for several columns; `advance_objective()` had a first-write concurrency gap; §14.1's completion-rule/visibility-policy concepts and §15.1's full knowledge-type seed list were incomplete; and `knowledge.knowledge_versions` allowed mutating an already-cited version. A correction pass (revision 074) closed all six, including building `campaign.party_knowledge` — the table the second exit criterion actually names — as a genuinely distinct table from `knowledge.party_discoveries`. [PR #17](https://github.com/NemesisGhost/dnd_ai/pull/17)'s exact final head reached a confirmed green CI run. A post-merge review found a second gap — the domain's same-world/same-scope triggers validated child rows only, never re-checking a parent row's own scope identity after a dependent referenced it — closed by revision 075 (`075_phase7_reparent_guards`, [PR #19](https://github.com/NemesisGhost/dnd_ai/pull/19), confirmed green CI). Verification evidence: [PHASE7_VERIFICATION.md](PHASE7_VERIFICATION.md).

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

**Inherits three tables already built.** `knowledge.knowledge_items`, `.entity_knowledge`, and `.party_discoveries` were pulled forward into Phase 5 (revision 041) to satisfy that phase's own exit criteria — treat them as already delivered rather than re-designed. Real provenance for `entity_knowledge.learned_source`/`party_discoveries.discovery_method` was Phase 6's obligation (closed by revision 063), not this phase's. What Phase 5 explicitly left for this phase — `knowledge.knowledge_versions`, `.information_transfers`, `.expertise_domains`/`.character_expertise`, `.public_knowledge`, and temporal validity on `knowledge_items` — is now delivered by revision 073 (above); `entity_knowledge.knowledge_version_id` (nullable) closes revision 041's own "nothing to version yet" placeholder now that `knowledge_versions` exists. See [DATABASE_MODEL.md §15](architecture/DATABASE_MODEL.md#15-knowledge-model) for the full boundary.

### Phase 8: Relationships and organizations

**Complete.** Revision 076 (originally drafted as `075_relationships_and_orgs` before Phase 7's own `075_phase7_reparent_guards` existed; renumbered by a deployable-integrity correction pass after both revisions forked the Alembic graph and failed CI — see [PHASE8_VERIFICATION.md](PHASE8_VERIFICATION.md)) delivers the universal relationship model (`world.relationship_types`/`.relationships`/`.relationship_participants`/`.relationship_perspectives`), the specialized relationships (`world.organization_memberships`/`.employment_relationships`/`.ownership_relationships`/`.family_relationships`/`.political_relationships`), the organization CTI hierarchy (`world.organizations` plus `.businesses`/`.governments`/`.religious_organizations`/`.military_units`/`.political_factions`), the religion/religious-affiliation distinction (`world.religions`, `character.character_religious_affiliations`), and the two timeline-state tables `DATABASE_MODEL.md §17` had already named but no earlier phase built (`campaign.organization_state`/`.relationship_state`). Two commands (`src/dnd_ai/commands/relationships.py`): `evolve_relationship_reaction()` and `update_organization_status()`. The correction pass also extended the `target_relationship_id`/`resulting_relationship_state_id` world/timeline-agreement guards, added reverse-mutation guards on `world.relationships`/`.relationship_participants`/`campaign.relationship_state`, and fixed `world.employment_relationships` to use a single §12.4 current-records pattern. All local verification — migration round trip (including a from-empty full `downgrade base → upgrade head` against a disposable scratch database), `alembic check`, the full test suite (2,058 tests), `ruff`/`mypy` — passed against AWS `dev`. See [PHASE8_VERIFICATION.md](PHASE8_VERIFICATION.md) for the full account.

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

### Phase 9: Items, inventory, encounters, and Foundry integration contracts

Phase 9 is the first phase developed under the local-first loop in [§24.0](#240-verification-policy) — its verification file is the first to record both a local result and a CI run ID. The [PostgreSQL 18 gate](POSTGRES18_UPGRADE_PLAN.md) that previously blocked this phase from merging closed 2026-08-08: `dev` now runs PostgreSQL 18.4, matching local.

**Boundary clarification (2026-08-09).** Phase 9 is the final database-foundation phase. It completes the items, inventory, ownership, treasure/economy, encounters, and Foundry-facing persistence and command contracts already underway. It may deliver database records and constraints required by Foundry integration, external identifiers and synchronization state, encounter commands and service-layer behavior, and adapter-facing persistence contracts. It does **not** deliver live Foundry-to-platform synchronization: no application API or Foundry adapter exists yet. Phase 10 creates the client-safe application boundary, and Phase 11 proves the concrete Foundry flow. External clients never write directly to PostgreSQL, and no temporary Foundry-to-database path is planned.

Deliver:

- item definitions and instances
- inventory and ownership
- encounters
- encounter and combat commands (`start_encounter`, `resolve_combat_turn`, `end_encounter` — see [docs/PHASE9_VERIFICATION.md](PHASE9_VERIFICATION.md))
- the database model for external identifiers and synchronization state (`integration.external_systems`/`.external_identifiers`/`.sync_jobs`/`.sync_state`/`.delivery_attempts`, [DATABASE_MODEL.md §19](architecture/DATABASE_MODEL.md#19-security-audit-and-integration))
- adapter-facing contracts: the `dnd_ai.commands.*` surface a client adapter (Foundry, the web portal, or a later integration) calls once Phase 10's API exists to route to it — defined and tested now, exposed over HTTP later

Exit criteria:

- Item ownership and possession are distinct and independently queryable.
- Combat resolved through `resolve_combat_turn` updates persistent character state (`campaign.character_state`) through a causal event, entirely through the command layer — never a direct table write (rule 3) — proven by `tests/scenario`, locally and in CI against `dev`.
- An external system's identifier for a world entity, and a synchronization job's lifecycle, are representable and round-trip through `integration.*` without any client writing PostgreSQL directly.
- Live Foundry synchronization is explicitly excluded and moves to [Phase 11](#phase-11-foundry-mvp); Phase 9 proves only the persistence and application-service behavior that the later adapter will call.

### Phase 10: Core API and playable vertical slice

> **Revised deployment boundary:** Phase 10 continues and delivers the portable application/API layer for local production. FastAPI runs under Uvicorn in a container and connects to local PostgreSQL through private Compose networking. Lambda, Mangum, API Gateway, Lambda IAM/deployment packaging, AWS-only networking/RDS access, and AWS-specific production telemetry are not required acceptance criteria. If a Lambda adapter exists or is later useful, it must remain isolated and optional.

Phase 10 delivers the smallest usable application boundary over the existing domain and persistence layers. It owns the end-to-end vertical slice in [§25](#25-vertical-slice-acceptance-scenario), establishes the security boundary used by every client, and is the first phase with an application deployable.

**Progress.** Workstream 1 (`080_security_identity_and_access`) delivered the `security.*` schema. Workstream 2 (`src/dnd_ai/domain/access.py`) delivered the effective-access resolver, including the rule that a campaign resolves access only against its own pinned timeline — never an unrelated timeline, branch, or a different world's — documented in that module and in [DATABASE_MODEL.md §19.7](architecture/DATABASE_MODEL.md#197-effective-access-resolution); a mismatch raises `UnauthorizedTimelineError`, mapped at the API boundary to a fixed, non-disclosing 404 rather than echoing the timeline/campaign IDs involved. Workstream 3 (`src/dnd_ai/api/`) delivered the FastAPI application skeleton: `/healthz` (process liveness) and `/readyz` (a real database round trip through the normal engine wiring, failing closed with a fixed, non-secret body), correlation IDs (a client-supplied `X-Correlation-Id` is length- and character-validated before being trusted, echoed, or logged — never passed through verbatim), and one-transaction-per-request dependency. `src/dnd_ai/domain/errors.py`'s `SafeMessageError`/`DomainAuthorizationError` give a domain error explicit, type-level control over its client-facing message: `safe_message` is a fixed string owned by the exception *type*, never derived from the constructor argument (`str(self)`), so raising `SafeMessageError` with some text does not, by itself, make that text safe to expose — only a subclass that deliberately defines its own `safe_message` can. Every API error handler logs one fixed-shape, safe line — exception class, response status/error code, correlation ID, and the matched route *template* — and never `str(exc)`, a traceback, or any other exception-specific text, for any handler, including the ones that previously used `logger.exception`/`exc_info=`. `IntegrityError` is classified by PostgreSQL SQLSTATE: unique/exclusion-constraint violations map to a fixed 409 that describes the conflict but makes no retry promise (a unique violation is not, by itself, a demonstrated case where retrying the same request would succeed — only a command that recognizes a specific optimistic-concurrency/idempotency case should say that, through its own exception type); not-null/foreign-key/check violations map to a conservative, non-disclosing 400; and a missing or unrecognized SQLSTATE — evidence of an application/schema/runtime defect, not a request the caller could have made differently — maps to a fixed 500, never guessed at as 400 or 409. A follow-up correction pass closed four further deployable-boundary gaps once the first Phase 10 cut was reviewed against ADR 0012: `ApiError` and framework-raised `StarletteHTTPException`s (FastAPI's own routing 404/405, or any `HTTPException(...)` a call site raises) now carry the identical fixed, type-level `safe_message` discipline `SafeMessageError` already had — `ApiError.safe_message` is a class attribute, never the constructor's `detail` argument, and `exc.detail` on a framework `HTTPException` is never trusted or echoed, only its `status_code` selecting a fixed message from a closed vocabulary; request-validation field *locations* (`fields[].field`) are bounded and character-restricted before being echoed, since a `loc` entry can itself carry an `extra="forbid"` model's rejected extra key or a `dict[str, X]` body's own key verbatim from the request, not just an ordinary field name; and the accepted `X-Correlation-Id` shape was narrowed from a loosely bounded `[A-Za-z0-9._-]{1,100}` character class (which still admitted token/password-like text that would then be echoed and logged) to exactly a canonical UUID, normalized to lowercase, with anything else replaced by a freshly generated server UUID. A second correction pass found that character-shape filtering on a validation field *location* was itself the wrong tool — an identifier-shaped secret (`SUPER_SECRET_TOKEN_ABC123`) is indistinguishable by shape from a legitimate dynamic key — so `fields[].field` is gone entirely: the generic 422 response now carries only `error_codes`, a bounded, allowlisted list of pydantic's own error-*type* codes with no location of any kind, and `handle_validation_error` logs through the same sanitized `_log_error` path every other handler uses instead of logging nothing. The same pass also closed `ApiError`'s remaining ad hoc path: the `error_code=`/`status_code=` constructor overrides (added in the first Phase 10 cut for "ad hoc" cases) let a raise site turn arbitrary runtime values into public response/log fields, so they're gone — `status_code`, `error_code`, and `safe_message` are now exclusively fixed, type-level class attributes on `ApiError` and its four narrowly scoped subclasses (`UnauthorizedError`/`ForbiddenError`/`NotFoundError`/`ConflictError`), and `handle_api_error` additionally re-validates even a subclass's own attributes against a small, fixed, server-owned vocabulary before trusting them, falling back to the base class's fixed internal-error contract for anything unrecognized. A third correction pass found that second pass's "small, fixed, server-owned vocabulary" was still too permissive — it checked `status_code` and `error_code` independently (any identifier-shaped code paired with any status from a small set), which doesn't enforce that a *particular* triple was ever actually registered. `dnd_ai.api.errors._API_ERROR_CONTRACTS` now maps each exact recognized `ApiError` subclass to its one fixed `(status_code, error_code, safe_message)` triple, and `_validated_api_error_response` requires the exception's current attributes to equal that triple exactly — an unrecognized subclass, a status paired with the wrong code, or an altered message on an otherwise-known type all fall back identically. The same pass closed two further gaps: `_sanitize_validation_error_types` no longer echoes pydantic's own `type` string at all, even syntax-checked — an identifier-shaped custom-validator type (`secret_token_abc123`) passed the same character check a real pydantic type would, and pydantic's internal vocabulary isn't a contract this module should mirror anyway — so validation responses now carry only a small, fixed public vocabulary (`missing`/`invalid_type`/`invalid_format`/`out_of_range`/`invalid`) mapped by exact dict lookup against a closed set of real pydantic type strings, with every unmapped type (built-in or custom) falling back to `invalid`; and `handle_http_exception` no longer forwards `exc.status_code` to the response verbatim for an unrecognized value — `_SUPPORTED_HTTP_EXCEPTION_STATUSES` is now the complete, explicit set of framework statuses this application forwards (currently just routing 404/405), and anything else, however HTTP-shaped, gets the fixed 500/internal-error contract instead. A fourth correction pass closed two remaining gaps found after that third pass: `handle_http_exception` returned a 405 with no `Allow` header at all, and separately, unrecognized/unclassified failures across different handlers described the identical 500/`internal_error` category with two different wordings ("The request could not be processed." from `ApiError`'s own base-class default versus "An unexpected error occurred." everywhere else). `dnd_ai.api.errors._INTERNAL_ERROR_CONTRACT` is now the one canonical, immutable `(500, "internal_error", "An unexpected error occurred.")` triple every unclassified/fallback path returns and logs — `ApiError`'s own class attributes are defined from it, so a bare or unrecognized `ApiError` is exactly this contract rather than a fourth independently-maintained copy. A 405 response now carries a server-constructed `Allow` header (`_method_not_allowed_allow_header`), never from `exc.headers` — a directly raised `HTTPException(status_code=405, headers={...})` could otherwise carry a forged `Allow` value or an arbitrary sensitive header a caller or careless call site chose. A fifth correction pass found that fourth pass's `Allow` construction was itself incomplete: it read only `request.scope["route"]`, but Starlette's router remembers just the *first* route whose path matches but whose method doesn't, so when the same path is registered as separate routes per method (e.g. `@app.get("/same")` and a separate `@app.post("/same")`), the header reported only the first one's method, silently omitting the rest. `_method_not_allowed_allow_header` now unions `methods` across every application route whose own `.matches()` — the same framework logic Starlette's router uses internally, never custom path/regex matching — accepts the request's path, whether by a full or partial match; an endpoint that explicitly raises the supported 405 contract is covered by the same general union rather than a special case, and an unrelated path never contributes methods to another path's header. Application configuration (`src/dnd_ai/config.py`) is namespaced under `DND_AI_*` with an explicit allowlist for the test/CI/seed variables that share the namespace but belong to other subsystems (`DND_AI_TEST_DATABASE_URL`, `DND_AI_CI_DB_NAME`, `DND_AI_SEEDS_DIR`), and is genuinely fail-closed in production: `DND_AI_ENVIRONMENT=production` is selected only by the real process/deployment environment (checked before `.env` is even considered for loading), skips loading `.env` entirely once selected, and requires `DND_AI_DATABASE_URL` (a real environment variable or a mounted secret file named `dnd_ai_database_url`) — the legacy unprefixed `DATABASE_URL` alias and the local-dev default both remain local/test-only, and `.env` cannot promote a process into production either: if the real environment doesn't already request it, `.env` is loaded, but if `.env` itself then sets `DND_AI_ENVIRONMENT=production`, that fails startup outright rather than silently taking effect. Workstream 4 (`src/dnd_ai/domain/tokens.py`, `src/dnd_ai/api/auth.py`) delivered OIDC bearer-token verification — the scoping pass the first Phase 10 cut's own `app.py` docstring deferred explicitly ("needs its own scoping pass: library choice, JWKS caching, and a no-live-provider test strategy"). Library choice: `pyjwt[crypto]`, over `python-jose` (stalled maintenance, past CVEs) and `authlib` (heavier, bundles its own HTTP/OAuth client); its `PyJWKClient` fetches and caches a JWKS document over stdlib `urllib`, so this added no new runtime HTTP-client dependency (`httpx` remains dev-only). `dnd_ai.domain.tokens.verify_bearer_token()` is framework-free, mirroring `dnd_ai.domain.access`'s own scoping: it always passes `algorithms=["RS256"]` explicitly to `jwt.decode()` and rejects any other `alg` header value before ever resolving a signing key — closing the classic `alg=none`/algorithm-confusion class of JWT vulnerability — and resolves the signing key through an injected `kid -> RSAPublicKey` callable rather than owning a JWKS client itself, so unit tests (`tests/unit/test_token_verification.py`) supply a plain dict-backed fake against a locally generated RSA keypair instead of a live identity provider or JWKS HTTP server. Every failure mode (malformed token, disallowed algorithm, unresolvable `kid`, bad signature, wrong issuer/audience, expired token, missing required claim) raises one new `dnd_ai.domain.errors.AuthenticationError`, picked up automatically by the already-registered generic `SafeMessageError` handler with no new wiring in `api/errors.py`. `src/dnd_ai/api/auth.py` adds the FastAPI-layer dependencies: `get_jwks_client()` (a process-wide singleton mirroring `deps.get_engine`'s shape, 5-minute JWKS cache), `get_verified_token_claims()` (header extraction plus verification), and `get_authenticated_user_id()` (resolves a verified token to its linked `security.users` row via the already-existing but previously-unused `domain.access.resolve_user_by_external_identity()`, raising `UnauthorizedError` for an unknown or revoked identity). `dnd_ai.config.Settings` gained `oidc_issuer`/`oidc_audience`/`oidc_jwks_url`, optional locally/in tests and required together in production via the same fail-closed `@model_validator` pattern `database_url` already established. Deliberately out of scope: updating `security.external_identities.last_authenticated_at`/`.claims_snapshot` on each authenticated request, which belongs in a dedicated login/session-establishment command with its own atomicity and audit shape (rule 6), not implicitly on every request a bare verification dependency handles; and no protected business endpoint exists yet to actually use `get_authenticated_user_id`, the same way `get_connection` shipped as reusable plumbing before any command endpoint used it. Workstream 5 (`src/dnd_ai/api/access.py`, `src/dnd_ai/api/encounters.py`) began "command endpoints over the existing command/application services" with the encounter domain: `start_encounter`, `resolve_combat_turn`, and `end_encounter` ([PHASE9_VERIFICATION.md](PHASE9_VERIFICATION.md)) are now reachable over HTTP as `POST /campaigns/{campaign_id}/encounters`, `.../encounters/{encounter_id}/turns`, and `.../encounters/{encounter_id}/end`. `dnd_ai.api.access.require_campaign_capability()` is the reusable dependency factory every future command/query endpoint route can build on: it resolves `dnd_ai.domain.access.resolve_access_context()` against the route's own `campaign_id` path parameter and a capability code, mapping no active membership to a non-disclosing `NotFoundError` and an authenticated member lacking the capability to `ForbiddenError` — the same "prefer NotFound when existence itself is a disclosure" rule §19.7 and `ApiError`'s own docstring already establish. All three encounter routes require the campaign-wide `canon.edit` role capability for this first cut (encounter management treated as GM/adapter-level, not yet extended to a player submitting their own character's turn via `character.control`). `dnd_ai.commands.encounters.start_encounter`/`end_encounter` were each split into a connection-taking `_..._impl` plus a thin engine-based public wrapper — the same composition `resolve_combat_turn`/`_resolve_combat_turn_impl` already used for `apply_foundry_combat_sync` — so these routes run on the request's own `get_connection` transaction rather than opening a second, nested one; `resolve_combat_turn`'s existing split needed no change. No new idempotency-key store was added: `narrative.encounter_turns`' existing `UNIQUE(encounter_round_id, participant_id)` (revision 078) already turns a naive client retry into a 409 through the existing `IntegrityError` handler. Workstream 6 (`src/dnd_ai/api/items.py`) continued "command endpoints over the existing command/application services" into the item domain: `transfer_item_possession` and `identify_item` ([PHASE9_VERIFICATION.md](PHASE9_VERIFICATION.md)) are now reachable over HTTP as `POST /campaigns/{campaign_id}/items/{item_instance_id}/transfer` and `.../items/{item_instance_id}/identify`, both requiring `canon.edit` in the target campaign, the same first-cut GM/adapter-level scoping workstream 5 chose for encounter management. `dnd_ai.commands.items.transfer_item_possession`/`identify_item` were each split into a connection-taking `_..._impl` plus a thin engine-based public wrapper, identical to workstream 5's `start_encounter`/`end_encounter` split, so these routes also run on the request's own `get_connection` transaction. Unlike the encounter routes, there is no encounter-style "does this resource belong to my campaign" ownership check: neither `world.item_instances` nor `campaign.inventory_entries`/`knowledge.item_identification` carries a `campaign_id` at all — they are scoped by `timeline_id`, taken from the resolved `AccessContext` (the campaign's own pinned timeline), never from the request body, and a cross-world item instance is rejected atomically by the existing `campaign.enforce_inventory_entry_world()` (revision 077) as a generic `IntegrityError` → 400, not a bespoke application-layer lookup. `SessionNotInCampaignError` and its `validate_session_campaign()` check — previously private to `dnd_ai.commands.encounters` — moved to `dnd_ai.commands._shared` (encounters.py re-exports the name unchanged) once the item commands needed the identical caller-supplied-`session_id`-vs-trusted-`campaign_id` guard; both `transfer_item_possession`/`identify_item` now apply it, closing a gap neither command had before (no caller previously supplied both `campaign_id` and `session_id` together). **Workstream 6 correction pass.** A review against this section's own "retries do not duplicate effects" vertical-slice criterion (§25) found that workstream 6's original cut re-applied a retried transfer/identify request rather than deduplicating it — a naive client retry (a dropped response, a proxy timeout) created a second `narrative.events`/`.event_effects` pair instead of returning the original result, and neither route wrote an `audit.change_log` row at all despite `audit.change_log` already existing (revision 007) and Phase 10's own §25/architecture docs requiring atomic auditing for command endpoints. Two additions close both gaps, both delivered by revision `082_item_command_idempotency`: `security.idempotent_requests` (schema: DATABASE_MODEL.md §19.8) is a durable, PostgreSQL-backed store for `dnd_ai.api.deps.get_idempotency_key`'s `Idempotency-Key` header — `dnd_ai.api.idempotency.begin_idempotent_request()` reserves `(actor_user_id, campaign_id, idempotency_key)` via a single `INSERT ... ON CONFLICT DO NOTHING` (the unique index itself serializes concurrent requests for the same key — no `SELECT ... FOR UPDATE`, advisory lock, or in-memory cache) before the command runs, and `complete_idempotent_request()` fills in the response before the same transaction commits; because the reservation lives inside the command's own transaction, a rolled-back or failed attempt never durably consumes the key, and a retry with a mismatched fingerprint (a different command or a different payload reusing the same key) gets the existing `ConflictError` contract (fixed 409) rather than being replayed or silently applied. `dnd_ai.api.audit.record_change_log()` is the first API-layer writer for `audit.change_log`: one row per successful call, on the same connection, identifying `actor_user_id` from the resolved `AccessContext` — never a command's own `actor_entity_id` argument, which is an unrelated in-world attribution that may be absent or point somewhere unrelated to the authenticated caller — plus the request's correlation ID (`dnd_ai.api.correlation.get_request_correlation_id`, factored out of `dnd_ai.api.errors` so both share one validated accessor), the fixed command name, the affected record/entity/world, and the resulting `event_id`. `dnd_ai.api.deps.get_idempotency_key` now also bounds and character-restricts the header value before it can reach the store, a log line, or an error response — the same discipline already applied to `X-Correlation-Id` — rejecting a malformed value outright (400) rather than silently substituting a generated one, which would defeat the caller's own idempotency contract without telling it. `dnd_ai.commands.items.TransferItemPossessionResult`/`IdentifyItemResult` each gained a `world_id` field (already computed internally, just not previously returned) so the API layer can populate `audit.change_log.world_id` without a duplicate lookup. Workstream 7 (`src/dnd_ai/api/quests.py`) continued "command endpoints over the existing command/application services" into the quest domain: `advance_objective` ([PHASE7_VERIFICATION.md](PHASE7_VERIFICATION.md)) is now reachable over HTTP as `POST /campaigns/{campaign_id}/quests/objectives/{quest_objective_id}/advance`, requiring `canon.edit` in the target campaign — the same first-cut GM/adapter-level scoping workstreams 5 and 6 chose for encounter and item management. `dnd_ai.commands.quests.advance_objective` was split into a connection-taking `_advance_objective_impl` plus a thin engine-based public wrapper, identical to the encounter and item commands' composition, so this route also runs on the request's own `get_connection` transaction. `AdvanceObjectiveResult` gained a `world_id` field (computed internally via the existing `_quest_objective_world` lookup) so the API layer can populate `audit.change_log.world_id` without a duplicate query. Like the item routes, there is no encounter-style "does this resource belong to my campaign" ownership check: neither `narrative.quest_objectives` nor `campaign.objective_state` carries a `campaign_id` at all — they are scoped by `timeline_id`, taken from the resolved `AccessContext`. Unlike the original (pre-workstream-6-correction-pass) commands, `_advance_objective_impl` applies `validate_session_campaign()` against its caller-supplied `session_id`/`campaign_id` from the start — the same guard workstream 6's correction pass added to the item commands — since the command was previously only called with server-trusted arguments and never validated that pairing itself. Idempotency (`security.idempotent_requests`) and `audit.change_log` auditing are wired identically to workstreams 5 and 6. **Workstream 7 correction pass.** A review found two further gaps. First, `party_id` had no campaign-scope check at all: `campaign.campaign_parties` (revision 010) only enforces that a party and the campaigns using it agree on *world* (`campaign.enforce_campaign_party_world()`), so a same-world party belonging only to a *different* campaign passed cleanly, letting a caller advance an objective "for" a party with no relationship to the campaign named in the request. `dnd_ai.commands.quests._validate_campaign_party()` (kept local to that module, not promoted to `dnd_ai.commands._shared` — no second caller needs it yet, mirroring `_shared`'s own promote-on-second-use history) now requires an authoritative `campaign.campaign_parties` row for exactly `(campaign_id, party_id)` before any mutation, raising the new `PartyNotInCampaignError` (a `DomainAuthorizationError`, the same fixed non-disclosing 404 contract `SessionNotInCampaignError` already carries) for a nonexistent or foreign-campaign party; `party_id=None` remains a no-op, matching every other optional caller-supplied scope check in this codebase. Second, `audit.change_log.entity_id` was populated with `quest_objective_id` — not a `core.entities` row at all (only the owning quest is, via class-table inheritance; `narrative.quest_objectives`/`.quest_stages` have no entity identity of their own), contradicting that column's own documented contract (migration 007: "The `core.entities` row this change concerns"). The former `_quest_objective_world()` lookup became `_quest_objective_context()`, returning both `world_id` and `quest_id` in one query (no redundant second lookup); `AdvanceObjectiveResult` gained a `quest_id` field, and `dnd_ai.api.quests` now records `entity_id=result.quest_id`. Both checks run inside `_advance_objective_impl`, before any row is touched, so a rejected call — with or without an `Idempotency-Key` — leaves no `campaign.objective_state`/`narrative.events`/`.event_effects`/`audit.change_log` row and no completed idempotency reservation, the same rollback guarantee every other rejected command endpoint in this codebase already has. **Tests:** `tests/database/test_api_quests.py` gained a second campaign on the same timeline plus a party associated only with it, and cases proving the cross-campaign party is rejected (404) both with and without an idempotency key, alongside the existing entity_id audit assertion now checking the owning quest's ID rather than the objective's. Workstream 8 (`src/dnd_ai/api/relationships.py`) continued "command endpoints over the existing command/application services" into the relationship/organization domain: `evolve_relationship_reaction` and `update_organization_status` ([PHASE8_VERIFICATION.md](PHASE8_VERIFICATION.md)) are now reachable over HTTP as `POST /campaigns/{campaign_id}/relationships/{relationship_id}/evolve` and `.../organizations/{organization_id}/status`, both requiring `canon.edit` in the target campaign — the same first-cut GM/adapter-level scoping every earlier command router chose. `dnd_ai.commands.relationships.evolve_relationship_reaction`/`update_organization_status` were each split into a connection-taking `_..._impl` plus a thin engine-based public wrapper, identical to every other command router's composition, so these routes also run on the request's own `get_connection` transaction; unlike workstream 7's `advance_objective`, neither command previously had this split (Phase 8 predates Phase 10's API layer entirely), so this workstream is the first to apply it here. Both `_impl` functions also gained `validate_session_campaign()` against their caller-supplied `session_id`/`campaign_id` — neither `world.relationships`/`campaign.relationship_state` nor `world.organizations`/`campaign.organization_state` carries a `campaign_id` at all (both scoped by `timeline_id`, like the item and quest domains), so this closes the same class of gap workstream 6's correction pass closed for items. Both `Result` dataclasses gained a `world_id` field (already computed internally via `_relationship_world`/`_organization_world`, just not previously returned) so the API layer can populate `audit.change_log.world_id` without a duplicate lookup. `audit.change_log.entity_id` is deliberately asymmetric between the two routes, learned directly from workstream 7's correction pass rather than repeating its mistake: `world.organizations` rows are `core.entities` rows via class-table inheritance (`organization_id` *is* the entity_id, confirmed by `_organization_world`'s own `core.entities` lookup), so `update_organization_status_endpoint` records `entity_id=organization_id` directly; `world.relationships` rows are not `core.entities` rows at all and have no single owning entity a relationship could resolve to (unlike a quest objective's owning quest), so `evolve_relationship_reaction_endpoint` records `entity_id=None` — matching `entity_id`'s own documented contract, "the `core.entities` row this change concerns, *when there is one*" (migration 007), rather than forcing a value that doesn't exist. Idempotency (`security.idempotent_requests`) and `audit.change_log` auditing are wired identically to every earlier workstream. **Tests:** `tests/database/test_api_relationships.py` covers access control, both commands' state transitions (including a relationship's independent shared/subjective-holder rows), invalid-status and cross-campaign-session rejection, the full idempotency suite (sequential replay, concurrent reservation via the established `lock_timeout` idiom, mismatched-payload and cross-endpoint key reuse, retry-after-rollback, unauthorized-with-key), and the entity_id asymmetry itself — one test per route, asserting `entity_id IS NULL` for the relationship route and `entity_id = organization_id` for the organization route. Workstream 9 (`src/dnd_ai/api/events.py`, `src/dnd_ai/api/interactions.py`) completed "command endpoints over the existing command/application services" with the last remaining domain this section's own progress note named: `record_event` ([ENTITY_LIFECYCLE.md §21](ENTITY_LIFECYCLE.md#21-service-commands)), `perform_interaction`, and `resolve_check` ([PHASE6_VERIFICATION.md](PHASE6_VERIFICATION.md)) are now reachable over HTTP as `POST /campaigns/{campaign_id}/events`, `.../interactions`, and `.../checks/{check_request_id}/resolve`, all three requiring `canon.edit` in the target campaign — the same first-cut GM/adapter-level scoping every earlier command router chose (interactions and check resolutions are, in principle, more naturally player-initiated, but extending to a narrower character-scoped capability is left for a caller that actually needs it, not invented speculatively here). `dnd_ai.commands.events.record_event` and `dnd_ai.commands.interactions.perform_interaction`/`.resolve_check` were each split into a connection-taking `_..._impl` plus a thin engine-based public wrapper, identical to every other command router's composition; `resolve_check`'s existing internal use of `_insert_event_row` (to record the conditional-route-opening event) is untouched — only its own caller-supplied session/campaign arguments go through the new validation, never the trusted values `resolve_check` derives from the interaction it already locked. `_record_event_impl`/`_perform_interaction_impl` both gained `validate_session_campaign()` against their caller-supplied `session_id`/`campaign_id`, the same guard every earlier workstream's correction pass added; `record_event`'s own `world_id` argument is never accepted from the request body either — `dnd_ai.api.events` resolves it server-side from the campaign's own pinned timeline (`campaign.timelines.world_id`), the same "never trust a caller-supplied world/timeline pairing" rule already applied to `timeline_id`. Unlike every earlier workstream, `interaction.interactions` *does* carry its own `campaign_id` column (like `narrative.encounters`), so `resolve_check` needed the same "does this resource belong to my campaign" ownership check workstream 5 established for encounters rather than the item/quest/relationship domains' campaign-less scoping: `_lock_interaction_for_check_resolution()` replaces the former two-step `_interaction_id_for_check_request()`/`_lock_interaction_for_resolution()` pair with one locked read that resolves `check_request_id`'s parent interaction, locks it, and — when `expected_campaign_id` is supplied — asserts its `campaign_id` matches before anything is mutated, raising `InteractionNotFoundError` (a `DomainAuthorizationError`, fixed non-disclosing 404) for a nonexistent check request or one belonging to a different campaign, mirroring `dnd_ai.commands.encounters.EncounterNotFoundError`/`_lock_encounter` exactly. The same function's former "already terminal" `ValueError` became `InteractionNotOpenError` (a `SafeMessageError` mapping to 409, matching `EncounterNotActiveError`) — still a `ValueError` subclass with "terminal" in its message, so the existing scenario-test assertion (`tests/scenario/test_resolve_conditional_route_check.py`) needed no change. `PerformInteractionResult`/`ResolveCheckResult` each gained the fields the API layer needed but the command previously computed and discarded: `world_id` on both, plus `actor_entity_id` on `ResolveCheckResult`. Neither `interaction.interactions` nor `interaction.check_results` is a `core.entities` row, so both routes record `audit.change_log.entity_id` as the acting character's own `actor_entity_id` — the same "resolve to a real owning entity" indirection workstream 7's correction pass established for quest objectives — while `record_event_endpoint` records `entity_id=result.event_id` directly, since `narrative.events` rows *are* `core.entities` rows via class-table inheritance. Idempotency (`security.idempotent_requests`) and `audit.change_log` auditing are wired identically to every earlier workstream. **Tests:** `tests/database/test_api_events.py` and `tests/database/test_api_interactions.py` cover access control, the happy path for all three commands, session/campaign-mismatch rejection, the `resolve_check` campaign-ownership check (a check request resolved against a campaign the caller has real `canon.edit` access to, but that isn't the check's own owning campaign, is rejected as 404 with no `check_results` row left behind), the terminal-interaction 409, the audit `entity_id` split described above, and one idempotency replay/conflict case per route. Workstream 10 (`src/dnd_ai/api/integration.py`) continued "command endpoints over the existing command/application services" into the world-scoped half of the `integration` domain: `register_external_system` and `map_external_identifier` are now reachable over HTTP as `POST /campaigns/{campaign_id}/integration/external-systems` and `.../external-systems/{external_system_id}/identifiers`, both requiring `canon.edit` in the target campaign — the same first-cut GM/adapter-level scoping every earlier command router chose. `dnd_ai.commands.integration.register_external_system`/`.map_external_identifier` were each split into a connection-taking `_..._impl` plus a thin engine-based public wrapper, identical to every other command router's composition. `apply_foundry_combat_sync` deliberately gained no endpoint: its own module docstring already reasons that it has no authoritative `campaign_id` to authorize against until Phase 11 maps Foundry users to platform users, and separately, its three-transaction, session-scoped-advisory-lock design (needed so a naive redelivery can't duplicate a combat mutation) is incompatible with the one-transaction-per-request model every other command endpoint relies on for atomic auditing — retrofitting either concern here would mean designing them without the real Foundry-adapter caller Phase 11 introduces, so both are left for that phase instead. Neither `integration.external_systems` nor `.external_identifiers` carries a `campaign_id` (both are world-scoped, like the item/quest/relationship domains before them), so `world_id` is always resolved server-side from the campaign's own pinned timeline via the new `dnd_ai.api._shared.timeline_world_id()` — promoted out of `dnd_ai.api.events`'s own identical inline lookup once this workstream needed the same thing a second time, mirroring `dnd_ai.commands._shared`'s own promote-on-second-use history. `map_external_identifier_endpoint` closes a gap none of the world-scoped item/quest/relationship domains had to consider: `integration.enforce_external_identifier_world()` (revision 079) only guarantees `external_system_id` and the mapped `entity_id` agree with *each other*, never with the caller's own authorized world, so a caller authorized only for one campaign/world could otherwise target an `external_system_id` belonging to an entirely different one. `dnd_ai.commands.integration._map_external_identifier_impl` now accepts an `expected_world_id` argument that asserts this before writing anything, raising the new `ExternalSystemNotFoundError` (a `DomainAuthorizationError`, fixed non-disclosing 404, mirroring `dnd_ai.commands.encounters.EncounterNotFoundError`'s identical reasoning) otherwise; no row lock is needed the way `_lock_encounter` needs one, since `external_systems.world_id` is immutable once created (no command ever reparents one to a different world). Idempotency is asymmetric between the two routes, each independently justified: `register_external_system` has no natural dedup key (every call inserts a new row), so `register_external_system_endpoint` wires the same durable `security.idempotent_requests` mechanism every mutating route uses; `map_external_identifier` already upserts on `ux_external_identifiers_system_kind_external` (its own docstring: "re-registering the same external object is idempotent"), the same reasoning `dnd_ai.api.encounters` used to skip a bespoke idempotency store for its own naturally-deduplicated routes. Auditing: `integration.external_systems` rows have no `core.entities` identity (adapter-facing infrastructure, not a world entity), so `register_external_system_endpoint` records `entity_id=None`; `map_external_identifier_endpoint` records `entity_id=body.entity_id` directly — the caller already supplies the real entity the mapping concerns, so no owning-entity indirection lookup is needed the way quest objectives/relationships required one. **Tests:** `tests/database/test_api_integration.py` covers access control, both commands' happy paths, `register_external_system`'s idempotency replay/conflict pair, the upsert-not-duplicate behavior of a remapped identifier, the cross-world rejection (a caller with real `canon.edit` access to a *different* campaign/world's `external_system_id` is rejected as 404 with no `external_identifiers` row left behind), and both routes' distinct audit `entity_id` contracts. Workstream 11 (`Dockerfile`, `compose.yaml`, `compose.override.yaml`, `.github/workflows/ci.yml`) delivered "a FastAPI application entry point executed by Uvicorn and containerized as a portable service" and the "Docker Compose integration appropriate to this phase" from this section's own Deliver list: a new `api` service in `compose.yaml`, built from the same `Dockerfile` `migrate` already builds — the image's `ENTRYPOINT` (`uv run --no-sync`) is unchanged; only the service's own `command:` (`uvicorn dnd_ai.api.app:app --host 0.0.0.0 --port 8000`) selects this role, the same mechanism `migrate`'s `command:` already used. `api` reaches `db` over the compose-internal network via a new required `API_DATABASE_URL` (mapped to the container's `DND_AI_DATABASE_URL`) — deliberately a separate setting from `MIGRATION_DATABASE_URL`, not reused, even though both currently authenticate as the same `postgres` superuser: no least-privileged application database role is bootstrapped yet (`docs/DATABASE_CONVENTIONS.md`'s "Application roles should not own schemas or tables"), so this reuses the superuser credential for now and flags introducing a scoped role as future hardening rather than inventing one speculatively here. Unlike `migrate`, `api` carries no `profiles:` restriction — it is a standing service plain `docker compose up` starts, not a one-off job — and it publishes no host port in the base `compose.yaml`, matching `db`'s own "no ports by design" discipline; `compose.override.yaml` adds a `127.0.0.1`-only mapping for local development, mirroring `db`'s override exactly. Its container `HEALTHCHECK` polls `/healthz` (not `/readyz`) via a Python-standard-library one-liner (`urllib.request` — this image has no `curl`/`wget`) run directly through the image's own `PATH`, since a Docker `HEALTHCHECK` exec bypasses `ENTRYPOINT` entirely; `/healthz`'s own deliberate database-independence (`dnd_ai.api.app`'s docstring) means the container is never reported unhealthy merely because PostgreSQL is briefly unreachable. `scripts/check_compose_config.py`'s merged-config check and `.github/workflows/ci.yml`'s `docker-build` job were both extended in step with `db`'s existing checks: no host port for `api` either, plus a build, a `--wait`-gated health check, and a `/readyz` round trip against the migrated database exec'd inside the running container — proving the full chain (image build, Uvicorn boot, real PostgreSQL connectivity over the compose network) works, not merely that the container starts. The `persistence-check` job's `env:` block also gained `API_DATABASE_URL`, alongside the existing `MIGRATION_DATABASE_URL`, for the same already-documented reason: Compose interpolates every service's `environment:` block up front regardless of which service a command actually targets, so an `up -d db`-only job still fails at config-parsing time without it. Verified locally end to end (Docker Desktop, not just source-level YAML parsing): built the image, brought up `db`+`api` together, confirmed `api` reported healthy, and exec'd a `/readyz` call returning `200 {"status":"ready"}` — then tore the disposable run down and confirmed the pre-existing local dev database (a different, persistent `db` container/volume) still held its data afterward, since a CI-profile `down -v` against a `tmpfs`-backed `db` does not touch the named `dnd_ai_pgdata` volume. Deliberately **not** delivered here: the actual reverse proxy this section's Deliver list also names ("one local path through the reverse proxy") — `§32`'s own text already assigns "Compose, reverse proxy, ... automatic TLS, secure cookies/CSRF, rate limits" to Phase 14 and states "nothing in this section is built yet," so standing up even a minimal proxy container now would be building ahead of the phase that owns its design; `api` is positioned to sit behind one later (no host port by default, binds `0.0.0.0:8000` only inside the compose network) without pre-empting that phase's own routing/TLS decisions. **Tests:** `tests/unit/test_compose_files.py` gained source-level coverage for `api` mirroring `db`'s own (`API_DATABASE_URL` required with no fallback, no host port in the base file, `compose.override.yaml` binds `127.0.0.1` only, no `profiles:` gate, shares `migrate`'s `build:`, healthcheck targets `/healthz` not `/readyz`); `tests/unit/test_check_compose_config.py` gained the same for the merged-config check, generalizing `check_no_published_ports()` to take a `service_name` rather than hardcoding `db`. **Workstream 11 correction pass — critical production configuration defect.** The original cut passed `api` only `DND_AI_DATABASE_URL`, leaving `DND_AI_ENVIRONMENT` at `dnd_ai.config.Settings`' own `"local"` default inside the container. `/healthz` and `/readyz` still passed (neither touches OIDC), so the container looked healthy, but every authenticated route failed closed with a generic 500 — `dnd_ai.api.auth.get_jwks_client()`'s own `assert settings.oidc_jwks_url is not None` — instead of the intended 401, and production's fail-closed/HTTPS validation (`dnd_ai.config`'s own `model_validator`) never ran at all. Fixed by making `DND_AI_ENVIRONMENT=production` a fixed literal in `compose.yaml`'s `api` service — never a variable, so no missing host-side setting can silently reintroduce this — plus three new required, no-fallback variables (`DND_AI_OIDC_ISSUER`/`DND_AI_OIDC_AUDIENCE`/`DND_AI_OIDC_JWKS_URL`, mapped from host-side `API_OIDC_ISSUER`/`API_OIDC_AUDIENCE`/`API_OIDC_JWKS_URL` the same way `API_DATABASE_URL` maps to `DND_AI_DATABASE_URL`). Forcing `production` is what makes the three OIDC variables actually required and HTTPS-validated — `dnd_ai.config`'s own all-or-nothing production rule rejects a partial or non-HTTPS configuration outright at process startup. `.env.example`'s OIDC section now distinguishes two paths with different requirements: running the API directly on the host (`uv run uvicorn ...`, `DND_AI_ENVIRONMENT` left at `"local"`) still runs without any OIDC configuration for local exploration of the non-authenticated endpoints, while `docker compose up -d api` — this file being the self-hosted/production deployment topology, not a "local" convenience default — always requires a real, HTTPS OIDC provider. `scripts/check_compose_config.py`'s merged-config check gained `check_api_environment_configured()`, asserting the rendered `api` service's `DND_AI_ENVIRONMENT` equals `"production"` and all three `DND_AI_OIDC_*` keys are present and non-empty. `.github/workflows/ci.yml`'s `docker-build` and `persistence-check` jobs both gained disposable, syntactically valid HTTPS `API_OIDC_ISSUER`/`API_OIDC_JWKS_URL` values and a non-empty `API_OIDC_AUDIENCE` (never a live identity provider — `PyJWKClient` fetches lazily, so constructing `_JWKSClient` in `get_jwks_client()` makes no network call by itself), for the same "Compose interpolates every service's environment block up front" reason `API_DATABASE_URL` already needed both jobs. A new negative CI step proves each of the three OIDC variables truly has no fallback: `docker compose config` is run once per variable with exactly that one unset (`env -u VAR`, every other required variable still set), asserting Compose itself refuses to render a config rather than silently substituting an empty string. The container smoke test was extended beyond `/healthz`/`/readyz` (both deliberately left unchanged — `/healthz` still process-liveness-only and DB-independent, `/readyz` still a real database round trip only) with a third check: `POST /campaigns/{campaign_id}/events` with a well-formed body but no `Authorization` header, exec'd inside the running container, asserting the fixed 401 `UnauthorizedError` contract — proving the OIDC dependency chain (`get_jwks_client` → `get_verified_token_claims`) is wired and constructible in this exact deployment configuration without ever calling `get_signing_key()` (a missing header is rejected before that call), so this proves configuration correctness without depending on network access to a real identity provider. **Tests:** `tests/unit/test_compose_files.py` gained coverage asserting `api`'s `DND_AI_ENVIRONMENT` is the literal `"production"` (not interpolated) and that all three `DND_AI_OIDC_*` environment values use `:?` with no `:-` fallback, each referencing its own distinct `API_OIDC_*` host-side variable; `tests/unit/test_check_compose_config.py` gained the fabricated-config equivalent for the new merged-config check, including the negative case (a config missing one `DND_AI_OIDC_*` key fails the check). **Workstream 11 correction pass 2 — critical production security defect.** `api` still connected to PostgreSQL as the `postgres` superuser after the first correction pass — `API_DATABASE_URL` was never actually required to identify anything else, so nothing stopped it. This is a materially different failure mode from the OIDC gap the first correction pass closed: it does not fail closed, and it does not merely disable a feature — a request that reached the database at all (`/readyz`, or any command endpoint, once OIDC was fixed) ran with full schema-DDL, role-management, and RLS-bypass capability, regardless of whether the application code itself ever intended to use it. `001_bootstrap` (revision 001) already defines exactly the role this should have used: `app_read_write`, `LOGIN`, DML-only, no membership in `migration_owner`, not a superuser, no schema ownership, no `CREATEDB`/`CREATEROLE`/`BYPASSRLS` — ADR 0009's whole reason for splitting an owning role from login roles in the first place. Fixing this surfaced a second, independent, more fundamental defect underneath it: `001_bootstrap` grants `app_read_write`/`app_read_only`/`integration_worker` table/sequence-level DML via `ALTER DEFAULT PRIVILEGES`, but never grants any of them `USAGE` on the schemas those tables live in — PostgreSQL requires schema `USAGE` before a role can reference *any* object inside it, independent of that object's own grants, so every one of those DML grants had been unreachable since Phase 1. This had never been caught because every test, and the application itself, had only ever connected as `postgres` or (until this pass) `api`'s own superuser identity — never as `app_read_write` — so the gap was invisible to every existing grant-presence test (`tests/database/test_role_grants.py` already checked `information_schema.role_table_grants` correctly; it just never proved those grants were *reachable*). New migration `083_schema_usage_grants` closes it: `GRANT USAGE ON SCHEMA <all thirteen>` to `app_read_write`/`app_read_only` (matching their existing table-grant scope exactly — no role's *capability* changed, only what was already granted became usable), and `GRANT USAGE ON SCHEMA integration` to `integration_worker` (matching its own narrower existing scope). Verified directly against a real cluster before and after: a session authenticated as `app_read_write` got `permission denied for schema core` on a bare `SELECT` before this migration, despite holding `SELECT` on that exact table per the grant tables — and worked immediately after. Function `EXECUTE` needed no equivalent fix — PostgreSQL grants `EXECUTE` on a new function to `PUBLIC` by default and no migration in this repository has ever revoked that, confirmed by grepping the full `database/` tree.

`compose.yaml`'s `api` service now hardcodes `DND_AI_DATABASE_URL: ${API_DATABASE_URL:?...}` with a comment stating the required identity explicitly (`app_read_write`, never `postgres`/`migration_runner`/`migration_owner`) — enforcement here is necessarily the executable database-level proof below, not a static check on an opaque, operator-supplied URL string, since Compose can't inspect what password/role a URL a human pasted into `.env` actually names. The credential-provisioning gap this exposed — `app_read_write` has existed since Phase 1 with **no password at all**, so nothing could ever have authenticated as it — is closed by a new `scripts/operations/database_recovery.py set-role-password` subcommand: `--role` accepts only the five real `LOGIN` roles (`argparse`'s own `choices=`, never `migration_owner`); the new password comes from `--password-env-var`/`--password-file` (mutually exclusive, mirroring `dnd_ai.config.Settings`' own environment-variable-or-mounted-secret duality) and is **never** accepted as a `--password` flag, which would leave it visible in `ps`/`docker top`/shell history for as long as the process ran; it reaches PostgreSQL only inside the STDIN payload of a piped `psql ALTER ROLE ...` statement (`_pg_string_literal` — client-side SQL-literal escaping by doubling embedded quotes, the standard mechanism under `standard_conforming_strings = on`), never a command-line argument, mirroring `_grant_create_on_database`'s existing stdin-piping pattern for a non-secret value and extending the same discipline to a genuinely secret one. It carries no `--confirm-*` gate (it mutates exactly one role's credential, nothing else) and is fully idempotent — rerunning it with a new value rotates the password, the same command serving as the rotation path, which is what keeps migration and application credentials independently rotatable (they are always two separate roles with two separate passwords, never shared). `check_roles()` (used by both `verify-roles` and `bootstrap-roles`) gained a per-LOGIN-role password-presence check against `pg_authid.rolpassword IS NOT NULL` — deliberately `WARN`, not a hard failure, since `bootstrap-roles` calls this immediately after creating fresh roles, before an operator has had any chance to run `set-role-password` yet; a standalone `verify-roles` run (what an operator actually runs to confirm the full sequence completed) still surfaces a missing password as a visible report line. This is the "enforce," not merely "document," half of the required `migrate` → `set-role-password` → `up -d api` ordering: Compose has no native dependency mechanism for a `profiles: ["tools"]` one-off job (`migrate`) or a step external to Compose entirely (`set-role-password`), the same limitation that already made `migrate` a manual, documented first step before this correction pass existed — `verify-roles`'s new automated check is what makes "did the operator actually complete the sequence" a scriptable yes/no instead of only a documentation promise. `.env.example`/`docs/DEVELOPMENT.md` §3.6/`docs/operations/DATABASE_RECOVERY.md` all gained a "Provisioning application-role credentials" walkthrough, and every prior "no least-privileged application database role exists yet... reuses the superuser credential for now... tracked as future hardening" statement from the first correction pass was removed and replaced with the actual enforced boundary — this was never meant to describe an accepted interim state.

CI's `docker-build` job (the only job that spins up a real, containerized `api`) now provisions `app_read_write`'s password through the *actual* `set-role-password` command — not a hand-rolled SQL equivalent — immediately after `migrate` and before starting `api`, using a disposable `API_READ_WRITE_PASSWORD`; this required adding `Install uv`/`Set up Python`/`Install dependencies` steps to that job (every other step in it only ever shelled out to `docker compose`). A new step then connects with the exact `app_read_write` credential `API_DATABASE_URL` configures — over `docker compose exec` with the password passed as the exec'd process's own environment variable (`-e PGPASSWORD=...`), never a `psql` command-line flag — and proves both directions live, against this job's own disposable database, not merely `tests/database/test_app_read_write_role.py`'s separate instance: a real `SELECT` succeeds, and both `CREATE TABLE` and `SET ROLE migration_owner` are rejected with `permission denied`. `persistence-check`'s `API_DATABASE_URL` placeholder (never actually connected to — that job only starts `db`) was updated to name `app_read_write` too, for consistency, even though its value is otherwise inert there. **Tests:** `tests/database/test_role_grants.py` gained static assertions that `app_read_write` is not a superuser, cannot `CREATEDB`/`CREATEROLE`/`BYPASSRLS`, is not a member of `migration_owner`, and owns no schema. `tests/database/test_app_read_write_role.py` is new: a real, authenticated connection as `app_read_write` (a session-scoped fixture sets a fixed, openly test-only password directly, since these tests must be self-sufficient against a freshly migrated database rather than assuming an operator already provisioned one) proving the identity (`current_user`, `rolsuper`/`rolbypassrls` both false), the positive path (`SELECT`/`INSERT`/`UPDATE`/`DELETE` through the same `tests/factories.py` helpers application code effectively mirrors, plus calling `world.conditional_route_requirement_satisfied()` directly), and the full negative path (`CREATE`/`ALTER`/`DROP TABLE`, `CREATE ROLE`, altering another role's password, `SET ROLE migration_owner`, `TRUNCATE`, and `UPDATE`/`DELETE` against `audit.change_log`) all in one place. `tests/unit/test_database_recovery_set_role_password.py` covers `_pg_string_literal`'s escaping (including a SQL-metacharacter password proving the fix isn't merely "no error today") and `_read_role_password`'s env-var/file resolution, both/neither-source rejection, and the single-trailing-newline-only file-stripping rule.

**Workstream 11 correction pass 3 — remaining High production security gap.** Correction pass 2 made `compose.yaml`/`.env.example`/every doc *describe* `app_read_write` as the required identity, but nothing in `src/dnd_ai` actually checked it: a stale `postgres` or `migration_runner` `API_DATABASE_URL` still started the container, still passed `/healthz` and `/readyz`, and would have silently recreated the exact privileged-API defect pass 2 fixed — enforcement lived entirely in Compose comments and CI convention, never in the process that matters. Two independent checks close this, both scoped to `DND_AI_ENVIRONMENT=production` only (local/test intentionally keep connecting as the `postgres` admin credential, unaffected). **Static:** `dnd_ai.config.Settings` gained `_require_app_read_write_identity_in_production`, a `model_validator` that parses `DND_AI_DATABASE_URL` with SQLAlchemy's own `make_url` (never string splitting — a percent-encoded password can legally contain `@`/`:`/`/`) and refuses to start unless the parsed username is exactly `PRODUCTION_REQUIRED_DATABASE_ROLE` (`app_read_write`); the error names only the expected role, never the configured URL or its password. This proves what the configured URL *claims*, not what a live connection actually authenticates as — those can diverge (a connection pooler/proxy remapping the credential, an implicit/explicit `SET ROLE` after authentication), so a second, **live** check closes that gap: `dnd_ai.api.deps.verify_database_identity()` opens a real connection and asserts `SELECT session_user, current_user` both equal `app_read_write`, checking both rather than just `current_user` specifically so a `SET ROLE` can't mask a mismatch (verified directly: a superuser session that does `SET ROLE app_read_write` reports `current_user = app_read_write` while `session_user` still shows the original role). `dnd_ai.api.app`'s lifespan startup calls this eagerly, before `yield`, only when `settings.environment == "production"` — deliberately here rather than deferred to `/readyz`: a lifespan-startup exception aborts Uvicorn's own startup entirely, so the process never binds its port and `/healthz` can never be reached at all, strictly stronger than a 503 from a route that still requires the process to be up and answering. On failure the engine is disposed before the exception propagates, so no connection leaks past the failed startup. **Tests:** `tests/unit/test_config.py` gained the static-check regression suite (rejects `postgres`/`migration_runner`/`migration_owner` identities, accepts `app_read_write`, rejects an unparseable URL, and confirms the failure message never contains the configured URL or password); every existing production-`Settings()` test fixture that previously used an arbitrary `prod:prod@dbhost` credential now uses `app_read_write` so those tests keep exercising their own original concern (OIDC validation, `.env`/mounted-secret precedence) rather than tripping the new identity check instead. `tests/unit/test_api_app.py` gained lifespan-level regression tests (stubbing `get_engine`/`verify_database_identity`/`dispose_engine` at the module level, no real database needed) proving the check runs and disposes-on-failure in production and never runs at all outside it. `tests/database/test_database_identity_enforcement.py` is new: proves `verify_database_identity`/its connection-level helper against a real cluster — a `postgres` admin connection fails the check, an `app_read_write` connection passes it, an explicit `SET ROLE app_read_write` from a superuser session still fails it (the dual session_user/current_user proof), and the raised message contains neither the admin connection's password nor any URL-shaped substring. The `app_read_write_engine`/`app_read_write_connection` fixtures moved from `test_app_read_write_role.py` into a new `tests/database/conftest.py` so both files share one definition. `docs/operations/DATABASE_RECOVERY.md`'s stale "acceptable only because today's topology runs nothing but `alembic upgrade head`... not the intended eventual model once `src/dnd_ai/api` exists" line — written before `src/dnd_ai/api` existed at all — was replaced with the actual enforced boundary description; no other doc described superuser API access as an accepted future-hardening item (pass 2 already removed those).

Workstream 12 (`src/dnd_ai/queries/dungeon.py`, `src/dnd_ai/api/dungeon.py`) began "query services for the effective dungeon, character, quest, relationship, inventory, encounter, and knowledge state required by the vertical slice" — the deliverable workstreams 5-11 left untouched while every command endpoint was built first. `dnd_ai.queries` is the new package for this half of the deliverable list, mirroring `dnd_ai.commands`' framework-free, connection-taking shape (docs/architecture/SYSTEM_ARCHITECTURE.md §5.4, §6) but with no `_..._impl`/engine-wrapper split, since a read has no transaction-boundary reason to open its own. `get_dungeon_area_view()` is the first query: the effective, audience-filtered state of one `world.dungeon_areas` row — its definition, current `campaign.location_state`, and every structural child (`world.area_features`/`.area_hazards`/`.area_interactables`/`.area_connections`, each joined to its own `campaign.*_state` table) — reachable over HTTP as `GET /campaigns/{campaign_id}/dungeon-areas/{dungeon_area_id}`, satisfying §25 steps 7-8 ("move the party into the dungeon... search an area and discover the trap but not the hidden door"). This is the "party/public knowledge-derived access... resolved by the query layer that already has a character perspective" `dnd_ai.domain.access` (workstream 2) explicitly deferred to this workstream in its own docstring.

Audience filtering is the query's central new concept, not yet needed by any command endpoint: a caller holding `canon.edit` (a GM) receives every structural child regardless of `is_hidden`; anyone else receives a hidden child only once their party has discovered it — a `knowledge.knowledge_items` row whose `subject_area_*_id` names that exact child, joined to a `knowledge.party_discoveries` row for `(timeline_id, party_id)`. A hidden, undiscovered child is dropped from the result set entirely, not merely flagged, satisfying §25 step 15's "cannot be inferred through counts... or errors" for this first query the same way every command endpoint's non-disclosure already does for mutations. `PartyNotInCampaignError`/`_validate_campaign_party`, originally private to `dnd_ai.commands.quests` (workstream 7's correction pass), moved to `dnd_ai.commands._shared` as `validate_campaign_party` once this query needed the identical check — the same promote-on-second-use history `SessionNotInCampaignError`/`validate_session_campaign` already went through; `dnd_ai.commands.quests` re-exports both names unchanged.

**Workstream 12 correction pass — High authorization defect.** The original cut trusted a caller-supplied `party_id` for hidden-content filtering once `validate_campaign_party` confirmed it was associated with the caller's own campaign — but campaign-party association is a fact about the *fictional world* (which parties a campaign uses), not about which *authenticated user* is entitled to see through any one of them. Any member holding only `campaign.view` could supply any other same-campaign party's UUID and read that party's hidden dungeon discoveries, regardless of whether they controlled, could view, or had ever heard of a character in it — exactly the gap docs/architecture/DATABASE_MODEL.md §15 warns against ("a fact known by a character is exposed to a user only when that user has the appropriate character relationship and capability for the requested perspective"). `dnd_ai.api.access.resolve_party_perspective()` closes it: the endpoint now accepts `character_id` alongside `party_id`, and a hidden-content perspective is authorized only once three independent checks all pass — the caller holds `character.view_knowledge` (this codebase's own seed data names it for exactly this purpose) for `character_id` via `AccessContext.has_capability` (role capabilities, the caller's own resolved `security.membership_character_relationships` row, and any `security.resource_grants` override, exactly as every other capability check in this codebase already resolves); `party_id` is associated with `campaign_id` (`validate_campaign_party`, unchanged); and `character_id` is *currently* a member of that exact `party_id` on the campaign's own timeline — a `campaign.party_memberships` row with `effective_to_world_time_id IS NULL`, that table's own documented "the single representation of 'still a member'" (migration 009), used as a trusted, time-independent perspective contract rather than guessing a fictional "now" this API has no other source for, and never derived from `character_id` alone, since a character may belong to several parties at once. `character_id`/`party_id` supplied together but failing any of the three raises the new `PartyPerspectiveNotAuthorizedError` (a fixed, non-disclosing 404, identical for a missing capability, a foreign-campaign party, and a party the character does not currently belong to) rather than silently downgrading; only *both* omitted (or only one of the two supplied) is treated as "no perspective requested," the existing safe default limiting the response to non-hidden content. A `canon.edit` caller (GM) still needs no perspective at all — `character_id`/`party_id` are never even resolved for that caller. `dnd_ai.queries.get_dungeon_area_view` itself is unchanged: it remains framework-free and performs no authorization of its own, trusting `party_id` only because its one caller now guarantees it has already been through this exact chain. **Tests:** `tests/database/test_api_dungeon.py`'s fixture gained a second, same-campaign party with its own current member and discoveries; new cases prove a caller with an authorized character sees that party's discoveries, the same caller cannot use the other party's UUID (with or without a character genuinely in it that the caller isn't authorized to view), an unauthorized character cannot unlock any party, and every existing GM/no-perspective/foreign-campaign/cross-world case still passes unchanged.

Authorization: the route requires the new `campaign.view` role capability (this codebase's own seed data names it for exactly this purpose; every command router instead requires `canon.edit`, since this is Phase 10's first read-only endpoint). Cross-campaign/world ownership: neither `world.dungeon_areas` nor its structural children carry a `campaign_id` (world-scoped, like the item/quest/relationship domains) — `get_dungeon_area_view()` itself asserts the area's own `core.entities.world_id` matches the caller's resolved-timeline world (`dnd_ai.api._shared.timeline_world_id`, never caller-supplied), raising `DungeonAreaNotFoundError` (a fixed, non-disclosing 404) identically for a nonexistent area or one in a different world. No idempotency key and no `audit.change_log` row: this is a read, and `audit.change_log`'s documented scope (login-linked identity changes, role/access changes, sensitive reads, writes) does not cover a routine, already-authorized dungeon-area read. **Tests:** `tests/database/test_api_dungeon.py` covers access control (non-member 404, capless-member 403), GM-vs-player audience filtering across all four structural-child kinds, the party-discovers-one-of-several-hidden-children case (proving filtering is per child, not an all-or-nothing party flag), connection direction/other-area reporting, `campaign.location_state` defaults when no state row exists, the cross-campaign `party_id` rejection, and the cross-world area rejection.

Workstream 13 (`src/dnd_ai/queries/character.py`, `src/dnd_ai/api/characters.py`) continued "query services for the effective dungeon, character, quest, relationship, inventory, encounter, and knowledge state required by the vertical slice" into the character domain: `get_character_view()` reassembles `character.characters`/`rules.species` (definition) with `campaign.character_state`/`.character_conditions`/`.character_resources`/`.character_location_history` (current timeline state), reachable over HTTP as `GET /campaigns/{campaign_id}/characters/{character_id}`. Where workstream 12's audience split was GM-vs-party-perspective, this one is a two-tier detail split this codebase's own seed data already names for exactly this purpose: `character.view_summary` (name, species code, size category only) versus `character.view_full` (adds current/maximum/temporary hit points, exhaustion level, death save counts, current conditions, current resources, and current location) or `canon.edit` (a GM, same bypass workstream 12 established). `dnd_ai.api.access.resolve_character_view_tier()` is the new resource-scoped resolver alongside workstream 12's `resolve_party_perspective()` — pure `AccessContext` logic, no database access, since (unlike a party perspective) there is no further fictional-world fact to verify once `AccessContext.has_capability(..., character_id=...)` has answered which tier applies; a caller holding neither capability for the named character gets the same fixed, non-disclosing 404 a nonexistent character would (`CharacterViewNotAuthorizedError`), never a 403, since confirming a real character exists that the caller simply cannot view would itself be a disclosure. `dnd_ai.queries.character.get_character_view` never even fetches the full-tier data when `include_full=False`, rather than fetching and withholding it. Cross-world ownership mirrors workstream 12 exactly: `character.characters` carries no `campaign_id`, so the query asserts the character's own `core.entities.world_id` against the caller's resolved-timeline world (`dnd_ai.api._shared.timeline_world_id`), raising `CharacterNotFoundError` identically for a nonexistent character or one in a different world. No idempotency key or `audit.change_log` row, for the same reasons workstream 12's endpoint has neither. **Tests:** `tests/database/test_api_characters.py` covers access control (non-member 404, capless-member 403, a member holding `campaign.view` but no character-specific capability 404), both view tiers' exact field sets, the GM bypass, and cross-world/nonexistent-character rejection; `tests/factories.py` gained `make_condition`/`make_resource_definition` (the same ruleset-content-lookup shape `make_species`/`make_ability` already established) and `make_character_condition`/`make_character_resource`/`make_character_location_history`.

**Workstream 13 correction pass — High authorization defect.** The original cut's `resolve_character_view_tier()` checked `access.has_capability("canon.edit")` with no `character_id` — every other check in the same function (`character.view_full`, `character.view_summary`) passed `character_id=character_id`, but the `canon.edit` check didn't, and `AccessContext.has_capability`'s own contract makes that a real gap, not a stylistic inconsistency: passing no resource target skips its `security.resource_grants` lookup entirely and returns the role-only baseline. A `security.resource_grants` row explicitly *denying* `canon.edit` for one specific character — a deliberate, targeted restriction a GM's own resource-grant tooling exists to express — was silently ignored, and a role-derived GM always saw full detail regardless. The fix is one added argument: `access.has_capability("canon.edit", character_id=character_id)`, so the same deny-overrides-allow-overrides-baseline resolution `character.view_full`/`character.view_summary` already receive now applies to `canon.edit` too, with no behavior change for the ordinary case (a role that grants `canon.edit` with no character-scoped grant at all still resolves `True` from the same role-only baseline). **Tests:** `tests/database/test_api_characters.py` gained three regression cases — a character-targeted `canon.edit` deny granted directly to the GM's own membership, paired with a `character.view_summary` allow grant to prove the resolution falls through to the summary tier specifically rather than merely failing some check; an equivalent deny inherited through `security.access_group_memberships` rather than a direct grant, left with no compensating allow so the fixed 404 contract applies; and a character-targeted `canon.edit` *allow* granted to a member with no role-derived `canon.edit` at all, proving `AccessContext.has_capability`'s existing allow-grant semantics (§19.6) now reach this check end to end. Every existing GM/full-view/summary-view/no-character-capability/cross-world/nonexistent-character test continues to pass unmodified.

Workstream 14 (`src/dnd_ai/queries/quest.py`, `src/dnd_ai/api/quests.py`) continued "query services for the effective dungeon, character, quest, relationship, inventory, encounter, and knowledge state required by the vertical slice" into the quest domain, reachable over HTTP as `GET /campaigns/{campaign_id}/quests/{quest_id}` on the same router `dnd_ai.commands.quests.advance_objective`'s command endpoint already uses (one router per domain, command and query routes together). `get_quest_view()` reassembles `narrative.quests`/`.quest_stages`/`.quest_objectives` (definition) with `campaign.quest_state`/`.objective_state` (current progress), audience-filtered by `narrative.quest_objectives.visibility_policy` — the vocabulary revision 074 added ('visible', 'hidden_until_active', 'hidden_until_discovered', 'gm_only') and documented there as "an inferred, illustrative vocabulary." A GM (`canon.edit`) sees every objective regardless of policy; a non-GM always sees `'visible'` objectives, never `'gm_only'` ones, and sees a `'hidden_until_active'`/`'hidden_until_discovered'` objective only once *some* `campaign.objective_state` row exists for it (party-scoped or campaign-wide) — this first cut deliberately collapses the two "hidden until" values to one shared "has this objective's own tracked history begun at all" signal rather than inventing a separate per-knowledge-item discovery check the way `dnd_ai.queries.dungeon` does for structural children; the column's own migration comment already scopes it as illustrative rather than a fixed contract, so splitting the two is deferred until a caller actually needs the distinction. Party scope reuses workstream 12's `dnd_ai.api.access.resolve_party_perspective` unchanged (`character.view_knowledge`, the same capability): both `campaign.quest_state` and `.objective_state` may carry a campaign-wide row (`party_id IS NULL`) and independent per-party rows simultaneously (migration 073's own partial unique indexes), so the query prefers an authorized party's own row over the campaign-wide one wherever both exist, falling back to campaign-wide when no party row does. Cross-world ownership mirrors workstreams 12-13: `narrative.quests` carries no `campaign_id`, so the query asserts the quest's own `core.entities.world_id` against the caller's resolved-timeline world, raising `QuestNotFoundError` identically for a nonexistent quest or one in a different world. No idempotency key or `audit.change_log` row, for the same reasons every other Phase 10 read endpoint has neither. **Tests:** `tests/database/test_api_quests_query.py` covers access control, all four `visibility_policy` values (including the has-state/no-state contrast between the two "hidden until" values), the party-over-campaign-wide status fallback for both quest- and objective-level state, and cross-world/nonexistent-quest rejection; party-perspective authorization itself is not re-tested exhaustively here, since `tests/database/test_api_dungeon.py` already covers every edge case of the shared `resolve_party_perspective` function.

Workstream 15 (`src/dnd_ai/queries/relationship.py`, `src/dnd_ai/api/relationships.py`) continued "query services for the effective dungeon, character, quest, relationship, inventory, encounter, and knowledge state required by the vertical slice" into the relationship domain, reachable over HTTP as `GET /campaigns/{campaign_id}/relationships/{relationship_id}` on the same router `dnd_ai.commands.relationships.evolve_relationship_reaction`/`update_organization_status`'s command endpoints already use. `get_relationship_view()` reassembles `world.relationships`/`.relationship_participants` (definition) with `campaign.relationship_state` (current status), which is itself split between one shared, objective row (`perspective_holder_entity_id IS NULL`) and independent per-participant subjective rows (migration 076's own partial unique indexes, `ux_relationship_state_timeline_relationship_no_holder`/`..._holder`). Participants and the shared row are always returned to any `campaign.view` caller — who is related to whom is a structural fact — but subjective rows (`affinity`/`trust`/`respect`/`fear`/`obligation`/`emotional_tone` and a `private_interpretation` the schema itself documents as private, §10.1) are returned only to a caller holding `canon.edit`, deliberately conservative rather than guessing a per-holder character-relationship rule the way `dnd_ai.queries.character`'s two-tier split does for a single character — `dnd_ai.queries.character`'s "fetch nothing rather than fetch-and-withhold" discipline applies here too: `subjective_states` is never even queried for a non-GM caller. `world.relationship_perspectives` (the world-scoped, author-time baseline this state table's subjective rows evolve from) is out of scope for this first cut — `campaign.relationship_state` is the current, timeline-scoped read a live session needs; organizations (`world.organizations`/`campaign.organization_state`, workstream 8's other command endpoint) are also deferred to a later workstream, not bundled speculatively into this one. Cross-world ownership is simpler than every prior query workstream: `world.relationships.world_id` is a direct, non-nullable column (the table is not entity-rooted), so no `core.entities` join is needed to assert it against the caller's resolved-timeline world before raising `RelationshipNotFoundError` for a mismatch or nonexistent relationship. No idempotency key or `audit.change_log` row, for the same reasons every other Phase 10 read endpoint has neither. **Tests:** `tests/database/test_api_relationships_query.py` covers access control, the GM-sees-everything/player-sees-shared-only split (including that a non-GM's `subjective_states` is an empty list, not a redacted one), and cross-world/nonexistent-relationship rejection.

Workstream 16 (`src/dnd_ai/queries/inventory.py`) continued "query services for the effective dungeon, character, quest, relationship, inventory, encounter, and knowledge state required by the vertical slice" into the item domain, reachable over HTTP as `GET /campaigns/{campaign_id}/characters/{character_id}/inventory` on `dnd_ai.api.characters`, the same router workstream 13's character-detail read already uses. `get_inventory_view()` reassembles `rules.item_definitions`/`world.item_instances` (definition) with `campaign.item_state`/`.item_ownership`/`campaign.inventory_entries` (current condition, legal owner, and current possessor) — a direct query, not a maintained index table, confirming this document's own §19.7 reconciliation note on `campaign.character_inventory` ("Phase 9, which owns items, should confirm whether a separate index table is actually warranted or whether a view/query suffices"): no such table was ever built, and this workstream is that confirmation. Definition and timeline-state fields (name, category, rarity, quantity, condition, charges, equipped/destroyed, current legal owner) are never described as secret anywhere in this schema, so they are always returned once the caller is authorized to view the holder's inventory at all; an item's hidden mechanical properties (`rules.item_definitions.properties_jsonb`) are gated by `knowledge.item_identification`, resolved from exactly one perspective — the holder's own (`knower_entity_id = holder_entity_id`) — rather than an arbitrary caller-supplied knower, since that would be the same class of question `dnd_ai.api.access.resolve_party_perspective`/`resolve_character_view_tier` already answer for their own resources and inventing a third variant for a case no caller has needed yet would be speculative. Authorization at the API layer reuses workstream 13's `resolve_character_view_tier` directly against `character_id` (the holder), but is stricter than the character-detail read itself: `False` (summary tier) is treated as unauthorized here too — inventory has no summary form — raising the same `CharacterViewNotAuthorizedError` fixed 404 that function already raises for "neither capability held." A caller holding `canon.edit` sees every item's full properties regardless of the holder's own identification state, mirroring every other GM bypass in this phase. **Tests:** `tests/database/test_api_characters_inventory.py` covers access control (including the summary-tier-insufficient case), all three identification levels plus the no-identification-row default, the GM bypass, and cross-world holder rejection; `tests/factories.py`'s `make_item_definition` gained a `properties` parameter (JSONB, same pattern `make_quest_objective`'s `completion_rule` already established).

Workstream 17 (`src/dnd_ai/queries/encounter.py`) completed "query services for the effective dungeon, character, quest, relationship, inventory, encounter, and knowledge state required by the vertical slice"'s named-domain list with the encounter domain, reachable over HTTP as `GET /campaigns/{campaign_id}/encounters/{encounter_id}` on `dnd_ai.api.encounters`, the same router the three combat command endpoints already use. `get_encounter_view()` reassembles `narrative.encounters`/`.encounter_participants`/`.encounter_rounds`/`.encounter_turns` and `interaction.combat_actions` directly — this domain has no separate "definition versus state" split the way every other query workstream's domain does (§13: "the database captures synchronized state and meaningful outcomes rather than duplicating every tactical decision"). It is also the first Phase 10 query with **no audience filtering at all**: every prior workstream's domain drew a real line (a GM's full view vs. a party's discovered subset, `gm_only` objectives, subjective relationship rows, identification-gated item properties), but a round, turn, or combat action is already a resolved outcome — the same "observations and consequences" every interaction participant already witnesses (§16) — so any `campaign.view` caller sees the identical full record a GM does. Cross-campaign ownership reuses `dnd_ai.commands.encounters.EncounterNotFoundError` directly (re-exported by `dnd_ai.queries.encounter`, not duplicated) rather than defining a parallel error type, since `narrative.encounters.campaign_id` is a direct column — unlike every world-scoped domain queried so far — and both raise the identical fixed, non-disclosing 404 for "doesn't exist or belongs to a different campaign." No idempotency key or `audit.change_log` row, for the same reasons every other Phase 10 read endpoint has neither. **Tests:** `tests/database/test_api_encounters_query.py` covers access control, the full unfiltered participant/round/turn/combat-action record, and cross-campaign/nonexistent-encounter rejection.

Workstream 18 (`src/dnd_ai/queries/knowledge.py`, `src/dnd_ai/api/knowledge.py`) completed the exact named-domain list in "query services for the effective dungeon, character, quest, relationship, inventory, encounter, and knowledge state required by the vertical slice" with the knowledge domain, reachable over HTTP as `GET /campaigns/{campaign_id}/knowledge/{knowledge_item_id}` on a new `dnd_ai.api.knowledge` router — the first Phase 10 router with no command endpoint at all, since canon knowledge is currently written only as a side effect of discovery/interaction commands, not through a dedicated mutation endpoint. `get_knowledge_view()` resolves exactly the audience split `knowledge.knowledge_items` (ground truth) versus `campaign.party_knowledge` (a party's own current belief, deliberately kept separate so a false belief is never silently overwritten by the canonical truth, §15) already implies: a GM (`canon.edit`) sees `canonical_statement`/`truth_status_code`/`sensitivity` regardless of any party's belief; anyone else must supply an authorized party perspective (workstream 12's `resolve_party_perspective`, `character.view_knowledge`, reused unchanged) and sees only that party's own `awareness_level`/`confidence`/`willing_to_share` plus a `statement` resolved as the party's own recorded `interpretation` when one exists, falling back to the canonical text when the party's belief carries no recorded distortion — never the ground-truth `truth_status`/`sensitivity` metadata. Per §15's own list of authorization paths ("because the user's selected character knows it, because the user's party knows it, because it is public, ... or because an explicit resource grant allows it"), this first cut resolves only the party-belief path; public knowledge (`knowledge.public_knowledge`) and individual `knowledge.entity_knowledge` are deferred until a caller actually needs them. An omitted perspective and an authorized party with no `campaign.party_knowledge` row for the item at all both resolve to the identical fixed, non-disclosing 404 (`KnowledgeNotAuthorizedError`) a nonexistent item would — a knowledge item's own existence can itself be sensitive (`sensitivity` up to `'dangerous'`), so "exists but your party doesn't know it" must be indistinguishable from "doesn't exist," the same principle `dnd_ai.queries.dungeon` already applies to undiscovered structural children. No idempotency key or `audit.change_log` row, for the same reasons every other Phase 10 read endpoint has neither. **Tests:** `tests/database/test_api_knowledge.py` covers access control, the GM-ground-truth-vs-party-belief split for both an accurately- and a falsely-believed item, the omitted-perspective and no-belief-record non-disclosure cases, an unauthorized (foreign-campaign) party rejection, and cross-world/nonexistent-item rejection.

This closes out the seven-domain query-services list workstreams 12-18 were named for. Still to come: organization state (a query sibling to workstream 15's relationship read, deferred there), the deterministic audience-filtered summary/detail reads (GM/player-character/observer campaign summaries, docs/PLAN.md §25 step 15), OIDC-backed campaign invitation/membership/role-assignment/access-revocation command endpoints (§19.1-19.6's data model exists; no command endpoint creates or revokes a membership, role assignment, or resource grant yet), and the actual reverse-proxy container (deliberately deferred to Phase 14 — see workstream 11 above). `apply_foundry_combat_sync`'s own HTTP exposure is also deliberately deferred, to Phase 11 (Foundry MVP), where a real Foundry-adapter caller and its authorization/transaction shape are designed together rather than retrofitted here — see workstream 10 above and `dnd_ai.commands.integration`'s own module docstring. A Lambda adapter is neither required nor part of the production path; see ADR 0012.

Deliver:

- a FastAPI application entry point executed by Uvicorn and containerized as a portable service
- database transaction and session management with cross-domain transaction boundaries owned by the application layer
- command endpoints over the existing command/application services
- query services for the effective dungeon, character, quest, relationship, inventory, encounter, and knowledge state required by the vertical slice
- deterministic, audience-filtered summary and detail query services for current campaign/session state, active quests, recent events, locations, characters, NPCs/factions, inventory, knowledge, and the prior-session recap
- stable request and response contracts usable by the web portal, Foundry, and future clients
- OIDC-backed login integration for `dev`, authenticated user mapping, campaign invitations/memberships, campaign-scoped multi-role assignment, capabilities, and access revocation
- many-to-many user-character relationships and resource-access grants sufficient for the vertical slice, including access derived through roles, controlled characters, parties, and knowledge
- centralized access resolution and server-side filtering for rows, fields, relationships, counts, search results, and summary inputs
- audit records for login-linked identity changes, role/access changes, sensitive reads, and all writes
- correlation and idempotency identifiers and consistent error contracts
- health and readiness endpoints; environment-variable or mounted-secret configuration; local PostgreSQL connectivity; and Docker Compose integration appropriate to this phase
- one local path through the reverse proxy, as defined in [§32](#32-local-production-deployment-plan)
- end-to-end execution of the existing vertical-slice acceptance scenario through the API

Keep the endpoint surface limited to what that scenario needs:

- establish or retrieve the required world, timeline, campaign, party, session, characters, NPC, dungeon, encounter, items, and quest
- enter a location or dungeon area and retrieve party-visible context
- search or interact with a feature and resolve a check
- record the resulting event and interaction
- atomically apply dungeon, character, inventory, encounter, knowledge, and quest changes where required
- retrieve knowledge filtered for the requesting party or character
- retrieve distinct GM, player-character, and observer summaries without disclosing hidden-resource existence
- end a session
- verify effective state in another campaign and a branched timeline

Exit criteria:

> The complete vertical-slice scenario executes through the application API without direct client writes to PostgreSQL. Authenticated GM, player, and observer requests receive only their permitted rows, fields, relationships, search results, counts, and summaries; a user can relate to multiple characters and a character or fact can relate to multiple users. Required cross-domain changes commit atomically, retries do not duplicate effects, and campaign/timeline isolation is preserved.

Testing focuses on application behavior and this end-to-end scenario. Do not create another generalized test framework or duplicate database invariants already adequately tested in earlier phases.

Phase 10 also proves secure authentication cookies, CSRF protection, and player, GM, observer, and user-to-detail many-to-many access enforcement through the reverse proxy. Its application contracts, command/query services, transaction/session management, validation, authorization, audit, correlation, and idempotency behavior remain platform-neutral.

### Phase 11: Foundry MVP

Wires Phase 9's `integration.*` schema and adapter-facing contracts through Phase 10's API to the smallest playable Foundry integration. Build the concrete encounter flow before designing any general-purpose bidirectional synchronization framework.

Deliver:

- associate Foundry worlds, scenes, actors, tokens, items, and encounters with canonical platform records
- retrieve party-visible state for the current location or encounter
- submit interactions, checks, combat outcomes, and meaningful state changes through the API
- synchronize the minimum required character HP, conditions, resource use, inventory, and encounter results
- handle duplicate delivery and retries safely
- restore synchronized state after reopening or reconnecting
- map Foundry users to authenticated platform users and enforce the same campaign, character-control, knowledge, and resource-access rules as the API and portal

Exit criteria:

> A real Foundry encounter updates canonical state through the application API, and reopening or reconnecting retrieves the updated state without duplicate events or direct database access.

### Phase 12: Narrow AI/NPC MVP

AI delivery is separate from the web-portal implementation and world/campaign-data import. Start with one NPC portrayal/conversation use case, one provider, one audience-aware summary/question path, and one authorized representative rules source—preferably an applicable SRD or user-authored homebrew document—before broader AI infrastructure.

Deliver:

- deterministic context assembly using existing knowledge and visibility rules
- the smallest useful rules/reference corpus described in [§18.3](#183-rulesreference-corpus-ingestion-and-retrieval): source registration and rights validation, immutable source/hash retention, structured extraction, passage provenance, PostgreSQL full-text indexing, filtered retrieval, citations, removal, and auditing
- one NPC portrayal/conversation use case and one AI provider
- structured generated output
- audience-aware on-demand synthesis over the deterministic summary/detail query services, including player/character questions, observer-safe summaries, and GM preparation briefs
- proposed changes that require validation and the configured approval path before becoming canonical
- auditing of AI requests, context selection, responses, proposals, and decisions

Exit criteria:

- The NPC receives only permitted knowledge; party-private and character-private knowledge do not leak.
- Responses can reference current encounter, quest, and relationship state.
- AI output cannot directly mutate canonical state.
- Rejected or invalid proposals leave canonical state unchanged.
- One authorized rules source can be registered, extracted, indexed, and retrieved.
- A rules question retrieves cited passages from the campaign-selected edition and source, including section or page location.
- A conflicting edition or unauthorized source is excluded, and a campaign house rule takes precedence over the general rule.
- Registering or ingesting reference material does not create or mutate canonical campaign state.
- Removing or disabling a source prevents later retrieval.
- Corpus retrieval and downstream AI use are auditable.
- Normal automated tests prove retrieval behavior without live AI-provider calls.
- The same question produces appropriately different GM, player-character, and observer answers from pre-filtered context, and inaccessible facts never enter the provider request.

Do not create a general-purpose document-ingestion or vector-search framework for this scenario. Defer embeddings and broad retrieval-augmented-generation infrastructure until structured metadata, relational retrieval, and PostgreSQL full-text search have proved insufficient. Normal automated tests must not depend on live provider calls; real-provider testing is limited to deliberate smoke verification.

### Phase 13: Web portal MVP and same-origin packaging

The web portal becomes the primary out-of-session interface over the Phase 10 API and Phase 12 on-demand assistant. Implement the bounded experience in [§23](#23-identity-authorization-and-web-portal-implementation) and [UI_DESIGN.md](UI_DESIGN.md); do not turn this phase into an unrestricted content-management platform.

Deliver:

- a responsive React portal hosted as static assets and authenticated through the Phase 10 OIDC flow
- login, logout, invitation acceptance, campaign selection, and visible campaign/timeline/role/character perspective
- personalized Home dashboard with recap, current situation, active quests, recent discoveries, relevant NPCs/factions, reminders, and Ask entry point
- filtered World, Characters, Quests, Sessions, and Knowledge views
- on-demand summaries, campaign questions, GM briefs, and cited rules questions through deterministic queries and the Phase 12 AI service
- observer-safe curated views
- GM user/role management, user-character relationship management, resource grants, visibility preview, and access audit history
- consistent loading, empty, denied, expired-session, and recoverable-error states without leaking hidden-resource existence

Exit criteria:

- Players, GMs, assistant GMs, and observers can log in and receive distinct campaign views based on campaign roles, user-character relationships, knowledge, groups, and explicit resource grants.
- One user can access multiple characters, one character can be associated with multiple users, one fact can be visible to multiple users through different derivations, and revocation removes access.
- Users can request audience-filtered summaries and details; GM, player-character, and observer results differ correctly, and AI receives only pre-authorized context.
- Inaccessible resources cannot be inferred through routes, identifiers, fields, search suggestions, counts, relationship edges, errors, cached content, or AI responses.
- A GM can preview the portal as a selected user/character perspective before publishing or granting information.
- Portal commands use the same authorization, command, query, audit, visibility, and idempotency boundaries as Foundry and other API clients.

### Phase 14: Local production deployment and hardening

Deliver:

- Docker Compose for UI, API/Uvicorn, PostgreSQL, required workers/jobs, and reverse-proxy integration;
- production multi-stage Dockerfiles and `.dockerignore` files that produce minimal, non-root runtime images, with dependencies pinned and images tagged immutably to a release and Git commit;
- an explicitly recorded mini-PC CPU architecture and a build/release path that produces compatible images (including a multi-platform build when development/CI and production architectures differ);
- a version-controlled `compose.yaml` with health checks, dependency readiness, persistent named volumes, external secret/configuration inputs, and a one-off migration service using the same application image as the API/worker where practical;
- private networking with no public PostgreSQL port and no direct Uvicorn exposure;
- preferred same-origin `world` UI plus `/api/*`, separate Foundry routing, No-IP updates, and automatic HTTPS;
- secure cookies, CSRF, login/AI rate limits, external secrets, health/restart policies, log rotation, disk monitoring, and Foundry-safe resource guidance;
- database and uploaded-file onsite/offsite backups, restore testing, upgrade, rollback, and disaster recovery, including documented one-command deployment and application-image rollback procedures that preserve the prior image and account for schema compatibility; and
- end-to-end local verification of Phase 10 authentication, authorization, and the vertical slice.

Exact hostnames remain a deployment-time decision. Foundry and D&D AI retain separate data, authentication, configuration, lifecycle, and backups. The detailed acceptance gate is [LOCAL_DEPLOYMENT.md](LOCAL_DEPLOYMENT.md#production-readiness-gate).

Exit criteria:

- A clean checkout can build the production images and deploy the complete D&D AI stack on the recorded mini-PC architecture using the documented command without editing tracked files on the host.
- The deployed containers run as non-root where the upstream service permits it, become healthy through Compose, retain database and uploaded data across container replacement, and run migrations as an explicit one-off deployment step rather than as an uncontrolled API-startup side effect.
- An immutable prior application release can be selected and restored with the documented rollback command; the procedure is exercised against a compatible schema or, when a schema rollback is required, against the matching verified database restore point.

### Phase 15: World and campaign-data import

World/campaign-data import begins only after canonical API commands and application services exist. Its representative campaign packet and controlled staging and promotion flow are defined in [§22](#22-worldcampaign-data-import-implementation). Complete application-command coverage for every proposal type in that packet is an entry or implementation requirement; the importer cannot bypass a missing command.

Deliver:

- source/hash retention and source-location provenance for one world-building document, one quest description, and one set of session notes
- staged entity, relationship, event, knowledge, and resulting-state proposals
- entity matching, ambiguity handling, deduplication, canon-conflict detection, and resumable GM review
- editable individual or grouped approval and rejection decisions
- atomic, idempotent promotion through approved application commands using normal validation and authorization
- historical-event reconstruction or an explicitly identified initial-state reconciliation when causal history is impractical
- portal review surfaces integrated with the Phase 13 GM workspace for proposal editing, entity-match resolution, conflict review, approval, rejection, progress, and resumable promotion

Exit criteria:

- The representative packet is retained with hashes and source-location provenance, and extraction produces staged entities, relationships, events, knowledge, and state proposals.
- Existing entities match without silent duplicates; ambiguous matches require GM resolution, and canon conflicts are presented for review.
- The GM can edit, approve, and reject individual or grouped proposals; rejected proposals leave canonical state unchanged.
- Approved proposals invoke application commands and create valid canonical records, atomically where required.
- Partially reviewed work resumes safely, and reprocessing the same source does not duplicate canonical effects.
- Session notes produce appropriate historical events and resulting state or an explicitly identified initial-state reconciliation without fabricated history.
- Every accepted canonical effect is traceable to its source, review decision, application command, and result.
- No client, extractor, campaign import staging process, or AI component writes directly to canonical domain tables.
- Only authorized import reviewers can view or act on proposals, and proposal details do not leak through ordinary player or observer portal views.

### Later phases: demonstrated-need expansion

After revised Phase 14 passes, perform a bounded AWS-retirement workstream: inventory resources; take final snapshots/logical exports; migrate retained data; verify local restoration, extensions, roles, migrations, vertical slice, proxy authentication/authorization, and backups; obtain explicit teardown approval; remove resources through existing infrastructure as code; and confirm recurring charges stop. Until then RDS and other AWS assets are transitional infrastructure and must not be deleted. AWS-to-local replication and hybrid production are not normal architecture.

Broader AI, simulation, economy, administration, performance optimization, additional reference-source and campaign-import formats, OCR, embeddings, bulk campaign-review tools, broader import automation, and Discord integration follow only when demonstrated need exists. Defer AWS application infrastructure, hybrid production, continuously polling workers without a workload, comprehensive embeddings/RAG, broad economy or NPC simulation, administration beyond the bounded portal/import review, generalized import frameworks, and premature performance optimization. A VPS or AWS move requires measured availability, bandwidth, capacity, security, recovery, or maintenance justification.

---

## 25. Vertical-slice acceptance scenario

The first end-to-end vertical slice should implement the following scenario:

1. Create a world and primary timeline.
2. Create a campaign, party, session, two characters, and one NPC.
3. Create a GM user, two player users, and one observer; assign campaign-scoped roles.
4. Associate both players with one shared character, associate one player with a second character, and directly grant a fact to more than one user.
5. Create a dungeon with three connected areas.
6. Create a hidden door, trap, mechanism, and quest.
7. Move the party into the dungeon.
8. Search an area and discover the trap but not the hidden door.
9. Resolve a check that discovers the hidden door.
10. Trigger or disarm the trap.
11. Activate a mechanism.
12. Advance the quest objective.
13. Talk to the NPC and receive restricted knowledge.
14. End the session and generate a summary.
15. Retrieve GM, player-character, and observer summaries; verify that each contains only authorized information and that hidden records cannot be inferred through counts, relationships, search, or errors.
16. Revoke one user-character or fact grant and verify that access disappears on the next request and from any refreshed summary context.
17. Open a second campaign on the same timeline and verify that it sees altered dungeon state but not the first party's private knowledge.
18. Branch a new timeline before the first campaign's dungeon entry and verify that the dungeon remains untouched there.

Phase 10 owns this scenario as the primary architectural and application acceptance test. It must run through the application API without direct client database writes. A design that cannot support it cleanly must be revised before broader implementation.

---

## 26. Testing strategy

### 26.1 Database tests

Run against a local/self-hosted PostgreSQL 18 server during development and against a disposable containerized PostgreSQL 18 instance in CI, per [§24.0](#240-verification-policy). Both targets run the identical suite; nothing is skipped or conditionally disabled on either.

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

### 26.2 Application-service and API tests

Test command and query behavior through the application boundary, including authentication, campaign-scoped role/capability resolution, many-to-many user-character and resource access, revocation, non-disclosure, authorization, visibility, idempotent retry, consistent errors, and rollback on partial failure. Verify filtering before AI context assembly. Reuse earlier database-invariant coverage rather than duplicating it.

### 26.3 Scenario tests

Use dungeon and quest scenarios to validate cross-domain behavior. The Phase 10 scenario includes GM, player, and observer access with shared characters and facts. Phase 12 adds narrow authorized rules-source retrieval and audience-aware synthesis; Phase 13 adds portal navigation and non-disclosure; Phase 14 adds the representative campaign-packet review and promotion scenario. Focus on application behavior and acceptance criteria without building a generalized UI/document test harness or duplicating earlier database invariants.

### 26.4 Property-based tests

Use property-based testing for:

- timeline resolution
- relationship participant combinations
- event-effect application
- quest dependency graphs
- world-time ordering

### 26.5 Performance tests

Measure:

- effective-state queries
- NPC context assembly
- dungeon-map retrieval
- session event ingestion
- knowledge filtering
- branch resolution

### 26.6 Proportional test-infrastructure policy

Tests exist to provide confidence in production behavior and delivery safety. The project does not optimize for the largest test count or for exhaustive proof that test-only infrastructure survives every hypothetical failure of its dependencies.

Prioritize work in this order:

1. Production and schema invariants, including negative cases.
2. Migration, rollback, seed, deployment, and security behavior.
3. Realistic integration and concurrency scenarios, with independently observed final state where timing matters.
4. Regression tests for defects that occurred or have a credible path to false results, leaked persistent resources, or unstable CI.
5. Test-helper unit tests only to the degree needed to support items 1–4.

Test-only infrastructure should be simple, bounded, and observable. Its normal success path, assertion-failure path, startup failure, timeout, and ordinary cancellation/teardown path should be covered when relevant. Additional fault injection requires a concrete risk statement. Do not add exhaustive combinations for failures of `join()`, status inspection, process signaling, pipe closure, or the emergency cleanup code itself unless such a failure has been observed in a supported environment or can realistically corrupt later results.

When a harness limitation remains after the material risks are covered:

- document it briefly;
- rely on process/CI isolation where appropriate;
- create a non-blocking issue only if follow-up has plausible value; and
- continue the delivery phase.

The same rule applies during review: a reviewer must distinguish production defects, inadequate evidence for a production claim, realistic harness defects, and theoretical harness limitations. Only the first three can block a phase, and a harness defect must be fixed with the smallest sufficient change rather than a new general-purpose framework.

---

## 27. Operational strategy

### 27.1 Migrations

Use versioned migrations from the first commit. Alembic is the decided tool (see [DATABASE_CONVENTIONS.md §25.1](DATABASE_CONVENTIONS.md#251-migration-tool) and [DEVELOPMENT.md §4](DEVELOPMENT.md#4-database-and-migrations)), with explicit SQL migrations for PostgreSQL-specific features.

Never use destructive `DROP TABLE ... CASCADE` initialization scripts outside disposable development databases.

Migrations are executed three ways, all from the same revision files: directly against a local server during development ([DEVELOPMENT.md §3](DEVELOPMENT.md#3-local-setup)), against a per-run ephemeral database on `dev` in CI ([§30.9](#309-shared-dev-verification-mechanism-ci)), and — once `staging`/`prod` exist — through the selected private migration mechanism ([§30.6](#306-migration-execution-mechanism)). See [§30.5–§30.7](#30-aws-terraform-deployment-plan-for-postgresql) for the AWS paths.

### 27.2 Environments

Maintain the current two-tier workflow:

- **local** — a PostgreSQL 18 server on each developer's own machine. The default development and test target per [§24.0](#240-verification-policy). Disposable by definition: it holds nothing that isn't reproducible from migrations plus seeds, it is not backed up, and it is not an environment anything deploys to.
- `dev` — shared, always-on AWS RDS. CI verifies every commit against it; it is the merge gate, not the inner loop. Do not destroy or stop it as routine cost hygiene ([CONTRIBUTING.md §6](CONTRIBUTING.md#6-cost-management)).
- `staging` and `production` — deferred until the Phase 10 vertical slice is usable and workload or delivery needs justify them

Local and `dev` must stay in agreement on PostgreSQL major version, installed extensions, and the six bootstrap roles. Drift between them is the failure mode this two-tier model trades for a faster loop — see [§24.0](#240-verification-policy).

### 27.3 Backups

Before production use, configure:

- automated RDS backups
- point-in-time recovery
- periodic restore tests
- export of critical world and campaign records

### 27.4 Observability

Track:

- command failures
- authentication failures, denied requests, role/grant changes, and suspicious enumeration attempts
- transaction duration
- event throughput
- AI proposal approval rates
- integration sync errors
- slow effective-state queries
- world/campaign-data import validation and promotion failures
- rules/reference-corpus ingestion, removal, authorization, and retrieval failures
- portal errors, audience-filtered query latency, AI-context filtering failures, and stale authorization-cache incidents

---

## 28. Deferred decisions

The following should remain deferred until their dedicated design documents:

- exact REST or GraphQL API shape beyond the contracts required by the API, Foundry, and portal phases
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
- staging and production environments before the Phase 10 vertical slice is usable
- three continuously running Fargate services, an Application Load Balancer, and a NAT gateway for the initial vertical slice
- a continuously polling background worker as the default architecture
- RDS Proxy or broad VPC endpoint expansion without measured need
- comprehensive embeddings or RAG before structured metadata and PostgreSQL-native rules/reference retrieval prove insufficient
- Discord integration unless demonstrated player demand justifies it; if later added, begin with a thin HTTP/slash-command client and do not assume a persistent gateway
- broad economy or NPC simulation, portal administration beyond the bounded Phase 13/14 needs, and generalized reference-ingestion or world/campaign-data import frameworks
- premature performance optimization

Deferred decisions must not be implemented implicitly through ad hoc columns.

---

## 29. Definition of implementation success

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
- Retrieve authorized rules/reference passages with edition, permission, precedence, provenance, and citation controls without treating them as campaign canon or training data.
- Accept future world/campaign material through controlled staging, GM review, and application commands.
- Let authenticated players, GMs, assistant GMs, and observers browse and query distinct authorized views of the world through the web portal.
- Support many-to-many relationships between users and characters, facts, knowledge, and other securable resources without collapsing truth, awareness, control, and administrative permission.
- Produce on-demand summaries and answers from pre-filtered context without exposing inaccessible records or their existence.

---

## 30. AWS Terraform deployment plan for PostgreSQL

> **Optional, no longer the default path (2026-08-11).** Self-hosted Docker Compose (`compose.yaml`) is the officially supported deployment topology, and CI verifies against containerized PostgreSQL 18, not AWS — see [ADR 0012](adr/0012-self-hosted-docker-deployment-and-ci-verification.md). Everything below remains accurate as a plan for anyone who chooses to host PostgreSQL on AWS RDS instead; it is not required reading for development, CI, or the default deployment path, and nothing in it is a current delivery obligation.

### 30.1 Scope and current state

This section defines how the PostgreSQL database is provisioned, reached, and migrated in AWS, entirely through Terraform, for anyone who opts into that path. It closes the gap left after the pre-restart Lambda-based deployment tooling was removed (see [README.md § Current Status](../README.md#current-status)).

This section is the **plan** — what the infrastructure should become. [INFRASTRUCTURE.md](INFRASTRUCTURE.md) documents what exists today and how to operate it.

`terraform/modules/database` and `terraform/modules/secrets` already exist and provide:

- An RDS PostgreSQL instance (version pinned via `postgres_version`, now `18.4`), encrypted at rest with a dedicated KMS key. Matches the project's pinned target ([DATABASE_CONVENTIONS.md §2.1](DATABASE_CONVENTIONS.md#21-supported-postgresql-version)) and the local development server — `dev` was replaced onto this version 2026-08-08, see [POSTGRES18_UPGRADE_PLAN.md](POSTGRES18_UPGRADE_PLAN.md).
- A VPC with two private subnets across two availability zones (or reuse of an existing VPC/subnets), a security group scoped to `allowed_cidr_blocks` / `allowed_security_group_ids`, and the currently configured VPC endpoints. Phase 10 must review actual Lambda networking and egress needs; do not assume a VPC-attached Lambda gains internet access from a public subnet, and do not automatically expand or re-enable KMS or Secrets Manager endpoints across every subnet.
- An AWS-managed master user secret (`manage_master_user_password = true`) — no master password is ever stored in Terraform state or code.
- IAM database authentication enabled on the instance (`iam_database_authentication_enabled = true`), ready for use once application-level roles are created.
- Automated backups, deletion protection, enhanced monitoring, and Performance Insights, all on by default.
- A `secrets` module providing named (value-less) Secrets Manager entries. Retain entries required for the AI provider and Phase 10/13 identity or portal deployment; retire or leave unused the legacy Discord placeholder until a later Discord phase is justified.

The database bootstrap, Alembic execution from development/CI, temporary `dev` ingress, and ephemeral-per-run database isolation are implemented and verified. Potential later infrastructure includes the following, but staging and production remain deferred until the Phase 10 vertical slice is usable:

- A remote Terraform state backend (currently local state only).
- `staging` and `prod` environment directories (only `dev` exists today).
- A way to run Alembic migrations against a non-public `staging` or `prod` RDS instance without a bastion host or committed SSH keys.
- Multi-AZ support in the database module for production.

### 30.2 Remote Terraform state

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

### 30.3 Environments: dev, staging, prod

`terraform/environments/dev/` already exists. Do not create `staging/` or `prod/` until the Phase 10 vertical slice is usable and a delivery need is demonstrated. When that happens, create each by copying the `dev` structure rather than parameterizing a single environment with conditionals — per-environment tfvars keep blast radius explicit.

| Setting | dev | staging | prod |
|---|---|---|---|
| `publicly_accessible` | optional (`enable_public_access`) | `false` | `false` |
| `instance_class` | `db.t3.micro` | `db.t3.small` or larger | sized after load testing |
| `deletion_protection` | `false` (fast teardown) | `true` | `true` (already the module default) |
| `skip_final_snapshot` | `true` | `false` | `false` (already the module default) |
| `backup_retention_period` | short (3–7 days) | 7 days | 14–30 days |
| Multi-AZ | no | optional | yes (module gap, see §30.8) |

### 30.4 Provisioning order

A `terraform apply` in a given environment builds, in dependency order:

1. VPC, subnets, route tables, security groups (`module.database`, `networking.tf`).
2. KMS key (`module.database`, `secrets.tf`).
3. RDS instance with its AWS-managed master secret (`module.database`, `rds.tf`).
4. Named Secrets Manager entries for external credentials (`module.secrets`).
5. A migration execution mechanism only if the selected environment cannot use the existing `dev` path; the standing runner in §30.6 is one conditional option, not a default provision.

### 30.5 Database role, schema, and extension bootstrap

The RDS instance boots with only the master role and an empty database. Terraform cannot reach inside PostgreSQL to run SQL, so a one-time (and re-runnable) bootstrap step must execute before `alembic upgrade head` takes over ongoing schema changes. Treat this bootstrap as the first Alembic revision, not a separate untracked script, so it's versioned the same way as everything else.

The bootstrap must be idempotent and cover:

- Extensions, per [DATABASE_CONVENTIONS.md §2.2](DATABASE_CONVENTIONS.md): `CREATE EXTENSION IF NOT EXISTS pgcrypto;` and `CREATE EXTENSION IF NOT EXISTS pg_trgm;` (`btree_gist` is added by the Phase 3 revision that needs it, and `vector` is deferred until PostgreSQL-native rules/reference retrieval proves insufficient — see [§4.1](#41-postgresql-extensions)).
- All thirteen schemas from [§3](#3-postgresql-schema-organization): `core`, `security`, `rules`, `character`, `world`, `campaign`, `narrative`, `knowledge`, `interaction`, `ai`, `audit`, `import`, `integration`.
- `REVOKE CREATE ON SCHEMA public FROM PUBLIC;` per [DATABASE_CONVENTIONS.md §3.1](DATABASE_CONVENTIONS.md).
- The six database roles from [DATABASE_CONVENTIONS.md §27.1](DATABASE_CONVENTIONS.md), split into one owning role and five login roles:
  - `migration_owner` — **`NOLOGIN`**. Owns every schema object; never authenticates.
  - `migration_runner` — executes migrations as a member of `migration_owner`.
  - `app_read_write` — the application's runtime role; DML only, no DDL.
  - `app_read_only` — reporting and read-model queries.
  - `integration_worker` — scoped grants for Foundry, reference-corpus ingestion, world/campaign-data import, and later external integrations.
  - `admin_maintenance` — break-glass, human use only.
- Each of the five **login** roles created `WITH LOGIN` and `GRANT rds_iam TO <role>;` so applications authenticate with short-lived IAM tokens rather than static passwords — the instance already has `iam_database_authentication_enabled = true`, so no new Secrets Manager entries are needed for these roles (per rule 10 in [CLAUDE.md](../CLAUDE.md)).
- `migration_owner` is **excluded** from that grant, and from IAM auth generally. `rds_iam` forces IAM authentication on every role that inherits it, so an owning role carrying it would disable password authentication for the RDS master user the moment the master user is granted the membership that ownership transfer requires. This is not theoretical — it locked a real instance out. See [ADR 0009](adr/0009-separate-owning-role-from-login-roles.md).
- Migrations issue `SET ROLE migration_owner` after connecting, because PostgreSQL takes object ownership from the current role rather than from inherited membership.
- `GRANT CREATE ON DATABASE <current> TO migration_owner;`, so that later revisions — which run as `migration_owner` because of the `SET ROLE` above — can install trusted extensions. Without it, Phase 3's `CREATE EXTENSION btree_gist` fails with `permission denied to create extension` even when the connecting user is the RDS master. See [DATABASE_CONVENTIONS.md §2.3](DATABASE_CONVENTIONS.md#23-extension-ownership).

### 30.6 Migration execution mechanism

**Problem**: the RDS instance is not publicly reachable (by design, in every environment except an explicit `dev` opt-in), so neither a developer's laptop nor Terraform itself can run `alembic upgrade head` against it directly, and there's no bastion host or committed SSH key in this project.

**Decision**: build a **migration runner** — the Alembic-oriented successor to the retired `db_runner` module — as a new `terraform/modules/db_migration_runner/`:

- A small EC2 instance (or an on-demand SSM-managed instance) inside the same private subnets as the database.
- Invoked via **AWS Systems Manager Run Command** — no bastion, no SSH keys, no public IP, consistent with how `db_runner` worked and with the least-privilege stance in [DATABASE_CONVENTIONS.md §27](DATABASE_CONVENTIONS.md).
- An IAM instance role scoped to `rds-db:connect` for the `migration_runner` database user only (IAM auth, not a stored password). Not `migration_owner` — that role is `NOLOGIN` and cannot authenticate at all ([§30.5](#305-database-role-schema-and-extension-bootstrap)); the runner connects as `migration_runner` and becomes the owner via `SET ROLE`.
- Its own security group, attached to the RDS security group via an `aws_security_group_rule` granting itself ingress on 5432 (the same pattern `db_runner` used).
- An S3 bucket holding the versioned Alembic migrations package (`database/` — Alembic env plus revisions), synced by `build.ps1` or CI before each run.

Runtime behavior: `pip install -r requirements.txt && alembic upgrade head`, authenticating via an IAM auth token instead of a password.

This was originally chosen as the lowest-setup-cost option for the project's pre-implementation stage, reusing AWS primitives (EC2, SSM, S3, IAM) already understood from the deleted `db_runner` and requiring no container registry or CI/CD platform decision.

**That deferral remains conditional.** Phase 10 uses Lambda for the initial API, not a standing Fargate service. The standing EC2 runner described above is worth building only if a private `staging` or `prod` environment needs migrations before a cheaper one-off mechanism is selected. Those environments are deferred until the vertical slice is usable. `dev` does not need the runner: `dev` migrations run directly per [§30.9](#309-shared-dev-verification-mechanism-ci). Fargate remains a later option for a genuine persistent or one-off workload, but is not the assumed migration path.

### 30.7 Deployment runbook

The following is a later-environment runbook, not Phase 10 work:

1. One-time per AWS account: apply `terraform/bootstrap/` to create the remote state bucket and lock table (§30.2).
2. `terraform init` (pointed at the remote backend) and `terraform apply` in `terraform/environments/<env>/` — provisions the VPC, RDS instance, KMS key, secrets, and migration runner.
3. Package and sync the Alembic migrations project to the migration runner's S3 bucket.
4. Trigger the migration runner via SSM Run Command (wrapped by `build.ps1` or CI) — runs the bootstrap revision (roles, schemas, extensions) followed by any pending `alembic upgrade head`.
5. Verify: connect using an IAM auth token as `app_read_only`, confirm all thirteen schemas exist and the Alembic version table reflects the expected head revision.
6. For every subsequent schema change: new Alembic revision → re-sync the package → re-trigger the runner. This manual loop is the seed of what should become an automated CI/CD pipeline once one is chosen.

### 30.8 Open items

Additional defects found in the current Terraform — notably that `dev` cannot be destroyed because `deletion_protection` is never overridden to `false`, and that `my_ip_cidr` defaults to `0.0.0.0/0` — are catalogued in [INFRASTRUCTURE.md §11](INFRASTRUCTURE.md#11-known-gaps-and-discrepancies).

- ~~PostgreSQL 18.4 on `dev`~~ — resolved 2026-08-08. `dev` was replaced with a fresh PostgreSQL 18.4 instance (`terraform apply -replace=module.database.aws_db_instance.main`, not an in-place upgrade — see [POSTGRES18_UPGRADE_PLAN.md](POSTGRES18_UPGRADE_PLAN.md) B0 for why). Local and CI now agree on major version.
- **`allow_major_version_upgrade` and `apply_immediately`**: neither exists on `terraform/modules/database`, and neither is being added. They serve only an *in-place* major version upgrade. Nothing in this project needs one: `dev` is replaced rather than upgraded (above), and `staging`/`prod` — when they exist — will be provisioned at 18.x rather than upgraded to it. **Trigger for building them:** the first environment that holds data which must survive a major version upgrade, which is not the case for any environment today. Recorded here rather than built speculatively, per the deferral discipline in [§24.1](#241-phase-exit-review).
- **Multi-AZ**: `terraform/modules/database` has no `multi_az` variable yet; add one before standing up `prod`.
- **Read replicas**: deferred until query load actually justifies one, per [DATABASE_CONVENTIONS.md §33](DATABASE_CONVENTIONS.md).
- **CloudWatch alarms**: CPU, storage, connection count, and (once applicable) replica lag are not yet defined anywhere in the module.
- **Cost**: with current `dev` defaults (`db.t3.micro`, 20GB gp3, VPC endpoints instead of NAT, an on-demand migration runner) expect roughly the same range the project saw before the restart (~$20/month for `dev`). `staging`/`prod` will cost more once Multi-AZ and larger instance classes are applied — measure rather than guess once those environments exist.

### 30.9 Shared-dev verification mechanism (historical; superseded as CI's mechanism by ADR 0012)

**This section describes the AWS-based CI mechanism used through Phase 9, before [ADR 0012](adr/0012-self-hosted-docker-deployment-and-ci-verification.md).** `.github/workflows/ci.yml` no longer runs any of this — CI verifies against a disposable `postgres:18.4` GitHub Actions service container instead ([DEVELOPMENT.md §8](DEVELOPMENT.md#8-continuous-integration)), and `scripts/ci_ephemeral_database.py`/`scripts/ci_cleanup.py` and the `terraform/modules/github_actions_ci` OIDC role described below were removed. This section is kept as the accurate historical record of how that mechanism worked and the reasoning that shaped it (ephemeral-database isolation, cleanup-on-failure discipline) — it remains available reference material for anyone reintroducing AWS RDS verification for their own deployment.

Per [§24.0](#240-verification-policy) as it stood at the time, CI verified every commit's migrations and `tests/database`/`tests/scenario` suites against the deployed `dev` RDS instance. (Developers run the same suites locally — see [DEVELOPMENT.md §3](DEVELOPMENT.md#3-local-setup); this section is the AWS half of the two-tier model, and since [ADR 0011](adr/0011-local-first-development-aws-verified-delivery.md) it is primarily CI's path rather than a routine developer one.) It needs two things: a way in, and isolation so concurrent runs on the one shared instance don't collide.

**Reachability — dev only, via temporary security-group ingress, not a new bridge module.** `dev` already supports `enable_public_access` (§30.3) with its security group ID exposed as the `database_security_group_id` output. Rather than standing up an SSM bastion/tunnel for routine test access, CI manages a narrow, short-lived ingress rule directly against that security group with the AWS CLI, scoped to the caller's own current public IP, for the duration of the run only. A developer occasionally needs the same thing — reproducing a CI-only failure, or inspecting `dev` directly — and uses `scripts/aws-db-allow-my-ip.sh`, which wraps exactly this:

```bash
SG_ID=$(terraform -chdir=terraform/environments/dev output -raw database_security_group_id)
MY_IP=$(curl -s https://checkip.amazonaws.com)/32

aws ec2 authorize-security-group-ingress --group-id "$SG_ID" \
  --protocol tcp --port 5432 --cidr "$MY_IP"

# ... run migrations / pytest against the dev endpoint ...

aws ec2 revoke-security-group-ingress --group-id "$SG_ID" \
  --protocol tcp --port 5432 --cidr "$MY_IP"
```

This reuses infrastructure that already exists rather than adding a new module. It bypasses Terraform for the add/revoke (a `terraform plan` run mid-session will show the rule as drift and is expected to remove it on apply — harmless as long as CI always revokes at job end, including on failure). `enable_public_access` must be `true` for `dev`; `staging` and `prod` stay `publicly_accessible = false` per §30.3 and are never opened this way — their migrations continue to go through the SSM-based migration runner in §30.6, and there is currently no plan to run `tests/database`/`tests/scenario` against them at all (they exist to host real environments, not to be a shared test fixture).

**Isolation — an ephemeral database per test run, not per-schema.** Bootstrap-created roles (`migration_owner`, `app_read_write`, etc.) are cluster-wide in PostgreSQL and already exist on the instance; schemas, domains, and extensions are per-database. Each CI run creates its own throwaway database on the shared instance (for example, `dnd_ai_test_<run-id>`), runs `alembic upgrade head` inside it, runs tests, and drops it — real isolation on shared infrastructure without needing a database per environment. `scripts/ci_ephemeral_database.py` and `.github/workflows/ci.yml` implement this today using the RDS master login because no narrower `CREATEDB`-capable test login exists yet. The same per-run ephemeral-database pattern is what `tests/conftest.py` applies locally, so the suite behaves identically against either target. Before using this mechanism unattended in a prod-adjacent environment, add a dedicated login role with `CREATEDB` plus `rds_iam`, listed in `iam_auth_db_users`. `migration_owner` must not gain `CREATEDB`: it is `NOLOGIN` and nothing connects as it.

**Implementation status (historical).** Temporary runner ingress and ephemeral database isolation were implemented and ran successfully against live `dev` through Phase 9, including GitHub Actions run [`30765722355`](https://github.com/NemesisGhost/dnd_ai/actions/runs/30765722355), with `scripts/ci_cleanup.py`'s combining logic exercised against every failure combination by a safe, AWS-free unit test (see [PHASE4_VERIFICATION.md § Second closeout](PHASE4_VERIFICATION.md#second-closeout-2026-08-02)). `scripts/ci_ephemeral_database.py`, `scripts/ci_cleanup.py`, and their test were removed when CI moved off AWS ([ADR 0012](adr/0012-self-hosted-docker-deployment-and-ci-verification.md)); rebuilding equivalent automation is required if AWS RDS CI verification is ever reintroduced. The private migration runner in §30.6 remains a separate, unbuilt `staging`/`prod` obligation for anyone who takes that path.

**Superseded by [ADR 0012](adr/0012-self-hosted-docker-deployment-and-ci-verification.md).** `.github/workflows/ci.yml` no longer has an AWS job at all — no OIDC role assumption, no scoped ingress, no RDS ephemeral database. CI verifies against a disposable containerized PostgreSQL 18 instance instead ([DEVELOPMENT.md §8](DEVELOPMENT.md#8-continuous-integration)).

**Local/self-hosted counterpart.** The local/self-hosted tier needs none of the above: a local or `compose.yaml` server is directly reachable, and `tests/conftest.py` creates and drops its own ephemeral database on it. What it needs is *agreement* with CI's container — same PostgreSQL major version, same extensions, same six bootstrap roles — which is why the setup in [DEVELOPMENT.md §3](DEVELOPMENT.md#3-local-setup) runs the same `001_bootstrap` revision rather than a hand-rolled local schema.

---

## 31. AWS deployment plan for application services

> **Optional, no longer the default path (2026-08-11).** Self-hosted Docker Compose (`compose.yaml`, `Dockerfile`) is the officially supported deployment topology for whatever application services eventually exist — see [ADR 0012](adr/0012-self-hosted-docker-deployment-and-ci-verification.md) and [DEVELOPMENT.md §2](DEVELOPMENT.md#2-repository-layout). Everything below remains documented, unbuilt planning material for anyone who chooses AWS instead; it is not a current delivery obligation, and no phase has deployed anything under this section yet. [§32](#32-local-production-deployment-plan) covers the officially supported self-hosted path.

### 31.1 Scope and initial target

[§30](#30-aws-terraform-deployment-plan-for-postgresql) covers the database. This section defines a possible cost-conscious API, identity, and portal deployment path on AWS, for whenever that target is chosen. Nothing here is built yet; [INFRASTRUCTURE.md §1](INFRASTRUCTURE.md#1-current-state) remains the record of what exists.

The initial topology is:

```text
Browser → static React portal
Browser/Foundry → OIDC login and access token
Authorized clients → API Gateway HTTP API
  → one FastAPI Lambda handler
    → application/domain services and access resolver
      → PostgreSQL
```

This is one modular FastAPI application hosted through a Lambda ASGI adapter, not one Lambda function per endpoint. Phase 13 adds a statically hosted React portal and CDN/TLS path selected during its bounded deployment design. The initial vertical slice does not deploy an always-running API Fargate service, an Application Load Balancer, or three continuously running services.

### 31.2 Compute principles

- Keep local PostgreSQL as the normal development and test loop.
- Use AWS verification only at the deliberate checkpoints in [§24.0](#240-verification-policy).
- Bound Lambda concurrency so the application cannot exhaust the development RDS connection limit.
- Start with direct database connections. Add RDS Proxy only if measured connection behavior demonstrates a need.
- Reevaluate compute and networking when real workload evidence exists.
- Fargate remains available for workloads that genuinely require persistent processes; it is not the initial API default.
- Prefer SQS- or EventBridge-triggered Lambda execution for intermittent background work. Do not preserve a continuously polling worker without a demonstrated workload requirement.

### 31.3 Packaging and release

Phase 10 chooses the smallest supported Lambda packaging path during deployment design. Whether it uses a zip artifact or container image is an implementation decision, not a reason to provision ECR, ECS, or an ALB preemptively. Artifacts must be immutable and traceable to a Git commit, and deployment must preserve expand-and-contract migration compatibility.

### 31.4 Networking decisions for Phase 10

Resolve networking during Phase 10 deployment design from the actual Lambda, RDS, IAM-authentication, secrets, and external-egress requirements. Required principles:

- API Gateway is the public application entry point; PostgreSQL is never a client-facing interface.
- A VPC-attached Lambda in a public subnet does **not** thereby receive internet access.
- Do not add a NAT gateway, broad VPC endpoint set, or automatic KMS/Secrets Manager endpoints across all subnets preemptively.
- Grant database ingress narrowly from the Lambda security group rather than widening CIDR access.
- If external egress is required, compare concrete secure options and recurring cost before choosing.

### 31.5 Identity, portal hosting, and secrets

- The Lambda gets a least-privilege execution role; later persistent services get their own roles only if they exist.
- Phase 10 deploys an OIDC-compatible login provider for `dev`; AWS Cognito is the initial default unless deployment design records a cheaper or simpler equivalent that meets the same token-validation, invitation, revocation, and account-recovery needs.
- Identity-provider tokens establish identity only. Campaign roles, capabilities, character/resource relationships, and detailed authorization remain in PostgreSQL and are resolved by the application.
- Phase 13 hosts versioned React assets on the smallest managed static-hosting path that provides HTTPS and controlled cache invalidation. Do not introduce a persistent web server solely to serve the portal.
- Database access uses the appropriate login role from [§30.5](#305-database-role-schema-and-extension-bootstrap), with credentials and IAM policy scoped to the application rather than shared broadly.
- External credentials remain outside artifacts and source control. Provision and retrieve only credentials required by the phase being delivered.

### 31.6 Deployment flow

1. Run the normal local PostgreSQL and application checks.
2. Build immutable Lambda and, when applicable, portal artifacts tied to the commit.
3. Run the existing deliberate AWS database verification checkpoint.
4. Apply any required compatible migration before application code that depends on it.
5. Deploy the Phase 10 OIDC provider, API Gateway, and single FastAPI Lambda handler to `dev`.
6. Exercise the Phase 10 authenticated API scenario and record the deployment evidence.
7. From Phase 13 onward, deploy versioned portal assets, invalidate only the required cached paths, and exercise GM, player, and observer flows against the live API.

Do not provision staging or production as part of the initial vertical slice. Their release and rollback design is deferred until the application is usable and an environment need is demonstrated.

### 31.7 Observability

The telemetry requirements are in [SYSTEM_ARCHITECTURE.md §19](architecture/SYSTEM_ARCHITECTURE.md#19-observability); this is where they land:

- Lambda and API Gateway logs go to **CloudWatch Logs**, with retention set explicitly rather than left to never expire.
- The correlation, causation, and identity fields from §19 are emitted as structured JSON so they are queryable, not free text.
- Begin with focused visibility into API errors, latency, throttling/concurrency, and database connection pressure. Add broader alarms when the corresponding workloads exist.
- Record authentication failures, authorization denials, resource-grant changes, sensitive reads, portal release identity, and correlation between browser requests and API activity without logging tokens or restricted content.

### 31.8 Per-phase deployment expectations

Application services do not exist until there is application code to run. Phases 2–9 are predominantly schema and domain logic, so their AWS obligation is the one in [§24.0](#240-verification-policy): a green CI run against the deployed `dev` database on the phase's final head commit. Their development happens locally. Phase 9 is adapter-ready, not live-synchronized.

The additional obligations in this section begin when the corresponding deployable first exists:

| From | Additionally deployed and verified in `dev` |
|---|---|
| Phase 10 (Core API and playable vertical slice) | OIDC login provider, API Gateway HTTP API, and one FastAPI Lambda handler; the complete §25 authenticated and audience-filtered scenario exercised through it |
| Phase 11 (Foundry MVP) | The FoundryVTT-facing surface, exercised end-to-end against the live API in `dev` |
| Phase 12 (Narrow AI/NPC MVP) | Deliberate one-provider smoke verification for NPC and audience-aware assistant behavior only; normal automated tests use no live provider |
| Phase 13 (Web portal MVP) | Versioned static React portal; GM, player, assistant-GM, and observer flows exercised against the live authenticated API |
| Phase 14 (Local production hardening) | Compose, local PostgreSQL, reverse proxy, No-IP/HTTPS, backup/restore, security and operational controls verified end to end |
| Phase 15 (World and campaign-data import) | Portal import-review surface plus one representative campaign packet promoted through GM-approved application commands; compute selected for the actual batch shape |

A phase is not done when its code merges; it is done when its deployables are running in `dev` and the phase's tests pass against them. Local development remains the inner loop for the code inside those deployables ([§24.0](#240-verification-policy)), but there is no local substitute for the deployment itself.

### 31.9 Open items

- **Lambda-to-RDS networking and egress** ([§31.4](#314-networking-decisions-for-phase-10)) — resolve from the Phase 10 flow without assuming public-subnet internet access, NAT, RDS Proxy, or a broad endpoint set.
- **Terraform modules**: the OIDC, API Gateway/Lambda, and static portal deployment paths do not exist. Add only the bounded infrastructure required by Phase 10, then Phase 13; ECS service and ALB modules remain deferred.
- **CI/CD platform**: GitHub Actions is already used for CI ([DEVELOPMENT.md §8](DEVELOPMENT.md#8-continuous-integration)); deployment is assumed to extend it rather than introduce a second system, but the OIDC role and environment protection rules are unbuilt.
- **`staging`/`prod` environments** remain unbuilt per [§30.3](#303-environments-dev-staging-prod); everything above is specified for `dev` first.
- **Cost and scaling**: set bounded Lambda concurrency from the development RDS connection budget, begin with direct connections, and measure before adding RDS Proxy, persistent compute, NAT, or performance infrastructure.

---

## 32. Local production deployment plan

Production is planned to run on the existing Ubuntu mini-PC using Docker Compose, per [ADR 0013](adr/0013-locally-host-production-on-existing-mini-pc.md), which builds on [ADR 0012](adr/0012-self-hosted-docker-deployment-and-ci-verification.md)'s self-hosted Docker Compose decision. Nothing in this section is built yet.

The application project would contain the React UI, FastAPI under Uvicorn, PostgreSQL, and only those worker/scheduled-job containers the delivered features require. A Caddy- or Traefik-class reverse proxy would be the sole inbound HTTP/HTTPS service; PostgreSQL and Uvicorn would publish no host ports. The preferred routes are `world.<domain>/` for UI, `world.<domain>/api/*` for API, and `foundry.<domain>/` for Foundry; ADR 0013 records both supported DNS arrangements without inventing a domain.

Phase 10 containerizes the portable API and validates local PostgreSQL. Phase 13 packages React for the same `world` origin. Phase 14 would integrate Compose, reverse proxy, No-IP, automatic TLS, secure cookies/CSRF, rate limits, backups/restores, health/restart policies, log/disk/resource controls, upgrades, rollback, disaster recovery, and end-to-end local verification. See [LOCAL_DEPLOYMENT.md](LOCAL_DEPLOYMENT.md).

AWS RDS remains available as an optional, no-longer-CI-verified path regardless of whether this plan is ever built ([ADR 0012](adr/0012-self-hosted-docker-deployment-and-ci-verification.md)); nothing here requires tearing it down.

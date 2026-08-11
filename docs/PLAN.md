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

> **Current policy (ADR 0012):** Production targets the existing Ubuntu mini-PC, not AWS. Local PostgreSQL is the development default; deployables close their phases by running in Docker Compose and being exercised through the local reverse proxy. The RDS CI mechanism described below is retained transitional/historical evidence and may continue while AWS exists, but it is no longer the required production architecture or an indefinite phase gate. Before AWS retirement, failures in an enabled RDS job are still investigated honestly. After the local readiness gate and explicit teardown approval, the AWS-specific job may be removed with the other resources.

Development is local; delivery is verified on AWS. These are two different steps, and conflating them is what [ADR 0011](adr/0011-local-first-development-aws-verified-delivery.md) corrected in the original AWS-first policy ([ADR 0008](adr/0008-aws-first-deployment-and-verification.md)).

**Tier 1 — the inner loop runs against a local PostgreSQL 18 server.** Writing a migration, iterating on a constraint or trigger, and running `tests/database`/`tests/scenario` all happen locally, with no AWS credentials, no security-group rule, and no network dependency. This is the default and expected way to work, not a fallback. Setup is [DEVELOPMENT.md §3](DEVELOPMENT.md#3-local-setup).

The local server must be the **same PostgreSQL major version the project deploys** ([DATABASE_CONVENTIONS.md §2.1](DATABASE_CONVENTIONS.md#21-supported-postgresql-version)). A local server on a different major version is a defect, not a preference — it reintroduces exactly the divergence this policy exists to prevent.

**Tier 2 — CI verifies the same work against the deployed AWS `dev` RDS instance.** `.github/workflows/ci.yml` runs migrations from empty to head, the downgrade round trip, `alembic check`, seed idempotency, and the full test suite against a per-run ephemeral database on `dev`, using the mechanism in [§30.9](#309-shared-dev-verification-mechanism-ci). This is a **merge gate**, not advisory. It exists because a class of defect is only reachable on RDS — IAM authentication, `rds_superuser` boundaries, `rds.force_ssl`, parameter groups, managed-role behavior. The ungated `GRANT rds_iam` in the bootstrap revision was exactly this, and it survived a fully green local run.

`tests/unit` is unaffected by either tier — it uses no database at all.

The AWS obligation still applies to *running* code, not just schema: once a phase delivers a deployable — an API, portal, or adapter — its selected cost-conscious AWS path runs in `dev` and is exercised there at a deliberate checkpoint. Local PostgreSQL remains the normal development and test loop. The compute and networking decisions and per-phase expectations are in [§31](#31-aws-deployment-plan-for-application-services).

A phase's exit criteria below are therefore necessary but not sufficient. A phase is done when, additionally:

1. Its migrations run cleanly — up, and down where supported — against a local PostgreSQL 18 database.
2. Its `tests/database`/`tests/scenario` suites pass locally.
3. A CI run on the phase's final head commit is green against the deployed `dev` database, and its run ID is recorded in `docs/PHASEn_VERIFICATION.md`.
4. Its deployables (if any — see [§31.8](#318-per-phase-deployment-expectations)) are running in `dev` and exercised there.

"It passes locally" is the expected *first* claim and is never the last one. A phase closes on item 3, not item 2.

**When local and CI disagree, CI is right.** A green local run followed by a red CI run is not flaky infrastructure to be re-run until it passes; it is an RDS-specific defect, or local and `dev` have drifted apart. Investigate before re-running. The one exception the project has observed is a transient RDS connection fault during Phase 6, which was diagnosed as such and re-run deliberately — that is a judgment recorded in the verification file, not a default response.

### 24.1 Phase exit review

Every phase ends with a review, before the next one starts. Phase 1 produced six defects that no amount of offline checking would have found, and several of them were latent for days because the exit criteria could be marked done without evidence. This section is the correction.

**Write down what was actually verified.** Each phase produces `docs/PHASEn_VERIFICATION.md`, following the shape of [PHASE1_VERIFICATION.md](PHASE1_VERIFICATION.md): what was run and against what, the bugs found and fixed, and what remains outstanding. "Verified" means a command was run and its output observed — not that the code looks right. State the method next to the claim, so a reader can tell `alembic --sql` output from a live run.

Under [§24.0](#240-verification-policy) that record now has **two targets**, and the file must distinguish them: what was run against the local PostgreSQL 18 server, and the CI run ID that proved the same work against `dev` RDS. A verification file that reports only local results has not recorded a closed phase.

**Re-check the recurring obligations.** These can regress silently in any phase that touches schema, and several are invisible until something downstream breaks:

| Obligation | Why it needs re-checking |
|---|---|
| Object ownership | Tables must end up owned by `migration_owner` ([ADR 0009](adr/0009-separate-owning-role-from-login-roles.md)). If `SET ROLE` stops holding, ownership silently moves to the connecting user |
| Default privileges | `ALTER DEFAULT PRIVILEGES` only fires for objects created *by* `migration_owner`. Verify by connecting as `app_read_write`/`app_read_only`, not by reading grant statements |
| Seed idempotency | Seeding twice must be a no-op ([DATABASE_CONVENTIONS.md §25.6](DATABASE_CONVENTIONS.md#256-migration-testing)) |
| Constraint tests | Positive *and* negative per [§32.1](DATABASE_CONVENTIONS.md#321-constraint-tests). An untested `CHECK` is an unverified rule |
| Comments and FK indexes | [§31](DATABASE_CONVENTIONS.md#31-documentation-conventions) and [§19.1](DATABASE_CONVENTIONS.md#191-foreign-key-indexes), in the same revision that creates the object |
| Downgrade | Round trip to `base` and back. Cheap to run locally now, so run it every phase — Phase 1's downgrade was broken for weeks while looking fine. CI repeats it against `dev` |
| Local/`dev` agreement | Same PostgreSQL major version, same extensions, same six bootstrap roles. Drift here shows up as a green local run and a red CI run ([§24.0](#240-verification-policy)) |
| CI green | On a real push, against `dev` RDS, on the phase's **final head** commit — not an earlier one, and not locally |

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

**Progress.** Workstream 1 (`080_security_identity_and_access`) delivered the `security.*` schema and workstream 2 (`src/dnd_ai/domain/access.py`) delivered the effective-access resolver. Workstream 3 (`src/dnd_ai/api/`) delivered the FastAPI application skeleton, `/healthz`, normalized errors, correlation IDs, and one-transaction-per-request dependency. Still to come are authentication verification, readiness, command/query endpoints and contracts, Uvicorn/container execution, local PostgreSQL configuration, and Compose/reverse-proxy integration. A Lambda adapter is neither required nor part of the production path.

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
- one local path through the reverse proxy, as defined in [§31](#31-local-production-deployment-plan)
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
- private networking with no public PostgreSQL port and no direct Uvicorn exposure;
- preferred same-origin `world` UI plus `/api/*`, separate Foundry routing, No-IP updates, and automatic HTTPS;
- secure cookies, CSRF, login/AI rate limits, external secrets, health/restart policies, log rotation, disk monitoring, and Foundry-safe resource guidance;
- database and uploaded-file onsite/offsite backups, restore testing, upgrade, rollback, and disaster recovery; and
- end-to-end local verification of Phase 10 authentication, authorization, and the vertical slice.

Exact hostnames remain a deployment-time decision. Foundry and D&D AI retain separate data, authentication, configuration, lifecycle, and backups. The detailed acceptance gate is [LOCAL_DEPLOYMENT.md](LOCAL_DEPLOYMENT.md#production-readiness-gate).

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

Run against a local PostgreSQL 18 server during development and against the deployed `dev` RDS instance in CI, per [§24.0](#240-verification-policy). Both targets run the identical suite; nothing is skipped or conditionally disabled on either.

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

### 30.1 Scope and current state

This section defines how the PostgreSQL database is provisioned, reached, and migrated in AWS, entirely through Terraform. It closes the gap left after the pre-restart Lambda-based deployment tooling was removed (see [README.md § Current Status](../README.md#current-status)).

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

### 30.9 Shared-dev verification mechanism (CI)

Per [§24.0](#240-verification-policy), CI verifies every commit's migrations and `tests/database`/`tests/scenario` suites against the deployed `dev` RDS instance. (Developers run the same suites locally — see [DEVELOPMENT.md §3](DEVELOPMENT.md#3-local-setup); this section is the AWS half of the two-tier model, and since [ADR 0011](adr/0011-local-first-development-aws-verified-delivery.md) it is primarily CI's path rather than a routine developer one.) It needs two things: a way in, and isolation so concurrent runs on the one shared instance don't collide.

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

**Implementation status.** Temporary runner ingress and ephemeral database isolation are implemented and have run successfully against live `dev`, including GitHub Actions run [`30765722355`](https://github.com/NemesisGhost/dnd_ai/actions/runs/30765722355). Cleanup now fails the workflow if either cleanup operation fails, rather than masking it, with `scripts/ci_cleanup.py`'s combining logic exercised against every failure combination by a safe, AWS-free unit test (see [PHASE4_VERIFICATION.md § Second closeout](PHASE4_VERIFICATION.md#second-closeout-2026-08-02)). Remaining work is the dedicated least-privilege test login above. The private migration runner in §30.6 remains a separate `staging`/`prod` obligation.

**Unchanged by [ADR 0011](adr/0011-local-first-development-aws-verified-delivery.md).** Moving the inner loop to a local server does not retire any of this. `.github/workflows/ci.yml` keeps its AWS job exactly as built — OIDC role assumption, scoped ingress, ephemeral database, always-run cleanup — because it is now the *only* thing standing between an RDS-specific defect and `main`. What changes is who runs it routinely: CI on every push and pull request, rather than every developer on every test run.

**Local counterpart.** The local tier needs none of the above: a local server is directly reachable, and `tests/conftest.py` creates and drops its own ephemeral database on it. What the local tier does need is *agreement* with `dev` — same PostgreSQL major version, same extensions, same six bootstrap roles — which is why the setup in [DEVELOPMENT.md §3](DEVELOPMENT.md#3-local-setup) runs the same `001_bootstrap` revision rather than a hand-rolled local schema.

---

## 31. Local production deployment plan

> **This section supersedes the AWS application-service proposal below.** The older Lambda/API Gateway/Fargate text is retained only as an obsolete proposal for historical traceability and is not a current requirement.

Production runs on the existing Ubuntu mini-PC using Docker Compose. The application project contains React UI, FastAPI under Uvicorn, PostgreSQL, and only those worker/scheduled-job containers the delivered features require. A Caddy- or Traefik-class reverse proxy is the sole inbound HTTP/HTTPS service. PostgreSQL and Uvicorn publish no host ports. The preferred routes are `world.<domain>/` for UI, `world.<domain>/api/*` for API, and `foundry.<domain>/` for Foundry; [ADR 0012](adr/0012-locally-host-production-on-existing-mini-pc.md) records both supported DNS arrangements without inventing a domain.

Phase 10 containerizes the portable API and validates local PostgreSQL. Phase 13 packages React for the same `world` origin. Revised Phase 14 integrates Compose, reverse proxy, No-IP, automatic TLS, secure cookies/CSRF, rate limits, backups/restores, health/restart policies, log/disk/resource controls, upgrades, rollback, disaster recovery, and end-to-end local verification. See [LOCAL_DEPLOYMENT.md](LOCAL_DEPLOYMENT.md).

Existing AWS resources follow the retirement gate in the roadmap. A VPS or AWS becomes a future option only when measured availability, bandwidth, capacity, security, recovery, or operator burden justifies it.

### Historical appendix: obsolete AWS application-service proposal (never built)

### 31.1 Scope and initial target

[§30](#30-aws-terraform-deployment-plan-for-postgresql) covers the database. This section defines the cost-conscious API, identity, and portal deployment path beginning in Phase 10. Nothing here is built yet; [INFRASTRUCTURE.md §1](INFRASTRUCTURE.md#1-current-state) remains the record of what exists.

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

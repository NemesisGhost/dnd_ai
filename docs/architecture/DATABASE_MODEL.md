# Persistent World Database Model

## 1. Purpose

This document defines the logical PostgreSQL database model for the D&D AI World Platform. It translates the conceptual model in `docs/DOMAIN_MODEL.md` into a complete set of database domains, primary relationships, ownership rules, and state boundaries.

**This is the authoritative source of truth for database schema and table scope** — which tables exist, what schema they live in, and their key columns. `docs/PLAN.md` is authoritative for implementation *phasing* (which phase builds which table, exit criteria, first-time obligations) but its per-phase "Implement" prose is a working sketch, not the schema record; where the two disagree on a table's existence, name, or column shape, this document wins and PLAN.md should be corrected to match. `README.md`'s schema summary is illustrative only — it exists to give newcomers a feel for the shape of the platform, not to enumerate tables authoritatively.

This is a logical model rather than final migration SQL. Column details may evolve during implementation, but the ownership, identity, inheritance, timeline, event, knowledge, and state rules in this document are architectural constraints.

## 2. Modeling principles

1. PostgreSQL is the authoritative source of structured world state.
2. A world owns persistent entity definitions.
3. A timeline owns evolving world state and history.
4. A campaign organizes play within a timeline but does not normally own copies of world entities.
5. Important world objects use a shared entity identity.
6. Major entity specializations use class-table inheritance.
7. Current state is stored in typed state tables.
8. Events preserve causality and history.
9. Knowledge is separate from objective truth.
10. AI-generated changes are proposals until validated and approved.
11. Rules definitions are separate from world instances.
12. Imports enter staging before becoming canonical records.
13. Authentication identity, campaign responsibility, in-world knowledge, and resource authorization are separate concerns.
14. Roles provide campaign-scoped capability defaults; individual access is many-to-many and may also derive from character, party, group, or direct resource relationships.
15. Authorization is enforced before rows, fields, relationships, counts, search results, or AI context leave the application query layer.

## 3. PostgreSQL schema map

| Schema | Primary responsibility |
|---|---|
| `core` | Worlds, entities, names, provenance, tags, calendars, fictional time, common statuses |
| `security` | Users, external identities, campaign memberships, roles, capabilities, character relationships, resource grants, access groups and service identities |
| `rules` | Rulesets and reusable mechanical definitions |
| `character` | Shared character definitions, builds, NPC and PC extensions |
| `world` | Locations, organizations, relationships, item instances, cultures and economies |
| `campaign` | Timelines, campaigns, parties, sessions, mutable effective state |
| `narrative` | Events, encounters, quests, objectives, story arcs and outcomes |
| `knowledge` | Knowledge claims, beliefs, discoveries, expertise and transfers |
| `interaction` | Actions, targets, checks, resolutions and consequences |
| `ai` | Agents, context requests, generated outputs, proposals and embeddings |
| `audit` | Change records, approvals, validation failures and agent activity |
| `import` | Staged extraction, matching, review and promotion |
| `integration` | External identifiers, synchronization state and delivery metadata |

## 4. High-level database diagram

```mermaid
erDiagram
    CORE_WORLDS ||--o{ CORE_ENTITIES : owns
    CORE_WORLDS ||--o{ CAMPAIGN_TIMELINES : contains
    CORE_WORLDS ||--o{ CORE_CALENDARS : uses
    CORE_WORLDS ||--o{ RULES_WORLD_RULESETS : configures

    SECURITY_USERS ||--o{ SECURITY_EXTERNAL_IDENTITIES : authenticates_as
    SECURITY_USERS ||--o{ SECURITY_CAMPAIGN_MEMBERSHIPS : joins
    CAMPAIGN_CAMPAIGNS ||--o{ SECURITY_CAMPAIGN_MEMBERSHIPS : authorizes
    SECURITY_CAMPAIGN_MEMBERSHIPS ||--o{ SECURITY_MEMBERSHIP_ROLES : assigned
    SECURITY_ROLES ||--o{ SECURITY_MEMBERSHIP_ROLES : grants
    SECURITY_ROLES ||--o{ SECURITY_ROLE_CAPABILITIES : includes
    SECURITY_CAPABILITIES ||--o{ SECURITY_ROLE_CAPABILITIES : defines
    SECURITY_CAMPAIGN_MEMBERSHIPS ||--o{ SECURITY_MEMBERSHIP_CHARACTER_RELATIONSHIPS : relates
    CHARACTER_CHARACTERS ||--o{ SECURITY_MEMBERSHIP_CHARACTER_RELATIONSHIPS : accessible_to
    SECURITY_CAMPAIGN_MEMBERSHIPS ||--o{ SECURITY_ACCESS_GROUP_MEMBERSHIPS : grouped
    SECURITY_ACCESS_GROUPS ||--o{ SECURITY_ACCESS_GROUP_MEMBERSHIPS : contains
    SECURITY_CAMPAIGN_MEMBERSHIPS ||--o{ SECURITY_RESOURCE_GRANTS : receives
    SECURITY_ACCESS_GROUPS ||--o{ SECURITY_RESOURCE_GRANTS : receives

    CORE_ENTITY_TYPES ||--o{ CORE_ENTITIES : classifies
    CORE_SOURCES ||--o{ CORE_ENTITIES : originates
    CORE_CANON_STATUSES ||--o{ CORE_ENTITIES : governs
    CORE_ENTITIES ||--o{ CORE_ENTITY_NAMES : has
    CORE_ENTITIES ||--o{ CORE_ENTITY_TAGS : tagged
    CORE_TAGS ||--o{ CORE_ENTITY_TAGS : applies

    CORE_ENTITIES ||--o| CHARACTER_CHARACTERS : specializes
    CHARACTER_CHARACTERS ||--o| CHARACTER_NPCS : specializes
    CHARACTER_CHARACTERS ||--o| CHARACTER_PLAYER_CHARACTERS : specializes

    CORE_ENTITIES ||--o| WORLD_LOCATIONS : specializes
    WORLD_LOCATIONS ||--o| WORLD_DUNGEONS : specializes
    WORLD_LOCATIONS ||--o| WORLD_DUNGEON_AREAS : specializes
    WORLD_LOCATIONS ||--o| WORLD_SETTLEMENTS : specializes
    WORLD_LOCATIONS ||--o| WORLD_BUILDINGS : specializes

    CORE_ENTITIES ||--o| WORLD_ORGANIZATIONS : specializes
    CORE_ENTITIES ||--o| WORLD_ITEM_INSTANCES : specializes
    CORE_ENTITIES ||--o| NARRATIVE_EVENTS : specializes
    CORE_ENTITIES ||--o| NARRATIVE_QUESTS : specializes
    CORE_ENTITIES ||--o| KNOWLEDGE_KNOWLEDGE_ITEMS : specializes

    CAMPAIGN_TIMELINES ||--o{ CAMPAIGN_CAMPAIGNS : hosts
    CAMPAIGN_CAMPAIGNS ||--o{ CAMPAIGN_SESSIONS : contains
    CAMPAIGN_CAMPAIGNS ||--o{ CAMPAIGN_CAMPAIGN_PARTIES : uses
    CAMPAIGN_PARTIES ||--o{ CAMPAIGN_CAMPAIGN_PARTIES : participates_in
    CAMPAIGN_TIMELINES ||--o{ CAMPAIGN_PARTY_MEMBERSHIPS : scopes
    CAMPAIGN_PARTIES ||--o{ CAMPAIGN_PARTY_MEMBERSHIPS : includes
    CHARACTER_CHARACTERS ||--o{ CAMPAIGN_PARTY_MEMBERSHIPS : joins

    CAMPAIGN_TIMELINES ||--o{ NARRATIVE_EVENTS : records
    CAMPAIGN_SESSIONS ||--o{ NARRATIVE_EVENTS : produces
    NARRATIVE_EVENTS ||--o{ NARRATIVE_EVENT_PARTICIPANTS : has
    CORE_ENTITIES ||--o{ NARRATIVE_EVENT_PARTICIPANTS : participates
    NARRATIVE_EVENTS ||--o{ NARRATIVE_EVENT_EFFECTS : causes

    NARRATIVE_ENCOUNTERS ||--o{ NARRATIVE_ENCOUNTER_PARTICIPANTS : has
    NARRATIVE_ENCOUNTERS ||--o{ NARRATIVE_ENCOUNTER_ROUNDS : contains
    NARRATIVE_ENCOUNTER_ROUNDS ||--o{ NARRATIVE_ENCOUNTER_TURNS : contains
    NARRATIVE_ENCOUNTERS ||--o{ NARRATIVE_EVENTS : produces

    CAMPAIGN_TIMELINES ||--o{ CAMPAIGN_CHARACTER_STATE : owns
    CHARACTER_CHARACTERS ||--o{ CAMPAIGN_CHARACTER_STATE : has
    CAMPAIGN_TIMELINES ||--o{ CAMPAIGN_LOCATION_STATE : owns
    WORLD_LOCATIONS ||--o{ CAMPAIGN_LOCATION_STATE : has
    CAMPAIGN_TIMELINES ||--o{ CAMPAIGN_ITEM_STATE : owns
    WORLD_ITEM_INSTANCES ||--o{ CAMPAIGN_ITEM_STATE : has

    NARRATIVE_QUESTS ||--o{ NARRATIVE_QUEST_STAGES : contains
    NARRATIVE_QUEST_STAGES ||--o{ NARRATIVE_QUEST_OBJECTIVES : contains
    CAMPAIGN_TIMELINES ||--o{ CAMPAIGN_QUEST_STATE : owns
    NARRATIVE_QUESTS ||--o{ CAMPAIGN_QUEST_STATE : tracks
    NARRATIVE_QUEST_OBJECTIVES ||--o{ CAMPAIGN_OBJECTIVE_STATE : tracks

    KNOWLEDGE_KNOWLEDGE_ITEMS ||--o{ KNOWLEDGE_ENTITY_KNOWLEDGE : believed
    CORE_ENTITIES ||--o{ KNOWLEDGE_ENTITY_KNOWLEDGE : knows
    CAMPAIGN_TIMELINES ||--o{ KNOWLEDGE_ENTITY_KNOWLEDGE : scopes

    WORLD_RELATIONSHIPS ||--o{ WORLD_RELATIONSHIP_PARTICIPANTS : contains
    CORE_ENTITIES ||--o{ WORLD_RELATIONSHIP_PARTICIPANTS : participates
    CAMPAIGN_TIMELINES ||--o{ CAMPAIGN_RELATIONSHIP_STATE : owns
    WORLD_RELATIONSHIPS ||--o{ CAMPAIGN_RELATIONSHIP_STATE : tracks

    INTERACTION_INTERACTIONS ||--o{ INTERACTION_TARGETS : targets
    INTERACTION_INTERACTIONS ||--o{ INTERACTION_CHECK_REQUESTS : requests
    INTERACTION_CHECK_REQUESTS ||--o{ INTERACTION_CHECK_RESULTS : resolves
    INTERACTION_INTERACTIONS ||--o{ NARRATIVE_EVENTS : produces

    AI_AGENTS ||--o{ AI_PROPOSED_CHANGES : proposes
    AI_PROPOSED_CHANGES ||--o{ AI_CHANGE_REVIEWS : reviewed
    AI_PROPOSED_CHANGES ||--o| NARRATIVE_EVENTS : accepted_as
```

## 5. Core identity and provenance

### 5.1 `core.worlds`

Represents one persistent fictional setting.

Key columns:

- `world_id UUID PK`
- `name TEXT`
- `slug TEXT`
- `default_calendar_id UUID NULL`
- `default_ruleset_id UUID FK NULL` — added in Phase 4
- `lifecycle_status_id UUID FK`
- `created_at TIMESTAMPTZ`
- `updated_at TIMESTAMPTZ`

A world owns entity definitions, calendars, timelines, and world-specific configuration.

### 5.2 `core.entity_types`

Defines the allowed entity type hierarchy.

Key columns:

- `entity_type_id UUID PK`
- `code TEXT UNIQUE`
- `display_name TEXT`
- `parent_entity_type_id UUID NULL`
- `required_subtype_table TEXT`
- `is_abstract BOOLEAN`

The service layer and database validation functions must ensure that an entity type matches its required subtype row.

### 5.3 `core.entities`

Provides stable identity for important world objects.

Key columns:

- `entity_id UUID PK`
- `world_id UUID FK`
- `entity_type_id UUID FK`
- `canonical_name TEXT`
- `summary TEXT NULL`
- `canon_status_id UUID FK`
- `lifecycle_status_id UUID FK`
- `source_id UUID FK NULL`
- `created_by_user_id UUID NULL`
- `created_at TIMESTAMPTZ`
- `updated_at TIMESTAMPTZ`
- `archived_at TIMESTAMPTZ NULL`

Entity rows are definition records. Timeline-specific conditions do not belong here.

### 5.4 Names, aliases and tags

- `core.entity_names`
- `core.name_types` — lookup for `entity_names.name_type_id` (canonical, common, former, translated, secret, mistaken, …)
- `core.tags`
- `core.entity_tags`

`entity_names` supports canonical, common, former, translated, secret and mistaken names, typed through `name_types` rather than an enum. Names may optionally be scoped to a same-world `campaign.timeline_id` when a name only exists after a historical event; a `NULL` timeline is a global name.

### 5.5 Sources and canon

- `core.sources`
- `core.source_types` — lookup for `sources.source_type_id` (book, session note, homebrew document, import, …)
- `core.source_documents`
- `core.canon_statuses`
- `core.lifecycle_statuses`

Every imported or generated fact should retain provenance. Canon status and operational lifecycle status are separate concepts.

Example:

- Canon status: `canon`
- Lifecycle status: `active`

or

- Canon status: `proposed`
- Lifecycle status: `pending_review`

### 5.6 Calendars and fictional time

- `core.calendars`
- `core.calendar_months`
- `core.world_time_precisions`
- `core.world_times`

A world may define several calendars (a common reckoning and an elvish one, say), each with `calendar_id`, `world_id FK`, `code`, `days_per_week`, and an `epoch_label`. `calendar_months` orders a calendar's months by `month_number` with a `day_count` each.

`world_times` is the concrete representation of a point in fictional chronology: `world_time_id PK`, `world_id FK`, an optional `calendar_id FK` and calendar-aware `year`/`month_number`/`day`/`hour`/`minute` fields (each cascading a NOT NULL requirement onto the field above it — a day needs a month, a month needs a year), a `world_time_precision_id FK` (exact, partial, approximate, narrative — how precisely this moment is known), an optional narrative `label` for moments with no calendar date, and a `sort_key BIGINT NOT NULL` used to order and range-compare moments regardless of calendar. Every fictional-time interval elsewhere in the schema (party membership, sessions, event ordering) is built from `world_times` foreign keys plus a derived range over `sort_key`, never from calendar fields directly — see [ADR 0010](../adr/0010-use-sort-key-ranges-for-fictional-time-intervals.md).

## 6. World, timeline, campaign and session

```mermaid
erDiagram
    CORE_WORLDS ||--o{ CAMPAIGN_TIMELINES : contains
    CAMPAIGN_TIMELINES ||--o{ CAMPAIGN_TIMELINES : branches_to
    CAMPAIGN_TIMELINES ||--o{ CAMPAIGN_CAMPAIGNS : hosts
    CAMPAIGN_CAMPAIGNS ||--o{ CAMPAIGN_SESSIONS : contains
    CAMPAIGN_CAMPAIGNS ||--o{ CAMPAIGN_CAMPAIGN_PARTIES : uses
    CAMPAIGN_PARTIES ||--o{ CAMPAIGN_CAMPAIGN_PARTIES : participates_in
    CAMPAIGN_TIMELINES ||--o{ CAMPAIGN_PARTY_MEMBERSHIPS : scopes
    CAMPAIGN_PARTIES ||--o{ CAMPAIGN_PARTY_MEMBERSHIPS : includes
    CHARACTER_CHARACTERS ||--o{ CAMPAIGN_PARTY_MEMBERSHIPS : participates
```

### 6.1 `campaign.timelines`

Key columns:

- `timeline_id UUID PK`
- `world_id UUID FK`
- `name TEXT`
- `parent_timeline_id UUID NULL`
- `branch_event_id UUID FK NULL` — added by Phase 6 revision 058, `REFERENCES narrative.events(event_id) ON DELETE RESTRICT`
- `branch_world_time_id UUID FK NULL`
- `is_primary BOOLEAN`
- `lifecycle_status_id UUID FK`

A branch inherits parent history only through its branch point. Effective-state queries must never include parent events after that point.

`branch_event_id` is nullable — a branch may exist with only its world-time point (Phase 3 shape) before being given a causal event, or may never get one. When set, `campaign.enforce_timeline_branch()` (extended by revision 058, not a second trigger — see §26's Phase 6 notes) validates it belongs to `parent_timeline_id` and occurs at or before `branch_world_time_id`'s `sort_key`.

A root has neither `parent_timeline_id` nor branch-point fields. A child requires both `parent_timeline_id` and `branch_world_time_id`; the latter must belong to the shared world. `campaign.effective_events(timeline_id)` (revision 059) is the branch-aware effective-history query: a recursive walk of `parent_timeline_id` returning the timeline's own full history plus each ancestor's history bounded by the point the next timeline down actually branched off it — see §12 and §26.

### 6.2 `campaign.campaigns`

Key columns:

- `campaign_id UUID PK`
- `timeline_id UUID FK` — immutable once set (Phase 4 corrections)
- `name TEXT`
- `ruleset_version_id UUID FK` — added in Phase 4, added as `ruleset_id` (pinning a ruleset family) and renamed to `ruleset_version_id` (pinning a specific version) by a Phase 4 corrections revision, for reproducibility: a campaign's rules configuration should not silently change if its ruleset family later gains a second current version
- `lifecycle_status_id UUID FK`
- `started_at TIMESTAMPTZ NULL`
- `ended_at TIMESTAMPTZ NULL`

`ruleset_version_id` must be allowed for the campaign's world (`rules.world_rulesets`, resolved through the pinned version's ruleset family) — enforced by trigger.

### 6.3 Parties and membership

- `campaign.parties`
- `campaign.party_memberships`
- `campaign.campaign_parties`

`campaign.parties` holds a stable party identity within a world, including `party_id UUID PK` and `world_id UUID FK`. `campaign.campaign_parties` associates that identity with one or more campaigns. Membership is mutable timeline state rather than a property of the party definition, so `campaign.party_memberships` includes:

- `party_membership_id UUID PK`
- `timeline_id UUID FK`
- `party_id UUID FK`
- `member_entity_id UUID FK`
- `effective_from_world_time_id UUID FK`
- `effective_to_world_time_id UUID FK NULL`
- `effective_period INT8RANGE`

The endpoints are half-open `[from, to)` positions in fictional chronology. The range is derived from the endpoint rows' `sort_key` values and is used by a GiST exclusion constraint over `(timeline_id, party_id, member_entity_id, effective_period)` to reject overlaps. The upper bound is unbounded while membership is current. A trigger enforces world agreement, endpoint ordering, and agreement between the endpoint IDs and stored range.

Until `character.characters` exists in Phase 4, `member_entity_id` references `core.entities`; Phase 4 adds enforcement that the entity is a character. Until `narrative.events` exists in Phase 6, join/leave event references are omitted rather than stored as unconstrained UUIDs.

### 6.4 Sessions

`campaign.sessions` organizes a period of play and is not itself the owner of permanent world state.

Key columns:

- `session_id UUID PK`
- `campaign_id UUID FK`
- `session_number INTEGER`
- `title TEXT`
- `lifecycle_status_id UUID FK`
- `start_world_time_id UUID FK NULL`
- `end_world_time_id UUID FK NULL`
- `started_at TIMESTAMPTZ NULL`
- `ended_at TIMESTAMPTZ NULL`
- `summary TEXT NULL`
- `source_id UUID FK NULL`
- `world_time_period INT8RANGE NULL` — added by a Phase 4 corrections revision

A session carries both real-world time (`started_at`/`ended_at`, when the table actually played) and fictional time (`start_world_time_id`/`end_world_time_id`, where the story was) at once — they answer different questions and neither substitutes for the other. `world_time_period` is derived from the two world-time endpoints' `sort_key` values the same way `party_memberships.effective_period` is (half-open `[start, end)`, unbounded upper when open-ended, `NULL` when unscheduled — [ADR 0010](../adr/0010-use-sort-key-ranges-for-fictional-time-intervals.md)), but unlike party memberships, sessions carry **no exclusion constraint**: overlapping fictional-time spans across sessions (a flashback, two sessions each covering an overlapping stretch of story time) are legitimate. The range makes the interval queryable; it does not make overlap invalid.

## 7. Character model

```mermaid
erDiagram
    CORE_ENTITIES ||--|| CHARACTER_CHARACTERS : is
    CHARACTER_CHARACTERS ||--o| CHARACTER_NPCS : may_be
    CHARACTER_CHARACTERS ||--o| CHARACTER_PLAYER_CHARACTERS : may_be
    CHARACTER_CHARACTERS ||--o{ CHARACTER_BUILDS : has
    CHARACTER_BUILDS ||--o{ CHARACTER_ABILITY_SCORES : has
    CHARACTER_BUILDS ||--o{ CHARACTER_CLASS_LEVELS : has
    CHARACTER_BUILDS ||--o{ CHARACTER_PROFICIENCIES : has
    CHARACTER_BUILDS ||--o{ CHARACTER_FEATURES : has
    CHARACTER_BUILDS ||--o{ CHARACTER_SPELLCASTING_PROFILES : has
    CHARACTER_CHARACTERS ||--o{ CAMPAIGN_CHARACTER_STATE : state
    CHARACTER_CHARACTERS ||--o{ CAMPAIGN_CHARACTER_CONDITIONS : affected_by
    CHARACTER_CHARACTERS ||--o{ CAMPAIGN_CHARACTER_RESOURCES : consumes
```

### 7.1 Shared character definition

`character.characters` contains identity-level mechanical references such as species, size and origin. NPCs and player characters both extend it. Potential later subtypes (companions, familiars, summons, special creature actors) reuse `character.characters` when they need full character mechanics, rather than growing a parallel hierarchy.

- `character.characters` — `character_id UUID PK/FK` to `core.entities`; `species_id UUID FK` to `rules.species`, which must be allowed for the character's own world (`rules.world_rulesets`, enforced by trigger since a Phase 4 corrections revision); `size_category TEXT` (a fixed CHECK vocabulary, not a lookup table — the six D&D size categories don't vary by ruleset); `origin_location_id UUID FK NULL` to `world.locations`, added by Phase 5 revision 042 once locations existed, same-world enforced by trigger
- `character.character_descriptions` — free-text background, appearance, and other prose that doesn't drive mechanics
- `character.character_languages` — reusable character-to-language association. A character may know languages from multiple ruleset families, but every referenced language's family must be present in the character's world's `rules.world_rulesets` allow-list, enforced by trigger (revision 037), same shape as species/build/condition/resource (revision 029) and inheriting the same concurrency-safe locking (revision 035) via the shared `rules.ruleset_allowed_for_world()` helper.
- `character.character_senses`
- `character.character_movements`
- `character.character_religious_affiliations` — personal belief, distinct from organizational membership or employment (§10.3)

### 7.2 NPC extension

- `character.npcs`
- `character.npc_portrayal_profiles` — versioned: speech style, voice, vocabulary, mannerisms, emotional baseline, conversational habits, topics avoided, disclosure boundaries, roleplay guidance
- `character.npc_characteristics`
- `character.npc_goals` — may be world-level or timeline-specific; each goal has an owner, description, type, priority, status, target entities, progress, secrecy/visibility policy, initiating event, completion/failure event, and dependencies
- `character.npc_routines`
- `character.npc_routine_steps`
- `character.npc_preferences`
- `character.npc_boundaries` — hard limits on portrayal distinct from `npc_disclosure_rules`' softer information-sharing policy
- `character.npc_disclosure_rules`
- `character.npc_agent_assignments`

Portrayal defaults (`npc_portrayal_profiles`, `npc_characteristics`, `npc_preferences`, `npc_boundaries`, `npc_disclosure_rules`) are world definitions. Current mood, trust, and goal progress are timeline-scoped and live in typed state (`campaign.npc_emotional_state`, `campaign.npc_goal_state` — §16), not here — this table holds what an NPC generally *is*, not what is currently true of them in a given timeline.

The AI context service assembles prompts from the current portrayal profile and current state rather than relying on one unstructured personality prompt.

### 7.3 Player character extension

- `character.player_characters`
- `character.character_controllers`
- `security.membership_character_relationships`
- `security.character_relationship_type_capabilities`

A player character can participate in multiple campaigns and timelines. Ownership does not duplicate the character definition. `character_controllers` records operational control by a human, service account, external VTT actor, or AI agent, including temporary control handoffs; assignments are campaign- or timeline-aware. It is not the human authorization source of truth.

Human relationships to characters are modeled separately by `security.membership_character_relationships` (§19). A campaign membership may own, primarily control, co-control, portray, or view many characters, and a character may have each relationship with many memberships. Relationship types provide default capabilities through `security.character_relationship_type_capabilities`; direct grants may add or explicitly restrict a capability for a particular membership. In-world character knowledge remains in the knowledge model (§15) and is not created merely because a user can administer or view the character.

### 7.4 Character builds

- `character.character_builds` — `character_id UUID FK`, `ruleset_version_id UUID FK` (must be allowed for the character's own world, enforced by trigger), `label TEXT NULL`. No `is_current` column: which build is active on a given timeline is timeline state (`campaign.character_state.character_build_id`, §17), not a property of the build, since a character may use different builds on different timelines after a branch — a global "current" flag couldn't represent that. A character may have any number of builds.
- `character.character_ability_scores` — one row per `(build, ability)`; the ability's ruleset version must match the build's
- `character.character_class_levels` — one row per `(build, class)`, so a build may hold levels in more than one class (multiclassing); an optional `subclass_id` must belong to the same class; the class's ruleset version must match the build's
- `character.character_proficiencies` — exactly one of `skill_id`, `saving_throw_ability_id`, or a free-text `target_label` (weapon/armor/tool categories with no dedicated lookup) per row, and that one must be the kind `proficiency_type_id` requires (`rules.proficiency_types.target_kind`); a build cannot hold the same semantic proficiency twice; the proficiency type itself, and whichever target is a rule reference, must match the build's ruleset version (revision 032 closed the proficiency-type gap)
- `character.character_features` — a granted `rules.features` row per build; ruleset version must match
- `character.character_spellcasting_profiles` — an optional `class_id` plus a required `spellcasting_ability_id`; both, when set, must match the build's ruleset version
- `character.character_known_spells` / `character.character_prepared_spells` — independent associations (not one a subset of the other — whether "prepared" is even meaningful varies by class); each spell's ruleset version must match its profile's build

Builds are versioned definitions. Current hit points, conditions, spell-slot use and other temporary resources belong to campaign timeline state (§16), not the build. Ruleset-version cross-checks are enforced by triggers because a CHECK cannot compare across tables. Revision 033 made every parent side of these cross-version invariants (and `character_builds`/`character_spellcasting_profiles`'s own identity columns) immutable, so a parent edit can no longer invalidate an already-valid child row — see §8's closing paragraphs for the full policy.

## 8. Rules model

Rules data is reusable and ruleset-scoped. All rule definitions must identify their ruleset and version; homebrew definitions use the same tables rather than a separate schema. Every table below carries a nullable `source_id UUID FK` (`core.sources`) and a required `canon_status_id UUID FK` (`core.canon_statuses`, defaulted to `'canon'` for officially authored content and overridable for homebrew or proposed content). `source_id` is nullable and uses `ON DELETE SET NULL` for every origin — official content legitimately has no single authored source row, so presence is not database-enforced. There is also no schema concept of content *origin* (AI-generated, imported, homebrew, ...) independent of canon status today, and inventing one to key a structural check off of would be new domain vocabulary ahead of the phase that needs it. The policy resolved in the Phase 4 closeout is that source presence for AI-generated/imported/homebrew content is an **application-command obligation**, not a database constraint — the command handler that creates such content is responsible for requiring and validating a source, with its own tests, once that command exists (no `commands/` layer exists yet — see §2 of this document and CLAUDE.md's "don't build ahead of the phase that needs it"). Do not describe nullable `source_id` as database-enforced provenance in code or docs.

Every rule-content row's `ruleset_version_id` (or, for `rules.subclasses`/`rules.features`, the class/subclass/species association it is scoped by) is immutable once set, using the same `core.enforce_immutable_columns()` trigger revision 030 introduced for world/timeline/party/campaign scope — a cross-version-consistency trigger only re-validates a *child* row at that child's own insert/update, so the *parent* row's identity must not change out from under already-valid children instead of needing a transactional revalidate-and-rebuild path. Revisions 033 and 036 implement this for every rule-definition table, including `rules.creature_types`, `rules.languages`, and `rules.feats` (no cross-version invariant reads them as a parent yet, but the identity policy applies regardless of whether something references them today). `character.character_builds.character_id`/`ruleset_version_id` and `character.character_spellcasting_profiles.character_build_id` are immutable for the same reason. Associations that are not identity (e.g. `rules.classes.primary_ability_id`, `rules.skills.ability_id`, `rules.spells.damage_type_id`) remain mutable — their owning row's trigger re-checks the relationship when that row changes.

Primary tables:

- `rules.rulesets` — `ruleset_id UUID PK`, `code TEXT UNIQUE`, `display_name TEXT`. Edition-neutral (e.g. code `dnd5e`, display name "D&D 5e") — a specific edition or revision (e.g. "2024") is recorded on `rules.ruleset_versions.version_label`/`description`, not here (revision 034)
- `rules.ruleset_versions` — `ruleset_version_id UUID PK`, `ruleset_id UUID FK`, `version_label TEXT`, `is_current BOOLEAN` (at most one per ruleset)
- `rules.world_rulesets` — a pure allow-list associating a world with the ruleset families it allows (`world_id`, `ruleset_id` composite PK). Identifying the *default* is `core.worlds.default_ruleset_id UUID FK` alone (§5.1) — `world_rulesets` carries no `is_default` column of its own; a Phase 4 corrections revision removed one after finding the two could disagree. The revision-031 trigger prevents removing or repointing an association while it is a world's default, or while a campaign, character species, character build, applied condition, or tracked resource in that world still depends on it, and returns `NEW` on a permitted update and `OLD` on a permitted delete within one transaction. Revision 035 closes the remaining `READ COMMITTED` race between that check and concurrent dependency creation: every covered dependency-creation path takes a `FOR SHARE` lock on the specific `world_rulesets` row it depends on, which a concurrent removal or repoint (needing an exclusive lock on the same row) must wait behind — see that revision's docstring for why a single, always-same-row lock cannot deadlock. Revision 037 (second post-closeout review) extends the same still-in-use check and the same concurrency-safe path to character languages, closing the last uncovered dependency category — see §7.1.
- `rules.abilities`
- `rules.skills` — governing `ability_id` must share the skill's ruleset version
- `rules.species`
- `rules.classes` — optional `primary_ability_id` must share the class's ruleset version
- `rules.subclasses` — scoped to a `class_id`, not directly to a ruleset version; must share its class's version
- `rules.features` — independently nullable `class_id`/`subclass_id`/`species_id`, each of which (when set) must share the feature's ruleset version
- `rules.feats`
- `rules.spells` — optional `damage_type_id` must share the spell's ruleset version; `code` follows the same `^[a-z][a-z0-9_]*$` format as every sibling table
- `rules.conditions`
- `rules.creature_types`
- `rules.damage_types`
- `rules.languages`
- `rules.proficiency_types` — `target_kind TEXT` (`skill` / `saving_throw` / `free_text`) added by a Phase 4 corrections revision, naming which `character.character_proficiencies` column a proficiency of this type must set
- `rules.resource_definitions`

`rules.item_definitions` is listed here as a rule-definition concept (§11) but is deferred to Phase 9, which owns both item definitions and item instances together.

## 9. Location and dungeon model

```mermaid
erDiagram
    CORE_ENTITIES ||--|| WORLD_LOCATIONS : is
    WORLD_LOCATIONS ||--o{ WORLD_LOCATIONS : contains
    WORLD_LOCATIONS ||--o| WORLD_DUNGEONS : may_be
    WORLD_LOCATIONS ||--o| WORLD_DUNGEON_AREAS : may_be
    WORLD_DUNGEON_AREAS ||--o{ WORLD_AREA_CONNECTIONS : from
    WORLD_DUNGEON_AREAS ||--o{ WORLD_AREA_CONNECTIONS : to
    WORLD_DUNGEON_AREAS ||--o{ WORLD_AREA_FEATURES : contains
    WORLD_DUNGEON_AREAS ||--o{ WORLD_AREA_HAZARDS : contains
    WORLD_DUNGEON_AREAS ||--o{ WORLD_AREA_INTERACTABLES : contains
    WORLD_LOCATIONS ||--o{ CAMPAIGN_LOCATION_STATE : state
    WORLD_AREA_CONNECTIONS ||--o{ CAMPAIGN_AREA_CONNECTION_STATE : state
    WORLD_AREA_FEATURES ||--o{ CAMPAIGN_AREA_FEATURE_STATE : state
    WORLD_AREA_HAZARDS ||--o{ CAMPAIGN_HAZARD_STATE : state
```

### 9.1 Location hierarchy

`world.locations` contains a nullable `parent_location_id` for containment. General semantic relationships (adjacency, claims, portals, trade routes, disputed control) use the universal relationship model (§10) instead of dedicated columns.

Built in Phase 5 (revision 038): `world.locations` is the class-table-inheritance root. Leaf location kinds with no structured data of their own beyond "is a location" — plane, continent, nation, region, district, geographic_feature, and **realm** (added by revision 047, closing an oversight in revision 038 — DOMAIN_MODEL.md §9.1 lists it and nothing argues for its removal) — are plain `core.entity_types` rows under `location`, the same pattern `character.characters` already uses for types with no dedicated apparatus. Two kinds get their own subtype table: `world.settlements` (`population` only — government, factions, and economy are later-phase concepts; districts are plain child locations; control/damage state is timeline state) and `world.buildings` (`building_use TEXT`, free text pending a documented vocabulary).

`parent_location_id` is mutable (legitimate reparenting — moving a building to a different district — is a real operation). Revision 044 added ancestry validation and a second trigger that re-validates the dungeon-area-must-have-a-dungeon-parent rule whenever `parent_location_id` changes directly; revision 049 serialized containment changes per world; revision 054 replaced the depth-bounded walk with PostgreSQL's native `CYCLE` clause for real repeated-node detection, keeping the depth bound only as a resource cap that now raises instead of silently truncating; revision 056 added a per-child-location advisory lock so inserting a `world.dungeon_areas` row cannot race with a direct change to that same child's `parent_location_id` — see [PHASE5_VERIFICATION.md § Fourth exit review corrections](../PHASE5_VERIFICATION.md#fourth-exit-review-corrections-2026-08-03).

### 9.2 Dungeon structure

Built in Phase 5 (revision 039):

- `world.dungeons` — `danger_level` (`core.rating_1_10`, optional)
- `world.dungeon_areas` — `area_type`, `dimensions`, `environmental_properties`, all free text; a trigger requires `parent_location_id` to reference a `dungeon`-typed location
- `world.connection_types` — lookup, seeded: door, secret_door, passage, portal, stair, ladder, pit, bridge, teleportation_link
- `world.area_connections` — links two dungeon areas; requires the same world but deliberately *not* the same dungeon (a teleportation link may cross dungeons); `is_hidden` is a structural fact about the connection, never party knowledge; `from_dungeon_area_id`/`to_dungeon_area_id` are immutable once set (revision 044 — an endpoint has no legitimate "move" operation, the same reasoning revision 030 applied to `core.entities.world_id` and similar identity columns)
- `world.area_features`, `world.area_hazards`, `world.area_interactables` — plain children of a dungeon area, not entities (modeling principle 5 — a lever or bloodstain has no independent identity the way an NPC or dungeon does); each carries `is_hidden`; `dungeon_area_id` is immutable once set (revision 044, same reasoning as the connection endpoints above)

Area connections support normal doors, secret doors, passages, portals, stairs/ladders, pits, bridges, one-way routes (`is_one_way`), and **conditional routes** (`is_conditional`/`condition_description`, added by revision 047). Phase 6 revision 064 added the machine-checkable half for the check-gated case: `required_check_kind`/`required_ability_id`/`required_skill_id`/`required_difficulty` (all nullable — only set when the condition is simply "pass a check," as opposed to quest-gated or state-gated) plus `world.conditional_route_requirement_satisfied(area_connection_id, check_result_id)`, a pure read-only function a command can call to decide whether a given check result satisfies a given route's requirement. It deliberately does not mutate `campaign.area_connection_state` itself — rule 6 requires that to go through a causal event via the command layer (Phase 6 increment 5, not yet built); see §27. `world.area_spawn_definitions` (named in earlier drafts of this section and in PLAN.md §9.2) was **not built** in Phase 5 — no creature-instance or stat-block model exists anywhere in this schema yet, and Phase 9 (encounters) is the natural first consumer; building it now would either reference nothing meaningful or invent encounter-generation scope ahead of the phase that needs it.

Definitions describe what can exist. Timeline state (§17) describes what is currently open, destroyed, active, occupied, or depleted — kept mutation-safe by the five `campaign.*_state` tables' own `updated_at` triggers (revision 046, closing a gap where revision 040 declared the column but never attached `core.set_updated_at()`).

### 9.3 Discovery versus existence

A hidden feature exists independently of whether a party knows about it. Do not store `is_discovered` as a global property of a feature — discovery belongs to the knowledge model (§15) and may differ by party or character.

Phase 5 proves this structurally: `world.area_connections.is_hidden` (and the equivalent column on features/hazards/interactables) says the object was built to be concealed, never who has found it. Discovery itself is recorded in `knowledge.party_discoveries`, pulled forward from Phase 7 for this reason — see §15's note and §26.

## 10. Organizations and relationships

```mermaid
erDiagram
    CORE_ENTITIES ||--|| WORLD_ORGANIZATIONS : is
    WORLD_RELATIONSHIPS ||--o{ WORLD_RELATIONSHIP_PARTICIPANTS : contains
    CORE_ENTITIES ||--o{ WORLD_RELATIONSHIP_PARTICIPANTS : participates
    WORLD_RELATIONSHIPS ||--o{ WORLD_RELATIONSHIP_PERSPECTIVES : perceived_as
    WORLD_RELATIONSHIPS ||--o{ CAMPAIGN_RELATIONSHIP_STATE : state
```

Built by **Phase 8 revision 076**.

### 10.1 Universal relationships

- `world.relationship_types` — lookup: family, employment, membership, ownership, alliance, rivalry, war, control, worship, adjacency, capital_of, parent_of, other
- `world.relationships` — not entity-rooted, same reasoning as `world.area_connections`/`interaction.interactions`/`narrative.story_arcs`: a structural record connecting entities with no independent canonical identity of its own
- `world.relationship_participants` — an entity's typed role in a relationship (`world.relationship_participant_roles`, a lookup: subject/object, parent/child, employer/employee, owner/property, ruler/territory, member/organization, ally/rival, other)
- `world.relationship_perspectives`

Relationships may connect any entities — an NPC parent of another NPC, an NPC member of an organization, an organization controlling a settlement, an item owned by an NPC, a religion revered by a city, a dungeon area connected to another. The base relationship row stores shared facts and history; perspectives store a participant's **authored, world-scoped baseline** subjective view (affinity, trust, respect, fear, obligation, emotional tone, private interpretation) — the objective/subjective split rule 5 of §21 depends on. This baseline is stable content, not something an event updates — comparable to `character.npc_characteristics`. The **current, timeline-scoped, event-driven** version that can diverge after a branch is `campaign.relationship_state` (§17), not this table; a perspective's holder must be a participant in the same relationship, enforced by trigger.

### 10.2 Specialized relationship subtypes

Class-table inheritance for relationship details that need typed columns beyond the generic participant/perspective shape (PK = `world.relationships.relationship_id`):

- `world.organization_memberships` — `organization_id`, `member_entity_id`, `role`, `rank`, `is_public`, and an ADR 0010-shaped `effective_from_world_time_id`/`effective_to_world_time_id`/`membership_period` with an `EXCLUDE USING gist` over `(organization_id, member_entity_id, membership_period)` — the same overlap-prevention shape `campaign.party_memberships` established. Rejoining creates a new `world.relationships` row rather than reopening an old one.
- `world.employment_relationships` — `employer_entity_id`, `employee_entity_id`, `job_title`, `effective_from_world_time_id`/`effective_to_world_time_id`; currentness is `effective_to_world_time_id IS NULL` (§12.4's "current records" pattern — one pattern per domain, not an exclusion constraint; no exit criterion requires overlap prevention for employment specifically)
- `world.ownership_relationships` — `owner_entity_id`, `owned_entity_id`, `ownership_share`, `is_public`. Item ownership stays with the future Phase 9 item domain (`campaign.item_ownership`) rather than this table.
- `world.family_relationships` — `family_unit_name`; participants (parent/child, sibling, spouse, …) are `world.relationship_participants` roles, not duplicated here
- `world.political_relationships` — `is_active`, `treaty_terms`; the kind of political relationship is `world.relationships.relationship_type_id` (alliance/rivalry/war/control/…), not a second column here

### 10.3 Organizations

Hierarchy:

```text
core.entities
    -> world.organizations
        -> world.businesses
        -> world.governments
        -> world.religious_organizations
        -> world.military_units
        -> world.political_factions
```

An organization row stores `organization_type_id` (a lookup — government, business, guild, military_unit, religious_organization, criminal_organization, political_faction, secret_society, other), founded/dissolved world times, headquarters (`world.locations`), parent organization (self-referencing), public description, and internal description. Only five of the nine `organization_type_id` values additionally get their own CTI leaf table above (each with at least one typed column beyond the generic organization row); guild/criminal_organization/secret_society/other are expressed through the lookup value alone, the same way a bare `character.characters` row needs no further subtype table.

**Operational status is timeline state, not a column here.** An organization's current active/dissolved/dormant/banned/underground/unknown status is `campaign.organization_state` (§17) — the same definition/state split `narrative.quests`/`campaign.quest_state` already established; `world.organizations` carries no `status`/`organization_status_id` column of its own. Jurisdiction and territorial control (`world.governments`) are expressed through the universal relationship model (`relationship_type = control`) rather than a typed column, per this section's own "organization controlling a settlement" example; offices and leaders are `world.organization_memberships`, agencies are child organizations (`parent_organization_id`).

Membership is a specialized relationship (§10.2), supporting multiple roles, rejoining, secret membership, ranks, and historical periods — it is not a separate ad hoc table.

### 10.4 Religion distinction

A religion is a belief system; a church, temple, order, or cult is an organization that may serve it. Conflating the two loses the distinction between believing something and belonging to (or being employed by) an institution built around it.

- `world.religions` — entity-rooted, a separate CTI chain from `world.organizations`; `pantheon_structure` is illustrative free text. Holy sites and reverence are expressed through the universal relationship model (`relationship_type = worship`), not typed columns; doctrines/rituals/sacred texts/symbols/traditions have no exit criterion requiring structured columns yet and are carried by the inherited `core.entities.summary`/`core.entity_names`.
- `world.religious_organizations` — CTI leaf of `world.organizations`, with a `religion_id` FK to `world.religions`
- `character.character_religious_affiliations` — personal belief (devotion, belief status, practice, interpretation, conflicts, public display), kept separate from organizational rank (`world.organization_memberships`) and employment (`world.employment_relationships`)

## 11. Item model

Rules item definitions are distinct from world item instances, which are distinct again from the state and ownership of a particular instance.

Primary tables:

- `rules.item_definitions` — reusable mechanical definitions (deferred to Phase 9)
- `world.item_instances` — particular objects in the world
- `world.item_containers`
- `campaign.item_state` — location, charges, damage/condition, equipped state
- `campaign.item_ownership` — who owns an instance
- `campaign.inventory_entries` — who currently possesses/carries it, and where (a container, a location) — distinct from ownership, since a borrowed or stolen item is possessed without being owned
- `campaign.item_attunements`
- `knowledge.item_identification` — identification level and which hidden properties are known to whom

Examples:

- `Longsword`: rules definition
- `Blade of Saint Orra`: world entity plus item instance
- Current possessor, charges and damage: timeline state (`item_state`, `inventory_entries`)
- True magical properties known by a character: knowledge state (`item_identification`)

## 12. Events and effects

```mermaid
erDiagram
    CORE_ENTITIES ||--|| NARRATIVE_EVENTS : is
    CAMPAIGN_TIMELINES ||--o{ NARRATIVE_EVENTS : records
    CAMPAIGN_SESSIONS ||--o{ NARRATIVE_EVENTS : produces
    NARRATIVE_EVENTS ||--o{ NARRATIVE_EVENT_PARTICIPANTS : includes
    CORE_ENTITIES ||--o{ NARRATIVE_EVENT_PARTICIPANTS : participates
    NARRATIVE_EVENTS ||--o{ NARRATIVE_EVENT_LOCATIONS : occurs_at
    WORLD_LOCATIONS ||--o{ NARRATIVE_EVENT_LOCATIONS : hosts
    NARRATIVE_EVENTS ||--o{ NARRATIVE_EVENT_CAUSES : caused_by
    NARRATIVE_EVENTS ||--o{ NARRATIVE_EVENT_EFFECTS : causes
```

Primary tables — all built by Phase 6 revision 057:

- `narrative.events`
- `narrative.event_participants`
- `narrative.event_locations`
- `narrative.event_causes`
- `narrative.event_effects`
- `narrative.event_observations`

An event belongs to a timeline and may reference a campaign and session when produced during play (`timeline_id` `NOT NULL`; `campaign_id`/`session_id` nullable, cross-checked by trigger to form a consistent timeline → campaign → session chain when set). Title, summary, source, and recording time are inherited from `core.entities` rather than duplicated on the subtype row — `narrative.events` adds only `timeline_id`/`campaign_id`/`session_id`, `event_type_id`, `event_status_id` (`draft`/`recorded`/`voided`/`corrected`), `world_time_id` (the effective world time — `core.world_times`' own label/precision support covers "approximate period"), and free-form `details`.

Effects (`narrative.event_effects`) identify a target, affected component, old value, new value, effective world time, and application status (`pending`/`applied`/`failed`/`skipped`); common effects should also update typed state tables in the same transaction (rule 6). The target is at most one of `target_entity_id` or one of the four dungeon-domain non-entity columns (`target_area_connection_id`/`_feature_id`/`_hazard_id`/`_interactable_id`) — the same single-typed-target pattern `knowledge.knowledge_items` established in Phase 5, reused rather than reinvented; zero targets is allowed for an effect with no single typed target. `previous_value`/`new_value` are `JSONB`.

`narrative.event_causes` links an event to exactly one of: a prior event (`cause_event_id`), a recorded interaction (`cause_interaction_id`, added by revision 062 once `interaction.interactions` existed — see §16, §27), or a free-text `cause_description` for undocumented decisions/conditions (a GM ruling, an ambient world condition) — the same placeholder pattern Phase 5 used for `knowledge.entity_knowledge.learned_source`, now narrowed to only the genuinely undocumented case.

Not every attack roll needs a permanent world event — high-volume tactical actions live in interaction and encounter logs (§16, §13) instead. Promote meaningful outcomes to narrative events: a character is killed, a ward is disabled, a room is flooded, an artifact is destroyed, an NPC is rescued, a faction becomes hostile, a quest stage is completed.

A recorded (non-draft) event is immutable — its content and status cannot be edited in place (revision 065), and it cannot be deleted, either directly or by deleting its `core.entities` row and letting `ON DELETE CASCADE` take it along (revision 069, a Phase 6 exit-review follow-up correction). Only a draft event may still be edited or deleted; see §27.

## 13. Encounters and combat

```mermaid
erDiagram
    NARRATIVE_ENCOUNTERS ||--o{ NARRATIVE_ENCOUNTER_PARTICIPANTS : has
    NARRATIVE_ENCOUNTERS ||--o{ NARRATIVE_ENCOUNTER_ROUNDS : contains
    NARRATIVE_ENCOUNTER_ROUNDS ||--o{ NARRATIVE_ENCOUNTER_TURNS : contains
    INTERACTION_COMBAT_ACTIONS ||--o{ NARRATIVE_ENCOUNTER_TURNS : resolves
    NARRATIVE_ENCOUNTERS ||--o{ NARRATIVE_EVENTS : produces
```

Primary tables:

- `narrative.encounters`
- `narrative.encounter_participants`
- `narrative.encounter_rounds`
- `narrative.encounter_turns`
- `interaction.combat_actions`

FoundryVTT may remain the detailed tactical authority during live combat; the database captures synchronized state and meaningful outcomes rather than duplicating every tactical decision. Persist enough to support initiative and turn order, current HP and conditions, resource consumption, participants, defeated/escaped/surrendered/captured outcomes, an encounter summary, and the resulting narrative events.

`narrative.encounters.campaign_id`/`.session_id` (both nullable) form the same timeline -> campaign -> session ownership chain `narrative.events` and `interaction.interactions` already require: `campaign_id`, when set, must belong to the encounter's own `timeline_id`, and `session_id`, when set, must belong to `campaign_id` — enforced by `narrative.enforce_encounter_world()` (revision 081, extending revision 078's original same-world-only checks) and, ahead of it in application code, `dnd_ai.commands.encounters._validate_session_campaign()`.

`narrative.encounters.timeline_id` and `.campaign_id` are both immutable once the encounter exists — `campaign_id` including NULL <-> non-NULL transitions, stricter than the generic `core.enforce_immutable_columns()` pattern (§30/33), which allows one NULL -> value transition — enforced by a single `tr_encounters_identity_immutable` trigger (revision 081 correction). Reparenting an encounter to a different timeline or campaign would otherwise silently orphan any `interaction.interactions`/`narrative.events` rows already created under its original timeline/campaign (via `narrative.event_causes.cause_encounter_id`/`.resulting_event_id`), which never re-validate against the encounter's own row changing — this applies to campaign-less encounters too, since nothing else pins a campaign-less encounter's timeline down once created. `src/dnd_ai/commands/encounters.py`'s `_lock_encounter()`/`LockedEncounter` is the matching application-layer guarantee that every such row is always attributed to the encounter's real (and now permanently fixed) timeline and campaign. `session_id` is deliberately left mutable: no dependent row derives its own session from the encounter's `session_id` (`resolve_combat_turn`/`end_encounter` each take their own, independent `session_id` per call), so there is nothing for a later change to orphan.

## 14. Quest and story model

```mermaid
erDiagram
    CORE_ENTITIES ||--|| NARRATIVE_QUESTS : is
    NARRATIVE_STORY_ARCS ||--o{ NARRATIVE_QUESTS : contains
    NARRATIVE_QUESTS ||--o{ NARRATIVE_QUEST_STAGES : contains
    NARRATIVE_QUEST_STAGES ||--o{ NARRATIVE_QUEST_OBJECTIVES : contains
    NARRATIVE_QUEST_OBJECTIVES ||--o{ NARRATIVE_OBJECTIVE_DEPENDENCIES : depends
    NARRATIVE_QUESTS ||--o{ NARRATIVE_QUEST_OUTCOMES : allows
    NARRATIVE_QUESTS ||--o{ CAMPAIGN_QUEST_STATE : tracked
    NARRATIVE_QUEST_OBJECTIVES ||--o{ CAMPAIGN_OBJECTIVE_STATE : tracked
    NARRATIVE_EVENTS ||--o{ CAMPAIGN_OBJECTIVE_STATE : advances
```

Primary tables — all built by **Phase 7 revision 073**:

- `narrative.story_arcs` — not entity-rooted (the diagram's `is` relationship is `narrative.quests` only), same reasoning as `world.area_connections`/`interaction.interactions`: a world-scoped grouping record with no independent canonical identity.
- `narrative.quests` — entity-rooted; the one CTI subtype in this domain.
- `narrative.quest_stages`
- `narrative.quest_objectives` — target reuses the `knowledge_items`/`event_effects` at-most-one-typed-target pattern (`target_entity_id` or one of the four dungeon-domain non-entity columns). `world.locations` and `knowledge.knowledge_items` are both entity-rooted, so `target_entity_id` alone covers "reach a location" and "discover knowledge" objectives without a separate typed column for either. `completion_rule` (JSONB, structured completion-rule metadata — e.g. a quantity threshold) and `visibility_policy` (an inferred small vocabulary: visible/hidden_until_active/hidden_until_discovered/gm_only) were added by **Phase 7 revision 074**, docs/PLAN.md §14.1 naming both as distinct from `completion_mode` (who decides completion) and `requirement_level='hidden'` (whether the objective is mandatory, not whether it's visible) — revision 073 had built only the latter two.
- `narrative.objective_dependencies`
- `narrative.quest_participants`
- `narrative.quest_rewards` — tied to `quest_outcome_id`, not `quest_id` directly, since different outcomes plausibly grant different rewards; item/currency rewards have no typed target yet (Phase 9's item domain doesn't exist), only `reward_knowledge_item_id`.
- `narrative.quest_outcomes`
- `campaign.quest_state` / `campaign.objective_state` — timeline-scoped, with an additional nullable `party_id` (NULL = timeline/campaign-wide tracking, set = that party's own independent progress) and `last_event_id` provenance reusing the shared `campaign.enforce_state_event_timeline()` guard (revision 066) — see §17.

Quest definitions describe possible progression; timeline or campaign state records actual progression. Objectives support required/optional/hidden status, dependencies, target entities, quantities, and automatic or GM-confirmed completion. Events advance objectives through `src/dnd_ai/commands/quests.py`'s `advance_objective()`: it locks the current `campaign.objective_state` row, records the causing `narrative.events` row (`objective_completed`/`objective_failed`), updates the state row, and links the two through a `narrative.event_effects` row (`target_quest_objective_id`, the sixth column in that table's at-most-one-target pattern) — every automated transition records its triggering event, per this section's original design intent. No automatic quest-level completion cascade is built yet (stage sequencing/optionality/mutual-exclusion policy is real design work with no exit criterion forcing a specific answer) — `campaign.quest_state` exists and is written directly for now, the same way `campaign.character_state` started as a plain snapshot table before anything automated wrote to it.

## 15. Knowledge model

```mermaid
erDiagram
    CORE_ENTITIES ||--|| KNOWLEDGE_KNOWLEDGE_ITEMS : is
    KNOWLEDGE_KNOWLEDGE_ITEMS ||--o{ KNOWLEDGE_KNOWLEDGE_VERSIONS : versions
    KNOWLEDGE_KNOWLEDGE_ITEMS ||--o{ KNOWLEDGE_ENTITY_KNOWLEDGE : believed
    CORE_ENTITIES ||--o{ KNOWLEDGE_ENTITY_KNOWLEDGE : knows
    KNOWLEDGE_ENTITY_KNOWLEDGE ||--o{ KNOWLEDGE_INFORMATION_TRANSFERS : source
    KNOWLEDGE_ENTITY_KNOWLEDGE ||--o{ KNOWLEDGE_INFORMATION_TRANSFERS : recipient
    CAMPAIGN_PARTIES ||--o{ KNOWLEDGE_PARTY_DISCOVERIES : discovers
    KNOWLEDGE_KNOWLEDGE_ITEMS ||--o{ KNOWLEDGE_PARTY_DISCOVERIES : revealed
```

Primary tables:

- `knowledge.knowledge_items` — **built in Phase 5** (revision 041), pulled forward from Phase 7 to satisfy that phase's "hidden connections remain distinct from party knowledge" exit criterion; see §26. Entity-rooted; `truth_status_id`/`knowledge_type_id` lookups; a single nullable typed subject reference (`subject_entity_id` or one of `subject_area_connection_id`/`_feature_id`/`_hazard_id`/`_interactable_id`, at most one set) rather than the plural `knowledge_item_subjects` junction the conceptual model implies — still not promoted; no exit criterion has needed more than one subject yet. **Phase 7 revision 073** added `effective_from_world_time_id`/`effective_to_world_time_id` (both nullable, ADR 0010 shape without an EXCLUDE constraint — a single row has nothing to overlap) plus a database-derived `validity_period INT8RANGE`.
- `knowledge.knowledge_versions` — **built by Phase 7 revision 073.** Append-only; `distortion_type` is an inferred, illustrative starter vocabulary (embellishment/omission/exaggeration/fabrication/simplification/other) — the domain model names the concept, not a taxonomy. No link back to `information_transfers` — a version can originate from a transfer or from direct GM authoring, and nothing yet forces the former.
- `knowledge.entity_knowledge` — **built in Phase 5** (revision 041). **Phase 7 revision 073** added a nullable `knowledge_version_id`, closing revision 041's own "nothing to version yet" placeholder now that `knowledge.knowledge_versions` exists; a trigger requires the version (when set) to belong to the same `knowledge_item_id` the row itself cites.
- `knowledge.information_transfers` — **built by Phase 7 revision 073.** Deviates from the erDiagram above in one respect: `source_entity_knowledge_id` is a single FK to `knowledge.entity_knowledge` (which already carries the source knower, the knowledge item, and their own interpretation together), not a separate source-knower reference; `recipient_entity_id` is a direct FK to `core.entities`, not to a second `entity_knowledge` row — the recipient's own belief, if one is later recorded, is a separate `entity_knowledge` row a caller inserts, not implied by the transfer itself. `modified_interpretation` records what was actually conveyed, when it differs from the source's own `interpretation` — this is what supports rumor propagation and misinformation. `caused_by_interaction_id`/`caused_by_event_id` are at most one of the two (both `NULL` is valid — an unrecorded/ambient rumor).
- `knowledge.expertise_domains` — lookup for `character_expertise.expertise_domain_id`; **built by Phase 7 revision 073** as an illustrative, extensible starter set (arcana, history, religion, nature, investigation, medicine, survival, persuasion, deception, insight, engineering, other).
- `knowledge.character_expertise` — **built by Phase 7 revision 073.** Character-level (`character.characters.character_id`), not timeline-scoped state — the same latitude `character.characters.size_category` already takes for stable character-definition traits.
- `knowledge.party_discoveries` — the discovery *record*: when and how a party learned a knowledge item. **Built in Phase 5** (revision 041); recipient is exactly one of `party_id` or `knower_entity_id` (partial unique indexes per recipient kind).
- `knowledge.public_knowledge` — what is known publicly within a location, independent of any one knower; **built by Phase 7 revision 073.** Regions are themselves locations (`world.locations.parent_location_id`, revision 038), so `location_id` alone covers both a single settlement and a broad region — no separate "region" concept was needed.

`campaign.party_knowledge` (§17) is the related but distinct *current effective view* of what a party presently knows — kept separate from the discovery log the same way `campaign.character_state` is kept separate from the events that produced it. **Built by a Phase 7 correction pass (revision 074)**, after review found the original revision 073 exit-criterion test exercised an unrelated individual knower's `entity_knowledge` row instead of party-level belief, and that `knowledge.party_discoveries` (an acquisition record with no belief/confidence/interpretation columns) could not stand in for it. One row per `(timeline, party, knowledge item)`; a nullable `knowledge_version_id` (same role as `entity_knowledge.knowledge_version_id`) and `last_event_id` provenance (reusing `campaign.enforce_state_event_timeline()`, revision 066).

A knowledge item represents a claim; truth status, awareness, belief, confidence, interpretation, and willingness to share are distinct fields. Entity knowledge stores what a knower believes, its confidence, interpretation, source, and willingness to share — a false belief is valid game data and must not be overwritten merely because the canonical truth is known to the GM. Discovery may be recorded for an individual character, a party, an organization, or the public within a location or region. Information transfers record source knower, recipient, transferred knowledge, modified interpretation, the causing interaction or event, and world time — this is what supports rumor propagation and misinformation.

Authenticated-user visibility is a fourth, separate concern. A user may be allowed to inspect a claim because the user's selected character knows it, because the user's party knows it, because it is public, because a campaign role supplies a GM capability, or because an explicit resource grant allows it. None of those authorization paths inserts `knowledge.entity_knowledge`, `knowledge.party_discoveries`, or `campaign.party_knowledge`; those tables describe the fictional world's awareness, not what an administrator is permitted to inspect. Conversely, a fact known by a character is exposed to a user only when that user has the appropriate character relationship and capability for the requested perspective.

**Phase 5 / Phase 7 boundary (closed).** Phase 5 pulled `knowledge_items`/`entity_knowledge`/`party_discoveries` forward (revision 041) and explicitly left temporal validity, `knowledge_versions`, `information_transfers`, `expertise_domains`/`character_expertise`, and `public_knowledge` for this phase — all delivered by revision 073 above. Discovery source/provenance was a free-text placeholder through Phase 5; real provenance (`learned_via_interaction_id`/`learned_via_event_id`, `discovered_via_interaction_id`/`discovered_via_event_id`) was closed by **Phase 6** revision 063, not this phase — see §27.

## 16. Interaction and resolution model

Built by Phase 6 revision 061; `narrative.event_causes.cause_interaction_id` (revision 062) closes the reference this domain's existence unblocks — see §27.

```mermaid
erDiagram
    INTERACTION_INTERACTIONS ||--o{ INTERACTION_ACTIONS : contains
    INTERACTION_ACTIONS ||--o{ INTERACTION_TARGETS : targets
    INTERACTION_ACTIONS ||--o{ INTERACTION_CHECK_REQUESTS : requests
    INTERACTION_CHECK_REQUESTS ||--o{ INTERACTION_CHECK_RESULTS : resolves
    INTERACTION_INTERACTIONS ||--o{ INTERACTION_CONSEQUENCES : yields
    INTERACTION_INTERACTIONS ||--o{ INTERACTION_EXTERNAL_MESSAGES : originates
    INTERACTION_INTERACTIONS |o--o| NARRATIVE_EVENTS : produces
```

Primary tables:

- `interaction.interactions` — not entity-rooted, unlike `narrative.events`; a high-volume log record (same reasoning DATABASE_MODEL.md §9 gives for `world.area_connections`/etc. not being entities). Scoped to `timeline_id`/`campaign_id`/`session_id` like events; `resulting_event_id` (nullable) is the event this interaction produced, when its outcome was significant enough to promote (§12's event-granularity guidance) — most interactions have none. `status` moves `initiated → resolving → resolved` (or `failed`/`cancelled`): still `initiated` until its first check result lands, `resolving` from then until its last, and irreversibly terminal once `resolved`/`failed`/`cancelled` (revisions 070–071, see §27) — a status revert is rejected outright, which is what keeps the append-only structural-record guard below from being bypassed by reverting it first. The transition itself is database-owned (`interaction.advance_interaction_status_on_check_result()`, revision 072, see §27) — it fires atomically with any `check_results` `INSERT`, regardless of which command performs it.
- `interaction.actions` — an individual operation within an interaction (DOMAIN_MODEL.md §16.2); a complex interaction may contain several, ordered by `sequence_number`, each with its own `actor_entity_id`. Can only be created while the interaction is still `initiated` (revision 072, see §27) — the same rule that already governed editing one.
- `interaction.targets` — belongs to an *action*, not the interaction directly (DOMAIN_MODEL.md §16.3 ties it there explicitly). Reuses the `knowledge.knowledge_items`/`narrative.event_effects` single-typed-target pattern (`target_entity_id` or one of the four dungeon-domain non-entity columns, at most one) plus a free-text `target_description` for abstract objectives with no typed reference. Can only be created while its interaction is still `initiated` (revision 072).
- `interaction.check_requests` — also action-scoped. References `rules.abilities`/`rules.skills` properly (not free text): `check_kind` is `ability_check`/`skill_check`/`saving_throw`; exactly one of `ability_id` (ability check/saving throw) or `skill_id` (skill check, governing ability reached through `rules.skills.ability_id`) is set. Validated against the interaction's world's ruleset allow-list via the existing `rules.ruleset_allowed_for_world()` helper (revision 035) on insert, and by `rules.enforce_world_ruleset_still_in_use()`'s reverse guard on the ruleset side (revision 068, see §27). `target_id` (nullable FK to `interaction.targets`, added by revision 064) names which of the action's possibly-several targets this specific check resolves, when there is one; enforced to belong to the same action as the check request. May have more than one per interaction (an interaction's actions may each request several) — see the resolution flow below for how completion is tracked. Can only be created while its interaction is still `initiated` (revision 072) — a request created once resolution has begun could never be answered, since `check_results` itself only accepts `initiated`/`resolving` (below).
- `interaction.check_results` — at most one per `check_requests` row (a re-roll is a new request, not a mutation); roll, modifiers, total, `degree_of_success`, visibility, external system source. Can only be inserted while the owning interaction is still `initiated` or `resolving` — never once terminal (revisions 070–071, Phase 6 exit-review follow-up corrections — see §27). Once recorded, a result itself becomes append-only immediately (revision 067's guard already treats any non-`initiated` status, including `resolving`, as locked for `UPDATE`/`DELETE`).
- `interaction.consequences` — interaction-level, not action-level (DOMAIN_MODEL.md §16.6 is explicit). `consequence_type` classifies what kind of outcome (observation/event/state_change/discovery/quest_change/relationship_change); `resulting_event_id`/`resulting_party_discovery_id`/`resulting_quest_objective_state_id` (the last added by **Phase 7 revision 073**, closing this table's own documented placeholder for its quest half) are the typed outcome references built so far — `relationship_change` still has no FK target (Phase 8's domain doesn't exist).
- `interaction.external_messages` — the Discord/Foundry message or command that originated an interaction, so external actions create or reference interaction records rather than writing directly to arbitrary tables. Unique per `(source_system, external_id)` so re-delivery cannot double-ingest.

Interactions include searching, movement, lockpicking, conversation, attacks, spellcasting, resting, travel, using an item, activating mechanisms, and reading inscriptions. Not all interactions create events — persistent or narratively meaningful consequences should.

Resolution flow:

```text
Create interaction
    -> determine required checks
    -> resolve rules
    -> create observations and consequences
    -> create significant event where appropriate
    -> update state, knowledge, relationships, and quests
```

`src/dnd_ai/commands/interactions.py`'s `resolve_check()` implements this per check_request: it locks the parent interaction before recording a result (rejecting a check resolved against an interaction that has already reached a terminal status) and links any event it produces to the interaction (`resulting_event_id`, a `state_change` consequence). The status transition itself — forward to `resolving` if any check_request across the interaction's actions is still unanswered, or to `resolved` once every one of them has a result, never backward, and (status irreversibility, above) never past `resolved` once reached — is not application logic at all: `interaction.advance_interaction_status_on_check_result()` (revision 072) performs it atomically as part of the `check_results` `INSERT`, so it applies uniformly whether that insert came from `resolve_check()` or any other caller. A single-check interaction skips `resolving` entirely, since its one result is simultaneously its first and its last.

## 17. Typed timeline state

Typed state tables are optimized for current effective reads. Once `narrative.events` exists (Phase 6), a state row's target-level history should include `timeline_id`, a target identifier, `effective_from_event_id`, `effective_to_event_id NULL` for current rows, and system timestamps, with a partial unique index enforcing one current row per timeline and target where history is tracked that way.

That is the target model, not a requirement every typed-state table must already meet. Phase 4's `campaign.character_state`, `.character_conditions`, and `.character_resources` are current-state snapshots with no full interval-history columns: they predate `narrative.events` and each table instead enforces "one row per (timeline, target)" directly through its primary key. This is correct for their phase, not a gap to silently work around — do not add `effective_from_event_id`/`effective_to_event_id` to a table merely because this section names them as the general shape; rule 6 (state changes need a causal event, committing atomically) is a transaction-boundary guarantee the command layer provides, not a column these tables were missing.

Phase 6 revision 060 extended the five Phase-5 dungeon-domain state tables below with `last_event_id UUID FK NULL REFERENCES narrative.events(event_id) ON DELETE SET NULL` — the provenance reference this section calls for, not full interval history. A Phase 6 exit-review correction pass (revision 066) closed the remaining gap this section previously flagged as "unstarted": `campaign.character_state`/`.character_conditions`/`.character_resources` now carry the same column, and — for all eight tables, not just the original five — a shared `campaign.enforce_state_event_timeline()` trigger additionally guarantees the cited event actually belongs to the same timeline as the state row (revision 060 alone did not check this). Phase 7 revision 073 attaches the same shared trigger to `campaign.quest_state`/`.objective_state` directly at creation, rather than retrofitting it later — ten tables now share this one guard.

That column had no application writer for `character_conditions`/`.character_resources`, and only one narrow writer (combat-turn damage) for `character_state.current_hit_points`, until Phase 11 workstream 6's `dnd_ai.commands.character_state` — healing/non-combat HP adjustment, condition apply/remove, and resource adjustment, each populating `last_event_id` alongside the state change in the same transaction, closing the "left to whichever later increment actually produces character-affecting events" deferral this document's own "Not built in increment 1" list (§6.4) recorded.

Primary tables:

- `campaign.character_state` — includes `character_build_id UUID FK NULL` to `character.character_builds` (§7.4), the active build for this character *on this timeline*; must belong to the same character as the state row (enforced by trigger)
- `campaign.character_conditions`
- `campaign.character_resources`
- `campaign.character_inventory` — a character-centric read index over `item_ownership`/`inventory_entries` (§11); the source of truth stays with the item-level tables, this is the "what is this character carrying right now" view
- `campaign.character_location_history` — built by Phase 5 revision 042, upgraded to the full ADR 0010 interval contract by revision 043 (exit-review finding: revision 042 only had same-world checks and a partial-unique-index shortcut). `arrived_at_world_time_id` is required (the interval's finite start, mirroring `campaign.party_memberships.effective_from_world_time_id`); `location_period INT8RANGE` is derived by trigger from the endpoints' `sort_key` values and, since revision 050, declared `NOT NULL` — matching `party_memberships.effective_period` exactly rather than only behaving as if it were; `EXCLUDE USING gist (timeline_id WITH =, character_id WITH =, location_period WITH &&)` rejects any overlap, open or closed — which also fully subsumes the old "one open row" rule, since two unbounded-upper ranges for the same `(timeline, character)` always overlap. Doubles as the current-location view: the row with `departed_at_world_time_id IS NULL` is current. No `current_location_id` column was added to `campaign.character_state` (revision 021) for this.
- `campaign.location_state` — built by Phase 5 revision 040 (`is_searched`, `is_destroyed`, `alarm_level`, `condition_notes`); `last_event_id` added by Phase 6 revision 060
- `campaign.area_connection_state` — built by Phase 5 revision 040; `connection_status_id` FK to a seeded lookup (open/closed/locked/broken/destroyed); `last_event_id` added by Phase 6 revision 060
- `campaign.area_feature_state` — built by Phase 5 revision 040 (`is_destroyed`, `condition_notes`); `last_event_id` added by Phase 6 revision 060
- `campaign.hazard_state` — built by Phase 5 revision 040; `hazard_status_id` FK to a seeded lookup (armed/triggered/reset/bypassed/disarmed); `last_event_id` added by Phase 6 revision 060
- `campaign.interactable_state` — built by Phase 5 revision 040; `interactable_status_id` FK to a seeded lookup (active/inactive/activated/deactivated/broken/locked); `last_event_id` added by Phase 6 revision 060
- `campaign.organization_state` — built by **Phase 8 revision 076**; `organization_status_id` FK to a seeded lookup (active/dissolved/dormant/banned/underground/unknown); one current row per `(timeline, organization)`, using the shared `campaign.enforce_state_event_timeline()` guard directly.
- `campaign.relationship_state` — built by **Phase 8 revision 076**; `relationship_status_id` FK to a seeded lookup (active/ended/broken/estranged/dormant/unknown) plus `affinity`/`trust`/`respect`/`fear`/`obligation`/`emotional_tone`/`private_interpretation`. Additional nullable `perspective_holder_entity_id` dimension — same NULL/set convention as `quest_state`'s `party_id`: `NULL` is the relationship's shared/objective status; set is that one participant's own current subjective reaction, and it must be a participant in the relationship (enforced by trigger). This is the row `src/dnd_ai/commands/relationships.py`'s `evolve_relationship_reaction()` updates — the "NPC and faction reactions can evolve from events" exit criterion — distinct from the stable, authored `world.relationship_perspectives` baseline (§10.1).
- `campaign.item_state`
- `campaign.quest_state` — built by **Phase 7 revision 073**; `quest_status_id` FK to a seeded lookup (unavailable/available/active/suspended/completed/failed/abandoned); `last_event_id` from creation, using the shared `campaign.enforce_state_event_timeline()` guard (revision 066) directly rather than needing its own copy. Additional nullable `party_id` dimension — see §14.
- `campaign.objective_state` — built by **Phase 7 revision 073**; `objective_status_id` FK to a seeded lookup (hidden/available/active/completed/failed/skipped/superseded); same `last_event_id`/`party_id` shape as `quest_state`.
- `campaign.npc_goal_state`
- `campaign.npc_emotional_state`
- `campaign.party_knowledge` — built by **Phase 7 revision 074**; current effective view of what a party knows, distinct from the discovery log (see §15). One row per `(timeline, party, knowledge item)`, with a nullable `knowledge_version_id` and `last_event_id` provenance, same shape as `quest_state`/`objective_state` above.
- `campaign.entity_overrides` — a generic JSON escape hatch for experimental or rarely queried properties; must not replace typed designs (§19.2 in PLAN.md), and a property that turns out to matter should be promoted to its own typed column rather than left here

Examples of tracked state: current and maximum HP, temporary HP, death-save state, exhaustion, initiative when in an encounter, current location, active conditions, expended resources, current form/transformation; door open/closed/locked/broken/destroyed; connection known/undiscovered; trap armed/triggered/reset/bypassed/disarmed; room searched; shrine activated; bridge collapsed; alarm level.

## 18. AI and approval model

```mermaid
erDiagram
    AI_AGENTS ||--o{ AI_AGENT_ASSIGNMENTS : assigned
    AI_AGENTS ||--o{ AI_CONTEXT_REQUESTS : receives
    AI_CONTEXT_REQUESTS ||--o{ AI_CONTEXT_SNAPSHOTS : captures
    AI_CONTEXT_REQUESTS ||--o{ AI_GENERATED_OUTPUTS : produces
    AI_GENERATED_OUTPUTS ||--o{ AI_PROPOSED_CHANGES : proposes
    AI_PROPOSED_CHANGES ||--o{ AI_CHANGE_REVIEWS : reviewed
    AI_PROPOSED_CHANGES ||--o| NARRATIVE_EVENTS : accepted_as
    AI_GENERATED_OUTPUTS ||--o{ AI_EMBEDDING_RECORDS : indexed
```

Primary tables:

- `ai.agents`
- `ai.agent_roles`
- `ai.agent_assignments`
- `ai.prompt_templates`
- `ai.prompt_fragments`
- `ai.context_requests`
- `ai.context_snapshots` — the assembled context actually sent for a request, retained for reproducibility and debugging, distinct from the request itself
- `ai.generated_outputs`
- `ai.proposed_changes`
- `ai.change_reviews`
- `ai.embedding_records`

Initial agent roles: NPC portrayal agent, dungeon-state agent, quest manager, rules assistant, world-state manager, lore consistency checker, session summarizer, rumor propagation agent.

AI proposals never become canonical merely because they were generated. Agents do not write directly to canonical tables — they submit proposed commands or structured changes, and a policy engine determines whether a proposal may be applied automatically, requires GM approval, or is rejected by validation. Low-risk automatic examples: marking an already-authored hidden feature as discovered, recording conversational memory, advancing a deterministic counter. High-impact approval-required examples: character death, settlement destruction, faction-control changes, permanent quest failure, creation of major new canon. Accepted mutations must produce normal domain commands, events, state updates and audit records.

**Built by Phase 12 (revision 093_ai_domain):** every table above except `ai.embedding_records`, which stays unbuilt — PLAN.md's own Phase 12 entry forbids a vector-search framework until PostgreSQL full-text search and relational retrieval have proved insufficient, so a table with no reader would only be the "build ahead of the phase that needs it" anti-pattern CLAUDE.md warns against. `ai.agent_roles` is seeded with all eight initial roles; only `npc_portrayal` is wired to a concrete `ai.agents` row anywhere in this phase's application code (`dnd_ai.commands.ai_npc`), per PLAN.md's "start with one use case" instruction. `ai.agent_assignments.entity_id` was `NOT NULL` in the original revision — this phase's first wired role (`npc_portrayal`) always names the NPC entity being portrayed — but is made nullable by a same-phase follow-up (revision `096_campaign_scoped_agents`) once the audience-aware synthesis service below needed a second, `session_summarizer`-rooted role with no single in-world entity target; `ai.enforce_agent_assignment_world()` skips its own entity/world check entirely when `entity_id IS NULL`. `ai.proposed_changes.proposal_kind` is a single-value closed CHECK set (`'reveal_knowledge'` only) rather than free text, since — unlike `integration.external_identifiers.external_kind`, whose vocabulary genuinely varies per external system — this vocabulary is entirely owned by this codebase's own command layer; extending it is a migration, the same posture `narrative.event_types`/`audit.change_actions` already take. `dnd_ai.commands.knowledge.reveal_knowledge_to_party` is the one target command an approved proposal invokes today, reusing the existing `'knowledge_revealed'` `narrative.event_types` code and a new `narrative.event_effects.target_knowledge_item_id` column (revision `095_knowledge_event_target`) alongside the pre-existing `target_entity_id`. No `audit.agent_activity`/`.approval_history` rows are written — every fact those tables would carry is already captured, with full provenance, by `ai.context_requests`/`.context_snapshots`/`.generated_outputs`/`.proposed_changes`/`.change_reviews`; a second `audit.*` copy of the same facts would violate rule 1 (PostgreSQL is the only source of truth, not "the same fact stored twice").

The rules/reference corpus §18.3 of PLAN.md describes is built by the same phase (revision `094_reference_corpus`), split across `core.source_documents` (the registered, immutable, hash-identified source — alongside its §5.5 siblings, since it is a provenance/administrative record, not a world entity) and three `ai.*` tables under the AI/context boundary: `ai.reference_passages` (one citable chunk per registered source, with a generated `tsvector` column and a GIN index — PostgreSQL-native full-text search, no embeddings), `ai.reference_source_campaigns` (the campaign-restricted retrieval grant, `is_house_rule`-flagged for precedence), and `ai.reference_retrievals`/`.reference_retrieval_results` (the retrieval audit trail, independent of `ai.context_requests` since a rules-question lookup is not always driven by an agent invocation). `security.resource_grants.source_document_id`/`.ai_proposed_change_id` — two of the eight `§19.6` target columns revision 080 deliberately deferred ("the migration that introduces their target table") — are added in the same revision, once both target tables exist.

**Also built by Phase 12:** the audience-aware synthesis service PLAN.md's Phase 12 "Deliver" list names — `dnd_ai.domain.context_assembly.assemble_campaign_synthesis_context` (`GM_BRIEF`/`PLAYER_SUMMARY`/`OBSERVER_SUMMARY`), layered over the existing `dnd_ai.queries.summary.get_campaign_summary_view` rather than reimplementing session/event retrieval, and `dnd_ai.commands.ai_synthesis.request_campaign_synthesis` (same three-transaction, no-network-call-under-a-lock shape as `dnd_ai.commands.ai_npc`). Purely informational — it writes only `ai.context_requests`/`.context_snapshots`/`.generated_outputs`, never `ai.proposed_changes`. The three audience tiers are three distinct, separately-authorized query paths (`dnd_ai.api.ai_synthesis`: `canon.edit` for `gm_brief`, an authorized `dnd_ai.api.access.resolve_party_perspective` result for `player_summary`, `campaign.view` alone for `observer_summary`), not one payload filtered after assembly — the mechanism the "same question, appropriately different GM/player-character/observer answers, and inaccessible facts never enter the provider request" exit criterion requires. `ai.context_requests.request_kind`'s existing CHECK set (`gm_brief`/`player_summary`/`observer_summary`, alongside `npc_conversation`/`rules_question`) already covered all three tiers without any migration change. Not yet built: a `rules_question`-tier synthesis command over `dnd_ai.commands.reference_corpus.retrieve_cited_passages` — §18.3's own retrieval/citation/audit requirements are fully delivered (see above), but no AI agent yet turns a retrieved passage set into prose. `dnd_ai.domain.context_assembly.assemble_npc_conversation_context`'s own `related_quests` field (the NPC's `narrative.quest_participants` involvement, joined to the requesting party's own `campaign.quest_state`) closes what was originally the one remaining gap in the NPC-conversation exit criterion — encounter, relationship, and quest state are all included there now.

## 19. Security, audit and integration

### Security

Security distinguishes identity, campaign membership, role-derived capability, semantic character relationships, in-world knowledge, and explicit resource access. A user may have multiple roles and characters in one campaign and different roles and characters in another. No character, fact, or other protected record has a single `owner_user_id` visibility shortcut.

**§19.1–19.7 delivered by revision 080** (`080_security_identity_and_access`, Phase 10 workstream 1 — schema only, chained after `079_integration_domain`). Reconciles rather than collides with the revision-003 placeholder: `security.users` is reshaped in place (drop `username`/`is_active`, add `lifecycle_status_id`/`last_login_at`) since it is already FK-referenced for attribution by `core.entities.created_by_user_id`, `core.entity_names`/`.entity_tags.tagged_by_user_id`, `audit.change_actions.actor_user_id`, and `character.characters.player_user_id`; the old global `security.roles`/`.user_roles` pair is dropped and replaced by the campaign-scoped `security.roles` plus `security.membership_roles` below. `security.resource_grants` implements only the six target columns the Phase 10 vertical slice needs (`character_id`, `entity_id`, `knowledge_item_id`, `quest_id`, `session_id`, `event_id`) — `source_document_id`, `ai_proposed_change_id`, and `import_job_id` are deferred to the migration that introduces their target table, per §19.6's own extension rule. The application layer, command/query services, OIDC integration, and AWS deployment this schema supports are later Phase 10 workstreams, not part of this revision.

Two correction passes folded into the same, still-unmerged revision 080 close gaps reviews found before this workstream ever shipped.

The first pass: (1) the §22 rule 19 campaign owner/access-manager retention invariant is database-enforced — `security.campaign_has_access_manager()`/`.assert_campaign_retains_access_manager()` plus five `DEFERRABLE INITIALLY DEFERRED` constraint triggers on `security.campaign_memberships`, `.membership_roles`, `.role_capabilities`, `.roles`, and `campaign.campaigns`, using the stable `access.manage` capability code (never a role's name) and a `campaign.campaigns` row lock for concurrency-safety, seeded with exactly the `campaign_owner`/`access.manage` `role_capabilities` pairing the invariant needs to be satisfiable at all; (2) reverse-mutation guards — `security.campaign_memberships.campaign_id`, `security.access_groups.campaign_id`, `campaign.sessions.campaign_id`, and `narrative.events.campaign_id`/`.timeline_id` are immutable once set (`core.enforce_immutable_columns()`, the same mechanism revisions 030/033/075 established), closing the "parent row reparented out from under an already-valid child" gap for every table below that scope-checks against them; (3) every `*_by_membership_id` actor column (`campaign_memberships.ended_by_membership_id`, `campaign_invitations.invited_by_membership_id`, `membership_roles.granted_by_membership_id`, `membership_character_relationships.granted_by_membership_id`, `access_group_memberships.added_by_membership_id`, `resource_grants.granted_by_membership_id`) is guarded to belong to the same campaign as the row it acts on.

A second pass closed three further gaps the first pass's own honest limitations section had flagged as accepted, which a follow-up review concluded were not actually acceptable: (1) the retention invariant's `campaign.campaigns` constraint trigger now fires on **INSERT as well as UPDATE** — a campaign row created active directly, not only one later transitioned into `'active'`, is checked; there is no remaining "a campaign that never had an owner is exempt" case, since the trigger unconditionally asserts on insert and `assert_campaign_retains_access_manager()` re-reads live status, so establishing the campaign and its owner in one transaction (active from the start, or created non-active and activated after assigning ownership — both work identically since the check is deferred to commit) is the only way to create an active campaign at all. (2) `security.campaign_has_access_manager()` now requires a **non-expiring** qualifying grant (`membership_roles.expires_at IS NULL`), not merely one that satisfies `expires_at > now()` at write time — a trigger cannot fire on the later passage of a stored timestamp, so comparing against `now()` inside the check function could only ever be true "for now," not actually enforced; requiring permanence closes that hole without depending on a wall-clock mechanism PostgreSQL doesn't have. A temporary co-owner remains fully supported alongside a permanent one. (3) `security.roles.campaign_id` no longer reuses the shared `core.enforce_immutable_columns()` (which allows a NULL → value transition, correct for every *other* nullable identity column it protects but wrong here) — a dedicated `security.enforce_roles_campaign_immutable()` treats NULL as a permanent value (system template) and rejects every transition, including NULL → value, so a system-template role already assigned across multiple campaigns can never be promoted to campaign-scoped.

A third pass closed a gap none of the above actually protected against: every retention-invariant comparison above is expressed as a hardcoded lookup **code** — `core.lifecycle_statuses.code = 'active'`, `security.membership_statuses.code = 'active'`, `security.capabilities.code = 'access.manage'` — and nothing in the first two passes fired on an UPDATE that renamed one of those specific rows' `code` directly, since none of the guard triggers listen for that event. A rename would have silently broken every comparison in the invariant with no trigger able to observe it, contradicting the "fully database-enforced" and "stable identifier" claims made above. The fix has two parts, both scoped to only the specific seeded rows this revision actually depends on by name (every other row, and every other column on these same rows — display name, description, sort order — remains freely editable): (1) a new generic `core.enforce_protected_lookup_codes()` (the same reusable-trigger-with-arguments shape as `core.enforce_immutable_columns()`) rejects renaming those three specific rows, attached to `core.lifecycle_statuses` (a table this revision does not own — the trigger is dropped explicitly in `downgrade()`, not via a `DROP TABLE` this revision doesn't perform), `security.membership_statuses`, and `security.capabilities`; the existing per-table `code` `UNIQUE` constraint already stops a *different* row from being renamed into the freed-up code, so protecting only the original seeded row is sufficient. (2) `security.campaign_has_access_manager()` now also requires `security.capabilities.is_active` and `security.membership_statuses.is_active` on the specific rows it matches — an explicit decision, not a silent gap: an inactive `access.manage` capability or an inactive `'active'` membership-status row does not authorize, mirroring how `security.roles.is_active` already worked. Deactivating either specific row is guarded exactly like removing `access.manage` from a role already was, via two more constraint triggers (`security.enforce_capabilities_retain_access_manager()`, `security.enforce_membership_statuses_retain_access_manager()`), bringing the total to seven. `core.lifecycle_statuses.is_active` (the campaign's own status row) is deliberately excluded from this — it is shared, pre-existing infrastructure this revision does not own, every row is seeded active with no other consumer anywhere in the codebase gating on it, and its documented meaning (whether a value is offered for new assignment) is a different question from whether an already-active campaign should retroactively stop counting; see the migration's own "Deliberate scoping decisions" for the full reasoning.

See the migration's own docstring for the full design and its "Deliberate scoping decisions" for what remains intentionally out of scope.

#### 19.1 Identity and login

##### `security.users`

Application identity independent of any login provider.

Key columns:

- `user_id UUID PK`
- `display_name TEXT`
- `email TEXT NULL` — informational and not the durable external identity key
- `lifecycle_status_id UUID FK`
- `created_at TIMESTAMPTZ`
- `updated_at TIMESTAMPTZ`
- `last_login_at TIMESTAMPTZ NULL`

##### `security.external_identities`

Maps one application user to one or more OIDC identities.

Key columns:

- `external_identity_id UUID PK`
- `user_id UUID FK`
- `issuer TEXT`
- `subject TEXT`
- `email_at_last_login TEXT NULL`
- `claims_snapshot JSONB NULL` — minimal allow-listed claims needed for diagnostics; never raw tokens
- `linked_at TIMESTAMPTZ`
- `last_authenticated_at TIMESTAMPTZ NULL`
- `revoked_at TIMESTAMPTZ NULL`

The active identity key is unique on `(issuer, subject)`. Email is not an identity key because it may change or be reused. Password hashes and OIDC access/refresh tokens do not belong in this table when authentication is delegated to an external identity provider.

Despite the table's docstring above, `issuer`/`subject` are plain, unconstrained `TEXT` — nothing requires `issuer` to be a real OIDC issuer URL or `subject` to be an OIDC `sub` claim. Phase 11 workstream 1's `link_foundry_identity` (`dnd_ai.commands.integration`) reuses this same table for Foundry-user-to-platform-user mapping rather than introducing a parallel Foundry-specific table: it derives a synthetic `issuer` of `foundry:<external_system_id>`, scoping a Foundry-side user id to the one registered `integration.external_systems` row (world) it came from, so the same Foundry-side id from two different Foundry worlds never collides. This maps identity only, not authentication — a live Foundry adapter still needs its own way to authenticate a request as acting for a given Foundry user, which is not yet built (see [docs/PLAN.md](../PLAN.md) Phase 11).

##### `security.service_accounts`

Non-human application principals. Service accounts never gain campaign access merely by existing; capabilities are assigned through explicit service-account grants or narrowly scoped application configuration, and all actions identify the service principal in audit records.

#### 19.2 Campaign membership and invitations

##### `security.campaign_invitations`

Tracks invitations without pre-creating a durable membership for an unknown recipient.

Key columns:

- `campaign_invitation_id UUID PK`
- `campaign_id UUID FK`
- `invited_email TEXT NULL`
- `invitation_token_hash TEXT`
- `invited_by_membership_id UUID FK`
- `expires_at TIMESTAMPTZ`
- `accepted_by_user_id UUID FK NULL`
- `accepted_at TIMESTAMPTZ NULL`
- `revoked_at TIMESTAMPTZ NULL`
- `created_at TIMESTAMPTZ`

Only the token hash is retained. Acceptance creates or activates a campaign membership through an application command and is idempotent.

##### `security.campaign_memberships`

The many-to-many association between users and campaigns and the root of human authorization within a campaign.

Key columns:

- `campaign_membership_id UUID PK`
- `campaign_id UUID FK`
- `user_id UUID FK`
- `membership_status_id UUID FK` — invited, active, suspended, revoked, departed
- `joined_at TIMESTAMPTZ NULL`
- `ended_at TIMESTAMPTZ NULL`
- `ended_by_membership_id UUID FK NULL`
- `created_at TIMESTAMPTZ`
- `updated_at TIMESTAMPTZ`

There is at most one open membership (`ended_at IS NULL`) per `(campaign_id, user_id)`. Revoked and departed memberships are closed rather than deleted and remain for auditability. Suspended is an open but non-authorizing status. A membership belongs to the campaign's timeline through `campaign.campaigns`; narrower timeline scope is placed on the particular relationship or grant that requires it rather than duplicating the campaign's normal timeline on every membership row.

The earlier sketch names `security.campaign_members`; the target name is **`security.campaign_memberships`** because each row is an authorization relationship with lifecycle and roles, not a user record.

#### 19.3 Roles and capabilities

Primary tables:

- `security.roles` — configurable campaign-role definitions such as campaign owner, GM, assistant GM, player, observer, import reviewer and rules curator
- `security.capabilities` — stable operation codes such as `campaign.view`, `character.control`, `canon.edit`, `import.approve`, `access.manage` and `rules_source.manage`
- `security.role_capabilities` — many-to-many role-to-capability defaults
- `security.membership_roles` — many-to-many campaign-membership-to-role assignments

Key constraints:

- A role is either a system template or belongs to one campaign; a campaign membership may receive only roles usable by that campaign.
- A membership may hold multiple roles concurrently.
- Role and capability codes are stable identifiers; display names are not authorization keys.
- Assignment and revocation record `granted_by_membership_id`, `granted_at`, optional `expires_at`, and `revoked_at`.
- Campaign owner and access-management changes are application commands with audit records; the database prevents an active campaign from being left with no authorized owner.

Application code authorizes capabilities, not hard-coded role names. Roles provide broad defaults but do not imply that a player or observer may inspect every resource in the campaign.

The earlier `security.user_roles` and `security.permissions` sketches are superseded by `security.membership_roles` and `security.capabilities`/`security.role_capabilities`. Global administrative privileges, if later required, use a separate explicitly privileged mechanism and never masquerade as campaign roles.

#### 19.4 Human-to-character relationships

##### `security.character_relationship_types`

Lookup for semantic relationships such as owner, primary controller, co-controller, viewer, portrayer/assistant GM, former controller and observer-approved viewer.

##### `security.membership_character_relationships`

Many-to-many relationship between an active campaign membership and a same-world character.

Key columns:

- `membership_character_relationship_id UUID PK`
- `campaign_membership_id UUID FK`
- `character_id UUID FK`
- `character_relationship_type_id UUID FK`
- `timeline_id UUID FK NULL`
- `effective_from_world_time_id UUID FK NULL`
- `effective_to_world_time_id UUID FK NULL`
- `effective_period INT8RANGE NULL`
- `granted_by_membership_id UUID FK`
- `granted_at TIMESTAMPTZ`
- `expires_at TIMESTAMPTZ NULL`
- `revoked_at TIMESTAMPTZ NULL`
- `notes TEXT NULL`

The membership's campaign, the character's world, and an optional timeline must agree. Fictional-time bounds use the ADR 0010 shape when supplied; real-time `expires_at` separately supports temporary operational access. Active duplicate relationships of the same type are rejected. A transfer of ownership or control closes the prior relationship and creates a new row rather than overwriting history.

##### `security.character_relationship_type_capabilities`

Maps a relationship type to default character-scoped capabilities, including:

- `discover`
- `view_summary`
- `view_full`
- `view_private`
- `view_character_knowledge`
- `edit_narrative`
- `edit_mechanical_state`
- `interact`
- `control`
- `manage_access`

The relationship records semantic meaning; this mapping supplies defaults. A direct typed resource grant (§19.6) may extend or restrict a specific membership without inventing another relationship type.

The earlier `security.character_permissions` sketch is superseded by these semantic relationships plus typed resource grants. `character.character_controllers` remains the operational controller assignment described in §7.3 and may include AI, service, or external-system controllers; it is not interchangeable with a user's campaign authorization.

#### 19.5 Access groups

Primary tables:

- `security.access_groups` — campaign-scoped named sets such as livestream observers, former players or a GM-curated lore audience
- `security.access_group_memberships` — many-to-many association between campaign memberships and access groups

Groups simplify repeated grants but do not represent in-world parties. Adding a user to an access group does not add a character to `campaign.party_memberships`, reveal knowledge in-world, or create an event. Group membership and revocation retain granting actor and timestamps.

#### 19.6 Typed resource grants

##### `security.resource_grants`

Provides explicit many-to-many access to protected records without an unenforced `(resource_type, resource_id)` polymorphic reference.

Key columns:

- `resource_grant_id UUID PK`
- `campaign_id UUID FK`
- `timeline_id UUID FK NULL`
- `grantee_campaign_membership_id UUID FK NULL`
- `grantee_access_group_id UUID FK NULL`
- `capability_id UUID FK`
- `effect TEXT` — `allow` or `deny`
- `character_id UUID FK NULL`
- `entity_id UUID FK NULL`
- `knowledge_item_id UUID FK NULL`
- `quest_id UUID FK NULL`
- `session_id UUID FK NULL`
- `event_id UUID FK NULL`
- `source_document_id UUID FK NULL`
- `ai_proposed_change_id UUID FK NULL`
- `import_job_id UUID FK NULL`
- `granted_by_membership_id UUID FK`
- `grant_source TEXT`
- `reason TEXT NULL`
- `granted_at TIMESTAMPTZ`
- `expires_at TIMESTAMPTZ NULL`
- `revoked_at TIMESTAMPTZ NULL`

Exactly one grantee column and exactly one typed resource target column are non-null. Every target must belong to the grant's campaign world and, where relevant, its campaign or timeline. `character_id` exists separately from general `entity_id` so character-only capabilities can be constrained to actual characters; callers must not create two grants for the same logical target. Additional protected resource kinds add real nullable foreign-key columns and extend the one-target constraint in the migration that introduces them.

Active grants are unique for the same grantee, target, timeline scope, capability and effect. Revocation closes the grant; it does not delete it. Expiration uses real time. Fictional-time visibility is derived from the target's knowledge/event validity or represented by an explicit timeline-scoped grant, not overloaded into `expires_at`.

An explicit deny overrides an allow at the same or broader inherited path, except that the application must not permit a grant to remove the minimum capabilities required to preserve an active campaign owner. Denies are used sparingly for concrete exceptions; absence of an allow remains the default denial.

The initial Phase 10 migration implements only the typed targets required by the playable vertical slice and portal queries. Later resource types extend the same constrained pattern as needed; Phase 10 does not need a universal ACL framework for every table in the database.

#### 19.7 Effective access resolution

For every human request, application services resolve access in this order:

1. Authenticate the external identity to `security.users`.
2. Require an active `security.campaign_memberships` row.
3. Resolve the campaign and requested timeline.
4. Collect capabilities from active membership roles.
5. Resolve semantic character relationships and their default capabilities.
6. Resolve party/public knowledge only for an authorized selected character perspective.
7. Apply active direct and access-group resource grants, including explicit restrictions.
8. Filter rows, sensitive fields, relationship edges, identifiers, counts, search results and AI context before returning or synthesizing an answer.
9. Audit sensitive reads and all mutations.

GM administrative visibility does not make a GM-controlled character an in-world knower. A user-character relationship does not expose all facts known by all of that user's characters simultaneously: the request identifies a viewing perspective, and the query layer evaluates that perspective. Inaccessible resources must be indistinguishable from nonexistent resources to unauthorized callers except where a deliberate, safe denial response is required.

Clients—including the web portal, Foundry, imports and any future Discord integration—never determine their own authorization. PostgreSQL constraints preserve grant integrity, while the application query and command layers calculate and enforce effective access. Database row-level security may be added as defense in depth later, but it does not replace the application-level perspective and knowledge rules.

**Steps 1-5 and 7 delivered by Phase 10 workstream 2** (`src/dnd_ai/domain/access.py`, no migration — schema-only, built on revision 080). `resolve_user_by_external_identity()` resolves step 1; `resolve_access_context()` resolves steps 2-5 and 7 into one `AccessContext`, whose `has_capability()` combines role- and character-relationship-derived baseline capabilities with active direct/access-group resource grants, an explicit `deny` always overriding an `allow` at the same resource target (§19.6). Deliberately out of scope for this workstream, left for the query/command/API workstreams that actually have the context to do them correctly: step 6 (party/public knowledge-derived access — depends on the knowledge domain's own visibility rules, §14, and a selected character perspective the resolver itself doesn't have), step 8 (row/field/search/AI-context filtering — what callers do *with* an `AccessContext`, not part of resolving one), and step 9 (auditing sensitive reads — only the caller knows which read was sensitive; this module is called on every query and command, so it is the wrong layer to decide that). Covered by `tests/database/test_access_resolution.py` against the real `security.*` schema.

**Timeline scope (step 3).** `campaign.campaigns.timeline_id` is single-valued and non-nullable — one campaign resolves access against exactly one timeline, its own. A caller-supplied `timeline_id` is accepted only when it equals the campaign's own; any other value — a different same-world timeline, a branch/descendant of the campaign's own timeline, or a timeline from a different world — raises `UnauthorizedTimelineError` rather than being used to select timeline-scoped character-relationship capabilities or resource grants. §19.2 and §19.6 place *narrower* timeline scoping on the individual relationship/grant row that needs it, not on substituting a different timeline for the whole resolution; nothing in the domain model gives one campaign more than one timeline to resolve access against. `UnauthorizedTimelineError` is a `dnd_ai.domain.errors.DomainAuthorizationError` — its constructor argument (with the supplied/campaign/canonical timeline IDs) is available via `str(self)` for local/interactive debugging only, never for a response *or* a log line; `dnd_ai.api.errors`' `SafeMessageError` handler maps every instance, automatically and regardless of which endpoint raised it, to a fixed 404 and logs only the exception's class, status/error code, correlation ID, and route template (see that module's `_log_error`). Covered by `tests/database/test_access_resolution.py`'s "Timeline scope" section, including a same-world non-branch timeline, a branch of the campaign's own timeline, and a different-world timeline, plus `tests/unit/test_api_app.py`'s API-level disclosure and logging regressions.

#### 19.8 Durable command idempotency

##### `security.idempotent_requests`

Delivered by revision 082 (Phase 10 workstream 6 correction pass), first used by `dnd_ai.api.items`. Backs `dnd_ai.api.deps.get_idempotency_key`'s `Idempotency-Key` request header with durable, PostgreSQL-backed deduplication — closing the PLAN.md §25 "retries do not duplicate effects" gap the item command endpoints originally left open.

Key columns:

- `idempotent_request_id UUID PK`
- `actor_user_id UUID FK -> security.users, ON DELETE CASCADE`
- `campaign_id UUID FK -> campaign.campaigns, ON DELETE CASCADE`
- `idempotency_key TEXT` — the client-supplied header value, bounded and character-restricted before it reaches this column
- `request_fingerprint TEXT` — sha256 of the canonical (command name, path parameters, request body) tuple
- `correlation_id UUID NULL`
- `response_status_code SMALLINT NULL`, `response_body JSONB NULL`, `completed_at TIMESTAMPTZ NULL` — all three NULL until the command completes, all three set together (`ck_idempotent_requests_completion_consistent`)

Unique on `(actor_user_id, campaign_id, idempotency_key)`. A row is reserved (`INSERT ... ON CONFLICT DO NOTHING`) before the command runs and completed with its response before the same transaction commits — see `dnd_ai.api.idempotency`'s module docstring for the full concurrency argument (the unique index itself, not application-level locking, serializes concurrent requests for the same key) and for why a rolled-back or failed command never permanently consumes a key.

Deliberately **not** under `audit`: `audit.*` tables are append-only to normal application roles (conventions §24.2) and outlive the records they describe, by design. This table is the opposite on both counts — reserved, updated once, and disposable cache state, not history — so it carries real `ON DELETE CASCADE` foreign keys rather than `audit.change_log`'s deliberately unconstrained columns.

##### `security.campaign_creation_reservations`

Delivered by revision 088 (Phase 10 workstream 33). `POST /campaigns` (`dnd_ai.commands.campaigns.create_campaign`) has no existing `campaign_id` to scope a `security.idempotent_requests` row against — it is the one write in this codebase that *creates* the campaign a reservation would otherwise be keyed to, so that table's `NOT NULL campaign_id` foreign key structurally excludes it. This is a dedicated pre-campaign counterpart, not a nullable-column extension of `idempotent_requests`: a nullable column inside a `UNIQUE` constraint does not enforce uniqueness across multiple `NULL`s, so weakening that column would have silently stopped deduplicating every other command's reservations without protecting this one either.

Migration 087's single-use `security.timeline_bootstrap_grants` entitlement stops a *different* user from claiming the first campaign, but on its own did nothing to stop the successful creator's own dropped-response retry: seeing an already-used timeline, the retry passes the ordinary timeline-*reuse* check via the `access.manage` it just received as the new campaign's own owner, and mints a second active campaign, membership, owner role assignment, and audit row for what the caller believes is one logical request. `security.campaign_creation_reservations` closes that gap.

Key columns:

- `campaign_creation_reservation_id UUID PK`
- `actor_user_id UUID FK -> security.users, ON DELETE CASCADE`
- `idempotency_key TEXT` — same bounded, character-restricted header value as `idempotent_requests.idempotency_key`
- `request_fingerprint TEXT` — sha256 of the canonical (`"create_campaign"`, request body) tuple; no path parameters exist for this route, unlike every other command endpoint's fingerprint
- `correlation_id UUID NULL`
- `response_status_code SMALLINT NULL`, `response_body JSONB NULL`, `created_campaign_id UUID NULL FK -> campaign.campaigns, ON DELETE SET NULL`, `completed_at TIMESTAMPTZ NULL` — all four NULL until `create_campaign` actually succeeds, all four set together (`ck_campaign_creation_reservations_completion_consistent`)

Unique on `(actor_user_id, idempotency_key)` alone — no `campaign_id` column (none exists at reservation time) and no `command_name` column (exactly one command ever reserves a row here; the command name is still baked into the stored fingerprint for parity with `idempotent_requests`' own shape). `created_campaign_id` is stored as a real column, not left buried inside `response_body`, so the campaign a reservation produced can be queried directly. Reservation/replay/completion behavior mirrors `idempotent_requests` exactly — see `dnd_ai.api.idempotency`'s module docstring ("Pre-campaign idempotency") for the shared concurrency argument and for why a rolled-back or failed `create_campaign` attempt never permanently consumes the key.

### Audit

- `audit.change_log`
- `audit.change_actions` — lookup for `change_log.change_action_id` (create, update, archive, delete, …)
- `audit.state_transitions`
- `audit.approval_history`
- `audit.validation_failures`
- `audit.agent_activity`

Security-sensitive audit records identify the authenticated user or service account, campaign membership, selected character perspective when applicable, effective capability, authorization source (role, relationship, group, direct grant or owner rule), target resource, action, outcome, request correlation ID and timestamp. Grant, role, group, invitation, membership and identity-link changes are always audited. Read auditing may be limited to sensitive categories and summarized batches to avoid turning ordinary page loads into an unbounded log stream, but GM-only facts, access previews, exports and AI-context assembly remain traceable.

### Integration

- `integration.external_systems`
- `integration.external_identifiers`
- `integration.sync_jobs`
- `integration.sync_state`
- `integration.delivery_attempts`

External IDs must never replace internal UUID identity.

`integration.external_systems.system_key_hash` (migration 089, Phase 11 workstream 2) holds the sha256 hash of a Foundry-adapter system-level credential — minted by `dnd_ai.commands.integration.issue_foundry_system_key`, verified during authentication by `dnd_ai.domain.access.resolve_foundry_system_principal`, which resolves a full `AuthenticatedPrincipal` (carrying the authenticated `external_system_id`/`world_id`, not just a bare `user_id` — see that dataclass's own docstring for why, following a Phase 11 security correction) rather than a `user_id` alone. `NULL` until a key is issued; issuing again overwrites it in place (rotation, immediately invalidating the prior key), matching `security.campaign_invitations.invitation_token_hash`'s existing "store only a hash" shape rather than a new table. `system_key_principal_user_id` (migration 092, a second, more severe Phase 11 workstream 2 correction — a Critical credential-impersonation defect the first correction pass above did not touch) is bound to that same row *atomically with issuance*: the one platform user this credential authenticates as, resolved once and stored, never re-derived from anything a caller supplies per request. `NULL` (cannot authenticate at all) until bound, or if the bound user is later deleted. See §19.1's `security.external_identities` entry for the companion identity mapping (`foundry:<external_system_id>` issuer) `issue_foundry_system_key` resolves this from, and `foundry-module/README.md`'s "Trust boundary" section for the full defect this closes and the client-side half of the fix (the credential moved from a Foundry world-scoped setting to a client-scoped one).

`audit.change_log.acting_external_system_id` (migration 091, Phase 11 workstream 2 security correction) records which `integration.external_systems` row authenticated a change made through a delegated `FoundrySystem` credential, set alongside (never instead of) `actor_user_id` — distinct from `actor_service`, which is documented as set *instead of* `actor_user_id` for an actor with no linked platform user at all. `NULL` for every OIDC-authenticated change. `acting_foundry_actor_id` (migration 092) is its sibling for the client-claimed, server-unverified Foundry actor id (`X-Foundry-Actor-Id`, renamed from `X-Foundry-User-Id`) — recorded as free text purely for operator visibility, never consulted by `resolve_foundry_system_principal` or any other authorization logic; `actor_user_id` is resolved entirely from `system_key_principal_user_id` above, regardless of what this header claims.

## 20. Import staging

Primary tables:

- `import.import_jobs`
- `import.import_sources`
- `import.staged_entities`
- `import.staged_relationships`
- `import.staged_events`
- `import.staged_knowledge`
- `import.entity_matches`
- `import.validation_results`
- `import.promotion_batches`

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

Promotion from staging must use the same entity creation and approval pathways as manually authored data. Imported text must not directly create canon without review.

## 21. Delete and archival rules

- Canonical entities are normally archived, not physically deleted.
- Child subtype rows use `ON DELETE CASCADE` from the base entity only for controlled administrative deletion.
- Timeline state is closed through effective-end fields, not overwritten without history.
- Events, audit records and approved provenance are immutable except through explicit correction workflows.
- Test fixtures may use destructive cleanup; production domain operations may not.

## 22. Required database invariants

1. Every subtype row has a matching base entity.
2. Every base entity requiring a subtype has exactly one valid subtype chain.
3. Entity and subtype world ownership agree.
4. Timeline state references entities from the timeline's world.
5. Events cannot affect entities from unrelated worlds.
6. One current typed state row exists per timeline and target.
7. Timeline branches cannot inherit parent history after their branch point.
8. Accepted AI proposals produce standard events and audit records.
9. Quest objective transitions follow allowed state transitions.
10. Knowledge discovery does not mutate objective truth.
11. External integration records cannot become authoritative identity.
12. Imported records cannot bypass review and promotion.
13. A campaign membership joins exactly one user to one campaign and receives only roles valid for that campaign.
14. Character relationships, access groups and resource grants cannot cross their campaign's world or applicable timeline.
15. Every resource grant has exactly one grantee and one database-enforced typed resource target.
16. Revoked, suspended or expired memberships, role assignments, group memberships, character relationships and grants confer no access.
17. User authorization never creates or alters in-world knowledge, and in-world knowledge is exposed only through an authorized viewing perspective.
18. Canonical queries, search, counts, relationship traversal and AI context exclude resources the requester is not allowed to discover.
19. Every active campaign retains at least one membership authorized to manage campaign ownership and access. Enforced at the database level by `security.assert_campaign_retains_access_manager()`, seven deferred constraint triggers, and a lookup-code-renaming guard the invariant's hardcoded comparisons depend on (revision 080) — see §19's delivered-by note.

## 23. Dependency order

1. `core`, the initial identity/security foundation and database conventions.
2. Worlds, entity types, entities, sources, names and statuses.
3. Timelines, campaigns, parties and sessions.
4. Rulesets and shared characters.
5. Locations, dungeons and typed location state.
6. Interactions, checks, events and event effects.
7. Quests, objectives and progression state.
8. Knowledge and discovery.
9. Organizations, relationships and items.
10. Phase 10 application security: external identities, campaign-scoped membership roles, capabilities, semantic user-character relationships, access groups, the typed resource-grant subset required by the vertical slice, and authorization audit support.
11. AI proposals and approval flows.
12. Portal/import resource targets, integration, audit hardening and import staging.

This is the intended dependency order, not a strict phase-to-section mapping — `docs/PLAN.md` §23 is authoritative for what each numbered phase actually delivers and in what order; consult it before starting a phase.

## 24. Acceptance scenario

The database model is sufficient for the first vertical slice when it can represent and query all of the following atomically and historically:

- A party enters a dungeon area.
- Character locations change on one timeline.
- A hidden feature exists before the party knows about it.
- A successful check reveals that feature.
- A player interaction changes a trap, door or pylon state.
- An event records the cause.
- A quest objective advances from the resulting event.
- An NPC learns or reacts to the change.
- Another campaign on the same timeline sees the changed dungeon.
- A campaign on a branch created before the event sees the original state.
- One authenticated user can be a GM in one campaign, a player controlling multiple characters in another, and an observer in a third.
- Several users can share access to one character, while each user retains an independently revocable relationship and capability set.
- Two users requesting the same fact receive different results when their selected characters, campaign roles or explicit grants differ.
- A GM can inspect canon without causing any GM-controlled character to know it.
- Revoking a membership, character relationship, group membership or direct grant removes its access path without deleting the user, character, fact or audit history.
- An unauthorized user cannot infer a protected fact or record through identifiers, search matches, counts, relationship edges, summaries or AI-generated responses.

## 25. Schema reconciliation decisions

This document and `docs/PLAN.md` had drifted independently: this document's per-domain "primary tables" lists were a compressed sketch, while PLAN.md's per-domain implementation sections had grown more detailed prose covering additional tables neither document cross-referenced. This section records the merge and the judgment calls it required, so a future pass can revisit them if they turn out wrong rather than rediscovering the drift from scratch.

**Tables added that already existed in migrations but were undocumented here** (Phases 1–3 built them; this document simply hadn't caught up): `audit.change_actions`, `core.calendars`, `core.calendar_months`, `core.world_time_precisions`, `core.world_times`, `core.name_types`, `core.source_types`. These are facts, not judgment calls — §5.6 and the audit/security section above now describe their actual shape.

**Tables added from PLAN.md with no naming conflict** (genuinely new to this document, not a rename of something already here): `rules.creature_types`; `rules.resource_definitions`, `rules.species`, `rules.world_rulesets` (these three were already present in this document but missing from PLAN.md — PLAN.md should be updated to mention them); `character.character_descriptions`, `character.character_languages`, `character.character_movements`, `character.character_senses`, `character.character_prepared_spells`, `character.character_religious_affiliations`; `character.npc_routine_steps`, `character.npc_boundaries`; `world.relationship_types`, `world.religions`, `world.religious_organizations`; `knowledge.expertise_domains`; `interaction.external_messages`; `ai.context_snapshots`; the entire encounters/combat domain (`narrative.encounters`, `narrative.encounter_participants`, `narrative.encounter_rounds`, `narrative.encounter_turns`, `interaction.combat_actions`) — this document previously had no encounter model at all, now §13.

**Naming or schema conflicts resolved** (the same real concept named or scoped differently in each document — one name was chosen as canonical; PLAN.md should be updated to match):

- `audit.approvals` (this document) vs. `audit.approval_history` (PLAN.md) → kept **`audit.approval_history`**, matching the `_log`/`_history` naming pattern already used by its sibling `audit.change_log`.
- `import.promotion_batches` (this document) vs. `import.approval_batches` (PLAN.md) → kept **`import.promotion_batches`** — this document's own import-flow prose already uses "promotion" as the operative verb for staging → canonical.
- `character.npc_emotional_state` (PLAN.md, under `character` schema) vs. `campaign.npc_emotional_state` (this document, under `campaign` schema) → kept **`campaign.npc_emotional_state`**. This document's own §7.2 text ("current mood and trust belong to timeline state") already argued for campaign-schema placement; PLAN.md's schema tag looks like the error.
- `character.character_classes` (PLAN.md) vs. `character.character_class_levels` (this document) → kept **`character.character_class_levels`**, consistent with `character_ability_scores` naming a scored instance rather than the bare concept.

**Judgment calls that are genuinely uncertain** and should be revisited when the owning phase is actually implemented, not assumed correct from this pass alone:

- `campaign.character_inventory` (PLAN.md) is documented in §17 as a character-centric read index over `campaign.item_ownership` / `campaign.inventory_entries` (this document's existing, more granular item-state split). This is a reasonable reconciliation, but it was not validated against any actual query pattern — Phase 9, which owns items, should confirm whether a separate index table is actually warranted or whether a view/query suffices.
- `campaign.knowledge_discoveries` (PLAN.md, `campaign` schema) was treated as the same concept as `knowledge.party_discoveries` (this document, `knowledge` schema already present) — kept **`knowledge.party_discoveries`** per this document's own schema-responsibility table (§3: discoveries belong to `knowledge`). `campaign.party_knowledge` (PLAN.md) was kept as a **separate**, additional table (§17) for the current-effective-view side, distinct from the discovery log. **Confirmed at Phase 7 time** (revision 074): the split is real, not two names for one table — `knowledge.party_discoveries` has no belief/confidence/interpretation columns to diverge from canonical truth with; `campaign.party_knowledge` is exactly that, and a Phase 7 review found the original exit-criterion test had not actually exercised it (see §14/§15 above and PHASE7_VERIFICATION.md).
- `campaign.character_location_history` (PLAN.md) is listed in §17 but its ownership is deferred to Phase 5 (locations) rather than built alongside the other Phase 4 character-state tables, since it cannot reference anything before `world.locations` exists. **Confirmed at Phase 5 time** (revision 042): built as the sole source of truth for both history and current location, per §17's updated entry.

## 26. Location, dungeon, and knowledge implementation decisions

Phase 5 ("Locations and dungeon play") surfaced one real drift between PLAN.md's Phase 5 deliverable list and this document's own implementation order (§23), plus several scoping decisions made while building against it. Recorded here so a future pass can revisit them rather than rediscovering the reasoning from scratch — same purpose as §25.

**The "discovery records" drift.** PLAN.md's Phase 5 deliverables name "discovery records" and its exit criteria require "hidden connections remain distinct from party knowledge," but this document's own implementation order (§23) places "Knowledge and discovery" at item 8 — after locations (item 5), interactions/events (item 6), and quests (item 7) — and the documented shape of `knowledge.party_discoveries` (§15) ties it to `knowledge.knowledge_items`, a Phase 7 concept. Discussed with the user rather than resolved unilaterally; the chosen resolution was to pull the minimum slice of the knowledge domain forward into Phase 5 (revision 041) — `knowledge.knowledge_items`, `knowledge.entity_knowledge`, `knowledge.party_discoveries`, plus the two lookups they need — using their documented shape rather than inventing a smaller, Phase-5-only table that Phase 7 would need to reconcile or replace later. `knowledge.knowledge_versions`, `information_transfers`, `expertise_domains`/`character_expertise`, and `public_knowledge` remain genuinely Phase 7's job; nothing in Phase 5's exit criteria needed them. §15's table list above records exactly which three tables exist now versus which four remain deferred.

**Simplified knowledge-item subjects.** DOMAIN_MODEL.md §15.1 describes a knowledge item's subject as plural ("subject entities"), implying a junction table. Revision 041 instead adds a single nullable typed reference directly on `knowledge.knowledge_items` (`subject_entity_id` for the common entity case — NPCs, locations, organizations — plus one column each for the four non-entity dungeon-domain targets, since connections/features/hazards/interactables are not `core.entities` rows). At most one is set. This was sufficient for Phase 5's dungeon-discovery use case (one knowledge item, one concealed thing) and avoids building a junction table against requirements Phase 7 hasn't specified yet. Phase 7 should promote this to a real `knowledge.knowledge_item_subjects` table if a knowledge item genuinely needs more than one subject — a multi-party rumor about several NPCs, for instance.

**`world.area_spawn_definitions` deliberately not built.** Named in both PLAN.md §9.2 and this document's own §9.2 (prior revision), but no creature-instance or stat-block model exists anywhere in this schema — `rules.creature_types` is a bare classification lookup, not a stat block — and Phase 9 (encounters) is the natural first consumer. Building it now would either reference nothing meaningful or invent encounter-generation scope ahead of the phase that needs it. None of Phase 5's three exit criteria required it. PLAN.md §9.2 should be corrected to match.

**`world.settlements` and `world.buildings` are deliberately minimal**, matching the same "build the marker row, defer the apparatus" pattern Phase 4 used for `character.npcs`: settlements carry `population` only (government and factions are Phase 8 organization concepts; economy is an intentionally deferred domain per DOMAIN_MODEL.md §27; districts are plain child locations via `parent_location_id`; control/damage state is timeline state); buildings carry a free-text `building_use` (no documented controlled vocabulary exists, same reasoning as Phase 4's `character_senses.sense_type`). Six DOMAIN_MODEL.md §9.1 location "subtypes" with no structured data of their own (plane, continent, nation, region, district, geographic_feature) were registered as plain `core.entity_types` leaves under `location` rather than given their own CTI tables — the same pattern `character.characters` uses for types needing no dedicated apparatus.

### First exit review corrections (2026-08-03)

A Phase 5 exit review — before the branch was merged — found seven integrity, completeness, and documentation gaps the original schema's own exit criteria didn't happen to exercise, the same shape of review Phase 4 went through (see PHASE4_VERIFICATION.md's corrections/closeout passes). Five forward-only revisions (043–047) closed them, none touching the already-applied revisions 038–042; full account in PHASE5_VERIFICATION.md.

| Revision | Closes |
|---|---|
| `043_character_location_temporal` | `campaign.character_location_history` only had same-world checks and a partial-unique-index shortcut, not the full ADR 0010 interval contract `campaign.party_memberships` already implements. Added a required `arrived_at_world_time_id`, a derived `location_period INT8RANGE`, and `EXCLUDE USING gist (timeline_id, character_id, location_period WITH &&)` — the exclusion constraint fully subsumes the old "one open row" partial index, since two unbounded-upper ranges for the same (timeline, character) always overlap. Both world-time endpoints' `ON DELETE` action changed from `SET NULL` to `RESTRICT`, matching `party_memberships`' endpoints — `SET NULL` on a now-`NOT NULL` column can't fire cleanly, and on the nullable end it would silently reopen a closed period without re-deriving the range. |
| `044_dungeon_mutation_safety` | Revision 039's dungeon-structure rules validated only at insert time (or, for dungeon areas, only when `dungeon_areas` itself changed). Made `world.area_connections.from_dungeon_area_id`/`to_dungeon_area_id` and `world.area_features/area_hazards/area_interactables.dungeon_area_id` immutable via the existing `core.enforce_immutable_columns()` (revision 030) rather than a new mechanism; added a cycle-of-any-length guard and a dungeon-parent revalidation trigger to `world.locations`, closing the case where `parent_location_id` changes directly rather than through `world.dungeon_areas`. |
| `045_knowledge_timestamp_world` | `knowledge.entity_knowledge.learned_at_world_time_id` and `knowledge.party_discoveries.discovered_at_world_time_id` were nullable `core.world_times` references revision 041's world-agreement triggers never checked. Extended (`CREATE OR REPLACE`) both existing functions rather than adding new ones — same one-function-owns-the-contract shape revision 041 and revision 009 both already use. |
| `046_dungeon_state_updated_at` | The five `campaign.*_state` tables from revision 040 each declared an `updated_at` column but revision 040 never attached `core.set_updated_at()` to any of them — unlike revision 040's own three status lookups, which do have it. |
| `047_realm_conditional_routes` | Two completeness gaps: the `realm` location kind DOMAIN_MODEL.md §9.1 lists (revision 038 registered the other six no-subtype-table kinds but omitted this one by oversight), and the descriptive half of conditional routes PLAN.md §9.2 names (`is_conditional`/`condition_description` on `world.area_connections` — evaluating the condition is deferred to Phase 6, plus Phase 7 for quest-gated conditions specifically (§15's distinction below applies the same way here), recorded explicitly in PLAN.md rather than left silent). |

**Judgment call carried forward, not fully resolved:** the knowledge-domain Phase 5/Phase 7 boundary (temporal validity of knowledge items) is now documented explicitly in §15 rather than left implicit, but the gap was not closed — it remains genuinely Phase 7's job. Real discovery source/provenance is a separate gap with a different, single owner: Phase 6 (see §15's revised wording — `interaction.interactions`/`narrative.events` are Phase 6 deliverables, so replacing the free-text placeholder can happen as soon as both exist, with no dependency on Phase 7's quest or knowledge-versioning work).

### Second exit review corrections (2026-08-03)

A second Phase 5 exit review — also before the branch was merged — found four further integrity gaps a purely sequential, single-transaction test suite hadn't exercised (parent-side type mutation, a genuine concurrent write race, an incompletely-tightened NOT NULL, and an under-constrained pair of columns), plus documentation drift including the Phase 6/7 ambiguity resolved just above. Revisions 048–051 addressed the ordinary tested cases; a post-merge review then found each of the four had a concurrency, recursion, populated-upgrade, or whitespace edge case still open, closed by the third exit review corrections below.

| Revision | Closes |
|---|---|
| `048_entity_type_change_protect` | `core.enforce_entity_subtype()` (revision 004) only validates from the subtype side (INSERT/UPDATE on e.g. `world.dungeons`); nothing stopped `UPDATE core.entities SET entity_type_id = ...` from retyping an entity out from under an existing subtype row. Added `core.entity_types.required_subtype_pk_column` (paired explicitly with `required_subtype_table`, not derived from it) and `core.enforce_entity_type_change()`, a generic `BEFORE UPDATE OF entity_type_id` trigger on `core.entities` that rejects a type change stranding any subtype row still present — protects every registered subtype (character/npc/player_character, location/settlement/building/dungeon/dungeon_area, knowledge_item), not just dungeons. A second, dungeon-specific trigger (`world.enforce_dungeon_type_change_preserves_areas()`) closes the deeper case: `world.dungeons` rows are deletable (conventions §7.5), and once deleted the generic trigger has nothing left to check, but `world.dungeon_areas` children may still depend on the parent staying dungeon-typed — this trigger checks for those children directly. |
| `049_location_containment_lock` | Revision 044's cycle check read the containment ancestry with no lock, so two concurrent transactions (A placed under B; B placed under A, started from the same acyclic snapshot) could each observe no cycle and both commit. `world.enforce_location_no_cycle()` now takes a per-world `pg_advisory_xact_lock`, closing that tested write skew. (Completed by revision 054 below — its recursive walk merely stopped at depth 10,000 until then, silently truncating rather than raising.) |
| `050_char_location_period_notnull` | `campaign.character_location_history.location_period` (revision 043) was never declared `NOT NULL`, unlike `campaign.party_memberships.effective_period`. Revision 050 asserts that no NULL periods exist and then sets `NOT NULL`. (Depends on revision 052 below, spliced immediately before it, for the actual backfill of rows predating revision 043's derivation trigger.) |
| `051_conditional_route_semantics` | Revision 047's `is_conditional`/`condition_description` had no constraint tying them together. The added CHECK rejects NULL and ordinary-space-only descriptions for conditional routes and requires unconditional routes to have no description. (Completed by revision 055 below — it trimmed only `' '` and still accepted tab/newline-only values until then.) |

**Judgment call:** `core.enforce_entity_type_change()` is deliberately not a blanket immutability lock on `entity_type_id` the way `core.enforce_immutable_columns()` treats `world_id` — a type correction before any subtype row exists remains legitimate, since nothing depends on it yet. Only a change that would strand an *existing* subtype row (or, for dungeons specifically, existing dungeon-area children) is rejected.

### Third exit review corrections (2026-08-03)

A post-merge review — the first to run against `main` rather than an open PR — found that each of revisions 049, 050, and 051 had closed only its sequential/single-transaction/always-fresh-database case, plus one incomplete fix and documentation drift. Three forward revisions (053–055) plus one explicitly documented migration-history exception (revision 052 spliced before 050, requiring 050's `down_revision` to change) addressed those findings. A fourth review found revision 053 still left dungeon-area subtype creation racy against direct changes to the child location's `parent_location_id`, and its concurrency tests did not prove that the original waiting statements resume and revalidate; revision 056 closed both — see [Fourth exit review corrections](#fourth-exit-review-corrections-2026-08-03) below.

| Revision | Closes |
|---|---|
| `052_char_location_backfill` | Spliced into history between 049 and 050 — revision 050's `down_revision` repointed here, a narrowly-scoped, explicitly recorded exception to the forward-only policy (justified in the revision's own docstring: revision 050 has never run against a populated database in any deployed environment, and its own DDL is unchanged). Backfills `location_period` for any pre-revision-043 row by re-firing revision 043's own derivation trigger via a no-op `UPDATE`, reusing its validation rather than duplicating it. |
| `053_entity_subtype_change_lock` | `core.enforce_entity_subtype()` and `core.enforce_entity_type_change()`/`world.enforce_dungeon_type_change_preserves_areas()` each read the other side of the subtype-consistency relationship with no shared lock — the same write-skew shape revision 049 fixed for containment. `CREATE OR REPLACE` on five subtype/dungeon-area-related functions adds per-entity `pg_advisory_xact_lock` protection for generic subtype-vs-retype and parent-dungeon-vs-retype writes. (Completed by revision 056 below — it did not yet serialize inserting `world.dungeon_areas` for child location L against concurrently changing L's `world.locations.parent_location_id`.) |
| `054_location_cycle_detection` | Adopts PostgreSQL's native `CYCLE location_id SET is_cycle USING path` clause for real repeated-node detection, independent of whether the row being updated is part of the cycle. The depth bound remains as a resource cap but now raises a clear error when reached instead of silently truncating. |
| `055_conditional_route_whitespace` | Replaces `trim(both ' ' from condition_description)` with `condition_description ~ '\S'` (contains at least one non-whitespace character), rejecting tab/newline/carriage-return/mixed-whitespace-only descriptions the same way a space-only one already was. |

The third pass correctly closed the populated-upgrade, cycle-detection, and whitespace cases and part of the entity/subtype concurrency case. See [PHASE5_VERIFICATION.md § Third exit review corrections](../PHASE5_VERIFICATION.md#third-exit-review-corrections-2026-08-03) for the full account, including the two-connection tests' prior limitation and the populated-upgrade fixtures.

### Fourth exit review corrections (2026-08-03)

A fourth review, of merged PR #6, found revision 053's locking incomplete on one path and its concurrency tests short of the standard the review required.

| Revision | Closes |
|---|---|
| `056_dungeon_area_child_lock` | `world.enforce_dungeon_area_parent_dungeon()` locked only the proposed parent dungeon before checking its type, never the child location whose `parent_location_id` it had just read; `world.enforce_dungeon_area_parent_dungeon_on_update()` checked for an existing `world.dungeon_areas` row before acquiring any lock, so a still-uncommitted concurrent insert was invisible to it. `CREATE OR REPLACE` on both functions adds a `pg_advisory_xact_lock` keyed on the child location, acquired first (in a distinct namespace from revision 053's entity-subtype lock, so the two never collide), with each function's existing read moved to after the lock. Both functions that also need the revision-053 parent-dungeon lock acquire the new child lock strictly before it, giving a single consistent acquisition order across the pair. |

The fourth pass also rewrote the three revision-053 concurrency tests and added two more (one per starting order of the child-lock race) to prove the *original* waiting statement resumes and revalidates against the newly committed state, rather than proving only that a `lock_timeout`-driven copy fails and a fresh retry is rejected — using a real background thread plus a `pg_stat_activity` poll for a genuine lock wait, the same pattern the former `test_phase4_remaining_issues.py` (now redistributed; see `test_world_ruleset_dependency_and_concurrency.py`) established for a `FOR SHARE` row lock. This pass was pushed directly to `main` without a pull request, then verified by integrated `main` GitHub Actions run [`30874081442`](https://github.com/NemesisGhost/dnd_ai/actions/runs/30874081442). See [PHASE5_VERIFICATION.md § Fourth exit review corrections](../PHASE5_VERIFICATION.md#fourth-exit-review-corrections-2026-08-03) for the full account.

### Fifth exit review corrections (2026-08-03)

A fifth review re-checked the fourth pass's five resumed-waiter tests against the acceptance criteria in `PHASE5_REMAINING_ISSUES.md` line by line. Two criteria were not met: no test queried final committed state from an independent connection, and the shared blocking-thread helper had no cleanup path if a resumption assertion failed. No schema or migration change was needed — revision 056 and the revision-053 trigger functions were reviewed again and found correct. The fifth pass added the independent final-state queries and replaced the unmanaged helper with `_BackgroundStatement`, which attempts to terminate a still-alive backend before a bounded join. PR #10 passed all 1,093 tests at its first and final reviewed heads. A sixth review found the helper was still best-effort — it did not verify backend termination or the final join, could lack a backend PID, and had no forced-cleanup regression test — and added explicit checks plus three focused regression tests against a plain advisory lock. A seventh review found that the revised helper still did not contain all failure paths: startup timeout could raise while connection acquisition remained alive, and failed termination/cancellation could raise or return control while the worker remained alive; the two fault-injection tests demonstrated the latter by manually terminating the real backend after leaving the context manager. An eighth pass closed both gaps — the worker's connection acquisition is now bounded by a driver-level `connect_timeout` shorter than every join/poll deadline above it, `__enter__` verifies the thread stopped before raising, and all three regression tests' safety-net cleanup now runs unconditionally in `finally` — with no schema or migration change needed. A ninth review then found that fix still not airtight: ownership was established by racing a poll/join against the worker thread's own startup rather than synchronously before it existed, and the only fallback for failed PostgreSQL signals was to report the failure rather than actually stop the worker through a mechanism the helper itself controls. A ninth pass redesigned `_BackgroundStatement` to establish connection/backend ownership synchronously before any worker thread is created, and added a layered fallback ending in a `lock_timeout` PostgreSQL itself enforces — again with no schema or migration change. A tenth review then found that even this could not deliver a literal no-survivor guarantee, since no Python thread can be unconditionally, forcibly stopped regardless of what it is blocked inside; a tenth pass replaced the worker thread with an independently terminable worker process, reclaimable via `terminate()`/`kill()` regardless of what it is doing, with `_force_stop()` ending in forcible process termination followed by an unconditional `pg_terminate_backend()` call — once more with no schema or migration change. See [PHASE5_VERIFICATION.md § Tenth exit review](../PHASE5_VERIFICATION.md#tenth-exit-review-findings-and-corrections-2026-08-04). An eleventh review then found that process-based redesign could still report false success and silently discard cleanup failures — the worker outcome protocol and controller-side cleanup were hardened in response, confirmed by its own final documentation head's CI run [`30966346368`](https://github.com/NemesisGhost/dnd_ai/actions/runs/30966346368); see [PHASE5_VERIFICATION.md § Eleventh exit review](../PHASE5_VERIFICATION.md#eleventh-exit-review-worker-outcome-protocol-controller-cleanup-and-processipc-hardening-2026-08-04). A twelfth review then found the eleventh pass's own verification-tooling claim didn't hold up to its exit code, the worker outcome protocol still had a gap, `_worker_main`'s cleanup was not itself independently failure-safe, and its IPC redesign still relied on an abandonable thread — the verification tooling was fixed, the worker outcome protocol made total, and the IPC redesigned around `multiprocessing.Pipe`, confirmed by [PR #15](https://github.com/NemesisGhost/dnd_ai/pull/15)'s push-triggered GitHub Actions run [`30972855981`](https://github.com/NemesisGhost/dnd_ai/actions/runs/30972855981) for implementation commit `f3ed98a`; see [PHASE5_VERIFICATION.md § Twelfth exit review](../PHASE5_VERIFICATION.md#twelfth-exit-review-verification-tooling-correctness-worker-outcome-protocol-totality-and-pipe-based-ipc-2026-08-04). A thirteenth review of that same open PR's follow-up commit (`d0032dc`) then found the twelfth pass's own missing-outcome classification, backend verification, and `Process.start()` failure handling were themselves still incomplete — fixed by a thirteenth pass, confirmed by PR #15's push-triggered CI run [`30977657034`](https://github.com/NemesisGhost/dnd_ai/actions/runs/30977657034); see [PHASE5_VERIFICATION.md § Thirteenth exit review](../PHASE5_VERIFICATION.md#thirteenth-exit-review-accurate-missing-outcome-classification-universal-backend-verification-and-processstart-failure-ownership-2026-08-05). A fourteenth review of that same commit (`267ac1d`) then found the thirteenth pass's own forced-termination classification, partial-start cleanup, and regression-test safety net were themselves still incomplete — fixed by a fourteenth pass, verified locally (93 tests in `test_entity_type_change_protection.py`, 1,189 total); see [PHASE5_VERIFICATION.md § Fourteenth exit review](../PHASE5_VERIFICATION.md#fourteenth-exit-review-evidence-based-containment-classification-fully-guarded-cleanup-and-a-complete-independent-safety-net-2026-08-05). The production model remains complete; formal test-infrastructure/tooling closeout is complete pending PR #15's own final-head CI confirmation; [PHASE5_REMAINING_ISSUES.md](../PHASE5_REMAINING_ISSUES.md) reflects the same status.

## 27. Event and interaction implementation decisions

Phase 6 ("Events and interactions") is being delivered as a sequence of independently reviewable increments rather than one change, the same way Phase 5 was.

**Increment 1**: `narrative.events` and its five satellite tables (revision 057), `campaign.timelines.branch_event_id` (revision 058), `campaign.effective_events()` (revision 059), and `last_event_id` provenance on the five Phase-5 dungeon-domain state tables (revision 060).

**Increment 2**: the `interaction.*` domain (revision 061) and `narrative.event_causes.cause_interaction_id` (revision 062), closing increment 1's own placeholder now that `interaction.interactions` exists.

**Increment 3**: real source provenance for `knowledge.entity_knowledge`/`knowledge.party_discoveries` (revision 063), closing the last Phase 5 free-text placeholder — see §15.

**Increment 4**: conditional-route evaluation (revision 064) — structured check requirements on `world.area_connections`, `interaction.check_requests.target_id`, and `world.conditional_route_requirement_satisfied()` — see §9.2, §16.

**Increment 5**: `src/dnd_ai/commands` — the first application-layer code in this repository, per `SYSTEM_ARCHITECTURE.md` §5.3/§6. No schema change (no new migration); this increment is Python only. `record_event()` (the `RecordEvent` command, `docs/ENTITY_LIFECYCLE.md` §21), `perform_interaction()` (`PerformInteraction`), and `resolve_check()` (`ResolveCheck`) together give the first end-to-end path from a player action to an atomically-committed event and typed-state change, closing Phase 6's "first full exercise of rule 6" obligation and its "a player action can resolve into an event and atomic state changes" exit criterion. Increment 6 (encounters/combat) does not belong to this phase — `PLAN.md` §23 lists encounters under Phase 9, not Phase 6; the increment numbering here stops at 5.

**No command/service layer existed before increment 5.** Increment 1 proved the *schema* supports atomic event + typed-state commits with a hand-written multi-statement transaction, forced to fail partway through, leaving no partial write (`tests/database/test_event_state_atomicity.py`) — but `src/dnd_ai` had no `commands`, `services`, or API app at that point. Increment 5 is where `SYSTEM_ARCHITECTURE.md` §5–7's command/transaction-boundary design is actually implemented for the first time, and where the atomicity guarantee is re-proven through real application code rather than hand-written SQL (`tests/scenario/test_resolve_conditional_route_check.py`).

**Correction pass (revisions 065–068)**: a second, more critical exit review of the five-increment implementation found six production defects the first review's own verification loop missed, closed as four corrective migrations plus two application/test-only fixes — see `docs/PHASE6_VERIFICATION.md`'s "Correction Pass" section for the full account (what each defect was, how it was found, and every test added). In schema-diagram terms: `narrative.enforce_recorded_event_immutable()`/`enforce_recorded_event_entity_immutable()`/`enforce_recorded_event_child_immutable()` (065) make a recorded event and its append-only children genuinely immutable; `campaign.enforce_state_event_timeline()` (066) is now the single shared trigger every `last_event_id`-carrying table uses, including the three character-state tables named just above; `interaction.enforce_interaction_locked()` plus five per-table wrapper functions (067) make `interaction.actions`/`.targets`/`.check_requests`/`.check_results`/`.external_messages` append-only once their interaction leaves `initiated`; and `rules.enforce_world_ruleset_still_in_use()` (068) gained the two usage clauses revision 061 had already flagged as a known gap for `check_requests` and never flagged at all for `area_connections`.

**Second correction pass (revisions 069–070)**: that correction pass was opened as PR #16; a further review of the PR found three more production lifecycle gaps the two prior reviews both missed, closed as two corrective migrations plus a `resolve_check()` rewrite — see `docs/PHASE6_VERIFICATION.md`'s "Second Correction Pass" section for the full account. `narrative.enforce_recorded_event_not_deletable()` (069) is a `BEFORE DELETE` trigger on `narrative.events` rejecting deletion of any non-draft row; because `ON DELETE CASCADE` fires a referencing table's own `BEFORE DELETE` triggers, this single trigger also blocks deleting a recorded event by deleting its `core.entities` row, with no second trigger needed on `core.entities` itself. `interaction.enforce_interaction_status_irreversible()` (070) rejects any further change to `interaction.interactions.status` once it reaches `resolved`/`failed`/`cancelled` — closing the gap that let revision 067's append-only guard be bypassed by reverting the status first. `interaction.enforce_check_result_interaction_open()` (070) is a `BEFORE INSERT` trigger on `interaction.check_results` reusing revision 067's `enforce_interaction_locked()` helper unchanged, so a check result can only ever be recorded while its interaction is still `initiated` — the same rule 067 already applied to editing one, now applied to creating one. `src/dnd_ai/commands/interactions.py`'s `resolve_check()` was rewritten to lock the parent interaction (`SELECT ... FOR UPDATE`) and validate it is not already terminal before inserting a check result, and to track how many of the interaction's check_requests (across all of its actions) have a result, moving the interaction to `resolved` only once every one of them does — the multi-check completion contract §16 now describes, exercised by `tests/scenario/test_resolve_conditional_route_check.py::test_an_interaction_with_multiple_checks_stays_open_until_all_are_resolved` and already implicitly relied on by the pre-existing `test_two_concurrent_successful_checks_open_the_route_exactly_once` (an interaction with two check_requests on one action, which the new completion tracking now also handles correctly rather than by accident).

**Third correction pass (revision 071)**: the second correction pass above kept a multi-check interaction `initiated` until every check_request had a result — but `initiated` is the one status revision 067's `enforce_interaction_locked()` treats as unlocked, so a check resolved first (which may already have produced an immutable event, effect, consequence, and state change) left its own `check_requests`/`check_results` rows freely editable for as long as any other check on the interaction was still outstanding. **Fixed**: `_resolve_interaction()` now moves the interaction to the already-defined-but-previously-unused `resolving` status as soon as its first result lands, reaching `resolved` only on its last — a single-check interaction still goes straight from `initiated` to `resolved`, since its one result is simultaneously first and last. Revision 067's guard needed no change (it already rejects `UPDATE`/`DELETE` for any status other than `initiated`, `resolving` included); revision 070's `check_results` `INSERT` guard did — `interaction.enforce_interaction_accepting_check_results()` (071) is a narrower sibling of `enforce_interaction_locked()` accepting `initiated` or `resolving`, and `enforce_check_result_interaction_open()` was changed (`CREATE OR REPLACE`, same trigger) to call it instead. See `docs/PHASE6_VERIFICATION.md`'s "Third Correction Pass" section.

**Fourth correction pass (revision 072)**: the third correction pass introduced `resolving`, but only `resolve_check()` itself ever set it — a check result inserted by any other path would leave the interaction at `initiated`, which `enforce_interaction_locked()` treats as fully unlocked, reopening exactly the bypass `resolving` exists to close. Separately, nothing stopped *creating* a brand new `actions`/`targets`/`check_requests` row after resolution had begun, which is incoherent once `resolved` (supposed to mean every required check has already been answered) and would permanently strand an unanswerable request. **Fixed**: `interaction.advance_interaction_status_on_check_result()` is now an `AFTER INSERT` trigger on `check_results` itself — it locks the parent interaction, counts total versus answered check_requests across all of the interaction's actions, and sets `resolving` or `resolved` accordingly, atomically with the insert and regardless of caller. `resolve_check()`'s own separate status `UPDATE` became fully redundant and was removed. `interaction.enforce_actions_creatable()`/`enforce_targets_creatable()`/`enforce_check_requests_creatable()` are three new `BEFORE INSERT` triggers, each reusing `enforce_interaction_locked()` (revision 067) unchanged — the same "must still be `initiated`" rule now governs creating one of these rows, not only editing one. `check_results` and `external_messages` were deliberately left out: `check_results` already has its own, more permissive `initiated`-or-`resolving` insert guard, and `external_messages` carries no "required check" invariant to protect. The scenario test that used to prove terminal rejection by inserting a *new* check_request after resolution was replaced — that path no longer exists — with one that administratively cancels an interaction whose request was created beforehand, a realistic case revision 072 does not (and should not) prevent. See `docs/PHASE6_VERIFICATION.md`'s "Fourth Correction Pass" section.

**`narrative.events` reuses `core.enforce_entity_subtype()` unchanged.** No new generic-subtype-checking function was needed — the existing one (revision 004, generalized further by revision 048) already walks `core.entity_types.parent_entity_type_id` ancestry and checks `required_subtype_table`, exactly as it does for every other CTI subtype.

**`campaign.enforce_timeline_branch()` was extended, not duplicated.** Revision 058 adds branch_event_id validation via `CREATE OR REPLACE` on the existing revision-008 function rather than a second trigger on `campaign.timelines` — the same "one function owns the contract" shape revision 045 used when it extended the knowledge-domain world-agreement functions. The existing `tr_timelines_enforce_branch` trigger needed no change.

**`campaign.effective_events()` bounds each ancestor by its own child's branch point, not the target timeline's.** Climbing a multi-level branch chain (grandchild → child → parent), the correct cutoff for the *parent's* events is the point at which *child* branched off parent — not the point at which grandchild branched off child, even when that point is later in fictional chronology. A timeline never gains access to more of an ancestor's history than its own immediate parent ever inherited. `tests/scenario/test_branch_effective_history.py` builds exactly this three-level case (a child branch point later than the parent's own branch point from the grandparent) to prove the distinction — a single-level branch test cannot exercise it.

**`narrative.event_effects` reuses `knowledge.knowledge_items`' single-typed-target pattern.** `target_entity_id` plus one column per dungeon-domain non-entity target (`target_area_connection_id`/`_feature_id`/`_hazard_id`/`_interactable_id`), `CHECK (num_nonnulls(...) <= 1)` — the same shape Phase 5 revision 041 established for knowledge-item subjects, reused rather than redesigned for the same underlying problem (several possible non-entity target kinds, at most one set).

**Not built in increment 1, and why:**
- `narrative.events.corrected_by_event_id` / any correction-linkage column — `docs/ENTITY_LIFECYCLE.md` §15's `corrected` status exists as a value, but no Phase 6 exit criterion requires the linkage mechanism yet. Still not built as of the correction pass — the correction pass added `event_status` transition validation (recorded → voided/corrected) but not a linkage column, since no `CorrectEvent` command exists yet to populate it.
- `last_event_id` on `campaign.character_state`/`.character_conditions`/`.character_resources` — PLAN.md's Phase 6 first-time obligations name only the five dungeon-domain state tables explicitly; the character-state tables were an equally valid target for the same provenance column but were not named, and adding it was left to whichever later increment actually produces character-affecting events. Closed by the exit-review correction pass (revision 066) instead — see "Correction pass design decisions" below.

**Increment 2 design decisions:**

**`interaction.interactions` is not entity-rooted.** Unlike `narrative.events`, interactions have no independent canonical identity — no source, no canon status, nothing else references "the interaction" the way `branch_event_id` references "the event." They are high-volume log records, the same category `world.area_connections`/`area_features`/`area_hazards`/`area_interactables` already occupy (§9).

**`interaction.targets` and `interaction.check_requests` belong to `interaction.actions`, not `interaction.interactions` directly.** `docs/DOMAIN_MODEL.md` §16.3 ties a target to "an action" explicitly, and a check resolves whether a specific action succeeds — both are one level more granular than the mermaid diagram in an earlier draft of this section implied (now corrected above). `interaction.consequences` stays interaction-level, per §16.6's own wording ("a proposed or resolved outcome of an *interaction*").

**`interaction.check_requests` reuses `rules.ruleset_allowed_for_world()` (revision 035) rather than inventing new validation.** Same concurrency-safe `FOR SHARE`-locked allow-list check every other ruleset-scoped category (species, build, condition, resource, language) already uses. The insert-side check landed with this increment; `rules.enforce_world_ruleset_still_in_use()`'s reverse DELETE/UPDATE guard gained its matching `check_requests` usage clause later, in the exit-review correction pass (revision 068) — the same incremental pattern revision 037 followed for `character_languages`.

**Increment 3 design decisions:**

**The TEXT placeholders were dropped, not kept alongside their replacements.** `learned_source`/`discovery_method` are gone from `knowledge.entity_knowledge`/`knowledge.party_discoveries` entirely, replaced by `learned_via_interaction_id`/`learned_via_event_id` and `discovered_via_interaction_id`/`discovered_via_event_id` respectively (revision 063) — a stale free-text guess sitting next to a real reference would be a second, disagreeing source of truth. At most one of each pair is set; both `NULL` is legitimate (an unrecorded or administrative source, e.g. seeded starting knowledge), the same "explicit administrative source" carve-out rule 6 already allows for state changes generally.

**Each gets its own world-agreement trigger function** (`knowledge.enforce_entity_knowledge_source_world()`, `knowledge.enforce_party_discovery_source_world()`) rather than folding the check into the existing `enforce_entity_knowledge_world()`/`enforce_party_discovery_world()` functions from revision 041 — the existing functions check the *row's own* timeline/item/knower agreement (an INSERT-time concern that fires on every write); the new functions check an *optional* source reference only when one is set. Keeping them separate means the common no-source path never touches the added checks.

**Increment 4 design decisions:**

**No state-mutating trigger, by design.** The obvious "elegant" implementation — a trigger on `interaction.check_results` that flips `campaign.area_connection_state.connection_status_id` to open the moment a matching check succeeds — was considered and rejected: rule 6 requires state changes to go through a causal event committed atomically by the command layer, and a bare trigger effect has no event to attach to. `world.conditional_route_requirement_satisfied()` is deliberately read-only; the actual state transition is increment 5's job once a command exists to pair it with an event.

**`interaction.check_requests.target_id` is a general modeling fix, not a conditional-route-only feature.** Revision 061 gave an action possibly-several targets and possibly-several check requests with no way to say which check resolves which target. Closing that gap benefits any check that needs a specific target (an attack against a specific enemy, a lock-pick attempt against a specific interactable), not just conditional routes — conditional-route evaluation is simply the first consumer that needed it enough to force the fix.

**The structured requirement lives directly on `world.area_connections`, not a separate table.** One route has at most one check requirement in this model (mirroring `interaction.check_requests`' own single ability-or-skill shape), so a satellite table would add a join for no expressiveness gained — consistent with how `campaign.timelines.branch_event_id` and the Phase 6 `last_event_id` columns were added directly to existing tables rather than through new ones.

**Increment 5 design decisions:**

**A command owns its transaction by calling `engine.begin()` itself, not by receiving an already-open connection.** `record_event()`, `perform_interaction()`, and `resolve_check()` each take a SQLAlchemy `Engine` and open exactly one transaction internally, matching `docs/DEVELOPMENT.md` §9's "each handler owns its transaction boundary." Internal, non-transaction-owning helpers (`_insert_event_row()`, module-private step functions) take an already-open `Connection` instead, so a command that needs to combine several steps atomically — `resolve_check()` calling the same event-insertion logic `record_event()` uses — does so inside its own single transaction rather than nesting or reopening one.

**`resolve_check()` reacts only when the check result is narratively significant, per `SYSTEM_ARCHITECTURE.md` §6 step 5.** A check with no conditional-route target, or one that fails or doesn't meet the route's requirement, still records its `check_results` row — it simply produces no event and no state change. Only a check that `world.conditional_route_requirement_satisfied()` reports as satisfying its route's requirement causes `resolve_check()` to record an event (`mechanism_activated`), a `narrative.event_effects` row (`target_component = 'connection_status_id'`, previous/new value), and open `campaign.area_connection_state`, all in the same transaction — the effect record and the typed-state update `event_effects`' own comment (revision 057) calls for together, not the typed-state update alone. This mirrors increment 4's read/write split exactly: the read-only decision function decides, the command acts on the decision and supplies the event.

**No `domain/` layer was added.** `docs/DEVELOPMENT.md` §2's "create each subpackage as the phase that needs it requires" applied literally here: every invariant these commands must respect (same-world agreement, ruleset allow-listing, the conditional-route decision itself) already lives in database triggers and `world.conditional_route_requirement_satisfied()`. A `domain/` layer re-deriving those rules in Python would be a second, driftable copy of validation the database already owns — the commands call the existing decision primitives instead.

**The forced-failure atomicity test uses `monkeypatch`, not a naturally arising constraint violation.** `tests/scenario/test_resolve_conditional_route_check.py`'s docstring records why: by the time `resolve_check()` runs, `interaction.enforce_target_world()` (revision 061) has already guaranteed the check's target is same-world as the check, closing off the mismatched-world failure that increment 1's hand-written test could still use; and a duplicate check-result submission fails at the first statement, before any event or state work happens, proving nothing about a later-step rollback. The injected fault exercises the real `engine.begin()` rollback path around real, unmodified production code, standing in for any downstream failure a future validation step might introduce.

## 28. Portal identity and access design decisions

The web-portal roadmap introduced authenticated player, GM, assistant-GM and observer views plus on-demand, audience-filtered summaries. The prior security section was only a table-name sketch and could not represent the required many-to-many or campaign-scoped behavior. Section 19 now defines the target access model.

The principal naming and ownership decisions are:

- `security.campaign_members` becomes `security.campaign_memberships` in the target model.
- Global `security.user_roles` becomes campaign-scoped `security.membership_roles`.
- `security.permissions` is clarified as reusable `security.capabilities`, assigned through `security.role_capabilities` and evaluated by application commands and queries.
- `security.character_permissions` is superseded by semantic `security.membership_character_relationships`, relationship-type capability defaults and explicit typed resource grants.
- `character.character_controllers` remains a distinct operational-control concept because it also supports AI, service and external-system control; it does not by itself authorize a human portal request.
- Facts remain canonical claims and in-world beliefs in `knowledge.*`; user visibility derives through an authorized perspective or explicit administrative access and never rewrites fictional knowledge.
- Explicit resource access uses real typed foreign keys in `security.resource_grants`, not an unenforced text resource type plus opaque UUID.

This is a target-model documentation change, not a claim that the Phase 1–9 database already contains these tables. `docs/PLAN.md` owns delivery phasing: Phase 10 adds the identity and authorization subset required by the application API and playable vertical slice; the portal and import phases extend typed targets only when their acceptance scenarios need them. Completed domain migrations need not be rewritten merely to introduce the new access layer.

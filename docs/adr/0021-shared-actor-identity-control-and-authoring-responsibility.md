# ADR 0021: Shared actor identity, campaign control, and authoring responsibility

- **Status**: Proposed. R19-P0 architecture deliverable, first drafted at `10a1a4e` and corrected after independent review (findings R19-01 to R19-04). Not accepted. One owner decision is recorded: **OD-1 is Owner-approved (2026-11-02)**. Campaigns sharing a world or timeline maintain independent mechanical character state (§3). No other owner acceptance is recorded.
- **Acceptance prerequisites**: These owner decisions in [R19_FOUNDATION_IMPLEMENTATION_PLAN.md §9](../R19_FOUNDATION_IMPLEMENTATION_PLAN.md#9-decision-register) must be recorded before this ADR can be accepted and before the P03-B/P03-C/P03-S contracts freeze:
  - OD-2: co-controller authority;
  - OD-20: classification of item ownership and character location;
  - OD-21: authority for cross-campaign copy and lineage seeding;
  - OD-4: who may assign control;
  - OD-5: authoring delegation;
  - OD-14: no-clock control;
  - OD-17: revelation audiences;
  - OD-19: intentional legacy-access reductions.

  OD-3 (initial operation allow-list) blocks only P03-B implementation of operations.
- **Date**: 2026-11-02
- **Would amend, once accepted**: [ADR 0020](0020-scoped-system-world-and-campaign-roles.md) decision 6, for player-character identity only (§4.6). ADR 0020 remains fully in force until this ADR is accepted *and* the P03-C cutover for each character has completed.
- **Implemented by**: Phase 15 checkpoints P03-A, P03-B, P03-C, and **P03-S** (campaign mechanical-state isolation, §3). The P03-S name is provisional; Phase 15 may fold it into P03-B/C, but it must precede controller operations that write state ([PLANv2.md](../PLANv2.md) §8, 15H). Phase 19 consumes the contracts ([R19_FOUNDATION_IMPLEMENTATION_PLAN.md §5.1](../R19_FOUNDATION_IMPLEMENTATION_PLAN.md#51-actor-contract-owner-phase-15)) and implements none of them.
- **Related**: [ADR 0003](0003-separate-world-timeline-and-campaign.md), [ADR 0010](0010-use-sort-key-ranges-for-fictional-time-intervals.md), [ADR 0016](0016-data-classification-and-private-data-handling.md), [ADR 0022](0022-creature-templates-combatants-and-promotion.md), [ADR 0023](0023-rules-engine-calculation-validation-and-source-authorization.md).

## Context

The owner has approved six product decisions. This ADR implements two of them:
- **Decision 1:** campaign-based character control, with one primary and optional co-controllers.
- **Decision 2:** world authority owns canonical characters, with delegated authoring.

The owner has also confirmed:
- A Character is the identity of an individual actor, whether a person or a creature.
- PC/NPC describes control in a campaign, not an immutable kind.
- Statistics may be partial or absent.
- A change of control preserves the UUID, references and history.

### Verified current implementation (`10a1a4e`; application code unchanged since `defe3f7`)

| Concern | Current implementation (source) | Consequence for this ADR |
|---|---|---|
| Identity | `core.entities` → `character.characters`. Subtype markers are `character.npcs` (`detail_level`) and `character.player_characters` (`player_user_id`, never set by commands, D-8). See `persistence/tables/characters.py`. | Markers are used as identity and as eligibility switches. |
| Kind-driven eligibility | `_BUILDABLE = {"npc", "player_character"}` in `commands/character_builds.py`; `PARTICIPANT_KINDS` in `domain/session_participation.py`; NPC portrayal requires the NPC marker (`commands/npc_portrayal.py`). | A player-controlled monster is mis-routed or refused because of its kind. |
| Relationship storage | `security.membership_character_relationships` columns: membership, character, type, optional `timeline_id`, optional `effective_from_world_time_id` / `effective_to_world_time_id`, `granted_by_membership_id`, `granted_at`, `expires_at`, `revoked_at`. | This is the existing human-to-character table. |
| Period derivation | `security.enforce_membership_character_relationship_scope()` (revision 080) sets `effective_period := NULL` whenever no start endpoint is supplied. It derives `[from, to)` only when a start exists. | An undated row has **no period at all**. A period exclusion constraint cannot see it. |
| Live uniqueness | Unique index `ux_membership_character_relationships_active_type` on `(campaign_membership_id, character_id, character_relationship_type_id)` `WHERE revoked_at IS NULL`. | A live legacy `primary_controller` row and a second live `primary_controller` row for the same membership and character cannot coexist. Nothing limits primaries **per campaign**. |
| Effectiveness | `domain/access.py` (the relationship capability query) requires `revoked_at IS NULL`, `expires_at` unset or in the future, `effective_to_world_time_id IS NULL`, the row's timeline unset or equal to the campaign's own, and the character canon and active. Its docstring says no fictional clock exists, but `campaign.timeline_clocks` and `queries/campaign_clock.resolve_effective_clock` now exist. The relationship query does not use them. | Legacy relationships are "current" by the open-end rule, not by the clock. |
| Capabilities | The `BUILTIN_RELATIONSHIP_CAPABILITIES` matrix gives `owner` and `primary_controller` the capabilities `view_private` and `view_knowledge`, among others. `character.control`, `edit_mechanical_state`, `edit_narrative` and `interact` exist as codes and are withheld. | Legacy rows already carry private and perspective reads that must survive independently. |
| Relationship locking | `commands/access_grants.grant_character_relationship` locks membership (`FOR UPDATE OF cm`), then `campaign.campaigns` (`OF c`), then the user (`OF u`), then the character's `core.entities` row (`OF e`), then candidate rows. `change_character_relationship` locks the target row and its membership first, then the same chain. Character-state and item operations take `lock_operation_scope` and then share-lock the entity through `lock_entities`. | The character's entity row is already the common serialization anchor between relationship writes and character operations. |
| Documented controller table | `character.character_controllers` (`DATABASE_MODEL.md` §7.3, `DOMAIN_MODEL.md` §8.4) | It was never built: no table, migration or code exists. |
| PC identity authoring | `commands/npcs._identity_world_capability` returns no world capability for `player_character` (decision D8/E3). `record_authoring.CAMPAIGN_ORIGINATED_TYPES` holds `player_character` and `item_instance`. `update_character_identity` locks by **world** only. | Any campaign `canon.edit` holder of **any** campaign on the world may edit, and run the lifecycle of, **any** player character of that world. |
| NPC identity authoring | Campaign `canon.edit` plus world `world.canon.edit` (lifecycle needs `world.canon.review`) | World-governed today |
| Builds | `create_character_build` needs campaign `canon.edit` (route campaign on the world), an `npc`/`player_character` kind, and an active lifecycle. It validates against the route campaign's pinned version. `activate_character_build` writes `campaign.character_state.character_build_id` for `(timeline, character)` and does **not** check the build's ruleset version. | Builds are world-attached and unscoped. Activation is timeline-wide. |
| Active build on branches | `queries/character_build_resolution.py`: local state row first, then bounded event-effect history (`campaign.effective_events`), then the administrative ancestor baseline. | A branch inherits its parent's active build as of the branch point. |
| Runtime state | `campaign.character_state`, `character_conditions` and `character_resources` are keyed `(timeline_id, character_id)`. `campaign.campaigns.timeline_id` is not unique. Each campaign pins its own `ruleset_version_id`. | Campaigns sharing a timeline share one active build and one runtime state, possibly under different ruleset versions. |
| Portrayal | `character.npc_portrayal_profiles.npc_id` → `character.npcs` `ON DELETE CASCADE`. Writes need campaign `canon.edit` only (`api/npc_portrayal.py`). | Removing a marker would delete history. Portrayal is GM-scoped and must not become a player surface. |

Supplementary evidence:
- The Phase 14/15 app-interaction investigation (§D6, P03-A/B/C), the DEF-007 plan and the 2026-11-02 handoff are **untracked on this branch and not committed**. They were used as supporting analysis and checked against the source above.
- The cited commits B1-1 `67f80de` (encounter member projection) and DEF7a/b/c (`bcc0e16`, `cb26462`, `4ce9187`) are ancestors of this branch.

## Decision

### 1. One actor identity

1. The individual actor is `core.entities` plus `character.characters`. Its UUID never changes because of control, kind, template, build, promotion or campaign. No other actor or creature identity table is created ([ADR 0022](0022-creature-templates-combatants-and-promotion.md) keeps creatures inside this identity).
2. `character.npcs` and `character.player_characters` become **legacy compatibility markers**. They stay readable as a display and creation hint and for old routes and payloads. Once P03-C moves each consumer, they never decide authorization, build or participation eligibility, control or authoring. No code converts one marker into the other to change a character between NPC and PC.
3. **Mechanics are optional.** A character with no build, or an unsupported or incomplete one, is fully valid for identity, relationships, inventory, knowledge, portrayal and control. A missing build is an empty state, never a reason to invent statistics or to grant authoring.
4. **Eligibility is by capability and lifecycle, not kind.** P03-C replaces the `_BUILDABLE` and `PARTICIPANT_KINDS` kind lists. Stored historical participation roles stay as recorded.

### 2. Campaign control assignments (owner Decision 1)

#### 2.1 One storage authority

Human play control is stored in `security.membership_character_relationships`. The never-built `character.character_controllers` design is **retired**.

Non-human operators are not controllers:
- AI portrayal uses the AI domain.
- Foundry and other clients act through their own principals on behalf of an authorized human.
- A GM operating an uncontrolled actor uses GM authority.

#### 2.2 Columns added by P03-B

- `is_control_assignment BOOLEAN NOT NULL DEFAULT false`.
- `campaign_id UUID NOT NULL`, denormalized from the membership, immutable, and verified by the existing scope trigger. It is backfilled for every existing row.
- `assignment_period_kind TEXT NULL`, a lookup value of `ongoing` or `dated`. It is required when `is_control_assignment`, and must be NULL otherwise.
- `revoked_by_membership_id UUID NULL` (same-campaign, trigger-checked) and `revocation_reason TEXT NULL`.

#### 2.3 Assignment invariants

| Invariant | Enforcement |
|---|---|
| Assignment rows use type `primary_controller` or `co_controller` only. | Trigger on the type code. |
| An `ongoing` assignment has both world-time endpoints NULL, so `effective_period` is NULL by the existing derivation. | CHECK. |
| A `dated` assignment has `effective_from_world_time_id` set, so the trigger derives a non-NULL half-open `effective_period`; `effective_to` is optional. | CHECK plus the existing derivation. |
| Assignment rows never use `expires_at`. Real-time expiry of control is a future extension. | CHECK (`is_control_assignment → expires_at IS NULL`). This avoids expired-but-unrevoked rows occupying uniqueness slots. |
| Assignment rows have `timeline_id IS NULL`. The campaign already fixes the timeline. | CHECK. |
| At most one live (unrevoked) **primary** assignment per `(campaign_id, character_id)`, whatever its period kind. | New partial unique index `WHERE is_control_assignment AND type = primary AND revoked_at IS NULL`. The type is resolved through a denormalized `is_primary` boolean maintained by the type trigger, because index predicates cannot join. |
| At most one live assignment of any role per `(campaign_membership_id, character_id)`. A member cannot be primary and co-controller at once. | New partial unique index `WHERE is_control_assignment AND revoked_at IS NULL`. |
| Scheduled future hand-offs (two live dated primaries with non-overlapping periods) are **not** supported initially. Replacement revokes the old row and inserts the new one in one transaction. | The command, plus the unique index above. |
| Legacy and assignment rows coexist. | `ux_membership_character_relationships_active_type` is replaced by the same unique index with the extra predicate `AND NOT is_control_assignment`. Legacy uniqueness is unchanged, and a member may hold one live legacy row and one live assignment of the same type. |

#### 2.4 When an assignment is in effect (R19-03)

1. **One request clock.** Each request resolves `resolve_effective_clock(campaign timeline)` once. This is the same resolver the party-membership predicate uses, including its bounded branch fallback. Every control decision in the request uses that value.
2. **Dated assignment.** It is in effect when the clock is set and `effective_period @> clock`. The interval is half-open: the start is included and the end excluded. A dated assignment whose start is after the clock is upcoming, not in effect.
3. **Ongoing assignment.** It is in effect from creation until revoked, regardless of the clock. "Ongoing" is an **explicitly chosen** kind recorded on the row. It is never inferred from absent endpoints.
4. **No clock.** With no effective clock, a dated assignment is *undetermined* and confers nothing. An ongoing assignment is unaffected. Whether undated ongoing control is permitted at all, and whether it should be the default kind, is **owner decision OD-14**. DEF-007's party rule ("no clock, nothing current") is evidence for a consistent choice. It is **not** silently applied to the control domain, which is distinct.
5. **Branches.** Assignments belong to campaigns, and campaigns are fixed to one timeline, so nothing is inherited across branches. A campaign on a branch makes its own assignments. A branch without its own clock reads its parent's clock bounded at the branch point, per the resolver.
6. **Legacy rows** keep today's effectiveness rule (open `effective_to`) unchanged. P03-B does not alter legacy semantics.
7. **History.** "Who controlled the actor at world time T" is answered from dated assignments' periods. Ongoing assignments carry real-time `granted_at` / `revoked_at` only. Read models label them "ongoing since …" and never fabricate fictional dates.

#### 2.5 Capability routing

1. The relationship capability query **excludes** `is_control_assignment` rows from `BUILTIN_RELATIONSHIP_CAPABILITIES`.
2. Assignment rows resolve **exclusively** through a new closed matrix, `CONTROL_ASSIGNMENT_CAPABILITIES`, keyed by role:
   - `discover`, `view_summary`, `view_full` (the controller mechanical projection), `view_inventory`;
   - `character.control`;
   - `character.edit_mechanical_state`, limited to the P03-B operation allow-list (OD-3).
3. It never includes:
   - `canon.edit`, world capabilities, `access.manage`;
   - `view_private`, `view_knowledge` (perspective);
   - build proposals, portrayal or revelation.
4. The co-controller set is fixed by OD-2.
5. **Legacy relationship rows keep their existing capabilities**, including `view_private` and `view_knowledge`, through their own matrix. Creating, revoking or replacing an assignment never alters, revokes or promotes a legacy row.
6. A knowledge perspective for an assigned controller is a separate, explicitly created grant: a legacy-matrix relationship row or a resource grant, with its own revocation.

#### 2.6 GM default

With no live, in-effect player assignment, the actor is GM-operated under existing GM authority. No row records this. Read models report `controller: none (GM-operated)`.

#### 2.7 Assignment management

- Commands `assign_character_control`, `replace_primary_controller` and `revoke_character_control` are idempotent and audited.
- They require a new campaign capability, `character.assign_control`, separate from `access.manage` and `canon.edit`. Its holders are OD-4. **No default holder is encoded until OD-4 is decided.**
- The assignee must be an active membership of the campaign.

#### 2.8 Common locking protocol (R19-02)

The protocol extends the existing relationship order and must not invert it.

| Path | Lock sequence |
|---|---|
| Assign / replace / revoke | (1) the target membership row `FOR UPDATE`, plus any existing assignment row being revoked, together with its membership (`OF mcr, cm`); (2) `campaign.campaigns` `FOR UPDATE`; (3) the user row `FOR UPDATE`; (4) **the character's `core.entities` row `FOR UPDATE`, the stable anchor even when the assignment set is empty**; (5) read and modify the live assignment rows; (6) insert, update and audit. |
| Controller operation | `lock_operation_scope` (as today), then the character's `core.entities` row `FOR SHARE` via `lock_entities`, then the state rows the operation changes. After those locks are taken, it re-reads the in-effect assignment for the caller. A missing assignment is refused, non-disclosing. |

Because revocation takes the anchor `FOR UPDATE` and operations take it `FOR SHARE`:
- an operation that holds the share lock completes before the revocation commits;
- an operation that arrives after the revocation's commit sees no assignment and is refused;
- a committed operation remains history.

No operation re-checks against a cached `AccessContext`.

#### 2.9 Revocation scope

- Each capability source (role, legacy relationship, assignment, revelation, resource grant) is revoked independently.
- A whole-character `campaign.view` deny suppresses discovery, profiles, mechanics and play from every source.
- An operation-specific deny blocks only that operation.

#### 2.10 Legacy rows are never promoted automatically

The P03-C manifest (§8) lists live legacy `primary_controller` and `co_controller` rows. A GM may create an assignment for a listed membership as an explicit, audited action. The legacy row is left untouched unless the GM separately revokes it.

### 3. Campaign mechanical-state isolation (owner decision OD-1: **Owner-approved**, 2026-11-02)

**Binding owner decision:** campaigns sharing a world or timeline must maintain independent mechanical character state.

This replaces the earlier proposal, which is withdrawn. That proposal allowed campaign-scoped builds only on single-campaign timelines, required an acknowledgement for cross-campaign activation, and allowed one controlling campaign per timeline.

Shared world identities and shared narrative timelines remain fully supported. Only **mechanical** character state moves from timeline scope to campaign scope.

#### 3.1 What stays shared and what becomes per campaign

| Concern | Scope | Storage |
|---|---|---|
| Character identity, world definitions and descriptions, builds as reusable definitions (§5), world portrayal defaults | World (shared) | Unchanged |
| Canonical narrative history: events, event participants and causes, the timeline clock, party memberships, quest, objective, knowledge, location, dungeon, organization and relationship state, character location history | Timeline (shared narrative, ADR 0003) | Unchanged |
| Active build selection | **Campaign** | `campaign.campaign_character_state.character_build_id` |
| Current, maximum and temporary hit points; exhaustion; death saves; initiative; transformation | **Campaign** | `campaign.campaign_character_state` |
| Conditions | **Campaign** | `campaign.campaign_character_conditions` |
| Resources | **Campaign** | `campaign.campaign_character_resources` |
| Item mechanical state: quantity, charges, damage, equipped, destroyed | **Campaign** | `campaign.campaign_item_state` |
| Possession and carrying (inventory) | **Campaign** | `campaign.campaign_inventory_entries` |
| Attunement | **Campaign** | `campaign.campaign_item_attunements` |
| Temporary effects | **Campaign** | Defined with the future effect model; never timeline-scoped |
| Item legal ownership (`campaign.item_ownership`) and character location (`campaign.character_location_history`) | Timeline narrative: proposed to stay shared | Unchanged. **OD-20 confirms this classification.** |
| Item identification (`knowledge.item_identification`) | Knowledge, per knower | Unchanged |
| Encounter combatant state (ADR 0022) | Encounter, already campaign-owned through the encounter | ADR 0022 |

Different campaigns sharing a world and timeline **may pin different rulesets or versions**. Campaign creation gains no restriction.

#### 3.2 Campaign-keyed storage (Phase 15, checkpoint P03-S)

The new tables are additive. The legacy tables are retained.

| New table | Key | Mirrors | Additional invariants |
|---|---|---|---|
| `campaign.campaign_character_state` | `(campaign_id, character_id)` | `campaign.character_state` columns, including `character_build_id` and `last_event_id` | `timeline_id`, denormalized and immutable, must equal the campaign's timeline (trigger). `origin` lookup: `initialized`, `lineage_seeded`, `migrated_from_timeline`, `cross_campaign_copy`. The character must belong to the campaign's world. |
| `campaign.campaign_character_conditions` | `(campaign_id, character_id, condition_id)` | `character_conditions` | The condition must belong to the **campaign's pinned version** |
| `campaign.campaign_character_resources` | `(campaign_id, character_id, resource_definition_id)` | `character_resources` | Same version rule |
| `campaign.campaign_item_state` | `(campaign_id, item_instance_id)` | `item_state` | The item must belong to the campaign's world |
| `campaign.campaign_inventory_entries` | Surrogate PK; one active possession per `(campaign_id, item_instance_id)` | `inventory_entries` | Holder and container checks as today, plus the campaign |
| `campaign.campaign_item_attunements` | Surrogate PK | `item_attunements` | One active attunement per `(campaign_id, item_instance_id)`; at most three active per `(campaign_id, character_id)`, under the per-(campaign, character) advisory lock |
| `campaign.campaign_mechanical_lineages` | `campaign_id` | — | `source_campaign_id` must be on an **ancestor** timeline of this campaign's timeline (trigger). Also `seeded_at`, `seeded_by_user_id`, `reason`, and a seed report snapshot. |
| `campaign.mechanical_state_migration_records` | Surrogate | — | Source legacy table and key, target campaign, manifest disposition, reviewer, time |

**Why new tables rather than a `campaign_id` column on the existing tables:** the existing primary keys (`(timeline_id, character_id)`, and so on) cannot hold two campaigns' rows. Changing them in place is destructive and cannot be rolled back. New tables allow a dual-read compatibility period and a clean downgrade.

The ruleset dependency guard on `rules.world_rulesets` (revisions 031/035/037) and the event-consistency triggers are extended to the new tables.

#### 3.3 Mechanical events

- Events remain shared timeline narrative history, visible under the existing audience rules.
- Every event that records an effect on a **mechanical component** must carry `campaign_id`. The mechanical components are listed in a new lookup `campaign.mechanical_components`: `current_hit_points`, `character_build_id`, conditions, resources, item state, possession and attunement. A deferred constraint trigger enforces this for **new** events. Existing events with a NULL campaign are listed in the manifest (§3.8) and are not rewritten.
- The effect's values belong to that campaign's state.
- Corrections (`commands/event_corrections.py`) restore values into the corrected event's campaign table.

#### 3.4 Resolution, including timeline inheritance within a campaign

A campaign's timeline is immutable (revision 030), so a campaign never moves between timelines. Inheritance therefore happens only through an explicit **lineage**:

1. **Local campaign row.** `resolve_campaign_mechanical_state(campaign_id, character_id, component)` returns the campaign's own row. It wins even when NULL ("explicitly none").
2. **No row.** The component is absent in this campaign. Calculation reports `missing_input`, and nothing is read from another campaign or from the legacy timeline tables. The only exception is the dual-read period (§3.8), labeled `legacy_shared_state`.
3. **Lineage seeding.** This is how a branch campaign inherits. When a campaign on a branch timeline is created, or later through an explicit command, a GM may record a lineage from a **source campaign on an ancestor timeline**. Seeding then runs once, explicitly and with an audit record:
   - it reconstructs the source campaign's mechanical state **as of the branch point** from that campaign's mechanical events in `campaign.effective_events(branch timeline)`, which is the existing bounded-ancestry function filtered to `campaign_id = source`;
   - it falls back to the source campaign's administrative baselines, with the documented limitation of `character_build_resolution`;
   - it writes local rows with `origin = lineage_seeded`.

   Components that cannot be reconstructed are **not** seeded and are listed in the seed report. Examples: a condition or resource change made without an effect, or possession that is not event-linked.

   Lineage is never inferred: not from timeline ancestry alone, shared membership, or names. After seeding, the campaign's state is fully local. Later source changes never propagate (CLAUDE.md rule 7). Seeding is a cross-campaign operation and follows §3.6's authority.
4. **Active build.** `resolve_campaign_active_build(campaign_id, character_id) -> usable | incompatible_ruleset_version | out_of_scope | none`:
   - `usable`: a campaign row selects a build whose version equals the campaign pin and whose scope is `world_shared`, `legacy_unscoped`, or this campaign;
   - `incompatible_ruleset_version`: possible only for migrated or seeded rows;
   - `out_of_scope`: a seeded or migrated row names another campaign's private build. It is shown to GMs as a status only.

#### 3.5 Authorization and control

- Mechanical reads and writes are authorized in **the campaign whose state they touch**, which is always the route campaign. No ordinary command writes another campaign's state.
- Control assignments are campaign-scoped (§2). **The same character may be controlled by different players in different campaigns on the same timeline.** Their operations write different rows. The withdrawn "one controlling campaign per timeline" rule does not apply.
- Locking: operations take the character entity `FOR SHARE` (§2.8), then the campaign state rows they change `FOR UPDATE`. Attunement limits use an advisory lock keyed by `(campaign_id, character_id)`.
- Projection, discovery and revelation (P03-A) are unchanged. A campaign's mechanical state is visible only through that campaign's projections.

#### 3.6 Explicit cross-campaign operation

The command is `copy_character_mechanical_state(source_campaign_id, target_campaign_id, character_id, components[], as_of)`. Lineage seeding uses the same machinery.

- It reads the source in truth mode, writes **only the target**, and records an event in the target campaign whose effects cite the source campaign and the source values. It never modifies the source.
- Components that are invalid in the target are skipped and listed:
  - a build whose version differs from the target pin;
  - a condition or resource definition not in the target version;
  - another campaign's private build.
- **Authority is OD-21, owner decision. It is UNRESOLVED.** The recommendation is target-campaign `canon.edit` plus source-campaign `canon.edit`, because truth reads are needed. The command, and lineage seeding, ship disabled until OD-21 is recorded.

#### 3.7 Builds and rulesets under isolation

- Activation writes `campaign_character_state.character_build_id` for the route campaign only.
- The build version must equal that campaign's pin (the X4 guard, now per campaign).
- `world_shared` builds are selectable by any campaign on the world with a matching version.
- `campaign` builds are selectable only by their origin campaign, on any timeline. **OD-6 is reconciled:** campaign-scoped builds are permitted without timeline restriction.
- Two campaigns on one timeline may activate different builds, including builds on different rulesets or versions.

#### 3.8 Migrating existing timeline-only records (P03-S; additive, reversible, manifest-reviewed)

1. **Create** the empty campaign tables, the lineage and migration-record tables, and the mechanical-components lookup.
2. **Manifest.** A read-only script run on a restored copy lists every legacy mechanical row (character state, conditions and resources; item state, inventory and attunements), keyed by `(timeline, …)`, with:
   - every campaign ever created on that timeline, including archived ones;
   - mechanical events by `campaign_id`, sessions and encounters, as **evidence only**.

   It classifies each row:
   - `single_campaign`: exactly one campaign has ever existed on the timeline. A mapping to that campaign is *proposed* and still reviewed;
   - `multi_campaign`: ambiguous. The reviewer chooses copy to all listed campaigns, copy to selected campaigns, or leave unmapped (the campaigns start without that state);
   - `no_campaign`: legacy only;
   - `branch_inherited`: the timeline has no local row but resolves through ancestry. The reviewer may record a lineage (§3.4).

   Historical campaign ownership is **never inferred** for ambiguous rows.
3. **Apply.** Copy reviewed rows with `origin = migrated_from_timeline` and a `mechanical_state_migration_records` entry each. Unreviewed rows stay legacy.
4. **Dual-read.** Readers prefer campaign rows. A campaign with only a `pending` legacy row shows it, GM-visible only, labeled `legacy_shared_state` and read-only. Calculation results built from it carry a `legacy_shared_state` warning and are never labeled rules-validated.
5. **Cut over** writers one consumer family at a time (§3.9). After cutover, a trigger makes the legacy tables read-only. They are **never dropped in Phase 15**.
6. **Rollback.**
   - Before writers cut over: drop the new tables; the legacy tables are untouched.
   - After cutover: a reverse copy is possible only for `single_campaign` rows. Divergent multi-campaign state cannot be merged back, so rollback is a backup restore.
   - The migration takes a backup before writers cut over.

#### 3.9 Affected tables, commands, resolvers and APIs

The owner is Phase 15, P03-S, unless noted.

| Kind | Item | Change |
|---|---|---|
| Tables | `campaign.character_state`, `character_conditions`, `character_resources` | Legacy, read-only after cutover; replaced by the campaign tables |
| Tables | `campaign.item_state`, `inventory_entries`, `item_attunements` | Same |
| Tables | `narrative.event_effects` / `narrative.events` | Campaign required for new mechanical effects (deferred trigger) |
| Tables | `rules.world_rulesets` dependency guard (revisions 031/035/037) | Extend to the new tables |
| Commands | `commands/character_builds.py` (`initialize_character_state`, `activate_character_build`) | Campaign rows; per-campaign version guard |
| Commands | `commands/character_state.py` (HP, conditions, resources) | Campaign rows |
| Commands | `commands/encounters.py` (combat damage) | The encounter's campaign row, and set `last_event_id`. Campaign-less encounters may not write mechanical state after cutover: they are refused explicitly, and existing ones are listed in the manifest |
| Commands | `commands/event_corrections.py` | Restore into the event's campaign table |
| Commands | `commands/item_operations.py`, `commands/items.py` | Campaign item state, possession and attunement; per-campaign limits |
| Commands | `commands/integration.py` (Foundry sync via `_resolve_combat_turn_impl`) | Writes the paired campaign's rows only |
| Resolvers | `queries/character_build_resolution.py` | Replaced by `resolve_campaign_active_build`. Branch ancestry is used only during lineage seeding |
| Queries | `queries/character.py`, `character_sheet.py`, `character_builds.py`, `encounter_preparation.py` | Read campaign rows (dual-read during migration) |
| Queries | `queries/inventory.py`, `item_authoring.py`, `world_explorer.py` (item state, possession) | Campaign rows. World Explorer item cards show possession only for the route campaign |
| Queries | Party inventory reads (`api/parties` via `queries/inventory.py`) | Campaign rows |
| APIs | `api/character_state.py`, `api/character_builds.py`, `api/characters.py` (sheet, inventory, attunements), `api/items.py`, `api/encounters.py`, `api/integration.py` | Route campaign = state campaign. Response shapes unchanged, plus a `state_origin` field where useful |
| New commands | `record_campaign_mechanical_lineage`, `seed_campaign_mechanical_state`, `copy_character_mechanical_state` | Disabled until OD-21 |
| Rules (Phase 19) | `queries/rules_context*.py`, the manifest and fingerprint, catalog | ADR 0023: campaign-scoped facts and manifest context |

#### 3.10 Regression examples

- **Same ruleset, shared timeline.** Campaigns A and B both pin 5e 2024 on timeline T. Character K is shared.
  - A activates world-shared build Bw1; B activates Bw2. Each resolves its own.
  - P1, K's primary in A, lowers K's HP. B's HP is unchanged.
  - P2 controls K in B at the same time.
  - K equips and attunes a sword in A. In B the sword is neither equipped nor attuned, and B's attunement limit is unaffected.
  - An encounter in A damages K. Only A changes.
  - Correcting that event restores A only.
  - Travel on T moves K in both campaigns: location is shared narrative (OD-20).
- **Different versions, shared timeline.** A pins 5e 2024; B pins another version.
  - Each activates a build of its own version, and each is evaluated under its own adapter and support level.
  - Neither sees `incompatible_ruleset_version`.
  - Copying K's active build from A to B is refused for version mismatch and listed.
- **Branch lineage.** Timeline T2 branches from T, and campaign C is created on T2.
  - With a lineage to A, C is seeded from A's mechanical history bounded at the branch point. The report lists non-reconstructable components. Later changes in A never reach C.
  - Without a lineage, C starts with no mechanical state.
- **Cross-campaign copy.** After OD-21, B's GM copies K's conditions from A. An event is recorded in B, and A is unchanged.
- **Migration.**
  - A `single_campaign` timeline's rows are proposed for its campaign.
  - A `multi_campaign` timeline's rows stay legacy until reviewed. Both campaigns see the `legacy_shared_state` label, and neither can write it.

### 4. Authoring responsibility (owner Decision 2; R19-04)

#### 4.1 Current effective author sets

Character P is a published player character on world W, used by campaigns A and B. Campaign C is also hosted on W and has never referenced P.

| Operation on P | Who may do it today |
|---|---|
| Edit identity (name, species, descriptions, …) | Every campaign `canon.edit` holder of **A, B and C**, and of any future campaign on W |
| Lifecycle (submit, publish, archive, restore) | The same set (`CAMPAIGN_ORIGINATED_TYPES` bypasses world review) |
| Create a build | The same set (campaign `canon.edit`; builds have no world check) |
| Activate a build | `canon.edit` holders of a campaign on the timeline where the state row is written |

A world Editor with no campaign role has no route to edit P. Authoring routes are campaign-scoped (ADR 0020 decision 6).

So a single campaign delegation, for example "P is delegated to A", would **remove** B's and C's GMs. It does not preserve current access. Any reduction is an intentional decision (OD-19), never a side effect.

#### 4.2 Three separate concepts

1. **Stewardship.** World authority always governs canonical character definitions, under ADR 0020's two-key rule: world capability plus route-campaign `canon.edit`.
2. **Delegations.** Zero or more rows in `character.character_authoring_delegations`:
   - `character_id`, `campaign_id`;
   - `operations`: a closed set drawn from `identity_edit`, `lifecycle_submit`, `lifecycle_publish`, `lifecycle_archive_restore`, `build_create_campaign_scoped`;
   - `granted_by_user_id`, `granted_at`, `revoked_by_user_id`, `revoked_at`, `reason`.

   Each delegation lets that campaign's `canon.edit` holders perform exactly the listed operations on that character without the world capability. Delegations are history-preserving and never edited in place.
3. **Legacy compatibility exception.** In `character.character_authoring_legacy_exceptions`, `character_id` (PK), `basis` = `adr0020_d6_player_character`, `recorded_at`, `disposition` (`pending` | `kept` | `replaced`), `disposed_by_user_id`, `disposed_at`. While this row exists with `pending` or `kept`, the character keeps today's rule: any campaign `canon.edit` on the world may edit it and run its lifecycle.

#### 4.3 Authority to grant and revoke

This is **OD-5, owner decision**. No default is encoded.

The recommended rule is that granting or revoking a delegation requires world `world.canon.review` on W plus campaign `canon.edit` on the route campaign. Delegating a lifecycle operation requires that the granter hold the matching world capability. Nobody delegates more than they hold.

Delegations are never created by campaign creation, world-use grants (`campaign.create` / hosting permission), control assignment, character creation, subtype, first campaign, or audit history.

#### 4.4 New characters

Whether a character created through a campaign route without a world role is allowed, and with which delegation, is **OD-5**. Until decided, P03-C must preserve current behavior for new player characters. Each new player character gets a legacy exception row (`pending`), so behavior is unchanged and the record is explicit.

#### 4.5 Migration

The P03-C manifest:
1. lists every player character;
2. writes a `pending` legacy exception for each;
3. shows evidence: relationships, sessions, events, audit, each cited only as evidence;
4. offers dispositions:
   - **keep** the exception;
   - **replace** it with explicit delegations to named campaigns. This is an access reduction for unnamed campaigns and needs an OD-19 record per world or per character;
   - **steward only.**

Ambiguous characters stay `pending`, with unchanged access, until reviewed. Creator, subtype, first campaign and audit history are never used to infer a disposition.

#### 4.6 ADR 0020 amendment and timing

- On acceptance, this ADR amends ADR 0020 decision 6 so that player-character identity is governed by §4.2 rather than by the `CAMPAIGN_ORIGINATED_TYPES` exception.
- The code change, removing `player_character` from `CAMPAIGN_ORIGINATED_TYPES` and routing through §4.2, ships in P03-C. It has **no effect for any character whose legacy exception is `pending` or `kept`**.
- `item_instance` is unaffected.
- Until acceptance, ADR 0020 governs unchanged. A note in ADR 0020 points to this proposal.

#### 4.7 Delegated player authoring

Delegated player authoring uses resource grants (`security.resource_grants`, character target) for:
- `character.edit_narrative`, limited to the player-editable profile fields that OD-18 defines;
- `character.propose_build`, a new capability (ADR 0023 §7).

A grant is campaign-scoped, revocable and audited. The granter must hold `access.manage` **and** the delegated authority for that character in that campaign. Direct build commit is not delegable.

#### 4.8 Campaign preferences never overwrite world definitions

Campaign notes, preferences and controller briefings live in campaign-scoped storage (P03-A, Phase 16). They never live in `character.character_descriptions`. Campaign-owned character copies are prohibited (`DATABASE_CONVENTIONS.md` §34).

### 5. Builds: definition scope versus activation

P03-C adds `build_scope` (`world_shared` | `campaign` | `legacy_unscoped`), `origin_campaign_id` (required for `campaign`, immutable) and `created_by_user_id` to `character.character_builds`. Existing builds are backfilled `legacy_unscoped`, which behaves exactly like today.

| Operation | Authority |
|---|---|
| Create a `world_shared` build | World `world.canon.edit` + route-campaign `canon.edit` (stewardship) |
| Create a `campaign` build | Route-campaign `canon.edit` where the character has a legacy exception or a `build_create_campaign_scoped` delegation for that campaign; or approval of a delegated `character.propose_build` draft (ADR 0023 §7) |
| List or read a build's mechanics | `world_shared` / `legacy_unscoped`: per character projection. `campaign`: only within its origin campaign |
| Activate | Route-campaign `canon.edit`. The write goes to that campaign's `campaign_character_state` only (§3.7), plus the per-campaign ruleset-version guard, plus the ADR 0023 §7.4 activation gate |
| Modify | Nobody. Builds are immutable. |

The **ruleset-version guard** (reject a build whose version differs from the activating campaign's pin) is a Phase 15 change. It may land before P03-C. Under OD-1 it applies per campaign once P03-S moves activation to `campaign_character_state`.

### 6. Public profile, revelation and projections (P03-A)

This ADR adopts the investigation's recommended contract (§D6.3–D6.5, supplementary):
- publication is not revelation;
- a narrow `character.reveal` capability separate from `access.manage`;
- a source-tagged revelation record;
- an explicitly released, versioned public profile;
- legacy background kept restricted until reviewed;
- one discovery and profile predicate for every consumer.

**Audiences** (selected members, groups, campaign-wide including future members or not) and **release semantics** (whether a reveal follows later releases) are **OD-17, owner decision**, required before the P03-A schema.

Four projections are distinct server DTOs:
1. public profile;
2. controller view;
3. GM view;
4. derived mechanics. These are returned only under a projection that may read every input, per ADR 0023 §9.

### 7. Portrayal

P03-C re-keys `npc_portrayal_profiles` to `character_id`:
1. add a nullable column;
2. backfill it from `npc_id` (same UUID);
3. verify version chains and counts;
4. switch commands and reads;
5. swap the FK and cascade target.

The `npc_id` dependency is dropped only after verification, with a backup. Portrayal remains a GM authoring surface (`canon.edit`).

**Player-authored portrayal guidance** for a controlled character (PLANv2 16A) is a separate, campaign-scoped, controller-owned profile. It is not `npc_portrayal_profiles` and grants no GM portrayal access. Its fields and review are **OD-18**.

### 8. Migration, compatibility and rollback

1. **Manifest.** A read-only script on a restored copy classifies every character:
   - markers;
   - live and historical relationships by type;
   - legacy exception candidates;
   - builds and candidate scopes;
   - portrayal versions;
   - session and encounter participations;
   - campaigns sharing timelines and their pins;
   - legacy timeline-scoped mechanical rows and their §3.8 classification.

   Audit is evidence only. The mechanical-state migration itself follows §3.8.
2. **Additive first.** New columns, tables and indexes ship with code that still honours legacy paths. Old and new effective access are compared on the restored copy, and every difference is recorded with its OD-19 decision.
3. **Preserve.**
   - Keep: UUIDs, entity rows, builds and their children, active-state history, events and effects, Knowledge, relationship and inventory references, portrayal versions, historical session roles.
   - No automatic control or revelation.
4. **Index replacement.** Inside one migration:
   1. create the new legacy-only unique index concurrently-safe (it is a subset predicate, so existing rows satisfy it);
   2. create the assignment indexes;
   3. drop the old index.

   The downgrade restores the old index only while no assignment rows exist. Otherwise it refuses.
5. **Compatibility adapters.** Legacy `/npcs` and `/player-characters` routes and `kind` payloads re-check the new authority. A legacy kind is only a creation hint.
6. **Subtype retirement** comes last and is not required to close Phase 15. Irreversible steps are backup-gated. Rollback after them is a restore.

### 9. Rules-engine boundary

The actor model exposes to ADR 0023 only these elements of the plan's §5.1 contract:
- identity;
- the campaign-aware active build (§3.4);
- build scope;
- the **route campaign's** mechanical state rows (§3.2) and their loaded values, with their `origin`, or the `legacy_shared_state` marker during dual-read;
- the route campaign's inventory, item state and attunements;
- the caller's projection tier.

The rules engine never decides control, revelation or authoring. Control never decides mechanics.

## Acceptance scenarios (added to the plan's §8)

- **Migration.**
  - Restored-copy migration with legacy `primary_controller` rows. Before and after, effective capabilities are identical, no assignment row exists, and the old index is replaced without violations.
  - A PC used by two campaigns plus an unrelated third keeps all three campaigns' authors while its exception is `pending`.
  - Disposition `replace` removes exactly the unnamed campaigns, recorded under OD-19.
- **Concurrency.**
  - Two concurrent `assign` primaries for one campaign and character: one succeeds, the other gets a stale or conflict error, and the unique index is the backstop.
  - Revoke racing a controller HP operation: either the operation commits first and the revocation follows, or the operation is refused. Never a commit after the revocation.
  - An assignment for an empty set racing a second assignment: serialized on the entity anchor.
  - Assignments in campaigns A and B on the same timeline both succeed (OD-1). Concurrent HP operations by the two controllers update different campaign rows, with no lost update and no cross-campaign effect.
- **Mechanical isolation (OD-1).**
  - The §3.10 same-ruleset and different-version examples.
  - Branch lineage seeding, with and without a lineage.
  - Cross-campaign copy writes the target only.
  - Event correction restores only the event's campaign.
  - A campaign-less encounter cannot write mechanical state after cutover.
  - Mechanical events without a campaign are refused.
  - Manifest: `single_campaign` rows are proposed for their campaign; `multi_campaign` rows stay legacy until reviewed.
  - Rollback before writer cutover leaves the legacy tables byte-identical.
- **Clock.**
  - A dated assignment at clock = start is in effect; at clock = end it is not; after the clock is unset it is undetermined.
  - An ongoing assignment is unaffected by the clock.
  - A branch campaign does not inherit assignments.
- **Routing.**
  - An assignment row never grants `view_private` or `view_knowledge`.
  - A legacy `primary_controller` row keeps them after an assignment is created and after one is revoked.

## Consequences

- **Easier.**
  - A player-controlled monster, an NPC handed to a player, and different controllers in different campaigns, even on one timeline, are ordinary assignments on one UUID. Each campaign has its own mechanical state.
  - Phase 16 and Phase 19 consume stable contracts instead of kind checks.
- **Harder.**
  - Capability sources must stay distinguishable.
  - P03-S adds campaign-keyed mechanical tables and moves every mechanical writer and reader to them. It needs a reviewed manifest for legacy timeline rows and a dual-read period.
  - P03-C needs a manifest and owner review per legacy exception.
  - Campaigns sharing a timeline share narrative history but not mechanics. A narrative event recorded in campaign A (for example "K was wounded") does not change K's HP in campaign B unless B's GM records it or copies it (§3.6).
- **Foreclosed.**
  - A `character.character_controllers` table.
  - NPC↔PC conversion by marker swap.
  - Recreating actors to change control.
  - Control granting canon, secrets or perspective.
  - Inferring authoring from creator, kind, first campaign, hosting permission or audit.
- **Documentation follow-ups** (with the implementing checkpoint):
  - `DOMAIN_MODEL.md` §2.5 and §8.4–8.6;
  - `DATABASE_MODEL.md` §7.3 and §19.4;
  - `ENTITY_LIFECYCLE.md`;
  - `PHASE13E_ACCESS_CONTRACT.md`;
  - the `domain/access.py` docstring that claims no fictional clock exists.

## References

- [PLANv2.md](../PLANv2.md) §6.1, §8 (15C, 15H, 15.9), §9 (16A), §12 (19.0)
- Code: `src/dnd_ai/domain/access.py`, `src/dnd_ai/domain/record_authoring.py`, `src/dnd_ai/commands/{access_grants,character_builds,npcs,player_characters,npc_portrayal}.py`, `src/dnd_ai/queries/{character_build_resolution,campaign_clock,party_membership_period}.py`, `src/dnd_ai/persistence/tables/{characters,security,campaign}.py`, `database/migrations/versions/080_security_identity_and_access.py`
- Supplementary, untracked: `PHASE14_15_APP_INTERACTION_INVESTIGATION_2026-11-01.md` §D6, `PHASE14_15_DEF007_EFFECTIVE_TIME_MEMBERSHIP_PLAN_2026-11-01.md`, `PHASE14_15_REMAINING_WORK_AND_HANDOFF_2026-11-02.md` §6
- [DATABASE_CONVENTIONS.md](../DATABASE_CONVENTIONS.md) §12, §26, §34

# ADR 0021: Shared actor identity, campaign control, and authoring responsibility

- **Status**: Proposed. R19-P0 architecture deliverable, first drafted at `10a1a4e` and corrected after independent reviews: R19-01 to R19-04, then R19-10 to R19-13 and residual R19-02 at `74a10cb`, then R19-14 to R19-16 and residual items at `6ea0e73`, then residual R19-14 (withheld unclassified effects, with the Owner-approved stricter attribution rule of 2026-11-03) at `e812dcf`, then the universal event-effect disclosure rule (Owner-approved 2026-11-03) at `678db69`, then the confirmed attribution policy (`authorized_at_write` and `migration_reviewed` bases, Owner-approved 2026-11-03) at `2d17acf`. Not accepted. The second-review content (§2.8 controller path, §3.1.1 tokens and intent, §3.3 events, §3.7 item versions, §3.8 migration protocol) is proposed design, **not implemented, enabled, tested or accepted**. Owner decisions recorded, all 2026-11-02:
  - **OD-1, Owner-approved:** independent mechanical state per campaign (§3).
  - **OD-20, Owner-approved:** shared narrative ownership and location; campaign-specific mechanical possession (§3.1.1).
  - **OD-21, Owner-approved:** separately authorized lineage seeding and cross-campaign copy, both disabled until enablement acceptance (§3.6).

  No other owner acceptance is recorded.
- **Acceptance prerequisites**: These owner decisions in [R19_FOUNDATION_IMPLEMENTATION_PLAN.md §9](../R19_FOUNDATION_IMPLEMENTATION_PLAN.md#9-decision-register) must be recorded before this ADR can be accepted and before the P03-B/P03-C/P03-S contracts freeze:
  - OD-2: co-controller authority;
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
| Controller operation | **A new bounded scope, `lock_controller_operation_scope(campaign_id, actor_user_id, character_id, operation_code)`.** `lock_operation_scope` cannot be used: it raises unless the capability is `canon.edit` (`commands/_operations.py`). The new scope takes the same prefix as `lock_authoring_scope`, in the same order: world `FOR SHARE`, the actor's membership and role rows, the account, campaign `FOR SHARE`. It does **not** require `canon.edit`. Then: the character's `core.entities` row `FOR SHARE`; then the caller's live, in-effect assignment row `FOR SHARE`, re-read under lock; then a check that `operation_code` is in the closed `CONTROLLER_OPERATIONS` allow-list (OD-3) and not denied; then the route campaign's state rows the operation changes, `FOR UPDATE`. A failure at any step is a non-disclosing refusal. |

Because revocation takes the anchor `FOR UPDATE` and operations take it `FOR SHARE`:
- an operation that holds the share lock completes before the revocation commits;
- an operation that arrives after the revocation's commit sees no assignment and is refused;
- a committed operation remains history.

No operation re-checks against a cached `AccessContext`.

**Controller commands are separate, named intents** (for example `controller_adjust_hit_points`, `controller_set_resource`, `controller_equip_item`). Each returns a typed scope and calls a shared **internal** implementation function, the same function the canonical command uses after its own authorization. The public canonical commands (`commands/character_state.py`, `commands/item_operations.py`, …) keep their `canon.edit` requirement **unchanged**. They are never widened, given an alternative capability parameter, or reachable with a controller scope. Controller commands accept only the allow-listed parameters (for example HP delta within bounds), never maxima, builds, ownership, location or another actor.

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
| Fictional/legal item ownership (`campaign.item_ownership`) and character location (`campaign.character_location_history`) | **Timeline narrative, shared (OD-20, Owner-approved)** | Unchanged tables; ownership writes are decoupled from possession (§3.1.1) |
| Item identification (`knowledge.item_identification`) | Knowledge, per knower | Unchanged |
| Encounter combatant state (ADR 0022) | Encounter, already campaign-owned through the encounter | ADR 0022 |

Different campaigns sharing a world and timeline **may pin different rulesets or versions**. Campaign creation gains no restriction.

#### 3.1.1 Ownership, possession and mechanical item state (OD-20: **Owner-approved**, 2026-11-02)

**Binding owner decision:**
- Character location and fictional/legal item ownership remain world/timeline narrative state.
- Mechanical item possession, inventory, equipment, attunement, charges, consumable quantities and other mechanical item state belong to the individual campaign.

| Concept | Storage | Scope | Who may change it |
|---|---|---|---|
| World item identity | `world.item_instances` (an entity) | World | Item-instance authoring. It stays a campaign-originated record under ADR 0020 decision 6, unchanged here |
| Item definition | `rules.item_definitions` (per ruleset version, or world homebrew) | Ruleset-wide or world | Rules and homebrew authoring (ADR 0023) |
| **Fictional/legal ownership** | `campaign.item_ownership`: `(timeline_id, item_instance_id)` gives `owner_entity_id`, with NULL meaning unowned. Its comment reads "current legal owner … distinct from who currently possesses it", and it has its own `last_event_id` | **Timeline narrative, shared** | The canonical narrative path: a causal event at a world time under the existing canonical authorization for shared timeline state, which is campaign `canon.edit` in a campaign on that timeline. **Never** a control assignment |
| **Possession and inventory**: holder, containing item, or the place where it lies | Today `campaign.inventory_entries`, keyed `(timeline_id, item_instance_id)`, holding at most one of holder, container or location. After P03-S, `campaign.campaign_inventory_entries` | **Campaign** | Campaign mechanical authority, plus OD-3 controller intents |
| **Mechanical item state**: quantity, charges, damage, equipped, destroyed, attunement | `campaign.item_state`, `item_attunements`; after P03-S, the campaign tables | **Campaign** | As possession |
| Ruleset interpretation | Adapter mechanics (ADR 0023) | The campaign's pinned version (§3.7) | Phase 19 engine (read-only) |

**Verified semantics.** The schema already separates legal ownership from possession (both table comments cite `DOMAIN_MODEL.md` §12.4). No holder relationship is relabeled as ownership.

**R19-11. Revision checks are split; there is no single item token.** Today `campaign.item_state.last_event_id` is "the item's single optimistic token: every operation writes it, so `expected_last_event_id` goes stale whichever table another operation changed" (`commands/item_operations.py` docstring). `assess_event` also reverses item effects by matching it. Under OD-1 and OD-20 that single token is replaced by two independent checks:

| State | Revision check | Locked as |
|---|---|---|
| Shared ownership (`item_ownership`) | `expected_ownership_event_id`, compared with `item_ownership.last_event_id`. A NULL row is the "no ownership row" sentinel | `item_ownership` row `FOR UPDATE`. When no row exists, the item instance `FOR UPDATE` is the anchor (this already exists in the lock order) |
| Campaign mechanical state (possession, item state, attunement) | `expected_campaign_item_event_id`, compared with `campaign_item_state.last_event_id` **for the route campaign**. Every campaign item operation writes it. Another campaign's operations never touch it | The route campaign's `campaign_item_state` row `FOR UPDATE` (the item instance anchor when absent) |

- **Lock order:** the item instance first, then the shared ownership row, then the campaign rows.
- **A mechanical-only operation** supplies and checks only the campaign token. A change made by another campaign, or to shared ownership, never makes it stale.
- **An ownership-only operation** (`change_item_ownership`) supplies and checks only the ownership token.
- **A mixed operation** (an explicit award or transfer *with* ownership):
  - supplies both tokens;
  - is authorized for both parts: campaign mechanical authority and the narrative ownership authority;
  - checks both tokens under lock;
  - commits both effects in **one** event and transaction, or neither. A stale token on either side refuses the whole operation and names which side is stale, without disclosing another campaign's values;
  - records one audit row per state family;
  - has its idempotency fingerprint include both tokens, the ownership intent, and the route campaign.
- **Corrections** (§3.3):
  - a mechanical effect is reversible only if the effect's own campaign token still equals the corrected event;
  - an ownership effect is reversible only if `item_ownership.last_event_id` still equals it;
  - a mixed event is corrected atomically: if either part is no longer reversible, nothing is reversed.
- **Regression (sequential A/E1, then B/E2, then correction of E1):**
  1. Event E1 in campaign A awards item X to K **with** ownership. It changes A's possession and the shared owner (X now owned by K).
  2. Event E2 in campaign B changes B's possession of X (equip or transfer within B).
  3. A's GM corrects E1. Both E1 effects are still reversible: A's campaign token is still E1, the ownership token is still E1, and E2 touched only B's rows. The correction reverts A's possession and the shared owner and leaves B untouched.
  4. **Variant:** if E2 had changed the shared owner (an ownership effect recorded from B), E1's ownership effect is no longer reversible, so the whole E1 correction is refused (`state_changed`, side `ownership`). B's mechanical rows are never read or disclosed.

**R19-12. No implicit ownership intent anywhere.** Today:
- `AwardRequest.set_owner: bool = True` (`api/item_authoring.py`) is forwarded as `award_item(set_owner=body.set_owner)`, and `award_item(…, set_owner=True)` defaults the same way (`commands/item_operations.py`).
- The portal's `AwardItemSection.tsx` posts `{expected_last_event_id, holder_entity_id}` **without** `set_owner`, so it changes ownership through the default.
- `ItemPlaySections.tsx` / `useItemDrafts.ts` already require an explicit choice ("There is no default: ownership is its own decision").
- The transfer path: `TransferRequest.transfer_ownership: bool = False` (`api/items.py`) → `commands/items.transfer_item_possession(transfer_ownership=False)` → `transfer_in_context(transfer_ownership=False)`.

P03-S changes every boundary:

| Boundary | Change | Omission behavior |
|---|---|---|
| `api/item_authoring.py` `AwardRequest` | Replace `set_owner: bool = True` with `ownership: Literal["unchanged","assign_to_holder"]`, **required** | Missing gives `422 ownership_intent_required`. No default |
| `api/items.py` transfer request | Replace `transfer_ownership: bool = False` with the same required `ownership` field | Missing gives 422. `unchanged` is the explicit choice for the current behavior |
| `commands/item_operations.award_item`, `transfer_in_context`, `commands/items.transfer_item_possession` | Keyword-only `ownership` parameter with **no default** | A missing argument is a `TypeError` at the call site, caught by mypy and tests |
| Internal callers (`commands/items.py`, the `commands/encounters.py` re-export noted in `commands/_shared.py`, tests and builders) | Each passes an explicit intent | — |
| Portal (`portal/src/api/items.ts` `runItemOperation`, `AwardItemSection.tsx`, `ItemPlaySections.tsx`, `useItemDrafts.ts`, `types/items.ts`) | Send the explicit `ownership` field. `AwardItemSection` gains the same required choice as `ItemPlaySections` | The client cannot submit without a choice |
| Idempotency fingerprints and audit | Include the intent | — |
| `assign_to_holder` | A mixed operation, with both authorizations and both tokens (R19-11). It is never available to controller intents | — |

**Character location** (`campaign.character_location_history`, `commands/movement.py`, `commands/travel.py`) stays shared narrative under its existing canonical authorization and temporal events. Controllers have no movement intent.

**Mechanical use never changes ownership.** Equip, unequip, consume, charge use, damage, repair, attune, end attunement, and campaign "destroyed" write campaign rows only.

**Where an unheld item lies (OD-22, UNRESOLVED, non-blocking).** `inventory_entries.location_id` and `container_id` record where an unheld item lies. Under OD-20 that becomes part of each campaign's possession, so an item may lie in different places in different campaigns. **No shared record of item whereabouts exists today or is planned.** OD-22 only asks whether the owner wants one. No design is proposed or approved.

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

#### 3.3 Mechanical events: authoring, visibility, explanations and corrections (R19-10)

**Classification is a closed, fail-closed registry (R19-14).** P03-S adds the lookup `campaign.effect_component_classes`, which maps each `target_component` code to exactly one class:
- `campaign_mechanical`;
- `shared_narrative`;
- `shared_knowledge`, governed by the knowledge-domain audience rules;
- `unclassified`.

`narrative.event_effects.target_component` gets a foreign key to this lookup **for new rows**. A code missing from the registry therefore cannot be written. Adding a code requires a migration that classifies it. **No code is ever narrative by default.**

The registry is seeded from the codes the current commands actually emit (verified at `6ea0e73`):

| Class | Codes | Emitted by |
|---|---|---|
| `campaign_mechanical` | `current_hit_points` | `commands/character_state.py`, `commands/encounters.py`, corrections |
| | `character_build_id` | `commands/character_builds.py`, corrections |
| | `condition_id` (apply and remove) | `commands/character_state.py` |
| | `current_amount` (resources) | `commands/character_state.py` |
| | `item_state` (quantity, condition, equipped, destroyed) | `commands/item_operations.py` |
| | `inventory_entries.location` (possession: holder, container or place) | `commands/item_operations.py` (award, transfer) |
| | `item_attuned`, `item_attunement_ended` | `commands/item_operations.py` |
| `shared_narrative` | `item_ownership` | `commands/item_operations.py` |
| | `current_location_id` | `commands/movement.py`, `commands/travel.py` |
| | `current_world_time_id` | `commands/campaign_clock.py` |
| | `party_membership` | `commands/party_members.py` |
| | `quest_status_id`, `objective_status_id` | `commands/quests.py`, `commands/quest_runtime.py` |
| | `organization_status_id`, `relationship_status_id` | `commands/relationships.py` |
| | `location_is_searched`, `location_is_destroyed`, `location_alarm_level`, `location_condition_notes`, `feature_is_destroyed`, `feature_condition_notes` | `commands/dungeon_state.py` (fixed field spec) |
| | `connection_status_id`, `hazard_status_id`, `interactable_status_id` | `commands/interactions.py` |
| `shared_knowledge` | `knowledge_learned`, `knowledge_public`, `belief_awareness_level`, `belief_confidence`, `belief_interpretation`, `belief_willing_to_share`, `awareness_level`, `party_discovered`, `discovered` | `commands/knowledge.py`, `knowledge_runtime.py`, `interactions.py` |
| | `identification_level` | `commands/items.py` (`identify_item`): per-knower knowledge, not mechanical |

The generic `POST /campaigns/{id}/events` (`api/events.py` → `commands/events._record_event_impl`) records **no** effects. So it has no caller-supplied codes.

**Disclosure rule for event effects (R19-14; universal rule Owner-approved 2026-11-03).** One rule governs every effect, whenever its code was classified:

> **A `campaign_mechanical` effect may be disclosed only after its classification and its origin-campaign attribution have both been explicitly reviewed and recorded.** A `shared_knowledge` effect may be disclosed only under the knowledge-domain audience rules, once the knower or audience that those rules need is recorded. A `shared_narrative` effect needs classification only.

An effect that does not yet meet its rule is **withheld**. A **released** effect is one that does. The rule applies equally to:
- codes in the seeded registry;
- codes classified later by a reviewed registry migration;
- `unclassified` codes, which are always withheld;
- legacy effects recorded before P03-S, with or without an event `campaign_id`.

The migration manifest (§3.8) lists every distinct `target_component` in existing `narrative.event_effects`, and a code not in the seeded registry is recorded as `unclassified`.

1. **Recorded attribution.** An origin-campaign attribution is a separate, additive record in `campaign.event_effect_attributions`, with:
   - the event, and the attributed campaign (or the knower or audience, for knowledge);
   - `basis`, and the reviewer or authorizing actor, the manifest where there is one, and the time.

   There are exactly two bases:
   - **`authorized_at_write`.** A command writing a mechanical effect after the G4 writer cutover records the origin in the same transaction. The origin is the route campaign whose authorization that command has just checked. This is the authoring rule below, recorded explicitly, not read back from the event's `campaign_id`. **(Owner-approved 2026-11-03.)** The effect is released as soon as that transaction commits. No routine human review of individual, properly authorized new mechanical events is required.
   - **`migration_reviewed`.** For every historical effect, meaning one that existed before the G4 writer cutover, a reviewer records the attribution in the restricted offline migration-review workflow (§3.8 step 2a). This holds even when the legacy event already has a `campaign_id`.

   An event row's `campaign_id` is **evidence only**. It may support a review, but it never satisfies the attribution requirement by itself. A campaign-less event that contains a classified mechanical effect authorizes no campaign to see it.
2. **Nothing is inferred.** Classification, origin campaign, knower and audience are never derived from any of these:
   - the effect's value or the event type;
   - timeline membership, or which campaigns share the timeline;
   - current or past character control, or other campaign relationships;
   - the creator or recorder of the event;
   - the session, party or encounter;
   - the request route.

   Recorded evidence may be shown to the reviewer, labeled as evidence only (§3.8 step 2).
3. **No application audience receives a withheld effect.** No application read returns any part of a withheld effect:
   - not its value, component name, identifiers, target or reference;
   - not its existence, and no metadata derived from it.

   This holds for players, controllers, event recorders and audience-mode calculations. It holds equally for world Owners, Editors and Reviewers, and for the `canon.edit` holders of every campaign: the campaign named by the event's `campaign_id`, other campaigns on the timeline, and every campaign on the timeline when the event has no `campaign_id`. No application role is an exception.
4. **Every surface.** The rule covers lists, counts, cause and correction links, explanations, the authoring view, correction previews and diagnostics, voids and corrections. It also covers every caller of those readers (event pages, session activity, summaries, the World Explorer) and calculation inputs. A withheld effect is omitted entirely: there is no placeholder (`unavailable`, `withheld` or similar), count or status for it. Effect counts and statuses are computed over the released effects that the caller may see.
   - **All effects withheld.** The event is excluded from every application list, count and link, and a direct read returns the existing single 404. This holds whether or not the event has a `campaign_id`.
   - **Mixed events.** An event with both withheld and released effects shows each audience only the released components that audience is independently authorized to see: the narrative/knowledge part under its rules, and a released `campaign_mechanical` part only to its attributed origin campaign. The withheld part adds nothing, including to the effect count.
   - **Preview, void and correct.** Any event with a withheld component returns the existing single 404 (`EventNotFoundError`) to every caller until every component is released. The 404 carries no reason, status, count, component name or diagnostic. The atomic rule ("nothing is reversed unless every effect is reversible") therefore never runs over a withheld effect, and no released part is reversed on its own.
   - **Writes and calculations.** An `unclassified` code cannot be written (the foreign key refuses it). No reader passes a withheld effect into a calculation or an as-of reconstruction.
4a. **`legacy_shared_state` never applies to event effects.** It is the label of the GM-only dual-read of legacy **character-state rows** (§3.8 step 6), and that independently authorized state read is unchanged. No event effect, explanation, preview, correction diagnostic or count is ever disclosed through it, so it cannot bypass this rule.
5. **After release.** Once the origin campaign is recorded, the effect follows that origin campaign's mechanical-effect visibility and correction authority in this section. No other campaign receives it.
6. **Raw inspection belongs to migration review only.** Adjudicating a withheld legacy effect may require reading its raw rows. That happens only in the restricted offline migration-review workflow (§3.8 step 2a), never through an application read.
7. **Preservation.** Withholding is a read rule only.
   - It never deletes, rewrites or moves effect or event rows, or their references.
   - Classification changes only the registry.
   - Attribution adds records and never modifies the raw effect row or the event's `campaign_id`.
   - **Attribution records are immutable to application paths.**
     - Ordinary event correction, voiding, editing, authoring views and idempotent replay never change, replace or delete an attribution record.
     - A replay returns the original outcome and writes no new attribution.
     - Changing a `migration_reviewed` attribution is possible only through a new reviewed record in the migration-review workflow, which supersedes the old one and keeps it in history.
   - Existing provenance and audit history are kept unchanged. Release or later correction adds to them and never replaces them.

**Event shape.** Shape is computed over **released** effects. An event is:
- **withheld** if every effect is withheld (item 4);
- **mechanical** if every released effect is `campaign_mechanical`;
- **narrative/knowledge** if every released effect is `shared_narrative` or `shared_knowledge`;
- **mixed** otherwise.

Any withheld effect additionally makes the whole event uncorrectable (404) until it is released (item 4).

The **same** classification drives writes (the campaign requirement), reads, lists, counts, cause and correction links, explanations, authoring views, correction previews and corrections. Every reader resolves a code's class **through the registry**. A code missing from a reader's local mapping fails closed to **withheld** (item 4 above).

**Registry coverage tests.**
- A unit test scans `src/dnd_ai/commands/` for emitted `target_component` literals and constants, and fails if any is missing from the seed.
- A database test proves the foreign key refuses an unregistered code.
- Reader tests feed `unclassified` effects, and seeded `campaign_mechanical` effects without a recorded attribution, on events with and without a `campaign_id`, alone and in mixed events (plan T48, T64, T70–T75). They prove that no application audience, **including the GM of the campaign named by the event**, receives any part of them on any surface.

**Authoring rule.** A new event with any mechanical effect must carry `campaign_id`. This is enforced by a deferred constraint trigger and by the commands. In the same transaction the command records the `authorized_at_write` attribution (disclosure rule, item 1) for its route campaign, which becomes the **origin campaign**. The trigger refuses a mechanical effect that has no matching attribution. Throughout this section, "origin campaign" means this **recorded** attribution, never the bare `campaign_id`.

**Visibility.** This is enforced in every reader *before* anything is serialized:

| Reader | Today (verified) | After P03-S |
|---|---|---|
| `queries/event_explanations.py` via `api/event_explanations.explain_for_caller`. Callers: campaign event page, GM event view (`api/event_corrections.py` GET), session activity (`api/sessions.py`), recent events (`api/summary.py`), World Explorer event detail (`api/world_explorer.py` `/world/events/{id}`) | Admits any event on the caller's own timeline; character, build, party, session and time references are audience-filtered | Narrative effects follow today's rules. **Mechanical effects are included only when they are released and the caller's route campaign equals their recorded origin campaign** (disclosure rule above), and the existing tier checks pass (for example `may_read_build`). Otherwise they are **omitted entirely**: no value, name, reference, `unavailable` placeholder, count or status. A **mechanical-only** event from another campaign is excluded from lists, counts, cause and correction links, and direct reads (404). A **mixed** event appears to other campaigns as its narrative part only |
| `queries/event_authoring.get_event_authoring_view` (GM event view, effects list) | Reads every `narrative.event_effects` row of the event | Same origin-campaign filter on effect rows. Other campaigns' GMs see narrative effects only |
| `campaign.effective_events()`-based resolution | Timeline-bounded | Mechanical resolution also filters on recorded origin = route campaign (§3.4). Withheld effects are excluded |
| `POST /campaigns/{id}/events` (`api/events.py`, `commands/events.py`) | Records events for the route campaign | Mechanical effects require `campaign_id` = route campaign. Recording a mechanical effect for another campaign is impossible |

**Corrections** (`api/event_corrections.py` preview, void and correct; `commands/event_corrections.assess_event`, `void_event`, `correct_event`; `domain/event_corrections.REVERSIBLE_COMPONENTS`):

1. **Authorization happens before any diagnostic.** Reaching an event requires that it is on the route campaign's timeline (today's rule), **and**:
   - every effect is released (disclosure rule above);
   - for a mechanical-only event, route campaign = recorded origin campaign;
   - for a mixed event, route campaign = recorded origin campaign **and** the narrative correction authority;
   - for a narrative-only event, today's rule.

   Otherwise the result is the existing single 404 (`EventNotFoundError`). No preview, reason, status, effect count or component name is returned.
2. **Diagnostics.** The preview reports reversibility per effect using only the event's own campaign tokens and the shared narrative tokens (R19-11). A reason never derives from another campaign's state, because no other campaign's rows are read.
3. **Atomic.** "Nothing is reversed unless every effect is reversible" (current rule) is kept for mixed events. Narrative and mechanical parts are reversed together in one transaction and one correcting event (`campaign_id` = origin campaign), or not at all. The correcting event's mechanical effects receive an `authorized_at_write` attribution to the **same** origin campaign, in the same transaction. Correction never moves an effect to another campaign. Any other mixed-event transaction records its mechanical attribution in the same way, under the same authorization boundary as its route campaign.
4. **Writes.**
   - Mechanical reversals go to the origin campaign's tables, never to legacy rows after that family's cutover.
   - Narrative reversals go to the shared tables.
   - Audit uses the existing correction audit rows, with the GM-only reason redacted. Idempotency uses the existing campaign store.
5. **Legacy mechanical events** (effects recorded before the G4 writer cutover, whether or not the event has a `campaign_id`, and whether the code was seeded or classified later). The disclosure rule above applies to them unchanged:
   - **Before the G4 cutover**, today's behavior is unchanged. The registry and the attribution records do not exist yet, and G4 switches no later than the first of G1–G3.
   - **After the G4 cutover**, until a `migration_reviewed` origin attribution is recorded:
     - the effect is withheld from every application audience, including the campaign named by the event's `campaign_id`, world roles, controllers and the recorder;
     - preview, void and correct return the single 404, with no reason or details;
     - there is no `legacy_shared_state` projection of the effect (item 4a).
   - **Once the attribution is recorded**, the event is read and corrected under that origin campaign's authority.
   - Attribution is never inferred (item 2).

#### 3.4 Resolution, including timeline inheritance within a campaign

A campaign's timeline is immutable (revision 030), so a campaign never moves between timelines. Inheritance therefore happens only through an explicit **lineage**:

1. **Local campaign row.** `resolve_campaign_mechanical_state(campaign_id, character_id, component)` returns the campaign's own row. It wins even when NULL ("explicitly none").
2. **No row.** The component is absent in this campaign. Calculation reports `missing_input`, and nothing is read from another campaign or from the legacy timeline tables. The only exception is the dual-read period (§3.8), labeled `legacy_shared_state`.
3. **Lineage seeding.** This is how a branch campaign inherits. When a campaign on a branch timeline is created, or later through an explicit command, a GM may record a lineage from a **source campaign on an ancestor timeline**. Seeding then runs once, explicitly and with an audit record:
   - it reconstructs the source campaign's mechanical state **as of the branch point** from that campaign's mechanical events in `campaign.effective_events(branch timeline)`, which is the existing bounded-ancestry function filtered to `campaign_id = source`;
   - **only proven branch-time values are used.** An administrative baseline (`last_event_id IS NULL`) cannot be proven to predate the branch point. This is the documented limitation in `character_build_resolution`. Such a component is reported `history_unavailable` and is **not** seeded;
   - it writes local rows with `origin = lineage_seeded`.

   Components that cannot be reconstructed are **not** seeded and are listed in the seed report. Examples: a condition or resource change made without an effect, or possession that is not event-linked.

   Lineage is never inferred: not from timeline ancestry alone, shared membership, or names. After seeding, the campaign's state is fully local. Later source changes never propagate (CLAUDE.md rule 7). Seeding is a cross-campaign operation. It is authorized, previewed, approved and disabled exactly as §3.6 describes. Until it is enabled, a campaign without a lineage starts without mechanical state.
4. **Active build.** `resolve_campaign_active_build(campaign_id, character_id) -> usable | incompatible_ruleset_version | out_of_scope | none`:
   - `usable`: a campaign row selects a build whose version equals the campaign pin and whose scope is `world_shared`, `legacy_unscoped`, or this campaign;
   - `incompatible_ruleset_version`: possible only for migrated or seeded rows;
   - `out_of_scope`: a seeded or migrated row names another campaign's private build. It is shown to GMs as a status only.

#### 3.5 Authorization and control

- Mechanical reads and writes are authorized in **the campaign whose state they touch**, which is always the route campaign. No ordinary command writes another campaign's state.
- Control assignments are campaign-scoped (§2). **The same character may be controlled by different players in different campaigns on the same timeline.** Their operations write different rows. The withdrawn "one controlling campaign per timeline" rule does not apply.
- Locking: operations take the character entity `FOR SHARE` (§2.8), then the campaign state rows they change `FOR UPDATE`. Attunement limits use an advisory lock keyed by `(campaign_id, character_id)`.
- Projection, discovery and revelation (P03-A) are unchanged. A campaign's mechanical state is visible only through that campaign's projections.

#### 3.6 Lineage seeding and cross-campaign copy (OD-21: **Owner-approved**, 2026-11-02)

These are **two distinct commands with separate authorization**. Both ship **disabled**. OD-21 approval does **not** authorize enabling either one (see Enablement below).

**Lineage seeding:** `request_lineage_seed` → `approve_lineage_seed`. It initializes a target campaign's mechanical state from an explicitly selected source campaign and branch point.

- **Explicit lineage.** The caller names the source campaign. Its timeline must be an ancestor of the target campaign's timeline (trigger), and the branch point is the target timeline's own. Lineage is never inferred and never implicit.
- **Bounded reconstruction (§3.4).** The source's mechanical events go through `campaign.effective_events(target timeline)`, filtered to the source campaign and bounded at the branch point. **Untimed administrative baselines (`last_event_id IS NULL`) are never used**: they cannot be proven to predate the branch point, so such a component is `history_unavailable`. This matches §3.4. The reviewed offline migration (§3.8) is a separate, explicit disposition and is not seeding. Each component gets one explicit outcome:
  - `seeded`;
  - `history_unavailable`: not reconstructable;
  - `incompatible_version`: the definition or build is not valid in the target version;
  - `out_of_scope_build`: another campaign's private build;
  - `target_has_state`: a conflict. The approver must explicitly choose `replace` or `skip`;
  - `not_selected`.

  Nothing missing is filled in silently.
- The preview is recorded first, then the target-campaign approval is a separate, explicit, recorded action (below). Rows are written with `origin = lineage_seeded`, and a `campaign_mechanical_lineages` row records source, branch point, approver and the report.

**Cross-campaign copy:** `request_mechanical_copy` → `approve_mechanical_copy`. It copies explicitly selected components of one character from a source campaign to a target campaign.

- **Per-component selection.** The caller chooses from: active build, hit-point fields, each condition, each resource, each item's possession, state and attunement.
- **Preview per component.** It shows the source value, the target's current value, and an outcome: `copy`, `conflict` (the target has a different value and needs an explicit overwrite), `incompatible_version` (for example a build or definition not in the target's pinned version, so copying between different ruleset versions skips it with a reason), `out_of_scope_build`, or `world_mismatch`.
- **One-time and no synchronization.** Later source changes have no effect. There is no subscription and no periodic job.
- Rows are written with `origin = cross_campaign_copy`.

**Authorization, shared by both commands.** This is engineering decision ED-11. The capability codes are new campaign capabilities:

| Requirement | Capability (campaign-scoped) | Notes |
|---|---|---|
| Source-campaign read for transfer | `mechanics.transfer_read` in the **source** campaign | Grants a truth-mode read of the source's **mechanical components only** for this purpose. It confers no general read of the source campaign |
| Target initialization (seeding) | `mechanics.seed` in the **target** campaign | — |
| Target write (copy) | `mechanics.copy_in` in the **target** campaign | — |
| Target approval | The approving action is taken by a holder of the target capability for that command | A separate recorded action. Whether the requester may also approve is fixed at enablement review |

- A caller must satisfy **both** source and target authorization. They are checked at request, re-checked at approval, and re-checked again under lock when the transfer is applied.
- **Ordinary control grants neither.** These codes are never in `CONTROL_ASSIGNMENT_CAPABILITIES` or `BUILTIN_RELATIONSHIP_CAPABILITIES`.
- **World roles grant neither.** A world Owner, Editor or Reviewer is not a campaign member (ADR 0020 decision 1). Campaign `canon.edit` alone does not imply them either.
- **The mapping of roles to these capabilities is not encoded.** It is set at enablement review.

**Audience and privacy.**
- Previews and transfers contain **mechanical components only**. They never contain:
  - player-private material (ADR 0016; the Phase 16 collaboration domain);
  - controller briefings, GM notes, portrayal, Knowledge or belief;
  - `knowledge.item_identification` (identification is per knower and is not copied);
  - narrative history, or anything outside the selected components.
- A preview is returned only to a caller who holds both authorizations, re-checked now.
- **Provenance contract (one definition):**

  | Where | Contains | Readable by |
  |---|---|---|
  | **Target event** (`mechanical_transfer_applied`, `campaign_id` = target) | `campaign_mechanical` effects with `previous_value` = the target's old value and `new_value` = the applied value, plus an opaque `transfer_request_id` | The target campaign's normal mechanical-event rules (§3.3). It carries **no** source campaign id, source fingerprint, or non-applied source value |
  | **Protected transfer record** (`campaign.mechanical_transfer_requests`) | Source campaign id, branch point or `as_of`, the selected components, the **source snapshot** (all selected source values, including skipped and incompatible ones), outcomes, conflicts, both fingerprints, requester, approver, timestamps | Only a caller who **currently** holds `mechanics.transfer_read` in the source **and** the kind's target capability (`mechanics.seed` or `mechanics.copy_in`) in the target. Re-checked on every read. A caller without both gets a non-disclosing refusal |
  | **Audit** | Ids, kind, status changes and actor. No values | Existing audit-history rules |

  No other surface exposes source values or the source campaign's identity. A target GM without source read sees that a transfer was applied, and its applied values through the target event, but not where they came from.
- No path uses the source campaign's audience to widen the target's, or the reverse.

**Integrity, idempotency and concurrency.**
- Each request and approval goes through the established command, idempotency and audit framework. `campaign.mechanical_transfer_requests` (planned for P03-S) holds: kind; source and target; character; components; branch point or `as_of`; a preview snapshot of mechanical facts; the source and target state fingerprints at preview; status `requested`, `approved`, `applied`, `rejected` or `expired`; requester and approver; and the idempotency keys.
- A replay with the same key returns the original result.
- Applying a transfer takes the character anchor `FOR SHARE` (§2.8) and the target campaign's affected rows `FOR UPDATE`. If the target's fingerprint differs from the preview's, the transfer is refused as `stale_preview` with a new conflict report. A concurrent target update is never overwritten.
- **The source is never mutated.** Tests compare source fingerprints before and after.

**Additional obligations before enablement:**
- **Source snapshot semantics.**
  - The preview stores a snapshot of the selected source mechanical facts together with the source and target fingerprints.
  - Approval and apply re-check, under lock, that **both** fingerprints are unchanged. A change on either side gives `stale_preview` and needs a new preview.
  - Apply writes exactly the previewed values. It never re-reads the source to pick up newer values.
- **Revoked-access replays.**
  - Request, approve and apply responses are **id-only receipts**. An idempotent replay returns the receipt, never preview content.
  - Reading a preview or transfer record re-authorizes the caller against both sides **now**. A caller who has lost `mechanics.transfer_read` in the source gets a non-disclosing refusal, even for their own earlier request.
  - Approval or apply after the requester's or approver's revocation fails.
- **Safe conflict responses.** Conflict reports are part of the protected transfer record and follow its read rule. An approval response is an id-only receipt, which includes no conflict detail.
- **Indirect paths cannot reach either operation.** Build approval or activation (P3d-2), item award and transfer, encounter damage and promotion (ADR 0022), the Foundry integration sync (`commands/integration.py`), quest rewards, Phase 18 import promotion and AI proposals never read another campaign's mechanical state or write it cross-campaign. They operate only on the route campaign. Tests cover each path.

**Enablement.** Both commands refuse with `feature_not_enabled` (a non-disclosing 404-equivalent) until all of the following are true:
1. their security tests pass: authorization matrix, audience and privacy, non-disclosure;
2. their compatibility tests pass: versions, scopes, conflicts;
3. their acceptance tests pass: T24, T32, T40–T45;
4. an explicit enablement review is recorded.

OD-21's approval does not satisfy item 4. **Ordinary P03-S isolation does not depend on either command.** Campaigns without a lineage start without mechanical state. Existing branch-inherited rows are handled by the **reviewed offline migration** (§3.8). That migration runs as operator tooling under the owner-reviewed manifest in a stopped-writer window. It is **not** a runtime command and grants or uses no runtime capability (`mechanics.*`).

#### 3.7 Builds and rulesets under isolation

- Activation writes `campaign_character_state.character_build_id` for the route campaign only.
- The build version must equal that campaign's pin (the X4 guard, now per campaign).
- `world_shared` builds are selectable by any campaign on the world with a matching version.
- `campaign` builds are selectable only by their origin campaign, on any timeline. **OD-6 is reconciled:** campaign-scoped builds are permitted without timeline restriction.
- Two campaigns on one timeline may activate different builds, including builds on different rulesets or versions.

**Shared item instances across ruleset versions (R19-8; engineering decision ED-12).** A world item instance has one fixed `rules.item_definitions` row, whose `ruleset_version_id` matched the creating campaign (`commands/item_instances._require_usable_definition`). Another campaign on the world may pin a different version. Today the item operations perform no version check. After P03-S the normal rule is:

| Operation in campaign C whose pin ≠ the item definition's version | Rule |
|---|---|
| Possession: award, transfer, place; ownership (narrative); `change_item_ownership` | **Allowed.** Version-neutral state of a world object |
| Equip and unequip; quantity consume; damage, repair, destroy | **Allowed** as campaign mechanical state. The flags are version-neutral |
| **Attune**; any operation that **creates or interprets** definition mechanics (charges maximum, attunement requirement) | **Refused** with `item_definition_version_mismatch` (400, non-disclosing about other campaigns), because the definition's rules belong to another version |
| **End attunement** (`end_item_attunement`) | **Allowed** (R19-16). Ending removes a campaign row and interprets no mechanics. It uses the normal campaign authorization (`canon.edit`, or a controller intent if OD-3 includes it), the campaign token and an event |
| Calculation (ADR 0023) | The item's equipment facts are `incompatible_ruleset_version`: they contribute nothing and raise a warning. No implicit mapping to a same-code definition in C's version. Any mapping is a separate future design |

A campaign whose pin equals the definition's version behaves as today.

**Quarantined incompatible state (R19-16).** The migration (§3.8) can bring a mechanically incompatible row into a campaign: an attunement, or item state with charges, whose item definition belongs to another version than the target campaign's pin. Apply copies such a row with `compatibility_status = 'quarantined_incompatible_version'`, a column on the campaign item tables. Quarantined rows:
- contribute nothing to calculation (ADR 0023);
- are shown to the campaign's GMs with a resolution prompt;
- **count toward the attunement limit** until resolved, so no limit is silently exceeded;
- block transfer of the item's possession while attuned, under the existing rule that an attuned item does not change holder.

Supported resolutions, each an audited command with an event in **that campaign only**:
- **end the attunement** (`end_item_attunement`), allowed as above;
- **acknowledge and keep quarantined** (`acknowledge_quarantined_item_state`), recorded with a reason;
- **clear quarantined item mechanical state** (`clear_quarantined_item_state`), which resets version-specific values such as charges to unset, through a campaign event.

None of these touches shared ownership or any other campaign. After resolution, a later possession transfer in that campaign follows the normal rules and still changes only that campaign's rows.

#### 3.8 Migrating existing timeline-only records (P03-S; additive; manifest-reviewed; no rolling deployment assumed)

The supported deployment is self-hosted Docker Compose on one host (ADR 0012, ADR 0013). This protocol **does not assume a rolling production deployment**. Every write cutover happens in a **stopped-writer window**:
- the API service is stopped, or put into a refusing maintenance mode;
- the worker and Foundry sync are stopped, if present.

1. **Schema (additive).** Create:
   - the empty campaign tables;
   - `campaign_mechanical_lineages`, `mechanical_state_migration_records`, `effect_component_classes`, `event_effect_attributions` (§3.3);
   - **`campaign.campaign_mechanical_initializations`** (`campaign_id`, `character_id` or `item_instance_id`, `component_family`, `origin`, `initialized_at`).

   The initializations table makes an explicitly **empty** state (for example "no conditions") distinguishable from "never initialized". Row-set families (conditions, resources, inventory, attunements) are authoritative for a campaign once their initialization row exists. Absent rows then mean none, and an absent initialization means not initialized.

   Data classification: every new TEXT or JSONB column is registered in `domain/data_classification.COLUMN_CLASSES`, and audit structural fields in `AUDIT_STRUCTURAL_FIELDS`. Examples: condition `source_description` (GM-only), lineage and migration `reason` (GM-only), transfer-request preview (GM-only).
2. **Manifest** (read-only, on a restored copy at snapshot S0). The unit of review and application is the **family**: one target campaign, one subject, one component family, with its complete membership:

   | Family | Subject | Members | Dependencies checked at apply |
   |---|---|---|---|
   | `character_core` | (character) | The `character_state` row (HP, maximum, temporary, exhaustion, death saves, initiative, transformation, `character_build_id`) | The build exists and is usable by the target (else the build field is quarantined and shown to GMs); the character is in the target's world |
   | `conditions` | (character) | **All** `character_conditions` rows of `(timeline, character)` | Each condition is in the target's pinned version (else the family needs an explicit replacement) |
   | `resources` | (character) | **All** `character_resources` rows | Same version rule |
   | `item` | (item instance) | The `item_state` row, the `inventory_entries` row, and **all** `item_attunements` rows of the item | The holder is in the world; the attunement holder equals the possessor; the per-(campaign, character) attunement limit holds across all families applied for the campaign; version compatibility (incompatible rows are quarantined, §3.7) |

   For each family the manifest records:
   - every member row with its content hash;
   - the **membership hash**, a hash over the sorted member keys and hashes;
   - the classification (`single_campaign`, `multi_campaign`, `no_campaign`, `branch_inherited`);
   - the reviewed disposition.

   The manifest also lists:
   - every campaign ever created on each timeline, including archived ones;
   - every legacy event with `campaign_mechanical`, `shared_knowledge` or `unclassified` effects, **with or without** a `campaign_id`, for attribution;
   - every distinct effect code (§3.3), with the unknown codes reviewed under step 2a;
   - evidence, labeled as evidence only.

   `item_ownership` and `character_location_history` are excluded (OD-20).

   **2a. Migration review of withheld legacy effects (R19-14).** This restricted offline process is the only place where withheld effect contents (§3.3) may be read. It covers unknown codes **and** every legacy effect whose class needs attribution.
   - **Where:** the operator manifest tooling, on the restored copy at S0. It is not an application route, command or query, and holding campaign `canon.edit` or a world role grants nothing here.
   - **What the reviewer sees:** each unknown code, and each legacy effect needing attribution, with its rows (event id, the event's `campaign_id` or none as evidence, timeline, value, event type and time).
   - **Where the extract lives:** with the manifest, as a restricted operator artifact. It is never written to an application-readable table and never served by the API.
   - **Outcome:** for each code, the reviewer either records a classification, which ships as a reviewed registry migration, or leaves the code `unclassified`. Classification alone releases nothing.
     - For each `campaign_mechanical` effect, whether its code was seeded or classified here, the reviewer records a verified **origin campaign** (`basis = migration_reviewed`), or none. This applies whether or not the event row has a `campaign_id`.
     - **Proposals and bulk review (Owner-approved 2026-11-03).**
       - The tooling may **propose** mappings from evidence, for example an event's existing `campaign_id`. A proposal never establishes authorization by itself.
       - The reviewer may approve proposals in bulk when the evidence supports them. Every exception is listed explicitly in the approval: a conflicting, missing or inconsistent piece of evidence, or a record removed from the batch.
       - A bulk approval is recorded per effect, with the batch id, the evidence basis, the reviewer and the time.
     - **Ambiguous effects stay withheld.** A genuinely ambiguous historical effect gets no attribution. It stays withheld until a later review resolves it. Nothing is guessed.
     - For each `shared_knowledge` effect, the reviewer records the knower or audience it needs.
     - Attributions are additive records (§3.3 disclosure rule, items 1 and 7), and none is inferred (item 2).
   - **Effect on reads:** an effect stays withheld from every application audience until its classification and every attribution it needs are applied (§3.3). An unattributed `campaign_mechanical` effect is never shown through `legacy_shared_state` (§3.3 item 4a).

   **Dispositions are per family, never per row.**
   - `copy` to listed campaigns.
   - `leave_unmapped`.
   - `reviewed_replacement`: the reviewer supplies the complete member set to write, including an explicitly empty set, with a reason.
   - `empty_confirmed`: the legacy family has no rows, and the reviewer explicitly confirms "this campaign starts with none".

   For `branch_inherited`, materializing the value that resolves today is a **distinct, explicit disposition** (`materialize_inherited`, reviewer-acknowledged as an unproven administrative baseline). It is never runtime seeding. A partial review of a family's members is **not** a disposition. The family stays `pending`.
3. **Manifest-to-live validation** (inside the stopped-writer window). For every family with a disposition, the validator recomputes the **membership hash and every member hash** on the live database. Any added, changed or deleted member, or a failed dependency, makes the **whole family** `pending_drift`:
   - nothing from it is written;
   - **no initialization marker is created**, so the campaign keeps the GM-only legacy fallback for that family;
   - it is returned for re-review.

   Families are never partially applied. A deleted legacy member is recorded and never resurrected.
4. **Apply** (operator tooling, not a runtime command; one transaction per family). For each validated family:
   - write exactly the reviewed member set (or the reviewed replacement), with `origin = migrated_from_timeline`;
   - quarantine incompatible members (§3.7);
   - write the family's `campaign_mechanical_initializations` row **in the same transaction**;
   - write the `mechanical_state_migration_records` entry, keyed by `(manifest_id, family_key, membership_hash)`.

   **Retry is idempotent:** a family whose record exists with the same membership hash is skipped. The same family key with a different hash is refused for re-review. An `empty_confirmed` or empty `reviewed_replacement` writes only the initialization row. A family with no disposition writes nothing and stays uninitialized. Event attributions are applied with their families' group.
5. **Cutover groups.** Readers move first (dual-read), then writers move in the stopped-writer window. Each group's legacy tables get a write-block trigger at its writer cutover.

| Group | Tables | Writers | Readers |
|---|---|---|---|
| G1 Character core | `character_state` (HP, build, exhaustion, …) | `commands/character_builds.py`, `character_state.py` (HP), `encounters.py` damage, which **also gains `last_event_id`**: the encounter-token repair is assigned to P03-S; `event_corrections.py` for these components; `integration.py` combat sync | `queries/character.py`, `character_sheet.py`, `character_builds.py`, `character_build_resolution.py`, `encounter_preparation.py`, `event_explanations.py`, `event_authoring.py` |
| G2 Conditions and resources | `character_conditions`, `character_resources` | `character_state.py`, `event_corrections.py` | `queries/character.py`, explanations, authoring view |
| G3 Items | `item_state`, `inventory_entries`, `item_attunements` (the token split, R19-11; intents, R19-12) | `item_operations.py`, `items.py`, `event_corrections.py` item components; `api/item_authoring.py`, `api/items.py` | `queries/inventory.py`, `item_authoring.py` (including party inventory, `GET /campaigns/{id}/parties/{party_id}/inventory` in `api/item_authoring.py`), `world_explorer.py`, `api/characters.py` |
| G4 Event visibility | — | `commands/events.py` (campaign required) | §3.3 readers. **This group switches no later than the first of G1–G3**, so that no campaign-scoped value is ever readable cross-campaign |

   **G4 attribution readiness gate (Owner-approved 2026-11-03).** Before the G4 cutover, the operator tooling produces an **attribution readiness report** over every historical effect that needs attribution. The report:
   - gives counts and identifiers per timeline and per campaign for four outcomes: **reviewed** (attribution recorded), **withheld** (not reviewed, or no attribution approved), **ambiguous** (explicitly left unattributed) and **failed** (validation or apply errors);
   - lists the exceptions reported in each bulk approval;
   - is a restricted operator artifact, like the step 2a extract.

   G4 proceeds only with the operator's **explicit, recorded approval** of the report. If any effect is withheld, ambiguous or failed, the approval must say explicitly that the cutover proceeds with those effects withheld. Failed records are never released by proceeding. Without an approval, the cutover does not run.

6. **Authorization-safe legacy fallback (dual-read).**
   - A campaign subject with **no** initialization row for a family may fall back to the legacy timeline row **only** for callers holding `canon.edit` in that campaign, labeled `legacy_shared_state`, read-only.
   - Players, controllers and audience-mode calculations get "no mechanical state", never legacy values, because those values may come from another campaign's play.
   - Calculations from legacy rows are GM-only and never labeled rules-validated.
   - This fallback covers **character-state rows only**. It never discloses event effects, explanations, previews, correction diagnostics or counts. Those follow the §3.3 disclosure rule.
7. **Rollback** (qualified the same way everywhere):
   - **Code rollback** is possible while the schema is backward compatible, that is, before a group's write-block trigger.
   - **Data rollback before a group's writer cutover:** drop or empty that group's new rows. Legacy rows are untouched.
   - **After a group's writer cutover, once any campaign row has diverged:** the only data rollback is **restoring the backup taken in that group's stopped-writer window immediately before cutover**. This discards every write made after it. The backup is verified restorable before cutover (the Phase 17 runbook).
   - A reverse copy into legacy tables is not a supported rollback.
   - Legacy tables are never dropped in Phase 15.

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
| Commands | `commands/encounters.py` (combat damage) | The encounter's campaign row, and set `last_event_id`. **The encounter state-token repair is owned by P03-S (G1)**, not R19-P4b. Campaign-less encounters may not write mechanical state after cutover: they are refused explicitly, and existing ones are listed in the manifest |
| Commands | `commands/event_corrections.py` (`assess_event`, `void_event`, `correct_event`), `domain/event_corrections.py` (`REVERSIBLE_COMPONENTS`) | Origin-campaign authorization before diagnostics; split tokens; atomic mixed corrections; legacy campaign-less refusal (§3.3) |
| Commands | `commands/events.py` (`_insert_event_row`, `_record_event_impl`) | Campaign required for mechanical effects |
| Commands (new) | `lock_controller_operation_scope` and named controller intents (§2.8) | Bounded controller path. Canonical commands unchanged |
| Commands | `commands/item_operations.py`, `commands/items.py` | Campaign item state, possession and attunement; per-campaign limits. **OD-20:** `award_item` loses its implicit `set_owner=True` default; `transfer_in_context(transfer_ownership)` and any explicit ownership request write a separately authorized narrative effect on the shared `item_ownership`. Phase 15 owner sign-off (behavior change) |
| Commands (new) | `change_item_ownership` | A dedicated temporal narrative command for fictional/legal ownership (OD-20). Never available to controllers |
| Tables | `campaign.item_ownership`, `campaign.character_location_history` | **Unchanged and shared** (OD-20). Not migrated |
| Commands | `commands/integration.py` (Foundry sync via `_resolve_combat_turn_impl`) | Writes the paired campaign's rows only |
| Resolvers | `queries/character_build_resolution.py` | Replaced by `resolve_campaign_active_build`. Branch ancestry is used only during lineage seeding |
| Queries | `queries/character.py`, `character_sheet.py`, `character_builds.py`, `encounter_preparation.py` | Read campaign rows (dual-read during migration) |
| Queries | `queries/inventory.py`, `item_authoring.py`, `world_explorer.py` (item state, possession) | Campaign rows. World Explorer item cards show possession only for the route campaign |
| Queries/APIs | Party inventory: `GET /campaigns/{id}/parties/{party_id}/inventory` in **`api/item_authoring.py`** (not `api/parties.py`), via `queries/inventory.py` | Campaign rows |
| Queries/APIs | Events: `queries/event_explanations.py`, `queries/event_authoring.py`; `api/event_explanations.py`, `api/event_corrections.py` (GET, preview, void, correct), `api/events.py` (POST), `api/sessions.py` (session activity), `api/summary.py` (recent events), `api/world_explorer.py` (`/world/events/{id}`) | §3.3 visibility and correction rules |
| APIs | `api/item_authoring.py` (`AwardRequest`, `_RUNTIME/award` and other operations, party inventory), `api/items.py` (transfer) | Required `ownership` intent; split tokens (§3.1.1) |
| Domain | `domain/data_classification.py` (`COLUMN_CLASSES`, `AUDIT_STRUCTURAL_FIELDS`) | Register every new TEXT/JSONB column and audit field |
| Tables (new) | `campaign.effect_component_classes`, plus a foreign key from new `narrative.event_effects` rows; `campaign.event_effect_attributions` (additive; registered in `data_classification`) | Fail-closed effect classification and the universal disclosure rule (§3.3) |
| Columns and commands (new) | `compatibility_status` on campaign item tables; `acknowledge_quarantined_item_state`, `clear_quarantined_item_state`; `end_item_attunement` allowed across versions | Quarantine and resolution (§3.7) |
| Portal | `portal/src/api/items.ts` (`runItemOperation`), `components/AwardItemSection.tsx`, `components/items/ItemPlaySections.tsx`, `components/items/useItemDrafts.ts`, `types/items.ts`; event explanation, correction and inventory views | Explicit ownership intent; split tokens; render omitted mechanical effects without placeholders |
| APIs | `api/character_state.py`, `api/character_builds.py`, `api/characters.py` (sheet, inventory, attunements), `api/items.py`, `api/encounters.py`, `api/integration.py` | Route campaign = state campaign. Response shapes unchanged, plus a `state_origin` field where useful |
| New commands | `request_lineage_seed` / `approve_lineage_seed`; `request_mechanical_copy` / `approve_mechanical_copy`; table `campaign.mechanical_transfer_requests`; capabilities `mechanics.transfer_read`, `mechanics.seed`, `mechanics.copy_in` | OD-21 Owner-approved. **Disabled until the enablement conditions in §3.6 are met**; not required for P03-S isolation |
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
  - **Inventory independence:** K carries a rope and three potions in A, while in B K carries nothing. B's GM awarding K a sword does not appear in A (T36).
  - **Ownership without transfer:** A's GM records that the sword now legally belongs to K (`change_item_ownership`). The shared owner changes for A and B, but nobody's possession changes in either campaign (T37).
  - **Use without ownership change:** P1 drinks a potion in A. A's quantity drops; the legal owner and B's state are unchanged (T38).
  - **Controller refused:** P1 tries to change the sword's legal owner or K's location. Refused, non-disclosing (T39).
- **Different versions, shared timeline.** A pins 5e 2024; B pins another version.
  - Each activates a build of its own version, and each is evaluated under its own adapter and support level.
  - Neither sees `incompatible_ruleset_version`.
  - Copying K's active build from A to B is refused for version mismatch and listed.
- **Branch lineage.** Timeline T2 branches from T, and campaign C is created on T2.
  - Once seeding is enabled (§3.6), a caller holding `mechanics.transfer_read` in A and `mechanics.seed` in C requests a seed, reviews the preview, and approves it. C is then seeded from A's mechanical history bounded at the branch point (T40). The report lists non-reconstructable components. Later changes in A never reach C. A caller without A's read authority is refused, non-disclosing (T41).
  - Without a lineage, C starts with no mechanical state.
- **Cross-campaign copy** (only after enablement, §3.6). B's GM, holding `mechanics.transfer_read` in A and `mechanics.copy_in` in B, copies K's conditions from A after a preview and approval. An event is recorded in B, and A is unchanged. Copying from a different-version campaign skips incompatible components with reasons (T42). Before enablement, the request is refused (T45).
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

P03-C and P03-S may land in either order. The port's intermediate behavior is specified in the plan's §5.1 (phases a, a+C, a+S, b).

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
  - Cross-campaign copy and lineage seeding (once enabled) write the target only, require both authorizations, refuse stale previews, and replay idempotently. Before enablement they refuse (T40–T45).
  - OD-20: inventory independence, ownership without transfer, use without ownership change, controller refusal (T36–T39).
  - Event correction restores only the event's campaign.
  - A campaign-less encounter cannot write mechanical state after cutover.
  - Mechanical events without a campaign are refused.
  - Manifest: `single_campaign` rows are proposed for their campaign; `multi_campaign` rows stay legacy until reviewed.
  - Rollback before writer cutover leaves the legacy tables byte-identical.
- **Clock.**
  - A dated assignment at clock = start is in effect; at clock = end it is not; after the clock is unset it is undetermined.
  - An ongoing assignment is unaffected by the clock.
  - A branch campaign does not inherit assignments.
- **R19-10 to R19-13 (this revision).**
  - A mechanical-only event of campaign A is absent from B's lists, counts, links, detail, preview and correction (404).
  - A mixed event shows B only its narrative part.
  - B's GM cannot preview or correct A's mechanical effects.
  - The A/E1 → B/E2 → correct-E1 regression (§3.1.1), including the ownership variant.
  - An award without `ownership` is rejected with 422, and the portal sends explicit intent.
  - A controller intent succeeds without `canon.edit`, while the canonical command still refuses the controller.
  - Manifest-to-live validation is per family: any drift makes the whole family pending, with no marker (see the third-review items).
  - An explicitly empty condition set does not fall back to legacy rows.
  - A player never sees `legacy_shared_state` values.
  - Attunement of another version's item is refused, while possession and equip are allowed.
  - Legacy mechanical events, with or without a `campaign_id`, are withheld and refused for correction (404) after cutover until attribution is reviewed and recorded (universal rule, T48).
- **Third review (R19-14 to R19-16).**
  - The registry covers every emitted code; an unregistered code is refused at write.
  - Campaign A ending K's attunement to X leaves B's attunement row, events and counts unchanged; the event is invisible to B and B cannot correct it.
  - A family drifting after S0 (member added, changed or deleted) is entirely `pending_drift`, with no marker.
  - A partially reviewed family is not applied.
  - `reviewed_replacement` and `empty_confirmed` write exactly what was reviewed.
  - A retry is idempotent.
  - A quarantined incompatible attunement contributes nothing, counts toward the limit, and can be ended in the target campaign only. A later transfer in that campaign changes only its rows, and legal ownership is unchanged.
  - Seeding never uses untimed baselines.
  - Provenance follows the single contract.
- **Residual R19-14 (withheld unclassified effects).**
  - An `unclassified` effect on an event of campaign A gives nothing to A's GM, A's players and controllers, or B's GM. If every effect is unclassified, the event is absent and a direct read returns 404 (T70).
  - On a campaign-less event, neither an `unclassified` effect nor an effect whose code the seeded registry classifies as `campaign_mechanical` gives anything to any GM or world role, and neither is labeled `legacy_shared_state`, until reviewed attribution (T71).
  - A mixed event shows each audience only the released parts it is independently authorized to see, with counts over those parts only. Preview, void and correct return 404 to every caller (T72).
  - The GM of another campaign sharing the timeline receives nothing derived from the withheld effects (T73).
  - Raw withheld contents are readable only in migration review (§3.8 step 2a). Classification alone releases nothing. A `campaign_mechanical` effect stays withheld until its origin campaign is reviewed and recorded, then follows that campaign's rules only. A `shared_knowledge` effect stays withheld until its knower or audience is recorded. Nothing is inferred, and raw rows, provenance and audit history are preserved (T74).
  - On a timeline shared by A and B, the GMs of both campaigns receive nothing from an unattributed `campaign_mechanical` effect, seeded or later classified, including through `legacy_shared_state` (T75).
  - Disclosure never depends on when a code was classified: one rule for seeded, later-classified and legacy effects. `legacy_shared_state` applies only to independently authorized character-state reads.
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

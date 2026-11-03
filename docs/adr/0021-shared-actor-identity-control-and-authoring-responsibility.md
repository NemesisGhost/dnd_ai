# ADR 0021: Shared actor identity, campaign control, and authoring responsibility

- **Status**: Proposed (R19-P0 architecture deliverable, 2026-11-02; awaiting independent architecture review and owner acceptance). The six product decisions it implements were approved by the owner and are not reopened here; the mechanisms below are proposals until this ADR is accepted.
- **Date**: 2026-11-02
- **Amends**: [ADR 0020](0020-scoped-system-world-and-campaign-roles.md) decision 6, only for player-character identity (the `player_character` entry in `CAMPAIGN_ORIGINATED_TYPES`); see Decision 6 below. ADR 0020's three-scope model is otherwise unchanged.
- **Implemented by**: Phase 15 checkpoints P03-A, P03-B and P03-C ([PLANv2.md](../PLANv2.md) §8, 15H). Phase 19 consumes the contracts ([R19_FOUNDATION_IMPLEMENTATION_PLAN.md](../R19_FOUNDATION_IMPLEMENTATION_PLAN.md) §5.1) and does not implement them.
- **Related**: [ADR 0002](0002-use-class-table-inheritance.md), [ADR 0003](0003-separate-world-timeline-and-campaign.md), [ADR 0007](0007-separate-knowledge-from-truth.md), [ADR 0016](0016-data-classification-and-private-data-handling.md), [ADR 0022](0022-creature-templates-combatants-and-promotion.md), [ADR 0023](0023-rules-engine-calculation-validation-and-source-authorization.md).

## Context

The owner has confirmed that a Character is the common identity of an individual actor: a person, monster, animal, companion or other creature. Being a PC or an NPC describes who controls the actor in a campaign. It is not an immutable kind. A player may control a monster. The same world character may have different controllers in different campaigns. Statistics may be partial or absent. A control change preserves the UUID and every reference and history.

The repository does not represent that today. What exists at `414d3b3`/`defe3f7`:

| Concern | Current implementation | Gap |
|---|---|---|
| Identity | `core.entities` → `character.characters` (species, size, origin) → `character.npcs` (`detail_level`) or `character.player_characters` (`player_user_id`, unset by current commands). `src/dnd_ai/persistence/tables/characters.py`. | The subtype marker is treated as identity and as an eligibility switch. |
| Kind-driven eligibility | `_BUILDABLE = {"npc", "player_character"}` (`commands/character_builds.py:57`); session `PARTICIPANT_KINDS` (`domain/session_participation.py`); NPC portrayal requires the NPC subtype (`commands/npc_portrayal.py`); portal `CharacterManageLinks.tsx`. | A player-controlled monster is rejected or mis-routed because of its old kind. |
| Human-to-character relationships | `security.membership_character_relationships`: membership, character, type (`owner`, `primary_controller`, `co_controller`, `portrayer`, `viewer`, `observer_approved_viewer`, `former_controller`), optional `timeline_id`, fictional `effective_period` from world-time endpoints, `granted_by_membership_id`, `granted_at`, `expires_at`, `revoked_at`. Capabilities come from `BUILTIN_RELATIONSHIP_CAPABILITIES` (`domain/access.py`). | No uniqueness of a primary controller. Rows confer only read tiers and knowledge perspective. `character.control`, `character.edit_mechanical_state`, `character.edit_narrative` and `character.interact` exist as capability codes but are deliberately withheld. No row records that a human has been *assigned* play control. |
| Documented controller table | `character.character_controllers` is described in `DATABASE_MODEL.md` §7.3 and `DOMAIN_MODEL.md` §8.4. | It has never been built. No table, migration or code exists. |
| Canonical authoring | `domain/record_authoring.py`: world definitions need campaign `canon.edit` **and** a world capability (ADR 0020 decision 6), except `CAMPAIGN_ORIGINATED_TYPES = {"player_character", "item_instance"}`, which need campaign `canon.edit` only. Characters have no owning-campaign column. | Player-character identity is world canon edited without world authority, on the basis of its subtype. |
| Builds | `character.character_builds` (character, ruleset version, label; immutable; no edit command) and children. Created by `create_character_build` with campaign `canon.edit` only, validated against the campaign's pinned ruleset version. Activated per timeline by `activate_character_build` (`campaign.character_state.character_build_id`, keyed `(timeline_id, character_id)`). | Builds record no origin campaign or author. Activation does not check that the build's ruleset version matches the activating campaign's. Builds require an `active` (published) character. |
| Runtime state | `campaign.character_state`, `character_conditions`, `character_resources`, all keyed by `(timeline_id, character_id)`. | Two campaigns may share a timeline (`campaign.campaigns.timeline_id` is not unique) and may pin different ruleset versions, so they share one active build and one runtime state. |
| Portrayal | `character.npc_portrayal_profiles`, FK to `character.npcs.npc_id` `ON DELETE CASCADE`, append-only. | Removing an NPC marker would delete portrayal history. |
| Revelation and public profile | Discovery is derived from roles, relationships and grants. No reveal workflow. Normal reader DTOs omit appearance and background. | Covered by P03-A (investigation §D6.3–D6.5). |

The Phase 14/15 app-interaction investigation (§D6, packages P03-A/B/C) analysed these dependencies and proposed defaults. This ADR records the architecture those packages must implement, so that P03-B/C schema work and Phase 19 build on one actor model.

## Decision

### 1. One actor identity

1. The individual actor is `core.entities` + `character.characters`. Its UUID never changes because of control, kind, template, build, promotion or campaign. No phase creates a second actor or creature identity table (ADR 0022 keeps creatures inside this identity).
2. `character.npcs` and `character.player_characters` become **legacy compatibility markers**. They may still be read as a display hint and to keep old routes and payloads working. They never decide authorization, build eligibility, session participation, control or authoring responsibility once P03-C has moved each consumer. A character may carry no marker, either marker or, during migration, both. No code may convert one marker into the other to "change" a character between PC and NPC.
3. Mechanics are optional. A character with no build, or a build that the ruleset adapter reports as unsupported or incomplete, is valid and fully usable for identity, relationships, inventory, knowledge, portrayal and control. A missing build is an empty state, never grounds to invent statistics or to grant authoring.
4. Eligibility is by capability, not kind. Build, session-participation, encounter-participation and portrayal eligibility are resolved from the actor's lifecycle, world, and the caller's authority. The `_BUILDABLE` and `PARTICIPANT_KINDS` kind lists are replaced by "any lifecycle-eligible character of the world" (P03-C). Historical participation role labels already stored remain as recorded.

### 2. Campaign control assignments (owner Decision 1)

1. **Single authority.** Human play control is stored in `security.membership_character_relationships`. The never-built `character.character_controllers` design is **retired, not built**. Non-human operators are not controllers:
   - AI portrayal uses the AI domain's assignments;
   - Foundry and other clients act through their own principals on behalf of an authorized human or GM;
   - a GM operating an uncontrolled actor uses GM authority.

   `DATABASE_MODEL.md` §7.3 and `DOMAIN_MODEL.md` §8.4 are corrected accordingly (follow-up, §Consequences).
2. **Assignments are explicit rows, distinct from legacy relationships.** P03-B adds to `security.membership_character_relationships`:
   - `is_control_assignment BOOLEAN NOT NULL DEFAULT false`. It is permitted only for types `primary_controller` and `co_controller` (CHECK plus trigger on the type code).
   - `campaign_id UUID NOT NULL`, denormalized from the membership, immutable, and verified by the existing scope trigger. This is needed for constraints.
   - `revoked_by_membership_id` and `revocation_reason`, for auditable revocation.

   Only rows with `is_control_assignment = true` confer control. Existing `primary_controller`/`co_controller` rows keep their current read and perspective capabilities and confer **no** new control. Owner Decision 1 forbids automatic control from existing relationships, so legacy rows are promoted only through the reviewed manifest in §7.
3. **One primary per campaign.** A partial exclusion constraint allows at most one live primary assignment per `(campaign_id, character_id)` with overlapping fictional `effective_period`, where `is_control_assignment AND revoked_at IS NULL`. Real-time expiry is checked by the resolver, not the constraint. The constraint follows the `btree_gist` pattern of `campaign.party_memberships`. Any number of co-controller assignments may exist. Assigning a new primary closes the prior one (`revoked_at`) in the same transaction. Rows are never overwritten.
4. **Different campaigns, different controllers.** Assignments are campaign-scoped by construction (membership → campaign). The same character may have a primary controller in campaign A, a different one in campaign B, and none in campaign C.
5. **GM default.** When no live player assignment exists for a character in a campaign, the actor is GM-operated. That is GM authority (`canon.edit` and the bounded operations it already holds), not a row. Read models report `controller: none (GM-operated)`.
6. **Effective-time semantics.** Two clocks, kept separate:
   - *Fictional effectiveness:* the existing `effective_period` (world-time endpoints, half-open). It answers "who controlled this actor at world time T" for history.
   - *Real-time authority:* `granted_at`, `expires_at`, `revoked_at`. It answers "may this request act now".

   A request is authorized only if the assignment is not revoked, not expired, and its `effective_period` contains the campaign's effective clock. When a campaign has no clock, the DEF-007 no-clock rule applies; until DEF-007 records it, an open-ended period counts as effective. Time-bounded possession and encounter- or session-scoped control are future extensions and are not built in P03-B.
7. **Control confers bounded operations only.** A live assignment confers the capabilities in a new closed matrix, `CONTROL_ASSIGNMENT_CAPABILITIES`, separate from `BUILTIN_RELATIONSHIP_CAPABILITIES`:
   - `character.discover`, `character.view_summary`, `character.view_full` (the controller mechanical projection), `character.view_inventory`;
   - `character.control`;
   - `character.edit_mechanical_state`, limited to the named own-actor operations on the P03-B allow-list (owner decision OD-3 in the plan's register).

   It does **not** confer:
   - `canon.edit`, world capabilities, `access.manage`;
   - `character.view_private` (GM secrets), campaign briefings of other actors;
   - `character.view_knowledge` (perspective), build creation, portrayal authoring, or revelation.

   A knowledge perspective for the controlled actor is a **separate** grant that the assigning GM may add explicitly. It is a separate row with its own revocation. Revoking control does not revoke it, and vice versa.
8. **Co-controllers.** A co-controller holds the same bounded play operations as the primary (default, owner-confirmable as OD-2), and nothing else:
   - no assignment management;
   - no build proposals unless separately delegated (§4);
   - no perspective unless separately granted.

   Revoking the primary leaves co-controllers in place. Nobody is promoted automatically. The read model shows "no primary controller" so the GM can act.
9. **Assignment management** is a new campaign capability, `character.assign_control`. It is separate from `access.manage` and from `canon.edit`, held by default by `campaign_owner` and `gm`, with `assistant_gm` opt-in (OD-4). The assignee must be an active membership of the campaign. Assignment, revocation and replacement are audited commands with durable idempotency (`assign_character_control`, `revoke_character_control`). They lock the character's assignment set `FOR UPDATE` in the documented lock order.
10. **Revocation precedence.** Every capability carries its source (role, legacy relationship, control assignment, revelation, resource grant). Revoking one source removes only that source's rights. A whole-character deny (an explicit resource-grant deny on `campaign.view` for the character) suppresses discovery, profile, mechanics and play from every source. An operation-specific deny blocks only that operation. Authority is rechecked under the mutation's own lock: an operation whose authorizing assignment was revoked before the lock is refused, and an already-committed operation remains history.

### 3. World authority owns canonical characters (owner Decision 2)

1. The character's **canonical definition** is world canon and is governed by world authority under ADR 0020 decision 6. That covers identity, names, species, size, origin, descriptions, languages, senses, movement, affiliations, world portrayal defaults and world-shared builds. Writing it requires the world capability plus campaign `canon.edit` on the route campaign.
2. **Control never transfers stewardship.** Assigning, changing or revoking control changes no authoring row, no world role and no lifecycle state.
3. **Authoring responsibility is explicit** (P03-C). A new table, `character.character_authoring_responsibilities`, holds one current row per character, with history kept by closing rows:
   - `responsibility_kind`: `world` (stewarded by world authority alone) or `campaign_delegated`;
   - `campaign_id` (required for `campaign_delegated`): the campaign the world authority has delegated authoring of this character's definition to;
   - `delegated_by_user_id`, `created_at`, `closed_at`.

   Authoring eligibility for character definitions is resolved by `record_authoring` from this row and the caller's world and campaign authority. It is never resolved from the subtype, the controller, the creator, or the first campaign that used the character.
4. **Retiring the player-character exception (amends ADR 0020 decision 6).** `player_character` is removed from `CAMPAIGN_ORIGINATED_TYPES` when P03-C cuts over. Existing player characters keep exactly their current effective access through the migration manifest (§7), which records `campaign_delegated` responsibility for the campaign that a reviewed mapping identifies. A character whose mapping is ambiguous keeps the legacy rule until it is adjudicated. Whether new characters created by a campaign GM without a world role default to `campaign_delegated` is owner decision OD-5. Until it is decided, P03-C must preserve today's behavior for the GM-creates-a-PC path and record its responsibility explicitly. `item_instance` stays campaign-originated; this ADR does not change it.
5. **Delegated player authoring** is bounded by resource, operation and scope. It uses the existing resource-grant mechanism (`security.resource_grants`, character target) with these capabilities:
   - `character.edit_narrative`, existing and currently withheld, limited to the designated player-editable profile fields that P03-A/Phase 16 name;
   - `character.propose_build`, a new capability, which submits a build draft for review (ADR 0023 §7).

   A grant is campaign-scoped, revocable and audited. The granter must hold `access.manage` **and** the authority being delegated (no one delegates more than they hold). Direct build commit without review is not delegable in the initial model.
6. **Campaign preferences never overwrite world definitions.** Campaign-specific player notes, preferences and controller briefings live in campaign-scoped storage (P03-A briefing, Phase 16 notes and collaboration). They are never written into `character.character_descriptions` or other world definition rows. A campaign-owned copy of a world character is prohibited (`DATABASE_CONVENTIONS.md` §34).

### 4. Builds: reusable definitions versus campaign activation

The build model is kept: an immutable `character.character_builds` row plus typed children; activation is timeline state. This ADR adds scope and authority, owned by P03-C (build scope and authority) with one small guard that Phase 15 may land earlier:

| Operation | Authority | Notes |
|---|---|---|
| Create a **world-shared** build (the character's canonical mechanics) | World `world.canon.edit` + campaign `canon.edit` (ADR 0020 decision 6) | Visible to every campaign on the world whose ruleset version matches. |
| Create a **campaign-scoped** build | Campaign `canon.edit` on the origin campaign; or approval of a delegated `character.propose_build` draft (ADR 0023 §7) | Listed, selectable and activatable only in its origin campaign. Never shown to another campaign. |
| Activate a build on a timeline | Campaign `canon.edit` on a campaign of that timeline | The build must be world-shared or have `origin_campaign_id` = the activating campaign. Its `ruleset_version_id` must equal the activating campaign's pinned version (the new guard). The character must be lifecycle-eligible. |
| Modify a build | Nobody | Builds stay immutable. A change is a new build, and its history is preserved. |

P03-C adds to `character.character_builds`:
- `build_scope` (`world_shared` | `campaign` | `legacy_unscoped`);
- `origin_campaign_id`, nullable and immutable;
- `created_by_user_id`.

Existing builds are backfilled as `legacy_unscoped`, which behaves exactly like today (visible and activatable wherever it is today), so no access changes until a reviewed reclassification. **Shared-timeline campaigns** with different pinned ruleset versions share one active build and one runtime state by the existing timeline architecture (ADR 0003). This ADR does not change that. The activation guard prevents a campaign from activating an incompatible build. Evaluation in a campaign whose version differs from the active build's reports `incompatible_ruleset_version` instead of computing (ADR 0023). Whether to add a campaign-scoped active-build selection is owner decision OD-1.

### 5. Public profile, revelation and projections (P03-A)

This ADR adopts the investigation's §D6.3–D6.5 recommended contract as the architecture:
- publication is not revelation;
- a narrow campaign capability `character.reveal`, separate from `access.manage`;
- a first-class, source-tagged revelation record with audience, provenance and revocation;
- an explicitly released, versioned public profile;
- legacy background kept restricted until deliberately reviewed;
- one discovery and profile predicate shared by every list, count, search, detail, relationship, roster, session, encounter, quest, Knowledge and preview consumer.

Four projections are distinct server-side DTOs, never one payload hidden by CSS:
1. **Public profile:** revealed, released fields only.
2. **Controller view:** mechanics, inventory, and the controller briefing for an assigned controller.
3. **GM view:** authoring, private and GM-only material under the existing rules.
4. **Derived mechanics** (ADR 0023): returned only under the projection that may see its inputs.

### 6. Portrayal

Portrayal profiles are re-keyed from `character.npcs.npc_id` to `character.characters.character_id` (P03-C):
1. add a nullable `character_id` column;
2. backfill it from `npc_id` (same UUID, since class-table inheritance shares the primary key);
3. verify version chains and counts;
4. switch commands and reads;
5. replace the FK and cascade target.

Only after verification is the `npc_id` dependency dropped. Portrayal becomes available to any lifecycle-eligible character. It stays GM-only and is never part of a player or controller read.

### 7. Migration, compatibility and rollback

P03-C delivers a **migration manifest**: a reviewed listing, produced by a read-only script on a restored copy, that classifies every character's:
- subtype markers;
- legacy relationships, by type and whether each is live;
- candidate authoring responsibility, with the evidence used;
- builds, with candidate scope;
- portrayal versions;
- session participations and encounter participations.

Audit history may be cited as evidence, never as authority. Ambiguous rows are listed for owner adjudication.

Rules:
1. **Additive first.** New columns and tables ship with code that still honours every legacy path. No destructive change happens until the old and new effective access have been compared on a restored copy and each intended difference is recorded.
2. **Preserve.** Keep:
   - every UUID;
   - `core.entities` row and history;
   - build and child rows, and active-state history;
   - event, effect, Knowledge and relationship references;
   - inventory rows and portrayal versions;
   - historical session participant roles (snapshots of their time, never rewritten to today's control).
3. **No automatic control or revelation.** Legacy `primary_controller`/`co_controller` rows are not converted to assignments, and published characters are not revealed, except by a reviewed manifest action that a GM confirms. The manifest offers "create assignment for membership M" as an explicit, audited action per row.
4. **Compatibility adapters.** The legacy NPC/PC authoring routes and payload fields (`/npcs`, `/player-characters`, `kind`) keep working through guarded adapters. They re-check the new authority, and a legacy kind is only a creation hint (which marker to write). Clients are switched one consumer family at a time.
5. **Subtype retirement is last and optional for Phase 15 closure.** Marker tables are dropped or emptied only after every FK, query, adapter, import and export, audit and replay reader has moved, and only through a further reviewed migration. Phase 15 closes without it (PLANv2 15.9).
6. **Rollback.** Each additive migration has a working downgrade while the legacy columns are still authoritative. Before any irreversible step (dropping `npc_id` from portrayal, dropping markers), a backup is required. Rollback after that point is a restore, never a cascade delete or reconstruction.

### 8. Rules-engine boundary

The actor model knows nothing about rules mechanics. It exposes to ADR 0023's calculation service only:
- the actor UUID;
- the active build on a timeline (or none);
- the build's ruleset version and scope;
- the timeline runtime state;
- inventory;
- the caller's projection tier.

The rules engine never decides control, revelation or authoring. Control never decides mechanics. Creature identity and template basis are ADR 0022's concern and attach through the same build model.

## Consequences

- **Easier.** A player-controlled monster, an NPC handed to a player, and a character controlled by different players in two campaigns are ordinary assignments on one UUID. Phase 16 and Phase 19 get stable contracts (control check, authoring responsibility, build scope, projections) instead of kind checks.
- **Harder.**
  - Every capability source must stay distinguishable, and every reader of character data must use the shared discovery and projection predicates.
  - P03-C needs a manifest and owner adjudication before cutover.
  - The PC exception's retirement changes who may edit player-character identity, so OD-5 must be decided before cutover.
- **Foreclosed.**
  - A `character.character_controllers` table.
  - Converting NPC↔PC by marker swap.
  - Recreating an actor to change control.
  - Granting `canon.edit`, secrets or perspective through control.
  - Campaign-owned character copies.
- **Shared-timeline limitation.** Campaigns sharing a timeline continue to share one active build and runtime state (OD-1).
- **Documentation follow-ups** (with the implementing checkpoint, not now):
  - `DOMAIN_MODEL.md` §2.5 and §8.4–8.6;
  - `DATABASE_MODEL.md` §7.3 (retire `character.character_controllers`) and §19.4;
  - `ENTITY_LIFECYCLE.md` (assignment, revocation, revelation, responsibility commands);
  - ADR 0020 decision 6 amendment note;
  - `PHASE13E_ACCESS_CONTRACT.md` capability matrix.

## References

- [PLANv2.md](../PLANv2.md) §6.1, §8 (15C, 15H, 15.9), §9 (16A), §12 (19.0, 19.3)
- `PHASE14_15_APP_INTERACTION_INVESTIGATION_2026-11-01.md` §D6 and packages P03-A/B/C; `PHASE14_15_REMAINING_WORK_AND_HANDOFF_2026-11-02.md` §6. At this ADR's date both documents are held by the primary workstream and are not committed to `main`.
- Code: `src/dnd_ai/domain/access.py` (`BUILTIN_RELATIONSHIP_CAPABILITIES`, `CHARACTER_TARGET_CAPABILITY_CODES`), `src/dnd_ai/domain/record_authoring.py`, `src/dnd_ai/commands/character_builds.py`, `src/dnd_ai/persistence/tables/{characters,security,campaign}.py`, `src/dnd_ai/domain/session_participation.py`
- [DATABASE_CONVENTIONS.md](../DATABASE_CONVENTIONS.md) §12 (temporal), §34 (anti-patterns)
- [R19_FOUNDATION_IMPLEMENTATION_PLAN.md](../R19_FOUNDATION_IMPLEMENTATION_PLAN.md) §5.1 (actor contract), §9 (outstanding decisions)

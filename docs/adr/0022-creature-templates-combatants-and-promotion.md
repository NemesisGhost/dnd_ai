# ADR 0022: Creature templates, encounter combatants, and promotion

- **Status**: Proposed. R19-P0 architecture deliverable, corrected after independent review (finding R19-07). Not accepted. It implements owner Decision 3 (hybrid creature representation) and is the creature-model ADR that [PLANv2.md](../PLANv2.md) 19.3 and §18 item 8 require.
- **Owner decisions applied (Owner-approved 2026-11-03)**: OD-5 (no delegation for creating and publishing a promoted character, §6) and OD-11 (no promotion during an active encounter, §6). These are policy approvals, not acceptance of this ADR.
- **Date**: 2026-11-02
- **Extends**: [ADR 0005](0005-separate-rules-definitions-from-world-instances.md). A creature template is a rules definition; a persistent creature is a world instance.
- **Depends on**: [ADR 0021](0021-shared-actor-identity-control-and-authoring-responsibility.md) (actor identity, control, build scope, campaign-aware active build); [ADR 0023](0023-rules-engine-calculation-validation-and-source-authorization.md) (adapters, payload validation, provenance, validation and review).
- **Implementation gate**: Template definitions are R19-P2d. **Every encounter-integration change in this ADR (§4–§7) is R19-P4b**. That work happens after the Phase 17 gate, under Phase 15 encounter-command owner review. Nothing in §4–§7 is implemented by an early checkpoint.

## Context

The owner chose three concepts:
1. a reusable creature template;
2. a lightweight encounter combatant;
3. a persistent creature, which is a Character.

### What exists (verified at `10a1a4e`)

- **Templates.** `rules.creature_types` is a seeded lookup. No template, stat-block, creature-instance or spawn model exists.
- **Encounters.** `narrative.encounters`.
- **Participants.** `narrative.encounter_participants` has:
  - `encounter_participant_id` (PK);
  - `participant_entity_id`, NOT NULL, FK `core.entities` `ON DELETE CASCADE`;
  - `side`, `initiative`, `outcome`;
  - `UNIQUE (encounter_id, participant_entity_id)`.
- **Turns.** `narrative.encounter_turns.participant_id` references the participant id.
- **Interactions.**
  - `interaction.actions.actor_entity_id` is NOT NULL (entity FK).
  - `interaction.check_requests.actor_entity_id` is NOT NULL.
  - `interaction.targets` has at-most-one `target_entity_id` or dungeon-feature targets.
  - `interaction.combat_actions` references a target row.
- **Events.** `narrative.event_participants.participant_entity_id` is an entity.
- **Damage.** Combat damage to a character with timeline state updates `campaign.character_state.current_hit_points` and records an event with `event_causes.cause_encounter_id` and a `current_hit_points` effect (`commands/encounters.py`). This path does **not** set `character_state.last_event_id`.

### Every entity assumption a combatant breaks

| # | Component (source) | Assumption | Required change (P4b) |
|---|---|---|---|
| E1 | `narrative.encounter_participants` | The entity is NOT NULL and unique per encounter. | The entity becomes nullable; add combatant columns (§4.1). |
| E2 | Preparation `add`/`update` participant (`commands/encounter_preparation.py`, `api/encounter_preparation.py`) | Participants are published characters of the world, addressed by entity. | Keep the entity path. Add `add_encounter_combatants` and participant-id addressing. |
| E3 | `start_prepared_encounter` (`commands/encounter_operations.py`) | It selects `participant_entity_id` and requires every participant still published. | Per participant kind: an entity participant must still be published; a combatant's template version must still be canon and usable by the world and version. |
| E4 | Turn recording (`commands/encounters._participant_id`, `resolve_combat_turn`) | The actor is addressed by entity and must be a participant. | Accept `actor_encounter_participant_id`. The entity form remains for entity participants. |
| E5 | `interaction.actions.actor_entity_id` NOT NULL | The actor is an entity. | Add `actor_encounter_participant_id`. Exactly one actor is set (§4.3). |
| E6 | `interaction.check_requests.actor_entity_id` NOT NULL | The check actor is an entity. | Combatant checks are **unsupported in P4b**: the command refuses with `combatant_checks_unsupported`. A later checkpoint adds a participant-actor column. |
| E7 | `interaction.targets` | The target is an entity or a dungeon feature. | Add `target_encounter_participant_id` in the at-most-one pattern. |
| E8 | `narrative.event_participants` | Event participants are entities. | Combatants are never event participants. They appear through causes and effects and the action record (§4.4). |
| E9 | Outcomes at encounter end (`commands/encounters`, `outcomes` by entity) | Outcomes are keyed by entity. | Accept participant-id outcomes. Entity outcomes keep working. |
| E10 | Readers `queries/encounter_preparation.py` | `JOIN core.entities` for the participant (line 93) and the turn actor (line 111) would silently **drop** combatants. | LEFT JOIN plus a combatant branch. A reader test fails if a combatant row is missing. |
| E11 | Member projection (`queries/encounter.py`, B1-1) | Visibility is computed over the participant entity set. | Combatants are visible to members as label, side and public outcome only. The template identity, mechanics and overrides are GM-only. |
| E12 | Response schemas (`api/encounters.py`, `api/encounter_preparation.py`, portal types) | `participant_entity_id` is always present. | Additive fields: `encounter_participant_id` (present today in the readers), `participant_kind`, `combatant_label`. `participant_entity_id` is NULL for combatants. The portal and typed clients update in the same checkpoint. |
| E13 | Foundry sync (`commands/integration.py` → `_resolve_combat_turn_impl`) | Actors and targets map to entities. | A sync payload naming a combatant participant is **refused explicitly** (`combatant_not_supported_by_integration`), never skipped. Token mapping to combatants is Phase 21. |
| E14 | Damage to character state (`commands/encounters.py`) | The attacker is an entity. | §4.4 |

## Decision

### 1. Three concepts, one identity rule

| Concept | Identity | Mechanics | State |
|---|---|---|---|
| **Creature template** ("Goblin") | `rules.creature_templates`, a rules definition with no world entity | Immutable published `rules.creature_template_versions` | None |
| **Encounter combatant** ("Goblin 3") | `encounter_participant_id`, stable for the encounter's life and kept forever as history | A pinned template version plus recorded overrides | Encounter-scoped combatant state |
| **Persistent creature** ("Grishnak", a companion wolf, a kept familiar) | `core.entities` + `character.characters` (ADR 0021), never a separate identity | A template-basis build (§3), another build, or none | Ordinary timeline state, inventory, knowledge, relationships, control |

### 2. Creature templates (R19-P2d)

- **`rules.creature_templates`** is the stable identity:
  - `creature_template_id`, `ruleset_id`;
  - `owning_world_id`: required in P2d (world homebrew); NULL is allowed only for content-package templates from R19-P4d;
  - `code` (unique per owning world, or per ruleset for packages), `display_name`;
  - `creature_type_id`, nullable;
  - `content_package_id`, `source_id` (ADR 0023 §4);
  - `canon_status_id`, `created_by_user_id`, `row_version`.
- **`rules.creature_template_versions`** is append-only:
  - `version_number`, `ruleset_version_id` (pinned);
  - `mechanics_schema_code` and `mechanics_schema_version`, plus `mechanics_jsonb`, validated by the adapter on every write;
  - `canon_status_id`, `change_note`, `supersedes_version_id`, `created_by_user_id`, `created_at`, `row_version`.

  A version is editable while `draft` and immutable once `canon` (trigger). Publication follows ADR 0023 §7 for validation and review.
- **Typed references.** `rules.creature_template_version_references` uses at-most-one-typed-target FKs: ability, skill, condition, damage type, language, feature, spell, item definition. A same-version trigger applies, and the adapter requires every reference in the payload to appear here.
- **Template updates** never change pinned users. Combatants and template-basis builds keep their version until a deliberate re-pin or rebuild (§5).

### 3. Persistent creatures use the build model (R19-P4a)

A persistent creature derived from a template has a **template-basis build**: an ordinary immutable `character.character_builds` row (scoped per ADR 0021 §5) plus `character.character_build_template_bases`:
- `character_build_id` (PK);
- `creature_template_version_id`;
- `overrides_schema_version`, `overrides_jsonb` (adapter-validated);
- `override_note`.

Creation, activation, history, validation and review reuse `create_character_build`, `activate_character_build` and ADR 0023 §7. A build has exactly one basis: either a template basis or the ordinary typed children. The adapter reports a mixed build as `conflicting`. Overrides are declared values in every trace.

### 4. Lightweight encounter combatants (R19-P4b)

#### 4.1 Participant columns

On `narrative.encounter_participants`:
- `participant_entity_id` becomes nullable.
- New columns:
  - `combatant_template_version_id` (FK);
  - `combatant_label` (TEXT);
  - `combatant_overrides_schema_version`, `combatant_overrides_jsonb`;
  - `spawn_group_id` (UUID);
  - `promoted_character_id` (FK `character.characters`, immutable once set).
- A CHECK requires exactly one of `participant_entity_id` or `combatant_template_version_id`, and requires a label for combatants.
- The existing `UNIQUE (encounter_id, participant_entity_id)` stays. NULLs are distinct in PostgreSQL, so existing rows remain valid.
- A partial unique index covers `(encounter_id, combatant_label) WHERE participant_entity_id IS NULL`.
- A trigger requires the template version to be canon, usable by the encounter's world (same-world homebrew or a package), and on the version of the encounter campaign's pin.

#### 4.2 Combatant state

- `narrative.encounter_combatant_state`:
  - `encounter_participant_id` (PK);
  - adapter-schema `state_jsonb` (for 5e: current, maximum and temporary hit points);
  - `state_schema_version`, `row_version`;
  - `last_combat_action_id` (FK).
- `narrative.encounter_combatant_conditions` (participant, condition, `applied_by_combat_action_id`, `removed_by_combat_action_id`).

This is tactical encounter-log state (`DATABASE_MODEL.md` §12). Every change cites the combat action that caused it. Combatants never get `campaign.*_state` rows.

#### 4.3 Participant-addressed actors and targets, with integrity

- `interaction.actions` adds `actor_encounter_participant_id`. A CHECK requires exactly one of `actor_entity_id` or `actor_encounter_participant_id`.
- `interaction.targets` adds `target_encounter_participant_id`, extending the at-most-one-target CHECK.
- A trigger on both requires the referenced participant's encounter to be the encounter that owns the action's interaction. That interaction is the one `resolve_combat_turn` creates for the encounter; the link is recorded on the interaction or through its event cause. The trigger also requires the same world and timeline.
- An entity participant should still be addressed by entity, to keep existing rows and the Foundry path unchanged. Addressing an entity participant by participant id is also accepted and normalized to the entity column.

#### 4.4 Causal damage across the boundary

- **Combatant damages a character.** This uses the existing character-damage path:
  - a `narrative.events` row;
  - `event_causes.cause_encounter_id`;
  - the `current_hit_points` effect;
  - **and the state row's `last_event_id` set to that event**. For the **character** path, the existing omission is fixed by **Phase 15 P03-S** (cutover group G1, ADR 0021 §3.8). R19-P4b only reuses that path for combatant attackers, and adds `last_combat_action_id` for combatant targets.

  Under OD-1 (ADR 0021 §3) the write targets the **encounter campaign's** `campaign.campaign_character_state` row once P03-S has cut over, and the event carries that `campaign_id`. Another campaign's state for the same character is never touched. A campaign-less encounter cannot apply mechanical damage.

  Event participants list the damaged character only. The attacker is recorded on `interaction.actions.actor_encounter_participant_id` and the combat action. The event `details` may carry the combatant's label as a display snapshot.
- **Character damages a combatant.** The combatant's state changes with `last_combat_action_id`. No narrative event is written unless an outcome is promoted at encounter end.
- **Combatant damages a combatant.** Combat actions and state only.

#### 4.5 Spawning

`add_encounter_combatants(encounter, template_version, count, label_prefix, side, overrides?, initiative_mode)`:
- creates `count` participants and their initial state, derived by the engine from the template and overrides, in one idempotent transaction under the encounter lock, with one `spawn_group_id`;
- numbers labels `"{prefix} {n}"` after the highest existing number for that prefix;
- is allowed when the encounter is **`pending`** (preparation) or **`active`** (reinforcements and temporary summons). An active-encounter spawn is recorded as an encounter-log entry for the current round with no turn. A completed or aborted encounter refuses it;
- enforces limits per call and per encounter (engineering decision ED-3);
- copies the template version and overrides, never state.

#### 4.6 Summons and companions

- A temporary summon is a combatant spawned into the active encounter.
- A persistent summon or companion is a persistent creature, created directly or by promotion.
- Automatic summon workflows are out of the initial scope.

### 5. Template re-pin

A combatant may be re-pinned to a newer template version only while its encounter is `pending`. Its state is re-derived. A persistent creature moves to a newer version only by a new build plus activation.

### 6. Promotion to a persistent character (R19-P4b)

`promote_encounter_combatant(encounter_participant_id, name, idempotency_key)` is allowed only after the encounter has ended (`completed` or `aborted`). **OD-11 (Owner-approved 2026-11-03):** promotion of a lightweight combatant to a persistent character is not permitted during an active encounter. The command refuses in every other status.

The caller must hold the authority to create **and publish** the character on that world:
- world `world.canon.edit` and `world.canon.review`, plus route-campaign `canon.edit`, under ADR 0021 §4.

OD-5 (Owner-approved 2026-11-03) provides no delegation for creating **and** publishing a new character. Delegations attach to an existing character, and publication into world canon follows world-authorized review (ADR 0021 §4.3, §4.4).

Otherwise the command refuses. It never leaves a half-promoted actor. Steps, in one transaction:

1. Lock the encounter, then the participant row `FOR UPDATE`. If `promoted_character_id` is already set, return the existing character (the idempotent replay).
2. Create the character identity through the normal character command, then publish it through the normal lifecycle command. Authoring responsibility follows ADR 0021 §4. A legacy `npc` marker is written only while P03-C adapters require one.
3. Create the template-basis build through `create_character_build`, from the combatant's pinned version and overrides. It is campaign-scoped to the encounter's campaign by default, or world-shared when the caller holds world authority (ADR 0021 §5, §3.7). OD-6 is reconciled: campaign-scoped builds are permitted.
4. **Initialize campaign mechanical state before activation.** `activate_character_build` requires an existing state row. After P03-S that is the encounter campaign's `campaign_character_state` row; before P03-S it is the timeline row. Initialize it with the combatant's final values through a `combatant_promoted` event, whose effects record the encounter, the participant and the copied values, with `last_event_id` set.
5. Activate the build through `activate_character_build`. The state row now has an event, so activation records a `character_build_activated` event.
6. Set `promoted_character_id`. The trigger makes it immutable.

Historical participants, turns, actions, targets and outcomes are never rewritten.

Read models show "Goblin 3 (later: Grishnak)" **only to viewers who may discover the promoted character** (ADR 0021 §6). Everyone else sees the label alone, with no name, link or id. Promotion reveals nothing and assigns no control.

### 7. Control

- A persistent creature is controlled through ADR 0021 assignments. A player-controlled monster needs no class or level.
- Player control of an unpromoted combatant is not supported. If it is ever needed, it would be an encounter-scoped operation authority on the participant, not a control assignment.

### 8. Read projections

- **Templates:** GM authoring reads only by default.
- **Persistent creatures:** ADR 0021 §6.
- **Combatants:** the encounter projection (E11).

Derived mechanics follow ADR 0023 §9.

### 9. Delivery

| Component | Checkpoint | Gate |
|---|---|---|
| This ADR | R19-P0 | Review and owner acceptance |
| Template tables, versions, references, adapter validation, GM homebrew API | R19-P2d | May merge before Phase 17 (category 2). No user-facing claim |
| Template evaluation by the engine (informational) | R19-P3c or later | Category 2 |
| Template-basis builds, persistent creatures, player-controlled creatures | R19-P4a | After Phase 17 and the P03-B/C contracts |
| E1–E14 combatant integration, spawning, promotion (the character-damage `last_event_id` repair itself belongs to P03-S) | R19-P4b | After Phase 17, with Phase 15 encounter-owner review |
| Catalog packages, generators, automatic summons | R19-P4d or later | After Phase 17 |

### 10. Migration and rollback

All schema changes are additive or relax a NOT NULL, so existing encounters need no data migration. The R19-P4b downgrade works while no combatant rows exist; after that, restore from backup is the rollback. Entity-addressed commands keep their contracts. A command or integration that cannot handle a combatant refuses it explicitly.

## Consequences

- **Easier.** Four goblins are four participant rows, not four world entities. Recurring creatures are ordinary characters. Template edits are safe. Historical encounters keep their pinned versions and recorded actions.
- **Harder.** Every encounter reader and command needs both participant shapes and tests (E1–E14). Adapter schemas must version their payloads.
- **Foreclosed.** A monster identity table. Templates mutating pinned users. Combatants in `campaign.*_state`. Promotion rewriting history. Silent skipping of combatants by integrations.
- **Risks.** Large encounters (ED-3 limits, indexed reads). JSONB drift (versioned schemas). Template leakage to players (GM-only projection plus negative tests).

## References

- [PLANv2.md](../PLANv2.md) 19.0, 19.3, 19.4, §6.1
- [DATABASE_MODEL.md](../architecture/DATABASE_MODEL.md) §9.2, §12, §13; [DATABASE_CONVENTIONS.md](../DATABASE_CONVENTIONS.md) §5.7, §18, §34
- Code: `src/dnd_ai/persistence/tables/{encounters,interaction,narrative}.py`, `src/dnd_ai/commands/{encounters,encounter_operations,encounter_preparation,integration}.py`, `src/dnd_ai/queries/{encounter,encounter_preparation}.py`, `src/dnd_ai/api/{encounters,encounter_preparation}.py`
- [R19_FOUNDATION_IMPLEMENTATION_PLAN.md](../R19_FOUNDATION_IMPLEMENTATION_PLAN.md) §5.3, §6 (P2d, P4a, P4b)

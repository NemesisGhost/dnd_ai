# ADR 0022: Creature templates, encounter combatants, and promotion

- **Status**: Proposed (R19-P0 architecture deliverable, 2026-11-02; awaiting independent architecture review and owner acceptance). It implements owner Decision 3 (hybrid creature representation) and settles the creature-model decision that [PLANv2.md](../PLANv2.md) 19.3 and §18 item 8 require before implementation.
- **Date**: 2026-11-02
- **Extends**: [ADR 0005](0005-separate-rules-definitions-from-world-instances.md). A creature template is a rules definition; a persistent creature is a world instance.
- **Depends on**: [ADR 0021](0021-shared-actor-identity-control-and-authoring-responsibility.md) (actor identity, control, build scope), [ADR 0023](0023-rules-engine-calculation-validation-and-source-authorization.md) (ruleset adapters, mechanics payload validation, provenance).

## Context

PLANv2 19.3 asked whether creatures should be character-based monsters with detail levels, or separate templates plus world instances. The owner has chosen a hybrid of three concepts:

1. a reusable **creature template** with mechanical definitions;
2. a **lightweight encounter combatant** that needs no permanent world identity;
3. a **persistent creature**, which is a Character.

What exists today:

- `rules.creature_types` is a seeded lookup (aberration, beast, …). There is no template, stat block, creature instance or spawn model anywhere in the schema (`DATABASE_MODEL.md` §9.2 notes that `world.area_spawn_definitions` was never built).
- `narrative.encounter_participants` (`src/dnd_ai/persistence/tables/encounters.py`) has:
  - `encounter_participant_id` (PK);
  - `participant_entity_id`, `NOT NULL`, FK `core.entities` `ON DELETE CASCADE`;
  - `side`, `initiative`, `outcome`;
  - `UNIQUE (encounter_id, participant_entity_id)`.
- Preparation accepts only existing published characters of the world (15.3B-2a). `narrative.encounter_turns.participant_id` references `encounter_participant_id`, not the entity. `interaction.targets.target_entity_id` targets entities.
- Many APIs and commands address participants by `participant_entity_id`: turn recording, outcomes, the Foundry combat sync (`api/encounters.py`, `commands/encounters.py`, `commands/encounter_operations.py`). A hit lowers `campaign.character_state.current_hit_points` for a character with timeline state.
- The member encounter projection (B1-1, `67f80de`) withholds GM summaries and turn notes and filters hidden participants.

Representing every goblin as a persistent world character would create `core.entities`, `character.characters`, lifecycle, discovery and audit rows for actors nobody will reference again. It would also inflate World Explorer lists, discovery predicates, counts and the review queue. Representing a named monster as anything other than a Character would break ADR 0021's one-actor rule.

## Decision

### 1. Three concepts, one identity rule

| Concept | What it is | Identity | Mechanics | State |
|---|---|---|---|---|
| **Creature template** | A reusable mechanical definition: "Goblin", "Wolf", "Young Red Dragon" | `rules.creature_templates`, a rules definition (no world entity) | Immutable `rules.creature_template_versions` | None |
| **Encounter combatant** | One unnamed creature inside one encounter: "Goblin 3" | `narrative.encounter_participants.encounter_participant_id`, stable for the encounter's life | Pinned template version plus recorded overrides | Encounter-scoped combatant state |
| **Persistent creature** | An individual: "Grishnak the goblin boss", a companion wolf, a summoned familiar the GM keeps | `core.entities` + `character.characters` (ADR 0021), never a separate creature identity | A build whose basis is a template version plus overrides (§3), or an ordinary build, or none | Ordinary timeline state, inventory, knowledge, relationships, control |

A persistent creature *is* a Character. Named monsters, animals, companions, summons the GM keeps, and player-controlled creatures all use ADR 0021's identity, control assignments, projections and authoring responsibility. Species and creature type are attributes, not identity.

### 2. Creature templates (rules definitions)

- `rules.creature_templates` is the template's stable identity:
  - `creature_template_id`, `ruleset_id`;
  - `owning_world_id` (NULL = ruleset-wide content-package template; set = world homebrew, the `rules.item_definitions` precedent), immutable;
  - `code` (unique per ruleset for ruleset-wide templates, per owning world for homebrew), `display_name`;
  - `creature_type_id`, nullable because not every system has creature types;
  - `content_package_id` / `source_id` and `canon_status_id` (ADR 0023 §4);
  - `created_by_user_id`, `row_version`.
- `rules.creature_template_versions` is append-only:
  - `creature_template_version_id`, `creature_template_id`, `version_number`;
  - `ruleset_version_id`, which pins the template version to one ruleset version;
  - `mechanics_schema_code` + `mechanics_schema_version`, naming the adapter schema;
  - `mechanics_jsonb`;
  - `canon_status_id`, `change_note`, `supersedes_version_id`, `created_by_user_id`, `created_at`.

  While a version's canon status is `draft` it may be edited. Once it is `canon` it is immutable (trigger): a change is a new version.
- **Why JSONB for mechanics.** A stat block's shape is ruleset-specific. A 5e block has armor class, hit dice, challenge rating and legendary actions; a skill-based system has none of these. `DATABASE_CONVENTIONS.md` §5.7 permits JSONB for ruleset-specific properties, and §18.4 requires a schema version. The universal tables therefore carry no 5e columns. The payload is validated on every write by the ruleset adapter's registered schema (ADR 0023 §3). An unknown schema or a version the adapter does not support is stored only as a draft and is reported `unsupported`; it is never silently accepted as validated.
- **Referential integrity for definitions.** References from a template to other rules definitions (abilities, skills, conditions, damage types, languages, features, spells, item definitions) live in `rules.creature_template_version_references`. This is a typed table with at-most-one-typed-target columns per row (the `knowledge_items` pattern), FKs, and a same-ruleset-version trigger. The JSONB never holds the only copy of a reference that needs integrity. The adapter validates that every reference in the payload appears in that table.
- **Template update behavior.** Publishing a new version never changes existing pinned users. Combatants and template-based builds keep the version they pinned until a deliberate operation moves them. Moving them creates a new build or records a combatant re-pin, which is allowed only while the encounter is `pending`. Read models show "a newer template version exists".

### 3. Persistent creatures use the build model

A persistent creature derived from a template gets a **template-basis build**. This is a normal `character.character_builds` row (immutable, ruleset-version-pinned, scoped per ADR 0021 §4) plus a typed child, `character.character_build_template_bases`:
- `character_build_id` (PK);
- `creature_template_version_id`;
- `overrides_schema_version`, `overrides_jsonb`, validated by the adapter;
- `override_note`.

Consequences:
- creation, activation, timeline scoping, history, validation (ADR 0023) and authority all reuse `create_character_build` / `activate_character_build`, so there is no second mechanical write path;
- a template update affects a creature only when someone creates and activates a new build from the new version;
- overrides are explicit, recorded and attributable. They are declared values, distinguishable from derived values in every calculation trace;
- a creature that later gains class levels (or the equivalent in another system) gets a different build. A build has exactly one basis (template-basis, or the ordinary typed children); the adapter reports a build that mixes them as `conflicting`.

### 4. Lightweight encounter combatants

Additive changes to `narrative.encounter_participants` (R19-P4b):

1. `participant_entity_id` becomes nullable.
2. New columns:
   - `combatant_template_version_id` (FK, nullable);
   - `combatant_label` (TEXT, nullable);
   - `combatant_overrides_schema_version`, `combatant_overrides_jsonb` (nullable);
   - `spawn_group_id` (UUID, nullable), shared by combatants created together;
   - `promoted_character_id` (FK `character.characters`, nullable, immutable once set).
3. CHECK: exactly one of `participant_entity_id` or `combatant_template_version_id` is set. `combatant_label` is required when the template version is set.
4. The existing `UNIQUE (encounter_id, participant_entity_id)` is kept unchanged. PostgreSQL treats NULLs as distinct, so many combatants coexist and every existing row still satisfies it. A partial unique index on `(encounter_id, combatant_label) WHERE participant_entity_id IS NULL` keeps labels unique.
5. The template version must be canon and usable by the encounter's world: ruleset-wide, or homebrew owned by the same world. Its ruleset version must equal the campaign's (trigger plus command check).

Combatant runtime state (R19-P4b):
- `narrative.encounter_combatant_state` (`encounter_participant_id` PK, current, maximum and temporary hit points or the adapter's equivalent, `last_combat_action_id`);
- `narrative.encounter_combatant_conditions`.

This is tactical encounter-log state, consistent with `DATABASE_MODEL.md` §12 ("high-volume tactical actions live in encounter logs"). Every change references the `interaction.combat_actions` row or turn that caused it. Combatants never get `campaign.*_state` rows. Meaningful outcomes still become narrative events through the existing "Encounter ended" path.

Targeting: `interaction.targets` gains `target_encounter_participant_id` (nullable FK) in the at-most-one-typed-target pattern.

API compatibility:
- every existing request and response that addresses participants by `participant_entity_id` keeps working for entity participants;
- new requests may address any participant by `encounter_participant_id`;
- responses add `encounter_participant_id` and `combatant_label`;
- the Foundry combat sync continues to map character actors as today. Mapping Foundry tokens to combatants is Phase 21 work, and until then combatants are portal-only.

The member projection treats a combatant like any participant: label, side and public outcome only. The template identity, mechanics and overrides are GM data.

### 5. Spawning and duplication

`add_encounter_combatants(encounter, template_version, count, label_prefix, side, overrides?, initiative_mode)` creates `count` participants in one transaction, sharing a `spawn_group_id`, with labels `"{prefix} {n}"` numbered after the highest existing label for that prefix. Constraints:
- `count` is bounded per call;
- the encounter's total participant count is bounded, with limits in the plan;
- the encounter must be `pending`;
- adding to an active encounter mid-combat (reinforcements) is the same command, allowed for `active` too, recorded as a turn-independent action.

Duplication copies the template version and overrides, never state. Initiative may be one roll per spawn group or per combatant (adapter-defined).

**Summons and companions.**
- A temporary summon (a conjured creature that lasts one fight) is a combatant added to the active encounter through this command.
- A summon or companion that persists (a familiar, an animal companion, a bound servant) is a persistent creature, created directly or by promotion (§6), and may be player-controlled through ADR 0021.
- Automatic summon workflows (a spell that creates its creature) are out of the initial scope. When built, they call these same commands.

### 6. Promotion to a persistent character

`promote_encounter_combatant(encounter_participant_id, name, …)` is an explicit, audited, idempotent command, allowed when the encounter is `completed` or `aborted`. Promotion during an `active` encounter is deferred (OD-11). In one transaction it:

1. creates the character through the normal character-creation command: draft or published per the caller's authority, with authoring responsibility per ADR 0021, and legacy marker `npc` only while P03-C adapters still need one;
2. creates a template-basis build from the combatant's pinned version and overrides, and activates it on the campaign's timeline;
3. initializes `campaign.character_state` from the combatant's final encounter state with a `combatant_promoted` event, whose effects record the encounter, participant and copied values;
4. sets `promoted_character_id` on the participant row (immutable), and records nothing else on historical turns or actions.

Historical turns, combat actions, targets and outcomes keep pointing at the `encounter_participant_id`. Read models resolve "Goblin 3, later Grishnak". Neither the encounter nor its history is rewritten. Promotion does not reveal the new character, assign control, or grant any audience. Those remain ADR 0021 operations.

### 7. Controller assignment

A persistent creature is controlled through ADR 0021 assignments like any character. A player-controlled monster needs no class or level, only a character, optionally a template-basis build, and an assignment. Player control of an unpromoted combatant is not supported initially. If needed later, it is an encounter-scoped operation authority on the participant, never a control assignment, because combatants are not actors in the world model.

### 8. Read projections

- **Templates:** a GM authoring read, and a player read only where the campaign's rules policy publishes a creature's stat block (default: none).
- **Persistent creature:** ADR 0021's four projections.
- **Combatant:** an encounter projection only.

Derived mechanics for any of them come from ADR 0023 and follow the projection of their inputs.

### 9. What ships when

| Component | Checkpoint | Notes |
|---|---|---|
| ADR acceptance, interface definitions | R19-P0 | This document |
| `rules.creature_templates`, versions, references, adapter schema validation, GM homebrew authoring API (no portal) | R19-P2d | Additive rules definitions. May merge before Phase 17. No user-facing claim |
| Template mechanics evaluated by the calculation service (5e subset) | R19-P3 (after P2d) | Informational results |
| Template-basis builds, persistent creature authoring and player-controlled creatures | R19-P4a | Needs the P03-C build scope and actor contracts, plus Phase 17 |
| Encounter combatants, combatant state, spawning, targeting, promotion | R19-P4b | Needs Phase 17. Touches Phase 15 encounter commands under coordinated ownership |
| Creature catalog content packages, generators, summon workflows | R19-P4 or later | Generators and automatic summons are out of the initial scope |

### 10. Migration and rollback

- **Schema.** Every change is additive. Making `participant_entity_id` nullable is backward compatible for every existing row. Rollback of R19-P4b is possible while no combatant rows exist; after that, the downgrade refuses, and restore from backup is the rollback.
- **Existing encounters** are untouched. No data migration is required. Existing participants remain entity participants.
- **Commands.** Entity-addressed commands keep their contracts. New participant-addressed variants are added alongside. A command that receives a combatant where only entities are supported (for example the Foundry sync) refuses it explicitly; it never silently skips it.

## Consequences

- **Easier.** Four goblins cost four participant rows, not four world entities. A named or recurring creature is a normal character with history, control and knowledge. Template edits are safe, because nothing changes until it is deliberately re-pinned or rebuilt. Historical encounters stay reproducible from the pinned version, the overrides and the recorded actions.
- **Harder.** Encounter queries must handle two participant shapes. Every participant-addressing command and read model needs combatant tests. Adapter schema validation must keep pace with template payload versions.
- **Foreclosed.**
  - A separate monster identity table.
  - Templates that mutate pinned instances.
  - Combatants holding `campaign.*_state`.
  - Promotion that rewrites encounter history.
- **Risks.**
  - Large encounters: bounded spawn counts and indexed participant reads.
  - JSONB drift: versioned schemas and adapter validation on write.
  - Leakage of template stats to players: GM-only projection plus negative tests.

## References

- [PLANv2.md](../PLANv2.md) 19.0, 19.3, 19.4, §6.1 (encounter records ownership)
- [DATABASE_MODEL.md](../architecture/DATABASE_MODEL.md) §9.2, §12, §13; [DATABASE_CONVENTIONS.md](../DATABASE_CONVENTIONS.md) §5.7, §18, §34
- Code: `src/dnd_ai/persistence/tables/encounters.py`, `src/dnd_ai/persistence/tables/interaction.py`, `src/dnd_ai/commands/encounters.py`, `src/dnd_ai/commands/encounter_operations.py`, `src/dnd_ai/api/encounters.py`
- [R19_FOUNDATION_IMPLEMENTATION_PLAN.md](../R19_FOUNDATION_IMPLEMENTATION_PLAN.md) §5.3 (creature contract), §6 (checkpoints P2d, P4a, P4b)

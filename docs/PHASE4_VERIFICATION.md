# Phase 4 Verification Checklist

Verifies Phase 4 (Rules and shared characters) per [PLAN.md §23](PLAN.md#23-delivery-phases), following the exit review in [§23.1](PLAN.md#231-phase-exit-review).

## Exit Criteria

- [x] NPC and PC use the same mechanical model — both are, structurally, a `character.characters` row plus a marker subtype (`character.npcs` / `character.player_characters`), proven in `test_characters.py::test_npc_and_player_character_both_extend_characters`
- [x] A character sheet can be assembled from structured data — the seeded ruleset (§6 below) supplies real classes, species, spells, and features a build can reference; `test_character_builds.py` exercises ability scores, multiclass levels, proficiencies, and spellcasting profiles against it
- [x] A subtype row cannot exist without its parent `core.entities` row, cannot use a primary key of its own, and cannot attach to a parent of the wrong entity type — each rejected by the database, each with a negative test (`test_characters.py`, verbatim test names matching the criterion's own wording)

All verified against the deployed AWS `dev` RDS instance, per [§23.0](PLAN.md#230-aws-verification-policy): full downgrade-to-`base` and upgrade-to-`head` round trip through all 22 revisions, `alembic check` clean, 523 tests passing.

## Preceded by a documentation reconciliation

Before writing schema, a real drift between `PLAN.md` and `docs/architecture/DATABASE_MODEL.md` was found and fixed: `DATABASE_MODEL.md`'s per-domain table lists were a compressed sketch, `PLAN.md`'s per-phase prose had grown ~40 additional table mentions neither document cross-referenced, and 7 tables built in Phases 1–3 had never been added to `DATABASE_MODEL.md` at all. `DATABASE_MODEL.md` is now the explicit schema source of truth (`CLAUDE.md`'s documentation map updated to say so); `PLAN.md` is corrected to match; `README.md`'s schema-flavored sections are marked illustrative. `DATABASE_MODEL.md` §25 records every reconciliation judgment call made, including a few flagged as genuinely uncertain for the phase that actually owns them to revisit. See the "Make DATABASE_MODEL.md the primary source of truth" commit for the full account — it is not repeated here since it precedes this phase's own schema work rather than being part of it.

## What Was Built

Ten revisions, 34 tables, one seed migration.

| Revision | Delivers |
|---|---|
| `013_rulesets` | `rules.rulesets`, `rules.ruleset_versions` (at most one current version per ruleset) |
| `014_ruleset_content` | Eight ruleset-version-scoped lookups generated from one shared shape (abilities, species, damage types, conditions, creature types, languages, proficiency types, resource definitions), plus `rules.skills` (governing ability cross-checked) |
| `015_ruleset_classes` | `rules.classes`, `rules.subclasses` (class agreement enforced), `rules.features` (independently nullable class/subclass/species associations), `rules.feats`, `rules.spells` |
| `016_close_ruleset_refs` | `rules.world_rulesets`; closes `core.worlds.default_ruleset_id` (deferred Phase 2) and `campaign.campaigns.ruleset_id` (deferred Phase 3), both trigger-checked against `world_rulesets` |
| `017_characters` | `character.characters` → `character.npcs` / `character.player_characters`, wired to Phase 2's `core.enforce_entity_subtype()`; the three `core.entity_types` rows |
| `018_party_membership_char` | Closes Phase 3's deferral: `party_memberships.member_entity_id` must be a `character.characters` row |
| `019_character_shared_data` | `character_descriptions`, `character_languages`, `character_senses`, `character_movements` |
| `020_character_builds` | `character_builds` (one current per character), `character_ability_scores`, `character_class_levels` (multiclass-capable, subclass-checked), `character_proficiencies` (exactly-one-target CHECK), `character_features`, `character_spellcasting_profiles`, `character_known_spells`, `character_prepared_spells` |
| `021_character_timeline_state` | `campaign.character_state`, `.character_conditions`, `.character_resources` — one shared world-agreement trigger function across all three |
| `022_seed_ruleset` | One ruleset ("D&D 5e (2024)"), one current version, and real cross-referenced content: 6 abilities, 18 skills, 2 species, 13 damage types, 14 conditions, 14 creature types, 10 languages, 5 proficiency types, 5 resource kinds, 2 classes, 2 subclasses, 2 feats, 5 spells, 3 features |

## Recurring Obligations ([§23.1](PLAN.md#231-phase-exit-review))

| Obligation | Result |
|---|---|
| Object ownership | All 34 tables owned by `migration_owner` |
| Default privileges | `app_read_write`/`app_read_only` asserted per-table in `test_role_grants.py`, now covering all 34 new tables |
| Seed idempotency | Re-ran `022`'s `upgrade()` a second time directly against an already-seeded database: zero new rows, zero errors. First seed content with real cross-references (skills→abilities, subclasses/features→classes, spells→damage types) rather than flat codes — see "Bugs and Gaps Found" for what that surfaced |
| Constraint tests | 523 tests total (up from 327 at Phase 3 exit) |
| Comments and FK indexes | Zero tables without a comment; `test_every_foreign_key_is_indexed` clean after fixing three gaps (below) |
| Downgrade | Full round trip to `base` and back through all 22 revisions |
| CI green | **Not yet run** — same gap noted at Phase 3 exit, still outstanding. Push and confirm before treating this phase as fully closed. |

## Bugs and Gaps Found

1. **Three more foreign keys missing their §19.1 index**: `campaign.character_conditions.character_id`, `campaign.character_resources.character_id`, `character.character_spellcasting_profiles.class_id`. Same class of gap as Phase 3's three — tables with no natural composite index happening to cover a given column. `test_every_foreign_key_is_indexed` caught all three.
2. **Phase 3 test fixtures broke against the new party-membership enforcement.** `018_party_membership_char` requires `member_entity_id` to be an actual character; Phase 3's `test_party_memberships.py` built members as bare `core.entities` rows via `make_entity`. Fixed by adding `make_character()` to `tests/factories.py` and switching the fixture to it — this is expected, intentional breakage (the whole point of the revision), not a regression.
3. **`make_ruleset_for_world()` always set `is_default = true`.** A second call for a world that already had an allowed ruleset collided with `ux_world_rulesets_one_default_per_world`. Fixed to default `is_default` based on whether the world already has a `world_rulesets` row, with an explicit override still available.
4. **`make_character()` always used the bare `character` entity type.** Tests that then tried to also insert a `character.npcs` or `character.player_characters` row for it were correctly rejected by `core.enforce_entity_subtype()` — the entity wasn't typed as an NPC or PC. Not a schema bug; the test helper needed an `entity_type_code` parameter, since a caller building an NPC needs the entity created as one from the start.
5. **A test entity-type code used a hyphen.** `ck_entity_types_code_format` requires `^[a-z][a-z0-9_]*$` (underscore, no hyphens) — `"non-character-type"` fixed to `"non_character_type"`.
6. **A column comment drifted between a migration and `tables.py`** (same class of gap Phase 3 hit once): `campaign.character_state`'s table comment text differed by a few words between the two, caught by `alembic check`.

None of these were schema-design defects — all six were test/tooling bugs found and fixed before they could hide a real one.

## Deliberate Scoping Decisions

- **NPC portrayal and simulation apparatus is deferred to Phase 10.** `character.npc_portrayal_profiles`, `.npc_characteristics`, `.npc_goals`, `.npc_routines`, `.npc_routine_steps`, `.npc_preferences`, `.npc_boundaries`, `.npc_disclosure_rules`, `.npc_agent_assignments`, `character.character_controllers`, `security.character_permissions`, `campaign.npc_goal_state`, `campaign.npc_emotional_state` — none of these appear in Phase 4's own Deliver/exit-criteria text, and Phase 10 is what actually builds the AI agents and control assignment they serve. `character.npcs` itself is built now, deliberately minimal.
- **`character.character_religious_affiliations` is deferred to Phase 8**, which builds `world.religions`.
- **`campaign.character_location_history` is deferred to Phase 5** (locations) and **`campaign.character_inventory` to Phase 9** (items) — both already recorded as deferred in `PLAN.md` §7.3 before this phase started.
- **`rules.item_definitions` is deferred to Phase 9**, which explicitly owns "item definitions and instances" together.
- **No event-linked history on the three timeline-state tables.** `DATABASE_MODEL.md` §17's general shape calls for `effective_from_event_id`/`effective_to_event_id`, but `narrative.events` doesn't exist until Phase 6. Each table is a single mutable current row per `(timeline, character)` instead, enforced by its primary key; Phase 6 is expected to add event linkage without needing to change these tables' shape, since atomicity is a transaction-boundary guarantee the command layer provides, not a column.
- **Cross-ruleset-version checks stop at ability scores and class levels.** Proficiencies, features, and spellcasting profiles rely on their target rows' own foreign keys for referential validity but do not cross-check ruleset version against the build. Documented as a scope cut in `020_character_builds.py`'s docstring, not an oversight — revisit if mixed-version references turn out to matter in practice.
- **`size_category` is a CHECK, not a lookup table.** The six D&D size categories are a fixed, universal vocabulary unlike canon/lifecycle status or ability names, which the conventions' "lookup tables over ENUM" guidance targets because they vary by ruleset or need GM extension.
- **`character.character_senses.sense_type` and `character.character_movements.movement_type` are free text**, not lookups — this project has no documented controlled vocabulary for either, and inventing one unprompted risked recreating the exact drift the pre-phase reconciliation just fixed.

## Outstanding

Carried forward, still open:

- **Orphaned KMS key** (`5a359a0a-4d30-4c00-925f-2dfad6e5820d`) from the Phase 1 teardown.
- **No `CREATEDB`-capable test role.**
- **`iam_auth_db_users` duplicates the login-role list** in `001_bootstrap.py`.
- **No remote Terraform state**, and `staging`/`prod` unbuilt.
- **CI has not run for Phase 3 or Phase 4 work yet.** Push and confirm both are green.

Next phase: Phase 5 (Locations and dungeon play) per [PLAN.md §23](PLAN.md#23-delivery-phases).

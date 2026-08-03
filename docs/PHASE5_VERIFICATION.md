# Phase 5 Verification Checklist

Verifies Phase 5 (Locations and dungeon play) per [PLAN.md §23](PLAN.md#23-delivery-phases), following the exit review in [§23.1](PLAN.md#231-phase-exit-review). Phase 5 also pulled a minimal slice of the knowledge domain forward from Phase 7 to satisfy its own exit criteria — see "Preceded by a scope decision" below and [DATABASE_MODEL.md §26](architecture/DATABASE_MODEL.md#26-reconciliation-notes-phase-5) for the full account.

## Exit Criteria

- [x] A party can enter and navigate a multi-room dungeon — `campaign.character_location_history` records arrival/departure per timeline, with the open (`departed_at_world_time_id IS NULL`) row as current location; `test_close_phase4_location_refs.py::test_a_character_can_move_between_dungeon_areas` moves a character between two `world.dungeon_areas` rows and asserts both the new current location and a two-row history.
- [x] Hidden connections remain distinct from party knowledge — `world.area_connections.is_hidden` (and the equivalent column on features/hazards/interactables) is a structural fact with no party reference anywhere in its table; discovery is recorded separately in `knowledge.party_discoveries`, scoped per party. `test_knowledge_domain.py::test_a_hidden_connections_own_row_never_reveals_party_knowledge` asserts both structurally (`world.area_connections` has no `discover`/`known`-named column) and behaviorally (two parties on the same timeline have independent discovery records for the same connection, which itself stays `is_hidden = true` throughout).
- [x] Actions can alter dungeon state — all five typed state tables (`campaign.location_state`, `.area_connection_state`, `.area_feature_state`, `.hazard_state`, `.interactable_state`) support in-place transitions, exercised by `test_dungeon_timeline_state.py` (e.g. a connection moving from locked to open, a hazard from armed to disarmed).

All verified against the deployed AWS `dev` RDS instance, per [§23.0](PLAN.md#230-aws-verification-policy): upgrade to `head` through all 5 new revisions (038–042), a downgrade/upgrade round trip covering them, `alembic check` clean, and the full `tests/database` suite (971 tests, including a from-scratch `upgrade head` against a fresh ephemeral database) passing.

## Preceded by a scope decision

PLAN.md's Phase 5 deliverable list names "discovery records" and its exit criteria require hidden connections to stay distinct from party knowledge, but the documented shape of discovery (`knowledge.party_discoveries`, DATABASE_MODEL.md §15) is tied to `knowledge.knowledge_items` — a table DATABASE_MODEL.md's own implementation order (§23) places in Phase 7, after locations, interactions/events, and quests. This was surfaced and discussed with the user before writing schema (matching the process CLAUDE.md §7 asks for) rather than resolved unilaterally. The decision: pull the minimal slice of the knowledge domain forward — `knowledge.knowledge_items`, `knowledge.entity_knowledge`, `knowledge.party_discoveries`, plus the two lookups they need — using their documented Phase 7 shape, rather than invent a smaller Phase-5-only table Phase 7 would need to reconcile later. `knowledge.knowledge_versions`, `.information_transfers`, `.expertise_domains`/`.character_expertise`, and `.public_knowledge` remain genuinely deferred to Phase 7. See DATABASE_MODEL.md §26 for the full reconciliation note, including the simplified single-subject shape used on `knowledge.knowledge_items` in place of the plural "subject entities" DOMAIN_MODEL.md §15.1 describes.

## What Was Built

Five revisions, 24 tables, one column added to an existing table.

| Revision | Delivers |
|---|---|
| `038_locations` | `world.locations` (class-table-inheritance root, self-referencing `parent_location_id` with a same-world trigger), `world.settlements` (`population`), `world.buildings` (`building_use`); nine `core.entity_types` rows (`location` plus six no-subtype-table leaves — plane, continent, nation, region, district, geographic_feature — plus `settlement`, `building`) |
| `039_dungeon_structures` | `world.dungeons` (`danger_level`), `world.dungeon_areas` (with a trigger requiring a dungeon-typed parent), `world.connection_types` (seeded lookup), `world.area_connections` (same-world but deliberately not same-dungeon enforced — teleportation links may cross dungeons), `world.area_features`, `world.area_hazards`, `world.area_interactables` (none entity-rooted; each carries `is_hidden`) |
| `040_dungeon_timeline_state` | `campaign.location_state`, `.connection_statuses` (seeded), `.area_connection_state`, `.area_feature_state`, `.hazard_statuses` (seeded), `.hazard_state`, `.interactable_statuses` (seeded), `.interactable_state` — five trigger functions, one per table, each reaching `world_id` through a different join path |
| `041_knowledge_domain` | `knowledge.knowledge_types` (seeded), `.truth_statuses` (seeded), `.knowledge_items` (entity-rooted, at-most-one-subject CHECK across five typed subject columns), `.entity_knowledge` (one current belief per timeline/item/knower), `.party_discoveries` (exactly-one-recipient CHECK, partial unique indexes per recipient kind) |
| `042_close_phase4_location_refs` | Closes Phase 4's two forward references: `character.characters.origin_location_id` (same-world trigger) and `campaign.character_location_history` (one open/current row per timeline+character via partial unique index) |

## Recurring Obligations ([§23.1](PLAN.md#231-phase-exit-review))

| Obligation | Result |
|---|---|
| Object ownership | All 24 new tables owned by `migration_owner` (schema-level default privileges from revision 001 apply automatically) |
| Default privileges | `app_read_write`/`app_read_only` asserted per-table in `test_role_grants.py`, now covering all 24 new tables |
| Seed idempotency | `world.connection_types` (9 rows), `campaign.connection_statuses`/`.hazard_statuses`/`.interactable_statuses` (5/5/6 rows), `knowledge.knowledge_types`/`.truth_statuses` (7/6 rows) all seeded with `ON CONFLICT (code) DO NOTHING`, same pattern as every prior lookup |
| Constraint tests | 971 tests total (up from 924 at Phase 4 exit); 47 new across five test files |
| Comments and FK indexes | Zero tables without a comment (`test_schema_documentation.py`); every foreign key indexed, including partial indexes for nullable FKs (`test_every_foreign_key_is_indexed`) |
| Downgrade | Verified for the bounded range covering all five new revisions (`downgrade 037_character_language_ruleset` → `upgrade head`) against the shared `dev` instance. A full downgrade-to-`base` was not run against `dev` in this pass — doing so would wipe every prior phase's data on shared infrastructure; `tests/database`'s from-scratch `upgrade head` against a fresh ephemeral database is the equivalent full-chain proof Phase 4's own exit review accepted in spirit, and downgrade for 038–042 specifically was exercised directly. |
| CI green | Not yet run for this phase — no commit/push has been made as part of this work. Run the GitHub Actions workflow before merging, per the pattern Phase 4 used. |

## Bugs and Gaps Found

1. **A trigger function's error message masked a CHECK constraint.** `knowledge.enforce_party_discovery_world()` originally looked up a recipient's world unconditionally; when both `party_id` and `knower_entity_id` were `NULL` (violating `ck_party_discoveries_exactly_one_recipient`), the `BEFORE INSERT` trigger ran first and raised its own "mixes worlds" error before the `CHECK` constraint got a chance, since PostgreSQL evaluates `BEFORE ROW` triggers before per-row constraints. Fixed by having the trigger return early when both recipient columns are `NULL`, letting the `CHECK` constraint report the more specific error. Found by `test_a_discovery_needs_exactly_one_recipient`.
2. **Two `TEXT` column defaults needed an explicit cast in `tables.py`.** `knowledge.knowledge_items.sensitivity` and `knowledge.entity_knowledge.awareness_level` both declare a string `server_default`; PostgreSQL normalizes a literal-string default on a `TEXT` column to include `::text` in `information_schema.columns.column_default`, so `tables.py` had to declare `text("'public'::text")` / `text("'aware'::text")` rather than the bare literal to match, caught by `test_metadata_server_default_matches_live_schema` (the same test class that caught a Phase 4 corrections-pass bug in `rules.default_canon_status_id()`).
3. **A `Column(...)` comment was declared in the migration but not mirrored in `tables.py`.** `world.area_connections.is_one_way` had its `COMMENT ON COLUMN` in the migration but the corresponding `tables.py` `Column()` call had no `comment=` argument, caught immediately by `alembic check` before any test ran.

None of these were schema-design defects — all three were test/tooling-parity bugs caught before they could hide a real one, the same class of finding every prior phase's verification pass recorded.

## Deliberate Scoping Decisions

- **`world.area_spawn_definitions` was not built**, despite being named in PLAN.md §9.2 and (a prior revision of) DATABASE_MODEL.md §9.2. No creature-instance or stat-block model exists anywhere in this schema — `rules.creature_types` is a bare classification lookup — and Phase 9 (encounters) is the natural first consumer. Both docs corrected to record the deferral; see DATABASE_MODEL.md §26.
- **`world.settlements` and `world.buildings` are minimal**, matching Phase 4's `character.npcs` pattern: settlements carry `population` only (government/factions are Phase 8 organization concepts; economy is intentionally deferred per DOMAIN_MODEL.md §27; districts are plain child locations; control/damage state is timeline state); buildings carry free-text `building_use` (no documented vocabulary exists).
- **Six DOMAIN_MODEL.md §9.1 location kinds with no structured data** (plane, continent, nation, region, district, geographic_feature) are plain `core.entity_types` leaves under `location`, not separate CTI tables — the same pattern `character.characters` already uses for types needing no dedicated apparatus.
- **Knowledge items carry a single simplified subject reference**, not the plural "subject entities" association DOMAIN_MODEL.md §15.1 describes. Sufficient for Phase 5's one-item-one-concealed-thing use case; Phase 7 should promote to a junction table if a real requirement for multiple subjects appears.
- **`knowledge.knowledge_versions`, `.information_transfers`, `.expertise_domains`/`.character_expertise`, and `.public_knowledge` remain deferred to Phase 7** — only the three tables Phase 5's exit criteria actually needed were pulled forward.
- **No event-linked history on any of the five new timeline-state tables**, for the same reason Phase 4's three character-state tables have none: `narrative.events` does not exist until Phase 6. Each is a single mutable current row per `(timeline, target)`, enforced by its primary key.
- **`campaign.character_state` was not given a `current_location_id` column.** DATABASE_MODEL.md §17's example prose lists "current location" among tracked state, but `campaign.character_location_history`'s open row already serves that purpose (same "`NULL` end = current" convention `campaign.party_memberships` uses), so no change to the already-shipped Phase 4 table was needed.

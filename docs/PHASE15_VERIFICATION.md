# Phase 15.1 Verification

Evidence for Phase 15.1 (GM world-content definitions) on branch `phase15/gm-authoring`, recorded against [PLAN.md Phase 15](PLAN.md) and [ADR 0015](adr/0015-typed-world-content-authoring.md). **Status: implementation complete and merged (PR #65, `60d5bc9`); automated gates green; manual browser and accessibility verification NOT performed** (see below). Phase 15.1 is a **subset** of Phase 15: **Phase 15 as a whole is incomplete**, and the remaining campaign-operations and world-structure work is the checkpoint sequence in [PLAN.md Phase 15](PLAN.md). Phase 16 is blocked by the Phase 15 completion gate.

**Disclosed limitations (2026-10-05):** audit rows written by the 15.1 commands *before checkpoint 15.2A-3* copy up to 1,000 characters of narrative per field into `audit.change_log.changed_fields`, and the 15.1 authoring routes stored the full authoring view, including GM-only notes and background, in idempotency replay rows. **New writes no longer do either (15.2A-3, resolved).** Existing rows remain until the owner-gated checkpoint 15.2A-4. Audience-preview reads are audited as of 15.2A-3.

## What was delivered

| Area | Delivered |
|---|---|
| Schema | Migration `113_organization_cycle_guard` (`world.enforce_organization_no_cycle()` trigger; refuses to install over an existing cycle). No other schema change. |
| Commands | `create/update` for locations (ten non-dungeon categories), organizations (six kinds), religions, NPC identity, knowledge items; quest definitions (create/update plus stage and objective add/update/reorder/remove). All use `canon.edit`, current authority re-checked under lock, `row_version` optimistic concurrency, atomic subtype creation with a `gm_entry` source, bounded audit diffs, and campaign-scoped idempotency. |
| Lifecycle | `npc`, `quest`, `knowledge_item` and the place/organization/religion types join the Phase 14 registry. Publish and archive take per-type hooks (reference publication, hierarchy children, headquarters use, quest completeness, knowledge subject) shared by commands and read models. |
| State-command guards | Every command that writes state against a lifecycle-guarded entity takes it `FOR SHARE` and refuses one that is not canon and active. |
| Read gating | Explorer, character, quest list/detail, knowledge list/detail, relationships, AI and encounter paths hide unpublished definitions from callers without `canon.edit`. Editors get `canon_status`/`lifecycle_status` on quest and knowledge lists and an editor-only `canon_status` filter on world search. |
| Freezes | Quest structure freezes once progress exists (`quest_has_progress`); a knowledge statement, type, and subject freeze once any knower, party, discovery, public-knowledge, version, or event-effect row exists (`knowledge_already_known`). |
| Portal | Create/edit routes for locations, organizations, religions, NPCs, quests, and knowledge claims on shared shells (`ContentCreatePage`, `ContentEditPage`, `ReferenceCombobox`): validation summaries, unsaved-change guard, stale-write recovery that keeps the user input, `replace` navigation, direct-reload routes, announcements, entry and Edit links for editors only. |
| Dev data | `scripts/setup_phase15_world_content.py` authors a sample body of content through the production commands; idempotent; preview by default; same local-target safety guards as the Phase 13C fixture; a unit guard blocks raw inserts of authored-content tables in `scripts/`. |

## Commands run and results (local PostgreSQL 18)

| Check | Result |
|---|---|
| `uv run ruff format --check .` / `ruff check .` | clean |
| `uv run mypy src` | no issues (170 files) |
| `uv run pytest tests/unit tests/database tests/scenario` | 5786 tests: 5785 passed, 1 failed (below) |
| Migration round trip on a throwaway database: `upgrade head`, `downgrade 112_actor_idempotent_requests`, `upgrade head`, `alembic check` | all rc=0, no drift |
| Portal `npm test` / `npm run lint` / `npm run build` | 268 files, 1931 tests passed / clean / build OK |
| `git diff --check` | clean (only LF-to-CRLF working-copy notices) |

Explained non-pass: `tests/unit/test_config.py::test_local_session_allowed_origins_defaults_to_dev_topology_outside_production` fails because the developer `.env` adds an extra origin; it fails identically on the baseline and is environment-only, not a product failure.

CI on the pushed head is the merge gate and was not observed from this session.

## Concurrency evidence (real PostgreSQL)

`tests/database/test_content_authoring_concurrency.py` holds a transaction open and starts a racer that must block on the entity lock: edit vs edit, edit vs archive, edit vs publish, submit vs edit, opposing reparents and organization reparents (cycle prevention), child vs parent archive and draft delete, creation vs role revocation and campaign archive, identical idempotent creates, headquarters archive vs assignment, quest structural edit vs first progress write, and knowledge reword vs first reveal. A lock-order deadlock found by these tests was fixed (membership, roles and account before campaign; recorded in SYSTEM_ARCHITECTURE §7.1).

## Not verified

- **Manual browser verification** of every authoring route (create, edit, stale write, unsaved-change prompt, direct reload) was not performed; automated Testing Library tests only.
- **Accessibility** (keyboard-only operation, screen-reader announcements, focus order, 200% zoom, reduced motion) was not manually verified; only roles, names, and live-region text are asserted in tests.
- The Phase 14 navigation correction remains manually unverified.
- The dev-data script was not applied to the developer database. To apply it after the Phase 13C fixture exists:
  `uv run python scripts/setup_phase15_world_content.py --user-id <world owner user id> --apply` (omit `--apply` to preview).

## Deviations from the plan

- Migration revision id is `113_organization_cycle_guard` (the plan text used a longer name).
- Business operating status and quest `sequence_number` assumptions in the plan were corrected from the actual schema.
- The quest list now includes authored, not-yet-started definitions for editors; the audience-safe organization detail route is new; knowledge lists gained editor-only status fields. These were required to make authored records reachable and are documented in ENTITY_LIFECYCLE and UI_DESIGN.
- The dev-data script runs in one transaction (preview rolls it back) rather than one connection per item.

## Deferred (Phase 15.2 and later)

Sessions, events and corrections, world-time authoring, timeline state, quest activation and progress, knowledge reveal and per-knower state, `world.relationships`, items and inventory, encounters, PC creation by the GM, dungeons and maps, import, AI authoring, Foundry authoring. The 15.8 exit scenario and 15.9 exit criteria close only after Phase 15.2.

## Commits

Merge base with `main`: `3046714`. Branch commits, oldest first: `db6b501` docs/ADR 0015, `03bd97d` no-store, `6eb917b` state-command guards, `e62166e` Location backend, `e1c622a` Location portal, `c4af6e8` migration 113, `1711426` Organization/Religion backend, `7583741` Organization/Religion portal, `8649edd` NPC backend, `a024b2c` NPC portal, `8f62ded` Quest backend, `79a125d` Quest portal, `241aaaa` Knowledge, `fa8261c` cross-record isolation, `cb816a4` dev data, `5f04460` scenario.

## Checkpoint 15.2A-1 — production relationship-capability defaults

Branch `phase15/2a1-relationship-defaults` (stacked on the 15.2-0 documentation branch; no code overlap). **Status: implemented; automated gates below green locally; CI on the pushed head not observed; manual Compose walkthrough not performed.**

| Area | Delivered |
|---|---|
| Migration | `114_relationship_defaults`: seeds the approved matrix as production reference data and reconciles the seven built-in types on upgrade (adds missing pairs, deletes pairs outside the matrix, lists removals in a NOTICE and one `audit.change_log` maintenance row with `actor_service = 'migration'`; custom-type rows left in place). The matrix is a literal in the migration (frozen-seed rule), not a YAML file. Downgrade deletes exactly the matrix pairs and does not restore removed extras. |
| Resolver | `domain/access.py`: `BUILTIN_RELATIONSHIP_CAPABILITIES`, `ADMITTED_RELATIONSHIP_TYPES`, `relationship_capability_permitted`. A relationship-derived capability is effective only with a database row **and** code-matrix permission **and** an active type. The effective-access panel applies the same conjunction. Role capabilities and resource grants are untouched. |
| Bootstrap | A character is a selectable perspective only when the user holds `character.view_knowledge` for it (owner, primary_controller, co_controller, portrayer). Previously any relationship-derived capability listed the character. |
| Dev data | `setup_phase13c_dev_data.py` no longer seeds the mapping; it exits with a clear message if the table is empty. Script guard forbids inserts into the mapping table with no marker exception. |
| Tests | `tests/database/test_relationship_capability_defaults.py` (35): clean-install matrix, migration/code matrix agreement, idempotent insert, per-type resolver results, former_controller/custom/inactive/stray-row denial, bootstrap perspective selection per type and revocation on the next call, and a throwaway-database upgrade over dev-style rows with reconciliation, audit row, custom row kept, downgrade, re-upgrade, and `alembic check`. Existing tests updated: bootstrap perspective tests, `test_api_access_grants` (owner type), vertical-slice scenario (`player2` is a `viewer` so the direct grant is their only source). |

Test seams (tests only): an autouse fixture relaxes the code-matrix check for the many legacy access tests that build arbitrary custom relationship types (opt out with `@pytest.mark.real_relationship_policy`), and an autouse guard restores the built-in matrix after each database test because 30 existing cleanups delete mapping pairs by (type, capability) and would otherwise remove seeded production rows from the shared session database. `make_relationship_type_capability` is now `ON CONFLICT DO NOTHING`.

### Commands run (local PostgreSQL 18)

| Check | Result |
|---|---|
| `uv run ruff format --check .` / `ruff check .` / `mypy src` | clean (170 source files) |
| `uv run pytest tests/unit tests/database tests/scenario` | 5838 tests: 5837 passed, 1 failed (below) |
| Migration round trip on a throwaway database (in the new test file): `upgrade 113` → seed dev-style rows → `upgrade 114` → `downgrade 113` → `upgrade head` → `alembic check` | all passed, no drift |

Explained non-pass: `tests/unit/test_config.py::test_local_session_allowed_origins_defaults_to_dev_topology_outside_production` fails because the developer `.env` adds an extra origin (environment-only, identical on the baseline).

### Not verified

- CI on the pushed head; portal `npm test`/lint/build (no portal code changed); the manual Compose walkthrough (migrate → invite → grant `owner` → select perspective) from the plan.
- Existing developer databases: running the migration over one removes the old `owner` → `edit_*`/`control`/`interact`/`discover` extras that the dev script created; the removed pairs are in the migration NOTICE and the maintenance audit row.

## Checkpoint 15.2A-2 — reporting-role (`app_read_only`) boundary

Commit on `phase15/completion`. **Status: implemented; local automated gates green; CI and manual checks not observed.** Decision D-5 (owner decision, plan recommendation option a, deny by default) was applied as recommended.

| Area | Delivered |
|---|---|
| Migration | `115_reporting_role_boundary`: revokes `SELECT` on all tables in the 13 application schemas from `app_read_only`, revokes the default privilege for future tables created by `migration_owner`, then grants `SELECT` only on an allowlist of 31 lookup tables plus 17 seeded `rules.*` reference tables (`REPORTING_READABLE_TABLES`). Excluded on purpose: `rules.item_definitions` (gains world-owned homebrew in a later checkpoint) and `rules.world_rulesets`. Sequences unchanged. Downgrade restores revision 001's grants. No row-level security. |
| Consumer inventory | None at runtime: Compose `api` uses `app_read_write`; `database_recovery.py` only asserts the role exists; Terraform lists it for IAM login; remaining references are docs and grant tests. |
| Tests | `tests/database/test_reporting_role_boundary.py` (32): 25 named sensitive tables denied (credential/token hashes, session and CSRF storage, idempotency stores, audit log, AI context, GM-only content); every table outside the allowlist denied and every allowlisted table readable; real `SET ROLE app_read_only` reads refused for secrets and allowed for a lookup; a new table created by `migration_owner` in `security`/`core`/`campaign` is denied to `app_read_only` and granted DML to `app_read_write`; runtime role unchanged; throwaway-database upgrade from 114 → 115 → downgrade → head → `alembic check`. `test_role_grants.py` no longer asserts a blanket `app_read_only` `SELECT` (its write-denial test remains). |
| Docs | DATABASE_CONVENTIONS §27.1/§27.4 (deny-by-default, reporting is not administrator access, reviewed-views contract, no RLS), DATABASE_RECOVERY note that grants restore with the dump. |

### Commands run (local PostgreSQL 18)

| Check | Result |
|---|---|
| `uv run ruff format --check .` / `ruff check .` / `mypy src` | clean |
| `uv run pytest tests/unit tests/database tests/scenario` | 5683 tests: 5682 passed, 1 failed (below) |
| Round trip on a throwaway database (in the new test file) | passed, no drift |

The test count fell from 5838 to 5683 because the ≈190 parametrized blanket `app_read_only` grant checks were replaced by the targeted boundary tests above. Explained non-pass: `tests/unit/test_config.py::test_local_session_allowed_origins_defaults_to_dev_topology_outside_production` (developer `.env` adds an origin; environment-only).

### Not verified

CI on the pushed head; the recovery script `verify` against a live restore (it only asserts the role exists and is unchanged by this migration).

## Checkpoint 15.2A-3 — stop narrative leakage; audited, closed preview

Commit on `phase15/completion`. **Status: implemented; local automated gates green; CI and manual checks not observed.** Owner decisions D-3, D-4, and D-27 were applied as the plan recommended (GM-only fields hidden from non-editors; `sensitive_read` action in `audit.change_log`; receipts-only responses and replay bodies).

| Area | Delivered |
|---|---|
| Classification | `domain/data_classification.py`: `DataClass`, `COLUMN_CLASSES` (every TEXT/JSONB column of the authored and state tables; lookup/reference tables exempt), default-deny audit builders (`audit_change`/`audit_initial`/`audit_diff`; only `AUDIT_STRUCTURAL_FIELDS` keep values, everything else records `{"redacted": true}`), and `content_receipt`. `PLAYER_PRIVATE` is reserved and unused. |
| Audit | 15.1 commands now write redacted diffs; world, timeline, and campaign `description` diffs are redacted too. `reason` (the GM change note) is kept, GM-only. |
| Replay storage | Every 15.1 create/update/structural route (locations, organizations, religions, NPCs, knowledge, quests incl. stages/objectives) stores and returns a receipt: ids, `row_version`, `created`, `changed` (+ `record_id` for a quest child). Lifecycle routes already stored receipt-shaped bodies. |
| Preview | `api/preview.py`: closed `PREVIEW_ADAPTERS` registry (`quests`, `knowledge`; read-only, fixed GET routes, no dispatch parameter, ceilings exclude `PLAYER_PRIVATE`/`SECRET`). Every request that passes the actor's `access.manage` writes one metadata-only `sensitive_read` row (actor, world, resource kind/id, subject membership id, `shown`/`refused`, perspective-supplied booleans, correlation id); refusals are committed before the identical 404, including refusals raised by the resolver. Preview rows are not in the audit-history allowlist. |
| Migration | `116_sensitive_read_action`: seeds the `sensitive_read` action; conditional downgrade (refuses once referencing audit rows exist), like revision 103. |
| Projection (D-3) | `item_instances.origin_notes`, `campaign.location_state.condition_notes`, and `narrative.events.details` (world-explorer event detail and session detail) are returned only to callers holding `canon.edit`. |
| Portal | Write functions and `ContentCreate/EditPage`/`QuestEditor` types take receipts; the create flow navigates by the receipt id, edit/quest flows already refetched. |
| Tests | New: `test_data_classification.py`, `test_preview_registry.py`, `test_data_classification_schema.py` (live-schema introspection), `test_private_data_not_stored.py` (sentinel proof across every route family incl. replay and conflict), `test_sensitive_read_action_migration.py`, preview audit tests, D-3 projection test. Harness: `Actor.post` follows a receipt with the authoritative GET (`post_raw` returns the raw receipt); existing audit assertions updated to the redacted contract. |

### Commands run (local PostgreSQL 18)

| Check | Result |
|---|---|
| `uv run ruff format --check .` / `ruff check .` / `mypy src` | clean |
| `uv run pytest tests/unit tests/database tests/scenario` | one full run: 5719 tests, 5717 passed, 2 failed; the one real failure (`test_seeded_change_actions_cover_the_lifecycle`, which pins the action list) was fixed, and that file plus the new migration test were re-run green on their own (the full suite was not repeated after that one-line fix); the other failure is the known developer-`.env` origins test |
| Portal `npm test` / `npm run lint` / `npm run build` | 268 files, 1950 tests passed / clean / build OK |

### Not verified

CI on the pushed head; manual browser checks. Idempotency rows written before this checkpoint still hold full views until checkpoint 15.2A-4. Decision recorded: world/timeline/campaign replay bodies (public or campaign-visible descriptions) were not changed.

## Checkpoint 15.2A-5 — private-data policy foundation (Phase 16 prerequisite)

Commit on `phase15/completion`. **Status: implemented; focused tests green.** Decision D-6 applied as proposed.

- ADR 0016 (`docs/adr/0016-data-classification-and-private-data-handling.md`): the data classes, the handling matrix, retention/deletion/export/backup/log defaults, the host-administrator statement, and the Phase 16 obligations (classification, receipt-only mutations, no reporting grant, no preview adapter without a new decision). The existing-row scrub (D-2/D-28) is decided separately at 15.2A-4 and recorded as an addendum.
- SYSTEM_ARCHITECTURE §19: what telemetry may contain.
- `tests/unit/test_privacy_guards.py` (4): no column is `PLAYER_PRIVATE`/`SECRET`; any future private field would be redacted by every audit builder; no preview adapter can expose private data; a rejected request body is neither echoed nor logged.
- Checks run: `uv run pytest tests/unit/test_privacy_guards.py` (4 passed); ruff clean. The full suite was not re-run (no production behaviour changed in this checkpoint).

## Checkpoint 15.2R — canonical revision capture

Commit on `phase15/completion`. **Status: implemented; focused tests green; full suite run below.** Decision D-24 (option a: full GM-only snapshots, no diffs) applied as recommended.

- Migration `117_entity_revisions`: `core.entity_revisions` (`UNIQUE (entity_id, row_version)`, kind check, JSON-object check, append-only trigger on `UPDATE`, same-world trigger, `UPDATE`/`DELETE`/`TRUNCATE` revoked from the application roles, no access for `app_read_only`, `ON DELETE CASCADE` from the entity so deleting a draft removes its revisions). Matching SQLAlchemy metadata (`persistence/tables/core.py`) so `alembic check` is clean.
- `commands/_revisions.py`: `snapshot_from_view` (JSON-safe authored record, minus server-computed presentation fields) and `capture_revision`. `audit_content_write` takes a `view_loader` and captures one revision per real create/update (a quest stage/objective change is an *update* of the quest aggregate); every typed route (locations, organizations, religions, NPCs, knowledge, quests) passes its authoring view loader; lifecycle transitions capture a status-only revision. No-ops, replays, stale writes, and refusals capture nothing.
- Revision capture never reads audit: the capture module has no audit dependency and a test pins it. Audit redaction (15.2A-3) deployed before this checkpoint.
- Tests: `tests/database/test_entity_revisions.py` (10): full GM-only snapshot at the entity version, prior version preserved on update, no revision for no-op/replay/stale write, lifecycle revisions, quest child snapshot, append-only update refusal, same-world trigger, grants (app roles cannot update/delete; reporting role cannot read), draft-delete cascade, audit-independence guard, and a throwaway-database migration round trip with `alembic check`.
- Limitation: history begins here; edits before this checkpoint have no snapshot and nothing is backfilled from audit. No read path or UI until 15.3C-2.

Commands run (local PostgreSQL 18): `ruff format --check`, `ruff check`, `mypy src` clean. Full Python suite once: 5737 tests, 5732 passed, 5 failed — the known `.env` origins test, plus four consequences of adding a table that were then fixed (the expected table lists in `test_persistence_tables_package.py`, the live-schema classification of `core.entity_revisions`, and the entity-FK classification registry, where `entity_revisions.entity_id` is a reviewed owned cascade). Those four test files, plus the new revision tests and the role-grant tests, were re-run green on their own; the full suite was not repeated after those fixes. Portal unchanged by this checkpoint.

## Checkpoint 15.2W-1 — calendars and world-time points

Commit on `phase15/completion`. **Status: implemented; local automated gates below; CI and manual browser/accessibility checks not performed.** Decisions D-11 (calendar dates in minutes from year zero; narrative points server-allocated into gaps) and D-12 (minimal calendar authoring, no editing after use) applied as recommended. No migration (the tables already existed).

| Area | Delivered |
|---|---|
| Domain | `domain/world_time.py`: calendar normalization, `calendar_sort_key`, derived precision, `allocate_narrative_sort_key` (strictly between neighbours, `world_time_no_gap` when none fits), display text, error codes `calendar_id_invalid`/`world_time_id_invalid`/`world_time_no_gap`. |
| Commands | `commands/_operations.py::lock_operation_scope` (the shared start for campaign operations, delegating to `lock_authoring_scope` and adding the campaign's own timeline); `commands/world_time.py`: `create_calendar` (world row `FOR SHARE`, `world.manage` re-resolved under lock) and `create_world_time` (operation scope, calendar `FOR SHARE`, per-world advisory lock for allocation). |
| API | `GET/POST /worlds/{id}/calendars` (view/manage; actor idempotency), `GET /campaigns/{id}/calendars`, `GET/POST /campaigns/{id}/world-times` (`canon.edit`; keyset-paged latest first; campaign idempotency). Id-only receipts; audit rows hold structural values only (labels and descriptions redacted); human principals only; the world's `available_actions` gain `create_calendar`. |
| Portal | `/worlds/:worldId/calendars/new`, `/app/:campaignId/world-times`, reusable `WorldTimePicker`/`WorldTimeForm`, "New calendar" on the world page, and a Campaign Home "Game master tools" card (the home for later checkpoints' entry points). |
| Dev data | `setup_phase13c_dev_data.py` creates its world times through `create_world_time` on a one-month 400-day fixture calendar (every non-negative fixture key is exactly representable, so keys and ordering are unchanged); the guard now covers `core.calendars`, `core.calendar_months`, `core.world_times` (the AI smoke test keeps one marked direct insert). |
| Tests | Unit policy tests (46 incl. gaps and invariants), 28 API/concurrency tests (receipts, authority per world, foreign ids indistinguishable from missing, CSRF/Origin/Foundry, replay and conflict, redacted audit, paging, narrative placement, closed gap, archived campaign; a real-PostgreSQL race where two placements into one gap serialize and stay ordered), 22 portal tests (validation util, calendar page, world-times page), and the first steps of `tests/scenario/test_phase15_completion_flow.py`. |

Commands run (local PostgreSQL 18): ruff format/check and mypy clean; portal `npm test` (271 files, 1972 tests) / `npm run lint` / `npm run build` clean; the focused Python suites above and the dev-data tests (`test_setup_phase13c_dev_data.py`, `test_setup_phase15_world_content.py`) green. Full Python suite (once, on the final tree of this checkpoint): 5787 tests, 5786 passed, 1 failed (the known developer-`.env` origins test).

Not verified: CI; manual browser/accessibility (keyboard operation of the picker and calendar form, narrow width); the dev-data script against a pre-existing developer database (the label lookup tolerates the trailing space older fixture rows kept, but this was exercised only on throwaway databases).

## Checkpoint 15.2W-2 — campaign clock

Commit on `phase15/completion`. **Status: implemented; local automated gates below; CI and manual browser/accessibility checks not performed.** Decision D-10 (typed state `campaign.timeline_clocks`, branch-aware read) applied as recommended.

| Area | Delivered |
|---|---|
| Migration | `118_campaign_clock`: `campaign.timeline_clocks (timeline_id PK, current_world_time_id, last_event_id, row_version, …)` with `core.set_updated_at`, `core.bump_row_version`, the shared same-timeline event guard, and a world-agreement trigger; event types `time_advanced` and `time_corrected`. Metadata, table lists, and grants tests updated. |
| Domain / queries | `domain/campaign_clock.py` (errors `clock_not_advanced`, `clock_not_set`, `clock_unchanged`); `queries/campaign_clock.py::resolve_effective_clock`: the timeline's own row, else its parent's effective clock bounded by the branch point, else the branch point itself. |
| Commands | `advance_campaign_clock` (strictly later than the effective value; first write on a timeline creates its own row at `expected_row_version` 0) and `correct_campaign_clock` (own clock only; cites the event it corrects, which must still be the clock's last event; any different time). Each writes one event, one `current_world_time_id` effect, and the clock row atomically. A concurrent first write is classified as a stale write (`ON CONFLICT DO NOTHING`). Lock order recorded in SYSTEM_ARCHITECTURE §7.1 (operations section). |
| API | `GET /campaigns/{id}/clock` (`campaign.view`), `POST …/clock/advance` and `…/clock/correct` (`canon.edit`, campaign idempotency, id-only receipts incl. `event_id`, one audit row citing the event, human principals only). |
| Portal | `CampaignClockCard` on Campaign Home: current time for every member (branch carry-over labelled); editors advance or correct (confirmation for a correction); messages for a non-later time, an unavailable time, and a stale clock. |
| Tests | 14 API tests (events, effects, chaining, refusals, stale, replay, correction and its cause, foreign ids, authority/CSRF/Origin/Foundry, archived campaign, branch inheritance, bounding and divergence, DB invariants), 2 real-PostgreSQL races (two advances at one version; two first advances), a migration round trip with `alembic check`, 7 portal tests, and scenario step 9. |

Commands run (local PostgreSQL 18): focused Python suites above green; portal `npm test` (272 files, 1979 tests) / `npm run lint` / `npm run build` clean. Full Python suite on the final tree: 5809 passed, 1 failed (the known developer-`.env` test `test_local_session_allowed_origins_defaults_to_dev_topology_outside_production`), 933 s.

Known behaviours: clock events are ordinary recorded events and so appear in event lists; a later checkpoint (events, 15.2E-1) decides whether system events are filtered from player feeds. Not verified: CI; manual browser/accessibility; keyboard operation of the correction dialog.

## Checkpoint 15.2B-1 — player-character identity and lifecycle

Commit(s) on `phase15/completion`. **Status: implemented; local automated gates below; CI and manual browser/accessibility checks not performed.** Decisions D-7 (PCs join the lifecycle registry; draft then publish; archive refused while a user is linked) and D-8 (`player_user_id` never set or read; authorization only through relationships) applied as recommended. No migration.

| Area | Delivered |
|---|---|
| Registry | `player_character` is lifecycle-eligible (so every lifecycle-gated read surface, the state-target guard, and the draft-delete flow cover it); the registry text that deferred PC identity to Phase 16 is corrected; `character.player_characters` is owned (cascade) for an unreferenced draft. |
| Access | A relationship confers capabilities only for a `canon` and `active` character (a draft PC grants no perspective even with a relationship in place). |
| Commands | `create_player_character` / `update_player_character` are thin wrappers over the shared `create_character_identity` / `update_character_identity` (the NPC commands are wrappers over the same functions), so lock order, species and origin validation, descriptions, and the audit/revision shape are identical. |
| API | `/campaigns/{id}/authoring/player-characters` (`GET options`, `POST`, `GET {id}`, `POST {id}/update`); each kind is a 404 at the other kind's route. |
| Portal | Character kind chooser, PC create page, one edit route for both kinds, edit link and **Link a player** on the World detail (Access opens with the character preselected). |
| Dev data | `setup_phase13c_dev_data.py` creates its player characters through the command and publishes them (no direct `character.player_characters` insert, `player_user_id` unset); the guard now covers `character.characters`, `character.player_characters` and `character.character_descriptions` (two fixture exceptions are marked). |
| Tests | 11 API tests (draft PC and unset `player_user_id`, round trip with redacted audit and revisions, route isolation both ways and a bare character, authority, publish waits for origin, archive guard and revoke, draft delete removes identity rows, draft invisible on every character read then visible once published with no GM notes, perspective appears after publish and disappears after revoke/archive under the real policy, replay and conflict, atomic failure), 2 real-PostgreSQL races (archive vs grant, both orders), portal route/control tests. |

Commands run (local PostgreSQL 18): ruff format/check and mypy clean; portal `npm test` (273 files, 1987 tests) / `npm run lint` / `npm run build` clean. Full Python suite: 5831 passed, 1 failed (the known developer-`.env` test `test_local_session_allowed_origins_defaults_to_dev_topology_outside_production`), 1209 s. The tests added after that run started (atomic failure, the corrected replay count, both races, scenario steps 5-6, the dev-data guard) were rerun on their own: 18 passed. One mid-run caveat: a second pytest session ran against the same database during the full suite; no table-count test failed.

Not verified: CI; manual browser/accessibility at 390/1280/2560 px (planned for B-1 and still owed); keyboard operation of the chooser and the preselected Access control; the dev-data script against a pre-existing developer database.

## Checkpoint 15.2B-2 — character builds and bootstrap state

Commit(s) on `phase15/completion`. **Status: implemented; local automated gates below; CI and manual browser/accessibility checks not performed.** Decision D-9 (builds immutable once created; a change is a new build plus an activation event; the first activation is administrative) applied as recommended.

| Area | Delivered |
|---|---|
| Migration | `119_character_build_activated`: the `character_build_activated` event type only (no new tables). |
| Domain / commands | `domain/character_builds.py` (input shapes, bounds, fixed-code errors) and `commands/character_builds.py`: `create_character_build` (build and all children in one transaction; every referenced ability, class, subclass, skill, proficiency type, feature and spell must be canon content of the campaign's pinned ruleset version, a subclass must belong to its class, a proficiency's target must match its type's kind; one non-disclosing `build_option_not_available`), `initialize_character_state` (administrative, once), `activate_character_build` (first activation administrative; later ones record an event and effect with the replaced value). |
| Resolver | `resolve_effective_character_build_id` now recovers the baseline when an ancestor changed the build by event only after the branch point. |
| API | `GET /campaigns/{id}/authoring/character-build-options`, `GET|POST …/characters/{id}/builds`, `POST …/builds/{id}/activate`, `POST …/state/initialize`; all `canon.edit`, campaign idempotency, id-only receipts, redacted audit. |
| Portal | Builds page (state, list, activate with confirmation), new-build form (incl. known and prepared spells), "Builds and starting state" link on a character. |
| Dev data | `setup_phase13c_dev_data.py` creates builds and starting state through the commands (one `create_character_build` per character, first activation administrative); the per-row insert helpers were removed and the guard now covers the build tables and `campaign.character_state`. Temporary hit points, exhaustion and death saves, which the starting-state command does not take, are still reconciled by a direct administrative update, as before. |
| Tests | 18 API tests (options, administrative state once, atomic build creation without events, NPC and PC, bare/foreign characters refused, invalid shapes, rules scoping incl. spells, replay, list/state, administrative then event activation with effect, stale and repeat, foreign build, a branch keeping its branch-point build), a migration round trip, a real-PostgreSQL race (two activations from one view), 8 portal tests, and scenario step 5. |

Decisions I made that you may want to review (not owner decisions in the plan): (1) the optimistic token for an activation is `expected_active_build_id` (the build the editor saw as active) rather than the character's `row_version`, because an activation changes timeline state, not the definition, and a definition version bump would add a revision with no content change; (2) an event activation requires the character to be published (a draft cannot take part in an event) and the campaign clock to be set (the event is recorded at the clock's time), each with its own error code; (3) expertise can be sent through the API but the form does not offer it yet.

Not verified: CI; manual browser/accessibility (keyboard operation of the build form, narrow width).

Commands run (local PostgreSQL 18): ruff format/check and mypy clean; portal `npm test` (274 files, 1995 tests) / `npm run lint` / `npm run build` clean. Full Python suite on the final tree, run with no other database session active: 5854 passed, 1 failed (the known developer-`.env` test `test_local_session_allowed_origins_defaults_to_dev_topology_outside_production`), 1077 s. The dev-data tests (`test_setup_phase13c_dev_data.py`, `test_setup_phase15_world_content.py`) are part of that run.

## Checkpoint 15.2C-1 — party definition

Commit(s) on `phase15/completion`. **Status: implemented; local automated gates below; CI and manual browser/accessibility checks not performed.** Decision D-30 (an archived party stays referenced by history, is hidden from pickers, and refuses new membership and knowledge writes) applied as recommended.

| Area | Delivered |
|---|---|
| Migration | `120_party_definition`: `campaign.parties` gains `row_version` (bumped by `core.bump_row_version()`), `lifecycle_status_id` (backfilled `active`; a `BEFORE INSERT` trigger defaults it so pre-existing inserts keep working), `archived_at`, `created_by_user_id`, and indexes for the two foreign keys. Metadata, round trip with a populated party, and `alembic check` covered. |
| Commands | `create_party` (party and campaign attachment in one transaction), `update_party`, `archive_party`, `restore_party`; lock order operation scope then the party row `FOR UPDATE`; a party is reachable only through a campaign it is attached to (any other id is the same non-disclosing 404). |
| Shared check | `validate_campaign_party(..., require_active=True)` refuses an archived party; the knowledge reveal to a party uses it. Reads (perspective, quest progress) keep resolving an archived party, so history stays intact. Membership writes use it in 15.2C-2. |
| API | `GET|POST /campaigns/{id}/parties`, `GET …/parties/{id}`, `POST …/update|archive|restore`; list and detail are `campaign.view` (archived parties only for an editor who asks), writes `canon.edit`, campaign idempotency, id-only receipts, redacted audit (name structural, description redacted). |
| Portal | Parties list (show archived, archive/restore with confirmation), create form, edit form (stale-write handling), link from Game master tools. |
| Dev data | `setup_phase13c_dev_data.py` creates and attaches its parties through `create_party`; a fixture party that pre-exists but is unattached is attached by a marked direct insert. The guard covers `campaign.parties` and `campaign.campaign_parties` (two throwaway smoke-test inserts are marked). |
| Tests | 14 API tests (creation and attachment, validation, authority and read access, update/no-op/stale, archive and restore with audit codes, foreign and unattached parties indistinguishable from missing, replay, atomic failure, the shared active check, legacy parties start active), 2 real-PostgreSQL races (two edits; edit versus archive), a populated migration round trip, 7 portal tests. |

Not verified: CI; manual browser/accessibility (list at narrow width, keyboard operation of the archive dialog).

Commands run (local PostgreSQL 18): ruff format/check and mypy clean; portal `npm test` (275 files, 2002 tests) / `npm run lint` / `npm run build` clean. Full Python suite on the final tree, no other database session active: 5872 passed, 1 failed (the known developer-`.env` test `test_local_session_allowed_origins_defaults_to_dev_topology_outside_production`), 1120 s.

## Checkpoint 15.2C-2 — temporal party membership

Commit(s) on `phase15/completion`. **Status: implemented; local automated gates below; CI and manual browser/accessibility checks not performed.** No new owner decision.

| Area | Delivered |
|---|---|
| Migration | `121_party_membership_events`: `narrative.event_types` `party_member_joined` and `party_member_left`; `campaign.party_memberships.joined_event_id` and `left_event_id` (nullable, `ON DELETE SET NULL`, partial indexes), a check that a left event needs an end, and a trigger that both events belong to the membership's own timeline. Metadata, round trip and `alembic check` covered. |
| Commands | `add_party_member` and `end_party_membership`. Each records an event at the membership's own world time (the character is the participant) and a `party_membership` effect (previous to new party id), writes the membership citing the event, and bumps the party version, which is the optimistic token (`expected_party_row_version`). Lock order: operation scope, the party row `FOR UPDATE`, the member entity `FOR SHARE`, the membership rows. The member must be a published, active NPC or player character of the world; the party must be active to add (ending is allowed on an archived party); the overlap is checked under the party lock (`party_membership_overlap`) and a database exclusion violation is classified the same way; a membership ends once and strictly after it began. |
| API | `GET|POST /campaigns/{id}/parties/{id}/members`, `POST …/members/{id}/end`; all `canon.edit` (membership is not exposed to other members), campaign idempotency, receipts with the event id, redacted audit (reasons are GM-only). |
| Portal | Party page with current members and history tables, an add form (character search, time picker, reason) and an end-membership dialog; "Members of …" link on the party list. |
| Dev data | `setup_phase13c_dev_data.py` adds its two fixture members through the command; the guard covers `campaign.party_memberships` (one smoke-test insert is marked). |
| Tests | 14 API tests (event, effect and version bump with redacted audit; ineligible members; time, version and archived-party checks; overlap and adjacency; end rules and the left event; foreign ids indistinguishable from missing; player authority; replay; atomic failure; a branch starting without rows; the party perspective appearing on join and going on leave under the real policy; database event guards), 4 real-PostgreSQL races (two adds from one version, an overlap that is a conflict not a 500, add versus archive in both orders), a migration round trip, 5 portal tests, and scenario step 7. |

Known behaviours: a branch has no membership rows of its own until something is written there (the existing timeline-scoped model; inheritance up to a branch point is not implemented for memberships and is not claimed). Not verified: CI; manual browser/accessibility (keyboard operation of the tables and dialog).

Commands run (local PostgreSQL 18): ruff format/check and mypy clean; portal `npm test` (276 files, 2007 tests) / `npm run lint` / `npm run build` clean. Full Python suite on the final tree, no other database session active: 5891 passed, 1 failed (the known developer-`.env` test `test_local_session_allowed_origins_defaults_to_dev_topology_outside_production`), 1147 s. An earlier full run of this checkpoint's tree had four failures in `tests/database/test_party_memberships.py`: the new race tests committed membership rows that the shared `_purge_user_worlds` helper (which runs with triggers and foreign keys off) did not delete, and those older tests read the table unscoped. The helper now also removes party memberships, clocks, character state, builds, their children, character subtype rows, and entity revisions; the rerun above is clean.

## Checkpoint 15.2D-1 — session definition and lifecycle

Commit(s) on `phase15/completion`. **Status: implemented; local automated gates below; CI and manual browser/accessibility checks not performed.** Decision D-13 (play status derived from `scheduled_for`, `started_at` and `ended_at`; `lifecycle_status` only for archive) applied as recommended. The at-most-one-in-progress rule belongs to the start command (checkpoint 15.2D-2).

| Area | Delivered |
|---|---|
| Migration | `122_session_definition`: `campaign.sessions` gains `row_version` (bumped by `core.bump_row_version()`), `scheduled_for`, `archived_at`, `created_by_user_id` and a partial index. `(campaign_id, session_number)` was already unique. Metadata, a populated round trip and `alembic check` covered. |
| Domain / commands | `domain/session_authoring.py` (derived play status, fixed-code errors) and `commands/session_authoring.py`: `schedule_session` (number from `max + 1` under a per-campaign advisory lock), `update_session`, `archive_session` (refused while in progress), `restore_session` (reason required). The session row is locked without a join and its status read separately, because a join inside a locking statement is re-evaluated after a wait and can return nothing (found by the edit-versus-archive race test). |
| Read model / API | The existing list and detail now return `scheduled_for` and the derived `play_status`; editors also get `row_version` and `available_actions`; archived sessions are hidden from, and a 404 for, anyone without `canon.edit`. New `POST /campaigns/{id}/sessions` and `…/{id}/update|archive|restore` (`canon.edit`, campaign idempotency, receipts carrying the number, redacted audit: number and planned start structural, title and summary redacted). |
| Portal | Session list status and planned-start columns, Schedule and Edit links for editors, a schedule form and an edit form (stale handling, planned start disabled after start) with archive and restore dialogs. |
| Dev data | The guard now covers `campaign.sessions`. The dev-data fixture still inserts its played sessions (with start and end times) directly, with a marked exception, because only the 15.2D-2 play commands can create played sessions; it is replaced there. |
| Tests | 15 API tests (consecutive numbers and creator, validation, derived status for all four states, authority, update/no-op/stale, a started session keeps its plan but can be retitled and cannot be archived, archive hides and restore returns with audit codes, foreign ids indistinguishable from missing, replay, atomic failure, numbering after gaps, legacy rows), 3 real-PostgreSQL races (six concurrent schedules get consecutive numbers; two edits; edit versus archive), a populated migration round trip, 12 portal tests, and scenario step 10. |

Not verified: CI; manual browser/accessibility (the datetime-local input, keyboard operation of the dialogs).

Commands run (local PostgreSQL 18): ruff format/check and mypy clean; portal `npm test` (277 files, 2016 tests) / `npm run lint` / `npm run build` clean. Full Python suite on the final tree, no other database session active: 5910 passed, 1 failed (the known developer-`.env` test), 1134 s; a second failure in that run (the dev-script guard, because the marked exception sat three lines above its INSERT instead of within two) was fixed, and the guard test and the dev-data tests were rerun: 51 passed.

## Checkpoint 15.2D-2 — session participation, run, and manual log

Commit(s) on `phase15/completion`. **Status: implemented; local automated gates below; CI and manual browser/accessibility checks not performed.** Decision D-14 (participants are characters only) applied as recommended; the one-in-progress rule of D-13 is enforced here.

| Area | Delivered |
|---|---|
| Migration | `123_session_participants`: `campaign.session_participants` (role check, one open row per session and character, a same-world trigger) and `ux_sessions_one_in_progress` (a unique partial index on started-but-not-ended sessions). Metadata, grants and package lists updated; populated round trip with `alembic check`. |
| Commands | `commands/session_play.py`: `start_session`, `add_session_participant`, `remove_session_participant`, `record_session_log_entry`, `end_session`. Start serializes on a per-campaign advisory lock; end and participant changes serialize on the session row; a log entry takes the row `FOR SHARE`, so it either lands before an end or sees the ended session. A participant is a published, active character of the world and a `player_character` or `npc` role must match its kind. The time of a start, end or log entry is the caller's or the campaign clock's (`clock_required` otherwise). |
| API | `POST /campaigns/{id}/sessions/{id}/start|end|participants|log` and `…/participants/{id}/remove` (`canon.edit`, campaign idempotency, id-only receipts, redacted audit). The earlier ungated end route is replaced: ending now needs the version the editor saw and a session in progress (ending an ended session is a 409, not a silent no-op). Session detail gains `participants` (editors only) and the derived actions now include start, manage participants, log and end. |
| Portal | The run page (status, clock card, start, participants, log, end) and **Run** links on the session list. |
| Dev data | Unchanged apart from the guard: the fixture still inserts its sessions directly (marked exception) because it needs fixed historical start and end timestamps and fixed numbers, which the play commands (always the current time, server numbers) cannot produce. |
| Tests | 19 API tests (start time rules, one session in progress, participant eligibility and roles, removal and re-adding, no changes after the end, log event shape with GM-only details hidden from players, entry validation, time validation, replay, atomic failure, end rules, authority, foreign sessions indistinguishable from missing, branch isolation, database guards), 3 real-PostgreSQL races (two starts; an end versus a participant change; a log entry versus an end), a migration round trip, 8 portal tests, scenario step 11, and the legacy end-session API and vertical-slice tests updated to the hardened command. |

Decisions I made that you may want to review: (1) ending a session that is not in progress is now a 409 instead of a silent no-op, and a start is required before an end (the plan's "end before start 409"); the legacy `end_session` tests and the vertical-slice scenario were updated, and the legacy test fixture's campaign was made active; (2) participant lists are visible only to editors (presence can name characters a player may not see); (3) start and end do not themselves record a campaign event: a session is not timeline state, and the manual log is the narrative record.

Not verified: CI; manual browser/accessibility of the run page at all widths, keyboard log entry and live-region announcements (planned for this checkpoint and still owed).

Commands run (local PostgreSQL 18): ruff format/check and mypy clean; portal `npm test` (278 files, 2024 tests) / `npm run lint` / `npm run build` clean. Full Python suite on the tree before two fixes, no other database session active: 5937 passed, 3 failed (the known developer-`.env` test and two real failures): the 15.2D-1 test that listed an editor's actions (they now include start, participants, log and end, so the expectation was updated) and the entity-reference classification test (the new `session_participants.character_id` reference is classified as blocking: a character that took part in a session keeps that history). The two affected test files were rerun after the fixes: 19 passed.

## Checkpoint 15.2E-1 — event recording and correction

Commit(s) on `phase15/completion`. **Status: implemented; local automated gates below; CI and manual browser/accessibility checks not performed.** Decision D-15 (option a: a correcting event with compensating effects and a link, applied atomically; refused with `correction_not_reversible` when state has moved on) applied as recommended.

| Area | Delivered |
|---|---|
| Migration | `124_event_corrections`: `narrative.event_corrections` (unique corrected event, kind, GM-only reason, optional replacement), a same-timeline trigger, an append-only trigger, and a deferred constraint trigger on `narrative.events` that refuses `voided` / `corrected` without a matching link. Metadata, grants and package lists updated; round trip with `alembic check`. |
| Commands | `commands/event_corrections.py`: `assess_event` (read-only, per-effect reversibility), `void_event`, `correct_event`. Lock order: operation scope, the event row, then the state rows reversed. Supported reversals: hit points, the active build, and party membership (join, leave). Any other effect kind, an effect that was not applied, a changed state, a correction, or an already corrected event refuses with its own fixed code (`correction_not_reversible`, `event_not_correctable`, `event_already_corrected`). Events of the campaign's own timeline only (ancestor, sibling and foreign events are one 404). |
| API | `GET /campaigns/{id}/events/{id}`, `GET …/correction-preview`, `POST …/void`, `POST …/correct` (`canon.edit`, campaign idempotency, id-only receipts, two audit rows with the reason redacted). A recorded narrative event is recorded through the existing `POST /campaigns/{id}/events`, unchanged. Foundry principals and anyone without `canon.edit` are refused; AI proposals have no path to these routes. |
| Portal | A record-event page, an event page with the effects, the preview and the Void and Correct dialogs, a Game master tools link, and session log entries that link to their event. |
| Dev data | The guard now covers `narrative.events`, `narrative.event_participants` and `narrative.event_effects`; the two fixture sites that insert events (and their participants) are marked because they need events in states such as draft and voided, at fixed times, to exercise audience visibility. |
| Tests | 14 API tests (voiding and correcting a narrative event with the link, the compensating effects and redacted audit; effective history excluding a voided event; a replacement; repeat, nested and missing reason; hit points restored and refused once the state moved on, then undone in order; an activation event restoring the previous build; a join removed and a leave reopened, with the dependent join refused while the membership has ended; the clock event refusing as unsupported; one 404 for branch, foreign and missing events; authority and Foundry refusal; replay; atomic failure; the status-link trigger; append-only and self-correction guards), 2 real-PostgreSQL races (two voids; a void versus a later hit-point change), a migration round trip, 7 portal tests, and scenario step 12. |

Known limits: reversals exist only for the three effect kinds above; location, condition, resource, clock, quest-objective, knowledge and relationship events cannot be corrected through this surface yet (each refuses plainly) and extend the catalog as their checkpoints land. Bulk correction is deferred as the plan says. Not verified: CI; manual browser/accessibility (correction dialog focus and the preview at narrow width).

Commands run (local PostgreSQL 18): ruff format/check and mypy clean; portal `npm test` (280 files, 2031 tests) / `npm run lint` / `npm run build` clean. Full Python suite on the final tree, no other database session active: 5961 passed, 1 failed (the known developer-`.env` test), 1322 s.

## Checkpoint 15.2E-2a — quest definition completion

Commit(s) on `phase15/completion`. **Status: implemented; local automated gates below; CI and manual browser/accessibility checks not performed.**

| Area | Delivered |
|---|---|
| Migration | `125_quest_gm_notes`: `narrative.quests.gm_notes` (GM-only, at most 4000 characters) with its check and comment; round trip with `alembic check`. |
| Commands | `commands/quest_children.py`: add and remove objective dependencies (prerequisite loops refused with `objective_dependency_cycle`; both objectives must belong to the quest; structural, so refused once progress exists), add and remove participants (published characters or organizations, one row per participant and role), add, update and remove outcomes (code immutable, unique per quest; removal deletes its rewards), add and remove rewards (a knowledge reward must name a usable knowledge item). `update_quest` gains `gm_notes` (omitted keeps, empty clears). All run under the authoring kernel: locks, expected version, idempotency, default-deny audit, revision snapshots. |
| API | Routes under `/campaigns/{id}/authoring/quests/{quest_id}`: `dependencies`, `participants`, `outcomes`, `outcomes/{id}/update`, `outcomes/{id}/rewards`, `rewards/{id}/remove` and the matching removals; the view and options gain the new collections and catalogs. |
| Portal | A completion section under the quest editor: notes, dependencies, participants, outcomes and rewards, each with validation messages and fixed-code error text. |
| Tests | 11 API tests, 2 real-PostgreSQL races (opposite prerequisites cannot both land; two edits from one version, one is stale), a migration round trip, 9 portal tests, the dev-script guard extended to the four quest tables, and scenario step 13. |

Decisions applied (not owner decisions): dependencies stop counting as quest progress and are themselves structural; item rewards are free text (no item domain target yet); only knowledge rewards carry a typed reference.

Not verified: CI; manual browser/accessibility of the completion section.


Commands run (local PostgreSQL 18): ruff format/check and mypy clean; portal `npm test` (280 files, 2041 tests) / `npm run lint` / `npm run build` clean. Full Python suite on the final tree, no other database session active: 5975 passed, 1 failed (the known developer-`.env` test), 1234 s.

## Checkpoint 15.2E-2b — quest runtime

Commit(s) on `phase15/completion`. **Status: implemented; local automated gates below; CI and manual browser/accessibility checks not performed.** Decision D-16 (option a: explicit GM commands only; the read model hints when all required objectives are complete) applied as recommended.

| Area | Delivered |
|---|---|
| Migration | `126_quest_runtime_events`: seven event types (`quest_activated|completed|suspended|resumed|abandoned`, `objective_activated|skipped`); `quest_failed` already existed and is not touched. Round trip with `alembic check`. |
| Commands | `commands/quest_runtime.py`: `change_quest_status` (activate, complete, fail, suspend, resume, abandon) and `set_objective_status` (available, active, completed, failed, skipped), with per-scope advisory lock, quest `FOR SHARE`, from-status guard (`expected_status`, stale otherwise), published-quest requirement, party validation, and world time from the request or the clock. The adapter `advance_objective` shares the lock and now refuses a suspended or finished quest. |
| Event correction | The E-1 catalog gains `quest_status_id` and `objective_status_id` (reversible while the state row is still the one the event last wrote; a first write is undone by removing the state). The adapter route's existing objective events become correctable too. |
| API | `GET /campaigns/{id}/quests/{quest_id}/progress`, `POST .../{quest_id}/activate|complete|fail|suspend|resume|abandon`, `POST .../quests/objectives/{id}/status` (`canon.edit`, campaign idempotency, id-only receipts, audit rows without the note). |
| Portal | Run quest page with per-scope cards, confirmed finishing actions, objective moves, and a link from the published quest's editor; event pages label the new effects. |
| Dev data | The guard now covers `campaign.quest_state` and `campaign.objective_state`; the two fixture sites in the dev-data script are marked (fixed statuses without a clock or events). |
| Tests | 15 API tests (a full run; the matrix; stale; unpublished and foreign quests; time from clock or request; party scopes; objective rules; hint without completion; adapter route interplay; authority, replay, audit; corrections restoring status and removing a first activation; refused after the state moved; unpublished quests stop running), 4 real-PostgreSQL races (complete vs fail, two first activations, suspend vs objective change, structural edit vs first activation), a migration round trip, 10 portal tests, and scenario step 14. |

Decisions applied (not owner decisions): prerequisites between objectives are shown to authors but not enforced at runtime (the GM decides); objective changes need an `active` quest for that audience; the quest-level note is stored as the event's GM-only details; a quest with no state row stays untracked for the adapter route.

Not verified: CI; manual browser/accessibility (confirmation dialog, objective buttons); the player-facing quest read model is unchanged and was not re-verified beyond the existing suites.


Commands run (local PostgreSQL 18): ruff format/check and mypy clean; portal `npm test` (281 files, 2051 tests) / `npm run lint` / `npm run build` clean. Full Python suite on the final tree, no other database session active: 5995 passed, 1 failed (the known developer-`.env` test), 1288 s.

## Checkpoint 15.2E-3 — knowledge runtime

Commit(s) on `phase15/completion`. **Status: implemented; local automated gates below; CI and manual browser/accessibility checks not performed.** Decision D-17 (the audiences the schema already has: party, character, NPC, organization and public-at-location; no new audience type) applied as recommended.

| Area | Delivered |
|---|---|
| Migration | `127_knowledge_runtime`: event types `knowledge_learned`, `knowledge_transferred`, `belief_changed`, `knowledge_made_public`; `last_event_id` (nullable, partial index, shared same-timeline trigger) on `knowledge.entity_knowledge` and `knowledge.public_knowledge`. Round trip with `alembic check`. |
| Commands | `commands/knowledge_runtime.py`: `reveal_knowledge_to_party` (the existing writer behind the kernel), `record_character_knowledge`, `record_knowledge_transfer`, `change_belief` (token: the event that last wrote the belief), `make_knowledge_public`. Published claim and knowers required, per-(timeline, claim, knower) advisory lock, claim and entities `FOR SHARE`, world time from the request or the clock. |
| Event correction | The E-1 catalog reverses learning and telling (belief and transfer removed), public records, party reveals and belief changes (previous values restored), while the row is still the one the event last wrote. |
| API | `GET /campaigns/{id}/knowledge/{item}/audience`, `POST .../reveal-to-party|learn|transfer|make-public`, `POST .../knowledge/knowers/{id}/belief` (`canon.edit`, campaign idempotency, id-only receipts, audit rows with interpretation text redacted). |
| Portal | A Who knows this page (parties, individual beliefs with Change belief, learned, told and public forms) linked from the claim editor; event pages label the new effects. |
| Dev data | The guard now covers the five knowledge state tables; four fixture sites in the dev-data script are marked. |
| Tests | 13 API tests (learn with belief, audit redaction and an unchanged truth; the statement freeze; knower and claim validity; one belief per knower and the clock; transfers with conveyed interpretation; belief changes with stale, no-op and empty cases; public locations seen by a player; party reveals; corrections of each kind and refusals after the state moved; branch isolation; authority, replay and foreign claims), 4 real-PostgreSQL races (two first learnings, two belief changes from one token, a statement edit vs the first learning, a correction vs a belief change), a migration round trip, 8 portal tests, and scenario step 15. |

Decisions applied (not owner decisions): transferring to someone who already knows the claim is refused (use Change belief); distorted versions (`knowledge_version_id`) are not written by these commands; the belief token is the last event rather than a new row version column; every command takes its time from the request or the campaign clock (the page uses the clock).

Not verified: CI; manual browser/accessibility (the forms and comboboxes with a screen reader); the player-facing knowledge reads are unchanged and were not re-verified beyond the existing suites.


Commands run (local PostgreSQL 18): ruff format/check and mypy clean; portal `npm test` (282 files, 2059 tests) / `npm run lint` / `npm run build` clean. Full Python suite on the final tree, no other database session active: 6013 passed, 1 failed (the known developer-`.env` test), 1221 s.

## Checkpoint 15.3A-1 — dungeon structure and GM state

Commit(s) on `phase15/completion`. **Status: implemented; local automated gates below; CI and manual browser/accessibility checks not performed.** Decision D-31 (option a: the dungeon root `row_version` covers its structural children; an area versions its own fields) applied as recommended.

| Area | Delivered |
|---|---|
| Registry and gating | `dungeon` and `dungeon_area` join the lifecycle registry (and so every read-side visibility gate that uses it). Publish preconditions: a dungeon needs a published parent location, an area a published dungeon. Archive precondition: a dungeon with active areas cannot be archived (`dungeon_has_active_areas`). The player-facing dungeon-area read now answers not-found for an unpublished area or dungeon and omits connections to areas the reader cannot see. The five structural child FKs are classified `OWNED_CASCADE`. |
| Migration | `128_dungeon_state_event`: the event type `dungeon_state_changed` (the plan expected no migration; one event type was needed). Round trip with `alembic check`. |
| Commands | `commands/dungeons.py` (create and update a dungeon and an area; add, update and remove connections, features, hazards and interactables, all against the dungeon version; removal only while a draft) and `commands/dungeon_state.py` (`set_dungeon_state` for an area, a connection, a feature, a hazard or an interactable, with a last-event token, an event and one effect per component). |
| Event correction | The E-1 catalog reverses dungeon state (restoring previous values, or removing a state row a first write created), including the interaction commands' own effects on the same rows, while the row is still the one the event last wrote. |
| API | `/campaigns/{id}/authoring/dungeons...` and `.../dungeon-areas/{id}` (read and update), and `POST /campaigns/{id}/dungeon-areas/{id}/state`; `canon.edit`, campaign idempotency, audit rows with content redacted, a revision of the authored aggregate for each real change. |
| Portal | Create and edit pages for a dungeon and an area, with areas, connections, contents and the state panel; an edit link on dungeon and area detail pages; the content-edit shell gains an optional sections-after-the-form hook. |
| Dev data | The guard now covers the dungeon tables and the five dungeon state tables; three fixture sites in the dev-data script are marked. |
| Tests | 13 API tests (drafts and areas; the dungeon and area versions; publish order and the archive block; a published parent location; versions of children and connections; connection rules; removal only while a draft; what players see; each kind of state; tokens, values and targets; published areas and the clock; correcting a state change; authority, replay and foreign dungeons), 3 real-PostgreSQL races (two structural edits from one version, an archive vs adding an area, two first state writes), a migration round trip, 11 portal tests, and scenario step 16. |

Decisions applied (not owner decisions): authoring joins areas of one dungeon (the schema still allows teleportation links across dungeons; existing ones are untouched); a conditional route's machine-checkable requirement fields are not authored yet (only the description); state changes use the campaign clock or a time given in the request; connection state is shown on both of its areas.

Not verified: CI; manual browser/accessibility (the inline forms and the state panel; narrow width); the discovery of hidden children is unchanged and was not re-verified beyond the existing suites.


Commands run (local PostgreSQL 18): ruff format/check and mypy clean; portal `npm test` (283 files, 2070 tests; two unrelated tests flaked once under load and passed on rerun) / `npm run lint` / `npm run build` clean. Full Python suite on the final tree, no other database session active: 6054 passed, 1 failed (the known developer-`.env` test), 1585 s. (An earlier run showed two downgrade-ordering failures that came from an orphaned second pytest session sharing the database; they pass alone and in the clean rerun.)

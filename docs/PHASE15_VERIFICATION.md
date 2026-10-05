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

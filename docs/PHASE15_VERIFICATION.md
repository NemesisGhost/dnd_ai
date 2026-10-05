# Phase 15.1 Verification

Evidence for Phase 15.1 (GM world-content definitions) on branch `phase15/gm-authoring`, recorded against [PLAN.md Phase 15](PLAN.md) and [ADR 0015](adr/0015-typed-world-content-authoring.md). **Status: implementation complete and merged (PR #65, `60d5bc9`); automated gates green; manual browser and accessibility verification NOT performed** (see below). Phase 15.1 is a **subset** of Phase 15: **Phase 15 as a whole is incomplete**, and the remaining campaign-operations and world-structure work is the checkpoint sequence in [PLAN.md Phase 15](PLAN.md). Phase 16 is blocked by the Phase 15 completion gate.

**Disclosed limitations (2026-10-05, until the named checkpoints ship):** audit rows written by the 15.1 commands copy up to 1,000 characters of narrative per field into `audit.change_log.changed_fields` (and `reason` stores the GM change note), and the 15.1 authoring routes store the full authoring view, including GM-only notes and background, in idempotency replay rows. New writes stop in checkpoint 15.2A-3; existing rows are handled by the owner-gated checkpoint 15.2A-4. Audience-preview reads are not audited until 15.2A-3.

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

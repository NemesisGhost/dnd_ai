# Phase 14 Verification

Evidence for Phase 14 (shared authoring kernel and campaign setup) on branch `phase14/authoring-kernel`, recorded against [PLAN.md Phase 14](PLAN.md) and [ADR 0014](adr/0014-world-authoring-authority.md). **Status: implemented and locally verified; final-head CI has not run, so Phase 14 is not yet marked complete** (the exit criteria require a green CI run).

## What was delivered

| Area | Delivered |
|---|---|
| Schema | Migrations `110_world_authoring_authority` (per-world `world_roles`/`world_memberships`), `111_authoring_row_versions` (row versions, supersession link, immutable timeline lineage), `112_actor_idempotent_requests`; seed `security.world_roles.yaml`. |
| Authority | Closed per-world capability mapping (`world.view`, `world.manage`, `timeline.manage`, `campaign.create`) plus global `world.create` for human principals; resolved from the database on every request and re-checked under lock. Foundry and machine principals never gain authoring rights. |
| Commands / API | Worlds (create, update, archive, restore, claim), timelines (create, update, branch, archive, restore), campaigns (create, update, archive, reactivate), and canon lifecycle (submit, return to draft, approve, reject, publish, supersede, archive, restore, delete draft), each with optimistic versions, durable idempotency, bounded audit, and non-disclosing targets. |
| Reads | World/timeline/campaign settings with server-computed `available_actions`/`blocked_actions`, branch-point and ruleset option lists, archived-campaign list, draft/published World Explorer separation. |
| Portal | `/worlds` management, timeline pages and branch creation, three-step `/campaigns/new`, `/app/:id/settings`, archive/reactivate, a Get-started card, and the entity Lifecycle panel with a draft/archived preview toggle. |
| Dev data | `scripts/setup_phase13c_dev_data.py` builds world, timelines and campaigns through the production commands; a unit guard blocks unmarked direct inserts of those records in `scripts/`. |

## Commands run and results (2026-10-04, local PostgreSQL 18)

| Check | Result |
|---|---|
| `uv run ruff format --check .` / `ruff check .` | clean |
| `uv run mypy src` | no issues (144 files) |
| Full Python suite, 6 parallel shards (`tests/unit`, `tests/database`, `tests/scenario`) | 5135 tests: all passed except two (below) |
| `tests/database/test_downgrade_deferred_trigger_ordering.py` run alone | 5 passed |
| Migration `upgrade head` → `downgrade 109_user_portal_preferences` → `upgrade head` → `alembic check` on a throwaway database | all rc=0, no drift |
| Seed idempotency | `tests/database/test_seed_idempotency.py` (in the database suite) passes, including `security.world_roles` |
| Portal `npm test` / `npm run lint` / `npm run build` | 247 files, 1705 tests passed / clean / build OK |
| `git diff --check origin/main...HEAD` | only trailing whitespace in `docs/PLANv2.md`, which belongs to the pre-existing commit `b6ff89c` |

Explained non-passes:

- `tests/unit/test_config.py::test_local_session_allowed_origins_defaults_to_dev_topology_outside_production` fails here because the developer `.env` adds an extra origin; it fails identically on the baseline and is environment-only.
- The downgrade-to-base test fails only when other shards run concurrently (cluster-global role changes); it passes alone.
- `alembic check` against the developer's own `dnd_ai` database reports it is behind head; that database was deliberately not migrated. The same check passes on the throwaway database.

## Not verified locally

- Final-head CI (the merge gate).
- Manual browser verification at 390 / 1280 / 2560 px: not performed. Layout is covered by CSS and component tests only.
- Full `downgrade base` round trip beyond what the downgrade test covers.

## Deviations from the plan

- `CreateEntityDraft` and source/provenance attachment are not provided as generic commands: ADR/plan 14.1 forbids a generic entity-write endpoint, and per-type creation belongs to Phase 15. The lifecycle commands operate on existing entities of registered types.
- `scripts/ai_provider_smoke_test.py` keeps direct inserts (throwaway ruleset, `pending` campaign, no user to own a world); each is marked and guarded.
- The World list preview toggle is component state, not a URL parameter, matching the existing World page filters.
- `make_entity` in the test factories now defaults to canon rather than draft.

## Accepted limitations and remaining work

- Phase 15 supplies authoring of world content (entity creation/editing per type); only the lifecycle kernel and its portal controls exist now.
- Invitation delivery and collaboration (Phase 16) are untouched; the scenario adds a player membership directly.
- No import, AI, Foundry UI, or deployment packaging was added.

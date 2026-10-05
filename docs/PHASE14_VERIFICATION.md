# Phase 14 Verification

Evidence for Phase 14 (shared authoring kernel and campaign setup) on branch `phase14/authoring-kernel`, recorded against [PLAN.md Phase 14](PLAN.md) and [ADR 0014](adr/0014-world-authoring-authority.md). **Status: complete.** Merged as PR #64 (`3046714`); final-head CI run `37227612984` was green. Manual browser verification of the navigation/hierarchy correction is still pending and is carried into the Phase 15 manual matrix (not a Phase 15 gate).

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

## Navigation and hierarchy correction (2026-10-04)

Manual acceptance found the sidebar and context hierarchy incoherent. Corrected on `phase14/authoring-kernel`; **no backend contract, schema, or authorization rule changed**.

- **Contracts used:** `GET /worlds?status=all` (authorized worlds), `GET /worlds/{id}` (its authorized `timelines`, `available_actions`), `GET /worlds/{id}/timelines/{timelineId}` (detail; bound to the route world, non-disclosing 404). No timeline-list endpoint was needed.
- **Sidebar:** one Worlds group — All worlds, New world, World overview, Timelines (`/worlds/:id/timelines`, the whole world), Timeline overview, Campaign world. Context-dependent entries are disabled in place, never removed.
- **Routes:** added `/worlds/:worldId/timelines`; all `/worlds/*` routes now render under `WorldWorkspaceLayout`. Existing deep links are unchanged.
- **Context panel:** `HierarchyContextPanel` (World, Timeline, Campaign, Character) rendered by `WorkspaceFrame` on World and Campaign pages; the pages inside no longer render their own `<main>`. Selection is route-derived via `WorkspaceHierarchyProvider`; nothing is persisted.
- **Cascade:** selectors navigate; lower levels unmount with their routes; stale data is excluded because every request is keyed by its path.
- **Character perspectives** stay Campaign-membership scoped; World-scoped characters are never selectable.

Automated evidence (local, 2026-10-04): portal `npm test` 249 files / 1756 tests passed, `npm run lint` clean, `npm run build` OK, `git diff --check` clean. New or changed suites: `HierarchyContextPanel.test.tsx`, `TimelinesPage.test.tsx`, `App.worldWorkspace.test.tsx`, `PortalSidebar.test.tsx`, plus layout/App/perspective tests adapted to the hierarchy panel. This is automated evidence only.

**Manual browser verification of this correction: not yet performed.** A source-level review of the CSS (existing grid: single column below 64rem, panel in the right column above it; sticky from 64rem; disabled-select styling) found no layout change, but it is not a substitute for checking 390 / 1280 / 2560 px.

Follow-up fixes (manual testing):

- `/worlds/new` crashed with `Cannot destructure property 'bootstrap'` when the `/worlds/*` routes were nested under a layout that did not forward the shell's outlet context. `WorldWorkspaceLayout` forwards it, `useAuthenticatedSession` now throws a deliberate message when the context is missing, and `App.worldNew.test.tsx` renders the whole app under a data router (as `main.tsx` does) to cover direct render, no duplicate bootstrap request, no request on open, CSRF and same-origin credentials on submit, the missing-capability state, session expiry, and login return.
- The post-login allowlist now accepts `/worlds` routes so an unauthenticated visit to `/worlds/new` returns there after sign-in (the destination still re-authorizes on arrival).
- On campaign routes World overview, Timelines, and Timeline overview are enabled only after `GET /worlds/{id}` succeeds (ADR 0014).

Accepted limitations of the correction:

- An unconfirmed route world shows "No selection" until `GET /worlds/{id}` returns (no optimistic selection).
- On a campaign page whose world the caller cannot read, the Timeline selector shows the campaign's own timeline but stays disabled.
- The panel, sidebar, and world page share one hierarchy read, but the world page still issues its own `GET /worlds/{id}` (no shared cache).
- The Campaign selector lists campaigns from the session bootstrap only; campaigns the caller does not belong to are never listed.

## Not verified locally

- Final-head CI (the merge gate).
- Manual browser verification at 390 / 1280 / 2560 px: not performed (including the navigation and hierarchy correction above). Layout is covered by CSS and component tests only.
- Full `downgrade base` round trip beyond what the downgrade test covers.

## Deviations from the plan

- `CreateEntityDraft` and source/provenance attachment are not provided as generic commands: ADR/plan 14.1 forbids a generic entity-write endpoint, and per-type creation belongs to Phase 15. The lifecycle commands operate on existing entities of registered types.
- `scripts/ai_provider_smoke_test.py` keeps direct inserts (throwaway ruleset, `pending` campaign, no user to own a world); each is marked and guarded.
- The World list preview toggle is component state, not a URL parameter, matching the existing World page filters.
- `make_entity` in the test factories now defaults to canon rather than draft.

## Accepted limitations and remaining work

- **Provenance and history (disclosed 2026-10-05):** safe source/provenance attachment, provenance presentation, and prior-version history/revision comparison are **not provided** by Phase 14 (only the `gm_entry` source and the audit trail exist). They are scheduled in Phase 15 checkpoints 15.2R (revision capture), 15.3C-1 (sources and provenance), and 15.3C-2 (review queues and comparison).
- **Clean-install access defaults (disclosed 2026-10-05):** a clean database has no relationship-type capability mappings (see the Phase 13 limitation in PROJECT_STATUS); character perspectives work only where development data supplies them, until checkpoint 15.2A-1.

- Phase 15 supplies authoring of world content (entity creation/editing per type); only the lifecycle kernel and its portal controls exist now.
- Invitation delivery and collaboration (Phase 16) are untouched; the scenario adds a player membership directly.
- No import, AI, Foundry UI, or deployment packaging was added.

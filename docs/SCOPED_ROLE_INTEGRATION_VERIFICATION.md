# Scoped-role integration: verification record (CP-4)

Branch `integration/scoped-roles`, built from `phase15/completion` @ `67bd15ae93a906ca11f40efbd105d175aab79120` (CP-3 sign-off) and `origin/feature/scoped-role-model` @ `07dcece1df199778b9971aec4ce9b2af3cf1d31b`. The tested code is the head named in the handoff; the later commits on the branch change documentation only. **Not merged into `phase15/completion`, not deployed to any database, no CI run.** Phase 15 remains implemented with acceptance pending.

## What was run, and the result

| Check | Result |
|---|---|
| `ruff format --check`, `ruff check` (`src tests scripts`), `mypy src` | clean |
| Portal `tsc -b`, `eslint .`, `vite build` | clean / succeeds (the chunk-size warning is pre-existing) |
| Portal `vitest` full run | 3312 tests, 0 failed (the merge commit alone: 3281) |
| Python `tests/` in four parallel shards (`CI_TEST_SHARD`), local PostgreSQL 18.4 | all pass: 1290 + 1236 + 1889 + 2244. Shard 2 (which holds the member-preview tests) was re-run after the last source change; shards 1, 3 and 4 ran on the preceding code |
| Merge commit `16a8aff` alone, before reconciliation | 17 failed, 6618 passed: see below |
| Isolated API on `127.0.0.1:8001` against a throwaway database | `healthz`/`readyz` 200, activation, login, session bootstrap `system_roles ["admin","gm"]`, `world.create` creation: pass |

The 17 failures at the bare merge, each attributed rather than waived: 14 `test_frozen_seed_file_is_unchanged` (a worktree materialised with `core.autocrlf=true` has CRLF seed files while the owner's checkout has LF; normalising the 14 files in the worktree, which changes no repository content and no test, makes them pass); `test_concurrent_disable_cannot_leave_zero_active_administrators` (fails identically, 3 of 3, on the unmodified `phase15/completion` checkout: a timing assumption of the test, not this work; it passed in the final runs); a stale organization-reader fixture and a pinned route count (both fixed in the reconciliation).

## Browser and accessibility

No browser automation was available in this session. Nothing was checked in a real browser, with a screen reader, or at responsive widths. The portal behaviour is covered by component and route tests (DOM roles, `aria-disabled`, focus, request counts) only. SR-M1..SR-M14 and the AT/responsive acceptance are not run.

## Migration rehearsals (disposable `dnd_ai_m1415_cp4_*` databases; never `dnd_ai`)

- **Clean:** empty → `138_world_roles_and_use_grants`, single head, `alembic check` clean, `bootstrap_admin` gives `admin`+`gm`, `is_platform_administrator` gone, five world roles.
- **Populated 136 → 137 → 138** (9 accounts: two legacy administrators incl. a dormant one, a campaign-only GM, players, observer, former owner; two worlds, three campaigns, invitations, a character relationship, allow and deny resource grants): `verify_scoped_role_upgrade.py` reports no failures; roles are exactly as the policy says (Dev Admin and Dormant Admin `admin`+`gm`, Co Owner `gm`, all others `player`, the campaign-only GM keeps `campaign_owner`+`gm`+`assistant_gm` campaign roles and gets no system `gm`); `alembic check` clean.
- **Lossy downgrade and re-upgrade:** with Editor, Reviewer and Reader rows, a use grant, a non-admin system role and a Viewer beside an Owner added, `downgrade` to 136 **failed** (revision 138 rebuilt a unique index with deferred trigger events pending). Fixed (`SET CONSTRAINTS ALL IMMEDIATE` before the rebuild) and covered by a repository test that fails without the fix. Rerun: the new world roles, the use-grant table and the system-role table are gone, entities and campaign memberships unchanged, the Viewer beside the Owner closed and kept as history, the admin flag restored; re-upgrade and verifier clean.
- **Grants, default privileges, documentation:** `test_role_grants.py`, `test_schema_documentation.py`, `test_data_classification_schema.py` (602 tests) pass against both the upgraded copy and the clean database.
- This is a **representative populated fixture, not the owner's snapshot**. CP-0's dump and restore of `dnd_ai` was not authorised or run; verifying the exact snapshot is pending (runbook in `LOCAL_DEPLOYMENT.md`).
- Interrupted test runs left `dnd_ai_test_*` databases on the local server (they are named by the test harness and were not dropped, per the plan's rule on unknown databases).

## Integrated authority and exceptions, as tested

Campaign-only GM: runs the campaign (sessions, clock, events, encounters, travel, items, knowledge runtime, quest progress, organization status, NPC running, relationship status and reactions), reads published canon with GM-only fields, creates and finishes player-character identity, item instances and world-time points; is refused (403 `world_authority_required`) every shared-definition write and every read of the private side, and is not sent those requests by the portal. World Editor, Reviewer, both, Reader, Viewer and Player are pinned per role union by `tests/database/test_scoped_roles_current_surfaces.py`; agreement of the per-record flags with the commands is tested with otherwise valid requests. The set of private-read routes and the explicit `world_capability` of every authoring scope are pinned by `tests/unit/test_world_gate_registry.py`. A world role ended while a relationship-definition write waits on the world lock is honoured (real-concurrency test).

## Not delivered, with reasons

- **"Area now" for a campaign-only GM.** The dungeon area's runtime panel reads the area through its authoring view (the world's private side), so it is listed as unavailable for a campaign GM without a world role; the dungeon-state routes themselves are campaign-authorized. Fix: serve the area's state and choices from a campaign-scoped read.
- **Permission-loss retention is implemented in the edit shell only.** Typed input inside the staged workspaces' sub-sections is dropped when the whole record becomes unavailable (existing fail-closed behaviour); it is not specially retained.
- **Session travel, party directory:** reviewed (they use the shared visibility resolution and need no world role); no scoped-role-specific test was added beyond the existing suites.
- **The three owner-modified verification documents** were not touched on this branch; their integration sections are this file. After the owner commits their edits, `PHASE15_VERIFICATION.md` should link here and the manual-acceptance matrix needs the role matrices and SR scenarios (CP-11).
- **Defaults awaiting confirmation (DR-7):** Q2, Q5, Q8, Q11, Q12, Q13, lifecycle of the campaign-originated records, Viewer/Reader coexistence, the Q4 interpretation. Implemented as defaults; reconciling them on this branch is not approval to deploy them.

# Scoped-role integration: verification record (CP-4)

Branch `integration/scoped-roles`. The feature (`origin/feature/scoped-role-model` @ `07dcece1df199778b9971aec4ce9b2af3cf1d31b`) is merged **on this branch** (merge commit `16a8aff287a02db457bc30ba72d85b67663d1fe2`, parents `67bd15a…` and `07dcece…`); `phase15/completion` is unchanged at `67bd15ae93a906ca11f40efbd105d175aab79120` and does not contain the feature (`git merge-base --is-ancestor 07dcece 67bd15a` is false). Nothing here is merged into `phase15/completion`, deployed to any database, or CI-verified. Phase 15 remains implemented with acceptance pending.

## What was run on the final source tree

The final source tree is `34b8bc45a0f265d7e42eff477b7edd2714fbb7b2`. Python and database code are identical between `cdd14e8` and that commit (the later commit changes three portal files only), so the Python results below, taken at `cdd14e8dfcc6e24bac964c34fd63b67d5a6aa796`, apply to the final tree; the portal results were taken on the final tree's contents. Later commits change documentation only.

| Check | Result |
|---|---|
| `ruff format --check`, `ruff check` (`src tests scripts`), `mypy src` | clean |
| Portal `tsc -b`, `eslint .` | clean |
| Python `tests/` in four shards (`CI_TEST_SHARD=1..4/4`, run in parallel with the portal suite), local PostgreSQL 18.4, `-rfEsx` | 2300 + 1368 + 1191 + 1808 = **6667 passed, 0 failed, 0 skipped, 0 xfail, none excluded, none retried** |
| Portal `vitest` full run on the final tree's contents | **3320 of 3320 passed, in two consecutive runs** |

Portal runs that did not pass, all disclosed: (1) in the run concurrent with the four Python shards, 1 of 3319 failed (`a dungeon has Areas and Connections…`, a synchronous assertion after a click, 166 ms); it passed 2/2 alone and with its file 96/96, and the assertion now awaits the navigation (assertion unchanged); (2) a later quiet-machine run failed 1 of 3319 on a different timing-bound test in the same file (`a dungeon adds an area…`, an 8 s lookup timeout); that run predated a real fix (the dungeon authoring read was still being requested for a caller who may not have it) and the two runs after it passed in full. On the unmodified `phase15/completion` checkout, two full runs gave 3253/3253 and 3251/3253 (`OrganizationMembersReader does not show the previous organization's roster…`, `the month roster expands only the selected row…`): the intermittent portal timing failures predate this work and move between tests.

No test was excluded, selected away, conditionally skipped or retried to obtain these results.

### The concurrent-disable test (`test_local_auth_commands.py::test_concurrent_disable_cannot_leave_zero_active_administrators`)

It is timing-dependent and **fails every time when run alone or as its module on a quiet machine, on both trees**: 3 of 3 isolated runs plus the module run fail on the unmodified `phase15/completion` checkout (`67bd15a`) and 3 of 3 plus the module run on the integration tree, with the same `NotPlatformAdministratorError` (the administrator whose disable ran second has already been disabled when its own authorization is checked, so the rejection arrives as the wrong error). It *passed* in all four shards of the final full run and in the preceding full runs, where load interleaves the two threads. So "all four shards pass" and "it fails identically on the original checkout" are both true and refer to different conditions: under the parallel shard load it passes; alone it fails on the original checkout exactly as it does here. Its source and the code it exercises (`is_platform_administrator` requires an active account) are the same on the original tree; it was not changed, weakened or excluded. Practical impact: a test-design race only; the production behaviour (a disabled administrator cannot act) is correct. At the bare merge commit it failed in one of four shards (run under the same load), which is how it was first seen.

### Frozen-seed line endings

The 14 `database/seeds/rules.*.yaml` files listed in `database/seeds/frozen_manifest.json` were affected, in the two worktrees created for this work (`../dnd_ai-roles-integration` and the detached `../dnd_ai-roles-verify`). With `core.autocrlf=true` (the machine's Git for Windows default) `git worktree add` materialised them with CRLF, so their SHA-256 differed from the frozen manifest (`git ls-files --eol`: `i/lf w/crlf`; 14 tests failed at the bare merge). The owner's main checkout has them as `i/lf w/lf` and passes. I rewrote those 14 files to LF in both worktrees. **Tracked content did not change** (the index blobs are LF; `git add database/seeds` staged nothing; `git diff` is empty). The correction is **not reproducible from the repository's checkout conventions**: `.gitattributes` has no `eol` rule for the seeds, so any fresh worktree on this machine will show the same 14 failures until the files are normalised or an `eol=lf` attribute is added for the frozen seeds (a separate maintenance change, not made here). Other seed files in the worktree are still CRLF and unaffected (not in the manifest).

## Browser and accessibility

No browser automation was available. Nothing was checked in a real browser, with a screen reader, or at responsive widths. SR-M1..SR-M14 are not run. Portal behaviour is covered by component and route tests (DOM roles, `aria-disabled`, focus, request counts).

## Migration rehearsals (disposable `dnd_ai_m1415_cp4_*` databases; never `dnd_ai`)

Unchanged by this follow-up (no migration changed). Clean to 138 with `alembic check` clean; a populated 136→137→138 fixture verified by `scripts/operations/verify_scoped_role_upgrade.py`; lossy downgrade and re-upgrade (the revision 138 downgrade defect was found and fixed here); grants, default privileges, documentation and data-classification tests (602) green on the upgraded copy and the clean database. These are **representative fixtures, not verification of the owner's snapshot**: CP-0's dump and restore of `dnd_ai` was not authorised or run, and that verification is pending. Interrupted test runs earlier left `dnd_ai_test_*` databases on the local server; they were not dropped.

## Integrated authority and exceptions, as tested

See `tests/database/test_scoped_roles_current_surfaces.py`, `tests/unit/test_world_gate_registry.py`, `tests/database/test_scoped_roles_concurrency.py` and, for "Area now", `tests/database/test_area_runtime_projection.py` and `portal/src/components/world/WorldRecordWorkspace.areaNow.test.tsx`.

### "Area now" (fixed in this follow-up)

Root cause: the panel loaded the area through `GET …/authoring/dungeon-areas/{id}` and `…/authoring/dungeons/options`, which require `world.canon.read_private`, so a campaign-only GM got 403 on both and the panel reported that it could not load; the workspace also fired the area's (and a dungeon's) authoring read for such a caller, and the panel treated the lifecycle read a campaign-only GM never has as "status could not be loaded". Fix: `GET /campaigns/{id}/dungeon-areas/{area_id}/runtime`, campaign `canon.edit`, returning only the dungeon's name, the area's recorded state, parts and connections with recorded statuses and last-event tokens, status choices, two limits and `can_set_state`; authorized like the audience-safe area read (a per-area `campaign.view` deny, an unpublished area or dungeon, or a foreign campaign are the same 404; a connection to an area the caller cannot see is not listed); no descriptions, hidden flags, severities, dimensions, revisions or actions. It grants no edit or review right and does not touch `POST …/state`, whose authorization is independent. The area's and the dungeon's authoring reads are now requested only for a caller holding the world's private side.

## Not delivered, with reasons

- **Permission-loss retention is implemented in the edit shell only.** Typed input inside the staged workspaces' sub-sections is dropped when the whole record becomes unavailable (existing fail-closed behaviour). Low.
- **Session travel and party directory:** reviewed (shared visibility resolution, no world role needed); no scoped-role-specific test beyond the existing suites.
- **Seed line endings** are not fixed in the repository (see above). Low, development-only on Windows.
- **The three owner-modified verification documents** are untouched on this branch.
- **Defaults awaiting confirmation (DR-7):** Q2, Q5, Q8, Q11, Q12, Q13, lifecycle of the campaign-originated records, Viewer/Reader coexistence, the Q4 interpretation. Implemented as defaults; reconciling them here is not approval to deploy them.
- **Pending evidence:** CI on the final head, real-browser/AT/responsive checks, SR-M1..SR-M14, the exact CP-0 snapshot restore and verification.

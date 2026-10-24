# Scoped-role integration: verification record (CP-4)

Branch `integration/scoped-roles`. The feature (`origin/feature/scoped-role-model` @ `07dcece1df199778b9971aec4ce9b2af3cf1d31b`) is merged **on this branch** (merge commit `16a8aff287a02db457bc30ba72d85b67663d1fe2`, parents `67bd15a…` and `07dcece…`); `phase15/completion` is unchanged at `67bd15ae93a906ca11f40efbd105d175aab79120` and does not contain the feature (`git merge-base --is-ancestor 07dcece 67bd15a` is false). Nothing here is merged into `phase15/completion` or deployed to the owner's database; CI evidence, when any exists, is recorded under the draft PR for this branch, not here. Phase 15 remains implemented with acceptance pending.

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

Unchanged by this follow-up (no migration changed). Clean to 138 with `alembic check` clean; a populated 136→137→138 fixture verified by `scripts/operations/verify_scoped_role_upgrade.py`; lossy downgrade and re-upgrade (the revision 138 downgrade defect was found and fixed here); grants, default privileges, documentation and data-classification tests (602) green on the upgraded copy and the clean database. These are **representative fixtures, not verification of the owner's snapshot**: the exact snapshot of `dnd_ai` was dumped, restored and upgraded afterwards (next section). Interrupted test runs earlier left `dnd_ai_test_*` databases on the local server; they were not dropped.

## Integrated authority and exceptions, as tested

See `tests/database/test_scoped_roles_current_surfaces.py`, `tests/unit/test_world_gate_registry.py`, `tests/database/test_scoped_roles_concurrency.py` and, for "Area now", `tests/database/test_area_runtime_projection.py` and `portal/src/components/world/WorldRecordWorkspace.areaNow.test.tsx`.

### "Area now" (fixed in this follow-up)

Root cause: the panel loaded the area through `GET …/authoring/dungeon-areas/{id}` and `…/authoring/dungeons/options`, which require `world.canon.read_private`, so a campaign-only GM got 403 on both and the panel reported that it could not load; the workspace also fired the area's (and a dungeon's) authoring read for such a caller, and the panel treated the lifecycle read a campaign-only GM never has as "status could not be loaded". Fix: `GET /campaigns/{id}/dungeon-areas/{area_id}/runtime`, campaign `canon.edit`, returning only the dungeon's name, the area's recorded state, parts and connections with recorded statuses and last-event tokens, status choices, two limits and `can_set_state`; authorized like the audience-safe area read (a per-area `campaign.view` deny, an unpublished area or dungeon, or a foreign campaign are the same 404; a connection to an area the caller cannot see is not listed); no descriptions, hidden flags, severities, dimensions, revisions or actions. It grants no edit or review right and does not touch `POST …/state`, whose authorization is independent. The area's and the dungeon's authoring reads are now requested only for a caller holding the world's private side.

### Permission loss in the staged dungeon and area workspace (fixed in this follow-up)

Finding: a private-authoring command refused because the caller's world authority was revoked showed a local error, and the workspace kept showing the private server-loaded views (areas, connections, area contents, edit links, lifecycle) because reads only refresh after successful writes.

Behavior now (`components/authoring/permissionLoss.ts`, `useDungeonCommand`, `WorldRecordWorkspace`, `PermissionLost`):
- **Detection is the server's, and narrow:** only a 403 with code `world_authority_required` from a dungeon/area command is a confirmed loss, the same rule as the edit shell. A bare 403 (`forbidden`, CSRF/session) is not: it keeps the form, its values, the views and the "Check my session" path. The client infers and grants nothing.
- **On a confirmed loss** the workspace sets one `lost` state: the record's `authoring` is replaced by the none value (every edit entry point fails closed), the world-private capability is treated as not held (the lifecycle, provenance, revision, dungeon and area authoring reads are no longer requested or shown), the private sections become unavailable text, and the session bootstrap is refreshed. The audience-safe Details view stays.
- **Retention follows the ContentEditPage contract:** a "Permission lost" alert shows only what the person typed and had not sent, read-only, as changed fields (`retainedChanges`), never the saved row or anything the server loaded. Registered: new area, new connection (the chosen From/To areas are shown only as "Selected": their names come from the private read and are never copied), connection and child editor rows, new contents (feature/hazard/interactable). camelCase field names are labelled as words.
- **"Check my access again"** clears the loss, refreshes the bootstrap and re-reads the record; the server's answer decides what returns. The section the person was in is offered again, not forced open.
- Tests (`WorldRecordWorkspace.test.tsx`): refused add-area withdraws the Areas list, summaries, add form/button, edit links and Prepare/Review sections, keeps only the typed name and kind, and sends no further authoring read; refused add-connection keeps the typed fields and shows no area name from the loaded view (asserted for all three area names); refused connection edit keeps only the changed field; a bare 403 does not trigger loss; re-check restores access; refused add-hazard in the area workspace withdraws the contents and keeps only the typed values. Writing these found one leftover (the "Edit dungeon" link built from the loaded detail), fixed by overriding `authoring` on the shown record.
- Checks: `WorldRecordWorkspace.test.tsx` 102/102 (three consecutive runs); full portal suite 3326/3326 on the final run (an earlier full run had two 8-second timeouts, in the new bare-403 test and an existing "pauses a state save" test, both passing in the file alone and in the next full run: load-dependent timing, the class already disclosed above); `tsc -b`, `eslint .` clean; `vite build` succeeds (chunk-size warning only). No Python, database tests or migrations were run for this change.
- Limits: the "Area now" state forms are campaign-authorized and are not part of this path; loss is detected only on a refused dungeon/area command (not on a refused read); no real-browser check.

## Not delivered, with reasons

- **Permission-loss retention in the staged workspace covers the registered forms only** (see the section above); a form added later must register its unsent input with `useRetainedInput`, and an unregistered one is dropped on loss. Loss is workspace-local (another open tab learns on its own next refused write or read). Low.
- **Session travel and party directory:** reviewed (shared visibility resolution, no world role needed); no scoped-role-specific test beyond the existing suites.
- **Seed line endings** are not fixed in the repository (see above). Low, development-only on Windows.
- **The three owner-modified verification documents** are untouched on this branch.
- **Defaults approved (DR-7):** Q2, Q5, Q8, Q11, Q12, Q13, lifecycle of the campaign-originated records, Viewer/Reader coexistence, the Q4 interpretation. The owner approved the implemented defaults as a set on 2026-10-24 ("For now I accept the defaults."). Nothing was added to them. This is not approval to land or deploy.
- **Pending evidence:** CI on the draft PR (see below), real-browser/AT/responsive checks and SR-M1..SR-M14. The exact-snapshot restore and upgrade rehearsal is now done (next section).

## Exact-snapshot restore and upgrade rehearsal (2026-10-24)

Performed against reviewed code `fef5431a72930f77c40bee9c26c467d50292c3e8` (the code reviewed at CP-4 sign-off; later commits on this branch are documentation only). Source: the owner's `dnd_ai` at revision 136, dumped with `pg_dump -Fc` (SHA-256 `034b7976f908809b4229cf32b8602b70f73ab39762a5217edabeeccd464f8783`) with no writers running; the dump and its evidence are kept outside every repository.

- A restored baseline copy was identical to the source across all 215 tables (row counts and content hashes) at revision 136, and stayed unchanged.
- A separate restored copy upgraded `136_world_viewer_role` -> `137_system_roles` -> `138_world_roles_and_use_grants` with no error.
- Domain data and the required identities were preserved: every recorded user, membership, invitation, character link and grant id is present with identical key columns, and the domain schemas are row-for-row identical. Administrator holds `admin`+`gm`; the other 11 accounts hold `player`; the campaign-only GM was not promoted.
- `scripts/operations/verify_scoped_role_upgrade.py verify` passed (`failures: []`); `alembic check` found no drift; grants, owners, defaults and comments equal a clean install of the same code; `tests/database/test_role_grants.py` 596 passed.
- **Limits:** the real data held no `world_viewer` assignments and no deny grants (six `allow`), so Viewer treatment and deny preservation on the upgrade are covered by repository tests, not by this data. The dump is a point-in-time copy: the real `dnd_ai` has not been migrated and a fresh dump is required immediately before upgrading it.

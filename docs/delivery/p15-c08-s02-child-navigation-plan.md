# D/P15-C08-S02 implementation plan: navigate children in the portal

Owner register rows: [P15-C08](work-register.md#p15-c08), [P15-C08-S02](work-register.md#p15-c08-s02), [P15-C08-S02-T01](work-register.md#p15-c08-s02-t01). Source finding: [R16 — Location hierarchy](work-register.md#r16--location-hierarchy). API contract: [S01 plan §3.2](p15-c08-s01-location-children-plan.md#32-in-scope-t01). Checkpoint coordination: [S01 plan §12](p15-c08-s01-location-children-plan.md#12-c08-checkpoint-coordination).

Prepared by Opus, 2026-11-24, against planning baseline `680629b0e9d8193112c1e6378e74fcd41323cac6` (see the S01 plan header). **T01 independent review: PASS WITH VERIFICATION LIMITS (§11.6).** The original CHANGES REQUIRED finding and score remain in §11.4; §11.6 confirms the correction at `041fe4d10b646a29bc8a54b6a545dc4274d42e98`.

## 1. Entry readiness

- **Register prerequisite:** [P15-C08-S01](work-register.md#p15-c08-s01) independently reviewed. This is a real prerequisite, not a scheduling preference, because S02 consumes S01's new read.
- **Coordination prerequisite:** S03-T01's records commit exists (S01 plan §12.3). It sets the starting state of the shared `WorldRecordWorkspace.test.tsx`. Without it, S03 and S02 would make conflicting assumptions about that file.
- **Revalidation before writing tests** (§11.1 step 2). At the then-current head, the implementer confirms the following:
  - S01's reviewed response shape, parameters and status codes match §3.2 of the S01 plan, including any confirmed correction.
  - The §2 facts below still hold.
  - S03's changes to `WorldRecordWorkspace.test.tsx` are present.

  Any difference is a stop condition, not something to adapt silently.
- No owner decision blocks S02.

## 2. Verified current behavior (at `680629b0`)

### 2.1 How a place's page works today

- `CampaignWorldDetailPage` dispatches `/app/:campaignId/world/location/:entityId`:
  - An editor (`canon.edit`) gets `WorldRecordWorkspace`, keyed by category and ID. Its Details section renders `LocationPanels`, with `omitCurrentState` for an area.
  - Everyone else gets `WorldEntityDetailBoundary` → `WorldLocationDetailPage` → `LocationPanels`.
  - Switching `canon.edit` swaps the two hosts, which unmounts one and mounts the other.
- `LocationPanels` shows Overview, a **Containment** panel and Current State.
  - Containment renders `breadcrumbs` as an ordered list labelled "Location path".
  - Each entry is plain text, "Name (Type)", with **no link**.
  - `parent_location_id` is never rendered.
  - The server already truncates the path at a hidden ancestor.
- Return links:
  - `WorldRecordBack` shows the shared task breadcrumb when the page was opened inside a task, and otherwise "Back to World". It never consults containment.
  - Reader pages link related records with `useWorldReturnState()` state.
  - The workspace links with its `linkState`.
- The workspace's `useStagedNavigation.sectionHref` copies every current search parameter and sets `section`. A new search parameter therefore survives section links and edit-page returns.
- `useWorldDetail` maps statuses this way:
  - 401: clear and reload the session;
  - 403 and 404: "unavailable";
  - anything else: error with "Try again".
- Load-more precedent: `WorldCanonPage` ("Load more" with a cursor and an abort controller).
- Tests:
  - `authoringHarness.installMockServer` fails an unmatched request loudly.
  - `WorldRecordWorkspace.test.tsx`'s `setup` registers a catch-all `GET /.*/ → 404`.
  - `App.worldNavigation.test.tsx` and `App.locationAuthoring.test.tsx` register their own location routes. `App.worldNavigation.test.tsx:609` asserts a request sequence that starts at the location read.

### 2.2 Plan-entry reproduction results

A temporary Vitest file rendered `LocationPanels` for "The Archive" with path "Ashen Vale (Region) › Hollowmere (Settlement)". It ran once and was deleted.

| Case | Kind | Observation |
|---|---|---|
| P1 | defect | The "Location path" list has 2 items and **0 links**. |
| P2 | defect | The panel headings are only Overview, Containment and Current State. There is no list of places within the place. |
| P3 | defect | The panel contains no search box (0 search boxes, 0 text boxes). |

### 2.3 Deviations S02 repairs

- **DV-1:** no way to see or open the places inside a place.
- **DV-2:** no search limited to a place's subtree.
- **DV-3:** the containment path cannot be followed back up.

### 2.4 Source-inspected risks (to be proven by cases below)

- **Late answers.**
  - An answer for a previous place, query or page could render under the current one (N9 and N10).
  - A loaded page could outlive a lost authority (N11–N13).
- **Editor drafts.** Drafts listed for an editor could stay visible after the page becomes the reader's (N13).
- **Request volume.** Request-count assumptions in the existing tests (§6.2).

### 2.5 Behavior that must not regress (baseline-passing guards)

- The containment path shows only the server's crumbs in order. A hidden ancestor never appears (N16).
- `WorldRecordBack` and the task breadcrumb are unchanged, and containment never feeds them. Existing `WorldRecordWorkspace.breadcrumb.test.tsx`, `App.worldNavigation.test.tsx` and `editNavigation.test.tsx` cases cover this.
- A non-editor sends no authoring request. This is the existing workspace test "sends no dungeon authoring request to someone who cannot edit canon". The new read is under `/world/`, not `/authoring/`.
- Section links, edit returns and the guard on unsaved input in other sections (existing workspace tests).

## 3. Outcome, scope and exclusions

### 3.1 User outcome

On any place except a dungeon area, a person sees **Places within <name>**. It lists the places directly inside, 25 at a time, with **Show more places**. A search finds places further down, each shown with where it sits. Each result opens that place. On the place opened, the Location path links back up to each visible ancestor. Back returns to the previous place with its search still applied. Nothing hidden is named or counted.

### 3.2 In scope (T01)

**API client.** Add `fetchLocationChildren(campaignId, locationId, { q, cursor, includeHidden }, signal)` in `api/world.ts`.
- It calls `GET /api/campaigns/{c}/world/locations/{id}/children` with `limit=25`.
- `q` is sent only when non-empty, and `cursor` only when present.
- `includeHidden` sends `include_noncanon=true&include_archived=true`, exactly as World search does.
- A non-OK response throws `WorldRequestError(status)`.
- Types `LocationChild` and `LocationChildrenPage` go in `types/world.ts`.

**Panel.** A new `components/world/LocationChildren.tsx` (with its hook in the same file or `hooks/useLocationChildren.ts`).
- **Layout.** A `DetailPanel` titled "Places within" contains:
  - a `<form role="search" aria-label="Search places within <name>">` holding an `<input type="search">` labelled "Search places within <name>", a **Search** submit button and, while a search is applied, **Clear search**;
  - a list `<ul aria-label="Places within <name>">`. Each item is a `Link` to `worldRecordPath(campaignId, "location", id)` with the host's link state, followed by the humanized type.
  - For a search result with a non-empty `path`, the item adds "in A › B" as plain text. Path entries are not links; the opened place's own Location path provides those.
  - For an editor host, the item shows a `LifecycleBadge`.
  - **Show more places** appears while `next_cursor` is present.
- **Query in the address.** The applied query lives in the parameter `within`.
  - Submitting navigates with `replace: true`, keeping every other parameter (including `section`) and `location.state`.
  - Clear search removes `within` the same way.
  - Typing alone sends nothing.
  - The address is the source of truth: on arrival, Back or a direct link, the panel reads the first page for `within`.
- **Paging.** Show more requests the next page with the exact `next_cursor` and appends it. Loaded pages are not persisted, so Back shows the first page of the applied query.
- **Read ownership.** Each read belongs to the tuple (campaign, place, `within`, `includeHidden`, page index).
  - A change of tuple, or unmount, aborts in-flight reads.
  - A generation check ignores any answer whose tuple is no longer current.
  - A tuple change clears loaded rows immediately, before the new answer arrives.
- **Outcomes.**
  - 200: render the page.
  - 401: clear the rows and call the session `reload`, as `useWorldDetail` does.
  - 403 or 404, on the first page or on Show more: clear **all** loaded rows and show "Places within this place are not available."
  - Any other failure or a network failure: keep rows already loaded and show an alert with **Try again**, which repeats exactly the failed read (same tuple and cursor). This is a read, so there is no write identity.
- **Status line.** A `role="status"` paragraph:
  - "No places within <name>." (no query, empty);
  - "No places within <name> match “q”." (with query, empty);
  - otherwise "Showing N places." or "Showing N places. More are available." N is the number loaded, never a total.
- **Focus.**
  - Submitting or clearing keeps focus on the search field.
  - After Show more, focus moves to the first newly added link. If the page added nothing, focus goes to the status line, which has `tabIndex={-1}`.
  - Arrival focus stays with the page's existing `usePageArrival` heading.

**Hosts.**
- `WorldLocationDetailPage` renders the panel after `LocationPanels` with `includeHidden=false` and link state `useWorldReturnState()`.
- `WorldRecordWorkspace` `DetailsSection` (category location) renders it after `LocationPanels` with `includeHidden=true` and the workspace's `linkState`.
- Neither renders it for `location_type_code === "dungeon_area"`.

**Containment path.** `LocationPanels` takes `campaignId` and an optional `linkState` (both callers pass them).
- Each crumb becomes a `Link` to the ancestor's record path with that state. The text stays "Name (Type)".
- The list keeps the label "Location path".
- Containment stays separate from the task breadcrumb, which is not changed.

**Documentation.** Update `docs/reference/portal-behavior.md`:
- the World record row (around the `world/:category/:entityId[?section=…]` row): Places within, `within`, Show more, the path links;
- the "breadcrumbs for location containment" bullet.

### 3.3 Exclusions

- No backend change. S01's contract is consumed as reviewed.
- No change to `WorldRecordBack`, `TaskBreadcrumb`, `breadcrumbModel`, `useWorldDetail`, `usePageArrival`, `useStagedNavigation` or World search.
- No departure protection for an unsubmitted query: it is not a draft of a write.
- No persisted Show more pages, no totals, no tree widget, no prefetch of grandchildren, no reparenting.
- The workspace's Areas section is unchanged. A dungeon's panel lists its areas as places, while Areas keeps authoring.

## 4. Affected files and interfaces

| File | Change |
|---|---|
| `portal/src/api/world.ts`, `portal/src/types/world.ts` | Client and types |
| `portal/src/components/world/LocationChildren.tsx` (+ optional `hooks/useLocationChildren.ts`) | New panel |
| `portal/src/pages/WorldLocationDetailPage.tsx` | `LocationPanels` path links; the reader renders the panel |
| `portal/src/components/world/WorldRecordWorkspace.tsx` | `DetailsSection` passes `campaignId` and `linkState` and renders the panel |
| `portal/src/components/world/LocationChildren.test.tsx` | New: N1–N15, N17, N18 |
| `portal/src/App.locationChildren.test.tsx` | New: N16, N19 and the route-level Back case of N7 |
| Existing tests | Only the §6.2 adaptations |
| `docs/reference/portal-behavior.md` | The rows of §3.2 |

## 5. Task commit

One commit: `P15-C08-S02-T01: browse and search places within a place and follow the containment path back`. A records commit follows (docs only).

## 6. Acceptance cases

Cases use the mock server (`installMockServer`), with routes keyed by full path including the query string. Rows are read from rendered link `href`s.

| Case | Behavior | Baseline |
|---|---|---|
| N1 | The reader shows "Places within <name>" with links in the server's order. The first request is exactly `…/children?limit=25`. | fails |
| N2 | An editor workspace's Details sends `include_noncanon=true&include_archived=true` and shows status badges. The reader never sends either flag. | fails |
| N3 | Paging: Show more sends the exact `next_cursor`, appends without duplicates, and disappears when `next_cursor` is null. Three pages make three requests and no others to `/world/search` or `/counts`. | fails |
| N4 | Keyboard: tabbing reaches the search field, the Search button, each result link and Show more, in that order. After Show more, focus is on the first new link. | fails |
| N5 | Search submit sets `within` with replace (history length unchanged), keeps `section` and the task state, and sends `q`. Typing alone sends nothing. | fails |
| N6 | A deep result shows "in A › B" from `path`, and its link opens that place. | fails |
| N7 | Back from an opened child returns to the parent with `within` applied and the first page re-read. This is a route-level case in the App file. | fails |
| N8 | The status line wording for empty, empty with query, more available and none left. It never states a total. | fails |
| N9 | Late answer for a superseded query: q=a is slow and q=b answers first; a's answer is never shown. | fails |
| N10 | Late answer across places: opening a child while the parent's read is pending never shows the parent's rows on the child. | fails |
| N11 | Show more answered 404: all rows are cleared and the "not available" message shows, with no old names left in the document. | fails |
| N12 | First page answered 403: nothing is listed and the message shows. A 401 calls the session `reload` and shows no rows. | fails |
| N13 | Editor to reader: when `canon.edit` is lost, the reader mounts and requests without flags, and no draft name from the editor's list remains. | fails |
| N14 | A 500 on Show more keeps the loaded rows and shows an alert. Try again sends the identical request (same `q` and cursor) once. | fails |
| N15 | A dungeon area shows no Places within panel and sends no children request. | guard (passes at baseline: there is no panel); must stay passing |
| N16 | The Location path entries are links to each crumb's record path, carrying the page's task state. A hidden ancestor (absent from the crumbs) never appears. The task breadcrumb and "Back to World" are unchanged. | fails (links); the truncation part is a guard |
| N17 | Changing `within` clears the rows at once, so no old row is shown while the new read is pending. | fails |
| N18 | Clear search removes `within` and lists the direct children again. | fails |
| N19 | An App-level walk from World search to a region, then a child, then a grandchild, then the Location path back up to the region. Each step sends only the reads for that page. | fails |

"Fails" means the case fails at baseline: record the test name and assertion. Guards are not expected to fail first.

### 6.1 Mutation probes

| Probe | Mutation | Must fail |
|---|---|---|
| M1 | Drop the generation check, so any answer renders | N9, N10 |
| M2 | Keep rows on 403/404 | N11, N12 |
| M3 | Do not clear rows on a tuple change | N13, N17 |
| M4 | Re-request from the first page on Show more (ignore `next_cursor`) | N3 |
| M5 | Navigate with push instead of replace | N5 |
| M6 | Send the preview flags for the reader too | N2 |
| M7 | Leave focus on the button after Show more | N4 |
| M8 | Render crumbs as text again | N16, N19 |

Revert each probe with exact bytes restored and hashes compared.

### 6.2 Permitted changes to existing tests

Only these:
- Register a handler for `…/world/locations/<id>/children…` returning `{ "items": [], "next_cursor": null }` in the setup of the affected files: `WorldRecordWorkspace*.test.tsx` setups, `App.worldNavigation.test.tsx` and `App.locationAuthoring.test.tsx`. Any other file found to request it unhandled may also get this handler, recorded by name.
- In request-sequence assertions (for example `App.worldNavigation.test.tsx:609`), exclude the children read, or expect it at its documented position. Assertions about every other request stay as they are.
- Where a test renders `LocationPanels` directly, pass the new `campaignId` prop.

Any other changed expectation is a stop condition.

## 7. Verification

### 7.1 Per-commit checks (Sonnet; repeated by the reviewer)

From PowerShell in `C:\Users\nemes\dnd_ai\portal` (uppercase `C:`):
- **Focused run:**

  ```
  npx vitest run src/components/world/LocationChildren.test.tsx src/App.locationChildren.test.tsx src/components/world/WorldRecordWorkspace.test.tsx src/components/world/WorldRecordWorkspace.breadcrumb.test.tsx src/components/world/WorldRecordWorkspace.areaNow.test.tsx src/components/world/WorldRecordWorkspace.scoped.test.tsx src/components/world/WorldRecordWorkspace.runtime.test.tsx src/components/world/editNavigation.test.tsx src/App.worldNavigation.test.tsx src/App.locationAuthoring.test.tsx
  ```
- **Full run:** `npm test`. Record the first run and any rerun separately, naming each failure. A failure matching an open investigation is recorded as such, without a claimed cause.
- `npm run lint`, `npx tsc -b`, `npm run build`.
- From the repository root: `uv run python scripts/check_documentation.py` and `git diff --check`.

Backend checks are not required. A backend change is a stop condition.

### 7.2 C08 checkpoint merge requirements

See [S01 plan §12.4](p15-c08-s01-location-children-plan.md#124-c08-checkpoint-merge-requirements).

## 8. Authorization, disclosure, late answers, focus and announcements

- **Server-authoritative.** The panel shows exactly what the S01 read returns for the current access. An editor's flags only request preview, and the server decides whether to honor them.
- **Disclosure.** No totals. Every path entry, name and link comes from the read. Loaded rows are dropped on 401, 403 and 404, and on any change of place, query, preview or campaign.
- **Account and resource isolation.** A campaign change is a route change, which unmounts or retuples the panel and aborts reads. Session account changes go through the existing session boundary and the 401 handling.
- **Late answers.** One owner per read tuple, with abort plus a generation check (N9, N10, N17).
- **Refused, partial and unknown outcomes.**
  - Reads only.
  - A refused read clears the list.
  - A failed Show more keeps earlier authorized rows and retries exactly that page.
  - No write identity or reconciliation is involved.
- **Drafts and navigation.** No draft is created. The query is in the address, so Back and Forward restore it. Departure protection is not needed (R-4).
- **Focus and announcements.** As §3.2: one polite status line, focus kept on search, moved to the first new row after Show more.

## 9. Intermediate states

T01 is a single commit. It requires S01's API on the branch, and C08 merges only as one checkpoint (S01 plan §12.4).

## 10. Decisions

**No owner decision is required.** Routine choices made here:

- **R-1 (panel on every place except a dungeon area).** Areas cannot be parents under the current commands.
- **R-2 (`within` with replace).** This is the same pattern as C04's and C06's list state. Back leaves the page instead of stepping through queries.
- **R-3 (Show more, first page on return).** Persisting loaded pages would put cursors in history. Re-reading keeps answers current with access.
- **R-4 (no departure guard for the query).** It is a read filter, not unsent work.
- **R-5 (editors preview drafts and archived places).** This matches World search's editor toggle and lets authors find draft children. The server still applies the read-private gate.
- **R-6 (path text is not linked in results).** One link per row keeps the keyboard order short. The opened place's Location path gives the way back up.
- **R-7 (containment links carry the page's task state).** This is the same convention as other in-record links. Containment is never added to the task trail (R16).

## 11. Handoffs

### 11.1 Sonnet implementation instructions

1. **Eligibility.** Confirm that S01 has a recorded independent pass (S01 plan §11 and the register's S01 row), and that S03-T01's records commit is present. If either is missing, stop.
2. **Baseline.** Use the current `origin/phase15/completion` head: confirm it is HEAD, the worktree is clean, and record its full SHA as this task's baseline. Revalidate:
   - S01's route, parameters, response keys and status codes against S01 plan §3.2 and any confirmed correction;
   - §2.1 of this plan;
   - the state S03 left in `WorldRecordWorkspace.test.tsx`.

   Record each check. Stop on any difference.
3. Read §2 to §10. Write N1–N19 first and run them at this baseline. Record each failure, and that N15 and N16's truncation part pass.
4. Implement §3.2 in the files of §4 and apply only §6.2's adaptations.
5. Run §7.1. Run M1–M8 and revert each with exact bytes restored.
6. **Stop and report instead of continuing if:**
   - a backend, API or authorization change seems necessary;
   - a change to `WorldRecordBack`, `TaskBreadcrumb`, `breadcrumbModel`, `useWorldDetail`, `usePageArrival`, `useStagedNavigation` or World search seems necessary;
   - an existing expectation outside §6.2 would change;
   - a "fails" case cannot be made to fail at the baseline;
   - the panel would need to read more than one page per user action.
7. Commit with the §5 subject and push. Record the following in §11.3 and the register's S02-T01 row, then commit and push the records:
   - the baseline and implementation SHAs;
   - the revalidation results;
   - the test-first failures and guards;
   - the focused and full runs (first run and rerun separately);
   - the probes;
   - the CI position: "pending checkpoint PR".
8. Do not open, mark ready or merge a PR. Do not run browser or AX checks, start consumers, or record any acceptance.

### 11.2 Independent review boundary

- **T01 = combined S02:** from the recorded baseline to the implementation commit, plus its records commit.
- Review against §2.5, §3, §6 and §8, and re-run §7.1 and M1–M8.
- A pass is a slice verdict only. S01 plan §12.4 remains.

### 11.3 Implementation record

**Baseline and eligibility.** Baseline `041fef3ce9ae6e7171694b0f54c5f16cc42c05ff` (the commit recording Luna's S03 confirmation), equal to `origin/phase15/completion`, worktree clean at the start of implementation. S01 has a recorded independent PASS WITH VERIFICATION LIMITS (its plan §11.4; implementation `1f0164481a32fce50f48375752f7d29eb2cee53f`, records `b45736e71aff0ab887fbdce121284863b3257c46`). S03's implementation (`67922e8ce46561240a72e3e25be3134a5c29b6fd`, correction `12ca7ec0616243a027755f070a201f2f5cea3cc5`) and its review records are present (S03 plan §11.4–§11.6). Implementation commit: `25bc01912d8991ab8bc77603ed90f8163127237e` (`P15-C08-S02-T01: browse and search places within a place and follow the containment path back`).

**Revalidation (all matched; no stop condition).**
- S01 route `GET /campaigns/{campaign_id}/world/locations/{location_id}/children` (`api/world_explorer.py`): `q` (max 200), `limit` 1–100 default 25, `cursor`, `include_noncanon`, `include_archived`; response `{items, next_cursor}`; item keys `location_id, name, location_type_code, summary, canon_status, lifecycle_status, path[{location_id, name, location_type_code}]`; 200, and the detail route's 404 for an unavailable parent. This matches S01 plan §3.2.
- §2.1 against the code: the Location path was plain text (no links); `LocationPanels` had no `campaignId`; the reader and the workspace's `DetailsSection` were the two hosts; `useWorldDetail` maps 401/403/404 as described; `usePageArrival` is keyed by navigation in the reader.
- S03's state in `WorldRecordWorkspace.test.tsx` was intact: D1–D10 and E1–E6 present, and `DungeonAreasSection.tsx` keeps the per-field edit counters. None of it was touched.

**Test-first (baseline `041fef3c`, new files only; `LocationChildren.test.tsx` 18 cases, `App.locationChildren.test.tsx` 3).** 21 cases ran: **20 failed, 1 passed**.
- Failed at baseline: N1, N2 (both variants), N3, N4 (both variants), N5, N6, N8, N9, N11, N12, N13, N14, N17 and N18 on "Unable to find role heading 'Places within The Vale'"; N7 and N19 on the missing "Places within" panel and results; N16 on the missing link "Hollowmere (Settlement)" in the Location path; N10 on `Cannot find module './LocationChildren'` (it imports the panel with a dynamic import, so that one case fails alone and the other cases run).
- **Guards:** N15 passed at baseline (no panel, no children request) and stayed passing. N16's truncation assertions (the list holds only the server's crumbs, in order) ran before the link assertion and passed at baseline.
- The cases drive the existing hosts (reader and workspace), so a baseline failure is a missing behavior, not a missing import. N10 is the exception, because it needs the same panel mounted across two places.

**Implementation notes.**
- New `LocationChildren.tsx` (panel and read ownership in one file), `fetchLocationChildren` in `api/world.ts`, `LocationChild`/`LocationChildrenPage` types, linked crumbs in `LocationPanels` (`campaignId` and `linkState` props), and both hosts render the panel except for `dungeon_area`.
- Read ownership is one owner object per tuple; an answer is applied only if its owner is still current (the generation check), and a tuple change clears rows at once (rows shown are derived from the tuple).
- A bug found while making the cases pass and fixed before the commit: the first-page answer was dropped when the snapshot still held the previous tuple's key.
- The reader's `usePageArrival` moves focus to the heading on any replace of the address. The panel therefore returns focus to the search field with `focusSoon` after submit or clear (the existing hook is unchanged, as §3.3 requires). A short-lived heading focus before the return is possible in a real browser; it was not observed there.
- The panel reads the session with the optional `SessionContext` instead of `useSession`, because `WorldLocationDetailPage.test.tsx` renders the reader without a `SessionProvider`. See run 1 below.

**Existing tests changed (§6.2 only).** A `…/world/locations/<id>/children` handler returning `{ items: [], next_cursor: null }` in the setups of `WorldRecordWorkspace.test.tsx`, `App.worldNavigation.test.tsx` and `App.locationAuthoring.test.tsx`. No expectation changed. The §7.1 files already passed before these handlers (265 passed with the catch-all 404 or an unmocked read); `WorldRecordWorkspace.breadcrumb.test.tsx` and `.areaNow.test.tsx` were not changed because they have a catch-all 404 and no assertion touches the panel. No `LocationPanels` call in any test needed the new prop.

**Runs (kept separate).**
- Focused §7.1: 10 files, 265 passed (before the three handlers and again after).
- **Full run 1:** 458 files, **8 failed**, 5,960 passed. Failures: `WorldLocationDetailPage.test.tsx` ×6, all with `useSession must be used inside SessionProvider`, which this change caused (the panel called `useSession`; fixed as above); `terminalStates.test.tsx` "gives a missing world and a hidden world the same output" (1); `WorldsPage.filter.test.tsx` F8 (1). The cause of the last two is not diagnosed; F8 also failed in the S03 first full run.
- Isolated: those three files with the two new files, **5 files, 75 passed**.
- **Full run 2:** 458 files, **5,968 passed**, 0 failed.
- `npm run lint`, `npx tsc -b` and `npm run build` pass. `uv run python scripts/check_documentation.py` and `git diff --check` pass. No backend change, so no backend or shard run.

**Probes (each source file restored byte-exact; SHA-256 before = after: `LocationChildren.tsx` `62527d23c9a2…`, `WorldLocationDetailPage.tsx` `df3ff880c8a2…`; run over both new files, 21 cases).**

| Probe | Mutation | Failed |
|---|---|---|
| M1 | Drop the generation check | N9, N10 |
| M2 | Keep rows on 403/404 | N11 |
| M3 | Do not clear rows on a tuple change | N17 |
| M4 | Show more ignores `next_cursor` | N3, N4, N8, N11, N14 |
| M5 | Push instead of replace | N5 |
| M6 | Reader sends the preview flags | N1, N2, N3, N4, N6–N9, N11–N14, N17–N19 |
| M7 | No focus move after Show more | N4 |
| M8 | Crumbs as text | N16, N19 |

M2 fails N11 but not N12: with no rows loaded before a first-page refusal, keeping rows is not distinguishable. M3 fails N17 but not N13: an editor-to-reader change remounts the panel, so the cleared rows come from the new mount. Both are narrower than the plan's expectation and are reported as such.

**Limitations and position.**
- All of this is jsdom with a mock server: no real browser, keyboard, zoom or screen-reader behavior, including the focus return after submit.
- No backend change and no backend shard run. CI is pending the checkpoint PR; none was opened. Not run: browser/AX, human review, owner acceptance, consumers.
- This is not C08 checkpoint readiness (S01 plan §12.4).

**Independent review range:** `041fef3ce9ae6e7171694b0f54c5f16cc42c05ff..25bc01912d8991ab8bc77603ed90f8163127237e`, plus the records commit that adds this section.

### 11.4 Independent review (Codex, 2026-11-24)

**Verdicts:** **T01/S02: CHANGES REQUIRED.** Finding C08-S02-1 below prevents the stated focus-preservation acceptance case. No other implementation finding was demonstrated. S01 and S03 review passes remain intact. This is a slice verdict, not C08 checkpoint acceptance. CI remains pending the checkpoint PR; browser/AX, human and owner acceptance remain pending.

**Ancestry, scope and worktree.** Verified baseline `041fef3ce9ae6e7171694b0f54c5f16cc42c05ff` → implementation `25bc01912d8991ab8bc77603ed90f8163127237e` → records HEAD `9439ba7cfe8021219603cee8134b249769e980aa`; all are ancestors of HEAD, on `phase15/completion`. The worktree was clean before review. Implementation is limited to the listed 11 portal/API-type/test/docs files; no backend change. The records commit is limited to this plan and the register. S01's reviewed §3.2 endpoint contract and S03's §11.5–§11.6 correction record were checked against the implementation. S03's D/E tests and source remain unchanged.

**C08-S02-1 — deferred search-focus restoration can override a user's move.** Track: keyboard interaction. In `LocationChildren.tsx` `apply()`, submitting a search immediately focuses the search field and schedules an unconditional `focusSoon(SEARCH_ID)`. If the user moves focus to another persistent control after the request starts but before that animation-frame callback runs, the callback steals focus back to Search while the read is still loading. A temporary held-read probe reproduced this: submit `q=cave`, wait until the request is observed, focus the Search button, keep the response unresolved, and observe that focus returns to the search input. The temporary test was removed and `LocationChildren.test.tsx` restored byte-for-byte (SHA-256 `C1710CBFF4286877E0A784D9C82CD3D18442C6CCE8B48DB83A7796E8967CE6B`; no source diff remains). **Rubric:** exposure **1** (reader/editor place search with a narrow deferred-focus timing window); impact **1** (bounded keyboard-navigation interruption); triggerability **1** (requires a deliberate focus move before the scheduled callback); detection/recovery **0** (immediately visible and easy to recover); blast radius **0** (one user/page). **Score 3, Low.** Readiness: blocks this slice because the explicit acceptance requires preserving a focus move made while loading. Bounded correction: return focus after page-arrival handling only while focus remains on the element displaced by that arrival (or the search field); skip the delayed focus if another connected control has gained focus. Add a held-read regression that moves focus before deferred restoration and verifies it remains there; retain N5's ordinary search-focus behavior.

**Other contracts and evidence.** Direct-child reads and recursive search consume S01's reviewed response, cursor, visibility and hidden-chain rules. Query state uses `within` with replace, retains other query parameters and router state, and Back/reopen restores it. Result links and Location path links carry the existing task state; path entries come only from the server's visible/truncated crumbs. Tuple ownership and generation checks prevent stale query/place responses; paging uses the returned cursor and deduplicates against loaded IDs; failed reads preserve rows only for recoverable errors and Retry repeats the same read. Optional `SessionContext` is used only for 401 reload compatibility with provider-free tests. In production `AuthenticatedAppLayout` gates the route subtree and `RouteSessionProvider` remounts session scope on campaign changes; place and campaign are also part of the read tuple. The S01 API and S03 behavior are unchanged.

Baseline evidence is limited: missing-panel/module failures show absence, not all later behavior. N15 passed at baseline; N16 truncation passed and its link assertion failed. M2's “keep rows on 403/404” fails N11 but not N12 because a first-page refusal has no prior rows; N11 is the discriminating loaded-rows case and N12 independently verifies first-page refusal and 401 reload. M3 fails N17 but not N13 because editor-to-reader remount clears component state; N17 exercises same-instance query change and asserts immediate row clearing, while N13 protects draft visibility across permission loss. Those results adequately protect the distinct behaviors; no additional issue is assigned for the planned mutation counts. The six provider-free detail-page failures in full run 1 were caused by the required session provider and were corrected to optional context. The `terminalStates` and `WorldsPage.filter` F8 failures remain undiagnosed.

**Verification.** Exact §7.1 focused set: **10 files, 265 passed**, including the S03 workspace regressions. An extra broad focused selection passed **8 files, 230 tests**. Lint, `npx tsc -b` and build passed (build emitted the existing large-chunk advisory). Documentation and diff checks pass after these records are updated. The temporary focus probe failed as described and source was restored byte-exact. Keep full portal evidence separate: run 1 **8 failed, 5,960 passed** (six provider failures corrected; `terminalStates` and `WorldsPage.filter` F8 unproven); isolated **5 files, 75 passed**; run 2 **458 files, 5,968 passed**. No full suite was repeated, and no backend change or shard run occurred.

**Remaining C08 integration requirements.** S02's review finding must be corrected and confirmed. The checkpoint still requires independent S01/S02/S03 passes, integrated A1–A16/N1–N19/D1–D13 acceptance on the integration head, a full portal run and full backend shard run on executable code, and CI on that exact head as stated in S01 plan §12.4. Browser/AX, human and owner acceptance remain separate. No consumer work was started and no checkpoint readiness or acceptance is claimed.

### 11.5 Correction of C08-S02-1 (Sonnet, 2026-11-24)

Luna's §11.4 review (CHANGES REQUIRED, score 3 Low) stays above as history. **C08-S02-1: corrected, pending independent confirmation. S02 is not passed.**

**Baseline and commit.** Baseline `9439ba7cfe8021219603cee8134b249769e980aa` (equal to `origin/phase15/completion`; Luna's uncommitted plan and register edits were present and are preserved in the records commit). Correction commit `041fe4d10b646a29bc8a54b6a545dc4274d42e98`: `P15-C08-S02-T01: keep search focus where the person moved it before the deferred return (C08-S02-1)`. It changes only `LocationChildren.tsx` and `LocationChildren.test.tsx`. No page-arrival hook, API, S01 or S03 file changed.

**Fix.** `apply()` still focuses the search field at once and then schedules one return of focus after the page's own arrival focus. That frame now:
- runs only while focus is still on the search field, on no element, or on a page heading (the `<h1>` page arrival moved it to); focus on Search, a result, Show more or any other control is left alone;
- belongs to the latest search: a newer search cancels the earlier frame and an owner counter makes an already-queued stale frame inert;
- is cancelled when the panel unmounts or the place or campaign changes, and does nothing if the field is no longer connected.

**Regressions written first (`LocationChildren.test.tsx`, "Search focus return").** The animation frames are captured by a `requestAnimationFrame` stub and run by the test, so the race is controlled (no sleep or timer). Against baseline `9439ba7cfe8021219603cee8134b249769e980aa` (22 cases in the file):
- **Failed before the fix (3):** F1 (focus moved to Search, then a result, while the read is held and after it settles, is stolen back to the field); F3 (a frame from an earlier search steals focus after a newer search); F4 (a frame scheduled before leaving the place moves focus on the next place's page).
- **Guard that passed at baseline (1):** F2 (focus still on the heading or the field returns to the field); N5 and N18 also keep the ordinary return, unchanged.
- During test writing a first draft of F3 passed at baseline because it did not exercise a stale frame; it was rewritten to run the earlier frames explicitly and then failed as intended. The final F3 is the version recorded here.

**Verification.**
- New and S02 cases after the fix: 2 files, 25 passed. §7.1 focused set (10 files, including the S03 workspace regressions): **269 passed**.
- `npm run lint`, `npx tsc -b` and `npm run build` pass. `uv run python scripts/check_documentation.py` and `git diff --check` pass.
- **Full portal run 1:** 458 files, 1 failed, 5,971 passed. The failure was `OrganizationMembersReader.test.tsx` "does not show the previous organization's roster while the next one loads" (about 8 s); cause not diagnosed. **Isolated:** that file, 12 passed. **Full portal run 2 (rerun):** 458 files, **5,972 passed**, 0 failed.
- No backend change, so no backend shard run. C08's integrated backend verification remains outstanding.

**Mutations (source restored byte-exact; SHA-256 before = after `10b74666fab9…`).**

| Probe | Mutation | Failed |
|---|---|---|
| MA | The frame focuses the field unconditionally (the reviewed behavior) | F1 |
| MC | No cancellation and no owner check, so an earlier search's frame still runs | F3 |
| MB | Owner check alone removed (cancellation kept) | none: cancellation already covers it, so the check is a second guard that no case isolates |

F4 passes under MA because the pending frame is cancelled when the panel unmounts; no mutation removed that unmount cancellation alone, so F4 is a guard on the combined behavior, not a separately mutation-checked case.

**Limitations.** jsdom with a stubbed animation frame: real browser timing, keyboard behavior, zoom and screen readers were not exercised, and a brief heading focus before the return is still possible in a real browser. CI is pending the checkpoint PR; none was opened. Not run: browser/AX, human review, owner acceptance, consumers. This does not establish C08 checkpoint readiness.

**Luna's re-review range:** `9439ba7cfe8021219603cee8134b249769e980aa..041fe4d10b646a29bc8a54b6a545dc4274d42e98`, plus the records commit that adds this section.

### 11.6 Independent confirmation of C08-S02-1 (Codex, 2026-11-24)

**Verdicts:** **C08-S02-1: CONFIRMED CORRECTED. T01/S02: PASS WITH VERIFICATION LIMITS.** The original §11.4 CHANGES REQUIRED verdict and score 3 Low remain as history. No new implementation finding was demonstrated. This is not C08 checkpoint acceptance. CI remains pending the checkpoint PR; browser/AX, human and owner acceptance remain pending.

**Ancestry, scope and worktree.** Verified baseline `9439ba7cfe8021219603cee8134b249769e980aa` → correction `041fe4d10b646a29bc8a54b6a545dc4274d42e98` → records HEAD `cd4372c08ddacf7ec2117ebcd192548086c2814c`; all are ancestors of HEAD on `phase15/completion`. The worktree was clean before review-record edits. Correction scope is only `LocationChildren.tsx` and its tests; S01, S03, and shared page-arrival code are unchanged. The records commit changes this plan and the register.

**Correction behavior and controlled callbacks.** `apply()` still focuses the input immediately. Its deferred callback returns focus only if active focus is absent, on `body`, on the input, or on the `<h1>` used by page arrival; Search, a result link, and other controls are left alone. F1 holds the read, explicitly runs the queued frame after moving focus to Search, verifies focus while the read remains pending, resolves the read, then verifies it remains. Its later result assertion occurs after the original frame has already run. To check that post-settlement path directly, I ran a temporary controlled-frame probe that settled the held read first, moved focus to the newly rendered result, explicitly ran the still-queued callback, and verified focus stayed on that result. The probe passed and was removed; `LocationChildren.test.tsx` was restored byte-exact (SHA-256 `8E0C6B911EAAEEC1DED55B91D7D3F9CBAB330D210BDB2E5F12886FBD814A9EA4`). F2 explicitly runs the frame for heading/input fallback, while the implementation's narrow predicate does not match another focused control. The original N5 path remains unchanged; N5 and N18 retain normal return-to-search behavior. F3 explicitly runs the newer callback and attempts the older frame; it passes with cancellation in place. F4 routes to another place and explicitly drains the captured frame queue after the old panel unmounts; cleanup cancellation, rather than test teardown, prevents focus movement. Campaign/place changes and unmount invoke cancellation; the owner counter additionally makes a stale callback inert, and a disconnected input is rejected.

**Mutation evidence.** MA (unconditional focus) fails F1. MC (remove both cancellation and owner protection) fails F3. MB (remove owner protection while retaining cancellation) fails no case because cancellation already prevents the callback; the ownership check is a redundant defense under the tested scheduling model. F4 protects their combined lifecycle behavior. The tests' frame queue is stubbed and manually drained, so regression assertions execute relevant callbacks; F4 additionally proves unmount cleanup cancels its queued callback. No production source was mutated during this confirmation.

**Other contract review.** Direct children, recursive search, `within` replace/restoration, unrelated query/state preservation, cursor paging/deduplication, row ordering, linked visible crumbs, parent navigation, permission-loss remount, session-optional 401 reload, failures/retry, stale query/place responses, and campaign/place/unmount ownership were reviewed. S01's child API contract remains consumed as reviewed; S03's D/E behavior and implementation are unchanged. The prior N11/N17 and M2/M3 evidence disposition remains adequate: N11 exercises a loaded-row Show-more 404; N12 verifies first-page refusal and 401; N17 proves same-instance query clearing; N13 checks draft removal across the editor-to-reader remount. No extra finding is warranted for those planned mutation counts.

**Current verification and historical runs.** Re-ran exact §7.1 focused set: **10 files, 269 passed**, including S03 regressions. Documentation and diff checks pass after this record update. No full suite was repeated. Keep correction full-run events separate: run 1 **5,971 passed, 1 failed** (`OrganizationMembersReader`); that file isolated **12 passed**; run 2 **458 files, 5,972 passed**. The OrganizationMembersReader failure cause is unproven. Earlier implementation full-run events remain historical: run 1 **8 failures/5,960 passed** (six provider failures were caused by the required session provider and corrected to optional context; `terminalStates` and `WorldsPage.filter` F8 causes remain unproven); isolated **5 files/75 passed**; run 2 **458 files/5,968 passed**. No backend change or backend shard run was performed for the correction.

**Limits and remaining C08 requirements.** The focus confirmation uses jsdom with controlled animation frames, not a real browser, keyboard, zoom, or screen reader. C08 still requires integrated A1–A16/N1–N19/D1–D13 acceptance plus correction regressions, full portal and backend verification on the integrated executable code, and CI on that exact head (S01 plan §12.4). CI is pending the checkpoint PR; no checkpoint readiness or acceptance is claimed. S01/S03 passes remain intact; no consumers were started.

# D/P15-C08-S02 implementation plan: navigate children in the portal

Owner register rows: [P15-C08](work-register.md#p15-c08), [P15-C08-S02](work-register.md#p15-c08-s02), [P15-C08-S02-T01](work-register.md#p15-c08-s02-t01). Source finding: [R16 — Location hierarchy](work-register.md#r16--location-hierarchy). API contract: [S01 plan §3.2](p15-c08-s01-location-children-plan.md#32-in-scope-t01). Checkpoint coordination: [S01 plan §12](p15-c08-s01-location-children-plan.md#12-c08-checkpoint-coordination).

Prepared by Opus, 2026-11-24, against planning baseline `680629b0e9d8193112c1e6378e74fcd41323cac6` (see the S01 plan header). **Plan only. T01 is not eligible until S01 is independently reviewed.**

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

*(Sonnet records here.)*

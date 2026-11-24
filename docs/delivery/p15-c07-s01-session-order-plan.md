# D/P15-C07-S01 implementation plan: default planned-session order

Owner register rows: [P15-C07](work-register.md#p15-c07), [P15-C07-S01](work-register.md#p15-c07-s01), [P15-C07-S01-T01](work-register.md#p15-c07-s01-t01). Source finding: [R09](work-register.md#r09--smaller-layout-list-and-form-repairs) and the 2026-11-11 review row S02 ([review-2026-11-11.md](review-2026-11-11.md)): "Scheduled ascending, unscheduled last, stable sequence/id tie; explicit user sort preserved."

Prepared by Opus, 2026-11-24.

- Starting SHA: `666cf7696bfb93af4ceee13fa20931ccc10c5b8d`, the PR #75 head, clean worktree.
- Plan-entry head: `73acad3eb92f775bf0667dc64b70566e3dd4a8cb`, the C06 merge (PR #75), reached by fast-forward. Its tree (`3982aed8…`) is identical to `666cf76`'s; no history was rewritten.
- Implementation baseline: the commit that adds this plan (reported in the handoff).
- CI: no run exists for C07; its checkpoint PR has not been opened.

## 1. Entry readiness

- C07 has no checkpoint prerequisite in the register, and S01 names no slice-specific gate. Table order is not used as a dependency.
- C07 has one slice and one task: S01-T01.
- The [run-log](work-register.md#run-log) investigation (Run Session log handoff and layout) stays a separate record. It is not part of C07 and does not gate it.
- The recurring backend shard-7 failure (C04 row) and the `OrganizationMembersReader` CI failure (C06 row) are separate investigation obligations. They are not C07 prerequisites, and nothing in this plan depends on their cause.
- No owner decision blocks S01.

## 2. Verified current behavior

### 2.1 How the Sessions page works today

- `GET /campaigns/{campaign_id}/sessions` returns every session the caller may see, unpaged, ordered `session_number DESC` (`src/dnd_ai/queries/session.py`, `list_campaign_sessions`). Each item carries `session_number`, `title`, `status_code`, `play_status`, `scheduled_for`, `started_at`, `ended_at` and, for editors, `available_actions`. `(campaign_id, session_number)` is unique (`ux_sessions_campaign_number`).
- `CampaignSessionsPage` reads the list once per mount through `useCampaignSessions` (abort and campaign/version matching already own late answers) and renders `SessionsPage` only on success.
- `SessionsPage` passes the rows to the shared `SortableTable` with `initialSort={{ column: "session_started_at", direction: "desc" }}`. Sort state is local React state: it lives as long as the page is mounted, and it is not in the address.
- Column comparators: Title uses `localeCompare`; Status compares `play_status` codes; Planned start, Start time and End time use `compareNullableTimestamps`, which compares instants and keeps nulls last in both directions. A tie returns 0, so `Array.prototype.sort` (stable) leaves tied rows in the server's order. The Actions column has `compare: () => 0`.

### 2.2 Plan-entry reproduction results

A temporary test (`SessionsPage.c07repro.test.tsx`, run once at `73acad3` and deleted; the worktree was clean afterwards) rendered the real `SessionsPage` with fixtures in the server's `session_number DESC` order.

| Case | Kind | Fixture and action | Result at baseline |
|---|---|---|---|
| R1 | **defect** | Sessions 4 (unscheduled), 3, 2, 1 with planned starts Dec 3, Dec 1 and Dec 2; two have start times. No interaction. | Expected 2, 1, 3, 4; got **3, 1, 4, 2** (start time descending, unstarted last). |
| R2 | **defect** | Default headers. | The only `aria-sort` is **Start time: descending**; Planned start has none. |
| R3 | **defect** | Sessions 2 and 1 at the same instant (`…19:00:00Z` and `…19:00:00.000+00:00`), 3 and 5 unscheduled; Planned start sorted ascending by the user. | Expected 1, 2, 3, 5; got **2, 1, 3, 5** (ties keep server order). |
| R4 | **defect** | Two sessions titled "Same", input 2 then 1; Title sorted. | Expected session 1 first; got **session 2 first**. |
| R5 | guard | Planned start sorted descending by the user. | Later first, unscheduled last: **passes**. |
| R6 | guard | Title sorted, then the rows are replaced (a re-render with a new session). | The explicit sort stays applied to the new rows: **passes**. |

### 2.3 Deviations S01 repairs

- **DV-1 (R1, R2):** the default order is start time descending, so a planned session is placed by when it was played, not when it is planned, and every unstarted session falls to the end in server order.
- **DV-2 (R3, R4):** a tie in any column keeps the server's order instead of a defined sequence. The result changes if the server order changes, which the criteria forbid ("stable order across ties and user-selected sort").

### 2.4 Source-inspected, not reproduced

- **Campaign change.** `CampaignSessionsBoundary` renders a loading page while a new campaign's list loads, which unmounts `SessionsPage`; the next campaign opens with the default order. Late answers are owned by `useCampaignSessions` (existing tests in `useCampaignSessions.test.ts` and `CampaignSessionsBoundary.test.tsx`). S01 does not change either file.
- **Instant comparison.** `compareNullableTimestamps` compares `Date.getTime()`, so offsets that sort differently as text still sort by instant. This is guarded by F5.

### 2.5 Behavior that must not regress

- The same rows are shown: sorting never adds, drops or reorders the server's authorization decisions. Run links still appear only where `available_actions` allow (`canRunSession`).
- The empty state, links and their task state (`useTaskLinkState`, `continuedStateVia`) are unchanged.
- `SortableTable`, `utils/sorting`, the API and the query are unchanged, so the other tables that use `SortableTable` keep their behavior.

## 3. Outcome, scope and exclusions

### 3.1 User outcome

A member opening Sessions finds the next planned session near the top: the list opens ordered by **Planned start**, earliest first, with unscheduled sessions after every scheduled one. Sessions at the same planned start, and unscheduled sessions, appear in session order. Choosing a column heading sorts by that column instead, and ties there also follow session order, so the same data always appears in the same order.

### 3.2 In scope (T01)

1. **Default order.** `initialSort` becomes `{ column: "session_scheduled_for", direction: "asc" }`. The Planned start heading shows `aria-sort="ascending"` and ▲; no other heading has `aria-sort`.
2. **Tie-break.** A page-local comparator orders tied rows by `session_number` ascending, then by `session_id` in code-unit order (a guard only: numbers are unique per campaign). The tie-break is **always ascending**, whatever the chosen direction, in the same way nulls stay last in both directions (R-1).
3. **Where it applies.** The tie-break wraps the comparators of Title, Status, Planned start, Start time and End time, in the default sort and in every explicit sort. The Actions column is unchanged (§3.3).
4. **Explicit sort.** Clicking a heading keeps the existing `SortableTable` behavior: a new column starts ascending, the current column toggles. Clicking Planned start in the default state therefore toggles it to descending. The explicit sort stays applied while the page is mounted, including when its rows are replaced (guard F9).
5. **Documentation.** Add the ordering to the session-list sentence in the `/app/:campaignId/sessions/new`, `…/sessions/:sessionId` row of [portal behavior](../reference/portal-behavior.md): the list opens by Planned start, earliest first, unscheduled last, ties in session order; a chosen column sorts instead, with nulls last and ties in session order, until the page is left.

### 3.3 Exclusions

- No API, query, pagination or server-order change (the review's "future API pagination contract" stays future work). The page still sorts the complete list it receives.
- No sort in the address and no restoration on Back (R-2). The register asks for explicit-sort precedence, not persistence.
- No change to `SortableTable`, `utils/sorting`, or other tables that use them.
- The Status column keeps comparing status codes, and the Actions column keeps `compare: () => 0`. Neither is part of R09's finding. Changing them is a separate request.
- Campaign Home, the Run Session page, session pickers and the [run-log](work-register.md#run-log) investigation are excluded.
- No new announcement: `aria-sort` and the visible arrow already report the sort, and focus stays on the clicked heading button.

## 4. Affected files and interfaces

| File | Change |
|---|---|
| `portal/src/pages/SessionsPage.tsx` | `initialSort`, a session-sequence tie-break and its use in five comparators. |
| `portal/src/pages/SessionsPage.order.test.tsx` (new) | Cases F1–F13. |
| `portal/src/pages/SessionsPage.test.tsx` | One allowed adaptation (§6.2). |
| `docs/reference/portal-behavior.md` | The ordering sentence (§3.2 item 5). |

No other test expectation may change. If another existing test fails, stop (§11.1).

## 5. Task commit

One commit: `P15-C07-S01-T01: order planned sessions by planned start with unscheduled last and stable ties`.

## 6. Acceptance cases

Fixtures are given in the server's order (`session_number DESC`) unless the case permutes them. Row order is read from the title links' `href` (`…/sessions/<session_id>`) so that equal titles stay distinguishable. "(fails at baseline)" cases must be written first and recorded failing; "(guard)" cases pass at baseline and are recorded passing. A guard is not expected to fail first.

| Case | Kind | Fixture and action | Expected |
|---|---|---|---|
| F1 | fails at baseline | R1's four sessions, with start times that would put them in another order. No interaction. | Order 2, 1, 3, 4: planned start ascending, unscheduled last. |
| F2 | fails at baseline | Any rows. | Planned start has `aria-sort="ascending"` and ▲; no other heading has `aria-sort`. |
| F3 | fails at baseline | Two sessions at the same instant written differently (`Z` and `+00:00`), rendered in both input orders. | Lower session number first in both renders. |
| F4 | fails at baseline | Three unscheduled sessions in a shuffled input order, plus one scheduled. | The scheduled one first, then the unscheduled ones by session number ascending. |
| F5 | guard | `2026-12-01T20:00:00+02:00` (18:00Z) and `2026-12-01T19:00:00Z`. | The 18:00Z session first (instants, not text). |
| F6 | fails at baseline | F3/F4 fixture; click Planned start once (it is the default column, so it toggles to descending). | Later planned starts first, unscheduled last, both tie groups still in ascending session order; heading `descending`. |
| F7 | fails at baseline | Two sessions titled "Same" and one "Alpha"; click Title, then click it again. | Ascending: Alpha, then the two "Same" by session number ascending. Descending: the two "Same" (still ascending session number), then Alpha. |
| F8 | fails at baseline | Sessions with equal start times, equal end times, equal play status and missing start/end times; sort Start time, End time and Status in each direction. | Ties by session number ascending in every direction; missing times last. |
| F9 | guard | Sort by Title, then re-render with a new row added. | The new row is placed by Title; the default order is not reapplied. |
| F10 | fails at baseline (repeats DV-1) | A new mount after an explicit sort (unmount, mount). | The default order of F1 and the F2 heading. |
| F11 | guard | Editor rows where some offer `run` and some do not, plus an archived session. | Same set of rows as the input, each Run link only where `canRunSession` allows, archived marked, in every sort. |
| F12 | guard | Click a heading button. | Focus stays on that button. |
| F13 | guard | The unchanged `SessionsPage.test.tsx` cases (empty state, links) and the adapted case (§6.2). | Pass. |

F10's reset to a default already happens at baseline; it fails there only because the default is wrong, so it is not a separate defect.

### 6.1 Mutation probes (Sonnet runs them; the reviewer reruns them)

Each probe is applied to `SessionsPage.tsx`, the named cases are run, and the file is restored byte-for-byte (compare hashes: `git restore` rewrites LF files as CRLF here).

| Probe | Mutation | Must fail |
|---|---|---|
| M1 | `initialSort` back to `session_started_at` / `desc`. | F1, F2 |
| M2 | Remove the tie-break from the Planned start comparator only. | F3, F6 |
| M3 | Apply the chosen direction to the tie-break (`applyDirection`). | F6 or F7 (descending ties) |
| M4 | Tie-break by `session_number` descending. | F3, F4 |
| M5 | Remove the tie-break from the Title comparator only. | F7 |
| M6 | Pass `initialSort` with `direction: "desc"`. | F1, F2 |

### 6.2 Allowed adaptation of an existing test

`SessionsPage.test.tsx` › "initially sorts sessions by descending start time with missing timestamps last" describes the behavior S01 replaces. Keep its fixture and its assertion (Newer, Older, Unscheduled) but reach it explicitly: click **Start time** twice (ascending, then descending), and rename it to say that a chosen start-time sort is descending with missing times last. No other expectation in that file changes.

## 7. Verification

### 7.1 Per-commit checks (Sonnet; repeated by the reviewer)

From PowerShell in `C:\Users\nemes\dnd_ai\portal` (uppercase `C:`):

1. Focused: `npx vitest run src/pages/SessionsPage.order.test.tsx src/pages/SessionsPage.test.tsx src/components/SortableTable.test.tsx src/components/CampaignSessionsBoundary.test.tsx src/hooks/useCampaignSessions.test.ts src/App.sessionAuthoring.test.tsx src/pages/SessionDetailPage.test.tsx`.
2. Full `npm test`. Record the first run and any rerun separately, with the failing test's name.
3. `npm run lint`, `npx tsc -b`, `npm run build`.
4. From the repository root: `uv run python scripts/check_documentation.py` and `git diff --check`.

### 7.2 C07 checkpoint merge requirements (not S01's verdict)

1. S01 passes independent review.
2. F1–F13 pass on the integration head, with one full portal run there.
3. CI passes on the exact integration head.

### 7.3 Separate events (after the merge; not merge gates)

Portal ordering evidence in a real [browser](work-register.md#browser) (the register's C07 criterion), [ax](work-register.md#ax) checks of the sort buttons and `aria-sort`, human review, [p15-integration](work-register.md#p15-integration) and `p15-owner`.

## 8. Authorization, disclosure, concurrency and focus rules

- **Server authority.** The server decides which sessions are listed and which actions each offers. The page only orders what it received; it never infers a permission from order or position.
- **Writes.** The page sends none. Refusal, partial success, uncertain outcomes, retries and reconciliation do not apply to S01; session edits keep their own detail-page handling.
- **Authority loss and account or campaign change.** A lost permission or a new campaign reaches the page as a new list read through the unchanged hook and boundary; a new mount starts from the default order (F10).
- **Late answers.** Owned by `useCampaignSessions`; unchanged.
- **Focus and announcements.** Sorting keeps focus on the clicked button (F12). No live-region announcement is added.
- **Departure protection.** None: nothing is edited on the list.

## 9. Intermediate states

None. The change lands in one commit; the default and the tie-break are not split.

## 10. Decisions

Routine choices made by Opus; none needs the owner.

- **R-1 Tie-break direction.** Ties are always ascending by session number, whatever direction the user chose, matching nulls-last. Reversing tied rows on a direction toggle would make "stable" depend on the click count.
- **R-2 Persistence.** The explicit sort lasts while the page is mounted (existing behavior), and is not written to the address. R09 asks that an explicit sort take precedence over the default, not that it survive navigation. A later request can add an address parameter.
- **R-3 Placement.** The tie-break is page-local in `SessionsPage.tsx`, not a new `SortableTable` prop, so no other table changes.
- **R-4 Final key.** `session_id` after `session_number` is a defensive total order; it is unreachable for valid data because numbers are unique per campaign, so no case asserts it.
- **R-5 Default direction.** Ascending ("Scheduled ascending", review row S02): the earliest planned session first. Past scheduled sessions also come first; the Status column and an explicit descending sort remain available. Hiding or splitting past sessions would be a new product choice and is excluded.
- **R-6 Status column.** Its code-order comparison stays (§3.3); only the tie-break is added.

## 11. Handoffs

### 11.1 Sonnet implementation instructions

1. Confirm the baseline is HEAD and `origin/phase15/completion` and the worktree is clean.
2. Write F1–F13 in `SessionsPage.order.test.tsx`. Run them on the unchanged page: record which fail (the "fails at baseline" cases) and which pass (the guards).
3. Make the §3.2 changes and the §6.2 adaptation. Change nothing else listed in §2.5 or §3.3.
4. Run §7.1, then M1–M6 with byte-exact restoration.
5. **Stop and report** instead of committing if: an existing test outside §6.2 must change; a guard fails after the change; `SortableTable`, `utils/sorting`, the API or the query would need to change; or a probe does not fail any case it names.
6. Commit with the §5 subject and push. Record in §11.3 and the register's T01 row: the SHA, the test-first failures and guard results, the runs (first run and rerun separately), the probes and the CI position ("pending checkpoint PR"). Commit and push the records.
7. Do not open or merge a PR, run browser/AX checks, start consumers, or record acceptance.

### 11.2 Independent review boundary

The review range is from this plan's commit to the T01 implementation commit, plus its records commit. The reviewer reruns §7.1 and M1–M6 and checks R-1 to R-6. C07's checkpoint requirements (§7.2) are separate from the slice verdict.

### 11.3 Implementation record

Sonnet, 2026-11-24. Baseline `3175c3899dad7dcbe0cf5b08d3230b28f8780d59` (confirmed as HEAD and `origin/phase15/completion`, clean worktree). Implementation commit `6f61188d9a5fa7322134c8213a496de5b62e9712`: `P15-C07-S01-T01: order planned sessions by planned start with unscheduled last and stable ties`. Review range: `3175c3899dad7dcbe0cf5b08d3230b28f8780d59..6f61188d9a5fa7322134c8213a496de5b62e9712`, plus this records commit.

**Change.** `SessionsPage.tsx`: `initialSort` is `session_scheduled_for` ascending; a page-local `compareSessionSequence` (session number ascending, then session id in code-unit order) is wrapped around the Title, Status, Planned start, Start time and End time comparators by `withSequenceTieBreak`; Actions is unchanged. `SessionsPage.order.test.tsx` is new (F1–F12 in 12 tests; F13 is the existing file). `SessionsPage.test.tsx` has only the §6.2 change (the start-time case now clicks Start time twice and is renamed). `portal-behavior.md` has the ordering sentence. `SortableTable`, `utils/sorting`, `CampaignSessionsPage`, `CampaignSessionsBoundary`, `useCampaignSessions`, the API and the query are untouched.

**Direction (verified before implementing).** `SortableTable` does not reverse rows: it calls `compare(a, b, direction)` and each comparator applies the direction itself (`applyDirection`, nulls last in `compareNullableTimestamps`). A tie-break applied after the primary comparison and not passed through `applyDirection` is therefore ascending in both directions, and F6, F7 and F8 assert this on displayed rows.

**Fixtures.** Shuffled inputs, equal instants written as `Z` and `+00:00`, missing timestamps, repeated titles and play statuses; row order is read from each row's title-link `href`. The session-id key (R-4) is unreachable for valid data and has no case.

**Test-first (unchanged page).** Of 12 tests, 8 failed and 4 passed, exactly as designated: failed F1, F2, F3, F4, F6, F7, F8, F10; passed (guards) F5, F9, F11, F12. F5 passes at baseline only because its input order already equals its expected order; after the change it is what separates instants from timestamp text. F13 is the existing `SessionsPage.test.tsx` and passes after the change.

**After the change.** Focused set of §7.1 (7 files): 72 passed.

**Full portal runs (reported separately).**
1. First run: 455 files passed, 1 failed (456 files, 5,927 of 5,928 tests): `App.knowledgeClaim.test.tsx` › "a confirmed save whose authoring read-back fails (DEF-006) › says the save went through, keeps the editor, holds Save, and recovers by reading only". That file then passed alone (150 of 150).
2. Second run: 1 failed (5,927 of 5,928): `App.characterShell.test.tsx` › "direct entry, history and malformed task state › gives the defaults after a direct entry and carries no task into the section links". That file then passed alone (35 of 35).
3. Third run: **456 files, 5,928 tests passed, 0 failed.**
Neither failing test imports or renders `SessionsPage`; each passed on its own. Their cause is **not diagnosed** here (both are long App-level files under a loaded full run). They are recorded as two further unexplained single-test failures, distinct from the shard-7 backend investigation and from the `OrganizationMembersReader` failure, and are not resolved by this record.

**Other checks.** `npm run lint`, `npx tsc -b` and `npm run build` pass. `uv run python scripts/check_documentation.py` and `git diff --check` pass.

**Probes (each restored byte-for-byte, SHA-256 compared equal after every probe and at the end).**

| Probe | Failed cases |
|---|---|
| M1 | F1, F2 (also F4, F5, F6, F10) |
| M2 | F3, F4, F6 |
| M3 | F6, F7, F8 |
| M4 | F3, F4, F6, F7, F8 |
| M5 | F7 |
| M6 | F1, F2 (also F5, F6, F10) |

The first M2 and M5 mutations were malformed (a syntax error, "no tests"); they were discarded and redone with an identity wrapper, and the table gives the redone results.

**CI position.** Pending the checkpoint PR; none opened. Not run: browser/AX, zoom, human review, owner acceptance, consumers.

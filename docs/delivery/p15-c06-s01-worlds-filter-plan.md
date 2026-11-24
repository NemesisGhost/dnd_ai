# D/P15-C06-S01 implementation plan: preserve the active-plus-archived filter

**Status:** Opus plan prepared 2026-11-24. **Ready for Sonnet (T01).** No owner decision blocks the task. Section 10 lists the routine choices made here; none changes a product policy, an API contract, authorization or what a caller may see.

**Register rows:**
- slice [D/P15-C06-S01](work-register.md#p15-c06-s01);
- task [T01](work-register.md#p15-c06-s01-t01);
- parent checkpoint [D/P15-C06](work-register.md#p15-c06).

**Plan-entry head:** `f0ea6d1bbbbb99218fee1a8d306631eaef13cae9` ("Merge pull request #74 from NemesisGhost/phase15/completion"), the C05 merge on `main`.
- `phase15/completion` was at `fe4dbf8f1626e22d5a70e721eb900521ae815848` (equal to its origin, clean worktree). That commit is the merge's second parent and the merge tree is identical to it (`3ee36ad9…`), so the branch was fast-forwarded to `f0ea6d1` after `git fetch origin`. No history was rewritten.
- CI: no run exists for C06; its checkpoint PR has not been opened.

Sonnet's implementation baseline is the commit that adds this plan, a child of `f0ea6d1`. The handoff prompt names it.

**How each statement was established:**
- by reading source, tests and documents at the plan-entry head;
- by a temporary plan-entry reproduction (§2.2): one Vitest file, written into `portal/src/pages/` only for the run and deleted afterwards. It rendered the real `WorldsPage`, `useAuthoringResource`, `usePageArrival` and `buildWorldChoices` with a stubbed `fetch` and the harness session. No repository file was changed by it.

**Governing sources:**
- [R09](work-register.md#r09--smaller-layout-list-and-form-repairs): "[Worlds] still selects Active **or** Archived … archived filtering can hide active choices … Worlds checkbox means active plus archived, including deduped campaign-visible active worlds; preserve URL/Back state and picker eligibility." Acceptance: "filter union and empty states … 320 CSS px and actual 200%/400% browser zoom. The first-100-worlds limit is an existing separate limitation, not silently solved by changing the filter."
- The register's [C06](work-register.md#criteria-p15-c06) ("Browse at narrow viewport and actual zoom → ax"), [S01](work-register.md#criteria-p15-c06-s01) ("Campaign-visible active choices survive the filter") and [T01](work-register.md#criteria-p15-c06-s01-t01) ("Union eligible worlds with deduplication, URL/Back state and picker tests") criteria.
- [Portal behavior](../reference/portal-behavior.md), the `/worlds` route row: one entry per world, explicit world authority wins, a campaign-visible world opens `/app/{campaignId}/world` and is marked "View only", "Create world" only with `world.create`.
- [Portal behavior §5.11](../reference/portal-behavior.md#511-authoring-patterns-phase-14) and `hooks/usePageArrival.ts`: focus moves to the `h1` once per navigation; "for a page whose own links only change the query … once per path (`keyBy: "path"`)".
- The list API, unchanged: `GET /worlds?status=active|archived|all&limit=&cursor=` (`src/dnd_ai/api/worlds.py`, `queries/worlds.py`). It returns only worlds where the caller holds an open world role or use grant, with capabilities computed per world, ordered `(lower(name), world_id)`, keyset-paged, with a maximum `limit` of 100. `all` is the union of active and archived from one ordered query, so no client-side merge of two server pages is needed.
- [world-page](work-register.md#world-page) (owner deferred): Infobox explicit-world pagination. It is not consumed here, and the first-100 limit is not changed.

## 1. Entry readiness

C06 is "Browse visible active and archived worlds". Its prerequisite column is "—" and its criteria row has no entry contract, so C06 has no checkpoint prerequisite. It has one slice, S01, with one task, T01. S01's prerequisite is "Checkpoint entry criteria; no additional slice-specific gate". The attached `world-page` record is an owner-deferred limitation that gates nothing. The legacy crosswalk rows "P15-C05-S04-T0x" are previous-register IDs; R09's session ordering (C07) and dungeon scalars (C08-S03) are separate checkpoints with their own rows.

The recurring backend shard-7 timing failure (C04/C05 rows) is a separate diagnosis obligation. It is not a C06 prerequisite, and nothing here depends on its cause.

**Verdict: S01 eligible and ready for Sonnet.**

## 2. Verified current behavior

### 2.1 How the Worlds page works today

- `WorldsPage` reads `?status=` (`archived` → archived, anything else → active) and renders a radio group "Show: Active | Archived". A change writes `?status=archived` or nothing, by REPLACE.
- It requests `GET /worlds?status=<filter>&limit=100` and merges the answer with the bootstrap's campaigns through `buildWorldChoices`, **only when the filter is Active**. Under Archived the campaign-visible worlds are not passed in.
- When the server returned a `next_cursor`, the page shows "Only the first 100 worlds are shown."
- `usePageArrival(state.kind !== "loading")` uses the default `keyBy: "navigation"`, so a REPLACE to a different query is treated as a new arrival.
- The page is read only: it sends no write.

### 2.2 Plan-entry reproduction results

Temporary file `portal/src/pages/zzC06S01Repro.test.tsx`, run from `C:\Users\nemes\dnd_ai\portal`: **1 file, 6 tests passed** (each asserts current behavior). The file was then deleted; `git status` was clean.

| # | Kind | Reproduction | Observed |
|---|---|---|---|
| R1 | **defect** | Explicit active `Eberron`, explicit archived `Old World`; choose Archived | The only choices are the two radios; the list becomes `["Old World"]`. No request ever uses `status=all`. |
| R2 | **defect** | Add a campaign-visible active world `Hosted World`; choose Archived | `Hosted World` disappears. |
| R3 | **defect** | Focus the Archived radio and choose it | After the new list loads, focus is on the `h1`, not the control the person used. |
| R4 | guard | Open `/worlds?status=archived` | The archived list loads and Archived is checked (the address restores the filter). |
| R5 | guard | Archived (answer held), then Active, then release the archived answer | The active list stays (the path-keyed resource ignores the older answer). |
| R6 | guard | `next_cursor` present | "Only the first 100 worlds are shown." |

Source-inspected only (no reproduction): the campaign setup world picker requests `status=active` (`CampaignSetupPage.tsx`); the Infobox requests `status=all` and builds its own options through `navigation/contextOptions.ts` with `buildWorldChoices`. Neither reads the Worlds page's filter.

### 2.3 Deviations S01 repairs

- **DV-1 (no union).** Active and archived worlds cannot be listed together (R1).
- **DV-2 (campaign-visible worlds hidden).** The archived view drops campaign-visible active worlds, contrary to the S01 criterion (R2).
- **DV-3 (focus taken).** Changing the filter moves focus to the `h1` (R3). This is a page-arrival rule applied to an in-page control.

### 2.4 Behavior that must not regress

- The R4–R6 guards: the address restores the filter, a late answer for the other filter is ignored, and the first-100 note follows `next_cursor`.
- Every `WorldsPage.test.tsx` case except those §4 names: loading state, links by capability, omission without access, heading focus on arrival, empty states and the Create world gate, campaign-visible entries, deduplication, unavailable/error/expired states.
- `buildWorldChoices`, `contextOptions`, the Infobox, the campaign setup picker and their tests are unchanged (`HierarchyContextPanel*.test.tsx`, `navigation/contextOptions.test.ts`, `pages/campaignSetup.test.tsx`, `pages/CampaignSetupPage.hosting.test.tsx`, `App.worldVisibility.integration.test.tsx`).

## 3. Outcome, scope and exclusions

### 3.1 User outcome

The Worlds page lists active worlds by default. One checkbox, **Include archived worlds**, adds the caller's archived worlds to the same list without hiding any active world, including worlds visible only through a campaign. The choice is in the address, so reload, Back/Forward and a shared link reproduce it. Changing it keeps focus on the checkbox and says how many worlds are shown.

### 3.2 In scope (T01)

1. **Filter control (DV-1).** Replace the radio group with one checkbox, **Include archived worlds** (unchecked by default).
   - Unchecked: `GET /worlds?status=active&limit=100`, exactly as today.
   - Checked: `GET /worlds?status=all&limit=100`. `all` is the server's own union, ordered and paged as one list.
2. **Campaign-visible worlds in both states (DV-2).** Pass `bootstrap.campaigns` to `buildWorldChoices` whether or not the box is checked. Explicit world authority still wins (deduplication by `world_id`, unchanged); a campaign-visible world stays "View only" with its campaign link and is never marked archived.
3. **Address.** Checked writes `?archived=1` by REPLACE; unchecked removes it. Reading:
   - `archived=1` → checked;
   - the legacy `status=archived` (old bookmarks and Back entries) → checked, which shows a superset of what that address showed;
   - anything else → unchecked.
   When writing, the page drops a legacy `status` parameter and keeps any other parameter.
4. **Focus and announcement (DV-3).** `usePageArrival(…, "path")`: the `h1` takes focus once per arrival at `/worlds`, not on a filter change (a documented option of the hook; the hook is unchanged). After a filter change settles, the page announces once through the existing announcer: "Showing ‹n› worlds, including archived." or "Showing ‹n› active worlds." (‹n› = listed choices; "1 world" singular). Nothing is announced on arrival beyond today's behavior.
5. **States.**
   - Loading: unchanged ("Loading worlds…"); the checkbox stays enabled. A newer choice replaces an older pending read (path-keyed resource, R5).
   - Empty, unchecked: today's text. Empty, checked: "You do not have access to any worlds yet." (both kinds are included).
   - Denied, unavailable, error and expired: unchanged.
   - The archived badge stays on archived entries only.
6. **First-100 limit.** Unchanged: one request with `limit=100`. The note shows when `next_cursor` is present, whichever state. It reads "Only the first 100 worlds are shown." and, when checked, adds "Archived worlds count toward this limit." No paging is added ([world-page](work-register.md#world-page) stays deferred).
7. **Documentation:** the `/worlds` row in `docs/reference/portal-behavior.md` changes "(Active/Archived filter)" to describe the checkbox, the address, campaign-visible worlds in both states, focus and the limit.

### 3.3 Exclusions

- No backend, API or authorization change; no paging or search; no change to the first-100 limit.
- No change to `buildWorldChoices`, `contextOptions`, the Infobox, the campaign setup picker, `useAuthoringResource` or `usePageArrival`.
- No write, so no departure question, unknown outcome, retry or reconciliation applies; a failed read keeps today's recovery.
- No copy-ui, preview or other consumer; no browser/AX run; no acceptance.

## 4. Affected files and interfaces

| File | Change |
|---|---|
| `portal/src/pages/WorldsPage.tsx` | checkbox, `status=all`, campaign worlds in both states, address read/write, `keyBy: "path"`, announcement, empty and limit text |
| `portal/src/pages/WorldsPage.test.tsx` | only these expectation changes are allowed: "switches to archived worlds and badges them with text" now checks **Include archived worlds** and expects `status=all` with both worlds; "does not list campaign-visible worlds under Archived" is replaced by its opposite (they survive, F2). Every other assertion stays |
| `portal/src/pages/WorldsPage.filter.test.tsx` | new: cases F1–F14 |
| `docs/reference/portal-behavior.md` | the `/worlds` row |

## 5. Task commit

`P15-C06-S01-T01: list archived worlds alongside active ones without hiding campaign worlds`

Followed by a docs-only records commit (plan §11.3 and the register).

## 6. Acceptance cases

"(fails at baseline)" means the case is written first and fails at this plan's commit; record each failure. "(guard)" means it passes at baseline and must keep passing; a guard is not expected to fail first.

| # | Case |
|---|---|
| F1 (fails at baseline) | Checking **Include archived worlds** sends `status=all&limit=100` and lists `Eberron` (active) and `Old World` (archived, badged) together, sorted by the server's order. |
| F2 (fails at baseline) | With the box checked, the campaign-visible `Hosted World` is still listed, "View only", linking to `/app/camp-a/world`, with no archived badge. |
| F3 (fails at baseline) | Deduplication in the checked state: a world that is both explicit (archived or active) and campaign-visible appears once, with its explicit `/worlds/{id}` link. |
| F4 (fails at baseline) | Checking writes `?archived=1` by REPLACE (history length unchanged); unchecking removes it. |
| F5 (fails at baseline) | `/worlds?archived=1` and the legacy `/worlds?status=archived` both open checked and request `status=all`; `/worlds?status=active` and `/worlds` open unchecked. |
| F6 (guard) | Back/Forward between `/worlds?archived=1` and another page restores the checked state and list. |
| F7 (fails at baseline) | Changing the filter leaves focus on the checkbox after the new list loads; arriving at `/worlds` still focuses the `h1` once. |
| F8 (fails at baseline) | One announcement per settled change: "Showing 3 worlds, including archived." / "Showing 2 active worlds."; no announcement on arrival. |
| F9 (guard) | A late answer for the previous state never replaces the current list (R5). |
| F10 | Empty states: checked with nothing returned and no campaign worlds shows "You do not have access to any worlds yet."; unchecked keeps today's text. |
| F11 (guard) | The first-100 note follows `next_cursor` in both states; when checked it adds "Archived worlds count toward this limit."; only one list request is sent per state. |
| F12 (guard) | Denied, unavailable, error and expired reads keep today's states in the checked state too. |
| F13 (guard) | Picker eligibility is unchanged: campaign setup still requests only `status=active` and never offers an archived world; the Infobox's options are unchanged (existing tests, run unchanged). |
| F14 (guard) | No identifier, archived-only campaign or world without access is listed; Create world still needs `world.create`. |

R09's 320 CSS px and actual 200%/400% zoom checks belong to the [ax](work-register.md#ax) obligation (§7.3), not to this commit.

### 6.1 Mutation probes (run by Sonnet; re-run by the reviewer)

Each probe targets behavior this task adds; a probe of a guard that already passed at baseline is not required.

| # | Mutation | Must fail |
|---|---|---|
| M1 | Request `status=archived` instead of `status=all` when checked | F1 |
| M2 | Pass campaigns only when unchecked (the old condition) | F2 |
| M3 | Write the address with PUSH | F4 |
| M4 | Stop reading the legacy `status=archived` | F5 |
| M5 | Use the default `keyBy` again | F7 |
| M6 | Announce on every render of a ready list, not once per settled change | F8 |

Revert every probe and record its failing case.

## 7. Verification

### 7.1 Per-commit checks (Sonnet; repeated by the reviewer)

From PowerShell in `C:\Users\nemes\dnd_ai\portal` (uppercase `C:`):
- focused: `npx vitest run src/pages/WorldsPage.filter.test.tsx src/pages/WorldsPage.test.tsx src/pages/campaignSetup.test.tsx src/pages/CampaignSetupPage.hosting.test.tsx src/navigation/contextOptions.test.ts src/components/HierarchyContextPanel.options.test.tsx src/App.worldVisibility.integration.test.tsx`;
- full `npm test`. Record the first run and any rerun separately, and name any failure outside these files;
- `npm run lint`, `npx tsc -b`, `npm run build`;
- from the repository root: `uv run python scripts/check_documentation.py` and `git diff --check`.

Backend checks are not required; a backend change is a stop condition.

### 7.2 C06 checkpoint merge requirements (not S01's verdict)

The C06 PR merges only when all of these hold:
1. S01 (C06's only slice) has passed independent review.
2. F1–F14 pass on the integration head, with one full portal run.
3. CI passes on the exact integration head.

None of §7.3 is a merge gate.

### 7.3 Separate events (after the merge; not merge gates)

- AX evidence ([ax](work-register.md#ax)): browse at 320 CSS px and at actual 200% and 400% browser zoom, keyboard use of the checkbox, the announcement.
- Final [p15-integration](work-register.md#p15-integration), human review and owner acceptance (`p15-owner`). Nothing in this plan grants them.

## 8. Authorization, disclosure, concurrency and focus rules

- **Server-authoritative.** The list is exactly what `GET /worlds` returns for the caller plus the bootstrap's campaigns. Each entry's link and "View only" marker come from its own server-computed capabilities (unchanged `buildWorldChoices`). The checkbox only chooses which server list to read.
- **Disclosure.** `status=all` returns only worlds the caller already holds a role or use grant on; nothing new becomes visible. No identifier is displayed.
- **Concurrency and late answers.** One read per state, keyed by path; an older answer never replaces a newer state (F9).
- **Account change.** The session's bootstrap supplies the campaigns; a different signed-in account re-renders from its own bootstrap and its own list read (existing session boundary).
- **Focus.** Arrival focus once per path; a filter change keeps focus on the checkbox. The inherited `usePageArrival` uncertainty ([C02 readiness §4](p15-c02-checkpoint-readiness.md#4-the-provisional-cancel-focus-issue-against-the-checkpoint-criteria)) stays with §7.3.
- **Announcements.** One polite announcement per settled filter change, through the existing announcer.

## 9. Intermediate states

T01 is a single commit. Until it lands, the current behavior (§2.1) is shipped; no intermediate state is merged.

## 10. Decisions

**No owner decision is required.** Routine choices made here:

- **R-1 (checkbox, not a third radio).** R09 names a checkbox. An archived-only view is dropped; archived worlds remain identifiable by their badge.
- **R-2 (`status=all`, one request).** The server's union is ordered and paged as one list; two requests merged on the client would mis-order and mis-count the first 100.
- **R-3 (`?archived=1`, legacy `status=archived` read as checked).** A short boolean parameter; old addresses open a superset rather than an error.
- **R-4 (REPLACE).** Matches the existing page and C04's list search; Back leaves the page instead of stepping through filter states.
- **R-5 (`keyBy: "path"`).** The hook's documented option for pages whose own controls change only the query.
- **R-6 (announce the count once).** The list changes without a page change; one polite sentence states the result.

## 11. Handoffs

### 11.1 Sonnet implementation instructions

1. Confirm the baseline (the commit adding this plan) is HEAD and `origin/phase15/completion`, with a clean worktree.
2. Read §2 to §9. Write the "(fails at baseline)" cases first, run them on the baseline, and record each failure (test name and assertion). Run the "(guard)" cases at baseline too and record that they pass.
3. Implement §3.2 in the files of §4 only. Keep §2.4.
4. Run §7.1. Run M1–M6, record each probe's failing case, and revert every probe (restore exact bytes; `git restore` rewrites LF working files as CRLF under `core.autocrlf=true`, so compare hashes).
5. **Stop and report instead of continuing if:**
   - a backend, API or authorization change seems necessary;
   - a change to `buildWorldChoices`, `contextOptions`, the Infobox, the campaign setup picker, `useAuthoringResource` or `usePageArrival` seems necessary;
   - an existing test would need a changed expectation other than those §4 allows;
   - a "(fails at baseline)" case cannot be made to fail at baseline.
6. Commit with the §5 subject, push, and record in §11.3 and the register's T01 row: the SHA, the test-first failures and guard results, the focused and full runs (first run and rerun separately), the probes and the CI position ("pending checkpoint PR"). Commit and push the records.
7. Do not open, mark ready or merge a PR. Do not run browser or AX checks, start copy-ui, preview or other consumers, or record any acceptance.

### 11.2 Independent review boundary (Luna)

- **T01 = combined S01 = C06:** from this plan's commit to the T01 implementation commit, plus its docs-only records commit.
- Review against §2.4, §3, §6 and §8; re-run §7.1 and M1–M6.
- A pass is a slice verdict only; §7.2 and §7.3 remain.

### 11.3 Implementation record

Pending (Sonnet).

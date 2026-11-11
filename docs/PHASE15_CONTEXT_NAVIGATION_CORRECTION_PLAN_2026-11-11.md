# Context-navigation correction plan (Infobox, timelines, World options) — 2026-11-11

**Status:** planning only; nothing here is implemented. The normative contract is
[UI_DESIGN.md §4.8.12](UI_DESIGN.md#4812-context-navigation-correction-read-gates-destinations-and-meaningful-choice-approved-2026-11-11-implementation-pending).
This plan adds the findings, implementation boundaries, tests, and handoff prompts; it
does not restate that contract.

- **Baseline:** `phase15/completion` at `00c463f284f725b74d696452c59b0862fae7b679`. PR #68
  stays draft and unmerged. A4 is accepted and CI-green, and this correction does not
  reopen it. A5–A7 are not started by this work.
- **Workflow:** planning by Claude Code Opus 5.5; implementation by Claude Code Sonnet 5.5
  Medium (§8); independent review by Codex Luna Medium (§9).
- **Inputs:** Astra's investigation (summarised in §1), ADR 0019/0020, UI_DESIGN §4,
  §4.1, §4.8.2–§4.8.4, the [issue rubric](ISSUE_GRADING_RUBRIC.md), and the code traced at
  the baseline (file references below).

## 1. Scope and decisions

**Established by the investigation and confirmed by tracing:**

- `worldAccess(...) === "edit"` means `world.manage` (`portal/src/utils/worldAccess.ts`).
- Reading a world and its timelines requires `world.view`. The server's
  `GET /worlds/{w}/timelines/{t}` is `require_world_capability(WORLD_VIEW)`
  (`src/dnd_ai/api/timelines.py`), and its actions are filtered by capability
  (`src/dnd_ai/queries/timeline_detail.py`). Timeline mutations require `timeline.manage`.
- Campaign membership does not grant `world.view` (ADR 0019 decision 2).
- World choices merge explicit world access with campaign-derived destinations
  (`buildWorldChoices`). Campaign choices come from the bootstrap and are filtered by the
  active world and timeline.
- Timeline selection is personal navigation, not a campaign-setting mutation.
- A newer world-detail refusal can leave an obsolete explicit World option selectable.
- No backend authorization bypass was demonstrated. This plan's tracing found none either.

**Owner decisions (approved 2026-11-11), recorded in UI_DESIGN §4.8.12 and the ADR 0019
amendment:** CN-1, campaign-only Timeline navigation; CN-2, the meaningful-choice rule.

**Approved scope:**

- Timeline read-navigation gates in the Infobox (`HierarchyContextPanel`), the timeline
  tree on the Timelines collection and the read-only World overview, and the sidebar.
- Management controls stay under their existing mutation permissions.
- Reconcile stale World options against newer authoritative results, and keep
  independently valid campaign-derived destinations.
- Tell authoritative refusal apart from transient failure.
- Explain disabled, loading, empty, and error states, with accessible associations and
  read-only retries.
- Keep route precedence, departure guards, compatible selections, history restoration,
  and stale-response protection.

**Not approved:** backend authorization expansion, migrations, new routes (including any
campaign-scoped timeline detail page), changes to the selection store's semantics, or
World-level pagination/search. Tracing found no case that needs these. CN-1's
destinations are all existing routes the caller is already authorized for.

**Deferred:** World-level pagination beyond the first 100 explicit worlds (finding F5;
[backlog](BACKLOG.md#8-other-explicit-follow-ups)).

## 2. Findings and grading

Each finding is scored with the [rubric](ISSUE_GRADING_RUBRIC.md). Environment: local
development portal and API. The caller is an authenticated user on a normal portal path.
No data is at risk: these are presentation and navigation defects, and the server refuses
every unauthorized read.

| ID | Finding (evidence at baseline) | Track | Exp | Imp | Trig | Det | Blast | Score / severity | Disposition |
|---|---|---|---:|---:|---:|---:|---:|---|---|
| F1 | Timeline read navigation is gated on `world.manage`, not `world.view`. The gate appears in the Infobox `timelineListReady` (`HierarchyContextPanel.tsx:152`), the Timelines tree `linked` (`TimelinesPage.tsx:80`), the read-only overview tree `linked={false}` (`WorldOverviewPage.tsx:155`), and the sidebar Timeline overview `canAuthorWorld` (`PortalSidebar.tsx:348`, `WorldsNavGroup.tsx:156`). Viewers, Readers, Reviewers, Editors, and Owners without system GM cannot open timeline overviews they may read; Editors and GM-less Owners cannot reach the timeline-management pages the server allows them. | application | 2 normal path for every non-`world.manage` world role | 1 a supported read and management path is unreachable from navigation | 2 routine | 0 visible | 0 one user | **5 Medium** | Blocking for this correction |
| F2 | A campaign-only caller has no Timeline navigation: the level shows only the current timeline, disabled (`HierarchyContextPanel.tsx:152–168`). CN-1 defines the missing behavior. | design | 2 | 1 | 2 | 0 | 0 | **5 Medium** | Blocking for this correction (owner decision CN-1) |
| F3 | The `GET /worlds` list is read once per panel mount and never reconciled. A later `GET /worlds/{w}` refusal leaves W's explicit option selectable, and it leads to a non-disclosing "not available" page. | application | 1 needs revocation mid-session | 1 bounded failing navigation, no disclosure | 1 | 0 visible on use | 0 | **3 Low** | In scope (owner-approved). It does not block on severity, but the scoped acceptance includes it |
| F4 | Selectors are enabled whenever any option exists, including a sole already-selected value, and they give no reason when disabled. A failed `GET /worlds` looks like "no worlds" (only campaign-derived entries) and offers no retry. Loading is indistinguishable from empty. | application | 2 | 1 | 2 | 1 silent/misleading on list failure | 0 | **6 Medium** | Blocking for this correction (owner decision CN-2) |
| F5 | The Infobox requests `limit=100` and ignores `next_cursor`, so explicit worlds after the first 100 are not offered (`HierarchyContextPanel.tsx:106`). | application | 1 needs >100 explicit worlds | 1 | 1 | 0 the All Worlds page paginates; the current world is shown | 0 | **3 Low** | Deferred by the owner; backlog follow-up |
| I1 | No backend authorization bypass. A campaign-only caller gets 404 on world and timeline routes (`tests/database/test_world_visibility.py::test_campaign_player_gets_no_world_entry_or_world_route`). | informational | – | – | – | – | – | 0 | No action |

F1 and F4 share one cause: no shared option model or explicit read predicate. One
correction addresses both, so the plan does not treat them as separate gates. Existing
tests encode F1 as intended behavior and must be inverted rather than deleted:
`HierarchyContextPanel.test.tsx` "…and no timeline choice for a view-only world" and
`PortalSidebar.test.tsx` "gives a view-only world its read-only overview but no
timeline-authoring destination".

## 3. Implementation design (mechanics only; behavior is in UI_DESIGN §4.8.12)

### 3.1 One pure option model

Add `portal/src/navigation/contextOptions.ts`. It must stay pure: no React, router,
network, or store access. The panel and its tests consume it, and the sidebar and pages
use its predicates.

```ts
export function canReadWorld(capabilities: readonly string[] | undefined): boolean  // "world.view"

export type LevelDestination =
  | { kind: "route"; to: string; root: "world" | "campaign"; note: SelectionChange }
  | { kind: "chooseCampaign"; timelineId: string; campaignIds: readonly string[] }

export interface LevelOption { id: string; label: string; destination: LevelDestination }

export type LevelReason =
  | "select_world_first" | "select_timeline_first" | "select_campaign_first"
  | "loading_worlds" | "loading_timelines" | "worlds_failed" | "timelines_failed"
  | "no_world" | "no_timeline" | "no_campaign"
  | "no_other_world" | "no_other_timeline" | "no_other_campaign" | "timeline_gone"

export interface LevelModel {
  options: readonly LevelOption[]                 // real destinations only
  displayOnly: { id: string; label: string } | null  // shown as the value, never actionable
  selectedId: string | null
  enabled: boolean                                // CN-2
  reason: LevelReason | null                      // set whenever disabled, loading or failed
  retry: "worlds" | "world" | null                // the one read "Try again" repeats
}

export function worldLevel(input: WorldLevelInput): LevelModel
export function timelineLevel(input: TimelineLevelInput): LevelModel
export function campaignLevel(input: CampaignLevelInput): LevelModel
```

- `worldLevel` calls `buildWorldChoices` (unchanged and still used by All Worlds). It
  drops explicit entries that `explicitWorldValid(worldId, listStartedSeq, evidence)`
  rejects. The withdrawn world may still be added back as campaign-derived, so the
  campaign merge must run after the filter. Do this either with a `withdrawn` set
  parameter on `buildWorldChoices` or by filtering `worlds` before the call. Pick one and
  keep All Worlds' behavior identical when the set is empty.
- `timelineLevel` takes the active world's read state:
  `"readable" | "refused" | "failed" | "pending" | "not_requested"`.
  - `readable` gives world destinations.
  - `refused`, `failed`, and `not_requested` give campaign-derived destinations. `failed`
    also sets `reason: "timelines_failed"` and `retry: "world"`.
  - `pending` disables the level with `loading_timelines`.
- Destinations reuse `scopeRequest` (`navigation/selectionTransitions.ts`). There is
  exactly one place where the selection note and task root are chosen.
- Reason strings live in `components/navigationReasons.ts` next to the existing
  neutral reasons. Use the UI_DESIGN §4.8.12 wording exactly.

### 3.2 Ordering evidence for World reconciliation

- `useAuthoringResource` gains an additive result field, `startedSeq: number | null`.
  It is the value of a module-level monotonic counter taken when the read behind the
  current `state` started (a first load or a refetch); it is `null` while loading.
  Existing callers ignore it.
- `WorkspaceHierarchyProvider` records an entry each time its world read settles:
  `{ worldId → { verdict: "readable" | "refused", startedSeq } }`.
  - `ready` records `readable`. `unavailable` and `denied` record `refused`.
  - `error` records nothing.
  - An entry replaces an existing one only when its `startedSeq` is greater.
  - The map is discarded when `selectionOwner(bootstrap)` changes.
- The provider exposes the map (as an immutable snapshot) and the active world's read
  state for `timelineLevel`. On a campaign route where the bootstrap's
  `world_capabilities` lacks `world.view`, the read is still not sent
  (`not_requested`; unchanged behavior).
- The panel keeps its own list read and passes `worlds.startedSeq` as `listStartedSeq`.
  The list is positive evidence only.
- Timeline-detail refusals on `TimelinePage` are not world evidence, because a missing
  timeline is not a world refusal. The provider's own refetch on pathname change learns
  about a world refusal.

### 3.3 Components

- `HierarchyContextPanel`: render from the three `LevelModel`s. Each select gets its
  reason element and `aria-describedby` (via `useId`), and a **Try again** button when
  `retry` is set. `onSelect` looks the id up in `options` only, so a display-only id can
  never navigate. A `chooseCampaign` destination opens the chooser.
- New `components/TimelineCampaignChooser.tsx`, implementing the UI_DESIGN chooser
  bullet:
  - Its state is `{ timelineId, locationKey } | null` in the panel, discarded when
    `location.key` changes.
  - Its campaigns are recomputed from the current bootstrap on each render.
  - Its links use `<Link to state>` with the `scopeRequest` state, like the Navbar
    campaign menu.
  - Its announcement uses the announcer's owned-message API
    (`components/authoring/announcer.ts`), withdrawn on close.
- Retry focus: generalize `useRetryFocus` with an optional target resolver (the level's
  select if enabled, otherwise its reason element with `tabIndex={-1}`). Keep the
  existing default for current callers.
- `WorldsNavGroup` / `PortalSidebar`:
  - Replace the Timeline overview gate `canAuthorWorld` with a `canViewWorld`-based
    `canOpenTimeline`. Remove the `canAuthorWorld` prop if nothing else uses it (today
    only Timeline overview does).
  - Reason precedence: no world → existing reason; a world selected without known
    `world.view` → `NOT_AVAILABLE_FOR_ACCOUNT`; no confirmed timeline →
    `SELECT_TIMELINE_FIRST`.
- `TimelinesPage`: `linked` becomes `true` for any ready read (the read implies
  `world.view`). `WorldOverviewPage`'s read-only tree becomes linked. The management
  branch choice (`worldAccess === "edit"`) and every action gate are unchanged.
- `WorkspaceHierarchyContext`: correct the comment that says timeline navigation needs
  "edit".

## 4. Implementation boundaries and acceptance

Implement three commits in order on `phase15/completion`, staging each by explicit
paths.

| Slice | Content | Acceptance |
|---|---|---|
| **CNC-1 read gates** | §3.3 sidebar, `TimelinesPage`, `WorldOverviewPage`, and the Infobox Timeline gate switched to `world.view` (still world-derived only). Invert the two F1 tests. Add one database test (§5.3). | Viewer, Reader, Reviewer, Editor, and GM-less Owner can reach Timeline overview from the Infobox, the sidebar, and both trees. Management controls are unchanged per role. A campaign-only caller has no link to any `/worlds/...` timeline route. |
| **CNC-2 option model, reasons, reconciliation** | §3.1, §3.2, the reasons/retry UI, the CN-2 rule for World/Timeline/Campaign, and the Character "Select a campaign first" reason. | Every row of the UI_DESIGN state and reason tables is covered by a test. Stale explicit World options are reconciled by start order. Retry repeats only the failed read. |
| **CNC-3 campaign-only timelines and chooser** | Campaign-derived timeline destinations and `TimelineCampaignChooser`. | Every CN-1 rule, the guard interplay (Stay/Leave), dismissal, access change while open, and the no-world-route-leak check. |

**May change:**

- `portal/src/navigation/contextOptions.ts` (new) and its test
- `navigation/selectionTransitions.ts` (only to reuse `scopeRequest`; no semantic change)
- `hooks/useAuthoringResource.ts` (additive `startedSeq`)
- `hooks/useRetryFocus.ts` (additive target resolver)
- `context/WorkspaceHierarchyProvider.tsx` and `WorkspaceHierarchyContext.ts`
- `components/HierarchyContextPanel.tsx`, `TimelineCampaignChooser.tsx` (new),
  `navigationReasons.ts`, `WorldsNavGroup.tsx`, `PortalSidebar.tsx`
- `pages/TimelinesPage.tsx`, `pages/WorldOverviewPage.tsx` (the read-only tree's
  `linked` only)
- `utils/worldAccess.ts` (only to add the withdrawn-set parameter or a predicate; All
  Worlds' output must be unchanged)
- Panel CSS in the existing stylesheet that holds `.campaign-context-panel`, using
  theme tokens only
- Tests beside each file
- One database test file
- Documentation per §4.1

**Must not change:**

- Any `src/dnd_ai/**` code, migrations, API response types, routes in `App.tsx`, or the
  route metadata count
- `selectedContextStore`, `SelectedContextReconciler`, `CampaignLayout` adoption,
  `entryStamp`, `replaceOwnEntry`, or `SelectionArrivalProvider` semantics
- Departure-guard code, and the Character perspective selector's behavior
- `WorldsPage` behavior
- `docs/README.md`'s pre-existing uncommitted line, and the untracked planning documents

If one of these appears necessary, stop and report the specific gap.

### 4.1 Documentation fold-in (part of CNC-3)

- Fold UI_DESIGN §4.8.12 into the sentences it supersedes (§4 "One World group", §4.1
  `HierarchyContextPanel`, the §4.8.4 timeline row). Remove the "approved correction
  pending implementation" markers and §4.8.12's status line, and keep §4.8.12 as the
  implemented contract with its manual-check pointer.
- Update the ADR 0019 amendment and the style-guide bullet from "implementation
  pending" to the implementing SHA.
- Add one dated row to the [acceptance ledger](PHASE14_15_ACCEPTANCE_LEDGER.md):
  implemented and awaiting independent review, not owner-accepted, and with the real
  browser checks of §6 pending.

## 5. Automated verification

These tests use jsdom and the existing `server.on(...)` fake. Where ordering matters,
use deferred responses so the test controls when each read answers. Every test named
below must fail on the baseline for the reason stated. Do not count a test that passes
on the baseline toward closing a finding.

### 5.1 Pure model (`navigation/contextOptions.test.ts`)

1. **CN-2 matrix, for each level:**
   - zero options: disabled with the "no …" reason;
   - one option already selected: disabled with "no other …";
   - one option with nothing selected: enabled;
   - several options with one selected: enabled;
   - a display-only current plus zero real options: disabled (the display-only value
     is not counted);
   - loading: disabled with the loading reason;
   - transient failure with and without campaign-derived options: enabled/disabled per
     options, always with the failed reason and `retry`.
2. **Timeline destinations:**
   - `readable`: world routes, all world timelines in server order, no chooser.
   - `refused`, `not_requested`, and `failed`: campaign-derived destinations, with
     distinct timelines sorted by name then id. A timeline with one campaign opens
     `/app/{c}/home` with root `campaign` and a `campaign` note. A timeline with two
     campaigns gives `chooseCampaign` with bootstrap order. A campaign without a
     timeline is skipped. A null name reads "Unnamed timeline".
   - Mixed access (`readable` plus campaigns): one option per timeline, every one a
     world route.
3. **World reconciliation:**
   - list(seq 1) lists W, then refusal(seq 2): W's explicit entry is withdrawn.
   - The same, with a bootstrap campaign on W: W is campaign-derived to `/app/{c}/world`.
   - refusal(seq 1) answered after list(seq 2): W is kept (start order, not arrival
     order).
   - refusal(2) then readable(3): W is restored.
   - refusal(2) then a newer list(3): W is restored.
   - A transient error records nothing.
   - A readable read of an unlisted world adds no entry.
   - An empty withdrawn set leaves `buildWorldChoices` output identical (All Worlds is
     unchanged).

### 5.2 Components and integration

**Callers by role:**

- `world_viewer` on `/worlds/W`: Timeline is enabled. Choosing T pushes
  `/worlds/W/timelines/T` with a `timeline` note. This inverts the existing F1 test.
- Editor (`world.view` + `timeline.manage`) and Owner without system GM (role
  `world_owner`, capabilities without `world.manage`): the same, and Timeline overview
  shows Edit / Create branch only when the fixture's `available_actions` carries them.
- Owner with GM: unchanged behavior.

**Campaign-only caller** (bootstrap `world_capabilities: []`, campaigns C1/C2 on T1 and
C3 on T2), on `/app/C1/home`:

- `GET /worlds/W` is never sent (existing assertion kept).
- Timeline shows T1 selected, T2 actionable, and is enabled.
- Choosing T2 pushes `/app/C3/home`. The task root is `campaign` and the note level is
  `campaign`.
- From `/app/C3/home`, choosing T1 opens the chooser listing C1 and C2 in bootstrap
  order, with no navigation, no history entry, and the select still showing T2.
- Cancel and Escape close the chooser with focus on the select. Re-choosing the
  committed timeline closes it.
- No anchor anywhere in the document has an `href` starting `/worlds/W/timelines/`. Run
  this check in `App.worldVisibility.integration.test.tsx` across the panel, the
  sidebar, and the page.

**Chooser and the departure guard:** on a dirty page (an existing hold fixture), a
chooser link raises the existing question.

- Stay: same location and entry count, the chooser still open, focus on that link (as
  far as the jsdom dialog model shows).
- Leave: arrives at `/app/C2/home` and announces "Campaign changed to C2."

**Access change while the chooser is open** (bootstrap refresh):

- C2 removed: C1 is listed alone and nothing navigates.
- C1 and C2 removed: the chooser closes, the reason is "That timeline is no longer
  available.", and focus moves to the select.
- The world becomes readable after a retry: the chooser closes.

**Mixed caller on a campaign route:**

- The world read succeeds: world destinations.
- The read returns 403/404: campaign-derived destinations.
- The read returns 500: campaign-derived destinations, the failed reason, and Try again.
  Try again sends exactly one more `GET /worlds/W` and no other request, and on success
  the destinations become world routes.

**Singletons:**

- One world, selected: disabled, with accessible description "No other world
  available".
- One world on `/worlds` with nothing selected: enabled.
- Zero worlds: "No world available".
- The equivalent cases for Timeline (`/worlds/W` with one timeline: enabled; on its
  timeline route: disabled) and Campaign.
- Reasons are checked with `toHaveAccessibleDescription`.

**World list states:**

- Loading: disabled with "Loading worlds…". Campaign-derived entries also wait.
- Failure: the reason plus Try again, which re-requests only `GET /worlds?status=all…`.
  Campaign-derived entries stay offered.

**Stale World entry:**

- The list lists W, then navigation to `/worlds/W` gets 404: the World options no longer
  contain W, or W becomes campaign-derived when C is on W.
- A delayed refusal for W1 that started before a later list read is ignored.
- Navigating W1 → W2 aborts W1's read, and the abort records nothing.

**Rapid switching:** choose W2, then W3 before W2's read answers. Only W3 commits, and
W2's late answer changes neither options nor selection.

**History:** reuse `selectedContext.history.integration.test.tsx`.

- Back to an entry whose explicit world is now refused does not revive the World option.
- A compatible retained campaign survives a timeline change on the same timeline, and
  an incompatible one is cleared on arrival (§4.8.2 unchanged).
- A refresh does not restore the chooser.

**Sidebar (`PortalSidebar.test.tsx`):**

- Timeline overview is a link for viewer, Editor, and GM-less Owner (this inverts the
  existing F1 test).
- For a campaign-only caller it is disabled with "Not available for your account".
- With `world.view` and no confirmed timeline: "Select a timeline first".

**Pages:**

- `TimelinesPage` and the read-only `WorldOverviewPage` link each timeline for a viewer
  and still show no New timeline / Edit / Archive for a viewer.
- `timelinePages.test.tsx` viewer case unchanged.

### 5.3 Backend (one test, no code change)

`tests/database/test_world_visibility.py` already covers a viewer reading timeline
detail with no actions and a campaign player getting 404. Add one parametrized test:

- A world Editor and a world Owner without system GM each get 200 from
  `GET /worlds/{w}/timelines/{t}`.
- Both are offered `update` and `create_branch` (`timeline.manage`).
- The GM-less Owner is not offered `create_campaign` (`campaign.create` is withheld
  without system GM).

This pins the server contract the portal now links to. If an equivalent test already
exists, cite it instead of adding one.

### 5.4 Checks to run

- **Portal:** in `portal/`, run `npm run lint`, `npm run build` (includes `tsc -b`),
  and `npm test` (focused `npx vitest run <files>` while iterating), and report counts.
- **Backend:** `uv run pytest tests/database/test_world_visibility.py`,
  `ruff format --check`, `ruff check`, `mypy src`, and `git diff --check`.
- **Full suite:** not required for a portal-only change with one added database test.
  CI on the pushed head remains the merge gate. Report anything not run as not run.

## 6. Real-browser acceptance checks

These checks are pending and must not be claimed from jsdom. Run them on the
[manual-validation stack](PHASE14_15_ACCEPTANCE_ENVIRONMENT.md) with throwaway
accounts, never on the owner's own campaign.

1. **Keyboard:**
   - Tab and Shift+Tab order through the World, Timeline, Campaign, and Character
     levels, each reason's Try again, and the chooser.
   - Arrow-key browsing of a closed Timeline select in Chrome and Edge on Windows
     (change can fire per step). Record whether a one-campaign timeline navigates
     mid-browse and whether the chooser flickers. The current behavior for every
     Infobox select is unchanged, and this records it.
   - Enter and Space on chooser links and Cancel. Escape inside the chooser.
2. **Focus:**
   - Opening the chooser leaves focus on the select.
   - Cancel and Escape return focus to the select.
   - Stay returns focus to the activated chooser link (native `<dialog>`).
   - Leave lands on the destination `h1`.
   - A successful Try again moves focus to the select or the reason.
   - Focus visibility on every new control.
3. **Chooser dismissal:**
   - A pointer-down outside does not close it.
   - Navbar navigation and Back close it.
   - A reload does not restore it.
4. **Stay and Leave** with a dirty form and with an open picker hold.
5. **Announcements** (NVDA + Chrome or Firefox, and VoiceOver + Safari):
   - the chooser instruction, spoken once and withdrawn on close;
   - "Campaign changed to ‹name›." after Leave;
   - disabled selects read with their reasons;
   - the order of focus change and polite message.
6. **Context restoration:**
   - Reload and Back/Forward across a campaign-derived timeline switch.
   - Two-tab revocation while the chooser is open, and while an explicit World option
     is shown.
7. **Layout:** 320 px and 400% zoom for the reasons and the chooser (wrapping, no
   horizontal scroll), and light and dark themes.

## 7. Open questions

### 7.1 Policy questions (owner)

- **Q1 — Campaign-derived *World* entries.** ADR 0019 decision 3 opens a
  campaign-derived world through the route campaign, or else the first campaign in
  bootstrap order. CN-1's "never arbitrarily pick a campaign" is scoped to timelines, so
  this plan leaves the World rule unchanged. Should a World entry reachable through
  several campaigns (none of them the route campaign) also require an explicit choice?
  **Default if unanswered:** unchanged.
- **Q2 — Mixed-access timeline destination.** The plan applies "explicit authority wins"
  (the ADR 0019 precedent): a caller with `world.view` opens the world timeline overview
  even when they also have campaigns on it. The world route's Campaign level then offers
  those campaigns. This is a design choice the owner may override, and it is not open
  unless they do.

### 7.2 Routine technical choices (implementer may adjust within the contract)

- The note level for a campaign-derived timeline choice is `campaign`, so the
  announcement names the campaign.
- Chooser entries are links rather than buttons, matching the Navbar campaign menu.
- The start-order counter is module-level in `useAuthoringResource`.
- The retry focus target.
- CSS class names.
- Whether `buildWorldChoices` takes a withdrawn set or receives pre-filtered worlds.

## 8. Implementation prompt (Claude Code Sonnet 5.5, Medium)

> You are implementing the context-navigation correction on branch `phase15/completion`
> in `c:\Users\nemes\dnd_ai`. Planning commit: see the commit that added
> `docs/PHASE15_CONTEXT_NAVIGATION_CORRECTION_PLAN_2026-11-11.md`. Its parent is
> `00c463f`.
>
> **Read first, in this order:** `CLAUDE.md`, then
> `docs/PHASE15_CONTEXT_NAVIGATION_CORRECTION_PLAN_2026-11-11.md` (all of it), then
> `docs/UI_DESIGN.md` §4.8.12 (the contract), then §4.8.2 and §4.8.4 (selection
> ownership and Infobox departures, which you must not change). Then read the files in
> plan §4 "May change" and their existing tests.
>
> **Goal:** implement slices CNC-1, CNC-2, and CNC-3 as three commits, in order. Each
> slice's tests go in the same commit as its code.
>
> **Hard rules:**
> - Do not touch `src/dnd_ai/**` (except the one new database test in plan §5.3),
>   migrations, routes, the selection store, the reconciler, `CampaignLayout`
>   adoption, entry stamps, or the departure guard. If you believe one must change,
>   stop and report the gap with evidence.
> - Timeline *read* navigation uses `world.view`. Mutation controls keep their existing
>   server-provided gates.
> - Never build a `/worlds/...` link for a caller without confirmed `world.view`. Never
>   pick a campaign for the person. Never auto-select, and never add a "clear" option.
> - A display-only option is never actionable. `onSelect` resolves ids only through
>   the model's `options`.
> - Reconciliation compares read **start** order. Transient errors are not evidence.
>   Reconciliation never writes the selection store.
> - Retry buttons repeat exactly the failed read. Assert request counts in tests.
> - Use the reason strings from UI_DESIGN §4.8.12 verbatim. They carry no names, ids, or
>   counts.
> - Opening the chooser changes nothing but local panel state. Chooser links use the
>   same `scopeRequest` as the Campaign select.
> - Existing tests that encode the old `world.manage` gate (plan §2) are inverted, not
>   deleted. Every new test must fail on the baseline for the stated reason; check this
>   by running it against the baseline file versions before finalizing, and say how you
>   checked.
>
> **Docs:** in CNC-3, do the plan §4.1 fold-in and add the ledger row. Do not claim any
> plan §6 real-browser check.
>
> **Git:**
> - Stage only explicit paths (`git add <path>…`). Never `git add -A`, `.`, or `-u`.
> - `docs/README.md` has a pre-existing uncommitted line that is not yours; leave it
>   unstaged. Leave the untracked `docs/PHASE14_15_*` and `docs/PHASE15_POST_*` planning
>   files alone.
> - Do not push, merge, or change PR #68. Do not start P03-A A5–A7.
> - End each commit message with the attribution line from your session instructions.
>
> **Report:** the three SHAs; per slice, the files changed and tests added or inverted;
> the exact commands run with pass/fail counts; anything not run; any deviation from the
> plan with its reason; and the real-browser checks that remain pending.

## 9. Review guidance (Codex Luna, Medium)

Review the three CNC commits against this plan and UI_DESIGN §4.8.12, and grade every
finding with the [rubric](ISSUE_GRADING_RUBRIC.md). Use **CHANGES REQUIRED** only for a
demonstrated defect or design gap against the scoped acceptance.

**Check, in priority order:**

1. **No authority leak.**
   - No path builds a `/worlds/{w}` or `/worlds/{w}/timelines/{t}` link or navigation
     for a caller without confirmed `world.view`. Check the panel, chooser, sidebar,
     trees, and arrival focus.
   - The campaign-only world read is still not sent when the bootstrap says no
     `world.view`.
2. **Read and mutation gates split correctly.**
   - Timeline overview and trees follow `world.view` everywhere.
   - No management control appeared for Viewer/Reader/Reviewer.
   - Editor and GM-less Owner see exactly the actions the server offers.
3. **CN-1 exactly.**
   - One campaign navigates; several open the chooser.
   - Nothing is ever picked, auto-selected, or remembered.
   - Siblings appear only through authorized campaigns.
   - Campaign-level filtering is unchanged.
4. **CN-2 exactly.** Check the counting rule, that display-only options are inert, the
   reasons and their `aria-describedby`, and that no clear action exists.
5. **Reconciliation.**
   - Start-order comparison, not arrival order.
   - Aborted reads ignored, and transient errors not evidence.
   - Campaign-derived entries survive a refusal.
   - Evidence is reset on owner change.
   - No selection-store writes.
   - Try out a delayed-response interleaving of your own.
6. **Guard and history.**
   - Opening the chooser causes no guard question, entry, or task.
   - Stay preserves everything.
   - The §4.8.2 and §4.8.4 behaviors and their tests are untouched, apart from the
     inverted F1 tests.
7. **Retry** re-sends only the failed GET. Check request counts, and that there is no
   navigation, mutation, or bootstrap reload.
8. **Tests are meaningful.** They would fail on `00c463f` for the stated reason. Jsdom
   claims stay within jsdom, and no real-browser outcome is claimed.
9. **Scope.** No backend, route, migration, or store changes, and staging used explicit
   paths. `docs/README.md`'s unrelated line and the untracked documents are untouched.

**Do not flag as defects of this correction:**

- the deferred 100-world limit (F5);
- the unchanged ADR 0019 World-entry campaign rule (Q1);
- arrow-key `change` behavior of native selects (a recorded manual check);
- the absence of real-browser evidence (pending by design).

You may flag any of these as informational if the implementation makes them worse.

**Report:**

- the verdict;
- findings with rubric fields;
- the independent commands you ran and their results, kept separate from the
  implementer's reported evidence;
- the remaining manual checks.

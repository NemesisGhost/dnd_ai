# D/P15-C03-S02 implementation plan: confirm a startup preference from a later bootstrap

**Status:** Opus plan prepared 2026-11-22. **Ready for Sonnet.** No owner decision blocks the task. Section 10 lists the routine choices made here; none changes a product policy, an API contract or authorization.

**Register rows:**
- slice [D/P15-C03-S02](work-register.md#p15-c03-s02);
- task [T01](work-register.md#p15-c03-s02-t01);
- parent checkpoint [D/P15-C03](work-register.md#p15-c03).

**Plan-entry head:** `f20c1a7824341e88a48b7214b926980ddd29308d` ("docs: record P15-C03-S01 R1/R2 resolution and slice PASS WITH VERIFICATION LIMITS").
- Its parent is the reviewed S01 records head `4b4a48da931c7f3abc082a7afa8819ee9b6c2f9f`, which equalled `origin/phase15/completion` after `git fetch origin`. The worktree was clean apart from the S01 review records, which `f20c1a7` commits.
- S01 is **reviewed; PASS WITH VERIFICATION LIMITS** ([S01 plan §11.7](p15-c03-s01-knowledge-read-recovery-plan.md#117-independent-re-review-of-r1r2-codex-2026-11-22)). S02 does not depend on it; the two slices touch disjoint files.
- CI: no run exists for the C03 commits. CI runs on pull requests, and the C03 checkpoint PR has not been opened.

Sonnet's implementation baseline is the commit that adds this plan, a child of `f20c1a7`. The handoff prompt names it.

**How each statement was established:**
- by reading source, tests and documents at the plan-entry head;
- by temporary plan-entry reproductions (§2.2). They were two Vitest files, written into `portal/src/` only for the run and deleted afterwards; they reused the fixtures of `CampaignStartupForm.test.tsx` and `App.settingsSharedSession.test.tsx`. No repository file was changed by them.

**Governing sources:**
- [portal behavior §4.7](../reference/portal-behavior.md#47-settings-and-campaign-startup-preferences): the Campaign startup form, its save outcomes, the bootstrap contract and the authorization boundaries for stored campaign IDs.
- [portal behavior §4.2](../reference/portal-behavior.md#42-root-authentication-landing-and-deep-links): post-login landing precedence, computed by the server into `startup_campaign_id`.
- [portal behavior §5.11](../reference/portal-behavior.md#511-authoring-patterns-phase-14): one meaningful announcement, retry focus (`useRetryFocus`), newer drafts survive.
- [R05](work-register.md#r05--save-error-and-recovery-consistency): "Clear the preference notice only from matching authoritative evidence for that save and user"; "stale callbacks cannot clear newer episodes".
- The register residual [Startup-preference stale notice](work-register.md#focused-follow-up-evidence-and-dispositions) row: "Clear only when authoritative matching evidence exists, preserving newer drafts and never repeating PUT."
- The register's [C03 criteria](work-register.md#criteria-p15-c03), [S02 criteria](work-register.md#criteria-p15-c03-s02) and [T01 criteria](work-register.md#criteria-p15-c03-s02-t01): "Cover newer drafts/saves, changed account and stale refresh. Only a matching read clears the notice. Check PUT count stays one."
- The B1-DEF7c record in the [acceptance ledger](acceptance-ledger.md) (2026-11-02): the reviewed `unconfirmed`-not-`denied` outcome and the `refresh` abort contract, both preserved.

## 1. Entry readiness

C03 is "Recover Knowledge saves and startup preferences accurately". Its entry criteria were confirmed at `6ce3cbe` (no checkpoint prerequisite). S02 has no slice-specific gate ("Checkpoint entry criteria; no additional slice-specific gate"), and T01 needs only this completed plan. S02 is independent of S01: neither slice reads the other's files.

**Verdict: eligible and ready for Sonnet.**

## 2. Verified current behavior

### 2.1 How a save is confirmed today

- `useSaveCampaignStartupPreference` (`portal/src/hooks/useSaveCampaignStartupPreference.ts`) sends one `PUT /auth/preferences/campaign-startup`, then calls `refresh(controller.signal)` from the session context.
  - `refresh` resolving `true` → `success`.
  - `false` (superseded, or the session ended) or a rejection → `unconfirmed`.
  - A rejected PUT → `unavailable` (404), `denied` (401/403) or `error`.
  - Unmount aborts the controller. The hook ignores everything afterwards (the reviewed B1-DEF7c contract).
- Once the hook reaches `unconfirmed`, nothing moves it on again. It never looks at the session state again.
- `CampaignStartupForm` (`portal/src/components/CampaignStartupForm.tsx`):
  - derives `baseline` from the `bootstrap` prop and keeps the user's unsaved `draft`;
  - drops the draft whenever the status is `success`;
  - calls `reset()` on **any** edit while the status is neither `idle` nor `pending`, which ends `unconfirmed` too;
  - in the `unconfirmed` notice, "Check my session" calls `onCheckSession`.
- `SettingsPage` passes the outlet context's `reload` as `onCheckSession`. `reload` sets the session state to `loading`. `AuthenticatedSessionBoundary` then renders "Loading portal" in place of the route, so the Settings page **unmounts**. If that read fails, the boundary renders "Portal unavailable".
- The shared bootstrap can also change while Settings stays mounted:
  - an argument-free `refresh()` from another owner;
  - the hook's own superseding read;
  - a later save's read-back.
  The idle-expiry check never publishes a bootstrap.
- `/home` (`LandingRedirect`) resolves from the current shared bootstrap's `startup_campaign_id`. A fresh sign-in reads a fresh bootstrap, so the server resolves the startup campaign.

### 2.2 Plan-entry reproduction results

Each scenario starts from a fixed-campaign save of Beta that the server confirms; the read-back then fails, so the form shows "Your preference was saved, but the latest settings could not be confirmed".

| # | Scenario | Observed |
|---|---|---|
| P1 | A later in-place bootstrap reports Beta as the preferred campaign | The notice stays; the polite status stays empty. |
| P2 | The user changes the radio choice | The notice and its Check my session button disappear, with no read at all. |
| P3 | The user presses Save again with Beta still chosen | Save is enabled; a second PUT is sent. This is user-initiated, and the existing App test "applies nothing and stays recoverable…" relies on it. **Not a deviation** (see R-4). |
| P4 | An in-place bootstrap for **another user** is published | The previous user's notice and draft (`b`) remain on screen. |
| P5 | Check my session | Calls `reload` (one call). |
| P6 | A newer draft (Alpha), then a bootstrap reporting Beta | The notice had already gone at the edit (P2); nothing announces Beta as confirmed. |
| P7 (App) | Same as P6 in the real App | After the newer draft, the notice and its only recovery control are gone. |
| P8 (App) | Check my session while `GET /auth/session` fails | The Settings page is replaced by "Portal unavailable". After Try again, Settings remounts with no notice and no announcement. |
| P9 (App) | Check my session while the session read succeeds | Settings remounts and shows Beta. The polite status is empty, so the confirmation is never announced, and focus falls to `body`. |

### 2.3 Deviations S02 repairs

| ID | Deviation | Evidence |
|---|---|---|
| DV-1 | A later authoritative bootstrap that matches the confirmed save does not clear the notice or confirm the save. | P1, P6 |
| DV-2 | Editing the draft ends the unconfirmed episode, and its recovery control, without any evidence. | P2, P7 |
| DV-3 | A bootstrap for a different account keeps the previous account's episode and draft on screen. | P4 |
| DV-4 | Check my session unmounts the page. A newer draft is lost, a failed check replaces Settings with "Portal unavailable", and success is never announced, with focus left on `body`. | P5, P8, P9 |

### 2.4 Reviewed behavior that must not regress

- A confirmed PUT whose read-back is not applied or fails is `unconfirmed`, never `denied` (B1-DEF7c).
- The PUT is never repeated to repair a read. No automatic or recovery path sends a PUT.
- Success is reported only after an authoritative bootstrap. Nothing local is treated as the saved value.
- The 404 path drops that campaign from the selector without reloading, and says it is no longer available.
- The 401/403 path says nothing was saved and offers Check my session. That path's `onCheckSession` (`reload`) is **unchanged**.
- Unmount aborts the in-flight PUT and read-back, and nothing is reported afterwards. The existing hook test "aborts an in-flight save and ignores its refresh on unmount" stays as written.
- Only campaigns in the current bootstrap are offered, and a raw ID is never shown. An unauthorized stored ID is never disclosed.
- The App tests in `App.settingsSharedSession.test.tsx` keep passing: `/home` uses the saved value in the same session, a remounted Settings page shows it, and an unauthenticated read-back redirects to sign-in.

## 3. Outcome, scope and exclusions

### 3.1 User outcome

After the server confirms a startup-preference save, the Settings page reports it as saved as soon as the shared session bootstrap for the same user shows that value. That evidence can come from the save's own read, from Check my session, or from any other later session read.
- Until then, the "saved, but could not be confirmed" notice and its Check my session control stay visible, even while the user edits.
- Check my session re-reads the session in place. The page, the user's newer draft and the notice survive a failed check.
- The confirmation is announced once. Focus lands on the saved choice when the person had used the check control.
- Nothing from one account's save is shown to another account.

### 3.2 In scope (T01)

1. **Episode ownership in the hook.** A confirmed PUT whose read-back was not applied creates an *outstanding episode* `{ userId, submitted }`:
   - `userId` is the bootstrap user at save time;
   - `submitted` is the value sent, a campaign ID or `null`.
   Each episode is a distinct object. Late callbacks from an episode that has ended are ignored.
2. **Reconciliation from the shared session state.** An outstanding episode is **confirmed** when the current session state is `authenticated` and both hold:
   - `bootstrap.user.user_id === episode.userId`;
   - `bootstrap.campaign_preferences.preferred_campaign_id === episode.submitted`, with `null` equal to `null`.
   This is the only way an episode ends as confirmed (see R-1 for why no read-ordering ticket is needed).
3. **What ends an episode:**
   - confirmation, as in item 2;
   - a newer save whose PUT is **confirmed** (204), after which that newer save's own outcome governs;
   - a change of account;
   - unmount.
   Nothing else ends it: not an edit, not `reset()`, not a non-matching bootstrap, not a rejected newer PUT, and not a failed or superseded check.
4. **Check my session in place, for the unconfirmed notice only.**
   - A new hook action (for example `check()`) calls `refresh(signal)`, with its own controller owned by the episode. It never calls `reload`.
   - A double press during a check sends one read.
   - **Results:**
     - a failure keeps the notice and announces once that the latest settings still could not be confirmed;
     - "not applied" waits silently for the published state;
     - an unauthenticated result leaves sign-in to the session boundary;
     - a published non-matching bootstrap keeps the notice.
   - The denied (401/403) path keeps calling `onCheckSession` (`reload`).
5. **Form behavior.**
   - An edit resets only the last request's transient status (`success`, `error`, `unavailable`, `denied`), never an outstanding episode.
   - On confirmation, the form drops the draft only when it equals the confirmed value. A different newer draft stays, as do its Save state and `unchanged` computation.
   - The notice renders while an episode is outstanding. It can render alongside a later request's error, for example a rejected newer save.
6. **Account isolation.** `SettingsPage` keys `CampaignStartupForm` by `bootstrap.user.user_id`, so a different account remounts the form. The hook also checks `userId` before confirming, as defence in depth.
7. **Announcements and focus.**
   - A confirmation from a later read puts "Startup preference saved." in the existing polite status, once per episode. It is silent when a newer save is pending; that save's outcome is announced instead.
   - If the person used Check my session and the button still had focus when the notice was removed, focus moves to the checked radio of the saved choice. Use `useRetryFocus` with `resolveTarget`.
   - A failed check leaves focus on the button.
   - The same focus target applies when an independent read removes the notice while its button holds focus. That handling is local to this form; the shared hook is not changed.
8. **Documentation.** Update [portal behavior §4.7](../reference/portal-behavior.md#47-settings-and-campaign-startup-preferences) to describe the confirmed-episode notice, its reconciliation, in-place Check my session, edits keeping the notice and account isolation. Update [coverage](coverage.md)'s startup-preference row if its wording changes.

### 3.3 Exclusions

- **No backend, API, schema or authorization change.** `PUT /auth/preferences/campaign-startup`, the bootstrap shape and server-side resolution are unchanged.
- **No change to `useSessionBootstrap`, `SessionContext` or `useRetryFocus`.** The reconciliation reads the existing state, and no read ticket is exposed (R-1).
- **No change to the unmount abort contract.** Leaving Settings ends the episode, as today. This keeps a known limitation, O-1: if the page is left after a confirmed PUT but before its read-back is applied, the shared bootstrap can stay behind until the next session read, and in-session `/home` resolves from it. A fresh sign-in is unaffected. Changing that is a contract change to the reviewed B1-DEF7c behavior and is not part of S02.
- **No change to the last-visited write** (`recordLastVisitedCampaign`), its ordering queue, or the 404/401/403 save paths beyond item 5.
- **Not adding the startup PUT to the preference-write queue.** That queue is for never-aborted writes, and the startup PUT is abortable by contract.
- S01's files and the Knowledge page; other domains' recovery adoption; the 32-entry recovery map; the single-router assumption.
- Browser/AX runs, consumer pilots, copy-ui and preview, and acceptance.

## 4. Affected files and interfaces

| File | Change |
|---|---|
| `portal/src/hooks/useSaveCampaignStartupPreference.ts` | Outstanding episode, reconciliation from `useSession().state`, `check()`, an episode-scoped reset, and late-callback guards. The returned shape may grow (for example `outstanding`, `checking`, `check`); existing fields stay. |
| `portal/src/hooks/useSaveCampaignStartupPreference.test.ts` | New hook cases (§6); existing cases kept. "resets to idle" is adjusted only if `reset` semantics require it; record why. |
| `portal/src/components/CampaignStartupForm.tsx` | Edits don't end the episode; the draft is dropped only when it equals the confirmed value; the notice's Check my session uses `check()`; focus and announcement. |
| `portal/src/components/CampaignStartupForm.test.tsx` | New form cases. Two existing tests click Check my session after an unconfirmed save and assert `onCheckSession` was called; they change to assert one in-place `refresh` and no `onCheckSession` call. Record the changed expectation in §11.3. |
| `portal/src/pages/SettingsPage.tsx` (+ test) | `key={bootstrap.user.user_id}` on the form. |
| `portal/src/App.settingsSharedSession.test.tsx` | App cases A9–A12 (real provider and routes). |
| `docs/reference/portal-behavior.md` §4.7, `docs/delivery/coverage.md` | Behavior text (§3.2 item 8). |

## 5. Task commit

One task, one implementation commit (records can follow in a docs-only commit):

`P15-C03-S02-T01: confirm a saved startup preference from a matching later bootstrap for the same user and save`

## 6. Acceptance cases

"(fails at baseline)" marks a case that must be written first and shown failing on the implementation baseline before the fix. Every case asserts the PUT count where a save happened; it stays **one** unless the case itself presses Save again.

**Hook (`useSaveCampaignStartupPreference.test.ts`)**

| # | Case |
|---|---|
| A1 | Confirmed PUT, read-back rejects → unconfirmed. Then the session state becomes authenticated with the same user and `preferred_campaign_id === submitted` → `success`; PUT count 1. (fails at baseline) |
| A2 | As A1 with `submitted = null`, then a bootstrap with `preferred_campaign_id: null` → `success`. (fails at baseline) |
| A3 | Stale or unrelated evidence never confirms: a bootstrap with a different value, a different `user_id`, an `unauthenticated` state, or a read-back that resolves `false` with no published change each leave the episode outstanding. |
| A4 | Stale callbacks: episode X is outstanding; a check for X is in flight; a newer save Y starts and its PUT is confirmed. The late check result (resolve or reject) does not change Y's status, and a bootstrap matching X after Y's confirmation does not report success for Y. |
| A5 | A rejected newer save (404 / 403 / network) while X is outstanding keeps X outstanding, and still lets a matching bootstrap for X confirm it. (fails at baseline) |
| A6 | `check()` calls `refresh` once with a signal, never `reload`. A second `check()` while one is in flight sends no further read. A rejection keeps the episode outstanding and records a failed check; unmount aborts the check's signal and updates nothing. (fails at baseline) |

**Form (`CampaignStartupForm.test.tsx`) and Settings page**

| # | Case |
|---|---|
| A7 | Unconfirmed, then an edit (radio or select): the notice and its Check my session button stay. (fails at baseline) |
| A8 | Unconfirmed with a newer draft (Alpha); a bootstrap matching Beta is published. The notice goes, "Startup preference saved." is announced once, and the select still shows Alpha with Save enabled. With the draft still Beta instead, the draft is dropped and the form shows the saved Beta with Save disabled. (fails at baseline) |
| A8a | A bootstrap for another user (Settings page with the key): the previous user's notice, draft and status are gone, and the new user's own baseline shows. (fails at baseline) |
| A8b | A bootstrap that drops the submitted campaign (access lost): the notice stays, the campaign name is not shown, it is not offered, and Save stays disabled until another choice. |

**App (`App.settingsSharedSession.test.tsx`, real provider, routes and boundary)**

| # | Case |
|---|---|
| A9 | Save Beta, `GET /auth/session` fails → notice. Change the draft to Alpha; press Check my session with the session read still failing. Settings stays mounted (no "Portal unavailable"), the Alpha draft and the notice stay, one "still could not be confirmed" announcement is made, and focus stays on the button. PUT count 1. (fails at baseline) |
| A10 | Then the session read succeeds and Check my session is pressed again, with the Alpha draft still in place. The notice goes and "Startup preference saved." is announced once. The Alpha draft stays selected with Save enabled, and focus is on the checked "Always open this campaign" radio. PUT count 1; one session GET per check. (fails at baseline) |
| A11 | After A10, `/home` opens Beta's Campaign Home in the same session (the shared bootstrap is fresh). |
| A12 | Check my session whose read is unauthenticated → `/login`, and no saved-or-refused message is claimed. |

**Regressions (existing tests kept):** success after an applied read-back; `unconfirmed` (not `denied`) when the read-back fails or is not applied; rejected-PUT paths and messages; the 404 drop; unmount abort; all other `App.settingsSharedSession` cases.

### 6.1 Mutation probes (run by Sonnet; re-run by the reviewer)

Each probe must make at least one named case fail; revert it afterwards.

| # | Mutation | Must fail |
|---|---|---|
| M1 | Drop the `user_id` comparison in reconciliation | A3 (different user) |
| M2 | Confirm on any published bootstrap, ignoring the value | A3 (different value) |
| M3 | Let `reset()`, or an edit, end the outstanding episode | A7 |
| M4 | Drop the draft unconditionally on confirmation | A8 (newer Alpha draft) |
| M5 | Wire the notice's Check my session back to `onCheckSession` / `reload` | A6, A9 |
| M6 | Remove the episode guard on a late check result | A4 |
| M7 | Remove the `key` on the form | A8a |

## 7. Verification

### 7.1 Per-commit checks (Sonnet; repeated by the reviewer)

From PowerShell in `C:\Users\nemes\dnd_ai\portal` (uppercase `C:`; Vitest fails with "failed to find the current suite" from a lowercase `c:/` cwd):
- focused: `npx vitest run src/hooks/useSaveCampaignStartupPreference.test.ts src/components/CampaignStartupForm.test.tsx src/pages/SettingsPage.test.tsx src/App.settingsSharedSession.test.tsx`;
- full `npm test`. Record the first run and any rerun separately, and name any failure outside these files;
- `npm run lint`, `npm run build`;
- from the repository root: `uv run python scripts/check_documentation.py` and `git diff --check`.

Backend checks are not required (portal and docs only), unless a backend file changes, which would be a stop condition.

### 7.2 C03 checkpoint merge requirements (not S02's verdict)

The C03 PR merges only when all of these hold:
1. S01 and S02 have each passed independent review. S01 has (PASS WITH VERIFICATION LIMITS, [§11.7](p15-c03-s01-knowledge-read-recovery-plan.md#117-independent-re-review-of-r1r2-codex-2026-11-22)).
2. The checkpoint acceptance cases pass on the integration head: S01's A1–A14 and B1–B18, S02's A1–A12, and one full portal run showing both together.
3. CI passes on the exact integration head.

A reviewed slice is not a merged checkpoint.

### 7.3 Separate events (after the merge; not merge gates)

- Integrated-head browser and AX recovery evidence (the register's [browser](work-register.md#browser) obligation), including a real-browser run of A9–A11.
- Consumer pilot adoption, recorded per consumer.
- Owner acceptance (`p15-owner`). Nothing in this plan grants it.

## 8. Authorization, disclosure, concurrency and focus rules

- **Authorization is unchanged.** The server re-verifies on PUT; a stored ID never grants access; the client never navigates to a campaign absent from `campaigns`.
- **Disclosure.** Neither the notice nor the announcements name a campaign. A submitted campaign that the bootstrap no longer lists is never shown or offered (A8b). No episode, draft or status crosses an account change (A8a).
- **Concurrency.**
  - Session-read ownership stays with `useSessionBootstrap`: an older read cannot publish over a newer one.
  - The episode object guards the hook's own late callbacks.
  - One check per press; at most one in flight per episode.
  - No path sends a PUT except the user pressing Save.
- **Focus.** The check button keeps focus on failure. On confirmation after the button was used and still held focus, focus goes to the checked radio. A confirmation that arrives while focus is elsewhere never moves focus.
- **Announcements.** One polite "Startup preference saved." per confirmed episode. One "still could not be confirmed" per failed check. The `role="alert"` notice is not re-mounted on edits, so it is not re-announced.

## 9. Intermediate states

T01 is a single commit. Until it lands, current behavior (§2.1) is shipped; no intermediate state is merged.

## 10. Decisions

**No owner decision is required.** Routine choices made here:

- **R-1 (no read-order ticket).** A matching bootstrap for the same user is sufficient evidence for a server-confirmed save. The PUT is an idempotent set confirmed by a 204, and `useSessionBootstrap` already refuses to let an older read publish over a newer one. So a published bootstrap showing the submitted value is consistent with the confirmed write. A last-writer-wins race with another tab is the accepted §4.7 limitation. "Stale refresh" coverage is therefore about never-published, superseded, wrong-user and wrong-value reads (A3, A4), and needs no change to the shared session hook.
- **R-2 (non-matching read keeps the notice).** Per the criterion "Only a matching read clears the notice", a later bootstrap with a different value keeps the notice. Its wording stays truthful. The user can still save again.
- **R-3 (in-place check only for the unconfirmed notice).** `refresh` already re-reads the CSRF token and hands an ended session to the sign-in boundary, which is what §4.7 asks Check my session to do. The denied path keeps `reload`.
- **R-4 (manual Save stays available).** P3 is user-initiated. "Never repeating PUT" governs automatic and recovery paths, and the existing App retry test stays valid.
- **R-5 (focus target).** The checked radio of the saved choice, following the Infobox `resolveTarget` precedent in §5.11.
- **R-6 (account isolation by key).** Remounting the form per user is the smallest change that cannot carry state across accounts. The hook's `userId` check is defence in depth.
- **O-1 (kept limitation, §3.3).** Leaving Settings mid-episode keeps the reviewed abort contract. Changing it would be a separate contract decision.

## 11. Handoffs

### 11.1 Sonnet implementation instructions

1. Confirm the baseline (the commit adding this plan) is HEAD and `origin/phase15/completion`, with a clean worktree.
2. Read §2 to §8. Write the "(fails at baseline)" cases first, run them on the baseline, and record each failure (test name and assertion).
3. Implement §3.2 in the files of §4 only. Keep the reviewed behavior in §2.4.
4. Run §7.1. Run M1–M7, record each probe's failing case, and revert every probe.
5. **Stop and report instead of continuing if:**
   - a backend, API, `useSessionBootstrap`, `SessionContext` or `useRetryFocus` change seems necessary;
   - an existing test outside the two Check-my-session expectations named in §4 would need a changed expectation;
   - a case cannot be made to fail at baseline where marked.
6. Commit with the §5 subject, push, and record in §11.3 and the register's T01 row:
   - the SHA;
   - the test-first failures;
   - the focused and full runs, first run and rerun separately;
   - the probes;
   - the CI position. CI is expected to be "pending checkpoint PR".
7. Do not open, mark ready or merge a PR. Do not run browser or AX checks, start copy-ui or preview, or record any acceptance.

### 11.2 Independent review boundary (Luna)

- **T01 = combined S02:** from the plan commit to the T01 implementation commit, plus any docs-only records commit that follows it.
- Review against §2.4, §3, §6 and §8. Re-run the focused tests and M1–M7.
- A pass is a slice verdict only; §7.2 and §7.3 remain.

### 11.3 Implementation record (Sonnet)

**Implementation commit:** `d0a92536552cec7dbb45b75a534ae9cf16b1b1ec` (`d0a9253`), subject `P15-C03-S02-T01: confirm a saved startup preference from a matching later bootstrap for the same user and save`, a child of the baseline `f27c53dee5c87749f57d1177eadf9f2a42888903`. Pushed to `origin/phase15/completion`. Review range: `f27c53dee5c87749f57d1177eadf9f2a42888903..d0a92536552cec7dbb45b75a534ae9cf16b1b1ec`, plus the docs-only records commit that follows. Portal and docs only; no backend, API, `useSessionBootstrap`, `SessionContext` or `useRetryFocus` change.

**What changed.**
- `useSaveCampaignStartupPreference`: a confirmed PUT whose read-back is not applied creates an episode `{id, userId, submitted, before}`. It is confirmed during render from `useSession().state` when the session is authenticated, `user_id` equals the episode's user, the bootstrap is a different object from the one held when the save was sent (`before`), and `preferred_campaign_id === submitted` (null equals null). A different user ends it. A newer confirmed PUT ends it. Unmount aborts as before, and now also aborts a check. New result fields: `outstanding`, `confirmed` (confirmed while a rejected newer save's status is showing), `check()`, `checking`, `checkFailed`. `reset()` and edits never end an episode. `check()` calls `refresh(signal)` once (a second press while one is in flight sends nothing), never `reload`; a rejection records `checkFailed`; "not applied" is silent; a late result for an ended episode is ignored (aborted signal and episode id).
- `CampaignStartupForm`: the unconfirmed notice renders from `outstanding` (so it survives edits and sits beside a later request's error) as a small component that calls `useRetryFocus` with a `resolveTarget` (the checked radio, else another enabled radio, the select, a link or button of the section). The draft is dropped on confirmation only when it equals the saved choice. The polite status announces "Startup preference saved." (also when `confirmed`), "Checking your session…" and "The latest settings still could not be confirmed." The denied (401/403) notice still calls `onCheckSession`.
- `SettingsPage`: the form is keyed by `bootstrap.user.user_id`.
- `docs/reference/portal-behavior.md` §4.7 describes the episode, its reconciliation, edits keeping the notice, in-place check, focus, account isolation and limitation O-1. `docs/delivery/coverage.md` needed no change (its row's wording is unchanged).

**Two choices to review.**
- *Evidence must be a bootstrap published after the save was sent* (`before`). R-1 says a matching bootstrap for the same user suffices, but the existing hook test "keeps a confirmed save as unconfirmed, never denied, when the refresh was not applied" saves `null` from a session that already says null: the bootstrap that was there before the PUT is not evidence of it. A bootstrap published since (including one that superseded the save's own read) is.
- *Fixtures extended, no expectation changed.* The hook test's mocked session gained `user` and `campaign_preferences` (a `sessionWith` helper), because the hook now reads them; the form test harness gained a `publish` handle, records refresh signals and wraps the form in a `<section>` as the Settings page does (the focus handoff resolves within it).

**Changed existing expectations (the two named in §4, nothing else).** In `CampaignStartupForm.test.tsx`, "does not report success or apply the choice when the session refresh fails" and "says the confirmed save happened, and never that nothing was saved, when the refresh was not applied" clicked Check my session and asserted `onCheckSession` was called once; they now assert one in-place `refresh` and no `onCheckSession` call. The denied-path test ("offers a session check when the save is refused") is unchanged. The hook tests "resets to idle" and the unmount abort are unchanged.

**Test-first (new cases run on the baseline source, 71 tests in the four focused files): 24 failed.**
- Hook (11): A1, A2, A3 (different user), A3 (read-back false), A4, A5 (404, 403, network), A6 (check never reloads; unapplied check and unmount abort) and "reset() does not end the episode".
- Form (10): A7, A8 (newer draft), A8 (draft is the saved value), "Check my session reads once in place", "a failed check keeps the notice…", "moves focus to the checked choice", "does not move focus that went elsewhere", "falls back to the next focusable control", and the two changed Check-my-session expectations.
- Settings page (1): the A8a account-isolation case. App (2): A9 and A10/A11.
- Passed at baseline and kept as regression guards: the A8 "non-matching bootstrap keeps the notice" case, A8b (access dropped keeps the notice and names nothing) and A12 (an unauthenticated check goes to sign-in).

**Focused run after the change:** `useSaveCampaignStartupPreference.test.ts`, `CampaignStartupForm.test.tsx`, `SettingsPage.test.tsx` and `App.settingsSharedSession.test.tsx`: 4 files, 71 tests passed.

**Full `npm test`, four runs kept separate (the focused files pass in every run):**
- run 1: 1 failed of 5615, `App.knowledgeMemberPreview.test.tsx` "resets the character, party and page when the member changes…" (an 8 s timeout; that file passed alone, 39/39);
- run 2: 1 failed of 5615, `OrganizationMembersReader.test.tsx` "does not show the previous organization's roster while the next one loads" (an 8 s timeout; passed alone, 12/12);
- run 3: 1 failed of 5615, `App.knowledgeClaim.test.tsx` B13 (S01; passed alone, 150/150);
- run 4: 442 files and 5615 tests passed.
None of the failures touches startup preferences. `npm run lint` clean; `tsc -b` clean; `npm run build` passed (existing chunk-size advisory); `scripts/check_documentation.py` and `git diff --check` pass.

**Mutation probes (each temporary, reverted byte-for-byte), run against the four focused files:**
- M1 (drop the `user_id` comparison): fails A3 (different user);
- M2 (confirm on any published bootstrap): fails A3, A4, and the form A8 "non-matching" and A8b cases;
- M3 (`reset()` ends the episode): fails A7, A8 (newer draft), the failed-check and focus cases, the hook reset case, A9 and A10/A11;
- M4 (drop the draft unconditionally): fails A8 (newer draft) and A10/A11;
- M5 (the notice calls `onCheckSession`): fails A9, A10/A11 and six form cases (the in-place check, its failure and focus cases, and the two changed expectations);
- M6 (no episode guard on a late check): fails A4 and the A6 unapplied-check case; it took removing the guard, the id match in the derived `checking`/`checkFailed` and the abort on episode end together, because each is a separate defence;
- M7 (remove the `key`): fails A8a.

**Not done, by instruction:** no PR, copy-ui/preview or other consumers, no browser/AX run, no acceptance of any kind. **CI:** none ran for these commits; **CI pending checkpoint PR.**

**Known limits.** O-1 (§3.3) stands. The `before` rule means a bootstrap published between the PUT being sent and the failure being known is accepted as evidence, so a superseding read that already shows the value confirms the save at once. A confirmation that arrives while a rejected newer save's error is showing is reported beside it (`confirmed`), not in place of it.

### 11.4 Independent implementation review (Codex, 2026-11-22)

**Boundary and checkout.** Branch `phase15/completion`; initial worktree clean; HEAD and `origin/phase15/completion` both `fc83c2f2b0f81d0ee8c135c522e7744fe9d899cb`. Ancestry is valid for baseline `f27c53dee5c87749f57d1177eadf9f2a42888903` → implementation `d0a92536552cec7dbb45b75a534ae9cf16b1b1ec` → final records head `fc83c2f2b0f81d0ee8c135c522e7744fe9d899cb`. The implementation range changes the eight expected portal behavior/test files; implementation-to-final-records is docs-only (plan and register). `CLAUDE.md`, the current grading rubric, register, full S02 plan and implementation/tests were inspected.

**Acceptance review.** A1–A12 and M1–M7 were mapped against implementation, tests and §11.3 evidence. Confirmed PUTs whose own read-back is not applied create an episode keyed to account and submitted value, including `null`. Edits and `reset()` do not clear it; failed/nonmatching reads do not confirm; account change and unmount end it; only user Save issues a PUT. The form preserves a newer draft and drops only a draft equal to the confirmed bootstrap value. Check my session makes a single in-place `refresh(signal)`, never reloads or PUTs, suppresses duplicate in-flight checks, retains the episode on failure/non-application, and guards late results by episode identity. Settings keys the form by account. Status/notice separation, focus-on-current-button and connected enabled target fallback are implemented; the existing denied path retains its reload-based session check. The two named Check-my-session assertions now verify one refresh and no `onCheckSession`; fixture additions provide realistic user/preference fields, a publication handle, abort-signal capture and the production section container without weakening the expected page behavior.

**Publication ordering.** The `before` identity comparison establishes that the currently rendered bootstrap object differs from the one captured when Save was sent. `useSessionBootstrap.publish` installs a newly parsed bootstrap only when its read ticket still owns publication. The plan’s R-1 contract accepts an authenticated same-user matching bootstrap published after Save was sent; it does not require proof that the confirming read started after the PUT or was caused by that PUT. A temporary hook probe modeled a read started before Save and a matching new bootstrap published after Save was sent; the episode confirmed with one PUT, as the agreed contract allows. Existing A4 covers late check results after a newer confirmed save and prevents the old value from confirming the newer episode. The recorded M1/M2/M6 probes cover user/value matching and late-check guarding. No separate read-ticket or causal-proof requirement is inferred.

**Finding S02-R1 — confirmation lost when matched during a newer pending save.** `portal/src/hooks/useSaveCampaignStartupPreference.ts:96–105`. Trigger: save A is confirmed but its read-back leaves an outstanding episode; the person edits and submits B; while B is pending, a session read (for example the outstanding Check my session read) publishes a new same-user bootstrap matching A; then B's PUT rejects. The render reconciliation clears A's episode at lines 100–101, but because `status.kind === "pending"` it sets neither success nor `confirmed`; the later rejection changes only the status to error/unavailable/denied. The form consequently loses A's confirmation and recovery notice while showing B's failure. This fails the stated requirement that a confirmation remains truthful and distinct beside a rejected newer save's error. A temporary regression probe reproduced this: it failed at the final `confirmed === true` assertion (received false). The source test file was restored byte-for-byte; SHA-256 before/after `5E3AD2B5D8B43B2062C2A53C826B8830265F849B00A8B84AB81F3FB9ED6CBAD5`.

Rubric: application behavior in the authenticated Settings path; exposure **1/3** (a constrained overlap of two saves and a session publication), impact **1/3** (loss of truthful confirmation for the earlier successful preference write; no persisted data loss or authorization effect), triggerability **1/2** (requires that specific timing), detection/recovery **1/1** (the new request error remains visible, but the earlier result is silently lost), blast radius **0/1** (one account/form). **Score 4/10, Medium.** Readiness: **blocks this slice’s A5 acceptance**, although the practical impact is bounded. Bounded Sonnet correction: retain a distinct matched-earlier-episode result while a newer PUT is pending; if the newer PUT rejects, expose both facts without conflating which request failed or falsely saying B succeeded; if B confirms, let B’s result govern without duplicate completion; retain same-user scope and account/unmount guards. Add a regression for A matching during B-pending then B-refusal, plus the existing order (B refusal then A matching), and verify 403/404/network refusal labels remain tied to B.

**Verdicts.** S02-T01 / combined S02: **CHANGES REQUIRED** for S02-R1. The remaining acceptance cases passed review; no second material finding was identified. S01 remains PASS WITH VERIFICATION LIMITS; no demonstrated regression affects it. No owner decision is required.

**Verification (PowerShell).** From `C:\Users\nemes\dnd_ai\portal`, focused hook/form/Settings/App tests passed: 4 files, 71 tests. `npx tsc -b`, `npm run lint` and `npm run build` passed; build emitted the existing chunk-size advisory. From repository root, `uv run python scripts/check_documentation.py` and `git diff --check` passed before this review record was added; they are rerun after the records edit below. Two focused temporary probes were run and their source was restored and hash-verified: (1) A matched bootstrap arriving while B was pending and B then rejected failed as described above; (2) a pre-PUT-started read publishing a matching bootstrap after Save passed under the agreed publication-order contract. An initial mis-rooted probe filter selected no tests; it made no file changes and is not counted as a probe result. No full suite was rerun: §11.3 separately preserves the three failed 5615-test runs and the fourth clean 5615-test run. CI remains pending the checkpoint PR. Browser/AX, human and owner acceptance remain pending; this slice pass/fail does not establish C03 merge readiness.


### 11.5 Correction of S02-R1 (Sonnet, 2026-11-22)

The review in §11.4 is kept as the history of the finding. Baseline for the correction: `fc83c2f2b0f81d0ee8c135c522e7744fe9d899cb`. **S02-R1 is corrected, pending independent confirmation.** S01's PASS WITH VERIFICATION LIMITS is carried forward unchanged: no S01 file changed. No acceptance of any kind is claimed.

| What | Full SHA |
|---|---|
| Correction (portal) | `a5827e659ca299c0935fe09a97b1637264fb9064` |
| Re-review range | `fc83c2f2b0f81d0ee8c135c522e7744fe9d899cb..a5827e659ca299c0935fe09a97b1637264fb9064`, plus the docs-only records commit that follows (it changes no source) |

**Correction (portal only; no backend, shared session contract, `useRetryFocus` or consumer change).**
- Hook: when the session confirms an outstanding save A while any other request's status is showing (a newer save B that is pending, or was rejected, or is itself unconfirmed), `confirmed` is set and kept. Before, a pending B was excluded, so A's confirmation was dropped and B's later rejection showed alone. `confirmed` is not reported beside a success, because that newer save was read back by its own read.
- Form: A's confirmation is announced in its own words, "Your earlier startup preference change was confirmed.", once, whenever it arrives. "Startup preference saved." is said only for a save the session read back (`status` success), so A's matching read is never presented as B's confirmation. B's own result (rejection message, "saved, but could not be confirmed" notice, or success) is unchanged.
- The publication-order contract is unchanged: no proof that a PUT caused the observed value is required. Episode ownership, the `before` rule, the account key, the in-place check, the draft rule and the focus handoff are untouched.
- `docs/reference/portal-behavior.md` §4.7 now says so.

**Test-first.** On the `fc83c2f` source, with the new tests kept, 13 of the new cases failed (7 form, 6 hook); one new hook case, "B succeeds and is read back", passed as a guard.
- Form, announcement counts asserted from the live region: A confirmed while B is pending says the earlier confirmation once and not "Startup preference saved."; B rejected with 403, 404, 500 and a network failure each show B's own message, keep the earlier confirmation (announced once, "saved" never), and send two PUTs in all; B succeeds and is read back says each text once, in that order; B succeeds with its read-back outstanding shows B's notice and A's confirmation and never "Startup preference saved."
- Hook: `confirmed` is true while B is pending and after B's 404, 403, 500 or network failure, with the episode over; B succeeds with its read-back outstanding leaves B unconfirmed with A confirmed, A's value does not confirm B, and B's own matching bootstrap does.

**Verification.**
- Focused (hook, form, Settings page, App settings): 4 files, 85 tests passed.
- Full `npm test`, six runs kept separate. Each failure is in a file unrelated to startup preferences, each time a different one, and each passed when rerun alone:
  - run 1: 1 failed of 5629, `CharacterPublicProfilePage.test.tsx` "a release that returns a new snapshot returns focus to the Release button" (the known C02 focus symptom). Rerun alone: it failed once, then passed four times in a row. It also passed three times alone with this change stashed;
  - run 2: 3 failed, `CharacterPublicProfilePage` (same case again), `CharacterRevelationsSection.write` V19 and `EncounterPages` "reports a confirmed start whose re-read fails…";
  - run 3: 1 failed, `App.characterShell.test.tsx` "gives the defaults after a direct entry…" (breadcrumb label read before the character loaded; passed alone, 35/35);
  - run 4: the same `App.characterShell` case again;
  - a full run with the portal source stashed (baseline `fc83c2f`): 442 files and 5615 tests passed;
  - run 5: 442 files and 5629 tests passed;
  - run 6: 1 failed, `App.knowledgeClaim.test.tsx` "clears the draft when the retry says access is gone…" (S01, the case recorded as intermittent before).
  The runs are not hidden behind run 5; the baseline pass shows the failures are not stable evidence for or against this change, and the failing files do not import any startup-preference code.
- `npm run lint` clean; `tsc -b` clean; `npm run build` passed (existing chunk-size advisory); `scripts/check_documentation.py` and `git diff --check` pass.

**Mutation probes (temporary, restored byte-for-byte).**
- M8 (ignore a confirmation that arrives while a newer save is pending: the S02-R1 defect): fails all seven new form cases and the six hook cases that assert A's confirmation (13 in all).
- M9 (report A's confirmation beside B's success too): fails "B succeeds and is read back" in the form and the hook, and "B succeeds with its read-back outstanding" in the hook.

**CI:** none ran for these commits; **CI pending checkpoint PR.**

### 11.6 Independent confirmation of S02-R1 (Codex, 2026-11-22)

**Boundary and checkout.** Branch `phase15/completion`; initial worktree clean; HEAD and origin both `c81d6d90b5c48a5eccf72d0b967ceb7a5c44a314`. Verified ancestry baseline `fc83c2f2b0f81d0ee8c135c522e7744fe9d899cb` → correction `a5827e659ca299c0935fe09a97b1637264fb9064` → final records head `c81d6d90b5c48a5eccf72d0b967ceb7a5c44a314`. The correction changes the four reported portal source/test files; the records range changes only this plan, the register and portal behavior reference. The original S02-R1 finding in §11.4, correction evidence in §11.5, A1–A12, and grading rubric were reviewed.

**S02-R1 disposition: RESOLVED.** The hook retains A's confirmation when a matching same-user bootstrap arrives while B is pending. Form tests assert the distinct earlier-operation wording once, without saying B is saved. B's 403, 404, 500 and network failures each retain A's confirmation alongside B's truthful refusal/error. If B succeeds with its own read-back outstanding, A remains identified separately and B's unconfirmed notice remains; A's value does not confirm B. If B's own read-back applies, A's earlier text is replaced by B's own completion; the live-region test observes each announcement once and in order. The hook guard tests include the B-own-success path, the B-unconfirmed path, and a later matching B bootstrap. The acceptance publication-order rule is unchanged: a matching bootstrap published after submission is accepted without a causal-read requirement.

**Additional residual focus finding F-S02-1 — no focus target when A confirms during B-pending Check.** `portal/src/components/CampaignStartupForm.tsx:198–207`. Supported trigger: A is outstanding; B is pending; the still-enabled Check my session button is used; the read confirms A and removes the notice. B's pending state disables both radios, the select and Save. `resolveCheckTarget` therefore returns `null` after the focused Check button is removed. A temporary form probe reproduced focus falling to `document.body` rather than a connected enabled target. This behavior was present before the R1 correction as well (the correction did not change focus handling); the correction review surfaced it while exercising the required two-save interaction. Rubric: exposure **1/3** (constrained authenticated settings interaction), impact **1/3** (bounded loss of keyboard position; no data or authority effect), triggerability **1/2** (specific overlap), detection/recovery **0/1** (the user can tab again), blast radius **0/1** (one form/user): **3/10, Low**. Readiness: the current S02 plan's §8 focus promise is not met for this supported path, so the combined S02 acceptance remains incomplete even though R1 closes. Bounded Sonnet correction: when the notice is removed while the form is locked by another pending save, provide a meaningful connected focus fallback that remains available (for example a programmatically focusable section heading); retain the normal checked-radio target, do not focus disabled controls, and preserve the move-away/navigation guards. Add a regression that focuses Check, starts/holds B, confirms A, and asserts the fallback; also retain the existing ordinary checked-choice, failure-stays-focused and move-away cases.

**Verdicts.** S02-R1 correction: **PASS / RESOLVED.** S02-T01 and combined S02: **CHANGES REQUIRED** for F-S02-1; this is a remaining acceptance defect, not a new checkpoint gate. S01's PASS WITH VERIFICATION LIMITS is unchanged and no S01 regression was demonstrated.

**Verification (PowerShell).** From `C:\Users\nemes\dnd_ai\portal`, the focused hook/form/Settings/App suite passed: 4 files, 85 tests. Lint, typecheck, build, repository documentation check and `git diff --check` passed; the build emitted the existing chunk-size advisory. A targeted temporary focus probe failed as described, then its test source was restored byte-for-byte (SHA-256 `1ACC75ECBE0B5A0DA4D670D8CA19769B2D609F76A98EDD25B0431474A49C7697`). No whole suite was repeated. All six recorded full runs in §11.5 remain distinct: runs 1–4 and 6 failed, run 5 passed; the clean baseline 5615-test run and isolated reruns remain separate and do not establish cause. CI remains pending the checkpoint PR. No real-browser, AX, human or owner check was run.

**Remaining C03 checkpoint evidence.** Per §7.2, after the S02 focus acceptance is corrected and reviewed, C03 still requires S01 A1–A14/B1–B18 and S02 A1–A12 on the integration head, one full portal run with both slices, and CI on that exact integration head. Browser/AX (including real-browser S02 A9–A11), consumer pilots and owner acceptance remain separate later events under §7.3. This slice review does not declare any of them complete or add a separate review gate.


### 11.7 Correction of F-S02-1 (Sonnet, 2026-11-22)

The reviews in §§11.4 and 11.6, including the original CHANGES REQUIRED, are kept as history. Baseline for the correction: `c81d6d90b5c48a5eccf72d0b967ceb7a5c44a314`. **F-S02-1 is corrected, pending independent confirmation.** S02-R1's closure and S01's PASS WITH VERIFICATION LIMITS are carried forward unchanged: no S01 file changed. No acceptance of any kind is claimed.

| What | Full SHA |
|---|---|
| Correction (portal) | `45f18f0b0606b6d424342fdf8d326c8be954a2b5` |
| Re-review range | `c81d6d90b5c48a5eccf72d0b967ceb7a5c44a314..45f18f0b0606b6d424342fdf8d326c8be954a2b5`, plus the docs-only records commit that follows (it changes no source) |

**Correction (portal only; `useRetryFocus`, the session contracts and the hook are untouched).** The form's polite status region is now programmatically focusable (`tabIndex={-1}`), and the focus handoff's `resolveCheckTarget` falls back to it when no control is enabled, between the select and the links/buttons of the empty state. The order is: the enabled checked radio, another enabled radio, the enabled select, the status region, then a link or button. While another save is pending every control is disabled, so after Check my session confirms the earlier save and the notice goes, focus lands on the region that says what happened ("Saving your startup preference…" and "Your earlier startup preference change was confirmed."). Nothing else changes: controls stay disabled, and no save or confirmation behavior was touched. `docs/reference/portal-behavior.md` §4.7 now names the fallback.

**Reproduction and test-first.** On the baseline source (new tests kept), the reported case failed: A outstanding, B pending (radios, select and Save disabled), the Check my session button focused and used, A confirmed, the notice removed; the status region never took focus (`toHaveFocus` timed out, focus on the page). The other two new cases passed at baseline and are kept as guards: focus the person moved to another control before the confirmation stays there, and a failed check keeps focus on the button.

**Verification.**
- Focused (hook, form, Settings page, App settings): 4 files, 88 tests passed.
- Full `npm test` (both C03 slices are in it), two runs kept separate:
  - run 1: 2 failed of 5632, `CharacterPublicProfilePage.test.tsx` "Cancel still returns focus to Release" (the known C02 focus symptom) and `App.knowledgeClaim.test.tsx` "clears the draft when the retry says access is gone…" (S01, recorded as intermittent). Both passed together when rerun alone (208 tests);
  - run 2 (the justified rerun): 442 files and 5632 tests passed.
- `npm run lint` clean; `tsc -b` clean; `npm run build` passed (existing chunk-size advisory); `scripts/check_documentation.py` and `git diff --check` pass.
- Mutation probe M10 (remove the status-region fallback), restored byte-for-byte: fails the new locked-form case; the move-away and failed-check guards and everything else pass.

**CI:** none ran for these commits; **CI pending checkpoint PR.**

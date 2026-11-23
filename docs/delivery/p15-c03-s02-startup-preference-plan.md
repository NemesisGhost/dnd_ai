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

*Pending.*

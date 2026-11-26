# D/P15-C10-S02 implementation plan: guide the existing quest review and status action

Owner register rows: [P15-C10](work-register.md#p15-c10), [P15-C10-S02](work-register.md#p15-c10-s02), [P15-C10-S02-T01](work-register.md#p15-c10-s02-t01), [P15-C10-S02-T02](work-register.md#p15-c10-s02-t02). Source finding: [R14 — Guided quest outcome/review](work-register.md#r14--guided-quest-outcome-review), the guided-review part (R14a mapping and R14b guidance). Historical row: [review-2026-11-11.md](review-2026-11-11.md) Q03. Attached record outside this slice: [quest-effect](work-register.md#quest-effect) (persistent outcome choice and consequences, deferred). Checkpoint order, shared files and merge requirements are in the [S01 plan, section 12](p15-c10-s01-objective-actions-plan.md#12-c10-checkpoint-coordination).

Prepared by Opus, 2026-11-25. **T01 and T02 implemented (section 11.3); independent review pending.**

- Starting SHA `deb2760a90c126f73b5c28e7efa8b0a24117bd3c`; plan-entry head `341c0932d128ff49a0e29ff3e3a87ccdeab982a9` (C09 merge, fast-forward), as in the S01 plan.
- T01's baseline is the S01-T01 records commit, revalidated at start (S01 plan, section 12.1): `adb98bb8ba295aefd9f670f810fa668c5db60e89`. T02's baseline is the T01 records commit (not yet created).
- CI: no run exists for C10.

## 1. Entry readiness and scope

- S02 has no slice-specific gate and does not depend on S01. Its criteria: "Base through T02. Cancel discards uncommitted choices. History distinguishes confirmed changes from unapplied rewards."
- **T01:** "Display scope, objectives and descriptive rewards." **T02:** "Invoke the existing status action with per-step receipts and interruption tests."
- **R14 remaining work:** map each screen to an existing command or read and identify descriptive-only results; guide scope and objective review, the status action and confirmed history, with per-step recovery. Do not require new categories or evaluators. A persistent outcome choice or automatic consequence engine needs a separately admitted design ([quest-effect](work-register.md#quest-effect)).
- **R14 acceptance:** correct party/timeline scope, stale status, interrupted or unknown steps, refresh and navigation, no duplicate actions. Cancel discards only uncommitted choices. Receipts and history distinguish authored descriptions, confirmed state transitions and unapplied consequences.
- **Q03 (historical):** definitions have outcomes and rewards; the runtime status command has no outcome selection or reward application. Acceptance: review with an accurate consequence preview, receipt and history; no fictitious automatic rewards.
- **Not in scope:** choosing or recording an outcome, applying rewards, any consequence write ([quest-effect](work-register.md#quest-effect)); new objective categories or evaluators.

## 2. Verified current behavior (at `341c093`)

### 2.1 Screen-to-command map (R14a)

| Screen | Existing read or command | Result kind |
|---|---|---|
| Outcomes and rewards section ([QuestCompletionSections.tsx](../../portal/src/components/quests/QuestCompletionSections.tsx)) | Quest authoring read (`outcomes[].rewards[]`); outcome/reward commands | Authored descriptions only |
| Progress section ([QuestProgressPanel.tsx](../../portal/src/components/quests/QuestProgressPanel.tsx)) | `GET /campaigns/{c}/quests/{q}/progress` ([api/quest_runtime.py](../../src/dnd_ai/api/quest_runtime.py)) | Per-scope status, actions, objectives |
| Quest status buttons | `POST …/quests/{q}/{activate,complete,fail,suspend,resume,abandon}` with `expected_status`, `party_id`, `note` | One causal event plus `campaign.quest_state` update ([commands/quest_runtime.py](../../src/dnd_ai/commands/quest_runtime.py)); receipt `{quest_id, event_id, previous_status, status, changed}` |
| Objective moves | `POST …/quests/objectives/{o}/status` | One event plus `objective_state` |
| Recorded event | `GET /campaigns/{c}/events/{event_id}` (`canon.edit`, [api/event_corrections.py](../../src/dnd_ai/api/event_corrections.py)); portal route `/app/:campaignId/events/:eventId` | Confirmed transition, with correction |

No command chooses an outcome or applies a reward. The status command writes the quest's status only.

### 2.2 Plan-entry reproduction results

From the same temporary test as the S01 plan (deleted after the run), on a published quest with one outcome "Village saved" carrying the reward "50 gold":

| ID | Probe | Observed |
|---|---|---|
| P1 | Open **Complete quest for Everyone** | Dialog text: "Complete quest? This is recorded as an event in the campaign history. A correction can undo it only while nothing has changed since. Note (only editors see it)". No scope, objectives, outcomes or rewards. The Progress section shows no outcome or reward either. |
| P2 | Confirm it | The announcer says "Complete quest: done". No visible receipt and no link to the event. Focus lands on the page `h1` (the opener button disappeared). |
| P3 | Server answers `503`; then **Cancel** | The dialog showed "…we cannot tell whether this was saved… Retrying sends the same request…" with Retry. After Cancel: no alert or note remains; progress was read once in total (no re-read). Re-opening and confirming re-sent the **same** idempotency key. |
| P4 | `503` on **Suspend** (no dialog) | The same unknown-outcome alert with Retry. |
| P5 | Suspend confirmed, progress re-read fails | "The latest progress could not be loaded…" with Try again, and "Saved, but the latest data could not be loaded." |

### 2.3 Deviations S02 repairs (demonstrated)

1. The finishing confirmation shows nothing to review: no scope, objectives, or authored outcomes and rewards, and nothing says rewards are not applied (P1).
2. A confirmed status change leaves no receipt or history on the page, only a transient announcement, and focus falls to the page heading (P2).
3. Cancelling after a lost answer forgets the unknown outcome and does not reconcile progress (P3).

### 2.4 Source-inspected risks

- **Late success after a scope switch.** Quick actions (activate, suspend, resume) run without a dialog, so the person can select another scope while one is pending. The success message is built before sending and names no scope; a scope-naming receipt must come from the confirmed body (C4).
- **Navigation while unresolved.** The page guard ([UnsavedInputGuard](../../portal/src/components/staged/UnsavedInputGuard.tsx)) sees only a typed note; a pending or unknown status action is not reported (C9).
- **Section switch while pending.** The Progress panel stays mounted when another section opens; a focus move on success could target a hidden element (C10).

### 2.5 Behavior that must not regress (guards)

Existing tests in [QuestProgressPanel.test.tsx](../../portal/src/components/quests/QuestProgressPanel.test.tsx) and [QuestWorkspace.test.tsx](../../portal/src/components/quests/QuestWorkspace.test.tsx): statuses and actions per scope; publishing does not start a quest; suspend sends the status it saw; finishing asks for confirmation and sends the note; Cancel sends nothing; objective moves; the all-required hint; party scopes; refused-transition explanation; eligibility follows the lifecycle (draft, archived, replaced, unreadable); refresh in place keeping a typed note; stale-refresh notice; structure lock after a command; scope selection kept through refresh. Also P3's same-key retry and P5's confirmed-but-unread report.

## 3. Outcome, scope and exclusions

### 3.1 User outcome

Before finishing a quest, the GM sees exactly what they are about to change: for whom, where each objective stands, and what the quest's authored outcomes and rewards describe, plainly marked as not applied. After any quest status change they get a receipt naming the scope and the recorded transition, with a link to the recorded event, and a short history of this visit's confirmed changes. If the answer is lost, the page keeps saying so until progress has been read again, and leaving the page asks first.

### 3.2 In scope

**T01 — review content (portal only).**

1. `QuestWorkspace` passes `outcomes={view.outcomes ?? []}` to `QuestProgressPanel` (from the read already loaded; no new request).
2. New `QuestFinishReview` component rendered as `ConfirmDialog` children for **complete**, **fail** and **abandon**:
   - **Scope:** "For: Everyone" or "For: ‹party name›", and "Now: ‹status›".
   - **Objectives:** the scope's objectives from the progress read, as "‹stage›: ‹name› — ‹status›", optional ones marked "(optional)". A summary line: "All required objectives are complete." or "‹n› required objective(s) are not complete."
   - **Described in this quest:** each outcome as "‹name› (‹category label›)" with its rewards as "‹reward kind label›: ‹description›" (a knowledge reward also names its knowledge item). Labels come from the options catalogs already loaded. None: "This quest describes no outcomes or rewards."
   - **Statement:** "‹Completing/Failing/Abandoning› records only the quest's status for ‹scope›. No outcome is chosen and no reward is given or recorded. Apply any reward yourself."
3. The dialog's existing description, note field and buttons are unchanged. Activate, suspend and resume still act at once.
4. **Cancel** discards the note (unchanged) and sends nothing.

**T02 — per-step receipts and interruptions (portal only).**

5. **Receipt.** After a confirmed quest status change (any of the six actions), the Progress section shows a receipt at the top of a "Changes in this visit" list, newest first. Each receipt is built from the confirmed body and the server receipt, never from the currently selected scope:
   - heading (`h3`, `tabIndex=-1`): "Recorded: quest ‹completed/failed/abandoned/activated/suspended/resumed› for ‹scope›";
   - step lines: "Status: ‹previous› → ‹new›, recorded as an event." with a link **Open the recorded event** to `/app/:campaignId/events/:eventId`; then "Progress shown: read again." or, when the read-back failed, "Progress shown: could not be read again." with a read-only **Check progress**;
   - for complete, fail and abandon when the quest has any reward: "Rewards described in this quest were not applied."
   - The list is held in component state only: not persisted, cleared when the workspace unmounts. It holds the last 10 receipts.
6. **Announcement and focus.** The announcement becomes the receipt heading text, once, after the read-back (existing `combineRefetchOutcomes` rule). Focus moves to the new receipt heading only if the Progress section is still active, the heading can take focus, and focus is on the body, the closed dialog's opener or inside the closed dialog. Otherwise focus stays.
7. **Unknown outcome.** When a status action's answer is lost (an `error` that is not stale, not a refusal with a code, not 401/403/404):
   - in the dialog, the existing retry message stays;
   - on **Cancel**, or immediately for a quick action, the section shows a polite note: "The request to ‹action› the quest for ‹scope› may have been recorded. Progress is being read again." and reads progress once (read-only). After that read: "Progress was read again: ‹scope› is ‹status›." with **Check progress** to read again.
   - The attempt stays retryable: re-opening the same action for the same scope and confirming re-sends the same body and key (existing hook behavior; the dialog keeps the note value of that attempt).
8. **Navigation protection.** While a status action is pending, or its outcome is unknown and progress has not been read again since, the panel reports "a quest action whose result is not known" to the page's guard (alongside the existing note label). The label clears after a confirmed result or a successful re-read.
9. **Refusals.** Stale writes and coded refusals keep their existing notices; no receipt is added.
10. **Objective moves** keep their current behavior and announcement; they get no receipt.
11. **Documentation.** Update the Quest workspace row in [portal-behavior.md](../reference/portal-behavior.md) for T01 (review) and T02 (receipts, unknown outcome, guard).

### 3.3 Exclusions

- No backend, API, schema or command change; `QuestActionRequest` is unchanged. No outcome is chosen, recorded or applied; no reward is given ([quest-effect](work-register.md#quest-effect)).
- No change to objective status moves beyond guards, to the Outcomes and rewards section, to the event detail page, or to corrections.
- No persistent history store; the campaign event history remains authoritative and is reached by the event link.
- No change to `useAuthoringMutation`, `ConfirmDialog`, `UnsavedInputGuard` or the structure editor (S01).

## 4. Affected files and interfaces

| File | Task | Change |
|---|---|---|
| `portal/src/components/quests/QuestWorkspace.tsx` | T01 | Pass `outcomes` and the options' outcome-category and reward-type labels to the panel. |
| `portal/src/components/quests/QuestFinishReview.tsx` (new) | T01 | Review content. |
| `portal/src/components/quests/QuestProgressPanel.tsx` | T01, T02 | Render the review in the dialog (T01); receipts, unknown-outcome note, guard label, focus (T02). |
| `portal/src/components/quests/QuestActionReceipts.tsx` (new, optional) | T02 | Receipt list, if kept out of the panel. |
| `portal/src/components/quests/QuestProgressPanel.review.test.tsx` (new) | T01 | B-cases. |
| `portal/src/components/quests/QuestProgressPanel.receipts.test.tsx` (new) | T02 | C-cases. |
| `docs/reference/portal-behavior.md` | T01, T02 | Quest workspace row. |

`QuestProgressPanel` gains props `outcomes: QuestOutcomeView[]` and `optionLabels` (outcome categories and reward types). No API type changes.

## 5. Task commits

- T01: `feat(portal): review scope, objectives and described rewards before finishing a quest (P15-C10-S02-T01)`.
- T02: `feat(portal): quest status receipts, unknown-outcome recovery and guard (P15-C10-S02-T02)`.

Each is one implementation commit plus a records commit. Independent review boundary: S02 is reviewed once, from T01's baseline through the T02 records commit (the slice criteria are "base through T02").

## 6. Acceptance cases

"Fails" means expected to fail at the task's baseline; "guard" means expected to pass before and after.

### 6.1 T01

| ID | Case | Baseline |
|---|---|---|
| B1 | **Complete quest for Everyone** opens a dialog naming "For: Everyone" and "Now: Active". | Fails (P1) |
| B2 | For a party scope, the dialog names the party and that party's status. | Fails |
| B3 | It lists the scope's objectives with statuses and "(optional)", and says how many required objectives are not complete; with all complete it says so. | Fails (P1) |
| B4 | It lists "Village saved (Success)" and "Other: 50 gold" under "Described in this quest". | Fails (P1) |
| B5 | It states that only the status is recorded and no outcome is chosen or reward given, naming the scope; Fail and Abandon use their own verb. | Fails (P1) |
| B6 | A quest with no outcomes says "This quest describes no outcomes or rewards." | Fails |
| B7 | A knowledge reward names its knowledge item. | Fails |
| B8 | Opening the review sends no request (no POST, no extra read). | Guard |
| B9 | Cancel sends nothing, and re-opening shows an empty note. | Guard |
| B10 | Activate, suspend and resume still act at once, with no dialog. | Guard |
| B11 | Confirming sends the existing body (`expected_status`, `party_id`, `note`). | Guard |
| B12 | A draft, archived, replaced or unreadable-lifecycle quest still offers no commands (existing eligibility tests). | Guard |

### 6.2 T02

| ID | Case | Baseline |
|---|---|---|
| C1 | Completing shows a receipt "Recorded: quest completed for Everyone" with "Status: Active → Completed, recorded as an event." and **Open the recorded event** linking to `/app/c1/events/e1`. | Fails (P2) |
| C2 | Focus moves to that receipt heading. | Fails (P2: page `h1`) |
| C3 | The announcer says the receipt heading once; for activate it says "Recorded: quest activated for Everyone". | Fails (permitted adaptation of the existing "Activate quest: done" expectation, section 6.4) |
| C4 | Suspend for party A, select Everyone while it is pending, then let it confirm: the receipt names party A. | Fails (source-inspected) |
| C5 | Confirmed with a failed progress re-read: the receipt says "Progress shown: could not be read again." with **Check progress**, which only reads; the write is not repeated. | Fails (receipt line); no-repeat part is a guard (P5) |
| C6 | With a quest reward, a completion receipt says "Rewards described in this quest were not applied."; a suspend receipt does not. | Fails |
| C7 | Lost answer in the Complete dialog, then Cancel: the note "…may have been recorded. Progress is being read again." appears, progress is read once, then the note states the scope's status. | Fails (P3) |
| C8 | After C7, re-opening Complete for the same scope and confirming re-sends the same key and body. | Guard (P3) |
| C9 | While pending, and while unknown before the re-read, the page's guard lists "a quest action whose result is not known"; after the re-read it is gone. | Fails (source-inspected) |
| C10 | Opening Details while a quick action is pending: the action confirms, no focus moves into the hidden Progress section, and the receipt is there on return. | Fails (receipt absent; focus part source-inspected) |
| C11 | Lost answer on Suspend: the existing alert with Retry, plus the unknown note and one progress read. | Fails (note and read); alert part is a guard (P4) |
| C12 | Two confirmed actions give two receipts, newest first, each with its own scope; the list is not persisted across a remount. | Fails |
| C13 | A stale write and a `quest_transition_invalid` refusal keep their existing notices and add no receipt. | Guard |
| C14 | The confirm and action buttons are disabled while a request is pending (no duplicate send). | Guard |
| C15 | Objective moves keep their announcement and add no receipt. | Guard |

### 6.3 Mutation probes

| ID | Task | Mutation | Must fail |
|---|---|---|---|
| N1 | T01 | Omit the objectives list from the review. | B3 |
| N2 | T01 | Omit the "no reward is given" statement. | B5 |
| N3 | T01 | Read the scope from the currently selected scope at render rather than the confirm state. | B2 |
| N4 | T02 | Build the receipt scope from the selected scope instead of the confirmed body. | C4 |
| N5 | T02 | Skip the progress re-read after an unknown outcome. | C7, C11 |
| N6 | T02 | Never report the unresolved label to the guard. | C9 |
| N7 | T02 | Move focus to the receipt unconditionally. | C10 |
| N8 | T02 | Add the "not applied" line to every receipt. | C6 |

### 6.4 Permitted changes to existing tests

- `QuestProgressPanel.test.tsx` line 268: "Activate quest: done" becomes the T02 receipt heading text. No other expected text changes.
- A test that finds the finishing dialog's textbox with `getByRole("textbox")` may use the note's accessible name instead, if the review adds no textbox (it should not).

Any other expectation change is a stop condition.

## 7. Verification

### 7.1 Per-commit checks

From PowerShell in `C:\Users\nemes\dnd_ai\portal`:

- Focused: `npx vitest run src/components/quests/QuestProgressPanel.review.test.tsx src/components/quests/QuestProgressPanel.receipts.test.tsx src/components/quests/QuestProgressPanel.test.tsx src/components/quests/QuestWorkspace.test.tsx src/components/quests/QuestWorkspace.scoped.test.tsx src/components/quests/QuestCompletionSections.test.tsx src/pages/QuestAuthoringPages.test.tsx src/App.scopedRoles.test.tsx` (T01 omits the receipts file).
- Full `npm test` once per task; a failed first run and its rerun are reported separately with each failure named and no cause claimed.
- `npm run lint`, `npx tsc -b`, `npm run build`; from the root, the documentation check and `git diff --check`.

### 7.2 Merge requirements

As in the [S01 plan, section 12.2](p15-c10-s01-objective-actions-plan.md#122-c10-checkpoint-merge-requirements).

## 8. Authorization, disclosure, isolation, outcomes and focus

- **Authorization.** Progress, status commands and the event read all require `canon.edit`, the capability that mounts the workspace. The review and receipts add no request beyond the existing progress read; the event link goes to an existing `canon.edit` page.
- **Disclosure.** Review content is editor-only: GM-only objectives, notes and authored rewards appear only inside the workspace. Nothing changes for members or the member preview.
- **Scope isolation.** Every receipt and unknown note names the scope of the command that was sent (`party_id` of the confirmed or attempted body). Another quest or campaign remounts the workspace and drops the receipts.
- **Draft preservation.** The note survives a lost answer, a stale write and a refusal (existing); Cancel discards it. Typed input elsewhere on the page survives every refresh (existing).
- **Retry identity.** Same body and key for a retry or a re-confirm of the same unresolved attempt (existing hook); `expected_status` protects against a second transition if the first applied.
- **Refusals, partial results, unknown outcomes.** Refusals: existing notices, no receipt. Partial: confirmed but unread is a receipt with a read-only check. Unknown: a note plus one read-only progress read; never presented as done or failed.
- **Late responses.** A result that arrives after the scope or section changed is recorded against its own scope and does not take focus.
- **Navigation.** Section 3.2 item 8.
- **Announcements.** One per confirmed action, after the read-back. Unknown-outcome notes are polite; the existing alerts stay.

## 9. Intermediate states

After T01 alone, the review exists and receipts do not; the page is coherent (today's announcement remains). After T02 the slice is complete.

## 10. Decisions

Routine choices; none needs the owner.

- **R-1 Show every authored outcome.** The status command takes no outcome, so mapping a category to an action would invent semantics. All outcomes are shown, each with its category.
- **R-2 Receipts for all six quest actions,** the review only for the three finishing ones. Objective moves keep their announcement only.
- **R-3 Visit history in memory, last 10.** The event history is authoritative; the panel does not add a store.
- **R-4 Unknown outcome reconciled by one read.** It never claims success or failure; the person retries or acts on what the read shows.

No blocking product, policy, authorization or contract decision remains. The owner question of persistent outcomes stays with [quest-effect](work-register.md#quest-effect) and does not block S02.

## 11. Handoffs

### 11.1 Sonnet implementation instructions (T01, then T02)

For each task:

1. Revalidate the baseline: HEAD equals `origin/phase15/completion`, the worktree is clean, and the previous task's records commit is present (for T01, S01-T01's; for T02, T01's). Check that section 2 still describes the files the task changes; report any difference before implementing.
2. Write the task's "fails" cases first and record each failing assertion at the baseline; record that the guards pass.
3. Implement only the task's section 3.2 items in the section 4 files; make only section 6.4 adaptations, naming each.
4. Run section 7.1; then the task's probes (N1–N3 for T01, N4–N8 for T02) with exact byte restoration and hash comparison.
5. Stop and report if: a backend or API change seems needed; an outcome or reward would be recorded or applied; `useAuthoringMutation`, `ConfirmDialog` or the page guard must change; an expectation outside section 6.4 must change; or a guard fails.
6. Commit with the section 5 subject and push; record in section 11.3 and the task's register row; commit and push the records. CI position: pending checkpoint PR.
7. Do not open or merge a PR, run browser/AX checks, start a consumer, or record acceptance.

### 11.2 Independent review boundary

S02 review: T01's baseline through the T02 records commit, covering B1–B12, C1–C15, the probes and section 8.

### 11.3 Implementation record

#### T01 (Sonnet, 2026-11-25)

**Baseline.** T01 baseline is the S01 review-records commit `adb98bb8ba295aefd9f670f810fa668c5db60e89` (HEAD = `origin/phase15/completion`, clean worktree). It records Codex's S01 re-review (S01 plan §11.6: C10-S01-1 confirmed corrected; T01 and S01 PASS WITH VERIFICATION LIMITS) unchanged, with the original §11.4 finding and all evidence history kept; the parent `89fc473aab7185243a57bb0ed7acf0b222f8aeeb` was the S01 correction records commit. Before committing it I confirmed the only uncommitted changes were Luna's two S01 files, and that the documentation and diff checks passed.

**Implementation.** `104034c97907bbb01f5909d7d354470e67c02591` (`feat(portal): review scope, objectives and described rewards before finishing a quest (P15-C10-S02-T01)`), pushed; local HEAD = origin. Section 3.2 items 1–4 and the T01 part of item 11, portal only.

**Section 2 revalidation.** `QuestProgressPanel.tsx` and `QuestWorkspace.tsx` matched section 2 at the baseline (no outcomes prop, a bare `ConfirmDialog` with the note, quick actions without a dialog, no receipt). S01's objective-action and focus code is in `QuestEditor.tsx` and was not touched. One difference, handled without a stop condition: `CampaignQuestDetailPage.tsx` mounts the same `QuestProgressPanel` for a campaign GM who has no world role (a progress-only view whose definition reads are refused). Section 2 does not mention it. The two new props are therefore optional there: with no definition the review says "This view does not show the quest's authored outcomes or rewards." instead of claiming there are none; nothing else changes and no request is added. This is covered by one extra test, listed below.

**Files.** New `QuestFinishReview.tsx` (read-only review), new `questStatusLabel.ts` (the existing status wording moved out of the panel unchanged, so the review and the panel share it), new `QuestProgressPanel.review.test.tsx`. Changed: `QuestProgressPanel.tsx` (props `outcomes`, `optionLabels`; the review as the dialog's children, built from the confirm state's scope snapshot), `QuestWorkspace.tsx` (passes `view.outcomes ?? []` and the outcome-category and reward-type choices from reads already held), and the Quest workspace row of `docs/reference/portal-behavior.md` (T01 text only; receipts and recovery are T02's). No change to `useAuthoringMutation`, `ConfirmDialog`, `UnsavedInputGuard`, the backend or any API type.

**Test adaptations (section 6.4).** None for T01: the existing "Activate quest: done" expectation belongs to T02, and the finishing dialog's `getByRole("textbox")` still finds exactly the note because the review adds no textbox.

**Baseline evidence.** The 16 B-case tests were written and run against the baseline production code (new files absent). Designated failures, 11 tests, each failing on the missing text: B1 ("For: Everyone"), B2 ("For: Red Company"), B3 ×4 (objective lines with status; the optional marker and the all-complete line; the no-objectives line; the plural count), B4 ("Described in this quest"), B5 ×2 (statement for Everyone with the three verbs; the statement naming a party), B6 (no outcomes), B7 (knowledge item). Baseline-passing guards, 5: B8 (no request on opening), B9 (Cancel sends nothing, empty note on re-open), B10 (activate, suspend, resume at once, no dialog), B11 (confirm body with party, status seen and trimmed note), B12 (draft quest offers no finishing command). B8 first included the "For: Everyone" text in its body; I removed it so that the case is a guard as the plan says. After the implementation the file passes 17/17: the 16 plus one added case, "says outcomes and rewards are not shown, rather than that there are none", for the progress-only view above (it is an addition to B1–B12 and has no baseline run, because the component did not exist).

**Verification (first runs, no reruns needed).**
- Focused set (section 7.1 without the receipts file, plus S01's `QuestEditor.objectiveActions.test.tsx` as the applicable S01 regression): 8 files, 170 passed.
- Full `npm test` from PowerShell in `C:\Users\nemes\dnd_ai\portal`: 464 files, 6,029 passed, 0 failed (first run).
- `npm run lint` pass; `npx tsc -b` pass; `npm run build` pass (existing chunk-size notice only).
- Root: `scripts/check_documentation.py` pass; `git diff --check` pass.

**Probes (exact bytes restored, hashes compared equal).** N1 (objectives list omitted) fails B3 ×2. N2 (the "no reward is given" sentence omitted) fails B5 and the progress-only case. N3 (the review reads the currently selected scope instead of the confirm state) fails B2: B2 selects another scope behind the open dialog, which is contrived in a real modal but is the only way to separate the two in jsdom.

**Limits.** jsdom only: no real-browser focus, AX, zoom or layout of the longer dialog; the dialog scrolls inside the native `<dialog>` with its existing styling, unverified visually. The review shows the quest's whole authored outcome list because no outcome is chosen (decision R-1). CI is pending the checkpoint PR. T02, browser/AX, human review and acceptance are not started or recorded.

**T01 records commit:** `7d81ccaf012f779c7fdf88f717057b29a752560e`.

#### T02 (Sonnet, 2026-11-25)

**Baseline.** `7d81ccaf012f779c7fdf88f717057b29a752560e` (HEAD = `origin/phase15/completion`, clean worktree). T01 implementation `104034c97907bbb01f5909d7d354470e67c02591` and its records were present (ancestor check passed). The review props matched the recorded T01 implementation (`outcomes` and `optionLabels`, both optional, review built from the confirm state's scope snapshot).

**Callers of `QuestProgressPanel` (two).** (1) `QuestWorkspace` passes `outcomes`, `optionLabels` and the page guard's `onUnsaved`. (2) `CampaignQuestDetailPage`'s progress-only view for a campaign GM without a world role passes neither definition prop and a no-op `onUnsaved`. Unchanged and no definition read was added: there the review keeps "This view does not show the quest's authored outcomes or rewards", and a finishing receipt says "Authored rewards, if any, were not applied." rather than claiming there are none or are some. **Material discrepancy to report, not repaired:** that view has no page guard (`noUnsaved`), so item 8 (leaving the page asks first) cannot take effect there; the panel reports the label, and the reader drops it. Adding a guard to the reader page is outside S02's files (section 4) and was not done.

**Implementation.** `006a7ee69f0a46b1c84e86bf9c9017aedf21f703` (`feat(portal): quest status receipts, unknown-outcome recovery and guard (P15-C10-S02-T02)`), pushed; local HEAD = origin. Section 3.2 items 5–10 and the T02 part of item 11. Portal only; no backend, API, `useAuthoringMutation`, `ConfirmDialog` or guard change.

**Files.** New `QuestActionReceipts.tsx` (list and receipt), new `questReceipts.ts` (receipt type, heading text and id; a separate module because the lint rule bars non-component exports from a component file), new `QuestProgressPanel.receipts.test.tsx`. Changed: `QuestProgressPanel.tsx` and the Quest workspace row of `docs/reference/portal-behavior.md`.

**How it works.** The mutation's `onSuccess(result, body)` builds the receipt from the confirmed `body` (party named by the request, looked up in a map of party names seen in progress reads) and the server receipt, after the progress read, so it never uses the selected scope (N4). The announcement is the heading, once, only when both reads succeeded (existing rule); objective moves keep `done`-style announcements and add no receipt. Focus: the opener and the control used are captured; after the receipt renders, the heading takes focus only if focus is on the body, the opener, the control used or inside its dialog, and `canTakeFocus` accepts the heading (a hidden section refuses). A lost answer (`network` or `server`, any code) is reconciled at once for an action without a dialog and on Cancel for one with a dialog, by one read-only progress read; the existing retry message is untouched and a re-confirm sends the same body and key (the hook, unchanged). The guard label is reported while a request is pending, and while a lost answer has not been followed by a successful re-read.

**Differences and additions to note.** (a) A receipt whose server answer has `changed: false` says "Status: already ‹status›; no new change was recorded." (the plan did not specify this case). (b) The list's own label is an accessible name on a `section` rather than a visible heading, so receipt headings are the only `h3`s added. (c) The guard also covers a pending objective move, which the plan says only for status actions; it is truthful and was kept. (d) A confirmed receipt appears just before the request's status flips from pending to success (the announcement and the last read-back wait on it), so the guard still holds the page for that moment; the C12 test waits for the buttons to be enabled before navigating, which exposed it.

**Test adaptation (section 6.4).** `QuestProgressPanel.test.tsx`: "Activate quest: done" became "Recorded: quest activated for Everyone". No other existing expectation changed.

**Baseline evidence (C1–C15 written first, run against the T01 production code).** 18 tests; 13 failed as designated: C1, C2, C3, C4, C5, C6 (both: the completion receipt line and the suspend negative, which fails because no receipt exists), C7, C9, C10, C11 (note and one read), C12, and the progress-only caller case. 5 passed as baseline guards: C8 (same body and key on re-confirm), C11's alert-with-Retry part (split into its own test), C13 (stale and refused-transition notices, no receipt), C14 (disabled while pending), C15 (objective announcement, no receipt). C8, C13 and C14 first failed for reasons of my own tests (C8 waited on the new note; C13 used an ambiguous text matcher; C14 looked for the confirm button by its idle name while the button reads "Working…"); I corrected the tests, not the expectations, and reran the baseline: 13 failed, 5 passed. The progress-only case is an addition to C1–C15 (no plan ID).

**Verification.**
- Focused set (section 7.1 in full: B and C files, the existing quest files, `QuestAuthoringPages`, `App.scopedRoles`, plus S01's `QuestEditor.objectiveActions`): 9 files, 188 passed.
- Full `npm test` from PowerShell in `C:\Users\nemes\dnd_ai\portal`: 465 files, 6,047 passed, 0 failed, first run.
- `npm run lint`, `npx tsc -b`, `npm run build` pass (existing chunk-size notice). Root `scripts/check_documentation.py` and `git diff --check` pass.

**Flake in my own C12 test, found and fixed before the implementation commit (kept separate from the results above).** While stabilising, C12 (two receipts, then navigate away and back) failed intermittently in the receipts file alone: once with "Found multiple elements" for the receipt heading, and in 4 of 8 and then 5 of 8 later runs with a timeout or "Unable to find … Quests list page". Cause, shown by the run: the test navigated while the second request was still pending, and the departure guard (correctly) held the page. I fixed the test to wait for the buttons to be enabled; after that the receipts file passed 10 of 10 consecutive runs. The same intermittent C12 failure had also appeared under mutations N5 and N8 in their first run; their rerun after the fix (below) is the evidence of record.

**Probes (exact bytes restored, hashes equal, rerun after the test fix).** N4 (receipt scope from the selected scope) fails C4. N5 (no progress re-read after a lost answer) fails C7, C9 and C11. N6 (guard label never reported) fails C9. N7 (focus moved to the receipt unconditionally) fails C10. N8 ("not applied" on every receipt) fails C6 (suspend negative).

**Limits.** jsdom only: real-browser focus, AX behavior of the polite note and the receipts, zoom and layout are unverified. The reader page's missing guard is described above. CI is pending the checkpoint PR. Independent review, browser/AX/zoom, human review and acceptance are not recorded. T02 completes the slice's implementation, not its review.

**Review ranges for Luna.** T01: `adb98bb8ba295aefd9f670f810fa668c5db60e89..104034c97907bbb01f5909d7d354470e67c02591`. T02: `7d81ccaf012f779c7fdf88f717057b29a752560e..006a7ee69f0a46b1c84e86bf9c9017aedf21f703`. Combined S02: `adb98bb8ba295aefd9f670f810fa668c5db60e89..` the T02 records commit.

# D/P15-C10-S01 implementation plan: separate objective management from disclosure

Owner register rows: [P15-C10](work-register.md#p15-c10), [P15-C10-S01](work-register.md#p15-c10-s01), [P15-C10-S01-T01](work-register.md#p15-c10-s01-t01). Source finding: [R13 — Quest-objective authoring](work-register.md#r13--quest-objective-authoring), part R13a only. Historical row: [review-2026-11-11.md](review-2026-11-11.md) Q02. Attached records outside this slice: [quest-kind](work-register.md#quest-kind) (R13b) and [quest-eval](work-register.md#quest-eval) (R13c). The companion slice is [S02](p15-c10-s02-quest-completion-plan.md). Checkpoint coordination for both slices is in [section 12](#12-c10-checkpoint-coordination).

Prepared by Opus, 2026-11-25. **Merged with C10 through PR #79 at `ebe6c72` (section 12.5); S01 PASS WITH VERIFICATION LIMITS (section 11.6). Merged is not accepted.**

- Starting SHA: `deb2760a90c126f73b5c28e7efa8b0a24117bd3c`, the reviewed C09 PR head, with a clean worktree.
- Plan-entry head: `341c0932d128ff49a0e29ff3e3a87ccdeab982a9`, the C09 merge (PR #78), reached by fast-forward. Its tree equals `deb2760`'s; no history was rewritten.
- C09 merge bookkeeping is a separate documentation commit, `e729fd1677f1474bdfb9c8b0f828fdb7601d3e33`, before this plan.
- The implementation baseline is the commit that adds this plan (reported in the handoff).
- CI: no run exists for C10.

## 1. Entry readiness and scope

- **C10 ("Guide quest objective and completion work")** is admitted with no checkpoint prerequisite ("—"). Its criteria send browser objective focus and confirmed history to [browser](work-register.md#browser). It has two slices: S01 (this plan) and S02. Neither slice has a slice-specific gate, and neither depends on the other.
- **S01 criteria:** "Base through T01. Verify existing objective data and permitted actions."
- **T01:** "Place edit/remove actions with focus, authorization and progressed-quest structural-lock tests."
- **R13a remaining work:** "separate disclosure/content from management actions and preserve focus." R13 acceptance: existing objectives and progressed quests remain valid; no accidental toggle or remove; authorized actors only; keep the structural-progress lock; do not weaken historical invariants.
- **Q02 (historical):** Edit and Remove are already separate buttons, but they sit inside expanded content. It is a layout/disclosure change, not a missing command. Acceptance: an independent disclosure and action region, no accidental toggle or remove, focus retained.
- **Not in scope:** R13b new objective categories ([quest-kind](work-register.md#quest-kind), proposal pending inventory) and R13c automatic evaluation ([quest-eval](work-register.md#quest-eval), deferred). No objective type, completion mode or lookup value changes.
- **Reliability investigations** on the C04–C09 rows, including the organization-reader substring collision, are separate obligations. None is a C10 prerequisite.

## 2. Verified current behavior (at `341c093`)

### 2.1 How objective management works today

- [QuestEditor.tsx](../../portal/src/components/authoring/QuestEditor.tsx) (`QuestStructureEditor`) is the **Stages and objectives** section of the Quest workspace. It mounts only for `canon.edit` holders ([QuestWorkspace.tsx](../../portal/src/components/quests/QuestWorkspace.tsx)).
- Stages are cards. The `h3` toggle button (`stage-<id>`) is the stage's only disclosure control; its body (`stage-body-<id>`) is `hidden` until expanded. All stages start collapsed. A stage holding an open form never collapses.
- Inside an expanded stage, each objective is an `li` holding, in order: the `h5` name heading (`objective-<id>`, `tabIndex=-1`), a hint line (type, requirement, completion, visibility, quantity), the target, the description, then an unlabelled `div.authoring-actions` with **Edit objective** and **Remove objective**, then the edit panel when open.
- Actions come from the server's `available_actions` ([queries/quest_authoring.py](../../src/dnd_ai/queries/quest_authoring.py)): `update` gates editing; `remove_objective`, `remove_stage` and `reorder_stages` are withdrawn once the quest has progress, with `quest_has_progress` as the blocked reason. Commands re-check the lock on the server ([commands/quest_definitions.py](../../src/dnd_ai/commands/quest_definitions.py)).
- One panel is open at a time (`panel` state). `openPanel` replaces it unconditionally. `closePanel` clears it and the mutation status.
- Saves use one `useAuthoringMutation` scoped `quest:<id>`. On success the quest is read again, the panel closes, a message is announced and focus moves after a zero-delay timer: to `objective-<id>` after an objective save, to `add-objective-<stage>` after an objective removal, to `stage-<id>` after a stage save, to `add-stage` after a stage removal.
- Removal uses `ConfirmDialog` ("Remove this objective?", **Remove objective** / **Keep it**). Its error slot shows the mutation error. **Keep it** closes the dialog and calls `mutation.reset()`.
- A progressed quest shows a `role="note"` explanation, hides the remove and move controls, and disables kind, requirement, completion, quantity and target in an existing objective's panel. Wording and visibility stay editable.

### 2.2 Plan-entry reproduction results

A temporary test (`portal/src/components/quests/QuestC10.repro.test.tsx`, using [questWorkspaceHarness](../../portal/src/test/questWorkspaceHarness.tsx)) ran at `341c093` and was then deleted. All its probes passed as written; the logged values are the evidence.

| ID | Probe | Observed |
|---|---|---|
| R1 | Objective actions before and after **Expand all** | 0 Edit and 0 Remove buttons collapsed, 2 Edit after expanding. The Edit button has no labelled group ancestor; it sits in the objective's content `li`. |
| R2 | Focus **Edit objective Find the map**, open it, focus **Cancel**, press it | Focus on `BODY`. |
| R3 | Same with **Add objective to Opening** | Focus on `BODY`. |
| R4 | Type "Typed draft" into the open edit panel, then press **Edit objective Reach the ruin** | The panel now shows "Reach the ruin". No dialog. "Typed draft" is nowhere on the page. No request. |
| R5 | Open **Edit objective Find the map**; inspect its **Remove objective** | Enabled. |
| R6 | Server answers the removal with `409 quest_has_progress` | The dialog shows "This quest already has progress recorded, so its structure cannot change…". No retry offered. **0** further quest reads. Remove buttons remain. |

### 2.3 Deviations S01 repairs (demonstrated)

1. **Lost focus on Cancel** (R2, R3). Closing a panel without saving drops focus to the document.
2. **Silent draft loss** (R4). Opening another panel discards a dirty one with no warning; the page guard only covers leaving the page.
3. **No reconciliation after a lock refusal** (R6). The page keeps offering structural actions the server has just refused.
4. **Actions not separated from content** (R1). Management actions are an unlabelled block between description and form, not an identifiable region.

### 2.4 Source-inspected risks (to be proven by cases below)

- **Stage panels share `closePanel`.** Cancel on **Edit stage** and on a new stage very likely loses focus the same way (A3).
- **Removing the objective being edited** (R5). If confirmed, the panel's objective disappears while `panel` still holds its values, so the page guard may keep reporting "an objective" for a form that no longer exists (A9).
- **Structural update refused for progress recorded since the read.** `quest_has_progress` has a global message ([authoringValidation.ts](../../portal/src/utils/authoringValidation.ts)) but no field mapping. Without a re-read, the panel keeps structural values the server will refuse again (A11).
- **Unknown removal outcome then Keep it.** `onCancel` calls `mutation.reset()`, so a lost answer disappears with the dialog and nothing re-reads the quest (A17). The same pattern was demonstrated for the Progress dialog ([S02 plan, section 2.2](p15-c10-s02-quest-completion-plan.md#22-plan-entry-reproduction-results), P3).
- **Late focus after leaving the section.** The success timer focuses its target whether or not the Stages and objectives section is still shown or the person has moved focus elsewhere (A15).

### 2.5 Behavior that must not regress (baseline-passing guards)

- Expand/collapse per stage and **Expand all** send no request; a stage with an open form stays expanded (existing tests in [QuestAuthoringPages.test.tsx](../../portal/src/pages/QuestAuthoringPages.test.tsx), "Quest stage cards").
- Removal confirmation states what goes; **Keep it** sends nothing (existing).
- The progress-locked view: lock note, no remove or move controls, structural fields disabled, wording and visibility editable, additions offered (existing tests in QuestAuthoringPages and [QuestProgressPanel.test.tsx](../../portal/src/components/quests/QuestProgressPanel.test.tsx) "the structure it can lock").
- A quest under review offers no edit controls; a reader without `canon.edit` mounts nothing (existing).
- Stale write keeps the panel's input and never resubmits the old version (existing).
- Successful save and removal focus targets and single announcements (section 2.1).
- Server-side authorization and the structural lock are unchanged; the portal only presents `available_actions`.

## 3. Outcome, scope and exclusions

### 3.1 User outcome

A GM editing a quest's stages finds each objective's **Edit** and **Remove** in its own labelled action group, apart from what the objective says. Closing a form returns them to where they were. Switching to another form never throws away what they typed without asking. When the server refuses a structural change because play has begun, the page catches up at once: it shows the lock and stops offering what it just refused.

### 3.2 In scope (T01, portal only)

1. **Objective action group.** Each objective's management buttons move into `<div role="group" aria-label="Manage objective <name>">`, rendered directly after the objective's heading row and before its hint, target and description. The group is rendered only when at least one of `update_objective` or `remove_objective` is offered and the quest is editable (`update`). Button names and accessible names stay as they are. The stage toggle never contains an action. Stage expansion remains the disclosure for a stage's objective list (R-1).
2. **Focus on Cancel.** Cancelling any panel returns focus to the control that opened it: **Edit objective ‹name›**, **Add objective to ‹stage›**, **Edit stage ‹name›** or **Add stage**. If that control no longer exists, focus goes to the stage toggle (`stage-<id>`), or to **Add stage** for a new stage.
3. **Dirty panel switching.** Opening another panel while the open one is dirty (`panelDirty`) opens a `ConfirmDialog`: title "Discard your changes?", description "Your changes to ‹the objective "name" / the new objective / the stage "name" / the new stage› have not been saved.", confirm **Discard changes**, cancel **Keep editing**. Keep editing leaves the panel and its values unchanged and returns focus to the control that asked. Discard opens the requested panel. A clean panel switches without a dialog, as today.
4. **No removal of the objective being edited.** While an objective's panel is open, its **Remove objective** is disabled, with `aria-describedby` pointing to a hint "Close the edit form to remove this objective." Other objectives' Remove stays enabled.
5. **Lock reconciliation.** When any structure command fails with `quest_has_progress`, the section reads the quest again once (the existing `refetch`; read-only). The existing message stays where it is shown (the removal dialog, or the top of the section). After the read reports `has_progress`:
   - the lock note shows and the withdrawn actions disappear (existing rendering);
   - an open existing-objective panel keeps its name, description and visibility as typed, sets kind, requirement, completion, quantity and target back to the re-read saved values, and shows a polite note: "Kind, requirement, completion, quantity and target were set back to their saved values because this quest now has recorded progress.";
   - closing the removal dialog after such a refusal moves focus to the objective's heading (or the stage toggle for a stage removal), because the Remove button is gone.
6. **Unknown removal outcome.** If a removal attempt's answer was lost and the person chooses **Keep it**, the dialog closes, the quest is read again once (read-only), and the section shows a polite note: "The removal may have been applied. The list shows the latest read." Opening the same removal again and confirming re-sends the same request under the same key (existing hook behavior).
7. **Late focus.** A success's focus move happens only if the Stages and objectives section is still the active section, the target can take focus (`canTakeFocus` from [focusEligibility.ts](../../portal/src/utils/focusEligibility.ts)), and focus is still on the page body, the submitting control or inside the closed form or dialog. Otherwise focus stays where the person put it; the announcement still happens once.
8. **Documentation.** Update the Quest workspace row in [portal-behavior.md](../reference/portal-behavior.md) to describe the action group, focus return, discard confirmation, lock reconciliation and unknown-removal note.

### 3.3 Exclusions

- No backend, API, schema, command or authorization change. No change to `available_actions`, `blocked_actions` or the lock rules.
- No new objective types or completion semantics (R13b/R13c). No change to objective fields, validation or limits.
- No change to stage reordering, drag and drop, **Expand all**, the stage card header, the Dependencies, Outcomes or Participants sections, or `QuestProgressPanel` (S02).
- No change to `useAuthoringMutation`, `ConfirmDialog`, `UnsavedInputGuard` or the page guard.
- Stage **Edit**/**Remove** stay where they are; only their Cancel focus (3.2 item 2) and lock reconciliation (item 5) change.

## 4. Affected files and interfaces

| File | Change |
|---|---|
| `portal/src/components/authoring/QuestEditor.tsx` | Items 1–7. Track the opener id for focus return; a pending-switch state for the discard dialog; a refusal handler for `quest_has_progress`; a reset of structural panel values after a locked re-read. |
| `portal/src/components/authoring/authoring.css` | Only if the group needs layout (for example a `quest-objective-list__actions` row). No colour or token change. |
| `portal/src/components/authoring/QuestEditor.objectiveActions.test.tsx` (new) | Cases A1–A17 not already covered, using `setupQuestWorkspace`. |
| `docs/reference/portal-behavior.md` | Quest workspace row. |

Interfaces unchanged: the `QuestStructureEditor` props, the quest authoring endpoints and bodies, `RefreshOutcome`, the unsaved-report labels ("a stage", "an objective").

## 5. Task commit

`feat(portal): separate objective actions with focus return and lock recovery (P15-C10-S01-T01)`. One implementation commit, then a records commit. Independent review boundary: plan commit (baseline) through the T01 records commit.

## 6. Acceptance cases

"Fails" means expected to fail at the baseline; "guard" means expected to pass at the baseline and after.

| ID | Case | Baseline |
|---|---|---|
| A1 | Cancel on **Edit objective ‹name›** returns focus to that button. | Fails (R2) |
| A2 | Cancel on a new objective returns focus to **Add objective to ‹stage›**. | Fails (R3) |
| A3 | Cancel on **Edit stage ‹name›** returns focus to it; Cancel on a new stage returns focus to **Add stage**. | Fails (source-inspected) |
| A4 | With a dirty objective panel, pressing another objective's **Edit** opens "Discard your changes?" and sends nothing. **Keep editing** keeps "Typed draft" and focus returns to the pressed button. **Discard changes** opens the other objective's panel. | Fails (R4) |
| A5 | With a clean panel, pressing another **Edit** switches at once with no dialog. | Guard |
| A6 | Each objective's Edit and Remove are inside a group named "Manage objective ‹name›", which precedes the hint and description and is not inside the stage toggle. | Fails (R1) |
| A7 | The group is absent when neither `update_objective` nor `remove_objective` is offered, and contains only Remove when only `remove_objective` is offered. | Fails (no group at baseline); the button presence part is a guard |
| A8 | Toggling a stage with an open panel leaves the panel and its values; expanding and collapsing send no request. | Guard |
| A9 | While objective O's panel is open, O's **Remove objective** is disabled with the hint; another objective's Remove is enabled. | Fails (R5) |
| A10 | Removal refused with `quest_has_progress`: the dialog keeps the message and offers no retry; the quest is read again once; after the read reports progress, no Remove or Move control remains and the lock note shows; **Keep it** puts focus on the objective's heading. | Fails (R6: 0 reads) |
| A11 | Saving an objective with a changed kind is refused with `quest_has_progress`: one re-read; the panel keeps the typed name and visibility, shows the saved kind (disabled) and the set-back note. | Fails (source-inspected) |
| A12 | The progress-locked view is unchanged (note, no remove/move, disabled structural fields, editable wording and visibility, additions offered). | Guard (existing) |
| A13 | A quest without `update` shows no management group or **Add objective**; a caller without `canon.edit` mounts nothing. | Guard (existing) |
| A14 | Successful objective save focuses its heading and announces "Objective saved" once; successful removal focuses **Add objective to ‹stage›** and announces "Objective removed" once. | Guard |
| A15 | A removal still pending when the person opens the Details section completes without moving focus out of Details; the announcement happens once. | Fails (source-inspected) |
| A16 | A removal whose answer is lost offers Retry in the dialog; Retry sends the same body under the same idempotency key. | Guard |
| A17 | After a lost removal answer, **Keep it** closes the dialog, reads the quest once and shows "The removal may have been applied…"; confirming the same removal again re-sends the same key. | Fails (source-inspected) |

### 6.1 Mutation probes

Each probe is a temporary source edit, run against its named cases, then reverted with the file's bytes and hash restored.

| ID | Mutation | Must fail |
|---|---|---|
| M1 | Cancel does not restore focus to the opener. | A1, A2, A3 |
| M2 | `openPanel` ignores `panelDirty` (no discard dialog). | A4 |
| M3 | Remove the `role="group"` wrapper (buttons kept). | A6, A7 |
| M4 | Skip the re-read on `quest_has_progress`. | A10, A11 |
| M5 | Keep typed structural values after the locked re-read. | A11 |
| M6 | Leave Remove enabled for the objective being edited. | A9 |
| M7 | Move focus after success without the section and focus checks. | A15 |
| M8 | Keep it after a lost answer calls `reset()` with no re-read or note. | A17 |

### 6.2 Permitted changes to existing tests

None are expected: accessible names are unchanged. If a test in `QuestAuthoringPages.test.tsx`, `QuestWorkspace.test.tsx` or `QuestProgressPanel.test.tsx` locates a button by DOM position rather than name, it may be changed to locate the same button inside its "Manage objective ‹name›" group, with the asserted behavior unchanged. Each such change is named in the implementation record. Any other expectation change is a stop condition.

## 7. Verification

### 7.1 Per-commit checks (Sonnet; repeated by the reviewer)

From PowerShell in `C:\Users\nemes\dnd_ai\portal` (uppercase `C:`):

- Focused: `npx vitest run src/components/authoring/QuestEditor.objectiveActions.test.tsx src/pages/QuestAuthoringPages.test.tsx src/components/quests/QuestWorkspace.test.tsx src/components/quests/QuestWorkspace.scoped.test.tsx src/components/quests/QuestProgressPanel.test.tsx src/components/quests/QuestCompletionSections.test.tsx src/App.scopedRoles.test.tsx`.
- Full: `npm test` once; report a failed first run and its rerun separately, naming each failure without claiming a cause.
- `npm run lint`, `npx tsc -b`, `npm run build`.

From the repository root: `uv run python scripts/check_documentation.py` and `git diff --check`. No backend run is required because no backend file changes (a backend change is a stop condition).

### 7.2 Independent review boundary

S01 review covers the plan commit through the T01 records commit: the A-cases, the probes, section 8 and the permitted-change list.

## 8. Authorization, disclosure, isolation, outcomes and focus

- **Authorization.** The portal renders only server-offered actions; the server re-checks `canon.edit`, the quest's editability and the lock in every command. No action becomes visible that `available_actions` does not name. No new request type is added; the re-reads are the existing quest read.
- **Disclosure.** The section is editor-only; GM-only objectives and notes stay inside it. Nothing new is shown to members.
- **Isolation.** All state is per quest (`quest:<id>` mutation scope). Opening another quest remounts the workspace.
- **Draft preservation.** Typed input survives a stale write (existing), a refused structural save (only the locked fields are set back, with a note) and a declined discard. Discarding happens only on **Discard changes**.
- **Retry identity.** Unchanged: a lost answer retries the same body under the same key; an edited body is a new request.
- **Refusals.** `quest_has_progress` gets a read-only reconciliation; other refusals keep their existing messages.
- **Unknown outcomes.** A lost removal answer stays retryable; closing the dialog re-reads and says the removal may have been applied.
- **Late responses.** A success that lands after the person moved on updates the list and announces once but does not take focus (item 7).
- **Navigation.** The page guard keeps listing a dirty panel ("a stage", "an objective") as today. The discard dialog protects in-section switching.
- **Focus and announcements.** Section 3.2 items 2, 3, 5 and 7. Status notes are polite (`role="status"`); refusals keep their existing alerting.

## 9. Intermediate states

T01 is one commit. Between the implementation and records commits the code is complete; only the records are pending.

## 10. Decisions

Routine choices, made here; none needs the owner.

- **R-1 Stage expansion stays the disclosure for objectives.** Objectives are listed inside their stage; making them visible with the stage collapsed would change the stage card model that existing tests and users rely on. The separation is between each objective's content and its actions, and between the disclosure control and any action.
- **R-2 Discard confirmation rather than blocking.** Disabling other forms while one is open would hide actions; silently keeping two drafts needs two panels. A confirmation mirrors the existing dirty-close pattern.
- **R-3 Disable Remove for the objective being edited.** Simpler and safer than discarding the panel inside the removal flow.
- **R-4 Set back only the locked fields after a lock refusal.** Mirrors C09's clear-only-what-is-invalid approach; wording and visibility remain the person's.
- **R-5 Stage actions stay in the stage body.** Moving them is outside "objective management"; only their Cancel focus and lock reconciliation change.

No blocking product, policy, authorization or contract decision remains.

## 11. Handoffs

### 11.1 Sonnet implementation instructions

1. Confirm the baseline (the plan commit) is HEAD and `origin/phase15/completion`, with a clean worktree.
2. Write the A-cases in the new test file first. Run them at the baseline; record each "fails" case's failing assertion and each guard's pass.
3. Implement section 3.2 in the section 4 files only. Make only section 6.2 adaptations, naming each.
4. Run section 7.1: focused, full `npm test` (first run and any rerun reported separately), lint, `tsc -b`, build, the documentation check and `git diff --check`.
5. Run M1–M8, restoring the exact bytes after each and comparing hashes.
6. Stop and report instead of continuing if: a backend, API or schema change seems needed; `useAuthoringMutation`, `ConfirmDialog` or the page guard must change; an existing expectation outside section 6.2 must change; a guard fails after the change; or an R13b/R13c behavior is touched.
7. Commit with the section 5 subject and push. Record the commit, runs and probe results in section 11.3 and the T01 register row; commit and push the records. CI position: pending checkpoint PR.
8. Do not open or merge a PR, run browser/AX checks, start S02 or any consumer, or record acceptance.

### 11.2 Independent review boundary

Plan commit through the T01 records commit. The reviewer re-runs section 7.1 focused checks and a sample of the probes, and checks section 8.

### 11.3 Implementation record

Implemented by Sonnet at `a05351529bfa923a20a1d1c5451a21c444003b55` on top of baseline `ff9cf13ec2f803e16c5f3b6ebcb4b5ae8f549c9a` (HEAD and `origin/phase15/completion`, clean worktree at start). Portal and documentation only; no backend, API, schema, `useAuthoringMutation`, `ConfirmDialog`, page-guard or R13b/R13c change. No stop condition was reached. No existing test was changed (section 6.2: none needed).

**Files.** `QuestEditor.tsx` (items 1-7), new `QuestEditor.objectiveActions.test.tsx` (18 tests covering A1-A17; A7 is two tests), `docs/reference/portal-behavior.md` (Quest workspace row). No CSS change.

**Baseline run of the new file (before any implementation): 11 failed, 7 passed.**

| Case | Baseline | Failing assertion or note |
|---|---|---|
| A1, A2, A3 | fail | `toHaveFocus` on the opener; focus stayed on the page heading |
| A4 | fail | no dialog "Discard your changes?" |
| A6 | fail | no group "Manage objective Find the map" |
| A7 (only Remove offered) | fail | no group; the none-offered test passes |
| A9 | fail | Remove not disabled |
| A10, A11, A17 | fail | quest read once, expected twice (R6 pattern) |
| A15 | fail | focus moved to `add-objective-s1` in a hidden section |
| A5, A7 (none offered), A8, A12, A13, A14, A16 | guard pass | unchanged behaviour |

A13's "no `canon.edit` mounts nothing" half is not repeated in the new file (the shared harness has no reader setup); it stays guarded by the existing "Quest workspace: players" cases in QuestWorkspace.test.tsx, which passed.

**After implementation.** New file 18/18. Focused set (section 7.1): 7 files, 149 passed. Full `npm test`, **first run: 463 files, 6,008 passed, 0 failed; no rerun was needed.** `npm run lint`, `npx tsc -b`, `npm run build` (existing chunk-size notice only), `uv run python scripts/check_documentation.py` and `git diff --check` pass. One lint error in the first draft (state set inside an effect) was fixed before the commit by adjusting state during render; the tests passed before and after.

**Probes M1-M8** (new file only; bytes restored and hash equal each time; file hash before and after `BEEEAFA1…CEF184`):

| Probe | Failed cases |
|---|---|
| M1 | A1, A2, A3 |
| M2 | A4 |
| M3 | A6, A7 |
| M4 | A10, A11 |
| M5 | A11 |
| M6 | A9 |
| M7 | A15 |
| M8 | A17 |

**Implementation notes for the reviewer.**
- Focus moves go through one `focusLater` helper. A late success moves focus only if the target passes `canTakeFocus` (a section no longer shown is `hidden`) and focus is still on the body, where it was when the action began, inside the section, or inside a dialog. The person's own answer to the two dialogs (Keep it, Keep editing) is treated as theirs and always returns focus.
- The set-back after a lock refusal covers an open existing-objective panel only, as written in item 5; a stage panel's type field is not set back (it is disabled once the read shows the lock).
- Not covered by jsdom: real browser focus, 320 px layout, AX/screen reader, zoom (pending separate events). CI: pending checkpoint PR.

### 11.4 Independent review record

Reviewed `ff9cf13ec2f803e16c5f3b6ebcb4b5ae8f549c9a..a05351529bfa923a20a1d1c5451a21c444003b55`, with records at `7338ff08874ec19282e507d0677c56a0a9953ede`. The three commits are in ancestry order; `phase15/completion` and `origin/phase15/completion` both point at the records commit. The worktree was clean before review. The implementation scope is the three files listed in 11.3; records changes are confined to this plan and the register.

**T01 verdict: CHANGES REQUIRED. S01 verdict: NOT READY.** One Low finding blocks the slice because the specific late-focus acceptance contract in section 3.2 item 7 is not met. No other material defect was demonstrated.

**C10-S01-1 — Late save response can take focus from an independent control in the same section (Low, 3/10).** Trigger: while an objective save is pending, move focus to the still-enabled stage toggle in that section; let the save succeed and close the form. The response then moves focus to the objective heading, despite the user's move. A temporary deferred-response probe reproduced this: expected the stage toggle to retain focus, received focus on `objective-o1`. The helper currently treats every descendant of `sectionRef` (and any dialog) as focus still owned by the action. A15 covers navigation to the Details heading outside that section, so it does not cover this trigger. The toggle is still focusable during save; its handler safely does nothing while the panel is open.

Rubric: supported-path exposure 1 (rare, constrained authenticated editor action during an in-flight save); impact 1 (bounded focus disruption); triggerability 1 (requires this timing and deliberate focus move); detection/recovery 0 (visible and easily recovered); blast radius 0 (one editor action); total 3, Low. Readiness disposition: blocks this slice because item 7 expressly promises that focus moved elsewhere is preserved. Bounded correction: restrict late-response ownership to the originating form/trigger and its own closing dialog, rather than the entire section or any dialog; add a deferred-save regression that moves focus to the enabled stage toggle (and keep A15 and the explicit-answer focus tests).

The §7.1 focused set passed: 7 files, 149 tests. Lint and `tsc -b` passed; build passed with the existing chunk-size notice. The temporary focus probe failed as described and was removed; no production source was changed. The recorded implementation baseline failures and M1-M8 results were inspected, not rerun. The recorded full portal run (463 files/6,008 passed) remains implementation evidence; no full suite was repeated. `uv run python scripts/check_documentation.py` and `git diff --check` pass on the review records. CI remains pending the checkpoint PR; browser/AX/zoom, human review, S02 and acceptance remain outstanding events or gates as specified in section 12.

### 11.5 Correction of C10-S01-1 (Sonnet)

**C10-S01-1: corrected, pending independent confirmation.** Luna's finding, score and verdict in section 11.4 stay as history; S01 is not marked passed.

Correction `d8d0f261c4e90cdf06d871176ffe33de01ff9049` on baseline `7338ff08874ec19282e507d0677c56a0a9953ede` (HEAD and origin agreed at start; Luna's uncommitted section 11.4 and register edits were preserved unchanged and are committed here with these records). Portal only: `QuestEditor.tsx` and the new-case file. No shared hook, `ConfirmDialog`, page guard, backend or API change; save, retry, reconciliation and draft behavior are untouched.

**Change.** `focusLater` no longer treats the whole section and any dialog as focus the action owns. A late settlement moves focus only if focus is on the page body, still on the control the action began from, or inside the form or dialog that control was in (the one the action is closing). Another control, including one in the same section, and an unrelated dialog are not owned. A target in a section no longer shown still cannot take focus (`canTakeFocus`). The person's own dialog answers (Keep it, Keep editing) and Cancel-to-opener still restore focus. The same helper serves objective save, stage save, removal and reorder.

**Regressions added before the fix**, using gated server responses and one zero-delay timer flush (no fixed sleep):

| Case | Baseline (`7338ff08`) | After correction |
|---|---|---|
| R1 objective save settles while the stage toggle has focus; focus stays; "Objective saved" announced once | fail | pass |
| R2 stage save settles while Expand/Collapse all has focus; focus stays | fail | pass |
| R3 objective removal settles while the stage toggle has focus; focus stays, not on Add objective | fail | pass |
| R4 nothing moved focus: the heading still receives it (guard) | pass | pass |
| A1-A17 (18 tests, including A15's outside-section case and the dialog-answer cases A4 and A10) | pass | pass |

R2's first draft focused **Add stage**, which is disabled while a save is pending and so cannot hold focus; it was corrected to the enabled Expand/Collapse all button and the baseline was rerun against the pre-correction file (swapped in and restored, hash equal) to record the failures above.

**Verification.** Focused set (section 7.1): 7 files, 153 passed. Lint, `tsc -b`, build, `uv run python scripts/check_documentation.py` and `git diff --check` pass. **Full `npm test`, first run: 463 files, 6,012 passed, 0 failed; no rerun needed and no failure to attribute.** **Mutation MC1** (restore section-wide ownership: any descendant of the section, or any dialog, counts as owned): R1, R2 and R3 failed; bytes restored, hash equal (`cbd321d3...`).

**Not covered.** An unrelated dialog is not exercised as its own case: while a save is pending the opening controls are disabled, so a competing dialog cannot be opened in jsdom; the ownership test excludes it by construction (only the originating form or dialog is in scope). Real browser focus, AX, zoom, human review and owner acceptance remain separate events. CI: pending checkpoint PR.

**Re-review range for Luna:** `7338ff08874ec19282e507d0677c56a0a9953ede..` the C10-S01-1 records commit (correction `d8d0f261` plus this records commit).

### 11.6 Independent re-review of C10-S01-1 (Codex)

Reviewed baseline `7338ff08874ec19282e507d0677c56a0a9953ede`, correction `d8d0f261c4e90cdf06d871176ffe33de01ff9049`, and records/current `89fc473aab7185243a57bb0ed7acf0b222f8aeeb`. Ancestry is ordered; `phase15/completion` and origin agree at the records commit. The starting worktree was clean. The correction changes only `QuestEditor.tsx` and its objective-actions test; records since the correction change only this plan and the register.

**C10-S01-1 verdict: CONFIRMED CORRECTED. T01 verdict: PASS WITH VERIFICATION LIMITS. S01 verdict: PASS WITH VERIFICATION LIMITS.** The original 3/10 Low score and CHANGES REQUIRED disposition in §11.4 remain historical; this review confirms the correction against that contract. This is not C10 checkpoint acceptance.

**Behavior confirmed.** The shared `focusLater` captures the nearest form/dialog containing the originating element and only considers the current focus owned when it remains on that origin, inside that captured scope, or on the page body (the established lost-focus fallback). The section-wide and arbitrary-dialog ownership branches are gone. Thus a still-enabled stage toggle or Expand/Collapse control receives no late focus from objective save, stage save or removal (R1-R3); when focus has not moved, R4 retains the intended heading focus. The same helper is used for stage/objective writes, removals and reordering. `canTakeFocus` refuses detached, hidden, inert and disabled targets. Quest section navigation moves focus to the newly active heading; A15 verifies a pending removal does not take it back. The mutation hook aborts an in-flight request on unmount/scope change. These controls prevent stale restoration in the exercised navigation path and reject detached targets.

The unrelated-dialog branch was assessed by source inspection, as allowed: `scope.contains(active)` can only match the form/dialog that contained the original control, so an unrelated dialog is not owned. No artificial UI path was added. Explicit Keep it/Keep editing answers use the deliberate `own` path; Cancel still returns to its opener and uses the existing eligible fallback when that opener is unavailable. Correction changes only focus ownership and its regression tests; retry identity, request/save flow, lock reconciliation and newer drafts remain unchanged.

**Evidence.** R1-R3 failed at the correction baseline and passed after the correction; R4 and all 18 A-cases passed at baseline and after. Restoring section-wide/arbitrary-dialog ownership (MC1) failed R1-R3. These are the correction record's controlled-response results; they were inspected, not rerun. The reviewer reran §7.1 focused tests: 7 files, 153 passed. Documentation and diff checks pass. The corrected full run, first run, remains separately recorded as 463 files/6,012 passed; it was not repeated. The earlier implementation run remains historical and is not substituted for correction evidence.

Verification limits: jsdom does not establish real browser focus, AX/screen-reader behavior, layout or zoom. The unrelated-dialog exclusion is source-inspected, not an exercised user path. CI is pending the checkpoint PR. Remaining C10 gates are S02's independent review and B/C cases, one full portal run on final integration executable code, and CI on that exact head; browser/AX/zoom, human review and owner acceptance remain separate events. No acceptance is granted here.

## 12. C10 checkpoint coordination

### 12.1 Order and shared files

- **Order.** S01-T01, then S02-T01, then S02-T02, serially on `phase15/completion`. The order is a scheduling choice: S01 and S02 have no dependency on each other. S02-T01 starts after S01-T01's records commit exists, not after S01's review. S02-T02 starts after S02-T01's records commit.
- **Shared files.** `docs/reference/portal-behavior.md` (each task edits only its own sentences of the Quest workspace row) and `docs/delivery/work-register.md`. `QuestWorkspace.tsx` changes only in S02-T01. No source file is shared between S01 and S02.
- **Baselines.** S01-T01's baseline is the planning commit. Each later task revalidates its own baseline at start: HEAD equals origin, the worktree is clean, the previous task's records commit is present, and the plan's section 2 facts for its files still hold. A changed fact is reported before implementing.

### 12.2 C10 checkpoint merge requirements

The C10 PR may merge only when all of these hold (the register rule; nothing added):

1. S01 and S02 are each independently reviewed, with any corrections confirmed.
2. On the integration head, the acceptance cases A1–A17 (this plan) and B1–B12 and C1–C15 ([S02 plan](p15-c10-s02-quest-completion-plan.md#6-acceptance-cases)) pass, with one full portal run on the final executable code. No backend run is required unless a backend file changed.
3. CI passes on that exact PR head.

### 12.3 Separate events (after the merge; not merge gates)

Browser objective focus and confirmed history ([browser](work-register.md#browser)), [ax](work-register.md#ax) and actual zoom, human review, `p15-integration` and `p15-owner`. None is granted by this plan.

### 12.4 Integration evidence

Recorded 2026-11-25 (Sonnet) against the requirements in section 12.2. Nothing here is CI or acceptance.

1. **Reviews (requirement 1).** S01: PASS WITH VERIFICATION LIMITS (C10-S01-1 corrected and confirmed, section 11.6). S02: T01, T02 and combined S02 PASS WITH VERIFICATION LIMITS (C10-S02-1 corrected and confirmed, [S02 plan section 11.6](p15-c10-s02-quest-completion-plan.md#116-independent-re-review-of-c10-s02-1-codex-2026-11-25)). Original findings, scores and evidence stay in the review sections as history.
2. **Executable code tested.** The last commit that changed anything executable is the C10-S02-1 correction `26885a2040313b5d9258919629e3845e5e187314`. Every commit after it changes only `docs/delivery/p15-c10-s02-quest-completion-plan.md`, `docs/delivery/work-register.md` and this plan (checked with `git diff --name-only 26885a20..HEAD` before this record: the S02 plan and the register only).
3. **One full portal run on that code (requirement 2).** From PowerShell in `C:\Users\nemes\dnd_ai\portal`, first run, run before the correction commit on the same executable files: 466 files, 6,053 passed, 0 failed (recorded in S02 plan section 11.5). It was not repeated for documentation commits. The correction commit also carries one sentence in `docs/reference/portal-behavior.md`, added after that run; it is documentation.
4. **A, B and C cases together on that code.** Re-run at this head as one set: `QuestEditor.objectiveActions.test.tsx` (A1–A17 and the C10-S01-1 cases R1–R4), `QuestProgressPanel.review.test.tsx` (B1–B12 and the progress-only case), `QuestProgressPanel.receipts.test.tsx` (C1–C15 and the progress-only case) and `CampaignQuestDetailPage.guard.test.tsx` (G0–G5, the C10-S02-1 cases): 4 files, 63 passed, 0 failed, one run; every case ID A1–A17, B1–B12, C1–C15 and G0–G5 appears in the verbose result. They also passed inside the full run above.
5. **Static and documentation checks at this head.** `npm run lint`, `npx tsc -b` and `npm run build` pass (existing chunk-size notice only); `scripts/check_documentation.py` and `git diff --check` pass. No backend file changed, so no backend run is required.
6. **Failures, isolated passes and reruns.** No failure occurred in any run listed here or in the full runs recorded for the slices' corrections. Earlier failures, isolated passes and reruns (S01 T01 run history; S02 T02's intermittent C12 test failure and its fix; the S02-1 baseline runs) stay in their own sections. The sequential G4 baseline result in S02 plan section 11.5, where G4 failed in about 66 ms with "element could not be found in the document" and the guard file's isolated baseline runs timed out, is **unexplained**; this record does not assign it a cause.
7. **Limits.** jsdom and router level only. Real-browser focus, `beforeunload`, AX, zoom, human review and owner acceptance are separate events (section 12.3) and are not recorded. Exact-head CI on the checkpoint PR is the remaining merge requirement (3) and is reported on the PR, not in this file.

### 12.5 Merge record (2026-11-25)

- **Merge.** PR #79 merged by the owner at 2026-11-26 03:57:40 UTC (2026-11-25 local) as `ebe6c7241a581cff1e2fac265a3af9230c656fa1`. Its tree equals the reviewed PR head `dabd7d1ab92a1575eb3769e539074ccbab34de8e`. `phase15/completion` was fast-forwarded to the merge; no history was rewritten. Merged is not accepted.
- **Reviews.** S01: PASS WITH VERIFICATION LIMITS. C10-S01-1 (Low, 3/10) stays as found in section 11.4; its correction `d8d0f261c4e90cdf06d871176ffe33de01ff9049` was independently confirmed (section 11.6). S02: T01, T02 and combined S02 PASS WITH VERIFICATION LIMITS. C10-S02-1 (Medium, 6/10) stays as found in [S02 plan section 11.4](p15-c10-s02-quest-completion-plan.md#114-independent-review-record-codex); its correction `26885a2040313b5d9258919629e3845e5e187314` gave the progress-only `CampaignQuestDetailPage` caller the same departure protection while an action is pending or its outcome is unknown, and was independently confirmed ([S02 plan section 11.6](p15-c10-s02-quest-completion-plan.md#116-independent-re-review-of-c10-s02-1-codex-2026-11-25)).
- **Evidence kept separate.** Baseline runs, mutation probes, focused sets and full runs stay in their own sections (11.3–11.6 of each plan). The sequential G4 baseline result (S02 plan section 11.5) remains **unexplained**; no cause is assigned.
- **Integrated acceptance (section 12.4).** A1–A17, B1–B12, C1–C15 and G0–G5 together: 4 files, 63 passed. One full portal run on executable code `26885a2040313b5d9258919629e3845e5e187314`: 466 files, 6,053 passed, first run.
- **CI on the exact head.** Run [45749745899](https://github.com/NemesisGhost/dnd_ai/actions/runs/45749745899) on `dabd7d1ab92a1575eb3769e539074ccbab34de8e` passed all 14 jobs on attempt 1. The checkout log shows synthetic merge `af5e89802d2815885eeb5c1d6a9a132bb3657134` fetched as `pull/79/merge`.
- **Merge push run.** Run `45752166902` on `ebe6c72` completed **success**, all 14 jobs (observed 2026-11-25 with `gh run view`).
- **Pending, none granted.** Browser objective focus and confirmed history, AX and actual zoom, human review, `p15-integration` and `p15-owner` (section 12.3). Existing reliability investigations stay open; none is a C11 prerequisite.

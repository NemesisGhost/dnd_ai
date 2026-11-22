# D/P15-C03-S01 implementation plan: recover failed Knowledge reads without repeating a confirmed save

**Status:** Opus plan prepared 2026-11-22. **Ready for Sonnet.** No owner decision blocks either task. One plan decision changes a behavior the DEF-006 fix described: [PD-1](#pd-1-hold-claim-save-only-for-the-authoring-read). The owner may override it before T01 is reviewed (see §10).

**Register rows:**
- slice [D/P15-C03-S01](work-register.md#p15-c03-s01);
- tasks [T01](work-register.md#p15-c03-s01-t01) and [T02](work-register.md#p15-c03-s01-t02);
- parent checkpoint [D/P15-C03](work-register.md#p15-c03).

**Baseline:** `6ce3cbe34e11acf09310b4fd763d421ef522f35d` ("Merge remote-tracking branch 'origin/main' into phase15/completion").
- It is the head of `phase15/completion` and equals `origin/phase15/completion`. The worktree was clean when read, and `git fetch origin` brought nothing new.
- It already contains the C02 merge:
  - PR #71 was merged on 2026-11-22 at 15:37:44 UTC as `4a580c410d84bb9d5a5a899c5a85c2cccfe19eb4`.
  - The PR head `6c5cadb` and the merge commit `4a580c4` have identical trees. `4a580c4` and `6ce3cbe` also have identical trees.
- CI as read on 2026-11-22:
  - push run `45039370574` on `4a580c4` (`main`) **succeeded**;
  - PR run `45037635978` on the PR head `6c5cadb` **succeeded**.

Sonnet's implementation baseline is the commit that adds this plan, a child of `6ce3cbe`. The handoff prompt names it.

**How each statement was established:**
- by reading source, documents and git/GitHub metadata at the baseline;
- by temporary plan-entry reproductions, as the slice criteria require ("Confirm the specific failed reads in a focused reproduction at plan entry").

The reproductions were Vitest files, written into `portal/src/` only for the run and deleted afterwards. They reused the fixtures of `App.knowledgeClaim.test.tsx` (lines 1–206) and `useKnowledgeDetail.test.ts`. All nine passed as observation scripts, and §2.2 gives their results. No repository file was changed by them, and no application, schema or backend file changed.

**Governing sources:**
- [portal behavior §5.11](../reference/portal-behavior.md#511-authoring-patterns-phase-14). This is the binding contract for:
  - write outcomes and refresh;
  - every other caller (the DEF-001 fix);
  - pages that read more than one thing (`retryFailedReads`, `useRetryFocus`);
  - read states;
  - unsaved changes, including the Knowledge claim page's `PERSPECTIVE_QUERY_CHANGED` and the permission-loss party clean-up;
  - focus and announcements.
- [R05 history](work-register.md#r05--save-error-and-recovery-consistency): the source evidence, remaining work and acceptance.
- [DEF-001, DEF-005 and DEF-006](defects.md): fixed, reviewed behavior that this slice must preserve, except where [PD-1](#pd-1-hold-claim-save-only-for-the-authoring-read) says otherwise.
- The register's [C03 criteria](work-register.md#criteria-p15-c03) and [S01 criteria](work-register.md#criteria-p15-c03-s01).

## 1. Entry readiness

### 1.1 What C03 is

C03 is the adopted checkpoint "Recover Knowledge saves and startup preferences accurately". It has two slices:

| Slice | Outcome | Tasks | Stated prerequisite |
|---|---|---|---|
| [S01](work-register.md#p15-c03-s01) | Recover failed reads without repeating a confirmed save | T01 tracks the outcome of each dependent read for the save that owns it. T02 retries only the outstanding eligible reads, across 403/404, a changed party, navigation and superseded callbacks. | Checkpoint entry criteria; no slice-specific gate |
| [S02](work-register.md#p15-c03-s02) | Confirm a startup preference from a later bootstrap | T01 | Checkpoint entry criteria; no slice-specific gate |

The checkpoint's own prerequisite column is "—", and so is the entry-criteria cell of its [criteria row](work-register.md#criteria-p15-c03).
- **Lineage.** In the [crosswalk](work-register.md#register-p15), C03 is the former "P15-C04-T01 **direct task** · Recovery adoption and Knowledge/startup preference repairs (R05)". Its history is R05/P01 and DEF-001, DEF-005 and DEF-006.
- **Not the same item.** The crosswalk row "P15-C03 · Membership, travel, and temporal behavior" is a previous-register identifier. It is not this checkpoint, and matching numerals confer no identity ([register §Execution stages](work-register.md#execution-stages-and-review-gates)).

**Records that are kept separate.** The records [recovery-map](work-register.md#recovery-map) (the 32-entry party-recovery map) and [router](work-register.md#router) (router isolation) are known limits with no active delivery. They need a demonstrated regression before any change, so neither is in scope.

**Records that depend on C03, not prerequisites of it:**
- [pilot-encounter](work-register.md#pilot-encounter), [pilot-item](work-register.md#pilot-item) and [pilot-time](work-register.md#pilot-time) each wait for "P15-C03 independently reviewed".
- [P15-C21](work-register.md#p15-c21) waits for "P15-C03-S01 independently reviewed".

### 1.2 Readiness verdict

- **S01 is eligible and Ready for Sonnet.**
  - No dependency is inferred from display order.
  - C02's merge is not a stated prerequisite of C03. It is recorded here only because it is in the baseline.
  - No owner decision blocks T01 or T02.
- **S02 is also eligible.** It is independent of S01 and not planned here.
- **C03 merge.** C03 merges only after S01 and S02 are both independently reviewed, its acceptance cases pass, and CI passes on the integration head ([§7.2](#72-c03-checkpoint-merge-requirements-not-s01s-verdict)).

## 2. Verified current behavior

### 2.1 Which saves own which reads

Two saves on the Knowledge claim page (`portal/src/pages/KnowledgeClaimPage.tsx`) read more than one resource back:

| Owning save | Where | Dependent reads after a confirmed write | Row version the next write sends |
|---|---|---|---|
| **Claim save** (`POST …/authoring/knowledge/{id}/update`) | `ClaimForm`, `useAuthoringMutation` `onSuccess`, around line 1021 | **authoring** (`view.refetch()`, `GET …/authoring/knowledge/{id}`) and **detail** (`refreshDetail()`, the audience-safe `GET …/knowledge/{id}`, with the perspective query) | Authoring `row_version`. The detail has none. |
| **Lifecycle step** (`POST …/entities/{id}/lifecycle/{action}`) | `EntityLifecyclePanel` with `pageReportsRefresh`, where the page's `readBack` is passed as `onChanged` (around line 144) | **lifecycle** (`lifecycle.refetch()`), **authoring** and **detail** | Lifecycle `row_version` for the next step. Authoring `row_version` for the next claim save. |

Both saves join their reads with `combineRefetchOutcomes` into one boolean (`behind` or `lifecycleBehind`), and **Load latest** re-runs every read.

**Saves on the page that are not in scope:**
- **Knowledge actions** (`components/knowledge/KnowledgeRoster.tsx`) read a single resource, the audience.
- **Sources** use the shared `EntitySourcesSection`.

### 2.2 Plan-entry reproduction results

| # | Scenario | Observed at the baseline |
|---|---|---|
| P1 | Claim save. The authoring read works and the detail read fails with 500. A new edit is typed, then **Load latest** is used after the detail returns. | **Save stayed disabled** even though the authoring row version was current. Load latest re-read **both** the authoring read (+1) and the detail read (+1). The only announcement heard was "Saved, but the latest data could not be loaded."; **nothing was announced on recovery**. One POST. |
| P2 | Claim save. The authoring read fails with 500 and the detail read works. Load latest is used after the authoring read returns. | Load latest re-read the detail (+1), which had already answered. The only announcement was the "Saved, but…" status. One POST. |
| P3 | Lifecycle step (Submit for review). The lifecycle and authoring reads work and the detail fails. Load latest. | Load latest re-read the lifecycle (+1), the authoring (+1) and the detail (+1). The only announcement was the "Saved, but…" status. One POST. |
| P4 | Claim save, both reads work (control case). | One announcement: "Knowledge claim saved". |
| P5 | Hook level: `useKnowledgeDetail.refresh()` gets 404 under a character and party perspective. | Outcome `failed`, state `unavailable` **without `recheckedPartyId`**, and **0** bootstrap refreshes. |
| P6 | Hook level: the first read gets 404 under the same perspective (control case). | State `unavailable` with `recheckedPartyId: "p"` and **1** bootstrap refresh. |
| P7 / P8 | Claim save, then the detail read-back gets 403 or 404. | The page became "Knowledge unavailable" (correct), but the announcement was **"Saved, but the latest data could not be loaded."**, which describes a refusal as a failure. Focus fell to `body`. |
| P9 | Claim save, then the authoring read-back gets 403. | The editor was removed (correct, DEF-006), with the same "could not be loaded" announcement. Focus fell to `body`. |
| P10 | A new claim text is typed **while the save request is pending**, then the save is confirmed. | The typed text was **discarded**: the claim box showed the server's text. |
| P11 | A new claim text is typed **while the read-back is in flight**, then the read completes. | The typed text was **discarded**. |

### 2.3 Deviations S01 repairs

| ID | Deviation | Evidence | Task |
|---|---|---|---|
| DV-1 | Claim **Save** is held while only the detail read is outstanding, although the authoring row version it would send is current. | P1 | T01 ([PD-1](#pd-1-hold-claim-save-only-for-the-authoring-read)) |
| DV-2 | One notice text ("The latest claim could not be loaded") covers every read, so the person cannot tell which part is behind. | Code; P1–P3 | T01 |
| DV-3 | A write recovered through Load latest is never announced as done. §5.11 requires a "done" announcement when a read completes. | P1–P3 | T01 |
| DV-4 | A confirmed save **clears a newer draft**. `onSuccess` calls `setChanges({})` and `setChangeNote("")` unconditionally. §5.11 says to clear a draft only if it still equals the confirmed body. | P10, P11 | T01 |
| DV-5 | **Load latest re-reads reads that already answered.** §5.11 says Try again reads again only the reads that failed (`retryFailedReads`). | P1–P3 | T02 |
| DV-6 | A 403 or 404 on a read-back is announced as a failed read, focus is lost, and no safe confirmation of the write remains. §5.11 says a denied or unavailable read-back is an authoritative result: the retained content is dropped, nothing is held, and the write is still announced. | P7–P9 | T02 |
| DV-7 | A **post-save** detail 404 under a party perspective skips the party recheck that the first read performs. A party the change revoked ends on "Knowledge unavailable" instead of being dropped from the address and the claim read again. | P5 vs P6 | T02 |
| DV-8 | A `superseded` read outcome is shown as "behind". `setBehind(outcome !== "ok")` shows the could-not-load notice and holds Save although no read failed, and `loadLatest` keeps `behind` on `superseded`. | Code reading only; T02 must first prove it with a failing test | T02 |
| DV-9 | A successful Load latest removes the button that held focus, and focus falls to `body`. `SavedRefreshFailedNotice` does not use `useRetryFocus`. | Code reading only; T02 must first prove it with a failing test | T02 |

### 2.4 Reviewed behavior that must not regress

These come from DEF-006, DEF-005 and CP-10, and are covered today by `App.knowledgeClaim.test.tsx` lines 599–787 and 1050–1084:
- The editor is kept through a recoverable authoring failure (`useKeptData`), and Save is held while that read is outstanding.
- A 403 or 404 on the authoring read removes the editor and its draft, and leaving the page is then not guarded.
- `claimDirty` is measured against the kept view, so the unsaved-changes guard covers an edit on a retained editor.
- The stale-write (409) **Load latest version** path keeps the user's draft in a read-only panel.
- No write is ever repeated, and `useAuthoringMutation` keeps its key and retry semantics.
- After a failed read-back, the status "Saved, but the latest data could not be loaded." is heard once, and "Knowledge claim saved" is not heard before the reads complete.
- The first-read party recovery and the boundary's `onPartyRevoked` work as before, and so does the `PERSPECTIVE_QUERY_CHANGED` guard.
- The lifecycle panel offers no step while the lifecycle read is not `ready` (`NO_LIFECYCLE`).

## 3. Outcome, scope and exclusions

### 3.1 User outcome

After a confirmed claim save or lifecycle step on the Knowledge claim page:
1. **Each read reports separately.** Every dependent read of that save is tracked on its own. When some fail, the saved notice says which part may be out of date, and the claim's editing stays available unless the read it depends on is outstanding.
2. **The save is never repeated.** Load latest reads again only the reads that are still outstanding, under the current perspective, and never sends the write.
3. **The write is announced as done once.** This happens when its last outstanding read is applied, whether by Load latest or by any later applied read of the same resource. It never happens twice, and never for an episode that has ended.
4. **A refusal is a result, not a failure.** If a read-back answers 403 or 404, the content that read protected is dropped immediately and nothing is held. A non-disclosing confirmation of the write stays visible, and the write is announced once.
5. **Party recheck after a save.** If the post-save detail read gets 404 under a party perspective, the party is rechecked exactly as on the first read. A revoked party is removed from the address by the existing permission-loss clean-up, and the claim is read again without it.
6. **Newer drafts survive.** Text typed while the save or its read-back was in flight is kept as an unsaved draft against the newly read version.
7. **Late answers change nothing.** A late or superseded answer never clears or announces a newer episode, and never applies to another record, perspective or user.

### 3.2 In scope

- Portal only: the Knowledge claim page, its detail hook and boundary, and their tests.
- An optional, additive retry-focus prop on the shared `SavedRefreshFailedNotice`, so Knowledge can use `useRetryFocus`. The default stays as it is: no existing caller changes.
- A Knowledge-local outcome distinction between a refused (`closed`) read and a recoverable (`failed`) one. Shared `RefetchOutcome` and `combineRefetchOutcomes` stay unchanged.
- Documentation:
  - the Knowledge sentences in [portal behavior §5.11](../reference/portal-behavior.md#511-authoring-patterns-phase-14);
  - a dated note under DEF-006 in [defects.md](defects.md) recording PD-1;
  - Sonnet's implementation record in §11.3 of this plan and in the register rows.

### 3.3 Exclusions

- **S02** (startup preference) and any other domain's multi-read save: quests, the World record workspace, events, items, the shared `EntitySourcesSection`, and the relationship editor. Those migrate with their own domain checkpoints, per R05's remaining work.
- **No shared-hook behavior changes.** `useAuthoringMutation`, `useConfirmedRefresh`, `useAuthoringResource`, `retryFailedReads`, `combineRefetchOutcomes`, `useKeptData` and `usePartyNotFoundEpisodes` keep their behavior. If an implementation seems to need a shared behavior change, **stop and report**: do not widen scope.
- **Out-of-scope records and features.** The 32-entry party-recovery map ([recovery-map](work-register.md#recovery-map)), [router](work-register.md#router) isolation, the [pilot](work-register.md#pilot-encounter) adoptions, the roster's single-read actions, and the invitation-token receipt policy.
- **The C02 focus uncertainty.** `usePageArrival` possibly taking focus after a real interaction ([C02 readiness §4](p15-c02-checkpoint-readiness.md#4-the-provisional-cancel-focus-issue-against-the-checkpoint-criteria)) is not diagnosed or fixed here. S01's focus moves must not compete with it (§8).
- **No backend, API, schema or route change.** No new endpoint, field or error code is needed.
- Not started here: `copy-ui`, `preview`, browser/AX runs, `actor-a`, `p15-owner`, and the pilots.

## 4. Affected files and interfaces

| File | Change | Task |
|---|---|---|
| `portal/src/pages/KnowledgeClaimPage.tsx` | Replace the `behind`/`lifecycleBehind` booleans with a per-save, per-read episode record (below). Hold claim Save only while the authoring read is outstanding (PD-1) or the page's authoring read is `stale`. Name the outstanding parts in the notice. Clear the draft only where it still equals the confirmed body. Announce done once. | T01 |
| `portal/src/hooks/useKnowledgeSaveReads.ts` (new; the name is Sonnet's choice) | A Knowledge-local tracker that holds, for each open save episode, its done message and each read's state: `applied`, `outstanding`, `pending` (superseded, waiting for the newer read) or `closed`. A later applied read of the same resource satisfies it for every open episode. It reports whether an episode is complete, closed or held, and makes the one-time announcement. | T01 (states and completion), T02 (`pending`, `closed` and retry selection) |
| `portal/src/hooks/useKnowledgeDetail.ts` | `refresh` tells a refusal apart from a recoverable failure. Either return a Knowledge-local `"closed"` or expose the applied state through a Knowledge-local result type; the shared `RefetchOutcome` is not widened. A 404 under a character and party runs the same `usePartyNotFoundEpisodes` recheck as the first read, with an episode key distinct per refresh, so one refresh never rechecks twice and a later refresh is a new episode. To let a later applied detail read be observed, expose a monotonic applied-read marker (like `startedSeq`). | T02 (closed, party recheck); T01 (marker, if the tracker observes it) |
| `portal/src/components/KnowledgeDetailBoundary.tsx` | Show a non-disclosing confirmation ("Your change was saved.") on the unavailable state when that state follows a confirmed save in this mount. Give the terminal heading focus once, only if focus has been lost (§8). | T02 |
| `portal/src/components/authoring/feedback.tsx` | An optional prop that wires `useRetryFocus` into `SavedRefreshFailedNotice`. Without it, behavior is unchanged. | T02 |
| `portal/src/App.knowledgeClaim.test.tsx`, `portal/src/hooks/useKnowledgeDetail.test.ts`, a new tracker test | The cases in §6. | T01, T02 |
| `docs/reference/portal-behavior.md` §5.11 | The Knowledge claim page tracks its reads separately (DV-1 to DV-9 as fixed). | T01, T02 |
| `docs/delivery/defects.md` (under DEF-006) | A dated note: the detail-only hold was narrowed by PD-1 in C03-S01, with the SHA. | T01 |

Commands, routes and server contracts are unchanged.

## 5. Task commits

| Task | Commit subject (suggested) | Contents |
|---|---|---|
| T01 | `P15-C03-S01-T01: track each Knowledge read-back separately for the save that owns it` | Fixes DV-1 to DV-4. Adds the tracker states `applied`/`outstanding`. Hold, notice wording, done-once, and draft preservation. Cases A1–A14. Docs. |
| T02 | `P15-C03-S01-T02: retry only outstanding Knowledge reads across refusal, party change, navigation and superseded answers` | Fixes DV-5 to DV-9. Adds `pending` and `closed`. Retry selection, refusal handling with safe confirmation and focus, the party recheck on refresh, navigation and supersession, and retry focus. Cases B1–B18. Docs. |

**Intermediate state after T01.**
- Load latest still re-reads every read, as at the baseline (DV-5 remains).
- Refusals are handled as they are today (DV-6 remains).
- Everything T01 adds is correct on its own: the hold, the wording, done-once and the draft. The suite passes.

## 6. Acceptance cases

Each case is an automated test unless it says otherwise. "Heard" means the text of the shared announcer (`data-testid="authoring-announcer"`). Record every distinct message across the case, not only the last. A `MutationObserver` like the plan-entry reproductions is acceptable.

**Test-first evidence.**
- Cases marked **(fails at baseline)** must be shown failing before the fix, with the failure noted in §11.3.
- For DV-8 and DV-9, the failing test is the required proof. If it cannot be made to fail at the baseline, record that, drop the change, and report it. Do not ship an unproven fix.

### 6.1 T01: separate outcomes (A1–A14)

| # | Case | Expected |
|---|---|---|
| A1 | Claim save; authoring ok, detail fails with 500. **(fails at baseline)** | The notice names the claim's details (not "the claim") as possibly out of date. **Save is enabled for a new edit** (PD-1). One POST. Heard: the "Saved, but…" status once, and not "Knowledge claim saved". |
| A2 | As A1, then a new edit is saved. | The second POST carries `expected_row_version` from the recovered authoring read (2), not the old one. |
| A3 | Claim save; authoring fails with 500, detail ok. | The notice names the claim's editor/version. Save is held, and an edit typed meanwhile is kept and counted as unsaved. |
| A4 | Claim save; both reads fail. | The notice names both parts. Save is held. |
| A5 | A1, then the detail recovers through Load latest. **(fails at baseline)** | The notice goes away. "Knowledge claim saved" is heard **exactly once** across the whole case. No second POST. |
| A6 | A3, then the authoring read recovers. **(fails at baseline)** | Save is enabled. Done is heard once. The edit typed meanwhile survives. |
| A7 | A4, then the authoring read recovers but the detail does not. | Save is enabled. The notice now names only the details. Done is not heard. |
| A8 | Lifecycle step; the detail fails. **(fails at baseline)** | The notice names the details. On recovery the step's own done message (e.g., "Submitted for review") is heard once. No second POST. |
| A9 | Lifecycle step; the authoring read fails. | Claim Save is held. Lifecycle steps are offered from the fresh lifecycle read. |
| A10 | A new claim text is typed while the save POST is pending. **(fails at baseline: P10)** | After confirmation, the new text is still in the box and counted as unsaved, against the new row version. The field that was saved, and now equals the server, is no longer marked changed. |
| A11 | The same as A10, typed during the read-back. **(fails at baseline: P11)** | The same result. |
| A12 | The change note equals the confirmed body. | The note is cleared. A note edited after the submit is kept. |
| A13 | Claim save; the authoring read fails. A later authoring read that was **not** started by this episode is applied, e.g. the stale-write path's `refetch`. | That read recovers the episode: Save is enabled and done is heard once. |
| A14 | Two episodes in one mount: a claim save whose detail fails, then a lifecycle step whose reads all work. | The lifecycle step's done is heard. The claim episode completes from the step's detail read and announces its own done once. No episode announces twice. |

### 6.2 T02: retry and terminal outcomes (B1–B18)

| # | Case | Expected |
|---|---|---|
| B1 | A1, then Load latest. **(fails at baseline: P1)** | Only the detail read is sent: the authoring call count is unchanged. |
| B2 | A3, then Load latest. **(fails at baseline: P2)** | Only the authoring read is sent. |
| B3 | Lifecycle step with the detail failing (P3), then Load latest. **(fails at baseline)** | Only the detail is re-read. The lifecycle and authoring counts are unchanged. |
| B4 | Load latest is clicked twice quickly. | One read per outstanding resource. The button is busy. |
| B5 | Load latest fails again. | The notice stays. Focus stays on the button. Nothing is announced again. |
| B6 | Load latest succeeds while the button has focus. **(prove first: DV-9)** | Focus goes to the page `h1` once (`useRetryFocus`), not to `body`. If the person had moved focus elsewhere first, it does not move. |
| B7 | Claim save; the detail read-back gets 403. **(fails at baseline: P7)** | "Knowledge unavailable" is shown and nothing about the claim remains. A non-disclosing "Your change was saved." is shown, containing no statement, name or id. "Knowledge claim saved" is heard once, and the "could not be loaded" status is **not** heard. Focus is on the terminal `h1` if it had been lost. One POST. |
| B8 | The same with 404 and no party in the address. **(fails at baseline: P8)** | The same as B7, and byte-identical to B7 apart from the status code: the 404 and 403 presentations do not differ. |
| B9 | Claim save; the authoring read-back gets 403 (P9). | The editor and draft are removed (preserved behavior). The safe confirmation is shown and done is heard once, without the "could not be loaded" status. Nothing is held, and leaving is not guarded. |
| B10 | Hook level: `refresh()` gets 404 under a character and party; the bootstrap refresh no longer lists the party. **(fails at baseline: P5)** | One bootstrap refresh. The result carries the rechecked party, and the boundary calls `onPartyRevoked`. |
| B11 | App level: the B10 situation after a claim save. | The party is dropped from the address under permission-loss clean-up: no "Discard unsaved changes?" prompt, and history is replaced. The claim is read again without the party. The write is announced once. No second POST. |
| B12 | The B10 situation, but the party is still authorized. | A genuine unavailable result (B8 behavior). No address change. |
| B13 | The B10 situation, but the bootstrap refresh fails. | The read is a recoverable failure: the notice appears with Load latest. Nothing is dropped. |
| B14 | The same 404 episode is reached twice, e.g. the effect re-runs. | Exactly one bootstrap refresh for that refresh episode. A later Load latest is a new episode. |
| B15 | A read-back answer is `superseded` because a newer read of the same resource started. **(prove first: DV-8)** | No could-not-load notice for that read alone. It is satisfied or failed by the newer read's answer. The done-once rule holds. |
| B16 | The person changes the character perspective deliberately (clean form) while a read-back is outstanding. The old detail read then answers late. | The late answer does not apply to the new perspective's page. Nothing from the old episode is announced. No write is repeated. |
| B17 | The page unmounts (navigation to the Knowledge list) while a read-back is in flight. | Nothing is announced after unmount and no state warning. The write is not repeated. |
| B18 | The user, session owner or campaign changes while an episode is open. | No old episode's state is shown or announced under the new owner. This follows `useAuthoringResource`'s existing owner reset. |

### 6.3 Mutation probes (run by Sonnet; re-run by the reviewer)

Each probe is a temporary source change. Make it, run the named cases, confirm they **fail**, and revert. Record the result in §11.3.

| Probe | Must fail |
|---|---|
| M1: Re-join the reads with `combineRefetchOutcomes` and hold Save on any outstanding read. | A1, A7 |
| M2: Restore the unconditional `setChanges({})` in `onSuccess`. | A10, A11 |
| M3: Remove the once-guard, so done is announced on every applied read. | A5, A14 |
| M4: Make Load latest re-read every read. | B1–B3 |
| M5: Treat `closed` as `failed`. | B7–B9 |
| M6: Remove the party recheck from `refresh`. | B10, B11 |
| M7: Treat `superseded` as failed. | B15 (only if DV-8 was proven) |
| M8: Drop the episode or owner check on a late answer. | B16 or B18 |

## 7. Verification

### 7.1 Per-commit checks (Sonnet; repeated by the reviewer)

Run from `portal/` with a `C:\…` (uppercase) working path. Vitest at the baseline failed to load a suite started from a lowercase `c:/` path ("failed to find the current suite").
- The focused files: `npx vitest run src/App.knowledgeClaim.test.tsx src/hooks/useKnowledgeDetail.test.ts <tracker test> src/components/authoring` plus any shared test the change touches.
- The full portal suite, `npm test`. The portal suite is load-sensitive ([C02 readiness §4](p15-c02-checkpoint-readiness.md#4-the-provisional-cancel-focus-issue-against-the-checkpoint-criteria)), so record the first run and any rerun separately, with failing test names. Do not call a rerun pass a first-run pass.
- `npm run lint` and `npm run build`.
- `uv run python scripts/check_documentation.py` and `git diff --check`.
- The backend is unchanged, so no shard run is required for these commits. CI runs everything on the pushed head, and that run is what counts.

### 7.2 C03 checkpoint merge requirements (not S01's verdict)

S01's review verdict covers S01 only. **C03 may merge** when:
1. **Slice reviews.** S01 and S02 are each independently reviewed (Luna), including any re-review of a correction.
2. **PR acceptance cases pass.** These are the S01 and S02 acceptance cases. There is also one integration check: a full portal run on the integrated head that shows the S01 Knowledge recovery and the S02 startup-preference tests together.
3. **CI passes** on the exact integration head, with the synthetic PR merge recorded as such and any rerun recorded separately.

Re-review the affected ranges after any conflict resolution or material base change. The merge is the owner's event.

### 7.3 Separate events (after the merge; not merge gates)

- **Integrated-head [browser](work-register.md#browser)**: "save recovery" persona checks at the final head, after [p15-integration](work-register.md#p15-integration). [ax](work-register.md#ax) and [b16](work-register.md#b16) cover:
  - the polite status and done announcement with a real screen reader;
  - focus after Load latest and after a refusal;
  - whether `usePageArrival` competes with a real early interaction (the C02 uncertainty).
- **Pilot adoptions** ([pilot-encounter](work-register.md#pilot-encounter), [pilot-item](work-register.md#pilot-item), [pilot-time](work-register.md#pilot-time)), each recorded per consumer once C03 is independently reviewed.
- **Owner acceptance** at [p15-owner](work-register.md#p15-owner).

None of these is claimed or started by this plan.

## 8. Authorization, disclosure, concurrency and focus rules

- **Server authority.** The portal infers no access. A refusal is whatever the server answered: 403 means denied, 404 means not available (the same presentation for both on the detail). A withheld gated read (`useGatedAuthoringResource` while `canPrepare` is false) is not part of any episode: it is not the caller's read (§5.11 "a read that is not the caller's to make … is not part of the outcome").
- **Clearing on refusal.** Content from a refused read is dropped in the render that sees the refusal. Only the safe confirmation stays, and it contains no statement, name, identifier or field value. A typed draft on a removed editor is dropped (the existing DEF-006 rule).
- **No repeated write.** No path in either task calls `mutation.submit`, `mutation.retry` or a lifecycle action except a person's own new submit. Every case checks the POST count.
- **Read identity.** A retried read uses the current campaign, claim, character and party. An outstanding read from an episode whose perspective, record or owner has changed is abandoned, not retried (the "eligible" reads in T02's title).
- **Episode identity.** Each confirmed save creates one episode with its own identity. An answer settles only the episode or episodes still open for that resource. Ending or completing one episode never touches a newer one: this is the DEF-005 lesson.
- **Focus.** Focus moves only in two cases:
  - **retry success:** `useRetryFocus`, to the page `h1`;
  - **refusal:** to the terminal or page `h1`.

  In both cases it moves only if focus is on `body` or null when checked. It never moves on a background read, a re-render or a failed retry. These rules do not add a second arrival-focus mechanism.
- **Announcements:**
  - one "Saved, but…" status when a read-back first fails recoverably (existing);
  - exactly one done message per write, on completion or on refusal;
  - nothing for a superseded, abandoned or unmounted episode.

  The visible notice stays a non-live region (`quiet`), so nothing is announced twice.

## 9. Intermediate states

- **Baseline → T01.** The page is correct for hold, wording, done-once and drafts. Load latest still over-reads and refusals still announce "could not be loaded" (both are fixed by T02). No user-visible regression.
- **T01 → T02.** All of §3.1 holds.
- **No partial commit** may leave Save enabled while the authoring row version is unknown, or let a draft be cleared that differs from the confirmed body.

## 10. Decisions

**No owner decision blocks this slice.** The authorization, contracts and scope are unchanged.

### PD-1: hold claim Save only for the authoring read

**Decision.** Claim **Save** is held while the authoring read is outstanding or stale, and not while only the audience-safe detail read is outstanding.

**Basis.** The adopted S01 criterion is "Hold editing while required row versions are stale". The detail carries no row version. The save body and its `expected_row_version` come only from the authoring view, and the server rejects a stale version with 409, which the existing stale-write path handles. While the detail is outstanding, the notice still says the details may be out of date.

**What it changes.** The DEF-006 disposition text in [defects.md](defects.md) describes the reviewed fix as holding Save "until the required reads (authoring and detail) both work". PD-1 narrows that, so it is called out rather than made silently.

**If the owner prefers to keep the detail hold:**
- Before T01 is reviewed, record "PD-1 = keep".
- A1 then expects Save to stay held.
- Mutation probe M1 changes to "un-hold on detail" and must fail A1.
- Nothing else in the plan changes.

### Routine choices made here (not owner decisions)

| # | Choice | Basis |
|---|---|---|
| R-1 | Done is announced on recovery, after the earlier "Saved, but…" status. | §5.11 and `useConfirmedRefresh`: a done announcement when a read completes. DEF-006's assertion that done is not heard on the first failure is preserved. |
| R-2 | A refusal on a read-back announces done and shows a safe confirmation. | §5.11: an authoritative result, and the write is still announced (the World Sharing precedent). The visible confirmation satisfies the criterion "keep safe confirmation". |
| R-3 | The party-revocation path uses the existing permission-loss clean-up, so a draft on a removed perspective is dropped, as on the first read. | §5.11 unsaved changes: the party clean-up is permission loss. |
| R-4 | The `closed` outcome is a Knowledge-local type. The shared `RefetchOutcome` is not widened. | Twenty-plus other consumers would otherwise need to be checked. |
| R-5 | The retry focus is an optional prop on the shared notice. | It is additive and changes no other caller. |
| R-6 | Notice copy, decided by Sonnet within these constraints. | It names a part ("the claim's details", "the claim's editor", "the claim's status") and contains no record text. |

## 11. Handoffs

### 11.1 Sonnet implementation instructions

1. **Start.** Begin from the baseline named in the handoff prompt. Confirm it is the head of `phase15/completion`, that the worktree is clean, and that origin matches.
2. **Read first:**
   - this plan;
   - [portal behavior §5.11](../reference/portal-behavior.md#511-authoring-patterns-phase-14);
   - DEF-005 and DEF-006 in [defects.md](defects.md);
   - `KnowledgeClaimPage.tsx` (lines 100–200 and 960–1206), `useKnowledgeDetail.ts`, `KnowledgeDetailBoundary.tsx`, `useConfirmedRefresh.tsx`, `useAuthoringMutation.ts`, `useAuthoringResource.ts` (including `retryFailedReads`), `useRetryFocus.ts` and `usePartyScopeRecovery.ts`;
   - the existing tests at `App.knowledgeClaim.test.tsx` lines 599–787 and 1050–1084.
3. **T01.**
   - Write the cases marked **(fails at baseline)** first and record their failures.
   - Implement T01 (§4, §5), make A1–A14 pass, run §7.1, and run mutation probes M1–M3.
   - Update the docs rows in §4.
   - Commit with the T01 subject. Record the SHA, the first and any rerun results, and the probe results in §11.3 and in the register's T01 row.
4. **T02.** The same procedure for B1–B18 and M4–M8, with one addition first. Prove DV-8 and DV-9 with failing tests. If either cannot be made to fail, do not implement its fix: record that and report.
5. **Stop and report** instead of improvising if:
   - a shared hook's behavior would have to change;
   - a backend or API change seems needed;
   - an existing §2.4 test has to change its assertion, other than A1's hold under PD-1;
   - PD-1 is overridden.
6. **Push.** Push `phase15/completion` after each task commit, and record the CI run id and result for each exact head. Do not open, merge or mark ready any PR unless the owner asks. Do not start `copy-ui` or `preview`, run browser/AX, or mark any acceptance.

### 11.2 Independent review boundary (Luna)

- **T01:** from the plan commit (Sonnet's baseline) to the T01 SHA.
- **T02:** from the T01 SHA to the T02 SHA.
- **Combined S01:** from the plan commit to the T02 SHA, including the interactions between the tracker, the shared notice prop, the boundary and the existing DEF-005/DEF-006 behavior.

The reviewer re-runs §7.1 and the probes. They check §2.4 for regressions and §8 for disclosure, write repetition and focus competition. They also confirm that no shared hook behavior changed: every existing test is unmodified except where §11.1 step 5 allows.

The verdict covers S01 only. C03's merge is judged separately (§7.2).

### 11.3 Implementation record (Sonnet; pending)

Pending. Sonnet records, for each task:
- the SHA;
- the test-first failures;
- the first and any rerun results, kept separate;
- the mutation-probe results;
- lint, build and documentation checks;
- the CI run id and its exact head.

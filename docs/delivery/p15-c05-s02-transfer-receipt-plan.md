# D/P15-C05-S02 implementation plan: retain safe ownership-transfer feedback

**Status:** Opus plan prepared 2026-11-24. **T01 implemented (§11.3); independent review pending, not accepted.** No owner decision blocks the task. Section 10 lists the routine choices made here; none changes a product policy, an API contract, authorization or account discoverability.

**Register rows:**
- slice [D/P15-C05-S02](work-register.md#p15-c05-s02);
- task [T01](work-register.md#p15-c05-s02-t01);
- parent checkpoint [D/P15-C05](work-register.md#p15-c05).

**Plan-entry head:** `082b8eff506b8631e9e99ae5ad02e7b7c574ae0d` on `phase15/completion`, the S01 review-records commit on top of S01's reviewed head `44407e5c96d14e65340fe7d3591483e67843f2b1` (implementation `d7e0886` plus correction `755f05c`). So this plan is prepared against the completed S01 implementation, as the register's scheduling note asks. Clean worktree. No C05 CI run exists; the checkpoint PR has not been opened.

Sonnet's implementation baseline is the commit that adds this plan, a child of `082b8ef`. The handoff prompt names it.

**How each statement was established:**
- by reading source, tests and documents at the plan-entry head;
- by a temporary plan-entry reproduction (§2.2): one Vitest file, written into `portal/src/pages/` only for the run and deleted afterwards. It rendered the real `WorldSharingPage`, `useAuthoringMutation` and feedback components with a stubbed `fetch` and the harness session (`renderAuthoringRoutes` with `onRefresh`). No repository file was changed by it.

**Governing sources:**
- [R08](work-register.md#r08--world-sharing): "transfer can remove the acting user's own authority"; acceptance "retained transfer receipt after losing access, unknown/replay behavior, retained-owner-role options and last-owner invariants. Do not rebuild the existing transfer backend solely to reorganize the page."
- The register's [C05](work-register.md#criteria-p15-c05) ("Transfer and authority-loss browser evidence"), [S02](work-register.md#criteria-p15-c05-s02) ("Verify last-owner invariant, unknown outcome and no repeat of confirmed transfer") and [T01](work-register.md#criteria-p15-c05-s02-t01) ("Reconcile transfer receipt and retained-role options across loss of access") criteria.
- [S01 plan](p15-c05-s01-sharing-panels-plan.md) §3.2 and its reviewed implementation: the `Operation` descriptors (including `{op:"transfer", login, retain}`), per-field edit counters, truthful sharing feedback, 403/404 and unknown re-reads for rows, and the single `SharingDepartureGuard` ("a later reason (S02) is added here, never as a second blocker").
- [Portal behavior §4.3a](../reference/portal-behavior.md#43a-scoped-roles-in-the-portal-adr-0020) and the confirmed-write contract: "A denied or unavailable answer to the read-back is an authoritative result … (World Sharing after an ownership transfer)."
- The transfer API, unchanged (`src/dnd_ai/api/world_sharing.py`, `src/dnd_ai/commands/world_access.py`, `src/dnd_ai/api/world_access.py`):
  - `POST /worlds/{id}/ownership-transfer` `{login_name, retain_previous_owner_as}` (`world_editor|world_reviewer|world_reader|world_viewer|null`) → **200** `{world_id, previous_owner_user_id, new_owner_user_id, retained_role_code}`;
  - one transaction under the world row lock: the target must be an active local account (409 `world_role_target_ineligible`), not the caller (409 `invalid_ownership_transfer`), and hold system GM (409 `target_requires_system_gm`). It opens the target's Owner row **before** ending the caller's, then optionally opens the retained role, so the world is never left without an Owner;
  - the route dependency checks `world.transfer` **before** the idempotency store: no authority on the world → **404**, authority without the capability → **403**. Consequently a same-key retry of a transfer that has already committed is **refused (403/404), not replayed**: it can never be applied twice, but its answer is not a receipt;
  - after a transfer the caller no longer holds `world.share`, so `GET /worlds/{id}/access` answers 403 (some role remains, such as the retained one) or 404 (none);
  - a world role grants capabilities only from the Owner row for `world.transfer`, so a caller who still reads `may_transfer: true` still holds Owner.
- Capabilities that a transfer changes are also held elsewhere in the portal: the workspace hierarchy's world read (`useWorkspaceHierarchy().world`, the sidebar's Sharing entry; `refetchWorld`) and the session bootstrap's per-campaign `world_capabilities` (`useSession().refresh`, in place, no unmount).
- Not in scope: [account-search](work-register.md#account-search) (unresolved policy; no lookup is added) and [atomic-roles](work-register.md#atomic-roles) (an unadmitted system-role proposal).

## 1. Entry readiness

C05 has no checkpoint prerequisite (S01 plan §1). S02's prerequisite is "Checkpoint entry criteria; no additional slice-specific gate", confirmed at `720fc6e`. S01 is independently reviewed PASS WITH VERIFICATION LIMITS (S01 plan §11.6); S02 does not depend on that verdict, but builds on S01's code because both edit `WorldSharingPage.tsx`.

**Verdict: S02 eligible and ready for Sonnet.**

## 2. Verified current behavior

### 2.1 How a transfer works today (after S01)

- The Transfer form (`may_transfer` only) takes a login and "Keep me on the world as" (No role / Editor / Reviewer / Reader / Viewer), then opens a confirmation dialog: "The new owner takes over sharing and settings for this world, and your own Owner role ends." plus "You keep the ‹Role› role." when one is chosen.
- Confirming sends `{op:"transfer"}` through the page's one mutation (S01 descriptor, its own key). On 200 the shared `onSuccess` re-reads the access list and announces the fixed "Ownership transferred" (immediately on "ok", or through `useAnnounceWhenRead` on the read's denial).
- The access read after a transfer is denied, so `useKept` drops the list and `SharingContent` unmounts. The page shows `ReadTerminal` ("You do not have access to the sharing list") and focuses the `h1`. Nothing on screen names the new owner or the role that was kept.
- S01's refusal/unknown re-read effect returns early for `transfer` ("The transfer keeps its own feedback (S02)"). A transfer error shows `MutationStatusMessage` in the dialog. For a network/5xx error it offers **Retry** (same key), promising "Retrying sends the same request, which will not be applied twice."
- `SharingDepartureGuard` asks while any write is pending ("Leave while this change is being saved?"). It does not ask after an unknown transfer.
- Nothing refreshes the session bootstrap or the hierarchy's world read after a transfer.

### 2.2 Plan-entry reproduction results

Temporary file `portal/src/pages/zzC05S02Repro.test.tsx`, run from `C:\Users\nemes\dnd_ai\portal`: **1 file, 6 tests passed** (each asserts current behavior). The file was then deleted; `git status` was clean.

| # | Reproduction | Observed |
|---|---|---|
| Q1 | Confirmed transfer to `erin` keeping Editor; access read then 403 | "You do not have access to the sharing list"; "Ownership transferred" announced; no text names `erin` or the Editor role; focus on the `h1`. |
| Q2 | Same | The session `refresh` was never called. |
| Q3 | Transfer answered 500 | The dialog shows "…Retrying sends the same request…"; the access list is not re-read. |
| Q4 | Q3, then Retry answered 403 (as a committed transfer answers) | The same key is re-sent; the dialog says "You do not have permission to do this…"; still no re-read. |
| Q5 | Q3, Cancel, then a sidebar link | Navigation happens with no question. |
| Q6 | Transfer with "No role" | The dialog says only "…your own Owner role ends." |

### 2.3 Deviations S02 repairs

- **DV-1 (no receipt after loss of access).** A confirmed transfer leaves no record of who received ownership or what the person kept, once the page loses access (Q1). R08 asks for a retained receipt.
- **DV-2 (unknown not reconciled).** An unknown transfer is never re-read (Q3), although the access read settles whether the caller is still an Owner.
- **DV-3 (refused retry misreported).** A same-key retry of a transfer that had committed is refused by design, and the page reports that refusal as a permission problem (Q4), the opposite of what happened.
- **DV-4 (stale access elsewhere).** The session bootstrap's `world_capabilities` and the sidebar's world read keep the old Owner capabilities after a transfer (Q2).
- **DV-5 (departure after unknown).** Leaving after an unknown transfer asks nothing (Q5); the person loses the only page that can reconcile it.
- **DV-6 (retained-role consequence unclear).** With "No role", the dialog does not say the person will keep no role, and it ignores a non-Owner role they already hold (Q6).

### 2.4 Reviewed behavior that must not regress

- All of S01 (its §3.2, cases C1–C22 and review §11.4–§11.6): descriptors and keys, edit-counter clearing, truthful role/hosting sentences, refusal and unknown re-reads for rows, hosting copy, the single page guard, content keyed by account and world. S01's tests keep their expectations.
- Existing `WorldSharingPage.test.tsx` transfer cases keep their expectations except those §4 names.
- `useAuthoringMutation`, `useConfirmedRefresh`, `useKept`, `useAnnounceWhenRead`, `usePageArrival`, `useUnsavedChangesGuard`, `navigationHolds`, `ConfirmDialog`, `WorkspaceHierarchyContext` and `useSession` are unchanged (used, not edited).

## 3. Outcome, scope and exclusions

### 3.1 User outcome

An Owner confirms a transfer knowing exactly what they will keep. When the server confirms it, the page keeps a receipt that names the login they typed and the role the server says they kept, even though the sharing list is no longer theirs to see; their access elsewhere in the portal is refreshed. When the answer is lost, the page reads what the server now says about their own access and tells them truthfully: still an Owner (so it did not complete, and Retry is safe), or no longer an Owner (consistent with a completed transfer, which the page cannot confirm). A confirmed transfer is never re-sent, and a refused retry is never reported as a permission problem.

### 3.2 In scope (T01)

1. **Confirmation copy (DV-6).** The transfer dialog's description is built from the chosen retain and the access list on screen (the signed-in account's other open, non-Owner assignments, matched by `bootstrap.user.user_id`):
   - a role chosen: "…and your own Owner role ends. You keep the ‹Role› role on this world.";
   - No role and no other role held: "…and your own Owner role ends. You will have no role on this world and will lose access to its sharing page.";
   - No role but other roles held: "…and your own Owner role ends. You keep your ‹Role[, Role]› role on this world."
   The retain options are unchanged (server-accepted codes only).
2. **Transfer record, held above the content.** `WorldSharingPage` holds `transfer: { userId, worldId, login, retain, kind: "confirmed", retainedRoleCode } | { …, kind: "unconfirmed" } | null`. It is rendered only while `userId` and `worldId` match the current session and route, so it never shows under another account or world. `SharingContent` reports through `onTransferConfirmed(login, result)` and `onTransferUnconfirmed(login, retain)`. These are called before or alongside the re-read, so the record survives the content unmounting when access is lost.
3. **Confirmed receipt (DV-1).** On a 200 for `{op:"transfer"}`, `onSuccess` records `kind:"confirmed"` with the server's `retained_role_code`, then re-reads the access list as today. From then on the page renders, in place of the sharing content:
   - a section with `h2` "Ownership transferred" (`tabIndex={-1}`);
   - "‹login› is now an owner of ‹world name›." (the world name as already shown in the breadcrumb, or "this world");
   - "You keep the ‹Role› role on this world." when `retained_role_code` is set; otherwise "No role was kept for you.";
   - links **Back to the world** (`/worlds/{id}`) and **Worlds** (`/worlds`).
   The existing `ReadTerminal` explanation for a denied access read stays below the receipt. If the read failed instead of being denied, the receipt shows anyway and no sharing control is offered (the person is no longer an Owner; the kept list would be stale and its controls meaningless).
4. **Access refresh point (DV-4).** Once, when a transfer is confirmed (and once when §3.2 item 5 finds the caller is no longer an Owner): call the hierarchy's `refetchWorld()` and `useSession().refresh()` (through `bootstrapRefreshOutcome`). Read the hierarchy with `useContext(WorkspaceHierarchyContext)?.refetchWorld`, not `useWorkspaceHierarchy()`: the latter throws outside its provider, and the existing page tests render without one. Absent the provider, only the session refresh runs. Both are reads only, in place, never a reload and never a write. Their failure does not change the receipt.
5. **Unknown transfer (DV-2).** On a network or 5xx error for `{op:"transfer"}`, the dialog shows the unknown message, and the page re-reads the access list once (read only):
   - the read succeeds and `may_transfer` is still true: the caller is still an Owner, so the transfer did not complete when the list was read. The dialog adds "You are still an owner of this world, so the transfer does not appear to have been completed." **Retry** (same descriptor and key) stays offered;
   - the read is denied or unavailable: record `kind:"unconfirmed"`. The page renders the receipt shape with `h2` "Transfer not confirmed", "We could not confirm that ownership was transferred to ‹login›. You no longer have owner access to this world, which is what a completed transfer does.", the same links, and no Retry. The access refresh point (item 4) runs;
   - the read fails: the unknown message and Retry stay, plus **Check again** (read only, one GET per press).
6. **Refused retry (DV-3).** A 403 or 404 answer to a transfer whose previous attempt in this episode was unknown is **not** shown as a permission problem. It is handled exactly like item 5's re-read (the read decides). A 403/404 to a first transfer attempt also re-reads once: denied/unavailable shows the existing terminal with no receipt (nothing was transferred by this request), and the dialog closes. 409s keep their server sentences, keep the input, and do not re-read.
7. **No repeat.** After a confirmed or unconfirmed record, no transfer control exists on the page. The confirmed key is spent (hook); a second press while pending is ignored (hook); Retry is offered only while item 5's read says the caller is still an Owner or could not be read.
8. **Departure protection (DV-5).** `SharingDepartureGuard` gains two reasons, still one guard and one dialog:
   - a transfer pending: "Leave while ownership is being transferred?" / "It may still be completed. You will not see the result here.";
   - a transfer unknown and not reconciled (item 5, first or third outcome): "Leave without knowing whether ownership was transferred?" / "We could not confirm the transfer to ‹login›. Come back to this page to check."
   The receipt itself is not guarded. S01's reasons and wording are unchanged.
9. **Focus and announcements.** When the receipt replaces the content and focus was lost (on `body` or a detached element), the receipt's `h2` takes focus; otherwise focus stays. The `h1` fallback stays for a denial without a receipt. One announcement per outcome: "Ownership transferred to ‹login›." plus the kept-role sentence (it contains "Ownership transferred"), or "Transfer not confirmed." Nothing else announces it a second time (the shared `onSuccess`/`announceWhenRead` path must not also announce for a transfer).
10. **Documentation:** `docs/reference/portal-behavior.md` §4.3a's Sharing sub-list gains the transfer items 1–9.

### 3.3 Exclusions

- No backend, API, authorization or schema change. Moving the transfer route's idempotency check ahead of its authority check (so a committed retry replays) would be an API contract change; it is not needed and not proposed here.
- No account lookup, search, suggestion or display-name resolution for the typed login ([account-search](work-register.md#account-search)).
- No change to role/hosting feedback beyond the shared guard and `onSuccess` routing; no change to the shared hooks in §2.4.
- No copy-ui, preview or other consumer; no browser/AX run; no acceptance.

## 4. Affected files and interfaces

| File | Change |
|---|---|
| `portal/src/pages/WorldSharingPage.tsx` | dialog copy, transfer record and receipt, unknown/refused reconciliation, access refresh point, guard reasons, focus and announcement |
| `portal/src/pages/WorldSharingPage.transfer.test.tsx` | new: cases D1–D20 through the real page (stubbed `fetch`, harness `onRefresh`; hierarchy `refetchWorld` observed by wrapping the page in a test `WorkspaceHierarchyContext.Provider` whose `refetchWorld` is a mock) |
| `portal/src/pages/WorldSharingPage.test.tsx` | only these expectation changes are allowed: "moves focus to the page heading when a transfer leaves the person without Sharing" now expects the receipt's "Ownership transferred" `h2`; the dialog description in any transfer case follows §3.2 item 1. Every other assertion stays |
| `docs/reference/portal-behavior.md` §4.3a | as §3.2 item 10 |

`WorldSharingPage.panels.test.tsx` (S01) keeps every expectation.

## 5. Task commit

`P15-C05-S02-T01: keep a truthful ownership-transfer receipt across loss of access`

Followed by a docs-only records commit (plan §11.3 and the register).

## 6. Acceptance cases

"(fails at baseline)" means the case is written first and fails at this plan's commit; record each failure.

| # | Case |
|---|---|
| D1 (fails at baseline) | Q6: with No role and no other role, the dialog says "You will have no role on this world and will lose access to its sharing page."; with Editor chosen, "You keep the Editor role on this world."; with No role while also holding Reader, "You keep your Reader role on this world." |
| D2 (fails at baseline) | Q1: a confirmed transfer to `erin` (server `retained_role_code: world_editor`) followed by a 403 access read shows "Ownership transferred", "erin is now an owner of Eberron." and "You keep the Editor role on this world." above the access explanation, with Back to the world and Worlds. |
| D3 | Same with `retained_role_code: null` and a 404 read: "No role was kept for you." The kept role shown always comes from the server answer, never from the form. |
| D4 (fails at baseline) | Q2: after a confirmed transfer, `refresh` is called once and the hierarchy world is re-read once; neither repeats the POST. |
| D5 | A confirmed transfer whose access read fails (network) still shows the receipt and no sharing control. |
| D6 (fails at baseline) | Q3: an unknown transfer re-reads the access list once. |
| D7 | Unknown, then the read says `may_transfer: true`: the dialog adds "You are still an owner of this world, so the transfer does not appear to have been completed."; Retry sends the same body and key exactly once per press. |
| D8 (fails at baseline) | Unknown, then the read is 403: "Transfer not confirmed" with the §3.2 item 5 sentence; no Retry; the access refresh point runs once. |
| D9 | Unknown, then the read fails: Retry and Check again are offered; Check again sends one GET and no POST. |
| D10 (fails at baseline) | Q4: Retry answered 403 is not shown as a permission problem; the page re-reads, and a denied read gives "Transfer not confirmed". |
| D11 | A first transfer attempt answered 403/404 re-reads once; a denied read shows the existing terminal and **no** receipt; the dialog closes. |
| D12 | 409 `target_requires_system_gm`, `invalid_ownership_transfer` and `world_role_target_ineligible` keep their sentences, keep the login and retain, re-read nothing, and the person remains an Owner on screen. |
| D13 | No repeat: after a confirmed receipt no transfer form, dialog or Retry exists; total POSTs = 1. A second click while pending sends nothing. |
| D14 (fails at baseline) | Q5: leaving after an unknown, unreconciled transfer asks "Leave without knowing whether ownership was transferred?"; Stay keeps the page; Leave navigates and sends nothing. |
| D15 | Leaving while a transfer is pending asks "Leave while ownership is being transferred?"; one dialog only (S01's guard, no second blocker). |
| D16 | A receipt is not guarded: leaving from it asks nothing. |
| D17 | Focus: the receipt's `h2` takes focus when the content unmounts with focus lost; a control the person moved to outside the content keeps focus; a denial without a receipt still focuses the `h1`. |
| D18 | One announcement per outcome: "Ownership transferred to erin. You keep the Editor role on this world." once; "Transfer not confirmed." once; never also the old fixed text as a second announcement. |
| D19 | Isolation: a receipt for world w1 is not shown on w2's Sharing page, nor under another signed-in account; a late transfer answer after leaving or switching world records nothing. |
| D20 | Last-owner invariant: no transfer or refusal path leaves the page showing a world without an Owner; ending one's own last Owner role still shows `world_owner_required` (S01 C9, unchanged). |

S01's C1–C22 and existing tests stay green (§2.4).

### 6.1 Mutation probes (run by Sonnet; re-run by the reviewer)

| # | Mutation | Must fail |
|---|---|---|
| M1 | Keep the transfer record inside `SharingContent` | D2 |
| M2 | Take the kept role from the form instead of `retained_role_code` | D3 |
| M3 | Remove the access refresh point | D4 |
| M4 | Skip the unknown-transfer re-read | D6, D8 |
| M5 | Treat a read with `may_transfer: true` as "not confirmed" | D7 |
| M6 | Show a refused retry through `MutationStatusMessage` again | D10 |
| M7 | Drop the `userId`/`worldId` match on the record | D19 |
| M8 | Remove the unknown-transfer guard reason | D14 |
| M9 | Let the shared `onSuccess` announce for a transfer as well | D18 |

Revert every probe and record its failing case.

## 7. Verification

### 7.1 Per-commit checks (Sonnet; repeated by the reviewer)

From PowerShell in `C:\Users\nemes\dnd_ai\portal` (uppercase `C:`):
- focused: `npx vitest run src/pages/WorldSharingPage.transfer.test.tsx src/pages/WorldSharingPage.panels.test.tsx src/pages/WorldSharingPage.test.tsx src/hooks/useAuthoringMutation.test.tsx src/hooks/useUnsavedChangesGuard.registration.test.tsx src/App.test.tsx`;
- full `npm test`. Record the first run and any rerun separately, and name any failure outside these files;
- `npm run lint`, `npx tsc -b`, `npm run build`;
- from the repository root: `uv run python scripts/check_documentation.py` and `git diff --check`.

Backend checks are not required; a backend change is a stop condition.

### 7.2 C05 checkpoint merge requirements (not S02's verdict)

Unchanged from [S01 plan §7.2](p15-c05-s01-sharing-panels-plan.md#72-c05-checkpoint-merge-requirements-not-s01s-verdict): the C05 PR merges only when (1) S01 and S02 have each passed independent review, (2) S01's C1–C22 and S02's D1–D20 pass on the integration head with one full portal run showing both together, and (3) CI passes on that exact head. None of §7.3 is a merge gate.

### 7.3 Separate events (after the merge; not merge gates)

- Integrated-head browser evidence for transfer and authority loss ([browser](work-register.md#browser)): D2, D8, D14, D17 and the sidebar after D4 in a real browser, plus S01's items and the inherited `usePageArrival` uncertainty.
- AX evidence ([ax](work-register.md#ax)), final [p15-integration](work-register.md#p15-integration) and owner acceptance (`p15-owner`). Nothing here grants them.

## 8. Authorization, disclosure, concurrency and focus rules

- **Server-authoritative.** `may_transfer` decides only what is offered. The server re-checks Owner authority, the target and the GM requirement under the world lock. The page infers "still an Owner" only from the server's own `may_transfer` and "no longer an Owner" only from a denied or unavailable access read. It never claims a transfer completed without a 200.
- **Disclosure.** The receipt names only the login the person typed and the server's `retained_role_code`; it shows no user id from the response and performs no lookup. Refusal sentences are the existing fixed server sentences.
- **Keys and replay.** Retry re-sends the same descriptor and key. Because the route checks authority first, a committed transfer cannot be re-applied, and its refused retry is reconciled by a read, never reported as a permission problem. A confirmed key is spent; no control can send a second transfer.
- **Refresh point.** Reads only (`refetchWorld`, in-place session `refresh`), once per confirmed or reconciled loss of Owner access. A failed refresh leaves the receipt unchanged.
- **Isolation and late answers.** The content stays keyed by account and world (S01). The record carries its `userId` and `worldId` and renders only when both match. In-flight answers are aborted on unmount by the hook, and a late answer records nothing.
- **Focus and announcements.** §3.2 item 9. The inherited `usePageArrival` uncertainty ([C02 readiness §4](p15-c02-checkpoint-readiness.md#4-the-provisional-cancel-focus-issue-against-the-checkpoint-criteria)) stays with §7.3; S02 does not change it.

## 9. Intermediate states

T01 is a single commit. Until it lands, the S01 behavior (§2.1) is shipped; no intermediate state is merged.

## 10. Decisions

**No owner decision is required.** Routine choices made here:

- **R-1 (receipt from the server's answer).** The kept role comes from `retained_role_code`; the new owner is named by the typed login, the only identifier the person supplied (no lookup).
- **R-2 (reconcile with the caller's own access).** `may_transfer` and a denied/unavailable access read are the existing authoritative signals about the caller. A read taken while a lost request is still committing can say "still an Owner"; the wording says "does not appear", and a later refused Retry is reconciled again.
- **R-3 (no API change).** A replaying retry would need the route to consult the idempotency store before authority; reconciliation by read gives a truthful result without it.
- **R-4 (refresh point = reads only, in place).** A session reload would unmount the receipt; `refresh()` and `refetchWorld()` update capabilities in place.
- **R-5 (record above the keyed content, matched by account and world).** The content must unmount on loss of access; the record must not leak to another account or world.
- **R-6 (guard unknown, not the receipt).** Leaving after an unknown transfer loses the only reconciliation; leaving a receipt loses nothing the server does not keep.

## 11. Handoffs

### 11.1 Sonnet implementation instructions

1. Confirm the baseline (the commit adding this plan) is HEAD and `origin/phase15/completion`, with a clean worktree.
2. Read §2 to §9 and S01 plan §3.2. Write the "(fails at baseline)" cases first, run them on the baseline, and record each failure (test name and assertion).
3. Implement §3.2 in the files of §4 only. Keep §2.4.
4. Run §7.1. Run M1–M9, record each probe's failing case, and revert every probe (restore exact bytes; `git restore` rewrites LF working files as CRLF under `core.autocrlf=true`, so compare hashes).
5. **Stop and report instead of continuing if:**
   - a backend, API or authorization change seems necessary;
   - a change to `useAuthoringMutation`, `useConfirmedRefresh`, `useKept`, `useAnnounceWhenRead`, `usePageArrival`, `useUnsavedChangesGuard`, `navigationHolds`, `ConfirmDialog`, the workspace hierarchy or the session context seems necessary;
   - an existing test (including S01's) would need a changed expectation other than those §4 allows;
   - a case cannot be made to fail at baseline where marked.
6. Commit with the §5 subject, push, and record in §11.3 and the register's S02-T01 row: the SHA, the test-first failures, the focused and full runs (first run and rerun separately), the probes and the CI position ("pending checkpoint PR"). Commit and push the records.
7. Do not open, mark ready or merge a PR. Do not run browser or AX checks, start copy-ui, preview or other consumers, or record any acceptance.

### 11.2 Independent review boundary (Luna)

- **T01 = combined S02:** from this plan's commit to the T01 implementation commit, plus its docs-only records commit.
- Review against §2.4, §3, §6 and §8; re-run §7.1 and M1–M9; confirm S01's C1–C22 still pass.
- A pass is a slice verdict only; §7.2 and §7.3 remain.

### 11.3 Implementation record

#### T01 (Sonnet, 2026-11-24)

**Status:** T01 implemented at `191129b8569c510863324e20663fbad9c41aa26a` (`P15-C05-S02-T01: keep a truthful ownership-transfer receipt across loss of access`), pushed to `phase15/completion`; **independent review pending; not accepted.** Baseline `1f608119ef3344a7a660f1c2fccfb8ff80c820d8` (HEAD and origin, clean worktree). CI: **pending the C05 checkpoint PR** (none opened). No PR, browser/AX run, consumer or acceptance. No backend, API, shared-hook, hierarchy-context or session-context change.

**What changed** (`WorldSharingPage.tsx`, the new `WorldSharingPage.transfer.test.tsx`, one allowed expectation in `WorldSharingPage.test.tsx`, and `portal-behavior.md` §4.3a).
- **Dialog copy (item 1):** built from the chosen retain and the signed-in account's other open, non-Owner roles on the list (matched by `bootstrap.user.user_id`): "You keep the Editor role on this world.", "You will have no role on this world and will lose access to its sharing page.", or "You keep your Reader role on this world."
- **Record held above the keyed content (items 2, 3):** `WorldSharingPage` holds the transfer record with its `userId` and `worldId`, drops it in the render that sees either change (or an ended session), and shows it only when both match, so losing sharing authority alone keeps it. `SharingContent` reports through `onTransferConfirmed` and `onTransferUncertain` (plus `onTransferStart` and `onCheckAgain`). The receipt ("Ownership transferred", "‹login› is now an owner of ‹world›.", the kept role from the server's `retained_role_code` or "No role was kept for you.", links to the world and Worlds) replaces the sharing content; the access explanation stays below it; with a failed read the receipt shows and no control is offered.
- **Refresh point (item 4):** once, at a confirmed transfer and once when an unknown transfer is reconciled to "no longer an Owner": `useContext(WorkspaceHierarchyContext)?.refetchWorld()` and the in-place session refresh through `bootstrapRefreshOutcome`. Reads only; each failure is swallowed and changes nothing.
- **Unknown and refused (items 5, 6):** after a lost answer, or a 403/404 of a retry of one, the page records the access state at that moment and reads the list once; the first settled state after it is that read's own answer. A list that still allows transferring: the "still an owner" note and Retry; a denied, unavailable or no-longer-transferable read: the "Transfer not confirmed" record and the refresh point, no Retry; a read that fails: the unknown message, Retry and Check again (a read only). A first attempt refused 403/404 re-reads once and decides nothing (a denied read shows the terminal, no receipt). A refused retry is shown as "Checking whether the transfer went through…" and then the read's result, never as the permission message. 409s keep their sentences and the input and read nothing.
- **No repeat (item 7):** no transfer form, dialog or Retry exists after either record; the hook ignores a second press while pending. A Retry for a transfer is a send of the same descriptor, which reuses the reserved key (the hook does not keep a refused attempt as retryable).
- **Guard (item 8):** S01's single `SharingDepartureGuard` gained "Leave while ownership is being transferred?" and "Leave without knowing whether ownership was transferred?"; no second guard; a receipt is not guarded.
- **Focus and announcement (item 9):** the receipt's `h2` takes focus on mount only when focus was on the body or detached; the page-heading focus effect is skipped while a receipt is shown. One announcement per outcome ("Ownership transferred to erin. You keep the Editor role on this world." or "Transfer not confirmed."). The transfer branch of the shared `onSuccess` announces nothing and returns no outcome, so the mutation does not add "Saved, but the latest data could not be loaded." as a second announcement.

**Wording limited to what the read establishes (owner instruction).** The plan's sentences are kept verbatim and extended only to be honest: still being an Owner adds "That is what the list said when it was read; it does not rule out a transfer still in progress."; the unconfirmed record adds "This does not show whether ‹login› received ownership."; a read that failed or was superseded produces only "We could not check your access, so we cannot tell whether the transfer went through." and Check again. The receipt of a confirmed transfer rests only on the server's 200.

**Choices to review.** (1) A successful read that no longer allows transferring (`may_transfer: false` without a denial) is treated like a denied read (the plan is silent on it). (2) Sidebar and session refresh failures are swallowed and cannot touch the receipt; a session refresh that keeps the same account keeps the record. (3) The check effect and the render-time derivations carry two scoped lint exceptions (`set-state-in-effect`, `exhaustive-deps`) with reasons, as in S01. (4) The receipt is rendered by the page, not by content, which is why M1 (the record inside the content) loses it on a denial.

**Test-first failures (baseline `1f608119ef3344a7a660f1c2fccfb8ff80c820d8`, new file, first run of 32 cases: 27 failed, 5 passed).** The seven the task named all failed: D1 (the dialog did not say what is kept, three cases), D2 (no receipt: `Unable to find … "Ownership transferred"` heading), D4 (`refresh` and `refetchWorld` never called), D6 (no re-read after the unknown answer), D8 (no "Transfer not confirmed"), D10 (a refused retry was shown as a permission problem, no re-read), D14 (no departure question after an unknown transfer). Also failing: D3, D4 (second), D5, D7, D9, D11, D13, D15–D16 (no pending-transfer question or receipt), D17 (three), D18 (two), D19 (four, session and world transitions). Passing at baseline, as regression guards: D12 (three 409 sentences), D19's late-answer case (S01's guard plus unmount-abort) and D20 (the last-owner sentence). D10 was strengthened after the first full run to hold the re-read and see the dialog while it is pending; M6 passed everything before that and fails D10 after it.

**Existing-test edit (§4).** `WorldSharingPage.test.tsx`: "moves focus to the page heading when a transfer leaves the person without Sharing" now expects the receipt's "Ownership transferred" `h2` to have focus. "Still announces a transfer whose read-back is the denial" passes unchanged (the new announcement contains "Ownership transferred"). S01's `WorldSharingPage.panels.test.tsx` is untouched and passes.

**Runs (PowerShell, `C:\Users\nemes\dnd_ai\portal`).**
- Focused (§7.1): `WorldSharingPage.transfer`, `.panels`, `WorldSharingPage`, `useAuthoringMutation`, `useUnsavedChangesGuard.registration`, `App`: 6 files, **171 passed**.
- Full `npm test`, first run: **454 files, 5879 passed, 0 failed**. A second full run after D10 was strengthened: 454 files, 5879 passed, 0 failed. No failure to report.
- `npm run lint`, `npx tsc -b`, `npm run build` pass (chunk-size notice only). `uv run python scripts/check_documentation.py` and `git diff --check` pass.

**Probes (each reverted; `WorldSharingPage.tsx` restored byte-for-byte, SHA-256 prefix `511363d50e60`).**
- M1 (receipt only while the access list shows, i.e. the record dies with the content): failed 18 cases: 17 receipt cases including D2, plus the allowed existing focus test.
- M2 (the kept role not from the server's answer): failed D3 (and D2, D18, D19).
- M3 (no refresh point): failed D4 and D8.
- M4 (no unknown-transfer re-read): failed D6, D7, D8, D9, D10 and D14.
- M5 (a list that still allows transferring treated as not confirmed): failed D7, D9, D10 and D14.
- M6 (a refused retry shown through the permission message again): **passed everything on the first attempt**, so D10 was strengthened; it then fails D10.
- M7 (no account/world match on the record): failed D19 (three cases).
- M8 (no unknown-transfer guard reason): failed D14.
- M9 (the shared path also announces for a transfer): failed D18 (two cases) and D4's announcement count.

**Not done / limits.** No browser or AX evidence (focus on the receipt, the sidebar after the refresh, D2/D8/D14/D17). The unreconciled "still an owner" read can precede a transfer that is still committing (plan R-2); the wording says so and a later refused retry is reconciled again. A confirmed receipt does not survive a reload or a sign-out (it is page state by design).

**Review range for Luna (§11.2).** `1f608119ef3344a7a660f1c2fccfb8ff80c820d8..191129b8569c510863324e20663fbad9c41aa26a` plus the docs-only records commit that follows it.

# D/P15-C05-S01 implementation plan: clarify the role and hosting panels

**Status:** Opus plan prepared 2026-11-24. **T01 implemented (§11.3); independent review pending, not accepted.** Corrected at T01 entry (DV-6 not reproduced; C21, C3 and M7 amended). No owner decision blocks the task. Section 10 lists the routine choices made here; none changes a product policy, an API contract, authorization or account discoverability.

**Register rows:**
- slice [D/P15-C05-S01](work-register.md#p15-c05-s01);
- task [T01](work-register.md#p15-c05-s01-t01);
- parent checkpoint [D/P15-C05](work-register.md#p15-c05).

**Plan-entry head:** `720fc6ee8bc17001e717716c33dcc47c7ff13ce3` ("Merge pull request #73 from NemesisGhost/phase15/completion"), the C04 merge on `main`.
- `phase15/completion` was at `9fa2e3b5d230647875b1470d9494e04ce2147aa1` (equal to its origin, clean worktree). That commit is the merge's second parent and the merge tree is identical to it (`e4c5f17c…`), so the branch was fast-forwarded to `720fc6e` after `git fetch origin`. No history was rewritten.
- CI: no run exists for C05; its checkpoint PR has not been opened. The push run on `720fc6e` (`45321026728`) failed one backend test in shard 7 (recorded on the C04 row; not a C05 gate).

Sonnet's implementation baseline is the commit that adds this plan, a child of `720fc6e`. The handoff prompt names it.

**How each statement was established:**
- by reading source, tests and documents at the plan-entry head;
- by a temporary plan-entry reproduction (§2.2): one Vitest file, written into `portal/src/pages/` only for the run and deleted afterwards. It rendered the real `WorldSharingPage`, `useAuthoringMutation`, `useAuthoringResource` and feedback components with a stubbed `fetch` (`installMockServer`). No repository file was changed by it.

**Governing sources:**
- [R08](work-register.md#r08--world-sharing): "improve existing panels and feedback first if search policy is unresolved … Recheck target eligibility and role/hosting/transfer authority during the mutation." Acceptance includes "inactive/changed targets … unknown/replay behavior".
- The register's [C05](work-register.md#criteria-p15-c05), [S01](work-register.md#criteria-p15-c05-s01) and [T01](work-register.md#criteria-p15-c05-s01-t01) criteria: "Check permission and target changes without expanding account discoverability"; "Present existing exact-login operations and authoritative feedback".
- [Portal behavior §4.3a](../reference/portal-behavior.md#43a-scoped-roles-in-the-portal-adr-0020) (the Sharing page) and the confirmed-write contract (`useConfirmedRefresh`, `useKept`, `useAnnounceWhenRead`) in [portal behavior](../reference/portal-behavior.md) ("A denied or unavailable answer to the read-back is an authoritative result").
- [Portal behavior §5.11](../reference/portal-behavior.md#511-authoring-patterns-phase-14): one meaningful announcement, unsaved-input guard.
- [ADR 0020](../adr/0020-scoped-system-world-and-campaign-roles.md) and the world-sharing API, unchanged by this slice (`src/dnd_ai/api/world_sharing.py`, `src/dnd_ai/commands/world_access.py`):
  - every route resolves the caller's authority for the target world; no authority → fixed non-disclosing **404**; an Owner whose system GM was revoked (`world.share` withheld) → **403**. Each command locks the world row and re-checks authority and target eligibility under the lock;
  - `POST /worlds/{id}/roles` `{login_name, role_code}`: **201** `changed:true` / **200** `changed:false` (already held). Owner additionally needs `world.transfer`; a new Owner must hold system GM (409 `target_requires_system_gm`);
  - `POST /worlds/{id}/use-grants` `{login_name}`: 201/200 the same way. **No GM check**: any active account may be granted, but creating a campaign requires the system `campaign.host` capability at that time (`commands/campaigns.py`);
  - `POST …/roles/{membership_id}/end` and `…/use-grants/{grant_id}/revoke`: 200 `changed:true`; an id that is no longer open is the **same fixed 404** as no authority; ending the last Owner → 409 `world_owner_required`;
  - a missing, inactive or non-local login → 409 `world_role_target_ineligible`, indistinguishable by design;
  - each mutation accepts an optional `Idempotency-Key` (actor-scoped store; a committed request is replayed for the same key).
- [account-search](work-register.md#account-search) is unresolved policy. It gates only an account picker; "Existing panels can proceed". This plan adds no lookup, search, autocomplete or suggestion.

## 1. Entry readiness and C05 scope

C05 is "Complete existing world-sharing tasks". Its prerequisite column is "—" and its criteria row has no entry contract, so C05 has no checkpoint prerequisite. It has two slices:
- **S01 Clarify role and hosting panels** (one task, T01);
- **S02 Retain safe ownership-transfer feedback** (one task, T01: "Reconcile transfer receipt and retained-role options across loss of access"; criteria: last-owner invariant, unknown outcome, no repeat of a confirmed transfer).

Each says "Checkpoint entry criteria; no additional slice-specific gate", so neither depends on the other; table order is not a dependency. S01 is planned first as the first eligible slice. **S02 is independently eligible.** Both edit `WorldSharingPage.tsx`, so S02's plan should be prepared against S01's implementation head (scheduling, not a prerequisite).

Out of C05 by construction: the account picker ([account-search](work-register.md#account-search), unresolved policy); the unadmitted [atomic-roles](work-register.md#atomic-roles) proposal (a C04/system-role matter, not world sharing). The legacy crosswalk rows labelled "P15-C05-S0x" in the adoption tables are previous-register IDs, not C05's children.

**Verdict: S01 eligible and ready for Sonnet.**

## 2. Verified current behavior

### 2.1 How the panels work today

- One `useAuthoringMutation` serves every write on the page (scope `world-sharing:{worldId}`). Its body is an `Action` = `{ run: (ctx) => Promise, announce: string }`. The hook fingerprints a body with `JSON.stringify`, which drops the function, so every body of one kind has the same fingerprint (`{"announce":"Role assigned"}`, `{"announce":"Role ended"}` …).
- After a lost answer (network or 5xx) the hook keeps that attempt as unresolved and re-sends it, with its key, for any later submit with the same fingerprint (by design: "an unchanged body re-sends the unresolved attempt exactly").
- `addRole` and `addUse` clear their login field immediately after `submit`, before any answer.
- Success re-reads the access list and announces the action's fixed text ("Role assigned", "Permission to host campaigns granted", "Role ended", "Permission revoked") whether the server answered `changed:true` or `changed:false`.
- A refusal shows `MutationStatusMessage` (top of the page; inside the dialog while it is open). No refusal re-reads the list.
- The hosting field is labelled "Login name of a game master"; the server accepts any active account, and only an account with the system GM role can then host.
- There is no departure protection. The route has no key. (Correction at T01 entry: a change of `worldId` or account does **not** keep `SharingContent`: the access read goes back to loading, and the page's loading branch unmounts it, so nothing survives; see DV-6.)

### 2.2 Plan-entry reproduction results

Temporary file `portal/src/pages/zzC05S01Repro.test.tsx`, run from `C:\Users\nemes\dnd_ai\portal` with `npx vitest run`: **1 file, 7 tests passed** (each asserts the current, deviating behavior). The file was then deleted; `git status` was clean.

| # | Reproduction | Observed |
|---|---|---|
| P1 | Give role to `dana`, answered 500 | "…Your input has been kept…" is shown, and the Login name field is empty. |
| P2 | After P1, type `erin` and press Give role (answered 201) | The second POST's body is `{login_name:"dana", role_code:"world_editor"}` with the **same** `Idempotency-Key`; "Role assigned" is announced. `erin` was never sent. |
| P3 | Give role answered 200 `changed:false` | "Role assigned" is announced. |
| P4 | Give role answered 409 `world_role_target_ineligible` | The message shows and the typed login is gone. |
| P5 | End Bob's role, answered 500; Cancel; End Dan's role and confirm | The second POST goes to `/roles/m2/end` (Bob) again; `/roles/m3/end` (Dan) is never sent. |
| P6 | Revoke hosting answered 403 (authority withdrawn) | No access re-read; after Cancel, Give role and the other controls stay enabled. |
| P7 | End a role answered 404 (already ended elsewhere) | No access re-read; the ended row stays on screen. |

### 2.3 Deviations S01 repairs

- **DV-1 (wrong-target write).** A later operation of the same kind re-sends an earlier unresolved attempt, with its key, instead of what the person asked for (P2, P5). This is the serious one: it can apply a change the person did not confirm and silently skip the one they did.
- **DV-2 (input lost).** The login is cleared before the answer, so a refusal cannot be corrected and the unknown message's "Your input has been kept" is untrue (P1, P4).
- **DV-3 (no-op reported as a change).** `changed:false` is announced as a change (P3).
- **DV-4 (refusals not reconciled).** A 403/404 is shown without re-reading the authoritative list, so withdrawn authority leaves live-looking controls and an ended row stays (P6, P7).
- **DV-5 (hosting copy).** The label implies the server checks for a game master; it does not, and the grant is useless to an account without the GM system role.
- **DV-6 (isolation): not reproduced (corrected at T01 entry).** The plan asserted that typed values, notices and an open dialog survive a world or account change; no P-case reproduced it. Sonnet's test-first run at the baseline showed they do not: on a world change the access path differs, and on an account change the owner differs, so `useAuthoringResource` returns the loading state at once and `WorldSharingPage`'s loading branch unmounts `SharingContent` (its typed values, dialog, notices, unresolved attempt and in-flight write go with it, and the mutation's abort-on-unmount drops a late answer). The keyed content (§3.2 item 8) is therefore defense in depth, not a repair. The departure protection DV-6's neighbours need is the guard of §3.2 item 7.

### 2.4 Reviewed behavior that must not regress

- Every existing `WorldSharingPage.test.tsx` case (CSRF, refetch, confirmation dialogs and their focus return, Owner hiding without `world.transfer`, last-owner message, heading focus when a transfer removes access, the saved-but-not-read-back notice with read-only recovery, the announced transfer whose read-back is a denial) keeps its expectations, except the ones §4 names.
- The ownership-transfer section and its dialog behave as today (S02 owns their feedback); only the shared body shape changes (§3.2 item 1).
- `useAuthoringMutation`, `useConfirmedRefresh`, `useKept`, `useAnnounceWhenRead`, `usePageArrival`, `useUnsavedChangesGuard`, `navigationHolds` and `ConfirmDialog` are unchanged.

## 3. Outcome, scope and exclusions

### 3.1 User outcome

An Owner types an exact login name, chooses a role (or hosting), and is told exactly what the server did for that login: given, already held, refused with the server's reason, or unknown, with a safe retry of the same request. What they typed stays until the change is confirmed. A later change never re-sends an earlier one. When the server refuses because their own authority or the row has changed, the page re-reads the list and shows the truth. Nothing reveals more about accounts than the existing exact-login contract already does.

### 3.2 In scope (T01)

1. **Operation descriptors (fixes DV-1).** Replace `Action` with a plain serializable descriptor, for example:
   `{ op: "assign-role", login, role } | { op: "grant-use", login } | { op: "end-role", membershipId, name, role } | { op: "revoke-use", grantId, name } | { op: "transfer", login, retain }`.
   The mutation's `request` maps the descriptor to the existing API call. The fingerprint is now the operation and its target, so a different login, role or row is a different request with a new key, and the same descriptor is the same request with the same key. The transfer descriptor carries exactly today's body; transfer behavior is otherwise unchanged (S02).
2. **Inputs kept until confirmed (DV-2).** `addRole`/`addUse` no longer clear the field on submit. A field is cleared only when the server confirmed that operation (`changed:true` or `false`) **and** the field still holds the confirmed login (the hook's `onSuccess(result, body)` receives the confirmed body). A refusal or an unknown outcome keeps the field, so "Your input has been kept" is true.
3. **Truthful confirmations (DV-3).** The announcement (and, when the read-back fails, the saved-notice text) is built from the confirmed descriptor and the server's `changed`:

   | Operation | `changed:true` | `changed:false` |
   |---|---|---|
   | assign-role | "‹login› now has the ‹Role› role on this world." | "‹login› already had the ‹Role› role on this world. Nothing changed." |
   | grant-use | "‹login› may now host campaigns on this world." | "‹login› could already host campaigns on this world. Nothing changed." |
   | end-role | "‹name›'s ‹Role› role on this world has ended." | — |
   | revoke-use | "‹name› can no longer start new campaigns on this world." | — |

   ‹login› is exactly what the person typed (trimmed); ‹name› and ‹Role› come from the row they acted on. No display name is looked up for a typed login. The existing timing stays: announce on a read-back of "ok", otherwise `useAnnounceWhenRead` / the saved-but-not-read notice (`useConfirmedRefresh`), as today.
4. **Refusals.**
   - 409/400/422: the existing `MutationStatusMessage` with the server code's sentence (`world_role_target_ineligible`, `target_requires_system_gm`, `world_owner_required`); input kept; no re-read; no retry offered.
   - **403 and 404 (DV-4):** the write was not applied. The page re-reads the access list once (read only, never the write). Then:
     - the read is denied or unavailable: the existing authoritative path (controls, dialog and kept list dropped, heading focus, the "not available" explanation);
     - the read succeeds and, for end-role/revoke-use, the row is gone: "‹name›'s ‹Role› role had already ended. The list has been updated." / "‹name›'s permission had already been revoked. The list has been updated." (the dialog closes; focus follows the existing closed-dialog rule);
     - otherwise: the existing denied/unavailable message, with the list now current.
5. **Unknown outcomes** (network or 5xx; `MutationStatusMessage` as today, with **Retry** sending the same descriptor and key):
   - assign-role / grant-use: the login stays; editing it (or the role) and pressing the button is a **new** request with a new key, not a replay. The list is re-read once (read only) so the person can check it; the page does not claim the read settles the outcome (it cannot match a typed login to a row without new discovery).
   - end-role / revoke-use: the list is re-read once (read only). If the row is gone: "‹name›'s ‹Role› role has ended." (or the revoke sentence), announced once, the dialog closes and the mutation is reset (no Retry). If the row is still listed: the dialog keeps the unknown message and Retry; the sentence adds "It is still listed." No claim is made that it was not applied.
   - Choosing a different row's action (P5) sends that row's own descriptor.
   - **What a re-read may prove (owner-confirmed at T01 entry).** The decision is made from the data of the **successful, complete read itself** (the access list is unfiltered and unpaginated: it returns every open role and every unrevoked grant for the world, `list_world_access`), matched by the row's id. A read that failed, was denied, or was superseded by a newer one establishes nothing: the unknown message and its Retry stay, and no sentence claims the row ended or was still there. Absence from any filtered or partial list would not be proof, and none is used.
6. **Hosting copy (DV-5).** The field becomes "Login name"; the section hint adds: "Only an account with the game master system role can use it to start a campaign." The existing hint text stays. No client-side GM check is added.
7. **Departure protection.** One page-level `useUnsavedChangesGuard` + `ConfirmDialog`, mounted only while needed (C04's committed-blocker registration protects first mount):
   - a write is pending: "Leave while this change is being saved?" / "It may still be applied. You will not see the result here.";
   - an assign-role or grant-use outcome is unknown and unresolved: "Leave without knowing whether the change was saved?" / "We could not confirm whether ‹login› was given access. Check the list on this page later."
   Leave/Stay labels as C04. Typed but unsent text is not guarded (R-4). S02 must add its reasons to this same guard, never a second one.
8. **Isolation (DV-6, not reproduced; kept as defense in depth).** `WorldSharingPage` keys `SharingContent` by `bootstrap.user.user_id` and `worldId`, so typed values, notices, the dialog and any unresolved attempt can never appear under another account or world even if the loading branch were ever removed or a read answered synchronously. Today the loading branch already unmounts `SharingContent` on every world or account change, so this key changes no observable behavior and no test can fail without it (§6.1 M7).
9. **Documentation:** `docs/reference/portal-behavior.md` §4.3a's Sharing bullet gains a sub-list describing items 2–8 ("P15-C05-S01; implemented, awaiting independent review, not accepted" once implemented).

### 3.3 Exclusions

- No backend, API, authorization or schema change; no new error code.
- No account search, picker, autocomplete, suggestion, existence hint or display-name lookup ([account-search](work-register.md#account-search)).
- No ownership-transfer feedback, receipt or retained-role change beyond the descriptor shape (S02).
- No change to the shared hooks and components listed in §2.4.
- No copy-ui, preview or other consumer; no browser/AX run; no acceptance.

## 4. Affected files and interfaces

| File | Change |
|---|---|
| `portal/src/pages/WorldSharingPage.tsx` | descriptors, kept inputs, truthful messages, refusal/unknown re-reads, hosting copy, page guard, keyed content |
| `portal/src/pages/WorldSharingPage.panels.test.tsx` | new: cases C1–C22 through the real page (stubbed `fetch`) |
| `portal/src/pages/WorldSharingPage.test.tsx` | only these expectation changes are allowed: the "Allow hosting" field's accessible name (`Login name of a game master` → `Login name` within the hosting form), and any assertion of the old fixed announcement texts ("Role assigned" in the saved-but-not-read-back case becomes the §3.2 item 3 sentence). Every other assertion stays |
| `docs/reference/portal-behavior.md` §4.3a | as §3.2 item 9 |

## 5. Task commit

`P15-C05-S01-T01: tell the truth about each sharing change and never re-send an earlier one`

Followed by a docs-only records commit (plan §11.3 and the register).

## 6. Acceptance cases

"(fails at baseline)" means the case is written first and fails at the baseline (this plan's commit); record each failure. All cases run through the real page with `installMockServer`.

| # | Case |
|---|---|
| C1 (fails at baseline) | P2: after an unknown give-role for `dana`, giving a role to `erin` sends `erin` with a **different** key; `dana` is not re-sent. |
| C2 (fails at baseline) | P5: after an unknown end-role for Bob, Cancel, then ending Dan's role sends `/roles/m3/end`; Bob's is not re-sent. Same for two hosting revokes. |
| C3 (partly fails at baseline) | (a) The **Retry button** after an unknown give-role sends the same body with the same key (replay), exactly once per press: **passes at baseline** (inherited `mutation.retry`; a regression guard). (b) Pressing **Give role again** with the unchanged login and role sends the same body and key: **fails at baseline only because the login was cleared on submit** (DV-2), so the press does nothing. |
| C4 (fails at baseline) | P1/P4: after a 500 and after a 409, the Login name keeps `dana` and the role keeps its choice. |
| C5 | After a confirmed give-role, the field is empty; if the person edited the field while the request was pending, their edit is kept. |
| C6 (fails at baseline) | P3: `changed:false` announces "dana already had the Editor role on this world. Nothing changed."; `changed:true` announces "dana now has the Editor role on this world." |
| C7 | Hosting: `changed:true`/`false` sentences per §3.2 item 3. |
| C8 | End-role and revoke-use confirmations name the row's person and role. |
| C9 | 409 `world_role_target_ineligible`, `target_requires_system_gm` (Owner role) and `world_owner_required` show their server sentences; no access re-read; no Retry. |
| C10 (fails at baseline) | P6: a 403 on revoke re-reads the access list once; a denied read drops the controls and moves focus to the `h1`; no write is repeated. |
| C11 (fails at baseline) | P7: a 404 on end-role re-reads once; the row is gone; "Bob Editor's Editor role had already ended. The list has been updated." The dialog closes. |
| C12 | A 404 whose re-read still lists the row shows the unavailable message with the current list. |
| C13 | An unknown end-role whose re-read no longer lists the row: "Bob Editor's Editor role has ended." announced once; no Retry; one POST in total. |
| C14 | An unknown end-role whose re-read still lists the row keeps the dialog's unknown message, adds "It is still listed.", and Retry sends the same key. |
| C15 | An unknown give-role re-reads the list once and keeps the unknown message and the login; no claim of the outcome. |
| C16 | A saved change whose read-back fails keeps today's notice and read-only recovery, with the §3.2 item 3 sentence. |
| C17 | Hosting form: the field is "Login name"; the hint says only a game master can use it to start a campaign; no request is sent on typing. |
| C18 | Departure while a write is pending asks "Leave while this change is being saved?"; Leave navigates and sends nothing more; Stay keeps the page and the outcome is still shown. |
| C19 | Departure with an unresolved unknown give-role asks "Leave without knowing whether the change was saved?"; typed but unsent text alone asks nothing. |
| C20 | One guard only: with a pending write, a path change shows exactly one dialog (no second blocker). |
| C21 (passes at baseline; isolation regression guard) | A change of `worldId` (and, separately, of the signed-in account) drops typed but unsent values, an open dialog with an unknown outcome, notices and the unresolved attempt, and a late answer for the old world is not shown. These assertions need no typed input retention and no departure guard, and all pass at baseline because the loading branch unmounts `SharingContent`. They are kept as a guard against that ever changing. What the plan attributed to isolation that is really DV-2 (input kept) and the guard (a pending write is asked about when the person leaves) is asserted in C4, C18 and C19, not here. |
| C22 | No request other than the existing reads and the person's own writes is sent while typing or after any outcome (no lookup); messages show only the typed login and listed names. |

Existing `WorldSharingPage.test.tsx` cases stay green (§2.4).

### 6.1 Mutation probes (run by Sonnet; re-run by the reviewer)

| # | Mutation | Must fail |
|---|---|---|
| M1 | Drop the login (or row id) from the descriptor | C1, C2 |
| M2 | Clear the login on submit again | C4 |
| M3 | Ignore `changed` (always the "now has" sentence) | C6 |
| M4 | Remove the 403/404 re-read | C10, C11 |
| M5 | Treat a re-read that still lists the row after an unknown end-role as confirmed | C14 |
| M6 | Retry builds a new descriptor (new key) instead of `mutation.retry` | C3 |
| M7 | Remove the content key | **no case fails (by design, not run as a failing probe).** The key is defense in depth: the page's loading branch already unmounts `SharingContent` on a world or account change, so removing the key is observably identical and C21 stays green. Recorded in §11.3 as redundant with the existing isolation; no case was invented to fail it |
| M8 | Mount the guard twice (one per reason) | C20 |
| M9 | Clear the field on confirmation even when it was edited meanwhile | C5 |

Revert every probe and record its failing case.

## 7. Verification

### 7.1 Per-commit checks (Sonnet; repeated by the reviewer)

From PowerShell in `C:\Users\nemes\dnd_ai\portal` (uppercase `C:`):
- focused: `npx vitest run src/pages/WorldSharingPage.panels.test.tsx src/pages/WorldSharingPage.test.tsx src/hooks/useAuthoringMutation.test.tsx src/hooks/useUnsavedChangesGuard.registration.test.tsx src/App.test.tsx` (adjust only for files that are added);
- full `npm test`. Record the first run and any rerun separately, and name any failure outside these files;
- `npm run lint`, `npx tsc -b`, `npm run build`;
- from the repository root: `uv run python scripts/check_documentation.py` and `git diff --check`.

Backend checks are not required; a backend change is a stop condition.

### 7.2 C05 checkpoint merge requirements (not S01's verdict)

The C05 PR merges only when all of these hold:
1. S01 and S02 have each passed independent review.
2. The checkpoint acceptance cases pass on the integration head: S01's C1–C22, S02's cases (from its plan), and one full portal run showing both together.
3. CI passes on the exact integration head.

A reviewed slice is not a merged checkpoint. None of §7.3 is a merge gate.

### 7.3 Separate events (after the merge; not merge gates)

- Integrated-head browser evidence for transfer and authority loss (the C05 criteria's [browser](work-register.md#browser) obligation), including a real-browser check of C10, C11, C13, C18 and the inherited arrival-focus uncertainty (§8).
- AX evidence ([ax](work-register.md#ax)), final [p15-integration](work-register.md#p15-integration) and owner acceptance (`p15-owner`). Nothing in this plan grants them.

## 8. Authorization, disclosure, concurrency and focus rules

- **Server-authoritative.** `may_transfer` and the capabilities stay presentation only; every write and read is authorized by the server, which re-checks authority and target eligibility under the world lock. The portal never pre-checks a target's system role.
- **Disclosure.** No new request reveals anything about an account. Success sentences echo only the login the person typed; refusal sentences are the existing fixed server sentences; the ineligible refusal stays indistinguishable for missing, inactive and non-local logins.
- **Keys and replay.** Same descriptor = same key (a lost answer is retried safely); a different descriptor = a new key. A confirmed write's key is spent and never re-sent. Reads after refusals and unknown outcomes are read only and never repeat a write.
- **Isolation.** Content keyed by account and world; the scope key aborts in-flight answers; a late answer never appears elsewhere.
- **Focus.** Unchanged rules: the dialog returns focus to its trigger, or the roles heading when the trigger's row is gone; an authoritative denial moves focus to the `h1`; a form submit keeps focus on its button. No new focus target.
- **Inherited uncertainty.** The page uses `usePageArrival`; the C02 question about late arrival focus ([C02 readiness §4](p15-c02-checkpoint-readiness.md#4-the-provisional-cancel-focus-issue-against-the-checkpoint-criteria)) stays with the browser check in §7.3. S01 does not change it.
- **Announcements.** One announcement per confirmed outcome (existing announcer); refusal and unknown messages are the existing alert regions. A reconciled unknown end-role announces once.

## 9. Intermediate states

T01 is a single commit. Until it lands, current behavior (§2.1) is shipped; no intermediate state is merged.

## 10. Decisions

**No owner decision is required.** Routine choices made here:

- **R-1 (one mutation, serializable descriptors).** Keeps the page's single `busy`/`held` model and the hook unchanged; the fingerprint now names the operation and its target. Separate mutation hooks per panel were rejected: they would not fix same-panel collisions (P2, P5) by themselves.
- **R-2 (transfer descriptor in S01).** The body type is shared; leaving transfer on the old shape would keep a known collision. Only its shape changes; its feedback stays S02's.
- **R-3 (re-read after 403/404 and after unknown end/revoke).** The list is the authoritative answer the page already uses; reads never repeat a write. A typed login cannot be matched to a row without new discovery, so an unknown give-role stays unknown with Retry.
- **R-4 (guard only pending writes and unresolved unknown grants).** Leaving then loses the only chance to see or safely retry the result. Typed but unsent login text is short and re-typable, and the Phase 13 access pages do not guard it either.
- **R-5 (hosting copy, no client GM check).** The server's contract accepts any active account; the copy states the consequence instead of inventing a rule.
- **R-6 (key by account and world).** Matches C04's keyed pages; the route itself is unchanged. Kept as defense in depth: the loading branch already isolates (DV-6 not reproduced).

## 11. Handoffs

### 11.1 Sonnet implementation instructions

1. Confirm the baseline (the commit adding this plan) is HEAD and `origin/phase15/completion`, with a clean worktree.
2. Read §2 to §9. Write the "(fails at baseline)" cases first (C21 is a baseline-passing guard, C3 passes in part; see §6), run them on the baseline, and record each failure (test name and assertion).
3. Implement §3.2 in the files of §4 only. Keep §2.4.
4. Run §7.1. Run M1–M9, record each probe's failing case, and revert every probe (restore exact bytes; note that `git restore` rewrites LF working files as CRLF under `core.autocrlf=true`, so compare hashes).
5. **Stop and report instead of continuing if:**
   - a backend, API or authorization change seems necessary;
   - a change to `useAuthoringMutation`, `useConfirmedRefresh`, `useKept`, `useAnnounceWhenRead`, `usePageArrival`, `useUnsavedChangesGuard`, `navigationHolds` or `ConfirmDialog` seems necessary;
   - an existing test would need a changed expectation other than those §4 allows;
   - a case cannot be made to fail at baseline where marked.
6. Commit with the §5 subject, push, and record in §11.3 and the register's T01 row: the SHA, the test-first failures, the focused and full runs (first run and rerun separately), the probes and the CI position ("pending checkpoint PR"). Commit and push the records.
7. Do not open, mark ready or merge a PR. Do not plan or implement S02. Do not run browser or AX checks, start copy-ui, preview or other consumers, or record any acceptance.

### 11.2 Independent review boundary (Luna)

- **T01 = combined S01:** from this plan's commit to the T01 implementation commit, plus its docs-only records commit.
- Review against §2.4, §3, §6 and §8. Re-run §7.1 and M1–M9.
- A pass is a slice verdict only; §7.2 and §7.3 remain.

### 11.3 Implementation record

#### T01 (Sonnet, 2026-11-24)

**Status:** T01 implemented at `d7e08866050d05235c03fe94ddb8837d2015dfd5` (`P15-C05-S01-T01: tell the truth about each sharing change and never re-send an earlier one`), pushed to `phase15/completion`; **independent review pending; not accepted.** Baseline `60cfd3dc4765f3953b0894316fe5ca61f867067c` (HEAD and origin, clean worktree). CI: **pending the C05 checkpoint PR** (none opened). No PR, S02 work, browser/AX run, consumer or acceptance.

**Plan correction made at T01 entry (owner-approved, in the commit).** The test-first run stopped under §11.1 step 5: C21 could not be made to fail at the baseline. DV-6 is **not reproduced**: on a world change the access path differs and on an account change the owner differs, so `useAuthoringResource` returns the loading state at once and the page's loading branch unmounts `SharingContent`. Typed but unsent values, an open unknown-outcome dialog, an unresolved attempt and an in-flight write do not survive, and the mutation's abort-on-unmount drops a late answer. The plan was amended in §2.1, §2.3, §3.2 item 8, §6 (C3, C21), §6.1 (M7), §10 R-6 and §11.1: C21 is a baseline-passing isolation regression guard; the explicit content key stays as defense in depth; **M7 no longer requires a failing case** (removing the key is observably identical, so no case was invented); C21's isolation assertions are separated from DV-2 input retention and the departure guard (asserted in C4, C18, C19); C3's Retry-button variant is baseline-passing and its Give-role-again variant fails because the login was cleared. §3.2 item 5 also states what a re-read may prove (below).

**What changed.** `WorldSharingPage.tsx`: the `{ run, announce }` body became a serializable `Operation` descriptor (`assign-role`, `grant-use`, `end-role`, `revoke-use`, `transfer`; the transfer request body is unchanged), so a different login, role or row is a new request with a new key and the same descriptor is the same request. Inputs are kept until confirmed and cleared only when the field still holds the confirmed login (`onSuccess(result, body)`). The announcement and the saved-but-not-read notice come from the confirmed descriptor and `changed` (§3.2 item 3). A 403 or 404, and a lost answer (network or 5xx), re-read the access list once (read only); an end or revoke is then settled from that read (below); transfer is left to S02. The hosting field is "Login name" with the hint that only a game master system account can use it to start a campaign (no client GM check). One `SharingDepartureGuard` (the corrected shared guard) is mounted only while a write is pending ("Leave while this change is being saved?") or an unresolved give-role or hosting grant is unknown ("Leave without knowing whether the change was saved?"). `SharingContent` is keyed by account and world. No lookup, search or display-name resolution was added. `portal-behavior.md` §4.3a gains the sub-list.

**What a re-read may prove (reconciliation).** The decision uses the data of the **successful, complete read itself**, matched by row id: the access list (`list_world_access`) is unfiltered and unpaginated (every open role and every unrevoked grant), so a missing id means the row has ended. Implemented by recording the list shown when the re-read starts and acting on the first list applied after it. A read that failed, was denied or was superseded establishes nothing (the unknown message and Retry stay; C15 covers a failed read, and a superseded re-read of an earlier operation cannot replace newer feedback, the added C14 case). Starting anything newer drops the pending settlement. A typed login is never matched to a row, so a give-role or hosting grant stays unknown. The settlement effect carries a scoped `eslint-disable react-hooks/set-state-in-effect` with its reason (it reacts to data arriving from a read and also announces and closes a dialog); there is one earlier precedent in `CampaignLayout.tsx`.

**Test-first failures (baseline `60cfd3dc4765f3953b0894316fe5ca61f867067c`, new file `WorldSharingPage.panels.test.tsx`, first run of 34 cases: 29 failed, 5 passed).**
- Failed: C1 (a different login, and a different role for the same login, re-sent the earlier attempt: `expected {login_name: 'dana'…} to deeply equal {login_name: 'erin'…}`), C2 (both the roles and the hosting variants: the other row's POST was never sent), **C3b** (pressing Give role again did nothing because the login had been cleared), C4 (the login was gone: `expect(element).toHaveValue(dana)`), C5 (two cases), C6 (two cases, the old fixed "Role assigned" text), C7, C8, **C10** (no re-read after the 403), **C11** (no re-read, the row stayed), C12, C13, C14, C15 (two cases), C16, C17, C18 (two cases: no guard), C19 (asks), C20, C22 (the old announcement), and the two early C21 variants (see below).
- Passed at the baseline: **C3a** (the Retry button replays the same key: inherited `mutation.retry`), C9 (three refusals: server sentence, no re-read, no Retry) and C19's "typed but unsent text asks nothing".
- **C21.** The two early variants failed only for unrelated reasons (the login had been cleared before the isolation assertion; no departure guard to answer). They were removed. The isolation cases as finally written (typed unsent values on a world change and on an account change; an open dialog with an unknown outcome on an account change; no late answer for an in-flight end-role after an account change) were re-run against the baseline file and **all four pass there**, as the correction states.
- A late case added during implementation (C14: a superseded re-read cannot replace newer feedback) and two key assertions added to C2 (a different row has a different key) were written after the first run; M1 initially failed C1 only and failed C2 after those assertions.

**Existing-test edits (§4 and one consequence).** `WorldSharingPage.test.tsx` only: the two give-role queries are scoped to the "Give someone a role" form (the hosting field's accessible name is now also "Login name", which the plan allows; this makes an unscoped query ambiguous), and the saved-but-not-read-back case's old fixed "Role assigned" texts became the §3.2 item 3 sentence. No other assertion changed.

**Runs (PowerShell, `C:\Users\nemes\dnd_ai\portal`).**
- Focused (§7.1): `WorldSharingPage.panels`, `WorldSharingPage`, `useAuthoringMutation`, `useUnsavedChangesGuard.registration`, `App`: 5 files, **133 passed**.
- Full `npm test`, first run: **453 files, 5841 passed, 0 failed**. A second full run after the last test assertions were added: 453 files, 5841 passed, 0 failed. No failure to report.
- `npm run lint`, `npx tsc -b` and `npm run build` pass (chunk-size notice only). `uv run python scripts/check_documentation.py` and `git diff --check` pass.

**Probes (each reverted; `WorldSharingPage.tsx` restored byte-for-byte, SHA-256 prefix `0a8689108ec1`).**
- M1 (the login or row id dropped from the descriptor, request reads a drifting value): failed C1 and C2 (with the key assertions), plus C18, C19 and C22 as a side effect.
- M2 (clear the login on submit): failed C4, C3b, C15.
- M3 (ignore `changed`): failed C6 and C7.
- M4 (no 403/404 re-read): failed C10, C11, C12.
- M5 (a re-read that still lists the row treated as confirmed after an unknown end-role): failed C14.
- M6 (Retry sends a new descriptor, so a new key): failed C3a.
- M7 (remove the content key): **no case fails**, by design; 53 passed. Redundant with the loading-branch isolation, as the plan correction records.
- M8 (guard mounted twice): failed C20.
- M9 (clear the field on confirmation even if edited): failed C5.

**Not done / limits.** No browser or AX check (including the real-browser focus question for C10, C11, C13 and C18). Transfer feedback and any transfer 403/404 re-read are S02's. The departure guard relies on the shared guard's first-commit registration (C18 attempts the departure straight after the write begins, with no wait).

**Review range for Luna (§11.2).** `60cfd3dc4765f3953b0894316fe5ca61f867067c..d7e08866050d05235c03fe94ddb8837d2015dfd5` plus the docs-only records commit that follows it.

#### 11.4 Independent review (Codex, 2026-11-24)

**Verdicts:** **T01: CHANGES REQUIRED. S01: CHANGES REQUIRED** pending the bounded T01 correction and re-review. The failure is a direct C5 contract miss; it does not change the S02 boundary or require a shared-hook change.

**Finding C5-1 — confirmation can erase a newer edit with the same trimmed login.** Track: application. `WorldSharingPage.tsx`, `onSuccess` field clearing. On the supported owner give-role path, submit `dana`, edit the still-visible field to `dana ` while the POST is pending, then confirm the POST. The field becomes empty because the updater compares `current.trim()` with the submitted login. This silently discards newer input; it does not alter the confirmed request or durable state, and the owner can retype the value. Rubric: exposure 2 (normal, limited owner-panel action), impact 1 (one edited field is lost), triggerability 2 (routine typing during a pending request), detection/recovery 0 (visible and readily retyped), blast radius 0; **score 5, Medium**. Readiness: blocks this slice because C5 and §3.2 item 2 promise to preserve edits made while pending. Bounded correction: track whether the field changed after submission and clear only the untouched submitted value; keep request payload/key semantics stable. Add the same-login-with-whitespace edit to C5 (and the hosting field if it shares the clearing rule), then rerun focused panels, full portal tests, lint, typecheck, build, documentation and diff checks. No owner risk acceptance is recorded.

**Review evidence and boundaries.** Confirmed ancestry `60cfd3d -> d7e0886 -> d37441a`, HEAD `d37441a`, and clean worktree before review. The implementation range is the five files recorded in §11.3; the records commit changes only this plan and the work register. Reviewed C1–C22 and the reported test-first/probe record, including the C2 different-row key assertions added after the first test-first run. DV-6 is not reproduced: the resource loading branch unmounts the content on world/account changes; C21 is a baseline-passing guard; C3a is a baseline retry guard while C3b exposes the cleared-login defect; M7 correctly has no required failing case. The recorded M1–M6/M8/M9 failures are consistent with their described mutations; M7 is correctly redundant. Transfer request body/feedback remain S02-owned and unchanged in scope. The settlement effect is narrowly suppressed because it responds to an applied read, closes/announces a settled row operation, and depends on `view`, `settling`, `announce`, and the stable `resetMutation`; no dependency omission was found. The useAuthoringResource implementation aborts/supersedes overlapping reads, and the added C14 case exercises an earlier unknown read overlapping a newer operation.

Independent checks: focused page/hook/guard/App tests **133 passed**; standalone resource/kept/confirmed-refresh tests **28 passed**; lint, `tsc -b`, build, documentation check and range `git diff --check` passed (build emitted the existing chunk-size warning). Implementer-recorded full-suite runs remain two distinct clean events, each 453 files / 5,841 passed / 0 failed; they were not rerun independently for this review. A temporary C5 regression probe failed as predicted (`Expected dana `, received empty); test source was restored byte-for-byte (Git blob `6d43200c9479390408862da1888139416e641ab6`). No product source was changed. CI remains pending the checkpoint PR; browser/AX, human review and owner acceptance remain pending. No PR was opened and S02/consumers were not started.

**Sonnet correction handoff.** Correct C5-1 within the existing page/test scope. Preserve later typing even when its normalized login equals the submitted login. Keep `changed:false`, same-attempt retry keys, mutation/read ownership and transfer behavior intact. Record the correction commit, failing-first regression, focused and full runs as separate events, and rerun the proportional checks above; then request independent re-review. Do not start S02 or consumers.

### 11.5 Correction of C5-1 (Sonnet, 2026-11-24)

**Status:** C5-1 **corrected at `755f05cbd65ae1ceda8897e09430ed5a7fa91b2c` (`P15-C05-S01-C5-1: keep newer sharing input whose trimmed login equals the confirmed one`), pending independent confirmation.** Baseline `d37441a13ca063f0280726743e3d1cce36d38c15` (HEAD and `origin/phase15/completion`). Luna's uncommitted §11.4 review and register edits are preserved and committed with this record; the original CHANGES REQUIRED review and its finding text stay above as history, and the implementation record in §11.3 is unchanged. No S02 work, PR, consumer, or browser/AX, human or owner acceptance.

**Cause.** On confirmation the page cleared a login field with an updater that compared `current.trim()` with the submitted login, so a newer edit that reads the same after trimming (`dana` then `dana `), or one made away from and back to the submitted text, was cleared as if untouched.

**Fix (`WorldSharingPage.tsx` only).** Each login field (the give-role field and the hosting field) has an edit counter that every change increments (`changeLogin`, `changeUseLogin`). `submit` records the operation and the field's count at the moment of that submit. A confirmation clears the field only when (a) the confirmed operation is that latest submitted one (compared by its serialized descriptor) and (b) the field has not been edited at all since. Any other confirmation clears nothing. Unchanged: request normalization (the trimmed login is what is sent), the submitted descriptors, `mutation.submit`/`retry` semantics, and therefore the body and key of a same-attempt retry. A Retry (which does not call `submit`) keeps the original submit's count, so an edit made after the original press is kept; pressing Give role again with an unchanged descriptor is a new submit and takes a new count. The role select is still not cleared. An account or world change still unmounts the content, discarding every page-local value (the counters are refs of that component). The counters are written only in change and submit handlers and read only in the confirmation callback.

**Failing-first regressions** (added to `WorldSharingPage.panels.test.tsx` before the fix; run against the baseline code, **5 failed, 7 passed** among the 12 cases of the C5-C8 group):
- failed: same-login whitespace edit during a pending give-role (`dana` then `dana ` was cleared); the equivalent hosting-grant case; edit away and back (`danaX` then `dana`) for the give-role field; the same for the hosting field; and a Retry after an edit (the exact body and key were sent, but the edited field was cleared).
- passed (guards): the untouched give-role field still clears; the field edited to a different login while pending is kept (the original C5); the untouched hosting field still clears; the existing C3a, C3b and C14 cases keep their retry body and key semantics.
After the fix all 43 cases in the file pass.

**Runs (PowerShell, `C:\Users\nemes\dnd_ai\portal`).** Focused (`WorldSharingPage.panels`, `WorldSharingPage`, `useAuthoringMutation`, `useAuthoringResource`, `useConfirmedRefresh`, `useUnsavedChangesGuard.registration`, `App`): 7 files, **161 passed**. `npm run lint`, `npx tsc -b`, `npm run build`, `uv run python scripts/check_documentation.py` and `git diff --check` pass. **No full-suite rerun:** the change is two edit counters and one confirmation condition inside one page component and touches no shared module; the earlier full runs (453 files, 5,841 passed, twice, §11.3) predate it and are not claimed for it.

**Targeted mutation probe.** Restoring the trimmed-equality updaters in the confirmation callback (`setLogin((c) => c.trim() === operation.login ? "" : c)` and its hosting twin) failed exactly the five regressions above (5 failed, 38 passed). `WorldSharingPage.tsx` was restored byte-for-byte (SHA-256 prefix `667ca8ee5030` before and after).

**Re-review range.** `d37441a13ca063f0280726743e3d1cce36d38c15..755f05cbd65ae1ceda8897e09430ed5a7fa91b2c` (`WorldSharingPage.tsx` and `WorldSharingPage.panels.test.tsx`) plus the docs-only records commit that follows. CI: pending the C05 checkpoint PR. Browser/AX, human and owner acceptance remain pending.

# D/P15-C04-S02 implementation plan: stage and reconcile per-role changes

**Status:** Opus plan prepared 2026-11-23. **Ready for Sonnet: T01 first, then T02.** No owner decision blocks either task. Section 10 lists the routine choices made here; none changes a product policy, an API contract or authorization.

**Register rows:**
- slice [D/P15-C04-S02](work-register.md#p15-c04-s02);
- tasks [T01](work-register.md#p15-c04-s02-t01) and [T02](work-register.md#p15-c04-s02-t02);
- parent checkpoint [D/P15-C04](work-register.md#p15-c04).

**Plan-entry head:** `632f3058ed1aa7520e076e5d280a637fcb9aba21` on `phase15/completion`. It is the S01 review-records commit on top of S01's reviewed head `39d2a18e8949f0321951b843d03c5a52ae9bc925`, so this plan is prepared against S01's implementation (the register's scheduling note). Clean worktree. No C04 CI run exists; the C04 checkpoint PR has not been opened.

Sonnet's implementation baseline for T01 is the commit that adds this plan, a child of `632f305`. The handoff prompt names it. T02's baseline is the T01 records head.

**How each statement was established:**
- by reading source, tests and documents at the plan-entry head;
- by a temporary plan-entry reproduction (§2.2): one Vitest file, written into `portal/src/pages/` only for the run and deleted afterwards. It rendered the real `AdminAccountsPage`, `SystemRolesEditor` and `useSystemRoleChange` with the list read, the two role writes and the session faked. No repository file was changed by it.

**Governing sources:**
- [Portal behavior §4.4](../reference/portal-behavior.md#44-platform-accounts-authorization): visibility from `accounts.manage`, the System roles editor gated on `system_roles.manage`, Administrator grant only with `system_roles.grant_admin`, non-disclosing server refusals, and S01's list search, reset-link and departure behavior.
- [Portal behavior §5.11](../reference/portal-behavior.md#511-authoring-patterns-phase-14): unsaved-input guard, one meaningful announcement.
- [R07](work-register.md#r07--platform-users-administration): "Stage per-account role deltas with Save/Cancel … uses existing endpoints and an explicit per-change result ledger; it must not claim atomicity … Reconcile uncertain writes from authoritative role state; require a separate API design if stronger retry/atomic semantics are needed." Acceptance: "local Cancel before writes; confirmed/failed/unknown substeps; self-role loss; admin grant setting; last-active-admin protection; activation/reset links retained safely in transient memory."
- The register's [C04](work-register.md#criteria-p15-c04), [S02](work-register.md#criteria-p15-c04-s02), [T01](work-register.md#criteria-p15-c04-s02-t01) and [T02](work-register.md#criteria-p15-c04-s02-t02) criteria: "Enable staged Save only with honest partial results. Exercise self-role loss, last-admin refusal and grant setting."
- [ADR 0020](../adr/0020-scoped-system-world-and-campaign-roles.md) and `src/dnd_ai/domain/system_authority.py`: `admin` carries `accounts.manage`, `system_roles.manage` and (with the deployment setting) `system_roles.grant_admin`; `gm` carries `world.create`, `campaign.host` and `world.administer`; `player` and `observer` carry none.
- The role API (`src/dnd_ai/api/local_auth.py`, `src/dnd_ai/commands/system_roles.py`), unchanged by this slice:
  - `POST /api/admin/accounts/{user_id}/system-roles` `{system_role_code}`: 201 when newly assigned, 200 `changed:false` when already held. 403 `admin_grant_disabled` for `admin` while the deployment setting is off. Non-administrator caller: fixed 404.
  - `POST /api/admin/accounts/{user_id}/system-roles/{code}/revoke`: 200 `changed:true|false`; 409 `last_active_platform_administrator` when it would leave no active administrator (serialized with disablement by an advisory lock); `stranded_world_ids` for a `gm` revoke.
  - Each call is its own transaction. Both are **state-idempotent** (a repeat converges, it never duplicates) and take **no idempotency key**. There is no multi-role or atomic operation and no single-account read; `GET /api/admin/accounts?q=&limit=` (max 100, substring match on display name and active or pending login name) is the only authoritative read.
- [atomic-roles](work-register.md#atomic-roles) is a separate, unadmitted proposal. This plan neither implements nor depends on it.

## 1. Entry readiness

C04 has no checkpoint prerequisite. S02's prerequisite is "Checkpoint entry criteria; no additional slice-specific gate", confirmed at `d09429f` (S01 plan §1). S01 is independently reviewed PASS WITH VERIFICATION LIMITS (S01 plan §11.6); S02 does not depend on that verdict, but the plan uses S01's implementation as its baseline because both slices edit `AdminAccountsPage.tsx`.

**Verdict: S02 eligible; T01 ready for Sonnet; T02 ready after T01.**

## 2. Verified current behavior

### 2.1 How roles are changed today

- `AdminAccountsPage` renders, in each row's System roles cell, the roles as text **and** a `SystemRolesEditor` fieldset (four checkboxes) when `system_roles.manage` is held.
- Each checkbox `onChange` calls `useSystemRoleChange.change` at once: one POST per press, no draft, no Save, no Cancel. All checkboxes are disabled while one write is pending.
- On success the editor calls `onChanged`, which is the list's `retry`: the list goes back to `loading`, the table unmounts and every row editor (with its status) is remounted.
- Outcome mapping: 401 → session `reload()`; 403 and 404 → "You do not have permission to change this role."; 409 → the last-administrator text; anything else, including a transport failure and a 5xx, → "The role could not be changed. Try again."
- `api/systemRoles.ts` throws `PlatformAccountsRequestError(status)` and discards the response body, so `admin_grant_disabled` cannot be told apart from another 403 (for example a stale CSRF token).
- Nothing refreshes the session bootstrap after a change to the signed-in account's own roles.
- S01's `ResetLinkGuard` is the page's only `useUnsavedChangesGuard` (react-router supports one blocker per page).

### 2.2 Plan-entry reproduction results

Temporary file `portal/src/pages/zzC04S02Repro.test.tsx`, run from `C:\Users\nemes\dnd_ai\portal` with `npx vitest run`: **1 file, 5 tests passed** (each test asserts the current, deviating behavior). The file was then deleted; `git status` was clean.

| # | Reproduction | Observed |
|---|---|---|
| P1 | Press the Game master checkbox for Alice | `assignSystemRole("user-1","gm",…)` called once at once; no Save and no Cancel button exists. |
| P2 | Confirmed assign with focus on the checkbox | "Loading accounts…" replaces the table; focus is on `body`, and stays there after the list returns. |
| P3 | Assign rejects with `TypeError` (transport), then with 503 | Both show "The role could not be changed. Try again."; neither is reported as unknown. |
| P4 | Assign `admin` rejected with 403 (as `admin_grant_disabled` answers) | "You do not have permission to change this role." |
| P5 | Revoke one's own Administrator (confirmed), list read then 404 | Sent at once with no question; no bootstrap refresh or reload; the page shows "You do not have permission to view this page." with the Create account link still present. |

### 2.3 Deviations S02 repairs

- **DV-1 (no staging).** Every checkbox press writes at once; there is no local Cancel before writes (P1).
- **DV-2 (remount on refresh).** A confirmed write sends the list back to loading; the editor and its outcome are destroyed and focus falls to `body` (P2).
- **DV-3 (no unknown outcome).** A transport failure or 5xx is reported as a failure that invites a retry, though the write may have committed (P3).
- **DV-4 (refusals misdescribed).** `admin_grant_disabled` is reported as a permission denial (P4).
- **DV-5 (self-role loss).** Removing one's own Administrator role asks nothing, leaves a stale bootstrap and lands on a list denial with live-looking controls; no receipt of what happened is kept (P5).

### 2.4 Reviewed behavior that must not regress

- All of S01 (plan §§3.2, 6, 8): the `/platform/accounts/new` route, `?q=` written by REPLACE, the validated `accountsReturn`/`accountsFocus` keys, the Create account link focus on PUSH return, the reset-link panel above the table, its departure question "Leave without the password-reset link?", search typing not being a departure, the page keyed by `bootstrap.user.user_id`, and the C04-S01-R1 unknown-create departure question. S01's tests keep their expectations.
- Administrator: a new grant is offered only with `system_roles.grant_admin`, with the operator-script note otherwise; an already-held Administrator can always be removed.
- "A system role never grants access to any campaign or world" stays on the editor.
- Lifecycle actions, Load more and the stranded-world notice are unchanged.

## 3. Outcome, scope and exclusions

### 3.1 User outcome

An administrator opens one account's roles, ticks and unticks freely, sees what will change, and either cancels (nothing sent) or saves. Saving sends one request per changed role, one at a time, and then shows what happened to each: saved, already so, refused with the reason, not confirmed, or not sent. The portal then reads the account's current roles from the server and shows them; anything not confirmed is either confirmed from that read or stays staged for a deliberate second Save. It never says the set was saved as a whole when it was not. Removing one's own Administrator role is asked first, is sent last, and ends in a receipt rather than a broken page.

### 3.2 In scope

**T01: stage deltas and local cancel** (no write path):

1. **Pure staging module** `portal/src/utils/systemRoleStaging.ts`:
   - `stagedChanges(baseline, draft)` → ordered list of `{code, action: "add" | "remove"}`: adds first, then removes, each in `SYSTEM_ROLE_OPTIONS` order; a removal of `admin` from the signed-in account (`selfUserId` argument) is always last.
   - `isDirty(baseline, draft)`; `describeChange(change)` → "Add Game master" / "Remove Player" using the option labels.
2. **`SystemRolesPanel`** (`portal/src/components/SystemRolesPanel.tsx`), replacing `SystemRolesEditor` and `useSystemRoleChange` (both deleted with `SystemRolesEditor.test.tsx`):
   - a `section` labelled by an `h2` "System roles for ‹display name›" (`tabIndex={-1}`), rendered **above the table**, beside the reset-link panel, never inside a row, so a list reload cannot unmount it;
   - a fieldset of the four checkboxes bound to the draft. Administrator: a new grant is disabled with the existing operator-script note unless `system_roles.grant_admin`; removing a held Administrator is always enabled;
   - the line "A system role never grants access to any campaign or world." and, in T01, "Changes are saved one at a time; some can be saved while others are not.";
   - "Changes not saved yet" followed by a list of `describeChange` lines when dirty, "No changes" otherwise (plain text, not a live region);
   - **Cancel** (when dirty): restores the draft to the baseline, sends nothing, closes the panel. **Close** (when clean): closes the panel.
3. **Page wiring** in `AdminAccountsPage.tsx`:
   - each row's System roles cell shows the roles text and, with `system_roles.manage`, a button **Edit roles** with accessible name "Edit roles for ‹display name›";
   - page-level state `roleEdit: { userId, account snapshot, draft } | null` in `AuthorizedAccountsPage`, above the loading boundary;
   - pressing Edit roles opens the panel for that account and focuses its heading. While the open panel is dirty, every other row's Edit roles button is disabled and the panel says "Save or cancel these changes before editing another account." A clean panel is replaced by the newly chosen account;
   - while clean, the panel follows the latest list item for its account (so a list reload after a lifecycle action shows current roles). While dirty, its baseline stays as it was when editing began;
   - closing the panel (Cancel, Close) returns focus to that account's Edit roles button when it is rendered, otherwise to the search field;
   - a search change, Load more and lifecycle `onChanged` reloads keep the panel and its draft;
   - the panel and its buttons are not rendered without `system_roles.manage`.
4. **One page guard.** `ResetLinkGuard` becomes a single page-level `useUnsavedChangesGuard(resetShown || rolesDirty)` with one `ConfirmDialog`:
   - only a reset link shown: exactly S01's title and description (unchanged);
   - unsaved role changes: title "Discard unsaved role changes?", description "Your changes to ‹name›'s system roles have not been saved." plus, when a reset link is also shown, " The password-reset link shown on this page will also be lost.";
   - Leave/Stay labels as S01. Search typing is still not a departure (no `disposingQuery`).
5. **Documentation:** `docs/reference/portal-behavior.md` §4.4: replace the "System roles editor (… checkboxes …)" wording with the staged panel and add a "Staged system roles (P15-C04-S02; T01 implemented, Save in T02)" paragraph.

**T02: apply per-change outcomes and reconcile:**

6. **Error codes.** `PlatformAccountsRequestError` gains an optional readonly `code?: string` (third constructor argument). `api/systemRoles.ts` reads the error envelope's `error.code` best-effort (an unreadable body leaves it undefined) and returns the parsed `SystemRoleChangeResponse` on 2xx. An unparseable 2xx body is treated as unknown (item 8).
7. **`useSystemRoleSave`** (`portal/src/hooks/useSystemRoleSave.ts`), page-level, one save at a time:
   - `save(account, changes)` sends the changes **sequentially** in `stagedChanges` order through `assignSystemRole` / `revokeSystemRole`. Nothing is sent in parallel; nothing is sent without a Save press.
   - Per-step outcome (the **ledger**):

     | Answer | Step outcome | Batch |
     |---|---|---|
     | 2xx `changed:true` | **Saved** ("Game master added" / "Player removed") | continue |
     | 2xx `changed:false` | **Already so** ("Already had Game master" / "Already did not have Player") | continue |
     | 409 `last_active_platform_administrator` | **Refused**: "This is the platform's only active administrator and cannot lose the Administrator role." | continue |
     | 403 `admin_grant_disabled` | **Refused**: "Granting Administrator is done by the operator script on this deployment." | continue |
     | other 4xx except 401/403/404 | **Refused**: "This change was refused." | continue |
     | 403 (other code), 404 | **Refused**: "You do not have permission to make this change." | **stop**: later steps **Not sent** |
     | 401 | **Not sent** for this and later steps; session `reload()` | stop |
     | transport failure, 5xx, unreadable 2xx | **Not confirmed** | **stop**: later steps **Not sent** |

   - A `gm` removal whose answer lists N stranded worlds adds "N world(s) this account owns now have no manageable Owner." (a count only; no identifiers).
   - **Reconciliation** after any save that sent at least one request: one `fetchPlatformAccounts({ q: account.login_name ?? account.display_name, limit: 100 })`, matched by `user_id`. Outcomes:
     - **found:** its `system_roles` become the panel's baseline; the list's row is replaced in place (item 9); each **Not confirmed** and **Not sent** step becomes "Confirmed from current roles" when the current roles already match the intended change, and otherwise stays staged in the draft. **Refused** steps are dropped from the draft. The draft is therefore baseline plus still-unapplied intended changes;
     - **not found** (beyond the first 100 matches, or renamed meanwhile) or a transport/5xx failure: "We could not check this account's current roles." Save is disabled; **Check current roles** repeats only this read (one GET per press, never a POST); Cancel/Close stay available;
     - **404:** the access-check receipt (item 10).
   - **Retry** is only a later Save press. It sends `stagedChanges(reconciled baseline, draft)`, never the earlier batch. Because the endpoints are state-idempotent and the baseline is re-read, no confirmed step is repeated and no unknown one is replayed blindly. Save is disabled while saving, while reconciliation is pending or failed, and when the draft is clean.
   - Unmount (departure, account change) aborts the outstanding wait; a late answer is ignored; nothing more is sent.
8. **Panel (T02 additions):** a **Save changes** button; while saving, "Saving changes…" and every checkbox, Save and Cancel disabled; after a save, a "Result" `h3` (`tabIndex={-1}`) and the ledger list, and a polite status sentence: "‹a› of ‹n› changes saved." followed, when present, by "‹r› refused.", "‹u› could not be confirmed.", "‹s› not sent." ("Already so" counts as saved). When reconciliation confirms an unknown step, the sentence is recomputed. No text claims the changes were applied together.
9. **In-place list update.** `usePlatformAccounts` gains `replaceAccount(account)`: in a success state it replaces the item with the same `user_id` (no loading state, no refetch); otherwise it does nothing. The page no longer passes `retry` to the roles editor.
10. **Self-affecting changes** (the account is `bootstrap.user.user_id`):
    - Save with a staged removal of one's own Administrator first asks: `ConfirmDialog` "Remove your own Administrator role?", "You will lose Platform accounts and system-role management as soon as it is saved. Another administrator would have to give it back.", **Remove my role** / **Keep editing**. Keep editing sends nothing and keeps the draft.
    - The removal is sent last (item 1). If an earlier step stopped the batch, it is **Not sent**.
    - When it is **Saved** (or reconciliation confirms it), the page content below the `h1` is replaced by a receipt: `h2` "Your Administrator role was removed" (focused), the ledger, "Platform accounts will close when you continue.", and **Continue**. Continue calls the session `refresh()`; when that fails (`bootstrapRefreshOutcome` "failed"), `reload()`. The route adapter then shows its denial. No list, Create account link, Edit roles or lifecycle control is rendered under the receipt.
    - A reconciliation 404 shows the same receipt shape with `h2` "Your access to platform accounts may have changed" and "We could not check the result. Continue to update your access."
    - Any other confirmed change to one's own roles (for example `gm`) calls `refresh()` once after reconciliation, without unmounting the page; the ledger stays.
    - A 409 on one's own Administrator removal is an ordinary refusal: no receipt, no refresh.
11. **Guard (T02 addition):** while saving, the page guard holds path changes with "Leave while role changes are being saved?", "Changes already sent may still be saved. You will not see their result." Leave aborts the wait and sends nothing more. This reason takes priority over the others; a shown reset link adds S01's sentence as in item 4.
12. **Documentation:** §4.4 paragraph completed with items 6–11 and its status.

### 3.3 Exclusions

- No backend, API, authorization or schema change; no idempotency key; no multi-role or atomic endpoint (that is [atomic-roles](work-register.md#atomic-roles), unadmitted).
- No new route; no single-account read; no client-side last-administrator prediction (the server decides).
- No change to `usePageArrival`, `useUnsavedChangesGuard`, `navigationHolds`, the announcer, the task-origin modules, `CreateAccountPage`/`CreateAccountPanel`, `OneTimeSecretPanel` or `AccountLifecycleActions`.
- No retained receipt after sign-out (a 401 reloads the session; see §8).
- No copy-ui, preview or other consumer; no browser/AX run; no acceptance.

## 4. Affected files and interfaces

| File | Task | Change |
|---|---|---|
| `portal/src/utils/systemRoleStaging.ts` (+ `.test.ts`) | T01 | new pure module |
| `portal/src/components/SystemRolesPanel.tsx` (+ `.test.tsx`) | T01, T02 | new; Save/ledger in T02 |
| `portal/src/components/SystemRolesEditor.tsx`, `.test.tsx`; `portal/src/hooks/useSystemRoleChange.ts` | T01 | deleted |
| `portal/src/pages/AdminAccountsPage.tsx` | T01, T02 | Edit roles buttons, page-level panel, single guard; save hook, receipts, `replaceAccount` |
| `portal/src/pages/AdminAccountsPage.roles.test.tsx` | T01, T02 | new integration file: real page, panel, hooks; network and session faked |
| `portal/src/pages/AdminAccountsPage.test.tsx` | T01 | only its `SystemRolesEditor` mock is replaced (the module is gone); its assertions stay |
| `portal/src/api/platformAccounts.ts`, `portal/src/api/systemRoles.ts` (+ `systemRoles.test.ts`) | T02 | optional `code`; envelope parsing |
| `portal/src/hooks/useSystemRoleSave.ts` (+ `.test.ts`) | T02 | new |
| `portal/src/hooks/usePlatformAccounts.ts` (+ existing test) | T02 | add `replaceAccount`; existing cases unchanged |
| `docs/reference/portal-behavior.md` §4.4 | T01, T02 | as §3.2 items 5 and 12 |

**Only allowed changed test expectations:** the deletion of `SystemRolesEditor.test.tsx` (its immediate-write expectations are the deviation), the replaced mock in `AdminAccountsPage.test.tsx`, and one assertion there: line 83's `screen.getByText("system-roles-user-1")` (text only the deleted per-row editor's mock produced; the panel is no longer in the row, §3.2 item 2) is replaced by an assertion for the accessible button "Edit roles for GM Two". This clarification was approved by the owner at T01 entry (2026-11-23) after Sonnet stopped under §11.1 step 5; no wrapper component may be added to keep mock-generated text. Every other assertion in that file stays. Every S01 test file (`CreateAccountPage.test.tsx`, `CreateAccountPanel.test.tsx`, `AdminAccountsPage.resetLink.test.tsx`, `App.platformAccounts.test.tsx`, `platformAccountsReturn.test.ts`, `useCreateAccount.test.ts`) keeps its expectations.

## 5. Task commits

- **T01:** `P15-C04-S02-T01: stage system-role changes in one account panel with local cancel`
- **T02:** `P15-C04-S02-T02: save staged system-role changes one at a time with per-change outcomes and reconciliation`

Each is followed by a docs-only records commit (plan §11 and the register).

## 6. Acceptance cases

"(fails at baseline)" means the case is written first and fails at that task's baseline (T01: this plan's commit; T02: the T01 records head); record each failure. Integration cases use `AdminAccountsPage.roles.test.tsx` with a data router; the self account is the fixture's `user-fixture-001`.

**T01**

| # | Case |
|---|---|
| B1 (fails at baseline) | Opening Alice's roles and ticking Game master and unticking Player sends no request; the panel lists "Add Game master" and "Remove Player". |
| B2 (fails at baseline) | Cancel restores the draft and closes the panel with no request; Alice's row still shows `player`; focus is on "Edit roles for Alice Example". |
| B3 (fails at baseline) | Pressing Edit roles focuses the "System roles for Alice Example" heading. The panel is outside the table: a search change (list reloads) and a lifecycle `onChanged` reload keep the panel and its draft. |
| B4 | Without `system_roles.grant_admin`, a new Administrator is disabled with the operator-script note; on an account holding `admin` the box is enabled and can be unticked; with the capability, a new grant can be staged. |
| B5 | With `accounts.manage` but not `system_roles.manage`, no Edit roles button and no panel. |
| B6 | While Alice's panel is dirty, Bob's Edit roles is disabled and the panel explains why; when clean, pressing Bob's replaces the panel. |
| B7 | Unticking back to the baseline gives "No changes" and releases the guard. |
| B8 | With staged changes, a path change asks "Discard unsaved role changes?"; Stay keeps the draft; Leave navigates; typing in the search asks nothing. With a reset link also shown, one dialog appears (one blocker, no router warning) and its description names both. A reset link alone gives S01's dialog unchanged. |
| B9 | An account change (page key) drops the panel and its draft. |
| B10 | While clean, the panel shows the latest list roles after a list reload; while dirty, its baseline does not move. |

**T02**

| # | Case |
|---|---|
| B11 (fails at baseline) | Staging +GM, −Player and pressing Save sends assign `gm` then revoke `player`, one after the other (the second only after the first settles), and nothing for unchanged roles. |
| B12 (fails at baseline) | All confirmed (one `changed:false`): ledger "Game master added", "Already did not have Player"; status "2 of 2 changes saved."; one reconciliation GET with `q` = login name and `limit=100`; the row updates in place, the table never shows "Loading accounts…", and focus is on "Result" when it was lost. |
| B13 | Removing `admin` answered 409 alongside a confirmed `gm` add: the refusal shows the last-administrator text, the other step is saved, status "1 of 2 changes saved. 1 refused."; the refused change is no longer staged. |
| B14 | 403 `admin_grant_disabled` refuses only that step with the operator-script text and later steps are sent. A 403 with another code or a 404 refuses that step with the permission text and marks later steps Not sent; no further POST. |
| B15 | 401 on a step: it and later steps Not sent; `reload()` called once; no further POST. |
| B16 (fails at baseline) | A transport failure (and separately a 503) on step 1 of 2: step 1 "Not confirmed", step 2 "Not sent", no second POST. Reconciliation showing step 1 applied marks it "Confirmed from current roles"; showing it not applied keeps it staged. The next Save sends only the still-differing changes. |
| B17 | Reconciliation fails (network) or the account is absent from the result: "We could not check this account's current roles."; Save disabled; Check current roles sends one GET per press and no POST; Cancel/Close send nothing. |
| B18 | No confirmed step is ever re-sent: after B16's reconciliation, Save sends exactly the remaining delta; pressing Save twice quickly sends one batch. |
| B19 (fails at baseline) | Self: staging removal of own Administrator plus +Observer and pressing Save asks "Remove your own Administrator role?"; Keep editing sends nothing. Remove my role sends assign `observer` first and revoke `admin` last; on confirmation the receipt "Your Administrator role was removed" takes focus with the ledger and no list, Create account link, Edit roles or lifecycle controls; `refresh()` is not called until Continue; Continue calls `refresh()` once, and `reload()` when it rejects. |
| B20 | Self Administrator removal answered 409: ordinary refusal, no receipt, no `refresh()`. |
| B21 | Self `gm` removal confirmed: `refresh()` called once after reconciliation; the panel and ledger stay. A change to another account never calls `refresh()`. |
| B22 | Reconciliation answered 404: the "Your access to platform accounts may have changed" receipt with Continue. |
| B23 | A path change while saving asks "Leave while role changes are being saved?"; Leave aborts and no later step is sent; Stay continues the batch. Search typing while saving asks nothing and the batch continues. |
| B24 | An account change while saving: no late outcome appears under the new account and no later step is sent. |
| B25 | A `gm` removal answered with two stranded worlds shows "2 world(s) this account owns now have no manageable Owner." and no identifier. |
| B26 | The panel says "Changes are saved one at a time; some can be saved while others are not."; no status or ledger text says the changes were saved together unless every step is Saved or Already so. |
| B27 | `systemRoles.ts`: a 403 envelope with `admin_grant_disabled` yields `code`; an empty or non-JSON error body yields `code` undefined and the status; a 2xx non-JSON body rejects as unknown. |

S01's A1–A20 stay green through both tasks (§2.4).

### 6.1 Mutation probes (run by Sonnet; re-run by the reviewer)

| # | Task | Mutation | Must fail |
|---|---|---|---|
| M1 | T01 | Call the old immediate write from a checkbox change | B1 |
| M2 | T01 | Cancel closes without restoring the draft (reopen shows the draft) | B2 |
| M3 | T01 | Render the panel inside the row's cell | B3 |
| M4 | T01 | Mount a second `useUnsavedChangesGuard` for roles instead of the single page guard | B8 |
| M5 | T02 | Continue after Not confirmed instead of stopping | B16 |
| M6 | T02 | Treat a 5xx as Refused (dropped from the draft) | B16 |
| M7 | T02 | Retry resends the original batch instead of `stagedChanges(reconciled, draft)` | B18 |
| M8 | T02 | Order self Administrator removal first | B19 |
| M9 | T02 | Call `refresh()` immediately after a confirmed self Administrator removal | B19 |
| M10 | T02 | Map `admin_grant_disabled` to the stopping permission branch | B14 |
| M11 | T02 | Use `retry` instead of `replaceAccount` after reconciliation | B12 |

Revert every probe and record its failing case.

## 7. Verification

### 7.1 Per-commit checks (Sonnet; repeated by the reviewer)

From PowerShell in `C:\Users\nemes\dnd_ai\portal` (uppercase `C:`):
- focused: `npx vitest run src/pages/AdminAccountsPage.roles.test.tsx src/pages/AdminAccountsPage.test.tsx src/pages/AdminAccountsPage.resetLink.test.tsx src/components/SystemRolesPanel.test.tsx src/utils/systemRoleStaging.test.ts src/App.platformAccounts.test.tsx src/pages/CreateAccountPage.test.tsx` plus, for T02, `src/hooks/useSystemRoleSave.test.ts src/hooks/usePlatformAccounts.test.ts src/api/systemRoles.test.ts`;
- full `npm test`. Record the first run and any rerun separately, and name any failure outside these files;
- `npm run lint`, `npm run build`;
- from the repository root: `uv run python scripts/check_documentation.py` and `git diff --check`.

Backend checks are not required; a backend change is a stop condition.

### 7.2 C04 checkpoint merge requirements (not S02's verdict)

Unchanged from [S01 plan §7.2](p15-c04-s01-account-creation-route-plan.md#72-c04-checkpoint-merge-requirements-not-s01s-verdict): the C04 PR merges only when (1) S01 and S02 have each passed independent review, (2) S01's A1–A20 and S02's B1–B27 pass on the integration head with one full portal run showing both together, and (3) CI passes on that exact head. None of §7.3 is a merge gate.

### 7.3 Separate events (after the merge; not merge gates)

- Integrated-head browser evidence ([browser](work-register.md#browser)): B3, B12, B19, B23 focus and announcement in a real browser; the S01 items in its §7.3; and the inherited `usePageArrival` uncertainty (S02 does not use it).
- AX evidence ([ax](work-register.md#ax)) and owner acceptance (`p15-owner`). Nothing here grants them.

## 8. Authorization, disclosure, concurrency and focus rules

- **Server-authoritative.** Every capability check in the portal is presentation. Each POST and the reconciliation GET are authorized by the server; the portal never predicts the last-administrator rule or the deployment's grant setting beyond the existing `system_roles.grant_admin` presentation gate. A refusal is shown as refused, never as saved.
- **No atomicity claim.** Changes are separate transactions sent one at a time. Partial success is a normal, reported outcome. Stronger semantics require [atomic-roles](work-register.md#atomic-roles).
- **Unknown and retry.** Only a transport failure, a 5xx or an unreadable 2xx is unknown. The batch stops there; the authoritative read decides; a retry is a deliberate Save of the recomputed difference. The endpoints converge on repeat, so a retry cannot duplicate an assignment, but recomputing first keeps it from overriding a concurrent administrator's change with a stale intent.
- **Disclosure.** The reconciliation read uses an existing administrator-only request; the ledger shows role labels, server-safe messages and a stranded-world count only. Nothing enters the address, router state or storage. S01's one-time links are unaffected.
- **Isolation.** The page is keyed by `bootstrap.user.user_id`; an account change aborts waits and drops the panel, draft and ledger. Capability loss through the route adapter unmounts everything. One role save at a time per page.
- **Self-role loss.** Asked first, sent last, followed by a receipt that does not depend on the stale bootstrap; the bootstrap is refreshed on Continue. A sign-out (401) loses the ledger: the person can re-read the account's roles after signing in. That is an accepted limitation, consistent with S01.
- **Focus.** Edit roles → panel heading. Cancel/Close → that row's Edit roles button, else the search field. Save outcome → "Result" heading when focus was lost (the disabled Save button or `body`); otherwise focus stays. Self receipt → its heading. Check current roles keeps focus on itself.
- **Announcements.** One polite status sentence per save outcome (and per reconciliation change to it). Staged-change text and the ledger list are not live. The receipt is spoken through its focused heading only.

## 9. Intermediate states

- **After T01, before T02:** roles can be staged and cancelled but not saved; the panel has no Save button. This state is not mergeable on its own: C04 merges only after S02 is reviewed as a whole (§7.2). T01 must not add a disabled Save or placeholder text.
- **After T02:** complete slice.

## 10. Decisions

**No owner decision is required.** Routine choices made here:

- **R-1 (panel above the table, one account at a time).** It survives list reloads without new state machinery in the list hook and matches the reset-link panel's placement. A per-account route was rejected: there is no single-account read, and it would add a route without a user benefit.
- **R-2 (sequential, fixed order).** Grants before removals, option order, own Administrator removal last: the person keeps authority while other changes are made, and the ledger order is deterministic.
- **R-3 (stop rules).** Stop on unknown (the connection is suspect, and later steps stay staged); stop on 401/403/404 (later steps would be refused the same way); continue past a per-role refusal (409, `admin_grant_disabled`, other 4xx), which says nothing about other roles.
- **R-4 (reconciliation by search).** The list read with the login name (or display name) and `limit=100`, matched by `user_id`, is the existing authoritative read. A miss is reported as "could not check", never guessed. A single-account endpoint would be an API change and is not needed for this slice.
- **R-5 (retry = recomputed Save).** Never an automatic retry; never a replay of the earlier batch.
- **R-6 (self Administrator removal asks, receipt before refresh).** Refreshing first would let the route adapter unmount the page before the result is read.
- **R-7 (one page guard).** react-router supports one blocker per page, so the reset-link and role reasons share one guard with one dialog.
- **R-8 (error code parsing).** An optional `code` on the existing error class distinguishes `admin_grant_disabled` from other 403s without changing any other caller.

## 11. Handoffs

### 11.1 Sonnet implementation instructions

1. Confirm the baseline is HEAD and `origin/phase15/completion`, with a clean worktree (T01: the commit adding this plan; T02: the T01 records head).
2. Read §2 to §9. Write that task's "(fails at baseline)" cases first, run them on the baseline and record each failure (test name and assertion).
3. Implement only that task's part of §3.2 in the files of §4. Keep §2.4.
4. Run §7.1. Run that task's probes from §6.1, record each probe's failing case, and revert every probe.
5. **Stop and report instead of continuing if:**
   - a backend, API or authorization change seems necessary;
   - a change to `usePageArrival`, `useUnsavedChangesGuard`, `navigationHolds`, the announcer, the task-origin modules, `CreateAccountPage`/`CreateAccountPanel`, `OneTimeSecretPanel` or `AccountLifecycleActions` seems necessary;
   - an existing test would need a changed expectation other than those §4 allows;
   - a case cannot be made to fail at baseline where marked.
6. Commit with the §5 subject, push, then record in §11.3 and the register's task row: the SHA, the test-first failures, the focused and full runs (first run and rerun separately), the probes and the CI position ("pending checkpoint PR"). Commit and push the records.
7. Do not open, mark ready or merge a PR. Do not run browser or AX checks, start copy-ui, preview or other consumers, or record any acceptance.

### 11.2 Independent review boundaries (Luna)

- **T01:** from this plan's commit to the T01 implementation commit, plus its records commit.
- **T02:** from the T01 records head to the T02 implementation commit, plus its records commit.
- **Combined S02:** from this plan's commit to the T02 records head. Review against §2.4, §3, §6 and §8; re-run §7.1 and M1–M11.
- A pass is a slice verdict only; §7.2 and §7.3 remain.

### 11.3 Implementation record

Pending (Sonnet).

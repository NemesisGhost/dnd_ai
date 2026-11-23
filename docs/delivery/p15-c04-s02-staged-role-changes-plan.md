# D/P15-C04-S02 implementation plan: stage and reconcile per-role changes

**Status:** Opus plan prepared 2026-11-23. **T01 and T02 implementation verdicts remain PASS WITH VERIFICATION LIMITS (§11.4); C04 checkpoint readiness is CHANGES REQUIRED because the shared guard-registration window violates the existing S01 A18 departure requirement (§11.6).** This is a cross-cutting guard issue, not an S02 implementation regression or a new checkpoint gate.

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

#### T01 (Sonnet, 2026-11-23)

**Status:** T01 implemented at `86a001ec030f384568b5a6f3d0c3ef853f47475c` (`P15-C04-S02-T01: stage system-role changes in one account panel with local cancel`), pushed to `phase15/completion`; **awaiting independent review, not accepted.** It is an intermediate commit: the panel has no Save button, so it is **not mergeable on its own** (§9); T02 follows. Baseline: `3b6bf08a29a6ee3f1c19bd9a6c438c0bf91b6594` (HEAD and origin, clean worktree). CI: **pending the C04 checkpoint PR** (none opened).

**§4 clarification (owner-approved at T01 entry, in the commit).** Before any edit Sonnet stopped under §11.1 step 5: `AdminAccountsPage.test.tsx` line 83 asserted `getByText("system-roles-user-1")`, text only the deleted per-row `SystemRolesEditor` mock produced, so "mock replaced, assertions stay" could not hold once the panel left the row. The owner amended §4: the mock is removed and that one assertion becomes `getByRole("button", { name: "Edit roles for GM Two" })`; no wrapper component was added to keep mock text. Every other assertion in that file, and every S01 test file, is unchanged.

**What changed.** New `utils/systemRoleStaging.ts` (`stagedChanges(baseline, draft, ownAccount)`: grants then removals in option order, own Administrator removal last; `isDirty`; `describeChange`; `knownRoles`) and `components/SystemRolesPanel.tsx` (heading focused on open and on a repeated Edit roles press, checkboxes bound to the draft, Administrator grant gate and operator-script note, the campaign/world line, the one-at-a-time line, "Changes not saved yet" list or "No changes", Cancel when dirty / Close when clean, no Save and no placeholder). Deleted `SystemRolesEditor.tsx`, its test and `hooks/useSystemRoleChange.ts` (`api/systemRoles.ts` stays for T02). `AdminAccountsPage.tsx`: an "Edit roles for ‹name›" button per row (only with `system_roles.manage`), page-level `roleEdit` above the loading boundary, other rows' buttons disabled with the explanation while dirty, clean panel follows the latest list item, and `ResetLinkGuard` replaced by one `AccountsDepartureGuard` with one `ConfirmDialog` (reset-only wording exactly S01's). Docs: `portal-behavior.md` §4.4; one register evidence link to the deleted files became plain text so the documentation check passes.

**Choices to review.** (1) The guard component is still mounted only while a reset link or dirty roles exist (as S01's `ResetLinkGuard` was), because an always-mounted `useBlocker` breaks `App.landing` under its plain `MemoryRouter`; there is exactly one guard instance and one dialog, never two. (2) Losing `system_roles.manage` clears `roleEdit` (render-time reset), so the draft cannot come back if the capability returns. (3) Close focus: the row's button, else the search field, taken only when focus is on `body` or detached (a control the person moved to keeps it). (4) `stagedChanges` takes a boolean `ownAccount` rather than a user id; the page passes `editing.user_id === bootstrap.user.user_id`.

**Test-first failures (baseline `3b6bf08`, new file `AdminAccountsPage.roles.test.tsx`, 14 cases, 13 failed and 1 passed).** B1, B2 and B3 each failed with `Unable to find an accessible element with the role "button" and name "Edit roles for Alice Example"`; B4, B6, B7, B8 (both dirty-roles cases), B10 and the three focus cases failed the same way; the S01 reset-only dialog case failed only because it was clicked while the list refetch was in flight (see observation below) and passes once it waits for the list. B5 (no Edit roles without `system_roles.manage`) passes at baseline, as expected for an absence.

**Added coverage beyond B1–B10.** `App.platformAccounts.roles.test.tsx` (real route table): an account change drops the panel, draft and reset link (nothing under the new account, no extra POST); loss of `system_roles.manage` removes the panel and draft and regaining it does not restore them, with the reset link kept; a dirty draft is no longer asked about after the capability is lost; loss of `accounts.manage` shows the denial and leaves no token. Focus: close falls back to the search field, does not take back focus moved elsewhere, and a list reload after opening does not steal focus. `SystemRolesPanel.test.tsx` and `systemRoleStaging.test.ts` cover the component and pure rules.

**Runs (PowerShell, `C:\Users\nemes\dnd_ai\portal`).**
- Focused (§7.1 files plus `App.platformAccounts.roles.test.tsx`): 8 files, **96 passed**.
- Full `npm test`: first run **448 files, 5744 tests passed**; no failure, no rerun.
- `npm run lint`, `npx tsc -b` and `npm run build` pass (existing chunk-size notice only). `uv run python scripts/check_documentation.py` passes (after the register link fix) and `git diff --check` is clean (git warns that LF will become CRLF in new files; not an error).

**Probes (each reverted; `AdminAccountsPage.tsx` restored byte-for-byte, SHA-256 prefix `fdba378512e7` before and after).**
- M1 (checkbox change posts immediately) failed B1 (plus B2, B3, B8 stay-draft).
- M2 (Cancel keeps the draft for reopening) failed B2 (plus others that reopen).
- M3 (panel inside the row's cell) failed B3 (plus two focus cases).
- M4 (second guard for roles beside the page guard) failed exactly the B8 combined-reason case.

**Observation (pre-existing S01 behavior, not changed here).** Reproduced at baseline and with the new guard: if a link in the page's own shell is clicked immediately after the reset link appears, while the list refetch that follows issuance is still loading, the departure is not held and no question is asked; once the list has settled it is. Not caused by T01 and not in T01's scope (it would touch the guard path). Recommend Luna or the owner decide whether it needs its own finding.

**Not done.** T02, any PR, browser/AX checks, consumers and any acceptance.

#### T02 (Sonnet, 2026-11-23)

**Status:** T02 implemented at `b7328ea8cd8c9316d02447d372e3edcd693ed425` (`P15-C04-S02-T02: save staged system-role changes one at a time with per-change outcomes and reconciliation`), pushed to `phase15/completion`; **independent review pending; not accepted.** Baseline: the T01 records head `4952e560566ab21b7898ff27eaf4d522f33548f5` (HEAD and origin, clean worktree). CI: **pending the C04 checkpoint PR** (none opened). No PR, browser/AX run, consumer or acceptance.

**What changed.** `PlatformAccountsRequestError` gains an optional `code`; `api/systemRoles.ts` reads the error envelope's `error.code` best-effort and returns the parsed response (`stranded_world_ids` is typed); a 2xx that cannot be read or is not a role change throws an ordinary `Error`, which is an unknown outcome. New `hooks/useSystemRoleSave.ts`: page-level, one save at a time (a ref lock, so two quick presses send one batch), sequential sends in `stagedChanges` order, the §3.2 item 7 outcome table (saved, already so, refused with the reason, not confirmed, not sent), stop rules (unknown, 401, and a 403 other than `admin_grant_disabled` or a 404 stop; a 409 last-administrator, `admin_grant_disabled` on Administrator and any other 4xx continue), reconciliation by one `fetchPlatformAccounts({q: login name or display name, limit: 100})` matched by `user_id`, and `checkAgain` (reads only). Pure helpers in `utils/systemRoleStaging.ts` (`ledgerText`, `saveSentence`, `confirmFromRoles`, `draftAfterSave`, `mayHaveBeenSent`). `usePlatformAccounts.replaceAccount` replaces a row in place (no loading state, no refetch). `SystemRolesPanel` gains Save changes, the saving state, the polite status sentence, the Result heading and ledger, Check current roles and `SystemRolesReceipt`. `AdminAccountsPage` wires them, adds the own-Administrator question, the receipt, Continue, and the three departure questions. `portal-behavior.md` §4.4 is completed.

**Choices and departures from the plan, for review.**
1. **Departure feedback after a partial or uncertain save (beyond §3.2 item 11).** Item 11 specifies only the saving question. Without more, a save that left changes staged after some step may have been applied would be asked about as "Discard unsaved role changes? … have not been saved", which is untrue (the S01-R1 class of defect). The page therefore asks "Leave with role changes not fully saved?" ("Some changes to ‹name›'s system roles may already be saved. Leaving discards the changes still staged here and the record of what happened. Check the account's roles in the list afterwards.") whenever changes are still staged, or the read failed, and a saved, unconfirmed or confirmed step exists. Nothing sent keeps the ordinary question. Stay and Leave send nothing.
2. **No reconciliation read after one's own Administrator removal is saved.** The signed-in account can no longer read the list (it would be answered 404), so the ledger is final and the receipt shows at once; an unconfirmed own removal that a read answers 404 still ends in the access receipt (B22). Plan item 10 does not say; flag for Luna.
3. **Result is shown only once settled** (not while the read is under way), so the heading cannot appear before the status sentence and ledger are final. Checkboxes, Save and (while saving) Cancel are disabled; other rows' Edit roles stay disabled while a save is outstanding or the read has failed.
4. **Test placement.** B11–B26 are in `AdminAccountsPage.roles.save.test.tsx` (not appended to `AdminAccountsPage.roles.test.tsx`); the account-change and capability-loss cases through the real route table are in `App.platformAccounts.roles.test.tsx`; B27 is `api/systemRoles.test.ts`.
5. **Existing-test edits beyond the plan's list, none changing a S01 expectation.** `App.test.tsx`: the typed `usePlatformAccounts` mock gains `replaceAccount: vi.fn()` (required by the result type). `AdminAccountsPage.test.tsx`: a `SessionContext` mock, because the page now reads the session; no assertion changed. T01's own `AdminAccountsPage.roles.test.tsx` B1 asserted there is no Save button (T01's deliberate intermediate state, plan §9); it now asserts Save changes is enabled and ticking still sends nothing. `SystemRolesPanel.test.tsx` has the new props and, for the same reason, a disabled Save in the clean case.
6. Singular "1 of 1 change saved." is used for a single change.

**Test-first failures (baseline `4952e560566ab21b7898ff27eaf4d522f33548f5`).** The new files `AdminAccountsPage.roles.save.test.tsx`, additions to `App.platformAccounts.roles.test.tsx` and `api/systemRoles.test.ts` were run before any implementation: **3 files, 33 failed, 9 passed, 1 expected fail** (the reset-link gap reproduction). The B11–B26 cases that exercise a save failed on the missing "Save changes" button (B24 and the capability-loss case on the missing save path); B27's success, error-code and non-role 2xx cases failed on the missing `code` and response validation. The nine that passed assert behavior the old code already had or an absence: the empty, non-JSON and non-string-code variants of B27 and the unreadable 2xx, and the `accounts.manage`-loss case, among others.

**Runs (PowerShell, `C:\Users\nemes\dnd_ai\portal`).**
- Focused (the §7.1 files plus T02's `useSystemRoleSave`, `usePlatformAccounts`, `systemRoles`, `AdminAccountsPage.roles.save`, `App.platformAccounts.roles`): 12 files, **152 passed, 1 expected fail**.
- Full `npm test`, **first run:** 451 files, 5794 passed, 1 expected fail, **1 failed**: `src/components/quests/QuestCompletionSections.test.tsx > Choice-only drafts are unsent input > is clean again once its own command succeeded` (a dialog still open under load; a file this change does not touch). That file alone: 25 passed. **Rerun (separate):** 451 files, **5795 passed**, 1 expected fail, no failure.
- `npm run lint`, `npx tsc -b`, `npm run build` pass (chunk-size notice only). `uv run python scripts/check_documentation.py` and `git diff --check` pass.

**Probes (each reverted; each file restored byte-for-byte, SHA-256 prefixes: `useSystemRoleSave.ts` `a51d6288d64a`, `systemRoleStaging.ts` `5dbf7def9ea5`, `AdminAccountsPage.tsx` `17a67da0b3a3`).**
- M5 (continue after not confirmed): failed B16 (transport, 503 and the confirmed variant), B18 and the uncertain-departure case.
- M6 (a 5xx treated as refused): failed B16 (503).
- M7 (a retry resends the first batch, via module state that leaks across the file): failed B18, and also B13, B14, B19–B21 and B25 as a side effect of the leak.
- M8 (own Administrator removal first): failed B19.
- M9 (refresh at once after an own Administrator removal): failed both B19 cases.
- M10 (`admin_grant_disabled` takes the stopping permission branch): failed B14.
- M11 (`retry` instead of `replaceAccount`): failed B12.

**Isolation covered.** Account change while a step is held (B24: no later step, no late outcome, no read); `system_roles.manage` lost while a step is held (no later step, no ledger, regaining does not restore it); `accounts.manage` lost while pending (denial, no later step); Leave while saving; 401 mid-batch; a late answer after Leave or clear.

**UNRESOLVED, carried from T01: the S01 reset-link departure gap.** If a shell link is clicked right after the reset link appears, while the list refetch that follows issuance is still loading, the departure is not held and no question is asked; after the list settles it is. Evidence, distinguishing baseline from regressions: (a) reproduced against S01's unchanged code at the T02 plan baseline `3b6bf08a29a6ee3f1c19bd9a6c438c0bf91b6594` (S01's `ResetLinkGuard`), in T01's session before any T01 change; (b) still reproduces at T01 `86a001ec030f384568b5a6f3d0c3ef853f47475c`; (c) still reproduces at T02: `AdminAccountsPage.roles.save.test.tsx` ends with an `it.fails` case for exactly this sequence, which passes (the gap exists) and will start failing, prompting its removal, once the gap is fixed. So it is **S01-baseline behavior, not a T02 regression**, and T02 neither fixes nor worsens it. No shared navigation or guard module (`useUnsavedChangesGuard`, `navigationHolds`) was touched, the cause is **not diagnosed**, and it is not claimed harmless: a departure in that window loses a one-time link without asking. It needs its own finding or slice; fixing it likely changes the guard path, which is outside S02's boundary.

**Not done.** Any PR, browser/AX evidence, human or owner acceptance, consumers; independent review is pending.

**Review ranges (§11.2).** T01: `3b6bf08a29a6ee3f1c19bd9a6c438c0bf91b6594..4952e560566ab21b7898ff27eaf4d522f33548f5` (implementation `86a001ec030f384568b5a6f3d0c3ef853f47475c` plus its records). T02: `4952e560566ab21b7898ff27eaf4d522f33548f5..` the T02 records head (implementation `b7328ea8cd8c9316d02447d372e3edcd693ed425` plus its records commit). Combined S02: `3b6bf08a29a6ee3f1c19bd9a6c438c0bf91b6594..` the T02 records head.

### 11.4 Independent review of T01, T02 and combined S02 (Codex, 2026-11-23)

**Boundary and repository state.** All supplied commits are ancestors of HEAD `a89a8c3960837374a2854e3592754a2d3fd241f7` (`phase15/completion`, also `origin/phase15/completion`). T01 and T02 implementation and records commits appear in the stated order. T01 changes the plan, register, reference behavior, and role panel/page/util/test files; T02 changes those records and role API/hook/page/component/test files. The combined range has no backend changes. The worktree was clean before review. Applicable instructions: no `AGENTS.md` was present in the repository; `docs/delivery/grading.md`, this plan, and S01 plan §§3, 7, 8, 10, 11.6 were read.

**Verdicts.** T01: **PASS WITH VERIFICATION LIMITS** for its scoped implementation; local staging/cancel, capability presentation, one-panel layout, shared departure guard, focus and account/capability isolation match B1–B10. T02: **PASS WITH VERIFICATION LIMITS** for its scoped implementation; sequential per-role writes, stop/continue rules, result ledger, reconciliation, retry-by-current-difference, self-removal receipt, session refresh timing, and isolation match B11–B27. Combined S02: **PASS WITH VERIFICATION LIMITS**. The reset-link case initially described as an S01 departure gap is a test-only defect, not a demonstrated product gap: a correct held-refetch probe passes on both S01 baseline and the reviewed head. No S02 acceptance blocker was identified. No merge readiness is granted; checkpoint CI, integrated acceptance and the separate browser/AX, human and owner checks remain pending.

**Independent verification.** From `portal/`, the focused S02 set listed in §7.1 plus the route-table role tests ran: 12 files, **152 passed, 1 expected failure**. The broader S01/S02/page/hook/navigation set then ran: 18 files, **235 passed, 1 expected failure**. The expected failure in each run is the explicit `it.fails` reset-link timing test below; it is not a passing acceptance case. The separate valid held-refetch probe passed on both the S01 baseline and reviewed head. `npm run lint`, `npm run build` (including `tsc -b`), `uv run python scripts/check_documentation.py`, and `git diff --check` passed. Build emitted the existing large-chunk advisory. No full suite or CI was run independently. Preserve the implementation's full-run history as reported in §11.3: T01's full run passed (448 files, 5,744 tests); T02's first full run had one unrelated failure (QuestCompletionSections), that file alone passed 25 tests, and a separate clean rerun passed (451 files, 5,795 passed, plus the one expected failure). The first full run remains failed; the isolated pass does not establish its cause, and causation of the timeout remains unproven. CI is pending the checkpoint PR. Browser/AX, human and owner checks remain pending.

**Contract and deviation review.** The UI copy accurately says the deployment's operator script grants Administrator; the client gate is presentational and each write/read remains server-authoritative. Requests run one at a time, grants before removals and own-Administrator removal last; a ref lock prevents a second batch. Per-step statuses and reconciliation use the existing administrator list endpoint, match by user ID, replace the row in place, preserve failed-read recovery, and Save only recomputed outstanding differences. Own-removal confirmation precedes writes; its receipt remains until Continue, when session refresh occurs. Account/capability loss and navigation abort later steps and ignore late answers; search changes do not count as departure. Result-heading timing waits until the ledger is settled and does not steal focus from a deliberate move-away. The documented partial-save departure wording is more truthful than “not saved”; skipping reconciliation after confirmed own-Administrator removal is justified because the now-unauthorized read cannot provide authority and the receipt already states the confirmed result. Test placement and the T01 intermediate Save assertion change preserve the intended contracts. These deviations do not add findings.

**Finding: reset-link expected-failure test does not establish a product gap.** `AdminAccountsPage.roles.save.test.tsx` labels its `it.fails` case as occurring while the list reloads, but it does not defer the post-issuance GET. It waits for the link and clicks the navigation link immediately; the list GET can already have settled. A temporary probe held that GET unresolved, verified the visible link and loading state, then attempted departure. The required dialog appeared before resolving the read. The same probe passed at the reviewed T02 head and in a detached worktree at S01 baseline `3b6bf08`; the temporary test/worktree were removed. Thus the plan's earlier claim that this sequence loses the secret is not supported, and there is no demonstrated violation of S01 A18/R-5 in the actual held-refetch case.

**Disposition:** test/tooling finding, no product-severity score. The `it.fails` case is a misleading expected failure and should be replaced by a deterministic deferred-GET test (asserting the loading state before navigation), alongside the already passing settled-list and search behavior. The current valid held-refetch probe passes. This does not block S02 or C04 acceptance. The original expected failure remains distinguished from passing tests in the run record until the test is corrected.

No implementation, commit, push, PR, consumer work, or acceptance was performed by this review.

### 11.5 Reset-link test correction and C04 finalization (Sonnet, 2026-11-23)

**Scope.** Started from `a89a8c3960837374a2854e3592754a2d3fd241f7` with Luna's uncommitted §11.4 and register edits preserved byte for byte and committed with this record. Test-only change at `347e22946330f34b4aac864140c8723a4c39d658`: no production code, shared guard or navigation module changed. S01 and S02 passes are unchanged. Browser/AX, human and owner acceptance are not granted; no consumer work.

**The old `it.fails` case was a test defect (history kept).** §11.3's T02 record and the earlier T01 record describe an "unresolved S01 reset-link departure gap" backed by an `it.fails` case. §11.4 found that case did not hold the post-issuance list read. Both statements stay above as written; this section supersedes them: the case was a misleading expected failure, replaced by the deterministic test below. No product gap was demonstrated by it.

**Replacement.** `AdminAccountsPage.roles.save.test.tsx` > "S01 reset-link departure while the list reload is held": the list GET that follows the issuance is held unresolved; the reset link and the "Loading accounts…" state are asserted (two list GETs, one reset POST); a shell navigation is attempted; the question "Leave without the password-reset link?" ("It is shown once and cannot be shown again.") appears and the destination does not; **Stay** keeps the link, the pending read and the single reset POST; **Leave** reaches the destination, the token is not on the page, and after the held read is released the reset POST count is still one and the list was not read again. A mutation that unmounts the page guard fails it (restored byte-for-byte, SHA-256 prefix `17a67da0b3a3`).

**Discrepancy with §11.4's evidence, found while making the test deterministic.** The first version of the replacement passed alone but failed in the first full run, and failed in about a third of cold single-test runs (4 of 12, then 9 of 14), with the guard mounted and the list read held: the shell navigation was not held and no question appeared. Cause (confirmed, not assumed): react-router 8.3.0's `useBlocker` registers a blocker in effects after the guard first renders (`useEffect` sets a key, a second `useEffect` calls `router.getBlocker`), so a navigation attempted in that first moment is not held. It is independent of the held read and of S01 or S02 code. With one macrotask of waiting before the click, 16 of 16 cold runs held the departure (and 16 of 16 again after the final edit), and without the wait 325 warm in-process iterations lost the question once. This is consistent with §11.4's single passing probe (timing luck) and does not contradict its conclusion that the held refetch itself is guarded; it does show a window, a few milliseconds after any guard first mounts, in which react-router does not yet hold a departure. That is a framework behavior shared by every `useUnsavedChangesGuard` page, not specific to the reset link, and not something a person can hit by hand; no production change was made. The test now waits for registration and says why. Flagged for the owner and Luna; any mitigation would touch the shared guard, which is outside C04.

**Acceptance evidence at `347e22946330f34b4aac864140c8723a4c39d658`.** Focused C04 set (A1–A20: `CreateAccountPage`, `CreateAccountPanel`, `AdminAccountsPage` and its reset-link file, `App.platformAccounts`, `platformAccountsReturn`, `useCreateAccount`; B1–B27: `AdminAccountsPage.roles`, `.roles.save`, `SystemRolesPanel`, `systemRoleStaging`, `App.platformAccounts.roles`, `useSystemRoleSave`, `usePlatformAccounts`, `systemRoles`; plus `App` and `App.landing`): 17 files, **253 passed**. `npm run lint`, `npx tsc -b`, `npm run build`, `uv run python scripts/check_documentation.py` and `git diff --check` pass.

**Full portal runs, kept separate.** **First run (failed):** 451 files, 5795 passed, **1 failed**: the new test above, at its first departure (the registration window; not yet waiting). **Rerun after the test waited:** 451 files, **5796 passed**, 0 failed, no expected failures remain. The earlier T02 full-run failure (`QuestCompletionSections`, passes alone) is recorded in §11.3 and did not recur.

**Status.** C04 S01 and S02 are independently reviewed PASS WITH VERIFICATION LIMITS (S01 plan §11.6, this plan §11.4). Open limits: integrated browser/AX evidence, human and owner acceptance, and CI on the checkpoint PR's exact head (CI result is reported on the PR, not recorded by a further commit). The checkpoint PR is a draft and unmerged pending the owner's decision.

### 11.6 Independent review of the test correction and blocker-registration window (Codex, 2026-11-23)

**Boundary.** Previously reviewed head `a89a8c3960837374a2854e3592754a2d3fd241f7`; test correction `347e22946330f34b4aac864140c8723a4c39d658`; final records head `9c89622d1b977813e74252b2c594590fe9dca687`. The correction changes only `AdminAccountsPage.roles.save.test.tsx`; it does not change production code. S01 and S02 implementation verdicts remain **PASS WITH VERIFICATION LIMITS**. This review concerns the newly demonstrated behavior and C04 readiness.

**Held-refetch hypothesis.** Confirmed: holding the post-issuance account-list GET does not itself defeat the reset-link guard. Once its blocker has registered, the navigation is held, Stay preserves the link, and Leave discards the transient secret without repeating the reset POST. The replacement test establishes this settled registration behavior.

**Actual registration window.** The correction's `await settle()` calls a fixed 25 ms timer. There is no observable ready signal for blocker registration. It therefore waits past the race instead of proving readiness. In react-router 8.3.0, `useBlocker` assigns its blocker key and calls `router.getBlocker` in successive effects after render (`portal/node_modules/react-router/dist/development/lib/hooks.js`, `useBlocker`; the application call is `portal/src/hooks/useUnsavedChangesGuard.ts`). Before registration, a navigation is not intercepted. The correction record reports repeated reproductions: first deterministic-test attempts failed cold in 4/12 and then 9/14 runs; after the timer, 16/16 cold attempts passed on each of two edits; 325 warm in-process iterations without the wait still lost the question once. That evidence demonstrates a small, real registration window; the timer does not close it.

**Origin and scope.** This comes from the shared `useUnsavedChangesGuard`/React Router registration lifecycle, not the held fetch, reset-link state logic, or S01/S02 role changes. The shared hook is used by account creation and many other guarded editors/pages. On C04's reset-link path the guard mounts when the link appears; a departure before its effects register can leave immediately and drop the one-time link without the promised question. The same registration gap can affect any protected draft or pending departure on a page whose guard has just mounted. Cold and warm test runs establish the code path and consequence under automated navigation. A real-browser or human reproduction was not performed, so human timing/reachability and frequency remain unverified. The statement “not something a person can hit by hand” in §11.5 is unsupported by evidence and is not accepted as a reason to waive the requirement.

**Grade and acceptance disposition.** Application/UI; authenticated account manager; precondition is navigation in the brief interval after a guard mounts for a shown reset link or other protected state. Supported-path exposure **1/3** (narrow timing window); impact **1/3** (the in-memory link or draft is lost, bounded to that page/user and recoverable only by reissuing or re-entering); triggerability **1/2** (special timing, but repeatedly produced by immediate navigation in cold and warm tests); detection/recovery **1/1** (no prompt is shown and the transient content is silently discarded); blast radius **0/1** (bounded to that user's current page): **4/10, Medium**. This **blocks C04 checkpoint acceptance** under the existing S01 A18/R-5 contract: A18 requires a departure question while the reset link is shown. This is not a new gate and does not reverse S01 or S02 implementation passes. Human reachability is uncertain, but the directly demonstrated route violates the promised behavior and there is no evidence establishing it unreachable.

**Bounded correction brief.** Correct the shared guard registration so protected navigation is intercepted from the first committed moment the guard is required, rather than relying on a post-render timer. Add a deterministic regression that attempts navigation immediately when a newly mounted guard protects the displayed reset link, with the list GET held; do not sleep before the attempt. Preserve one blocker per page, query-only search behavior, Stay/Leave semantics, and the existing form/role guard behavior. Verify the shared guard cases and C04 A18/A15–A17 focused suites, then lint/typecheck/build and diff/documentation checks. No code correction was made in this review.

**Targeted check and CI.** At final head, `npx vitest run src/pages/AdminAccountsPage.roles.save.test.tsx`: 1 file, **28 passed**. No full implementation run was repeated. CI run [45230414539](https://github.com/NemesisGhost/dnd_ai/actions/runs/45230414539) completed successfully for PR #73 with `head_sha` exactly `9c89622d1b977813e74252b2c594590fe9dca687`. The Portal tests/lint/build job and all other workflow jobs succeeded. The workflow checked out synthetic PR merge commit `91757cc32a48e45657a0d578a6c1d3e14e6d3e57` (`9c89622` merged into base `d09429f`), so CI validates that PR integration checkout, not a bare-head checkout. This CI success does not address the uncovered registration window because the corrected test waits through it.

**Full-run evidence retained.** The correction's first full run remains a failure: 451 files, 5,795 passed, one failed at the first departure because the registration window was active. The subsequent separate clean run passed: 451 files, 5,796 passed. The earlier T02 full run's unrelated `QuestCompletionSections` failure and its isolated 25-test pass remain separate in §11.3; the later clean run does not prove that failure's cause. Timeout causation remains unproven.

**Checkpoint readiness: CHANGES REQUIRED.** Keep the S01 and S02 implementation passes. Do not treat the 25 ms test wait as a readiness condition or the missing human reproduction as proof of unreachability. C04's existing A18 acceptance remains unmet until the shared guard-registration window is corrected and verified. CI passed on the synthetic merge checkout; browser/AX, human and owner checks remain pending.

### 11.7 Correction of the blocker-registration window (Sonnet, 2026-11-23)

**Status:** implemented at `32223ef74ec469d8f9734ddfc15fb5aba693ba90`; **independent review pending; not accepted.** Baseline `9c89622d1b977813e74252b2c594590fe9dca687` (HEAD and `origin/phase15/completion`). Luna's uncommitted §11.6 review and register edits are preserved unchanged and committed with this record. §11.4's PASS WITH VERIFICATION LIMITS verdicts, §11.5's record and §11.6's CHANGES REQUIRED stay as history. The scope extension authorizing the shared unsaved-changes guard was used; no API, authorization or backend contract changed.

**Diagnosis of the registration lifecycle.** The shared `useUnsavedChangesGuard` called react-router 8.3.0's `useBlocker`. That hook takes two passive-effect passes to register: its first effect only chooses the blocker's key and calls `setState`; the state update must render and commit; only then does a second effect call `router.getBlocker(key, fn)`. Until it does, `router.navigate` finds no blocker function and proceeds. The guard itself added two more late steps: `dirtyRef.current = isDirty` and `registerPageGuard()` ran in passive effects too (the ref was seeded correctly at first render, but a later clean-to-dirty transition was not visible to the blocker until a passive pass). So the unprotected interval began at the first commit that needed protection (a reset link appearing; a form first becoming dirty) and ended after up to two further passive passes. A click, or a navigation from a sibling's layout effect, in that interval was not held. This is independent of the held list read: the earlier replacement test simply raced it.

**Fix (shared guard).** New `hooks/useCommittedBlocker.ts`, a minimal data-router blocker: the key is chosen at first render (`useState` initializer, no state update); the blocker function is registered in a **layout effect**, i.e. synchronously inside the commit that puts the guard on screen, before any event or task can run; it is re-registered in the same phase if its identity changes (that only stores the function, never resets a blocked state); it is deleted in a **passive** cleanup, as `useBlocker` did, so the guard's own earlier passive cleanup (resetting an open question when the page goes away) still runs while the blocker exists. It requires a data router and throws react-router's own message otherwise, strips a non-root basename, reads `routerState.blockers` like `useBlocker`, and returns the idle blocker until the router reports one. `useUnsavedChangesGuard` now calls it, keeps the dirty ref and the page-guard count in layout effects (so a transition to dirty and a holder mounting beside the guard are seen in the commit that made them), and is otherwise unchanged: one blocker per page, query-only changes not held, `disposingQuery`, `release`, `discard` and `stay`, the `beforeunload` prompt, the hold registry and every caller's wording. No sleep, delay of the secret's display or test-only readiness wait is involved; the 25 ms wait is removed from the page test.

**Regression, shown failing before the fix.** New `hooks/useUnsavedChangesGuard.registration.test.tsx` (8 cases) attempts the navigation from a sibling's layout effect in the commit where (a) a protected guard first renders, (b) a mounted guard first becomes dirty; also: a clean guard does not hold, a query-only change is not held from the first protected render, unmounting removes the blocker and leaves none, unmounting with the question open cancels instead of approving, repeated protected transitions leave one blocker with no router warning, and a plain `MemoryRouter` still throws the data-router error. **At the baseline code, 4 of 8 failed** (cases a, b, the unmount-with-question case and the repeated-transitions case, all because the departure went through). The page-level test (reset link, post-reset list GET held, immediate shell navigation, no wait; Stay keeps the link, Leave navigates without repeating the POST) failed **7 of 12** cold single-test runs before the fix and **passed 16 of 16** after.

**Targeted mutation probes (each reverted; files restored byte-for-byte, SHA-256 prefixes `6e22ef27768b` for `useCommittedBlocker.ts`, `0ee9c32b3fe2` for `useUnsavedChangesGuard.ts`).** G1 registration moved to a passive effect: failed case (a). G2 dirty ref moved to a passive effect: failed case (b), the unmount-with-question case and the repeated-transitions case. G3 deletion moved to a layout cleanup (before the guard's reset of an open question): failed the unmount-with-question case.

**Runs (PowerShell, `C:\Users\nemes\dnd_ai\portal`).**
- Affected callers and integrated C04 acceptance (all of `src/hooks`, `src/navigation`, `CreateAccountPage`, `CreateAccountPanel`, `AdminAccountsPage` and its reset-link, roles and roles.save files, `SystemRolesPanel`, `systemRoleStaging`, `App.platformAccounts` and `.roles`, `systemRoles`, `App`, `App.landing`): 126 files, **1729 passed**.
- Full `npm test`, first run: **452 files, 5804 passed, 0 failed** (no failure to record separately; no rerun needed).
- `npm run lint`, `npx tsc -b`, `npm run build`, `uv run python scripts/check_documentation.py` and `git diff --check` pass.

**Correction range for independent review.** `9c89622d1b977813e74252b2c594590fe9dca687..32223ef74ec469d8f9734ddfc15fb5aba693ba90` (the shared guard, the new hook and tests, and the page test) plus the docs-only records commit that follows. CI: fresh run on PR #73's final head is reported on the PR, not recorded by a further commit. Browser/AX, human and owner acceptance remain pending; the PR stays a draft and unmerged; no consumers.

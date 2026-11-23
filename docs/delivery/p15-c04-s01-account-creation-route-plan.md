# D/P15-C04-S01 implementation plan: separate account creation from the list

**Status:** Opus plan prepared 2026-11-23. **T01 implemented by Sonnet at `c2f15975c98943d952df6550f3c0cc2ebdf7d269` (see §11.3); awaiting independent review.** It was ready for Sonnet. No owner decision blocks the task. Section 10 lists the routine choices made here; none changes a product policy, an API contract or authorization.

**Register rows:**
- slice [D/P15-C04-S01](work-register.md#p15-c04-s01);
- task [T01](work-register.md#p15-c04-s01-t01);
- parent checkpoint [D/P15-C04](work-register.md#p15-c04).

**Plan-entry head:** `d09429fbc5a56636ee4b71a746510c4ddcb7bc7e` ("Merge pull request #72 from NemesisGhost/phase15/completion"), the C03 merge on `main`.
- `phase15/completion` was at `38b92ec29d45a1d5761f4bfed45a4dc2cd5be265` (equal to its origin, clean worktree). That commit is the merge's second parent and the merge tree is identical to it, so the branch was fast-forwarded to `d09429f` after `git fetch origin`. No history was rewritten.
- CI: no run exists for C04. CI runs on pull requests, and the C04 checkpoint PR has not been opened.

Sonnet's implementation baseline is the commit that adds this plan, a child of `d09429f`. The handoff prompt names it.

**How each statement was established:**
- by reading source, tests and documents at the plan-entry head;
- by a temporary plan-entry reproduction (§2.2): one Vitest file, written into `portal/src/pages/` only for the run and deleted afterwards. It rendered the real `AdminAccountsPage`, `CreateAccountPanel` and `useCreateAccount` with the list read and the session faked, and a stubbed `fetch` for the create request. No repository file was changed by it.

**Governing sources:**
- [Portal behavior §4.4](../reference/portal-behavior.md#44-platform-accounts-authorization): Platform Accounts visibility from `accounts.manage` only, the direct route as the gate, non-disclosing server refusals, the create form's role choice (default Player; Administrator only with `system_roles.grant_admin`).
- [Portal behavior §5.11](../reference/portal-behavior.md#511-authoring-patterns-phase-14): unsaved-input guard, page-arrival focus, one meaningful announcement.
- [Navigation contract §4.8.10](../reference/portal-navigation.md#4810-campaign-setup-settings-and-access-p02-7e): unscoped pages have no task model; Platform Users was left untouched by P02.
- [R07](work-register.md#r07--platform-users-administration): "separate creation into a route using P02 task return; preserve the list's query/focus"; "activation/reset links retained safely in transient memory. Do not persist secrets in return state, URLs, logs or generic recovery storage."
- The register's [C04 criteria](work-register.md#criteria-p15-c04), [S01 criteria](work-register.md#criteria-p15-c04-s01) and [T01 criteria](work-register.md#criteria-p15-c04-s01-t01): "List navigation retains state and keeps credentials out of URLs and persistent storage"; "Preserve query, direct-entry return and focus on the creation route with transient activation/reset handling".
- The create command (`src/dnd_ai/commands/local_auth.py`, `_create_user_with_activation_token`): a login name is reserved only at activation, so two creates with the same values make two pending accounts. The API is `POST /api/admin/accounts` (201 `CreateAccountResponse` with `raw_activation_token`); it has no idempotency key.

## 1. Entry readiness

C04 is "Stage system-role operations". Its prerequisite column is "—" and its criteria row has no entry contract, so C04 has no checkpoint prerequisite. The attached [atomic-roles](work-register.md#atomic-roles) record is a separate, unadmitted proposal; it gates nothing in C04 and is not consumed here.

S01 and S02 each say "Checkpoint entry criteria; no additional slice-specific gate". Neither names the other, so neither depends on the other; table order is not a dependency. S01 is planned first because it is the first eligible slice. **S02 is independently eligible** (Ready for Opus). Both slices edit `AdminAccountsPage.tsx`, so S02's plan should be prepared against S01's implementation head to avoid a conflicting baseline; that is scheduling, not a prerequisite.

**Verdict: S01 eligible and ready for Sonnet.**

## 2. Verified current behavior

### 2.1 How accounts are created today

- `AdminAccountsPage` (`portal/src/pages/AdminAccountsPage.tsx`, route `/platform/accounts` behind `PlatformAccountsRoute` in `App.tsx`) renders the create form inline above the list: `<CreateAccountPanel onCreated={retry} …/>`.
- `CreateAccountPanel` keeps login name, display name, email and roles in component state and calls `useCreateAccount`. On success it replaces itself with `OneTimeSecretPanel` showing `buildFragmentLink("/activate", raw_activation_token)` and calls `onCreated`, which is the list's `retry`.
- `retry` bumps the list's request version, so the list re-enters `loading`: the table unmounts and "Loading accounts…" is shown until the read answers.
- `useCreateAccount` sends one POST with the session CSRF token, ignores a second submit while pending, aborts on unmount, maps 401 to `reload()`, 403/404 to `denied`, and **everything else, including a transport failure and a 5xx, to `error`**, shown as "The account could not be created. Try again." Editing the login or display name clears any status.
- The list search (`usePlatformAccounts().query`) is React state only. It is not in the address, router state or storage, so any remount starts empty.
- The password-reset link (`issuedReset`) is held in `AdminAccountsPage` state, above the list's loading boundary, and survives the refetch and query changes (`AdminAccountsPage.resetLink.test.tsx`). Leaving the page loses it silently. No departure guard exists on the page.
- `/platform/accounts` has route metadata `platform.accounts` (kind `other`, no task root). There is no creation route.

### 2.2 Plan-entry reproduction results

The temporary file (§ header) ran 5 tests; all passed, confirming:

| # | Behavior at `d09429f` |
|---|---|
| P1 | The list page renders the `form` named "Create account" inline; there is no Create account link. |
| P2 | Typing "ali" in the search leaves the address at `/platform/accounts`; unmounting and remounting the page shows an empty search. |
| P3 | A create whose `fetch` rejects (`TypeError`) shows "The account could not be created. Try again."; pressing Create account again sends a second POST. |
| P4 | A 500 answer shows the same "could not be created" text. |
| P5 | After a successful create (focus on the submit button) the list re-enters "Loading accounts…" and `document.activeElement` is `body`. |

### 2.3 Deviations S01 repairs

- **DV-1 (P1).** Creation is not separate from the list (R07, S01 title).
- **DV-2 (P2).** The list query is not retained across navigation; there is no return to it (T01 "preserve query").
- **DV-3 (P5).** Focus is lost to `body` when the account is created, at the moment the one-time activation link appears.
- **DV-4 (P3, P4).** An outcome the portal cannot know (no answer, or a server error) is reported as a refusal and invites "Try again", which can create a second pending account because the server does not reserve the login name before activation. The repair is wording and ownership only; it does not add retry semantics.

### 2.4 Reviewed behavior that must not regress

- The route adapter is the gate: without `accounts.manage` no account page mounts and no `/api/admin/accounts` request is sent; `/admin/accounts` still redirects to `/platform/accounts` (`App.test.tsx`).
- Default role Player; at least one role; Administrator disabled without `system_roles.grant_admin`, with the operator-script note; "A system role never grants access to any campaign or world."
- Trimmed values; blank email sent as `null`; no second POST while pending; abort on unmount; 401 → `reload()`; 403/404 → "You do not have permission to create accounts."
- The activation and reset links are built as fragment links (`#token=`), held in React memory only, with Copy and Dismiss.
- Every behavior in `AdminAccountsPage.resetLink.test.tsx`: the reset link survives the list refetch and query changes, Dismiss removes it, remount does not restore it, a new issuance clears the old link first, 401 reloads.
- The list, the system-roles editor and lifecycle actions are otherwise unchanged (S02 owns role staging).

## 3. Outcome, scope and exclusions

### 3.1 User outcome

A platform administrator browses accounts with a search that lives in the address. **Create account** opens its own page. Cancel, the back link, or **Back to accounts** after creating returns to the list as it was left, with focus on Create account. The one-time activation link is shown once on the creation page, holds focus, never enters an address, router state or storage, and is not silently lost to an in-app navigation. When the portal cannot tell whether an account was created, it says so and does not suggest a blind retry.

### 3.2 In scope (T01)

1. **Creation route.** `/platform/accounts/new` → `CreateAccountPage`, behind a route adapter that applies the same `accounts.manage` gate as the list (`AccessDeniedPage` with `HOME_RECOVERY` otherwise; nothing mounts, nothing is requested). Add route metadata `platform.accounts.new` (unscoped, no task root, kind `create`, label "New account") so `routeMeta.test.ts` stays in step with `App.tsx`. No `/admin/accounts/new` alias (R-6).
2. **The creation page.** An `h1` "Create account" with page-arrival focus (`usePageArrival(true)`), a **Platform accounts** back link, the existing form fields and role rules, **Create account** and **Cancel**. The page is keyed by `bootstrap.user.user_id` so nothing crosses an account change.
3. **List without the form.** `AdminAccountsPage` drops the inline `CreateAccountPanel` and shows a **Create account** link to `/platform/accounts/new`, carrying the list's return state (item 5).
4. **Query in the address.** The list search is `?q=` on `/platform/accounts`. Typing writes it with a REPLACE navigation (no history entry per keystroke; an empty search removes `q`). On entry the page reads `q` and accepts it only when it is at most 200 characters with no control characters (U+0000–U+001F, U+007F); otherwise the search starts empty and nothing is echoed. `usePlatformAccounts` takes the query from the page (the address) instead of owning it; Load more stays as today and is not retained (R-3).
5. **Return state.** The Create account link's router state is `{ accountsReturn: "<search>" }`, where `<search>` is `""` or the list's own `?q=…` string. A new helper (`portal/src/navigation/platformAccountsReturn.ts`) builds it and reads it back: the value is accepted only if it is `""` or starts with `?`, parses to exactly one key `q` whose value passes item 4's rule, and is at most 1024 characters; anything else (missing, another type, extra keys, `//host`, an absolute URL, a path) gives `""`. The destination is always the pathname `/platform/accounts` plus that search, never a value taken from state.
6. **Return and focus.** Cancel, the back link and **Back to accounts** navigate (PUSH) to the validated list address with state `{ accountsFocus: "create" }`. The list focuses its Create account link once, only on a PUSH arrival carrying that marker (not on POP or a reload of that entry). No other list arrival moves focus.
7. **Outcomes on the creation page** (`useCreateAccount` and the form):
   - *success:* the form is replaced by `OneTimeSecretPanel` headed "Copy the activation link for ‹display name› now" (the submitted display name, already on screen), with the existing description and fragment link. Its heading takes focus (programmatic, `tabIndex=-1`). The page's status region stays empty, so the outcome is spoken once, through the heading. The panel offers **Copy**, **Back to accounts** (item 6) and **Create another account** (empty form, Player default, focus on Login name). Both actions drop the secret.
   - *rejected* (any other 4xx answer): unchanged text "The account could not be created. Try again."; values kept; edits clear it as today.
   - *denied* (403/404) and *session* (401): unchanged.
   - *unknown* (a transport failure, or any 5xx): new status kind `unknown`, text "We could not confirm whether the account was created. Check the account list before trying again: creating it again would add a second account." Values are kept. Edits do **not** clear it. Only a deliberate Create account press sends another POST (one per press), which replaces it with that attempt's outcome.
   - Abort on unmount stays silent.
8. **Departure guard** (`useUnsavedChangesGuard` + `ConfirmDialog`, the `CreateWorldPage` pattern), on path changes only:
   - *dirty form* (any field differs from the empty form with Player only): "Discard unsaved changes?" / "You have entered details for a new account that have not been created." / **Discard changes** / **Keep editing**;
   - *pending create:* "Leave while the account is being created?" / "The account may still be created, but its activation link will not be shown." / **Leave** / **Stay**;
   - *activation link shown:* "Leave without the activation link?" / "It is shown once and cannot be shown again." / **Leave** / **Stay**.
   **Back to accounts**, **Create another account** and the post-success state release the guard deliberately (`guard.release()` before navigating). Stay keeps the page, its values or secret and its entry. Leave goes once and sends nothing.
9. **Reset link on the list.** While a reset link is shown, the list page uses the same guard (activation wording with "password-reset link"). Query-only changes (typing in the search) are not departures and are not asked, so the existing "survives changing the search query" behavior stands. Dismiss releases it.
10. **Shared component.** `OneTimeSecretPanel` gains optional props only: a heading focus request and replacement action buttons (for the creation page's two actions). Its existing callers (the reset link, and any other) render as before.
11. **Docs.** Portal behavior §4.4 and the routes table (new row for `/platform/accounts/new`; the list's `?q=`), and the navigation contract's route count (91 → 92) and §4.8.10 note that Platform Users now has a creation route with its own return state (still no task model).

### 3.3 Exclusions

- No backend, API, command, database or authorization change. No idempotency key, login-name reservation or duplicate detection (DV-4 is repaired by honest wording only). Stronger retry semantics would need a separate API design ([R07](work-register.md#r07--platform-users-administration)).
- No change to role editing, `SystemRolesEditor`, `useSystemRoleChange` or the lifecycle actions (S02 and later).
- No task-origin (`TaskOriginV1`) adoption for Platform Users: unscoped routes have no task model (§4.8.10). The return state in item 5 is a page-local key with its own validator.
- No recovery of an activation link that was lost (an unknown outcome, a Leave, a dismissal); the server has no re-issue for it, and none is added.
- No change to `usePageArrival`, the shared guard hooks, `navigationHolds` or the announcer.
- No list-position (Load more) retention.
- No browser, AX or owner acceptance work.

## 4. Affected files and interfaces

- `portal/src/App.tsx`: the creation route and its adapter (keyed by user).
- `portal/src/navigation/routeMeta.ts`: `platform.accounts.new`.
- `portal/src/navigation/platformAccountsReturn.ts` (new) and its test.
- `portal/src/pages/CreateAccountPage.tsx` (new) and `CreateAccountPage.test.tsx` (new).
- `portal/src/components/CreateAccountPanel.tsx` (becomes the page's form, or is folded into the page) and its test.
- `portal/src/hooks/useCreateAccount.ts` (`unknown`) and its test.
- `portal/src/pages/AdminAccountsPage.tsx`, `portal/src/hooks/usePlatformAccounts.ts`.
- `portal/src/components/OneTimeSecretPanel.tsx` (optional props).
- Tests whose **harness** changes but whose expectations stay: `AdminAccountsPage.test.tsx` and `AdminAccountsPage.resetLink.test.tsx` (render inside a router; the `CreateAccountPanel` mock is no longer needed), `App.test.tsx` (new route cases added; existing cases unchanged).
- Expected changed expectations (allowed): the inline-form assertions of `CreateAccountPanel.test.tsx` move to the creation page; `useCreateAccount.test.ts` gains the `unknown` mapping.
- Docs: `docs/reference/portal-behavior.md`, `docs/reference/portal-navigation.md`.

## 5. Task commit

One commit: `P15-C04-S01-T01: give account creation its own route with list return, focus and transient activation handling`.

## 6. Acceptance cases

"(fails at baseline)" cases must be written first and shown failing on the baseline.

**Route and authorization**
- **A1** (fails at baseline) `/platform/accounts/new` with `accounts.manage`: `h1` "Create account", the form with Player checked; no `GET /api/admin/accounts` request.
- **A2** (fails at baseline) Without `accounts.manage`: the access-denied page on `/platform/accounts/new`; no form, no request. The existing list-route denial and the `/admin/accounts` redirect still pass.
- **A3** (fails at baseline) The list has no inline form and has a **Create account** link to `/platform/accounts/new`.

**Query and return**
- **A4** (fails at baseline) Typing "ali" makes the address `/platform/accounts?q=ali` by REPLACE (history length unchanged); clearing removes `q`; the list request carries the query.
- **A5** (fails at baseline) Entering `/platform/accounts?q=ali` shows "ali" and requests it. A `q` over 200 characters, or with a control character, gives an empty search and a request without `q`.
- **A6** (fails at baseline) From `?q=ali`, Create account then Cancel returns to `/platform/accounts?q=ali` with "ali" in the search; the same holds for the back link, and for browser Back.
- **A7** (fails at baseline) A direct entry to `/platform/accounts/new` returns to `/platform/accounts`. Tampered `accountsReturn` values (a number, `"?q=a&x=1"`, `"//evil.example"`, `"https://evil.example/"`, `"/campaigns"`, an over-length value, a control character) all return to `/platform/accounts`; no navigation leaves that pathname. (Unit cases on the helper plus one page case.)

**Outcomes**
- **A8** (fails at baseline) Success: one POST with trimmed values, `null` email and the chosen roles; the panel "Copy the activation link for New GM now" with the fragment link; its heading holds focus; the status region is empty.
- **A9** (fails at baseline) The token never appears in `location` (pathname, search, hash or state) at any point of the flow (creation, Back to accounts, Create another, browser Back to the creation page), and `sessionStorage.setItem` / `localStorage.setItem` are never called with it. After Back to accounts or Create another it is no longer in the document, and browser Back to `/platform/accounts/new` shows an empty form.
- **A10** (fails at baseline) **Back to accounts** returns to the carried query with focus on the list's Create account link and a fresh list read. **Create another account** shows the empty form (Player only) with focus on Login name.
- **A11** Rejected (422): "The account could not be created. Try again."; values kept; editing clears it.
- **A12** 403 and 404: the existing denial text; 401: one `reload()` and no message.
- **A13** (fails at baseline) Unknown: a rejected `fetch` and a 503 each show the unknown text, never "could not be created"; no further POST without a press; editing a field keeps the text; one more press sends exactly one more POST.
- **A14** A second press while pending sends no second POST.

**Navigation guards**
- **A15** (fails at baseline) A dirty form asks on the back link and on a sidebar link; Keep editing keeps values and the entry; Discard leaves once and sends no POST. A clean form leaves without a question.
- **A16** (fails at baseline) Leaving while the POST is pending asks with the pending wording; Leave aborts the wait, shows nothing afterwards, sends no second POST, and the list loads.
- **A17** (fails at baseline) With the activation link shown, the back link asks "Leave without the activation link?"; Stay keeps the link; Leave removes it, and returning to the creation page does not restore it. Back to accounts and Create another do not ask.
- **A18** (fails at baseline) On the list with a reset link shown, Create account asks; Stay keeps the link; Leave discards it. Typing in the search does not ask and keeps the link.

**Account and focus**
- **A19** (fails at baseline) A bootstrap for another `user_id` remounts the creation page: no values, status or secret carry over. Losing `accounts.manage` shows the denial and removes the secret.
- **A20** (fails at baseline) A PUSH arrival at the creation page focuses its `h1` once; Back/Forward to it and a reload do not move focus. The list's Create-account focus happens only on the PUSH return of A6/A10, not when that entry is later reached by Back/Forward.

### 6.1 Mutation probes (run by Sonnet; re-run by the reviewer)

| Probe | Change | Must fail |
|---|---|---|
| M1 | Write `q` with PUSH instead of REPLACE | A4 |
| M2 | Accept any string as `accountsReturn` | A7 |
| M3 | Map a transport failure or 5xx back to `error` | A13 |
| M4 | Clear the `unknown` status on edit | A13 |
| M5 | Carry the created response in Back to accounts' router state | A9 |
| M6 | Drop the activation-shown condition from the guard | A17 |
| M7 | Remove the `user_id` key from the creation route | A19 |
| M8 | Focus the Create account link on POP as well | A20 |
| M9 | Keep rendering the inline `CreateAccountPanel` on the list | A3 |

Record each probe's failing case, then revert it.

## 7. Verification

### 7.1 Per-commit checks (Sonnet; repeated by the reviewer)

From PowerShell in `C:\Users\nemes\dnd_ai\portal` (uppercase `C:`; Vitest fails with "failed to find the current suite" from a lowercase `c:/` cwd):
- focused: `npx vitest run src/pages/CreateAccountPage.test.tsx src/pages/AdminAccountsPage.test.tsx src/pages/AdminAccountsPage.resetLink.test.tsx src/components/CreateAccountPanel.test.tsx src/hooks/useCreateAccount.test.ts src/navigation/platformAccountsReturn.test.ts src/navigation/routeMeta.test.ts src/App.test.tsx` (adjust only for files that are folded or added);
- full `npm test`. Record the first run and any rerun separately, and name any failure outside these files;
- `npm run lint`, `npm run build`;
- from the repository root: `uv run python scripts/check_documentation.py` and `git diff --check`.

Backend checks are not required (portal and docs only), unless a backend file changes, which would be a stop condition.

### 7.2 C04 checkpoint merge requirements (not S01's verdict)

The C04 PR merges only when all of these hold:
1. S01 and S02 have each passed independent review.
2. The checkpoint acceptance cases pass on the integration head: S01's A1–A20, S02's cases (from its plan), and one full portal run showing both together.
3. CI passes on the exact integration head.

A reviewed slice is not a merged checkpoint. None of §7.3 is a merge gate.

### 7.3 Separate events (after the merge; not merge gates)

- Integrated-head browser evidence for focus, list return and one-time credentials (the C04 criteria's [browser](work-register.md#browser) obligation), including a real-browser check of A6, A10, A15–A17 and A20 and of the inherited arrival-focus uncertainty (§8).
- AX evidence ([ax](work-register.md#ax)) and owner acceptance (`p15-owner`). Nothing in this plan grants them.

## 8. Authorization, disclosure, concurrency and focus rules

- **Authorization is unchanged.** Both routes gate on `accounts.manage` as presentation; every request stays server-authorized, and a refusal is the fixed non-disclosing 404. Administrator stays disabled without `system_roles.grant_admin`.
- **Disclosure.**
  - The activation token lives only in the creation page's React memory: never in a URL, router state, storage, a log statement or an announcement (A9).
  - The search text may be in the address and router state. It is not a credential, the list request already sends it as `?q=` to the server, and it is bounded (§3.2 item 4). Nothing else from the list (names, ids, roles, statuses) enters history.
  - The unknown text names no account and does not claim that the account exists.
- **Concurrency.**
  - At most one create in flight; a POST is sent only by a press.
  - A late answer after unmount is ignored (existing abort).
  - An account change remounts the page; a capability loss unmounts the form.
- **Focus.**
  - Arrival at the creation page: its `h1`, once per PUSH arrival.
  - Success: the activation panel heading. Create another: Login name. Return to the list: its Create account link, on the PUSH return only.
  - Rejected, denied and unknown outcomes leave focus on the submit button, which is enabled again.
  - Back/Forward and reload move nothing.
  - **Inherited uncertainty.** C02 left open whether `usePageArrival` can take focus after a real interaction has started ([C02 readiness §4](p15-c02-checkpoint-readiness.md#4-the-provisional-cancel-focus-issue-against-the-checkpoint-criteria)). The creation page uses it, so its tests must wait for the heading to hold focus before typing, and the question stays with the browser check in §7.3. S01 does not diagnose or change `usePageArrival`.
- **Announcements.** Outcome text uses the existing polite status region; success is announced through the focused heading only (one meaningful announcement).

## 9. Intermediate states

T01 is a single commit. Until it lands, current behavior (§2.1) is shipped; no intermediate state is merged.

## 10. Decisions

**No owner decision is required.** Routine choices made here:

- **R-1 (query in the address).** The list search goes in `?q=` like the Characters and World browsers, which gives reload, Back and return for free. It is not a credential, and the API request already carries it. Router state alone was the alternative; it loses the query on a shared or reopened address with no privacy gain.
- **R-2 (page-local return key).** Unscoped pages have no task model (§4.8.10), so the return is a validated page-local key that can only name `/platform/accounts` plus a `q`. No `returnTo` address is accepted.
- **R-3 (Load more not retained).** The task names the query; page position is not part of it.
- **R-4 (unknown = transport failure or 5xx).** The portal cannot tell whether those committed; any other 4xx is a refusal. The wording warns about duplicates because the server reserves login names only at activation. A deliberate retry stays available: the administrator may have checked the list.
- **R-5 (guard the shown one-time links).** Leaving with a one-time link on screen loses it permanently, so in-app departures ask, as for unsaved input. Explicit actions on the panel do not ask.
- **R-6 (no legacy alias).** `/admin/accounts` exists only for old bookmarks; no bookmark to a creation route exists.
- **R-7 (heading-only success announcement).** Focusing the panel heading speaks the outcome; a second live announcement would repeat it.

## 11. Handoffs

### 11.1 Sonnet implementation instructions

1. Confirm the baseline (the commit adding this plan) is HEAD and `origin/phase15/completion`, with a clean worktree.
2. Read §2 to §8. Write the "(fails at baseline)" cases first, run them on the baseline, and record each failure (test name and assertion).
3. Implement §3.2 in the files of §4 only. Keep the reviewed behavior in §2.4.
4. Run §7.1. Run M1–M9, record each probe's failing case, and revert every probe.
5. **Stop and report instead of continuing if:**
   - a backend, API or authorization change seems necessary;
   - a change to `usePageArrival`, `useUnsavedChangesGuard`, `navigationHolds`, the announcer or the task-origin modules seems necessary;
   - an existing test would need a changed expectation other than those named in §4;
   - a case cannot be made to fail at baseline where marked.
6. Commit with the §5 subject, push, and record in §11.3 and the register's T01 row:
   - the SHA;
   - the test-first failures;
   - the focused and full runs, first run and rerun separately;
   - the probes;
   - the CI position. CI is expected to be "pending checkpoint PR".
7. Do not open, mark ready or merge a PR. Do not run browser or AX checks, start copy-ui, preview or other consumers, or record any acceptance.

### 11.2 Independent review boundary (Luna)

- **T01 = combined S01:** from the plan commit to the T01 implementation commit, plus any docs-only records commit that follows it.
- Review against §2.4, §3, §6 and §8. Re-run the focused tests and M1–M9.
- A pass is a slice verdict only; §7.2 and §7.3 remain.

### 11.3 Implementation record (Sonnet, 2026-11-23)

**Status:** implemented and pushed; **awaiting independent review (Luna); not accepted.** CI is pending the C04 checkpoint PR (none opened; no workflow was triggered or waited for). Browser, AX, pilot and owner acceptance were not run and are not claimed.

**Commits.** Baseline (plan) `f5f6e6e455709fddc2a27dc6a2fb08a984f8e2f0` (HEAD = `origin/phase15/completion`, clean worktree, confirmed first). T01 implementation `c2f15975c98943d952df6550f3c0cc2ebdf7d269`, subject "P15-C04-S01-T01: give account creation its own route with list return, focus and transient activation handling". Luna's range per §11.2: `f5f6e6e..c2f1597` plus the records commit that follows it (docs only; its SHA is in the hand-off report, because a commit cannot name itself).

**What changed (portal and docs only; no backend, API or authorization file).**
- New: `navigation/platformAccountsReturn.ts`, `pages/CreateAccountPage.tsx`, and their tests plus `App.platformAccounts.test.tsx`.
- Changed: `App.tsx` (route adapter `PlatformAccountCreateRoute`; both account routes keyed by `bootstrap.user.user_id`), `navigation/routeMeta.ts` (`platform.accounts.new`), `AdminAccountsPage.tsx` (no inline form, Create account link, `?q=` by REPLACE, focus on PUSH return, `ResetLinkGuard`), `usePlatformAccounts.ts` (takes the query), `useCreateAccount.ts` (`unknown`), `CreateAccountPanel.tsx` (now the page's form and activation panel with the guard), `OneTimeSecretPanel.tsx` (optional `actions` and `focusHeading`; `onDismiss` became optional), and `portal-behavior.md` / `portal-navigation.md` (route count 92).
- Not changed: `usePageArrival`, `useUnsavedChangesGuard`, `navigationHolds`, the announcer, the task-origin modules, `SessionContext`.

**Test-first failures (before any implementation).** The cases were written first. Because the new modules did not exist, two temporary stubs were created (`platformAccountsReturn.ts` returning empty values and `CreateAccountPage.tsx` rendering `null`) so that each case reports its own assertion instead of one import error; the stubs were deleted before implementation. Run on the baseline plus stubs (4 files): **59 failed | 29 passed (88)**. The saved output is in the session scratchpad (`c04_baseline_failures.txt`). Failing, by file:
- `platformAccountsReturn.test.ts` (5): the bounded-`q` read, the search builder, the return-state round trip, the carried search and the focus marker.
- `useCreateAccount.test.ts` (6): the 500/502/503/599 and transport-failure mappings to `unknown`, and the one-more-request-per-press case.
- `CreateAccountPage.test.tsx`: 41 of its 44 cases, against the stub. They include A1, A2, A3, A4 (REPLACE), A5, A6, A7 (direct entry and the tampered values), A8, A9, A10 (both), A13 (both), A15 to A18 and A20 (three), plus the focus-preservation cases.
- `App.platformAccounts.test.tsx` (7 of 8): A1, A2 and five A19 cases (the list-gate and legacy-redirect case passes at baseline, as it should).
- Honest limits of this evidence: with the stub page most failures are absence of the page, not the old inline form's behavior. A11, A12 and A14 are not marked "(fails at baseline)" in §6 and fail here only for that reason. That a case can fail for the right reason is shown by the post-change probes M1 to M9 below. In the hook file, the 404 case, the not-authenticated case and the other pre-existing cases already passed.

**Runs.**
- Focused §7.1 files plus `App.test.tsx` and `App.platformAccounts.test.tsx`, before the first full run: 10 files, **165 passed**. One earlier run of `CreateAccountPage.test.tsx` had a single failure that was my own test (A8 did not focus the submit button before pressing, so the page heading still owned focus and, correctly, kept it); the test was corrected to focus the button as a person pressing it would.
- **Full `npm test`, first run: 445 files, 1 failed | 444 passed; 5718 tests, 1 failed | 5717 passed.** The failure was `src/App.landing.test.tsx > persistent sidebar through the real route tree > is present on /platform/accounts`, a defect of this change: that test renders the real list inside a plain `MemoryRouter`, and the list called `useBlocker` unconditionally, which needs a data router. Fixed in the implementation, not in the test: the guard moved into `ResetLinkGuard`, mounted only while a reset link is shown, so the list needs a data router only then (production always has one). `App.landing.test.tsx` is unchanged.
- Focused rerun after the fix (11 files, `App.landing.test.tsx` added): **186 passed**.
- **Full `npm test`, rerun: 445 files, 445 passed; 5718 tests, 5718 passed.**
- `npm run lint`: clean. `npm run build`: succeeds (the existing chunk-size notice only).
- `uv run python scripts/check_documentation.py`: passes. `git diff --check`: clean (LF/CRLF notices only).

**Test files edited beyond the §4 list (harness or signature only; no expectation was weakened).**
- `usePlatformAccounts.test.ts`: the hook now takes the query, so the calls pass `""` and the query-change case uses `rerender`; one case added.
- `App.test.tsx`: the `usePlatformAccounts` mock no longer returns `query`/`setQuery` (they are not part of the hook's result any more). No expectation changed.
- `AdminAccountsPage.test.tsx`: the list needs a router (a `Link` and `useSearchParams`), so its renders sit in one; the `CreateAccountPanel` mock and its `create-account-panel` assertion are replaced by the A3 assertions (a Create account link to `/platform/accounts/new`, no inline form). The denial and table assertions are unchanged.
- `AdminAccountsPage.resetLink.test.tsx`: harness only (a data router); the `CreateAccountPanel` mock is removed; every expectation stands.
- `CreateAccountPanel.test.tsx`: the form moved to the page, so it renders inside a data router with `returnTo`; the two cases keep their assertions, and the link case now expects the named heading.

**Mutation probes** (each applied to one file, the named test files run, and the file restored byte-for-byte, checked by SHA-256 each time; no probe remains in the tree):

| Probe | Failing cases |
|---|---|
| M1 REPLACE to PUSH | A4 "writes q by REPLACE..." and A4 "leaves no history entry per keystroke" (2) |
| M2 accept any string as `accountsReturn` | 13 helper cases and 6 A7 page cases (19) |
| M3 transport failure / 5xx to `error` | 6 hook cases and both A13 cases (8) |
| M4 clear `unknown` on edit | both A13 cases (2) |
| M5 created response in Back to accounts' router state | A9 (1) |
| M6 drop the activation-shown condition from the guard | A17 "asks before the shown activation link is lost..." (1) |
| M7 remove the `user_id` key from the creation route | three A19 cases (remount, link removed, late answer) (3) |
| M8 focus the link on POP as well | A20 "focuses the list's Create account link on the PUSH return only" (1) |
| M9 keep the inline panel on the list | A3 and the two `AdminAccountsPage.test.tsx` table cases (3) |

**Decisions and notes for review.**
- *A20 and `usePageArrival`.* The hook focuses the heading on any arrival, including a first mount by Back or reload. To meet "PUSH only" without changing it, the page passes `ready = navigationType === PUSH`. A direct entry therefore moves no focus, so tests of a direct entry have no heading focus to wait for; every test that types after a PUSH arrival waits for the heading to hold focus first (`openCreation`). The inherited uncertainty (whether `usePageArrival` can take focus after a real interaction has started) is untouched and stays with the browser check in §7.3.
- *Focus is preserved, not forced.* The activation heading, the list's Create account link and the restored submit button take focus only if focus is on `body` (lost with the control that produced the change); a control the person chose meanwhile keeps it. Tests cover a sidebar link focused while the request was pending, for a refusal, an unknown outcome and a success, and a search field focused on the list.
- *The list is keyed by the signed-in account too* (not in §3.2 item 1, but required so a reset link, shown or in flight, cannot appear under another account); the creation route is keyed as planned.
- *`AdminAccountsPage` is split* into the capability gate and an authorized page, so a direct mount without `accounts.manage` no longer calls the list hook (it previously did before the check).
- *Late answers and account changes* rely on the existing abort-on-unmount in `useCreateAccount` and `useIssuePasswordReset` plus the key; `App.platformAccounts.test.tsx` covers a late create answer, a shown activation link, a lost capability, a shown reset link and a late reset answer across an account change.
- *Verification limits.* jsdom does not establish real-browser focus (including focus after a focused field becomes disabled), the native `<dialog>`, keyboard, zoom or screen-reader behavior; none of §7.3 was run. The unknown-outcome wording makes a retry deliberate, not impossible; duplicate accounts remain possible by design (no idempotency key; separate API work, R07).

### 11.4 Independent implementation review (Codex, 2026-11-23)

**Boundary and checkout.** Branch `phase15/completion`; initial worktree clean; HEAD and `origin/phase15/completion` both `f20b2f5e7575b20352f05184940b9aab951d4f32`. Ancestry is valid for baseline `f5f6e6e455709fddc2a27dc6a2fb08a984f8e2f0` → implementation `c2f15975c98943d952df6550f3c0cc2ebdf7d269` → docs-only records head `f20b2f5e7575b20352f05184940b9aab951d4f32`. The implementation changes the 20 reported portal/docs files; records after it are docs-only. `CLAUDE.md`, current grading rubric, maintained register, this plan, portal behavior/navigation references, route metadata, hooks, pages, components and changed test harnesses were inspected.

**A1–A20 and M1–M9.** Route adapters and page-level checks both gate list/create surfaces on current `accounts.manage` before protected account-list reads mount. Return navigation is rebuilt from the constant list path and a validated bounded `q`; the raw router state cannot supply a pathname or external destination. Search is URL state updated with REPLACE and query-only edits do not block. The activation token is held in the creation page's component state and passed only as a fragment-link string to a read-only input; it is not in the current location, router state or storage. Success, back and create-another paths remove the secret; account-key remount and route-gate unmount plus abort guards prevent late results crossing users or losing capability.

Dirty, pending and shown-secret guards preserve entered values/secret on Stay and send no second request on Leave. Unknown transport/5xx outcomes retain values and warning; edits do not clear that warning; another POST requires a deliberate submit. Refusal and unknown outcome focus return only if focus was lost; success heading, list Create account link and Create another login focus preserve a control the user moved to. Query return, tamper cases, one-time token absence, account changes, late create/reset responses and reset-link persistence are covered by the real component/App tests and the recorded mutations. The bounded baseline-plus-stubs run is not treated as proof that all 59 failures establish old behavior: most failed because the new module/page stubs were intentionally empty. The M1–M9 post-change probes are the more meaningful behavioral evidence and each targets its named acceptance case.

**Documented deviations.** (1) Passing `navigationType === PUSH` as `usePageArrival` readiness correctly suppresses its heading focus on direct entry/reload/POP while retaining PUSH focus. `usePageArrival` itself is unchanged. The known risk that its effect could take focus after a real interaction starts remains inherited and unverified in a browser; it is not newly graded here. (2) Keying the account list by `user_id` is a justified defense for reset-link state and late reset responses; A19 exercises account/capability changes. (3) Splitting `AdminAccountsPage` into the route/page gate and authorized descendant is necessary so denied direct renders do not mount `usePlatformAccounts`. (4) Mounting `ResetLinkGuard` only while a reset link exists avoids calling data-router-only `useBlocker` for existing plain-MemoryRouter list callers without a secret. Production routes and reset-link tests use a data router; the App landing regression test on a plain router now passes. (5) Test files beyond the plan's harness list are necessary signature adaptations: App's hook mock loses removed query setters; hook tests pass the new query parameter; reset/page tests supply router context. Two expectation changes are substantive but appropriate: the list test replaces the deleted inline-panel placeholder with the required link/no-form A3 assertion, and the panel test now asserts the actual secret heading/actions instead of its old callback-only contract. The remaining denial/table/reset expectations are preserved; none weakens acceptance. The first full run failed because the implementation initially called `useBlocker` on a plain router; the final conditional guard change addresses it, and the focused `App.landing` test and full rerun pass are recorded separately.

**Finding C04-S01-R1 — departure prompt falsely asserts no account was created after an unknown outcome.** `portal/src/components/CreateAccountPanel.tsx:107–126`. Trigger: the account POST has a transport failure or 5xx, so `status.kind === "unknown"`, then the user leaves with the retained nonempty form; alternatively, the user begins leaving while POST is pending and the request becomes unknown before they answer the blocker. In both cases `created === null` and `isPending === false`, so the generic dirty-form dialog says “You have entered details for a new account that have not been created.” The live status still says the portal could not confirm whether it was created, but the modal foreground contradicts it. A temporary test probe reproduced this in both orderings and was restored byte-for-byte (test-source SHA-256 `4E2F18CC07542F31E21D121C1A6A836094CCC4D256E2430B6789E22887C7C9C7`). Since duplicate pending accounts are possible by design, a user who takes the modal at its word may deliberately recreate an already-created account.

Rubric: authenticated account-manager creation path; exposure **2/3** (ordinary account setup, limited to an uncertain request followed by departure), impact **1/3** (bounded risk of duplicate pending accounts and operator cleanup; no automatic replay or lost committed data), triggerability **1/2** (requires a transport/5xx outcome and a departure), detection/recovery **1/1** (the foreground blocker is misleading and the uncertainty may be missed), blast radius **0/1** (one attempted account/user): **5/10, Medium**. Readiness: blocks the promised truthful-uncertainty behavior in T01. Bounded Sonnet correction: give `unknown` its own departure dialog, including when a pending blocker remains open as the POST settles; say the account may already exist, warn that leaving discards the form/activation link, and direct the user to check the account list before any deliberate retry. Preserve Stay, no-write Leave, the existing pending and activation-link wording, and no automatic replay. Add tests for both unknown-before-navigation and pending-navigation-then-unknown, plus A13/A15/A16 regression assertions.

**Verdicts.** T01 and C04-S01: **CHANGES REQUIRED** for C04-S01-R1. No authorization, secret-placement, return-path, account-isolation or duplicate-submit defect was found. The inherited `usePageArrival` browser-focus uncertainty remains separate; no new evidence establishes a current defect there.

**Independent verification (PowerShell).** From `C:\Users\nemes\dnd_ai\portal`, the focused route/navigation/creation/list/reset/hook suite plus plain-router regression passed: 11 files, 186 tests. The two temporary unknown-departure probes failed on the false modal wording; their source was restored and hash-verified. `npm run lint`, `npx tsc -b` and `npm run build` passed; build emitted the existing chunk-size advisory. From repository root, `uv run python scripts/check_documentation.py` and `git diff --check` are rerun after this record edit. No full suite was repeated: the initial full run's `App.landing` failure caused by unconditional `useBlocker`, and the subsequent clean 445-file/5718-test rerun remain separate in §11.3. CI remains pending the C04 checkpoint PR; browser/AX, human and owner checks remain pending.


### 11.5 C04-S01-R1 correction (Sonnet, 2026-11-23)

**Status:** C04-S01-R1 **corrected at `c031179a2997ecc4ead71d98008e4d8aee6cd558`, pending independent confirmation.** §11.4 is preserved unchanged as the original review. Baseline for this correction: `f20b2f5e7575b20352f05184940b9aab951d4f32` (HEAD = origin, with Luna's uncommitted §11.4 and register edits preserved and committed in the records commit). Scope: the departure dialog's wording only, in `CreateAccountPanel.tsx`; no backend, shared guard (`useUnsavedChangesGuard`, `ConfirmDialog`, `navigationHolds`), `usePageArrival`, hook or secret-handling change.

**Fix.** When the create outcome is unknown (transport failure or 5xx) and the person leaves, the question is "Leave before checking whether the account was created?" with "The account may already exist. Leaving discards this form and any activation link held by this page. Check the account list before deliberately creating it again.", **Leave** and **Stay**. The dialog is chosen from the current status on every render, so a pending question that is open when the request becomes unknown changes to this wording in place. Precedence is unchanged: pending ("Leave while the account is being created?"), then a shown activation link, then unknown, then the ordinary dirty-form question ("Discard unsaved changes?", which keeps its "have not been created" sentence because nothing was sent). The unknown question appears only while the form is dirty, as before; Stay, Leave, blocking and the absence of any automatic replay are untouched.

**Failed before the fix (both reported regressions, written first).** In `CreateAccountPage.test.tsx`: "C04-S01-R1 never says the account was not created when the outcome is unknown" (unknown settled, then leave) and "C04-S01-R1 updates an open pending question when the request becomes unknown" (pending question open, request becomes a 503). Both failed on the old text, "You have entered details for a new account that have not been created." (2 failed, 44 passed in the file). After the fix both pass. Each asserts the new title and body, that "have not been created" is absent, that Stay keeps the page and its values with one POST, and that Leave goes to the list with still one POST (no replay). The second also asserts the pending sentence is gone once the question has changed.

**Regression guards kept.** The existing A15 (dirty form: Keep editing / Discard, no POST), A16 (pending wording, Leave aborts, one POST), A17 (activation-link question, Back to accounts and Create another do not ask) and A13 (unknown text, edits keep it, one request per press) cases pass unchanged.

**Runs.** Focused suite (`CreateAccountPage`, `AdminAccountsPage` and its reset-link file, `CreateAccountPanel`, `useCreateAccount`, `useUnsavedChangesGuard`, `platformAccountsReturn`, `routeMeta`, `App`, `App.platformAccounts`, `App.landing`): 11 files, **189 passed**. `npm run lint`, `npx tsc -b` and `npm run build` pass (the existing chunk-size notice only). `uv run python scripts/check_documentation.py` and `git diff --check` pass. **No full-suite rerun:** the change is one conditional branch of a dialog's strings in one component and touches no shared module, so the bounded focused run is the evidence; the full-suite result of §11.3 (445 files, 5718 tests) predates this change and is not claimed for it.

**Mutation probe.** Making the new branch unreachable (`status.kind === "unknown"` replaced by `false`) fails exactly the two new regressions (2 failed, 44 passed in `CreateAccountPage.test.tsx`); the file was restored and its SHA-256 matched the pre-probe hash (`958ad14bb883…`).

**Re-review range.** `f20b2f5e7575b20352f05184940b9aab951d4f32..c031179a2997ecc4ead71d98008e4d8aee6cd558` (the correction: `CreateAccountPanel.tsx` and `CreateAccountPage.test.tsx`) plus the docs-only records commit that follows it. CI remains pending the C04 checkpoint PR; browser/AX, human and owner acceptance remain pending.

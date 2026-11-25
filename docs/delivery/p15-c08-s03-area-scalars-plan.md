# D/P15-C08-S03 implementation plan: maintain supported area scalars

Owner register rows: [P15-C08](work-register.md#p15-c08), [P15-C08-S03](work-register.md#p15-c08-s03), [P15-C08-S03-T01](work-register.md#p15-c08-s03-t01). Source finding: [R09 — Smaller layout, list and form repairs](work-register.md#r09--smaller-layout-list-and-form-repairs): "Add area summary/dimensions/environment using existing validation and commands." Checkpoint coordination: [S01 plan §12](p15-c08-s01-location-children-plan.md#12-c08-checkpoint-coordination).

Prepared by Opus, 2026-11-24, against planning baseline `680629b0e9d8193112c1e6378e74fcd41323cac6` (see the S01 plan header). **T01 independent review: PASS WITH VERIFICATION LIMITS (§11.6).** The original CHANGES REQUIRED disposition and C08-S03-1 score remain in §11.4; §11.6 confirms the bounded correction.

## 1. Entry readiness

- S03 has no slice prerequisite ("checkpoint entry criteria; no additional slice-specific gate"), and C08 has none. S03 is eligible now.
- **Scheduling, not a dependency:** S03-T01 runs after S01-T01's records commit (S01 plan §12.3), so the branch's commits stay linear. It does not wait for S01's review.
- Before writing tests, the implementer confirms at the then-current head that §2.1 still holds (§11.1 step 2).
- No owner decision blocks S03.

## 2. Verified current behavior (at `680629b0`)

### 2.1 What exists

- **API.** `POST /campaigns/{c}/authoring/dungeons/{dungeon_id}/areas` (`api/dungeon_authoring.py`, `CreateAreaRequest`) accepts these fields:
  - `name`: 1 to `NAME_MAX_LENGTH`;
  - `summary`: at most `DESCRIPTION_MAX_LENGTH`;
  - `area_type` and `dimensions`: at most `SHORT_TEXT_MAX_LENGTH`;
  - `environmental_properties`: at most `NOTES_MAX_LENGTH`.

  It calls `commands/dungeons.py` `create_dungeon_area`, which trims each field and turns whitespace-only into null (`normalize_description`, `normalize_child_text`, `normalize_long_text`). It also takes `canon.edit` plus the world authoring scope under lock, checks the dungeon, applies the area limit (`dungeon_limit_reached`), and stores a draft area with an idempotent receipt.
- **Update.** `POST …/dungeon-areas/{id}/update` accepts the same fields with `expected_row_version`.
- **Area edit page.** `pages/DungeonAuthoringPages.tsx` already edits all five fields:
  - Name;
  - Summary (`TextAreaField`, `summary_max_length`);
  - Kind of area;
  - Size (`TextField`, hint "For example 30 ft by 40 ft.", `short_text_max_length`);
  - Environment (`TextAreaField`, `notes_max_length`).

  It sends empty values as null.
- **The gap: the add-area form.** `components/world/DungeonAreasSection.tsx`, inside the dungeon workspace's Areas section, has only "Area name" and "Kind of area". It sends `{ name, area_type }`.
  - `types/dungeonAuthoring.ts` types `add_area`'s body as exactly those two fields.
  - The form's unsaved report and retained-input list name only those two values.
- **Command handling.** `useDungeonCommand` uses `useAuthoringMutation`:
  - The same body re-sent reuses its idempotency key, and an edited body gets a new key.
  - A network or server failure with an unknown outcome is shown by `MutationStatusMessage` with a retry of the same request.
  - A world-authority 403 is reported as permission loss: the workspace withdraws private views and shows the retained input read-only.
  - Codes in `DUNGEON_CODE_MESSAGE` (for example `dungeon_limit_reached`) show their sentence.
  - `after` (clear and refocus) runs only on success.
- **Tests.**
  - `WorldRecordWorkspace.test.tsx` ("World record workspace: a dungeon") covers adding an area, the required name, the half-typed area on leaving, a refused add and a bare 403. "Adds an area …" asserts the body `toEqual({ name: "Shrine of Ash", area_type: "chamber" })`.
  - `tests/database/test_api_dungeon_authoring.py` creates areas with `summary` and `dimensions` (`new_area`) and checks the dungeon read's per-area `summary`. It does not check `environmental_properties` on create, trimming or empty-to-null on create, or the create length limits.

### 2.2 Plan-entry reproduction results

A temporary copy of `WorldRecordWorkspace.test.tsx` with one added case ran once and was deleted.

| Case | Kind | Observation |
|---|---|---|
| Q1 | defect | The add-area form's text boxes are only `area-add-name` and `area-add-kind`. There is no Summary, Size or Environment field. |
| Q2 | defect | Submitting "Shrine" sends `{"name":"Shrine","area_type":null}`. |

### 2.3 Deviation S03 repairs

- **DV-1:** a new area's summary, size and environment can be entered only afterwards, on the area's edit page.

### 2.4 Source-inspected risks (to be proven by cases below)

- New fields left out of the unsaved report would let a person leave with only a typed summary and lose it unprotected (D5).
- New fields left out of the retained input would lose them on permission loss (D7).
- Clearing on failure would lose typed values on a refusal (D6).

### 2.5 Behavior that must not regress (baseline-passing guards)

- The existing dungeon-workspace add-area cases:
  - adds and announces;
  - requires a name;
  - keeps a half-typed area;
  - a refused add-area keeps only typed values;
  - a bare 403 is a session check;
  - asks again on request.

  These stay, except for the one body adaptation in §6.2.
- The area edit page's behavior (`DungeonAuthoringPages.test.tsx`).
- The backend: `test_api_dungeon_authoring.py`, unchanged except for the new guard cases D11–D13.

## 3. Outcome, scope and exclusions

### 3.1 User outcome

When adding an area to a dungeon, an author can also give its summary, size and environment. They are saved with the area, through the existing command, and appear wherever the area's details are read.

### 3.2 In scope (T01)

- **New fields.** `DungeonAreasSection` adds three fields to the add-area form, after "Kind of area", with the edit page's labels and limits:
  - **Summary**: `TextAreaField`, `id="area-add-summary"`, `maxLength={options.limits.summary_max_length}`.
  - **Size**: `TextField`, `id="area-add-dimensions"`, hint "For example 30 ft by 40 ft.", `maxLength={options.limits.short_text_max_length}`.
  - **Environment**: `TextAreaField`, `id="area-add-environment"`, `maxLength={options.limits.notes_max_length}`.
- **Body.** `{ name, summary, area_type, dimensions, environmental_properties }`. Each optional value is trimmed, and empty becomes null. The `add_area` type in `types/dungeonAuthoring.ts` is widened to match. Using `AreaFieldsBody`, if it fits, is preferable to a new type.
- **Unsaved report and retained input.** Both include all five values. The retained list uses the labels Name, Summary, Kind, Size and Environment, and leaves out empty values.
- **On success.** All five values clear, and focus returns to Area name. The announcement is unchanged ("Area <name> added as a draft"). The Areas list re-reads and shows the summary, as it already does from the server's `summary`.
- **On any failure.** Nothing clears. The existing notice paths are used unchanged.
- **Validation.** Name stays required client-side ("Enter a name."). The other limits are enforced by `maxLength` and by the server's 422. Like the edit page, no new client-side length messages are added.
- **Backend guards** (test-only, in `test_api_dungeon_authoring.py`) for the round trip the form relies on: D11–D13.
- **Documentation.** The dungeon authoring row of `docs/reference/portal-behavior.md` names the add form's fields.

### 3.3 Exclusions

- No API, command, schema, validation-rule or limit change. No new error codes or messages.
- No change to the area edit page, `useDungeonCommand`, `useAuthoringMutation`, the permission-loss components or the Area now panel.
- No structured dimensions (numbers or units). Size stays free text as stored.
- No change to the Areas list's columns.

## 4. Affected files and interfaces

| File | Change |
|---|---|
| `portal/src/components/world/DungeonAreasSection.tsx` | Fields, body, unsaved report, retained input, clearing |
| `portal/src/types/dungeonAuthoring.ts` | `add_area` body type |
| `portal/src/components/world/WorldRecordWorkspace.test.tsx` | New D1–D10 in the dungeon `describe` block, plus the §6.2 adaptation |
| `tests/database/test_api_dungeon_authoring.py` | New D11–D13 (guards) |
| `docs/reference/portal-behavior.md` | Dungeon authoring row |

## 5. Task commit

One commit: `P15-C08-S03-T01: add summary, size and environment to the add-area form`. A records commit follows (docs only).

## 6. Acceptance cases

| Case | Behavior | Baseline |
|---|---|---|
| D1 | The open add-area form has labelled Summary, Size (with its hint) and Environment fields, with the options' maximum lengths. | fails |
| D2 | Filling all five fields (with surrounding spaces) sends the trimmed body with all five keys. | fails |
| D3 | Leaving Summary, Size and Environment empty or whitespace sends `summary`, `dimensions` and `environmental_properties` as `null`. | fails |
| D4 | After success: all five fields are empty, Area name has focus, the announcement is unchanged, and the new area's summary appears in the Areas list (the mock echoes the posted summary). | fails |
| D5 | Typing only a Summary and then leaving ("Back to World") opens "Discard unsaved input?" naming "a new area". | fails |
| D6 | A 422 refusal keeps all five typed values, sends no clear or refocus, and makes no announcement. A `dungeon_limit_reached` refusal shows its sentence and keeps the values. | fails |
| D7 | Permission loss (the REVOKED fixture): the retained panel shows the typed Summary, Size and Environment read-only, and no private area names. | fails |
| D8 | Unknown outcome (a network failure): the retry sends the identical five-field body with the same `Idempotency-Key`. Editing Environment and submitting again sends a new key. | fails, because the fields are missing. The key rule itself is the shared hook's. |
| D9 | The name is still required: an empty name with a filled Summary sends nothing and shows "Enter a name.". | fails, because Summary is missing. The rule is a guard. |
| D10 | Done closes the form, and reopening it shows the values not yet sent (the form state stays mounted), as today for name and kind. | fails, because the fields are missing. The behavior is a guard for name and kind. |
| D11 | Backend guard: create with all five fields, then `GET …/authoring/dungeon-areas/{id}` (or the dungeon read) returns them trimmed. Whitespace-only values become null. | guard |
| D12 | Backend guard: create with `dimensions` longer than `SHORT_TEXT_MAX_LENGTH`, or `environmental_properties` longer than `NOTES_MAX_LENGTH`, gives 422 and creates no area. | guard |
| D13 | Backend guard: a caller without `canon.edit` gets the existing refusal for create with the new fields, and nothing is stored. | guard |

"Fails" means the case fails at baseline: record the test name and assertion. Guards are run and recorded as passing at baseline. They are not expected to fail first.

D10's premise (values kept after Done) must be confirmed at baseline for name and kind before the case is written. If it does not hold, drop D10 and record why.

### 6.1 Mutation probes

| Probe | Mutation | Must fail |
|---|---|---|
| M1 | Omit `summary` from the body | D2 |
| M2 | Send `""` instead of null for an empty Environment | D3 |
| M3 | Leave the new fields out of the unsaved report | D5 |
| M4 | Leave the new fields out of the retained input | D7 |
| M5 | Do not clear the new fields on success | D4 |
| M6 | Clear the fields before sending | D6, D8 |

Revert each probe with exact bytes restored and hashes compared.

### 6.2 Permitted changes to existing tests

- "adds an area, stays on the list, clears the form, keeps focus in Name and announces it": the expected body becomes `{ name: "Shrine of Ash", summary: null, area_type: "chamber", dimensions: null, environmental_properties: null }`.
- The dungeon mock's POST handler may also record `summary` into the area row it adds (needed by D4). Existing cases do not depend on it being absent.

Any other changed expectation is a stop condition.

## 7. Verification

### 7.1 Per-commit checks (Sonnet; repeated by the reviewer)

- **Portal**, from PowerShell in `C:\Users\nemes\dnd_ai\portal` (uppercase `C:`):
  - focused: `npx vitest run src/components/world/WorldRecordWorkspace.test.tsx src/pages/DungeonAuthoringPages.test.tsx src/components/world/WorldRecordWorkspace.areaNow.test.tsx src/components/world/WorldRecordWorkspace.scoped.test.tsx`;
  - full `npm test`. Record the first run and any rerun separately, naming each failure;
  - `npm run lint`, `npx tsc -b`, `npm run build`.
- **Backend** (test-only change):
  - `uv run pytest tests/database/test_api_dungeon_authoring.py`;
  - `uv run ruff format --check` and `uv run ruff check`.

  A full shard run is not required for a test-only addition to one file. Record if one was run.
- From the repository root: `uv run python scripts/check_documentation.py` and `git diff --check`.

### 7.2 C08 checkpoint merge requirements

See [S01 plan §12.4](p15-c08-s01-location-children-plan.md#124-c08-checkpoint-merge-requirements).

## 8. Authorization, disclosure, refusal, retry and focus

- **Server-authoritative.** The create command decides authority, limits, normalization and the draft status. The form only collects values and reports the answer.
- **Disclosure.** Retained input shows only what the person typed. Private views are withdrawn on loss by the existing workspace mechanism (D7).
- **Refused outcomes.** Validation (422), the area limit and stale-session (bare 403) answers keep every value and use the existing messages (D6, plus the guard cases in §2.5).
- **Unknown outcome and retry identity.** The same body re-sent reuses its key. An edited body is a new request with a new key, and a confirmed create is never repeated (D8; shared hook).
- **Read-only reconciliation.** After success the workspace re-reads the dungeon. If that read fails, the existing "saved, but the latest data could not be loaded" notice applies, unchanged.
- **Drafts and navigation.** All five values are protected on departure (D5) and survive section changes as before.
- **Focus and announcements.** Focus returns to Area name after success. The announcement is unchanged. Failures show their notice without moving focus.

## 9. Intermediate states

T01 is a single commit. It is independently mergeable in substance, but C08 merges as one checkpoint (S01 plan §12.4).

## 10. Decisions

**No owner decision is required.** Routine choices made here:

- **R-1 (the edit page's labels, hints and limits).** One vocabulary for the same fields.
- **R-2 (no new client-side length messages).** This matches the edit page. `maxLength` and the server's 422 already bound the values.
- **R-3 (backend guard cases).** They pin the create round trip the form now depends on. They pass at baseline and are labelled as guards.
- **R-4 ("the selected area").** The criteria's "use current commands for the selected area" is satisfied by sending through `create_dungeon_area`. The area edit page already uses `update_dungeon_area` and is unchanged.

## 11. Handoffs

### 11.1 Sonnet implementation instructions

1. Confirm that S01-T01's records commit is present, and use the current `origin/phase15/completion` head as this task's baseline. It must be HEAD with a clean worktree. Record its full SHA.
2. Revalidate §2.1 at this baseline: the API fields and limits, the form's two fields, the `add_area` type, and the existing test's body assertion. Stop on any difference.
3. Read §2 to §10. Write D1–D10 first and run them on the baseline. Record each failure (test name and assertion). Run D11–D13 and record that they pass. Confirm D10's premise.
4. Implement §3.2 in the files of §4 only, with only §6.2's adaptations.
5. Run §7.1. Run M1–M6 and revert each with exact bytes restored.
6. **Stop and report instead of continuing if:**
   - an API, command, schema or limit change seems necessary;
   - a change to `useDungeonCommand`, `useAuthoringMutation`, the permission-loss components or the area edit page seems necessary;
   - an existing expectation outside §6.2 would change;
   - a "fails" case cannot be made to fail at the baseline.
7. Commit with the §5 subject and push. Record the following in §11.3 and the register's S03-T01 row, then commit and push the records:
   - the baseline and implementation SHAs;
   - the revalidation;
   - the test-first failures and guards;
   - the runs (first run and rerun separately);
   - the probes;
   - the CI position: "pending checkpoint PR".
8. Do not open, mark ready or merge a PR. Do not start S02, run browser or AX checks, start consumers, or record any acceptance.

### 11.2 Independent review boundary

- **T01 = combined S03:** from the recorded baseline to the implementation commit, plus its records commit.
- Review against §2.5, §3, §6 and §8, and re-run §7.1 and M1–M6.
- A pass is a slice verdict only. S01 plan §12.4 remains.

### 11.3 Implementation record

Sonnet, 2026-11-24. Baseline `ba73a88f4b76388f377e4245d11cf95527953bdc` (the S01 review records commit; confirmed as HEAD and `origin/phase15/completion` with a clean worktree before starting). Implementation commit `67922e8ce46561240a72e3e25be3134a5c29b6fd`: `P15-C08-S03-T01: add summary, size and environment to the add-area form`. Review range: `ba73a88f4b76388f377e4245d11cf95527953bdc..67922e8ce46561240a72e3e25be3134a5c29b6fd`, plus this records commit.

**Revalidation of §2.1 at the baseline (no difference).** `CreateAreaRequest` (via `_AreaFields`) takes `name` (1 to `NAME_MAX_LENGTH`), `summary` (`DESCRIPTION_MAX_LENGTH`), `area_type` and `dimensions` (`SHORT_TEXT_MAX_LENGTH`) and `environmental_properties` (`NOTES_MAX_LENGTH`); `DungeonAreasSection` had only Area name and Kind of area; the `add_area` command body was typed `{ name; area_type }`; the existing test asserted exactly `{ name: "Shrine of Ash", area_type: "chamber" }`; the edit page already has Summary, Kind of area, Size (hint "For example 30 ft by 40 ft.") and Environment with the same limits. No API, command, schema or limit change was needed.

**Change.** `DungeonAreasSection.tsx`: Summary (`TextAreaField`, `area-add-summary`), Size (`TextField`, `area-add-dimensions`, the edit page's hint) and Environment (`TextAreaField`, `area-add-environment`) after Kind of area, with the options' `summary_max_length`, `short_text_max_length` and `notes_max_length`; the body is the five keys with each optional value trimmed and empty sent as null; the unsaved report and the retained input (labels Name, Summary, Kind, Size, Environment, empty values left out) include all five; all five clear and focus returns to Area name only on success. `types/dungeonAuthoring.ts`: `add_area` now carries the existing `AreaFieldsBody`. `portal-behavior.md`: the Add area sentence of the dungeon authoring row. `test_api_dungeon_authoring.py`: D11-D13. No API, command, `useDungeonCommand`, `useAuthoringMutation`, permission-loss or area edit page change.

**Test-first (unchanged form).** In `WorldRecordWorkspace.test.tsx` ("World record workspace: a dungeon") D1-D10 were written first. At the baseline all ten failed: D1-D9 and D10 at `Unable to find an accessible element with the role "textbox" and name "Summary"`, and the §6.2-adapted existing test ("adds an area, stays on the list, ...") failed on the body `toEqual` (the form sent two keys). D10's premise was confirmed before it was kept: a temporary case (name and kind typed, Done, reopen) passed at the baseline and was deleted. D1 and D6 were revised after that first baseline run (see below) and the revised versions were run again against the unmodified source (restored byte-for-byte, SHA-256 equal): both failed at the same Summary lookup. D11-D13 (backend guards, test-only) passed on the unchanged backend (3 passed), as did the other 15 cases of the file (18 in all).

**Two corrections to my own new tests (disclosed).** D1 first asserted a `maxlength` attribute; the shared fields do not set one (the limit is shown by the counter near the end), so D1 now types 3,990, 195 and 3,980 characters and asserts "10", "5" and "20 characters remaining", which distinguishes the options' 4,000, 200 and 4,000. D6 first moved focus to Environment right after opening the form, but opening the form moves focus to Area name later (deferred), so D6 now waits for that and then moves focus; it asserts that a refusal leaves focus where it was. No assertion was weakened to match the implementation.

**After the change.** Focused set of §7.1 (4 files): 160 passed. The dungeon block of `WorldRecordWorkspace.test.tsx`: 66 passed.

**Full portal runs (reported separately).**
1. First run: 454 files passed, 2 failed (456 files, 5,936 of 5,938 tests): `OrganizationMembersReader.test.tsx` > "does not show the previous organization's roster while the next one loads" (8,122 ms; the open C06 investigation) and `WorldsPage.filter.test.tsx` > "F8: counts the deduplicated worlds actually displayed, campaign-visible ones included, and says 1 world" (8,138 ms). Both files then passed together (44 of 44).
2. Second run: **456 files, 5,938 tests passed, 0 failed.**
Both first-run failures took about 8 seconds, but their causes are **not diagnosed** here. The `OrganizationMembersReader` failure is the open C06 obligation; the `WorldsPage.filter` F8 failure is a further unexplained single-test failure, distinct from it, and neither is resolved by this record.

**Other checks.** `npm run lint`, `npx tsc -b` and `npm run build` pass. Backend: `uv run pytest tests/database/test_api_dungeon_authoring.py` (18 passed); `ruff format --check` and `ruff check` pass. `uv run python scripts/check_documentation.py` and `git diff --check` pass. No full backend shard run was made (test-only addition to one file, per §7.1); no CPU-heavy verification overlapped another.

**Probes (each restored byte-for-byte; SHA-256 compared equal after every probe).**

| Probe | Failed cases |
|---|---|
| M1 | D2 (also D3, D4, D8 and the adapted existing test) |
| M2 | D3 (also the adapted existing test) |
| M3 | D5 |
| M4 | D7 |
| M5 | D4 |
| M6 | D6, D8 (also D7) |

The first probe run aborted on a console-encoding error in the probe script (the file was restored by its `finally` block and compared equal to the backup); the table gives the rerun after the script was fixed.

**CI position.** Pending the checkpoint PR; none opened. Not run: browser/AX, human review, owner acceptance, S02, consumers.

### 11.6 Independent confirmation of C08-S03-1 (Codex, 2026-11-24)

**Verdicts:** **C08-S03-1: CONFIRMED CORRECTED. T01/S03: PASS WITH VERIFICATION LIMITS.** The original §11.4 CHANGES REQUIRED verdict and score 6 Medium remain historical. No new implementation finding was demonstrated. This review does not grant checkpoint acceptance. CI remains pending the checkpoint PR; browser/AX, human and owner acceptance remain pending.

**Ancestry, scope and worktree.** Verified baseline `f327c13a1963d6e327d443e26168db70e05827af` → correction `12ca7ec0616243a027755f070a201f2f5cea3cc5` → records HEAD `9037f7f750c0d028c2c0d82bcc6376c6a46c1fc7` on `phase15/completion`; all are ancestors of HEAD, which matches `origin/phase15/completion`. The worktree was clean before these review-record edits. Correction changes only `DungeonAreasSection.tsx` and `WorldRecordWorkspace.test.tsx`; no backend, API, shared hook, or other production boundary changed. The records commit changes this plan and the maintained register.

**Finding disposition and behavior.** The per-field edit counters advance on every input change and the submission snapshots them. Successful settlement clears each field only if its counter still matches; whitespace changes and edits away and back therefore remain newer input even if the value is equivalent. E1/E2 cover newer Environment, Name, Summary, Kind and Size; the untouched fields clear. E3 covers whitespace and away-and-back edits. E4 verifies untouched fields clear and focus returns to Area name. E1 verifies focus remains in a focused field holding newer input. E5 verifies a retry preserves the newer Environment value and repeats the original body and `Idempotency-Key`. Because `useDungeonCommand` disables Add while pending and Retry invokes the existing `useAuthoringMutation` retry path, the original `after` callback retains its submission snapshot while the edit counters continue advancing. E6 verifies refusal preserves input. Existing D4/D6/D8/D10 remain unchanged, retaining success, refusal/retry and Done/reopen behavior. Announcements and submitted body are unchanged. Account/world isolation remains in the existing hook; no hook or scope-key change occurred.

**Test-first and mutation evidence.** E1, E2's four field variants, E3 and E5 failed on the unfixed source because the expected newer input was empty after success (seven failures). E4 and E6 passed before the fix as guards. Both recorded correction mutations were inspected: MA (unconditional clearing) fails E1/E2/E3/E5; MB (always refocus Area name) fails E1. The correction record reports exact byte restoration with equal before/after SHA-256 `4d93d0acb986...`; no mutation was made during this confirmation.

**Current verification.** Re-ran §7.1 focused portal tests: **4 files, 169 passed**. Dungeon-authoring backend guards: **18 passed**. Documentation checker and diff checks pass after this record update. No full portal suite or backend shard was rerun. Keep full portal evidence as separate events: original run 1 **5,936 passed, 2 failed**; the two failing files later passed together in isolation (**44 tests**); original clean rerun **456 files, 5,938 passed**; correction's clean run **456 files, 5,947 passed**. The two initial failure causes remain unproven. No backend shard run was performed for S03. CI remains pending the checkpoint PR.

**Limits and coordination.** This confirmation is focused on the C08-S03-1 correction; it is not browser/AX, human or owner acceptance and does not replace exact-integration-head C08 criteria in S01 plan §12.4. S02 and consumers were not started.

### 11.4 Independent review (Codex, 2026-11-24)

**Verdicts:** **T01/S03: CHANGES REQUIRED.** Finding C08-S03-1 below prevents the newer-input contract from being met. No second implementation finding was demonstrated. The review disposition blocks this slice only; it does not grant checkpoint acceptance. CI remains pending the checkpoint PR; browser/AX, human and owner acceptance remain pending.

**Ancestry, scope and governing contract.** Verified `ba73a88f -> 67922e8c -> f327c13a`; baseline, implementation and records head are ancestors of current HEAD `f327c13a1963d6e327d443e26168db70e05827af` on `phase15/completion`. The worktree was clean before these review-record edits. Production changes are limited to `DungeonAreasSection.tsx`, its `add_area` body type, and the dungeon-authoring documentation row. Backend changes are tests only (`test_api_dungeon_authoring.py`). The only additional file is the disclosed test-only acceptance-guard pin. No API, command, schema, validation limit, `useDungeonCommand`, `useAuthoringMutation`, permission-loss code, area edit page or S01 route changed. Reviewed R09, the area-scalar contract, the governing API/command/editor implementations and the maintained register.

**C08-S03-1 — successful completion erases newer, unsent form input.** Track: application behavior. Location: `portal/src/components/world/DungeonAreasSection.tsx`, `submit()` success callback. Trigger: an editor submits an area, then changes one of the still-enabled fields while the request is pending, before the response succeeds. The callback unconditionally clears all five fields. A temporary probe held the POST response, changed Environment to `Newer note typed while pending`, then released a successful create. The area and normal success announcement appeared, but the Environment input was empty; the later text was never included in the submitted request and was silently lost. The probe was removed and the test file restored byte-for-byte (SHA-256 `04C9D1B1EA033E55CBA2D68D6706605306D3F248D4FE5FD48F5E8BCBF9C099EB`; final Git blob matches HEAD).

**Rubric and readiness.** Supported-path exposure **2** (ordinary editor create flow; the controls remain editable while the request is pending); impact **1** (one user's unsent field content is lost and can be re-entered); triggerability **2** (readily repeatable during a pending request); detection/recovery **1** (the form silently clears and appears settled even though newer input was not submitted); blast radius **0** (bounded to that form/user). **Score 6, Medium.** No database corruption or partial write: the server creates only the submitted body. Readiness: **blocks this slice** because the task explicitly requires newer input to remain correct. Bounded correction: associate successful clearing with the submitted values and clear only fields that have not changed since submission; preserve newer values and avoid moving focus away from a field containing newer input. Add a held-success regression that edits a field after submit, verifies the created body is the original snapshot, verifies the newer field remains, and checks focus; retain D4's no-new-edit success behavior and D6/D8 refusal/retry cases.

**A1–A16-style evidence review (D1–D13).** The record's D1–D10 baseline failures mostly stop at the absent Summary textbox; they establish missing form controls, not every success/refusal/retry behavior. D10's old behavior premise was separately demonstrated at baseline (Done/reopen retained name and kind). D1's revised test tests the shared character counters against limits rather than a nonexistent `maxlength` attribute; D6's revised focus assertion waits for the opening focus effect before testing a later refusal. Both revised tests were rerun against byte-restored baseline source and still fail at the missing Summary field. D11–D13 are genuine baseline guards with positive controls where appropriate and exercise server-side normalization, 422/no-write limits and refusal/no-write authorization. `test_api_dungeon_authoring.py` adds tests only. The §6.2 adaptation changes the old add-area body expectation to include the three null optionals required by the five-key contract; its mock now echoes submitted summary so D4 can assert the listed result. No other existing test expectation was weakened in the diff.

**Mutation evidence.** Independently reran valid targeted M1–M6 mutations; each failed its named D case and restored `DungeonAreasSection.tsx` byte-for-byte (SHA-256 `982CB8F47EA25E4BB34D17F7DA3903C56CE62E0D631FA25B5A0F745C1F58B5DC`): M1 omitted summary and failed D2; M2 sent empty string and failed D3; M3 omitted new fields from unsaved reporting and failed D5; M4 omitted retained Summary and failed D7; M5 omitted new-field clearing and failed D4; M6 cleared new fields before send and failed D6. One reviewer M6 attempt was malformed at PowerShell argument parsing and ran no tests; it is excluded. The valid rerun failed D6. The implementation record's earlier probe-script console-encoding attempt is also excluded; only its corrected rerun is evidence.

**Independent checks and separate historical runs.** Focused §7.1 portal set: **4 files, 160 passed**. Dungeon-authoring backend guards: **18 passed**. Portal lint, `npx tsc -b`, build, `ruff format --check`, `ruff check`, documentation and diff checks passed; build emitted the existing large-chunk advisory. No backend shard run was performed for S03, and I did not repeat either full portal run. Preserve the recorded events separately: full run 1 had **5,936 passed, 2 failed** (`OrganizationMembersReader` and `WorldsPage.filter` F8); both files then passed together in isolation (**44 tests**); full run 2 passed (**456 files, 5,938 tests**). The causes of both first-run failures remain unproven. CI is pending the checkpoint PR.

**Coordination.** No other slice or consumer was started. S02's recorded implementation prerequisites (S01 review and S03 records commit) are now met, but C08 remains blocked on independent S02 and S03 passes and the integrated requirements in S01 plan §12.4. This finding does not change S01's reviewed endpoint contract. No browser/AX, human or owner acceptance was performed or granted.

### 11.5 Correction of C08-S03-1 (Sonnet, 2026-11-24)

**Status: C08-S03-1 corrected, pending independent confirmation.** S03 is not passed; §11.4's CHANGES REQUIRED stays as the review history. Baseline `f327c13a1963d6e327d443e26168db70e05827af` (confirmed as HEAD and `origin/phase15/completion`; Luna's uncommitted §11.4 and register edits preserved in the records commit). Correction commit `12ca7ec0616243a027755f070a201f2f5cea3cc5`: `P15-C08-S03-T01: keep add-area input typed after submitting when the create succeeds (C08-S03-1)`. Re-review range: `f327c13a1963d6e327d443e26168db70e05827af..12ca7ec0616243a027755f070a201f2f5cea3cc5`, plus this records commit.

**Change.** `DungeonAreasSection.tsx` only (plus tests). The fields stay editable while the create is pending. Each field has an edit count (a ref bumped on every change, whatever the new value), and the submission snapshots the counts. On success a field is cleared only when its count is unchanged since the submission, so a value changed and changed back, or by whitespace only, counts as newer input and is kept. Focus returns to Area name as before, except when the focused element is a field that holds newer input. The submitted body, the retry identity, the announcement, the refusal paths and Done/reopen are untouched. No field is disabled; no backend, API, `useDungeonCommand` or `useAuthoringMutation` change.

**Regressions written first (held create, unfixed code).** New cases in the dungeon block of `WorldRecordWorkspace.test.tsx`, each holding the POST until released.
- **Failed before the fix (7):** E1 (Environment typed after submitting survives, keeps focus, other fields clear, one POST with the submitted snapshot), E2 for Name, Summary, Kind and Size (four cases: the newer value survives and the other four clear), E3 (a field edited away and back, and one changed by whitespace only, survive), E5 (newer input survives the success of a retry of an unknown outcome, same body and same `Idempotency-Key`). Each failed at `toHaveValue` with the newer value expected and the field empty.
- **Passed before the fix, kept as guards (2):** E4 (nothing typed after submitting: every field clears and focus returns to Area name) and E6 (a refusal after newer input keeps every value, the newer one included). The existing D4, D6, D8 and D10 are unchanged and pass.

**After the fix.** Dungeon block: 75 passed. Focused §7.1 set (4 files): 169 passed. `test_api_dungeon_authoring.py`: 18 passed. `npm run lint`, `npx tsc -b`, `npm run build`, `ruff format --check`, `ruff check`, `scripts/check_documentation.py` and `git diff --check` pass.

**Full portal run.** First run: **456 files, 5,947 tests passed, 0 failed** (no rerun needed). The earlier full runs (5,936 of 5,938 with two failures, then a clean 5,938) are recorded in §11.3 and are separate history; their causes remain unproven. No backend shard run (no backend change).

**Mutations (each restored byte-for-byte; SHA-256 `4d93d0acb986...` equal before and after).**

| Mutation | Failed cases |
|---|---|
| MA: clear every field unconditionally on success (the old behavior) | E1, E2 (Name, Summary, Kind, Size), E3, E5 |
| MB: always refocus Area name on success | E1 |

**CI position.** Pending the checkpoint PR; none opened. Not run: browser/AX, human review, owner acceptance, S02, consumers.

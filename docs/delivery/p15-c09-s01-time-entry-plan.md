# D/P15-C09-S01 implementation plan: use the existing time model in the entry dialog

Owner register rows: [P15-C09](work-register.md#p15-c09), [P15-C09-S01](work-register.md#p15-c09-s01), [P15-C09-S01-T01](work-register.md#p15-c09-s01-t01). Source finding: [R12 — Time entry and duration arithmetic](work-register.md#r12--time-entry-and-duration-arithmetic), part R12a only ("a specified interaction improvement using current inputs/picker/dialog"). Attached records: [pilot-time](work-register.md#pilot-time) (a later adoption consumer) and [duration-policy](work-register.md#duration-policy) (an unresolved owner policy; not in scope).

Prepared by Opus, 2026-11-25. **Plan only; T01 not started.**

- Starting SHA: `1c9cc3ac50132c6f854e5752c60e33154b595c55`, the reviewed C08 PR head, with a clean worktree.
- Plan-entry head: `fe560e7e0be5e6c6040d195782ed923d7f7ca6dc`, the C08 merge (PR #77), reached by fast-forward. Its tree equals `1c9cc3ac`'s; no history was rewritten.
- C08 merge bookkeeping is a separate documentation commit, `321f04132a2a1508a11b0484e38e00aa0445d3b9`, before this plan.
- The implementation baseline is the commit that adds this plan (reported in the handoff).
- CI: no run exists for C09.

## 1. Entry readiness and scope

- **C09 ("Improve record-time entry")** is admitted with no checkpoint prerequisite ("—"). Its criteria send the record-time pilot to [pilot-time](work-register.md#pilot-time), and actual keyboard and zoom to [ax](work-register.md#ax).
- **Structure.** C09 has one slice, S01 ("Use the existing time model in the entry dialog"), with one task, T01 ("Implement the specified picker interaction with dirty-close, focus return and receipt tests"). S01's only gate is the checkpoint entry criteria, which hold.
- **S01 criteria:**
  - "Creating a point preserves Now."
  - "Duration arithmetic has a separate owner decision."
- **Where the "specified interaction" comes from.** It is defined by the historical finding rows the register derives R12a from ([review-2026-11-11.md](review-2026-11-11.md), rows T01, T02 and T04):
  - T01: "Shared scoped input, explicit precision, no calendar coercion or implicit clock advance."
  - T02: "Pristine Cancel closes/returns; dirty Cancel guards; no write; focus restored."
  - T04: "Record-time dialog with dirty close/Cancel/Escape rules, focus return, saved receipt and fresh picker selection."
- **Already delivered.** T02 and T04's dialog behavior was delivered as the B1-3a and B1-3b pilots ([acceptance ledger](acceptance-ledger.md), 2026-11-01 rows). [pilot-time](work-register.md#pilot-time) is its later adoption and acceptance consumer, gated on "C09 merged". C09 therefore keeps that dialog behavior intact under tests, and repairs what T01's target still lacks (§2.3).
- **Not in scope:**
  - [duration-policy](work-register.md#duration-policy) and [duration-work](work-register.md#duration-work): R12b and R12c, an unresolved policy and later conditional work. Nothing in C09 adds elapsed-time arithmetic or relative-time entry.
  - The pilot's adoption and browser evidence ([pilot-time](work-register.md#pilot-time)).
- **Open reliability investigations.** These are on the C04, C06, C07 and C08 rows, including the C08 shard-5 caller-expiry failure. They are separate obligations, not C09 prerequisites, and nothing here depends on their causes.
- No owner decision blocks S01.

## 2. Verified current behavior (at `fe560e7`)

### 2.1 How time entry works today

- **Data.**
  - `GET /campaigns/{c}/world-times?limit=&cursor=` (`api/world_time.py`, `queries/world_time.py`) lists points latest first. Each item carries `calendar_id`, `year`, `month_number`, `day`, `hour`, `minute`, `label`, `precision` and `display`.
  - `display` is `domain/world_time.py` `display_text`. This is the label if there is one, otherwise "Year Y (Epoch), Month D". It takes **no hour, minute or calendar name**.
  - The server derives precision as follows:
    - `approximate` when that flag is sent;
    - `exact` when a day is given;
    - `partial` otherwise;
    - `narrative` for narrative points.
  - Creating a point never touches the campaign clock.
- **`WorldTimeForm`** (`components/authoring/WorldTimeForm.tsx`, with `utils/worldTimeForm.ts`).
  - **Calendar mode:** Calendar, Year, Month (a select of the chosen calendar's months), Day, Hour (0–23), Minute (0–59), "This date is approximate", and Label.
  - **Narrative mode:** "Describe this moment", "Comes after" and "Comes before (optional)". The after and before options are labelled with `display`.
  - **Validation** mirrors the domain rules.
  - **Precision is never shown;** the server derives it.
  - **Changing the calendar keeps every other value as typed.**
  - **Writes** go through `useAuthoringMutation`, scoped `create-world-time:{campaign}`. With `holdUnresolved`, a changed form re-sends an attempt whose outcome is unknown, with the same key and body.
- **`WorldTimePicker`** offers a `<select>` of the latest 100 points ("Showing the latest 100 times." when more exist), labelled with `display`. Its trigger, "Record a new time", opens `PickerRecordTime`, which provides:
  - the portalled `FormDialog`: Escape and Cancel rules, discard on a dirty close, and "Close and check later" for an unknown outcome;
  - focus return to the trigger;
  - its own navigation hold;
  - the announcement "World time recorded";
  - a kept-input message naming the recorded time by `display`.

  The picker chooses the recorded time only once the re-read list shows it.
- **`WorldTimesPage`** (`/app/:campaignId/world-times`) has its own "Record a time" dialog. Its list and its saved confirmation use a page-local `recordedTime(item)`: "Calendar name: Year Y (Epoch), Month D, HH:MM — label", with the precision in visually hidden text. The Campaign time card shows the server's full reading in the same form.
- **Tests:**
  - `WorldTimePicker.test.tsx` (39 tests);
  - `WorldTimesPage.dialog.test.tsx`, including "records once, closes, shows and announces it once, and never touches the clock";
  - `WorldTimesPage.test.tsx`, `FormDialog.test.tsx` and `utils/worldTimeForm.test.ts`;
  - caller integration tests in `CampaignClockCard.test.tsx`, `App.partyMembers.test.tsx`, `App.eventCorrections.test.tsx` and `App.sessionRun.test.tsx`.

### 2.2 Plan-entry reproduction results

A temporary copy of `WorldTimePicker.test.tsx` with one added case, plus a one-line call of `display_text`, ran once and was deleted. The fixture had two points on Year 3 Bloom 5, at 09:00 and 14:00, and two calendars: Common Reckoning with 2 months, and Short Count with 1 month.

| Case | Kind | Observation |
|---|---|---|
| Q1 | defect | The picker's options are `["Choose a time", "Year 3 (Founding), Bloom 5", "Year 3 (Founding), Bloom 5"]`: the two points cannot be told apart. `display_text(label=None, year=3, month_name="Bloom", day=5, epoch_label="Founding")` returns `'Year 3 (Founding), Bloom 5'`, so the server's `display` really omits the hour. |
| Q2 | defect | The open record dialog contains no precision wording (`/precision\|exact\|partial/` does not match). |
| Q3 | defect | With Common Reckoning, month 2 and day 20 entered, switching to Short Count leaves the Month select showing **"Not specified"** (DOM value `""`) while the form still holds month 2. There is no message before submitting. Submitting shows "Month must be a whole number from 1 to 1." twice, for a field that visibly has no month, and sends nothing. |

### 2.3 Deviations S01 repairs

- **DV-1 (T01 "shared scoped input"):** the picker and the form's after and before choices read points differently from the World times page and the Campaign time card. They drop the calendar name and clock time, so same-day points are indistinguishable (Q1).
- **DV-2 (T01 "explicit precision"):** a person cannot see what precision the point will be recorded with (Q2).
- **DV-3 (T01 "no calendar coercion"):** a calendar change leaves a hidden value that the visible field does not show. Validation then contradicts the screen (Q3).

### 2.4 Source-inspected risks (to be proven by cases below)

- The picker's kept-input message ("The time you submitted earlier was recorded: …") names the time by `display`, so the same ambiguity reaches the receipt (E11).
- A missing calendar for an item (a stale or partial calendar list) must not produce an invented reading (E15).

### 2.5 Behavior that must not regress (baseline-passing guards)

- **Dialog behavior (B1-3a/B1-3b):**
  - pristine and dirty close, Escape and Cancel, and discard confirmation;
  - pending and unknown outcomes, "Close and check later", reopen to retry with one key;
  - focus return to the trigger;
  - one announcement;
  - outer-form isolation;
  - navigation holds with and without a page guard;
  - campaign switch with late answers, and permission loss;
  - choosing the recorded time only once listed and unchanged.

  Covered by the existing picker and page dialog suites, unchanged except §6.2.
- **Now is preserved:** recording sends no clock request (`WorldTimesPage.dialog.test.tsx:224`) and no caller write (the caller integration tests).
- **Narrative points** keep their reading (`display`) everywhere.
- **The World times page** keeps its list and confirmation text exactly, including for a point whose calendar is not loaded ("Calendar: Year N, …"); it adopts the shared function with its page fallback (§11.5).

## 3. Outcome, scope and exclusions

### 3.1 User outcome

Wherever a person chooses or records a world time, each point reads the same way as on the World times page, with calendar, date, clock time and label, so points on the same day can be told apart. While entering a calendar date, the dialog says plainly how it will be recorded and with what precision. Changing the calendar never leaves a value hidden behind a field. Recording a point still never moves the campaign's Now.

### 3.2 In scope (T01)

- **Shared reading.** New `utils/worldTimeReading.ts` exports `worldTimeReading(item, calendars)`.
  - It is moved from `WorldTimesPage`'s `recordedTime` with identical output.
  - A narrative or calendar-less item gets `display`.
  - When the item's calendar is not in `calendars`, it gets `display`, followed by ", HH:MM" when `hour` is set. It never guesses a calendar or month name.
- **Users of the shared reading:**
  - `WorldTimesPage`: no visible change;
  - `WorldTimePicker` option labels, which use the picker's loaded calendars;
  - `WorldTimeForm`'s "Comes after" and "Comes before" options;
  - `PickerRecordTime`'s kept-input message.
- **Explicit precision.** In `utils/worldTimeForm.ts`, `calendarPrecision(values)` mirrors the server rule for display only: `approximate` when the box is checked, `exact` when a day is entered, otherwise `partial`.
  - In calendar mode, when the calendar fields validate, `WorldTimeForm` shows a plain paragraph associated with the fields, for example "Will be recorded as: Common Reckoning: Year 3 (Founding), Bloom 5, 14:00. Precision: exact (a specific day)."
  - The precision descriptions are:
    - "exact (a specific day)";
    - "partial (year or month only)";
    - "approximate (marked approximate)".
  - The paragraph is absent while the fields do not validate. It is not a live region, so it is read when reached and not announced on every keystroke.
  - Narrative mode shows nothing new.
  - The server remains authoritative; the saved point's own `precision` is what the list shows afterwards.
- **No hidden values on a calendar change.** When the calendar changes, the form keeps the month only if the new calendar has it, and keeps the day only if that month has it. Otherwise it clears the month (with day, hour and minute) or the day (with hour and minute).
  - A polite `role="status"` note says what was cleared, for example "Month and day were cleared: Short Count has no such month."
  - The values remain dirty for the close and leave guards.
  - Year, Approximate and Label are untouched.
  - No date is converted between calendars.
- **Documentation.** Update `docs/reference/portal-behavior.md`:
  - the World times row and the record-time picker description (the `events/new` row names `WorldTimePicker`): the shared reading, the precision line, and the calendar-change rule;
  - the time-display bullet.

### 3.3 Exclusions

- No backend, API, schema or domain change. In particular `display_text` and the list's `display` are unchanged: the C09 repair is portal-side, so other consumers of `display` keep their contract.
- No elapsed-duration entry, "how long before/after", month/year arithmetic or relative provenance (duration-policy and duration-work).
- No change to `FormDialog`, `ConfirmDialog`, `useAuthoringMutation`, `navigationHolds`, `useUnsavedChangesGuard`, the picker's selection rules or the announcement wording.
- No searchable or paged picker beyond the existing latest-100 list, and no calendar-aware hour model (the domain's 24-hour day stays).
- No change to callers of `WorldTimePicker`.
- The pilot's adoption, browser and AX evidence stay with [pilot-time](work-register.md#pilot-time) and [ax](work-register.md#ax).

## 4. Affected files and interfaces

| File | Change |
|---|---|
| `portal/src/utils/worldTimeReading.ts` (+ `worldTimeReading.test.ts`) | New shared reading |
| `portal/src/pages/WorldTimesPage.tsx` | Uses the shared reading; no behavior change |
| `portal/src/components/authoring/WorldTimePicker.tsx` | Option labels from the shared reading |
| `portal/src/components/authoring/PickerRecordTime.tsx` | Kept-input message from the shared reading |
| `portal/src/components/authoring/WorldTimeForm.tsx` | Anchor labels, precision line, calendar-change rule and note |
| `portal/src/utils/worldTimeForm.ts` (+ its test) | `calendarPrecision`, and a pure `onCalendarChange(values, calendars)` returning the next values and what was cleared |
| `portal/src/components/authoring/WorldTimeForm.test.tsx` (new) or additions to `WorldTimePicker.test.tsx` | E-cases |
| `docs/reference/portal-behavior.md` | §3.2 rows |

## 5. Task commit

One commit: `P15-C09-S01-T01: read times alike everywhere, show the recorded precision and never hide a value on a calendar change`. A records commit follows (docs only).

## 6. Acceptance cases

| Case | Behavior | Baseline |
|---|---|---|
| E1 | Picker options for two points on the same day read "Common Reckoning: Year 3 (Founding), Bloom 5, 09:00" and "…, 14:00", and are distinct. | fails |
| E2 | The form's "Comes after" and "Comes before" options use the same reading. | fails |
| E3 | Narrative points keep `display` in the picker, the form and the page. | guard |
| E4 | A labelled calendar point reads "Calendar: Year…, Month D, HH:MM — Label" in the picker, as on the World times page. | fails |
| E5 | `worldTimeReading` returns exactly the old page output for each kind of item: narrative, year only, month, day, clock, epoch and label. The World times page list and confirmation text are unchanged. | guard (page); the unit test is new and fails only because the module is absent |
| E6 | Calendar mode shows "Will be recorded as: … Precision: …" once the fields validate, updates as fields change, and is absent while invalid and in narrative mode. | fails |
| E7 | `calendarPrecision`: a day gives exact, no day gives partial, and approximate wins. It agrees with `calendar_precision` for the same inputs. | fails |
| E8 | A calendar change clears a month the new calendar lacks (with its day, hour and minute), clears a day the month lacks (with hour and minute), keeps valid values, shows the polite note, and leaves the visible fields equal to the form's values. | fails |
| E9 | After E8's change the dialog is still dirty: Escape asks "Discard this time?", and Keep editing keeps the values. | guard |
| E10 | Focus returns to "Record a new time" after a recorded point, after a discard and after a pristine close. | guard (existing coverage; rerun) |
| E11 | The picker's kept-input message names the recorded time by the shared reading, including its clock time. | fails |
| E12 | The World times page confirmation "World time recorded: <reading>" is unchanged. | guard |
| E13 | Recording from the page or a picker sends no clock request and no caller write, so Now is unchanged. | guard |
| E14 | The picker sends only its existing two reads (times and calendars) and no new request. | guard |
| E15 | An item whose calendar is not in the loaded list reads `display` plus ", HH:MM", with no invented calendar or month name. | fails |
| E16 | After E8, submitting sends exactly the visible values. The server receives no month that the chosen calendar lacks. | fails |
| E17 | An unknown outcome followed by a calendar change re-sends the earlier attempt first (same key and body), per the existing `holdUnresolved` rule. | guard |

"Fails" means the case fails at the baseline: record the test name and assertion. Guards are run at baseline and recorded as passing; they are not expected to fail first.

### 6.1 Mutation probes

| Probe | Mutation | Must fail |
|---|---|---|
| M1 | Picker options back to `display` | E1, E4 |
| M2 | Form anchors back to `display` | E2 |
| M3 | `calendarPrecision` ignores the approximate flag | E6, E7 |
| M4 | Do not clear values on a calendar change | E8, E16 |
| M5 | Clear every date field on any calendar change | E8 (valid values kept) |
| M6 | Kept-input message back to `display` | E11 |
| M7 | Invent the first calendar for an unknown `calendar_id` | E15 |

Revert each probe with exact bytes restored, and compare hashes (`git restore` rewrites LF working files as CRLF here).

### 6.2 Permitted changes to existing tests

- An expected option label or kept-input text for a **calendar-based** point in `WorldTimePicker.test.tsx` or a caller test may change from `display` to the shared reading. Record each changed test by name.
- `WorldTimesPage` tests take no change.

Any other changed expectation is a stop condition.

## 7. Verification

### 7.1 Per-commit checks (Sonnet; repeated by the reviewer)

From PowerShell in `C:\Users\nemes\dnd_ai\portal` (uppercase `C:`):
- **Focused run:**

  ```
  npx vitest run src/utils/worldTimeReading.test.ts src/utils/worldTimeForm.test.ts src/components/authoring/WorldTimePicker.test.tsx src/pages/WorldTimesPage.dialog.test.tsx src/pages/WorldTimesPage.test.tsx src/components/authoring/FormDialog.test.tsx src/components/CampaignClockCard.test.tsx src/App.partyMembers.test.tsx src/App.eventCorrections.test.tsx src/App.sessionRun.test.tsx
  ```

  Add the new form test file if created.
- **Full run:** `npm test`. Record the first run and any rerun separately, naming each failure. A failure matching an open investigation is recorded as such, with no claimed cause.
- `npm run lint`, `npx tsc -b`, `npm run build`.
- From the repository root: `uv run python scripts/check_documentation.py` and `git diff --check`.

No backend check is required. A backend change is a stop condition.

### 7.2 C09 checkpoint merge requirements

The C09 PR merges only when all of these hold (register sequencing rules):
1. S01 (C09's only slice) has passed independent review, with any correction confirmed.
2. E1–E17 pass on the integration head, with one full portal run on its executable code. A run may be reused when no executable or test file changed after it.
3. CI passes on the exact integration head.

No backend full run is required, because C09 changes no backend file.

### 7.3 Separate events (after the merge; not merge gates)

- [pilot-time](work-register.md#pilot-time): adoption of the record-time dialog behavior, with dirty-close, focus, receipt and fresh-picker browser evidence.
- [ax](work-register.md#ax): actual keyboard, screen reader, 320 CSS px, and 200% and 400% zoom for the dialog, the precision line and the calendar-change note.
- Human review, [p15-integration](work-register.md#p15-integration) and `p15-owner`. Nothing here grants them.

## 8. Authorization, disclosure, isolation, outcomes and focus

- **Server-authoritative.**
  - Every option comes from the campaign's own list and calendar reads.
  - The precision line is a preview; the saved point's server `precision` is authoritative.
  - Validation stays duplicated client and server, with the server deciding.
- **Disclosure.** The reading uses only fields already in the list response the caller is entitled to. No new field or request is introduced.
- **Isolation and late answers.**
  - The picker stays keyed by campaign, so a different campaign never inherits options, drafts or answers (existing).
  - Calendars and times come from the same campaign's reads.
- **Drafts and navigation.** Dirty tracking, close confirmation and navigation holds are unchanged. A calendar-change clearing is a form edit like any other (E9).
- **Retry identity and unknown outcomes.** These are unchanged: the same body re-sent reuses its key, a changed body during an unknown outcome re-sends the earlier attempt first (E17), and a confirmed time is never recorded twice.
- **Refusals and reconciliation.**
  - Server refusals keep their existing messages.
  - After a confirmed write the list is re-read; a failed read leaves the existing read-only notice and never repeats the write.
- **Focus and announcements.**
  - Focus behavior is unchanged (E10).
  - The calendar-change note is one polite status message.
  - The precision line is static text, not announced.
  - The success announcement is unchanged.

## 9. Intermediate states

T01 is a single commit and C09's only task, so no intermediate state is merged.

## 10. Decisions

**No owner decision is required.** Routine choices made here:

- **R-1 (portal-side reading, server `display` unchanged).** The page and the Campaign time card already use the full reading. Changing `display` would alter every other consumer's contract.
- **R-2 (no precision words in option labels).** Labels stay short and match the page's visible text. Precision is made explicit where a point is being recorded.
- **R-3 (clear only values the new calendar lacks, and say so).** This is explicit and visible, never converted, and nothing valid is lost. It is preferred over keeping hidden values (the defect) or clearing everything.
- **R-4 (precision line not live).** This avoids an announcement on every keystroke. It is read with the fields.
- **R-5 (fallback reading for an unknown calendar, interaction readings only).** Use `display` plus the clock time, with no guessed names, in the picker, the form's choices and the kept-input message. The World times page keeps its existing visible text for this case (§11.5).
- **R-6 (announcement wording unchanged).** The receipt carries the reading through the selected option and the kept-input message, and existing announcement expectations stay valid.

## 11. Handoffs

### 11.1 Sonnet implementation instructions

1. Confirm that the baseline (the commit adding this plan, given in the prompt) is HEAD and `origin/phase15/completion`, with a clean worktree.
2. Read §1 to §10. Write the "fails" cases first and run them on the baseline. Record each failure (test name and assertion). Run the guards and record that they pass.
3. Implement §3.2 in the files of §4 only, with only §6.2's adaptations.
4. Run §7.1. Run M1–M7 and revert each with exact bytes restored.
5. **Stop and report instead of continuing if:**
   - a backend, API, domain or `display_text` change seems necessary;
   - a change to `FormDialog`, `ConfirmDialog`, `useAuthoringMutation`, `navigationHolds`, `useUnsavedChangesGuard`, the picker's selection rules or any picker caller seems necessary;
   - the World times page's visible text would change;
   - an existing expectation outside §6.2 would change;
   - a "fails" case cannot be made to fail at the baseline;
   - duration or relative-time behavior appears necessary.
6. Commit with the §5 subject and push. Record the following in §11.3 and the register's S01-T01 row, then commit and push the records:
   - the SHA;
   - the test-first failures and guards;
   - the focused and full runs (first run and rerun separately);
   - the probes;
   - the CI position: "pending checkpoint PR".
7. Do not open, mark ready or merge a PR. Do not run browser or AX checks, start pilot-time or other consumers, or record any acceptance.

### 11.2 Independent review boundary

- **T01 = combined S01 = C09:** from the plan commit to the implementation commit, plus its records commit.
- Review against §2.5, §3, §6 and §8, and re-run §7.1 and M1–M7.
- A pass is a slice verdict only. §7.2 and §7.3 remain.

### 11.3 Implementation record

Implemented by Sonnet 5.5, 2026-11-25. Baseline `61dbc2d428e2974726053464b98093c8164c0215` (HEAD and `origin/phase15/completion`, clean worktree). Implementation commit `82027ac5e9852ad3146d3983085bb044a2d7ae73`, pushed. Independent review range: `61dbc2d4..82027ac5e9852ad3146d3983085bb044a2d7ae73` plus this records commit. CI position: pending checkpoint PR (no PR opened).

**Test-first failures at the baseline** (11 failures in 4 files, run before any production change; the new reading module was absent):
- E5/E15 `utils/worldTimeReading.test.ts`: the suite failed to load ("Failed to resolve import ./worldTimeReading").
- E7 `worldTimeForm.test.ts > calendarPrecision`: `calendarPrecision is not a function`; E8 `onCalendarChange` (3 tests): `onCalendarChange is not a function`.
- E2 `WorldTimeForm.test.tsx`: the after-option labels were the server display text, not the shared reading; E6: "Will be recorded as: …" text not found; E8/E16 (2 tests): after a calendar change the Month select/Day/Hour/Minute kept their values (`toHaveValue` mismatch).
- E1/E4 and E15 (`WorldTimePicker.reading.test.tsx`): option labels equalled `display`, not the reading; E11: kept-input message not found (it named the time by `display`).
**Guards at the baseline** (existing suites, unchanged): `WorldTimePicker`, `WorldTimesPage.dialog`, `WorldTimesPage`, `FormDialog`, `CampaignClockCard`, `App.partyMembers`, `App.eventCorrections`, `App.sessionRun`: 8 files, 229 passed. E3, E9, E12, E13, E14 and E10 are covered by these suites and by the new tests E3 (form narrative option), E9 and E14 (`WorldTimePicker.reading.test.tsx`); E17 by the existing `holdUnresolved` tests.

**Implementation (§3.2).** New `utils/worldTimeReading.ts` (moved from the page's `recordedTime`); used by `WorldTimesPage`, the picker options, the form's after/before options and the kept-input message. `calendarPrecision`, `PRECISION_DESCRIPTIONS` and `onCalendarChange` in `utils/worldTimeForm.ts`; the "Will be recorded as … Precision: …" paragraph (plain text, not a live region) and the polite `role="status"` calendar-change note in `WorldTimeForm`. `portal-behavior.md` updated (World times/picker row, time-display bullet). No backend, `display_text`, dialog, mutation, guard or selection change.

**Changes to existing tests.** §6.2 required none: every existing picker/caller fixture uses narrative points, so no expectation changed. **One change outside §6.2, reported for review:** `RelationshipsPanel.test.tsx` line 162 mocked the calendars read as `{ items: [], can_create: true }`, which is not the API's shape (`{ calendars }`); the picker now reads `calendars.calendars`, so that mock crashed the picker. The mock was corrected to `{ calendars: [] }`; no expectation changed. **Behavior difference to review:** the old page `recordedTime` printed the literal word "Calendar" when an item's calendar was not in the loaded list; the plan (§3.2, R-5) specifies `display` plus the clock time instead, and no World times test covered the old case.

**Runs.** Focused §7.1 set plus the three new files: 12 files, 251 passed. `npm run lint`, `npx tsc -b`, `npm run build` exit 0. Documentation check and `git diff --check` pass. **Full `npm test`, run 1: 1 failed**, 460 files passed (5,986 passed of 5,987): `RelationshipsPanel.test.tsx > ends a relationship with the version it saw, and asks for a time first` ("Unexpected Application Error": `worldTimeReading` read `.find` of undefined from the mis-shaped mock above; it failed the same way alone). After the mock correction, **rerun (full): 461 files, 5,987 passed, 0 failed.**

**Mutation probes** (each applied to one file, run against the four new test files, then exact bytes restored with the hash compared equal): M1 failed E1/E4 (and E15); M2 failed E2; M3 failed E6 and E7; M4 failed both E8/E16 form tests; M5 failed the E8 form and unit tests (valid values kept); M6 failed E11; M7 failed E15 (picker and unit).

**Not done / pending:** no PR, browser/AX, zoom, pilot-time or acceptance; independent review pending.

### 11.4 Independent review of T01/S01 (Codex, 2026-11-25)

**Verdict: T01/S01 CHANGES REQUIRED.** The principal interaction is supported by the implementation and focused evidence, but one explicit implementation boundary is violated: the World times page's visible fallback text changes when an item's calendar is not in the loaded list. This condition is uncommon and the impact is bounded, but §2.5 and §11.1 explicitly require the page's visible text to remain unchanged and direct the implementer to stop if it would change. This therefore prevents this slice from passing until corrected or the governing scope is explicitly amended by the owner. No acceptance or CI is implied.

**Finding C09-S01-1 — World times page fallback text changes (score 3, Low; application/contract).** In `portal/src/pages/WorldTimesPage.tsx`, the old page-local formatter returned a reading beginning `Calendar:` when `calendar_id` was non-null but its calendar was missing. The shared `worldTimeReading` now follows R-5 and returns `display` plus clock time instead. Thus an item with an unavailable calendar visibly changes on the World times page, contrary to §2.5 (“keeps its list and confirmation text exactly”) and the stop condition in §11.1. Score: supported-path exposure 1 (a page reader encountering a stale/partial calendar list); impact 1 (bounded reading-text difference); triggerability 1 (requires that uncommon missing-calendar state); detection/recovery 0 (visible and recoverable); blast radius 0 (one reading). Total 3, Low. **Readiness:** blocks this slice because the explicit page-text contract is unmet, despite the low product severity. **Bounded correction:** keep the shared formatter's R-5 fallback for picker, form and receipt, while preserving the prior `Calendar:` fallback specifically for the World times page (for example, an explicit page fallback mode/helper); add a regression that exercises a missing calendar on that page and checks both list and confirmation. Re-run the focused page and formatter tests plus lint/typecheck/build and docs/diff checks. An owner may instead amend the explicit no-visible-change contract, but R-5 alone does not silently waive it.

**Separate plan inconsistency (not a second product finding).** §3.2/R-5 explicitly specifies the new unknown-calendar fallback, while §2.5 and §11.1 prohibit any visible World times page text change. These instructions conflict for the page's missing-calendar case. The implementation record disclosed the consequence; this review does not treat that disclosure as authorization. Resolve the contract through the bounded correction above or an explicit owner decision, then align the plan text.

**Fixture scope deviation — accepted.** `RelationshipsPanel.test.tsx` changes only the calendars mock from `{ items: [], can_create: true }` to `{ calendars: [] }`. `CalendarListResponse` declares `calendars: Calendar[]`, and the application consumes `calendars.calendars`; the old shape was invalid and caused the first full run's picker crash. The correction changes no expectation and repairs the fixture to the API contract. This is a narrow, justified test-harness deviation from §6.2, not a product finding. Keep the first full-run failure and the passing rerun distinct as recorded in §11.3.

**Other criteria and evidence.** The inspected implementation derives `exact` from a day, `partial` without one, and `approximate` with the flag, matching `src/dnd_ai/domain/world_time.py::calendar_precision`. The calendar-change helper retains only supported month/day values and clears dependent day/hour/minute fields; its status text is generated from the values cleared. Missing-calendar readings do not guess names. The formatter extraction preserves the old output for loaded calendar points, narrative points, and normal page readings. Dialog close/focus, receipt and announcement, held retry identity, picker selection/read count, and Now behavior are unchanged by the implementation diff and covered by the recorded guards; the reviewer focused run also reran those guard suites.

**Independent verification.** Ancestry verified: baseline `61dbc2d428e2974726053464b98093c8164c0215` → implementation `82027ac5e9852ad3146d3983085bb044a2d7ae73` → records/current HEAD `7ad49ab8231499d4716eb2f1748a416013073994`. Branch `phase15/completion`; worktree was clean before these review edits. Implementation changes are limited to the recorded 12 portal/reference files, including the disclosed one-line fixture correction; records changes are limited to this plan and the owning register. The focused §7.1 set plus all new tests passed: 12 files, 251 tests. `npm run lint`, `npx tsc -b`, `npm run build`, `uv run python scripts/check_documentation.py`, and `git diff --check` passed. Build emitted only its existing large-chunk advisory. No full suite was repeated. M1–M7 and the separate full-run history are implementer evidence recorded in §11.3, not independently repeated here. CI remains pending the checkpoint PR; no browser/AX, pilot-time, consumer work or acceptance was performed.

### 11.5 Correction of C09-S01-1 (Sonnet 5.5, 2026-11-25): corrected, pending independent confirmation

Luna's review (§11.4, CHANGES REQUIRED) is kept as history. S01 is **not** marked passed. Baseline `7ad49ab8231499d4716eb2f1748a416013073994`; correction commit `7bf14b492c673d0dda4db801f6ddbbdccc9b7f98` (pushed); this records commit follows. **Luna's re-review range: `7ad49ab8..7bf14b49` plus the records commit.** CI: pending checkpoint PR.

**Plan wording clarified.** R-5 (display text plus clock time for a point whose calendar is not loaded) applies to **interaction readings only**: the picker options, the form's after/before choices and the kept-input message. The World times page keeps its pre-extraction visible text for that case (§2.5, §11.1): its list and its saved confirmation read "Calendar: Year N, HH:MM — label" (no epoch label and no month name, because the calendar is not known). §3.2's "identical output" for the page therefore includes this case.

**Test first.** `pages/WorldTimesPage.missingCalendar.test.tsx` (new; no existing page test changed) was run at `7ad49ab8` before any change and failed both tests: the list entry read "Year 3 (Founding), Bloom 5, 14:30 (ex…" where `^Calendar: Year 3, 14:30 — The feast` was expected, and the saved confirmation "World time recorded: Calendar: Year 3, 14:30 — The feast" was not found (8 s wait). It also asserts that a point with a loaded calendar reads in full on the same page.

**Correction.** `worldTimeReading(item, calendars, { pageFallback?: boolean })` gains a small explicit option. With it, a missing calendar continues through the original formatting (name "Calendar", no epoch, no month name, clock and label kept) instead of returning the display fallback. `WorldTimesPage` passes `pageFallback: true`; the picker, form and receipt pass nothing and keep the R-5 fallback. Normal calendar and narrative readings are unchanged. The formatter is not duplicated. `worldTimeReading.test.ts` gains a unit test of both modes; the existing interaction-fallback tests (E15 and the picker/form/receipt cases) are unchanged guards and pass.

**Verification.** Focused §7.1 set plus the new tests: 13 files, 254 passed. `npm run lint`, `npx tsc -b`, `npm run build` exit 0; documentation check and `git diff --check` pass. **Mutation MC1** (the page's call without `pageFallback`): both page regression tests failed; exact bytes restored, hash equal. **Full `npm test`, run 1: 2 failed** (460 of 462 files passed; 5,988 of 5,990): `App.knowledgeClaim.test.tsx > … a confirmed save whose authoring read-back fails (DEF-006) > says the save went through, keeps the editor, holds Save, and recovers by reading only` and `CampaignRevealAuthorityPage.write.test.tsx > … M9: reveal_delegation_recipient_not_gm re-reads, closes the dialog and says nothing was changed`; no cause claimed. **Isolated:** those two files together, 173 passed. **Rerun (full): 462 files, 5,990 passed, 0 failed.** The earlier accepted `RelationshipsPanel.test.tsx` fixture correction is kept. No backend, server display, duration, dialog, mutation, guard or picker-selection change.

### 11.6 Independent re-review of C09-S01-1 and T01/S01 (Codex, 2026-11-25)

**Verdict: C09-S01-1 CORRECTED. T01/S01: PASS WITH VERIFICATION LIMITS.** The original finding and score remain in §11.4 as history. The explicit formatter mode and tests now satisfy both the page's unchanged-text contract and R-5's interaction-reading fallback without adding a second formatter. This is a task/slice review only, not C09 acceptance or CI.

**Direct comparison with the pre-extraction page.** I compared the original `recordedTime` in `WorldTimesPage.tsx` at the pre-extraction implementation (`82027ac5^`) with the correction. For a non-null `calendar_id` absent from the loaded calendars, that code produced `Calendar: Year 3, 14:30 — The feast`: no epoch label, no month name, clock time and label retained. The corrected page calls `worldTimeReading(..., { pageFallback: true })`; when the calendar is missing it follows the same shared formatting path and yields that exact text. The new page tests assert the list reading and the saved confirmation reading, and verify a loaded-calendar point still receives the full calendar/epoch/month reading. They failed at correction baseline `7ad49ab8` before the implementation change: list expected the original `Calendar:` text but got the display fallback, and the confirmation expectation was absent.

**Fallback boundary and no duplicated formatter.** `pageFallback` is an explicit optional mode on the shared `worldTimeReading` function. It only affects the missing-calendar branch. The World times page opts in; picker options, form ordering choices and kept-input receipt use the default and retain `display` plus clock time, without guessed calendar or month names. The formatter remains centralized. Unit coverage checks both modes, the normal loaded-calendar output, and narrative `display`; these behaviors are unchanged. The fallback distinction is bounded to presentation and does not add requests or data.

**Other behavior review.** The correction diff changes only the page's formatter call, the shared formatter's option and missing-calendar branch, and page/formatter tests. It does not touch precision derivation, calendar-change clearing, dialog/focus behavior, mutation or retry identity, picker selection, or Now. Those behaviors remain supported by the earlier E1–E17 review and its focused guards; the correction focused run repeated those suites. No concern requires a temporary probe.

**Rubric and finding disposition.** C09-S01-1 retains its original 3 Low score (exposure 1, impact 1, triggerability 1, detection/recovery 0, blast 0) as historical evidence; the score describes the corrected behavior's prior bounded presentation difference, not a remaining defect. Its readiness disposition is now corrected: the page contract is met. No new finding is established.

**Independent verification and run history.** Verified ancestry: baseline `7ad49ab8231499d4716eb2f1748a416013073994` → correction `7bf14b492c673d0dda4db801f6ddbbdccc9b7f98` → records/current `2738cfbb56d87d79b8037958637f188cbe17a9ef`, on `phase15/completion`. The worktree was clean before this review's documentation edits. Correction scope is four portal files; records scope is this plan and the register. Reviewer focused plan set plus new tests: 13 files, 254 passed. Documentation check and `git diff --check` passed. Correction implementation evidence remains distinct: full run 1 had two failures (`App.knowledgeClaim` and `CampaignRevealAuthorityPage.write` M9), causes unproven; those files passed 173 tests in isolation; separate full rerun passed 462 files/5,990 tests. Earlier implementation run history remains in §§11.3–11.4 and is not replaced by these runs. No full suite was repeated by the reviewer. CI remains pending the checkpoint PR.

**Remaining requirements.** The correction clears the independent-review gate and the recorded E1–E17/full-portal evidence is available on the correction's executable code. C09 still requires CI passing on the exact integration/PR head under §7.2. Browser/AX, zoom, pilot-time adoption, human review and owner acceptance remain separate later events; none is granted here. No pilot-time or consumer work was started.

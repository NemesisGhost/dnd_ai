# Phase 15 — DEF-001 browser retest on the reviewed candidate (CP-11, scripted)

Run 2026-10-26 (evidence folder `retest_20261027`, UTC date of the first run). **This records scripted real-browser evidence only. Every human acceptance row stays `Unexecuted`; DEF-001, CP-11 and Phase 15 are not closed, and the candidate is not frozen** (two new defects below). No secret, cookie, token or credential appears here.

## 1. What was tested, and on what

| Item | Value |
|---|---|
| Branch / code | `phase15/completion` @ `38d2865ff9889f5a1f68f19315b79a088c3ea97d` (the Codex-reviewed candidate; working tree clean, equal to `origin/phase15/completion`). Product code did not advance past the reviewed candidate, so the review applies unchanged |
| Code review / CI (recorded separately from browser results) | Codex: no confirmed defects in the preparation/DEF-001 code. CI run [40422430588](https://github.com/NemesisGhost/dnd_ai/actions/runs/40422430588) on this head. Neither is a browser result |
| Schema revision | `140_clock_advance_details` (restored from the accounts-only baseline dump; no migration run) |
| Database | Disposable `dnd_ai_m1415_retest_20261027`, created with `createdb` + `pg_restore` of `accept_clean_baseline_140.dump`; table fingerprint identical to the baseline at the start (219 tables, 567 rows). Left in place, not dropped |
| Stack | API `127.0.0.1:8002`, Vite `127.0.0.1:5175` from the main checkout at `38d2865`, origin `http://127.0.0.1:5175` only. **Stopped** after the run |
| Browser | Chrome 155.0.8059.85 headless driven by playwright-core 1.49.1 |
| Personas | `admin` (world Owner, campaign owner and GM); `gm` (world **Editor and Reviewer**, given through World Sharing by `admin`, campaign `gm` role); `player_a` (sign-in and one negative check only). No account authority was changed, no password reset or Platform-accounts action was used |
| Credentials | Passwords reached the browser only through the child environment (`tools/envrun.py`) into the sign-in request body; never printed or stored |
| Protected state | The human database `dnd_ai_m1415_accept_clean_20261026` fingerprint is **identical** before the run, after it, and after its stack started (219 tables / 567 rows); working `dnd_ai` and ports 8000/5173 were never touched |
| Fault injection | `page.route` on `/api/**`. A write is passed to the real server; the rule that breaks the following read is armed **only after a 2xx write answer**, so a failed read is never confused with a failed write. Variants: read fails (5xx), read held then released (superseded), authoritative 403, lost answer (server applies the write, the page never hears — RC-03) |
| Assertions | one confirmed write (counted from the recorded requests); the saved-but-behind notice; no "done" in the live-region **history** (a MutationObserver records every announcement, so a transient one is not missed); the write control held where the version could be stale; recovery by a read-only action; the right state afterwards; announcement after the read; no second write |

## 2. Results by item

`PASS`/`FAIL` are counts of recorded checks in the final run of each script. Files are in the evidence folder (`<script>.json`, `logs/`, `shots/`).

| Script | Covers | Result |
|---|---|---|
| `ga` | ops 1, 2 | 14 pass, **1 expected fail = DEF-005 reproduction** |
| `gb` | op 11 | 12 pass, 2 fail — both are **script counting artifacts** (the page's write counter accumulated three intentional writes: 1, 2, 3); each intentional write was a single POST (§5) |
| `gc2`, `gc3` | ops 3–9 | 14 pass |
| `gd` | ops 10, 16, 25, 26 | 10 pass |
| `ge` / `ge2` | ops 12, 14, 15 / 13, 17, 18 | 6 pass (+ 1 earlier script fault on op 13, rerun in `ge2`) / 6 pass |
| `gf` / `gf2` | ops 19, 20 | op 19 pass; op 20 pass in `gf2` (earlier retry-button selector fault) |
| `gg` / `gg2` | op 21 | 3 pass |
| `gh` | op 22 (World record) incl. Reviewer verification | 8 pass |
| `gi`, `gj` | ops 24, 23 | 4 + 4 pass |
| `gk` | RC-03 | 3 pass |
| `gl` | RC-04, RC-05, RC-06, RC-07 | 12 pass, **1 recorded fail = DEF-006** |
| `go` | RC-08, RC-09, permission loss | 7 pass |
| `gn`, `gn2` | scripted C1, D1, D2 | 12 pass, 1 script fault (hidden `<option>` matched first), rerun in `gn2`: 2 pass |

### 2.1 Scripted C1, D1, D2 and the Reviewer role

Run on a **new** world in the disposable database (the earlier world already existed). C1: the New world form creates the world and its primary timeline in one request; reload shows both; `gm` cannot see it. D1: Sharing shows Administrator as the only row, Owner, "No one has been given this permission"; Transfer ownership was not submitted; `gm` is refused on `/sharing`. D2: `gm` given Editor then Reviewer through the page ("Role assigned" each time); the table shows both; `gm` then lists the world with no Edit / Sharing / Transfer actions; `/edit`, `/sharing`, `/calendars/new` give no usable form; `/timelines/new` shows the form (not saved); `/worlds/new` gives no usable form; `player_a` still sees no world. **Reviewer is verified explicitly (not only Editor):** in `gh` the Game Master, holding both roles, was offered and used Submit for review, Approve (with the record read failing, recovered read-only) and Publish; the record reached canon.

## 3. Evidence map: the 26 operations (DEF-001 inventory §4.1)

Each row names what a browser check actually exercised. **Not every command or variant of every operation was run**; the right-hand column is the remaining coverage. Nothing here claims all 26 are verified from one example.

| # | Operation | Browser evidence (confirmed write + failed/superseded read) | Remaining coverage (not exercised in a browser) |
|---|---|---|---|
| 1 | World archive / restore | archive with the read failing; recovery; restore after a reload (`ga`) | restore recovered in place hits DEF-005 |
| 2 | Timeline archive / restore | both directions (`ga`) | — |
| 3 | Party archive / restore | archive (`gc3`) | party **restore** |
| 4 | Party member end | `gc3` | — |
| 5 | Party member add | `gc3`; RC-03 lost answer then Retry with the same body and key, one membership (`gk`) | — |
| 6 | NPC portrayal save | `gc3` | — |
| 7 | NPC detail level | `gc2` | — |
| 8 | Character starting state | `gc2` | — |
| 9 | Activate a build | `gc2` | — |
| 10 | Event void / correct | void with the event read failing; void with only the preview read failing (`gd`) | event **correct** |
| 11 | World Sharing | assign role (Editor) read failing; assign (Reviewer) read held then released; authoritative 403 read-back removes content, write still announced, focus on the heading (`gb`) | end role, grant/revoke use; **transfer ownership is Blocked** (needs a second system-GM account; account authority may not be changed) |
| 12 | Session start | `ge` | — |
| 13 | Session end | `ge2` | — |
| 14 | Session log entry | `ge` | — |
| 15 | Travel | `ge` | superseded variant |
| 16 | Campaign clock advance | `gd` | clock **correct** |
| 17 | Session details save | `ge2` | — |
| 18 | Session archive / restore | archive, Load latest, Restore offered (`ge2`) | — |
| 19 | Encounter commands | start; record turn (`gf`) | update, participant add/change/remove, abort, end |
| 20 | NPC runtime | hit points (`gf2`) | conditions, resources, move |
| 21 | Dungeon / area commands | add area (`gg`); Area now record hazard state, reopening the editor does not lift the hold (`gg2`) | Connections, Contents |
| 22 | Lifecycle steps | World record submit (lifecycle read fails) and Reviewer approve (record read fails) and publish (`gh`); Quest submit, Item submit (`gl`); Claim submit (own notice, `gl`) | reject/return/archive/restore steps; Claim recovery is read-only retry |
| 23 | Relationship add / edit | add, edit (`gj`) | end, archive, perspectives |
| 24 | Organization | set status, add member (`gi`) | member editor |
| 25 | World time (inline picker) | `gd` | other host forms (party, session, clock, event, organization) use the same picker |
| 26 | World times page | `gd` | — |

## 4. RC rows

| Row | Result (scripted, `38d2865`) |
|---|---|
| RC-03 | PASS (`gk`): the lost answer shows "cannot tell whether this was saved", input kept; Retry sends the same body and `Idempotency-Key`; exactly one membership |
| RC-04 | PASS (`gl`): Quest details save and Quest submit. Details recovery is the page's Try again (no announcement of "saved" at recovery, by the CP-10 design); the lifecycle's Try again is on the Publication tab |
| RC-05 | PASS (`gl`): Item definition edit; Item submit (the Item lifecycle has no in-page retry by design: "Reload the page"; a reload restores the Approve step with no second POST) |
| RC-06 | PASS for the detail-read variant (`gl`). **FAIL for the authoring-read variant — DEF-006** |
| RC-07 | PASS (`gl`): Claim submit with the lifecycle read failing |
| RC-08 | PASS (`go`): after the read-only recovery the next save carries `expected_row_version` 1 → 2 and a new key, and is accepted |
| RC-09 | PASS (`go`): an unsaved Planning-notes draft is kept through a details save that is behind and through the recovery; a held read for record A returning after navigating to record B does not change B's page; **permission loss** — a 403 read-back on the Quest page replaces it with "Quest unavailable" and the private Planning notes are gone from the DOM (no "saved" announced). Not exercised: network throttling to Slow 3G (the script holds and releases the read instead) |
| RC-10 | Covered operation by operation in §3 |

## 5. Script faults corrected (not product defects)

Cumulative per-page write counts; loose or hidden-element selectors (`getByRole` strict mode, a hidden `<option>` matched first, ambiguous Description fields, a duplicate "Spike trap"); a stale fixture (an archived party, a quest already in review); a wrong role option value (`world_editor`, `world_reviewer`); asserting that a page retry announces when the design announces only on a good first read; the Review tab's retry living on Publication. **No expectation was weakened to hide a product failure**; the two product failures below are recorded as failures.

## 6. Defects found

See the register: **DEF-005** (a second confirmed write in one mounted view loses its saved-but-behind notice after the first was recovered by the page retry; reproduced in `ga`) and **DEF-006** (Claim save whose authoring read fails: the editor is replaced silently, with no notice, retry or announcement; `logs/ex5_auth.log`, `shots/ex5_auth.png`). Neither shows a premature "done", a repeated write or a stale-version write; both are explanation and recovery gaps. The candidate is therefore **not frozen**.

## 7. Limits of this evidence

* The announcement assertion records the live-region history. `ga` was rerun with it in its final form; earlier groups (`gb`–`gg`) were written while that helper was being strengthened, and their JSON does not record which form ran. Treat their "no premature done" checks as the weaker, text-at-the-time assertion unless rerun.
* Chrome only, headless, one viewport (1280 × 900). Responsive, keyboard-only and screen-reader behaviour is **not** covered (TC-55, the NV and AX rows stay Unexecuted).
* TC-38 positive resource, TC-31 deprecated claim, TC-41 attunement limit and SR-M14 stay Blocked as before; ownership transfer in the browser is Blocked as above.
* Backend and database suites were not rerun (no backend change since `9ab549d`).

## 8. DEF-005 / DEF-006 fixes and the required retest (added after the owner chose to fix)

The owner chose to **fix** DEF-005 and DEF-006 (not accept them). The fixes are portal-only and are in the commit after `38d2865`; see the register for cause and fix. **Neither the code review nor the browser retest below has happened; the new head is not a manual-run candidate and nothing here is frozen.** Results in §2–§4 remain the record for `38d2865` and are not carried to the new head.

### 8.1 Retest plan on the Codex-reviewed new head (disposable database only)

1. Reproduce and verify both defects in a real browser: `ga` "DEF-005 repro" must now pass; `ex5.mjs auth` and `gl` RC-06 authoring variant must show the notice, the held Save and a read-only recovery; add a 403 variant (private editor removed, status announced).
2. Rerun `ga`–`gg` with the final history-based announcement assertions (the earlier groups used a weaker text-at-the-time check, §7), on fresh fixtures.
3. Confirm per intended write: one mutation, the saved-but-behind status, the right gating, read-only recovery, no premature completion.
4. Reassess RC-03 … RC-10 on the reviewed head. Operations or variants not exercised stay explicitly unverified (§3); shared-hook coverage is not counted as verification of an operation.
5. Ownership transfer (op 11, Blocked at `38d2865`): a supported workflow exists. On a **disposable copy** only, the administrator can give an existing account (for example `gm` or `player_b`) the Game Master **system** role through Platform accounts → system roles (`system_roles.assign`). If that works there, transfer ownership with "Keep me on the world as" Editor, and test the confirmed-write/failed-read variants of the transfer, end role and grant/revoke use. Never in the human baseline or the working `dnd_ai`.
6. Sign-in is throttled to 10 per 15 minutes per account: batch the scripts and create personas lazily.

### 8.2 Codex review of `caa6589`: two confirmed findings, fixed in the next commit

| Finding | Confirmed fix | Remaining browser variants (unverified until run) |
|---|---|---|
| DEF-006: `claimDirty` used the live authoring state, so an edit on the retained editor was not "unsaved" and leaving was not guarded | The page's dirty calculation uses the kept authoring view; denied/missing still drops it and clears the draft. Save stays held while stale | Save with the authoring read failing, edit, Load latest fails again, follow a navigation link (dialog appears, Keep editing keeps the text); the same with 403 and 404 on the authoring read (editor and draft gone, leaving not guarded) |
| DEF-005: the recovery effect called the caller's `reset()`, which could clear a newer pending/confirmed write or newer unread state | No cleanup effect. Each write has its own status object; recovery is recorded against it; Load latest and `end()` / `reset(expected)` act only on the episode they were started for | The archive → page Try again → restore → page Try again sequence (`ga`), the same two-write sequence on ops 2, 22 (provider), 24, 26, Load latest followed by a further write, and a double press while pending, each checking one POST per intended write |

Not changed: the retest plan in §8.1, the 38d2865 results, and every human row (all `Unexecuted`). The head after this fix is not a manual-run candidate and no baseline is frozen.

## 9. Browser retest on the reviewed head `88ee96a` (run 2026-10-26/27, scripted, disposable copy)

Everything above this section is the record for `38d2865` and is kept under that SHA. This section is the retest of the fixes reviewed by Codex. **Scripted browser evidence only. Every human and accessibility row stays `Unexecuted`; DEF-001, CP-11 and Phase 15 are not closed; no manual-run baseline is frozen or proposed here** (§9.6).

### 9.1 What was run

| Item | Value |
|---|---|
| Code | `phase15/completion` @ `88ee96a32a10f5c689c5e8647dbe026f5c9be3d4` (Codex-reviewed fixes for DEF-005/DEF-006; CI run 40444946370 green on this head, recorded separately). Working tree: only the owner's three unstaged acceptance documents differ |
| Disposable database | `dnd_ai_m1415_retest2_20261027`: new, `createdb` + `pg_restore` of `accept_clean_baseline_140.dump`, fingerprint identical to the baseline at the start (219 tables / 567 rows), revision `140_clock_advance_details`. Retained, not dropped. The earlier disposable copy (`…retest_20261027`) was not reused |
| Stack | API `127.0.0.1:8002`, Vite `127.0.0.1:5175` from the main checkout at `88ee96a`; origin `http://127.0.0.1:5175` only. Stopped afterwards (nothing listens on 8000–8002 / 5173–5175) |
| Protected state | Human database `dnd_ai_m1415_accept_clean_20261026`: fingerprint **identical** to the baseline after the run (219 / 567). Working `dnd_ai`, the other databases and the human stack (stopped since the fixes began) were not touched. Account authority was changed **only** on the disposable copy (§9.4) |
| Browser / harness | Chrome 155.0.8059.85 headless, playwright-core 1.49.1; folder `retest2_20261027\` (outside the repository): `lib.mjs`, `run.mjs`, the scripts below, `*.json` results, `logs\`, `shots\` (45 screenshots) |
| Credentials | From the child environment only (`envrun.py`); never printed or stored. One sign-in per persona for the whole process (`run.mjs` shares the signed-in context), so the 10-per-15-minute throttle was not hit |
| Personas | `admin` (campaign owner and GM, world Owner), `gm` (world Editor + Reviewer via Sharing, campaign `gm`), `player_a` (negative check only); `player_b` received the Game Master **system** role on the disposable copy for the ownership-transfer test |
| Assertions | As §1, with the final announcement history: a MutationObserver records every announcement. After `run1` the observer was refined to count the announcer's alternating `<span>`/`<p>` node, so two identical messages are two announcements (`gp`, `gq`, `gr`, `gs` ran with it; `run1` ran with the earlier de-duplicating form, which its presence/absence checks are not affected by) |

### 9.2 Results by script

**Raw recorded totals** are what each result file contains (`retest2_20261027\<script>.json`, as written; nothing was edited or excluded). The last column says where each recorded failure came from. A script that throws before its own `save` writes nothing, and its records are carried into the next file saved by the same process, so a file can hold records of a different script. Failures of executions whose file was never written exist only in `logs\run*.log` (§9.5).

| File | Recorded pass / fail | Covers | Recorded failures |
|---|---|---|---|
| `ga.json` | 15 / 0 | ops 1, 2; the DEF-005 reproduction | none |
| `gb.json` | 14 / 0 | op 11 (counting fixed per write) | none |
| `gc2.json` | 6 / 0 | ops 7–9 | none |
| `gc3.json` | 8 / 0 | ops 3–6 | none |
| `gd.json` | 10 / 0 | ops 10, 16, 25, 26 | none |
| `ge2.json` | 12 / 2 | ops 13, 17, 18; carries `ge` | both from the `ge` execution in `run1` (op 13 script fault, then `SCRIPT ERROR ge`); `ge2` itself recorded no failure |
| `gf.json` | 5 / 1 | op 19; the first op 20 attempt | the old op 20 check (script fault), superseded by `gf2` |
| `gf2.json` | 2 / 0 | op 20 hit points | none |
| `gg.json` | 5 / 0 | op 21 add area | none |
| `gg2.json` | 3 / 0 | op 21 Area now (rerun, `run2`) | none |
| `gh.json` | 8 / 1 | op 22, Reviewer | the `SCRIPT ERROR gg2` of the first `gg2` execution in `run1`; `gh` itself recorded no failure |
| `gi.json` / `gj.json` / `gk.json` | 4 / 0, 4 / 0, 3 / 0 | ops 24, 23; RC-03 | none |
| `gl.json` | 12 / 1 | RC-04 … RC-07 | one unconditional record at the end of the script of the `38d2865` DEF-006 finding (a historical record, not a measurement of `88ee96a`); DEF-006 on `88ee96a` is measured in `gq` |
| `gn.json` / `go.json` | 13 / 0, 7 / 0 | C1/D1/D2; RC-08, RC-09, permission loss | none |
| `gp.json` | **21 / 0** | DEF-005 two-write sequences | none. Written by the **`run5`** execution (see below) |
| `gq.json` | **31 records: 29 pass / 2 fail** | DEF-006 | **both failures are `gp` records from the `run4` execution** (see below). `gq` itself recorded **19 checks, all passed** (records 13–31 of the file) |
| `gr.json` | 8 / 0 | party restore, NPC condition, event correct, clock correct | none. Written by `run14` |
| `gs.json` | 13 / 0 | ownership transfer, end role, allow/revoke hosting | none. Written by `run8` |

**`gp` and `gq`, reconciled.** `run4` executed `gp` and then `gq` in one process (`logs\run4.log`: 29 PASS, 2 FAIL).
- `gp` in `run4` recorded 10 passes, then failed `DEF-005 organization: SECOND write (add member) on the same mounted roster reports its own failed read, not announced early` (a Playwright wait, 8 s timeout) and threw `SCRIPT ERROR gp` (a click timeout). It never reached its own `save`, so these 12 records (10 pass, 2 fail) were written into `gq.json` by `gq`'s save, followed by `gq`'s 19 own records. That is why `gq.json` is 31 records, 29 pass and 2 fail, and why the 29 is **not** "gq passed 29/29": 10 of the 29 passes are `gp` records and 19 are `gq`.
- **Cause of the failed organization assertion:** the failure screenshot (`shots\FAIL_DEF_005_organization_SECOND_write_add_member_on_the_same_mounted_roste.png`, taken in `run4`) shows the add-member form with the message "That member already belongs to this organization during that time" and Tobin Reed already on the roster. The preceding `run3` execution of the same script had added Tobin Reed to that organization's roster on the same disposable database; `run4` selected the same character again, so the write was refused (it was not a confirmed write with a failed read). This is a script/fixture-state cause, shown by the screenshot rather than inferred.
- **What resolves it:** the script was changed to select a different character (Sella), and `gp` was run alone as `run5` (`logs\run5.log`: 21 PASS, 0 FAIL), which wrote `gp.json` (21 records, 21 pass, 0 fail). That `gp.json` includes the organization scenario (status, then the second write, add member, on the same mounted roster: records 9–12 of the file). `run3` had also passed 21/21 with the original character on a roster that did not yet contain him; its `gp.json` was overwritten by `run5`'s. The 21/21 in `gp.json` is therefore attributed to `run5`, not to `run4`.
- **`SCRIPT ERROR gp` in `gq.json`** is the click timeout thrown by that same `run4` execution after the organization step; it has the same origin and the same resolution. A second, earlier `gp` failure exists only in `logs\run2.log`: an organization **status** step that chose a status the organization already had ("already has that status", shown in `shots\FAIL_DEF_005_organization_status_confirmed_roster_read_fails_notice_held_no.png`); it threw before any save, so it is in no JSON. Selecting the status from the page's own "Now:" text fixed it (`run3` onward).
- **Not resolved by evidence:** nothing in these records shows the second organization write failing as a product behaviour. The records do not prove why `run3`'s clean pass and `run4`'s failure differ beyond the roster state shown in the screenshot; no rerun was made to test that statement further.

### 9.3 DEF-005 and DEF-006 in a real browser

**DEF-005** (`ga`, `gp`, `gs`; logs `run1.log`, `run5.log`, `run8.log`). Each second write on the same mounted view reports its own saved-but-behind notice, holds, is not announced early, recovers by a read, is announced once, and each intended write is exactly one POST:

- world archive → page Try again → restore → page Try again (`ga`: the reproduction that failed on `38d2865` now passes);
- timeline archive → Try again → restore → Try again;
- lifecycle pair through the provider (submit for review, Try again, approve, Try again) on a World record;
- organization status → Try again → add member (same mounted roster) → Try again;
- two world-time records on the World times page (two announcements of the same words, counted separately);
- inline picker: record, **Load latest**, then a further record reported afresh;
- a second submit of the form while the first is pending (held at the server): the POST was started once, then confirmed once;
- ownership transfer, end role, allow hosting then revoke hosting on one mounted Sharing page (`gs`).

**DEF-006** (`gq`: its own 19 checks, `logs\run4.log`, shots `def006_*.png`). On fresh claims:

- authoring read **500**: notice "Claim saved. The latest claim could not be loaded", the editor stays, the generic status is announced, "Knowledge claim saved" is not; an edit on the retained editor keeps **Save held**; **Load latest** failing again changes nothing; following the Knowledge link shows the unsaved-changes dialog and **Keep editing** preserves the draft; once authoring and detail work the notice goes, the draft is kept, Save is enabled, no second POST, and the next save carries `expected_row_version` 1 → 2, a new key, and is announced;
- authoring read **403** and **404**, both immediately after the save and after a retained edit: the editor, the form controls and the draft text are gone, a status says the editor is no longer available, and leaving is no longer guarded;
- detail read alone fails: notice, editor kept, Load latest recovers; both required reads fail: an authoring read that works alone does not recover it, both do; a claim **lifecycle step** whose authoring read fails: notice, no early "Submitted for review", one POST, a read-only retry clears it.

### 9.4 Ownership transfer (op 11) and the remaining Sharing variants (`gs`)

The supported system-role assignment (`POST /admin/accounts/{id}/system-roles`, the call behind the Platform accounts role checkboxes) gave the existing account `player_b` the Game Master system role **on the disposable copy only**. Transfer with "Keep me on the world as" Editor and the access read failing: notice, controls held, not announced early; the read-only retry is then answered with an **authoritative denial** (an Editor cannot read Sharing), which removes the content and announces "Ownership transferred" exactly once, one POST. Transfer keeping no role: the real read is refused, content removed, announced, focus on the heading, one POST (no fault injection). End role, allow hosting and revoke hosting each show their own notice and recover by a read, with one POST each.

### 9.5 Failures recorded in earlier executions, and how each was resolved

Every failure below was recorded by an execution of the scripts on this run's disposable database; none was removed from a log or a result file. Each is a script, fixture-state or selector problem **as shown by the cited evidence**, was resolved by changing the script (never by relaxing what it asserts) and rerunning, and was superseded by clean evidence.

| Execution | Recorded | Origin and evidence | Superseded by |
|---|---|---|---|
| `run1` `ge` | `op13 session end` fail, then `SCRIPT ERROR ge` (in `ge2.json`) | the same script fault as in §5 (the session end needs the clock advanced first, which `ge2` does); this run's screenshot was not re-inspected, the attribution rests on `ge2` passing op 13 with that change | `ge2` in `run1`: op 13 passes |
| `run1` `gf` | `op20 NPC hit points` recovery fail (in `gf.json`) | the same script fault as in §5 (the banner's Try again was clicked instead of the panel's); not re-inspected for this run, the attribution rests on `gf2` passing with the panel's button | `gf2` 2/2 |
| `run1` `gg2` | `SCRIPT ERROR gg2` (in `gh.json`) | selector "Spike trap (1)" exists only when a hazard name is duplicated | `gg2` rerun in `run2`: 3/3 (`gg2.json`) |
| `run2` `gp` | organization status fail, `SCRIPT ERROR gp` (log only) | the status chosen was the current one (screenshot) | `run3` 21/21, `run5` 21/21 |
| `run4` `gp` (in `gq.json`) | organization add-member fail, `SCRIPT ERROR gp` | character already on the roster from `run3` (screenshot) | `run5` 21/21 (`gp.json`) |
| `run6`, `run7` `gs` | fails and `SCRIPT ERROR gs` (logs only) | wrong write path in the fault rule (`/transfer` instead of `/ownership-transfer`); an assertion that matched the header's "Administrator" text; assuming the Editor's retry shows a role table when an Editor cannot read Sharing (an authoritative denial); a role already assigned by the earlier execution; the wrong dialog button | `run8` 13/13 (`gs.json`) |
| `run9` … `run13` `gr` | fails and `SCRIPT ERROR gr` (logs only) | the restore dialog requires a reason; NPC **resource** is refused because this NPC tracks no resource (a fixture limit: TC-38 block); NPC **move** selected nothing in the script; the clock Correct form and its confirmation dialog | `run14` 8/8 (`gr.json`); resource and move **remain unexercised** |
| `run15` `gt` | `SCRIPT ERROR gt` (log only) | the archive action was not reachable as a button on the Publication tab | not superseded: World-record archive/restore steps **remain unexercised** |
| `gl.json` | one unconditional historical record of the `38d2865` DEF-006 finding | written by the script's last line regardless of outcome | measured separately in `gq` |

**Accounting statement.** The earlier executions listed above recorded failures. The subsequent clean executions (`gp` 21/21, `gq`'s 19 checks, `gr` 8/8, `gs` 13/13, and the passing reruns of the other scripts) are the evidence that supports the DEF-005 and DEF-006 fixes, and the Codex review of the fixes found no code defect. Whether any recorded failure was a product defect is decided here only by the cited screenshots and logs; where they are silent (the exact reason `run3` and `run4` differ beyond the roster state in the screenshot), this document does not claim more.

### 9.6 RC-03 … RC-10 reassessed, and what is still not browser-verified

| Row | On `88ee96a` |
|---|---|
| RC-03 | Pass (`gk`). RC-04 / RC-05 / RC-07 pass (`gl`). RC-06 passes for the detail, authoring (500/403/404), both-reads and lifecycle variants (`gl`, `gq`) |
| RC-08 | Pass (`go`; and the next claim save, `gq` A) |
| RC-09 | Pass (`go`: drafts kept, a late response does not touch another record, permission loss removes private content; `gq`: 403/404 remove the claim editor and draft). Slow 3G was not used |
| RC-10 | Every one of the 26 operations has at least one browser-verified variant, **but not every command of every operation**: see below. Shared-hook tests are not counted as verification of an operation |

**Not exercised in a browser (still unverified):**

- op 19: encounter update, participant add/change/remove, abort, end (start and record turn were run, `gf`).
- op 20: NPC **resource** (this NPC tracks no resource, so the write is refused: the TC-38 positive-resource block) and **move** (the place search offered nothing selectable in the script).
- op 21: dungeon Connections and Contents.
- op 22: lifecycle reject / return / **archive / restore** / delete steps of a World record (the archive action was not reachable as a button on the Publication tab in the script), and the Item and Quest steps beyond submit.
- op 23: relationship end, archive, perspectives.
- op 24: organization member editor.
- op 15: travel superseded variant. op 25: the inline picker inside the party, session, event and organization forms (clock form and World times page covered).
- Newly covered in this run: op 3 party restore, op 10 event correct, op 16 clock correct, op 20 NPC condition, op 11 transfer / end role / allow and revoke hosting (`gr`, `gs`).
- Also unexercised: keyboard-only, screen-reader (TC-55), responsive widths, other browsers, Slow 3G, and the backend/database suites (not rerun: no backend change since `9ab549d`).

**Baseline.** The evidence supports the **retested** items passing on `88ee96a`, but the unexercised variants above remain, Codex has not reviewed this evidence, and no human row is executed. This document therefore does **not** propose a manual-run baseline and freezes none; that decision stays with the owner and Codex.

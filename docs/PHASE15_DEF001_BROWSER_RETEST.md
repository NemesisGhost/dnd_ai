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

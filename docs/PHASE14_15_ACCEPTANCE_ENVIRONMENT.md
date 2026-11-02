# Phase 14/15 acceptance — environment and evidence handoff (CP-11)

Prepared 2026-10-26. **This document prepares the owner's manual run; it does not record any acceptance.** No secret (password, hash, token, cookie, connection string, authenticated header) appears here or in the evidence folder.

Evidence folder (outside every repository): `C:\Users\nemes\dnd_ai_evidence_20261026\cp11\`

## 1. Code under test

| Item | Value |
|---|---|
| Branch / HEAD | `phase15/completion` @ `9ab549ddbc78cb9b5c1aac9c99f3a967112edc62`; `origin/phase15/completion` identical; PR #66 head identical, mergeable, state clean |
| CP-10 approved range | `e054bd1…9ab549d` = `a922a51` (CP-10 consolidation), `707a71e` (claim save refresh), `9ab549d` (claim lifecycle read-back). Approval by Codex was stated in the task; the head was verified from git and CI, not assumed |
| Current-head CI | Run **40402307296** (event: pull_request) on `9ab549d`: all 10 jobs `SUCCESS` — Lint and Type Check; Portal tests, lint, and build; Foundry module tests and packaging; Migrations (PostgreSQL 18); Tests (PostgreSQL 18) shards 1–4/4; Application image and compose smoke test; Named volume survives container recreation |
| Prerequisite product changes | **None.** The renamed login names are already usable (see account manifest §3), so nothing was committed or pushed |
| Selected acceptance SHA | `9ab549ddbc78cb9b5c1aac9c99f3a967112edc62`. If it changes, update the ledger's "Code change log" |
| Documentation snapshot at preparation | The three owner-edited verification/acceptance files had patch SHA-256 `2059022c…2de5`, matching the 2026-10-25 landing record. The CP-11 documents below were untracked then and are now committed as the acceptance handoff. No acceptance results are implied by that commit. |

CP-11 acceptance documents committed with this record (all under `docs/`): `PHASE14_15_HOWTO_FIRST_CAMPAIGN.md`, `PHASE14_15_ACCEPTANCE_LEDGER.md`, `PHASE14_15_COVERAGE_MATRIX.md`, `PHASE14_15_COMPANION_SCENARIOS.md`, `PHASE14_15_DEFECT_REGISTER.md`, `PHASE14_15_ACCOUNT_MANIFEST.md`, and `PHASE14_15_ACCEPTANCE_ENVIRONMENT.md` (this file). Supporting history: `PHASE14_15_INTEGRATION_AND_CONSOLIDATION_PLAN.md`, `PHASE14_15_MANUAL_TESTING.md` (historical guide, unedited), and `PHASE15_CP10_HANDOFF.md`. Historical snapshot with hashes: `historical\` + `historical.sha256`.

## 2. Databases (PostgreSQL 18.4, 127.0.0.1:5432)

| Database | Revision | Purpose | State |
|---|---|---|---|
| `dnd_ai` | `138_world_roles_and_use_grants` | The owner's working database | **Unchanged.** Fingerprint (218 tables, 2,989 rows) identical before and after; not migrated; 0 connections during the work |
| `dnd_ai_m1415_accept_clean_20261026` | `140_clock_advance_details` | **Human acceptance run** (accounts-only) | 12 accounts, 0 worlds/campaigns/sessions/entities/receipts. Untouched baseline dump: `accept_clean_baseline_140.dump` (SHA-256 `38f97db4…1825`) |
| `dnd_ai_m1415_clean_install_20261026` | `140_clock_advance_details` | **TC-56 clean installation** | Migrated, **zero accounts**, not started |
| `dnd_ai_m1415_cp11_backupverify_20261026T164103` | `138…` | Disposable restore used only to prove the backup | Can be dropped once you have seen this record |

All earlier `dnd_ai_m1415_*` and `dnd_ai_test_*` databases were left in place; nothing was dropped or overwritten. Backup of the source: `dnd_ai_138_cp11_20261026T164103.dump` (SHA-256 `67a53727…b601`), verified by TOC read and a disposable restore with identical per-table fingerprints (account manifest §1).

## 3. The isolated stack

| | |
|---|---|
| Portal (**running** since 2026-10-27 06:15 -05:00, serving `af34a34`; §11) | `http://127.0.0.1:5174` (Vite from `C:\Users\nemes\dnd_ai\portal`, config `stack\vite.accept.config.mjs`) |
| API | `http://127.0.0.1:8001` (uvicorn, `dnd_ai.api.app:app`, working directory `C:\Users\nemes\dnd_ai`) |
| Proxy | `/api` → `127.0.0.1:8001` (prefix stripped); `/auth` → `127.0.0.1:8001` |
| Database | `dnd_ai_m1415_accept_clean_20261026` (the API's only database connection — checked in `pg_stat_activity`) |
| Allowed browser origin | `http://127.0.0.1:5174` only (`DND_AI_LOCAL_SESSION_ALLOWED_ORIGINS`, set in the child environment; a foreign `Origin` returns 403 — checked) |
| Why `127.0.0.1`, not `localhost` | The session cookie has one fixed name and is host-scoped, not port-scoped; signing in at `localhost:5174` would replace your own `localhost:5173` session |
| Code SHA served | `af34a34` since 2026-10-27 (the main checkout's source; editable install; earlier text in this document names the SHA served at the time) |
| Processes at preparation | API launcher pid 1252 → server pid 29896; Vite launcher pid 30288 → server pid 18104. They were started detached; **stopped at your request** (nothing is listening on 8000/8001/8002/5173–5175 now). Start them yourself with §3 |

Nothing was listening on 8000, 8001, 5173 or 5174 before the stack started; no prior acceptance process existed and none was stopped. Your own servers (8000/5173) were not running and were not touched.

**Start** (PowerShell; the database URL is composed in the child environment from your `.env` credentials and is never printed):
```powershell
& C:\Users\nemes\dnd_ai_evidence_20261026\cp11\stack\start_stack.ps1 -DbName dnd_ai_m1415_accept_clean_20261026 -ApiPort 8001 -WebPort 5174
```
**Stop** (stops only a listener whose command line proves it is a CP-11 stack; anything else is left alone):
```powershell
& C:\Users\nemes\dnd_ai_evidence_20261026\cp11\stack\stop_stack.ps1 -ApiPort 8001 -WebPort 5174
```
**Personas** (five fresh Chrome profiles under `%TEMP%\cp11_profiles`):
```powershell
& C:\Users\nemes\dnd_ai_evidence_20261026\cp11\stack\open_personas.ps1
```
**Logs:** `stack\api_p8001.*.log`, `stack\web_p8001.*.log`. The API prints a FastAPI "Duplicate Operation ID" warning at start (DEF-002, Low).

## 4. What is ready for you

| Path | Purpose |
|---|---|
| `docs\PHASE14_15_HOWTO_FIRST_CAMPAIGN.md` | **Start here.** Chronological How-To, 68 tasks (A–K), UNEXECUTED |
| `docs\PHASE14_15_ACCEPTANCE_LEDGER.md` | 283 rows; result states; five separate evidence fields |
| `docs\PHASE14_15_COVERAGE_MATRIX.md` | Every TC-01–58 and variant → task, methods, row; gaps (§6) |
| `docs\PHASE14_15_COMPANION_SCENARIOS.md` | SR-M1–16, RC-01–10, NV, PV, TC-53, TC-55, TC-56 |
| `docs\PHASE14_15_DEFECT_REGISTER.md` | DEF-001 … 006, blockers, closed items, new-defect template |
| `docs\PHASE15_DEF001_BROWSER_RETEST.md` | Scripted browser retest of the DEF-001 fix on `38d2865`: evidence map for the 26 operations, RC rows, limits |
| `docs\PHASE14_15_ACCOUNT_MANIFEST.md` | What was copied/renamed and how it was verified |

## 5. Exact first manual steps

1. Confirm the stack is up: open `http://127.0.0.1:5174/` — you should see **D&D AI World** with **Email or Username** and **Password**. If not, run the Start command in §3.
2. Run `open_personas.ps1` (or open five private windows) and name them ADMIN, GM, PLAYER-A, PLAYER-B, OBSERVER.
3. Create `C:\Users\nemes\dnd_ai_evidence_20261026\cp11\human\` for screenshots. Do not photograph a password, link or token.
4. Fill in the ledger **Run header** (tester, date, Chrome version).
5. Open the How-To and begin at **Task A1**: in the ADMIN window sign in as `admin` with the **existing** password.
6. Continue A → K in order. Update the matching ledger rows as you go; leave anything not yet done `Unexecuted`.

**Do not** use Platform accounts' Actions (disable / reactivate / reset), re-run any seed script, or touch ports 8000/5173 during the main journey. Create the checkpoint copy in the companion document §0 before the SR scenarios, which change accounts.

## 6. Automated and scripted checks actually executed (preparation only)

All on `9ab549d`; none marks any ledger row.

| Check | Result |
|---|---|
| `ruff format --check`, `ruff check`, `mypy src`, `node --test foundry-module` (via `scripts/verify.sh full`) | PASS ×4 |
| `pytest tests/unit` | 1,204 passed, **1 failed**: `test_local_session_allowed_origins_defaults_to_dev_topology_outside_production` — depends on the owner's `.env` (DEF-003, Informational, passes in CI). With that one test deselected: **PASS** (`unit_excluding_env_test`, exit 0) |
| `pytest tests/database` | **5,457 passed** (exit 0, 37 min) |
| `pytest tests/scenario` | **117 passed** (exit 0) |
| Portal `eslint .` | PASS |
| Portal `tsc -b && vite build` | PASS |
| Portal `vitest run` | **360 files, 3,485 tests passed** |
| `alembic upgrade head` on the new database (136→140), `alembic check` | PASS, "No new upgrade operations detected" |
| Scripted real-browser check, **signed-out only** (`scripted\signed_out_check.mjs`, Chrome 155): deep links land on Sign In; API reads 401; foreign Origin 403; signed-out mutation 401; Sign In page has no horizontal scroll at 390/1280/2560; no session cookie; no mutation sent | 16/16 |
| Accept database after the signed-out check | still 0 sessions, 12 users, 1 (migration) audit row — the check wrote nothing |
| Scripted authenticated pass on the disposable copy (A1, A3, B1, B2, C1, D1, D2) | 5 sign-ins OK with correct roles (`admin`: admin+gm, `world.create`, `campaign.host`, `accounts.manage`; others: player only); 12 account rows as documented; `disabled` and unknown logins get the identical refusal; non-admins refused on Platform accounts and get no World form; world creation and Sharing work. **Two script assertions failed on my own string handling** (page-text slice; Reviewer option label) — not product failures, not counted as passes. Product text differences found are fixed in the guide: non-admin empty-state wording, `Testing 1` shows "(pending activation)", Last login shows "Never" |

## 7. Remaining for you, and why

| Item | Reason |
|---|---|
| **Everything in the How-To** (68 tasks) | Human/manual evidence is the only field that can pass a UI workflow |
| **Further scripted real-browser evidence** | BLK-1 is **lifted**: you told me the passwords are `ADMIN_ACCOUNT_PASSWORD` / `DEV_ACCOUNT_PASSWORD` in `.env`. They were used only from the child process on a **disposable copy** (`dnd_ai_m1415_accept_scripted_20261026`, ports 8002/5175, now stopped), never printed or reset. Done so far (Scripted column only): sign-in for all five personas, A3, B1, B2, C1, D1, D2 (partial). Remaining Tasks C2–K8 can be scripted on request; the human run still uses the untouched `…accept_clean…` database |
| TC-55 (screen reader, 200 % zoom, reduced motion, 2560 px, high contrast) | Human + assistive technology required |
| TC-56 clean installation | You choose the bootstrap administrator's password (companion §7) |
| SR scenarios | Run on the checkpoint copy |
| Decisions | Owner: DEF-001 (fix or explicit risk acceptance, DR-9); Phase 14 hierarchy decision; Phase 15 acceptance decision |

## 8. Completion gate

CP-11 and Phase 15 are **not** complete because preparation finished or CI is green. Closure needs: required coverage executed with evidence; every defect fixed or explicitly accepted under the rubric; reviewed code with current-head green CI; accurate documentation; and your acceptance decision recorded in the ledger. Working `dnd_ai` was not migrated; no PR was merged; `main`, `integration/scoped-roles` and PR #67 were not touched.

## 9. DEF-001 fix: effect on the evidence above (added 2026-10-26)

The owner chose to **fix** DEF-001 (register §5). The candidate head is code commit `7990225af3305d7d7221d0daf068ae1c70199aee` (plus the docs commit(s) after it). **Nothing above was re-executed against it, no ledger row changed, and the manual-acceptance version is not frozen:** §1 and the ledger header still name `9ab549d` until the owner or Codex freezes a reviewed head. Everything in §1–§8 describes `9ab549d`; this section says what still applies to the candidate.

### 9.1 Applicability of the §6 results

| §6 item (at `9ab549d`) | Applies to the candidate? | Why |
|---|---|---|
| `ruff`, `mypy`, `node --test foundry-module`, `pytest tests/unit` (1,204 + the DEF-003 test), `tests/database` (5,457), `tests/scenario` (117), `alembic upgrade head` / `alembic check` | **Yes, by diff.** Not rerun | `git diff 9ab549d..HEAD` touches only `portal/src` and `docs/`. CI reruns them on the pushed head |
| Portal `eslint`, `tsc -b && vite build`, `vitest` (360 files / 3,485 tests) | **Superseded** | Rerun on the candidate: eslint PASS, tsc PASS, build PASS, vitest **363 files / 3,527 tests PASS** (register §5) |
| Scripted signed-out real-browser check (16 assertions) | **Yes, conditionally** | It exercises the Sign In page, deep-link redirects, signed-out API refusals and Sign In layout. None of the 60 changed portal files is on that path (the only stylesheet change adds a rule scoped to a notice inside an action row). Rerun it if the frozen head differs further from `7990225` |
| Scripted authenticated pass: sign-in ×5, A3, B1, B2 | **Yes, conditionally** | Sign-in, Platform accounts and the account list use unchanged pages |
| Scripted authenticated pass: **C1 (create world), D1, D2 (World Sharing)** | **No — must be rerun** | They load the changed World overview (`WorldOverviewPage`, `TransitionControls`) and Sharing page (`WorldSharingPage`). The earlier pass says "world creation and Sharing work" for `9ab549d` only |
| "Product text differences found" fixed in the guide | Yes | Unrelated to this change |

### 9.2 What must be retested on the reviewed head (human / scripted browser)

Because every ledger row is still `Unexecuted`, no earlier result is carried forward and nothing is discarded; the list says where DEF-001 changed observable behaviour, so these are the rows to run with the new expectations.

| Area changed | Run (companion / task → cases) |
|---|---|
| The recovery contract itself | **RC-10 (rewritten for 26 operations)**, RC-03 (uncertain retry, shared hook untouched but re-confirm on the changed callers), **RC-04 … RC-08** (the shared lifecycle panel, Quest and Item workspaces and the Claim page changed), **RC-09**, K5 → TC-48 |
| World / timeline archive and restore; world and timeline pages | K4 → TC-51; J4 → TC-03; C-series world and timeline pages |
| Party pages and members | G4 → TC-06, TC-20, TC-21 (+ CP-9a explanations) |
| NPC portrayal and Run this NPC | H9, I9 → TC-38 (the positive resource variant stays Blocked) |
| Character starting state and build activation | G3 → TC-19 |
| Event void and correct | I2 → TC-25 |
| World Sharing and ownership transfer | D1, D2 → SR-M4, SR-M5, SR-M6, SR-M11, SR-M12, TC-53, K6 → TC-54 (world-role), TC-04 |
| Run Session start, log, end, travel | I1 → TC-24; I11, J1 → TC-50; H6, I4 → TC-37; H2 → TC-23 |
| Campaign clock | E7, I3 → TC-15, CP-9b |
| Session details and archive/restore | H1 → TC-22; J1 → TC-50 |
| Encounters | H10 → TC-42; I10 → TC-43, TC-44 |
| Dungeon, area and Area now | H5 → TC-33; I7 → TC-34 |
| Lifecycle steps on World records, items, quests and claims | F1–F4 → TC-16, TC-17, TC-18; G1, G2; H3 → TC-26; H4 → TC-28, TC-29, TC-32; H7, H8 → TC-39, TC-40; J7 → TC-47; K1 → TC-10; K2 → TC-31; SR-M13; NV-07, NV-08 |
| Relationships; organization members | G6 → TC-35; G7 → TC-36 |
| World-time recording (World times page and the inline picker used by party, session, clock, event and organization forms) | C3, E6 → TC-14; E7, G4, I1, I2, I3, G7 wherever a time is recorded inline |
| New notices and live-region announcements | TC-55 (assistive technology must hear "Saved, but the latest data could not be loaded." once, and the write once it is read) |
| Clean installation | TC-56 passes through the changed World pages |

Not affected by file list (still `Unexecuted`, not carried forward): TC-01/02 login and account lists, TC-12 setup cancellation, TC-13 invitations and access, TC-49 route manifest, TC-52 branch creation form, TC-57/58 privacy and grants.

### 9.3 Decisions this changes

DEF-001: the fix is implemented but **not closed** (needs Codex review, current-head CI and the retests above). CP-11 and Phase 15 remain incomplete. DEF-002 and DEF-003 are unchanged.

## 10. Browser retest of the DEF-001 fix and the manual-run baseline (added 2026-10-26)

### 10.1 What was done

The Codex review of the preparation and DEF-001 code found no confirmed defects; CI on `38d2865` ran green ([run 40422430588](https://github.com/NemesisGhost/dnd_ai/actions/runs/40422430588)). Those are recorded here separately from the browser results. The scripted real-browser retest of §9.2 was then run on `38d2865` against a disposable copy; the evidence map (all 26 operations, with what each check did and did not exercise), the RC-03 … RC-10 results, the scripted C1/D1/D2 pass and the explicit Reviewer verification are in [PHASE15_DEF001_BROWSER_RETEST.md](PHASE15_DEF001_BROWSER_RETEST.md). Two residual defects were found, DEF-005 and DEF-006 (register §1, both proposed Medium 4, not fixed). **No human acceptance row changed; every ledger result is still `Unexecuted`.**

### 10.2 Proposed manual-run baseline

`38d2865ff9889f5a1f68f19315b79a088c3ea97d` is the **proposed** baseline for the human run (it is the reviewed candidate and is what the stack in §10.3 serves). It is **not frozen**: DEF-005 and DEF-006 are open Medium findings that need an owner decision (fix, or an explicit risk acceptance under DR-9) before the owner or Codex freezes a head. If either is fixed, the head changes and §9.2's retest list applies again to the affected rows (the ledger's "Code change log" says which). The ledger header and the run header still name `9ab549d` until a head is frozen.

### 10.3 The human acceptance stack (running for the owner)

| Check | Result |
|---|---|
| Database | `dnd_ai_m1415_accept_clean_20261026`, revision `140_clock_advance_details` (= the migration head in the repository); table fingerprint **identical** to `fp_accept_baseline.json` (219 tables, 567 rows) before the retest, after it, and with this stack up; the API's only database connection is to this database (`pg_stat_activity`) |
| Portal / API | `http://127.0.0.1:5174` and `http://127.0.0.1:8001`, serving `38d2865` from the main checkout; API title/version `D&D AI World Platform API 0.1.0` |
| Proxy | `/api` → `127.0.0.1:8001` (prefix stripped); `/auth` → `127.0.0.1:8001` (from `stack\vite.accept.config.mjs`) |
| Signed-out reachability | `/` and `/login` return 200 (HTML); `/api/auth/session` and `/auth/session` return 401 with the `unauthorized` error body. No sign-in was attempted on this stack (that would write login history to the baseline) |
| Allowed origin | `DND_AI_LOCAL_SESSION_ALLOWED_ORIGINS=http://127.0.0.1:5174`, set in the child environment by `start_stack.ps1` (same mechanism as the retest stack, where a sign-in from the allowed origin worked); not exercised on this stack for the reason above |
| Listeners | Only 8001 and 5174. 8000/5173 (yours) and 8002/5175 (the retest stack, stopped) are not listening |

**Start / stop** (PowerShell; the stack is running now, so you only need these after a stop or reboot):
```powershell
& C:\Users\nemes\dnd_ai_evidence_20261026\cp11\stack\start_stack.ps1 -DbName dnd_ai_m1415_accept_clean_20261026 -ApiPort 8001 -WebPort 5174
& C:\Users\nemes\dnd_ai_evidence_20261026\cp11\stack\stop_stack.ps1 -ApiPort 8001 -WebPort 5174
```
No manual setup record (world, campaign, account change) was created on your behalf.

### 10.4 Still to do by a person, and open items

* The whole How-To (68 tasks) and the ledger's human column; TC-55 (screen reader, 200 % zoom, reduced motion, 2560 px, high contrast), keyboard-only and responsive checks, TC-56, the SR scenarios.
* Open: DEF-001 (fix browser-retested by script; owner acceptance pending), DEF-005, DEF-006 (new), DEF-002, DEF-003, DEF-004.
* Blocked: TC-38 positive resource, TC-31 deprecated claim, TC-41 attunement limit, SR-M14, and ownership transfer in a browser (needs a second system-GM account).
* The disposable retest database `dnd_ai_m1415_retest_20261027` is kept for inspection; drop it when you no longer need it.

### 10.5 Status after the DEF-005 / DEF-006 fixes began (2026-10-26)

The owner chose to fix both defects, so the portal source changes. The acceptance stack in §10.3 (Vite serves the main checkout with hot reload) was **stopped** (ports 8001 and 5174 only) so it cannot serve changing or unreviewed code. §10.3 describes it as it was at `38d2865`; **nothing is running now** on 8000–8002 or 5173–5175. Its database `dnd_ai_m1415_accept_clean_20261026` was not touched (fingerprint identical, 219 tables / 567 rows) and is retained. The proposed manual-run baseline in §10.2 is **withdrawn** until the new head has Codex review, current-head CI and the browser retest in [PHASE15_DEF001_BROWSER_RETEST.md](PHASE15_DEF001_BROWSER_RETEST.md) §8; restart the stack with the §3 command only for the head that is then named.

## 11. Manual-run baseline selected, and the stack prepared (2026-10-27)

This section supersedes §10.2 ("proposed baseline") and §10.5 ("stack stopped, baseline withdrawn"), which stay as history. **The baseline below is selected for this one manual run. It is not final acceptance; no human result exists; DEF-001, CP-11 and Phase 15 are not complete.**

### 11.1 Selected baseline and its signoffs (kept apart)

| Item | Value |
|---|---|
| Code SHA for the manual run | `af34a3458ff0ee0f518a617f86dc18d6800f6673`, `phase15/completion`; local HEAD = `origin/phase15/completion`; nothing follows it. PR #66 is open and clean |
| Schema revision | `140_clock_advance_details` (the repository's migration head) |
| Database | `dnd_ai_m1415_accept_clean_20261026` (accounts-only baseline) |
| Stack started | 2026-10-27 06:15:15 -05:00 (API pid 18632, Vite pid 33816; launcher `dbrun.py dnd_ai_m1415_accept_clean_20261026`) |
| Code review (Codex) | Reviewed product fixes `caa6589` → `88ee96a` (DEF-005, DEF-006) and the retest-accounting correction `af34a34`; signoffs as reported to the author. A code review is not a browser result and not acceptance |
| CI (separate) | Run 40451117926 on `af34a34`: all 10 jobs `success` (runs 40444946370 on `88ee96a`, 40448377306 on `4bacc95` also green) |
| Scripted browser evidence (separate) | [PHASE15_DEF001_BROWSER_RETEST.md](PHASE15_DEF001_BROWSER_RETEST.md) §9 on `88ee96a`, disposable copy only. The only product diff from `88ee96a` to `af34a34` is documentation. Operation coverage is **partial** (§11.3) |
| Human, responsive, keyboard, screen-reader acceptance | **None executed.** Every ledger result is `Unexecuted` |
| Future code changes | Any commit after `af34a34` that touches `portal/`, `src/`, `database/` or the stack configuration needs an applicability/retest assessment in the ledger's Code change log before it is served; documentation-only commits do not change the served code |

### 11.2 What was verified on the stack before leaving it running (no sign-in, no application record)

| Check | Result |
|---|---|
| Database identity and contents | Revision `140_clock_advance_details`; 12 accounts; 0 worlds, campaigns or entities; the dump `accept_clean_baseline_140.dump` (SHA-256 prefix `38f97db4`) is the recorded baseline. Table fingerprint (219 tables, 567 rows, lookup tables plus accounts) **identical** to `fp_accept_baseline.json` before the start, and again with the stack up and probed. Scripted work used only the disposable copies (`…retest_20261027`, `…retest2_20261027`) |
| Effective database target | The API was launched by `dbrun.py dnd_ai_m1415_accept_clean_20261026 -- …` (the database name is the launcher's argument); `pg_stat_activity` shows exactly one connection to a `dnd_ai%` database, to `dnd_ai_m1415_accept_clean_20261026`; none to `dnd_ai` or any other |
| Processes | API: `C:\Users\nemes\dnd_ai\.venv\Scripts\python.exe -m uvicorn dnd_ai.api.app:app --host 127.0.0.1 --port 8001` (started with working directory `C:\Users\nemes\dnd_ai`, editable install: the code is the repository at `af34a34`). Portal: `node node_modules\vite\bin\vite.js --config …\stack\vite.accept.config.mjs` (relative script path: working directory `C:\Users\nemes\dnd_ai\portal`). Nothing else listens on 8000, 8002, 5173 or 5175 |
| Frontend serves the reviewed code | `/src/hooks/useConfirmedRefresh.tsx` contains `useUnreadWrite` and `/src/pages/KnowledgeClaimPage.tsx` contains `useKeptData` (the DEF-005/DEF-006 fixes) |
| Proxy targets | `stack\vite.accept.config.mjs` proxies `/api` (prefix stripped) and `/auth` to `127.0.0.1:$CP11_API_PORT` = 8001; `…:5174/api/auth/session` and `…:5174/auth/session` return the API's 401 with `server: uvicorn` |
| Effective allowed origin, measured on this API | `POST /auth/login` with an empty body (rejected by validation, so no sign-in attempt and no write): `Origin: http://127.0.0.1:5174` → **422** (passed the origin gate); `http://127.0.0.1:5175`, `http://localhost:5174`, `http://localhost:5173`, `http://evil.example` and no Origin → **403**. The same through the portal proxy → 422. Only `http://127.0.0.1:5174` is allowed |
| Signed-out reachability | `/`, `/login`, `/worlds/new` → 200 (the portal shell); `/auth/session` → 401 on the portal and on the API |

### 11.3 Outstanding coverage, made actionable (all still `Unexecuted`; nothing here is a pass)

Scripted browser evidence covered at least one variant of each of the 26 DEF-001 operations, **not every command**. Each variant below stays pending until a person executes it. Where the guide already has the task, run that task; the two items the script could not reach are given an explicit scenario and a ledger row.

| Variant not exercised by script | Where to run it | Prerequisites | Ledger row |
|---|---|---|---|
| **NPC move** (op 20) | Task **I9**, the "move to Hollowmere at an available time" step | NPC Archivist Sella published (F4); Hollowmere published and a world time recorded (F1/E6); GM window | L-I9 and the new case row **38.move** |
| **NPC resource** (op 20) | Task **I9**, Resources | as above; this NPC tracks no resource, so only the **refusal** can be observed | **38.resource-refusal** (run) and **38.resource-positive** (**Blocked**: no supported pre-tracked NPC fixture; do not insert one by SQL) |
| **World archive / restore** (a published World record through the Publication tab, op 22) | **Supplemental scenario S-1** below | a published location other than the ones later tasks depend on (create `Spare Reef` and publish it in F1/K1 time); GM or ADMIN | new case row **22.record-archive-restore** |
| World / timeline archive and restore (op 1, 2), party restore, event correct, clock correct | Tasks K4, G4, I2, E7/I3 as written | per task | existing rows (L-K4, L-G4, L-I2 …) |
| Encounter update, participant add/change/remove, abort, end (op 19) | Tasks H10, I10 | per task | L-H10, L-I10 |
| Dungeon Connections and Contents (op 21) | Tasks H5, I7 | per task | L-H5, L-I7 |
| Relationship end, archive, perspectives (op 23); organization member editor (op 24) | Tasks G6, G7 | per task | L-G6, L-G7 |
| Item and Quest lifecycle steps beyond submit; reject / return / delete steps | Tasks H4, H7, H8, J7, F-series lifecycle steps | per task | L-H4, L-H7, L-H8, L-J7 |
| Travel superseded variant; the inline time picker inside party, session, event and organization forms | Tasks I1, G4, I2, G7 | per task | existing rows |
| Ownership transfer, end role, hosting grant/revoke in a person's browser | Task D2 (Sharing), companion **SR-M11** on the checkpoint copy | SR-M11 creates its own second game-master account on `dnd_ai_m1415_accept_sr_20261026` (never on the main database) | SR-M11, TC-53 |

**Supplemental scenario S-1 — archive then restore a published World record (lifecycle panel).** Account: ADMIN or GM (world Reviewer). Prerequisite: a published location nobody else depends on. Steps: open the record → **2. Review & publish** → **Publication**; read the available steps; choose **Archive**, cancel, then archive again with the reason `Archive check`; read the status; ⟲ PLAYER-A reloads the record's old address and the World list; ADMIN/GM then **Restore** with the reason `Restore check`; reload. Expect: the archive and the restore each ask for a reason, change nothing on cancel, appear in the record's history, are announced once, and the record returns to published/active; the player sees the archived record only by reference and not in lists. Record the exact button names you saw (the script could not find the Archive action as a button on the Publication tab; if it is not offered, record that as a **Fail** or **Blocked** with a screenshot).

**Blocked cases kept as in the coverage matrix §6:** TC-38 positive resource, TC-31 deprecated claim, TC-41 attunement limit, SR-M14 stale tab, and the API-ONLY steps (TC-22 undiscovered participant, TC-58 grants, TC-48 replay). The matrix row "scripted browser evidence for the imported accounts — Blocked pending owner login" is **out of date**: BLK-1 was lifted and scripted passes exist on disposable copies (retest record §2, §9); it does not make any human row pass.

### 11.4 For the owner

- **Portal:** `http://127.0.0.1:5174/` (use `127.0.0.1`, not `localhost`: the allowed origin and the session cookie are host-specific).
- **Guide:** [docs/PHASE14_15_HOWTO_FIRST_CAMPAIGN.md](PHASE14_15_HOWTO_FIRST_CAMPAIGN.md). **Ledger:** [docs/PHASE14_15_ACCEPTANCE_LEDGER.md](PHASE14_15_ACCEPTANCE_LEDGER.md) (fill the Run header first: tester, dates, Chrome and screen-reader versions, viewports).
- **First account and first task:** Task **A1**, `admin` with your existing password (never written down by me). In a fresh ADMIN profile open the portal root (expect Sign in); type `admin` in **Email or Username**, your password in **Password**, press **Sign In** (expect **Campaigns**); in DevTools → Network read `/auth/session` (`system_roles`, capabilities; do not copy it); open the account menu (expect **Administrator**). Expect "You are not in any campaigns yet." with **Create a world**, **Accept a campaign invitation**, **Create campaign**, a **Platform accounts** link, and no data.
- **Recording:** in the ledger set the row's Result to `Pass`, `Fail` or `Blocked` (or `Owner-Accepted Exception` with your written reason) and write what you saw in the Human/manual column (tester, date, screenshot path under `…\cp11\human\`; no passwords, links or tokens). Never fill the Automated, Scripted, Database or Accessibility columns from a manual look, and never mark a row `Pass` from the scripted evidence. Report a defect by adding a block from the defect register's template (DEF-0nn) with the ledger row, steps, expected/actual, screenshot path, and tell me; a defect that blocks acceptance gets a bounded fix handoff and a new Code change log entry.
- **Stop / restart** (PowerShell):
  ```powershell
  & C:\Users\nemes\dnd_ai_evidence_20261026\cp11\stack\stop_stack.ps1 -ApiPort 8001 -WebPort 5174
  & C:\Users\nemes\dnd_ai_evidence_20261026\cp11\stack\start_stack.ps1 -DbName dnd_ai_m1415_accept_clean_20261026 -ApiPort 8001 -WebPort 5174
  ```
  Stop the stack before any work that edits `portal/` (Vite serves the working tree with hot reload) and before taking the SR checkpoint copy.
- **Known blockers and open items:** DEF-001 (fix scripted-retested; your acceptance pending), DEF-005 and DEF-006 (fixed, scripted-retested; your acceptance pending), DEF-002, DEF-003, DEF-004 (as in the register); the Blocked cases above; and the human, responsive, keyboard-only and screen-reader checks (TC-55), which no script covered.

## 12. Working `dnd_ai` database: state found on 2026-10-27 (no migration was needed)

The owner authorized migrating the working `dnd_ai` database to the reviewed schema. On inspection **it was already at the reviewed head and holds no worlds or campaigns**, so no migration was applied and nothing in `dnd_ai` was changed. §2's "`dnd_ai` … `138_world_roles_and_use_grants` … unchanged" describes 2026-10-26 16:41 and is out of date.

| Fact | Value |
|---|---|
| Target (from the owner's `.env`, secrets not printed) | `127.0.0.1:5432`, database `dnd_ai`, PostgreSQL 18.4 |
| Revision found | `140_clock_advance_details` = the repository's only head (`138 → 139 → 140`, `139_inventory_capability`, `140_clock_advance_details`); `alembic check`: "No new upgrade operations detected" |
| Contents found | 12 accounts, 11 credential rows, 13 system-role rows, **0 worlds, 0 campaigns, 0 entities, 0 events**: table fingerprint (219 tables, 567 rows) **identical** to the accounts-only baseline (`fp_accept_baseline.json`) and to `fp_new_dnd_ai.json` (taken 2026-10-26 17:42:25) |
| What it held earlier | At 2026-10-26 16:41 it was revision 138 with 3 worlds, 5 campaigns, 124 entities, 57 events, 6 sessions, 12 accounts (218 tables, 2,989 rows). Three dumps of that state exist (`dnd_ai_138_cp11_20261026T164103.dump`, `dnd_ai_138_prereset_20261026T174117.dump`, `dnd_ai_138_prereset2_20261026T174206.dump`); the database was replaced by an accounts-only revision-140 database at about 17:42. Who or what did so is **not recorded in the evidence folder**; this document does not assume |
| Application access | No D&D AI process was running; `pg_stat_activity` showed no sessions on any database |
| Backup of the state found | `…\cp11\dnd_ai_140_current_20261027T065533.dump` (outside the repository, new, not overwriting anything; SHA-256 prefix `b8f7fa6c1f2db771`; archive inspected: 3,441 TOC entries, `dbname: dnd_ai`); restored to `dnd_ai_verify_current_20261027T065533`: fingerprint **identical** to the live database |
| Rehearsal (extra, because the populated data exists only in the old dumps) | `dnd_ai_138_cp11_20261026T164103.dump` restored to `dnd_ai_rehearse_138to140_20261027T065533` (fingerprint identical to `fp_source_pre.json`: 218 tables, 2,989 rows); `alembic upgrade head` ran `138 → 139` and `139 → 140`; `alembic check` clean. Preserved byte-for-byte per table: accounts (12), credentials (11), system roles (13), worlds (3), campaigns (5), entities (124), events (57), sessions (6) and every other table except the three the migrations intend to change: `security.capabilities` 14 → 15, `security.character_relationship_type_capabilities` 22 → 28 (migration 139), and the new table `narrative.clock_advance_details` (migration 140). The live `dnd_ai` fingerprint was identical before and after |
| Grants | On the live database `app_read_write` and the migration roles hold SELECT/INSERT/UPDATE/DELETE on `narrative.clock_advance_details`; `app_read_only` and `integration_worker` hold none, matching the other narrative tables' ownership by `migration_owner` |

**Decision left to the owner.** If the populated 138 data should come back, it requires replacing the current accounts-only `dnd_ai` with a restore of one of the three dumps followed by `uv run alembic -c database/alembic.ini upgrade head` (rehearsed above). That replaces the live database's content and was **not** done, because it was not authorized in terms that cover it; the current contents are accounts-only.

**Separation of evidence.** Testing against `dnd_ai`, or against a populated copy, is separate from the clean-baseline acceptance run on `dnd_ai_m1415_accept_clean_20261026`. No acceptance result is carried between databases, and no ledger result is changed by this section. The accounts-only acceptance database was not touched (fingerprint identical).

**Development servers (normal ports 8000/5173), started by the owner, not by me.** In PowerShell from `C:\Users\nemes\dnd_ai`:
```powershell
# backend (terminal 1): reads DATABASE_URL / DND_AI_* from the repository .env
uv run uvicorn dnd_ai.api.app:app --host 127.0.0.1 --port 8000 --reload
# frontend (terminal 2)
cd portal; npm run dev
```
Open `http://localhost:5173/`. `portal\vite.config.ts` serves 5173 and proxies `/api` (prefix stripped) and `/auth` to `http://localhost:8000`. The `.env` allowed-origin list includes `http://localhost:5173` (and two other origins); `127.0.0.1:5173` is not in it, so use `localhost`. Do not run these while the acceptance stack on 8001/5174 is running unless you want both; they use different databases.


## 13. Working campaign through G: owner-authorized repairs (2026-10-30)

The accounts-only state recorded in §12 was the state on 2026-10-27, not the current contents. The owner has since completed the main guide through G in working `dnd_ai` on `127.0.0.1:5432`, using portal/API `127.0.0.1:5173` / `127.0.0.1:8000`. It contains The Saltmarch and The Drowned Archive. The prepared `dnd_ai_m1415_accept_clean_20261026` database remains without worlds/campaigns and was not changed during this repair run.

At the owner's explicit request, scripted portal UI repairs were followed by a backed-up, audited maintenance transaction for historical corrections unavailable in the UI. The [Step G repair report](PHASE14_15_STEP_G_REPAIR_REPORT.md) separates successful documented UI changes, unsupported historical edits, the exact database corrections, and remaining application findings. Final data/integrity/privacy verification: 36/36 checks; real-browser privacy verification: three personas / 24 UI-generated campaign GET responses. DEF-007 remains a confirmed current-party temporal mismatch; DEF-008 is a future-status semantics observation; DEF-DOC-01 records the missing restore-reason input.

Evidence: `C:/Users/nemes/dnd_ai_evidence_20261026/cp11/ui_db_repairs_20261030/`. The working database now contains explicit repair history. This is separate from clean-baseline acceptance; no human ledger result or owner acceptance decision was changed. Application servers were not restarted or redirected to another database.

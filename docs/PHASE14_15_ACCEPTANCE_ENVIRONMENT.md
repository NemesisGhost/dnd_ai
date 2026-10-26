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
| Portal (currently **stopped**) | `http://127.0.0.1:5174` (Vite from `C:\Users\nemes\dnd_ai\portal`, config `stack\vite.accept.config.mjs`) |
| API | `http://127.0.0.1:8001` (uvicorn, `dnd_ai.api.app:app`, working directory `C:\Users\nemes\dnd_ai`) |
| Proxy | `/api` → `127.0.0.1:8001` (prefix stripped); `/auth` → `127.0.0.1:8001` |
| Database | `dnd_ai_m1415_accept_clean_20261026` (the API's only database connection — checked in `pg_stat_activity`) |
| Allowed browser origin | `http://127.0.0.1:5174` only (`DND_AI_LOCAL_SESSION_ALLOWED_ORIGINS`, set in the child environment; a foreign `Origin` returns 403 — checked) |
| Why `127.0.0.1`, not `localhost` | The session cookie has one fixed name and is host-scoped, not port-scoped; signing in at `localhost:5174` would replace your own `localhost:5173` session |
| Code SHA served | `9ab549d` (the main checkout's source; editable install) |
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
| `docs\PHASE14_15_DEFECT_REGISTER.md` | DEF-001 … 004, blockers, closed items, new-defect template |
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

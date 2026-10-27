# Phase 14/15 acceptance ledger (restarted, CP-11)

**Every row below starts `Unexecuted`.** Historical results in [PHASE14_15_MANUAL_TESTING.md](PHASE14_15_MANUAL_TESTING.md) are preserved there and are not carried over: a prior pass or "executed" marking never becomes a fresh pass. Only a person (or, for the Scripted/Database/Automated columns, the tool named) writing in a row can change it, and only that row's own column.

## Run header (fill in at the start of the human run)

| Field | Value |
|---|---|
| Code SHA under test | `9ab549ddbc78cb9b5c1aac9c99f3a967112edc62` (`phase15/completion`, CP-10 approved head). If this changes, see "Code change rule" below. |
| Schema revision | `140_clock_advance_details` |
| Acceptance database (human run) | `dnd_ai_m1415_accept_clean_20261026` (accounts-only baseline; checkpoint dump `accept_clean_baseline_140.dump`, SHA-256 `38f97db4…1825`) |
| Clean-installation database (TC-56) | `dnd_ai_m1415_clean_install_20261026` (migrated, zero accounts) |
| API / portal | `http://127.0.0.1:8001` / `http://127.0.0.1:5174` (TC-56: 8002 / 5175) |
| Tester; execution dates | |
| Chrome version; NVDA/Narrator version | |
| Viewports used | |
| Owner decision — Phase 14 hierarchy manual acceptance | **Pending** |
| Owner decision — Phase 15 manual acceptance | **Pending** (CP-11 and Phase 15 are not complete until the owner records it) |
| Final-head CI (PR #66) run id and SHA | to be recorded for the frozen head; at preparation: all 10 jobs green on `9ab549ddbc78cb9b5c1aac9c99f3a967112edc62`. The DEF-001 candidate `7990225…` has its own run (see the delivery report); it is not the frozen head |

## Result states and evidence rules

`Unexecuted` · `Pass` · `Fail` · `Blocked` · `Owner-Accepted Exception` (stays visible; needs the owner's written reason).

Each row has **five separate evidence fields**; none may be used to fill another:

| Field | What may be written | Note |
|---|---|---|
| Automated | Test module/run id and result | Never a manual pass |
| Scripted browser | Script name, run id, result, screenshot path | Needs an owner login; see environment doc |
| Database | Read-only query/finding | **Corroborates**; it never proves that the UI workflow passed |
| Human/manual | Tester, date, what was seen, screenshot path | The only field that can produce `Pass` for a UI workflow |
| Accessibility | AT/browser/viewport/zoom and result | Required for TC-55/AX rows |

**Code change rule:** if the code SHA changes after this ledger starts, add a line to "Code change log" below naming the new SHA, the migration revision, and for every result which of *still applies* / *must be rerun*.

## Code change log

| Date | New SHA | Revision | Rows that still apply | Rows that must be rerun |
|---|---|---|---|---|
| 2026-10-26 | `9ab549ddbc78cb9b5c1aac9c99f3a967112edc62` | `140_clock_advance_details` | (baseline — nothing executed yet) | all |
| 2026-10-26 | **Candidate, not frozen:** `7990225af3305d7d7221d0daf068ae1c70199aee` (DEF-001 fix; portal and docs only) | `140_clock_advance_details` (unchanged) | Nothing in this ledger was executed, so there is no result to carry forward or discard. Scripted/automated evidence taken at `9ab549d` is assessed in the environment document §9.1 (backend checks and the signed-out and sign-in scripts apply by diff; portal checks are superseded) | RC-10 (rewritten), RC-03 … RC-09, and the rows listed in the environment document §9.2 — in particular TC-14, 15, 19, 20, 21, 24, 25, 33, 34, 35, 36, 37, 38, 42, 43, 44, 50, 51, 53, SR-M4/5/6/11/12/13, the lifecycle-step rows (TC-10, 16, 17, 18, 26, 28, 29, 31, 32, 39, 40, 47) and TC-55's new-notice announcements. The "Code SHA under test" above is **not** changed until the owner or Codex freezes a reviewed head |
| 2026-10-27 | **Presentation-policy change, awaiting Codex review (not frozen, not a manual-run baseline):** `6cc7baeac41d1470ae8ff890ee535ef577200c7d` (portal and documentation only: unavailable/unauthorized presentation consistency; no backend, authorization, schema or fixture change) | `140_clock_advance_details` (unchanged) | No human result exists to carry forward or discard; **no row is a Pass and none becomes one from this change**. Backend and database evidence still applies (no server change). Scripted evidence taken at `9ab549d`, `38d2865` and `88ee96a` still applies to behavior this change did not touch, but **not** to the pages named on the right. Automated: the portal suite passed on the committed tree (3583 tests; two failures appeared once under full-suite load and passed on rerun; they were not diagnosed at the time, and the reruns do not show them unrelated. The follow-up `83fede25ccf3cb4ac71c9a7f715c5ae25daf11cf` found concrete races in their assertions (see its row) and did not reproduce them); automated results never fill the Human or Accessibility columns. | **Rerun by a person on a build that contains this change, after Codex review:** B2 steps 3–4 and C1 (`/platform/accounts` and `/worlds/new` now show "Access denied", not "Page not found"); D1 and D2 (the gm negative tests: `/worlds/<W>/edit` shows "Editing unavailable" with the role explanation, Sharing shows "Access denied", `/worlds/<W>/calendars/new` and `/worlds/new` show their own reasons; a nonexistent world id shows the neutral "World not available"); C2 and C3 (new timeline, branch, calendar pages: first-read failure versus refusal, a failed branch-point read is not an empty list); E1 and E2 (campaign setup world, timeline and details steps); E6 (world times); G4 (parties); H1 and H2 (session run first read); H7 and H8 (item definitions and items); H10 (encounter page); I2 (event page); J9 and AX-40 (denial matrix and not-found/permission-denied states: new wording and headings); K6 (permission lost mid-edit: unchanged safeguards, re-observe once). **Accessibility retests required (screen reader and keyboard, new behavior):** a terminal heading takes focus once per navigation and is the announcement (no double speech); one `main` landmark on every terminal state, including the edit-world loading and error states; the tab title reads "Access denied · portal", "Not available · portal", "Could not load · portal", "Action unavailable · portal" or "Page not found · portal" and is restored on leaving; "Try again" stays focusable while it reads; recovery links are reachable. No development servers were left running by the change; the owner's 8000/5173 watchers were stopped to edit and must be started manually. |
| 2026-10-27 | **Presentation-policy follow-up, awaiting Codex review (not frozen, not a manual-run baseline):** `83fede25ccf3cb4ac71c9a7f715c5ae25daf11cf` (portal and documentation only, on review baseline `53a8134a4360d49d038384843b6c90df7758e20c`: recovery of required secondary reads and focus after a successful retry; no backend, authorization, schema or fixture change) | `140_clock_advance_details` (unchanged) | No human or accessibility result exists to carry forward or discard; **no row is a Pass and none becomes one from this change**. Backend and database evidence still applies (no server change). Scripted evidence from earlier heads still applies to behavior this change did not touch, but **not** to the event page, the item-definition list and form, the world-times and encounter retry, or the retry controls named on the right. Automated (mocked reads only; nothing run against working dnd_ai): event primary/preview failures alone and together, definition list/options failures alone and together, 404-before-403-before-failure ordering, read-only retry that retries only failed reads, a 401 during retry, scope change between events, focus kept while reading and after repeated failure, focus handed to the heading only for a used retry that still owned focus, no focus move for an unused button, a moved focus or a rerender. The earlier "two failures under load" were examined: `App.unavailableStates` read `document.title` right after a text query, but the title is set by a passive effect that can run after that commit (now awaited); `App.knowledgeClaim` "Next link" asserted the router location synchronously and sampled the request count before the page's reads settled (now awaited). The `App.knowledgeClaim` DEF-006 "access is gone" navigation failure was **not** reproduced (six concurrent loaded runs passed) and no cause was established; it is open, not declared unrelated. Automated results never fill the Human or Accessibility columns. | **Rerun by a person on a build that contains this change, after Codex review:** I2 (event page): open an event whose first reads fail, in each of the three combinations (event only, correction check only, both); the page names the missing part, Try again reads and recovers the Void / Correct controls, a refused or missing check shows a closed notice with no retry; a confirmed void or correction keeps its recovery and refreshed-version behavior (DEF-005/006 unchanged). H7 and H8 (item definitions and items): list failed, category options failed, both; the category filter is absent with an explanation, never an empty list of categories. E6 (world times) and H10 (encounter page): Try again reads only what failed. D1 and D2 (gm persona): Sharing shows exactly the 403 access explanation ("You do not have access to the sharing list."); a missing or hidden world shows the neutral 404 text. All earlier retests of the prior presentation-policy row still apply. **Accessibility retests required (screen reader and keyboard):** after a successful Try again on the page error, the event correction panel and the stale-read notices, focus lands on the page heading (once, announced as a heading), never on the document body; while reading and after a failed retry, focus stays on the button; moving focus elsewhere during the read is respected. No development servers were left running by the change; they remain stopped for the owner to start manually. |

## Record register (copy IDs from the address bar; never record links, tokens or passwords)

| Name | Id / URL path | Created in task |
|---|---|---|
| World The Saltmarch (W), slug | | C1 |
| Timelines Main Timeline (T1), What If Timeline (T2) | | C1, C2 |
| Campaign The Drowned Archive (C) | | E2 |
| Membership ids: gm, player_a, player_b, observer | | E4 |
| Times T0–T4, Between bells | | E6 |
| Places, organizations, religion, NPC, PCs | | F, G |
| Parties; sessions S1, S2; quest; claims K1…; dungeon/areas; items; encounters; sources | | G–H |
| Branch timeline/campaign; Empty Marsh slug | | K3, K4 |

## Preparation evidence (not case results)

These were executed during CP-11 preparation on `9ab549ddbc78cb9b5c1aac9c99f3a967112edc62`. They corroborate readiness; **none of them marks any row below**.

| ID | What | Result |
|---|---|---|
| P-1 | Source `dnd_ai` backup: `pg_dump -Fc` (SHA-256 `67a53727…b601`), TOC read, disposable restore, per-table fingerprints identical (218 tables / 2,989 rows) | Done |
| P-2 | Accept DB migrated `136→140`; `alembic check` clean; account manifest imported transactionally (12 users, 11 identities, 11 credentials, 13 system-role rows) | Done |
| P-3 | Source unchanged after copy (fingerprint identical before/after) | Done |
| P-4 | `verify.sh full`: ruff format/check, mypy, foundry tests PASS; `pytest tests/unit` 1,204 passed, 1 failed (`test_local_session_allowed_origins_defaults_to_dev_topology_outside_production` — environmental, see DEF-003) | See defect register |
| P-5 | Portal `eslint .` and `tsc -b && vite build` | PASS (exit 0) |
| P-6 | Scripted signed-out browser check (`scripted/signed_out_check.mjs`, Chrome 155, headless): 16/16 assertions pass; no credential used | Done — recorded only in the Scripted column of TC-01, 49.signed-out, 54.csrf, AX-39 |
| P-7 | `pytest tests/database` 5,457 passed; `pytest tests/scenario` 117 passed; portal vitest 3,485 passed (360 files) | Done |
| P-8 | Scripted sign-in and Tasks A1, A3, B1, B2, C1, D1, D2 (partial) on the **disposable copy** `dnd_ai_m1415_accept_scripted_20261026` using the owner-designated `.env` passwords (never printed). Scripted column only; the human baseline database was not touched | Done |

## Rows — original cases TC-01 … TC-58

| ID | Case / variant | Task | Persona | Result | Automated | Scripted browser | Database | Human/manual | Accessibility | Code SHA @ schema | Fixture / checkpoint | Defect | Expected vs actual / evidence |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| TC-01 | Administrator baseline and login return | A1, A2, A3 | admin, disabled | Unexecuted | — | SO-01/02: signed-out deep link lands on Sign In (signed_out_check, 2026-10-26); return-after-login not tested (needs a credential) | — | — | — | — | — | — | |
| TC-02 | Live account permissions and campaign lists | A1, B2 | all five + disabled | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-03 | Hierarchy and stable Worlds navigation | J4 | admin, gm, player_a | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-04 | Campaign-derived world visibility and creation eligibility | B2, C1, D2 | admin, gm, player_a | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-05 | World categories, counts and browse-state persistence | J4 | gm, player_a | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-06 | Collapsed party disclosure | G4 | player_a, admin | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-07 | Player Knowledge = character knowledge plus eligible parties | J3 | player_a, player_b | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-08 | Public Knowledge, no character, timeline separation | J3 | observer | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-09 | Member preview vs member's own view | J5 | gm vs player_a | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-10 | Draft, archive, supersession and scope boundaries | K1 | admin, player_a | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-11 | Create isolated world, timeline and campaign | C1, C2, E2, E3 | admin | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-12 | Setup cancellation and recovery | E1 | admin | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-13 | Enrol members, separate campaign roles | E4, E5 | admin, gm, player_a, player_b, observer | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-14 | Calendar dates and world-time points | C3, E6 | admin, gm | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-15 | Advance and correct the campaign clock | E7, I3 | gm, player_a | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-16 | Location types, hierarchy and reparenting | F1, F2 | gm | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-17 | Organizations, subtype fields, religion references | F3 | gm, player_a | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-18 | NPC/PC identity, publishing, character relationships | F4, G1, G2 | gm, admin, players | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-19 | Immutable builds, starting state, activation | G3 | gm, player_a | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-20 | Party create/edit, archive/restore | G4 | gm, player_a | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-21 | Temporal party membership, overlap | G4 | gm, players | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-22 | Schedule/edit sessions and participant preparation | H1, J2, K7 | gm, players | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-23 | Staged Run Session navigation, unsaved inputs | H2 | gm | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-24 | Start session, world-time bar, public/private log | I1 | gm, player_a | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-25 | Manual event record, void and correction | I2 | gm, player_a | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-26 | Quest definition | H3 | gm, player_a | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-27 | Quest runtime scopes, completion, correction | I5 | gm, player_a | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-28 | Knowledge creation, guided navigation, unsaved claim edits | H4 | gm | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-29 | Claim review/publication, rejection, unpublished subject | H4 | gm | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-30 | Party reveal, learning, telling, belief, public | I6 | gm, players | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-31 | Archived and superseded claims keep knowledge | K2 | gm, player_a | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-32 | Claim Sources, separate keys, navigation guard | H4 | gm | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-33 | Dungeon, areas, connections, content | H5 | gm | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-34 | Dungeon runtime state and correction | I7 | gm, player_a | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-35 | Relationships and participant perspectives | G6 | gm, player_a | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-36 | Organization members, offices, operational status | G7 | gm, player_a | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-37 | Routes and travel | H6, I4 | gm, player_a | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-38 | NPC portrayal, runtime, privacy | H9, I9 | gm, player_a | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-39 | World-owned item definitions, generic seed protection | H7 | gm, player_a | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-40 | Item instances: award, transfer, equip, custody | H8, I8, G5 | gm, players | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-41 | Item quantity, damage/repair, attunement, destruction | I8 | gm | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-42 | Encounter preparation and compact roster | H10 | gm | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-43 | Operate an encounter | I10 | gm | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-44 | Discard pending, abort active | I10 | gm | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-45 | Sources and provenance across typed records | H11 | gm, player_a | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-46 | Revision history and comparison | J6 | gm | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-47 | Review queue and lifecycle transitions | J7 | gm, player_a | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-48 | Validation, stale writes, retry, no-store | K5 | gm, admin | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-49 | Plain-player denial matrix | J9, K3 | player_a, observer, signed-out | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-50 | End session, review, read-only, archive/restore | I11, J1, J2 | gm, players | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-51 | Campaign, timeline, world archive/restore guards | K4 | admin, player_a | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-52 | Timeline branch boundaries | K3 | admin, gm, player_a | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-53 | Explicit world_viewer without campaign membership | Companion 5 | observer, admin | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-54 | CSRF, signed-out requests, current authority | K6 | gm, admin | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-55 | Responsive, keyboard, screen-reader, zoom, reduced-motion | Companion 6 | all | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-56 | Clean-deployment walkthrough | Companion 7 | admin + manual.player (clean DB) | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-57 | Manual privacy evidence: audit, receipts, reporting role | J8 | admin + DB read-only | Unexecuted | — | — | — | — | — | — | — | — | |
| TC-58 | Targeted claim grants/denies and preview agreement | K8 | admin, observer, player_a | Unexecuted | — | — | — | — | — | — | — | — | |

## Rows — variants and amended expectations

| ID | Case / variant | Task | Persona | Result | Automated | Scripted browser | Database | Human/manual | Accessibility | Code SHA @ schema | Fixture / checkpoint | Defect | Expected vs actual / evidence |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 02.gm | TC-02: `gm` campaign list/capabilities: none yet, then after E4 | B2/E4 | gm | Unexecuted | — | — | — | — | — | — | — | — | |
| 02.player_a | TC-02: `player_a` lists and perspectives | B2/G2 | player_a | Unexecuted | — | — | — | — | — | — | — | — | |
| 02.player_b | TC-02: `player_b` lists and perspectives | B2/G2 | player_b | Unexecuted | — | — | — | — | — | — | — | — | |
| 02.observer | TC-02: `observer` lists, no perspective | B2/E4 | observer | Unexecuted | — | — | — | — | — | — | — | — | |
| 02.disabled | TC-02: `disabled` safe login refusal | A3 | disabled | Unexecuted | — | — | — | — | — | — | — | — | |
| 04.gm-no-create | TC-04: `gm` (Player only) gets no World create form | B2 | gm | Unexecuted | — | — | — | — | — | — | — | — | |
| 10.draft | TC-10: Draft definition = same 404 as missing for a player (amended) | K1 | player_a | Unexecuted | — | — | — | — | — | — | — | — | |
| 10.archived | TC-10: Archived/superseded published readable by reference (amended) | K1 | player_a | Unexecuted | — | — | — | — | — | — | — | — | |
| 10.cross-scope | TC-10: Same-world other-timeline records unreadable; foreign campaign refused | K3 | admin, player_a | Unexecuted | — | — | — | — | — | — | — | — | |
| 15.manual | TC-15: Plain manual advance + correction (E7) | E7 | gm | Unexecuted | — | — | — | — | — | — | — | — | |
| 15.cause | TC-15: Optional cause + member-safe explanation (CP-9b) | I3 | gm, player_a, observer | Unexecuted | — | — | — | — | — | — | — | — | |
| 15.runtime-no-world-role | TC-15: Runtime GM advance without world role (SR-M8) | Companion SR-M8 | gm | Unexecuted | — | — | — | — | — | — | — | — | |
| 19.explain | TC-19: Build-activation event explanation by audience (CP-9a/DR-6) | G3 | gm, player_a, observer | Unexecuted | — | — | — | — | — | — | — | — | |
| 19.other-characters | TC-19: Hero B / NPC starting state and builds | G3 | gm | Unexecuted | — | — | — | — | — | — | — | — | |
| 21.explain | TC-21: Join/leave explanation (CP-9a) | G4 | gm, players | Unexecuted | — | — | — | — | — | — | — | — | |
| 21.leave-rejoin | TC-21: Tobin leaves and rejoins | G4 | gm | Unexecuted | — | — | — | — | — | — | — | — | |
| 21.npc-reserve | TC-21: NPC membership of Reserve | G4 | gm | Unexecuted | — | — | — | — | — | — | — | — | |
| 22.roles | TC-22: Compatible roles, accurate rejection, no Guest default for PC (CP-1) | H1 | gm | Unexecuted | — | — | — | — | — | — | — | — | |
| 22.roster-gm | TC-22: Roster section on session detail/run/review (CP-3) | H1/H2 | gm | Unexecuted | — | — | — | — | — | — | — | — | |
| 22.member-pc | TC-22: Member roster: player with related PC (CP-8) | J2 | player_a | Unexecuted | — | — | — | — | — | — | — | — | |
| 22.member-npc | TC-22: Member roster: discoverable NPC link rules | J2 | player_a, player_b | Unexecuted | — | — | — | — | — | — | — | — | |
| 22.member-undiscovered | TC-22: Undiscovered NPC absent, no hidden count (API-ONLY grant) | K7 | player_a, player_b | Unexecuted | — | — | — | — | — | — | — | — | |
| 22.member-observer | TC-22: Member roster: observer | J2 | observer | Unexecuted | — | — | — | — | — | — | — | — | |
| 25.wrong-title | TC-25: 'Wrong title' correction replacement variant (CP-9a) | I2 | gm, player_a | Unexecuted | — | — | — | — | — | — | — | — | |
| 25.void | TC-25: Void with confirm/cancel | I2 | gm | Unexecuted | — | — | — | — | — | — | — | — | |
| 31.browse | TC-31: Archive browse Active/Archived/All, eligibility, paging (CP-7) | K2 | gm, player_a | Unexecuted | — | — | — | — | — | — | — | — | |
| 31.archived-direct | TC-31: Archived claim direct read by audience member (DR-1) | K2 | player_a | Unexecuted | — | — | — | — | — | — | — | — | |
| 31.supersede | TC-31: Supersede, replacement inherits no knowers | K2 | gm | Unexecuted | — | — | — | — | — | — | — | — | |
| 38.resource-positive | TC-38: Positive NPC resource adjustment (no supported fixture) — expected Blocked | I9 | gm | Unexecuted | — | — | — | — | — | — | — | — | |
| 38.resource-refusal | TC-38: Missing tracked-resource refusal | I9 | gm | Unexecuted | — | — | — | — | — | — | — | — | |
| 40.owner-inventory | TC-40: Owner inventory reachable via character nav (CP-5) | G5/I8 | player_a | Unexecuted | — | — | — | — | — | — | — | — | |
| 40.viewer-inventory | TC-40: Viewer inventory-only view (CP-6) | Companion SR-M15 | observer | Unexecuted | — | — | — | — | — | — | — | — | |
| 49.01 | TC-49: Location/organization/religion authoring routes | J9 | player_a | Unexecuted | — | — | — | — | — | — | — | — | |
| 49.02 | TC-49: NPC/PC/builds/portrayal routes | J9 | player_a | Unexecuted | — | — | — | — | — | — | — | — | |
| 49.03 | TC-49: Party management routes | J9 | player_a | Unexecuted | — | — | — | — | — | — | — | — | |
| 49.04 | TC-49: Session/encounter operation routes | J9 | player_a | Unexecuted | — | — | — | — | — | — | — | — | |
| 49.05 | TC-49: Events/quest operation routes | J9 | player_a | Unexecuted | — | — | — | — | — | — | — | — | |
| 49.06 | TC-49: Knowledge authoring/management routes (legacy redirects to read-only claim) | J9 | player_a | Unexecuted | — | — | — | — | — | — | — | — | |
| 49.07 | TC-49: Dungeon authoring routes | J9 | player_a | Unexecuted | — | — | — | — | — | — | — | — | |
| 49.08 | TC-49: Items/definitions routes | J9 | player_a | Unexecuted | — | — | — | — | — | — | — | — | |
| 49.09 | TC-49: Sources/revisions/review routes | J9 | player_a | Unexecuted | — | — | — | — | — | — | — | — | |
| 49.10 | TC-49: Time authoring route | J9 | player_a | Unexecuted | — | — | — | — | — | — | — | — | |
| 49.11 | TC-49: New surfaces: Sharing, world edit, Platform accounts | J9 | player_a | Unexecuted | — | — | — | — | — | — | — | — | |
| 49.observer | TC-49: Representative denied routes as observer | J9 | observer | Unexecuted | — | — | — | — | — | — | — | — | |
| 49.signed-out | TC-49: Representative denied routes signed out | J9 | signed-out | Unexecuted | — | SO-03/04/05/06: signed-out GM/platform/world routes land on Sign In; SO-07/08 API 401 (2026-10-26) | — | — | — | — | — | — | |
| 49.foreign | TC-49: Foreign campaign (branch campaign) and nonexistent campaign | K3 | player_a | Unexecuted | — | — | — | — | — | — | — | — | |
| 50.completed | TC-50: Completed/archived read-only; archive/restore | J1 | gm, player_a | Unexecuted | — | — | — | — | — | — | — | — | |
| 50.roster | TC-50: Member roster on the completed detail | J2 | players | Unexecuted | — | — | — | — | — | — | — | — | |
| 54.csrf | TC-54: Missing/invalid CSRF, foreign Origin, signed-out 401 | K6 | gm | Unexecuted | — | SO-09 foreign Origin refused 403; SO-10 signed-out mutation 401 (2026-10-26); CSRF-header and role-revocation parts need a login | — | — | — | — | — | — | |
| 54.campaign-role | TC-54: Campaign GM role revoked before next request | K6 | gm, admin | Unexecuted | — | — | — | — | — | — | — | — | |
| 54.world-role | TC-54: World Editor role ended before next request | K6 | gm, admin | Unexecuted | — | — | — | — | — | — | — | — | |
| 54.use-grant | TC-54: Use-grant / system-GM revocation on next request | Companion SR-M6/M7 | admin | Unexecuted | — | — | — | — | — | — | — | — | |
| 57.receipts | TC-57: Typed-content receipts minimal | J8 | admin | Unexecuted | — | — | — | — | — | — | — | — | |
| 57.audit | TC-57: Audit/replay bodies hold no narrative markers (DB read-only) | J8 | admin | Unexecuted | — | — | — | — | — | — | — | — | |
| 57.sensitive-read | TC-57: Metadata-only sensitive_read audit entries | J8 | admin | Unexecuted | — | — | — | — | — | — | — | — | |
| 57.reporting-role | TC-57: Reporting role allowlist boundary (DB read-only) | J8 | admin | Unexecuted | — | — | — | — | — | — | — | — | |
| 58.allow | TC-58: Targeted canon allow (API-ONLY) | K8 | observer | Unexecuted | — | — | — | — | — | — | — | — | |
| 58.deny | TC-58: Targeted view deny (API-ONLY) and preview agreement | K8 | player_a | Unexecuted | — | — | — | — | — | — | — | — | |
| 58.revoke | TC-58: Revocation restores projection | K8 | observer, player_a | Unexecuted | — | — | — | — | — | — | — | — | |
| T56-01 | TC-56: Clean-install walkthrough step 1 (separate DB) | Companion 7 | admin, manual.player | Unexecuted | — | — | — | — | — | — | — | — | |
| T56-02 | TC-56: Clean-install walkthrough step 2 (separate DB) | Companion 7 | admin, manual.player | Unexecuted | — | — | — | — | — | — | — | — | |
| T56-03 | TC-56: Clean-install walkthrough step 3 (separate DB) | Companion 7 | admin, manual.player | Unexecuted | — | — | — | — | — | — | — | — | |
| T56-04 | TC-56: Clean-install walkthrough step 4 (separate DB) | Companion 7 | admin, manual.player | Unexecuted | — | — | — | — | — | — | — | — | |
| T56-05 | TC-56: Clean-install walkthrough step 5 (separate DB) | Companion 7 | admin, manual.player | Unexecuted | — | — | — | — | — | — | — | — | |
| T56-06 | TC-56: Clean-install walkthrough step 6 (separate DB) | Companion 7 | admin, manual.player | Unexecuted | — | — | — | — | — | — | — | — | |
| T56-07 | TC-56: Clean-install walkthrough step 7 (separate DB) | Companion 7 | admin, manual.player | Unexecuted | — | — | — | — | — | — | — | — | |
| T56-08 | TC-56: Clean-install walkthrough step 8 (separate DB) | Companion 7 | admin, manual.player | Unexecuted | — | — | — | — | — | — | — | — | |
| T56-09 | TC-56: Clean-install walkthrough step 9 (separate DB) | Companion 7 | admin, manual.player | Unexecuted | — | — | — | — | — | — | — | — | |
| T56-10 | TC-56: Clean-install walkthrough step 10 (separate DB) | Companion 7 | admin, manual.player | Unexecuted | — | — | — | — | — | — | — | — | |
| T56-11 | TC-56: Clean-install walkthrough step 11 (separate DB) | Companion 7 | admin, manual.player | Unexecuted | — | — | — | — | — | — | — | — | |
| T56-12 | TC-56: Clean-install walkthrough step 12 (separate DB) | Companion 7 | admin, manual.player | Unexecuted | — | — | — | — | — | — | — | — | |
| T56-13 | TC-56: Clean-install walkthrough step 13 (separate DB) | Companion 7 | admin, manual.player | Unexecuted | — | — | — | — | — | — | — | — | |
| T56-14 | TC-56: Clean-install walkthrough step 14 (separate DB) | Companion 7 | admin, manual.player | Unexecuted | — | — | — | — | — | — | — | — | |
| T56-15 | TC-56: Clean-install walkthrough step 15 (separate DB) | Companion 7 | admin, manual.player | Unexecuted | — | — | — | — | — | — | — | — | |
| T56-16 | TC-56: Clean-install walkthrough step 16 (separate DB) | Companion 7 | admin, manual.player | Unexecuted | — | — | — | — | — | — | — | — | |

## Rows — scoped-role scenarios (SR-M)

| ID | Case / variant | Task | Persona | Result | Automated | Scripted browser | Database | Human/manual | Accessibility | Code SHA @ schema | Fixture / checkpoint | Defect | Expected vs actual / evidence |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| SR-M1 | Admin creates GM-only account; GM signs in | Companion §1 | see scenario | Unexecuted | — | — | — | — | — | — | — | — | |
| SR-M2 | Admin-only account | Companion §1 | see scenario | Unexecuted | — | — | — | — | — | — | — | — | |
| SR-M3 | Populated-upgrade identities (accounts-only baseline) | Companion §1 | see scenario | Unexecuted | — | — | — | — | — | — | — | — | |
| SR-M4 | Editor vs Reviewer vs both | Companion §1 | see scenario | Unexecuted | — | — | — | — | — | — | — | — | |
| SR-M5 | Reader vs Viewer | Companion §1 | see scenario | Unexecuted | — | — | — | — | — | — | — | — | |
| SR-M6 | Use-grant hosting | Companion §1 | see scenario | Unexecuted | — | — | — | — | — | — | — | — | |
| SR-M7 | Revoke then restore system GM from an Owner | Companion §1 | see scenario | Unexecuted | — | — | — | — | — | — | — | — | |
| SR-M8 | Campaign-only GM in a shared world | Companion §1 | see scenario | Unexecuted | — | — | — | — | — | — | — | — | |
| SR-M9 | Same person GM in A, Player in B | Companion §1 | see scenario | Unexecuted | — | — | — | — | — | — | — | — | |
| SR-M10 | Invitation and account split | Companion §1 | see scenario | Unexecuted | — | — | — | — | — | — | — | — | |
| SR-M11 | World and campaign ownership transfer | Companion §1 | see scenario | Unexecuted | — | — | — | — | — | — | — | — | |
| SR-M12 | Stranding and recovery | Companion §1 | see scenario | Unexecuted | — | — | — | — | — | — | — | — | |
| SR-M13 | Permission loss mid-edit | Companion §1 | see scenario | Unexecuted | — | — | — | — | — | — | — | — | |
| SR-M14 | Offline upgrade with a stale tab (expected Blocked) | Companion §1 | see scenario | Unexecuted | — | — | — | — | — | — | — | — | |
| SR-M15 | Viewer inventory | Companion §1 | see scenario | Unexecuted | — | — | — | — | — | — | — | — | |
| SR-M16 | Character record navigation | Companion §1 | see scenario | Unexecuted | — | — | — | — | — | — | — | — | |

## Rows — recovery (RC), navigation (NV), privacy (PV)

| ID | Case / variant | Task | Persona | Result | Automated | Scripted browser | Database | Human/manual | Accessibility | Code SHA @ schema | Fixture / checkpoint | Defect | Expected vs actual / evidence |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| RC-01 | Validation refusal retains input | Companion §2 | gm / admin | Unexecuted | — | — | — | — | — | — | — | — | |
| RC-02 | Stale version, Load latest | Companion §2 | gm / admin | Unexecuted | — | — | — | — | — | — | — | — | |
| RC-03 | Uncertain retry keeps original payload and key | Companion §2 | gm / admin | Unexecuted | — | — | — | — | — | — | — | — | |
| RC-04 | Quest command confirmed, re-read fails | Companion §2 | gm / admin | Unexecuted | — | — | — | — | — | — | — | — | |
| RC-05 | Item operation/definition edit, re-read fails | Companion §2 | gm / admin | Unexecuted | — | — | — | — | — | — | — | — | |
| RC-06 | Claim save, detail read fails | Companion §2 | gm / admin | Unexecuted | — | — | — | — | — | — | — | — | |
| RC-07 | Claim lifecycle step, read-back fails | Companion §2 | gm / admin | Unexecuted | — | — | — | — | — | — | — | — | |
| RC-08 | Receipt-version gating, read-only recovery | Companion §2 | gm / admin | Unexecuted | — | — | — | — | — | — | — | — | |
| RC-09 | Independent drafts, record changes, late responses | Companion §2 | gm / admin | Unexecuted | — | — | — | — | — | — | — | — | |
| RC-10 | Callers fixed for DEF-001 (26 operations; retest on the reviewed head) | Companion §2 | gm / admin | Unexecuted | — | — | — | — | — | — | — | — | |
| NV-01 | Deep links | Companion §3 | gm, players | Unexecuted | — | — | — | — | — | — | — | — | |
| NV-02 | Section links | Companion §3 | gm, players | Unexecuted | — | — | — | — | — | — | — | — | |
| NV-03 | Breadcrumbs | Companion §3 | gm, players | Unexecuted | — | — | — | — | — | — | — | — | |
| NV-04 | Back/Forward and reload | Companion §3 | gm, players | Unexecuted | — | — | — | — | — | — | — | — | |
| NV-05 | Preserved filters and return context | Companion §3 | gm, players | Unexecuted | — | — | — | — | — | — | — | — | |
| NV-06 | World / Characters / Items entry paths | Companion §3 | gm, players | Unexecuted | — | — | — | — | — | — | — | — | |
| NV-07 | Focus after navigation | Companion §3 | gm, players | Unexecuted | — | — | — | — | — | — | — | — | |
| NV-08 | Permission-loss fallback focus | Companion §3 | gm, players | Unexecuted | — | — | — | — | — | — | — | — | |
| PV-01 | Platform authority (UI + data) | Companion §4 | players, observer | Unexecuted | — | — | — | — | — | — | — | — | |
| PV-02 | World authority | Companion §4 | players, observer | Unexecuted | — | — | — | — | — | — | — | — | |
| PV-03 | Campaign authority and foreign campaign | Companion §4 | players, observer | Unexecuted | — | — | — | — | — | — | — | — | |
| PV-04 | Ownership and inventory | Companion §4 | players, observer | Unexecuted | — | — | — | — | — | — | — | — | |
| PV-05 | Targeted deny and preview agreement | Companion §4 | players, observer | Unexecuted | — | — | — | — | — | — | — | — | |
| PV-06 | Revocation and unavailable records | Companion §4 | players, observer | Unexecuted | — | — | — | — | — | — | — | — | |
| PV-07 | Member-safe rosters, history, explanations, clock details | Companion §4 | players, observer | Unexecuted | — | — | — | — | — | — | — | — | |
| PV-08 | No legacy private-text disclosure | Companion §4 | players, observer | Unexecuted | — | — | — | — | — | — | — | — | |

## Rows — accessibility and layout (TC-55)

One row per page/panel. Rows 1–24 are the existing acceptance matrix; 25–40 are the new final layouts. Record widths 390/1280/2560, keyboard, screen reader, 200 % zoom and reduced motion in the Accessibility field.

| ID | Case / variant | Task | Persona | Result | Automated | Scripted browser | Database | Human/manual | Accessibility | Code SHA @ schema | Fixture / checkpoint | Defect | Expected vs actual / evidence |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| AX-01 | Calendar creation | Companion §6 | gm / player_a / observer | Unexecuted | — | — | — | — | — | — | — | — | |
| AX-02 | World times and clock card | Companion §6 | gm / player_a / observer | Unexecuted | — | — | — | — | — | — | — | — | |
| AX-03 | Location create/edit | Companion §6 | gm / player_a / observer | Unexecuted | — | — | — | — | — | — | — | — | |
| AX-04 | Organization and religion create/edit | Companion §6 | gm / player_a / observer | Unexecuted | — | — | — | — | — | — | — | — | |
| AX-05 | NPC and PC create/edit | Companion §6 | gm / player_a / observer | Unexecuted | — | — | — | — | — | — | — | — | |
| AX-06 | Character builds | Companion §6 | gm / player_a / observer | Unexecuted | — | — | — | — | — | — | — | — | |
| AX-07 | NPC portrayal and Run this NPC | Companion §6 | gm / player_a / observer | Unexecuted | — | — | — | — | — | — | — | — | |
| AX-08 | Parties and members | Companion §6 | gm / player_a / observer | Unexecuted | — | — | — | — | — | — | — | — | |
| AX-09 | Session create/edit | Companion §6 | gm / player_a / observer | Unexecuted | — | — | — | — | — | — | — | — | |
| AX-10 | Session run page | Companion §6 | gm / player_a / observer | Unexecuted | — | — | — | — | — | — | — | — | |
| AX-11 | Events record/correct | Companion §6 | gm / player_a / observer | Unexecuted | — | — | — | — | — | — | — | — | |
| AX-12 | Quest editor and progress | Companion §6 | gm / player_a / observer | Unexecuted | — | — | — | — | — | — | — | — | |
| AX-13 | Knowledge claim page and New claim | Companion §6 | gm / player_a / observer | Unexecuted | — | — | — | — | — | — | — | — | |
| AX-14 | Dungeon, areas, connections, state | Companion §6 | gm / player_a / observer | Unexecuted | — | — | — | — | — | — | — | — | |
| AX-15 | Relationships | Companion §6 | gm / player_a / observer | Unexecuted | — | — | — | — | — | — | — | — | |
| AX-16 | Organization members and offices | Companion §6 | gm / player_a / observer | Unexecuted | — | — | — | — | — | — | — | — | |
| AX-17 | Item definitions | Companion §6 | gm / player_a / observer | Unexecuted | — | — | — | — | — | — | — | — | |
| AX-18 | Items, Run this item, inventories | Companion §6 | gm / player_a / observer | Unexecuted | — | — | — | — | — | — | — | — | |
| AX-19 | Encounter preparation/operation | Companion §6 | gm / player_a / observer | Unexecuted | — | — | — | — | — | — | — | — | |
| AX-20 | Sources and provenance | Companion §6 | gm / player_a / observer | Unexecuted | — | — | — | — | — | — | — | — | |
| AX-21 | Review queue | Companion §6 | gm / player_a / observer | Unexecuted | — | — | — | — | — | — | — | — | |
| AX-22 | Revision history/comparison | Companion §6 | gm / player_a / observer | Unexecuted | — | — | — | — | — | — | — | — | |
| AX-23 | Lifecycle panel | Companion §6 | gm / player_a / observer | Unexecuted | — | — | — | — | — | — | — | — | |
| AX-24 | Sidebar and navigation (GM and player) | Companion §6 | gm / player_a / observer | Unexecuted | — | — | — | — | — | — | — | — | |
| AX-25 | World Sharing | Companion §6 | gm / player_a / observer | Unexecuted | — | — | — | — | — | — | — | — | |
| AX-26 | Platform accounts / system-role editor | Companion §6 | gm / player_a / observer | Unexecuted | — | — | — | — | — | — | — | — | |
| AX-27 | Character record navigation | Companion §6 | gm / player_a / observer | Unexecuted | — | — | — | — | — | — | — | — | |
| AX-28 | Session roster (GM and member) | Companion §6 | gm / player_a / observer | Unexecuted | — | — | — | — | — | — | — | — | |
| AX-29 | Knowledge archive filter | Companion §6 | gm / player_a / observer | Unexecuted | — | — | — | — | — | — | — | — | |
| AX-30 | Event explanation | Companion §6 | gm / player_a / observer | Unexecuted | — | — | — | — | — | — | — | — | |
| AX-31 | Clock cause form | Companion §6 | gm / player_a / observer | Unexecuted | — | — | — | — | — | — | — | — | |
| AX-32 | Member preview | Companion §6 | gm / player_a / observer | Unexecuted | — | — | — | — | — | — | — | — | |
| AX-33 | All worlds / Timelines / hierarchy context | Companion §6 | gm / player_a / observer | Unexecuted | — | — | — | — | — | — | — | — | |
| AX-34 | World category counts and browse | Companion §6 | gm / player_a / observer | Unexecuted | — | — | — | — | — | — | — | — | |
| AX-35 | Parties disclosure | Companion §6 | gm / player_a / observer | Unexecuted | — | — | — | — | — | — | — | — | |
| AX-36 | Campaign access / invitations | Companion §6 | gm / player_a / observer | Unexecuted | — | — | — | — | — | — | — | — | |
| AX-37 | Campaign settings | Companion §6 | gm / player_a / observer | Unexecuted | — | — | — | — | — | — | — | — | |
| AX-38 | Home and clock card (member) | Companion §6 | gm / player_a / observer | Unexecuted | — | — | — | — | — | — | — | — | |
| AX-39 | Login and account pages | Companion §6 | gm / player_a / observer | Unexecuted | — | SO-11: Sign In page has no horizontal page scroll at 390/1280/2560 (layout only; not an AT or keyboard result) | — | — | — | — | — | — | |
| AX-40 | Not-found / permission-denied states | Companion §6 | gm / player_a / observer | Unexecuted | — | — | — | — | — | — | — | — | |

## Rows — guide tasks (each task is a roll-up of its cases; set it only after its cases are recorded)

| ID | Case / variant | Task | Persona | Result | Automated | Scripted browser | Database | Human/manual | Accessibility | Code SHA @ schema | Fixture / checkpoint | Defect | Expected vs actual / evidence |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| L-A1 | Task A1 complete as written | A1 | see task | Unexecuted | — | scripted copy DB (accept_scripted, 8002/5175): admin/gm/player_a/player_b/observer all sign in; /auth/session roles admin+gm vs player; admin caps accounts.manage, campaign.host, world.create (2026-10-26) | — | — | — | — | — | — | |
| L-A2 | Task A2 complete as written | A2 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-A3 | Task A3 complete as written | A3 | see task | Unexecuted | — | scripted: disabled and unknown login both stay on Sign In with the identical text 'The login name or password is incorrect.' | — | — | — | — | — | — | |
| L-B1 | Task B1 complete as written | B1 | see task | Unexecuted | — | scripted: Platform accounts shows 12 rows, statuses and roles as the guide table | — | — | — | — | — | — | |
| L-B2 | Task B2 complete as written | B2 | see task | Unexecuted | — | scripted: gm/player_a/player_b/observer refused on /platform/accounts, no world form on /worlds/new, no worlds listed; gm empty-state text differs from admin's (guide updated) | — | — | — | — | — | — | |
| L-C1 | Task C1 complete as written | C1 | see task | Unexecuted | — | scripted: admin creates The Saltmarch + Main Timeline through the form; gm cannot see it before sharing | — | — | — | — | — | — | |
| L-C2 | Task C2 complete as written | C2 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-C3 | Task C3 complete as written | C3 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-C4 | Task C4 complete as written | C4 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-D1 | Task D1 complete as written | D1 | see task | Unexecuted | — | scripted: Sharing shows Administrator Owner; gm refused on /sharing | — | — | — | — | — | — | |
| L-D2 | Task D2 complete as written | D2 | see task | Unexecuted | — | scripted (partial, script defect on Reviewer): gm given Editor; gm then lists the world as View only/Editor | — | — | — | — | — | — | |
| L-E1 | Task E1 complete as written | E1 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-E2 | Task E2 complete as written | E2 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-E3 | Task E3 complete as written | E3 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-E4 | Task E4 complete as written | E4 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-E5 | Task E5 complete as written | E5 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-E6 | Task E6 complete as written | E6 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-E7 | Task E7 complete as written | E7 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-F1 | Task F1 complete as written | F1 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-F2 | Task F2 complete as written | F2 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-F3 | Task F3 complete as written | F3 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-F4 | Task F4 complete as written | F4 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-G1 | Task G1 complete as written | G1 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-G2 | Task G2 complete as written | G2 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-G3 | Task G3 complete as written | G3 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-G4 | Task G4 complete as written | G4 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-G5 | Task G5 complete as written | G5 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-G6 | Task G6 complete as written | G6 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-G7 | Task G7 complete as written | G7 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-H1 | Task H1 complete as written | H1 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-H2 | Task H2 complete as written | H2 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-H3 | Task H3 complete as written | H3 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-H4 | Task H4 complete as written | H4 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-H5 | Task H5 complete as written | H5 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-H6 | Task H6 complete as written | H6 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-H7 | Task H7 complete as written | H7 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-H8 | Task H8 complete as written | H8 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-H9 | Task H9 complete as written | H9 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-H10 | Task H10 complete as written | H10 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-H11 | Task H11 complete as written | H11 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-I1 | Task I1 complete as written | I1 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-I2 | Task I2 complete as written | I2 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-I3 | Task I3 complete as written | I3 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-I4 | Task I4 complete as written | I4 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-I5 | Task I5 complete as written | I5 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-I6 | Task I6 complete as written | I6 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-I7 | Task I7 complete as written | I7 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-I8 | Task I8 complete as written | I8 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-I9 | Task I9 complete as written | I9 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-I10 | Task I10 complete as written | I10 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-I11 | Task I11 complete as written | I11 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-J1 | Task J1 complete as written | J1 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-J2 | Task J2 complete as written | J2 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-J3 | Task J3 complete as written | J3 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-J4 | Task J4 complete as written | J4 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-J5 | Task J5 complete as written | J5 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-J6 | Task J6 complete as written | J6 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-J7 | Task J7 complete as written | J7 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-J8 | Task J8 complete as written | J8 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-J9 | Task J9 complete as written | J9 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-K1 | Task K1 complete as written | K1 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-K2 | Task K2 complete as written | K2 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-K3 | Task K3 complete as written | K3 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-K4 | Task K4 complete as written | K4 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-K5 | Task K5 complete as written | K5 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-K6 | Task K6 complete as written | K6 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-K7 | Task K7 complete as written | K7 | see task | Unexecuted | — | — | — | — | — | — | — | — | |
| L-K8 | Task K8 complete as written | K8 | see task | Unexecuted | — | — | — | — | — | — | — | — | |

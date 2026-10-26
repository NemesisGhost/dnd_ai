# How to set up your instance and run your first campaign

**Restarted Phase 14/15 acceptance guide (CP-11).** Written 2026-10-26 for code `9ab549ddbc78cb9b5c1aac9c99f3a967112edc62` (`phase15/completion`, CP-10 approved head), schema `140_clock_advance_details`.

> **Status: every task and variant below starts UNEXECUTED.** This guide is a test specification, not evidence. Nothing here has been passed by a human. Automated and scripted results are recorded separately in the [results ledger](PHASE14_15_ACCEPTANCE_LEDGER.md) and never change a human result. Historical markings in [PHASE14_15_MANUAL_TESTING.md](PHASE14_15_MANUAL_TESTING.md) are preserved and are **not** fresh passes.

Companion documents (all under `docs/`):

| Document | Use |
|---|---|
| [PHASE14_15_ACCEPTANCE_ENVIRONMENT.md](PHASE14_15_ACCEPTANCE_ENVIRONMENT.md) | Environment identity, start/stop, exact first manual steps, evidence handoff |
| [PHASE14_15_ACCEPTANCE_LEDGER.md](PHASE14_15_ACCEPTANCE_LEDGER.md) | One row per case/variant: result states, evidence fields, defects |
| [PHASE14_15_COVERAGE_MATRIX.md](PHASE14_15_COVERAGE_MATRIX.md) | Every original case/variant → task, evidence method, ledger row; gaps |
| [PHASE14_15_COMPANION_SCENARIOS.md](PHASE14_15_COMPANION_SCENARIOS.md) | Negative, recovery, scoped-role (SR), clean-install (TC-56) and accessibility (TC-55) scenarios |
| [PHASE14_15_DEFECT_REGISTER.md](PHASE14_15_DEFECT_REGISTER.md) | Known and deferred defects with rubric scores; where to record new ones |
| [PHASE14_15_ACCOUNT_MANIFEST.md](PHASE14_15_ACCOUNT_MANIFEST.md) | What was copied from the dev database, the rename map, verification |

## 1. What you are doing

You start with an instance that has **accounts and nothing else**: no worlds, timelines, campaigns, characters, sessions or knowledge. You will sign in, inspect who may do what, then build one coherent setting — **The Saltmarch**, a drowned coastal region — and run its first campaign, **The Drowned Archive**, through to the end of its first session and the preparation of the second. Every record you create is reused later (the NPC Archivist Sella is a quest target, a party-knowledge source, an encounter opponent and a portrayal subject). By the end you will have exercised creation, editing, runtime use, correction, archive and restore for every Phase 14/15 domain, under every relevant permission boundary, from the browser.

The journey is chronological, not TC-numbered. Original identifiers (TC-01–58, SR-M1–16) are kept as **Refs** on each task so the [coverage matrix](PHASE14_15_COVERAGE_MATRIX.md) can trace every case.

## 2. Ground rules

1. **Use the UI.** Every routine step is done in the portal. Where a supported step has no UI, the task says **API-ONLY** and explains the gap (only TC-58's claim-target grants and TC-48's replay checks need it).
2. **Do not seed through SQL or scripts.** Nothing in this journey is created with SQL, `setup_*` scripts, importers or the AI provider. Read-only database inspection is allowed where a task asks for it and is *corroboration*, not proof that the UI passed.
3. **Passwords.** You (the owner) hold the existing passwords. Nothing in this guide, the ledger or the evidence may contain a password, activation/reset link, cookie, CSRF value or authorization header. Do not reset any account's password to make this easier; if you must, record that fact as a deviation.
4. **Never test against the owner's dev servers.** Only `http://127.0.0.1:5174` (portal) and `http://127.0.0.1:8001` (API). Do not use `localhost`.
5. **One browser profile per persona** (see §4). Signing in as a second account in the same profile replaces the first session.
6. **Result states:** `Unexecuted` · `Pass` · `Fail` · `Blocked` · `Owner-Accepted Exception`. Record a state per ledger row. A page that merely loads, an empty list or a disabled button is not a Pass unless the task says that is the expected result and you checked the explanation.
7. **If a prerequisite cannot be established**, record `Blocked` with the missing prerequisite. Do not invent data.
8. **If the screen differs from the label named here**, record what you saw. A wrong label in this guide is a *documentation* defect (DEF-DOC-n), not a product failure, unless the control is missing.
9. **Order matters.** Archive, revoke, correct and terminal operations come after the checks that depend on the records they affect. Tasks marked **RESTORE** tell you how to put things back.
10. **Do not edit the database or restart the stack** during the run unless a task says so. If the stack restarts, note it in the ledger (login attempts are throttled in-process; a restart clears the throttle).

## 3. Order adjustments from the requested outline

The requested outline was A–J. Real dependencies force these changes:

| Requested | Here | Why |
|---|---|---|
| D. world access **and** build the setting | **D** world access only; **F** build the setting | World records (locations, organizations, NPCs, quests…) are authored inside a campaign's workspace (`/app/<campaignId>/world/...`); no world-only authoring surface exists (Q8 deferred). The campaign (E) must exist first. |
| E. campaign, time, access | **E** | Campaign access must be configured before the GM can author. World times are created inside the campaign. |
| F. users, characters, party | **G** | Characters need published locations (origin) from F. |
| G. prepare adventure/session | **H** | — |
| H. run | **I** | — |
| I. review | **J** | — |
| J. maintain | **K** | Adds branch, archive guards and second-session preparation. |

## 4. Personas, sessions and authority

Open **five separate browser profiles** (use `stack\open_personas.ps1`, which creates fresh throwaway profiles under `%TEMP%\cp11_profiles`) or five private-window sets that you keep apart. Name each window.

| Window | Sign in as | Display name | System roles | Used for |
|---|---|---|---|---|
| **ADMIN** | `admin` | Administrator | Administrator + Game Master | Platform accounts; world owner; creates the campaign; campaign owner |
| **GM** | `gm` | Game Master | Player only (**not** a system GM) | Campaign GM; world Editor + Reviewer after D2; runs every session |
| **PLAYER-A** | `player_a` | Player A | Player | Plays Mara Voss |
| **PLAYER-B** | `player_b` | Player B | Player | Plays Tobin Reed |
| **OBSERVER** | `observer` | Observer | Player | Campaign Observer; world Viewer in companion TC-53 |

Also present and **never signed into** in the main journey: `disabled` (Disabled User, inactive — used only to confirm login refusal) and six other inactive accounts preserved from the old data (see the [account manifest](PHASE14_15_ACCOUNT_MANIFEST.md)).

**The login name does not grant authority.** `admin` and `gm` are only names. Authority comes from four independent layers, and each task states which one it is testing:

| Layer | What it controls | Where you see/change it |
|---|---|---|
| **System role** (Administrator, Game Master, Player) | Platform accounts; create worlds; host campaigns | Platform accounts (`/platform/accounts`) |
| **World access** (Owner, Editor, Reviewer, Reader, Viewer; use grant) | Shared canon: author, review, share, transfer; host on an unused timeline | World → Sharing (`/worlds/<id>/sharing`) |
| **Campaign role** (campaign owner, GM, Player, Observer) | Running play; the campaign's own data | Campaign → Access |
| **Character / inventory permission** (Owner, Controller, Viewer… relationships; `character.view_inventory`) | A character's sheet, inventory, perspective | Campaign → Access → character relationships |

## 5. Browser, tools and evidence

- Chrome (current), DevTools open on Network with **Preserve log**. Record the exact Chrome version in the ledger run header.
- Viewports: 390, 1280, 2560 px (plus 360, 768, 1920 for Knowledge). Zoom 200 %.
- NVDA or Narrator for the screen-reader checks (TC-55). Record its version.
- Screenshots go in `C:\Users\nemes\dnd_ai_evidence_20261026\cp11\human\` (create it). No screenshot may show a password, link or token.
- Record IDs you create in the **Record register** in the ledger (world, timelines, campaign, characters…). Copy IDs from the address bar.

### How to read a task

Each task lists: **Goal**; **Account** (window and the layer of authority being exercised); **Start**; **Prerequisites**; numbered **Steps**; **Expect**; **Compare** (privacy/permission comparison to make); **Creates → used later**; **Refs** (original cases/variants); **Ledger** (row id). `⟲` marks a persona switch. `↺ RESTORE` marks restoration instructions.

### Fixed sample content

| Kind | Name |
|---|---|
| World | The Saltmarch (primary timeline **Main Timeline**; second timeline **What If Timeline**) |
| Calendar | Saltmarch Reckoning — epoch Founding, 7 days/week, months Firstfall and Lastfall (30 days each) |
| Campaign | The Drowned Archive |
| Times | T0 Arrival 09:00 · T1 Meeting 10:00 · T2 Descent 11:00 · T3 Discovery 12:00 · T4 Departure 13:00 (year 1, Firstfall day 1); narrative moment **Between bells** (after T1, before T2) |
| Places | Ashen Vale (region) → Hollowmere (settlement) → The Archive (building); dungeon The Cellar Vaults (areas Entry Hall, Store Room) |
| Organizations | Hollowmere Council (Government) → Lamplighters Guild; religion Faith of the Tide; Religious organization Chapter of the Tide |
| People | NPC Archivist Sella · PCs Mara Voss (Player A), Tobin Reed (Player B) |
| Parties | The Lantern-Bearers; Reserve |
| Sessions | Session 1: The Sunken Door (run now) · Session 2: What the Tide Left (prepared at the end) |
| Quest | Recover the Lost Ledger |
| Items | Definitions Brass Token (generic), Tide Charm (attunement), Unfinished Relic (draft); instances Brass Token, Tide Charm |
| Encounter | Vault dispute |
| Private markers | Texts that must **never** reach a player: `GM-NPC-ONLY`, `GM-LOG-ONLY`, `GM-EVENT-ONLY`, `GM-QUEST-ONLY`, `GM-SOURCE-ONLY`, `GM-ITEM-ONLY`, `GM-PORTRAYAL-ONLY`, `GM-DUNGEON-ONLY`, `GM-RELATIONSHIP-ONLY`, `GM-PROVENANCE-ONLY`. Always include the matching marker when a step says "with GM note". |

---

## A. Sign in and inspect the empty instance

### Task A1 — Sign in as the Administrator and read the session
- **Goal:** Confirm the instance is empty and that the signed-in identity carries the system roles the database says it should.
- **Account:** ADMIN window, `admin` (system roles Administrator + Game Master). Layer under test: system role.
- **Start:** `http://127.0.0.1:5174/` in a fresh ADMIN profile. **Prerequisite:** the owner's existing password for `admin` (never write it down).
- **Steps:**
  1. Open the portal root. Expect the Sign in page.
  2. On the page headed **D&D AI World**, type `admin` in **Email or Username**, your existing password in **Password**, and press **Sign In**. Expect to land on **Campaigns**. (Throughout this guide "sign in as X" means exactly this; the login name is the part before any display name.)
  3. With DevTools → Network, select the request `/auth/session` (or reload and inspect it). Read — do not copy — `system_roles` and the capability list.
  4. Open the user/account menu. Expect the display name **Administrator**.
- **Expect:** Campaigns says **You are not in any campaigns yet.** and offers **Create a world**, **Accept a campaign invitation** and **Create campaign**. `system_roles` lists the Administrator and Game Master codes; capabilities include account management, world creation and campaign hosting. There is a **Platform accounts** link. No world or campaign data of any kind exists.
- **Compare:** The response must not contain a password hash, token or CSRF secret in a place you would be tempted to copy; if it does, record a Fail for secret exposure.
- **Creates → later:** nothing. Establishes the ADMIN session used until C1.
- **Refs:** TC-01.1 · TC-02 (admin) · SR-M3 (identity on the accounts-only baseline). **Ledger:** L-A1.

### Task A2 — Login return, deep links and "opening is not creating"
- **Goal:** Prove a signed-out visit to a deep link returns to it after sign-in, and that merely opening a creation page creates nothing.
- **Account:** a second private window (signed out), then `admin`.
- **Start:** private window, `http://127.0.0.1:5174/worlds/new`.
- **Steps:**
  1. Open `/worlds/new` signed out. Expect the Sign in page (not the form).
  2. Sign in as `admin` in that window. Expect to be returned to **New world**.
  3. Do **not** submit. Open Network: no POST/PUT/PATCH/DELETE for the world.
  4. Back in the first window: sign out; visit `/campaigns`; expect Sign in; sign in again.
  5. Close the private window (its session ends with it).
- **Expect:** Return to the requested destination without a crash, blank outlet or duplicate form. Opening New world creates nothing (verify on **Worlds**: still empty).
- **Creates → later:** nothing.
- **Refs:** TC-01.2–3 · TC-54 (signed-out). **Ledger:** L-A2.

### Task A3 — A disabled account cannot sign in
- **Goal:** The inactive account is refused safely.
- **Account:** a third signed-out window; `disabled` (Disabled User). Layer: system lifecycle status.
- **Start:** Sign in page.
- **Steps:** Attempt one sign-in as `disabled` with its existing password. Do **not** retry repeatedly (logins are throttled to 10 per 15 minutes per account).
- **Expect:** A generic refusal that does not say whether the account exists, is disabled, or has a wrong password; no authenticated workspace; nowhere in the UI reveals the account's status.
- **Compare:** Repeat once with a login that does not exist (`nobody.here`): the refusal text must be indistinguishable.
- **Refs:** TC-01 (disabled login refused) · TC-02.4. **Ledger:** L-A3.

---

## B. Verify platform access and the existing accounts' roles and status

### Task B1 — Read the Platform accounts list
- **Goal:** Confirm which accounts exist, their login names, activation status and system roles — and that nothing else came with them.
- **Account:** ADMIN. Layer: system role (accounts management).
- **Start:** **Platform accounts** (`/platform/accounts`).
- **Steps:**
  1. Open **Platform accounts**. Use **Search by display name or login name** to find each login below.
  2. Compare every row with the table. Do not use any row's Actions in this run.
- **Expect (12 accounts):**

| Login name | Display name | Status | System roles | Role in this journey |
|---|---|---|---|---|
| `admin` | Administrator | Active | Administrator, Game Master | ADMIN |
| `gm` | Game Master | Active | Player | GM |
| `player_a` | Player A | Active | Player | PLAYER-A |
| `player_b` | Player B | Active | Player | PLAYER-B |
| `observer` | Observer | Active | Player | OBSERVER |
| `disabled` | Disabled User | Inactive | Player | refusal test only |
| `contmurd528l`, `contmurdsgm9`, `contmurlnn89` | Continuation Tester (×3) | Inactive | Player | not used |
| `tester1` | Tester 1 | Inactive | Player | not used |
| `invite_test` | Invite Test | Inactive | Player | not used |
| *(pending activation)* | Testing 1 | Inactive | Player | not used |

  *Last login* shows **Never** for every account until it signs in (login history was deliberately not copied). The statement "Granting Administrator is done by the operator script on this deployment" appears where the Administrator role would be edited.
- **Compare:** `gm` has **no** Game Master system role despite its name; `admin` has two roles. The names `admin`/`gm` confer nothing.
- **Do not:** disable, reactivate, issue a reset link, or change a role on these accounts here. Those operations live in companions SR-M7/M10/M12 and change the baseline.
- **Refs:** SR-M3 · SR-M2 (partial) · TC-01 · TC-02. **Ledger:** L-B1.

### Task B2 — Every other persona starts with nothing — and cannot reach platform or creation pages
- **Goal:** Each non-admin persona sees an empty instance and is refused administrative and creation surfaces.
- **Account:** ⟲ GM, PLAYER-A, PLAYER-B, OBSERVER windows in turn (sign each in once; keep the sessions open for later).
- **Start:** each window's Sign in page.
- **Steps (repeat for each persona):**
  1. Sign in. Expect **Campaigns** with **You do not have access to any campaigns yet. Ask a GM to invite you.** and **Accept a campaign invitation** only.
  2. Confirm there is **no Platform accounts link** and **no Create a world** offer.
  3. Type `/platform/accounts` and `/admin/accounts`. Expect "You do not have permission to view this page." (or a not-found state) and **no** account list request returning data.
  4. Type `/worlds/new`. Expect **no usable form** (refusal / blocked explanation). In the response of `/auth/session` confirm the world-create and campaign-host capabilities are **absent**.
  5. Type `/worlds`. Expect an empty list: **The Saltmarch does not exist yet** and nothing else.
- **Expect:** Identical emptiness for all four. In particular `gm` (a "Game Master" by name) gets **no** world-create form, because it holds only the Player system role.
- **Compare:** This is the key permission contrast of the whole run: *the display name Game Master and the login `gm` do not grant creation.* Record that you looked specifically for the New world form on `gm`.
- **Creates → later:** four live persona sessions.
- **Refs:** TC-02 (per persona) · TC-04.3 (revised: GM2 no longer creates worlds) · SR-M1/SR-M2 (negative side). **Ledger:** L-B2; 02.gm, 02.player_a, 02.player_b, 02.observer, 04.gm-no-create.

---

## C. Create the world and its timeline/calendar context

### Task C1 — Create The Saltmarch and its primary timeline
- **Goal:** One world with its primary timeline, created atomically.
- **Account:** ⟲ ADMIN. Layer: system role Game Master → world creation; becomes world **Owner**.
- **Start:** **Worlds → New world** (`/worlds/new`).
- **Steps:**
  1. Name `The Saltmarch`; description `Drowned coastal region for the first campaign`.
  2. Accept the offered D&D 5e ruleset as allowed/default.
  3. Primary timeline name `Main Timeline`.
  4. Save once. Record the world id **W**, the generated slug (there is no slug field), and the primary timeline id **T1** in the ledger Record register.
  5. Reload the world overview and the timeline overview.
- **Expect:** The world overview and its Timelines collection show **Main Timeline** as primary. Creation was one request and made one world and one timeline. You (admin) hold the Owner role (verify in D1).
- **Compare:** ⟲ GM window → **Worlds**: still empty. Nobody else can see The Saltmarch yet.
- **Creates → later:** W, T1 (hosts the campaign), the world Owner role.
- **Refs:** TC-11.1 · TC-04 (creation eligibility, admin) · SR-M1 (positive side). **Ledger:** L-C1.

### Task C2 — Add a second timeline for later branch and archive checks
- **Goal:** An independent timeline that no campaign uses.
- **Account:** ADMIN. Layer: world Owner (timeline creation: Owner or Editor).
- **Start:** The Saltmarch → Timelines.
- **Steps:** **New timeline** → name `What If Timeline`, description `Independent test timeline`. Save. Reload both timelines' overviews. Record id **T2**.
- **Expect:** Two timelines; neither shares events or lineage with the other. Opening the form alone created nothing.
- **Creates → later:** T2 (guard checks in K; not used for the campaign).
- **Refs:** TC-11.2. **Ledger:** L-C2.

### Task C3 — Create the calendar
- **Goal:** The calendar all in-world times will use.
- **Account:** ADMIN. Layer: world Owner (`world.manage`).
- **Start:** The Saltmarch overview → **New calendar** (`/worlds/<W>/calendars/new`).
- **Steps:**
  1. Calendar `Saltmarch Reckoning`, epoch `Founding`, seven days per week.
  2. Months `Firstfall` and `Lastfall`, 30 days each. Save.
  3. Re-open the form with invalid input (a month with 0 days; a blank name) and observe field-level errors; correct nothing; leave without saving.
- **Expect:** Calendar saved once and shown on the world overview. Invalid input is explained at the field and creates nothing.
- **Compare:** ⟲ GM window → `/worlds/<W>/calendars/new`: refused (GM has no world role yet).
- **Creates → later:** the calendar (E6 times; K1 "used calendars are not freely editable").
- **Refs:** TC-14.1, 14.4 (calendar half) · accessibility row 1. **Ledger:** L-C3.

### Task C4 — Edit the world and timeline descriptions
- **Goal:** Definition edits persist.
- **Account:** ADMIN.
- **Start:** The Saltmarch → **Edit**.
- **Steps:** Change the description to `A drowned coast of tidal archives and lamplit quays.` Save; reload. Open Main Timeline → Edit; set its description `Canon timeline of the first campaign.` Save; reload. Observe lineage and branch-point fields (read-only, if shown).
- **Expect:** Both persist after reload. The timeline edit offers **no** control to change lineage or branch point. Save receipts show ids/versions, not the full text (inspect the response).
- **Refs:** TC-11.4 · TC-52.5 (lineage fixed). **Ledger:** L-C4.

---

## D. Configure world access

### Task D1 — Read the world's sharing page
- **Goal:** See who holds which world role, and what each control does, before changing anything.
- **Account:** ADMIN. Layer: world access (Owner).
- **Start:** The Saltmarch overview → **Sharing** (`/worlds/<W>/sharing`).
- **Steps:** Read the **World roles** table (columns Name, Role, Granted by, Actions), the **Allowed to host campaigns** list and the **Transfer ownership** form. Do **not** submit Transfer ownership.
- **Expect:** `Administrator` is the only row, role **Owner**. **Allowed to host campaigns** says **No one has been given this permission.** The role choices offered by **Give someone a role** are Owner/Editor/Reviewer/Reader/Viewer as the product defines them.
- **Compare:** ⟲ GM → type `/worlds/<W>/sharing`: refused with no sharing data (GM holds no world role yet).
- **Refs:** SR-M5/6/7/11 (read side) · TC-04. **Ledger:** L-D1.

### Task D2 — Give the Game Master the world's Editor and Reviewer roles
- **Goal:** Let `gm` author and review shared canon. This is a *world-layer* grant; it is independent of the campaign role you assign in E4.
- **Account:** ADMIN. Layer: world access (Owner may share).
- **Start:** Sharing → **Give someone a role**.
- **Steps:**
  1. Login name `gm`, Role **Editor** → submit. Expect "Role assigned".
  2. Again with Role **Reviewer**. A person can hold both.
  3. Re-read the table: `Game Master` shows both roles.
  4. ⟲ GM: reload; **Worlds** now lists The Saltmarch. Open its overview: read access to the world, **no** management actions (no Edit, Sharing, Transfer; "View only" style state where the product shows one).
  5. GM types `/worlds/<W>/edit`, `/worlds/<W>/sharing`, `/worlds/<W>/timelines/new`, `/worlds/<W>/calendars/new`, `/worlds/new`. Expect: edit/sharing/calendars refused; **timeline creation allowed** (Owner or Editor may create/branch timelines — do **not** save one); New world refused.
  6. ⟲ PLAYER-A, PLAYER-B, OBSERVER: **Worlds** still empty.
- **Expect:** Editor allows definition authoring (once the GM is also a campaign GM, E4); Reviewer allows submit/approve/publish/archive; having both lets one person take a draft all the way through. Neither role lets GM share, transfer or manage the world.
- **Compare:** Three layers visible together: GM's *system* role is Player, *world* roles are Editor+Reviewer, *campaign* role is not yet assigned.
- **Creates → later:** GM's authoring authority from F onward. **↺ RESTORE** (for SR-M8 only): Sharing → **End role** on each of GM's roles; re-add the same two to restore.
- **Refs:** SR-M4 · TC-04.3 (revised) · TC-16/17 (authoring precondition). **Ledger:** L-D2.

---

## E. Create the campaign, establish its time, and configure access

### Task E1 — Setup cancellation and recovery (before creating the real campaign)
- **Goal:** Abandoning campaign setup creates nothing and recovery is understandable.
- **Account:** ⟲ ADMIN. Layer: system Game Master + world Owner → campaign creation eligibility.
- **Start:** **Campaigns → Create campaign** / `/campaigns/new`.
- **Steps:**
  1. Select world The Saltmarch → continue; select Main Timeline → continue; type `Cancelled campaign`; **Cancel** before submitting.
  2. Reopen setup; go backwards from the last step; change the selected world (only one exists; note the timeline choices follow the world); return to The Saltmarch.
  3. Reload the setup address at an intermediate step; follow the recovery/selection controls.
- **Expect:** No campaign named `Cancelled campaign` exists (Campaigns list empty). Timeline/ruleset options correspond to the chosen world; stale lower-level choices are cleared or rejected.
- **Refs:** TC-12 · CP-4 setup flow. **Ledger:** L-E1.

### Task E2 — Create The Drowned Archive
- **Goal:** The campaign on Main Timeline.
- **Account:** ADMIN.
- **Start:** `/campaigns/new`.
- **Steps:** World The Saltmarch → timeline Main Timeline → name `The Drowned Archive`, description `First campaign of The Saltmarch`, offered D&D 5e ruleset version. Submit **once**. Record campaign id **C**. Reload.
- **Expect:** The campaign appears in Campaigns; Home opens. You (admin) are campaign owner. Opening Setup/Home never created a second campaign.
- **Compare:** Open `/campaigns/new` again and step through to the timeline choice **without submitting**. Record whether Main Timeline is still offered and, if it is not, the stated reason (a used timeline cannot host a second campaign). Cancel.
- **Creates → later:** C. Every `/app/<C>/…` route.
- **Refs:** TC-11.3 · TC-04 · SR-M6 (read side). **Ledger:** L-E2.

### Task E3 — Inspect Home and Settings; edit the campaign description
- **Goal:** Empty-but-usable home; pinned ruleset and timeline visible.
- **Account:** ADMIN. Start: `/app/<C>/home`, then **Settings** (`/app/<C>/settings`).
- **Steps:** On Home read **Get started** ("Invite players", "Manage your worlds and timelines", "Review campaign settings"), **Game master tools** (Parties, Record an event, World times) and the **Campaign time** card ("No time has been recorded for this campaign yet."). In **Settings** read the pinned ruleset and current timeline; change the description to `First campaign of The Saltmarch — the sunken archive.`; save; reload. Open **Campaign startup** and leave defaults.
- **Expect:** Home is empty but offers next actions. Settings shows the ruleset and timeline. The edit persists.
- **Compare:** The Campaign time card says no time recorded; do **not** set it yet (E7).
- **Refs:** TC-11.4 · TC-02 (admin) · TC-05 (empty counts). **Ledger:** L-E3.

### Task E4 — Bring in the five accounts and give each a campaign role
- **Goal:** Existing accounts join the campaign. Joining grants nothing until a role is assigned.
- **Account:** ADMIN (campaign owner; `access.manage`) for all assignments; each invitee in their own window.
- **Start:** Campaign **Access** (`/app/<C>/access`) and **Invitations** (`/app/<C>/access/invitations`).
- **Steps:**
  1. **Invitation path for `gm` and `player_a`.** On Invitations issue an invitation with label `GM`. Privately copy the one-time link (the one-time panel; never paste it into any document). ⟲ GM: open the link in the GM window, confirm joining. Repeat with label `Player A` for PLAYER-A. After each acceptance ⟲ the invitee: open **Campaigns** — expect the campaign to be listed but **no authoring and no character perspective** (membership without a role).
  2. **Existing-account path for `player_b` and `observer`.** ⟲ ADMIN, Access → **Add campaign member** → type the exact login `player_b` → **Find account** → add. Repeat for `observer`.
  3. **Non-disclosure of the lookup.** With the same control look up `disabled` and `nobody.here`. Expect the **same** neutral result ("No eligible account found for that login name.") for both — it must not reveal that `disabled` exists or is inactive. Then look up `gm` (already a member): same neutral result.
  4. **Assign roles** on the Access page for each membership: `gm` → **GM**; `player_a` → **Player**; `player_b` → **Player**; `observer` → **Observer**. Record each membership id in the Record register (do not record invitation material).
  5. ⟲ each invitee: reload **Campaigns** and open the campaign. Compare against Expect.
- **Expect:** Invitation acceptance and adding a member give membership only; the role makes the difference. GM sees campaign authoring links; Players see player projections and no authoring; Observer sees read access with no character selector choices and no authoring. Nobody has a character perspective yet.
- **Compare (four layers together):** GM now has campaign role GM + world roles Editor/Reviewer but **only** the Player system role → still no New world, no Platform accounts, no campaign **creation**.
- **Creates → later:** memberships; role assignments; G2 adds character relationships.
- **Refs:** TC-13 · SR-M10 (invited existing account keeps system roles; a campaign GM role does not mint a system GM) · TC-02. **Ledger:** L-E4.

### Task E5 — Read the access overview and the access audit
- **Goal:** The access picture the owner will rely on is accurate.
- **Account:** ADMIN. Start: Access and **Access audit** (`/app/<C>/access/audit`).
- **Steps:** Read each member's roles; open an effective-access/detail view for `gm` and `player_a` if offered; read the audit entries for the role assignments.
- **Expect:** Roles exactly as assigned; audit entries identify actor, target, role and reason fields without any invitation token.
- **Refs:** TC-13 · TC-57 (audit side). **Ledger:** L-E5.

### Task E6 — Record the world's named times
- **Goal:** T0–T4 and a narrative moment, as the GM, for the clock and events later.
- **Account:** ⟲ GM. Layer: campaign GM runtime. (The time-point creation exception lets a campaign GM do this even without a world role; GM also holds Editor so the exception itself is isolated in SR-M8.)
- **Start:** **World times** (`/app/<C>/world-times`).
- **Steps:**
  1. Calendar `Saltmarch Reckoning`. Record year 1, Firstfall day 1, 09:00 label `Arrival` (**T0**); 10:00 `Meeting` (**T1**); 11:00 `Descent` (**T2**); 12:00 `Discovery` (**T3**); 13:00 `Departure` (**T4**). Record the ids.
  2. Narrative moment `Between bells`, after T1 and before T2.
  3. Try invalid input: day 31; hour 24; a narrative placement whose Before is earlier than After. Read each error; do not save.
  4. Reload **World times**.
  5. ⟲ GM: type the calendar creation route `/worlds/<W>/calendars/new` (still refused).
- **Expect:** Displays show calendar, date, time, label in order; **Between bells** lies strictly between Meeting and Descent. Invalid inputs are explained at the field and create no row. Calendar creation stays an Owner-only action.
- **Creates → later:** T0–T4 and Between (clock E7, memberships G4, events I2, attunement I8).
- **Refs:** TC-14.2–5 · SR-M8 (partial). **Ledger:** L-E6.

### Task E7 — Advance and correct the campaign clock (before any session)
- **Goal:** The clock stands at T1 when the first session starts.
- **Account:** GM. Start: Home → **Campaign time** card ("Advance time", "Correct time").
- **Steps:**
  1. **Advance to** T0 (leave **Optional details** closed); reload; Advance to T1.
  2. Try to advance to T0 and to T1 again. Expect "The new time must be later than the campaign's current time." / "The clock already shows that time."
  3. **Correct time** → "Correct to" T0 → in the confirmation ("Correct the campaign time?") cancel; reopen and confirm with a reason `Rehearsing a correction`.
  4. Advance to T1 again.
  5. ⟲ PLAYER-A: open Home. Read the clock; no Advance/Correct controls. Inspect the response: fictional time only, no real-world timestamp passed off as in-world time.
- **Expect:** First and later advances persist and each creates a causal event; refused advances change nothing; cancel is read-only; the final clock is **T1 (Meeting)**. Members can read the time; only editors see controls.
- **Compare:** The Observer and Player B windows show the same time with no controls.
- **Refs:** TC-15.1–4 · CP-9b (manual advance remains available; cause added in I3). **Ledger:** L-E7; 15.manual.

---

## F. Build the starting setting

All authoring is done as **⟲ GM** unless stated. World records live in the campaign workspace (`/app/<C>/world`). GM holds world Editor + Reviewer, so one person can submit, approve and publish. Players see only published, active records.

### Task F1 — Places: a region, a settlement and a building
- **Goal:** Ashen Vale → Hollowmere → The Archive, published.
- **Account:** GM. Layer: world Editor (author) + Reviewer (submit→approve→publish) on a campaign with GM role.
- **Start:** **World** → **New location**.
- **Steps:**
  1. Create region `Ashen Vale`. From its **Lifecycle** panel: submit for review → approve → publish.
  2. Create settlement `Hollowmere`, parent Ashen Vale, same lifecycle steps.
  3. Create building `The Archive`, parent Hollowmere, same steps. Edit its summary to `Public archive`; save; reload; read the hierarchy links.
  4. ⟲ PLAYER-A: open **World**; find all three places; open The Archive. Note the breadcrumb.
- **Expect:** Archive's hierarchy is Ashen Vale → Hollowmere → The Archive. Reference pickers offer only authorized records. Defining places does not move characters or create timeline state. Players see published active places only.
- **Compare:** In the PLAYER-A window request a draft you create in F2 (copy its URL as GM first): the player gets the same "not available" as for a nonexistent id (`00000000-0000-4000-8000-000000000001`) — no title or summary flash.
- **Creates → later:** places used as origin (G1), HQ (F3), travel (I4), route (H6), dungeon parent (H5).
- **Refs:** TC-16.1–3 · TC-10 (draft 404) · TC-05 (counts). **Ledger:** L-F1.

### Task F2 — Every other location category, and the hierarchy guards
- **Goal:** Each supported non-dungeon location category can be created, edited and saved as a draft; invalid hierarchies are refused.
- **Account:** GM. **Start:** New location.
- **Steps:**
  1. For every non-dungeon category the form offers beyond region/settlement/building, create `Saltmarch <category>` with required subtype fields filled from offered options; select a valid published parent where applicable; save as draft; edit the summary; reload. Record each category + URL.
  2. In a draft hierarchy try to make a place its own parent; try to reparent an ancestor beneath its descendant.
  3. Try to archive `Hollowmere` while The Archive still depends on it.
- **Expect:** All ten supported categories have a working create/edit and correct subtype fields. Cycles are excluded or refused with a reason; hierarchy unchanged. Archiving a parent with live dependents is refused with a stated reason.
- **Creates → later:** drafts that fill the Review queue (J4).
- **Refs:** TC-16.4–5. **Ledger:** L-F2.

### Task F3 — Organizations and a religion
- **Goal:** A council with a guild beneath it; a faith and its chapter.
- **Account:** GM. **Start:** World → New organization / New religion.
- **Steps:**
  1. `Hollowmere Council`, Government, headquarters Hollowmere, summary `Public council`; submit, approve, publish.
  2. `Lamplighters Guild`, beneath the Council, using the offered Organization/guild fields; keep as **draft**; edit summary; reload.
  3. For each other offered organization kind (six kinds total across steps 1–3) create and edit a draft with a concrete value for every required subtype field.
  4. `Faith of the Tide` (religion): save and publish. Then `Chapter of the Tide` (Religious organization) referencing Faith; save and publish.
  5. Try a self-parent and a cyclic parent organization.
  6. ⟲ PLAYER-A: open Council and Faith; try to open the draft Guild (copy its URL as GM).
- **Expect:** Subtype fields and parent/HQ/religion references persist and stay within the world. Cycles cannot be saved. The player reads published information and gets "not available" for the draft Guild. Definition edits change no membership or operational status.
- **Refs:** TC-17. **Ledger:** L-F3.

### Task F4 — The NPC: Archivist Sella
- **Goal:** A published NPC with a public appearance and a GM-only background.
- **Account:** GM. **Start:** **Characters → New character → NPC** (`/app/<C>/characters/npc/new`).
- **Steps:**
  1. `Archivist Sella`, Human/Medium, origin Hollowmere, public appearance `Blue coat`, GM background `GM-NPC-ONLY: secretly paid by the harbour guild`. Save, submit, approve, publish. Record id.
  2. Edit the public appearance to `Blue coat with a brass lantern`; save.
  3. ⟲ PLAYER-A and OBSERVER: open Archivist Sella (from World). In DevTools search the **response JSON** for `GM-NPC-ONLY`.
- **Expect:** Persisted; player and observer responses contain **no** GM background text anywhere (a CSS-hidden field still counts as a leak).
- **Creates → later:** quest target (H3), session participant (H1), encounter opponent (H10), org member (G7), portrayal subject (H9), knowledge knower (I6).
- **Refs:** TC-18.1, 18.4–5 (NPC half) · TC-57 (marker). **Ledger:** L-F4.

---

## G. Add the existing users, create characters, assemble the party

### Task G1 — Two player characters
- **Goal:** Mara Voss and Tobin Reed, published.
- **Account:** GM (player-character identity is the campaign-GM exception). **Start:** Characters → New character → PC.
- **Steps:** `Mara Voss` and `Tobin Reed`: Human/Medium, origin Hollowmere; save, submit, approve, publish each. Record ids.
- **Expect:** Both published and visible to GM. No player has a perspective on either yet.
- **Compare:** Open each as ⟲ PLAYER-A: published character page is visible as a discoverable character without full-sheet access.
- **Refs:** TC-18.2 · plan §5 (PC exception: GM can create/publish PC). **Ledger:** L-G1.

### Task G2 — Link each player to their character
- **Goal:** Access to a character comes from a relationship, not a field on the character.
- **Account:** ⟲ ADMIN (campaign owner, `access.manage`). Layer: character permission.
- **Start:** Characters → Mara Voss → **Manage character** → link a player; and campaign **Access** → character relationships.
- **Steps:** Grant `Player A` an **Owner** relationship to Mara Voss; grant `Player B` an **Owner** relationship to Tobin Reed. Try to archive Mara Voss while her relationship is active (as GM). ⟲ PLAYER-A and PLAYER-B refresh and open the character selector.
- **Expect:** Player A can select only Mara; Player B only Tobin; Observer none. Archiving a linked PC is refused with a useful reason. A draft/unpublished PC would have granted no perspective (note, not testable here).
- **Compare:** No `player_user_id`-style field exists in the identity edit form.
- **Refs:** TC-18.3, 18.5 · TC-02 (perspectives). **Ledger:** L-G2.

### Task G3 — Starting state and immutable builds
- **Goal:** Each character has hit points and an active build.
- **Account:** ⟲ GM. **Start:** Characters → Mara Voss → **Builds and starting state**.
- **Steps:**
  1. Mara: maximum/current HP 20/20; submit.
  2. Build `Fighter 1` (all ability scores 10, Fighter level 1, offered options only): save; **Activate**, cancel at the confirmation once, then confirm.
  3. Build `Fighter 2` (all scores 12, Fighter level 2): save; inspect that the active build is still Fighter 1; activate with confirmation.
  4. Reopen Fighter 1: no edit-in-place; try a second starting-state initialization (not offered/refused).
  5. Tobin and Archivist Sella: 20/20 HP each; create and activate one valid offered build each.
  6. Start another Mara build with a spellcasting class and its offered spells; inspect selections; cancel.
  7. Open the activation event for Fighter 2 (Mara → events or World → event) and read its explanation.
- **Expect:** Starting state initializes once. Saving a build does not activate it; cancel changes nothing. Activating Fighter 2 preserves Fighter 1 and records an activation event. Rules options come from the campaign's pinned version. The event explanation names the character, the build action and what changed in labels, not ids (full values to GM).
- **Compare:** ⟲ PLAYER-A (owner) opens Mara's activation event if reachable: expect owner-tier labels; ⟲ OBSERVER: a "build changed" level without build values.
- **Refs:** TC-19 · CP-9a (build activation, DR-6). **Ledger:** L-G3; 19.explain, 19.other-characters.

### Task G4 — Parties and temporal membership
- **Goal:** The Lantern-Bearers (Mara, Tobin) and Reserve (Sella).
- **Account:** GM. **Start:** `/app/<C>/parties`.
- **Steps:**
  1. Create `The Lantern-Bearers` (description `The first expedition`) and `Reserve` (description `Reserve audience`). Edit Reserve's description; save; reload.
  2. Archive Reserve: open **Archive**, cancel; then archive with reason `Archive check`. Turn on **Show archived**; open Reserve; **Restore** with reason `Restore check`.
  3. ⟲ PLAYER-A: read the party list; type Reserve's edit and member-management addresses → refused.
  4. ⟲ GM, The Lantern-Bearers → **Add member**: Mara and Tobin at T0, reason `Joined for the expedition`.
  5. Try a second overlapping Mara membership at T1; open Tobin's **End membership**, try to end at T0 (refused), cancel; end at T1 with reason `Left for the night`.
  6. Read the history and each join/leave event's explanation. Add Tobin again at T2. Add Archivist Sella to Reserve at T0.
  7. ⟲ PLAYER-A: select Mara; the context **Parties (1)** disclosure starts collapsed — expand with Enter/Space; collapse. ⟲ PLAYER-B: Tobin's party view at the current time (T1: no current membership; becomes current at T2).
- **Expect:** Join/leave events and membership rows agree; overlapping and non-later ends are refused; cancel preserves membership; adjacent rejoining succeeds. Party membership grants no character authority. Party list is readable by members; management pages are not.
- **Refs:** TC-20 · TC-21 · TC-06 · CP-9a (join explanation). **Ledger:** L-G4; 21.explain, 21.leave-rejoin, 21.npc-reserve.

### Task G5 — One coherent character record
- **Goal:** The same sections and Back behaviour whether you arrive from Characters or from World.
- **Account:** GM, then PLAYER-A (owner), OBSERVER. **Start:** Characters list and World.
- **Steps:**
  1. GM: open Mara Voss from **Characters**; note the sections (including Inventory) and the Back link. Go back; open her from **World**; compare sections and Back target.
  2. GM: the inventory is reachable from the record (empty state "No items carried" — not a vanished panel).
  3. PLAYER-A (owner): open Mara; read-only inventory section is reachable.
  4. OBSERVER: open Mara; no inventory section, no mutation.
  5. GM: open the "Characters" entry for `all` characters (`/characters/all`) and filters.
- **Expect:** Same sections and Back behaviour on both entry paths; visiting a record never changes the selected perspective; a missing/denied inventory is explained, never silently absent.
- **Refs:** CP-5 · SR-M16 · TC-40.b (owner inventory). **Ledger:** L-G5.

### Task G6 — Relationships between records
- **Goal:** Typed relationships with participant perspectives.
- **Account:** GM. **Start:** the Relationships panel on Mara Voss, Archivist Sella, Hollowmere Council, The Archive.
- **Steps:**
  1. Family between Mara and Tobin, family name `Voss-Reed`, offered roles.
  2. Employment: Archivist Sella ↔ Hollowmere Council, job title `Archivist`.
  3. Ownership: The Archive owned by Council (valid share/public values). Create one Political and one General example with offered role shapes.
  4. Edit a description; edit a participant perspective with emotional tone and private interpretation `GM-RELATIONSHIP-ONLY`; save; reload.
  5. End the General relationship at a later time; archive; **Include archived**; restore with reason.
  6. ⟲ PLAYER-A: open the same records and relationships; search the response for the marker.
- **Expect:** Five kernel kinds save typed fields and roles atomically; wrong role shapes are excluded or refused; archived relationships take no new reaction changes; the player sees no private interpretation and no GM controls.
- **Refs:** TC-35. **Ledger:** L-G6.

### Task G7 — Organization members and offices
- **Goal:** Public roster vs hidden membership; status is event-backed.
- **Account:** GM. **Start:** Hollowmere Council → **Members and offices**.
- **Steps:** Add Archivist Sella: office `Keeper`, rank `Senior`, Known to public **Yes**. Add Tobin Reed with Known to public **No**. Edit Sella's office/rank in the relationship editor; save. Set a different offered operational status at T2; read its event. ⟲ PLAYER-A: read the roster and status. ⟲ GM: end Tobin's membership at a valid later time; compare current vs historical roster.
- **Expect:** Public office/rank are in the player's roster; Tobin (not public) is absent and absent from the response; status is a timeline-state event, not a definition status overwrite; history stays coherent; archived targets cannot receive new memberships.
- **Refs:** TC-36. **Ledger:** L-G7.

---

## H. Prepare the adventure and the first session

All as **⟲ GM** unless noted. Nothing here starts the session.

### Task H1 — Schedule both sessions and prepare Session 1's participants
- **Goal:** Two scheduled sessions; Session 1 has its cast.
- **Account:** GM. **Start:** **Sessions** → **Schedule a session** (`/app/<C>/sessions/new`).
- **Steps:**
  1. Schedule `Session 1: The Sunken Door`, planned start a near-future date at 19:00 in your browser's zone, summary `Public plan`. Schedule `Session 2: What the Tide Left` with a later start.
  2. Open Session 1; edit title, summary and planned start in place; save; reload. Visit the legacy `/sessions/<id>/edit` address (redirects to the session page).
  3. Choose **Run Session 1** (`…/run`); go to **Prepare → Participants**. Add Mara Voss as **Player character**, Archivist Sella as **NPC**, Tobin Reed as **Guest**.
  4. Try: Mara again (duplicate); Mara as **NPC** and Sella as **Player character** (role/kind mismatch). Read each message.
  5. Remove Tobin, inspect the **Left** state, re-add him as **Player character**.
- **Expect:** Server-assigned, distinct session numbers; planned start is real-world time, separate from world time. Duplicate and mismatch are refused with a message that names the real reason (the participant's kind does not fit the role — **not** a generic "only published characters can" message). The chooser's default role is not Guest for a PC. Removed participation stays in history; no duplicate open participant exists.
- **Compare:** ⟲ PLAYER-A: the session list shows both sessions; the member Participants roster is covered in J2.
- **Creates → later:** sessions S1, S2 (ids); participant stints.
- **Refs:** TC-22 · CP-1 (compatible roles, accurate rejection) · CP-3 (roster section). **Ledger:** L-H1; 22.roles, 22.roster-gm.

### Task H2 — Staged navigation of the Run page
- **Goal:** Stage and section navigation never mutates the session and keeps typed input.
- **Account:** GM. **Start:** Session 1 Run page.
- **Steps:**
  1. Click **Prepare**, **Run session**, **Wrap up**; open each section without starting. Inspect Network: no POST/PUT/PATCH/DELETE.
  2. Type a draft Session log entry and GM notes, select Travel choices, an Award recipient and a half-entered Advance time. Switch sections and stages and come back.
  3. Browser Back/Forward; reload `?section=travel`; open `?section=bogus`; follow each breadcrumb link.
- **Expect:** Exactly one section visible at a time with its heading; unsaved inputs survive section changes and Back/Forward; reload selects the requested valid section; an invalid section resolves to the default without an extra Back entry; breadcrumb Sessions → Session 1 → Run session works; the roster section is present on Prepare.
- **Refs:** TC-23 · CP-3. **Ledger:** L-H2.

### Task H3 — The quest: Recover the Lost Ledger
- **Goal:** A published quest with stages, objectives, a dependency, participants and an outcome.
- **Account:** GM. **Start:** **Quests → New quest** (`/app/<C>/quests/new`).
- **Steps:**
  1. `Recover the Lost Ledger`, summary `Find the missing record`, GM notes `GM-QUEST-ONLY: the ledger is behind the plinth`.
  2. Stage `Investigate`: required manual objective `Meet Archivist Sella`, target Archivist Sella, player-visible. Stage `Recover`: required manual objective `Retrieve the ledger`, target The Archive; optional **GM-only** objective `Learn who the patron is`.
  3. Edit an objective's description; reorder stages/objectives with the controls; restore the order Investigate → Recover.
  4. Make `Meet Archivist Sella` a prerequisite of `Retrieve the ledger`; try the opposite edge (cycle error).
  5. Add Archivist Sella as a participant (offered role); add outcome code `success`, name `Ledger recovered`, an offered category, reward kind Other `A council favour`. Edit the outcome; remove and re-add the reward.
  6. Submit, approve and publish. ⟲ PLAYER-A: open the quest and inspect the response.
- **Expect:** Order and metadata persist; the cycle is rejected and the valid dependency stays; references are published/authorized; publishing with missing required parts fails with an actionable explanation. The player response omits the GM notes and the GM-only objective; defining the quest activates nothing and awards nothing.
- **Refs:** TC-26. **Ledger:** L-H3.

### Task H4 — Knowledge claims, review and publication
- **Goal:** Published claims about The Archive and a claim whose subject is unpublished.
- **Account:** GM. **Start:** **Knowledge → New claim**.
- **Steps:**
  1. Claim `The archive closes at dusk.` — a settled/fact kind, truth True, a sensitivity from the offered catalog, subject The Archive. Save as draft; record id **K1**.
  2. In **Prepare → Claim** change the wording; use Save/Discard (discard once, then edit and save).
  3. Make another unsaved edit, move among stages/sections and use Back/Forward and header Next; try to leave for World and cancel the discard dialog, then discard intentionally. Reload the tab with a dirty edit and observe the browser prompt.
  4. Open the old `/edit`, `/audience`, `#claim` and `#who-knows` addresses.
  5. Make one unsaved edit, then **submit for review** — read the warning about the unapplied edit; discard it; read the summary in Review claim; approve; publish in Publication.
  6. Create draft location `The Hidden Quay` and a claim `The hidden quay exists.` about it; submit and approve the claim; try Publication — read the blocker; follow **Publish its subject first**; publish the location (submit/approve/publish); return and publish the claim.
  7. Create `Rejected claim`; submit; reject with a reason; **Return to draft** and edit it.
  8. On K1's **Sources**: write and attach a source (offered type, title `Archive ledger page`, reference `GM-SOURCE-ONLY`) with Network open; check the `.create` and `.attach` idempotency keys differ; follow **View provenance**; start typing a second source, try to leave (cancel, then discard); detach with confirmation; reattach from the picker.
- **Expect:** One guided claim page handles Prepare / Review & publish / Use in play; only the current section shows. Save is enabled only for changes; navigation and reload guards are real browser behaviour. The unpublished-subject blocker names the real cause and links the subject. Publishing a claim never requires a source and tells no audience. Sources change without changing the claim's definition version.
- **Compare:** ⟲ PLAYER-A: K1 is visible only after publication; the source reference text appears nowhere.
- **Creates → later:** K1 (revealed in I6), claim 2 (archived/superseded in K2), Sources demo.
- **Refs:** TC-28 · TC-29 · TC-32. **Ledger:** L-H4.

### Task H5 — The dungeon: The Cellar Vaults
- **Goal:** A published two-area dungeon with a connection and content.
- **Account:** GM. **Start:** World → **New dungeon**.
- **Steps:**
  1. `The Cellar Vaults`, parent Hollowmere, danger level 1; add areas `Entry Hall` (room) and `Store Room` (room).
  2. Edit Entry Hall: summary, size `20 by 20 feet`, environment `Dry stone`; save; reload its deep edit URL.
  3. Connection Entry Hall → Store Room (offered type, hidden **Yes**, one-way **No**); flip to one-way and back, saving each.
  4. In Entry Hall add feature `stone plinth`, hazard `trip wire` (valid severity), interactable `iron lever`; edit each description; remove and re-add one while draft.
  5. Publish parent, dungeon and areas in dependency order, resolving any displayed blocker; reload all detail/edit URLs.
- **Expect:** Areas belong to the dungeon; typed fields persist; structural edits create no play events; published structure offers only permitted actions; no map/image upload is implied.
- **Refs:** TC-33. **Ledger:** L-H5.

### Task H6 — A route between Hollowmere and The Archive
- **Goal:** Route metadata for travel in I4.
- **Account:** GM. **Start:** Hollowmere → Relationships.
- **Steps:** Create a **Route** to The Archive: distance `1 mile`, travel time `20 minutes`, mode `walk`, Concealed **No**. Reload. Toggle Concealed **Yes** and ⟲ PLAYER-A inspect the route view and response; ⟲ GM restore Concealed **No**.
- **Expect:** Route metadata persists; a concealed route's details are absent from the player's reads. **↺ RESTORE:** Concealed No.
- **Refs:** TC-37.1. **Ledger:** L-H6.

### Task H7 — Item definitions
- **Goal:** Three world-owned definitions; generic seeds protected.
- **Account:** GM (world Editor+Reviewer). **Start:** **Item definitions** (`/app/<C>/item-definitions`).
- **Steps:**
  1. `Brass Token` — offered category/rarity, weight 1, value 2 gold, Description `Public token`, Status Canon, Requires attunement **No**. Record id.
  2. `Tide Charm` — similar, Requires attunement **Yes**, Status Canon; edit description; reload.
  3. `Unfinished Relic` — Status **Draft**; try to create an instance from it later (H8) — it must not be offered.
  4. Open a generic seeded definition: no edit controls through this form. Filter by category. Try a negative number: explained validation.
  5. ⟲ PLAYER-A: no Item definitions navigation; type `/app/<C>/item-definitions` → refused.
- **Expect:** World-owned create/edit and category filters work; the draft definition cannot yield an eligible instance; generic seeds are read-only; players have no management surface.
- **Refs:** TC-39. **Ledger:** L-H7.

### Task H8 — Item instances: Brass Token and Tide Charm
- **Goal:** Two published instances ready to award.
- **Account:** GM (item instance creation is a campaign-GM exception). **Start:** **Items → New item** (`/app/<C>/items/new`).
- **Steps:** Create `Brass Token` from the Brass Token definition, summary `Test treasure`, origin notes `GM-ITEM-ONLY`; submit, approve, publish. Edit the summary; reload; confirm the definition choice is fixed. Create and publish `Tide Charm` from Tide Charm. Create `Spare Token` (Brass Token definition) and publish it — a disposable unreferenced item for K1. The page shows exactly one Lifecycle panel.
- **Expect:** Instances require a published usable definition; start as drafts; the definition stays fixed; the draft Unfinished Relic is not offered.
- **Refs:** TC-40.1. **Ledger:** L-H8.

### Task H9 — NPC portrayal for Archivist Sella
- **Goal:** Versioned GM-only portrayal profile.
- **Account:** GM. **Start:** Archivist Sella → **Portrayal**.
- **Steps:** Change **Detail level**; save a profile whose visible text field contains `GM-PORTRAYAL-ONLY` with change note `First portrayal`. Change the field and save `Second portrayal`. Open version 1 and 2. Save the latest values unchanged once. ⟲ PLAYER-A: open Sella and type her Portrayal URL; inspect responses.
- **Expect:** Profiles append versions; old text is readable by the GM; an unchanged save creates no new version. No player response contains the marker; the player cannot reach portrayal. (AI use of portrayal is outside this phase.)
- **Refs:** TC-38.1–2, 38.5. **Ledger:** L-H9.

### Task H10 — Prepare the Vault dispute encounter
- **Goal:** A pending encounter on Session 1.
- **Account:** GM. **Start:** Session 1 Run → Prepare → **Encounter preparation**.
- **Steps:** Prepare an encounter at The Archive, summary `Vault dispute`; save; record id. Add Mara on an offered friendly side and Sella on an opposing side; read the compact roster. Change Sella's side (Save appears only while changed); restore the old selection (Save disappears); change and save once. Remove Sella with her named remove control; re-add. Try adding Mara twice. Leave and return via **Run the session**; reload the encounter's deep address.
- **Expect:** Preparation records no combat-start/turn events; no initiative-entry form; row errors sit beside the participant; duplicates refused; breadcrumb Sessions → Session 1 → encounter and return links keep campaign context.
- **Refs:** TC-42. **Ledger:** L-H10.

### Task H11 — Provenance across typed records
- **Goal:** One source attached to many records; provenance shown; GM-only.
- **Account:** GM. **Start:** The Archive → **Sources**.
- **Steps:** Write and attach source `Field notes` (offered type, reference `GM-PROVENANCE-ONLY`); record its id. Attach the same source to Hollowmere Council, Faith of the Tide, Archivist Sella, the quest, The Cellar Vaults and Tide Charm; open each **View provenance** and follow its links. Try attaching twice to The Archive; detach with confirmation; inspect provenance; reattach. On a draft record verify Sources, then approve/publish and confirm the attachment survives. Compare the record's row version before/after attaching. ⟲ PLAYER-A: type a captured provenance URL; inspect ordinary record responses.
- **Expect:** Sources attach to the correct entity; duplicate attachment is explained; attach/detach does not revise the definition or invalidate approval; players cannot open provenance/history and get no reference text.
- **Refs:** TC-45. **Ledger:** L-H11.

---

## I. Run Session 1

**⟲ GM** unless stated. Clock is at T1 (Meeting). Participants: Mara (Player character), Sella (NPC), Tobin (Player character).

### Task I1 — Start the session; the log; the world-time bar
- **Goal:** Session 1 runs; public and GM-only log entries separate.
- **Account:** GM. **Start:** Session 1 Run → **Run session**.
- **Steps:**
  1. Click **Start session**. Reload the session list and follow **Run Session 1**.
  2. In **Session log** record public entry `Mara met the archivist` with GM notes `GM-LOG-ONLY` at T1. Record a second entry using **Record a new time** at Firstfall day 1, 10:15, label `Quayside bell`.
  3. Open each event from the log; read the public text and GM notes.
  4. Go to Session 2 and try to start it while Session 1 runs.
  5. Inspect the clock bar in every stage; confirm Advance/Correct controls appear only in **Run session**.
  6. ⟲ PLAYER-A: open Session 1 and the events; search responses for `GM-LOG-ONLY`.
- **Expect:** Start only through the explicit button; Run now defaults to Session log; a second session cannot start while one runs. Entries/time selections persist; audience hints separate public text from GM-only notes; the player sees no marker and no run controls; the clock bar shows in every stage.
- **Refs:** TC-24. **Ledger:** L-I1.

### Task I2 — Record a manual event, void it, correct another
- **Goal:** Corrections keep history.
- **Account:** GM. **Start:** Game master tools → **Record an event** (`/app/<C>/events/new`).
- **Steps:**
  1. Event type Other, name `Mistaken meeting`, GM details `GM-EVENT-ONLY`, time T2; open its page.
  2. Read the correction preview; choose **Void**, reason `Entered twice`; cancel once, then confirm.
  3. Record `Wrong title` (Other, no effect) at T2; **Correct** with the replacement info and reason `Wrong title`; confirm.
  4. Reload original and replacement; inspect links/history/explanation; try another correction of an already voided/corrected original (refused); open a clock event's correction preview (unsupported-effect explanation).
  5. ⟲ PLAYER-A: try to read GM details through session and World views.
- **Expect:** Cancel preserves the original; confirmation leaves the original with a void/correction record and links; nested correction is refused; unsupported previews explain why; players never see `GM-EVENT-ONLY`; the replacement shows a correction explanation (CP-9a).
- **Refs:** TC-25 · CP-9a (event correction explanation; "Wrong title" replacement variant). **Ledger:** L-I2; 25.void, 25.wrong-title.

### Task I3 — Advance the clock with a cause and a member-safe explanation
- **Goal:** Optional clock cause and explanation work; the manual advance is still plain.
- **Account:** GM. **Start:** Run session → clock bar → **Advance time**.
- **Steps:**
  1. Open **Optional details**. In **Cause** choose the log event from I1 ("An event already recorded in this campaign…"). In **Explanation for members** write `The party descended into the cellar.` Advance to T2.
  2. Try a cause that takes effect after the new time (expect "That event takes effect after the new time, so it cannot have caused this advance." and the field cleared).
  3. Open the clock event and read its explanation as GM.
  4. ⟲ PLAYER-A and OBSERVER: open Home/the clock event they may see; read what they are shown.
  5. (Later, with no cause) the T3 advance in I8 is a plain manual advance: confirm it is labelled as manual.
- **Expect:** The advance succeeds, links the chosen cause, and members see the explanation only through an event they may open; the admin reason stays in audit, not in the member view; a plain advance is shown as a manual advance.
- **Refs:** TC-15.2 · CP-9b (DR-4) · CP-9a. **Ledger:** L-I3; 15.cause.

### Task I4 — Travel for individuals and the whole party
- **Goal:** Named travel moves exactly the intended travellers.
- **Account:** GM. **Start:** Run session → **Travel**.
- **Steps:**
  1. Individuals Mara and Sella → destination Hollowmere, no route; record.
  2. The same travellers Hollowmere → The Archive with the optional route selected; read each character's location and the travel event.
  3. Whole party The Lantern-Bearers → Hollowmere; read the resolved traveller set; record; read Mara's and Tobin's locations.
  4. Try a route that does not connect origin and destination, and an ineligible party.
- **Expect:** Only explicit/resolved eligible travellers move; party travel uses current membership; invalid choices are excluded or refused atomically; entered choices survive switching sections until submitted.
- **Refs:** TC-37.2–5. **Ledger:** L-I4.

### Task I5 — Quest runtime
- **Goal:** Progress is explicit; scopes are separate.
- **Account:** GM. **Start:** Recover the Lost Ledger → **Run quest / Progress**.
- **Steps:**
  1. Choose **Party** scope and activate the quest at T2; activate then complete `Meet Archivist Sella` and `Retrieve the ledger`.
  2. Read the completion hint; **suspend** and resume; check objective controls while suspended.
  3. Complete the quest with its confirmation; open the completion event; read the correction preview; void it with reason `Reopen for test`.
  4. Activate the **global** scope separately and compare with Party. Try to add/reorder structural objectives after progress.
  5. ⟲ PLAYER-A (Mara, Party selected): open the quest and its progress links.
- **Expect:** Objective completion yields a hint, not automatic quest completion or reward; prerequisites remain guidance (no invented runtime gate); global and party states are separate; mutations on a suspended/finished quest are refused; the latest completion reverses with history intact; structural edits freeze after progress; the player sees the party projection and no GM fields.
- **Refs:** TC-27. **Ledger:** L-I5.

### Task I6 — Knowledge: reveal, learn, tell, believe, make public
- **Goal:** Knowledge is per knower and never a flag on the claim.
- **Account:** GM. **Start:** K1 → **Who knows this**.
- **Steps:**
  1. **Tell** The Lantern-Bearers at the current time. Record Mara learning it with interpretation `I believe it closes at sunset` (offered awareness/confidence/sharing).
  2. Record Mara telling Tobin, interpretation `I heard it closes at dusk`, an offered transfer method.
  3. Expand Tobin's **Details**; change belief/confidence; save; compare canonical claim with belief. Try telling Tobin again.
  4. Make K1 public at Hollowmere. While a claim edit is dirty, perform an independent Who-knows action and confirm it does not save/discard the dirty edit.
  5. Tell Reserve too; read the "every active party already knows" state.
  6. ⟲ PLAYER-A (Mara) and PLAYER-B (Tobin): with and without the party filter, open K1.
- **Expect:** Party, individual and public groups are separate and each action records its own event and closes only its successful form; telling an existing knower is refused with the form and input retained and a group-local error (use **Change belief**); beliefs never rewrite canonical truth; once known, wording/kind/subject freeze with an explanation; players see their safe interpretation and character/party details with no truth/sensitivity leakage and no duplicate rows.
- **Refs:** TC-30 · TC-07 · TC-08 (public). **Ledger:** L-I6.

### Task I7 — Dungeon runtime
- **Goal:** Play state is separate from structure.
- **Account:** GM. **Start:** Entry Hall → state panel (**Area now**).
- **Steps:** Mark Entry Hall searched; set alarm level 1; GM condition notes `GM-DUNGEON-ONLY`; save. Set an offered new connection status, then feature/hazard/interactable statuses; inspect each event; reload. Open the latest state event's correction preview and void it with a reason; try to reverse an earlier dependent change while later changes remain. ⟲ PLAYER-A: open the published dungeon and area; inspect JSON for hidden connection/content and `GM-DUNGEON-ONLY`.
- **Expect:** Runtime changes record events/effects on this timeline and never rewrite structure; the latest supported reversal restores the preceding state; a moved-on reversal gives the real refusal and preserves state; players see no hidden structure and no GM notes.
- **Refs:** TC-34. **Ledger:** L-I7.

### Task I8 — Items in play: award, equip, transfer, custody, quantity, attunement
- **Goal:** Event-backed item operations.
- **Account:** GM. **Start:** Run session → **Award item**.
- **Steps:**
  1. Award `Brass Token`, recipient Mara, quantity 3. Open Brass Token's World page / **Run this item**.
  2. Equip it; try to give it to Tobin while equipped (refused); unequip; give to Tobin transferring ownership.
  3. Read both inventories and the **Party inventory**; place Brass Token at Hollowmere; read location/custody.
  4. Consume one unit (quantity 2); damage then repair with valid amounts; read each event.
  5. Award `Tide Charm` to Tobin; attune at T2; try to transfer or destroy it (refused while attuned). **Advance time** (no cause) to T3 and read the "manual advance" label; end the attunement; transfer or leave at Hollowmere.
  6. Consume the remaining Brass Token units; read the destroyed state; try another operation (refused). Archive and restore the disposable unreferenced `Spare Token` (cancel the destructive confirmation once first).
  7. On the latest supported item event, read the correction preview and void it; check the earlier operation's reversibility.
  8. ⟲ PLAYER-A: Mara's inventory; ⟲ PLAYER-B: Tobin's inventory; try each other's. Search responses for `GM-ITEM-ONLY`.
- **Expect:** Award/custody/equipment are event-backed; an equipped item cannot be transferred; quantities never go negative; consuming the last unit destroys the item and later operations are refused; attunement requires the carrier, blocks custody/destruction and ends strictly after its start; player inventories are limited to authorized characters; Party inventory is a GM surface; no marker in any player JSON.
- **Refs:** TC-40 · TC-41. **Ledger:** L-I8; 40.owner-inventory.

### Task I9 — NPC runtime: hit points, condition, location, resources
- **Goal:** Tracked state commands with causal events.
- **Account:** GM. **Start:** Archivist Sella's World page → **Run this NPC**.
- **Steps:** HP change `-3` (expect 17); add an offered condition with source `Salt rot`; remove it; move to Hollowmere at an available time. Open **Resources**: expect "None tracked"; select an offered resource and try Change `-1`: refused (no tracked row), state unchanged. Do **not** claim a positive resource pass. ⟲ PLAYER-A: try the NPC controls and her portrayal address.
- **Expect:** HP becomes 17 with a causal event; condition/location operations succeed; the missing-resource refusal is explained and nothing is initialized by adjustment; players cannot operate NPC controls. The positive NPC resource spend/restore variant is **Blocked** (no supported pre-tracked NPC fixture) unless the owner supplies one.
- **Refs:** TC-38.3–4. **Ledger:** L-I9; 38.resource-refusal, 38.resource-positive (expected Blocked).

### Task I10 — Run, finish, discard and abort encounters
- **Goal:** Vault dispute completes; two disposable encounters end other ways.
- **Account:** GM. **Start:** Vault dispute (H10).
- **Steps:**
  1. **Start encounter**; read Round 1; try to modify preparation (refused).
  2. Record Mara acting: Action Attack, target Sella, Result Hit, Damage 2, Round blank. Record Sella's turn; try a duplicate actor turn in the same round (refused); record a valid later-round turn using the Round field.
  3. Read Mara's and Sella's HP and the turn history; end with offered participant outcomes and summary `Dispute resolved`.
  4. Reload the encounter, Run session → Encounters, Wrap up → Session review.
  5. Prepare `Discard test`: choose **Discard**, cancel, then confirm. Prepare `Abort test`, add Mara, start, record one turn; **Abort**, cancel once, then confirm. Reload both; read history and resulting-event links.
- **Expect:** Start records one start event and opens Round 1; blank round/order take server defaults; damage changes tracked HP once and never below zero; End persists outcomes and makes the record read-only with rounds/turns retained; pending discard ends preparation as aborted with no play event; active abort records a causal event, retains turns and invents no completed outcome; lists distinguish pending/active/completed/aborted.
- **Refs:** TC-43 · TC-44. **Ledger:** L-I10.

### Task I11 — Review the session, then end it
- **Goal:** Session review is accurate; ending is explicit.
- **Account:** GM. **Start:** Wrap up → **Session review**.
- **Steps:** Read overview, participants, the log including GM notes, encounters; follow every **Go to** link. Open **End session**, recap `Session 1 complete`, **Ends at** T4; cancel once; then confirm. Advance the world clock to T4 first if the form requires it.
- **Expect:** Review links open the right sections or state why navigation is unavailable; GM notes remain GM-only; cancel leaves the session running; confirm completes it with correct world and real-world end labels; Run now defaults to Wrap up → Session review.
- **Refs:** TC-50.1–2. **Ledger:** L-I11.

---

## J. Review the resulting state and what members can see

Session 1 is complete. Everything below reads what the run produced. Each task states whose eyes it uses.

### Task J1 — The completed session is read-only; archive and restore it
- **Goal:** Completed means completed.
- **Account:** GM, then PLAYER-A. **Start:** Sessions → Session 1.
- **Steps:**
  1. **Run Session 1** again: inspect every stage; try a new log entry, participant, travel, award or encounter if any control is offered.
  2. On the session page try to edit the planned start (frozen once started).
  3. **Archive** the session with reason `Archive check`; ⟲ PLAYER-A reloads the old session URL and the sessions list; ⟲ GM **Show archived**, **Restore** with reason `Restore check`; reload.
- **Expect:** Completed/archived sections explain their read-only state and no play command succeeds; archive hides the session from players; restore returns it to **completed** with its history, not a fresh scheduled session.
- **↺ RESTORE:** done in step 3.
- **Refs:** TC-50.3–4. **Ledger:** L-J1; 50.completed.

### Task J2 — Member-safe session roster
- **Goal:** Who took part follows character discovery, never the session.
- **Account:** ⟲ PLAYER-A, PLAYER-B, OBSERVER. **Start:** Session 1 detail.
- **Steps:** For each persona read the **Participants** roster: names, roles, present/left stints (Tobin has a left stint and a rejoin), and which names are links. Count the rows against the GM's roster. Open the same list in the response JSON and check there is no hidden id, placeholder or count.
- **Expect:** Members see every stint (present or left, rejoins included, with times) of only the participants they may discover; no management controls; a name is a link only where the character page would open for that persona; the count shown equals the rows shown. Participation grants nothing. The "undiscovered participant is absent" variant is staged in K7.
- **Refs:** TC-22 and TC-50 member variants · CP-8 (DR-3). **Ledger:** L-J2; 22.member-pc, 22.member-npc, 22.member-observer, 50.roster.

### Task J3 — Knowledge as a player and as the observer
- **Goal:** Character knowledge plus eligible parties; public knowledge without a character.
- **Account:** ⟲ PLAYER-A (Mara), PLAYER-B (Tobin), OBSERVER.
- **Steps:** As Player A, **Knowledge** → *Known*, no party filter, include public knowledge: find K1; select The Lantern-Bearers; compare. Open K1 and the Knowledge details. Repeat as Player B. As OBSERVER (no character): *Known* with public included, then *Public only*; disable public inclusion; open K1 and `?section=who-knows`. Compare the interpretation each player sees with the canonical wording GM sees; search a phrase unique to the canonical wording as a player.
- **Expect:** A character needs no party filter to see their own belief plus eligible-party knowledge; selecting a party never hides their own knowledge; each claim appears once; neither player sees the other's individual belief; no player sees canon-only claims or truth/sensitivity fields; a canonical-only phrase cannot reveal a claim whose visible interpretation differs; the observer sees public knowledge only, text-only, no stages, Save/Discard or Who-knows controls, and `section` cannot enable editing.
- **Refs:** TC-07 · TC-08. **Ledger:** L-J3.

### Task J4 — World browse, counts and navigation state
- **Goal:** Counts equal lists; browse state survives navigation.
- **Account:** GM then PLAYER-A. **Start:** `/app/<C>/world`.
- **Steps:** Select each category; compare its count with the list (walk every page); return to All entries. Search `hollowmere`, then change category (address and counts); search nonsense and **Clear search**. Enable hidden preview (GM) and find drafts. Open a record, follow a related record/breadcrumb, **Back to World**. On unfiltered All entries go to the next page, open a record and a related record, return, **Previous page**, then browser Back/Forward and reload. Repeat counts/search as Player A and append `?hidden=1`.
- **Expect:** Counts use the same authorized inputs as lists across pages and never count drafts, archived records or foreign-timeline events for a player; category, search, hidden and page trail survive supported links and reloads; search/category changes reset pagination; Previous returns without duplicates or omissions; Player A sees no hidden-preview control and `?hidden=1` grants nothing.
- **Compare — hierarchy and Back/Forward (TC-03):** Walk Worlds → The Saltmarch → Timelines → Main Timeline → Campaign world; use hierarchy selectors; Back/Forward; reload a deep link. Context, route and data must agree at each step with no flash of stale data.
- **Refs:** TC-05 · TC-03 · NV scenarios. **Ledger:** L-J4.

### Task J5 — Member preview
- **Goal:** The GM sees exactly what a member sees.
- **Account:** GM, with PLAYER-A open for comparison. **Start:** Knowledge → **Member preview**.
- **Steps:** Open Member preview before choosing anyone (no Knowledge request). Choose Player A, then Mara, no party filter. Compare *Known*, *Rumors*, *Character private*, *Public only*, search and details with Player A's own pages and requests using identical filters. Choose The Lantern-Bearers; open a claim; Back; reload; change the preview member to Observer. Edit the URL to an unknown member id; then Player A with Tobin's character; then a party without a usable character. **Return to Knowledge**. ⟲ PLAYER-A: type `/app/<C>/knowledge/member-preview`.
- **Expect:** Before selection there is only the member-choice state and no Knowledge request; the banner names the subject and explains read-only preview; only the subject's own perspectives are offered; results match the member's own projection, never GM authority; changing the member clears old claims at once; invalid combinations show a safe error without a Knowledge request; Player A is refused at the preview address and makes no preview request.
- **Refs:** TC-09. **Ledger:** L-J5.

### Task J6 — Revision history and comparison
- **Goal:** Real earlier/later values; history is GM-only.
- **Account:** GM. **Start:** The Archive → **Revision history** (`…/history`).
- **Steps:** Select two revisions and compare; check name/summary/status changes against what you did in F1/H11; read actor, version and time; swap the comparison order. Save an unchanged edit and refresh history. (A stale edit is staged in K5.) Open a record whose older edits predate revision capture, if you have one, and read the messaging.
- **Expect:** Comparison shows correct earlier/later values in a readable table with the real actor; no-op saves, stale refusals and replays create no revision; lifecycle transitions have their own status revisions; missing older snapshots are not fabricated; comparison is GM-only and usable at 390 px.
- **Refs:** TC-46. **Ledger:** L-J6.

### Task J7 — Review queue and the general lifecycle
- **Goal:** Queue counts and every lifecycle transition are true.
- **Account:** GM. **Start:** `/app/<C>/review`.
- **Steps:**
  1. Create disposable location `Lifecycle Test` (no dependents). Filter Drafts and open it. Submit, reject with a reason, return to draft, edit summary, resubmit, approve, publish; check queue filter and count after each.
  2. Create and publish `Lifecycle Replacement`; supersede `Lifecycle Test` with it; follow the replacement link.
  3. Archive the replacement with a reason (cancel once), then restore it with a reason.
  4. Create another unreferenced draft `Delete Draft`; delete with confirmation; reload its URL.
  5. Exercise category/status/search filters and **Load more** when available.
  6. ⟲ PLAYER-A: no Review navigation; type `/app/<C>/review`.
- **Expect:** Queue counts and results agree with server state; every confirmation is clear and cancel changes nothing; supersession/archive preserve records and history; physical deletion is limited to the eligible draft and returns to a valid list; the player sees no review/lifecycle management and no draft content.
- **Refs:** TC-47. **Ledger:** L-J7.

### Task J8 — Privacy sweep: UI and returned data, plus read-only database corroboration
- **Goal:** No GM marker or private field reaches any player; receipts and audit hold no narrative.
- **Account:** PLAYER-A, PLAYER-B, OBSERVER for the sweep; ADMIN for the DB step.
- **Steps:**
  1. In each player window open: Home (recent activity), World list and every record you created, Sessions and Session 1, events, quests, Knowledge, characters, items, dungeon/area. In DevTools use **Network → Search** for each marker: `GM-NPC-ONLY`, `GM-LOG-ONLY`, `GM-EVENT-ONLY`, `GM-QUEST-ONLY`, `GM-SOURCE-ONLY`, `GM-ITEM-ONLY`, `GM-PORTRAYAL-ONLY`, `GM-DUNGEON-ONLY`, `GM-RELATIONSHIP-ONLY`, `GM-PROVENANCE-ONLY`.
  2. ADMIN: for the typed-content writes you made, read the receipt responses in Network: only minimal ids/versions.
  3. **Database corroboration (read-only, owner operator shell).** In a transaction opened `READ ONLY` against `dnd_ai_m1415_accept_clean_20261026`, search `audit.change_log.changed_fields` and the idempotent-request bodies scoped to this run for the markers: record field names and redaction flags, not copied narrative. Inspect `sensitive_read` audit entries produced by J3/J5 (metadata only). In separate rolled-back transactions use `SET LOCAL ROLE app_read_only` and read `core.lifecycle_statuses` (allowed), then try `security.local_credentials` and `core.entity_revisions` (both refused).
- **Expect:** Zero marker hits in any player response; receipts contain no narrative; audit keeps useful structural metadata with narrative fields redacted; GM revision snapshots are separate and not an audit leak; sensitive preview reads are audited without bodies; the reporting role cannot read credentials or revision snapshots.
- **Note:** Database results corroborate; the UI/JSON sweep is the proof for the browser behaviour.
- **Refs:** TC-57 · PV scenarios (no legacy private-text disclosure). **Ledger:** L-J8; 57.receipts, 57.audit, 57.sensitive-read, 57.reporting-role.

### Task J9 — The plain-player denial matrix
- **Goal:** Every GM page family refuses a plain player.
- **Account:** PLAYER-A, then OBSERVER, then a signed-out window; ADMIN to collect ids.
- **Steps:** Collect the real id for each `:id`. As Player A type **every** address below; for each record the heading, visible controls, request status and response shape. Then repeat representative routes as OBSERVER and signed out. (The foreign-campaign and nonexistent-campaign rows are repeated in K3 once the branch campaign exists.)

| Page family | Addresses under `/app/<C>` |
|---|---|
| Location / organization / religion | `/world/location/new`, `/world/location/:id/edit`, `/world/organization/new`, `/world/organization/:id/edit`, `/world/religion/new`, `/world/religion/:id/edit` |
| NPC / PC / builds / portrayal | `/characters/npc/new`, `/characters/pc/new`, `/characters/:id/edit`, `/characters/:id/builds`, `/characters/:id/builds/new`, `/characters/:npcId/portrayal` |
| Party management | `/parties/new`, `/parties/:id`, `/parties/:id/edit` |
| Session / encounter operations | `/sessions/new`, `/sessions/:id/run`, `/sessions/:id/encounters/new`, `/sessions/:id/encounters/:encounterId` |
| Events / quests | `/events/new`, `/events/:id`, `/quests/new`, `/quests/:id/edit`, `/quests/:id/progress` |
| Knowledge | `/knowledge/new`, `/knowledge/:id/edit`, `/knowledge/:id/audience`, `/knowledge/member-preview` |
| Dungeon | `/world/dungeon/new`, `/world/dungeon/:id/edit`, `/world/dungeon/:id/areas/:areaId/edit` |
| Items / definitions | `/items`, `/items/new`, `/items/:id/edit`, `/item-definitions`, `/item-definitions/new`, `/item-definitions/:id` |
| Sources / revisions / review | `/world/:category/:id/provenance`, `/world/:category/:id/history`, `/review` |
| Time | `/world-times` |
| New surfaces | `/worlds/<W>/sharing`, `/worlds/<W>/edit`, `/platform/accounts`, `/admin/accounts` |

- **Expect:** Each GM page gives the supported permission or not-found state with no partial form and no GM fields in the response; Knowledge legacy URLs may redirect to the allowed read-only claim, never to editor stages; published member-safe pages stay usable with no management controls; party-list reads do not authorize GM member-management pages; signed-out routes require login.
- **Record each address separately** in the ledger sub-rows; one refusal does not pass the matrix.
- **Refs:** TC-49 (+ new-surface rows). **Ledger:** L-J9; 49.01 to 49.11, 49.observer, 49.signed-out.

---

## K. Maintain the campaign and prepare the next session

### Task K1 — Archived and superseded places, and what a player can still reach
- **Goal:** The corrected archived-reference rule (DR-1) in practice.
- **Account:** GM, then PLAYER-A.
- **Steps:** Create and publish `Old Pier` and `New Pier`; supersede Old Pier with New Pier. Create and publish `Sunken Reef`, and an organization `Reef Watch` with headquarters Sunken Reef, published. Create draft `Harbor Draft`. Archive Sunken Reef with a reason. ⟲ PLAYER-A: (a) open `Harbor Draft` by its URL; (b) open Sunken Reef from Reef Watch's headquarters link and by its prior URL; (c) open Old Pier (superseded) and follow its replacement; (d) look for archived records in World browse and try `lifecycle=archived`/archive browsing. Compare (a) with `00000000-0000-4000-8000-000000000001`.
- **Expect (amended expectation):** The **draft** is the same not-available response as a missing id with no title/summary flash. The **archived and superseded published** records remain readable *by reference where already visible* (Reef via Reef Watch; Old Pier with its replacement link) as read-only history; they do not appear in ordinary lists or archive browsing for a player. Admin sees true statuses.
- **Refs:** TC-10 (**amended per DR-1**) · TC-31 (archived claims, in K2) · NV scenarios. **Ledger:** L-K1; 10.draft, 10.archived.

### Task K2 — Archive, restore and supersede a claim; archive browse
- **Goal:** Knowledge survives archive; replacement does not inherit knowers.
- **Account:** GM, then PLAYER-A.
- **Steps:**
  1. Archive K1 (`The archive closes at dusk.`) with a reason; inspect **Who knows**; try a new learning/belief action if one is offered.
  2. ⟲ PLAYER-A reloads K1's prior URL (a player whose audience already includes it can still read it as published history, with no new write offered; it is absent from lists).
  3. ⟲ GM: **Restore** with a reason; record a legitimate belief update on Tobin.
  4. Create and publish replacement `The archive closes at midnight.` (subject The Archive, no audience); **Supersede** K1 with it.
  5. Open the old claim, the replacement and Mara's Knowledge list; expand the old belief.
  6. In Knowledge use the **Active / Archived / All** filter: Archived lists archived claims; All adds superseded; drafts never appear. ⟲ PLAYER-A: `lifecycle=archived|all` is refused (403) and no archive filter is offered.
- **Expect:** Archive keeps recorded knowledge but offers no new learn/belief writes; Restore is prominent and requires its reason; the superseded claim links its replacement and text-only details; the replacement does not inherit knowers; archive browse eligibility is GM with private-read authority only.
- **Refs:** TC-31 (amended per DR-1) · CP-7 (DR-5). **Ledger:** L-K2; 31.browse, 31.archived-direct, 31.supersede.

### Task K3 — Branch the timeline; the second campaign; denial against a foreign campaign
- **Goal:** Branch lineage is fixed; later parent events never leak.
- **Account:** ⟲ ADMIN (world Owner/Editor may branch; admin is system GM to host).
- **Start:** The Saltmarch → Timelines → Main Timeline → **Create branch**.
- **Steps:**
  1. Create `Branch Timeline` at a selectable recorded point before a later parent event (e.g., after T1's Meeting events, before T2's); record the branch world-time and event ids.
  2. **Create campaign** `Branch Campaign` on it (same ruleset). Inspect its clock, effective character build/state and event list against the branch point.
  3. ⟲ GM, in The Drowned Archive: record Other event `Parent after branch` at a later world time. Under Branch Campaign (⟲ ADMIN) search for it and open it by direct URL.
  4. ADMIN: advance Branch Campaign's clock independently to a later time; compare both clocks.
  5. Inspect branch party memberships before creating any; inspect timeline edit fields for lineage/branch-point controls.
  6. ⟲ PLAYER-A: type `/app/<BranchCampaignId>/home` and a nonexistent campaign id; repeat the J9 routes against the branch campaign id.
- **Expect:** Lineage is fixed; effective clock/build/state obey the branch point and exclude later parent changes; the post-branch parent event is absent and its branch-scoped URL is non-disclosing; branch clock writes never move the parent clock; party memberships start empty on the branch (do not fail the case for unimplemented inheritance); Player A cannot enter the branch campaign and gets the same response as for a nonexistent campaign.
- **Refs:** TC-52 · TC-49.3 (foreign/nonexistent campaign) · SR-M6 (hosting). **Ledger:** L-K3; 10.cross-scope, 49.foreign.

### Task K4 — Archive guards and restore
- **Goal:** Unsafe archives are blocked; safe ones succeed and restore.
- **Account:** ADMIN.
- **Steps:**
  1. Try to archive The Saltmarch and Main Timeline while active campaigns depend on them; read the explanations.
  2. Create `Empty Marsh` (world) with timeline `Empty Timeline` and no campaign; record its slug. For the timeline then the world: open the archive dialog, cancel, then archive with a reason, then restore with a reason.
  3. In The Drowned Archive **Settings**: change the name to `The Drowned Archive (renamed)`; save; **Archive campaign** with a reason; ⟲ PLAYER-A reloads the old Home URL and the campaign selector; ⟲ ADMIN **Show archived**, reactivate, reload player access and Settings; restore the original name.
  4. Restore anything you archived and verify everything is active.
- **Expect:** Dependent active campaigns block unsafe world/timeline archive with an explanation; eligible archive/restore succeed with reason/history and no deletion; cancel changes nothing; an archived campaign disappears from member selection and authorization; reactivation restores intended memberships and history and does not bypass a world/timeline prerequisite.
- **↺ RESTORE:** campaign reactivated, original name restored, Empty Marsh and Empty Timeline left **active** (needed by TC-53).
- **Refs:** TC-51. **Ledger:** L-K4.

### Task K5 — Validation, stale writes and uncertain retries
- **Goal:** Nothing is overwritten or duplicated.
- **Account:** GM and ADMIN in two profiles. **Start:** The Archive's Edit form.
- **Steps:**
  1. GM: blank the required name, submit; follow the validation summary link; restore the name; enter summary `GM pending` without saving.
  2. ADMIN (has the world Owner role and campaign authority): change The Archive's summary to `Admin saved`; save.
  3. GM: submit the old form. Read the stale notice; use **Load latest**; re-enter the intended summary; save. Reload; navigate Back to the editor with Network open.
  4. For one fresh create (e.g., a small party) save its successful request privately. **API-ONLY (documented gap):** replay it once with the same body and `Idempotency-Key` using DevTools "Edit and resend" (no UI replay exists). Inspect receipt/state/history. Reuse the key with a different body and read the conflict. Use browser offline mode to simulate a transport failure; restore connection and use the page's Retry.
- **Expect:** Field validation is associated with controls and changes nothing; the stale write refuses to overwrite and GM's pending input is retained until explicitly replaced; Load latest/reapply succeeds; authoring reads use `Cache-Control: no-store`; same-key replay returns the same minimal receipt and produces one object/effect/revision; changed-body key reuse conflicts; a transport retry does not duplicate an uncertain successful mutation.
- **Refs:** TC-48 · RC-01–03. **Ledger:** L-K5.

### Task K6 — CSRF, signed-out writes and authority revoked mid-edit
- **Goal:** Authority is checked on the next request.
- **Account:** GM; ADMIN for revocation. **Start:** an editable disposable location draft.
- **Steps:**
  1. Capture a successful edit request privately. Send a new intended edit (fresh idempotency key) with the CSRF header omitted, then an invalid CSRF value (DevTools "Edit and resend").
  2. With an authenticated HTTP tool against the test API submit the same mutation with a foreign `Origin`, then without the session cookie. Do not paste cookies into any file.
  3. GM begins another edit. ⟲ ADMIN revokes **only** GM's campaign GM role (Access). ⟲ GM submits the pending edit; refresh.
  4. ⟲ ADMIN restores GM's campaign GM role. Then ⟲ ADMIN ends GM's world **Editor** role (Sharing → **End role**) while GM has a draft open: ⟲ GM submits and reloads (permission-loss behaviour: private content cleared, typed input kept read-only, no submit). ⟲ ADMIN re-adds **Editor**.
- **Expect:** Missing/invalid CSRF and foreign Origin are rejected; signed-out mutation is 401; no version/content/state changes; a role revoked before the next request removes authoring despite a rendered form; refresh removes stale navigation; restoration restores intended access. (This does not exercise the documented in-flight adapter race.)
- **↺ RESTORE:** GM campaign role GM and world roles Editor + Reviewer both restored; verify in Access and Sharing.
- **Refs:** TC-54 · SR-M13. **Ledger:** L-K6; 54.csrf, 54.campaign-role, 54.world-role.

### Task K7 — Prepare Session 2, including the "undiscovered participant" variant
- **Goal:** The next session is ready; a participant a player may not discover is truly absent from their roster.
- **Account:** GM; ADMIN for the API-only grant.
- **Steps:**
  1. GM: create and publish NPC `Quiet Courier`. Open Session 2 → **Run** → Prepare → Participants: add Mara (Player character), Tobin (Player character), Archivist Sella (NPC), Quiet Courier (NPC).
  2. **API-ONLY (documented UI gap — the Access UI creates only character allow grants):** ⟲ ADMIN POST `/api/campaigns/<C>/resource-grants` with `{"character_id":"<courier id>","capability_code":"campaign.view","effect":"deny","grantee_campaign_membership_id":"<Player A membership id>","reason":"Roster check"}`, current CSRF header, fresh `Idempotency-Key` (same private-capture procedure as K5 and K8). If the API refuses `character_id` for this capability, retry with `entity_id` and record which field worked; if neither works record the variant Blocked.
  3. ⟲ PLAYER-A and PLAYER-B: read Session 2's Participants roster.
  4. ⟲ ADMIN revoke only this grant (`POST …/resource-grants/<grant-id>/revoke`); ⟲ PLAYER-A reload.
  5. GM: schedule-edit Session 2's summary; in Prepare, add a Session 2 encounter plan if desired. Leave Session 2 **scheduled**; do not start it.
- **Expect:** Player A's roster omits Quiet Courier entirely (no id, name, placeholder or count) while Player B's shows him; after revocation Player A's roster matches B's; participation grants no authority.
- **Refs:** CP-8 (undiscovered NPC variant) · TC-22 (member roster). **Ledger:** L-K7; 22.member-undiscovered.

### Task K8 — Targeted claim grants and preview agreement
- **Goal:** A targeted grant is never baseline GM authority; preview follows the subject.
- **Account:** ADMIN (browser request tool), OBSERVER and PLAYER-A.
- **Steps:**
  1. GM: create `This grant claim is public.` (settled, about Hollowmere): save, submit, approve, publish, make public at Hollowmere. Record its id. Confirm Observer and Player A can read it with no GM controls.
  2. **API-ONLY:** ADMIN POST `/api/campaigns/<C>/resource-grants` `{"knowledge_item_id":"<claim-id>","capability_code":"canon.edit","effect":"allow","grantee_campaign_membership_id":"<observer membership id>","reason":"Targeted claim test"}` (CSRF header + fresh key). Record the returned grant id.
  3. ⟲ OBSERVER: reload the claim with `?section=who-knows`; inspect canonical fields, available controls and authoring requests. ⟲ GM: Member preview the Observer with the same filters; compare.
  4. ADMIN POST the same route with `capability_code` `campaign.view`, `effect` `deny`, Player A's membership id, reason `Deny check`. ⟲ PLAYER-A: reload list/direct claim; ⟲ GM: preview Player A with identical filters.
  5. ADMIN revoke **only these two grants** (`POST …/resource-grants/<grant-id>/revoke`, fresh key each). Refresh both members and previews.
- **Expect:** The canon allow reveals permitted canonical fields but adds no stages, Save/Discard, sources/lifecycle or Who-knows controls or authoring requests; the view-deny removes the claim and makes direct access non-disclosing; preview follows the subject's deny, not the previewer's authority; revoking restores each subject's original projection; no unrelated role or grant changed.
- **Refs:** TC-58. **Ledger:** L-K8; 58.allow, 58.deny, 58.revoke.

---

## End of main journey

At this point the instance holds: one world with two timelines and a branch, two campaigns, a six-person cast, a completed first session and a prepared second. Continue with the [companion scenarios](PHASE14_15_COMPANION_SCENARIOS.md) (scoped-role matrix SR-M1–M16, recovery RC-01–10, navigation NV, privacy PV, TC-53, TC-55 accessibility pass, and **TC-56 on the separate clean installation**). Record the final owner decision only in the ledger header.

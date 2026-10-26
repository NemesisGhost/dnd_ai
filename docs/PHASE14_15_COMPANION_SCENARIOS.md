# Phase 14/15 companion scenarios (CP-11 restarted acceptance)

Prepared 2026-10-26 for code `9ab549ddbc78cb9b5c1aac9c99f3a967112edc62`, schema `140_clock_advance_details`. **Every scenario starts UNEXECUTED.** These sit beside the [main How-To journey](PHASE14_15_HOWTO_FIRST_CAMPAIGN.md); they cover negative cases, recovery checks, scoped-role variants and the two separate gates (accessibility, clean installation).

## 0. Where and when to run these

| Group | Where | When |
|---|---|---|
| RC, NV, PV | Same stack and database as the main journey, at the task named | After the referenced main-journey task |
| SR-M1…M16 | A **checkpoint copy** of the post-journey database (see below) — several change accounts and system roles | After the main journey (Section K) is complete |
| TC-53 | Same database, `Empty Marsh` from K4 | After K4 |
| TC-55 | Same database, populated by the main journey | After the main journey |
| TC-56 | **Separate clean installation** (`dnd_ai_m1415_clean_install_20261026`, ports 8002/5175) | Any time; never confuse its results with the main journey |

**Checkpoint for SR scenarios** (stop the stack first so no connection holds the template; the working acceptance database is not dropped or changed):

```powershell
& C:\Users\nemes\dnd_ai_evidence_20261026\cp11\stack\stop_stack.ps1 -ApiPort 8001 -WebPort 5174
# in a PostgreSQL 18 shell (credentials from the owner's .env; do not print them):
#   CREATE DATABASE dnd_ai_m1415_accept_sr_20261026 TEMPLATE dnd_ai_m1415_accept_clean_20261026;
& C:\Users\nemes\dnd_ai_evidence_20261026\cp11\stack\start_stack.ps1 -DbName dnd_ai_m1415_accept_sr_20261026 -ApiPort 8001 -WebPort 5174
```

Record the SR database name in the ledger run header. Restore the main stack afterwards with the same script and the main database name.

---

## 1. Scoped-role scenarios SR-M1 … SR-M16

Layers: system role (Administrator / Game Master / Player), world access (Owner / Editor / Reviewer / Reader / Viewer / use grant), campaign role, character/inventory permission. Persona windows are as in the main guide §4. "New account" means created from **Platform accounts** (record login/ids in the ledger; never the activation link).

| ID | Scenario | Steps | Expected |
|---|---|---|---|
| **SR-M1** | Admin creates a GM-only account; the GM signs in with no campaigns | ADMIN: Platform accounts → create `scoped.gm` and, in **System roles**, add Game Master. Activate via the one-time link in a clean window. Sign in. | Sees no campaigns; **Create a world** is offered and works (do not save, or save `Scoped GM World`); **no** Platform accounts. |
| **SR-M2** | Admin-only account | Create `scoped.admin`; give Administrator only (no Game Master). Sign in. | Manages accounts; **cannot create a world**; cannot read any world or campaign. |
| **SR-M3** | Populated-upgrade identity expectations on this copy | Compare Platform accounts and `/auth/session` to the main guide Task B1 table. | Identical (this is the accounts-only baseline). Record only; no change. |
| **SR-M4** | Editor vs Reviewer vs both | ADMIN gives `player_b` **Editor** only, then **Reviewer** only, then both (Sharing). For each, `player_b` (also campaign Player: temporarily give campaign role GM) tries to create a draft, submit, approve, publish. | Editor-only: can create/submit, cannot approve/publish. Reviewer-only: cannot create; can approve/publish a submitted draft. Both: full path, including self-approval. End roles afterwards. |
| **SR-M5** | Reader vs Viewer | On `Empty Marsh`: give `observer` **Viewer**; give `player_b` **Reader** (neither is a member of any campaign using it). | Reader sees the published three-category catalog (locations, organizations, religions) of the world; Viewer sees world, timelines and calendars only; neither sees campaigns or drafts. |
| **SR-M6** | Use-grant hosting | ADMIN (Sharing) → **Allowed to host campaigns**: grant system-GM `scoped.gm` the right on The Saltmarch. `scoped.gm`: New campaign. | Unused timeline ✔ (e.g., `What If Timeline`); used timeline ✖ with a reason. Revoking blocks new hosting only; the campaign created stays. |
| **SR-M7** | Revoke then restore system GM from an Owner | ADMIN removes Game Master from `scoped.gm`'s account while they own a world; next request they try manage/share/transfer/host. Then restore the role. | Manage/share/transfer/host vanish on the next request; edit/review/timelines persist; restoring returns them. |
| **SR-M8** | Campaign-only GM in a shared world | ADMIN: Sharing → **End role** on both of `gm`'s world roles. GM runs Session 2 (start, log, clock, event, encounter), creates and publishes a PC and an item instance, creates a world-time point. GM opens World records. **↺ RESTORE:** re-add Editor and Reviewer. | Runtime works; creating a PC, an item instance and a time point works; world records open in **runtime mode** with explained, disabled preparation/review sections; **no page is a blank 403**. |
| **SR-M9** | Same person GM in A and Player in B on one world | In Branch Campaign give `gm` the **Player** role (not GM). Switch campaigns in the GM window. | Capabilities switch with the campaign; nothing of A is visible from B. |
| **SR-M10** | Invitation and account split | Invite an existing account and a new one; accept both. Try to mint a system GM by giving someone only a campaign GM role. | Invited new account = Player; existing account keeps its system roles; a campaign GM role never creates a system GM. |
| **SR-M11** | World and campaign ownership transfer | ADMIN: Sharing → **Transfer ownership** to `scoped.gm` with "Keep me on the world as" Editor; try the last-owner guards. | Authorship unchanged; last-owner guard refuses removal; retain-as-Editor works. |
| **SR-M12** | Stranding and recovery | Disable the only Owner's account; read the stranded-world report (ids only); use the documented recovery command (mandatory reason). Try to disable the last administrator. | The report shows ids only; recovery needs a reason; the last administrator is protected. |
| **SR-M13** | Permission loss mid-edit | Covered by main-journey Task K6 (step 4); also end `gm`'s campaign role while a draft is open. | Private content cleared, typed input kept read-only, no submit. |
| **SR-M14** | Offline upgrade with a stale tab | Not repeatable on this baseline (already rehearsed at landing). Record **Blocked: rehearsed at landing; stale-tab exercise requires a pre-upgrade build**. | — |
| **SR-M15** | Viewer inventory | Give `observer` a **Viewer** relationship to Mara (Access → character relationships); open Mara; also add an explicit deny of the inventory capability. | Viewer reads an inventory-only view; no sheet, no mutation; an explicit deny wins; hidden properties absent from the response. |
| **SR-M16** | Character record navigation | Main-journey Task G5; also the same record from the campaign's Items entry path. | Same sections and Back from Characters and World; perspective unchanged. |

---

## 2. Recovery scenarios RC-01 … RC-10

**How to force a failed read after a confirmed write.** DevTools → Network → **Network request blocking** → add the **exact GET URL** the page re-reads after the write (copy it from a previous reload; it differs from the POST command URL). Perform the write. In Network confirm the **POST succeeded once** and the **GET failed**. Remove the block before pressing the page's retry. Never block the POST.

| ID | Scenario | Steps | Expected |
|---|---|---|---|
| RC-01 | Validation refusal retains input | Any form: submit invalid values. | Errors associated with controls; nothing saved; typed input retained. |
| RC-02 | Stale version | Main Task K5 steps 1–3. | Draft kept; **Load latest** then reapply; no overwrite. |
| RC-03 | Uncertain retry keeps the original payload and key | Offline mode during a save; restore; press Retry. In Network compare the two attempts. | The retry sends the **same** body and `Idempotency-Key`; one object results. |
| RC-04 | Quest command confirmed, re-read fails | Block the quest GET; complete an objective. | Notice "Saved. Latest data couldn't be loaded." (or equivalent) with a read-only **Load latest**; **no "done" announcement**; one POST; Load latest issues reads only. |
| RC-05 | Item operation / definition edit, re-read fails | Same on an item operation and an item definition edit. | Same behaviour. |
| RC-06 | Claim save: authoring read ok, **detail** read fails | Block the claim detail GET; edit and save a claim. | "Knowledge claim saved" is **not** announced; refresh-failed notice; the shown item is kept; retry is read-only. |
| RC-07 | Claim lifecycle step, read-back fails | Block the lifecycle/detail GET; submit a draft claim for review. | Step not announced done; page-level refresh-failed notice; Load latest never re-sends the step. |
| RC-08 | Receipt-version gating | After RC-04/06, press Load latest, then edit and save again. | The next write carries the **new** row version and a **new** key; no stale-version replay. |
| RC-09 | Independent drafts, record changes and late responses | Type drafts in two forms on different sections; throttle to Slow 3G; navigate to another record before a response returns. | A late response never overwrites another record's page; each draft is kept until saved/discarded; denied/unavailable clears retained private data. |
| RC-10 | **Callers fixed for DEF-001** (see the register §5 and [PHASE15_DEF001_INVENTORY.md](PHASE15_DEF001_INVENTORY.md) §4.1, rows 1–26) | **Applies to the reviewed DEF-001 head, not to `9ab549d`.** For each caller, block its re-read GET and perform a confirmed write: world/timeline archive and restore; party archive/restore and party members (end, add); NPC portrayal (save, detail level); character starting state and build activation; event void and correct (block the event GET, then separately the correction-preview GET); World Sharing (role, use grant, ownership transfer); Run Session start, end, log entry, travel; the campaign clock (advance, correct); session details save and archive/restore; encounter start and record a turn; NPC Run (hit points); dungeon Areas, Connections, Contents and Area now; a lifecycle step on a World record, an item and a quest; relationship add and edit; organization status and add member; recording a world time (World times page and the inline picker). | **Record exactly what is announced and shown.** Expected: the POST succeeds **once**; the page stays (no "could not be loaded" or "does not exist" screen) on the last good read; it says the change was saved and the displayed data is behind; **no "done" announcement** (only "Saved, but the latest data could not be loaded."); anything that would send the version or token still on screen is **held**; **Load latest** / **Try again** sends GETs only and, once a read works, the change is announced and the hold lifts; typed drafts elsewhere are kept. World Sharing after an ownership transfer: a 403 read-back removes the lists, moves focus to the page heading and still announces "Ownership transferred". Create-and-open / edit-and-return forms and the Phase 13 access/invitation/account pages are **not** in scope (inventory §4.3–4.4). A deviation is a new defect, not a variant. |

---

## 3. Navigation scenarios NV-01 … NV-08

| ID | Scenario | Expected |
|---|---|---|
| NV-01 | Deep links: quest, claim, item, world record, session run, character record, encounter (copy each URL; open in a new tab) | Page loads at the right section with coherent context; no blank outlet. |
| NV-02 | Section links (`?section=…`) on quest, claim, item, World record, character record, session run; an invalid section | Valid section selected; invalid resolves to the default without an extra Back entry. |
| NV-03 | Breadcrumbs from each of the above | Each link goes to the correct parent with context preserved. |
| NV-04 | Back/Forward and reload after navigating stages and sections | Same view; unsaved inputs behave as the case states. |
| NV-05 | Preserved filters and return context: World browse, Characters, Items (filters, hidden preview, page trail) → open a record → Back to … | Filters and return target preserved; changing search/category resets paging. |
| NV-06 | Entry paths: open the same Mara Voss / Brass Token / Archivist Sella records from World, Characters and Items | Same sections and Back behaviour regardless of entry. |
| NV-07 | Focus after navigation: move between sections/stages with keyboard; note where focus lands | Focus moves to the section heading; never to `BODY` after a withdrawn section. |
| NV-08 | Permission-loss fallback (Task K6): focus after the explanation appears | Focus lands on the permission-loss explanation, not the page body. |

---

## 4. Privacy scenarios PV-01 … PV-08

Check **both** what is rendered and what the response returns (hiding with CSS is a failure).

| ID | Scenario | Expected |
|---|---|---|
| PV-01 | Platform: non-admin personas call account endpoints and pages | Refused; no account data returned. |
| PV-02 | World: persona without a world role requests world pages, sharing, drafts | Refused or non-disclosing; same shape as a missing id. |
| PV-03 | Campaign: Player/Observer request GM pages (J9) and a foreign campaign | Supported permission state; no GM fields. |
| PV-04 | Ownership/inventory: Player A requests Tobin's inventory and character sheet | Refused or summary only; no inventory. |
| PV-05 | Targeted deny (K8) and Member-preview agreement | Direct member view and preview agree. |
| PV-06 | Revocation and unavailable records (K4, K6) | Next request reflects the change; unavailable state is neutral. |
| PV-07 | Member-safe rosters, history, event explanations and clock details (J2, I2, I3, G3, G4) | Only audience-safe labels; no hidden counts, no GM details, no build values for non-full tier. |
| PV-08 | No legacy private-text disclosure: search every player response for the ten markers and for any GM-only field name | Zero hits. |

---

## 5. TC-53 — an explicit World Viewer with no campaign membership

- **Account:** ADMIN to grant; OBSERVER to test. **Start:** `Empty Marsh` (active, from K4).
- **Prerequisite:** `observer` is **not** a member of any campaign using `Empty Marsh`.
- **Steps:**
  1. OBSERVER: **Worlds** — `Empty Marsh` is absent.
  2. ADMIN: Empty Marsh → **Sharing** → **Give someone a role**: login `observer`, Role **Viewer**. (A portal form exists now; the previous guide's operator script is not required.) ⟲ OBSERVER: refresh the session.
  3. OBSERVER: **Worlds** → Empty Marsh → its Timelines and a calendar; try its Edit, New calendar, New timeline, timeline Edit/Branch, New campaign.
  4. ADMIN: **End role** on that Viewer row. OBSERVER: refresh and revisit the deep links.
- **Expect:** Viewer opens world-scoped read pages without any campaign membership and the card is view-only; no management/create action is offered, not even as a blocked action; revocation removes the access on the next request; campaign-derived access to The Saltmarch is unaffected.
- **Refs:** TC-53 · SR-M5. **Ledger:** L-C53.

---

## 6. TC-55 — responsive, keyboard, screen-reader, zoom and reduced-motion pass

Run on the populated main database. The page list is the 24-row matrix in [PHASE15_MANUAL_ACCEPTANCE.md](PHASE15_MANUAL_ACCEPTANCE.md#pages-and-panels) (that file also has the per-page checklist). Each page/width/AT combination has its own ledger row (AX-01 … AX-40); do not collapse them.

1. Tools: NVDA or Narrator (record version); Chrome (record version); viewport presets 390, 1280, 2560 px (plus 360, 768, 1920 for Knowledge and Member preview); OS reduced motion on and off; browser zoom 200 %.
2. For each ledger row, open the actual fixture URL named in the guide's Record register and check, at each width: no horizontal **page** scroll (a table may scroll in its own box), no clipped/overlapping content, form/button wrapping, labels, tables, empty/error states.
3. Keyboard only (Tab/Shift-Tab, arrows, Enter, Space, Escape): navigation, a combobox selection, a failed validation, a confirmed and a cancelled dialog (focus contained and returned), one safe save; visible focus; logical order; section-heading focus.
4. Screen reader: headings/landmarks, field names/hints/errors, table headers, status messages; submit a safe command and confirm the success/error is announced. Repeat Knowledge as GM, Player, Observer, and Member preview as GM.
5. 200 % zoom and reduced motion: repeat page/control checks and one save each.
6. **New final layouts that did not exist when the 24 rows were written** (AX-25 … AX-40): World Sharing; Platform accounts system-role editor; character record navigation; session roster (GM and member); Knowledge archive filter; event explanation; clock cause form; Member preview; All worlds / Timelines / hierarchy context; World category counts; Parties disclosure.

Source inspection, component tests and headless screenshots **cannot** stand in for this pass. Anything that cannot be done (no screen reader available) is **Blocked**, never skipped silently.

---

## 7. TC-56 — clean-installation walkthrough (separate environment)

This must run on a **truly empty** installation: a freshly migrated database, the supported administrator bootstrap, no imported accounts, no development content. It is a different environment from the main journey and its results go to separate ledger rows (T56-01…T56-16) so they cannot be confused with the imported-account baseline.

**Environment (prepared, not started):** database `dnd_ai_m1415_clean_install_20261026` at `140_clock_advance_details` with **zero** accounts (verified at preparation). Ports 8002 (API) and 5175 (portal), origin `http://127.0.0.1:5175`.

**Start:** `& …\stack\start_stack.ps1 -DbName dnd_ai_m1415_clean_install_20261026 -ApiPort 8002 -WebPort 5175`

**Bootstrap the administrator (supported path; chooses your own password):**
```powershell
cd C:\Users\nemes\dnd_ai
# dbrun.py composes the database URL for the clean database in the CHILD environment only (nothing is printed):
.\.venv\Scripts\python.exe C:\Users\nemes\dnd_ai_evidence_20261026\cp11\tools\dbrun.py dnd_ai_m1415_clean_install_20261026 -- .\.venv\Scripts\python.exe scripts\bootstrap_admin.py --login-name admin --display-name "Platform Administrator"
```
The script prints a one-time activation link; open it only in your own browser to choose the password (**do not record the link or the password**). `admin` receives Administrator + Game Master. Create `manual.player` from **Platform accounts** (the supported account-creation flow), activate it in a second profile.

**Walkthrough (prefix `E`; record every generated URL in the ledger):** the sixteen steps are exactly the previous guide's TC-56 sequence — see [PHASE14_15_MANUAL_TESTING.md §TC-56](PHASE14_15_MANUAL_TESTING.md) — with two updates: (a) the bootstrap administrator already holds admin+gm; (b) the invited player receives an **explicit campaign role and a character relationship**, and the owner's inventory is reachable through the character record. Nothing in the scenario may be created by SQL, a seed script, an importer, Foundry or an AI provider.

**Expected:** The entire exit scenario works through supported portal actions from a clean deployment; definitions, timeline state, knowledge and history remain separate. This case plus the human accessibility matrix and green final-head CI is the clean-deployment gate; a snapshot-copy run alone does not satisfy it.

**Stop:** `& …\stack\stop_stack.ps1 -ApiPort 8002 -WebPort 5175`.

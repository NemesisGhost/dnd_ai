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
| RC-10 | **Callers fixed for DEF-001** (see the register §5 and [RC-10 inventory](PHASE14_15_COVERAGE_MATRIX.md#rc-10-operation-inventory), rows 1–26) | **Applies to the reviewed DEF-001 head, not to `9ab549d`.** For each caller, block its re-read GET and perform a confirmed write: world/timeline archive and restore; party archive/restore and party members (end, add); NPC portrayal (save, detail level); character starting state and build activation; event void and correct (block the event GET, then separately the correction-preview GET); World Sharing (role, use grant, ownership transfer); Run Session start, end, log entry, travel; the campaign clock (advance, correct); session details save and archive/restore; encounter start and record a turn; NPC Run (hit points); dungeon Areas, Connections, Contents and Area now; a lifecycle step on a World record, an item and a quest; relationship add and edit; organization status and add member; recording a world time (World times page and the inline picker). | **Record exactly what is announced and shown.** Expected: the POST succeeds **once**; the page stays (no "could not be loaded" or "does not exist" screen) on the last good read; it says the change was saved and the displayed data is behind; **no "done" announcement** (only "Saved, but the latest data could not be loaded."); anything that would send the version or token still on screen is **held**; **Load latest** / **Try again** sends GETs only and, once a read works, the change is announced and the hold lifts; typed drafts elsewhere are kept. World Sharing after an ownership transfer: a 403 read-back removes the lists, moves focus to the page heading and still announces "Ownership transferred". Create-and-open / edit-and-return forms and the Phase 13 access/invitation/account pages are **not** in scope (inventory §4.3–4.4). A deviation is a new defect, not a variant. |

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

Run on the populated main database. The page list is the 24-row matrix in [page/panel obligations](#tc-55-page-and-panel-obligations) (that file also has the per-page checklist). Each page/width/AT combination has its own ledger row (AX-01 … AX-40); do not collapse them.

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

**Walkthrough (prefix `E`; record every generated URL in the ledger):** the sixteen steps are exactly the previous guide's TC-56 sequence — see [TC-56 clean-deployment sequence](#tc-56-clean-deployment-sequence) — with two updates: (a) the bootstrap administrator already holds admin+gm; (b) the invited player receives an **explicit campaign role and a character relationship**, and the owner's inventory is reachable through the character record. Nothing in the scenario may be created by SQL, a seed script, an importer, Foundry or an AI provider.

**Expected:** The entire exit scenario works through supported portal actions from a clean deployment; definitions, timeline state, knowledge and history remain separate. This case plus the human accessibility matrix and green final-head CI is the clean-deployment gate; a snapshot-copy run alone does not satisfy it.

**Stop:** `& …\stack\stop_stack.ps1 -ApiPort 8002 -WebPort 5175`.

## Access-management fixture scenarios

These scenarios were extracted from the access contract's §6. They retain their historical
fixture names and any dated execution statements; they are not fresh CP-11 results. Run
them only against a deliberately selected fixture environment and record the actual SHA,
method and substitutions in the ledger. Do not mix their fixture IDs with the first-campaign
journey. Current endpoint/authority behavior is in [access control](api/ACCESS_CONTROL.md).

### Safe invocation

The script already refuses to run against anything but a local/self-hosted development database (`DND_AI_ENVIRONMENT` must be a local/dev value; a non-loopback `DATABASE_URL` host or a production-looking database name aborts unless `DND_AI_ALLOW_NONLOCAL_DEV_DATA=1` explicitly acknowledges it) and prints a password-redacted summary of the resolved target before any write. It now also requires `PHASE13E_DEV_ACCOUNT_PASSWORD` — checked before any database connection is opened at all:

```powershell
$env:PHASE13E_DEV_ACCOUNT_PASSWORD = Read-Host "Phase 13E development account password"
uv run python scripts/setup_phase13c_dev_data.py --user-id <existing-admin-user-id>            # preview (rolled back)
uv run python scripts/setup_phase13c_dev_data.py --user-id <existing-admin-user-id> --apply    # write
```

- **Never commit a real value.** `PHASE13E_DEV_ACCOUNT_PASSWORD` belongs only in your own shell session, or in the gitignored `.env` (see `.env.example`'s own placeholder) — never in a tracked file, never printed by this script, never in a commit.
- **Rerun safely at any time.** Every step is create-or-reuse by a fixed, deterministic key (normalized login name; `(campaign, user)` for a membership; `(membership, role)` for a role; `(campaign, grantee, capability, character)` for a grant) — a second `--apply` reuses every row, creates nothing new, and never rotates an already-created account's password. The one exception, `_ensure_phase13e_account_disabled`, is itself idempotent (disabling an already-disabled account is a documented no-op).
- **Recognize the intended local database** by the printed `target database (password redacted): ...` line before any write — it must name your own local/self-hosted PostgreSQL server (`127.0.0.1:5432` by default per `docs/DEVELOPMENT.md` §3.1), never a shared or production-looking host/database name.

### Seeded accounts

| Login | Display name | Campaign | Role (capability) | Character relationship | Explicit grant |
|---|---|---|---|---|---|
| `phase13e.gm2` | Phase13E Dev GM2 | Phase13C Campaign A | `campaign_owner` (`access.manage`) | none | none |
| `phase13e.player_a` | Phase13E Dev Player A | Phase13C Campaign A | `player` (`campaign.view` only) | `owner` relationship to Phase13C Character A | one revoked grant (`character.view_summary`) — must not appear on the overview |
| `phase13e.observer_a` | Phase13E Dev Observer A | Phase13C Campaign A | `observer` (`campaign.view` only) | none | one active grant (`character.view_full` on Phase13C Character A) — must appear |
| `phase13e.player_b` | Phase13E Dev Player B | Phase13C Campaign B | `player` (`campaign.view` only) | none (Campaign B has no character fixture of its own) | none |
| `phase13e.disabled` | Phase13E Dev Disabled Player | Phase13C Campaign A | `player` (`campaign.view` only), then disabled | none | none |

All five share the one password supplied via `PHASE13E_DEV_ACCOUNT_PASSWORD` for that run. The pre-existing administrator/GM account is never modified — no password, login identifier, membership, role, capability, or session change.

### 13E-B checkpoint 1 manual-validation scenarios

No seed change was needed for this checkpoint — the existing five accounts
above already exercise every rule §3a documents:

- **Ordinary role change:** log in as `phase13e.gm2`, open Campaign A's
  Access page, choose the "Change role" control on `phase13e.player_a`'s
  `player` role, select `observer`, Save. The overview refreshes to show
  `observer` in place of `player`; `phase13e.player_a`'s unrelated
  character relationship/grant rows are unaffected.
- **Last-manager protection (self-change):** still as `phase13e.gm2` —
  Phase13C Campaign A is `active` and `phase13e.gm2` is its sole
  `access.manage` holder (`campaign_owner`) — attempt to change `gm2`'s own
  role to `player`. Rejected (400); `gm2` keeps `campaign_owner` and the
  Access nav item remains visible on the next request.
- **Non-manager self-change:** log in as `phase13e.observer_a` — no
  `access.manage`, so the Access page (and its role-change control) is
  never reachable at all; confirms the control's absence is not the only
  thing standing between a non-manager and this mutation (`POST
  .../roles/{membership_role_id}/change` also still returns 403 directly).
- **Cross-campaign isolation:** as `phase13e.gm2` (Campaign A only), a
  direct `POST /campaigns/<campaign_a_id>/memberships/roles/<a
  membership_role_id belonging to Campaign B>/change` returns 404 — the
  same non-disclosing contract §3a documents.
- **Idempotent replay:** repeating the same change request with the same
  `Idempotency-Key` returns the original response unchanged, without
  creating a second new role-assignment row. The portal itself now
  generates and reuses this header automatically — no manual header
  entry is needed to exercise it by hand; a genuine network retry (e.g.
  toggling dev tools offline mid-Save) is the observable case.
- **Same-role no-op (correction pass):** in the Change-role control, the
  Save button stays disabled while the selected role equals the row's
  current role — there is no UI path to submit a no-op at all. A direct
  `POST .../roles/{membership_role_id}/change` with `new_role_id` equal
  to the row's current role returns 422 and leaves the row untouched.
- **Active-state boundary (correction pass):** these conditions are not
  reachable through the seeded dev accounts without a direct database
  edit (none of the five accounts' assignments are expired, ended, or
  role-deactivated), so this checkpoint's PostgreSQL-backed tests
  (`tests/database/test_api_memberships.py`) are the authoritative
  coverage for expired assignments, ended/non-active memberships, and
  inactive current/new roles — all rejected with a non-disclosing 409/404
  per §3a, never a 5xx.

### 13E-B checkpoint 2 manual-validation scenarios

One dev-data addition was needed for this checkpoint (see "Seeded accounts"
above, Player B): a second `campaign_owner` role on `phase13e.player_b` in
Campaign B, making Player B a second `access.manage` holder there alongside
the pre-existing `--user-id` account's own membership — deliberately placed
in Campaign B, not Campaign A, so it never disturbs `phase13e.gm2`'s own
role as Campaign A's sole manager (the checkpoint-1 last-manager scenario
above still depends on that).

- **Add a role:** log in as `phase13e.gm2`, open Campaign A's Access page,
  choose "Add role" on `phase13e.observer_a` (currently `observer` only),
  select `player` from the server-supplied list (which must already
  exclude `observer`), Save. The overview refreshes to show both `observer`
  and `player` on Observer A; nothing else on the row changes.
- **Add-role choices exclude held roles:** the same control on
  `phase13e.player_b` (Campaign B; holds `player` and `campaign_owner`)
  must never offer either of those two — only the remaining system-template
  roles (`gm`, `assistant_gm`, `observer`, `import_reviewer`,
  `rules_curator`).
- **Revoke a role:** as `phase13e.gm2`, revoke `phase13e.player_a`'s
  `player` role. Confirmation names both the member and the role. After
  confirming, the overview refreshes and Player A holds no roles;
  `player_a`'s unrelated character relationship is unaffected. (This
  leaves Player A a member with no role — a valid, if unusual, state this
  checkpoint's own scope does not additionally restrict; deliberately not
  reversed by this scenario since the dev fixture is recreated fresh by a
  clean seed run.)
- **Safe self-revocation with a second manager:** log in as
  `phase13e.player_b` (Campaign B), open the Access page, revoke your own
  `campaign_owner` role. Succeeds (200) — the `--user-id` account's own
  Campaign B membership remains a manager, so the campaign never loses its
  last one. Player B keeps its `player` role and its Access-nav item
  disappears on the next request (no more `access.manage`).
- **Last-manager rejection (revoke):** still as `phase13e.gm2` in Campaign
  A — the sole `access.manage` holder there, unchanged by this checkpoint's
  dev-data addition — attempt to revoke `gm2`'s own `campaign_owner` role.
  Rejected (400); `gm2` keeps the role and the Access nav item remains
  visible on the next request. Mirrors the checkpoint-1 last-manager
  scenario for change, now exercised for a bare revoke.
- **Disabled-account rejection (add role):** the seeded `phase13e.disabled`
  account (Campaign A, `player` role, platform-disabled) cannot be given an
  additional role: a direct `POST .../memberships/{disabled_membership_id}/roles`
  as `phase13e.gm2` returns 409 — no seed change needed, this fixture
  already existed for the read-side scenario in §3.
- **Cross-campaign isolation:** as `phase13e.gm2` (Campaign A only), a
  direct `POST /campaigns/<campaign_a_id>/memberships/<a Campaign-B
  membership id>/roles` (add), or `.../roles/<a Campaign-B membership_role_
  id>/revoke` (revoke), both return 404 — the same non-disclosing contract
  §3b/§3c document.
- **Idempotent replay (add):** repeating the same add-role request with the
  same `Idempotency-Key` returns the original response unchanged, without
  creating a second role row.
- **Idempotent replay (revoke):** repeating the same revoke request with
  the same `Idempotency-Key` returns the original response unchanged,
  writing no second `audit.change_log` row — the portal generates and
  reuses this header automatically, exactly like the existing change-role
  control.

### 13E-B checkpoint 3 manual-validation scenarios

No seed change was needed for this checkpoint — `phase13e.player_b`
(Campaign B only, no membership in Campaign A) already provides an
existing, eligible, cross-campaign account to add; the other four seeded
accounts already exercise the removal side.

- **Add an existing account:** log in as `phase13e.gm2`, open Campaign A's
  Access page, choose "Add campaign member", enter the login name
  `phase13e.player_b`, "Find account" — the resolved display name ("Phase13E
  Dev Player B") is shown for confirmation, never the raw account id.
  Select `observer` from the server-supplied initial-role list, Save. The
  overview refreshes to show Player B as a Campaign A member holding
  `observer`; Player B's own, separate Campaign B membership and roles are
  unaffected (a new, second membership row for the same user, not a
  reactivation of anything).
- **Eligibility excludes an already-active member:** the same "Find
  account" step with login name `phase13e.gm2` (Campaign A's own caller)
  or `phase13e.player_a`/`phase13e.observer_a` (already Campaign A members)
  returns "No eligible account found for that login name." — indistinguish
  able from a login name that does not exist at all.
- **Remove a member:** as `phase13e.gm2`, choose "Remove member" on
  `phase13e.observer_a`'s card. The confirmation names Observer A and
  explains that their campaign access will end. Confirm — the overview
  refreshes with Observer A no longer listed; Observer A's own active grant
  (`View Character Full Detail`) and `phase13e.player_a`'s unrelated
  character relationship are unaffected.
- **Self-removal with a second manager:** log in as `phase13e.player_b`
  (Campaign B, holding `campaign_owner` alongside the pre-existing
  `--user-id` account's own Campaign B membership), open the Access page,
  "Remove member" on Player B's own card. The confirmation names it as the
  caller's own access. Succeeds (200) — the `--user-id` account remains
  Campaign B's manager, so the campaign never loses its last one. Player
  B's Access-nav item disappears on the next request.
- **Last-manager rejection (removal):** as `phase13e.gm2` in Campaign A —
  the sole `access.manage` holder there — attempt "Remove member" on `gm2`'s
  own card. Rejected: the control shows "This member cannot be removed —
  the campaign must always retain at least one access manager."; `gm2`
  remains a Campaign A member and the Access nav item stays visible on the
  next request.
- **Disabled-account/cross-campaign eligibility boundaries not seed-
  exercisable:** an eligible-but-disabled account, and an already-ended
  (re-addable) membership, are not reachable through the five seeded
  accounts without a direct database edit (`phase13e.disabled`'s only
  membership is already open in Campaign A, so it is excluded by the
  "already a member" rule before its disabled status is ever reached) —
  this checkpoint's PostgreSQL-backed tests
  (`tests/database/test_api_membership_lifecycle.py`) are the authoritative
  coverage for a disabled target's exclusion, an inactive/cross-scope
  initial role, a non-active target campaign, and a duplicate-open-
  membership race, all rejected with a non-disclosing 404/409, never a 5xx.
- **Idempotent replay (add):** repeating the same add-member request with
  the same `Idempotency-Key` returns the original response unchanged,
  creating no second membership or role row.
- **Idempotent replay (removal):** repeating the same removal request with
  the same `Idempotency-Key` returns the original response unchanged,
  writing no second `audit.change_log` row.

### Character-relationship-management checkpoint manual-validation scenarios

No seed change was needed — `phase13e.player_a`'s pre-existing `owner`
relationship to "Phase13C Character A" (see the seeded-accounts table
above) already provides an existing relationship to change/revoke, and
`phase13e.observer_a` (no relationship of their own) provides a target
with nothing yet to add to.

- **Add a character relationship:** log in as `phase13e.gm2`, open Campaign
  A's Access page, expand `phase13e.observer_a`'s card, choose "Add
  character relationship". "Phase13C Character A" and every currently
  active relationship type are offered (server-authoritative, never
  hardcoded). Select "Viewer", Add. The overview refreshes to show the new
  relationship on Observer A's card; `phase13e.player_a`'s own unrelated
  `owner` relationship to the same character is unaffected (sibling
  relationships preserved).
- **Add excludes an already-active combination:** on `phase13e.player_a`'s
  own card, "Add character relationship" with "Phase13C Character A"
  selected omits "Owner" from the relationship-type choices (already
  active for that exact character) while still offering every other type —
  proving the exclusion is per-`(character, type)` combination, not a
  blanket "already has a relationship to this character" rule.
- **Change relationship type:** as `phase13e.gm2`, choose "Change type" on
  `phase13e.player_a`'s "Owner" relationship, select "Primary Controller",
  Save. The overview refreshes to show "Primary Controller" in place of
  "Owner" for the same character; the old assignment's row is revoked, not
  overwritten (temporal history preserved, verifiable via `tests/database/
  test_api_access_grants.py::test_changing_a_character_relationship_type_succeeds`'s
  own database assertions).
- **Revoke a character relationship:** as `phase13e.gm2`, choose "Revoke
  relationship" on `phase13e.player_a`'s current relationship. The
  confirmation names the character and member and explains that the
  character perspective will no longer be available. Confirm — the
  overview refreshes with the relationship gone; on Player A's own next
  `GET /auth/session`, the corresponding entry disappears from `character_
  perspectives` (`dnd_ai.queries.bootstrap` re-resolves fresh every call —
  no browser-session revocation needed).
- **Idempotent replay (add/change):** repeating the same add or change
  request with the same `Idempotency-Key` returns the original response
  unchanged, creating no second relationship row.
- **Idempotent replay (revoke):** repeating the same revoke request with
  the same `Idempotency-Key` returns the original response unchanged,
  writing no second `audit.change_log` row.

### Checkpoint 5 (direct resource-grant management) manual-validation scenarios

No seed change was needed — `phase13e.observer_a`'s pre-existing active
grant (`View Character Full Detail` on "Phase13C Character A", see the
seeded-accounts table above) already provides an existing grant to revoke,
and `phase13e.player_a` (no grant of its own beyond the pre-existing
*revoked* one) provides a target with room to add a fresh one.

- **Add direct resource access:** log in as `phase13e.gm2`, open Campaign
  A's Access page, expand `phase13e.player_a`'s card, choose "Add direct
  resource access". "Character" is the only resource type offered;
  "Phase13C Character A" and every currently grantable capability not
  already active for it are offered (server-authoritative, never
  hardcoded). Select "View Character Knowledge", Add. The overview
  refreshes to show the new grant on Player A's card; `phase13e.observer_
  a`'s own unrelated active grant to the same character is unaffected
  (sibling grants preserved).
- **Add excludes an already-active combination:** the pre-existing
  *revoked* `character.view_summary` grant on `phase13e.player_a` does
  **not** exclude `character.view_summary` from the capability choices
  (only a currently *active* combination is excluded) — confirming the
  exclusion is about current state, not history.
- **Revoke direct resource access:** as `phase13e.gm2`, choose "Revoke
  access" on `phase13e.observer_a`'s active grant. The confirmation names
  Observer A, the permission (`View Character Full Detail`), and the
  resource ("Phase13C Character A"), and explains that access may
  disappear immediately. Confirm — the overview refreshes with the grant
  gone; `phase13e.observer_a`'s own unrelated `observer` role is
  unaffected.
- **Non-character target kinds, access-group grants, and deny effects not
  seed-exercisable:** none of the seeded accounts has a grant of any of
  the other five target kinds, an access-group-targeted grant (access
  groups have no management UI at all yet), or a `deny`-effect grant (the
  portal's own Add flow only ever creates `allow`) — this checkpoint's
  PostgreSQL-backed tests (`tests/database/test_api_access_grants.py`,
  `test_resource_grant_concurrency.py`) and portal tests (`AccessPage.
  test.tsx`, `CampaignAccessPage.resourceGrant.integration.test.tsx`) are
  the authoritative coverage for those, plus the disabled-account/ended-
  membership/inactive-campaign/inactive-target/deactivated-or-incompatible-
  capability eligibility boundaries, all rejected with a non-disclosing
  404/409, never a 5xx. A `deny` grant can still reach the portal if
  created directly against the database (or by a future increment) —
  `RevokeResourceGrant` renders it with effect-aware wording ("Remove
  denial" rather than "Revoke access", explaining that access may be
  *restored* from another source rather than lost) rather than the
  allow-oriented copy this checkpoint originally shipped with (correction).
- **Idempotent replay (add):** repeating the same add request with the
  same `Idempotency-Key` returns the original response unchanged, creating
  no second grant row.
- **Idempotent replay (revoke):** repeating the same revoke request with
  the same `Idempotency-Key` returns the original response unchanged,
  writing no second `audit.change_log` row.

### Checkpoint 6 (campaign access-group management) manual-validation scenarios

**Not manually exercised against the dev fixture as part of this
checkpoint** — no seed change was made, and no accepted/Codex-reviewed
manual walkthrough of this checkpoint has occurred. `tests/database/
test_api_access_groups.py`/`test_access_group_concurrency.py` and the
portal's own component/hook/integration tests are the authoritative,
already-run coverage. A future manual pass against `scripts/
setup_phase13c_dev_data.py` should cover, at minimum: creating a group as
`phase13e.gm2`; adding `phase13e.player_a`/`phase13e.observer_a` to it;
granting the group `character.view_summary` on "Phase13C Character A" and
confirming both members gain that view without an individual grant of
their own; deactivating the group and confirming both members lose that
access on their next request while their own direct roles/grants are
unaffected; reactivating it and confirming it starts empty (no members, no
grants) until explicitly re-populated; and reviewing the resulting
`access_group`/`access_group_membership` audit-history entries for correct
labels.

### Checkpoint 13 (effective-access explanation) manual-validation scenarios

Exercised against the dev fixture during this checkpoint's own development:
`GET /campaigns/{campaign_a_id}/members/{membership_id}/effective-access`
for `phase13e.gm2`, `phase13e.player_a`, and `phase13e.observer_a` (as
`phase13e.gm2`, the `access.manage`-holding actor). Results matched §6's own
"Expected access behavior" below exactly:
- GM2's own explanation: `access.manage`/`canon.edit` each with one `role`
  source (`Campaign Owner`); `campaign.view` with two role sources
  (`Campaign Owner` and `Player`); no denials.
- Player A's own explanation: `campaign.view` with one `role` source
  (`Player`); no other capability; no denials.
- Observer A's own explanation: `campaign.view` with one `role` source
  (`Observer`); `character.view_full` with one `resource_grant` source
  (labelled with the grant's own `reason`, target `Phase13C Character A`);
  no denials — matching §6's own "Observer A shows exactly one grant" fact
  above, now explained rather than merely listed.

### Checkpoint 15 (per-resource audience preview) manual-validation scenarios

`tests/database/test_api_preview.py`'s own fixture (GM/player subjects, a
`gm_only` quest objective, a knowledge item with a party belief distinct
from ground truth) is the primary evidence — including the byte-identical
comparison against each subject's own authenticated request, for both a GM
and a player subject. A full walkthrough against the dev fixture (creating
a `gm_only`-objective quest and a belief-divergent knowledge item under
"Phase13C Campaign A", then previewing both as `phase13e.player_a`,
`phase13e.observer_a`, and `phase13e.gm2` from `phase13e.gm2`'s own signed-in
session) is deferred to a future manual pass, matching checkpoint 6's own
"not yet exercised against the dev fixture" precedent above — the automated
byte-identical test already proves the property this manual pass would
otherwise exist to confirm.

### Expected access behavior

- **GM2** can log in and open the Access page directly, with no platform-administrator privilege needed — it holds `access.manage` only through the ordinary `campaign_owner` role.
- **Player A** and **Observer A** hold no `access.manage`: the Access nav item must not appear for either, and a direct `GET /campaigns/{campaign_a_id}/access-overview` request must return `403`.
- **Cross-campaign isolation:** Player A never sees Campaign B in their campaign list (no membership, no relationship reaching it); Player B never sees Campaign A, and vice versa.
- **Grants:** on Campaign A's Access overview, Observer A shows exactly one grant (`View Character Full Detail`); Player A shows none — the revoked grant is excluded, proving the same exclusion `tests/database/test_api_access_overview.py` already covers automatically.
- **Disabled account:** `phase13e.disabled` cannot authenticate and holds no usable browser session, but its Campaign A membership still appears on the Access overview with an ordinary "Active" *membership* status — `dnd_ai.queries.access_overview` deliberately never consults account-wide `security.users.lifecycle_status_id` (see §3 above). This is the documented contract, not a defect; the fixture does not invent a "disabled" label the implemented response does not provide.

## TC-55 page and panel obligations

The former Phase 15 manual matrix is consolidated here. Blank cells remain unexecuted;
record new results in the ledger, not this specification. The old row numbers identify
page obligations, not new TC IDs. P02's accepted task/selected-context contract in UI_DESIGN
supersedes old query-string instructions; a URL must never create an unauthorized perspective.
Dates and runtime selection come from the current run header, not the former setup ports.

## What to check on every page below

For each page, at **390 px**, **1280 px** and **2560 px** wide:

- **Layout:** no horizontal page scroll (a table may scroll inside its own box); nothing is cut off or overlaps; the form is usable.
- **Keyboard only:** every control is reachable in a sensible order, has a visible focus ring, and can be operated (including dialogs, comboboxes and the compare form); Escape closes a dialog and focus returns to what opened it.
- **Screen reader (NVDA or Narrator):** the page title and headings are announced; fields have names; errors are announced and linked to their field; the result of a command is announced (the live region); a table or a list reads sensibly.
- **200% zoom:** still usable.
- **Reduced motion:** with the operating system setting on, nothing animates in a way that is distracting.

Record **Pass**, **Fail** (with a note and the issue), or **Accepted** (with the owner's reason) in the three result columns. Leave a cell empty if it was not checked.

## Pages and panels

| # | Page or panel | Route | 390 px | 1280 px | 2560 px | Keyboard | Screen reader | Zoom 200% | Reduced motion | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Calendar creation | `/worlds/:worldId/calendars/new` | | | | | | | | |
| 2 | World times and the clock card | `/app/:campaignId/world-times`, Campaign Home | | | | | | | | |
| 3 | Location create and edit | `/app/:campaignId/world/location/new`, `…/edit` | | | | | | | | |
| 4 | Organization and religion create and edit | `…/world/{organization,religion}/new`, `…/edit` | | | | | | | | |
| 5 | NPC and player-character create and edit | `…/characters/npc/new`, `…/characters/pc/new`, `…/characters/:id/edit` | | | | | | | | |
| 6 | Character builds | `…/characters/:id/builds`, `…/builds/new` | | | | | | | | |
| 7 | NPC portrayal and the Run this NPC panel | `…/characters/:id/portrayal`, a character's World page | | | | | | | | |
| 8 | Parties and party members | `…/parties`, `…/parties/:id`, `…/parties/:id/edit` | | | | | | | | |
| 9 | Session create and edit | `…/sessions/new`, `…/sessions/:id` (edit in place) | | | | | | | | |
| 10 | Session run page: stages (Prepare, Run session, Wrap up), participants, encounter preparation, log, travel, award item, encounters, review, start/end, in-world time bar | `…/sessions/:id/run[?section=…]` | | | | | | | | |
| 11 | Events: record and correct | `…/events/new`, `…/events/:id` | | | | | | | | |
| 12 | Quest editor and quest progress | `…/quests/new`, `…/quests/:id/edit`, `…/quests/:id/progress` | | | | | | | | |
| 13 | Knowledge claim page (claim, About, canonical information, character knowledge, Who knows this roster) and the New claim form | `…/knowledge/new`, `…/knowledge/:id` (`/edit` and `/audience` redirect here) | | | | | | | | |
| 14 | Dungeon, areas, connections, features, hazards, interactables, area state | `…/world/dungeon/new` (opens the dungeon's Areas), the workspace `…/world/location/:dungeonId?section=areas\|connections` and `…/world/location/:areaId?section=contents\|area-now`, and the details-only `…/dungeon/:id/edit`, `…/areas/:id/edit` (the old `?section=structure` redirects to `areas`) | | | | | | | | |
| 15 | Relationships roster, Add form and editor (rows and period/visibility labels, Include archived, revealed Add, Details / Perspectives / End or archive, discard prompts, Members and offices handoff) | the Relationships panel on location, organization, religion and character pages | | | | | | | | |
| 16 | Organization members and offices | `…/world/organization/:id` | | | | | | | | |
| 17 | Item definitions | `…/item-definitions`, `…/new`, `…/:id` | | | | | | | | |
| 18 | Items and the Run this item panel; inventories | `…/items`, `…/items/new`, `…/items/:id/edit`, an item's World page, a character's Inventory, a party's Party inventory | | | | | | | | |
| 19 | Prepare and operate an encounter (compact participant roster: add, change side with Save only when changed, remove; no initiative) | `…/sessions/:id/encounters/new`, `…/encounters/:id` | | | | | | | | |
| 20 | Sources section and provenance | a record's Sources section, `…/world/:category/:id/provenance` | | | | | | | | |
| 21 | Review queue | `…/review` | | | | | | | | |
| 22 | Revision history and comparison (check the table at 2560 px and at 390 px, and with a screen reader) | `…/world/:category/:id/history` | | | | | | | | |
| 23 | Lifecycle panel (submit, approve, publish, supersede, archive, confirmation dialogs) | on any record | | | | | | | | |
| 24 | Sidebar and navigation, including the capability-gated links (Review, Items, Item definitions) for a GM and for a player | every page | | | | | | | | |

### Row 10 detail: the staged Run Session page

Check at 390, 1280 and 2560 px, with the keyboard only, at 200% zoom, and with a screen reader. Use one scheduled, one in-progress and one completed session.

1. The session list's "Run …" link opens Prepare › Participants for a scheduled session, Run session › Session log for one in progress, and Wrap up › Session review for a completed or archived one.
2. The breadcrumb reads "Sessions › [title] › Run session": Sessions opens the list, the title opens the session page, "Run session" is not a link. The campaign context panel (world, timeline, campaign, perspective) is the same before and after.
3. Choosing each stage never starts, ends or changes the session (no POST in the network tab). The section menu lists only the current stage's sections, and exactly one section is shown, with a heading, a purpose line and a visible border.
4. Type a log entry and GM notes, switch to Prepare and back: the text is still there. The same for the Travel and Award choices, the Add-participant choice and a half-entered Advance time. Back and Forward move between visited sections without losing it; reloading `?section=travel` reopens Travel; `?section=bogus` opens the default with no extra Back step.
5. Participants: add with each role (Player character, NPC, Guest); remove one and see them under "Left". Encounter preparation: prepare an encounter, return with "Run the session", start it, return again and find it under Run session › Encounters.
6. Travel: individual travelers versus a whole party, with the optional route. Award item: only eligible items; recipients are present participants. Session log: the two audience hints read "Visible to everyone in the campaign." and "Visible only to people who can edit canon."; the optional "When" and "Record a new time" work.
7. The "Campaign time (in-world)" bar shows in every stage; Advance/Correct appear only in Run session, and the correction confirmation works. Real-world times are labelled "Real-world start/end".
8. Start session appears only at the top of Run session for a scheduled session and needs its button. End session (Wrap up) opens a confirmation (recap, "Ends at"); Cancel leaves the session in progress; confirming completes it and every section then explains why it is read-only.
9. Session review shows the overview, participants, log and encounters; each "go to" link opens the right section, or a reason is shown instead.
10. A member without `canon.edit` sees the "no permission" message and none of the stage controls.

### Row 13 detail: the Knowledge claim page

Check at 390, 1280 and 2560 px, keyboard only, and with a screen reader, as a GM, as a player with a selected character, and as a member with `campaign.view` only.

1. Knowledge cards: the claim text leads, the kind is a quiet label, a labelled About area names the subject and type, and the card and its subject open separately (Tab reaches each). The grid never squeezes cards narrower than readable; search, view, party/character selection, public filter and Load more still work.
2. A card opens the claim page with the same character and party. The header shows the breadcrumb (Knowledge › Claim, the Knowledge crumb keeping the perspective), the claim as the heading, the About this World entry block and the real status badge. Under it, as a GM, the stages 1. Prepare, 2. Review & publish and 3. Use in play, with the section menu of the current stage; the stage links never show a status.
3. Navigation: every stage and section link (and the header Next link) only changes the address: nothing is saved, no status changes, no draft is discarded. Back and Forward walk the sections; the authorized selected context survives each supported navigation; one section is visible at a time and focus moves to its heading; each stage reopens on the section last used.
4. GM, draft: fields are controls at once. Change the claim: "Unsaved changes" appears and Save claim enables; Discard restores it; Save stays on the page and "Claim saved" appears only after the save succeeds. A published claim asks for confirmation first. After someone knows the claim, claim, kind and subject are disabled with the reason.
5. Sources: the copy says they are optional, can change at any status and do not affect review or publication. Write and attach a source with the network panel open: two requests with two different `Idempotency-Key` values (`<key>.create`, `<key>.attach`), both accepted. (Reproduced before the fix: with one key for both, the attach is refused with 409.) View provenance returns to the Sources section with the perspective. A typed source blocks leaving the page with the "Discard unsaved changes?" dialog.
6. Review and publication: submit a draft for review (with an unsaved claim edit it asks first and the edit stays, shown as "Unsaved changes not applied" with Discard); in Review claim read the summary and Approve; in Publication publish. An approved claim whose subject is unpublished says "Publish its subject first" in the header and Publication, links to the subject and offers only Return to draft (under More). The copy never says publishing tells anyone and never asks for a source.
7. Who knows this: the three groups stay separate; each action is beside its heading and opens a compact form; Details expands a knower inline. Tell a party, record that someone learned it or told another, make it public, change a belief: each succeeds on its own, closes its form, and never touches an unsaved claim edit. A refused action keeps the form and shows its error under that group. With every active party told, "Every active party already knows this" replaces the button.
8. Restrictions: for a draft, in review, approved or rejected claim one note names the status and the real next step, no action button is offered and recorded rows stay readable. An archived claim says what was recorded is kept and nothing new can be recorded until it is restored (Restore is the primary button in Publication and asks for a reason); a superseded claim links to its replacement and says to record knowledge there; belief details of both are text only.
9. Exceptional states: rejected (Return to draft is offered directly and makes the claim editable again), deprecated (no step offered, no Next link), archived (Archived badge beside Canon), superseded (Replaced by banner).
10. Player or reader: the same values as text, no stages, no Save/Discard, no Who knows this, no status badge, and canonical truth and sensitivity absent unless the server returned them. A `?section=` in the address is ignored. A member with only a targeted `canon.edit` allow on the claim sees the same read-only page. With no character selected, Character knowledge is one message asking for a perspective.
11. Widths: 360, 768, 1280 and 1920 px have no horizontal page scroll, the stage links wrap and the section menu is a left column from 64rem and a wrapping row below it. Closing the tab with an unsaved draft shows the browser's own prompt.
12. Old addresses `…/knowledge/:id/edit` and `…/knowledge/:id/audience` land on `?section=claim` and `?section=who-knows` with authorized selected context preserved; `#claim` and `#who-knows` map to the same sections.

### Knowledge Member preview

Check at 360, 768, 1280 and 1920 px, keyboard only, and with a screen reader, as a GM or owner (`access.manage`) and as a player.

1. Sidebar: for the GM, Knowledge expands into Claims and Member preview (the group opens on a Knowledge route; the active child is marked); for a player it is the plain Knowledge link with no Member preview. The normal Knowledge collection and claim pages have no "Preview as member" control.
2. Member preview before a choice: only the "Choose a member to preview" state and the member list (open, active members); no Knowledge is shown and no Knowledge request is made.
3. Choose a member: the bordered banner reads "Previewing as [member] ([roles])", says read-only and separates member access from fictional character and party knowledge; the URL holds `?member=`. Only that member's own characters are offered, and a party only for a character that may use it. The collection lists only what that member would see (compare it with the GM's own Knowledge page: drafts and unpublished claims are absent for a player).
4. Open a claim from the preview: it stays in the preview (breadcrumb Knowledge › Member preview › Claim, the same banner), shows the member's projection as text (no truth or sensitivity unless the member's own request would include them), has no edit, source, lifecycle or knowledge-management control, and the subject is not a link. With a party selected the knowledge section is headed "Party knowledge: [party]"; with only a character it is "Character knowledge: [character]"; when the projection includes no awareness, confidence or sharing details it says so neutrally rather than claiming no knowledge is recorded. Back returns to the same filters, page and perspective.
5. Invalid or stale selections: an unknown member, a character the member does not have, or a party without a usable character each give a clear error and no Knowledge request; changing the member clears the previous member's claims immediately; reload reproduces the same preview from the address.
6. Return to Knowledge (banner link or Claims) lands on the ordinary collection with no member, perspective or filter from the preview; the GM's own Knowledge page is unchanged.
7. A player who types the preview address is told they may not preview, and no preview or member-list request is made.
8. Keyboard: the sidebar group, the child links, every selector and the cards are reachable and operable; focus is visible; no horizontal page scroll at 360 px.

## Carried items from earlier phases

| Item | Result | Notes |
|---|---|---|
| Phase 14: sidebar and hierarchy correction (navigation between worlds, timelines, campaigns) | | |
| Phase 15.1: the typed authoring forms' unsaved-change guard, server-code to field-error mapping, `no-store` reads after a back navigation | | |
| Player account: every GM page above is absent from the navigation and a typed URL shows "no permission" or "not found", never a partial page | | |

## Session travel (recorded, linked and reviewed)

Use a throwaway database and the 8001/5174 servers. Not run yet; every result is blank on purpose.

| Check | Result | Notes |
|---|---|---|
| GM starts a session and records travel for two participants from two different places to one destination with a GM note and an explicit earlier in-world time: the history under the form shows two origin lines, the time and the note; the Session log shows the same entry; the campaign time bar is unchanged | | |
| A Log draft and an Award item draft typed before the travel are still there afterwards | | |
| Choosing a party that contains a non-participant: the preview marks them "(not in this session)" and the receipt moves them too | | |
| Recording travel to where everyone already is: "Nothing was recorded", history unchanged | | |
| Ending the session in a second tab, then recording travel in the first: a clear message, the form is replaced by its reason, history still visible | | |
| Wrap up: Review shows Travel (N); a completed session opened later shows the same in Session detail and in the Run page's Travel section with no form | | |
| A player with a restricted traveler and a restricted place: the traveler is absent, the place reads "A place you cannot see", no GM note, no counts, no new Knowledge | | |
| Editor event page of the travel event: places named and the session linked; an old unlinked travel event: places named, no session link | | |
| Standalone: the NPC "Run this NPC" move still records an unlinked event and does not appear in any session | | |
| Desktop and 390px widths, each supported theme, keyboard-only use of the new fields (time, notes, party, preview), screen-reader announcement of the saved journey | | |

## Character Relationships (player-facing, read-only)

Use a throwaway database and your own ports. GM fixture: a player character Aria linked to a player; relationships with Ser Bran (family, Parent/Child), a guild membership (office and rank), an ended employment, a not-yet-started worship, a private ownership and an archived alliance; a second NPC with no player path. Give the player a view-summary path to Ser Bran in Access and set the campaign clock.

| Check | Result | Notes |
|---|---|---|
| As the player with no party selected, Characters → Aria: **Relationships** lists Ser Bran (link), the guild (link, office and rank on Details), the ended employment (**Ended**, name only) and the worship (**Not started**); not the NPC without a path, the private ownership or the archived alliance; nothing hints at hidden ones | | |
| **Details** shows the period against campaign time, the timeline status and the kind's fields, and the Network tab shows no request on expand and no `/authoring/` request on the page | | |
| Clicking Ser Bran opens his summary page; removing the path in Access and reloading Aria drops the Ser Bran relationships | | |
| A character with nothing visible shows **No visible relationships.** | | |
| Stopping the API and reloading shows **Relationships could not be loaded.** with **Try again**, distinct from empty; restarting and retrying lists them | | |
| Advancing the clock past an end date turns the row's badge to **Ended** | | |
| As the GM, Aria's page has no Relationships section and a **Relationships** link in Manage that opens the World workspace section unchanged | | |
| Desktop and 390px widths, each supported theme, keyboard-only use of the **Details** toggle (`aria-expanded` announced) | | |

## Organization view (player-facing, read-only)

Use a throwaway database and your own ports. GM fixture: a published government R Council with a form of government and a founding time, and the timeline clock set; public memberships for the player's character (office and rank), a published organization (no office), an NPC the player cannot discover, an ended stint and one starting after the clock; a private stint. Sign in as the player, then as the GM.

| Check | Result | Notes |
|---|---|---|
| The player opens R Council from World: Overview shows Type, Form of government, Current status and Founded; no GM notes and no identifiers | | |
| **Members and offices** is a heading inside the page; the player's character (linked) shows its office and rank, the organization (linked) shows "No office recorded"; the ended stint says **Ended** and the future one **Not started**; *As of* names the clock | | |
| The undiscoverable NPC, the private stint, any "Vacant" text and any count of hidden members are absent, also from the members response in the network panel; only the detail, lifecycle and members GETs are sent | | |
| With the members request blocked, the section says "Members could not be loaded." with **Try again** and the rest of the page stays | | |
| A second player with no relationship to the character does not see it; after the GM gives them a viewer relationship to the NPC, the NPC appears | | |
| As the GM, the workspace's Members and offices still lists every stint with the visibility column, **Add a member**, **Edit** and **Set status**, and saving works; no second roster appears | | |
| Desktop and 390px widths, each supported theme, keyboard order of the member links, badges read as text, loading announced (`status`) and failure announced (`alert`) | | |

## TC-56 clean-deployment sequence

The original sixteen-step sequence is preserved below as a specification. The current
companion TC-56 environment/persona amendments apply; original execution markings, if any,
are historical and never become new results. Use the ledger for the current run.

### TC-56 — Clean-deployment Phase 15 exit walkthrough

- [ ] Test case executed and result recorded.

**GIVEN**

1. Log in as `admin` on a **separate clean acceptance deployment**. You should see an empty world/campaign collection and New world; this administrator was provisioned through the supported account bootstrap/activation process.
2. A separate active account `manual.player` is available through supported account registration/activation. It should see no campaign before invitation. The DB is freshly migrated to branch head with required immutable reference data; no dev content fixture has been loaded. Use a fresh prefix `E` and record all generated URLs.

**WHEN**

1. Create `E World`, selecting the offered allowed/default ruleset and naming its initial primary timeline `E Primary`; create `E Campaign` on that timeline with the offered ruleset version through the three-step campaign setup.
2. Create `E Calendar` with one 30-day month; record year 1/day 1 times 09:00, 10:00 and 11:00; set the campaign clock to 09:00.
3. Create/publish region `E Region` and settlement `E Town` beneath it; create/publish `E Council` headquartered at Town.
4. Create/publish Human/Medium NPC `E Guide` and PC `E Hero`, origin Town; initialize 20/20 HP and create/activate a valid Fighter 1 build for each.
5. Invite `manual.player`; accept as that account. As admin assign Player role and Owner relationship to Hero; verify the player's campaign/character selection.
6. Create `E Party`; add Hero at 09:00. Schedule `E Session`, add Hero/Guide participants and start it.
7. Create canon item definition `E Relic kind`; create item `E Relic`, submit/approve/publish, then award it to Hero through the session. Verify Hero inventory as the player.
8. Log `E Hero met Guide` publicly with separate GM notes. Create Quest with one stage/required manual objective, publish it, activate for Party and complete the objective explicitly.
9. Create a claim about Town, submit/approve/publish and reveal to Party/record Hero learning it. Confirm in the player's Knowledge view with Hero selected and no party filter.
10. Create dungeon `E Cellar`, two areas, a connection and one structural feature; publish eligible records and record searched state.
11. Create a General relationship between Hero/Guide; record Guide joining Council. Create a Town/Region route and perform valid session travel with a matching origin/destination.
12. Save a Guide portrayal profile. Prepare an encounter with Hero/Guide, start, record one valid turn, end with outcomes.
13. Write/attach a source to a record, open provenance, revise an editable field and compare its revisions; inspect Review queue.
14. Record a mistaken no-effect Other event, correct/void it with a reason and inspect retained original/replacement/correction history.
15. Archive/restore an unreferenced published location with a reason, checking the player cannot open it while archived.
16. End Session at 11:00 with recap; as GM inspect review/timeline/quest/character/knowledge, and as player inspect the permitted results without GM notes or controls.

**THEN**

1. The entire exit scenario works through supported portal actions from a clean deployment; no SQL, dev-content seed script, importer, Foundry or AI provider creates any scenario content.
2. Member onboarding, state changes, privacy, corrections, archive/restore, provenance and review work together; resulting definitions, timeline state, knowledge and history remain separate.
3. This case plus the human accessibility matrix and green **final-head** CI supplies acceptance evidence. A successful snapshot-copy run alone does not satisfy the clean-deployment gate.

## P02 browser checklist

This preserves the actionable B1–B22 specification, including prerequisite/action/expected
result and evidence rules, from the reconciliation record. Its former blanket “not
executed” status is superseded by per-check evidence in the ledger; P02 was owner-accepted
at `81bf164`, with B9/B16/B20 follow-ups and B21 deferred/unverified. This is not a fresh run.

### B1–B22 specification

Common evidence fields for every item (record in the ledger; no credentials, tokens or private names): date; stack commit SHA; browser name and version; operating system; viewport in CSS px and zoom; input method (keyboard, mouse, touch); assistive technology and version (or "none"); persona by role (for example "campaign GM", "player controller of a character", "viewer"); execution mode (scripted browser, human, owner); result (pass, fail, blocked); artifact path (screenshot or recording); notes. A failure criterion is a deviation from the expected result below; the contract text is UI_DESIGN §§4.8.1-4.8.4 and plan §9.1, and the expected results are not to be relaxed to fit what a browser happens to do. Where this record says "the contract names X", X is taken from those sections.

| ID | Prerequisites and starting state | Action | Expected result | Failure criteria and extra evidence |
|---|---|---|---|---|
| B1 Main control, other section (S1, S3) | Campaign GM; a selected campaign; clean page in a different section (for example Campaign Home); Navbar expanded. | Tab to **Parties** main control; Enter. | The control is a link to the section's default destination: route is the Parties list, task root `parties` (a one-item or no-ancestor trail), no question, selection unchanged; the destination heading takes focus once; no announcement. | Focus left on the control or `body`; a question on a clean page; selection changed. Evidence: URL before/after, focused element. |
| B2 Main control, already in section (S3) | A **split** control (Campaign, World or Characters; `SplitNavGroup`) with the page already at the control's destination, so the main control is the button form (`reason: at-destination`, `navbarDestinations.ts`). Parties, Quests, Sessions, Review and Ask are plain links (plan §2.3) with no menu and are not B2 controls. | Enter on the split control's **main control** (for example Characters on `/characters/all` with no selected perspective, or Campaign on Campaign Home). | No navigation, no question; the section's menu opens and focus moves to its first enabled menu item (keyboard). | Route change; no menu; focus not on the first item. |
| B2b Plain link, already on its page | Parties list open (also Quests, Sessions, Review, Ask). | Enter on the **Parties** link. | An ordinary link to the same address: the route is unchanged, no menu exists or opens, no question on a clean page. (The router restates a link to the current address as a replacement of the same entry, so no arrival and no heading focus is expected.) | A menu or disclosure appears; a question on a clean page. (Corrected 2026-11-06: B2 had been written for Parties, which is a plain link by the approved plan, so its menu expectation did not apply.) |
| B3 Menu open by pointer and keyboard (M1, PD-11) | Any group with children (Characters, Knowledge, Items, Access). | Open once by mouse click, once by Enter/Space on the disclosure. | Both: the menu opens and focus moves to the first enabled child; the opener is recorded. | Focus stays on the opener in either path. |
| B4 Escape (M2) | Menu open (once via the main control, once via the disclosure), drawer open at narrow width. | Escape. | Menu closes; focus returns to the opener it was opened from (main control or disclosure respectively); the drawer stays open. | Focus on `body`; drawer closes; wrong opener. |
| B5 Outside pointer and Tab out (M3) | Menu open. | Pointer-down outside; then reopen and Tab out of the menu. | Closes both times; focus is not moved by the close (pointer-down: wherever the browser puts it; Tab: to the next tab stop). | Menu stays open; focus forced elsewhere. |
| B6 Modified-link activation | Main control in link form (a selected destination exists, page differs); note the destination's route family (campaign, World or unscoped). | Ctrl/Cmd-click, Shift-click and middle-click. | The browser opens a new tab/window; the original tab runs no handler, asks no question, changes no selection, adds no history entry. The new tab has an **empty store and no usable stamp**, and follows §6.2 for the destination's family: campaign route, the route campaign with its perspective initialized from the authorized bootstrap default and default ancestors; World route, the confirmed world and timeline and no campaign; unscoped route, nothing selected. Breadcrumb nouns are generic; no error. | Original tab navigated, selection changed or a question shown; the new tab applying one rule to every family (for example nothing selected on a campaign route, or a campaign guessed on an unscoped one). Evidence: the new tab's Infobox and breadcrumb. |
| B7 Dirty Stay | A dirty form (for example Campaign settings name edited, unsaved); menu and drawer open for the Navbar path. | Activate a Navbar link, then separately a breadcrumb ancestor; in the question choose **Stay**. | The question opens (native modal); on Stay it closes; route, history entry, selection, task, draft and any picker draft are unchanged; menu and drawer remain open behind the question (M4); focus returns to the control that was activated (S2) or, for a menu child, to that child. | Draft lost; entry changed; focus on `body` or the drawer toggle while the opener exists (M6 allows the opener else the drawer toggle only if the opener is gone). Evidence: draft text, URL, history length, focused element. |
| B8 Dirty Leave and accepted departure | As B7. | Choose **Leave/Discard**. | One navigation to the destination; menu and drawer close; the destination heading takes focus once (accepted-departure focus); draft discarded; no write request in the network panel; announcement per the scenario (none for a plain Navbar link). | Second navigation; focus restored to the old opener over the destination heading; any POST/PUT. |
| B9 Native modal close | B7's question open. | Escape; then repeat and click the backdrop if the platform allows. | Treated as **Stay** (cancel): nothing changes and focus returns as in B7. After a **Leave** the destination heading, not the restored opener, keeps focus (P02-5 `ac00c1b`). | Close treated as Leave; focus overridden by the restored opener after a Leave. Record the P02-5 native-dialog inertness limit as observed or not. |
| B10 Immediate and deferred arrival | (a) Clean page; Infobox campaign select to a different campaign. (b) Same with the destination's data slowed (network throttling). | Choose the campaign. | (a) Commit, route to `/app/:new/home`, task root `campaign`, the page heading focused once, and the polite announcement `Campaign changed to ‹name›.` (plan §4.2 and UI_DESIGN §4.8.4; the portal says `Campaign changed.` when the name is not readable). (b) Focus waits for the heading to exist and then lands on it once; no earlier focus loss to `body`, no repeat. | Focus on `body`; heading focused twice; announcement missing, repeated or with a different text. Evidence: the announcement as spoken (B21) and its timing. |
| B11 Withdrawal after authority loss (L1/L2) | Two accounts or two tabs: a player with a selected campaign and perspective; a GM able to remove that access. Never use live data without authorization. | In tab 2 revoke; in tab 1 trigger a refresh or navigation. | Selection cleared with a polite notice; the old campaign's content is not rendered; "Campaign not found" for the route; a pending selection announcement is withdrawn; no focus move for a background clear. | Old content still shown; announcement for a state no longer true; selection restored later. |
| B12 Back/Forward (H2-H4, H7) | History with two entries of the same page under different perspectives, and one dirty case. | Back, then Forward, clean; repeat dirty. | Clean: the entry's own perspective and task, pages remounted, no "Loading portal". Dirty: the question; Stay keeps perspective, input and entry; Discard shows the entry's perspective. Symmetric on Forward. | Newer perspective shown for an older entry; question missing when dirty; crafted state accepted. |
| B13 Reload and supported restoration (H1, PD-5) | A reload empties the tab's store while the entry keeps its stamp. Starting states: (a) a record opened from a filtered World browser on a campaign route, under a campaign perspective chosen in the Infobox; (b) a campaign entry whose perspective is an **explicit none**; (c) a World route entry whose stamp holds a compatible campaign, and separately one whose stamp is World-only for the route's own World; (d) an unscoped entry (for example `/campaigns`) stamped with a selected campaign and perspective, and separately one stamped with an empty selection. | Reload each. | The first location restores from `history.state` (`task`, `ctx`) after **revalidation against the current authority**: the campaign must be listed, its world and timeline its own, the perspective authorized or an explicit `null`; a part that fails is dropped (I-4). (a) Same trail, filters and perspective; no repeated `Campaign changed to ‹name›.`; no error. (b) Still no perspective: an explicit none is restored as none, **not** replaced by the bootstrap default. (c) The stamp's campaign is restored, then kept only if it belongs to the route's confirmed world (and timeline if named), else cleared; a World-only stamp for the route's own World asks nothing more (the route's own World read confirms it). (d) **A valid stamped unscoped selection survives authorized restoration**: the campaign (and perspective) are expected back, shown as the selected campaign, and the entry stays stamped; the empty stamp leaves the selection empty. If the task is missing or fails validation the page shows the route's default trail; a missing or malformed `ctx` is **no stamp**, not an explicit none: a campaign route keeps the route campaign and initializes the default perspective, an unscoped route restores nothing. | Perspective defaulted over an explicit none; (d) always empty after reload; a stamp naming a campaign no longer listed still applied; a crafted value followed; announcement repeated; a missing `ctx` treated as none or as a loss. Evidence: Infobox before/after, breadcrumb, network panel (no extra reads beyond the route's own and, for a World-only stamp for a different World, one World read). |
| B14 New tab, duplicated tab and bfcache | As B13 (a)-(d), plus a signed-out and re-signed-in case in the same tab, and a World-only stamp whose World the session can no longer read. | Open the address in a new tab; duplicate the tab (whether the browser copies `history.state` is itself a result to record); navigate away to another site and return with Back; sign out and sign in as a different user in a tab holding an old entry, then Back; for the last case, on an **unscoped** page (W6a), Back/reload an entry stamped World-only for a World that is now refused; and separately on a **World** route for another World, Back/reload an entry stamped World-only for a different World, once with the route's own World readable (W6b-ok) and once with the route's World read refused or failing (W6b-fail). | **New tab** (empty store, no usable stamp): §6.2 by route family. **Duplicated tab**: if the state was copied, as a reload (usable stamp, empty store); if not, as a new tab. **bfcache restore**: the restored state or a re-validated one under the current authority; never content for a campaign the person can no longer open, and no stale announcement. **Entry surviving a sign-out and a different sign-in**: carries ids only and restores only what the new bootstrap authorizes; nothing of the previous user's selection remains. A perspective cleared by loss of authority is not resurrected by re-authorization. **World route for a different World, route read succeeds (W6b-ok)**: the route-confirmed World is the stable reconciled result and the World the route displays; a route commit that changes the selection supersedes the stamped attempt, while a no-op route commit leaves a still-owned attempt free to commit the stamped World into the retained store, after which the reconciliation restores the route World (retained-store state versus the displayed World are different things; record what the panel shows). **Same route, route read fails or is refused (W6b-fail)**: nothing is confirmed for the route; the separately authorized stamped World may remain as retained context if its own read succeeds, but the route does not present it as its confirmed World (the panel has no active World after a failed route read). **Refused World-only restoration (W6a)**: the attempt is dropped and a World-only selection of that World is cleared only if that attempt still owns the entry, revision, user and session; a newer selection made meanwhile is not cleared. This area is **unverified** (UI_DESIGN §4.8.2 limits 0-1). | Stale private content; an error page; a selection guessed on an unscoped route; the same fallback applied to every family; a previous user's selection restored; a newer selection cleared by an older, refused restoration; the retained stamped World shown by the route as its own confirmed World. |
| B15 Two-tab revocation | As B11, run in a real second tab with no refresh in tab 1 first. | Act in tab 1 after revocation in tab 2. | The server refuses reads; the page shows its non-disclosing unavailable state; nothing from the revoked scope is shown; selection is cleared when learned. | Private content rendered after a refused read. |
| B16 Breadcrumb at 320 px, 200% and 400% zoom | A record page deep in a task (World record from a filtered browser) with a long record name. | At 320 CSS px; at 200%; at 400%. | The breadcrumb wraps onto further lines; no horizontal page scroll; each crumb is visible, reachable and focus-visible; the current page is text. | Horizontal scroll; clipped or overlapped crumb; focus hidden. Evidence: screenshots at each setting. |
| B17 Narrow drawer and collapsed rail | Viewport narrower than the drawer breakpoint; separately the collapsed rail. | Open the drawer toggle, a disclosure, a child; close. Use rail icons. | Drawer opens/closes; disclosures and children reachable by keyboard; rail controls have names/titles; closing returns focus to the opener, else the drawer toggle, never `body` (M6). | Unreachable item; focus on `body`. |
| B18 Touch | A touch device or emulation. | Tap main controls, disclosures, drawer, breadcrumb links. | No hover dependency; targets large enough to hit; same results as the pointer. | Hover-only content; mis-taps. |
| B19 Reduced motion | OS reduced-motion on. | Use menus, drawer, dialogs and cards. | No non-essential animation or transition. | Any animated transition. |
| B20 Sticky header | A scrolled page. | Tab to a breadcrumb link and to the heading after navigation. | The focused element is not hidden under the sticky header (G01 not made worse). | Focus obscured. |
| B21 Screen reader (NVDA or platform reader) | NVDA version recorded; B1, B7-B10 and B16 states. | Navigate by landmarks, lists and links; trigger the selection change and the question. | Spoken: a "Breadcrumb" navigation landmark, the trail as a list with the current page announced as current; main control role and name ("Open campaign ‹name›" link, "Campaign menu" button) and expanded/collapsed state; the selection announcement once, not doubled; the question dialog's name and description; the destination heading on arrival. | Missing or doubled speech. **Evidence must be the reader's speech (speech viewer log or recording). DOM or live-region inspection is not screen-reader evidence.** |
| B22 Owner walkthrough | The owner's N01-N07 paths. | The owner's script. | Per the owner. | Owner-recorded. |

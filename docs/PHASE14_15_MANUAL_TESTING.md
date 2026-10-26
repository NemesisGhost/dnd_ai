# Phase 14 and 15 manual testing guide

Prepared 2026-10-10 from `phase15/completion` at `b957d98f9c34d7610a46fd1f478ce193a1c804f9`. Reviewed against local `main` / merge base `60d5bc90f73636beda83904cc89765b60e2a1ece` (Phase 15.1 is already on `main`). The branch adds migrations 114–136 and changes 614 files. This is a test specification, **not evidence that these tests passed**.

Phase 14 is recorded as complete; its navigation/hierarchy correction still needs manual verification. Phase 15.1's manual authoring checks and Phase 15's acceptance remain open. Record results in this guide and the existing [Phase 15 acceptance matrix](PHASE15_MANUAL_ACCEPTANCE.md). Do not change phase status solely because this guide exists.

## Basis and review findings that affect testing

- [Phase 14 verification](PHASE14_VERIFICATION.md), [Phase 15 verification](PHASE15_VERIFICATION.md), [Phase 14/15 scope and exit criteria](PLAN.md#phase-14-shared-authoring-kernel-and-campaign-setup), and [the existing acceptance matrix](PHASE15_MANUAL_ACCEPTANCE.md).
- The branch's commands, API/read models, portal routes and forms, scenario acceptance guards, and recent World, session and Knowledge changes. Recent commits require checks beyond the old matrix: World category counts and address-based browsing; preservation of browse state through related records; the collapsed `Parties (N)` disclosure; character-based Knowledge with an optional party filter; Knowledge details and Member preview.
- A read-only inspection of the configured **local** dev DB, `127.0.0.1:5432/dnd_ai`, at revision `136_world_viewer_role`, plus production `get_session_bootstrap` and `resolve_access_context` calls. No database data was changed during preparation.
- World ownership and campaign authoring are separate. Campaign-derived world cards lead to Campaign World; they do not authorize `/worlds/{id}`. An explicit `world_viewer` can read world management pages but cannot manage them ([ADR 0019](adr/0019-world-visibility-and-viewer-role.md)).
- Seed-script descriptions are not the current starting state: the DB has been used for manual work. Player B owns Campaign B; GM2 and Player A have revoked B memberships. Stowaway Pell and the customs-ledger claim are now published. The latter has already been revealed to The Ashen Vigil.
- Some expected limits are intentional: quest prerequisites are displayed but GM-controlled at runtime; finishing objectives does not automatically finish a quest; party memberships do not inherit into a branch; expertise and new item containers have no authoring form. Check correction previews rather than assuming every event type is reversible. NPC portrayal is GM-only and is not yet used by AI.
- Existing verification notes identify residual authorization-lock limitations on the legacy item-transfer and encounter-turn/end adapters. The permission tests below verify ordinary requests; a manual browser pass does not establish safety of an in-flight role-revocation race. Retain the automated concurrency and route guards as separate merge evidence.

## Environment and execution rules

Use the current dataset as the baseline, but perform this suite against an **isolated copy** of it. This follows the existing acceptance matrix's instruction to avoid the running development servers/database. Use a separate clean database for TC-56. Do not rerun either fixture script to prepare this suite: rerunning can reconcile memberships and overwrite the starting assumptions.

1. Restore a current backup into a separately named PostgreSQL 18 test database, following [Database recovery](operations/DATABASE_RECOVERY.md). Preserve the dev DB. Record the backup time, test DB name and migration revision. The UUIDs below apply only to this snapshot/copy.
2. Run the API from this branch on **8001**, with `DND_AI_DATABASE_URL` pointing explicitly at the test DB, `DND_AI_ENVIRONMENT=local`, and `DND_AI_LOCAL_SESSION_ALLOWED_ORIGINS=http://localhost:5174`. Start it with `uv run uvicorn dnd_ai.api.app:app --host 127.0.0.1 --port 8001`. Check that a higher-priority environment setting has not retained the dev DB URL.
3. Start the portal on **5174** from the `portal` directory. **Changing only the Vite port is insufficient:** the checked-in `portal/vite.config.ts` proxies both `/api` and `/auth` to port 8000. In a disposable checkout or temporary untracked Vite config, preserve the existing configuration and set both proxy targets to `http://127.0.0.1:8001`; then use `npm run dev -- --port 5174 --strictPort` (or `--config <temporary-config>`). Verify a login request reaches 8001 before proceeding. Do not commit this temporary configuration.
4. Use `http://localhost:5174` consistently. Open separate browser profiles/private windows for different accounts. Obtain the accounts' existing passwords from the owner; do not put passwords, invitation tokens, cookies, CSRF values or copied authenticated requests in this document or screenshots. `PHASE13E_DEV_ACCOUNT_PASSWORD` describes fixture creation, not a guarantee about the current passwords.
5. Record a unique run prefix, such as `M1415-20261010-A`. Replace **`R`** in every fixture name below with that exact prefix. `C` means the new test campaign ID created in TC-11, `W` its world ID, and `T` its primary timeline ID. Copy IDs from the address bar after creation into the run ledger. Routes beginning `/app/C` are on the isolated test server.
6. Run TC-01–10 before adding memberships or records. Then run TC-11–52 in order; dependent cases explicitly name their prerequisites. TC-53–55 and TC-57–58 use the resulting fixtures. TC-56 uses a clean database. For reruns, use another prefix or restore the test snapshot; do not assume an already completed session, learned claim or consumed item is fresh.
7. Keep DevTools Network open with Preserve log for mutation checks. An ordinary navigation GET is allowed; “no mutation” means no POST/PUT/PATCH/DELETE. Where requested, inspect response JSON as well as rendered text: hiding a leaked field with CSS is a failure.
8. If a GIVEN cannot be established, record **Blocked** with the missing prerequisite. Do not count an empty list, disabled action or unvisited page as a pass. Record expected intentional refusals as passes only after checking the explanatory message and unchanged data.

## Verified dev snapshot

### Accounts before test setup

| Login | What should be available after login and selecting the named campaign |
|---|---|
| `admin` | Platform Administrator; owner of both dev worlds and all four active campaigns. Campaign A has Character A and Character B perspectives; Campaign B has Archivist Sella Vane. World management and campaign authoring are available. |
| `phase13e.gm2` | Phase13E Dev GM2; Campaign A only, roles `campaign_owner` and `gm`, `canon.edit` and `access.manage`; no selectable characters and no explicit world membership. May create a new world because of the built-in GM role, but cannot manage the existing dev world. |
| `phase13e.player_a` | Campaign A only, `player`, Character A only; no `canon.edit`/`access.manage`; campaign-derived view-only dev world. |
| `phase13e.player_b` | Campaign A as `player`, Character B only. Campaign B as `campaign_owner` + `player`, with `canon.edit`/`access.manage` and no character perspective. This account is **not** a plain-player denial subject in B. |
| `phase13e.observer_a` | Campaign A only, `observer`, `campaign.view`, no character perspective and no authoring/preview management. |
| `phase13e.disabled` | Platform-inactive despite an active A membership. Login must be refused. |

Login can resume a saved campaign. Select the campaign explicitly; do not assume the landing page is Campaign A.

### Stable entry points and records

| Alias | Name / ID or initial state |
|---|---|
| Dev world | Phase13C Dev World — `d80d5c79-fab6-41eb-ae01-dbc69a41b192` |
| Dev A | Phase13C Campaign A — `f5c622cc-14b5-4875-8b3b-785dcd610c2a`, Timeline A `e96a79e8-8227-4dd4-a5cb-69dadcdd39b1` |
| Dev B | Phase13C Campaign B — `26d34154-8147-4e74-a44b-3b0a020d81b3`, Timeline B `4d7ff15a-b3f7-4c38-9a5a-9332c79ab085` |
| Other world | Test world — `dde7fcc0-2eb0-4a0a-b53d-8390375b34b4`; owned by admin, inaccessible to the other accounts |
| Character A / B | `85e2c58a-a945-4a88-9d0b-abbf122e5275` / `cdf89ae4-74ba-4de2-8d8c-c2f9ccecd906`; published, active |
| The Lantern-Bearers | `07c807f7-407b-4cb3-9e4a-f31563e082b1`; both characters are current members on Timeline A |
| The Ashen Vigil | `160adb4a-ce60-4478-ac1c-d737f9c8ac7e`; no current members in this snapshot; knows the customs-ledger claim on A |
| Location hierarchy | Auremar → The Ashen Vale → Hollowmere → The Sunken Archive (`715467cf-9d96-4545-9d94-f09fe134fc6d`) |
| Drafts | `[P15 dev] Harbor District`, `[P15 dev] Dockhands Guild`, `[P15 dev] Whispers on the Quay` |
| Archived / superseded | `[P15 dev] Sunken Reef` archived; `[P15 dev] Old Keep` superseded by `[P15 dev] New Keep` |
| Played sessions | A: The Sealed Descent and The Warden's Bargain completed; **Testing Session 3** (`649988b9-8eb1-4f29-9bf3-cf6858436a48`) in progress. B: Smoke Over Hollowmere completed. Session lifecycle `active` does not mean in progress. |
| Clock/calendar | Testing Calendar; A clock label `Testing what this does`, sort key `175240080`, row version 2. B has its own earlier clock. Create new times in the test world; do not advance A's existing clock. |
| Knowledge | A public: “Hollowmere is built directly over the drowned ruins of the older city of Aurell.” B public: “The Saltreach beacon-keeper was bribed to let the signal fire go out.” A alone: Sella Vane's private ledger. B character alone: Warden blood / lantern claim. Lantern-Bearers: lower-vault floods, drowned king, sluice-gates, sealed sub-basement and slack-tide claims. Canon-only: Wardens answering to the thing in the vault. |
| Existing items/dungeon | The Warden's Lantern, The Drowned Crown; The Tidebound Crypt and The Lantern Antechamber. Browse these; use new fixtures for state changes. |
| Fixtures still needed | No world-owned item definitions, NPC portrayal profiles, routes, scheduled session or timeline branch exist. Two encounters, seven entity revisions and an attached `Testing source` exist, but their states/history do not provide fresh fixtures for the operations below. |

## Test cases

### TC-01 — Administrator baseline and login return

- [x] Test case executed and result recorded.

**GIVEN**

1. Log in as `admin`. You should see an authenticated workspace and be able to select all four active campaigns listed in the snapshot.
2. Select Dev A; open Campaign Home. The context should identify the dev world, Timeline A and Campaign A; Character A and B should be offered.

**WHEN**

1. Open All worlds; verify Phase13C Dev World and Test world, then open the dev world overview.
2. Open a second signed-out/private window at `/worlds/new`; sign in there as `admin`.
3. Return to the first window, sign out, and visit `/app/f5c622cc-14b5-4875-8b3b-785dcd610c2a/home`; sign in again.

**THEN**

1. Both world overviews offer authorized management controls; the admin account is identified correctly.
2. Login returns to the requested New world or campaign destination, without a crash, blank outlet or duplicate form.
3. Merely opening a creation page makes no creation request and creates no record.

### TC-02 — Live account permissions and campaign lists

- [x] Test case executed and result recorded.

**GIVEN**

1. Log in as `phase13e.gm2`. You should see Dev A only, authoring links and no selectable character perspective.
2. Have separate signed-out profiles ready for the other four fixture accounts.

**WHEN**

1. Open the campaign selector and Dev A Home, World and Knowledge as GM2.
2. Sign in as `phase13e.player_a`; select Dev A and inspect the campaign/character selectors and sidebar.
3. Repeat as `phase13e.player_b`, first in A, then switch to B.
4. Repeat as `phase13e.observer_a` in A. Finally attempt login as `phase13e.disabled`.

**THEN**

1. Campaigns, perspectives and controls match the account table exactly; revoked memberships are absent.
2. Player B has GM controls in B but only player controls in A. Switching campaigns removes the previous campaign's controls and perspective.
3. The observer has no character selector choices or GM controls. The inactive account receives a safe login refusal and no authenticated workspace.

### TC-03 — Phase 14 hierarchy and stable Worlds navigation

- [x] Test case executed and result recorded.

**GIVEN**

1. Log in as `admin`. You should see the dev world and both A/B campaigns; in Dev A, select Character A.
2. Open `/worlds/d80d5c79-fab6-41eb-ae01-dbc69a41b192/timelines`.

**WHEN**

1. Expand Worlds and visit All worlds, World overview, Timelines, Timeline A overview and Campaign world in turn.
2. Return to Dev A; use the hierarchy selectors to navigate to Test world, then return to the dev world and select Timeline B / Dev B.
3. Use browser Back and Forward across those selections. Reload the Timelines collection and a timeline deep link.
4. On a world-only route, inspect the Campaign and Character levels; on Dev B, inspect available character perspectives.

**THEN**

1. One stable Worlds group remains; context-dependent entries are disabled in place. Timelines means the world's collection, not just one campaign timeline.
2. World, Timeline, Campaign and Character context agrees with the route at every step; lower-level selections/data from the previous route disappear.
3. World-only routes offer no campaign-derived character perspective. B offers Sella Vane rather than A's characters. No stale A data appears during B loading.
4. Deep reloads work, with one coherent main workspace and context panel.

### TC-04 — Campaign-derived world visibility and creation eligibility

- [x] Test case executed and result recorded.

**GIVEN**

1. Log in as `phase13e.player_a`. You should see Dev A, Character A and the dev world through the campaign, with no world-management authority.

**WHEN**

1. Open All worlds and the World selector; follow Phase13C Dev World from each.
2. Type `/worlds/d80d5c79-fab6-41eb-ae01-dbc69a41b192`, its `/edit` and `/timelines` addresses, then `/worlds/new`.
3. Sign in separately as `phase13e.gm2`; open All worlds, follow the dev world, and then open New world without submitting.

**THEN**

1. Player A's one dev-world entry is view-only and opens Dev A's Campaign World. It is not duplicated between the list and selector.
2. Direct world-management routes refuse access without revealing management data; New world offers no usable create form to Player A.
3. GM2 also cannot manage the existing dev world, despite campaign editing rights, but does receive the New world form through the built-in GM role. No test world is created here.

### TC-05 — World categories, authorized counts and browse-state persistence

- [x] Test case executed and result recorded.

**GIVEN**

1. Log in as `admin`. You should see Dev A's World browser, its category navigation and the editor's hidden/draft preview control.
2. Open `/app/f5c622cc-14b5-4875-8b3b-785dcd610c2a/world`; clear search and start on All entries.

**WHEN**

1. Select each category, compare its displayed count with the matching list (walk all pages where necessary), and return to All entries.
2. Search `hollowmere`, wait for results, then change category; record the address and counts. Search a unique nonsense string and use Clear search.
3. Enable hidden preview; find Harbor District and Sunken Reef. Open a record, follow a related record/breadcrumb, and use Back to World.
4. On unfiltered All entries, open the next page, open a record and a related record, return to World, choose Previous page, and exercise browser Back/Forward and reload.
5. In Player A's profile, repeat the category/count/search checks and manually append `?hidden=1`.

**THEN**

1. Counts reflect the same authorized search/preview inputs as the lists, across all pages; they do not count inaccessible drafts, archived records or foreign-timeline events for a player.
2. Category, `q`, `hidden` and page cursor trail survive supported links and reloads; search/category changes reset pagination. Previous returns to the prior page without duplicate/omitted entries.
3. Empty states identify the category/search and Clear search works. Related-record navigation preserves the originating browse context.
4. Player A sees no hidden-preview control; adding the query parameter grants nothing. Record count differences rather than assuming fixed counts after fixtures are added.

### TC-06 — Collapsed party disclosure in the context panel

- [x] Test case executed and result recorded.

**GIVEN**

1. Log in as `phase13e.player_a`. You should see Dev A with Character A selected and a collapsed `Parties (1)` disclosure in the context panel.

**WHEN**

1. Expand Parties with Enter/Space; inspect The Lantern-Bearers and collapse it.
2. Navigate between Home, World and Knowledge, then clear the character perspective.
3. Repeat as `admin` with Character A, expand the party list and follow its party link.

**THEN**

1. The party list starts collapsed, has an accessible count/name and shows the selected character's current parties.
2. Player A sees party text without a GM membership-page link. Admin's link opens the correct party page.
3. Clearing the perspective removes that character's disclosure; it does not leave the previous character's party list behind.

### TC-07 — Player Knowledge is character knowledge plus eligible parties

- [x] Test case executed and result recorded.

**GIVEN**

1. Log in as `phase13e.player_a`. You should see Dev A, Character A, the plain Knowledge sidebar link and no GM stages or Member preview link.
2. Open Knowledge, choose Known, leave the party filter unselected and include public knowledge.

**WHEN**

1. Search for and open Sella Vane's private-ledger claim; inspect the Knowledge details.
2. Clear search and find a settled Lantern-Bearers claim, such as the lower-vault flood claim; also check Rumors for rumor-typed party claims.
3. Select The Lantern-Bearers filter; repeat the private-ledger and party-claim checks. Open a claim and return using its breadcrumb.
4. Search the Warden blood / lantern claim and the canon-only Wardens/vault secret.
5. Repeat as Player B in A, selecting Character B and checking the Warden blood claim and Sella's ledger.
6. Compare the sluice-gates claim's player interpretation against admin's canonical claim. Search a phrase unique to canonical wording as the player.

**THEN**

1. A character needs no explicit party filter to see their own belief plus knowledge of eligible parties. Selecting a party does not hide the character's own knowledge.
2. Each visible claim appears once; collection and detail agree on the projected statement. The details identify the actual selected-character knowledge without inventing omitted awareness/confidence/sharing values.
3. A does not acquire B's individual lantern belief; B does not acquire A's private ledger. Neither gets the canon-only secret or canonical truth/sensitivity fields in response JSON.
4. A canonical-only search phrase cannot reveal a claim whose visible interpretation differs. Perspective survives claim/breadcrumb navigation.

### TC-08 — Public Knowledge, no character and timeline separation

- [x] Test case executed and result recorded.

**GIVEN**

1. Log in as `phase13e.observer_a`. You should see Dev A and Knowledge with no selectable character and no claim-management controls.

**WHEN**

1. Open Known with public knowledge included; then select Public only and search `Hollowmere`.
2. Disable public inclusion in a view that supports the checkbox; inspect the empty audience result.
3. Open the public Hollowmere claim, inspect Character knowledge, and type `?section=who-knows` on its address.
4. As admin in B, open Public only and search `beacon-keeper`; as the observer in A, search the same phrase.

**THEN**

1. A's public Hollowmere lore is visible without a character; private and party knowledge is absent. Excluding public does not manufacture an audience.
2. Claim values are text; no stages, status-management badge, Save/Discard or Who knows controls appear. Character knowledge asks for a perspective; `section` cannot enable editing.
3. B's beacon lore does not leak into A despite both campaigns sharing a world.

### TC-09 — Knowledge Member preview compared with the member's own view

- [x] Test case executed and result recorded.

**GIVEN**

1. Log in as `phase13e.gm2`. You should see Dev A with Knowledge → Claims and Member preview, and no personal character perspective.
2. Keep Player A's own Knowledge profile open for comparison.

**WHEN**

1. Open Member preview before choosing anyone; inspect Network. Choose Phase13E Dev Player A, then Character A, without a party filter.
2. Compare Known, Rumors, Character private, Public only, search and claim details with Player A's own requests/pages using the same filters.
3. Select The Lantern-Bearers, open a claim, use Back, reload, and change the preview member to the observer.
4. Edit the URL to use an unknown member UUID, then Player A with Character B, then a party without a usable character.
5. Use Return to Knowledge. As Player A, type `/app/f5c622cc-14b5-4875-8b3b-785dcd610c2a/knowledge/member-preview`.

**THEN**

1. Before selection there is only the member-choice state and no Knowledge request. The banner names the subject member/roles and explains read-only preview.
2. Only the subject's own perspectives are offered. Preview results match that member's own projection, never GM2's authority or ground truth.
3. The preview claim has the proper breadcrumb/banner, text-only data, no subject link or management controls, and correctly labels party versus character knowledge. Back/reload preserve filters and perspective.
4. Changing member clears old claims immediately. Invalid combinations show a safe error without a Knowledge request. Returning to normal Knowledge clears preview context.
5. Player A is refused at the preview address and makes no preview/member-list request.

### TC-10 — Existing draft, archive, supersession and scope boundaries

- [x] Test case executed and result recorded.

**GIVEN**

1. Log in as `admin`. You should see Dev A World with hidden preview available and the existing `[P15 dev]` lifecycle examples.
2. Keep Player A's A profile open and copy the actual URLs of Harbor District, Sunken Reef, Old Keep, a B-only event and a B-only session.

**WHEN**

1. Open each lifecycle example as admin; follow Old Keep's replacement link.
2. Open the draft/archived URLs as Player A and compare their responses with the same route using UUID `00000000-0000-4000-8000-000000000001`.
3. Under Dev A, substitute B's session/event IDs in A's session/event addresses; repeat as admin.
4. As Player A, type Dev B Home directly and compare with a nonexistent campaign ID.

**THEN**

1. Admin sees the true statuses and replacement. Player draft/archived failures are non-disclosing and match missing-resource behavior.
2. Same-world B timeline records are not readable through A, even by admin. Player A cannot enter B.
3. No hidden title, summary, GM notes or cached record flashes before a refusal.

> **Post-run note (CP-7 / DR-1, not part of the recorded result).** THEN 1's wording "Player draft/archived failures are non-disclosing and match missing-resource behavior" predates decision DR-1. The documented policy ([ENTITY_LIFECYCLE.md §3.3](ENTITY_LIFECYCLE.md)) is: a **draft** (and proposed/approved/rejected) definition is the same 404 as a missing record for a player, while an **archived, superseded or deprecated published** definition stays readable by reference wherever it is already visible to that player. Expect the first for drafts and the second for archived published history. This note changes no recorded result; re-performance under the corrected expectation is a CP-11 acceptance item.

### TC-11 — Create an isolated world, timeline and campaign through the portal

- [x] Test case executed and result recorded.

**GIVEN**

1. Log in as `admin`. You should see All worlds, New world and New campaign; no fixture with this run's prefix exists.

**WHEN**

1. Open New world; enter name `R World`, description `Manual Phase 14/15 run`, select the offered D&D 5e ruleset as allowed/default, and enter Primary timeline name `R Primary`. Save and record `W`, the server-generated slug and the primary timeline ID `T`. World creation creates that primary timeline atomically; there is no slug-entry field.
2. Open its Timelines collection and confirm Primary is present; use New timeline to create a separate `R Alternate`, with description `Independent test timeline`, and reload both overview pages.
3. Open New campaign. Select `R World`, continue, select `R Primary`, continue, enter `R Campaign`, description `Manual acceptance`, and choose the offered D&D 5e ruleset version. Submit once and record `C`.
4. Reload Home, Settings, the world overview and timeline overview. Edit the world's description, timeline description and campaign description, saving each.

**THEN**

1. The new world/timeline/campaign are visible and coherent; admin receives the intended world-owner/campaign-owner authority.
2. Home is empty but usable with next actions. Settings shows the pinned ruleset and current timeline.
3. Edits persist after reload. Creation and save receipts contain identifiers/versions rather than full authored narrative.

### TC-12 — Setup cancellation and recovery

- [x] Test case executed and result recorded.

**GIVEN**

1. Log in as `admin`. You should see `R World` and `R Primary` as eligible setup choices, and the existing `R Campaign` in the campaign list.

**WHEN**

1. Start another New campaign, select the world and timeline, enter `R Cancelled campaign`, then cancel before submitting.
2. Reopen setup, go backwards from the final step, change the selected world and inspect the timeline choices; return to `R World`.
3. Reload the setup address at an intermediate step and follow the offered recovery/selection controls.

**THEN**

1. No cancelled campaign is created. Existing explicitly created worlds/timelines remain reachable.
2. Timeline/ruleset options correspond to the chosen world; stale lower-level choices are cleared or rejected.
3. Recovery is understandable, with no invisible partial campaign or untracked repeated creation.

### TC-13 — Enrol test members and establish separate campaign roles

- [x] Test case executed and result recorded.

**GIVEN**

1. Log in as `admin`. You should see `R Campaign` Home and its Access/Invitations controls; initially admin is its only member.

**WHEN**

1. Open Invitations for `R Campaign`, issue one invitation with an optional label for GM2, and privately copy the generated link/token.
2. In GM2's profile, open that link, sign in as `phase13e.gm2` if prompted and confirm joining. Return as admin to Access, refresh, and assign the built-in GM role to that new membership.
3. Issue and accept separate invitations for `phase13e.player_a`, `phase13e.player_b` and `phase13e.observer_a`; as admin assign Player, Player and Observer respectively.
4. Refresh each member's campaign list and open `R Campaign`. Record membership IDs from the Access response for later permission tests.

**THEN**

1. Invitation acceptance alone does not grant roles or character relationships; access appears after the explicit role assignment.
2. GM2 has campaign authoring; players/observer have read access and no authoring. Nobody has a new character perspective yet.
3. Original dev-campaign memberships/roles remain as in the snapshot. Do not publish invitation material in the run ledger.

### TC-14 — Calendar dates and narrative world-time points

- [x] Test case executed and result recorded.

**GIVEN**

1. Log in as `admin`. You should see `R World` overview with New calendar and `R Campaign` Game master tools with World times; there are no test-world time points yet.

**WHEN**

1. Create calendar `R Reckoning`, epoch `Founding`, seven days per week, months Firstfall and Lastfall with 30 days each.
2. In `/app/C/world-times`, record year 1, Firstfall day 1, 09:00, label `R T0`; then 10:00 `R T1`, 11:00 `R T2`, 12:00 `R T3` and 13:00 `R T4`. Record their IDs.
3. Record narrative moment `R Between`, after T1 and before T2.
4. Attempt an invalid day 31, hour 24, and a narrative placement whose Before is earlier than After; correct the inputs and cancel without saving the corrections.
5. Reload World times. As GM2, open the campaign time form; also type the world's calendar-creation route.

**THEN**

1. Date/time displays include calendar, date, time and label, in the correct order; Between lies strictly between T1/T2.
2. Invalid inputs are explained at the field/form and make no invalid row. Existing used calendars are not offered as freely editable definitions.
3. GM2 can record campaign times but cannot create a calendar on admin's world without world-management authority.

### TC-15 — Advance and correct the campaign clock

- [x] Test case executed and result recorded.

**GIVEN**

1. Log in as `phase13e.gm2`. You should see `R Campaign` Home with an unset clock and editor clock controls; TC-14's T0–T4 are selectable.

**WHEN**

1. Advance to T0; reload Home, then advance to T1.
2. Attempt to advance to T0 or the same time T1.
3. Choose Correct to T0, open the confirmation and cancel; reopen and confirm with a change reason. Finally advance to T1 again.
4. As Player A, open the same Home and inspect the clock and its response.

**THEN**

1. First and later advances persist and create causal events; non-later advances are refused without changing the clock.
2. Cancel is read-only; confirmed correction changes the clock and identifies its causal history. The final clock is T1.
3. All members can read the time; Player A has no Advance/Correct controls. Real-world timestamps are not presented as fictional time.

### TC-16 — Location types, parent hierarchy and safe reparenting

- [x] Test case executed and result recorded.

**GIVEN**

1. Log in as `phase13e.gm2`. You should see `R Campaign` World with New location and no existing test locations.

**WHEN**

1. Create region `R Vale`; submit for review, approve and publish it from its Lifecycle panel.
2. Create settlement `R Haven` with parent Vale; submit, approve and publish. Create building `R Archive` with parent Haven and publish the same way.
3. Edit Archive's summary to `Public archive`; save, reload and inspect its hierarchy links.
4. For every remaining non-dungeon category offered by New location, create `R <category>`, fill its required fields using offered options, select a valid published parent where applicable, save as draft, edit its summary and reload. Record each category and URL separately.
5. In a draft hierarchy, attempt to make a location its own parent or reparent an ancestor beneath its descendant; also try archiving Haven while Archive still depends on it.

**THEN**

1. All ten supported non-dungeon location categories have a usable create/edit route and correct subtype fields. Archive's breadcrumb/hierarchy is Vale → Haven → Archive.
2. Reference choices are authorized records; invalid hierarchy actions are excluded or refused with a reason, with the hierarchy unchanged.
3. Creating/editing a definition does not move characters or silently create timeline state. Players see only published active locations.

### TC-17 — Organizations, subtype fields and religion references

- [x] Test case executed and result recorded.

**GIVEN**

1. Log in as `phase13e.gm2`. You should see `R Campaign` World with New organization/New religion and published Haven available as headquarters.

**WHEN**

1. Create `R Council` as Government, headquarters Haven, summary `Public council`; submit, approve and publish it.
2. Create `R Guild` beneath Council, using Organization/guild fields offered by the form; keep it draft, edit its summary and reload.
3. Repeat create/edit for each other offered organization kind, recording all six kinds and entering each required subtype field with a concrete value from its catalog.
4. Create religion `R Faith`; save and publish it. Create a Religious organization `R Chapter` referencing Faith; save and publish.
5. Attempt a self/cyclic organization parent and inspect the refusal or absence from the picker. As Player A, open Council, Faith and the draft Guild.

**THEN**

1. Subtype fields and parent/headquarters/religion references persist correctly; none crosses worlds.
2. Cycles cannot be saved. Player A sees published organization/religion information and cannot read the draft.
3. Definition edits do not silently change membership or operational timeline status.

### TC-18 — NPC/PC identity, publishing and character relationships

- [x] Test case executed and result recorded.

**GIVEN**

1. Log in as `admin`. You should see `R Campaign` Characters with New character and Access controls; players currently have no perspective there.

**WHEN**

1. Create NPC `R Archivist`, Human/Medium, origin Haven, with public appearance `Blue coat` and GM background marker `R GM-NPC-ONLY`; save, submit, approve and publish.
2. Create PCs `R Hero A` and `R Hero B`, Human/Medium, origin Haven; save, submit, approve and publish each. Record all three IDs.
3. Open Hero A's Link a player action; in Access grant Player A an Owner relationship to Hero A. Repeat for Player B / Hero B.
4. Edit Archivist's public appearance and save; open Hero A's edit page without changing its player ownership through an identity field.
5. Refresh both players' bootstraps/character selectors and open Archivist. Attempt to archive Hero A while its user relationship remains active.

**THEN**

1. Typed NPC and PC creation/editing works and persists; relationships, not `player_user_id`, establish character access.
2. Player A can select only Hero A; Player B only Hero B. Draft/unpublished PCs would grant no perspective.
3. Player responses contain no GM background marker. Archiving the actively linked PC is refused with a useful reason.

### TC-19 — Immutable builds, starting state and activation

- [x] Test case executed and result recorded.

**GIVEN**

1. Log in as `phase13e.gm2`. You should see Hero A's Builds and starting state page with no initialized state or build; TC-18's characters are published.

**WHEN**

1. Set Hero A maximum/current HP to 20/20; submit. Create build `R Fighter 1`, ability scores all 10, Fighter level 1, using only offered class/subclass/options; save and activate, cancelling once before confirming.
2. Create `R Fighter 2`, all ability scores 12, Fighter level 2; save without activating, inspect the active build, then activate it with confirmation.
3. Reopen build 1 and inspect whether it has an edit-in-place control. Attempt a second starting-state initialization if offered.
4. Initialize Hero B and Archivist to 20/20 HP on their own starting-state pages; create and activate one valid offered build for each.
5. Create another Hero A build containing an offered spellcasting class and its offered known/prepared spells; inspect required selections and cancel without saving if incomplete.

**THEN**

1. Starting state initializes once. Saving a build does not activate it; cancellation does not change the active build.
2. Activating build 2 preserves build 1, changes timeline state and records an activation event; earlier build snapshots remain immutable.
3. Rules options come from the campaign's pinned version; subclass/spell selections belong to valid offered choices. Expertise is not incorrectly claimed as a supported form feature.

### TC-20 — Party create/edit and archive/restore

- [x] Test case executed and result recorded.

**GIVEN**

1. Log in as `phase13e.gm2`. You should see `/app/C/parties` with a create control and no test parties yet.

**WHEN**

1. Create `R Party`, description `Manual party`, and `R Reserve`, description `Reserve audience`.
2. Edit Reserve's description, save and reload. Open its Archive confirmation, cancel, then archive with reason `Manual archive check`.
3. Turn on Show archived; open Reserve and restore with reason `Manual restore check`.
4. As Player A, inspect the campaign party list and type Reserve's edit/member-management addresses.

**THEN**

1. Creation attaches each party to this campaign; edits persist. Cancel changes nothing.
2. Archived Reserve is hidden from ordinary pickers; Show archived/Restore are editor controls and restore returns it to active use.
3. A member may read the allowed party list; a player cannot edit or inspect the GM membership-management page.

### TC-21 — Temporal party membership, overlap and selected-character parties

- [x] Test case executed and result recorded.

**GIVEN**

1. Log in as `phase13e.gm2`. You should see `R Party` with empty Current members and History and an Add member form; Hero A/B are published and T0–T4 exist.

**WHEN**

1. Add Hero A and Hero B to Party at T0, reasons `Joined for test`.
2. Attempt another overlapping Hero A membership at T1. Open Hero B's End membership dialog and try end T0; then cancel and end at T1 with reason `Left for test`.
3. Inspect history and each join/leave event. Add Hero B again at T2; finally add Archivist to Reserve at T0.
4. As Player A select Hero A; inspect the context's Parties disclosure. As Player B inspect Hero B's current party perspective at the effective time.

**THEN**

1. Join/leave events and temporal membership rows agree. Overlap and a non-later end are refused; cancellation preserves membership.
2. Ended membership remains in history; adjacent/non-overlapping rejoining succeeds.
3. The context and Knowledge party choices reflect authorized current memberships. Membership does not grant another user's character authority.

### TC-22 — Schedule/edit sessions and participant preparation

- [x] Test case executed and result recorded.

**GIVEN**

1. Log in as `phase13e.gm2`. You should see `R Campaign` Sessions with Schedule a session and no session currently in progress.

**WHEN**

1. Schedule `R Play`, Planned start `2026-10-11 19:00` in the browser's local zone, summary `Public plan`; schedule `R Next` with a later planned start.
2. Open Play's session page, edit title/summary/planned start in place, save and reload. Follow its legacy `/edit` address.
3. Choose Run Play; in Prepare → Participants, add Hero A as Player character, Archivist as NPC and Hero B as Guest.
4. Try duplicate Hero A and a role/kind mismatch; remove Hero B, inspect Left, then re-add it as Player character.

**THEN**

1. Numbers are assigned by the server and remain distinct; Planned start is a real-world time, separate from world time.
2. Edit/reload/legacy redirect work. Scheduled session preparation does not start the session.
3. Eligible participants and roles are validated; removed participation stays in history. No invalid/duplicate open participant is created.

> **Post-run note (CP-8 / DR-3, not part of the recorded result).** Members without `canon.edit` now see a member-safe **Participants** roster on session detail: every stint (present or left, including a rejoin, with its times) of the participants they may discover, no management controls, no placeholder or hidden count, and a name is a link only where the character page would open for them. Re-performing the member view of this case (a player with a related PC and a discoverable NPC, an undiscovered NPC absent, an observer) is **outstanding** and part of CP-11 acceptance; it has been verified by automated tests only.

### TC-23 — Staged Run Session navigation and unsaved inputs

- [x] Test case executed and result recorded.

**GIVEN**

1. Log in as `phase13e.gm2`. You should see Run Play on Prepare → Participants, a scheduled badge and the world/timeline/campaign context from TC-22.

**WHEN**

1. Click Prepare, Run session and Wrap up; inspect the section menu and each available section without starting the session.
2. Enter a draft Session log entry/GM notes, select Travel choices, an Award recipient when offered, a participant choice and a partly entered Advance time. Switch sections/stages and return.
3. Use Back/Forward; reload `?section=travel`; load `?section=bogus`; inspect the breadcrumb links.
4. Inspect Network for mutation requests caused just by stage/section navigation.

**THEN**

1. Exactly one section is visible, with its heading/purpose/border; the menu contains only that stage's sections. Stage navigation does not start/end/mutate a session.
2. Entered inputs survive supported section changes and browser navigation; a page reload is not required to preserve unsaved memory, but does select the requested valid section.
3. Invalid sections resolve to the default without an extra Back entry. Breadcrumb is Sessions → Play → Run session; title/list links work and context remains coherent.

### TC-24 — Start session, world-time bar and public/private log

- [x] Test case executed and result recorded.

**GIVEN**

1. Log in as `phase13e.gm2`. You should see scheduled Play with prepared participants and the T1 campaign clock; Start session is available only in its Run session stage.

**WHEN**

1. Enter Run session and click Start session. Reload the session list and follow Run Play again.
2. In Session log record public entry `R Met the archivist`, GM notes `R GM-LOG-ONLY`, at T1. Record a second entry with the Record a new time option at Firstfall day 1 10:15, label `R Log time`.
3. Open each event from the log and inspect the public text/GM notes; view the same session as Player A.
4. On Run Next attempt to start while Play is in progress. On Play inspect the clock bar in every stage, then advance it to T2 in Run session.

**THEN**

1. Play starts only through the explicit button and Run Play now defaults to Session log. The second session cannot also start.
2. Log entries/time selections persist and event links are correct. Audience hints accurately separate public entry text from canon-editor-only notes.
3. Player JSON/rendering contains no GM marker; the player receives no run controls. The clock is shown in every stage, with Advance/Correct controls only in Run session.

### TC-25 — Manual event record, void and correction

- [x] Test case executed and result recorded.

**GIVEN**

1. Log in as `phase13e.gm2`. You should see Game master tools → Record event and an in-progress Play session; T2 is an available time.

**WHEN**

1. Record event type Other, name `R Mistaken meeting`, GM details `R GM-EVENT-ONLY`, time T2; open its event page.
2. Inspect correction preview, choose Void, enter reason `Entered twice`, cancel once, then confirm.
3. Record another no-effect Other event `R Wrong title` at T2; choose Correct, enter the replacement information/time requested by the dialog and reason `Wrong title`, and confirm.
4. Reload originals and replacement, inspect links/history, then try another correction of an already voided/corrected original. Inspect a clock event's preview.

**THEN**

1. Cancellation preserves the original; confirmation leaves the original with a void/correction record and links, rather than deleting history.
2. Repeated/nested correction is refused; unsupported-effect previews explain why automatic reversal is unavailable.
3. Events/provenance keep the real actor and reason subject to the GM privacy contract; Player A cannot read GM details through session/World views.

### TC-26 — Quest definition: stages, objectives, completion metadata and cycles

- [x] Test case executed and result recorded.

**GIVEN**

1. Log in as `phase13e.gm2`. You should see New quest and published Hero A, Archivist and Council as available references; no `R Quest` exists.

**WHEN**

1. Create `R Quest`, summary `Find the missing record`, GM notes `R GM-QUEST-ONLY`.
2. Add stage `R Investigate`; add required manual objective `R Meet archivist`, target Archivist, player-visible policy. Add stage `R Recover`; add required manual objective `R Retrieve record`, target Archive, and optional GM-only objective `R Secret patron`.
3. Edit an objective's description, move stages/objectives with the reorder controls and then restore the intended Investigate → Recover order.
4. Add Meet archivist as a prerequisite of Retrieve record; attempt the opposite edge and inspect the cycle error.
5. Add Archivist as a participant using an offered role; add an outcome code `success`, name `Record recovered`, an offered outcome category, and Reward kind Other / Reward `A council favor`. Edit the outcome and remove/re-add that reward.
6. Submit, approve and publish the quest. Open it as Player A.

**THEN**

1. Stage/objective order and supported metadata persist; cycle rejection does not change the valid dependency.
2. References are published/authorized. Publishing fails with an actionable explanation if required completeness is missing.
3. Player response omits the GM notes marker and GM-only objective. Definition authoring has not activated the quest or awarded a reward.

### TC-27 — Quest runtime scopes, explicit completion and correction

- [x] Test case executed and result recorded.

**GIVEN**

1. Log in as `phase13e.gm2`. You should see the published Quest editor with Run quest/Progress and an untracked state for the intended audience; Party is active.

**WHEN**

1. Open Progress, choose Party scope and activate Quest at T2; activate then complete Meet archivist and Retrieve record using their status controls.
2. Inspect the completion hint before explicitly completing the quest. Suspend/resume while active and inspect objective controls during suspension.
3. Complete the quest using its confirmation. Open the resulting completion event, inspect the correction preview and void that latest completion with reason `Reopen for test`.
4. Activate the global scope separately and compare it with Party; attempt adding/reordering structural objectives after runtime progress exists.
5. As Player A with Hero A/Party selected, open the quest detail/progress links available to that member.

**THEN**

1. Objective completion produces a hint, not automatic quest completion or reward delivery. Prerequisites remain GM guidance rather than an invented runtime gate.
2. Global and Party states remain separate. Suspended/finished quest mutations are correctly refused.
3. Reversible latest completion restores the prior state with history intact; structural edits freeze after progress. Player sees the intended party projection and no GM planning fields.

### TC-28 — Knowledge creation, guided navigation and unsaved claim edits

- [x] Test case executed and result recorded.

**GIVEN**

1. Log in as `phase13e.gm2`. You should see New claim and the GM Knowledge workspace; published Archive is selectable as a subject.

**WHEN**

1. Create claim `R The archive closes at dusk.`, select a settled/fact kind, truth True, a sensitivity from the offered catalog, subject Archive; save as draft and record its ID.
2. In Prepare → Claim, change wording; check Save/Discard, discard once, then edit and save. Keep the final wording in the ledger.
3. Make another unsaved edit; navigate among stages/sections and with Back/Forward, keeping any selected character/party query parameters. Use header Next.
4. Attempt to leave for World and cancel the discard dialog; then discard intentionally. Close/reload a tab with a dirty edit and inspect the browser's real unsaved-change prompt.
5. Open its old `/edit`, `/audience`, `#claim` and `#who-knows` addresses.

**THEN**

1. One guided claim page handles Prepare, Review & publish and Use in play; only its current section is shown. Navigation changes no claim/lifecycle state.
2. Save is enabled only for changes, Discard restores saved values, and successful save stays on the claim and announces success after the response.
3. Navigation/reload guards are real browser behavior; perspective survives redirects and fragment mappings to Claim / Who knows.

### TC-29 — Claim review/publication, rejection and unpublished subject guidance

- [x] Test case executed and result recorded.

**GIVEN**

1. Log in as `phase13e.gm2`. You should see TC-28's draft claim with Review & publish and an enabled submit action; Archive is canon.

**WHEN**

1. Make an unsaved claim edit; submit for review and handle the warning. Read the summary in Review claim, approve and publish in Publication.
2. Create draft location `R Unpublished subject` and a second claim `R The hidden quay exists.` about it; submit and approve the claim, then try Publication.
3. Follow Publish its subject first; publish the location through submit/approve/publish, return to the claim and publish it.
4. Create another claim `R Rejected claim`; submit, reject with a reason, then use Return to draft and edit it.

**THEN**

1. Submission does not silently apply an unsaved edit; the page identifies an unapplied edit and allows discarding it. Review/publication succeed for the valid saved claim.
2. Approved claim with a draft subject names the true blocker, links the subject and offers only valid lifecycle actions. Publishing a claim does not tell any audience about it and never requires a source.
3. Rejected status and Return to draft are clear; returning makes the claim editable. Draft/in-review/approved/rejected audience sections show recorded rows but no knowledge-assignment action.

### TC-30 — Party reveal, individual learning, telling, belief and public knowledge

- [x] Test case executed and result recorded.

**GIVEN**

1. Log in as `phase13e.gm2`. You should see the first published claim from TC-29 with Who knows this and no existing audience rows; Party/Reserve, Hero A/B and Archivist are eligible.

**WHEN**

1. Tell Party at the current time; record Hero A learning it with interpretation `R I believe it closes at sunset`, offered awareness/confidence and sharing values.
2. Record Hero A telling Hero B, with interpretation `R I heard it closes at dusk` and an offered transfer method.
3. Expand Hero B Details, change its belief/confidence, save, and compare the canonical claim with the belief. Attempt to tell Hero B again.
4. Make the claim public at Haven. While a claim edit is dirty, perform an independent valid Who knows action; verify it does not save/discard that edit.
5. Tell Reserve too and inspect the “every active party already knows” state. As each player, select their hero with/without Party and open this claim.

**THEN**

1. Party, individual and public groups remain separate; each action creates its own recorded event and closes only its successful form.
2. Telling an existing knower is refused with the form/input retained and a group-local error; Change belief is the supported path. Beliefs do not rewrite canonical truth.
3. Once known, claim wording/kind/subject freeze with an explanation. Players receive their safe interpretation and character/party knowledge details, without truth/sensitivity leakage or duplicates.

### TC-31 — Archived and superseded claims retain knowledge without new writes

- [x] Test case executed and result recorded.

**GIVEN**

1. Log in as `phase13e.gm2`. You should see TC-30's canon claim with recorded knowers and Archive available in Publication.

**WHEN**

1. Archive it with a reason; inspect Who knows and attempt a new learning/belief action if offered. As Player A, reload its prior URL.
2. Restore with a reason, then record a legitimate belief update on Hero B.
3. Create and publish replacement `R The archive closes at midnight.` about Archive, without assigning an audience. Supersede the old claim with that replacement.
4. Inspect the old claim, replacement and Hero A's Knowledge list; expand old belief details.

**THEN**

1. Archive keeps recorded knowledge but offers no new learning/belief write; players cannot read the archived record. Restore is prominent and requires the supported reason.
2. Superseded claim links its replacement and directs new knowledge there; old details are text only.
3. Replacement does not automatically inherit/move knowers. No fabricated deprecated-state transition is required: if a deprecated fixture is supplied separately, it should show no forward step/Next link.

> **Post-run note (CP-7 / DR-1, not part of the recorded result).** THEN 1's "players cannot read the archived record" is reconciled with DR-1: an archived claim is no longer in lists or archive browsing for a player (`lifecycle=archived|all` is a 403 for them), but a player whose audience already includes the claim can still open it by its prior URL as read-only published history, with no new learn/tell/belief write offered. The archive-browse half (Active / Archived / All, eligibility, paging) is verified by automated tests only; the manual TC-31 archive part has not been performed and remains CP-11 acceptance.

### TC-32 — Claim Sources, separate retry keys and navigation guard

- [x] Test case executed and result recorded.

**GIVEN**

1. Log in as `phase13e.gm2`. You should see the replacement claim's Prepare → Sources section, with optional-source guidance; it has no source yet.

**WHEN**

1. Choose an offered source type, title `R Claim source`, reference `R GM-SOURCE-ONLY`; click Write and attach source with Network open.
2. Inspect the create and attach request keys and successful responses; follow View provenance and return.
3. Begin typing another source and try leaving the page; cancel the discard dialog, then discard explicitly.
4. Detach the existing source with confirmation, inspect the claim's status/version, and reattach it from the source picker.

**THEN**

1. Create and attach use different derived keys (`.create` and `.attach`), both succeed, and produce one attached source.
2. Sources can change at any status without changing definition version or requiring another approval; provenance returns to Sources with perspective intact.
3. Typed source data participates in the unsaved guard. No source reference text leaks to players.

### TC-33 — Dungeon, two areas, connections and structural content

- [x] Test case executed and result recorded.

**GIVEN**

1. Log in as `phase13e.gm2`. You should see New dungeon in `R Campaign` World and published Haven as a parent choice.

**WHEN**

1. Create `R Vault`, parent Haven, danger level 1; add areas `R Entry` (room) and `R Store` (room).
2. Edit Entry's summary, size `20 by 20 feet` and environment `Dry stone`; save and reload its deep edit URL.
3. Add a connection Entry → Store using an offered type, hidden Yes, one-way No; change it to one-way and back, saving each.
4. Add an Entry feature `stone plinth`, hazard `trip wire` with valid severity, and interactable `iron lever`, filling offered required fields. Edit each description; remove/re-add one while the dungeon remains draft.
5. Publish the required parent/dungeon/area records through their offered submit/approve/publish actions, resolving any displayed reference blocker in dependency order. Reload all detail/edit URLs.

**THEN**

1. Areas belong to Vault; connection endpoints and typed fields persist. Structural edits do not create play-state events.
2. Draft-only structural removal works; published structure offers only actions the server permits. No unsupported map/image upload is implied.
3. Parent/child publish blockers are clear and records remain reachable through dungeon/area breadcrumbs.

### TC-34 — Dungeon runtime state and correction

- [x] Test case executed and result recorded.

**GIVEN**

1. Log in as `phase13e.gm2`. You should see the published Entry editor's state panel and published connection/content from TC-33, with current clock T2.

**WHEN**

1. Mark Entry searched, set alarm level 1 and GM condition notes `R GM-DUNGEON-ONLY`; save its state.
2. Set an offered new connection status, then offered feature/hazard/interactable statuses; inspect each resulting event and reload state.
3. Open the latest supported state event's correction preview and void it with a reason; attempt an earlier dependent reversal while later changes remain.
4. As Player A, open the published dungeon/area and inspect JSON for hidden connection/content and GM condition notes.

**THEN**

1. Runtime changes record events/effects in this timeline and do not rewrite structural definitions.
2. A supported latest reversal restores the preceding state; a moved-on/unsupported reversal gives the real refusal and preserves state.
3. Player rendering and response omit hidden structural information and GM notes according to the read contract.

### TC-35 — Relationships and participant perspectives

- [x] Test case executed and result recorded.

**GIVEN**

1. Log in as `phase13e.gm2`. You should see Relationships panels on the heroes, Archivist, Council and locations, with Add relationship controls.

**WHEN**

1. Create a Family relationship between Hero A/B with an offered pair of participant roles and family name `R Family`.
2. Create Employment between Archivist and Council, job title `Archivist`; create Ownership of Archive by Council with valid share/public values; also create Political and General examples using the server's offered role shapes.
3. Edit a description and participant perspective with emotional tone plus private interpretation `R GM-RELATIONSHIP-ONLY`; save and reload.
4. End a disposable General relationship at a later time; archive it, show archived and restore with the required confirmation/reason.
5. As Player A, inspect the same related records and available relationships.

**THEN**

1. All five supported kernel kinds save their typed fields/participant roles atomically. Wrong role shapes/foreign participants are excluded or refused.
2. Lifecycle and end-time changes persist with history and version checks; archived relationships cannot take new reaction changes.
3. A player's perspective does not expose another participant's private interpretation or GM management controls.

### TC-36 — Organization members, offices and operational status

- [x] Test case executed and result recorded.

**GIVEN**

1. Log in as `phase13e.gm2`. You should see Council's Members and offices section and editor status controls; Archivist and heroes are published.

**WHEN**

1. Add Archivist as a Council member, office `Keeper`, rank `Senior`, Known to public Yes; reload.
2. Add Hero B with public No. Edit Archivist's office/rank through its relationship editor and save.
3. Set a different offered organizational operational status at T2; inspect its event and reload.
4. As Player A, inspect Council's member roster and status. End a membership with a valid later time as GM2 and inspect historical/current roster behavior.

**THEN**

1. Public office/rank appear in the allowed roster; hidden membership/private details stay out of the player's response.
2. Memberships use the relationship authoring boundary; operational status is event-backed timeline state, not a definition status overwrite.
3. Ended membership/history remains coherent. Invalid/archived targets cannot receive new membership/state changes.

### TC-37 — Routes and travel for individuals and whole parties

- [x] Test case executed and result recorded.

**GIVEN**

1. Log in as `phase13e.gm2`. You should see Play in progress, Travel in Run session, published Haven/Archive and Party with eligible current members.

**WHEN**

1. On Haven's Relationships panel create a Route to Archive; set Distance `1 mile`, Travel time `20 minutes`, Mode `walk`, Concealed No. Reload, then toggle Concealed Yes and inspect the player route view; restore No.
2. In Play → Travel choose individual travelers Hero A and Archivist, destination Haven, with no route; record travel.
3. Travel those individuals Haven → Archive with the optional route selected. Inspect each character's location and the travel event.
4. Choose whole Party and destination Haven; inspect the resolved traveler set, record travel, and inspect Hero A/B locations.
5. Try using a route that does not connect the travelers' origin and destination or an ineligible party, where selectable.

**THEN**

1. Route metadata persists; concealed route details are absent from player reads.
2. Travel moves only the explicit/resolved eligible travelers in this timeline and records causal effects; party travel uses the current membership set.
3. Invalid choices are excluded or refused atomically; navigation between Travel and other sections preserves entered choices until submission.

### TC-38 — NPC portrayal versions, runtime and privacy

- [x] Test case executed and result recorded.

**GIVEN**

1. Log in as `phase13e.gm2`. You should see Archivist's Portrayal link and Run this NPC panel, initialized 20 HP and no portrayal profile yet.

**WHEN**

1. Open Portrayal, change Detail level to another offered value, and save a profile with a visible text field containing `R GM-PORTRAYAL-ONLY`; save with change note `First portrayal`.
2. Change that field and save `Second portrayal`; open version 1 and version 2, then save the unchanged latest values once.
3. Return to Run this NPC: apply HP change -3, add an offered condition with source `R condition`, remove it, and move to Haven at an available time.
4. On the new NPC, inspect Resources → None tracked; select an offered resource and try Change -1. Verify the missing-tracked-resource refusal and unchanged state. There is no portal resource-initialization flow: this snapshot has a tracked spell-slot row only for dev Character A, not an NPC. Record positive NPC resource spend/restore as Blocked until a supported pretracked NPC fixture is supplied; do not invent a row with SQL or claim a positive pass from this refusal.
5. As Player A, open Archivist and type its Portrayal URL; inspect character/World responses.

**THEN**

1. Profiles append versions; old text remains readable to the GM. Unchanged save does not create a redundant version.
2. Successful HP/condition/location operations use tracked state commands with causal events; HP becomes 17 after the damage operation, before any later changes. Missing resource state is explained and is not initialized by adjustment.
3. No player response contains the portrayal marker/profile, and the player cannot operate NPC controls. AI-use of portrayal remains outside this phase's contract.

### TC-39 — World-owned item definitions and generic seed protection

- [x] Test case executed and result recorded.

**GIVEN**

1. Log in as `phase13e.gm2`. You should see Item definitions in `R Campaign`, seeded generic definitions and New item definition; there are no world-owned test definitions.

**WHEN**

1. Create `R Token kind`, an offered category/rarity, weight 1, value 2 gold, Description `Public token`, Status Canon, Requires attunement No; save and record its ID.
2. Create `R Charm kind` similarly, Requires attunement Yes, Status Canon; edit its description, save and reload.
3. Create `R Draft kind` with Draft status; inspect instance creation options. Open a generic seeded definition and inspect its edit controls.
4. Filter definitions by category; as Player A inspect navigation and type `/app/C/item-definitions`.

**THEN**

1. World-owned create/edit and category filters work; values persist and belong to this world/ruleset context.
2. Draft definition cannot be used to create an eligible instance; generic seeds are read-only to the GM through this form.
3. Players have no Item definitions management navigation/form. Negative numbers/invalid required fields produce explained validation rather than a partial record.

### TC-40 — Item instance authoring, award, transfer, equip and custody

- [x] Test case executed and result recorded.

**GIVEN**

1. Log in as `phase13e.gm2`. You should see Items → New item with Token kind and Charm kind offered; Play is in progress with Hero A/B present.

**WHEN**

1. Create `R Token`, Token kind, summary `Test treasure`, origin notes `R GM-ITEM-ONLY`; submit, approve and publish from its lifecycle panel. Edit summary and reload; inspect the fixed definition choice.
2. In Play → Award item, select Token, recipient Hero A, quantity 3 and ownership as intended; submit.
3. Open Token's World page/Run this item, equip it, attempt to give it to Hero B while equipped, unequip, then give to Hero B transferring ownership.
4. Inspect both character inventories and Party inventory; place Token at Haven and inspect its location/custody.
5. As Player A inspect allowed inventories and the item response; as Player B inspect Hero B's inventory.

**THEN**

1. Instance creation requires a published usable definition, creates a draft and leaves definition fixed. The item page has exactly one Lifecycle panel.
2. Award and custody/equipment changes are event-backed; equipped transfer refuses until unequipped. Inventory reflects the actual holder/place/owner without duplicate custody.
3. Player inventories are limited to authorized characters; party inventory is a GM surface. No origin-notes marker appears in player JSON.

### TC-41 — Item quantity, damage/repair, attunement and destruction

- [ ] Test case executed and result recorded.

**GIVEN**

1. Log in as `phase13e.gm2`. You should see Token at Haven with quantity 3 and available runtime controls; Hero B can carry a fresh Charm.

**WHEN**

1. Consume one Token unit, inspect quantity 2, damage then repair it using valid amounts, and inspect each event/state.
2. Create and publish `R Charm` from Charm kind; award to Hero B, attune to its carrier at T2, and attempt transfer/destruction while attuned.
3. Advance clock to T3; end attunement, then transfer the charm or leave it at Haven.
4. Consume the remaining Token quantity; inspect destroyed state, then attempt another operation. For a disposable unreferenced published item, inspect archive/restore; cancel a destructive confirmation once before proceeding.
5. On the latest supported item-operation event inspect correction and void it; then inspect the earlier operation's reversibility.

**THEN**

1. Quantities never go negative; consuming the last unit destroys the item. Destroyed items reject further runtime changes until an explicitly supported correction restores them.
2. Attunement requires the carrier, blocks custody/destruction, and ends strictly after its start. Limits/errors are understandable.
3. Supported correction restores the previous component/token state without losing history; no cancellation creates an effect.

### TC-42 — Encounter preparation and compact participant roster

- [ ] Test case executed and result recorded.

**GIVEN**

1. Log in as `phase13e.gm2`. You should see Play's Prepare → Encounter preparation and published Hero A/B/Archivist available; no new prepared encounter exists.

**WHEN**

1. Prepare an encounter at Archive with summary `R Vault dispute`; save and record its ID.
2. Add Hero A on an offered friendly side and Archivist on an offered opposing side; inspect the compact roster.
3. Change Archivist's side; observe Save appearing only while changed, cancel by restoring the old selection, then change and save once.
4. Remove Archivist with its named compact remove control, then re-add it. Try adding Hero A twice.
5. Follow Run the session, switch stages, return to the encounter and reload its deep address.

**THEN**

1. Pending preparation records no combat-start/turn events. The roster offers side changes and removal without an initiative-entry form.
2. Save is present only for a changed row, row errors stay beside that participant and duplicates are refused.
3. Breadcrumb includes Sessions → Play → encounter context; return links go to the correct run section and preserve campaign context.

### TC-43 — Operate an encounter, turns, damage and outcomes

- [ ] Test case executed and result recorded.

**GIVEN**

1. Log in as `phase13e.gm2`. You should see the pending Vault dispute with Hero A and Archivist, and Start encounter; their tracked HP values are available.

**WHEN**

1. Start the encounter; inspect active status and Round 1. Try modifying preparation afterward.
2. Record Hero A acting, select Action Attack from the offered action catalog, target Archivist, Result Hit, Damage 2, leaving Round blank.
3. Record Archivist's turn; try a duplicate actor turn in the same round, then record a valid subsequent-round turn using the offered Round field.
4. Inspect character HP and turn history; end with offered participant outcomes and summary `R Dispute resolved`.
5. Reload the encounter and Play's Run session → Encounters and Wrap up → Session review.

**THEN**

1. Start records one start event and opens Round 1; preparation is no longer editable.
2. Blank round/order use server defaults; damage changes tracked HP once and cannot take it below zero. Duplicate-turn conflicts are explained.
3. End persists outcomes/result and makes the record read-only, with rounds/turns retained and correct session links.

### TC-44 — Discard pending and abort active encounters

- [ ] Test case executed and result recorded.

**GIVEN**

1. Log in as `phase13e.gm2`. You should see Play's encounter-preparation form; Vault dispute is completed and there are no pending disposable encounters.

**WHEN**

1. Prepare `R Discard test`; choose Discard, cancel its confirmation, then confirm.
2. Prepare `R Abort test`, add Hero A, start it and record one valid turn; choose Abort, cancel once, then confirm.
3. Reload both encounter pages and inspect history/resulting-event links.

**THEN**

1. Cancellation leaves status unchanged. Pending discard ends preparation with aborted status and no play event.
2. Active abort records a causal event, retains turns/history and makes the encounter read-only; it does not invent a completed outcome.
3. The session's encounter lists distinguish pending, active, completed and aborted records correctly.

### TC-45 — Sources and provenance across typed records

- [ ] Test case executed and result recorded.

**GIVEN**

1. Log in as `phase13e.gm2`. You should see Sources sections on Archive, Council, Faith, Archivist, Quest, Vault and Charm, with attach/write controls.

**WHEN**

1. On Archive, write and attach source `R Field notes`, an offered source type, reference `R GM-PROVENANCE-ONLY`; record its source ID.
2. Attach that existing source to each other listed record; open each View provenance link and follow its record/history links.
3. Attempt duplicate attachment on Archive; detach with confirmation, inspect provenance and reattach.
4. Inspect a draft record's Sources, then approve/publish it and verify the attachment remains. Compare row version/history before and after attachment.
5. As Player A, type a captured provenance URL and inspect ordinary record responses.

**THEN**

1. Sources attach to the correct world/entity and provenance identifies their real creation/attachment context.
2. Duplicate/refused operations are explained; attachment/detachment does not revise the canonical definition or invalidate approval.
3. Player cannot open GM provenance/history surfaces or obtain reference text through ordinary reads.

### TC-46 — Revision history and comparison

- [ ] Test case executed and result recorded.

**GIVEN**

1. Log in as `phase13e.gm2`. You should see Archive's provenance/history links and at least its creation, summary edit and lifecycle revisions from this run.

**WHEN**

1. Open Revision history; select two different revisions and compare.
2. Check name/summary/status changes against the recorded fixture operations, inspect actor/version/timestamp, and switch comparison order.
3. Save an unchanged edit and refresh history. Cause a stale edit using TC-48's two-profile procedure and inspect history again.
4. Open a pre-existing dev record whose old edits predate revision capture and inspect its history messaging.

**THEN**

1. Comparison presents the correct earlier/later values with a readable table and real actor; snapshots are separate from redacted audit.
2. No-op saves, stale refusals and request replays create no extra revision. Lifecycle transitions have their own status revision.
3. Missing older snapshots are not fabricated from audit. Comparison is GM-only and usable at narrow widths.

### TC-47 — Review queue and general lifecycle transitions

- [ ] Test case executed and result recorded.

**GIVEN**

1. Log in as `phase13e.gm2`. You should see Review in `R Campaign`, including new draft location/organization records and published run fixtures.

**WHEN**

1. Create disposable location `R Lifecycle` with no dependent references. In Review filter Drafts, find it and open it.
2. Submit, reject with a reason, return to draft, edit summary, resubmit, approve and publish; inspect the appropriate queue filter/count after each.
3. Create/publish `R Lifecycle replacement`; supersede Lifecycle with it and follow the replacement link.
4. Archive/restore the replacement with reasons, cancelling the archive once. Create another unreferenced draft `R Delete draft`, delete with confirmation, and reload its URL.
5. Exercise queue category/status/search filters and Load more when enough results exist; inspect Player A's navigation and typed Review URL.

**THEN**

1. Queue counts/results and lifecycle actions agree with server state; filters and record links work. Every confirmation is clear and cancel changes nothing.
2. Supersession/archive preserve records/history; physical deletion is restricted to the eligible draft and returns to a valid list.
3. Player sees no Review/lifecycle management; missing/deleted/hidden record responses disclose no draft content.

### TC-48 — Validation, stale writes, retry and no-store reads

- [ ] Test case executed and result recorded.

**GIVEN**

1. Log in as `phase13e.gm2`. You should see Archive's Edit form populated with its saved summary; a second `admin` profile can edit the same record.

**WHEN**

1. In GM2's form blank the required name and submit; follow the validation summary link, restore name and enter summary `R GM2 pending` without saving.
2. In admin's profile change Archive's summary to `R Admin saved`, save and confirm success. Back in GM2's old form submit its pending edit.
3. Inspect the stale notice/input, use Load latest, reapply the intended new summary and save; reload and navigate Back to the editor with Network open.
4. For a fresh create or travel command, save its successful Network request privately. Replay the exact request once with the same body and Idempotency-Key using browser Edit and resend or an equivalent authenticated request tool; inspect receipt/state/history.
5. In the same test environment reuse that key with a different body; inspect the conflict. Simulate a transient request failure using browser offline mode, restore connection and use the page's Retry where offered.

**THEN**

1. Field validation and server-coded failures are readable/associated with controls; invalid save changes nothing.
2. Stale write refuses overwriting admin's value; GM2's pending input remains available until explicitly replaced. Loading latest/reapplying succeeds.
3. Authoring reads use `Cache-Control: no-store`; Back/reload shows authoritative data.
4. Same-key retry returns the same minimal receipt and produces one object/effect/revision; changed-body key reuse conflicts. A transport retry must not duplicate an uncertain successful mutation.

### TC-49 — Plain-player denial matrix for every GM page family

- [ ] Test case executed and result recorded.

**GIVEN**

1. Log in as `phase13e.player_a`. You should see `R Campaign` as a Player with Hero A, public data and no GM authoring sidebar links.
2. In admin's profile, privately collect the actual generated URLs for each row below. `:id` placeholders must be replaced with the corresponding run fixture's ID.

| Page family to attempt | Test address under `/app/C` |
|---|---|
| Location / organization / religion authoring | `/world/location/new`, `/world/location/:id/edit`, `/world/organization/new`, `/world/organization/:id/edit`, `/world/religion/new`, `/world/religion/:id/edit` |
| NPC / PC / builds / portrayal | `/characters/npc/new`, `/characters/pc/new`, `/characters/:id/edit`, `/characters/:id/builds`, `/characters/:id/builds/new`, `/characters/:npcId/portrayal` |
| Party management | `/parties/new`, `/parties/:id`, `/parties/:id/edit` |
| Session and encounter operations | `/sessions/new`, `/sessions/:id/run`, `/sessions/:id/encounters/new`, `/sessions/:id/encounters/:encounterId` |
| Events / quest operations | `/events/new`, `/events/:id`, `/quests/new`, `/quests/:id/edit`, `/quests/:id/progress` |
| Knowledge authoring / management | `/knowledge/new`, `/knowledge/:id/edit`, `/knowledge/:id/audience`, `/knowledge/member-preview` |
| Dungeon authoring | `/world/dungeon/new`, `/world/dungeon/:id/edit`, `/world/dungeon/:id/areas/:areaId/edit` |
| Items / definitions | `/items`, `/items/new`, `/items/:id/edit`, `/item-definitions`, `/item-definitions/new`, `/item-definitions/:id` |
| Sources / revisions / review | `/world/:category/:id/provenance`, `/world/:category/:id/history`, `/review` |
| Time authoring | `/world-times` |

**WHEN**

1. Type **every address** in the table as Player A; for each record heading, controls, request status and response shape.
2. Inspect ordinary published World/character/item/organization pages for embedded relationship, office, NPC runtime, inventory, source and lifecycle controls.
3. Repeat representative denied routes as the observer and as a signed-out browser. As Player A, type another campaign's corresponding route using Dev B's real ID, then a nonexistent campaign's route.

**THEN**

1. GM pages give the supported permission/not-found state without a partial form or GM response fields. Knowledge legacy URLs may redirect to the allowed **read-only claim**, never to editor stages.
2. Published member-safe detail/list surfaces stay usable, with no management controls. Party list reads do not authorize GM member-management pages.
3. Signed-out routes require login; foreign-campaign and nonexistent targets are non-disclosing. Record each address separately; one representative refusal does not pass the whole matrix.

### TC-50 — End session, review, completed read-only state and archive/restore

- [ ] Test case executed and result recorded.

**GIVEN**

1. Log in as `phase13e.gm2`. You should see Play in progress with its participants, public/private log, travel, awards and completed/aborted encounters from the earlier cases.

**WHEN**

1. Open Wrap up → Session review; inspect overview, participants, log including GM notes, encounters and each Go to link.
2. Open End session, enter recap `R Session complete` and Ends at T4; cancel once, then confirm.
3. From Sessions choose Run Play again; inspect all stages and attempt a new log/participant/travel/award/encounter action if offered.
4. On the session page inspect planned-start editing, archive with reason, show archived, restore with reason and reload. Inspect the session as Player A before/after archive and restoration.

**THEN**

1. Review links open the right sections or state why navigation is unavailable. GM notes remain GM-only.
2. Cancel leaves the session running; confirm completes it with correct world and real-world end labels. Run Play defaults to Wrap up → Session review.
3. Completed/archived sections explain their read-only state; no further play command succeeds. Started planned time is not freely rewritten.
4. Archive hides the session from players; restore restores its completed state/history, not a fresh scheduled session.

> **Post-run note (CP-8 / DR-3, not part of the recorded result).** Members without `canon.edit` now see a member-safe **Participants** roster on session detail: every stint (present or left, including a rejoin, with its times) of the participants they may discover, no management controls, no placeholder or hidden count, and a name is a link only where the character page would open for them. Re-performing the member view of this case (TC-50: the completed session read-only roster) (a player with a related PC and a discoverable NPC, an undiscovered NPC absent, an observer) is **outstanding** and part of CP-11 acceptance; it has been verified by automated tests only.

### TC-51 — Campaign, timeline and world archive/restore guards

- [ ] Test case executed and result recorded.

**GIVEN**

1. Log in as `admin`. You should see `R Campaign` Settings and `R World`/Primary overview with management actions; Play is completed and Next is scheduled.

**WHEN**

1. Attempt to archive the world and Primary while an active campaign depends on them; inspect blocked-action explanations.
2. Create a separate `R Empty world`, choosing an allowed/default ruleset and naming its initial primary timeline `R Empty timeline`, with no campaign. Record its generated slug. Archive/restore the timeline and world through their offered actions, cancelling each dialog once first.
3. In `R Campaign` Settings edit its name/description, then Archive campaign with a reason. As Player A reload its old Home URL and campaign selector.
4. As admin show archived campaigns, reactivate it, and reload player access and Settings. Restore the original `R Campaign` name.

**THEN**

1. Dependent active-campaign guards prevent unsafe world/timeline archive; blocked controls explain why.
2. Eligible archive/restore succeeds with reason/history and no physical deletion. Cancel changes nothing.
3. Archived campaign disappears from usable member selection/authorization; reactivation restores intended memberships and history. It does not bypass a world/timeline prerequisite.

### TC-52 — Timeline branch boundaries, inherited clock/build and independent writes

- [ ] Test case executed and result recorded.

**GIVEN**

1. Log in as `admin`. You should see `R Primary` with Create branch and a valid branch-point catalog; `R Campaign` is active and has events at known T0–T4 points.

**WHEN**

1. Create `R Branch` at a selectable recorded point before a later parent event; record its branch world-time/event IDs.
2. Through New campaign create `R Branch campaign` on that branch using the same ruleset. Inspect its clock, effective character build/state and event list against the recorded branch point.
3. Back in the parent, record Other event `R Parent after branch` at a later world time. Under Branch campaign search/open it, including a direct URL with its ID.
4. Advance the branch's clock independently to a later test-world time and compare both campaign clocks.
5. Inspect branch party memberships before creating any branch-local ones; inspect timeline edit fields for attempts to change lineage/branch point.

**THEN**

1. Branch lineage is fixed; effective clock/build/state obey supported branch-point inheritance and exclude later parent changes.
2. Post-branch parent event is absent and its branch-scoped detail is non-disclosing; branch clock writes do not move the parent's clock.
3. Party membership rows start empty on the branch under the documented current model; do not fail this case for unimplemented membership inheritance.

### TC-53 — Explicit world_viewer without campaign membership

- [ ] Test case executed and result recorded.

**GIVEN**

1. Log in as `phase13e.observer_a`. You should see the campaign-derived worlds from your memberships, but **no** `R Empty world` entry from TC-51 yet; that world and its timeline have been restored to active.
2. In the isolated test DB's operator shell, grant this account explicit read-only access using `uv run python scripts/manage_world_membership.py --world-slug <R-empty-world-slug> --login-name phase13e.observer_a --set-role world_viewer` to preview, then the same command with `--apply`. No portal world-membership form exists. Refresh the observer's session.

**WHEN**

1. Open All worlds, follow Empty world, open its Timelines collection/overview and inspect calendar reads.
2. Type its world Edit, New calendar, New timeline, timeline Edit/Branch and New campaign setup routes.
3. As operator end only this test-world viewer membership using the same script with `--end` (preview, then `--apply`); refresh and revisit the deep links.

**THEN**

1. Explicit viewer access opens world-scoped read pages without a campaign membership; the card is view-only.
2. No management/create actions or usable forms are offered, even as blocked actions. Revocation removes that world access on the next request.
3. Original campaign-derived dev/test-world access remains governed separately by campaign roles.

### TC-54 — CSRF, signed-out requests and current authority

- [ ] Test case executed and result recorded.

**GIVEN**

1. Log in as `phase13e.gm2`. You should see an editable disposable location in `R Campaign`; admin can manage GM2's test-campaign role from Access.

**WHEN**

1. Capture a successful test-location edit request privately. Resend a new intended edit with CSRF header omitted, then an invalid CSRF value; use fresh retry keys for distinct requests and inspect refusal/state.
2. In an authenticated HTTP tool against the test API, submit the same mutation with a foreign Origin, then without the session cookie. Do not share copied credentials with another origin.
3. In GM2's profile begin another edit. As admin revoke **only** the GM role assigned to GM2 in TC-13, leaving the original Dev A roles untouched; then submit GM2's pending test-campaign edit.
4. Restore GM2's test-campaign GM role through Access and refresh its session.

**THEN**

1. Missing/invalid CSRF and foreign Origin are rejected; signed-out mutation is 401. No version, content or state changes occur.
2. A role revoked before the next request removes authoring despite a previously rendered form; refresh removes stale navigation/access.
3. Restoration restores intended test access. This case does not claim to exercise the separately documented mid-flight adapter race.

### TC-55 — Responsive, keyboard, screen-reader, zoom and reduced-motion pass

- [ ] Test case executed and result recorded.

**GIVEN**

1. Log in as `admin`. You should see the populated `R Campaign` with every page/panel fixture from TC-11–52; use Player A and observer profiles for read-only variants.
2. Enable NVDA or Narrator and record version/browser. Have viewport presets **390, 1280 and 2560 px** and OS reduced motion available. Include **360, 768, 1280 and 1920 px** for Knowledge/Member preview.

**WHEN**

1. For **each of the 24 rows** in [the acceptance matrix](PHASE15_MANUAL_ACCEPTANCE.md#pages-and-panels), open its actual run-fixture URL at each required width; record screenshots and a separate result per row/width. Also cover All worlds/Timelines/context hierarchy, World category counts/browse navigation, Parties disclosure, and Member preview.
2. At each page inspect overflow/overlap, form/button wrapping, labels, tables and empty/error states. Check a history comparison and encounter roster at both narrow and ultrawide widths.
3. Use only Tab/Shift-Tab, arrows, Enter, Space and Escape to operate navigation, reference combobox selection, a failed validation, a confirmed/cancelled dialog and one safe save. Check visible focus, logical order, dialog containment/return and section-heading focus.
4. With the screen reader, read headings/landmarks, field names/hints/errors, roster/table headers and status messages; submit a safe command and verify success/error announcements. Repeat Knowledge as GM/player/observer and preview as GM.
5. Set browser zoom 200% and repeat page/control checks. Turn on reduced motion and navigate/save again. Restore normal settings afterward.

**THEN**

1. No horizontal **page** scrolling, clipped/overlapping content or inaccessible action; a table may scroll inside its own box. Context/sidebar/main remain coherent.
2. All controls are operable and announced with useful names; errors connect to fields; dialogs close/return focus correctly and command results are announced.
3. Zoom and reduced motion remain usable. Record failures individually; source inspection, component tests and headless screenshots cannot replace this assistive-technology pass.

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

### TC-57 — Manual privacy evidence for audit, receipts and reporting access

- [ ] Test case executed and result recorded.

**GIVEN**

1. Log in as `admin`. You should see `R Campaign`'s saved NPC, event, quest, source and item data; their GM markers are visible only in the intended GM views.
2. Have the isolated test DB's operator read-only inspection connection available, plus this run's IDs and operation times. This is technical evidence alongside browser testing, not a reporting-administration portal feature.

**WHEN**

1. In Network inspect the typed content mutation responses from this run: only the route's minimal receipt fields should be returned. Inspect replay rows and `audit.change_log.changed_fields` scoped to this run's resources/correlation IDs using a read-only transaction.
2. Search those audit/replay bodies for `GM-NPC-ONLY`, `GM-LOG-ONLY`, `GM-EVENT-ONLY`, `GM-QUEST-ONLY`, `GM-SOURCE-ONLY`, `GM-ITEM-ONLY` and `GM-PORTRAYAL-ONLY`. Record field names and redaction flags, not copied narrative.
3. Preview a member's Knowledge list/detail, then an invalid subject; inspect metadata-only `sensitive_read` audit entries for actor, subject/scope and shown/refused outcome. Verify they contain no response/claim body.
4. In a separate operator transaction use `SET LOCAL ROLE app_read_only`; read a permitted lookup such as `core.lifecycle_statuses`. In another transaction attempt `SELECT 1 FROM security.local_credentials LIMIT 1`, and in another attempt `SELECT 1 FROM core.entity_revisions LIMIT 1`; roll back each transaction.

**THEN**

1. Current typed-content receipts/replays contain no narrative; audit structural metadata remains useful while narrative fields are redacted. Full GM revision snapshots are intentionally separate and do not constitute an audit leak.
2. Sensitive preview is audited without copying its results. Both permitted and refused preview paths preserve that contract.
3. The reporting role can read the allowlisted reference lookup and cannot read credentials or GM revision snapshots. Pre-scrub backups remain subject to the documented retention policy; do not rerun migration 135 merely to perform this test.

### TC-58 — Targeted claim grants/denies and Member preview agreement

- [ ] Test case executed and result recorded.

**GIVEN**

1. Log in as `admin`. You should see `R Campaign` with Access and Knowledge authoring; observer and Player A have only the read roles established in TC-13.
2. Open a separate observer profile and Player A profile. Have their **test-campaign** membership IDs from Access available. This case uses the supported resource-grant API because the current Access UI creates only character-target allow grants; it does not create claim-target or deny grants.

**WHEN**

1. Create `R This grant claim is public.`, a settled claim about Haven; save, submit, approve and publish, then make it public at Haven. Record its ID. Verify observer and Player A can read it without GM controls.
2. In admin's authenticated browser request tool, POST `/api/campaigns/C/resource-grants` with JSON `{"knowledge_item_id":"<claim-id>","capability_code":"canon.edit","effect":"allow","grantee_campaign_membership_id":"<observer-membership-id>","reason":"Manual targeted claim test"}`. Use the current session's CSRF header and a fresh Idempotency-Key, following TC-48's private capture/resend procedure. Record the returned grant ID.
3. Reload the observer's claim with `?section=who-knows`; inspect canonical fields, available controls and authoring requests. As admin preview that observer with the same filters and compare the responses.
4. POST the same resource-grant route as admin with this claim, `capability_code` `campaign.view`, `effect` `deny`, Player A's membership ID and reason `Manual deny test`, using a fresh key. Reload Player A's list/direct claim, then preview Player A as admin using identical filters/perspective.
5. Revoke **only these two created grants** with POST `/api/campaigns/C/resource-grants/<grant-id>/revoke`, one fresh key per request and the current admin CSRF header. Refresh both members and their previews.

**THEN**

1. A targeted canon allow can reveal the claim's permitted canonical fields but does not turn the observer into a baseline GM: no stages, Save/Discard, sources/lifecycle or Who knows controls/authoring requests appear.
2. Targeted view denial removes the claim and makes direct access non-disclosing; admin's Member preview follows the subject's deny instead of admin's own authority.
3. Revoking the grants restores each subject's original public projection. Preview agrees with direct member requests throughout; no unrelated campaign role/grant changes occur.

## Coverage and result recording

Use one row **per case and parameter/URL/viewport variant**. All results start Not run. Copy this row as needed; evidence should identify the exact step and expected/actual behavior.

| Case / variant | Tester/date | Branch SHA / DB snapshot | Browser / viewport / assistive technology | Result (Not run / Pass / Fail / Blocked / Accepted) | Expected versus actual / evidence / issue | Retest SHA/result |
|---|---|---|---|---|---|---|
| | | | | Not run | | |

| Existing acceptance rows / checkpoint scope | Detailed cases |
|---|---|
| Phase 14 hierarchy, setup, lifecycle and world authority | 01–04, 10–13, 47–48, 51–54 |
| Rows 1–2: calendars, times, campaign clock | 14–15, 24, 52 |
| Rows 3–5: locations, organizations/religions, NPC/PC identity | 16–18, 35–36 |
| Rows 6–8: builds, portrayal, parties | 19–21, 38 |
| Rows 9–11: sessions, Run Session, events | 22–25, 37, 40, 42–44, 50 |
| Rows 12–13: quests and Knowledge claim | 07–09, 26–32 |
| Rows 14–16: dungeon, relationships, offices | 33–37 |
| Rows 17–19: item definitions, instances, encounters | 39–44 |
| Rows 20–23: sources, review, revisions, lifecycle | 29, 31–32, 45–48 |
| Row 24 and carried items: navigation, capability gates, unsaved guards, no-store | 01–06, 09–10, 23, 28, 32, 48–49, 53–55 |
| New branch corrections: World counts/browse, Parties disclosure, selected-character Knowledge, Member preview | 05–09 |
| Cross-scope, privacy, retries, CSRF and branch semantics | 10, 31, 48–49, 52, 54, 57–58; retain automated route/concurrency guards |
| Responsive and assistive-technology acceptance on every matrix page | 55, executed separately for every listed page/role/width |
| Clean-database exit scenario | 56 |

Record an additional coverage disposition for any fixture-dependent exceptional state not reached above (for example deprecated claims, positive NPC resource adjustment, a full attunement-limit setup, or exhausted narrative-time gaps): provision it through a supported command/API on the isolated DB and record a separate variant, or mark it Blocked with a reason. Do not silently claim those variants passed.

| Run ledger | Value |
|---|---|
| Run prefix; tester; execution dates | |
| Snapshot name/time; isolated DB/revision; API/portal ports | |
| Branch SHA actually tested | |
| Generated world/slug, timeline and campaign IDs | |
| Generated entity/party/session/encounter/source IDs and saved public texts | |
| Browser / NVDA or Narrator versions; viewports | |
| Failures and issue links; fixes and retests | |
| Blocked/accepted variants and owner's written disposition | |
| Clean-deployment walkthrough result | |
| Final-head CI run link and SHA | |
| Phase 14 hierarchy manual decision | Pending |
| Phase 15 manual acceptance decision and owner/date | Pending |

After testing, stop the isolated servers and dispose of only the explicitly named test databases/temporary configs using the recovery/runbook procedure. Preserve the original dev database and any agreed evidence. Phase 15 closes only after the owner records acceptance, failures have been fixed or explicitly accepted, and CI is green on the final tested head.

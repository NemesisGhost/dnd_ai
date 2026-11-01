# Step G data repairs and UI findings — 2026-10-30

The saved campaign data has been repaired to match the guide through G. **A confirmed application defect still prevents the guide's “Tobin has no current party at Meeting” UI expectation from passing**, even though the stored membership intervals now match that schedule. A future-dated organization-status display also needs a semantics decision.

This is scripted repair and verification evidence, not human acceptance. The owner expressly requested UI repairs followed by database changes for repairs the UI could not make. That authorization covers the maintenance exceptions below to the guide's normal no-SQL rule. No application source, migrations, account roles, passwords, or acceptance decisions were changed.

## Run identity and evidence

| Item | Value |
|---|---|
| Date / timezone | 2026-10-30, America/Chicago |
| Checkout inspected | `41264fe508969a0feaef1e3c193322a8b42827fb` |
| Working database | `dnd_ai`, `127.0.0.1:5432`, revision `140_clock_advance_details` |
| Portal / API | `http://127.0.0.1:5173` / `http://127.0.0.1:8000` |
| World | The Saltmarch — `abfc10db-d639-4271-a73b-5ebc767ae26c` |
| Campaign | The Drowned Archive — `5c4746c2-8ae6-4959-b707-432a529dd18b` |
| Campaign time after repair | Meeting, year 1 / Firstfall 1 / 10:00 |
| Browser | Chrome `156.0.8078.74`; separate automated browser profiles for each persona |
| Evidence directory | `C:\Users\nemes\dnd_ai_evidence_20261026\cp11\ui_db_repairs_20261030\` |

The prepared acceptance stack (`dnd_ai_m1415_accept_clean_20261026`, ports 8001/5174) was not the owner's working run and was not modified. Earlier environment/ledger descriptions of an accounts-only working database are historical. `.env`'s `POSTGRES_PORT=5433` is separate from its `DATABASE_URL` target at 5432; no service was reachable on 5433 during inspection. Connection settings were not changed.

UI writes used real portal forms and their normal confirmations. No direct HTTP mutation was substituted for a UI action. The integrated VS Code browser could read pages, but its controls intermittently timed out while its tab was hidden; work continued in a separate headless Chrome UI session. That tooling issue is distinct from the application findings below. Initial automation selector/navigation attempts and abandoned confirmations are not counted as completed UI repairs.

## Documented UI changes that worked

| Guide task | Documented capability | Repair and persisted result |
|---|---|---|
| E3 | Edit campaign description in Settings | Administrator saved `First campaign of The Saltmarch — the sunken archive.`; confirmed after reload. |
| F2 | Edit each extra location draft's summary | Saved summaries for Continent, District, Geographic feature, Location, Nation, Plane and Realm. All seven remain drafts; each edit returned to its detail page and has a saved update. |
| F3 | Edit the other organization kinds | Saved Military Unit summary/kind (`Harbour watch`) and Faction summary/ideology (`Civic self-rule`). Both remain drafts; their existing Council parent and Hollowmere headquarters were retained. |
| F4 | Edit the NPC's GM-only text | Corrected the missing leading `G` in `M-NPC-ONLY`. The private **GM notes** field now contains `GM-NPC-ONLY: secretly paid by the harbour guild`. The published-record **Save changes** confirmation was completed. Appearance remains `Blue coat with a brass lantern`. |
| G6 | Edit relationship description and participant perspective | Replaced Sella's employment public description with ordinary public text. Put `GM-RELATIONSHIP-ONLY` into Sella's private interpretation with emotional tone `Guarded`; existing private family interpretation retained. |
| G6 | Restore an archived relationship | Restored the Voss-Reed family relationship using **Include archived → Open → End or archive → Restore relationship**. Restore reinstated lifecycle availability; it did not remove the previously recorded end date. |
| G6 | Create Ownership | Added public 100% ownership of The Archive by Hollowmere Council, with Owner/Property participants. |
| G6 | Create Political | Added an Alliance between Hollowmere Council and Chapter of the Tide, with Ally/Ally participants and public cooperation terms. |
| G6 | Create General and exercise end/archive/restore | Created the UI's **other / Other connection** relationship between Mara and Sella, Subject/Object, starting at Meeting. Ended it at Discovery, archived it, and restored it. It is now active with its historical end retained. |
| G7 | Correct organization office/rank | Sella's public Council membership now reads **Chief Keeper (Principal)**. Joined time remains Arrival. |
| G7 | End an organization membership | Ended Tobin's nonpublic Council membership at Meeting, retaining Arrival → Meeting in history. |
| G7 | Set another operational status at T2 | Set Council status **Dormant**, When **Descent**. A new recorded event/applied effect and the state row reference agree. The earlier Active-at-Meeting event remains in history. See the display observation below. |

The original public employment marker was a data-placement error: the marker was in a reader-visible description. After moving it, actual player/observer response checks passed. This repair does not establish a defect in the private-interpretation filtering.

## Changes with no supported historical-correction UI

These are separate from failures of a documented edit control. The guide documents creating times and adding/ending party memberships; it does not provide a historical correction workflow for these saved values.

| Correction | UI inspection / documented limit | Database fallback |
|---|---|---|
| Reposition existing **Between bells** | World times offers a recorded list and **Record a new time**, with no existing-point editor. `src/dnd_ai/domain/world_time.py` explicitly says points are never edited and sort keys are permanent. | Confirmed this incorrectly placed point had **zero persisted foreign-key references**. Corrected its sort key from 86970 to 87030, strictly between Meeting 87000 and Descent 87060, retaining its ID. |
| Correct Mara's existing party join and omitted reason | Party detail offers Add member and End membership; no join-date/reason correction control. | Changed her join from Meeting to Arrival and added `Joined for the expedition`. |
| Correct Tobin's already-ended first party interval | History shows joined/left values without editing controls. End membership operates on an open interval and cannot amend the old one. | Corrected the first interval from Meeting → Descent to Arrival → Meeting. Preserved the separate Descent → open-ended rejoin. |
| Keep event provenance consistent with corrected party rows | These are recorded runtime events, not ordinary editable definitions. No party-history correction action updates them through the portal. | Corrected the two join events and one leave event, plus their three applied effects, to the same fictional time points as their memberships. Event IDs were retained. |
| Undo the accidental end of the restored family relationship | **Details** offers description/start/family-name corrections. **End or archive** offers end/archive/restore, but no clear/correct-end control. Restoring an archive does not undo an in-world end. | Cleared the family's accidental Discovery end. Its restored active lifecycle, participants, family name and authored perspectives remain. |

### Maintenance transaction and rollback evidence

- Before any repairs: `before_repairs_181039.dump`.
- Immediately before SQL fallback, including completed UI repairs: `before_db_fallback_20261030T182743.dump`, SHA-256 `34a335faf1e28ea981cbd118ae2f737c269d374b98929f1207e732ec5a53a1b2`. `pg_restore --list` succeeded with 3,437 TOC entries. A restore was not performed during this repair run.
- One owner-authorized transaction changed **11 gameplay/definition rows**: one time, two memberships, three events, three effects, one party version and one family relationship. The party version was advanced to invalidate stale management forms.
- It inserted **11 explicit `maintenance.step_g_repair` audit rows**, correlated by repair run `d9099814-1594-4efe-a647-21579e07dfc3`. Narrative join-reason text is represented only by presence metadata in those audit bodies.
- The transaction took exclusive locks on affected tables. It temporarily overrode only `core.world_times.tr_world_times_enforce_immutable` and `narrative.events.tr_events_enforce_recorded_immutable`, restoring both before commit. Foreign keys, range/overlap checks, scope checks, and other triggers remained active. All non-system application triggers were verified enabled afterward.
- Original and corrected rows are retained in `db_maintenance_20261030T182743.json`; the reviewed maintenance code is `maintenance_script.py`. The journal records the committed status. Original UI audit/replay receipts were not rewritten to pretend these were UI corrections.

The backups contain the database's original authentication data and remain outside the repository. No password, hash, cookie, invitation token, or credential-bearing connection string is in this document or the textual verification reports.

## What is not working as the guide expects

### DEF-007 — Future party rejoin is exposed as current at Meeting (confirmed)

**Expected (G4):** Tobin has no current party at Meeting, after his Arrival → Meeting interval and before rejoining at Descent.

**Actual after the SQL correction:** the database range containment query finds **zero** Tobin intervals containing the clock's Meeting sort key. Nevertheless, signing in through the UI as `player_b` and opening Tobin's Parties section shows **Parties (1)** and **The Lantern-Bearers**. The session-bootstrap read model also authorizes that party. The GM membership page calls the future open-ended Descent stint “Current members.”

**Cause confirmed in source:** `queries/party_members.py`, `queries/parties.py`, `queries/bootstrap.py`, and `api/access.py::resolve_party_perspective` use `effective_to_world_time_id IS NULL` / an equivalent open-ended test instead of testing whether the interval contains the effective campaign clock.

**Disposition:** Open; application correction or an explicit requirement decision is needed. A further database edit would have to remove/change the guide's required future rejoin to disguise this behavior, so no such workaround was made. No party-knowledge leak was exercised: this instance has no knowledge items yet. The premature party perspective itself was observed.

Evidence: `ui_verification.json`, `after_repairs_read_models.json`, `final_database_verification.json`, `player_b-future-membership-still-current.png`, and `party-members-after-db.png`.

Bounded fix/retest: align bootstrap, character-party reads, editor “current” labels and the per-request party-perspective guard with one effective-time policy. Verify Arrival/Meeting/Descent boundary behavior, a finite interval before its end, a future open-ended interval, and denial of an out-of-period party perspective. Do not fix only the UI label while retaining the authorization shortcut.

### DEF-008 — Future organization status is immediately labelled “Now” (observed; semantics triage)

With the campaign clock still at Meeting, the UI accepted **Dormant / Descent**, then displayed **Now: dormant** immediately. The data correctly records the status event at Descent. `queries/organization.py` reads the materialized `campaign.organization_state` directly and does not resolve its status as of the campaign clock.

The implementation consistently displays the latest recorded state. The guide's time-oriented workflow suggests an effective-time view but does not explicitly settle this status-card policy. **Owner/product semantics decision required**: apply time-aware status projection, or describe the card as the latest recorded status. No chronology-changing database workaround was applied. Evidence: the Set status action and read-back in `ui_actions.jsonl`, the event/state rows in `after_repairs_database_snapshot.json`, and `council-members-and-status-after-ui.png`.

### DEF-DOC-01 — Relationship restore has no reason entry

G6 instructs “restore with reason.” Both family and General restores used an immediate **Restore relationship** button with no reason field or reason confirmation. Restore itself worked. The application did not receive a reason through that UI; the ordinary restore audit reasons remain empty. The missing UI reason cannot be retrospectively represented as a human-entered reason by altering an audit row. Resolve by adding a reason control or changing the guide's expectation.

### UI wording and environment clarifications

- The guide's General kernel is chosen as **other** and displayed as **Other / Other connection**. Political is chosen by a concrete type such as **alliance**. These options worked; the kernel names are not literal picker labels.
- NPC private text is entered in **GM notes**, as the UI explicitly explains. The guide's phrase “GM background” should not be taken as an instruction to choose a differently labelled field.
- The working run is on `dnd_ai` and 8000/5173, not the prepared clean acceptance stack. The report and environment addendum record that difference without moving either database or changing acceptance results.

## Verification and remaining acceptance scope

- **36/36 final data, integrity and privacy checks passed.** See `final_database_verification.json` and the final snapshot taken at 18:28:36 -05:00.
- **Three real-browser persona checks** (`player_a`, `player_b`, `observer`) inspected **24 UI-generated successful campaign GET responses**: neither `GM-NPC-ONLY` nor `GM-RELATIONSHIP-ONLY` appeared. All three displayed Sella's edited public office/rank and excluded Tobin from the public Council roster.
- The real-browser verification has **9 passing assertions and 1 failing temporal expectation**, recorded separately as DEF-007. The data-check pass count does not turn that UI failure into a pass.
- Exact original character/time IDs, active builds, 20/20 HP, world/campaign access, two parties, clock history and the unused What If Timeline remain intact. No hierarchy cycles, membership overlaps, missing required subtypes, unvalidated constraints, or disabled application triggers were found. Party rows, join/leave events and applied effects agree after repair.
- No H-or-later sessions, quests, dungeons, item instances, encounters or character-location history were created.
- No cancelled-dialog, error-recovery, keyboard, responsive-layout or accessibility acceptance is inferred. Existing human ledger result cells remain unchanged. The working database now includes explicit repair history and is not an untouched manual-acceptance baseline.

Primary machine-readable evidence: `ui_actions.jsonl`, `ui_network.jsonl`, `ui_verification.json`, `db_maintenance_20261030T182743.json`, `after_repairs_database_snapshot.json`, `after_repairs_read_models.json`, `final_database_verification.json` and the screenshots listed above.

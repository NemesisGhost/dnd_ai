# DEF-001 — operation-level inventory of confirmed writes and their read-back

Written 2026-10-26 on `phase15/completion`, starting from HEAD `52fb3de891b3d7b4e61394edbab62a1f5b51dd2d`. This is the engineering record of the DEF-001 fix: what every portal mutation caller does after the server confirms a write, what was wrong, and what was changed or verified. It is **not** an acceptance result. DEF-001 is **not closed** by this document (see [PHASE14_15_DEFECT_REGISTER.md](PHASE14_15_DEFECT_REGISTER.md)); CP-11 and Phase 15 are not complete.

## 1. The contract being applied

Established by CP-2 and extended by CP-10 ([UI_DESIGN.md §"Write outcomes and refresh"](UI_DESIGN.md)); unchanged by this work:

- **Uncertain** (network/5xx before an answer): input kept; Retry sends the same body and `Idempotency-Key`.
- **Confirmed and refreshed**: the follow-up read(s) completed (`"ok"`).
- **Confirmed, read-back not completed** (`"failed"` or `"superseded"`, or a throwing callback): the write is saved and is **never sent again**; the page says the displayed state is behind, announces "done" only when a read completes, offers a **read-only** retry, and holds anything that would send the version or token it still shows.

## 2. Shared mechanisms (all in `portal/src`)

| Piece | Role | Status |
|---|---|---|
| `hooks/useAuthoringMutation.ts` | Separates request outcome from refresh outcome; reports `confirmed` when `onSuccess` returns `failed`/`superseded` or throws | **Unchanged** |
| `utils/refreshOutcome.ts` `combineRefetchOutcomes` | Joins several required reads (`ok` only if every read was applied) | **Unchanged**, now used by every multi-read caller |
| `components/authoring/feedback.tsx` `SavedRefreshFailedNotice` | The "saved, latest data could not be loaded" status | **Unchanged** |
| `hooks/useKeptResource.ts` `useKept` | Keeps the last good read through a recoverable failure; drops it on denied/unavailable | **Unchanged**, now used by the pages that used to be replaced by an error screen |
| `hooks/useConfirmedRefresh.tsx` | **New.** `useConfirmedRefresh`: renders the saved notice for a `confirmed` write, exposes `held`, reads again (never writes) on **Load latest**, announces the write when a read completes, recovers once when the page's own read later succeeds (a resolved write is not resurrected by a later unrelated failure). `useAnnounceWhenRead`: the page announces a write it could not read back once its read is applied, for a row or form that is replaced by the recovered read | **New** |

Two `useAuthoringResource`-level facts the work relies on: a gated (withheld) read answers `"failed"` without sending anything, so callers include a read in a combined outcome only when it is the caller's to make (`whenAllowed` in `WorldRecordWorkspace`); and a **denied/unavailable** answer is an authoritative result, not a failed read (World Sharing after an ownership transfer).

## 3. Method

1. Read the repository instructions, the DEF-001 register entry, the CP-10 handoff and the recovery-contract text.
2. Enumerated **every** `useAuthoringMutation` caller (56 call sites) and every other mutation path: `grep` for `useAuthoringMutation<`, for awaited/unused `refetch`/`refresh`/`reload` results, for `refetch().then`/`void refetch()` after a write, for `apiRequest("POST"|"PUT"|"PATCH"|"DELETE")` outside `api/`, and a review of the shared hooks (`usePairedRead`, `useAreaRuntimeRead`, `useDungeonCommand`, `LifecycleActionsProvider`, `TransitionControls`, `WorldTimeForm`).
3. Read each caller and its page's behaviour on a failed read (error screen, kept data, boundary reload).
4. The register's 14 additional sites plus the 8 named callers did **not** turn out to be exhaustive: the audit found further affected operations (Encounters, Session detail and lifecycle, Clock card, Event pages' second read, Dungeon commands, the shared lifecycle panel's own read, Relationship and Organization roster writes, World times). They are included below.

## 4. Inventory

Legend — **Reads**: what must be read back for the screen to agree with the write. **Result**: *Corrected*, *Compliant (reference)*, *Compliant (by design)* or *Retained difference*.

### 4.1 Corrected

| # | Operation (caller) | Reads | Behaviour before | Correction | Tests |
|---|---|---|---|---|---|
| 1 | World archive / restore (`TransitionControls` in `WorldOverviewPage`) | the world | `await refetch()`, outcome dropped; "World archived" announced; failed read replaced the page by "could not be loaded" | Returns the outcome; record kept (`useKept`); saved notice with read-only **Load latest**; transition held while stale; "done" announced when a read completes | `pages/WorldOverviewPage.test.tsx` (confirmed archive + failed read) |
| 2 | Timeline archive / restore (`TransitionControls` in `TimelinePage`) | the timeline | same | same | `pages/timelinePages.test.tsx` |
| 3 | Party archive / restore (`PartyRow` in `PartyPages`) | the party list | outcome dropped; archived row's state shown stale; failed read → error screen | outcome returned; list kept; row held; page announces when the list is read (the row may be gone) | `App.parties.test.tsx` |
| 4 | Party member end (`MemberTable` in `PartyMembersPage`) | the roster (party version) | same | outcome returned; roster kept; end and add held (party version); notice; recovery | `App.partyMembers.test.tsx` |
| 5 | Party member add (`AddMemberForm`) | the roster | same | same; **uncertain retry** keeps body and key | `App.partyMembers.test.tsx` (confirmed + failed read; lost answer then retry) |
| 6 | NPC portrayal save new version (`NpcPortrayalPage`) | the portrayal (versions) | outcome dropped; "not found" screen on a failed read; form re-keyed | outcome; portrayal kept; draft kept; both portrayal writes held; page announces on recovery (form is re-keyed) | `App.npcPortrayal.test.tsx` |
| 7 | NPC detail level | same | same | same | `App.npcPortrayal.test.tsx` |
| 8 | Character starting state (`StateSection`) | the builds listing | outcome dropped; error screen | outcome; listing kept; form held until read | `App.characterBuilds.test.tsx` |
| 9 | Activate a build (`BuildList`) | the builds listing | same | outcome; held (names the active build it showed) | `App.characterBuilds.test.tsx` |
| 10 | Event void / correct (`Corrections` in `EventPages`) | the event **and** the correction preview | two awaits, both outcomes dropped; "does not exist" screen on a failed read | both reads combined; both kept; actions held; page announces on recovery (the form is replaced by the correction) | `App.eventCorrections.test.tsx` (event read fails; preview-only fails) |
| 11 | World Sharing: assign / end role, grant / revoke use, transfer ownership (`WorldSharingPage`) | the access list | outcome dropped; any failed read → "Sharing is not available" | outcome; list kept; controls held; transfer's **denied** read is an authoritative answer (removes the content, focus to heading, "Ownership transferred" still announced) | `pages/WorldSharingPage.test.tsx` |
| 12 | Session Start (`StartControl`, `SessionRunPage`) | the session (version) | `await refetch()`; "Session started" and the log link shown after a failed read | not done until read; Start held; page announces and shows the link when the session is read | `App.sessionRun.test.tsx` |
| 13 | Session End (`EndControl`) | the session | same | same | `App.sessionRun.test.tsx` |
| 14 | Session log entry (`LogSection`) | the session | returned the outcome but showed no notice and never announced on recovery | notice beside the form; recovery announces | `App.sessionRun.test.tsx` |
| 15 | Travel (`TravelSection`) | the session's travel history | outcome dropped; "do not record again" only when the page was already stale | outcome; saved notice (receipt text) with read-only retry; a journey that moved no one reads nothing (intentional) | `components/TravelSection.test.tsx` (failed; superseded) |
| 16 | Campaign clock advance / correct (`CampaignClockCard`) | the clock (version, last event) | outcome dropped; card vanished on a failed read | outcome; clock kept; Advance/Correct held; notice | `components/CampaignClockCard.test.tsx` |
| 17 | Session details save (`SessionDetailPage`) | the session | "Session saved" announced after a failed read; Save not held; **Load latest** reset the stale notice even when its read failed | announced only when read; Save held until **Reload session**; stale reset only on success | `App.sessionAuthoring.test.tsx` |
| 18 | Session archive / restore (`SessionLifecycleControls`) | the session | outcome dropped | outcome; notice with read-only **Load latest** (no page retry exists); actions held | `App.sessionAuthoring.test.tsx` |
| 19 | Encounter commands: update, add / change / remove participant, start, abort, record turn, end (`PreparedEncounterPage`) | the encounter | outcome dropped; "does not exist" screen on a failed read | outcome; encounter kept; every command held (a turn could be recorded twice from the old view); page announces on recovery | `pages/EncounterPages.test.tsx` (start; turn) |
| 20 | NPC runtime: hit points, conditions, resources, move (`NpcRuntimePanel`) | the character | outcome dropped | outcome; panel keeps the numbers it read; all four held (they are deltas); notice | `components/NpcRuntimePanel.test.tsx`; `WorldRecordWorkspace.runtime.test.tsx` |
| 21 | Dungeon / area commands via `useDungeonCommand` (Areas, Connections, Contents, Area now) | the dungeon or area, its lifecycle and revisions (+ the record for Area now) | `reload()` returned nothing; `await refetch()` dropped; commands could repeat from a stale version | `reload()` returns an outcome (`usePairedRead`, `useAreaRuntimeRead`); the workspace's refresh functions combine only the reads that record makes; handle exposes `savedNotice` (rendered outside the form that closes) and holds commands; `clear()` no longer lifts the hold | `WorldRecordWorkspace.areaNow.test.tsx` |
| 22 | Lifecycle steps (`EntityLifecyclePanel` provider: World record, Item, Quest; Claim keeps its own page notice via `pageReportsRefresh`) | the lifecycle **and** the page's reads | the lifecycle read's outcome was dropped; Quest and Item `onChanged` returned nothing | combined; "done" only on `ok`; saved notice beside the actions; steps held; recovered when the lifecycle read works again | `WorldRecordWorkspace.test.tsx`; `QuestWorkspace.test.tsx` |
| 23 | Relationship add (`RelationshipsPanel`) and edit / perspectives / end / archive (`RelationshipEditor`) | the roster list and the relationship | decided "refreshed" from a shared ref (`refreshOk`), which a superseded read leaves untouched; reported `success` to the mutation | decided from the returned outcomes; mutation reports `confirmed`; a form whose relationship read failed holds its version-checked save | `components/RelationshipsPanel.test.tsx` |
| 24 | Organization: add member, set status, member editor (`OrganizationMembers`, `OrganizationMemberEditor`) | the roster | `void refetch()`; "Member added" / "Organization status saved" announced immediately | roster read awaited; announced only when read; roster-level saved notice (forms close); status and add held | `components/OrganizationMembers.test.tsx`; `WorldRecordWorkspace.runtime.test.tsx` |
| 25 | World time recorded inline (`WorldTimePicker`, used by party, session, clock, event and organization forms) | the world-time list | `refetch().then(...)` selected the id regardless; a failed read replaced the picker by an error | picker kept; new time chosen only once the list shows it; record-again held; read-only **Load latest** | `components/authoring/WorldTimePicker.test.tsx` |
| 26 | World time recorded (`WorldTimesPage`) | the list | announced "World time recorded" regardless; error screen | outcome; list kept; notice | `pages/WorldTimesPage.test.tsx` |

### 4.2 Compliant (reference implementations; not changed)

| Operation | Why it is compliant |
|---|---|
| Quest commands, details, structure editor, dependencies / outcomes / participants, progress (`useQuestCommand`, `QuestDetailsSection`, `QuestEditor`, `QuestProgressPanel`) | CP-10: return the (combined) outcome; announce on `ok` only; page-level kept data and retry |
| Item operations and item definition edit (`useItemOperation`, `ItemDefinitionPages`) | CP-10 |
| Knowledge claim save, audience, lifecycle read-back (`KnowledgeClaimPage`, `KnowledgeRoster`) | CP-10 (+ review follow-ups). Only the lifecycle provider's `refetch` now returns its outcome and the page passes `pageReportsRefresh`, so the panel does not add a second notice |
| Entity sources attach / detach (`EntitySourcesSection`) | CP-10 |
| Campaign settings save and archive; archived campaigns reactivation; shared content edit page | CP-2 |
| Session participants add / remove (`ParticipantForm`, `Participants`) | CP-2 (receipt-version gating) |
| Award item (`AwardItemSection`) | CP-2 |
| Campaign startup preference (`useSaveCampaignStartupPreference`) | returns outcomes already |
| Campaign setup (`CampaignSetupPage`) | waits for the authoritative bootstrap to list the campaign before navigating |

### 4.3 Compliant by design (navigate away, close, or intentionally need no reread)

Create-and-open and edit-and-return forms navigate to a destination that loads its own data, so there is no read-back to drop: `CreateWorldPage`, `EditWorldPage`, `CreateTimelinePage`, `EditTimelinePage`, `CreateTimelineBranchPage`, `ContentCreatePage`, `SessionFormPages` (schedule), `CalendarCreation`, `PartyForm` (create / edit), `RecordEventPage`, `CreateCharacterBuildPage` (`BuildForm`), `PrepareEncounterPage` (announces on the destination). `TravelSection` with `changed:false` records nothing and reads nothing.

### 4.4 Retained difference — "reload through the loading state" family (not changed)

The Phase 13 access, invitation, account, session-revocation and onboarding hooks (`useAccessOverview`, `useCampaignInvitations`, `usePlatformAccounts`, `useOwnSessions`, `useCampaignSession` boundaries, and the `Add/Change/Revoke…` mutation hooks such as `useAddCampaignMember`, `useAssignMembershipRole`, `useAddResourceGrant`, `useCreateAccessGroup`) do not keep a stale view after a write: their `retry()` increments a request version, the next render falls back to the **loading** state, and a failed read shows an explicit error page with **Try again**. No stale record is ever shown as current, so the DEF-001 harm ("done" while the screen is behind) cannot occur; the persistent status line ("Role added.") is true of the write. Changing this family would be a redesign of the 13E/13F pages, not a DEF-001 fix. **Reported as an assessed, unchanged family for Codex review**; a different decision (announce only after the reload) would be a separate change.

## 5. Intentional domain differences kept

- Row-version scopes (`StartControl`, `EndControl`, party row, session lifecycle) let the mutation's own status end with the record's version; callers that must outlive the version change (`TransitionControls`, `EntityLifecyclePanel`, `OrganizationMembers`, `WorldTimePicker`, `WorldTimesPage`) keep the unread write in component state and feed `useConfirmedRefresh` a synthetic `confirmed` status.
- Where the form that sent a write is replaced or removed by the recovered read (archived party row, started session, re-keyed portrayal, voided event) the **page** announces the write (`useAnnounceWhenRead`); the component announces only for its own **Load latest**.
- A denied/unavailable read-back is an authoritative answer (World Sharing after transfer; permission loss in the World workspace): the retained content is removed, nothing is held, and the write is still announced.
- Boundary-reload pages (§4.4), create/edit navigation (§4.3), and `Claim` lifecycle (page-level notice) keep their own shape.
- Wording is per domain ("party list", "campaign time", "world times"); no universal workspace framework was added.

## 6. Tests and results

Recorded in §5 of [PHASE14_15_DEFECT_REGISTER.md](PHASE14_15_DEFECT_REGISTER.md) (final numbers) so there is one place to update.

New / extended regression tests (all assert *write once, read fails, no "done" announcement, held, read-only recovery, one write*): `hooks/useConfirmedRefresh.test.tsx` (retry reads only; failed, superseded and throwing reads; component gone while a read is in flight; sticky recovery; deferred announcement), plus the per-operation tests named in §4.1. Against the **pre-change** source the 33 new or tightened tests fail and the 543 other tests in the same 22 files pass (verified by stashing only the non-test source).

## 7. Known limits

- Browser behaviour was **not** exercised (no browser or database mutation was performed in this work): the automated tests use jsdom with a mocked `fetch`. RC-10 and the rows in the register's "Affected coverage" are the human/scripted verification.
- Where a superseded read is reported (`RelationshipEditor`, `WorldTimePicker`) the conservative note stays until the next write or **Load latest**; it never claims a refresh that did not happen.
- Duplicated sentences are possible while a page is stale (the page's "may be out of date" notice and the operation's quiet "saved" notice). This matches the CP-10 reference callers (Run Session participants).

# Outstanding work and finding traceability

Reconciled 2026-11-08 from the recorded documentation at `53416d5`. This is a work
register, not a new severity assessment or permission to implement every proposal.
[PLANv2](PLANv2.md) owns delivery order; the [defect register](PHASE14_15_DEFECT_REGISTER.md)
owns DEF dispositions; the [ledger](PHASE14_15_ACCEPTANCE_LEDGER.md) owns acceptance.
Do not convert an old observation into a current defect without checking the current code.

## Current package disposition

| Work | Recorded state / next obligation |
|---|---|
| Batch 1 / P01 / P07 pilots | Encounter audience, item-save feedback and time-dialog repairs have implementation/review evidence in the ledger; broader shared adoption and integrated acceptance remain. |
| DEF-007 | Effective-time membership repair is implemented in the recorded handoff; integrated acceptance and related travel-time policy remain. The old plan-only heading is historical. |
| P02 | Owner-accepted at `81bf164`; browser follow-ups B9/B16/B20 and deferred B21 remain. This does not accept Phase 14/15. |
| P03-A | Active; use its latest implementation/review entry, not the older investigation's “not started” statement. Preserve D6/A4 and DEF-019/020/021, stale authorization, A1 wait-observation flake, and final-head CI obligations unless a later record closes them. |
| P03-B/C and R19 | Actor identity/control and rules foundations remain governed by accepted ADRs 0021–0023 and the R19 coordination/implementation gates. |
| P04–P17 | Carry the finding/package scopes below; completion must be linked to actual implementation and acceptance evidence. No blanket closure is recorded here. |
| Foundry / AI exit evidence | Licensed live Foundry v13 acceptance and a real-provider AI smoke/Phase 12 closure record remain due. |

## Original 43 app-interaction findings

The following rows retain the 2026-11-01 investigation's source observations and acceptance
targets. Source line numbers describe that baseline. They are a requirements crosswalk;
use the disposition table above and linked defect/implementation records for present status.

## C. Finding-by-finding traceability

Classification: **D** reported defect, **S** standardization, **E** enhancement; combinations are deliberate. Scope: **existing** = repair an advertised Phase 14/15 workflow; **standard** = requested app-wide interaction change; **new** = additional capability needing scope assignment. Packages P00–P17 are specified in F. File names here resolve to full source paths in D/E; references include current line anchors for the decisive evidence.

| ID | Class / scope | Source-supported behavior, likely cause and confidence | Key code and affected layers | Dependencies / package | Acceptance target |
|---|---|---|---|---|---|
| U01 | S / standard | S: account row prints role codes, then a role editor with its own heading. Redundancy confirmed, high. | `AdminAccountsPage.tsx:127`, `SystemRolesEditor.tsx:27`; portal. | D3; P05 | One role heading/grid; role status remains understandable without color. |
| U02 | S / standard | S: `ADMIN_NOTE` repeats in each editor. Policy text must distinguish grant from revoke; high. | `SystemRolesEditor.tsx:14,47`; portal + policy copy. | U04; P05 | One explanation near the group; no false blanket claim of immutable Administrator. |
| U03 | D/S / existing + standard | S: checkbox writes immediately; success refresh changes accounts state and removes the table. Strong remount/scroll explanation, high; exact scroll needs browser check. | `AdminAccountsPage.tsx:82`, `useSystemRoleChange.ts:55`; portal hooks; role APIs. | P00/P01; P05 | Stage changes, Save/Cancel, preserve row focus/search/scroll; report partial or uncertain results honestly. |
| U04 | D/S / existing | S: unchecked admin is disabled when grant flag is off; checked admin can be revoked. Backend protects last active admin. Apparent contradiction is policy-sensitive, high. | `SystemRolesEditor.tsx:32–40`; `local_auth.py:996,1046`; `system_roles.py:90,128`. | U02; P05 | Server-derived allowed actions; correctly explain disabled grant and protected revoke. |
| U05 | S / standard | S: inline CreateAccountPanel is mounted above account list. Dedicated route is a portal change; high. | `AdminAccountsPage.tsx:51`, `App.tsx:239`; existing create API `local_auth.py:936`. | P02; P05 | New user breadcrumb, direct-entry Back, dirty Cancel, list state restored; no credential persistence in navigation. |
| U06 | S / standard | S: bare label/input presentation differs from authoring fields. High. | `AdminAccountsPage.tsx:63`; shared authoring fields/CSS. | P01; P05 | Consistent label spacing, zoom/reflow and accessible name. |
| I01 | D/S / existing + standard | S: native disabled placeholder option; no decisive hover override found. Browser/theme/disabled-state explanation unconfirmed, low. | `HierarchyContextPanel.tsx:38–69`, `App.css:1309–1328`; portal/CSS. | P00 browser probe; P02/P08 | Reproduce with browser/OS/theme; stable normal/hover/focus/disabled appearance without concealing focus. |
| W01 | S/E / new | S: Sharing uses typed login; eligible campaign lookup is exact-match by privacy design and wrong scope for world sharing. New bounded search contract required, high. | `WorldSharingPage.tsx:313`, `useEligibleAccountLookup.ts:37`, `access_overview.py:439`; portal/API/query/policy. | D3, H decision; P06 | Authorized, debounced, bounded eligible search; no unauthorized account enumeration; mutation rechecks. |
| W02 | S / standard | S: dedicated Sharing page already exists with grant/use/transfer sections. Need contained task panels, not another page framework; high. | `WorldSharingPage.tsx`, `ConfirmDialog.tsx`; existing world role/use/transfer commands. | P01/P02; P06 | Focused grant/host panels; explicit ownership confirmation; preserve receipt after refresh/permission loss. |
| W03 | S / standard | S: active/archived select sends one status, so archived excludes active. Backend supports all; high. | `WorldsPage.tsx:13,76`, worlds list API; portal filter. | P02; P08 | Checkbox off=active, on=active+archived; restore filter in Back/reload; do not alter picker eligibility. |
| C01 | S / standard | S: navigation links are correct semantics but inconsistent presentation/return conventions. High. | campaign setup/details routes, `returnState.ts:28`, `RecordHeader.tsx`; portal. | P02; P08 | Styled Back link with validated destination and direct-entry fallback. |
| C02 | S / standard | S: home/clock/recent-event components exist; layout dissatisfaction is O, not a backend defect. Medium. | `CampaignHomePage.tsx:48`, `HomePage.tsx`, `RecentEventsSection.tsx`; portal. | P01/P04; P08 | Review compact Now/session action/event-rail prototype at narrow/wide sizes; authorized actions only. |
| C03 | D/S / existing | S: Recent Events already renders adapter explanations, but generic event names/limited context can remain indistinguishable. Partial explanation, medium. | `RecentEventsSection.tsx:77`, `event_explanations.py:149`; portal/read DTOs. | E01/E02; P04 | Distinguishable time/type/subject/context for supported families; generic safe fallback; no hidden identifiers. |
| C04 | E/S / new | S: invite create/pending schema has no role; acceptance activates membership only. High. | `campaign_invitations.py` API:75,94; command:265; `security.py:264`; all layers/migration. | E1; P10 | Selected role visible pending; both acceptance paths assign once under current authority; legacy invites remain defined. |
| T01 | S/E / standard; expanded calendars new | S: WorldTimeForm/Picker and parsing utilities already exist. Fixed 24h arithmetic is a backend rule, not just UI. High. | `WorldTimeForm.tsx:119,174`, `domain/world_time.py`; portal/domain. | D4/E2; P07 then P11 | Shared scoped input, explicit precision, no calendar coercion or implicit clock advance. |
| T02 | D / existing | S: `onCancel={() => undefined}` is a confirmed no-op. High. | `WorldTimesPage.tsx:203`; portal only for basic repair. | P01; P07 | Pristine Cancel closes/returns; dirty Cancel guards; no write; focus restored. |
| T03 | E / new | S: after-anchor ordering plus optional upper bound exists; symmetric before mode, duration and stored relative provenance do not. High. | `WorldTimeForm.tsx:214,224`, `commands/world_time.py:164,230`, `domain/world_time.py`; all layers. | E2/H; P11 | Exact or explicitly uncertain preview, validated same-world anchor, atomic allocation, preserved provenance and legacy sort keys. |
| N01 | S / standard | S: Campaign main link always navigates, World toggles, Characters is a campaign destination; hierarchy is route-derived. Proposal changes selection model. High. | `CampaignHomeNavGroup.tsx:128`, `WorldsNavGroup.tsx:145`, `PortalSidebar.tsx:47`; shell/state. | D1; P02 | Exact selected-entity behavior table in D1 for all three roots. |
| N02 | S / standard | S: independent link/disclosure exists for Campaign but not proposed conditional main action; fallback campaign resolution may guess. High. | `CampaignHomeNavGroup.tsx:146`, `PortalSidebar.tsx:184`; shell/state. | N01/N07; P02 | Same section or no selection expands; opening menu never discards input; touch and keyboard parity. |
| N03 | D/S / existing + standard | S: character sheet and World record editor use different shells/breadcrumbs; subviews keep a title but not full common summary. High. | `CharacterRecordNav.tsx:128,146`, `CampaignWorldDetailPage.tsx:58,160`; portal routes/shell. | P02/P03; D6 public-profile contract | Persistent permitted header/nav under every entry route; do not populate public summary with legacy background. |
| N04 | D/S / existing | S: ChooseCharacterTypePage renders heading and choices with no breadcrumb and drops return context. High. | `NpcAuthoringPages.tsx:442–457`, `App.tsx:340`; portal. | P02; P03 | Characters > New character, preserved origin into subtype create, success replaces leaf. |
| N05 | D/S / existing + standard | S: Parties list explicitly links Campaign Home; URL containment is being used as task ancestry. High. | `PartyPages.tsx:66`, `PartyDetailPage.tsx:27`; portal. | P02; P03 | Parties-origin task remains Parties > party > members/character; direct link has useful fallback. |
| E01 | D / existing; new safe field if wanted | S: membership reason is stored as joined/left reason and classified GM_ONLY; event adapter projects structured subjects but not reason. No evidence of lost persistence. High. | `party_members.py:126,181`, `data_classification.py:122`, `event_explanations.py:315`; all layers if member-safe prose added. | D5/H; P04 | GM sees authorized reason; members receive only explicitly safe explanation/structure; never raw audit text. |
| N06 | D/S / existing | S: character editor/view branches and can-edit section filtering yield different navigation from alternate entry routes. High. | `CampaignWorldDetailPage.tsx:58,160`, `CharacterRecordNav.tsx:62–100`; portal + capability DTO use. | A01/P02/P03; P03-B for player actions | Same eligible local views for same actor and authority; controller play must not require canonical-edit UI. |
| E02 | D / existing | S/T: current World event page renders status/details fallback and What happened; existing tests pass. Literal blank not explained by available source, low. | `WorldEventDetailPage.tsx:44–65`, `EventPages.tsx:350`; portal/read DTO. | P00 probe/P04 | Capture exact entry route/payload/persona; loading/error/no-details/unsupported-family all visibly distinct. |
| S01 | S / standard | S: session staged layout contains constrained authoring forms; wide panel CSS already exists. Exact cramped view needs visual check, medium. | `SessionRunPage.tsx:355,688`, `App.css:3660`; portal layout. | P01/P02; P09 | Main-workspace edit width, session origin, keyboard/zoom; do not invent editability of immutable log events. |
| S02 | S / standard | S: portal defaults started-at descending; API returns session-number descending and currently all rows. High. | `SessionsPage.tsx:141`, `queries/session.py:114–139`; portal, future API pagination contract. | P08 | Scheduled ascending, unscheduled last, stable sequence/id tie; explicit user sort preserved. |
| S03 | D / existing | S: link sets log section query; log may already be selected, so section-change focus hook does not fire. Plausible explanation, medium. | `SessionRunPage.tsx:373`, `useRunNavigation.ts:41`, `useFocusOnSectionChange.ts`; portal. | P01/P09 | Link from other section navigates; same-section action focuses/scrolls actual log heading/editor visibly. |
| A01 | D/E / existing usability + new inspection choice | S: bootstrap perspectives come from per-character relationship capabilities, not all characters a GM can read. Not simply PC ownership. High. | `queries/bootstrap.py:359–370`, `api/characters.py:420–508`; portal/API/policy. | D2/D6, DEF-007; P03/P03-A | Separate GM inspection, public profile, control and knowledge perspective; campaign eligibility and denies agree across all projections. |
| A02 | D/E / existing | S: browse party choice derives from character perspective; runtime progress already includes every active campaign party. Exact failing surface must be identified, medium. | `useQuestPartyPerspective.ts`, `queries/quest_runtime.py:104`, `QuestProgressPanel.tsx:186`; portal/read policy. | D2/DEF-007; P03 | GM can choose all eligible operation scopes; player perspective remains constrained; no world-wide party list. |
| Q01 | E / new | S: types are DB lookup values; `other` already exists; type selection is not an evaluator. High. | `domain/quest_authoring.py:13,102`, `queries/quest_authoring.py:135`, `quest_definitions.py:138`; E3. | H; P12 | Manual custom intent or one specified mechanic has explicit scope; unknown types rejected; existing progress preserved. |
| Q02 | S / standard | S: Edit/Remove already are separate buttons, but actions live inside expanded content. Layout/disclosure change, not missing command. High. | `QuestEditor.tsx:658–727`; portal. | P01; P12 | Independent disclosure/action region; no accidental toggle or remove; focus retained. |
| Q03 | S/E / standard + new persisted consequences | S: definitions have outcomes/rewards; runtime status command has no outcome selection/reward application. High. | `QuestCompletionSections.tsx`, `QuestProgressPanel.tsx:128`, `api/quest_runtime.py:51`, `commands/quest_runtime.py:161`; E4. | P01/P03/P12; P13 | Scope/objective/outcome review with accurate consequence preview, receipt/history; no fictitious automatic rewards. |
| K01 | D/E / existing author usability | S: active Knowledge browse can include noncanon when ground-truth/lifecycle permissions allow; archive is separately guarded. Need explicit authoring view/filter, not blanket backend bypass. High on support, medium on symptom. | `api/knowledge.py:534,696,846`, `queries/entity_lifecycle.py:52`; portal/query/API as needed. | D2; P14 | Eligible draft/review states outside Review; campaign-only GM/readers remain denied as appropriate; counts/detail/preview agree. |
| D01 | D/S / existing usability | S: create sends name/type only; API already accepts summary, dimensions, environment. These are sufficient for initial expanded create. High. | `DungeonAreasSection.tsx:83,149`, `api/dungeon_authoring.py:116`, `tables/locations.py:131`; portal. | P01; P08 | Supported scalar fields round-trip; child features/hazards/connections remain separate commands. |
| M01 | D/S / existing | S: successful edit refetches then announces through hidden live region; no equivalent visible success. High. | `ItemDefinitionPages.tsx:282–299`, `AnnouncerProvider.tsx:25`; portal. | D3; P01 | Visible saved state, updated baseline/version; saved-but-read-failed and unknown write are distinct; no duplicate POST. |
| G01 | S / standard | S: header is flex but not sticky; sidebar/context have sticky behavior. High. | `App.css:27–36,510,1470`; app shell. | P02; P08 | Persistent responsive header, no covered headings/dialogs/focus at 200–400% zoom. |
| G02 | D/S / existing + standard | S/T: shared mapped errors and recovery exist but adoption differs, especially older admin hooks. No blanket claim that all errors are broken. High. | `feedback.tsx:161–311`, `useAuthoringMutation.ts`, `useConfirmedRefresh.tsx`; all mutation callers. | D3; P01 and each migration | Local actionable error + summary/announcement; retain allowed input; proper conflict/auth/unknown/confirmed handling. |
| T04 | S / standard | S: World times always shows inline form; dialog primitives already exist. High. | `WorldTimesPage.tsx:187`, `WorldTimeForm.tsx`, `ConfirmDialog.tsx`; portal. | T02/P01; P07 | Record-time dialog with dirty close/Cancel/Escape rules, focus return, saved receipt and fresh picker selection. |
| S04 | E / new | S: events/travel/encounters have session relationships, but no general quest/dungeon link model. Quest runtime has composite scope. High. | `queries/session.py:167`, `tables/encounters.py:48`, `commands/dungeon_state.py:204`, E5; all layers. | P02/P03-A/P13; P15 then P16; P03-B for controller actions | Reuse runtime state; linking grants neither revelation nor control; historical participant role is not present control. |
| S05 | E / new | S: session roster is projected; the original report alleged encounter detail was not audience-filtered, including participant IDs and turn notes. That direct-read claim is superseded by the 2026-11-06 source/test review in D6.4; the owner-approved `active_encounter_id` discovery and same-campaign check remains implementation work. General backlinks absent. High. | `queries/session.py:306`, `api/encounters.py:415–456`; API/query/portal/privacy. | D6 projection repair/P03-A; S04/E5/P16 | Intersection of session/link/target rights across direct and indirect reads; retain direct encounter filtering and implement the owner-approved `active_encounter_id` policy before broad member links. |
| L01 | S/E / standard + bounded browse extension | S: detail has containment breadcrumbs and authoring parent references; world browse remains category list. High. | `WorldLocationDetailPage.tsx:73`, world explorer/location authoring APIs; portal + child query if needed. | P02; P14 | Scoped hierarchy with safe parent/children, lazy loading, expansion/search return; no hidden ancestor leakage. |
| N07 | S / standard | S: only domain return helpers exist; route-derived hierarchy cannot retain independent Navbar origin/context. High. | `WorkspaceHierarchyProvider.tsx:23–29,100`, `returnState.ts:9,28`; shell/router. | D1; P00/P02 | Validated bounded task origin; only accepted explicit selection resets; refresh/same selection preserves task. |


## Remaining package requirements

These are the carried requirements from the 2026-11-02 handoff. Current P02 implementation
supersedes instructions to build its navigation foundation again. Source and approval
history remain available in DELIVERY_HISTORY.

## 7. Remaining manual-finding work by package

### P01 — shared authoring feedback and errors

The item-definition and time-dialog pilots are reviewed; adoption across the app remains. Use the existing authoring/recovery hooks, not another parallel framework. Standardize visible success, one appropriate announcement, retained input/focus, validation summaries and noticeable errors. Distinguish rejected writes, unknown outcomes and confirmed writes whose follow-up read failed. Read recovery must not repeat a write; unknown retries retain the original key/body. Audit confirmed-but-unread holds and navigation ownership at each adoption.

### P04 — event summaries and explanations

Campaign event tiles need enough authorized information to distinguish events: meaningful type/title, time, involved readable entities, session and correction/supersession state where available. Reuse a member-safe projection for tiles and overview.

Party membership reasons already exist but are GM-only, rather than simply being lost. Do not expose them indiscriminately to satisfy the missing-description report. Present appropriate GM details and, if needed, introduce an explicitly authored member-safe explanation. No automatic backfill from secrets/audit text. Reproduce the blank Event overview before assigning a fix; “no data” and a broken projection require different remedies.

### P05 — Platform Users

Remove redundant role presentation, explain system-admin assignment policy, add spacing to search controls and move New user to its own page. Stage per-account role edits with Save/Cancel to avoid refresh/scroll jumps on every checkbox. Respect what the backend actually allows: a control that cannot grant admin should be accurately disabled/explained, while supported revocation and last-active-admin protection must remain correct.

Existing per-role endpoints are not an atomic multi-role transaction. Either report partial/unknown results honestly or separately design an atomic operation; do not label a sequence of requests atomic. Account activation/reset uses the supported flow, not administrator-selected passwords.

### P06 — Worlds sharing

Authorized, bounded live user search should replace exact login entry where appropriate. Avoid creating a global user/email directory through autocomplete. Separate Add role/user, allow host and ownership transfer into clear panels/pages with explicit scope, validation and recovery. World access, campaign membership and system roles stay distinct. Ownership transfer needs its own concrete safeguards and accurate outcome feedback.

### P08 — smaller layout/form/list repairs

- Worlds: Show archived as a checkbox while preserving the intended active/archived union.
- Campaign creation/details: consistent Back control; migrate with P02-7e.
- Campaign Home: cleaner layout, clear campaign Now and readable event rail; coordinate event content with P04.
- Session lists: ascending planned order with explicit null/tie behavior, using the actual planned timestamp, not an invented in-world sort.
- Dungeon areas: expose available writable summary/dimensions/environment fields, with existing validation. Do not expose persistence/internal identifiers as form inputs.
- Persistent header: retain usability at narrow widths and 200%/400% zoom; never obscure focused content.
- Search/label spacing and objective action alignment can be small bounded UI checkpoints.

### P09 — Run session usability

Use the available screen width for editing without compromising narrow layouts. Reproduce “Go to session log” against the actual section/scroll/focus state; a click that targets the already selected section may need explicit focus/scroll handling. Do not create an editable history log merely to fix navigation. Preserve current run-session and authoring ownership while changing layout.

### P10 — role selected with campaign invitation

Carry the chosen campaign role through invitation creation and every acceptance path, including existing-user and activation/new-user flows. Define allowed roles and inviter authority server-side. This is campaign role selection, not system-role or world-role assignment. Plan persistence/API changes rather than adding a frontend select whose value is discarded.

### P11 — richer calendar/date/time component and relative times

The shared picker/dialog groundwork exists, but expanded calendar/date/time entry and “how long before/after” remain. Distinguish ordering a moment before/after an anchor from adding actual elapsed time. The existing sort-key allocator is not a duration calculation.

Start with explicitly supported fixed-duration units such as minutes/hours/days under the actual calendar model. Do not assume month/year arithmetic or variable day lengths without a policy. Preserve uncertainty/precision and provenance; do not invent exact dates from narrative anchors. Immutable time keys and concurrent preview/commit behavior need server validation. Recording a time still must not set campaign Now.

### P12 — quest objective types and controls

Move Edit/Remove out of the expanded objective's main content/action collision. Separate adding an author-defined manual objective category from implementing a new automatic evaluator. Existing flags do not establish automatic tracking exists. Specify type validation, display, completion semantics, compatibility and allowed actors before introducing executable objective behavior.

### P13 — guided quest outcome/review

Refactor the existing workflow into clearer steps using actual quest/timeline/party-or-campaign state. Do not invent a runtime instance ID or imply authored outcome text already executes rewards. A first guided version can use existing commands with honest per-write status; Cancel cannot roll back already confirmed steps. An atomic consequences/rewards engine is a separate domain/API change and requires its own plan and review.

### P14 — unpublished Knowledge and location hierarchy

Add authorized author browsing of unpublished Knowledge outside Review. Preserve publication/discovery and the compound campaign/world authoring rules; GM status alone does not make all world content editable. Normal member lists remain filtered.

Locations need authorized parent/child navigation, useful paths/search and safe reparenting. Hidden ancestors must not leak through names, path fragments or counts. This is a containment browser, distinct from the P02 task breadcrumb. Align the World-page slice with P02-7d rather than building two competing breadcrumb systems.

### P15/P16 — session as an operational hub

Attach existing quests, dungeons, encounters and other supported entities as typed session references; do not duplicate their runtime state. Decide cardinality, ordering, removal and link ownership explicitly. Start with GM preparation; then add operational navigation and player-facing session links/backlinks.

Player access must be the intersection of session permission, link visibility and target permission/discovery. Attaching a secret dungeon or quest must not reveal it. Filter hidden IDs/names/counts. Existing encounter execution-session references must not be reassigned just to make a later session link work; distinguish preparation/reference from execution provenance. This is a larger enhancement and should have its own approved bounded plan.

### P17 — final guide and acceptance

Update the First Campaign guide, UI standards and coverage map to match implemented behavior. Repeat affected workflows and the guide's full acceptance sequence on the integrated build, including a clean-install path where required. Never repair acceptance data with ad hoc SQL and then claim the UI passed. Document any fixture-only changes separately from product behavior.

## 8. Other explicit follow-ups

| Follow-up | Context and required next step |
|---|---|
| DEF-007 integrated acceptance | Half-open membership includes join/excludes leave. Root no-clock means **undetermined** and no party-derived access. Independent GM/public/character/grant authority remains. Branch clocks inherit/cap; membership rows do not inherit. Exercise all affected readers and selectors, not only roster grouping. |
| U1 temporal travel policy | Current command and preview use open-ended memberships, not effective membership at campaign/travel time. Future-open included; finite-current excluded. Decide which time should govern travel, then change command+preview together. Current “Travel candidates” wording is intentional. |
| DEF-009 adjacent references | Review sync-state `target_encounter_id` and character-detail `active_encounter_id`. Dungeon-area location follows World Explorer discovery, not campaign dungeon discovery; keep that scoped limitation explicit until policy changes. Do not extrapolate a new filter for world-time/ruleset spell IDs without a contract. |
| Recovery episode map | Current map clears at 32 entries, potentially permitting a revisited episode to refresh again. No normal-flow loop was demonstrated. Plan bounded eviction without invalidating active ownership if addressing it. |
| Knowledge post-save reread | Its in-place 404 path bypasses party recovery and can replace saved-but-unrefreshed feedback with unavailable. It fails closed but loses confirmation context. Correct with explicit confirmed-write ownership, not broadened fallback. |
| Startup-preference stale notice | A later independent refresh can confirm the saved value while local “saved but unconfirmed” remains. Clear only when authoritative matching evidence exists, preserving newer drafts and never repeating PUT. |
| Single-router assumption | `navigationHolds` is module-global and documented for one router/document. Current entry uses one router. If multiple simultaneous routers become supported, scope holds/guards and add isolation tests. |
| Infobox explicit-world pagination (deferred by owner, 2026-11-11) | The hierarchy panel reads only the first 100 explicit worlds (`GET /worlds?status=all&limit=100`, the API maximum) and ignores `next_cursor`, so further worlds are not offered in its World level; All Worlds paginates and the current world stays shown display-only. Graded Low (3) in the [context-navigation correction plan](PHASE15_CONTEXT_NAVIGATION_CORRECTION_PLAN_2026-11-11.md#2-findings-and-grading). A follow-up needs a pagination-or-search design for the select, applying the same reconciliation rules (UI_DESIGN §4.8.12); it is not part of that correction. |
| Unreproduced I01/E02/S03/A02 | Timeline placeholder hover, Event overview, Go to session log and GM Quest-party availability need real runtime steps/evidence. Do not mark fixed from static suspicion alone. |


## Integration decisions and deferred scope

The DR rows preserve the original proposal/decision questions. The historical column
“Recommended” is not independent approval. DR-7 defaults were accepted as a set on
2026-10-24; recorded implementation is in the access reference. Other dispositions must
be read with the relevant ledger/defect entry. DR-8 substitutions and DR-9 acceptance of
remaining Medium risks still require their own explicit evidence/decision.

| DR | Decision | Current rule | Recommended | Implementation impact | Blocks |
|---|---|---|---|---|---|
| DR-1 | Archived historical references | §3.3: published-history definitions readable by reference in any lifecycle except deleted; guide TC-10/31 expect member denial | Keep §3.3; correct the guide | Guide amendment only; strict denial would need a policy change across every reference projection | CP-7 acceptance; TC-10/31 |
| DR-2 | Viewer inventory | Viewer = discover + summary; inventory needs full tier | New `character.view_inventory`; default for `viewer` and `observer_approved_viewer` (and listed for owner/controllers/portrayer for explicitness); not `former_controller`; explicit deny of the capability wins over full tier; restricted projection | Migration 139, matrix, resolver, projection, access UI label | CP-6 |
| DR-3 | Member session roster | Members get no roster | Discoverable participants only; no counts/placeholders for hidden | API member branch | CP-8 |
| DR-4 | Clock cause / explanation | Advance links only the previous clock event | Optional validated non-clock cause event + optional member-safe explanation in event `details`; admin reason stays in audit; manual advance shown as such; no schema unless chain/cause cannot be distinguished by cause event type | Command/API/form | CP-9b |
| DR-5 | Archive-browse eligibility (and Archived/All semantics) | No one can browse archives | Baseline campaign `canon.edit` ∧ `world.canon.read_private`; Archived = archived, All adds superseded/deprecated; drafts excluded; ineligible explicit parameter → 403. Alternative: let campaign-only GMs browse archived *published* claims | API eligibility | CP-7 |
| DR-6 | Build values in event explanations | n/a (ids only today) | Build labels to readers with full tier for that character (and GM); others see "build changed" | Explanation adapter | CP-9a |
| DR-7 | Scoped-role defaults (Q2, Q5, Q8, Q11, Q12, Q13, E2/E3 lifecycle, Viewer/Reader coexistence) and Q4 interpretation ("no campaign role requires system GM") | Adopted by the branch as defaults | Confirm as a set | None if confirmed; any change alters CP-4 | CP-4 fast-forward (not CP-4 start) |
| DR-8 | Fixture substitutions / variant equivalence | Unrecorded | Record actual values; targeted reruns; owner states whether any existing R operation counts | Ledger only | CP-11 retests of affected cases |
| DR-9 | Release disposition for any remaining Medium defects | Rubric: merge only with explicit evidence-backed risk decision | Fix D1–D7 per this plan; record any exception explicitly | Acceptance record | CP-11 |

---

## 11. Deferred refactoring and why

| Deferred | Why now is wrong | Revisit at |
|---|---|---|
| C9 unify legacy domain API clients (`api/knowledge.ts`, `world.ts`, `character.ts`, `session.ts`) with `api/http.ts` | No defect requires it; broad churn during role integration | Phase 16 when new clients are added; migrate one only while fixing a concrete inconsistency |
| C10 broad splits (QuestEditor, KnowledgeClaimPage, RelationshipsPanel, RelationshipEditor, EncounterPages; backend `access_grants`, `local_auth`, `world_explorer`, `domain/access`) | Size is not a defect; overlap with CP-4 would multiply conflicts | After CP-4/CP-9 reveal stable seams; Phase 16 authoring |
| C4 full staged-navigation/lifecycle-panel unification | Role modes must settle first; risk of collapsing Reviewer into Editor | After CP-4; Phase 16 proposals and Phase 18 change sets reuse navigation, not canon lifecycle semantics |
| C7 picker-state simplification | Display first (CP-9); picker semantics differ per domain | Phase 18 time extraction, Phase 20 scenes |
| Generic roster/member domain | Would merge distinct domains | Not planned |
| World-scoped authoring workspace (Q8) | Deferred by default | Phase 16/17 if owners need world-only authoring |
| Comprehensive World Reader browser | Outside accepted Q7 scope | Separate checkpoint before Phase 17 browser acceptance if wanted |
| Event name snapshots / historical backfill | Unknowable; would invent history | Phase 18 provenance may record names at promotion time going forward |
| `cause_kind` column on `event_causes` | Not needed if cause type disambiguates | Only if DR-4 shows ambiguity |
| Private-collaboration audience channel | Phase 16 domain; must not reuse `canon.edit` or `read_private` | Phase 16C |
| Promotion idempotency/provenance on the same commands | Phase 18 | Phase 18D (benefits from CP-4c eligibility and CP-9 explanations) |
| Build-history presentation beyond activation events | Phase 19 advancement | Phase 19.2 |
| Purpose-specific AI context from audience projections | Phase 20 | Phase 20.2 (consumes CP-4/CP-8/CP-9 projections) |
| Adapter command attribution | Phase 21 | Phase 21 (consumes CP-2 receipt semantics) |
| Windows CRLF frozen-seed failures; intermittent portal timing tests; legacy adapter revocation races | Pre-existing, not production defects under the rubric; harness hardening out of scope | Separate maintenance item |

## Earlier obligations and limitations

- Optional AWS: historical orphaned KMS resource, manual `iam_auth_db_users` drift,
  remote state and a narrower CREATEDB test login need operator reconciliation if that
  environment is used. No AWS resource was inspected or retired by this cleanup.
- Phase 5: creature/spawn modeling follows ADR 0022/R19; confirm knowledge propagation
  and other old schema deferrals against current schema before creating work. The
  proportional test-infrastructure policy is in DEVELOPMENT.
- Read API: session participants/history and item/knowledge limitations in the historical
  13D audit may have been addressed by later authoring. Reconcile against the current
  endpoint before carrying an old scope exclusion forward. Sheet limitations remain
  visible in api/CHARACTER_SHEET.
- Verification strategy still requires meaningful property-based coverage of timeline
  resolution, relationship combinations, event effects, quest dependency graphs and
  world-time ordering, plus measurements of effective-state queries, NPC context,
  dungeon retrieval, session ingestion, knowledge filtering and branches. No completion
  is inferred from a dependency merely being installed.

## September platform-review findings

The 18 finding IDs below identify the original 2026-09-25 review, not fresh reproductions.
Keep unresolved findings visible without importing its old severity labels as a new grading.

| Original ID | Finding | Disposition at documentation cleanup |
|---|---|---|
| 1 | `httpx` missing from production dependencies | Still in dev optional group at `53416d5`; runtime imports exist. Needs production-image validation/correction; not rerun here. |
| 2 | No world-authoring commands | Superseded by Phase 14/15 command delivery. Original scope gap is historical; current authoring acceptance remains separate. |
| 3 | Production operational envelope absent | Phase 17/runbook still owns ingress/TLS/portal/worker/operations acceptance. Base recovery delivery does not close all packaging. |
| 4 | Audit history UI unreachable | Superseded by the Access audit route recorded in AUDIT_HISTORY_API and portal source. No new browser test claimed. |
| 5 | No property-based tests | Reconcile existing tests with the explicit strategy targets; not closed here. |
| 6 | No performance tests | Preserve measurement targets above; not closed here. |
| 7 | No coverage measurement/gate | Reconcile current tooling and warranted policy; a local .coverage file does not establish a CI gate. |
| 8 | No browser E2E suite | Browser boundary evidence remains separate from jsdom. Follow Phase 17 acceptance; not closed by scripted one-off checks. |
| 9 | Tests not type-checked | Review scope/cost under ISSUE_GRADING_RUBRIC; current CI mypy targets src and the CI helper, not all tests. |
| 10 | CI type-checks only one script | Still a limited script scope in CI at baseline; decide proportionate follow-up. |
| 11 | Portal flake under coverage/load | Old reproduction, not proven current cause. Retain alongside later unattributed intermittencies; no passing rerun establishes a cause. |
| 12 | Stale PROJECT_STATUS | Documentation summary replaced by this consolidation; no test results refreshed. |
| 13 | Old PLAN AWS-CI contradiction | Superseded operational prose retired; DEVELOPMENT/ADR 0012 govern CI. |
| 14 | AI feature flag differs from boundary behavior | Reconcile config, route enforcement and feature manifest before any behavior change; not closed here. |
| 15 | Built/planned schema labels mixed | Accepted R19 architecture remains distinct from implemented tables. Review each affected schema entry when implementing it. |
| 16 | Token rules content/creature model | R19/ADRs 0022–0023 own expansion and provenance; acceptance of design is not seed/content delivery. |
| 17 | Conditional migration-test skips | Reconcile actual skip preconditions under current verification policy; not closed here. |
| 18 | Foundry live/AI smoke exit evidence missing | Carried explicitly in PROJECT_STATUS; not executed by cleanup. |

## Untracked planning sources

The Batch 1, DEF-007 and P02 plans were local untracked inputs. Their original bytes are
preserved outside the repository in `C:/Users/nemes/dnd_ai_documentation_sources_20261108/`.
They are not claimed to exist in the historical Git baseline. Approved/current requirements
are represented by the finding crosswalk, current topic contracts, acceptance scenarios,
and original source hash manifest in DELIVERY_HISTORY. The external proposed
`APP_INTERACTION_STANDARDS.md` was not imported or adopted by this cleanup.

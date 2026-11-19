# Outstanding work and finding traceability

Updated 2026-11-18 on `881786c`. Phase 15 remains open. Use [the roadmap](roadmap.md) for the adopted Phase → Checkpoint → Slice → Task sequence. Finding IDs trace work into that sequence. [Defects](defects.md) records defect evidence, and the [acceptance ledger](acceptance-ledger.md) records manual results and decisions.

## Current package disposition

| Work | Current state / next obligation |
|---|---|
| R01 | **Complete** for the owner-accepted backend scope. [Acceptance and separate follow-ups](#r01--runtime-authorization-and-transaction-defects). |
| Batch 1 / P01 / P07 pilots | Encounter audience, item-save feedback and record-time dialogs implemented; shared adoption and integrated/browser/owner acceptance remain. Do not rebuild the pilots. |
| DEF-007 | Shared half-open membership predicate and portal recovery implemented; integrated G4/TC-06/TC-21 and owner acceptance remain. Travel still uses open-ended membership (R04/U1). No-clock policy is already decided. |
| P02 | Owner-accepted at `81bf164`; B9/B16/B20 remain browser follow-ups, B21 is owner-deferred/unverified. |
| Context-navigation correction | CNC-1–3 and owner-evidence/pending-state repairs implemented through `6cdc68b`; review outcome at `bdd541b`: PASS WITH NONBLOCKING VERIFICATION LIMITATION. Browser checks and retained follow-ups remain; see below. |
| P03-A | A0–A4 and P0–P3 implemented and reviewed. A5a and A5b have independent review records, including nonblocking findings. A5c is implemented and its separate review remains outstanding in the [A5 record](player-profile-design.md). No production player-profile writer until P03-B. The DEF-019 prerequisite was closed within its agreed scope. A6 portal work and A7 reconciliation, optional preview and acceptance remain. |
| P03-B/C/S | Ongoing campaign control/bounded player operations, explicit canonical authoring and subtype compatibility, and campaign mechanical-state isolation remain unimplemented under accepted ADR 0021. A4 backend delivery does not complete the character refactor. |
| R19 | ADRs 0021–0023 accepted; implementation and primary-PC coordination gates remain in the [foundation plan](rules-foundations.md). Rules engine, content/provenance, creature templates and later combatant work are not delivered merely by ADR acceptance. |
| P04–P17 | Detailed remaining scope and acceptance in R05–R18 below. Repairs, proposals and acceptance-only obligations are distinguished. |
| Scoped roles and authoring kernel | The scoped-role upgrade was rehearsed on a retained snapshot. Preserve the rehearsal limits in [the deployment runbook](../operations/deployment.md). Phase 14 closed with accepted limitations at PR #64 (merge `3046714`, recorded CI 37227612984). Phase 13 portal/access and Phases 0–10 provide the delivered baseline. |
| Earlier and later phases | Live licensed Foundry v13 acceptance and real-provider AI smoke/Phase 12 closure remain due. Phases 16–22 remain roadmap work; Phase 16 delivery waits for Phase 15. The [roadmap overlap provision](roadmap.md#6-dependency-order) and checkpoint 31 start gate must be reconciled before scheduling a specific Phase 16 slice early. Phase 17 still needs the complete deployment/operations envelope. |

## Priority and dependencies

1. Reconcile admitted/deferred scope now (R18a). Compare character-deny policy by operation (R02a).
2. Preserve R01 and its same-key serialization and commit-before-response guarantees. Track separately excluded routes and deferred defects under the accepted scope below.
3. Complete the remaining P03-A/B/C/S contracts and acceptance. A5 is optional for entry to A6, not a reason to mark all player-profile work complete.
4. Finish membership acceptance and settle travel time policy (R04). Establish shared recovery (R05), then adopt it with each affected form family.
5. Group bounded work by shared workflows: Campaign Home/events (R06/R09), sessions (R09/R10), administration/sharing/invitations (R07/R08/admitted R11), Knowledge (R05/R15), locations/dungeon areas (R09/R16), quests (R13/R14). These groups need not form a strict chain.
6. Admit and design new search, duration arithmetic, evaluators, consequences and session links separately. Existing repairs need not wait for them. Final integrated exit is R18.
7. C1 remains an implementation gap. C2 and C3 share the September dependency and feature-setting work. C4 still needs an audience-policy disposition.

## Other open defects and acceptance obligations

| ID / work | Remaining disposition |
|---|---|
| DEF-001/005/006 | Fixes and scripted browser evidence exist (including `88ee96a`); carry remaining coverage variants, human/owner acceptance and final-head evidence. Do not revive superseded fix proposals. R05's remaining recovery gaps are separately scoped. |
| DEF-008 | Organization status reads latest stored state as “Now”; decide effective-clock projection versus latest-recorded labeling, then retest G7/TC-36. Unscored semantics triage. |
| DEF-DOC-01 | Relationship restore cannot collect the reason the guide requests. Add reason entry or amend G6; do not manufacture audit evidence. |
| DEF-009 | Encounter projection implemented; integrated API/owner acceptance remains. `active_encounter_id` filtering was implemented by A0 (`fca3ac7`), so it is no longer missing work. Sync-state encounter-reference policy and dungeon-area discovery limitation remain separately scoped. |
| DEF-010 / P02 F-1 | Pending or displayed invitation tokens can be lost on departure. Guard/own the issue operation; decide revoke-and-reissue and duplicate handling. Token recovery must stay within the same authenticated, authorized issuer/campaign and clear on logout/owner/session/authority loss. Sanitized replay cannot recover the token. Distinct from R01's F-1. |
| DEF-012 | Recovery/stranded detection accepts a custom access manager without a built-in owner. Resolve before enabling an application path that grants `access.manage` to a non-owner role. |
| DEF-016/017/019–021, DEF-015 F-1 | See R01–R03 for current disposition. The original grades and identifiers remain historical. |
| P02 browser evidence | B20 keyboard activation; B9 physical Escape and separate backdrop checks; B16 actual 200%/400% zoom. B21 remains deferred/unverified. Preserve reload/new-tab/history, focus, touch, narrow layout and reduced-motion coverage obligations where not executed. |
| Context-navigation browser evidence | Real user/browser-session owner transitions, sign-out/in; NVDA/VoiceOver (respect the owner's AT deferral), Edge/other browsers, physical keyboard, 400% zoom, Back/Forward beyond the chooser case, two-tab revocation. See correction plan §10.4/§10.7. |
| Context-navigation follow-ups | N3 unexplained load-sensitive intermittency (Low); N5 `TimelinePage` breadcrumbs built from typed IDs (informational); Q1 possible World-selection chooser improvement (proposal). First-100-worlds limit remains owner-deferred. N4's obsolete ignored probe was removed in this cleanup, with its bytes preserved; production regression tests remain. |
| Test-harness follow-ups | A1 wait-observation flake not generally closed by A3's diagnosed process-stall correction. A3/A4 retain best-effort thread cleanup after join timeouts, fixed-budget waits elsewhere, one undiagnosed migration-test failure under triple-runner load, and the unidentified source of process freezes. Historical failed runs remain evidence, not current failure counts. |

[Original 43 findings and November review evidence](review-2026-11-11.md#finding-by-finding-traceability)

## Consolidated implementation work (R01–R18)

The detailed entries replace the two November 9 local reports and the duplicate package
briefs. Existing contracts govern implementation; recommendations below do not override
accepted policy. Browser hypotheses remain hypotheses until reproduced.

| Review ID | Existing package / finding |
|---|---|
| R01 | DEF-019–021; DEF-015 follow-up F-1 (stale authorization) |
| R02 | DEF-016; P03-A/B/C/S operation policy |
| R03 | DEF-002 and proposed DEF-017 |
| R04 | DEF-007 acceptance and U1 travel |
| R05 | P01; remaining save/recovery adoption |
| R06 | P04 events |
| R07 | P05 Platform Users |
| R08 | P06 World sharing |
| R09 | P08 layouts/lists/forms |
| R10 | P09 Run Session |
| R11 | P10 invitation roles; DEF-010 remains distinct |
| R12 | P11 time entry/duration |
| R13 | P12 quest objectives |
| R14 | P13 guided quest outcomes |
| R15 / R16 | P14 unpublished Knowledge / location hierarchy |
| R17 | P15/P16 session links |
| R18 | P17 integrated exit |

### R01 — Runtime authorization and transaction defects

**Complete.** The owner accepted the backend scope verified at `f21fb2376abf9dd734aca27072408fcc85588cd5` on 2026-11-18. The route inventory closed at **187 finalized, zero pending, five world routes excluded**. The accepted work includes the eight engine routes, the scoped DEF-019 keyed-cycle correction, same-key queueing and commit-before-response. F-4 closed at `d138f88` and E1-C1 at `3fdd32f`. See the [final-check contract](../api/ACCESS_CONTROL.md#authorization-timing-and-the-final-check-r01-s6) and [route manifest](../../tests/r01_route_manifest.json).

**Recorded verification.** At `f21fb23` the four-shard backend run executed 11,317 tests, with 11,311 passed and six skipped. Ruff, mypy, lock, diff and disposable-database Alembic checks passed at that head. The earlier 11,048-pass/two-failure run and the 10,934-pass/one-failure run at `e1f8085` remain failed runs. The first Alembic attempt reached another session's server, created then dropped an empty database there, and did not migrate it. The successful Alembic check used the verified separate cluster. Runtime tracing covered eight of the 16 S4b routes in the D-7(a) trace. The full [pre-acceptance record](https://github.com/NemesisGhost/dnd_ai/blob/881786c/docs/BACKLOG.md#r01--runtime-authorization-and-transaction-defects) preserves slice evidence, 129 opt-ins and two late reservations. The local owner plan §6.61 and readiness assessment §12 record sign-off. Git records PR #69 merged as `a9952d8` and incorporated at `881786c`. This audit did not query CI or execute portal or Foundry acceptance.

**Approved nonblocking follow-ups.** DEF-020/021 retain their production-path reproduction and verification obligations. F-E4-5 retains the approved, deferred S4b active-account requirement. Restricted-source ownership needs an owner decision (F-E4-2). Removed-source ingestion and invalid-grant error handling remain open (F-E4-3/4). Five excluded world-role, ownership and use-grant routes retain their authorization-timing follow-up. Other residuals are the invitation-acceptance commit upgrade, F6, absent-user insert race, recovery two-lookup window, K9 mutation sensitivity, F-E1-3 and E2 T-5(b). A5c review, A6 and wider Phase 15 acceptance are separate.

### R02 — Character-specific deny consistency

**Source evidence:** [character access resolvers](../../src/dnd_ai/api/access.py) still check `canon.edit` with `character_id`; [public-profile policy](../../src/dnd_ai/domain/public_profiles.py) explicitly checks the character's `entity_id` deny. Normal grant creation already supports the D8 deny target: DEF-018 is not work to rebuild. D8 already fixes the public-profile draft/read/release rules; it does not decide all legacy authoring or inventory behavior.

**Application impact:** an access manager may believe an edit deny restricts an operation that remains available. Conversely, broadening that deny into a visibility restriction can wrongly hide released profiles, controller operations or independently authorized inventory. Changes fan out to sheets, rosters, search, previews and event/reference projections.

**Remaining work:** enumerate operations and capability/target pairs against accepted P03-A/B/C/S contracts. Record “preserve”, “already fixed”, “implementation mismatch”, or “policy unresolved” per row. Include canonical narrative/build authoring, controller mechanics/player profile, public draft/release/reveal, full/summary/public reads, inventory and explanation text. Correct only approved mismatches using the appropriate shared policy. The player-profile row is **decided** by owner-approved D15 (2026-11-11; [A5 design](player-profile-design.md) §4.3):
- A whole-character deny, or a `canon.edit` deny on the character, refuses the GM read and the copy.
- Reveal authority alone grants no access.
- The future controller read path does not require `canon.edit`; its deny semantics are P03-B's.

**Acceptance:** create grants through the application; test owner, GM, controller, delegated revealer and reader sources. Separate whole-character `campaign.view` denies from operation-specific denies; preserve D8 reveal-derived reads/releases. Include revocation and post-wait behavior. Do not bypass a real deny merely to make a list agree with a detail response.

### R03 — Access-group classification and duplicate registration

**DEF-002.** The reviewed method/path now has one runtime registration. The duplicate-decorator observation is historical. The [router](../../src/dnd_ai/api/access_groups.py) changed in `8c60e93`. Preserve the one-registration expectation and stable request/response behavior.

**DEF-017.** Keep group-state classification and coverage of both deactivation orderings separate. Inspect group-target grant behavior where applicable. The catalog check does not exercise the concurrent wait, error classification, audit or receipt behavior.

### R04 — Effective-time membership and travel

**Source evidence:** [the shared half-open predicate](../../src/dnd_ai/queries/party_membership_period.py) exists. Integrated acceptance remains a separate obligation. [Travel](../../src/dnd_ai/commands/travel.py) expands the party with `effective_to_world_time_id IS NULL` **before** resolving its action time. [The preview](../../portal/src/components/TravelSection.tsx) deliberately mirrors that limitation with `left_at === null`; the fresh sampled tests pass against it.

**Application impact:** future members can move early and finite-but-effective members can be omitted. Travel writes narrative location history and causal events, so incorrect expansion propagates beyond the roster. Membership predicates also govern bootstrap choices, Knowledge/Quest perspectives, inventory and the refactor's roster exception.

**Remaining work:** first complete DEF-007 integration against the accepted refactor. Recommended travel policy is membership at the recorded travel time, falling back to campaign Now only when no time is supplied; verify existing approval before treating this as settled. Resolve/validate that time once before expansion. Share the predicate and expose a server-authoritative preview at the same requested time; do not parse display strings or substitute campaign-current `is_current`. Revalidate at commit and explicitly define how a changed preview is reported.

**Acceptance:** future-open and finite-effective intervals, exact join/leave boundaries, explicit historical time, missing clock, branch clocks without inherited membership rows, explicit traveler/party deduplication, unchanged location skips, concurrent membership change, atomic location/event writes. Keep travel independent of duration arithmetic.

### R05 — Save, error and recovery consistency

**Source evidence:** [mutation](../../portal/src/hooks/useAuthoringMutation.ts), [confirmed-refresh](../../portal/src/hooks/useConfirmedRefresh.tsx), unread-write and announcement helpers already exist; the November 9 sampled UI tests covered this foundation; the fresh sample is recorded above. [Knowledge detail refresh](../../portal/src/hooks/useKnowledgeDetail.ts) handles post-save 403/404 differently from initial-read party recovery. [Claim editing](../../portal/src/pages/KnowledgeClaimPage.tsx) also owns its own `behind` state and rereads both resources. [Startup preference](../../portal/src/hooks/useSaveCampaignStartupPreference.ts) can enter `unconfirmed` without reconciling a later independent bootstrap result.

**Application impact:** users can lose evidence of a completed write, retry unnecessarily, or remain blocked behind a stale notice. Incorrect recovery can discard a newer draft or expose stale protected content after authority loss. Every later form package relies on these distinctions.

**Remaining work:** inventory only actual deviations. Repair confirmed-operation ownership across refresh, unmount, permission loss and navigation; retain safe receipt context while clearing inaccessible data. Retry failed reads without repeating the write; track multi-read outcomes instead of treating all reads as failed. Clear the preference notice only from matching authoritative evidence for that save and user. Migrate forms with their later domain checkpoint.

**Acceptance:** rejected/unknown/confirmed/confirmed-but-unread outcomes; original key/body for supported unknown retries; newer drafts survive; stale callbacks cannot clear newer episodes; one meaningful announcement. Recheck the already-fixed repeated-write notice before changing the shared helper; preserve the new owner-bound read reset in `useAuthoringResource`. The 32-entry party-recovery map limitation is separate and needs a demonstrated regression before broadening scope. Invitation tokens require their dedicated policy, not generic durable receipt storage.

### R06 — Campaign event tiles and details

**Source evidence:** [recent events](../../portal/src/components/RecentEventsSection.tsx) already show names, times and explanation sentences. [Event overview](../../portal/src/pages/WorldEventDetailPage.tsx) has status and a “Not recorded” details fallback, and its November 9 sampled tests passed. A literal blank overview remains unconfirmed. [Explanation queries](../../src/dnd_ai/queries/event_explanations.py) already provide audience-aware references and correction information; membership reasons are private.

**Application impact:** indistinguishable events impair session review and correction. Adding raw reasons/participants to improve labels could disclose GM information. P03-S changes mechanical-effect visibility, so this projection must follow the accepted refactor.

**Remaining work:** reproduce the exact route/persona/data for the blank view, including the authoring/read-only branch. Fix only the proven cause. Improve tile and detail context together using the existing explanation DTO and safe fallbacks; group the layout with R09 Campaign Home. Where a recorded membership reason is missing from the GM view, expose it only through that authorized projection. Add a member-safe explanation field only as a separately admitted R06c extension.

**Acceptance:** GM/member/unrevealed-character cases; missing and unsupported event data; corrections/voids; no hidden identity/count/private reason in payloads or labels. Never backfill member text from audit or GM-only reasons.

### R07 — Platform Users administration

**Source evidence:** [Accounts](../../portal/src/pages/AdminAccountsPage.tsx) still contains inline creation and repeated role display. [The editor](../../portal/src/components/SystemRolesEditor.tsx) writes on every checkbox. [Its hook](../../portal/src/hooks/useSystemRoleChange.ts) refreshes the list after success; the list renders only in its success state. The source supports the remount explanation, but scroll movement needs a browser check.

**Application impact:** multi-role editing is hard to follow; refresh can disrupt focus. Errors concern platform authority, not campaign/world roles. Existing one-time activation/reset secrets and last-admin safeguards are important adjacent workflows.

**Remaining work:** separate creation into a route using P02 task return; preserve the list's query/focus. Stage per-account role deltas with Save/Cancel. Recommended first slice uses existing endpoints and an explicit per-change result ledger; it must not claim atomicity. [The system-role client](../../portal/src/api/systemRoles.ts) does not currently send an idempotency key, so the authoring hook's keyed-retry guarantee cannot simply be assumed here. Reconcile uncertain writes from authoritative role state; require a separate API design if stronger retry/atomic semantics are needed.

**Acceptance:** local Cancel before writes; confirmed/failed/unknown substeps; self-role loss; admin grant setting; last-active-admin protection; activation/reset links retained safely in transient memory. Do not persist secrets in return state, URLs, logs or generic recovery storage.

### R08 — World sharing

**Source evidence:** [World sharing](../../portal/src/pages/WorldSharingPage.tsx) is already a dedicated page with role, hosting and transfer sections, confirmations, permission-loss handling and shared recovery. [Its API](../../src/dnd_ai/api/world_sharing.py) uses exact login names. Platform account search exists under platform-admin authority; it is not automatically safe for world sharers.

**Application impact:** clearer tasks improve collaboration and ownership handoff. An indiscriminate autocomplete would expand account enumeration; transfer can remove the acting user's own authority.

**Remaining work:** improve existing panels and feedback first if search policy is unresolved. For an admitted picker, define who may search, which accounts/fields are discoverable, minimum input, bounds/paging and non-disclosing responses. Reuse the combobox interaction, not the admin directory's permissions. Recheck target eligibility and role/hosting/transfer authority during the mutation.

**Acceptance:** authorized search, outsider denial, inactive/changed targets, rapid query changes, retained transfer receipt after losing access, unknown/replay behavior, retained-owner-role options and last-owner invariants. Do not rebuild the existing transfer backend solely to reorganize the page.

### R09 — Smaller layout, list and form repairs

**Source evidence:** [Worlds](../../portal/src/pages/WorldsPage.tsx) still selects Active **or** Archived. [Sessions](../../portal/src/pages/SessionsPage.tsx) defaults to `started_at` descending despite having `scheduled_for`. [Dungeon area creation](../../portal/src/components/world/DungeonAreasSection.tsx) sends only name/type although the authoring API accepts more scalar fields. P02 has already supplied the navigation foundation and addressed some width/focus behavior.

**Application impact:** archived filtering can hide active choices; planned sessions appear in an unhelpful order; users cannot author supported area detail from that form. Broad CSS changes can affect all workflows and keyboard reachability.

**Remaining work:** split this umbrella across its neighboring groups. Worlds checkbox means active plus archived, including deduped campaign-visible active worlds; preserve URL/Back state and picker eligibility. Default planned-session order uses the real-world scheduled timestamp, nulls last and deterministic sequence/ID ties; preserve explicit user sort. Add area summary/dimensions/environment using existing validation and commands. Confirm remaining spacing/sticky-header issues before editing shared CSS.

**Acceptance:** filter union and empty states; null/tie sorting; field round-trip and forbidden actions; 320 CSS px and actual 200%/400% browser zoom. The first-100-worlds limit is an existing separate limitation, not silently solved by changing the filter. Do not expose internal IDs as editable fields.

### R10 — Run Session navigation and width

**Source evidence:** [the page](../../portal/src/pages/SessionRunPage.tsx) links to `section=log`; [the focus hook](../../portal/src/components/staged/useFocusOnSectionChange.ts) deliberately returns when the section is unchanged. This supports the reported mechanism, but the visible failure still needs browser reproduction. Sections remain mounted to preserve drafts.

**Application impact:** a completed Start action can leave users unsure where to record play. Layout/focus changes affect live notes, encounters, travel and wrap-up in the same workspace.

**Remaining work:** group with session ordering from R09. Give the explicit “Go to session log” action a destination-focus/scroll behavior even when already selected. Keep normal Back/Forward and passive refresh focus behavior intact. Improve form width without remounting sections or inventing editable historical events.

**Acceptance:** same-section and cross-section activation, keyboard, sticky header, long content, narrow width, read-only mode, pending writes and preserved drafts. Extend `App.sessionRun.test.tsx` and perform real-browser checks; changing the generic focus hook for every consumer is unnecessary unless the contract requires it.

### R11 — Campaign roles in invitations

**Source evidence:** [invitation storage](../../src/dnd_ai/persistence/tables/security.py) has no intended-role field. [Acceptance](../../src/dnd_ai/commands/campaign_invitations.py) creates/reactivates membership without assigning an invitation-selected role. New-user onboarding shares `_accept_locked_invitation` through [the onboarding command](../../src/dnd_ai/commands/invitation_onboarding.py), providing a natural implementation seam.

**Application impact:** a frontend-only picker would falsely promise access. Role assignment changes onboarding authorization, activation rollback, replay and audit behavior. Inviter authority can change between issue and acceptance.

**Remaining work:** first confirm admission and allowed role policy, especially custom roles and `campaign_owner`. Store a nullable, correctly scoped role reference; null preserves membership-only legacy behavior. Validate creation and acceptance under current authority, with appropriate owner-only gates. Put additive assignment into the shared acceptance transaction; do not grant system/world roles or restore previously revoked roles on replay. Update pending/read DTOs and both UI paths.

**Acceptance:** existing user and registration/activation; revoked/expired token; inviter membership/role/account loss; inactive/foreign role; existing member; replay after subsequent role revocation; no partial role/membership/account changes on failure. Retain token non-disclosure. DEF-010/P02 F-1 one-time-token loss is a distinct recovery design; inspect it while touching this flow, but do not assume role persistence fixes it.

### R12 — Time entry and duration arithmetic

**Source evidence:** [WorldTimeForm](../../portal/src/components/authoring/WorldTimeForm.tsx) already composes calendar/year/month/day/hour/minute and narrative after/before bounds. [Domain time](../../src/dnd_ai/domain/world_time.py) computes calendar keys in minutes using fixed 24-hour days, while narrative keys use ordered gap allocation. [Creation](../../src/dnd_ai/commands/world_time.py) locks per world and stores immutable points. Existing input is not absent; richer interaction and elapsed-duration provenance are additional work.

**Application impact:** every clock, event, temporal membership, branch boundary and historical state relies on these keys. Treating arbitrary narrative gaps as elapsed minutes would introduce false chronology across domains.

**Remaining work:** R12a is a specified interaction improvement using current inputs/picker/dialog. For R12b/c, define eligible anchors, precision, same-calendar assumptions, negative/before durations, boundaries, collisions and stored provenance before schema/API changes. Recommended initial arithmetic supports only explicitly eligible calendar anchors and fixed minutes/hours/days; ambiguous/partial/narrative anchors must not silently become exact. Server recomputes the preview at commit.

**Acceptance:** month/year boundaries within the existing calendar model, invalid inputs, precision propagation, stale preview/anchor selection and concurrent allocation. Creating a point never advances Now. Variable days, month/year duration arithmetic and unusual calendar semantics remain separately admitted work.

### R13 — Quest-objective authoring

**Source evidence:** [QuestEditor](../../portal/src/components/authoring/QuestEditor.tsx) already has Edit/Remove actions inside expanded objective content. [The authoring contract](../../src/dnd_ai/domain/quest_authoring.py) reads objective types from a lookup and freezes structural fields after progress; `other` already provides a general category. A category label or `automatic` completion mode does not establish a new executable evaluator.

**Application impact:** action placement affects discoverability and accidental interaction. Changing types/completion semantics can invalidate recorded progress and future automation consumers.

**Remaining work:** ship R13a with quest UX: separate disclosure/content from management actions and preserve focus. For R13b, inventory actual missing categories before adding lookup values and choose supported manual semantics. R13c requires a distinct evaluator contract covering triggering commands, visibility, repeat/reversal behavior and causal state updates.

**Acceptance:** existing objectives and progressed quests remain valid; no accidental toggle/remove; authorized actors only; unsupported types refused; manual categories never advertised as automatically tracked. Keep the structural-progress lock. Do not silently weaken historical invariants to make editing easier.

### R14 — Guided quest outcome/review

**Source evidence:** [definition sections](../../portal/src/components/quests/QuestCompletionSections.tsx) author outcomes/rewards; [runtime UI](../../portal/src/components/quests/QuestProgressPanel.tsx) invokes status operations. [QuestActionRequest](../../src/dnd_ai/api/quest_runtime.py) has status, party, time and note, not outcome/reward execution. [The command](../../src/dnd_ai/commands/quest_runtime.py) records the quest state/event; it does not distribute authored rewards.

**Application impact:** a guide can improve completion, but falsely reporting rewards as applied would misrepresent inventory and character state. Multi-step flows can partially commit and need durable evidence of the steps actually executed.

**Remaining work:** R14a maps each screen to an existing command/read and identifies descriptive-only results. R14b guides scope/objective review, status action and confirmed history, with per-step recovery. Pull presentation alongside R13a. Do not require new categories/evaluators first. A persistent outcome choice or automatic consequence engine needs a separately admitted domain/API design and P03-S-compatible mechanics.

**Acceptance:** correct party/timeline scope, stale status, interrupted/unknown steps, refresh and navigation, no duplicate actions. Cancel discards only uncommitted choices. Receipts/history distinguish authored descriptions, confirmed state transitions and unapplied consequences.

### R15 — Unpublished Knowledge author browsing

**Source evidence:** [the Knowledge API](../../src/dnd_ai/api/knowledge.py) already opts eligible active browsing into noncanon records; [lifecycle filtering](../../src/dnd_ai/queries/entity_lifecycle.py) enforces world-private authority. The [UI](../../portal/src/pages/KnowledgePage.tsx) offers perspective/lifecycle filters, not explicit publication-state author browsing. Also, archive `all` currently means published history and excludes unpublished claims; it is not literally every author-visible record.

**Application impact:** authors struggle to rediscover drafts; weakening the query could expose private world work to campaign-only GMs or members. Counts, paging and subject/reference labels need the same authorization boundary as details.

**Remaining work:** reproduce the missing-record persona/state first. Add an explicit author mode/publication filter by extending existing queries and DTOs where needed; keep publication state distinct from operational lifecycle and perspective. Define allowed combinations and cursor identity. Reuse R05's Knowledge recovery so the new browse route does not reintroduce lost confirmation context.

**Acceptance:** world author/reviewer with the required campaign entry authority, campaign-only GM, ordinary member, explicit deny, draft/review/published/archived cases; filter before pagination/counts; unauthorized query tampering; return context and read retries. A world-only workspace is deferred below: do not accidentally make it a prerequisite for this campaign-route repair.

### R16 — Location hierarchy

**Source evidence:** [location fields](../../portal/src/components/authoring/LocationFields.tsx) already support a searchable parent picker. [Commands](../../src/dnd_ai/commands/locations.py) already implement reparenting, world checks and cycle prevention using the containment lock; existing tests cover parent assignment and cycles. [World Explorer](../../src/dnd_ai/queries/world_explorer.py) returns authorized ancestor breadcrumbs, truncating at a hidden ancestor. The gap is a useful child/hierarchy browsing workflow, not missing containment storage.

**Application impact:** place discovery affects campaign preparation, dungeon navigation and travel selection. Path/count/search additions can disclose hidden ancestors or introduce unstable pagination; bad reparenting can damage the world graph.

**Remaining work:** build bounded authorized child navigation/search atop current containment; preserve hidden-chain truncation and reuse existing reparent commands. Keep containment paths separate from P02 task breadcrumbs/return context. Group portal work with dungeon-area scalar inputs, while retaining separate domain acceptance.

**Acceptance:** hidden parent/ancestor/child with no ID/name/count leak; deep paths; deterministic paging; cross-world and cyclic reparent refusals; concurrent reparent safety; keyboard and narrow layouts. Only alter schema/commands if a concrete missing invariant is demonstrated. Avoid loading the entire world graph into the browser.

### R17 — Session preparation links and operational navigation

**Source evidence:** [Run Session stages](../../portal/src/components/sessionRun/runStages.ts) already include encounter preparation. [Encounter preparation](../../src/dnd_ai/queries/encounter_preparation.py) uses `encounters.encounters.session_id`; events also have an execution/session association. A general ordered, typed preparation-link collection spanning quests, dungeons and other records is not present in those models.

**Application impact:** useful cross-domain preparation, but broad new storage, authorization and navigation work. Reusing execution references for multiple preparation sessions would change the meaning of historical/runtime data. Links must not create discovery or grant target access.

**Remaining work:** recommend follow-on phase unless an accepted Phase 15 requirement admits it. If admitted, design allowed target kinds, cardinality, ordering, duplicate policy, removal/provenance, scope and GM visibility first. Implement GM preparation links separately from operational handoff and member backlinks. Reuse current encounter preparation where it already meets the need.

**Acceptance:** two-session linking without overwriting encounter execution ownership; hidden/archived/unavailable targets; permission loss; link and target authorization before counts/paging; no copied quest/encounter runtime state. Member links require session access AND link visibility AND target access. New typed links need same-world/campaign constraints, audit and mutation tests, not just UI links.

### R18 — Integrated acceptance and release preparation

**Source evidence:** [PROJECT_STATUS](work-register.md) and the ledger distinguish P02 owner acceptance from Phase 15 completion. [Roadmap §15.8–15.9](roadmap.md) requires the full character contracts and the portal-only First Campaign journey, not every requested enhancement. Existing route/scenario guards support verification but do not replace browser evidence.

**Application impact:** individually correct features may still fail when creation, invitation, control, travel, quest progress, Knowledge, corrections and archival interact. Scope drift or inaccurate records can falsely signal readiness to Phases 16/19.

**Remaining work:** R18a now records admitted/deferred items and refactor dependencies; maintain it as checkpoints close. At the end, reconcile guide, coverage, defects and implementation evidence on one final head. Run the four backend shards, applicable portal/Foundry suites, static/build/lock/migration checks, supported clean initialization, and integrated browser/persona journeys. Use the supported upgrade/recovery policy for retained data; do not invent production rollout requirements for this undeployed project.

**Acceptance:** record first runs separately from reruns and fixture setup separately from product acceptance. Carry B20 keyboard activation, B9 physical Escape and separate backdrop, B16 actual zoom; B21 remains owner-deferred/unverified. Preserve older live Foundry/AI smoke obligations with their actual phase disposition rather than silently turning the portal-only First Campaign scenario into an integration-dependent workflow. Final-head CI, independent review and owner acceptance remain separate records; this review supplies none of them.

## Decisions still needed for proposed additions

The November 9 review proposed these rubric grades; they are retained for triage,
not adopted as new defect-register dispositions or owner risk acceptance:

| Finding | Proposed factors / severity | Evidence and readiness |
|---|---|---|
| R01 / DEF-015 F-1 stale actor authority | `3+3+1+1+0=8`, High | Historical November 11 grade. See accepted R01 above. |
| DEF-019 different-key deadlock | `1+1+1+0+0=3`, Low | Constrained HTTP reproduction; loser rolls back completely. No corruption demonstrated. Scoped prerequisite fulfilled under R01. |
| DEF-002 duplicate registration | `1+1+0+0+0=2`, Low | Duplicate route, not evidence of duplicate execution. One registration at the audited head. |
| Proposed DEF-017 classification | `1+1+1+0+0=3`, Low | Source pattern remains; current race reproduction due. Refusal is preserved; no disclosure demonstrated. |
| R04 / U1 travel expansion | `2+2+1+1+0=6`, Medium | Command/preview source and characterization tests; end-to-end runtime reproduction and recorded-time policy remain due. |

R02 is partly a policy question; R05 needs focused reproductions for precise grading.
Visual symptoms in R06/R09/R10 remain browser hypotheses where noted. An unimplemented
enhancement is scope/design work, not automatically a defect.

Check for later accepted decisions first; do not reopen settled choices.

| Decision | Recommended starting boundary | What waits for it |
|---|---|---|
| Character deny scope beyond D8 | Preserve D8; derive controller/authoring behavior from accepted P03 contracts, then decide only unresolved operation rows. | R02b's unresolved corrections, not unrelated UI work. |
| Travel membership time | Recorded action time; omitted time resolves campaign Now once. Revalidation determines the committed traveler set. | R04b, not R04a acceptance. Preview-change UX must be specified. |
| Staged system roles | Honest per-role operations and reconciliation; no claim of atomic Save. | R07b. An atomic replacement endpoint is separately scoped. |
| World picker privacy | Bounded, world-sharing-authorized eligible search with minimal fields. Explicitly choose which accounts can be discovered. | R08a only; existing sharing panels can proceed. |
| Invitation roles | Nullable legacy intent; additive campaign role; current inviter authority at first acceptance. Specify custom/owner-role eligibility. | R11 schema/API implementation. |
| Time arithmetic | Current entry model first; exact eligible calendar anchors and fixed durations before broader calendars. | R12b/c; entry UI can proceed when specified. |
| New capabilities | Defer evaluators, automatic consequences, member-safe reason storage and general session links unless already admitted. | R13c, expanded R14, R06c, R17. Manual categories also need an actual missing-category requirement. |

## Other explicit follow-ups

Local usability notes (observations, no acceptance or new priority): party membership entry should offer the campaign’s Now, screen left edges vary, and Character → Relationship can highlight both World and Character. Check role-appropriate Quest layouts and consistent publication badges across Quests and Knowledge. Publication and discovery remain separate. Cross-reference R04, R09, R12 and the accepted navigation contract when triaging.

| Follow-up | Context and required next step |
|---|---|
| DEF-007 integrated acceptance | Half-open membership includes join/excludes leave. Root no-clock means **undetermined** and no party-derived access. Independent GM/public/character/grant authority remains. Branch clocks inherit/cap; membership rows do not inherit. Exercise all affected readers and selectors, not only roster grouping. |
| U1 temporal travel policy | Current command and preview use open-ended memberships, not effective membership at campaign/travel time. Future-open included; finite-current excluded. Decide which time should govern travel, then change command+preview together. Current “Travel candidates” wording is intentional. |
| DEF-009 adjacent references | Review sync-state `target_encounter_id`; character-detail `active_encounter_id` was repaired by A0 (`fca3ac7`). Dungeon-area location follows World Explorer discovery, not campaign dungeon discovery; keep that scoped limitation explicit until policy changes. Do not extrapolate a new filter for world-time/ruleset spell IDs without a contract. |
| Recovery episode map | Current map clears at 32 entries, potentially permitting a revisited episode to refresh again. No normal-flow loop was demonstrated. Plan bounded eviction without invalidating active ownership if addressing it. |
| Knowledge post-save reread | Its in-place 404 path bypasses party recovery and can replace saved-but-unrefreshed feedback with unavailable. It fails closed but loses confirmation context. Correct with explicit confirmed-write ownership, not broadened fallback. |
| Startup-preference stale notice | A later independent refresh can confirm the saved value while local “saved but unconfirmed” remains. Clear only when authoritative matching evidence exists, preserving newer drafts and never repeating PUT. |
| Single-router assumption | `navigationHolds` is module-global and documented for one router/document. Current entry uses one router. If multiple simultaneous routers become supported, scope holds/guards and add isolation tests. |
| Infobox explicit-world pagination (deferred by owner, 2026-11-11) | The hierarchy panel reads only the first 100 explicit worlds (`GET /worlds?status=all&limit=100`, the API maximum) and ignores `next_cursor`, so further worlds are not offered in its World level; All Worlds paginates and the current world stays shown display-only. Graded Low (3) in the [context-navigation correction plan](context-navigation.md#2-findings-and-grading). A follow-up needs a pagination-or-search design for the select, applying the same reconciliation rules (UI_DESIGN §4.8.12); it is not part of that correction. |
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

## Deferred refactoring and why

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
| 1 | `httpx` missing from production dependencies | Reconfirmed at `d51e38a` and reported again by Fable C2 at `b0910c4`: dev-only dependency, runtime provider imports (`domain/ai_provider.py:52,324,397`), Docker install with `--no-dev`. Correct runtime dependency declaration/lock and validate the production dependency set and OpenAI-compatible provider in the production image. Neither review built the image. |
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
| 12 | Stale PROJECT_STATUS | Historical report (current disposition D1 above): Fable D1 reports stale PR #68/A4 status in PROJECT_STATUS, docs index and context-navigation plan at `b0910c4`. Reconcile with the already-current P03-A row above; no test results refreshed. |
| 13 | Old PLAN AWS-CI contradiction | Superseded operational prose retired; DEVELOPMENT/ADR 0012 govern CI. |
| 14 | AI feature flag differs from boundary behavior | Expanded by Fable C3: the three `feature_*` settings are used only in config startup validation, no route checks them, and the Discord flag has no consumer. `.env.example` promises AI NPC dialogue is disabled by default. Reconcile intended gates, request enforcement and feature manifest; verify disabled/enabled behavior on affected entry points. Do not claim startup validation enforces requests or fabricate a Discord consumer. |
| 15 | Built/planned schema labels mixed | Expanded by Fable D4 (schema inventory) and D7 (architecture labels). Reconcile DATABASE_MODEL against imported metadata, label absent tables planned/deferred, document built omissions, and separate current architecture from target architecture. Accepted R19 design is not implemented tables or workers. See D4 and D7 below. |
| 16 | Token rules content/creature model | R19/ADRs 0022–0023 own expansion and provenance; acceptance of design is not seed/content delivery. |
| 17 | Conditional migration-test skips | Reconcile actual skip preconditions under current verification policy; not closed here. |
| 18 | Foundry live/AI smoke exit evidence missing | Carried explicitly in PROJECT_STATUS; not executed by cleanup. |

## Documentation drift at the audited head

Fable reviewed `b0910c4` on 2026-11-11. Its [original findings and closure criteria](review-2026-11-11.md#fable-documentation-drift-follow-ups-2026-11-11) remain intact. This reconciliation used source, imported metadata, registered routes and OpenAPI at `881786c`. No application behavior changed.

| ID | Disposition at this head |
|---|---|
| C1 | **Open.** Dungeon connections/features/hazards/interactables and quest/objective reads join state on the exact timeline. Branch creation copies no typed state. Preserve the accepted ancestry rule and verify before/at/after, nested forks, divergence, time bounds and audience when implementing it. [Branching](../ENTITY_LIFECYCLE.md#9-branching-timelines) |
| C2 | **Open, September 1.** The OpenAI-compatible provider imports `httpx`. Only the development extra declares it and the Dockerfile syncs without that extra. Verify the production install and real-provider smoke after dependency correction. |
| C3 | **Open, September 14.** The AI and Foundry flags participate in production startup validation. There is no request gate keyed to them. The Discord setting has no integration consumer. Decide and implement request semantics and verify both settings states. [Runtime configuration](../reference/runtime.md) |
| C4 | **Open policy and reader verification.** The interaction API and command persist `is_visible_to_players`. A source search found no audience reader of that column. No player disclosure demonstrated. Decide whether to enforce, replace or narrow its meaning and cover direct and indirect projections. |
| D1 | Status consolidated here. PR #68, A4 review and context-navigation review are historical outcomes. Browser obligations retained. PR #69 and bounded R01 completion recorded separately. |
| D2 | [Development layout](../DEVELOPMENT.md#2-repository-layout) identifies the current component and metadata modules. |
| D3 | Development navigation, CI job families, live portal proxy and lookup seed rules reconciled against source. |
| D4 | [Schema inventory](../reference/tables.md) names every imported table and the absent design candidates. Historical report counts use different baselines. |
| D5 | [Lifecycle commands](../ENTITY_LIFECYCLE.md#21-service-commands) identify implemented operations. C1 remains open. |
| D6 | [Deployment](../operations/deployment.md) distinguishes the three shipped services, world Sharing, fixture policy and target production topology. |
| D7 | [Architecture](../architecture/SYSTEM_ARCHITECTURE.md) distinguishes runnable services from the planned outbox, import, rules engine, Discord and MCP. |
| D8 | [Layering](../architecture/SYSTEM_ARCHITECTURE.md#5-layering) records request-owned infrastructure writes and SQL-backed domain reads. |
| D9 | [Database conventions](../DATABASE_CONVENTIONS.md#181-naming) describe purpose-based JSON and established singular state/association names. |
| D10 | The hub, component navigation, scoped-role configuration pointer, section links and [migration map](migration.md) replace the earlier blanket index references. |
| D11 | [HTTP catalog](../api/operations.md) maps 348 method/path operations on 333 distinct paths to contracts and handlers. Wire schemas can be inspected per operation in OpenAPI. |

## Checkpoint evidence and source retirement

Each checkpoint records its baseline/final SHA (or uncommitted diff), exact finding,
approved behavior, changed files, commands and first-run results separately from reruns,
refusal/retry/concurrent outcomes, independent review, browser evidence type, owner
acceptance and next checkpoint. Use focused tests locally and the documented four-shard
runner at shared-backend/integration boundaries; use lint/build and affected portal or
Foundry suites as applicable. Migrations use disposable databases and the supported
fresh/retained-data recovery policy. Never downgrade the working campaign database.

The five untracked plans were consolidated here and removed on 2026-11-11. Original bytes
and the obsolete ignored Infobox probe were copied and hash-verified outside the repository
at `C:/Users/nemes/dnd_ai_documentation_sources_20261111/`; see [DELIVERY_HISTORY](history.md)
for hashes and historical evidence. They are not Git-recoverable originals. The external
proposed `APP_INTERACTION_STANDARDS.md` was not imported or adopted. Active P03-A/A1,
context-navigation and R19 plans remain because they still own detailed contracts or gates.

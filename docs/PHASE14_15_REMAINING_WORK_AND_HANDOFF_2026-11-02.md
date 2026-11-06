# Phase 14/15 remaining work and handoff

Prepared 2026-11-02 for the owner, Claude Code planners/implementers, and GPT Luna Medium reviewers.

## Current handoff update (2026-11-06; `phase15/completion` at `4c78e28e13074ec299ef15dbafe477e1f40c2c0c`)

P02 is owner-accepted on reviewed code head `81bf16401cef36d0bc0ed052e64d5a11d9f098a4`, with the decision recorded in the acceptance ledger. That acceptance is separate from overall Phase 14/15 completion. R19-P0 planning documents are integrated at the current head; ADRs 0021–0023 were accepted by the owner on 2026-11-06 as reviewed at `2ca4648` (formal acceptance recorded separately). P03-A has not started.

Browser follow-ups remain as recorded: B20 keyboard activation; B9 physical-keyboard Escape and the separate backdrop check; B16 actual 200% and 400% zoom. B21 remains owner-deferred and screen-reader behavior remains unverified.

OD-17 is owner-approved. A revelation may target a member, access group, or campaign; campaign-wide scope must explicitly specify current members only or current and future members. Audiences receive deliberately published public-profile versions, and a revelation follows later deliberate releases, never unpublished edits. P03-A keeps derived mechanics outside the public profile and reveal capability.

Owner decisions recorded 2026-11-06: the current campaign owner has `character.reveal` directly and is the only role allowed to grant or revoke it for active GMs in that campaign. A GM role loss or revocation ends the grant; restoring GM status requires a fresh owner grant. Assistant-GM status, `canon.edit`, and custom `access.manage` alone confer no release/delegation authority. These are approved policy rules; implementation is pending.

The owner also approved applying the existing encounter discovery policy plus a same-campaign check to character-detail `active_encounter_id`, including for full-tier readers. This is a P03-A implementation requirement, not a currently implemented filter.

The encounter detail leak claim in the Nov. 1 investigation is retired after current source/test review. The direct member route now audience-filters encounter data. Character detail currently returns `active_encounter_id` without a same-campaign/audience check; the owner has approved applying the encounter discovery policy and same-campaign check there, including for full-tier readers. Implement and test this in P03-A; see the D6.4 matrix.

**The snapshot below is historical as of 2026-11-02.** It is retained for provenance; its HEAD, P02 review/acceptance status, and planning-file count are not current.

## 1. Scope and evidence

This document consolidates the original First Campaign manual findings, the investigation and Batch 1 work, the NPC/PC discussion, DEF-007, and the amended P02 navigation plan. It is a handoff, not a fresh repository review. Commit and test information below comes from the supplied implementation/review reports. The repository, database, CI and browser were not inspected to produce this document.

**Historical last reported HEAD:** `a0f690ca32f07f86d334494a971fbcf54b978313`, on `phase15/completion`. The statement that P02-0a findings were blocking and had no reported correction is superseded by the P02 acceptance and R19-P0 integration recorded above.

At the time, four planning documents were reported untracked. That count is historical; inspect current status and ancestry at each handoff. The favicon ancestry remains `f7b00e17d8144d9518042d09b77541e085ba6a10`.

Authoritative local sources to read before implementation:

- `docs/PHASE14_15_APP_INTERACTION_INVESTIGATION_2026-11-01.md`.
- `docs/PHASE14_15_APP_INTERACTION_REPAIR_PLAN_BATCH1_2026-11-01.md`.
- `docs/PHASE14_15_DEF007_EFFECTIVE_TIME_MEMBERSHIP_PLAN_2026-11-01.md`.
- The **amended** `docs/PHASE14_15_P02_NAVIGATION_CONTEXT_PLAN_2026-11-02.md`, including its amendment log.
- `APP_INTERACTION_STANDARDS.md`, previously reported outside the repository in Downloads; locate the owner's current copy.
- `UI_DESIGN.md`, `UI_STYLE_GUIDE.md`, the defect register and acceptance ledger, at their actual repository paths.

If this document differs from the amended plan or a later reviewed change, record the difference and use the latest approved contract. Historical ledger entries are evidence of what was known then, not current acceptance.

## 2. What is already code-review passed

| Work | Reviewed result | What remains |
|---|---|---|
| B1-1 encounter member projection, `67f80de` | Members get only started encounters; GM summaries/turn notes withheld; hidden participants/references filtered; turns densely ranked. Readers with `canon.edit` receive the full editor projection. | Scripted API exercise, CI and owner acceptance; adjacent reference policies below. |
| B1-2 item-definition save feedback, including test correction `8ab6d87` | Confirmed save, read failure, retained edits and deterministic stale-read retry evidence reviewed. | Owner retest M01; extend consistent interaction patterns elsewhere. |
| B1-3a World times dialog, corrected through `2d22468` | Working Cancel, dirty/uncertain dismissal, current-draft classification after GET, focus fallback and retry ownership reviewed. | Real-browser keyboard/focus/zoom/screen-reader checks; T02/T04 acceptance. |
| B1-3b picker dialog, through `529bd4b` | Outer-form isolation, selection revisions, retained drafts and completion during suspended navigation question reviewed. | Representative real-browser callers and accessibility checks. Single-router registry assumption remains. |
| DEF7a backend effective membership, `bcc0e16` | Reviewed server paths use effective campaign time. Portal integration gaps were subsequently addressed by DEF7b. | Integrated temporal/access tests and backend failure triage; no standalone claim that its full suite was green. |
| DEF7b presentation, corrected `cb26462` | Current/Upcoming/History/undetermined states and travel candidates corrected. | Manual presentation/travel checks. Its public-only notice finding was corrected in DEF7c. |
| DEF7c stale-party recovery and session ownership, corrected `4ce9187` | Code-review passed with minor lingering startup-preference notice. | Cross-client/manual/API tests; bounded recovery-map and post-save Knowledge limitations below. |

Code-review passed does not mean browser tested, CI passed, owner accepted, or Phase 14/15 complete. DEF-007 remains open for integrated retests and acceptance.

## 3. Recommended order from here

1. Correct the two P02-0a blockers; obtain independent GPT Luna Medium review of the correction and its integration with prior navigation work.
2. Freeze that reviewed SHA. Populate isolated, namespaced fixtures in local `dnd_ai`, then perform the manual checkpoint in the companion testing document. Resolve merge-blocking failures and repeat affected checks.
3. Complete the repository's checks/CI and merge the reviewed, tested repairs into `main` under the repository's normal merge policy. Record outstanding defects explicitly. This is an integration checkpoint, not phase acceptance.
4. Implement P02-0b, then the remaining P02 slices in dependency order. P02-0c requires PD-8. P02-4 requires PD-11 and P02-3.
5. Develop the detailed NPC/PC policy and migration plan alongside the navigation work; implement approved actor visibility/control contracts before features that depend on those contracts.
6. Deliver the remaining manual-finding repairs in bounded checkpoints. Separate smaller presentation fixes from new backend/domain features.
7. Run the amended First Campaign guide and final acceptance matrix on the integrated result. Close individual defects only against their own evidence.

Every implementation prompt should tell Claude Code to **continue autonomously through the authorized checkpoint until a required Review stage**, including corrections and appropriate checks. Do not stop after proposing a plan or after each routine substep. Stop at independent review, an actual missing policy decision, or an unresolved authorization/environment constraint. Do not silently cross into another checkpoint.

Use Opus for substantial design/planning, Sonnet for bounded implementation, and **GPT Luna Medium for independent reviews**. Review prompts should identify exact parent/target SHAs, changed scope, contracts, known limitations and evidence; they must not present the implementer's reported checks as independently executed checks.

## 4. P02-0a: immediate blockers

### 4.1 Permission-loss cleanup can strand a blank workspace

The latest review reproduced two orderings:

- A dirty page already has a blocked navigation/question. Revocation removes the URL-selected character. Layout holds/unmounts the page, which also owns the blocker and question. Cleanup waits for the blocker to settle, but the installed router can remove an unmounted blocker without notifying subscribers. The revoked query remains and no page, question or notice returns.
- Without an existing question, revoking a dirty page's bootstrap-default character causes cleanup itself to be blocked after the cleanup has unsubscribed. Again the question owner disappears and progress stalls.

Private content is removed, so this fails closed; it still fails recovery. A correction must keep the permission-loss transition live without approving an unrelated user departure, discarding retained work through a generic bypass, or waiting for an event from an unmounted owner. Use supported router operations, bind cleanup to its owning entry, and abandon stale cleanup when newer navigation wins. If a narrowly scoped internal cleanup bypass is necessary, define its exact entry and operation; do not make all REPLACE or all permission-loss navigation unguarded.

Required regressions: both orderings; no old private content; cleanup completes; unrelated query/record identity survives; selected character becomes explicit none; notice appears; no stuck blocker; subsequent navigation works; newer accepted navigation cannot be overwritten.

### 4.2 Revoked bootstrap default briefly reads as another character

An uninitialized selection still derives the new bootstrap default before the layout commits none. A replacement bootstrap authorizing B after A is revoked can produce `read A → read B → read none`. The existing regression set its replacement default to null and missed this.

Required behavior: the previously adopted default is a real selection for revocation purposes. Losing A clears to explicit none, without an intermediate read as B. Re-authorizing A must not resurrect it and remount away a new draft. Preserve fresh-entry authorized defaults and initial authorized/explicit-none history stamps.

Required regressions: default A to only/default B; no B request; clear persists across refresh/re-authorization; URL cleanup and blocked cleanup variants; initial-entry and Back/Forward behavior remain correct.

### 4.3 Contracts already established and worth preserving

- Perspective/campaign changes commit only after navigation is accepted. Stay preserves selection, editor, picker draft and uncertain-write key/body.
- No whole-portal reload/“Loading portal” on a normal perspective change. Authorized page reads remount under the accepted campaign/perspective; shell remains.
- Entry-bound stamping never overwrites a newer click/navigation. Stamping uses the owning router entry, preserves its query/state and scroll, and is not a user transition.
- Authorized initial history context is applied before page reads. Invalid state is not authority.
- A formerly selected revoked URL character is removed with its party parameter, preserving record identity/unrelated query. A never-selected invalid direct URL keeps its existing non-disclosing semantics.
- Revocation notice names no now-unreadable character. Existing approved ordinary Knowledge/Quest cleanup and late-response isolation must stay intact.

The read-only use of `UNSAFE_DataRouterContext` was accepted in principle by review; the identified defect concerns lifecycle/ownership, not the API's name. Re-check compatibility with the installed router version instead of replacing it solely for its prefix.

## 5. Remaining navigation checkpoints

| Checkpoint | Scope and context | Dependencies and completion evidence |
|---|---|---|
| P02-0b | Correct Parties-list breadcrumb root and add New-character breadcrumb. Existing Party detail/create/edit already return to Parties. Preserve validated character/world return adapters. | Can follow stable 0a. Breadcrumb-only; does not add the chooser or new creation entry point. Test direct URLs and each supported origin. |
| P02-0c | Replace New PC with a single New character chooser if approved; forward valid origin into PC/NPC creation. | **PD-8 required.** Creation semantics must remain compatible with the later actor design. |
| P02-1 | Shared route/context/task definitions, full route metadata, history validation and legacy adapters. Audit all 19 guard callers for query changes that dispose scope, drafts or operation owners. | Pure shared-contract checkpoint first. Cover malformed state, same-page Back/Forward, disposing queries and non-disposing queries; no extra authority from history. |
| P02-2 | One Breadcrumb component and authorized label registry, initially Parties and New character. Preserve legacy consumers while migrating. | P02-1. Stored trail contains IDs/descriptors, not durable private labels. Labels invalidate when their authorization context changes or reads return 403/404. |
| P02-3 | Shared explicit selection handling; route campaign always governs campaign pages. Per-tab history selection, validated restoration, explicit none and no hidden last-campaign fallback. | Land route-scope/kept-selection invariant together. Never show campaign A selection governing campaign B's data. P02-4 follows this. |
| P02-4 | Campaign/World/Characters Navbar activation: selected details when valid, expansion when already there or no selection; separate disclosure control. Fix menu closing before guard decision (CTX-4). | P02-3 and **PD-11** (owner-approved). Implemented, awaiting independent review (see the acceptance ledger's P02-4 row). Pointer, keyboard, mobile drawer, Stay/Leave, outside clicks and focus fallbacks have jsdom coverage; real-browser checks are pending. |
| P02-5 | Infobox selection starts the appropriate task root/default details; distinguish explicit selection changes from bootstrap refresh and permission loss. | P02-3/4 contracts. Refreshing the same selection does not reset task origin. Revocation clears safely without resurrecting old selection. |
| P02-6 | Consistent Character summary/details/sheet/relationships/inventory/party navigation and task context across entry paths. | Shared breadcrumb/selection. Reuse authorized DTOs; inventory-only authority must not trigger a broader character-detail read. |
| P02-7a | Sessions and Run session breadcrumb/navigation migration. | Preserve run state, log ownership and return origin. |
| P02-7b | Quests, Knowledge and preview migration. | Keep preview subject separate from operator/Infobox context; preserve party recovery and view query semantics. |
| P02-7c | Items and item definitions migration. | Preserve confirmed-write recovery, retained drafts and inventory authority. |
| P02-7d | World author/read pages. | Location containment path and task breadcrumb are different concepts; retain both where useful. |
| P02-7e | Campaign setup and access/sharing pages. | Back controls follow the common pattern; no permission broadening. Remove legacy adapters only after the last consumer migrates. |
| P02-8 | Reconcile standards, guide and ledger; full browser/accessibility transition matrix. | Actual reload/Back/Forward, labels after permission changes, zoom, focus, mobile and screen readers. Does not automatically accept the phase. |

The design separates four things: server-checked execution scope, explicit Infobox selection, viewed record, and Navbar task origin. Breadcrumb ancestry follows the user's task, not an inferred world/campaign containment tree. None grants access. History is per-tab and stores validated IDs only; no new local-storage, URL or redirect-target persistence.

Query-only navigation skips the guard only if nothing is lost: editor and dialog remain mounted, scope/perspective unchanged, and pending/uncertain/confirmed-but-unread operations keep their owner. Back/Forward compares the context of each entry rather than a temporary transition marker.

Breadcrumb labels are ephemeral authorized data. Do not persist names in history. Invalidate on session/user change, relevant capability/role/perspective/clock context change, selection clearing or record denial. Ignore late labels from an obsolete context; use a generic noun while a new authorized label is unavailable.

### Decisions to carry forward

These are recommendations in the plan, not a record that the owner approved every one.

| Decision | Recommended default / consequence |
|---|---|
| PD-1 | The address governs execution campaign scope; cross-scope context must not appear to govern that page. |
| PD-2 | With no selected campaign, do not silently substitute the last visited/startup campaign. Startup landing behavior is a separate concern. |
| PD-3 | World default goes to authorized world overview, otherwise the permitted campaign-world surface. |
| PD-4 | Characters opens the selected character's authorized full-record shell, without granting additional data rights. |
| PD-5 | Preserve selection through same-tab reload using validated history context. |
| PD-6 | A deliberate perspective change eventually navigates to the new character's Characters details. P02-0a currently remains on the page; do not silently implement PD-6 in that repair. |
| PD-7 | After reload, use generic breadcrumb nouns until an authorized label is available; do not add broad label-fetching reads. |
| PD-8 | Single New character chooser instead of New PC. Blocks only P02-0c and dependent create-action work. |
| PD-9 | GM Party-name links; member links only where their visibility contract permits them. |
| PD-10 | Bound the stored task trail to four steps, following the amended plan's root/leaf rules. |
| PD-11 | **Owner-approved.** Opening a menu by pointer or keyboard focuses its first enabled item; Escape returns to opener. Applied in P02-4 (implemented; awaiting independent review, not owner accepted). |

Menu close should follow accepted navigation, not the click that requested it. During the leave question, preserve the menu/drawer state. Stay restores the prior control when usable, then menu opener, then drawer toggle. Do not leave two active native modals.

## 6. NPC versus PC, visibility and control

This is substantial unfinished work, not something the navigation fixes or encounter projection already delivered. The target discussion is one persistent Character identity for an individual actor, including a person or monster. Being player-controlled is a campaign relationship; statistics, player-facing description, GM secrets, discovery, publication and editing authority are separate dimensions. Preserve IDs and historical references. A player-controlled monster does not require inventing a new creature catalog first.

### 6.1 Settle the policy contract before implementing grants

**Historical decision checklist; current disposition above controls.** R19-P0 and OD-17 settle revelation audiences, current versus future campaign membership, and versioned deliberate-release behavior. The 2026-11-06 owner decision settles `character.reveal` authority and the encounter-reference filter. Authorship responsibility, primary/co-controller rights, explicit-deny precedence and existing PC/NPC treatment remain separate decisions.

Do not conflate:

- Publication/lifecycle with discovery. A published NPC is not automatically discoverable by every campaign member.
- Discovery/public profile with mechanics, inventory, knowledge perspective, GM notes or control.
- Character control with `canon.edit`, world editing, access management or authority over other actors.
- A public appearance/background field with historic content that authors were told was GM-only.

### 6.2 P03-A: deliberate revelation and player-facing profile

The concrete failure discussed was an NPC such as Sella: publication alone does not make the NPC available, while the normal summary reader also lacks the descriptive fields needed for the desired player view. Adding a frontend panel cannot solve that response contract.

OD-17 settles the audience and release behavior: a revelation can name a member, access group, or campaign; campaign-wide scope must explicitly mean current members or current and future members; audiences see deliberately published public-profile versions, and a revelation follows later deliberate releases, never unpublished edits. The release/revelation model remains unimplemented. Keep derived mechanics outside the public profile and reveal capability.

**Owner-approved `character.reveal` policy (2026-11-06; implementation pending).** Current built-in role grants are: `campaign_owner` has `access.manage`, `campaign.view` and `canon.edit`; `gm` has `campaign.view`, `canon.edit`, `character.view_full` and `character.view_knowledge`, but not `access.manage`; `assistant_gm` has `campaign.view`, `canon.edit` and `character.view_full`; `player` and `observer` have `campaign.view`. Current code has no `character.reveal` capability or delegation. The current campaign owner has `character.reveal` directly. Only that current owner may grant or revoke it to active GM memberships in the same campaign. Losing active GM status or revocation ends the grant; restoring GM status requires a fresh grant. Assistant-GM status, `canon.edit`, and custom `access.manage` confer no release or delegation authority on their own. Use a separate audited, campaign/member-scoped delegation, not a global role-template grant or resource grant.

These grantor, recipient and revocation rules are owner-approved. Campaign owners release directly; each GM requires an explicit, live grant. Ending a GM grant ends future release authority; each existing revelation remains independently revocable.

Legacy background needs special care: source classification and guide instructions have conflicted. Quarantine/review existing text rather than blanket exposing every old background field. Keep GM notes protected; copying approved text into public profile must be intentional and attributable.

Track revelation-derived rights separately so revoking a revelation removes only that source, not independent grants/control. Define direct resource denies and narrower operation denies precisely. B1-1's approved editor encounter response is an endpoint-specific exception, not a universal rule that all editors bypass every resource deny.

Audit discovery in list queries, counts, pagination, searches, direct detail, relationships, organizations, rosters, sessions, encounters, quests, Knowledge and preview. Hiding a DOM element after sending private data is insufficient. A hidden reference must not leak via name, ID, count, error detail or breadcrumb label. The direct encounter detail path has an audience projection and query tests. P03-A must apply that encounter discovery policy and a same-campaign check to character-detail `active_encounter_id`, including for full-tier readers; source currently selects it by timeline/status without those checks.

Acceptance must include both positive and negative evidence: deliberately revealed public appearance is visible to the intended player; secrets, mechanics and unrelated knowledge remain absent; an unrevealed published actor stays unavailable; other audiences/campaigns are unaffected; revoke/deny and late-response behavior work. Do not accept an empty response as proof of a useful player profile.

### 6.3 P03-B: campaign controller assignments and bounded operations

Model ongoing player control explicitly per campaign, with primary/co-control semantics if approved, assignment/revocation history, and clear authorization at each write. Decide permitted sheet/resource/inventory operations individually. Existing GM-gated commands do not become safe player operations merely because a character is selectable.

Use named, bounded operations for self-management, expected versions, current authority and relevant locks. Determine HP/resources/conditions, equipment/attunement/consumption and encounter-turn rights separately. Control must not automatically unlock knowledge perspective, secrets, generic canonical edits, or an unrestricted “edit any character” endpoint.

Test two players, a co-controller if supported, a player-controlled monster, revocation, concurrent writes and cross-campaign isolation. Recheck authority at the mutation boundary so an old page cannot retain control after revocation.

### 6.4 P03-C: identity/subtype migration and authoring authority

Audit dependencies before removing subtype tables or filters: builds, session participants, NPC portrayal foreign keys/cascades, relationships, inventories, historical snapshots and legacy routes/payloads. Move shared references to the common actor identity additively before destructive cleanup. Never recreate an actor to change NPC/PC status.

Existing PC editing exceptions and world-scoped characters do not prove a stored owning campaign exists. Do not infer ownership from the first session that referenced the actor. Produce a migration manifest, identify ambiguous cases for owner decisions, and preserve historical classification where it is a snapshot rather than today's controller state.

Reusable creature templates, summons and temporary possession can remain later work. Do not make them prerequisites for revealing or assigning control of an existing individual actor.

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
| Unreproduced I01/E02/S03/A02 | Timeline placeholder hover, Event overview, Go to session log and GM Quest-party availability need real runtime steps/evidence. Do not mark fixed from static suspicion alone. |

## 9. Test failures and evidence debt

The DEF7a review's full backend run reported **6804 passed, 13 failed**: one wrong-password diagnostic under a trust-auth temporary PostgreSQL cluster; DEF-003 dotenv allowed-origin expectation; and eleven `verify.sh` failures involving Windows/Bash paths/configuration. Targeted temporal/access tests passed. Those facts do not make the whole suite green or prove all 13 pre-existing under every environment.

Reproduce with the intended database authentication and supported shell/path setup, capture complete failures, compare parent where necessary, and distinguish environment invalidity from product/test regressions. Keep `.env` values private. Do not edit assertions or authentication to erase failures.

Portal intermittencies have appeared in `App.sessionRun`, `OrganizationMembersReader`, `ItemWorkspace`, `knowledgeMemberPreview`, and a context transition test. Some outputs were not retained. Later isolated/full passes do not diagnose them. For a new occurrence preserve complete output, exact SHA, command, environment and order; use controlled comparisons before assigning causation. Do not turn repeated reruns into a green-only record.

Earlier automated browser launch was policy-blocked. Do not repeat a prohibited tool invocation or bypass policy. Human checks in the owner's normal browser remain a valid path. jsdom does not establish native dialog focus, inertness, touch, actual layout/zoom or screen-reader announcements.

## 10. Original manual findings: coverage crosswalk

| Original observation | Remaining disposition |
|---|---|
| Platform roles repeated/admin explanation/checkboxes/refresh/New user/search spacing | P05. |
| Timeline “No selection” hover appearance | I01 reproduction; then shared control fix if confirmed. |
| World user live search and sharing panels | P06. |
| Show archived checkbox | P08. |
| Campaign Back button and Home layout | P02-7e/P08. |
| Distinguishable event tiles and blank overview | P04; E02 reproduction. |
| Invite role | P10. |
| Calendar component, Cancel, before/after duration, Record time popup | Dialog/Cancel code-reviewed; manual acceptance pending. Rich time/duration P11. |
| Navbar selected details/expansion; summary lost; missing New character breadcrumb; Parties root; missing character tabs; origin breadcrumb reset | P02-0b through P02-8. |
| Missing party membership event reason | P04 with GM/member-safe distinction. |
| Run-session editing width/order/log link | P08/P09; S03 reproduction. |
| GM all campaign characters / all parties for Quests | P03 inspection-vs-perspective design; DEF-007 effective membership; A02 runtime evidence. GM inspect is not player Knowledge perspective or unrestricted world access. |
| Objective types and action separation | P12. |
| Cleaner quest Outcome & Review | P13. |
| Browse unpublished Knowledge | P14. |
| All dungeon-area fields | P08. |
| Item-definition save indication | Pilot code-reviewed; M01 owner retest and P01 adoption. |
| Header always visible, consistent noticeable errors | P08/P01. |
| Run quests/dungeons/etc from session; player session links | P15/P16. |
| Navigate location hierarchy | P14, coordinated with P02-7d. |

## 11. Handoff checklist for each checkpoint

State the exact baseline and contract; list approved decisions and deferred work; preserve unrelated changes; reproduce defects before correcting them where feasible; use tests that observe processed UI/API outcomes rather than elapsed sleeps; run appropriate checks and retain failures; update current docs without rewriting historical evidence; commit a bounded change under repository policy; then stop at independent GPT Luna Medium Review. Include unexecuted manual checks and limitations. Do not assert privacy, CI, owner acceptance or completion beyond the evidence.

The companion `PHASE14_15_MANUAL_TEST_AND_MERGE_CHECKPOINT_2026-11-02.md` defines the proposed first integration checkpoint, local `dnd_ai` fixture prompts, manual matrix, evidence record and merge handoff.

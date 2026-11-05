# P02 navigation and context: reconciliation record (P02-8)

Written 2026-11-04 on `phase15/completion` from baseline `9d6124fdf550aa7df1ae5bbcd18d5a621522a969` (commit `ab63924`), and revised the same day by the P02-8 review-correction commit that follows `ab63924ec9f6d2b98692d8ac641e5352bf77a833`. This record does not accept or close anything. It keeps apart statuses that are easy to blur:

| Status | Meaning here | State |
|---|---|---|
| **Implemented** | The checkpoint's code, tests and documentation are committed. | P02-0a through P02-7e, except P02-0c (gated by PD-8). |
| **Code-reviewed** | An independent code review of the checkpoint passed. | See §1 for the dispositions and their provenance. |
| **Browser-verified / owner-accepted** | The §9.2 browser and assistive-technology checks of the plan ran on a real stack, and the owner signed off. | **Nothing.** No browser check has run for any P02 checkpoint, and no owner acceptance is recorded. |

Automated tests (Vitest over a memory data router in jsdom) are the only executed evidence. They prove destinations, router state, request boundaries and rendered content. They do not establish keyboard order, focus visibility, native dialog behavior, zoom, wrapping, spoken output, reload, new-tab, bfcache or two-tab behavior (plan §9.2: "Never cite jsdom as browser evidence").

## 1. Review dispositions and provenance

| Checkpoint | Disposition | Provenance |
|---|---|---|
| P02-7d as corrected (`1de730c` plus the correction `df1658a`) | **Code-review passed.** The reviewer's nonblocking findings and evidence limits are retained: the limits this record and the ledger rows already carry (jsdom-only evidence; the unattributed intermittencies; the P02-7d deviations). The reviewer's own wording was not supplied to this record and is not reconstructed. | **Conversation-supplied.** Stated by the owner in the review hand-off pasted into this session. No review artifact, comment or record exists in the repository, and none was checked locally. |
| P02-7e (`9d6124f`) | **Code-review passed**, with one nonblocking, **pre-existing** limitation: the Invitations operation-ownership limitation (DEF-010, §5, follow-up F-1). | **Conversation-supplied**, as above. The limitation itself was **locally verified in source** (§5). |
| P02-8 (`ab63924`) | Reviewed by the same hand-off; its documentation findings are what this correction addresses. | Conversation-supplied. |
| P02-0a through P02-7c | Not stated in this hand-off. **Not asserted here.** | — |

The ledger's historical rows still read "awaiting independent review" because that is what they said when committed. They are not edited; the ledger carries an appended correction row that records the dispositions above with the same provenance. Nothing in this record is evidence that a review happened beyond what the owner stated.

## 2. Requirement-to-implementation map

Source of requirements: [the P02 plan](PHASE14_15_P02_NAVIGATION_CONTEXT_PLAN_2026-11-02.md) §8 (checkpoints) and §9 (matrix). Evidence is by ledger row ([acceptance ledger](PHASE14_15_ACCEPTANCE_LEDGER.md)) and test family. The scenario groups below were mapped from the ledger evidence text and test titles, not re-asserted ID by ID (the tests do not carry the plan's IDs).

| Checkpoint | Requirement | Implemented in | Automated evidence (families) | Remaining |
|---|---|---|---|---|
| P02-0a | Guard before context side effects | `useUnsavedChangesGuard` ordering, `navigationHolds`, permission-loss cleanup | `navigationHolds*`, `selectedContext.*`, `CampaignLayout.contextTransition` | Browser: native-dialog inertness (P02-5 limit) |
| P02-0b | Leaf breadcrumbs N04/N05; validated return state | `useCharactersBackPath`, canonical-path validation | `useCharactersBackPath.test.ts`, `breadcrumbModel.test.ts` | None known |
| P02-0c | Characters create entry point | not implemented | none | **Gated by PD-8 (pending)** |
| P02-1 | Contracts without UI change | `taskOrigin`, `routeMeta`, `listState`, `resolveTask`, `legacyReturn`, route and guard audit | `taskOrigin.test.ts`, `routeMeta.test.ts`, `listState.test.ts` | Audit rows are by checkpoint |
| P02-2 | Breadcrumb renderer, label registry, Navbar task start | `TaskBreadcrumb`, `labelRegistry`, `labelAuthority`, `navStart` | `labelRegistry.test.ts`, `labelAuthority.test.ts`, `BreadcrumbLabelProvider.test.tsx`, `App.taskBreadcrumb.test.tsx` | Browser: wrapping, landmark, `aria-current` |
| P02-3 | Selected-context ownership (S11-S13, H1-H9, L2-L5) | `selectedContextStore`, `SelectedContextReconciler`, `SelectedContextProvider`, entry restore | `selectedContext*.test.*`, `entryStamp.test.ts` | Browser: reload, new tab, bfcache, two-tab revocation |
| P02-4 | Navbar split controls, menu/drawer/focus (S3-S5, M1-M6) | `NavbarMenu`, `PortalSidebar`, `navbarDestinations` | `NavbarMenu.integration.test.tsx`, `PortalSidebar.test.tsx`, `navbarDestinations.test.ts` | Browser: keyboard, modified-link activation, collapsed rail, narrow drawer, touch |
| P02-5 | Infobox selection as an ordinary departure (PD-6; S6-S10, N1-N2, L1) | `selectionDeparture`, `selectionArrival`, tracker, focus | `selectionDeparture.integration.test.tsx`, `selectionArrival*.test.*`, `selectionTransitions.test.ts` | Browser: native-dialog close, destination-heading focus, announcements; **one-shot heading focus and dialog inertness limits** |
| P02-6 | Character shell (N03/N06 shell only) | `CharacterRecordNav` and routes | `App.*character*` families | PD-8 pending for any new chooser |
| P02-7a..e | Remaining route families | UI_DESIGN §§4.8.6-4.8.10 | `App.sessionNavigation`, quest/knowledge, `App.itemsNavigation`, `App.worldNavigation`, `App.setupAccessNavigation` tests | Per-family owner browser checks in their ledger rows |
| P02-8 | Documentation reconciliation; browser run | this record | none new | **Browser run not executed** (§4) |

Scenario groups of plan §9.1 and where they are exercised: S1-S10 and N1-N2 in `selectionDeparture.integration`, `NavbarMenu.integration` and `selectionTransitions`; S11-S13 and H1-H9 in `selectedContext.history.integration`, `selectedContext.integration`, `entryStamp`; S14 (create success replaces the form and keeps the trail) in the per-family create-page tests named in the ledger rows; Q1-Q4 in the staged-navigation, guard and per-family workspace tests; M1-M6 in `NavbarMenu.integration` and `PortalSidebar`; L1-L9 in `selectionArrival.integration`, `selectedContext.history.integration`, `labelRegistry` and `labelAuthority`. A group listed here has at least one test family; that is not a claim that every plan row has its own assertion.

## 3. Reconciled definitions

The documents agree on these five concepts (UI_DESIGN §4.8 holds the contract; the plan §4 states the layers).

| Concept | Meaning | Derived from / lives in | Never |
|---|---|---|---|
| **Execution scope** | Whose data a route reads and writes: the campaign (with its world and timeline) or the world a route names. | **Derived from the route's parameters (`campaignId`, `worldId`) and its route metadata (`routeMeta` scope kind).** Nothing is stored beyond the URL. | Chosen by the person, carried in router state, or read from the selection |
| **Server authorization** | Whether the caller may read or command inside that scope. | The server's answer to each request (and the bootstrap's capabilities for gating UI). | Replaced by anything on the client |
| **Selected context** | What the person explicitly chose in the Infobox (campaign, world, timeline, character perspective). | The tab's `SelectedContextStore`, mirrored into history entries as a re-validated `ctx` stamp | Inferred from a viewed account, campaign or access record; **a grant of any authority** |
| **Viewed record** | The record the page shows (`routeMeta.viewed`). | The route parameters and the page's own read | A selection |
| **Task origin** | How the person got here: root, scope, trail, optional list state. | `state.task` (validated), a legacy key that adapts into one, else route defaults | A guess from containment; a lone `returnTo` (a back address); **a grant of any authority** |
| **World containment** | A place's parent chain ("Location path"). | The record's own read | Task trail, breadcrumb ancestors |

Selected context and task state grant no authority: they choose what the UI shows and where links lead, and the server authorizes every read and command independently of them. A task or `ctx` stamp that does not validate against the route and the current bootstrap is ignored.

## 4. Contradictions and gaps found

| # | Finding | Resolution |
|---|---|---|
| R-1 | UI_DESIGN §4.8.6 and audit §9 said the World event page's `EventExplanation` links carry no task ("P02-7d"). P02-7d adopted them. | Superseded note appended; the historical text is kept. |
| R-2 | Audit §10 and §11 listed the World event page, World record workspace and World item page as keeping their links "(P02-7d)". P02-7d changed them. | Superseded notes appended. |
| R-3 | Plan §8 P02-7: "Each slice removes the legacy key writer and reader it owns." Not done: `worldSearch`, `reviewSearch`, `itemsSearch`, `definitionsSearch` and `charactersReturn` are still written beside the task (dual write) and still read by their pages (`useWorldBackPath`, `useItemsBackPath`, `useCharactersBackPath`, `editNavigation`, `WorldCard`, `ReviewPages`, member preview, `NpcAuthoringPages`, `CharactersBrowser`, `CharactersCreateAction`). | **An outstanding plan obligation, not an approved compatibility exception.** Follow-up F-3; no migration in this correction. |
| R-4 | Plan §8 P02-8 asks for the coverage-matrix variants `03.nav-split`, `05.task-origin`, `23.history`, `55.context-guard`, "marked not executed". Absent. | Added to the [coverage matrix](PHASE14_15_COVERAGE_MATRIX.md) §7, all *not executed*. |
| R-5 | Reduced motion (plan §9.2): no automated test. The only motion in the shared navigation CSS is a decorative card transition already inside `prefers-reduced-motion: no-preference`. | A browser check (B19); no code change. |
| R-6 | UI_DESIGN had per-checkpoint sections but no statement of what is and is not verified. | UI_DESIGN §4.8.11. |
| R-7 | The Invitations component can lose an issued token on departure and clears its idempotency key on unmount (found by the P02-7e review, confirmed in source). | §5; DEF-010; F-1. |
| R-8 | The first version of this record said no browser-automation tool was available. The review reported an available VS Code browser tool (no open pages) and unreachable localhost endpoints. | The statement is withdrawn; §6 attributes each observation. |
| R-9 | The first version defined execution scope as "decided by the server's authorization" and listed perspective in it. Perspective is selected context, and authorization is separate. | Corrected in §3. |

## 5. Invitations: reviewed pre-existing limitation (DEF-010)

Classification: a **reviewed pre-existing limitation**, not caused by P02 and not changed by P02-7e. P02-8 does not redesign it.

**Established by reading the source at `ab63924`** (no invitation was issued; no database or live service was inspected):

| Fact | Where |
|---|---|
| `InvitationsSection` has no navigation guard or hold. | `portal/src/components/InvitationsSection.tsx`, `pages/CampaignInvitationsPage.tsx` |
| `useCreateCampaignInvitation` aborts its request on unmount and drops a response that arrives after the abort; its unmount cleanup also sets the reserved idempotency key to null. The issued token lives in `CampaignInvitationsPage` state (`issuedInvitationToken`). | `portal/src/hooks/useCreateCampaignInvitation.ts` |
| The raw token is generated per invitation, returned to that one caller and never stored; only its SHA-256 hash is persisted. | `src/dnd_ai/commands/campaign_invitations.py` (`create_campaign_invitation`, `_hash_invitation_token`) |
| **A matching-key replay returns the sanitized response without the raw token.** With an `Idempotency-Key`, a completed matching request returns the stored body, which holds only `campaign_invitation_id`; the durable idempotency row stores only that sanitized body. | `src/dnd_ai/api/campaign_invitations.py` (replay branch and `complete_idempotent_request`) |
| The idempotency scope is actor user, campaign and key. The same key with a different command or payload (including a different `invited_email`) is a 409 conflict; so is a key whose reservation never completed. | `src/dnd_ai/api/idempotency.py` (`begin_idempotent_request`) |
| **Retaining the idempotency key alone cannot recover the token**: a retry with the key returns `token: null` ("replayed"), and the server holds only the hash. | the two rows above |
| **A fresh reserved key (or no key) can create another invitation.** The create command inserts a row without checking for an existing invitation to the same address. The reviewed schema has **no uniqueness on `invited_email`**: migration 080 defines `invited_email TEXT` with only a unique constraint on `invitation_token_hash`, and no later migration mentions the column. | `src/dnd_ai/commands/campaign_invitations.py`; `database/migrations/versions/080_security_identity_and_access.py`; `grep` over all migrations |
| An outstanding invitation can be revoked by id (an already-revoked one is a no-op; an accepted or expired one is a conflict). | `src/dnd_ai/commands/campaign_invitations.py` (`revoke_campaign_invitation`); `portal/src/api/campaignInvitations.ts` |

Net effect, source-derived and **not observed in a browser**: leaving during or just after an issue request can leave an invitation that exists on the server whose token the issuer never sees; the key cannot bring it back; a new key creates a second pending invitation for the same address if the issuer tries again.

**Remaining owner decision** (not made here): how a lost token is handled. Options include revoking the unseen invitation and issuing a new one, warning about or preventing pending duplicates for the same address, or retaining the token in the page within the authorization boundary (F-1). The established behavior above does not choose among them.

## 6. Browser and assistive-technology verification: not executed

**Executed in P02-8: none.**

Observations and their sources:

| Observation | Source and status |
|---|---|
| An available VS Code browser tool, with no open pages or tabs. | **Reported by the review. Not independently rechecked** by the author (the author's session listed no browser tool, which does not contradict the reviewer's). The first version of this record said no browser automation was available; that statement is withdrawn. |
| The localhost endpoints `127.0.0.1:8001` and `127.0.0.1:5174` were unreachable. | **Reported by the review.** The author's own connection attempts during P02-8 and again during this correction were also refused (curl, exit 7). |
| No application stack is running. | Consistent with both observations. |
| No screen-reader tool was available. | Reported by the review; the author saw none either. |
| Authorized accounts or credentials. | **Not verified.** The author neither used, invented nor reset any credential, and makes no claim about whether authorized accounts exist. |

Why the browser work remains unexecuted: no application stack is running, and starting one (a throwaway database, migrations, seeded accounts or content, the API and Vite) is provisioning that was **not authorized** for this checkpoint or its correction. The author provisioned no service, database, fixture or account. A browser tool alone cannot exercise the real application without a stack; running it against mocked responses would not be real-app evidence.

### 6.1 Checklist (all items **not executed**)

Common evidence fields for every item (record in the ledger; no credentials, tokens or private names): date; stack commit SHA; browser name and version; operating system; viewport in CSS px and zoom; input method (keyboard, mouse, touch); assistive technology and version (or "none"); persona by role (for example "campaign GM", "player controller of a character", "viewer"); execution mode (scripted browser, human, owner); result (pass, fail, blocked); artifact path (screenshot or recording); notes. A failure criterion is a deviation from the expected result below; the contract text is UI_DESIGN §§4.8.1-4.8.4 and plan §9.1, and the expected results are not to be relaxed to fit what a browser happens to do. Where this record says "the contract names X", X is taken from those sections.

| ID | Prerequisites and starting state | Action | Expected result | Failure criteria and extra evidence |
|---|---|---|---|---|
| B1 Main control, other section (S1, S3) | Campaign GM; a selected campaign; clean page in a different section (for example Campaign Home); Navbar expanded. | Tab to **Parties** main control; Enter. | The control is a link to the section's default destination: route is the Parties list, task root `parties` (a one-item or no-ancestor trail), no question, selection unchanged; the destination heading takes focus once; no announcement. | Focus left on the control or `body`; a question on a clean page; selection changed. Evidence: URL before/after, focused element. |
| B2 Main control, already in section (S3) | As B1 but on the Parties list. | Enter on the **Parties** control. | No navigation, no question; the section's menu opens and focus moves to its first menu item (keyboard). | Route change; no menu; focus not on the first item. |
| B3 Menu open by pointer and keyboard (M1, PD-11) | Any group with children (Characters, Knowledge, Items, Access). | Open once by mouse click, once by Enter/Space on the disclosure. | Both: the menu opens and focus moves to the first enabled child; the opener is recorded. | Focus stays on the opener in either path. |
| B4 Escape (M2) | Menu open (once via the main control, once via the disclosure), drawer open at narrow width. | Escape. | Menu closes; focus returns to the opener it was opened from (main control or disclosure respectively); the drawer stays open. | Focus on `body`; drawer closes; wrong opener. |
| B5 Outside pointer and Tab out (M3) | Menu open. | Pointer-down outside; then reopen and Tab out of the menu. | Closes both times; focus is not moved by the close (pointer-down: wherever the browser puts it; Tab: to the next tab stop). | Menu stays open; focus forced elsewhere. |
| B6 Modified-link activation | Main control in link form (a selected destination exists, page differs). | Ctrl/Cmd-click, Shift-click and middle-click. | The browser opens a new tab/window; the original tab runs no handler, asks no question, changes no selection, no history entry. The new tab starts with nothing selected and route defaults (a direct entry; UI_DESIGN §4.8.2 limit 1), generic breadcrumb nouns, no error. | Original tab navigated, selection changed or a question shown; new tab guessing a selection. |
| B7 Dirty Stay | A dirty form (for example Campaign settings name edited, unsaved); menu and drawer open for the Navbar path. | Activate a Navbar link, then separately a breadcrumb ancestor; in the question choose **Stay**. | The question opens (native modal); on Stay it closes; route, history entry, selection, task, draft and any picker draft are unchanged; menu and drawer remain open behind the question (M4); focus returns to the control that was activated (S2) or, for a menu child, to that child. | Draft lost; entry changed; focus on `body` or the drawer toggle while the opener exists (M6 allows the opener else the drawer toggle only if the opener is gone). Evidence: draft text, URL, history length, focused element. |
| B8 Dirty Leave and accepted departure | As B7. | Choose **Leave/Discard**. | One navigation to the destination; menu and drawer close; the destination heading takes focus once (accepted-departure focus); draft discarded; no write request in the network panel; announcement per the scenario (none for a plain Navbar link). | Second navigation; focus restored to the old opener over the destination heading; any POST/PUT. |
| B9 Native modal close | B7's question open. | Escape; then repeat and click the backdrop if the platform allows. | Treated as **Stay** (cancel): nothing changes and focus returns as in B7. After a **Leave** the destination heading, not the restored opener, keeps focus (P02-5 `ac00c1b`). | Close treated as Leave; focus overridden by the restored opener after a Leave. Record the P02-5 native-dialog inertness limit as observed or not. |
| B10 Immediate and deferred arrival | (a) Clean page; Infobox campaign select to a different campaign. (b) Same with the destination's data slowed (network throttling). | Choose the campaign. | (a) Commit, route to the new Campaign Home, root `campaign`, heading focused once, polite announcement per plan S6 ("Campaign changed…"). (b) Focus waits for the heading to exist and then lands on it once; no earlier focus loss to `body`, no repeat. | Focus on `body`; heading focused twice; no or duplicate announcement. Evidence: announcement text as spoken (B21) and timing. |
| B11 Withdrawal after authority loss (L1/L2) | Two accounts or two tabs: a player with a selected campaign and perspective; a GM able to remove that access. Never use live data without authorization. | In tab 2 revoke; in tab 1 trigger a refresh or navigation. | Selection cleared with a polite notice; the old campaign's content is not rendered; "Campaign not found" for the route; a pending selection announcement is withdrawn; no focus move for a background clear. | Old content still shown; announcement for a state no longer true; selection restored later. |
| B12 Back/Forward (H2-H4, H7) | History with two entries of the same page under different perspectives, and one dirty case. | Back, then Forward, clean; repeat dirty. | Clean: the entry's own perspective and task, pages remounted, no "Loading portal". Dirty: the question; Stay keeps perspective, input and entry; Discard shows the entry's perspective. Symmetric on Forward. | Newer perspective shown for an older entry; question missing when dirty; crafted state accepted. |
| B13 Reload and supported restoration (H1, PD-5) | A record opened from a filtered World browser (task + list) and a campaign entry with a perspective (`ctx`). | Reload. | Same trail, filters and perspective: `history.state` (`task`, `ctx`) is restored and re-validated against the current bootstrap; no repeated "Campaign changed" announcement; no error. **Fallback**: if the state is absent or fails validation, the page shows the route defaults (direct-entry trail) and selects nothing. | Different trail without cause; crafted value followed; announcement repeated. |
| B14 New tab, duplicated tab and bfcache | As B13. | Open the address in a new tab; duplicate the tab; navigate away to another site and return with Back. | New tab: nothing selected, route defaults. Duplicated tab and bfcache restore: either the same state or a re-validated one; never content for a campaign the person can no longer open; no stale announcement. This area is **unverified** in the contract (UI_DESIGN §4.8.2 limit 0). | Stale private content; error page; selection guessed. |
| B15 Two-tab revocation | As B11, run in a real second tab with no refresh in tab 1 first. | Act in tab 1 after revocation in tab 2. | The server refuses reads; the page shows its non-disclosing unavailable state; nothing from the revoked scope is shown; selection is cleared when learned. | Private content rendered after a refused read. |
| B16 Breadcrumb at 320 px, 200% and 400% zoom | A record page deep in a task (World record from a filtered browser) with a long record name. | At 320 CSS px; at 200%; at 400%. | The breadcrumb wraps onto further lines; no horizontal page scroll; each crumb is visible, reachable and focus-visible; the current page is text. | Horizontal scroll; clipped or overlapped crumb; focus hidden. Evidence: screenshots at each setting. |
| B17 Narrow drawer and collapsed rail | Viewport narrower than the drawer breakpoint; separately the collapsed rail. | Open the drawer toggle, a disclosure, a child; close. Use rail icons. | Drawer opens/closes; disclosures and children reachable by keyboard; rail controls have names/titles; closing returns focus to the opener, else the drawer toggle, never `body` (M6). | Unreachable item; focus on `body`. |
| B18 Touch | A touch device or emulation. | Tap main controls, disclosures, drawer, breadcrumb links. | No hover dependency; targets large enough to hit; same results as the pointer. | Hover-only content; mis-taps. |
| B19 Reduced motion | OS reduced-motion on. | Use menus, drawer, dialogs and cards. | No non-essential animation or transition. | Any animated transition. |
| B20 Sticky header | A scrolled page. | Tab to a breadcrumb link and to the heading after navigation. | The focused element is not hidden under the sticky header (G01 not made worse). | Focus obscured. |
| B21 Screen reader (NVDA or platform reader) | NVDA version recorded; B1, B7-B10 and B16 states. | Navigate by landmarks, lists and links; trigger the selection change and the question. | Spoken: a "Breadcrumb" navigation landmark, the trail as a list with the current page announced as current; main control role and name ("Open campaign ‹name›" link, "Campaign menu" button) and expanded/collapsed state; the selection announcement once, not doubled; the question dialog's name and description; the destination heading on arrival. | Missing or doubled speech. **Evidence must be the reader's speech (speech viewer log or recording). DOM or live-region inspection is not screen-reader evidence.** |
| B22 Owner walkthrough | The owner's N01-N07 paths. | The owner's script. | Per the owner. | Owner-recorded. |

## 7. Known limitations carried forward

| Limit | Source | State |
|---|---|---|
| Native dialog inertness and the one-shot heading-focus limit | P02-5 | Open; needs browser verification |
| Reload, new-tab, bfcache and two-tab revocation | plan §9.2, P02-3 | Unverified |
| Earlier unattributed portal intermittencies (`CampaignSettingsPage` "treats the saved values as saved…" timeout; `WorldRecordWorkspace.runtime` "shows a recorded status in Details too") | ledger rows 7a, 7c, 7d | Passing reruns do not establish a cause; unresolved |
| 13 backend failures recorded earlier | ledger | Unresolved; not touched by this branch's portal work |
| Invitations operation ownership | P02-7e review | §5 |
| Legacy return keys still dual-written and read | R-3 | **Open plan obligation** (F-3) |
| Wizard and `/campaigns` not on the shared breadcrumb; Cancel always goes to `/campaigns` | P02-7e | Deferred (F-4) |
| PD-8 | plan §10 | **Pending; no owner decision exists** |

## 8. Completion gate

P02 cannot be called complete while any of these stands:

1. **PD-8 / P02-0c.** Pending. No owner decision is recorded in the plan, the ledger or this branch, and this record does not decide it. P02-0c cannot ship; the Characters menu keeps its current contents; P02-6 kept the existing "New PC" entry.
2. **F-3, legacy writer and reader removal.** The plan requires each slice to remove the legacy key writer and reader it owns. That has not happened for any of the five legacy keys. It is an **outstanding plan obligation, not an approved compatibility exception**; no owner approval of leaving them exists.
3. **Browser and assistive-technology verification.** Incomplete: §6.1 is entirely unexecuted.
4. **Owner acceptance.** Not given.

Also unchanged: P03's prerequisite is to merge `planning/r19-p0-architecture` into `phase15/completion`, then check Character and rules readiness. It is not started. The wizard exclusion (F-4) was reviewed and requires no new unscoped task model or label authority; it stays deferred.

## 9. Follow-ups

| ID | Follow-up | Acceptance criteria |
|---|---|---|
| F-1 | **Invitations: own the issue operation across departure and recover only inside the authorization boundary** (DEF-010). | (1) Leaving `/access/invitations` while an issue request is pending asks first, or hands the request to an owner that outlives the page; Stay keeps the pending state and the idempotency key; Leave never sends the create again. (2) **Recovery is limited to the same currently authenticated and authorized issuer and campaign**: the lost token, an indication that an invitation was issued, or any held reservation is surfaced only to the user who issued it, in the campaign it was issued for, while that user is still signed in with `access.manage` on it. (3) **Logout, a session or owner change (a different sign-in in the same tab), or loss of `access.manage`** (learned by refresh or a 403) stops private token recovery at once, discards whatever was retained for it, and discloses nothing afterwards (no token, address or invitation id). (4) **Safe handling must not require retaining a bearer token beyond its authorization boundary**: no token in URLs, router or history state, browser storage or logs; whatever mechanism holds it (this record chooses none) is bounded by the authorized session and cleared at its end. (5) The idempotency key alone cannot recover the token (the server returns the sanitized body only, §5); recovery therefore needs either the token retained inside the boundary or a revoke-and-reissue path, which is the owner's decision. (6) Duplicate handling (warning or preventing a second pending invitation for the same address; the schema has no uniqueness) is the owner's decision, made before wording is fixed. (7) Tests: one POST per submit under navigation; Stay/Leave; late response after departure; replay wording; sign-out and a different sign-in in the same tab show nothing; loss of `access.manage` clears; no token in router state, URL or storage. (8) No change to role, authorization, activation/reset or ownership-transfer behavior. |
| F-2 | Run the §6.1 checks on an authorized disposable stack and record each per its fields. | Every row has a result or a stated blocker with browser, version, viewport, method and mode; no jsdom evidence in that column. |
| F-3 | Remove the legacy return keys once the last reader migrates (plan obligation, §8 item 2). | No writer or reader of `worldSearch`, `reviewSearch`, `itemsSearch`, `definitionsSearch` or `charactersReturn` remains outside `legacyReturn`'s adapter, which is then removed; per-family tests pass without them; old history entries fall back to route defaults. |
| F-4 | Deferred. Carry a validated origin into the campaign setup wizard and decide whether it joins the shared breadcrumb. | Only if taken up: Cancel and the top crumb return to the page that opened the wizard, validated, with a safe default; the recovery contract tests pass unchanged; no new unscoped task or label model is needed (the reviewed exclusion stands until then). |
| F-5 | Attribute or fix the unattributed portal intermittencies. | A reproduced cause, or a recorded repeated-run protocol with its result. |
| F-6 | PD-8 owner decision, then P02-0c if approved. | A written decision in the plan or ledger. |

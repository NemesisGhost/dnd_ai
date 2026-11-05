# P02 navigation and context: reconciliation record (P02-8)

Written 2026-11-04 on `phase15/completion`, baseline `9d6124fdf550aa7df1ae5bbcd18d5a621522a969`. This record does not accept or close anything. It separates three different statuses that earlier ledger rows keep distinct but that are easy to blur:

| Status | Meaning here | State |
|---|---|---|
| **Implemented** | The checkpoint's code, tests and documentation are committed. | P02-0a through P02-7e, except P02-0c (gated by PD-8). |
| **Code-reviewed** | An independent review of the checkpoint's commit(s) found no remaining blocking finding. The review outcomes are the owner's hand-off; this session does not see them and does not re-derive them, so none is asserted here. | Not asserted. Every ledger row says "awaiting independent review" as written at its commit; P02-7e and P02-8 are the newest. |
| **Browser-verified / owner-accepted** | The §9.2 browser and assistive-technology checks of the plan ran on a real stack, and the owner signed off. | **Nothing.** No browser check has run for any P02 checkpoint, and no owner acceptance is recorded. |

Automated tests (Vitest over a memory data router in jsdom) are the only executed evidence. They prove destinations, router state, request boundaries and rendered content. They do not establish keyboard order, focus visibility, native dialog behavior, zoom, wrapping, spoken output, reload, new-tab, bfcache or two-tab behavior (plan §9.2: "Never cite jsdom as browser evidence").

## 1. Requirement-to-implementation map

Source of requirements: [the P02 plan](PHASE14_15_P02_NAVIGATION_CONTEXT_PLAN_2026-11-02.md) §8 (checkpoints) and §9 (matrix). Evidence is by ledger row ([acceptance ledger](PHASE14_15_ACCEPTANCE_LEDGER.md)) and test family; the scenario columns below group the plan's IDs and were mapped from the ledger evidence text and test titles, not re-asserted ID by ID in this checkpoint (the tests do not carry the plan's IDs).

| Checkpoint | Requirement | Implemented in | Automated evidence (families) | Remaining |
|---|---|---|---|---|
| P02-0a | Guard before context side effects | `useUnsavedChangesGuard` ordering, `navigationHolds`, permission-loss cleanup | `navigationHolds*`, `selectedContext.*`, `CampaignLayout.contextTransition` | Browser: native-dialog inertness (P02-5 limit) |
| P02-0b | Leaf breadcrumbs N04/N05; validated return state | `useCharactersBackPath`, canonical-path validation | `useCharactersBackPath.test.ts`, `breadcrumbModel.test.ts` | None known |
| P02-0c | Characters create entry point | not implemented | none | **Gated by PD-8 (pending)** |
| P02-1 | Contracts without UI change | `taskOrigin`, `routeMeta`, `listState`, `resolveTask`, `legacyReturn`, route and guard audit | `taskOrigin.test.ts`, `routeMeta.test.ts`, `listState.test.ts` | Audit rows are by checkpoint; no new route since 7e was added |
| P02-2 | Breadcrumb renderer, label registry, Navbar task start | `TaskBreadcrumb`, `labelRegistry`, `labelAuthority`, `navStart` | `labelRegistry.test.ts`, `labelAuthority.test.ts`, `BreadcrumbLabelProvider.test.tsx`, `App.taskBreadcrumb.test.tsx` | Browser: wrapping, landmark, `aria-current` |
| P02-3 | Selected-context ownership (S11-S13, H1-H9, L2-L5) | `selectedContextStore`, `SelectedContextReconciler`, `SelectedContextProvider`, entry restore | `selectedContext*.test.*`, `entryStamp.test.ts` | Browser: reload, new tab, bfcache, two-tab revocation |
| P02-4 | Navbar split controls, menu/drawer/focus (S3-S5, M1-M6) | `NavbarMenu`, `PortalSidebar`, `navbarDestinations` | `NavbarMenu.integration.test.tsx`, `PortalSidebar.test.tsx`, `navbarDestinations.test.ts` | Browser: keyboard, modified-link activation, collapsed rail, narrow drawer, touch |
| P02-5 | Infobox selection as an ordinary departure (PD-6; S6-S10, N1-N2, L1) | `selectionDeparture`, `selectionArrival`, tracker, focus | `selectionDeparture.integration.test.tsx`, `selectionArrival*.test.*`, `selectionTransitions.test.ts` | Browser: native-dialog close, destination-heading focus, announcements; **one-shot heading focus and dialog inertness limits** |
| P02-6 | Character shell (N03/N06 shell only) | `CharacterRecordNav` and routes | `App.*character*` families | PD-8 pending for any new chooser |
| P02-7a..e | Remaining route families | see UI_DESIGN §§4.8.6-4.8.10 | `App.sessionNavigation`, quest/knowledge, `App.itemsNavigation`, `App.worldNavigation`, `App.setupAccessNavigation` tests | Per-family owner browser checks in their ledger rows |
| P02-8 | Documentation reconciliation; browser run | this record | none new | **Browser run blocked** (§4) |

Scenario groups of plan §9.1 and where they are exercised: S1-S10 and N1-N2 in `selectionDeparture.integration`, `NavbarMenu.integration` and `selectionTransitions`; S11-S13, H1-H9 in `selectedContext.history.integration`, `selectedContext.integration`, `entryStamp`; S14 (create success replaces the form and keeps the trail) in the per-family create-page tests named in the ledger rows; Q1-Q4 in the staged-navigation, guard and per-family workspace tests (`useStagedNavigation.test.tsx` plus the guards audited in the route and guard audit); M1-M6 in `NavbarMenu.integration` and `PortalSidebar`; L1-L9 in `selectionArrival.integration`, `selectedContext.history.integration`, `labelRegistry` and `labelAuthority`. A group listed here has at least one test family; that is not a claim that every plan row has its own assertion.

## 2. Reconciled definitions

The documents now agree on these five concepts; each is stated once in UI_DESIGN (§4.5 for context, §4.8 for task) and used the same way in the audit.

| Concept | Meaning | Lives in | Never |
|---|---|---|---|
| **Selected context** | The campaign / perspective / world the person chose or arrived in; the route campaign wins on campaign routes (I-1). | `selectedContextStore`, the entry's `ctx` stamp (re-validated) | Inferred from a viewed account, campaign or access record |
| **Execution scope** | What a request or command runs under (campaign, perspective); decided by the server's authorization. | The request and bootstrap | Granted by router state, a breadcrumb or a label |
| **Viewed record** | The record the page shows (`routeMeta.viewed`). | The route and its own read | A selection |
| **Task origin** | How the person got here: root, scope, trail, optional list state. | `state.task` (validated), a legacy key that adapts into one, else route defaults | A guess from containment; a lone `returnTo` (a back address, not an origin) |
| **World containment** | A place's parent chain ("Location path"). | The record's own read | Task trail, breadcrumb ancestors |

## 3. Contradictions and gaps found

Concrete checks run in this checkpoint, and what they found.

| # | Finding | Resolution |
|---|---|---|
| R-1 | UI_DESIGN §4.8.6 and audit §9 said the World event page's `EventExplanation` links carry no task ("P02-7d"). P02-7d adopted them. | Appended a superseded note to those sentences (the historical text is kept). |
| R-2 | Audit §10 and §11 listed the World event page / World record workspace / World item page as keeping their links "(P02-7d)". P02-7d changed them. | Appended superseded notes. |
| R-3 | Plan §8 P02-7: "Each slice removes the legacy key writer and reader it owns." Not done: `worldSearch`, `reviewSearch`, `itemsSearch`, `definitionsSearch` and `charactersReturn` are still written beside the task (dual write) and still read by their pages (`useWorldBackPath`, `useItemsBackPath`, `useCharactersBackPath`, `editNavigation`, `WorldCard`, `ReviewPages`, member preview, `NpcAuthoringPages`, `CharactersBrowser`, `CharactersCreateAction`). The handoff says to remove adapters only after the last consumer migrates. | Recorded as an open follow-up F-3 (no code change in this checkpoint). |
| R-4 | Plan §8 P02-8 asks for the coverage-matrix variants `03.nav-split`, `05.task-origin`, `23.history`, `55.context-guard`, "marked not executed". Absent. | Added to the [coverage matrix](PHASE14_15_COVERAGE_MATRIX.md) §7, all marked **not executed**. |
| R-5 | Reduced motion (plan §9.2): there is no automated test; the only motion in the shared navigation CSS is a decorative card transition already inside `prefers-reduced-motion: no-preference`. | Recorded as a browser check; no code change. |
| R-6 | `UI_DESIGN` had per-checkpoint sections (§4.8.1-4.8.10) but no statement of what is and is not verified. | Added §4.8.11 pointing to this record. |
| R-7 | The Invitations component can lose an issued token on departure and clears its idempotency key on unmount (found by the P02-7e review). | Classified in §5 and registered as DEF-010 in the [defect register](PHASE14_15_DEFECT_REGISTER.md); follow-up F-1. |

Previously recorded ledger rows are unchanged. The ledger gets one appended row for this checkpoint.

## 4. Browser and assistive-technology verification: not executed

**Executed in this checkpoint: none.** The attempt and the blockers:

- No stack is running (`127.0.0.1:8001` and `127.0.0.1:5174` refuse connections; the owner's earlier acceptance stack from CP-11 is no longer up).
- The plan's run needs a disposable stack with a throwaway database and seeded, authorized accounts. Creating that database, running migrations, seeding accounts or content and starting the API are direct database access and fixture creation, which this checkpoint's instructions do not authorize. No credential is held, and none was invented or reset.
- No browser-automation or assistive-technology tool is available in this session (no NVDA or other reader; no browser tool was offered).
- Substituting the app against mocked responses would be jsdom-equivalent evidence about a mock, not about the real app, so it was not done.

Everything in plan §9.2 therefore remains for the owner (or a session with an authorized stack). Record for each: browser and version, viewport, input method (keyboard, pointer, touch), assistive technology and version, account/persona, and execution mode (automated, scripted browser, human, owner); keep jsdom assertions out of the evidence column.

| Group | Checks (plan §9.2 and this checkpoint's list) |
|---|---|
| Keyboard and menus | Tab order and focus visibility; Enter/Space on main controls and disclosures; menu open by pointer and keyboard moves to the first enabled child (PD-11); Escape returns to the opener and keeps the drawer; outside pointer or Tab closes without moving focus; modified-link (ctrl/cmd/shift/middle) activation does not run the in-page handler |
| Dirty departures | Stay/Leave on each family's form; native modal close (Esc, backdrop) with the destination heading focused; the P02-5 one-shot heading-focus and native-dialog inertness limits |
| Arrival | Immediate and deferred destination arrival focus and announcement; no double announcement; selection announcements; withdrawal of a selection announcement after learned authority loss |
| History | Back/Forward across same-path entries; reload (does `history.state` keep `task` and `ctx`); new-tab entry; bfcache restore; two-tab revocation (L1/L2) |
| Layout | Breadcrumb wrapping at 320 CSS px and 200%/400% zoom (the CSS wraps and breaks long names; unverified in a browser); narrow drawer and collapsed rail reachable; sticky-header obstruction not worsened (G01); reduced motion |
| Assistive technology | NVDA (or the platform reader): breadcrumb landmark and `aria-current`, role and name changes of the main controls, polite announcements. DOM or live-region inspection does not establish spoken output |
| Owner paths | The N01-N07 walkthrough; each family's owner checks in its ledger row |

## 5. Known limitations carried forward

| Limit | Source | State |
|---|---|---|
| Native dialog inertness and the one-shot heading-focus limit | P02-5 | Open; needs browser verification |
| Reload, new-tab, bfcache and two-tab revocation | plan §9.2, P02-3 | Unverified |
| Earlier unattributed portal intermittencies (`CampaignSettingsPage` "treats the saved values as saved…" timeout; `WorldRecordWorkspace.runtime` "shows a recorded status in Details too") | ledger rows 7a, 7c, 7d | Passing reruns do not establish a cause; unresolved |
| 13 backend failures recorded earlier | ledger | Unresolved; not touched by this branch's portal work |
| Invitations operation ownership | P02-7e review | See below |
| Legacy return keys still dual-written and read | R-3 | Open (F-3) |
| Wizard and `/campaigns` not on the shared breadcrumb; Cancel always goes to `/campaigns` | P02-7e | Open (F-4) |
| PD-8 | plan §10 | **Pending; no owner decision exists** |

**Invitations (reviewed pre-existing limitation, not caused by P02).** `CampaignInvitationsPage` mounts `InvitationsSection`, which has no navigation guard or hold. `useCreateCampaignInvitation` aborts its request on unmount and drops a response that arrives after the abort (`controller.signal.aborted`), and its unmount cleanup also clears the reserved idempotency key. The issued token is held in the page's state (`issuedInvitationToken`). So if a person leaves the page (a breadcrumb, a tab, the Navbar, Back) after the server accepted the create but before the response is applied, or after the token is shown, the token is gone: a replay with the same key would return `token: null` (the "replayed" status), and a later submit after the cleared key uses a new key. Whether the server would then create a second pending invitation for the same address is a backend question not examined here. P02-7e did not change this component or add a guard, and P02-8 does not redesign it. Registered as DEF-010 with the follow-up below.

## 6. Decision gates

- **PD-8 (Characters "New" chooser).** Pending: no owner decision is recorded in the plan, the ledger or this branch. Effect on P02: P02-0c cannot ship, and the Characters menu keeps its current contents; P02-6 kept the existing "New PC" entry (ledger P02-6 correction). P02 as a navigation contract is implementable and implemented without it, but "P02 complete" in the sense of plan §8 (all of P02-0a..P02-8 including P02-0c) cannot be claimed until the owner decides. This record does not decide it.
- **P03 prerequisite (unchanged).** Merge `planning/r19-p0-architecture` into `phase15/completion`, then check Character and rules readiness. Not started.
- **Owner sign-off and the §9.2 browser run** are gates for any acceptance wording; neither has happened.

## 7. Follow-ups

| ID | Follow-up | Acceptance criteria |
|---|---|---|
| F-1 | **Invitations: own the issue operation across departure** (DEF-010). | (1) Leaving `/access/invitations` while an issue request is pending asks first (the existing guard question), or hands the request to an owner that survives the page; Stay keeps the pending state and the idempotency key; Leave never sends the create again. (2) An accepted response is never discarded: a token returned to a page that has been left is either shown on return or the person is told that the invitation exists and a new token must be issued (the exact behavior needs an owner choice because the token is shown once). (3) The idempotency key is reserved for the same email until the outcome is known, across unmount. (4) Tests: single POST per submit under navigation, Stay/Leave, late response after departure, replayed (`token: null`) wording, and no token in router state, URLs or storage. (5) No change to role, invitation or authorization behavior, and a backend question (duplicate invitations for one address) answered before the UI wording is fixed. |
| F-2 | Run the §9.2 browser and assistive-technology checks on an authorized disposable stack and record each per §4. | Every row of §4 has a result or a stated blocker with browser, version, viewport, method and mode; no jsdom evidence in that column. |
| F-3 | Remove the legacy return keys once the last reader migrates. | No writer or reader of `worldSearch`, `reviewSearch`, `itemsSearch`, `definitionsSearch` or `charactersReturn` remains outside `legacyReturn`'s adapter, which is then removed; the `legacyReturn` and per-family tests pass without them; old history entries fall back to route defaults. |
| F-4 | Carry a validated origin into the campaign setup wizard (World overview / timeline page entries) and decide whether the wizard joins the shared breadcrumb. | Cancel and the top crumb return to the page that opened the wizard, validated, with a safe default; the recovery contract tests pass unchanged. |
| F-5 | Attribute or fix the unattributed portal intermittencies. | A reproduced cause, or a recorded repeated-run protocol with its result. |
| F-6 | PD-8 owner decision, then P02-0c if approved. | A written decision in the plan or ledger. |

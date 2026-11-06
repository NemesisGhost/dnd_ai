# P02-1 — Navigation contracts, route inventory and guard-caller audit

Date: 2026-11-02. Baseline `3047ea19eac5d11447d0fec6647ee74583063375` on `phase15/completion`. Portal, tests and documentation only: no backend, API, schema or database change. Nothing here is a manual or owner acceptance, and Phase 14/15 stays open.

This document records what P02-1 implemented, separately from what later P02 checkpoints will do, so the next reviewer can check each claim against the code. The plan is [PHASE14_15_P02_NAVIGATION_CONTEXT_PLAN_2026-11-02.md](PHASE14_15_P02_NAVIGATION_CONTEXT_PLAN_2026-11-02.md) (untracked); the design contract is [UI_DESIGN.md §4.8 and §5.11](UI_DESIGN.md).

## 1. Implemented contracts (all in `portal/src/navigation/`, plus the guard)

| Module | Contract | Keeps apart from |
|---|---|---|
| `contexts.ts` | `ExecutionScope` (whose data the route reads and writes), `SelectedContext` (what the person explicitly chose), `ViewedRecord` (which record is on screen), `EntryContextV1` (the context stamp of a history entry), `readEntryContext`, `entryContextStamp`, `isIdShaped` | Each is a separate type with a separate source. No function turns one into another. |
| `routeMeta.ts` | `ROUTE_METAS` (one entry per production route pattern), `matchRouteMeta`, `executionScopeOf`, `viewedRecordOf`, `defaultAncestors`, `NavRoot` | The scope is read from route params, the viewed record from a different param; neither reads a selection. |
| `taskOrigin.ts` | `TaskOriginV1` (root, scope, bounded trail of route ids and id params, optional whitelisted list state, presentation-only `transition` hint), `parseTask` (shape and version), `validateTask` (fit to a route), `startTask`, `continueTask`, `defaultTask` | A task is navigation state. It never carries a label, free text, URL, capability, authorization outcome or receipt. |
| `legacyReturn.ts`, `resolveTask.ts` | Origin resolution steps 1 to 3 (`resolveTask`); the read-only adapters for `charactersReturn`, `reviewSearch`, `itemsSearch`, `definitionsSearch`, `worldSearch`, `returnTo` | Adapters read and validate; they never write state. |
| `listState.ts` | Per-list-route contract for persisted list state: declared keys, repeat limits, value rules (section 1.2) | |
| `queryKeys.ts` | `queryKeysChanged(...keys)` (a `disposingQuery` predicate), `PERSPECTIVE_QUERY_KEYS` (moved from `CampaignLayout.tsx`, same value) | |
| `hooks/navigationHolds.ts` | `isGuardedTransition(args, options?)`, `CommittedContext`, `setCommittedContext` | One predicate for both blockers. |
| `hooks/useUnsavedChangesGuard.ts` | `useUnsavedChangesGuard(isDirty, options?: { disposingQuery })` | The option is optional; no option means today's behavior. |

Client history and context never grant authority. A stamp or task only asks for something; every read and command is still authorized by the server, a failed or denied read fails closed as before, and a trail entry is never an access hint.

### 1.1 Compatibility decisions

1. **The P02-0a stamp stays valid.** `{ v: 1, characterId }` is read as `legacy-perspective`: it records the perspective only. The other three levels are *unrecorded*, not "none", so a comparison never treats them as having changed. The campaign layout still writes exactly this stamp; P02-1 does not change what is stamped (that is P02-3).
2. **The versioned stamp** has all four keys (`campaignId`, `worldId`, `timelineId`, `characterId`), each an id or `null`. Any other mix (a partial form, a mistyped or non-id value, a wrong or missing version, an array or non-object `ctx`, an inherited `ctx`) reads as `absent`.
3. **Explicit none.** `null` is "nothing selected". It is different from `absent` ("no valid stamp"). A stamp with `characterId: null` that is returned to by Back/Forward means no perspective; an absent stamp resolves to the bootstrap default on Back/Forward only.
4. **Authorization of the perspective** is applied by the reader exactly as before: a stamp (either form) naming an unauthorized perspective is `absent`.
5. **The committed side** (`CommittedContext`) keeps `characterId`, `defaultCharacterId` and `authorized` as before, and adds optional `campaignId`, `worldId`, `timelineId`. A level left `undefined` is *not committed* by the current owner and is not compared. Today only the campaign layout writes the committed context and it writes the perspective only, so the production predicate behaves as in P02-0a. `setCommittedPerspective` and `readEntryPerspective` remain as compatibility names for the same functions.
6. **Same-page Back/Forward** is compared on recorded context, never a transient marker: PUSH or REPLACE without a stamp keeps the committed context; Back/Forward to an unstamped, malformed, foreign or unauthorized entry resolves to the default; a stamp-only or hint-strip REPLACE (same path, same context, same query) is never guarded.
7. **Preserved unchanged:** the permission-loss exemption (`runPermissionLossCleanup`, same-path REPLACE of that entry, only while `run` executes), blocker cancellation on unmount, entry-bound stamping and accepted-selection ownership in `CampaignLayout`, and P02-0b's canonical `readCharactersReturn` (the adapter calls it; its UUID-only rule is not relaxed, and the new tests use UUIDs for that reason).
8. **Task parsing decisions.** A trail longer than 4 entries is rejected as tampered rather than truncated (writers never produce more; `continueTask` caps at 4). Duplicates and the current page are dropped when validating. An unknown `transition` value is dropped. Unknown keys are dropped. Parameters and scope ids must match `[A-Za-z0-9_-]{1,64}` (real ids are UUIDs); the legacy `characterId` string in a P02-0a stamp is deliberately not shape-checked so earlier entries and tests are unaffected.
9. **Unscoped ancestors.** A scoped page may have the unscoped Worlds list as an ancestor (`worlds.list`, no params). No other unscoped route can appear in a trail.
10. **`resolveTask` returns `null`** for a route that is not a task page (unscoped, public, a redirect, not-found). The plan said "never null"; this is the one deviation, and it is the only coherent answer where there is no execution scope.
11. **Extra legacy keys.** The plan named four. `itemsSearch` and `definitionsSearch` also exist in production (`useItemsBackPath`) and are adapted the same way. Precedence: `charactersReturn`, `reviewSearch`, `itemsSearch`, `definitionsSearch`, `worldSearch`, `returnTo`.

### 1.2 Validation contracts (correction)

**Root and destination consistency.** `validateTask` checks every trail entry and the list descriptor against two things: the route's actual scope and parameter contract (a known route, the same scope, exactly that pattern's id parameters, the task's own scope id), and the destination's own `allowedRoots`, which must contain the task's root. A task is not forced to equal containment: a Parties task may pass through a character page because the character routes list `parties` among their roots, but it may not carry an Items detail, whose roots do not include it. Reproduced at baseline `a72b9c5` (both were accepted): a Characters task with the Items list as its list, and a Parties task with an Items detail in its trail.

**List state.** A persisted list descriptor is `{ route, search }`. `route` must be a list route that has a contract in `listState.ts` and allows the task's root; `search` is empty or a `?` query satisfying that contract. The contracts follow the real producers (`useCharactersBrowseState`, `useWorldBrowseState`, the Review queue and item-definition filters):

| List route | Keys (value rule) |
|---|---|
| `characters.browse` | `type` (`npc` or `player_character`), `q` (text, at most 200 characters, no control characters), `hidden` (`1`), `cursor` (opaque token of the backend's unpadded Base64url alphabet `[A-Za-z0-9_-]`, at most 2048 characters, any number of repeats) |
| `campaign.world` | `category` (a World category: `location`, `character`, `organization`, `religion`, `item`, `event`), `q`, `hidden`, `cursor` (as above) |
| `review.queue` | `status` (the Review statuses, now shared from `utils/reviewStatus.ts`), `type` (a name, at most 60 characters as the endpoint allows) |
| `itemDefinitions.list` | `category` (a name, at most 100 characters as the endpoint allows), `homebrew` (`1`) |
| `characters.index`, `items.list`, `parties.list`, `quests.list`, `sessions.list`, `knowledge.list`, `worlds.timelines` | none (empty list state only) |

A key repeats only where the contract says so. Perspective and scope keys (`character_id`, `party_id`, campaign, world and timeline ids), `returnTo` and any key a page does not produce are in no contract; the Quests and Knowledge lists carry their perspective in the query, so their list state is empty. `q` is the only free text: it is permitted because the plan whitelists browse queries, it is bounded, and it stays in `history.state` (it already travels in router state as `worldSearch`).

**Cursor and size policy (second correction).** The list API pages forward only, so both browsers keep the whole page trail in the address, one cursor per next-page action, with no producer cap; Previous drops the last. The validator therefore has no per-key cap on the number of cursors (the first correction's limit of 20 cursors of 512 characters rejected reachable state and backend-valid cursors, which would have reset the person's browse position on return). A cursor is checked structurally, for the unpadded Base64url alphabet `[A-Za-z0-9_-]` that `encode_cursor` emits (`base64.urlsafe_b64encode(...).rstrip("=")`; padding and `.`, `=`, `~`, `+`, `/` are rejected) and for the backend's 2048-character bound (`api/pagination.py`, `Query(max_length=2048)`). This is not verification of a cursor's payload, keyset or freshness: it is never decoded, the backend's `decode_cursor` stays authoritative, and the string is stored and returned unchanged. The only size policy is a total resource bound on the whole persisted query, `MAX_LIST_SEARCH` = 524,288 UTF-16 code units (JavaScript `string.length`, not bytes; about 255 maximum-length cursors with their `cursor=` keys). Over it, the descriptor is rejected (the return falls back to the route default), never truncated; it is also the syntax bound of `isSafeSearch`, replacing the earlier 1024-character limit that would have rejected a single long cursor. This is a finite resource bound, not unlimited preservation: browse position is preserved up to it, over it the return falls back to the route default, and no browser limit is assumed or inferred. No paging limit is introduced and no pagination is reset below the bound. The same alignment fixed two name bounds: Review `type` 60 (was 64) and item-definition `category` 100 (was 64, found while checking the backend); the accepted character set for those names is unchanged.

**Invalid descriptors are rejected, never normalized**, by every reader. In history, an invalid `list`, or a trail entry that fails either check, makes `validateTask` return null, so the entry falls back to a legacy key and then to the route default. In the legacy adapters, a `worldSearch`, `reviewSearch`, `itemsSearch` or `definitionsSearch` that fails its list contract is ignored and the next key is tried; a `charactersReturn` whose browse query fails is ignored (the first P02-1 commit trimmed such a query to empty, which is removed). P02-0b's `readCharactersReturn` is unchanged and still decides which address is a valid Characters return; the adapter applies the list contract on top. The accepted bounded deviations keep their fallback contracts: `resolveTask` returns null where there is no execution scope or task root, and a trail over 4 entries is rejected as tampered.

### 1.3 Shared guarded-transition behavior

`isGuardedTransition(transition, options?)` is true for, in order of evaluation:

1. a pathname change (after the permission-loss exemption);
2. a change of committed context at the same path (section 1.1 rules 3 to 6);
3. a query-only change (`search` differs) that `options.disposingQuery(current, next)` declares disposing.

A query-only change is therefore unguarded unless the editor or dialog would unmount, the data scope or perspective would change, or an unresolved operation would lose its owner, and only a caller that says so is asked. `useUnsavedChangesGuard` stores the options in a ref updated in a layout effect, so an inline predicate is never stale and does not re-register the blocker. `PickerRecordTime`'s own blocker calls the predicate with no options (see 3.3).

## 2. Route inventory

The inventory is `ROUTE_METAS` in [routeMeta.ts](../portal/src/navigation/routeMeta.ts): **91 patterns**. `routeMeta.test.ts` takes the production patterns from `App.tsx` itself (it calls the hook-free `App` component, reads the `<Routes>` element and passes its children to react-router's `createRoutesFromChildren`), and fails when a production pattern has no entry or an entry matches no production pattern. There is no second, hand-maintained route table in the test. Matching in `matchRouteMeta` is react-router's own ranking over the same patterns, so route matching and permissions are untouched: nothing in `App.tsx` or any route element changed.

Coverage limits (correction). The test now also fails on a production pattern listed twice, checked on the raw list before the set comparison discards multiplicity (with a self-check of the detector). That is exact-string duplication only: two different patterns that can match the same URL are not analysed. Which entry wins for such URLs is react-router's ranking; the ranking tests pin a handful of selected cases (a static `member-preview` segment beside a claim id, `world/location/new` beside `world/:category/:entityId`, the splat fall-throughs) and do not prove every URL resolves to the intended entry.

| Scope / default root | Patterns |
|---|---|
| Unscoped, no task root (public, login, account, settings, campaigns, platform accounts, redirects) | 13 |
| Unscoped, root `world` (`/worlds`, `/worlds/new`) | 2 |
| World-scoped, root `world` (`/worlds/:worldId…`) | 10 |
| Campaign: `campaign` 5, `world` 13, `review` 1, `characters` 11, `items` 7, `sessions` 8 (sessions and events), `parties` 4, `quests` 3, `knowledge` 5, `access` 3 | 60 |
| Campaign, no root (the five legacy section redirects and the campaign not-found splat) | 6 |
| **Total** | **91** (9 are `redirect` kind) |

`ask` and `world-times` have no Navbar root of their own in the plan's `NavRoot`; `ask` uses `campaign` and `world-times` uses `campaign` (allowed also from `world`, `parties`, `sessions`). `events/*` default to `sessions`. These are safe defaults, not product decisions, and are listed so they can be corrected.

`defaultRoot` and `allowedRoots` are descriptive in P02-1: nothing in the UI reads them yet (P02-2 onward does). Parties routes allow `parties`, `characters`, `sessions` and have no Campaign Home ancestor, which `routeMeta.test.ts` checks.

## 3. Guard-caller audit

### 3.1 Count

`useUnsavedChangesGuard(` appears 19 times in `portal/src` outside tests: **18 call sites plus the hook's own definition.** The plan's "19" counts the definition. Beyond them there is one more blocker, `PickerRecordTime` (it installs its own only when no page guard is mounted). Several call sites are shared: `ContentCreatePage` and `ContentEditPage` host the location, organization, religion, dungeon, NPC/PC, quest, knowledge and item create and edit pages, and `staged/UnsavedInputGuard` hosts three workspaces.

### 3.2 Per-caller classification

"Query keys" are keys the page or its staged hook reads from `location.search`. "Scope" keys select data or perspective. "Disposing" keys unmount the editor or dialog. "Harmless" keys keep every editor mounted. "Ownership" says who holds pending, unknown-outcome and confirmed-but-unread operations across a query-only change.

| # | Caller (file:line) | Route(s) | Scope / perspective keys | Disposing keys | Harmless query changes | Ownership of pending and recovery | Configuration or follow-up |
|---|---|---|---|---|---|---|---|
| 1 | `CampaignSetupPage.tsx:275` (`CampaignDetails`, step 3) | `/campaigns/new` | `worldId`, `timelineId` (the wizard's world and timeline; they select what the campaign will be created in) | **`worldId`, `timelineId`**: each step is a different component, so the "Back to timeline choice" link (`?worldId=…`) unmounts the form and silently dropped typed input | none | `useAuthoringMutation` (`create-campaign:<timelineId>`) is local to `CampaignDetails`; an in-flight or unknown create is **not** part of `isDirty` | **Declared** `queryKeysChanged("worldId", "timelineId")`, tests in `campaignSetup.test.tsx` (5, including a deferred create that keeps its owner through a refused step change). Follow-up F-1 for the pending state |
| 2 | `CampaignSettingsPage.tsx:168` | `/app/:c/settings` | none | none | any (the page reads no query) | `save` and `archive` mutations are local; not in `isDirty` | none |
| 3 | `CharacterBuildPages.tsx:445` (new build) | `/app/:c/characters/:id/builds/new` | none (route params only) | none | any | `useAuthoringMutation`, `useConfirmedRefresh` local | none |
| 4 | `CreateTimelineBranchPage.tsx:111` | `/worlds/:w/timelines/:t/branch` | none | none | any | local mutation | none |
| 5 | `CalendarCreation.tsx:45` | `/worlds/:w/calendars/new` | none | none | `section` (`basics`, `months`, `review`): every `SectionPanel` stays mounted and only `hidden` changes; the draft lives above them | local mutation | Covered by the existing "moves between steps freely, but asks before a draft with changes is abandoned" test |
| 6 | `CreateTimelinePage.tsx:80` | `/worlds/:w/timelines/new` | none | none | any | local mutation | none |
| 7 | `CreateWorldPage.tsx:128` | `/worlds/new` | none | none | `returnTo` (read through `safeReturnTarget`; it only decides where a successful save goes, and the form stays mounted) | local mutation | none |
| 8 | `ContentCreatePage.tsx:130` | create pages for location, organization, religion, dungeon, NPC, PC, quest, knowledge, item | none (reads `location.state`, not query) | none | any | local mutation | none |
| 9 | `EditTimelinePage.tsx:92` | `/worlds/:w/timelines/:t/edit` | none | none | any | local mutation | none |
| 10 | `EditWorldPage.tsx:96` | `/worlds/:w/edit` | none | none | any | local mutation | none |
| 11 | `EventPages.tsx:119` (`RecordEventPage`) | `/app/:c/events/new` | none | none | any | local mutation, `useConfirmedRefresh` | none |
| 12 | `KnowledgeClaimPage.tsx:473` (page-local `UnsavedInputGuard`) | `/app/:c/knowledge/:id` | **`character_id`, `party_id`** (the claim is read under that perspective; the page also builds links that carry them) | **`character_id`, `party_id`** (`PERSPECTIVE_QUERY_CHANGED`, P02-3) | `section` (all sections stay mounted; `useClaimNavigation`) | claim edits, `useConfirmedRefresh` and write recovery are held by the page, mounted across a query change | **Declared in P02-3 (F-2 closed for this page, see 3.4).** The boundary shows "Loading knowledge" while the claim is re-read under a new perspective, which unmounts the editor. The page's own clean-up of a revoked party runs under `runPermissionLossCleanup` |
| 13 | `ContentEditPage.tsx:282` | edit pages for the same families as 8 | none (reads `location.state`) | none | any | local mutation; stale-write hold stays with the page | none |
| 14 | `PartyPages.tsx:336` (`PartyForm`: new and edit) | `/app/:c/parties/new`, `/parties/:id/edit` | none | none | any | local mutation | none |
| 15 | `SessionDetailPage.tsx:237` | `/app/:c/sessions/:id` | none (`?section=participants` belongs to the Run route, a different page) | none | any | local mutation, `useConfirmedRefresh` | none |
| 16 | `SessionFormPages.tsx:69` (`CreateSessionPage`) | `/app/:c/sessions/new` | none | none | any | local mutation | none |
| 17 | `WorldTimesPage.tsx:150` | `/app/:c/world-times` | none | none | any (reads no query) | **The guard owns it**: `isDirty = dirty || pending || unresolved`, so an in-flight or uncertain write holds a departure | none. The picker dialog is hosted here (see 3.3) |
| 18 | `staged/UnsavedInputGuard.tsx:8`, hosted by `QuestWorkspace`, `ItemWorkspace`, `WorldRecordWorkspace` | `/app/:c/quests/:id`, `/items/:id`, `/world/:category/:id` | Quest: **`character_id`, `party_id`** (`useQuestPartyPerspective`). Items and World record: none | none declared | `section` in all three (staged sections stay mounted) | drafts and receipts are held by the workspace, mounted across a query change; item time picker holds via `useNavigationHold` | Quest: **inspected in P02-3, not declared.** `QuestWorkspace` neither reads nor sends `character_id`/`party_id` (it only carries them to its back link), so a change disposes none of its input; `useQuestPartyPerspective` is used by the quest *reader* and list, which have no draft guard. Pinned by a test |
| – | `PickerRecordTime.tsx:54` (blocker; only when no page guard is mounted) | every `WorldTimePicker` host | none | none | any | the open recording is a navigation hold: it makes the page guard (or its own blocker) ask | Default, no options (3.3) |

No caller other than #1 was found whose query-only change unmounts its own editor. That is a finding about the 18 call sites reviewed, not a general guarantee: see 3.4.

#### Row 1: confirmed-but-unread ownership (correction)

The first P02-1 commit released the guard in `onSuccess`. After the server confirmed a create, the page still owned the created id and the "Open the campaign" recovery action, but a step change could drop them silently, and the confirmation dialog was not rendered in that state, so a held navigation would have had no question to answer. Now:

- The guard is active while `createdId !== null && !listed`, so it covers the confirming read and every recovery state.
- The question ("Leave before the campaign is confirmed?", Stay or Leave) is rendered in the created and recovery states.
- Stay keeps the created id, the recovery action and the entered values (all component state).
- Leave abandons only this page. Nothing on the page can send the create again once it is created, and a test asserts exactly one POST through every path.
- A successful read that lists the campaign releases the hold just before the deliberate navigation to the new campaign, so that navigation is never asked.
- Refresh outcomes inspected: a rejected read sets `refreshFailed`; a read that resolves `false` (superseded, aborted or unauthenticated) or applies a bootstrap that does not list the campaign leaves `success && !listed`. Both show the recovery action under the same hold, and the recovery action calls `refresh()` again on the retained id.

### 3.3 Picker hosts and their enclosing guards (traced from source)

`PickerRecordTime` holds a navigation while a recording is open (`useNavigationHold`) and installs a blocker only when no page guard is mounted (`useHostGuard`). It evaluates `isGuardedTransition` with no options. Each `WorldTimePicker` host, traced to its page:

| Picker host | Hosted by | Enclosing guard | Query-only unmount? |
|---|---|---|---|
| `NpcRuntimePanel`; `RelationshipEditor` (through `RelationshipsPanel`); `OrganizationMemberEditor` (through `OrganizationMembers`) | `WorldRecordWorkspace`, inside its `SectionPanel`s | `UnsavedInputGuard` (row 18) | No. `SectionPanel` is always mounted and only `hidden` changes; `section` is the only query key the workspace reads |
| `ItemWorkspace` time picker | `ItemWorkspace` | `UnsavedInputGuard` (row 18) | No, same staged panels |
| `WorldTimesPage` | the page | its own guard (row 17) | No query read |
| `RecordEventPage` | the page | row 11 | No query read |
| `CampaignClockCard` on Campaign Home | `CampaignHomePage` | none; the picker's own blocker | No query read by the page or the card; no query-only unmount condition identified |
| `CampaignClockCard` (compact) and `TravelSection` on Run session | `SessionRunPage` | none; the picker's own blocker | `section` only. `RunSectionPanel` is always mounted and the card sits outside the panels, so a section change unmounts neither |
| Party members picker | `PartyMembersPage` under `PartyDetailPage` | none; the picker's own blocker | No query read |

The picker's own blocker therefore guards pathname and context changes only, and no query-only unmount was found for any host. This is a trace of the current source, not a proof for a future host.

### 3.4 What is and is not claimed

- Claimed: every one of the 18 call sites was classified from source; two disposing queries (row 1, and the Knowledge claim page's `character_id`/`party_id` from P02-3) were found, declared and tested; staged `?section=` is harmless in the three guarded workspaces, the calendar steps and the knowledge claim page because their sections stay mounted.
- **Not claimed:** a complete query-safety guarantee. Open items, none of which is repaired here:
  - **F-1.** Most pages keep a pending or unknown-outcome write in a local `useAuthoringMutation` and exclude it from `isDirty` (only `WorldTimesPage` includes it). A pathname departure during an uncertain write therefore asks nothing on those pages; this is existing behavior, unchanged. Row 1 no longer has this gap once the create is confirmed (see its correction above); before confirmation the typed values still make the form dirty.
  - **F-2 (closed in P02-3).** *Knowledge claim:* the boundary re-reads the claim under the address's `character_id`/`party_id` and shows a loading placeholder meanwhile, so a deliberate change disposed the editor and its drafts without a question. The page's guard now declares both keys (`PERSPECTIVE_QUERY_CHANGED`): a deliberate change asks (Keep editing keeps the draft, the address and the reads; Discard re-reads under the new perspective), and a section, an unrelated key or an unchanged value never asks. The page's own clean-up of a party that is no longer authorized (`CampaignKnowledgeDetailPage.dropRevokedParty`) is permission loss and runs inside `runPermissionLossCleanup(location.key, …)`, whose exemption covers exactly that REPLACE of that entry for the duration of the call, so it is never held and every other navigation stays guarded; the real-page test shows the address cleaned, one REPLACE, no question. *Quest:* inspected and **not** declared, because the editor does not consume those keys (see row 18). `useQuestPartyPerspective`'s stale-party clean-up is unchanged: its consumers (the quest reader and list) have no draft guard, so nothing can hold it; if one is added, the clean-up must use the same exemption.
  - **F-3 (closed by tracing).** The picker hosts were traced in 3.3; none has a query-only unmount condition today.
  - **F-4.** `CharacterRecordSections` mounts only the shown section (`?section=`) and is not a guard caller. Its surfaces are read-only today: the relationships reader (one local disclosure toggle), the inventory panel and the parties panel contain no form, mutation or picker. If an editor is introduced there, `section` becomes disposing and the editor's host must declare it.
  - The guard does not distinguish a user-initiated query change from a page's own REPLACE of its address. A page that rewrites a declared key itself while dirty would be asked. Row 1 does not do this: its steps change only by user links.

## 4. Verification summary

Recorded in the ledger row for this checkpoint. In short: new pure tests for the contracts, route coverage against the real `App.tsx`, legacy compatibility, the predicate truth table, and five real-caller tests for the setup wizard's declared disposing query (question, Stay, Discard, clean form, an undeclared key, and a deferred create whose outcome still lands after a refused step change; they wait on processed UI and router outcomes, with no sleeps); the P02-0a predicate, layout and guard suites pass unchanged. The disposing-query tests were also run with the declaration removed and failed (2 of 5), so they cannot pass vacuously. The harmless-query side is represented by the existing New calendar test cited in row 5.

## 5. Not part of P02-1

Shared Breadcrumb adoption (P02-2); a selection provider, new persistence or any change to campaign or perspective behavior (P02-3); Navbar or menu redesign and task reset (P02-4/5); the New character chooser (P02-0c, PD-8); the F-1 to F-4 items; any backend, authorization, NPC/PC or database change. No manual acceptance is recorded.

## 6. Selected-context ownership and the route/guard picture after P02-3

This section records what P02-3 changed in the route and guard picture. Sections 1 to 5 are kept as written for P02-1.

- **Route scope versus selection, by route family.**

| Route family | Execution scope | Retained selection is | Committed by |
|---|---|---|---|
| `/app/:campaignId/*` with the campaign in the bootstrap | The route campaign (its world and timeline) | Replaced by the route campaign on arrival (`adoptRouteCampaign`); only this campaign's perspective is read | `CampaignLayout` (layout effect on the accepted location) |
| `/app/:campaignId/*` with a campaign the bootstrap does not list | None (the id is not echoed) | Not shown, not adopted; a *selected* campaign that disappears from an authenticated bootstrap is cleared | `SelectedContextReconciler` |
| `/worlds/:worldId/*` | The confirmed world (and timeline) | Shown as **Selected campaign** only if it belongs to them; otherwise cleared once the world is confirmed | `SelectedContextReconciler` |
| `/campaigns`, `/settings`, `/account`, `/platform/accounts`, `/admin/accounts`, `/worlds`, `/worlds/new` | None | Retained as is (validated against the bootstrap); sidebar targets it; nothing is guessed | `SelectedContextReconciler` (validates, restores from and stamps the entry) |

- **Stamp and restore ownership (history-retention correction).** Disjoint by route family, one writer per entry: `CampaignLayout` for `/app/:campaignId/*` with the campaign in the bootstrap; `SelectedContextReconciler` for every other authenticated route (World, unscoped, and a campaign id the bootstrap does not list, where it deliberately writes nothing). Both write only through `replaceOwnEntry`. The reconciler restores from the entry on a reload, on POP and on the first location it sees (`restorableSelection`), reconciles, and mirrors only when its pass changed nothing, so a change re-runs the pass with the settled selection. **World-only context** (no campaign, a World): restored as an attempt: one `fetchWorld` request and result per restoration (not the shared path-keyed read hook, whose retained snapshot an attempt could otherwise consume), owned by its history entry (key and state), the selection revision and the owner; applied only while `owns` holds, so a newer same-address entry, an unrelated REPLACE, a deliberate select-then-clear (or A to B to A) and a user or session change each supersede it; the entry\'s record is left untouched while it is outstanding. Stamps are decided from the router\'s own copy of the entry. Stamping routes added to the inventory: every authenticated pattern outside `/app/:campaignId`. Entries stamped by the previous commit (campaign routes only) restore as before; entries of other routes carry no stamp and so restore nothing, which is the pre-correction behavior.
- **Guard.** Both blockers still use the one `isGuardedTransition`. The committed context now carries `campaignId`, `worldId`, `timelineId` and `routeScoped: true` from the campaign layout; a versioned stamp naming another scope is "no stamp" for the guard exactly as it is for the layout. The perspective-only stamp is still honored. Nothing else about the blockers, `beforeunload` or the dialogs changed.
- **Unguarded by design.** A same-path change of the *retained* selection on a World or unscoped page is not a guarded transition (no committed owner there); those pages read nothing under it. This is recorded as a limit in UI_DESIGN §4.8.2.
- **Internal REPLACE paths that touch the context** (each with the owner that decides whether it may run): the layout's stamp (same entry, same context, never guarded), its revoked-address clean-up (`runPermissionLossCleanup`), `dropRevokedParty` (`runPermissionLossCleanup`), a page rewriting its own query (carries state, never asks for a context).

## 7. Deliberate Infobox selection after P02-5 (PD-6)

- **No new guard, caller or mechanism.** A deliberate Infobox selection asks the router for one destination, so the one blocker (`isGuardedTransition`) decides exactly as for any link: the pathname change, or, for a perspective chosen on the page that already shows its character, the committed-context difference. No caller's classification in section 4 changes. `CampaignLayout.requestPerspective` no longer navigates to the same path with a stamp; it navigates to `/app/:c/characters/:id` (or `/characters/all` for none), with `{ task, ctx }` built fresh, so the page's query is not carried (the F-2 `character_id`/`party_id` cleanup it used to do is now simply not carried).
- **Callers that are asked by a perspective change.** All 19 callers keep the answer they gave before (dirty, any hold, a page's own unresolved-write rule). What changed is the destination, not who asks. Pages whose perspective-carrying query (`character_id`, `party_id`) used to be removed in place now are left entirely.
- **Not a transition.** Bootstrap refresh, perspective loss, Back/Forward restoration and stamp-only REPLACEs are unchanged (sections 5 and 6) and none starts a task or navigates.
- **Open item, unchanged.** The guard compares context only where the campaign layout is the committed owner (section 6); a campaign, World or timeline selection on a World or unscoped page is guarded by its pathname change, which the destination always differs by.
- **Announcement and heading focus (P02-5 correction).** Neither adds a guard, a caller or a hold. The choice carries `state.selection` (level and id only) on the same navigation; `SelectionArrivalProvider` reads it from the router's committed locations (a PUSH begins an arrival, a same-address REPLACE keeps it, anything else ends it), announces after the selection store names the choice, and lets the destination's settled boundary focus its heading once. No guard decision reads `state.selection`; Stay never reaches it; no pending, unknown or confirmed-but-unread ownership is touched. The shell remounts on a campaign scope change, so the tracker also reads the location it is created under. Second correction: the arrival is also bound to the route its note names (`selectionScope`), and a REPLACE keeps it only as the entry's own stamp (same path/hash/query but for `section`, state identical except `ctx`); the Navbar menu's campaign list adds the note for a campaign other than the one in force. None of these is a guard input, and the announcer's withdrawal touches no hold, pending, unknown or confirmed-but-unread ownership. Third correction: announcement and focus share `contextEligible`; the menu's `useAcceptedNavigation.begin` also records the activated control (`navigation/activationOwner.ts`), released when the request ends, so the accepted arrival may take focus from that control; this adds no guard input, caller or hold, and the request's existing accepted/Stay/supersede/fail contract is unchanged. `usePageArrival` and the selection arrival recognise a stamp by the writer's in-memory mark (`markStamp` in `replaceOwnEntry`, `stampRoot` in observers; fourth correction), and the activation hand-off is bound to the accepted `NavigationAttempt`'s location key rather than a pathname. Neither is a guard input, caller or hold. Fifth correction: the staged section normalization is marked the same way (`markNormalization`), no unmarked REPLACE keeps a selection arrival, and `ConfirmDialog` no longer takes focus back from a live control that already has it; none adds a guard input, caller or hold. Sixth correction: `ConfirmDialog` and `FormDialog` read focus ownership before the native close; no guard input, caller or hold, and no close reason is added.

## 8. The character shell after P02-6

Routes now rendering the shared breadcrumb (`routeMeta` ids): `characters.detail`, `world.record` (a character), `characters.inventory`, `characters.builds`, `characters.builds.new`, `characters.portrayal`, `characters.edit`. `characters.index` is a REPLACE to `characters.detail` when a perspective is selected and the browser otherwise. No route was added or removed (`routeMeta.test.ts` unchanged and passing).

| Entry | Task carried to the record | Section links | Notes |
|---|---|---|---|
| Characters browser card | `charactersReturn` (legacy adapter) gives a Characters task with list state | `retainedState` | filters survive in the root crumb |
| Navbar / Infobox / Selected character | fresh `{task: characters}` | `retainedState` | |
| Parties members page (GM) | `useTaskLinkState` (Parties task, trail list + party) | `retainedState` | |
| Session roster | `useTaskLinkState` (Sessions task, trail session) | `retainedState` | the rest of Sessions is §9 (P02-7a) |
| World browser / organization members | `worldSearch` legacy / `useTaskLinkState` | `retainedState` | |
| Relationship counterpart (character) | `useTaskLinkState` | `retainedState` | other record kinds unchanged |
| Direct entry / tampered state | none (defaults) | none | |

Guard audit (F-4 revisited): `CharacterRecordSections` remains read-only and not a guard caller. New guard callers: none. `ContentEditPage` (character edit), `CreateCharacterBuildPage`/`BuildForm`, `NpcPortrayalPage` and `WorldRecordWorkspace` keep their existing declarations; their breadcrumb ancestors are plain links covered by the pathname predicate (a test drives a dirty new-build form: Stay keeps draft, task and entry; Leave goes). Query keys: `section` on the record remains retaining (nothing editable is mounted there). If an editor is ever added to a record section, `section` becomes disposing and its host must declare it.

**Correction after review of P02-6 (New PC).** `CharactersCreateAction` (the existing New PC link, `canon.edit`, `/characters/pc/new`, `charactersReturn`) is shared by the Characters header and `CharacterSheetRoutePage`. No route, guard, query key or read was added; the inventory-only route renders none of it.


## 9. Sessions and Run after P02-7a

Routes now rendering the shared breadcrumb (`routeMeta` ids): `sessions.new`, `sessions.detail`, `sessions.run`, `sessions.encounters.new`, `sessions.encounters.detail`, and `events.detail` when the entry has an origin. `sessions.list` is the top of its task and renders none. `sessions.encounters.new` and `sessions.encounters.detail` now declare `sessions.run` as their parent in `routeMeta`; no route was added or removed (`routeMeta.test.ts` passing).

| From | To | State carried |
|---|---|---|
| Sessions list | session, Schedule a session | `useTaskLinkState` |
| Sessions list | Run | `continuedStateVia` (list, then the session as Run's declared parent) |
| Session | Run (participants) | `useTaskLinkState` |
| Run (stage, section and in-page links) | the same page, other section | `retainedState` (none after a direct entry) |
| Run, review | encounter, prepare, session, event, character | `useTaskLinkState` |
| Prepare encounter | the new encounter | REPLACE with `retainedState` |
| Event page | character, party, session, related and correcting/replacing events | `useTaskLinkState({ requireOrigin })`; none after a direct entry, where the page keeps its **Campaign Home** link |
| Schedule a session | Sessions list (Cancel, success) | `useAncestorLink("sessions.list")` |

Legacy keys: `sessions.list` has no list state, so no legacy key is written or read for Sessions. The `returnTo`, `charactersReturn`, `worldSearch` and `reviewSearch` adapters are unchanged.

Guard audit: **no new guard caller, hold or declaring key.** `SessionDetailPage` (row 15) and `CreateSessionPage` (row 16) keep their declarations; their breadcrumb ancestors are plain links covered by the pathname predicate. The Run page's forms are not page-guarded (existing; pending and unknown-outcome writes are held by their `useAuthoringMutation` owners, and the pickers by `PickerRecordTime`'s blocker). `useRunNavigation` now delegates to `useStagedNavigation`, which keeps the entry's state when it normalizes `?section=`; `section` stays the only query key and every `RunSectionPanel` stays mounted, so it disposes nothing. `EncounterPages` and `RecordEventPage` are unchanged as guard callers.

Reads: none were added. Labels come from the session read of the session page, the Run page and the two encounter pages, and from the event page's own read; the member's session read stays member-shaped. Remaining exceptions: `events.new` keeps its **Campaign Home** breadcrumb (it is reached from Campaign Home's tools), a direct entry to `events.detail` keeps its **Campaign Home** link, the World event page's `EventExplanation` links carry no task (P02-7d) *(Superseded by P02-7d, which adopted these; see the reconciliation record R-1/R-2. Kept as written at that checkpoint.)*, and Home and other-family links to sessions carry none.


## 10. Quests and Knowledge after P02-7b

Routes now rendering the shared breadcrumb (`routeMeta` ids): `quests.new`, `quests.detail` (reader; workspace for a task of its own), `knowledge.new`, `knowledge.detail`, `knowledge.memberPreview`, `knowledge.memberPreview.claim`. `quests.list` and `knowledge.list` are tops of their tasks. No route was added or removed (`routeMeta.test.ts` passing).

| From | To | State carried |
|---|---|---|
| Quests list / Knowledge list | record, New quest / New claim, a claim's subject | `useTaskLinkState` |
| Quest workspace, claim page | their own sections and stages | `retainedState` (`nav.linkState`; none after a direct entry) |
| Claim page | replacement claim, subject, guidance to another record | `useTaskLinkState({ requireOrigin })` |
| Create page | the created record (REPLACE) | the entry's task (`ContentCreatePage taskBreadcrumb`) |
| List filters, party choice, Member preview member choice | the same page | `retainedState` on the same entry; no other state |
| Revoked-party cleanup | the same claim | `retainedState` under `runPermissionLossCleanup` |
| `/quests/:id/edit`, `/progress`, `/knowledge/:id/edit`, `/audience` | the record at the matching section | the entry's state |

Legacy keys: `quests.list` / `knowledge.list` have no list state; `reviewSearch` / `returnTo` adapters are unchanged and the Review queue keeps its own return for a quest opened from it.

Guard audit: **no new caller or declaring key.** Row 12 (`KnowledgeClaimPage`) keeps `character_id` / `party_id` disposing and its permission-loss path (a test: the cleanup is not asked and keeps the task; a deliberate change asks and Stay keeps the task). Row 18 (`QuestWorkspace`) stays undeclared, re-inspected: its editors read neither key, `section` is the only query it reads, every section stays mounted. `useQuestPartyPerspective`'s own REPLACEs (party choice, stale party) are used by the list and reader only, which have no draft guard. `ContentCreatePage` (rows 8) is unchanged as a guard caller. `useClaimNavigation` delegating to `useStagedNavigation` changes no query key.

Reads: none were added. The P02-7a `continuedStateVia` follow-up (§4.8.7) validates its parent against the destination's declared ancestors and the stored-task validation, and returns null otherwise.

Remaining exceptions: the World event page and the World record workspace for non-character categories keep their links (P02-7d) *(Superseded by P02-7d, which adopted these; see the reconciliation record R-1/R-2. Kept as written at that checkpoint.)*; a quest or claim opened from Campaign Home or another family's pages without task state shows the route defaults; `MemberPreviewShell`'s in-page **Return to Knowledge** / **Back to Member preview** links keep their plain hrefs.


## 11. Items and Item definitions after P02-7c

Routes now rendering the shared breadcrumb (`routeMeta` ids): `items.new`, `items.detail` (the workspace opened from the inventory), `items.edit` (inside a task), `itemDefinitions.new`, `itemDefinitions.detail`. `items.list` and `itemDefinitions.list` are tops of their tasks. No route was added or removed (`routeMeta.test.ts` passing).

| From | To | State carried |
|---|---|---|
| Item inventory | item, New item | `continuedListState` (task + `itemsSearch`) |
| Item definitions catalog | definition, New item definition | `continuedListState` (task with the recorded list when its contract accepts the query, + `definitionsSearch`) |
| Item workspace | its sections and stages | `retainedState` (+ the legacy keys); none added for the World origin |
| Item workspace | Edit item | `useTaskLinkState({ requireOrigin })` + the legacy keys + `returnTo` |
| Edit page | the item page (Save, Cancel) | the entry's task (`itemTaskOf`) + the legacy keys; `announce` on Save |
| Create page | the created item (REPLACE) | the entry's task (`ContentCreatePage taskBreadcrumb`) + the legacy keys |
| Inventory | the catalog | nothing (starts the catalog's own task) |

Legacy keys: `itemsSearch` and `definitionsSearch` are still written (and read by the pages' own Back, Cancel, delete and create destinations through `useItemsBackPath` / `useDefinitionsBackPath`) and adapted to a task by `adaptLegacyReturn`; `legacyKeys` now emits them beside any task that records the matching list, so the readers are not migrated away yet. The `ItemHeader` inventory breadcrumb markup was removed with its last user.

Guard audit: **no new caller or declaring key.** Row 18 (`ItemWorkspace`'s `UnsavedInputGuard`) re-inspected: it reads only `section`, every section stays mounted, so it stays undeclared. Rows 8 and 13 (`ContentCreatePage`, `ContentEditPage`) read `location.state`, not the query, as before. `ItemDefinitionFormPage` has no guard and none was added. The `useItemNavigation` rewrite over `useStagedNavigation` changes no query key and adds the entry stamp to its normalizing REPLACE.

Reads: none were added. The definition catalog's filters are replaced in place by the page itself, as before (no router state is carried by that REPLACE; the list is the top of its task).

Remaining exceptions: the World item page (`origin="world"`, **Back to World**), the character and party inventory panels' links to it, and an edit page reached from the World page keep their links (P02-7d) *(Superseded by P02-7d, which adopted these; see the reconciliation record R-1/R-2. Kept as written at that checkpoint.)*; an edit page reached by a direct entry or by the item page's `returnTo` alone keeps its single back link; the definition catalog's own filter REPLACE and create destination are unchanged.

## 12. World authoring and reader after P02-7d

Routes now rendering the shared breadcrumb (`routeMeta` ids): `world.record` (the editors' workspace for non-character categories, and the place, organization, religion, event and item readers, including the World item workspace) when the entry names an origin; `world.location.edit`, `world.dungeon.edit`, `world.dungeon.area.edit`, `world.organization.edit`, `world.religion.edit` inside World's own task; `world.location.new`, `world.dungeon.new`, `world.organization.new`, `world.religion.new` when the arrival names an origin. `campaign.world` is the top of World's task. Not changed: `worlds.*` (standalone), `world.record.provenance/history`, character on `world.record` (P02-6 rule), `NpcAuthoringPages`.

| From | To | State carried |
|---|---|---|
| World browser | record, New place/dungeon/organization/religion/NPC | `continuedListState` (task with the recorded list when its contract accepts the query, + `worldSearch`) |
| Record workspace | its sections, stages, area/dungeon links, guidance | `taskOf(...).state` merged over `pickWorldReturnState` (so `worldSearch` and `reviewSearch` both survive) |
| Record workspace | Edit | the above + `continuedState` (World task only) + `returnTo` |
| Edit page | the record (Save, Cancel) | `worldEditNavigation`: the record's crumb state (task cut back to before the record) over the carried legacy keys; `announce` on Save |
| Reader / workspace | related record (parent, HQ, religion, member, relationship, event explanation, Open the event record) | `useWorldReturnState` = `useTaskLinkState({ requireOrigin })`, else the older `worldSearch` behavior |
| Character / party inventory | World item | the same hook (task or nothing) |

Legacy keys: `worldSearch` and `reviewSearch` are still written (`legacyKeys`) and read by the pages' own destinations; `adaptLegacyReturn` turns them into a task for the breadcrumb. An edit page entered with only legacy keys keeps its single links (`inWorldTask` requires the entry's own task).

Guard audit: **no new caller or declaring key.** The workspace's `UnsavedInputGuard` (row for `WorldRecordWorkspace`) was re-inspected: it reads `section`, every section stays mounted, so it stays undeclared. `ContentCreatePage` / `ContentEditPage` read `location.state`, not the query, as before. Permission-loss cleanup, the retained-input registry and the lifecycle/source/member editors are untouched.

Reads: none were added. `useWorldDetail` now also returns the authority captured at request start (used only for labels).

Remaining exceptions: the standalone `/worlds/*` pages; the character on `world.record` opened from World, the Review queue or directly; delete destinations; an edit entered with only legacy keys or a Review-queue task.

Correction after review: (1) `hasTaskEvidence` separates task evidence from a return address, so `taskOf` / `outsideTaskOf` / `retainedState` / `useTaskLinkState` and the item and NPC edit readers treat a lone `returnTo` like a direct entry (single back link, no forwarded task); (2) `useStagedNavigation`'s section normalization is an entry-owned `replaceOwnEntry` write (writer mark `normalization`), checked against the router's current entry, waiting on pending navigation and on blocked or proceeding blockers, abandoned by a newer location, and never written over a destination after Leave. `replaceOwnEntry` now also waits on a `proceeding` blocker (the stamp writer shares it). Guard audit unchanged: no new caller, hold or declaring key. Shared-hook consumers re-run: Character (`CharacterRecordNav`), Quest, Knowledge claim, Item, Run, Calendar creation and the World workspace; defaults, aliases and stage availability are unchanged.

## 13. Campaign setup, settings and Access after P02-7e

Routes now rendering the shared breadcrumb (`routeMeta` ids): `campaign.settings` (Campaign Home › Campaign settings), `access.invitations` and `access.audit` (Access › page). `access.overview` is the Access root (no ancestors, nothing rendered). The unscoped `campaigns.list` / `campaigns.new` pages keep their own links and destinations.

| From | To | State carried |
|---|---|---|
| Settings / Invitations / Audit crumb | Campaign Home / Access | `breadcrumbModel` crumb state: the task (root only) cut back to the ancestor; no list, no name |
| Access tab strip | the three Access routes | none (peer routes; trail identical) |
| Campaign Home, Navbar | settings, Invitations | none (route default root = the explicit start) |

Guard audit: **no new caller or declaring key.** Row 1 (`CampaignDetails`, `worldId` / `timelineId` disposing query, confirmed-create recovery hold) and row 2 (`CampaignSettingsPage`, dirty edits, no query) were re-inspected and are unchanged; the Access pages hold no navigation guard of their own beyond the mutation components' existing ones, which were not touched. The recovery contract (single create, created id owned until listed, Stay/Leave, release on successful read) is covered by `campaignSetup.test.tsx` (pending, rejected, superseded and stale confirming reads) and was re-run.

Reads: none were added; the breadcrumb is static. Compatibility exceptions: the setup wizard's and `/campaigns`'s own links; Cancel returns to `/campaigns` whatever page opened the wizard (World overview, timeline page); `GetStartedCard` and the character panel's **Link a player** link carry no explicit task (the route's default root is the same).

## 14. Status after P02-8

No route, guard caller or declaring key changed in P02-8 or its correction. Rows 1 and 2 (campaign setup and settings) and every row above stand as audited at their checkpoint. Facts the earlier sections do not state: the legacy return keys are still read by the pages listed in the reconciliation record R-3 (an outstanding plan obligation, follow-up F-3, not an approved exception); and `InvitationsSection` (reached from `access.invitations`) declares no guard or hold, so a departure during or just after an issue request can abandon the response (DEF-010, follow-up F-1; source-confirmed: a matching-key replay returns the sanitized body without the token, and `invited_email` has no uniqueness). Neither was introduced by P02. No browser check has run; see [PHASE14_15_P02_RECONCILIATION_2026-11-04.md](PHASE14_15_P02_RECONCILIATION_2026-11-04.md) §6.


## 15. Legacy return keys after the F-3 migration

*Supersedes the "Legacy keys" paragraphs of §§8-12 and the dual-writing statements in §§11-12 (kept as written for the history of each checkpoint). Documentation of a code change; nothing here is browser-verified.*

### 15.1 Inventory before editing

| Key | Production writers | Production readers (incl. indirect) |
|---|---|---|
| `charactersReturn` | `legacyKeys` (every task link), `CharactersBrowser` card, `CharactersCreateAction`, `ChooseCharacterTypePage` (forward) | `readCharactersReturn` (`useCharactersBackPath`: adapter, `NpcAuthoringPages` create `listPath`/`breadcrumbLabelFor`), `useCharactersBackPath` (no caller), `pickCharactersReturnState` |
| `worldSearch` | `legacyKeys`, `CampaignWorldPage`, `WorldCard`/`WorldEntityList` (`returnSearch`) | `useWorldBackPath` (`useWorldBackPath`, `pickWorldReturnState`, `useWorldReturnState`), `WorldRecordBack`, `WorldRecordWorkspace`, `QuestWorkspace`, `ItemWorkspace`, `editNavigation`, `ProvenancePage`, `DungeonAuthoringPages`, `NpcAuthoringPages`, `ReviewPages` history, `InventoryPanels`, `CampaignWorldDetailPage`, `WorldEventDetailPage`, `WorldOrganizationDetailPage`, `ItemPages` (`pickReturnState`) |
| `reviewSearch` | `legacyKeys`, `ReviewPages` queue rows and History links (**legacy only, no task**) | `useReviewBackPath` (`WorldRecordWorkspace`, `QuestWorkspace`), `ReviewPages` history, `pickWorldReturnState` consumers above |
| `itemsSearch` | `legacyKeys`, `ItemsPage` | `useItemsBackPath`, `ItemPages` (edit `listPath`, create `listPath`, `pickReturnState`), `ItemWorkspace` |
| `definitionsSearch` | `legacyKeys`, `ItemDefinitionsPage` | `useDefinitionsBackPath` (`ItemDefinitionFormPage`) |

### 15.2 Behavior map and result

| Return behavior | Task equivalent now used |
|---|---|
| Back to World with category, search and page | `task.list` of root `world`, route `campaign.world`, read by `useCarriedListSearch` |
| Back to the Review queue with its filters; History and record links out of the queue | queue rows and History links write `continuedListState` (root `review`, route `review.queue`); `useReviewBackPath`, history `queueHref` read the list |
| Items inventory vs the definitions catalog | root `items`, list routes `items.list` / `itemDefinitions.list`, each read for its own route only (a definitions list is never the inventory's) |
| Characters browser filters and paging; a sheet; a sheet's section | browser cards write `continuedListState`; `CharactersCreateAction` writes `continuedListState` or `continuedState(…, section)`; the create pages' Cancel and breadcrumb take the nearest trail page that is not the chooser; `TrailEntry.section` reopens the section |
| Cross-root origin through a page that does not accept the root (edit, provenance, dungeon pages, the item and quest pages) | `carriedState` hands the task on as written (campaign-checked, parsed, `transition` dropped); the record validates it for its own route |
| Created record keeps the origin | the create shell's resolved task (`ContentCreatePage`); the per-config `resultState` is removed |

### 15.3 Removed and remaining

Removed: `legacyKeys`, the legacy members of `CrumbState`, `pickWorldReturnState`, `pickReturnState`, `useItemsReturnState`, `pickCharactersReturnState`, `useCharactersBackPath`, `pickQueryStates`, `WorldCard`/`WorldEntityList` `returnSearch`, `useCharactersBrowseState.returnTo`, `ContentCreateConfig.resultState`. Added: `navigation/taskReturn.ts`.

Remaining occurrences in production code (searched again after the change): `navigation/legacyReturn.ts` (the read-only adapter and its comments), `navigation/legacyCharactersReturn.ts` (the validator the adapter uses), `hooks/returnState.ts` `readQueryState` (the adapter's reader), the explanatory comment in `navigation/resolveTask.ts`; and ordinary local identifiers or the substring in `memberPreviewSearch`. No writer and no page reader remains. Tests keep a few seeded legacy-key entries on purpose: they are the adapter's historical-entry cases (plan H6).

### 15.4 Historical entry compatibility (decided: adapter retained)

Plan §4.3 step 2 and scenario H6 say an entry carrying only a legacy key is adapted. The reconciliation's F-3 acceptance text says the adapter is removed and old entries fall back to route defaults. The two disagreed; the owner decided to retain the centralized read-only adapter (H6), so no supported entry loses its origin. Production legacy writers and direct page readers stay removed and are not to be reintroduced; adapter removal is no longer pending or required. No persistence or versioning policy was invented. **F-3 is closed under H6 (reconciliation R-18):** the independent review passed commit 762f304c00b56df4ebb152ea8ce2b00271cf0fdd (10 files, 408 focused tests, independent evidence; the author's 5,004-test full run is reported separately, and the `ItemDefinitionPages` retry failure stays unattributed). The adapter remains for historical entries; production writers and direct page readers of the five keys are removed. Differences a retained adapter already has against the old readers: an entry with several legacy keys resolves to one origin (order: `charactersReturn`, `reviewSearch`, `itemsSearch`, `definitionsSearch`, `worldSearch`), and a query the list contract does not accept is ignored.

Two review findings were corrected (reconciliation R-15). **Sections:** an old `charactersReturn` to a valid UUID character route keeps `?section=` through adaptation, the breadcrumb and New PC Cancel, on the existing `TrailEntry.section` and only when the value is a section token; no other search parameter is copied into a detail trail; a non-token value opens the sheet plainly; malformed, foreign-campaign and unsupported destinations are still rejected. **Pass-through precedence:** `carriedTask` follows `resolveTask` (valid explicit task, else adapted legacy origin, else nothing); the explicit candidate is judged by `validateCarriedTask` for its own scope, trail and list contract without requiring this page to allow its root, so a foreign or invalid explicit task no longer hides a valid legacy origin and a Review task still passes through an edit page to its record. The output is the task only.

**Pass-through versus final-destination validation (reconciliation R-16).** Judging a candidate for the page that hands it on is not enough where the link's target is known: a same-campaign Access task passes the World edit page but not the World record, and used to hide a valid `worldSearch`. `carriedState(pathname, state, destination)` now also validates each candidate (explicit first, then the adapted legacy origin) with `validateTask` against the destination route and forwards the first that passes both; if none does, nothing is forwarded and the caller's default return applies. The intermediate restriction stays separate, so a valid Review task still passes through a World edit page. Destination-aware call sites: World edit (`editNavigation`), item edit (`ItemPages`), dungeon and area links (`DungeonAuthoringPages`), Review history record link (`ReviewPages`). **Quest return contract (reconciliation R-17):** a destination's breadcrumb roots (route metadata) and the roots it supports for a return are different things. `quests.detail` does not render a Review task as its breadcrumb but `QuestWorkspace` offers "Back to Review queue" from one; `taskReturn.ts` therefore accepts a Review task at that route, for return navigation only, by the pass-through rules, and every other root and destination by `validateTask`. Not changed because one carried state serves several targets: `ProvenancePage`, `ItemWorkspace`, `QuestWorkspace`, `WorldRecordWorkspace`.

## 16. P02-0c: the Characters create entry point (PD-8 approved)

No route, guard caller or declaring key changed. `CharactersCreateAction` (rendered by the Characters header on `/characters/all` and by the selected-character record) now reads **New character** and links to `/characters/new` instead of `/characters/pc/new`, carrying the task (the browser with its list filters and paging via `continuedListState`, or the record on its `?section=` via `continuedState`). `ChooseCharacterTypePage` was not changed: it forwards `useTaskLinkState({ requireOrigin: true })` to New NPC and New player character, and the create pages take the nearest trail page that is not `characters.new` as Cancel and breadcrumb target, so the chooser stays a step. Authorization is unchanged: the action shows for `canon.edit` (bootstrap), each form reads its own options endpoint and shows the server's refusal. The inventory-only page offers no action and its request boundary is unchanged. Historical `charactersReturn` entries are still read only by the adapter. Real-route tests: `App.characterShell` (selected record and `/characters/all`, both kinds with the record section, fallbacks for missing, malformed, foreign and crafted-older-key state, per-option refusal, inventory-only), `App.npcAuthoring` (filters and paging through the chooser to each kind), `App.taskBreadcrumb`, `CampaignCharactersPage`.

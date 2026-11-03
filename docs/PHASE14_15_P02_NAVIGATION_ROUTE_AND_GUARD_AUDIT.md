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

### 1.2 Shared guarded-transition behavior

`isGuardedTransition(transition, options?)` is true for, in order of evaluation:

1. a pathname change (after the permission-loss exemption);
2. a change of committed context at the same path (section 1.1 rules 3 to 6);
3. a query-only change (`search` differs) that `options.disposingQuery(current, next)` declares disposing.

A query-only change is therefore unguarded unless the editor or dialog would unmount, the data scope or perspective would change, or an unresolved operation would lose its owner, and only a caller that says so is asked. `useUnsavedChangesGuard` stores the options in a ref updated in a layout effect, so an inline predicate is never stale and does not re-register the blocker. `PickerRecordTime`'s own blocker calls the predicate with no options (see 3.3).

## 2. Route inventory

The inventory is `ROUTE_METAS` in [routeMeta.ts](../portal/src/navigation/routeMeta.ts): **91 patterns**. `routeMeta.test.ts` takes the production patterns from `App.tsx` itself (it calls the hook-free `App` component, reads the `<Routes>` element and passes its children to react-router's `createRoutesFromChildren`), and fails when a production pattern has no entry or an entry matches no production pattern. There is no second, hand-maintained route table in the test. Matching in `matchRouteMeta` is react-router's own ranking over the same patterns, so route matching and permissions are untouched: nothing in `App.tsx` or any route element changed.

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
| 12 | `KnowledgeClaimPage.tsx:473` (page-local `UnsavedInputGuard`) | `/app/:c/knowledge/:id` | **`character_id`, `party_id`** (the claim is read under that perspective; the page also builds links that carry them) | none declared | `section` (all sections stay mounted; `useClaimNavigation`) | claim edits, `useConfirmedRefresh` and write recovery are held by the page, mounted across a query change | **Not declared: follow-up F-2** (scope keys, see 3.4) |
| 13 | `ContentEditPage.tsx:282` | edit pages for the same families as 8 | none (reads `location.state`) | none | any | local mutation; stale-write hold stays with the page | none |
| 14 | `PartyPages.tsx:336` (`PartyForm`: new and edit) | `/app/:c/parties/new`, `/parties/:id/edit` | none | none | any | local mutation | none |
| 15 | `SessionDetailPage.tsx:237` | `/app/:c/sessions/:id` | none (`?section=participants` belongs to the Run route, a different page) | none | any | local mutation, `useConfirmedRefresh` | none |
| 16 | `SessionFormPages.tsx:69` (`CreateSessionPage`) | `/app/:c/sessions/new` | none | none | any | local mutation | none |
| 17 | `WorldTimesPage.tsx:150` | `/app/:c/world-times` | none | none | any (reads no query) | **The guard owns it**: `isDirty = dirty || pending || unresolved`, so an in-flight or uncertain write holds a departure | none. The picker dialog is hosted here (see 3.3) |
| 18 | `staged/UnsavedInputGuard.tsx:8`, hosted by `QuestWorkspace`, `ItemWorkspace`, `WorldRecordWorkspace` | `/app/:c/quests/:id`, `/items/:id`, `/world/:category/:id` | Quest: **`character_id`, `party_id`** (`useQuestPartyPerspective`). Items and World record: none | none declared | `section` in all three (staged sections stay mounted) | drafts and receipts are held by the workspace, mounted across a query change; item time picker holds via `useNavigationHold` | Quest: **F-2**. `UnsavedInputGuard` takes no options yet; a prop would be added with F-2 |
| – | `PickerRecordTime.tsx:54` (blocker; only when no page guard is mounted) | every `WorldTimePicker` host | none | none | any | the open recording is a navigation hold: it makes the page guard (or its own blocker) ask | Default, no options (3.3) |

No caller other than #1 was found whose query-only change unmounts its own editor. That is a finding about the 18 call sites reviewed, not a general guarantee: see 3.4.

### 3.3 Picker blockers

`PickerRecordTime` holds a navigation while a recording is open (`useNavigationHold`) and installs a blocker only when no page guard is mounted (`useHostGuard`). It evaluates `isGuardedTransition` with no options. The pages hosting `WorldTimePicker` without a page guard (Campaign Home's clock card, the NPC runtime panel, the relationship editor, the organization member editor) were **not** individually audited for query-driven remounts, so the picker's own blocker guards pathname and context changes only. Item workspace and World times are covered by their page guard (rows 17 and 18).

### 3.4 What is and is not claimed

- Claimed: every one of the 18 call sites was classified from source; one disposing query (row 1) was found, declared and tested; staged `?section=` is harmless in the three guarded workspaces, the calendar steps and the knowledge claim page because their sections stay mounted.
- **Not claimed:** a complete query-safety guarantee. Open items, none of which is repaired here:
  - **F-1.** Most pages keep a pending or unknown-outcome write in a local `useAuthoringMutation` and exclude it from `isDirty` (only `WorldTimesPage` includes it). A pathname departure during an uncertain write therefore asks nothing on those pages; this is existing behavior, unchanged. For row 1 the effect is that a query-only step change during an in-flight create is also not asked unless something is typed.
  - **F-2.** Quest and Knowledge claim read `character_id` and `party_id` and re-read under that perspective with the editor mounted. Whether a changed perspective may keep a draft is a scope decision, so it is a context transition in the plan (Q3), but declaring those keys today would also hold the pages' own stale-party cleanup (`useQuestPartyPerspective` rewrites the address when a party is no longer authorized, which is a permission-loss case and must never wait for a question). The declaration needs that cleanup distinguished first; the natural place is P02-3 (selection ownership). Concrete follow-up: add a `disposingQuery` prop to `UnsavedInputGuard`, pass `queryKeysChanged(...PERSPECTIVE_QUERY_KEYS)` from `QuestWorkspace` and the claim page, and route the stale-party cleanup through `runPermissionLossCleanup`.
  - **F-3.** Picker hosts without a page guard are unaudited for query keys (3.3).
  - **F-4.** `CharacterRecordSections` mounts only the shown section (`?section=`), but it is not a guard caller and no editor state lives in it today. A guard added there must declare `section` disposing.
  - The guard does not distinguish a user-initiated query change from a page's own REPLACE of its address. A page that rewrites a declared key itself while dirty would be asked. Row 1 does not do this: its steps change only by user links.

## 4. Verification summary

Recorded in the ledger row for this checkpoint. In short: new pure tests for the contracts, route coverage against the real `App.tsx`, legacy compatibility, the predicate truth table, and five real-caller tests for the setup wizard's declared disposing query (question, Stay, Discard, clean form, an undeclared key, and a deferred create whose outcome still lands after a refused step change; they wait on processed UI and router outcomes, with no sleeps); the P02-0a predicate, layout and guard suites pass unchanged. The disposing-query tests were also run with the declaration removed and failed (2 of 5), so they cannot pass vacuously. The harmless-query side is represented by the existing New calendar test cited in row 5.

## 5. Not part of P02-1

Shared Breadcrumb adoption (P02-2); a selection provider, new persistence or any change to campaign or perspective behavior (P02-3); Navbar or menu redesign and task reset (P02-4/5); the New character chooser (P02-0c, PD-8); the F-1 to F-4 items; any backend, authorization, NPC/PC or database change. No manual acceptance is recorded.

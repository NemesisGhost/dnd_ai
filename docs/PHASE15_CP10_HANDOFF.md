# CP-10 handoff — recovery completion and bounded workspace consolidation

Historical CP-10 handoff. Start HEAD `e054bd1d16d87fe2a092dbe3992cdb042a68b071`, branch `phase15/completion`. CP-10 is complete; the remaining deferred-caller observations below are retained as context for the CP-11 defect register.

## Responsibility map (before → after)

| Concern | Before | After |
|---|---|---|
| Confirmed quest command, re-read fails | `useQuestCommand`, `QuestDetailsSection`, `QuestProgressPanel`, `QuestStructureEditor` discarded the refetch outcome (`refetch: () => Promise<unknown>`): status `success`, "done" announced while the page was behind | Return the outcome; mutation reports `confirmed`; "done" announced only on `ok`; `QuestWorkspace.refreshRecord` joins the quest, lifecycle and revisions reads with `combineRefetchOutcomes`; progress panel joins its own read with the page's |
| Item operations / item definition edit | Same discard | Same fix (`useItemOperations`, `ItemDefinitionPages`) |
| Knowledge claim edit / audience writes | Same discard; `Knowledge claim saved` announced after a failed read | Same fix (`KnowledgeClaimPage`, `KnowledgeRoster`) |
| Source attach/detach | `Promise.all` of two reads, outcome discarded | `combineRefetchOutcomes` |
| Query-state readers | `startsWith("?")` + pick loop copied in `useWorldBackPath`, `useItemsBackPath`, `ItemPages`, `editNavigation` | `hooks/returnState.ts` (`readQueryState`, `pickQueryStates`) |
| `returnTo` allow-list | Copied in World `editNavigation` and `ItemPages.editNavigation` | `resolveReturnTo` |
| Record header frame | `WorldRecordHeader` and `ItemHeader` each rendered the same header/eyebrow/headline/status/summary/Next | `records/RecordHeader` + `RecordStatus`; both are thin wrappers |
| Focus on section change | Six hand-written effects (item, claim, session run, quest, World, character record) | `staged/useFocusOnSectionChange` (`ready`, `keep` options); callers keep their own heading ids |

## Retained domain differences (not extracted)

- `useCharactersBackPath`: a path inside the campaign's Characters area, not a query string; its validation differs by design.
- Item back paths (`itemsSearch`, `definitionsSearch`, `worldSearch`) vs World (`worldSearch`, `reviewSearch`) keep separate key sets and wrappers.
- `CharacterRecordSections` keeps its own section keys, outbound links and content-heading focus target (passed as the `focus` callback).
- The World workspace keeps its permission-loss rule (`keep`: focus does not move when the section left was withdrawn); quest keeps `ready` (arrival is the settled section).
- Encounters, sessions, knowledge, items, characters and access assignments stay domain-specific.

## Review follow-up: Claim save refresh gap

`KnowledgeClaimPage` awaited only the authoring read-back; the audience-safe detail refresh (`refreshDetail`) was fire-and-forget, so a confirmed save whose detail read failed was reported as fully refreshed (and, because a failed detail read replaced the page with an error screen, could drop other unsent input). Now: `useKnowledgeDetail.refresh()` is awaitable and resolves `ok`/`failed`/`superseded` (a recoverable failure keeps the item shown; 403/404 still fails closed to unavailable; a newer refresh supersedes an older one); `ClaimForm` joins it with the authoring read via `combineRefetchOutcomes`, still clears the confirmed edit, announces "Knowledge claim saved" only on `ok`, and otherwise shows `SavedRefreshFailedNotice` with a read-only "Load latest" (kept in local state because the mutation scope changes with the saved row version). Tests: `App.knowledgeClaim.test.tsx` (authoring read ok, detail read fails, one write, read-only retry) and `useKnowledgeDetail.test.ts` (refresh outcomes). Behaviour change for the other `refreshDetail` caller (lifecycle `onChanged`): a recoverable detail failure now keeps the page instead of replacing it with the error screen.

## Review follow-up 2: Claim lifecycle read-back

Once `useKnowledgeDetail.refresh()` kept the shown item on a recoverable failure, the Claim lifecycle `onChanged` path (which fired `view.refetch()` and `refreshDetail()` and discarded both) would have left stale Claim content with no sign of the failed read. Now `LifecycleActionsProvider`'s `onChanged` may return a `RefreshOutcome` (other callers still return nothing, unchanged); the panel announces the step as done only when that outcome is `ok` or absent, and returns it so the mutation reports confirmed-but-refresh-failed. `KnowledgeClaimPage` passes a read-back that joins the lifecycle, authoring and detail reads (`combineRefetchOutcomes`) and keeps a page-level `SavedRefreshFailedNotice` (the step's own status resets when the record version changes). Its "Load latest" runs the three reads only; the step is never sent again. Test: `App.knowledgeClaim.test.tsx` (submit for review confirmed, detail read fails: notice, no "done" announcement, retry reads only, one POST); it fails on the previous code. Other `EntityLifecyclePanel` callers (World, Item, Quest) were not migrated.

## Already complete (no change made)

CP-2 callers (inventory panels, settings, archived campaigns, content edit, participant form, session run, award item), CP-4d permission-loss handling in the World workspace, `kept`/`stale` retention in Quest/Item/World workspaces (denied/unavailable clear it), `SavedRefreshFailedNotice` use.

## Not changed (outside the plan-listed callers)

`TransitionControls` (world/timeline), party pages, NPC portrayal, character build, event pages, `WorldSharingPage`, `SessionRunPage` clock/log hooks, `TravelSection` still `await refetch()` and drop the outcome, so they can announce "done" after a failed re-read. They are outside CP-10's named Quest/Item/Claim scope; listed here as a follow-up, not fixed.

## Evidence

Automated only. No scripted-browser, human or accessibility evidence was produced for CP-10; no database, migration or backend change.

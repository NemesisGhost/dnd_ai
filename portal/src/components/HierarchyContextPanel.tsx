import { useId } from "react"
import { useNavigate } from "react-router"
import { worldsListPath } from "../api/worlds"
import { useSession } from "../context/SessionContext"
import { useWorkspaceHierarchy } from "../context/WorkspaceHierarchyContext"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { useRetryFocus } from "../hooks/useRetryFocus"
import type { CampaignContext } from "../types/bootstrap"
import type { WorldListResponse } from "../types/worldAuthoring"
import { campaignLevel, canReadWorld, timelineLevel, worldLevel } from "../navigation/contextOptions"
import type { LevelModel, LevelReason, WorldListState, WorldReadState } from "../navigation/contextOptions"
import { scopeRequest } from "../navigation/selectionTransitions"
import { selectionFor, useSelectedContextSnapshot } from "../navigation/selectedContextStore"
import { resolveNavigationCampaign } from "../utils/resolveNavigationCampaign"
import { CharacterContextDetails } from "./CharacterContextDetails"
import { CharacterParties } from "./CharacterParties"
import { CharacterPerspectiveSelector } from "./CharacterPerspectiveSelector"
import {
  LOADING_TIMELINES,
  LOADING_WORLDS,
  NO_CAMPAIGN,
  NO_OTHER_CAMPAIGN,
  NO_OTHER_TIMELINE,
  NO_OTHER_WORLD,
  NO_TIMELINE,
  NO_WORLD,
  SELECT_CAMPAIGN_FIRST,
  SELECT_TIMELINE_FIRST,
  SELECT_WORLD_FIRST,
  TIMELINES_FAILED,
  WORLDS_FAILED,
} from "./navigationReasons"

interface HierarchyContextPanelProps {
  // The authorized campaign the route selects, or null on World and Timeline
  // pages. Its character perspective is the only perspective ever offered.
  campaign: CampaignContext | null
  selectedCharacterId: string | null
  onSelectCharacter: (characterId: string | null) => void
}

const NO_SELECTION = "No selection"

const REASON_TEXT: Record<LevelReason, string> = {
  select_world_first: SELECT_WORLD_FIRST,
  select_timeline_first: SELECT_TIMELINE_FIRST,
  loading_worlds: LOADING_WORLDS,
  loading_timelines: LOADING_TIMELINES,
  worlds_failed: WORLDS_FAILED,
  timelines_failed: TIMELINES_FAILED,
  no_world: NO_WORLD,
  no_timeline: NO_TIMELINE,
  no_campaign: NO_CAMPAIGN,
  no_other_world: NO_OTHER_WORLD,
  no_other_timeline: NO_OTHER_TIMELINE,
  no_other_campaign: NO_OTHER_CAMPAIGN,
}

// After a successful retry the button is gone: focus goes to the level's select when it is usable, else to
// the reason text that explains the level (UI_DESIGN §4.8.12).
function retryTarget(section: HTMLElement): HTMLElement | null {
  return (
    section.querySelector<HTMLElement>("select:not(:disabled)") ??
    section.querySelector<HTMLElement>("[data-level-reason]")
  )
}

function RetryButton({ onRetry }: { onRetry: () => void }) {
  const { ref, used, left } = useRetryFocus<HTMLButtonElement>(retryTarget)
  return (
    <button
      ref={ref}
      type="button"
      className="campaign-context-panel__retry"
      onClick={() => {
        used()
        onRetry()
      }}
      onBlur={left}
    >
      Try again
    </button>
  )
}

interface LevelSelectProps {
  headingId: string
  reasonId: string
  model: LevelModel
  onRetry: (retry: NonNullable<LevelModel["retry"]>) => void
  onSelect: (id: string) => void
}

// One hierarchy level: its selector and, whenever the level is disabled, loading or failed, the visible
// reason the selector is described by. The empty placeholder is never a choice, a display-only current
// value is shown but inert, and `onSelect` resolves an id only through the model's real options.
function LevelSelect({ headingId, reasonId, model, onRetry, onSelect }: LevelSelectProps) {
  const known =
    model.selectedId !== null &&
    (model.options.some((option) => option.id === model.selectedId) ||
      model.displayOnly?.id === model.selectedId)
  const reason = model.reason === null ? null : REASON_TEXT[model.reason]
  return (
    <>
      <select
        className="campaign-context-panel__control"
        aria-labelledby={headingId}
        aria-describedby={reason === null ? undefined : reasonId}
        value={known ? model.selectedId! : ""}
        disabled={!model.enabled}
        onChange={(event) => {
          const next = event.currentTarget.value
          if (next !== "" && next !== model.selectedId) {
            onSelect(next)
          }
        }}
      >
        <option value="" disabled>
          {NO_SELECTION}
        </option>
        {model.options.map((option) => (
          <option key={option.id} value={option.id}>
            {option.label}
          </option>
        ))}
        {model.displayOnly !== null && (
          <option value={model.displayOnly.id} disabled>
            {model.displayOnly.label}
          </option>
        )}
      </select>
      {reason !== null && (
        <p id={reasonId} className="campaign-context-panel__reason" data-level-reason tabIndex={-1}>
          {reason}
        </p>
      )}
      {model.retry !== null && <RetryButton onRetry={() => onRetry(model.retry!)} />}
    </>
  )
}

// The World → Timeline → Campaign → Character context for every page of the
// authenticated World and Campaign workspace. Selection is route-derived (the
// hierarchy provider and the route campaign); choosing an option only
// asks the router for the destination with a new task (navigation/selectionTransitions), so the
// departure guard decides first and lower levels clear because their routes unmount. Option lists
// come from authoritative responses only — the worlds list, the selected world's timelines, and the
// session's authorized campaigns — through one pure model (navigation/contextOptions) that also decides
// when a level is worth enabling and why it is not. A level without options stays visible and disabled,
// with its reason beside it.
export function HierarchyContextPanel({
  campaign,
  selectedCharacterId,
  onSelectCharacter,
}: HierarchyContextPanelProps) {
  const worldHeadingId = useId()
  const timelineHeadingId = useId()
  const campaignHeadingId = useId()
  const characterHeadingId = useId()
  const worldReasonId = useId()
  const timelineReasonId = useId()
  const campaignReasonId = useId()
  const characterReasonId = useId()
  const navigate = useNavigate()
  const { state } = useSession()
  const {
    activeWorldId,
    activeTimelineId,
    routeNamesWorld,
    routeNamesTimeline,
    world,
    worldEvidence,
    refetchWorld,
  } = useWorkspaceHierarchy()
  const retained = useSelectedContextSnapshot()
  const worlds = useAuthoringResource<WorldListResponse>(
    `${worldsListPath("all")}&limit=100`,
  )

  const bootstrapCampaigns =
    state.status === "authenticated" ? state.bootstrap.campaigns : []
  const worldDetail = world?.kind === "ready" ? world.data : null

  // On a page with no campaign of its own (a World or Timeline page), a campaign this tab retained is
  // shown only as the selected campaign, and only while it belongs to the world and timeline the route
  // confirmed. It is not the page's scope: the page reads nothing under it.
  const selectedCampaign =
    campaign !== null || state.status !== "authenticated"
      ? null
      : resolveNavigationCampaign(
          state.bootstrap,
          undefined,
          { routeNamesWorld, routeNamesTimeline, activeWorldId, activeTimelineId },
          selectionFor(retained, state.bootstrap).campaignId,
        )

  const worldList: WorldListState =
    worlds.state.kind === "ready"
      ? { kind: "ready", items: worlds.state.data.items, startedSeq: worlds.startedSeq }
      : worlds.state.kind === "loading"
        ? { kind: "loading" }
        : { kind: "failed" }
  // The current world's name when the list does not carry it (the world read, or the route campaign).
  const worldName =
    activeWorldId === null
      ? null
      : ((worldList.kind === "ready"
          ? worldList.items.find((item) => item.world_id === activeWorldId)?.name
          : undefined) ??
        worldDetail?.name ??
        campaign?.world_name ??
        bootstrapCampaigns.find((item) => item.world_id === activeWorldId)?.world_name ??
        null)
  const worldModel = worldLevel({
    list: worldList,
    campaigns: bootstrapCampaigns,
    routeCampaignId: campaign?.campaign_id ?? null,
    activeWorldId,
    activeWorldName: worldName,
    evidence: worldEvidence,
  })

  const worldRead: WorldReadState =
    world === null
      ? "not_requested"
      : world.kind === "loading"
        ? "pending"
        : world.kind === "error"
          ? "failed"
          : world.kind === "ready" && canReadWorld(world.data.capabilities)
            ? "readable"
            : "refused"
  const timelineName =
    activeTimelineId === null
      ? null
      : (worldDetail?.timelines.find((item) => item.timeline_id === activeTimelineId)?.name ??
        campaign?.timeline_name ??
        null)
  const timelineModel = timelineLevel({
    worldRead,
    activeWorldId,
    activeTimelineId,
    activeTimelineName: timelineName,
    worldTimelines: worldDetail?.timelines ?? [],
  })

  const campaignSelected =
    campaign !== null
      ? { id: campaign.campaign_id, label: campaign.campaign_name }
      : selectedCampaign === null
        ? null
        : { id: selectedCampaign.campaign_id, label: selectedCampaign.campaign_name }
  const campaignModel = campaignLevel({
    campaigns: bootstrapCampaigns,
    activeWorldId,
    activeTimelineId,
    selected: campaignSelected,
  })

  const selectedCharacter = campaign?.character_perspectives.find(
    (character) => character.character_id === selectedCharacterId,
  )
  const rolesLabel =
    campaign !== null && campaign.roles.length > 0
      ? campaign.roles.join(", ")
      : "Not available"

  const summaryParts = [worldName, timelineName, campaign?.campaign_name ?? null].filter(
    (part): part is string => part !== null,
  )
  const summary =
    campaign === null
      ? summaryParts.length > 0
        ? `Context: ${summaryParts.join(" › ")}${selectedCampaign === null ? "" : ` · Selected campaign: ${selectedCampaign.campaign_name}`}`
        : selectedCampaign === null
          ? "Context: nothing selected"
          : `Context: Selected campaign: ${selectedCampaign.campaign_name}`
      : `Campaign context: ${summaryParts.join(" › ")} — Viewing as ${selectedCharacter?.character_name ?? "No character perspective selected"}`

  // A choice is an ordinary departure: the model names the destination, the same request every
  // Infobox departure makes carries the task and the note, and the guard decides before anything commits.
  function choose(model: LevelModel, id: string): void {
    const option = model.options.find((item) => item.id === id)
    if (option === undefined) return
    const { to, root, note } = option.destination
    const request = scopeRequest(to, root, note)
    navigate(request.to, { state: request.state })
  }

  function retry(which: NonNullable<LevelModel["retry"]>): void {
    // Repeats exactly the failed read: no navigation, no mutation, no bootstrap refresh.
    void (which === "worlds" ? worlds.refetch() : refetchWorld())
  }

  return (
    <details className="campaign-context-panel" open>
      <summary className="campaign-context-panel__summary">{summary}</summary>

      <div className="campaign-context-panel__body">
        <section
          className="campaign-context-panel__section"
          aria-labelledby={worldHeadingId}
        >
          <h3
            id={worldHeadingId}
            className="campaign-context-panel__section-heading"
          >
            World
          </h3>
          <LevelSelect
            headingId={worldHeadingId}
            reasonId={worldReasonId}
            model={worldModel}
            onRetry={retry}
            onSelect={(id) => choose(worldModel, id)}
          />
        </section>

        <section
          className="campaign-context-panel__section"
          aria-labelledby={timelineHeadingId}
        >
          <h3
            id={timelineHeadingId}
            className="campaign-context-panel__section-heading"
          >
            Timeline
          </h3>
          <LevelSelect
            headingId={timelineHeadingId}
            reasonId={timelineReasonId}
            model={timelineModel}
            onRetry={retry}
            onSelect={(id) => choose(timelineModel, id)}
          />
        </section>

        <section
          className="campaign-context-panel__section"
          aria-labelledby={campaignHeadingId}
        >
          <h3
            id={campaignHeadingId}
            className="campaign-context-panel__section-heading"
          >
            {selectedCampaign === null ? "Campaign" : "Selected campaign"}
          </h3>
          <LevelSelect
            headingId={campaignHeadingId}
            reasonId={campaignReasonId}
            model={campaignModel}
            onRetry={retry}
            onSelect={(id) => choose(campaignModel, id)}
          />

          {campaign !== null && (
            <dl className="campaign-context-panel__detail">
              <div className="campaign-context-panel__detail-row">
                <dt>Your roles</dt>
                <dd>{rolesLabel}</dd>
              </div>
            </dl>
          )}
        </section>

        <section
          className="campaign-context-panel__section"
          aria-labelledby={characterHeadingId}
        >
          <h3
            id={characterHeadingId}
            className="campaign-context-panel__section-heading"
          >
            Character
          </h3>
          {campaign === null ? (
            <>
              <select
                className="campaign-context-panel__control"
                aria-label="Character perspective"
                aria-describedby={characterReasonId}
                value=""
                disabled
              >
                <option value="">{NO_SELECTION}</option>
              </select>
              <p id={characterReasonId} className="campaign-context-panel__reason">
                {SELECT_CAMPAIGN_FIRST}
              </p>
            </>
          ) : (
            <CharacterPerspectiveSelector
              perspectives={campaign.character_perspectives}
              selectedCharacterId={selectedCharacterId}
              onSelectCharacter={onSelectCharacter}
            />
          )}

          {campaign !== null && selectedCharacterId !== null && (
            <CharacterParties
              key={`${campaign.campaign_id}/${selectedCharacterId}`}
              campaignId={campaign.campaign_id}
              characterId={selectedCharacterId}
            />
          )}

          {campaign !== null && selectedCharacterId !== null && (
            <CharacterContextDetails
              campaignId={campaign.campaign_id}
              characterId={selectedCharacterId}
            />
          )}
        </section>
      </div>
    </details>
  )
}

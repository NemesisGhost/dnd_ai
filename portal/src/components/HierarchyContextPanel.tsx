import { useId } from "react"
import { useNavigate } from "react-router"
import { worldsListPath } from "../api/worlds"
import { useSession } from "../context/SessionContext"
import { useWorkspaceHierarchy } from "../context/WorkspaceHierarchyContext"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import type { CampaignContext } from "../types/bootstrap"
import type { WorldListResponse } from "../types/worldAuthoring"
import { scopeRequest } from "../navigation/selectionTransitions"
import { selectionFor, useSelectedContextSnapshot } from "../navigation/selectedContextStore"
import { resolveNavigationCampaign } from "../utils/resolveNavigationCampaign"
import { buildWorldChoices, worldAccess } from "../utils/worldAccess"
import { CharacterContextDetails } from "./CharacterContextDetails"
import { CharacterParties } from "./CharacterParties"
import { CharacterPerspectiveSelector } from "./CharacterPerspectiveSelector"

interface HierarchyContextPanelProps {
  // The authorized campaign the route selects, or null on World and Timeline
  // pages. Its character perspective is the only perspective ever offered.
  campaign: CampaignContext | null
  selectedCharacterId: string | null
  onSelectCharacter: (characterId: string | null) => void
}

interface LevelOption {
  id: string
  label: string
}

interface LevelSelectProps {
  headingId: string
  value: string
  options: LevelOption[]
  enabled: boolean
  onSelect: (id: string) => void
}

const NO_SELECTION = "No selection"

// One hierarchy level's selector. The empty placeholder is never a choice;
// a disabled select keeps its slot and exposes its state to assistive tech.
function LevelSelect({
  headingId,
  value,
  options,
  enabled,
  onSelect,
}: LevelSelectProps) {
  return (
    <select
      className="campaign-context-panel__control"
      aria-labelledby={headingId}
      value={value}
      disabled={!enabled}
      onChange={(event) => {
        const next = event.currentTarget.value
        if (next !== "" && next !== value) {
          onSelect(next)
        }
      }}
    >
      <option value="" disabled>
        {NO_SELECTION}
      </option>
      {options.map((option) => (
        <option key={option.id} value={option.id}>
          {option.label}
        </option>
      ))}
    </select>
  )
}

// Adds the currently selected item when the authoritative list does not carry
// it, so the control never shows a blank value for a context it is in.
function withCurrent(
  options: LevelOption[],
  current: LevelOption | null,
): LevelOption[] {
  return current === null || options.some((option) => option.id === current.id)
    ? options
    : [...options, current]
}

// The World → Timeline → Campaign → Character context for every page of the
// authenticated World and Campaign workspace. Selection is route-derived (the
// hierarchy provider and the route campaign); choosing an option only
// asks the router for the destination with a new task (navigation/selectionTransitions), so the
// departure guard decides first and lower levels clear because their routes unmount. Option lists
// come from authoritative responses only: the worlds list, the selected
// world's timelines, and the session's authorized campaigns. A level without
// such a list stays visible and disabled.
export function HierarchyContextPanel({
  campaign,
  selectedCharacterId,
  onSelectCharacter,
}: HierarchyContextPanelProps) {
  const worldHeadingId = useId()
  const timelineHeadingId = useId()
  const campaignHeadingId = useId()
  const characterHeadingId = useId()
  const navigate = useNavigate()
  const { state } = useSession()
  const { activeWorldId, activeTimelineId, routeNamesWorld, routeNamesTimeline, world } = useWorkspaceHierarchy()
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

  // World: the same deduplicated choices All worlds shows — explicit world
  // authority from GET /worlds, plus every world visible through an
  // authorized campaign (opened via that campaign's World Explorer, preferring
  // the route campaign). The list does not depend on the current route.
  const worldChoices = buildWorldChoices(
    worlds.state.kind === "ready" ? worlds.state.data.items : [],
    bootstrapCampaigns,
    campaign?.campaign_id ?? null,
  )
  const worldName =
    activeWorldId === null
      ? null
      : (worldChoices.find((item) => item.world_id === activeWorldId)?.name ??
        worldDetail?.name ??
        campaign?.world_name ??
        null)
  const worldOptions = withCurrent(
    worldChoices.map((item) => ({ id: item.world_id, label: item.name })),
    activeWorldId !== null && worldName !== null
      ? { id: activeWorldId, label: worldName }
      : null,
  )

  // Timeline: choosing one opens a timeline-authoring route, so it is offered
  // only for a world the caller may author (server-computed capabilities).
  const timelineListReady =
    activeWorldId !== null && worldDetail !== null && worldAccess(worldDetail) === "edit"
  const timelineName =
    activeTimelineId === null
      ? null
      : (worldDetail?.timelines.find((item) => item.timeline_id === activeTimelineId)
          ?.name ??
        campaign?.timeline_name ??
        null)
  const timelineOptions = withCurrent(
    timelineListReady
      ? worldDetail.timelines.map((item) => ({ id: item.timeline_id, label: item.name }))
      : [],
    activeTimelineId !== null && timelineName !== null
      ? { id: activeTimelineId, label: timelineName }
      : null,
  )

  // Campaign: only authorized campaigns in the selected world and timeline.
  const campaignOptions: LevelOption[] =
    activeWorldId === null || activeTimelineId === null
      ? []
      : bootstrapCampaigns
          .filter(
            (item) =>
              item.world_id === activeWorldId && item.timeline_id === activeTimelineId,
          )
          .map((item) => ({ id: item.campaign_id, label: item.campaign_name }))

  const selectedCharacter = campaign?.character_perspectives.find(
    (character) => character.character_id === selectedCharacterId,
  )
  const rolesLabel =
    campaign !== null && campaign.roles.length > 0
      ? campaign.roles.join(", ")
      : "Not available"

  const campaignOptionsShown = withCurrent(
    campaignOptions,
    selectedCampaign === null
      ? null
      : { id: selectedCampaign.campaign_id, label: selectedCampaign.campaign_name },
  )

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
            value={activeWorldId ?? ""}
            options={worldOptions}
            enabled={worldOptions.length > 0}
            onSelect={(worldId) => {
              const choice = worldChoices.find((item) => item.world_id === worldId)
              if (choice !== undefined) {
                const request = scopeRequest(choice.to, "world", { level: "world", id: worldId })
                navigate(request.to, { state: request.state })
              }
            }}
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
            value={activeTimelineId ?? ""}
            options={timelineOptions}
            enabled={timelineListReady && timelineOptions.length > 0}
            onSelect={(timelineId) => {
              const request = scopeRequest(
                `/worlds/${encodeURIComponent(activeWorldId ?? "")}/timelines/${encodeURIComponent(timelineId)}`,
                "world",
                { level: "timeline", id: timelineId },
              )
              navigate(request.to, { state: request.state })
            }}
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
            value={campaign?.campaign_id ?? selectedCampaign?.campaign_id ?? ""}
            options={campaignOptionsShown}
            enabled={campaignOptionsShown.length > 0}
            onSelect={(campaignId) => {
              const request = scopeRequest(`/app/${encodeURIComponent(campaignId)}/home`, "campaign", { level: "campaign", id: campaignId })
              navigate(request.to, { state: request.state })
            }}
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
            <select
              className="campaign-context-panel__control"
              aria-label="Character perspective"
              value=""
              disabled
            >
              <option value="">{NO_SELECTION}</option>
            </select>
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

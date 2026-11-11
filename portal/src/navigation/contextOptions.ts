import type { CampaignContext } from "../types/bootstrap"
import type { WorldSummary } from "../types/worldAuthoring"
import { buildWorldChoices, canReadWorld } from "../utils/worldAccess"

// The Infobox's option model (docs/UI_DESIGN.md §4.8.12). One pure function per level turns authoritative
// inputs into what the level may offer: real destinations, an optional display-only current value, whether
// the level is enabled (CN-2, meaningful choice), and the reason to show when it is not. No React, router,
// network or store is read here, so the rules are testable without a render and the panel only draws them.

export { canReadWorld }

export type LevelReason =
    | "select_world_first"
    | "select_timeline_first"
    | "loading_worlds"
    | "loading_timelines"
    | "worlds_failed"
    | "timelines_failed"
    | "no_world"
    | "no_timeline"
    | "no_campaign"
    | "no_other_world"
    | "no_other_timeline"
    | "no_other_campaign"
    | "timeline_gone"

export interface RouteDestination {
    kind: "route"
    to: string
    // The task root the departure starts (navigation/selectionTransitions `scopeRequest`).
    root: "world" | "campaign"
    note: { level: "campaign" | "world" | "timeline"; id: string }
}

// A timeline reachable only through several of the caller's campaigns: nothing navigates until the person
// chooses one of them (the Infobox's inline campaign chooser). It carries ids only; the chooser derives its
// entries from the current bootstrap each time it renders, never from this snapshot.
export interface ChooseCampaignDestination {
    kind: "chooseCampaign"
    timelineId: string
    campaignIds: readonly string[]
}

export type LevelDestination = RouteDestination | ChooseCampaignDestination

export interface LevelOption {
    id: string
    label: string
    destination: LevelDestination
}

export interface LevelModel {
    // Real destinations only. `onSelect` resolves an id through this list and nothing else.
    options: readonly LevelOption[]
    // The current value when the option source does not carry it: shown, never actionable, never counted.
    displayOnly: { id: string; label: string } | null
    selectedId: string | null
    enabled: boolean
    // Set whenever the level is disabled, loading or failed.
    reason: LevelReason | null
    // The one read "Try again" repeats.
    retry: "worlds" | "world" | null
}

const route = (
    to: string,
    root: RouteDestination["root"],
    note: RouteDestination["note"],
): RouteDestination => ({ kind: "route", to, root, note })

interface Counted {
    options: readonly LevelOption[]
    selectedId: string | null
    selectedLabel: string | null
}

function displayOnlyOf({ options, selectedId, selectedLabel }: Counted): LevelModel["displayOnly"] {
    return selectedId !== null &&
        selectedLabel !== null &&
        !options.some((option) => option.id === selectedId)
        ? { id: selectedId, label: selectedLabel }
        : null
}

// CN-2: enabled when nothing is selected and an option exists, or when an option other than the selected
// one exists. A display-only current value is not an option, so it is never counted.
function actionable({ options, selectedId }: Counted): boolean {
    return selectedId === null
        ? options.length > 0
        : options.some((option) => option.id !== selectedId)
}

interface EmptyReasons {
    none: LevelReason
    sole: LevelReason
}

function settle(
    counted: Counted,
    reasons: EmptyReasons,
    extra: { reason?: LevelReason; retry?: LevelModel["retry"] } = {},
): LevelModel {
    const enabled = actionable(counted)
    return {
        options: counted.options,
        displayOnly: displayOnlyOf(counted),
        selectedId: counted.selectedId,
        enabled,
        // A failure keeps its own reason even when other options keep the level usable.
        reason:
            extra.reason ??
            (enabled ? null : counted.options.length === 0 ? reasons.none : reasons.sole),
        retry: extra.retry ?? null,
    }
}

function blocked(
    reason: LevelReason,
    selected: { id: string; label: string } | null,
    retry: LevelModel["retry"] = null,
): LevelModel {
    return {
        options: [],
        displayOnly: selected,
        selectedId: selected?.id ?? null,
        enabled: false,
        reason,
        retry,
    }
}

// --- World ---------------------------------------------------------------------------------------------

// What the panel knows about a world a read answered: only an authoritative answer is a verdict. A
// transient failure, an abort and a read still in flight are not (UI_DESIGN §4.8.12, "Transient failures").
export interface WorldReadEvidence {
    verdict: "readable" | "refused"
    // When the read STARTED (useAuthoringResource `startedSeq`).
    startedSeq: number
}

export type WorldEvidenceMap = ReadonlyMap<string, WorldReadEvidence>

// An explicit World entry is offered only while the list that carries it was not outranked by a refusal of
// `GET /worlds/{id}` that STARTED later. Absence from the list is never refusal; a successful read, or a
// newer list that still carries the world, restores it.
export function explicitWorldValid(
    worldId: string,
    listStartedSeq: number | null,
    evidence: WorldEvidenceMap,
): boolean {
    const entry = evidence.get(worldId)
    if (entry === undefined || entry.verdict === "readable") return true
    return listStartedSeq !== null && entry.startedSeq <= listStartedSeq
}

export type WorldListState =
    | { kind: "loading" }
    | { kind: "failed" }
    | { kind: "ready"; items: readonly WorldSummary[]; startedSeq: number | null }

export interface WorldLevelInput {
    list: WorldListState
    campaigns: readonly CampaignContext[]
    routeCampaignId: string | null
    activeWorldId: string | null
    activeWorldName: string | null
    evidence: WorldEvidenceMap
}

export function worldLevel(input: WorldLevelInput): LevelModel {
    const { list, campaigns, routeCampaignId, activeWorldId, activeWorldName, evidence } = input
    const selected =
        activeWorldId !== null && activeWorldName !== null
            ? { id: activeWorldId, label: activeWorldName }
            : null
    if (list.kind === "loading") {
        // Campaign-derived entries wait with the list so a destination never changes under the person.
        return blocked("loading_worlds", selected)
    }
    // Explicit entries the evidence withdraws are dropped BEFORE the merge, so a withdrawn world that a
    // campaign still reaches comes back as a campaign-derived entry.
    const explicit =
        list.kind === "ready"
            ? list.items.filter((world) =>
                  explicitWorldValid(world.world_id, list.startedSeq, evidence),
              )
            : []
    const choices = buildWorldChoices(explicit, campaigns, routeCampaignId)
    const options = choices.map(
        (choice): LevelOption => ({
            id: choice.world_id,
            label: choice.name,
            destination: route(choice.to, "world", { level: "world", id: choice.world_id }),
        }),
    )
    const counted: Counted = {
        options,
        selectedId: activeWorldId,
        selectedLabel: options.find((o) => o.id === activeWorldId)?.label ?? activeWorldName,
    }
    const reasons: EmptyReasons = { none: "no_world", sole: "no_other_world" }
    return list.kind === "failed"
        ? settle(counted, reasons, { reason: "worlds_failed", retry: "worlds" })
        : settle(counted, reasons)
}

// --- Timeline ------------------------------------------------------------------------------------------

// The active world's own read, as the Timeline level sees it.
export type WorldReadState = "readable" | "refused" | "failed" | "pending" | "not_requested"

export interface TimelineLevelInput {
    worldRead: WorldReadState
    activeWorldId: string | null
    activeTimelineId: string | null
    // The timeline's name when something authoritative supplies one (the world read or the bootstrap).
    activeTimelineName: string | null
    // The world read's timelines, in server order. Used only when `worldRead` is "readable".
    worldTimelines: readonly { timeline_id: string; name: string }[]
    // The caller's authorized campaigns (the current bootstrap). Used only when the world is not readable.
    campaigns: readonly CampaignContext[]
    // A chooser the person opened lost its last campaign: say so (UI_DESIGN §4.8.12).
    timelineGone?: boolean
}

const UNNAMED_TIMELINE = "Unnamed timeline"

// CN-1: a caller who cannot read the world is offered the timelines their authorized campaigns on it
// represent, never a world route. Distinct timelines by case-insensitive name then id; a campaign with no
// timeline adds nothing. One campaign on a timeline opens that campaign; several need an explicit choice.
function campaignDerivedTimelines(
    campaigns: readonly CampaignContext[],
    activeWorldId: string,
): LevelOption[] {
    const byTimeline = new Map<string, { name: string; campaigns: CampaignContext[] }>()
    for (const item of campaigns) {
        if (item.world_id !== activeWorldId || item.timeline_id === null) continue
        const entry = byTimeline.get(item.timeline_id)
        if (entry === undefined) {
            byTimeline.set(item.timeline_id, {
                name: item.timeline_name ?? UNNAMED_TIMELINE,
                campaigns: [item],
            })
        } else {
            entry.campaigns.push(item)
        }
    }
    return [...byTimeline.entries()]
        .sort(([leftId, left], [rightId, right]) => {
            const a = left.name.toLocaleLowerCase()
            const b = right.name.toLocaleLowerCase()
            if (a !== b) return a < b ? -1 : 1
            return leftId < rightId ? -1 : leftId > rightId ? 1 : 0
        })
        .map(([timelineId, entry]): LevelOption => {
            const [only] = entry.campaigns
            return {
                id: timelineId,
                label: entry.name,
                destination:
                    entry.campaigns.length === 1 && only !== undefined
                        ? route(`/app/${encodeURIComponent(only.campaign_id)}/home`, "campaign", {
                              level: "campaign",
                              id: only.campaign_id,
                          })
                        : {
                              kind: "chooseCampaign",
                              timelineId,
                              campaignIds: entry.campaigns.map((c) => c.campaign_id),
                          },
            }
        })
}

export function timelineLevel(input: TimelineLevelInput): LevelModel {
    const {
        worldRead,
        activeWorldId,
        activeTimelineId,
        activeTimelineName,
        worldTimelines,
        campaigns,
        timelineGone = false,
    } = input
    const selected =
        activeTimelineId !== null && activeTimelineName !== null
            ? { id: activeTimelineId, label: activeTimelineName }
            : null
    if (worldRead === "pending") return blocked("loading_timelines", selected)
    if (worldRead === "failed" && activeWorldId === null) {
        return blocked("timelines_failed", selected, "world")
    }
    if (activeWorldId === null) return blocked("select_world_first", selected)

    // Explicit authority wins: a readable world offers its timelines as world routes even when the caller
    // also has campaigns on them (the world route's Campaign level then offers those campaigns).
    const options: LevelOption[] =
        worldRead !== "readable"
            ? campaignDerivedTimelines(campaigns, activeWorldId)
            : worldTimelines.map((timeline) => ({
                  id: timeline.timeline_id,
                  label: timeline.name,
                  destination: route(
                      `/worlds/${encodeURIComponent(activeWorldId)}/timelines/${encodeURIComponent(timeline.timeline_id)}`,
                      "world",
                      { level: "timeline", id: timeline.timeline_id },
                  ),
              }))
    const counted: Counted = {
        options,
        selectedId: activeTimelineId,
        selectedLabel: options.find((o) => o.id === activeTimelineId)?.label ?? activeTimelineName,
    }
    const reasons: EmptyReasons = { none: "no_timeline", sole: "no_other_timeline" }
    if (worldRead === "failed") {
        return settle(counted, reasons, { reason: "timelines_failed", retry: "world" })
    }
    return settle(counted, reasons, timelineGone ? { reason: "timeline_gone" } : {})
}

// --- Campaign ------------------------------------------------------------------------------------------

export interface CampaignLevelInput {
    campaigns: readonly CampaignContext[]
    activeWorldId: string | null
    activeTimelineId: string | null
    // The route campaign, or the campaign this tab retained while it is compatible with the route.
    selected: { id: string; label: string } | null
}

export function campaignLevel(input: CampaignLevelInput): LevelModel {
    const { campaigns, activeWorldId, activeTimelineId, selected } = input
    if (activeWorldId === null || activeTimelineId === null) {
        return blocked("select_timeline_first", selected)
    }
    const options = campaigns
        .filter((item) => item.world_id === activeWorldId && item.timeline_id === activeTimelineId)
        .map(
            (item): LevelOption => ({
                id: item.campaign_id,
                label: item.campaign_name,
                destination: route(`/app/${encodeURIComponent(item.campaign_id)}/home`, "campaign", {
                    level: "campaign",
                    id: item.campaign_id,
                }),
            }),
        )
    return settle(
        { options, selectedId: selected?.id ?? null, selectedLabel: selected?.label ?? null },
        { none: "no_campaign", sole: "no_other_campaign" },
    )
}

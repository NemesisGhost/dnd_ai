import { describe, expect, it } from "vitest"
import type { CampaignContext } from "../types/bootstrap"
import type { WorldSummary } from "../types/worldAuthoring"
import { buildWorldChoices } from "../utils/worldAccess"
import {
  campaignLevel,
  canReadWorld,
  explicitWorldValid,
  timelineLevel,
  worldLevel,
} from "./contextOptions"
import type { RouteDestination, WorldEvidenceMap, WorldLevelInput, WorldListState } from "./contextOptions"

const world = (id: string, name: string, capabilities = ["world.view"]): WorldSummary =>
  ({ world_id: id, name, capabilities, description: null, lifecycle_status: "active" }) as WorldSummary

const campaign = (
  id: string,
  worldId: string,
  timelineId: string,
  over: Partial<CampaignContext> = {},
): CampaignContext =>
  ({
    campaign_id: id,
    campaign_name: `Campaign ${id}`,
    world_id: worldId,
    world_name: `World ${worldId}`,
    timeline_id: timelineId,
    timeline_name: `Timeline ${timelineId}`,
    ...over,
  }) as CampaignContext

const NO_EVIDENCE: WorldEvidenceMap = new Map()
const ready = (items: WorldSummary[], startedSeq: number | null = 1): WorldListState => ({
  kind: "ready",
  items,
  startedSeq,
})

function worlds(over: Partial<WorldLevelInput> = {}) {
  return worldLevel({
    list: ready([]),
    campaigns: [],
    routeCampaignId: null,
    activeWorldId: null,
    activeWorldName: null,
    evidence: NO_EVIDENCE,
    ...over,
  })
}

describe("canReadWorld", () => {
  it("is world.view and nothing else, failing closed", () => {
    expect(canReadWorld(["world.view"])).toBe(true)
    expect(canReadWorld(["world.manage", "timeline.manage"])).toBe(false)
    expect(canReadWorld([])).toBe(false)
    expect(canReadWorld(undefined)).toBe(false)
  })
})

describe("meaningful choice (CN-2): World", () => {
  it("is disabled with 'no world' when there is no option", () => {
    const model = worlds()
    expect(model).toMatchObject({ enabled: false, reason: "no_world", retry: null })
    expect(model.options).toEqual([])
  })

  it("is disabled with 'no other world' when the sole option is already selected", () => {
    const model = worlds({
      list: ready([world("w1", "One")]),
      activeWorldId: "w1",
      activeWorldName: "One",
    })
    expect(model).toMatchObject({ enabled: false, reason: "no_other_world", selectedId: "w1" })
    expect(model.displayOnly).toBeNull()
  })

  it("is enabled for a sole option with nothing selected, and gives it no reason", () => {
    const model = worlds({ list: ready([world("w1", "One")]) })
    expect(model).toMatchObject({ enabled: true, reason: null })
  })

  it("is enabled when several options exist and one is selected", () => {
    const model = worlds({
      list: ready([world("w1", "One"), world("w2", "Two")]),
      activeWorldId: "w1",
      activeWorldName: "One",
    })
    expect(model.enabled).toBe(true)
    expect(model.options.map((option) => option.id)).toEqual(["w1", "w2"])
  })

  it("never counts a display-only current world: it is shown, not actionable", () => {
    const model = worlds({ activeWorldId: "w9", activeWorldName: "Elsewhere" })
    expect(model).toMatchObject({
      enabled: false,
      reason: "no_world",
      displayOnly: { id: "w9", label: "Elsewhere" },
    })
    expect(model.options).toEqual([])
  })

  it("is enabled for a display-only current world beside one real option", () => {
    const model = worlds({
      list: ready([world("w1", "One")]),
      activeWorldId: "w9",
      activeWorldName: "Elsewhere",
    })
    expect(model.enabled).toBe(true)
    expect(model.displayOnly?.id).toBe("w9")
    expect(model.options.map((option) => option.id)).toEqual(["w1"])
  })

  it("is disabled and loading while the list is pending, offering no campaign-derived entry either", () => {
    const model = worlds({
      list: { kind: "loading" },
      campaigns: [campaign("c1", "w1", "t1")],
    })
    expect(model).toMatchObject({ enabled: false, reason: "loading_worlds", retry: null })
    expect(model.options).toEqual([])
  })

  it("keeps campaign-derived entries and offers a retry when the list failed", () => {
    const failing = worlds({
      list: { kind: "failed" },
      campaigns: [campaign("c1", "w1", "t1"), campaign("c2", "w2", "t2")],
    })
    expect(failing).toMatchObject({ enabled: true, reason: "worlds_failed", retry: "worlds" })
    expect(failing.options.map((option) => option.id)).toEqual(["w1", "w2"])

    const nothing = worlds({ list: { kind: "failed" } })
    expect(nothing).toMatchObject({ enabled: false, reason: "worlds_failed", retry: "worlds" })
  })

  it("names its destinations: a world route for explicit access, the route campaign's world page otherwise", () => {
    const model = worlds({
      list: ready([world("w1", "One")]),
      campaigns: [campaign("c1", "w1", "t1"), campaign("c2", "w2", "t2"), campaign("c3", "w2", "t3")],
      routeCampaignId: "c3",
    })
    const byId = Object.fromEntries(model.options.map((option) => [option.id, option.destination])) as Record<string, RouteDestination>
    expect(byId.w1).toEqual({ kind: "route", to: "/worlds/w1", root: "world", note: { level: "world", id: "w1" } })
    expect(byId.w2).toMatchObject({ to: "/app/c3/world", root: "world" })
  })
})

describe("meaningful choice (CN-2): Timeline", () => {
  const timelines = [
    { timeline_id: "t1", name: "Main" },
    { timeline_id: "t2", name: "Branch" },
  ]
  const base = {
    worldRead: "readable" as const,
    activeWorldId: "w1",
    activeTimelineId: null,
    activeTimelineName: null,
    worldTimelines: timelines,
    campaigns: [] as CampaignContext[],
  }

  it("lists the world's timelines in server order as world routes", () => {
    const model = timelineLevel(base)
    expect(model.options.map((option) => option.id)).toEqual(["t1", "t2"])
    expect(model.options[0]!.destination).toEqual({
      kind: "route",
      to: "/worlds/w1/timelines/t1",
      root: "world",
      note: { level: "timeline", id: "t1" },
    })
    expect(model).toMatchObject({ enabled: true, reason: null })
  })

  it("is disabled with 'no timeline' when the world has none", () => {
    expect(timelineLevel({ ...base, worldTimelines: [] })).toMatchObject({
      enabled: false,
      reason: "no_timeline",
    })
  })

  it("is disabled with 'no other timeline' for a sole selected timeline, enabled for a sole unselected one", () => {
    const sole = [timelines[0]!]
    expect(
      timelineLevel({ ...base, worldTimelines: sole, activeTimelineId: "t1", activeTimelineName: "Main" }),
    ).toMatchObject({ enabled: false, reason: "no_other_timeline" })
    expect(timelineLevel({ ...base, worldTimelines: sole })).toMatchObject({ enabled: true, reason: null })
  })

  it("never counts a display-only current timeline", () => {
    const model = timelineLevel({
      ...base,
      worldRead: "refused",
      activeTimelineId: "t1",
      activeTimelineName: "Main",
    })
    expect(model).toMatchObject({
      enabled: false,
      reason: "no_timeline",
      displayOnly: { id: "t1", label: "Main" },
    })
    expect(model.options).toEqual([])
  })

  it("asks for a world first when none is active", () => {
    expect(timelineLevel({ ...base, worldRead: "not_requested", activeWorldId: null })).toMatchObject({
      enabled: false,
      reason: "select_world_first",
    })
  })

  it("is disabled and loading while the world's first read is pending", () => {
    expect(timelineLevel({ ...base, worldRead: "pending" })).toMatchObject({
      enabled: false,
      reason: "loading_timelines",
      retry: null,
    })
  })

  it("shows a failed read with its retry, offering nothing it cannot prove", () => {
    expect(timelineLevel({ ...base, worldRead: "failed" })).toMatchObject({
      enabled: false,
      reason: "timelines_failed",
      retry: "world",
    })
    // The failure is shown even before the route's world is confirmed.
    expect(timelineLevel({ ...base, worldRead: "failed", activeWorldId: null })).toMatchObject({
      reason: "timelines_failed",
      retry: "world",
    })
  })
})

describe("meaningful choice (CN-2): Campaign", () => {
  const campaigns = [campaign("c1", "w1", "t1"), campaign("c2", "w1", "t1"), campaign("c3", "w1", "t2")]
  const base = {
    campaigns,
    activeWorldId: "w1",
    activeTimelineId: "t1",
    selected: null,
  }

  it("asks for a timeline first until a world and timeline are active", () => {
    expect(campaignLevel({ ...base, activeTimelineId: null })).toMatchObject({
      enabled: false,
      reason: "select_timeline_first",
    })
    expect(campaignLevel({ ...base, activeWorldId: null })).toMatchObject({
      reason: "select_timeline_first",
    })
  })

  it("offers only campaigns on the active world and timeline, in bootstrap order", () => {
    const model = campaignLevel(base)
    expect(model.options.map((option) => option.id)).toEqual(["c1", "c2"])
    expect(model.options[0]!.destination).toEqual({
      kind: "route",
      to: "/app/c1/home",
      root: "campaign",
      note: { level: "campaign", id: "c1" },
    })
    expect(model.enabled).toBe(true)
  })

  it("is disabled with 'no campaign' when none matches, and 'no other campaign' for the sole selected one", () => {
    expect(campaignLevel({ ...base, activeTimelineId: "t9" })).toMatchObject({
      enabled: false,
      reason: "no_campaign",
    })
    expect(
      campaignLevel({ ...base, activeTimelineId: "t2", selected: { id: "c3", label: "Campaign c3" } }),
    ).toMatchObject({ enabled: false, reason: "no_other_campaign" })
    expect(campaignLevel({ ...base, activeTimelineId: "t2" })).toMatchObject({ enabled: true, reason: null })
  })

  it("keeps a selected campaign the filter does not carry as inert display-only", () => {
    const model = campaignLevel({
      ...base,
      activeTimelineId: "t9",
      selected: { id: "c1", label: "Campaign c1" },
    })
    expect(model).toMatchObject({ enabled: false, reason: "no_campaign", displayOnly: { id: "c1" } })
  })
})

describe("World reconciliation by read start order", () => {
  const evidence = (...entries: [string, "readable" | "refused", number][]): WorldEvidenceMap =>
    new Map(entries.map(([id, verdict, startedSeq]) => [id, { verdict, startedSeq }]))
  const listed = (over: Partial<WorldLevelInput> = {}) =>
    worlds({ list: ready([world("w1", "One"), world("w2", "Two")], 2), ...over })
  const ids = (model: ReturnType<typeof worlds>) => model.options.map((option) => option.id)

  it("withdraws an explicit entry that a refusal started after the list read refused", () => {
    expect(ids(listed({ evidence: evidence(["w1", "refused", 3]) }))).toEqual(["w2"])
  })

  it("keeps a campaign-derived entry for the withdrawn world", () => {
    const model = listed({
      evidence: evidence(["w1", "refused", 3]),
      campaigns: [campaign("c1", "w1", "t1")],
    })
    // Entries sort by name: the campaign-derived "World w1" follows the explicit "Two".
    expect(ids(model)).toEqual(["w2", "w1"])
    expect(model.options.find((option) => option.id === "w1")!.destination).toMatchObject({
      to: "/app/c1/world",
    })
  })

  it("keeps the entry when the refusal STARTED before the list, whatever order they answered in", () => {
    expect(ids(listed({ evidence: evidence(["w1", "refused", 1]) }))).toEqual(["w1", "w2"])
    expect(explicitWorldValid("w1", 2, evidence(["w1", "refused", 2]))).toBe(true)
    expect(explicitWorldValid("w1", 2, evidence(["w1", "refused", 3]))).toBe(false)
  })

  it("restores the entry after a newer successful read or a newer list", () => {
    // refusal(2) then readable(3) leave a readable verdict.
    expect(ids(listed({ evidence: evidence(["w1", "readable", 3]) }))).toEqual(["w1", "w2"])
    // refusal(2) then a newer list(3) that still lists the world.
    expect(
      ids(
        listed({
          list: ready([world("w1", "One"), world("w2", "Two")], 3),
          evidence: evidence(["w1", "refused", 2]),
        }),
      ),
    ).toEqual(["w1", "w2"])
  })

  it("is not evidence when the list has not settled", () => {
    expect(explicitWorldValid("w1", null, evidence(["w1", "refused", 1]))).toBe(false)
    expect(explicitWorldValid("w1", null, evidence())).toBe(true)
  })

  it("adds no entry for a readable world the list does not carry, and withdraws nothing for others", () => {
    const model = listed({ evidence: evidence(["w9", "readable", 5]) })
    expect(ids(model)).toEqual(["w1", "w2"])
  })

  it("leaves buildWorldChoices output identical for an empty withdrawn set (All worlds is unchanged)", () => {
    const items = [world("w1", "One"), world("w2", "Two")]
    const campaigns = [campaign("c1", "w3", "t1")]
    const direct = buildWorldChoices(items, campaigns, "c1")
    const model = worldLevel({
      list: ready(items),
      campaigns,
      routeCampaignId: "c1",
      activeWorldId: null,
      activeWorldName: null,
      evidence: NO_EVIDENCE,
    })
    expect(model.options.map((option) => [option.id, option.label, (option.destination as RouteDestination).to])).toEqual(
      direct.map((choice) => [choice.world_id, choice.name, choice.to]),
    )
  })
})

describe("campaign-only Timeline destinations (CN-1)", () => {
  const input = (over: Partial<Parameters<typeof timelineLevel>[0]> = {}) =>
    timelineLevel({
      worldRead: "not_requested",
      activeWorldId: "w1",
      activeTimelineId: "t1",
      activeTimelineName: "Alpha",
      worldTimelines: [],
      campaigns: [],
      ...over,
    })
  const on = (id: string, timelineId: string | null, name: string | null, worldId = "w1") =>
    campaign(id, worldId, timelineId ?? "x", { timeline_id: timelineId, timeline_name: name } as Partial<CampaignContext>)
  const ids = (model: ReturnType<typeof timelineLevel>) => model.options.map((option) => option.id)

  it("derives one option per distinct timeline the caller's campaigns on the world represent", () => {
    const model = input({
      campaigns: [on("c1", "t1", "Alpha"), on("c2", "t1", "Alpha"), on("c3", "t2", "Beta"), on("c9", "t9", "Other", "w2")],
    })
    expect(ids(model)).toEqual(["t1", "t2"])
  })

  it("opens the campaign directly when exactly one is on the timeline, as a campaign task", () => {
    const model = input({ campaigns: [on("c1", "t1", "Alpha"), on("c3", "t2", "Beta")] })
    expect(model.options.find((option) => option.id === "t2")!.destination).toEqual({
      kind: "route",
      to: "/app/c3/home",
      root: "campaign",
      note: { level: "campaign", id: "c3" },
    })
  })

  it("asks for a choice when several campaigns are on it, in bootstrap order, never picking one", () => {
    const model = input({
      activeTimelineId: "t2",
      activeTimelineName: "Beta",
      campaigns: [on("c2", "t1", "Alpha"), on("c1", "t1", "Alpha"), on("c3", "t2", "Beta")],
    })
    expect(model.options.find((option) => option.id === "t1")!.destination).toEqual({
      kind: "chooseCampaign",
      timelineId: "t1",
      campaignIds: ["c2", "c1"],
    })
  })

  it("sorts by case-insensitive name then id, names a null name 'Unnamed timeline', and skips a campaign without a timeline", () => {
    const model = input({
      activeTimelineId: null,
      activeTimelineName: null,
      campaigns: [
        on("c1", "t3", "beta"),
        on("c2", "t2", "Alpha"),
        on("c3", "t1", "Alpha"),
        on("c4", "t4", null),
        on("c5", null, "Ghost"),
      ],
    })
    expect(ids(model)).toEqual(["t1", "t2", "t3", "t4"])
    expect(model.options.map((option) => option.label)).toEqual(["Alpha", "Alpha", "beta", "Unnamed timeline"])
  })

  it("enables the level only when another timeline exists, and counts the selected one once", () => {
    expect(input({ campaigns: [on("c1", "t1", "Alpha")] })).toMatchObject({
      enabled: false,
      reason: "no_other_timeline",
    })
    expect(input({ campaigns: [on("c1", "t1", "Alpha"), on("c2", "t2", "Beta")] })).toMatchObject({
      enabled: true,
      reason: null,
    })
  })

  it("derives from campaigns for a refused world and keeps them with a retry for a failed read", () => {
    const campaigns = [on("c1", "t1", "Alpha"), on("c2", "t2", "Beta")]
    expect(ids(input({ worldRead: "refused", campaigns }))).toEqual(["t1", "t2"])
    const failed = input({ worldRead: "failed", campaigns })
    expect(ids(failed)).toEqual(["t1", "t2"])
    expect(failed).toMatchObject({ enabled: true, reason: "timelines_failed", retry: "world" })
  })

  it("never derives while the read is pending, and says so", () => {
    expect(input({ worldRead: "pending", campaigns: [on("c1", "t1", "Alpha"), on("c2", "t2", "Beta")] })).toMatchObject({
      enabled: false,
      reason: "loading_timelines",
    })
  })

  it("explicit authority wins: a readable world offers only world routes, one option per timeline", () => {
    const model = input({
      worldRead: "readable",
      worldTimelines: [
        { timeline_id: "t1", name: "Alpha" },
        { timeline_id: "t2", name: "Beta" },
      ],
      campaigns: [on("c1", "t1", "Alpha"), on("c2", "t1", "Alpha"), on("c3", "t2", "Beta")],
    })
    expect(ids(model)).toEqual(["t1", "t2"])
    for (const option of model.options) {
      expect(option.destination).toMatchObject({ kind: "route", root: "world" })
      expect((option.destination as RouteDestination).to).toMatch(/^\/worlds\/w1\/timelines\//)
    }
  })

  it("never builds a world route from campaigns", () => {
    const model = input({
      worldRead: "refused",
      campaigns: [on("c1", "t1", "Alpha"), on("c2", "t1", "Alpha"), on("c3", "t2", "Beta")],
    })
    for (const option of model.options) {
      const destination = option.destination
      expect(destination.kind === "route" ? destination.to : "").not.toContain("/worlds/")
    }
  })

  it("reports a vanished chooser timeline without changing the options", () => {
    expect(input({ timelineGone: true, campaigns: [on("c1", "t1", "Alpha"), on("c2", "t2", "Beta")] })).toMatchObject({
      enabled: true,
      reason: "timeline_gone",
    })
  })
})

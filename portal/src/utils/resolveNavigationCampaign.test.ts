import { describe, expect, it } from "vitest"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import type { SessionBootstrap } from "../types/bootstrap"
import {
    resolveNavigationCampaign,
    type NavigationWorldScope,
} from "./resolveNavigationCampaign"

const first = sessionBootstrapFixture.campaigns[0]!
const second = { ...first, campaign_id: "second", campaign_name: "Second" }
const third = { ...first, campaign_id: "third", campaign_name: "Third" }

function bootstrap(overrides: Partial<SessionBootstrap> = {}): SessionBootstrap {
    return {
        ...sessionBootstrapFixture,
        startup_campaign_id: null,
        campaign_preferences: {
            startup_mode: "resume_last_visited",
            preferred_campaign_id: null,
            last_visited_campaign_id: null,
        },
        campaigns: [first, second, third],
        ...overrides,
    }
}

const preferences = (lastVisited: string | null) => ({
    startup_mode: "resume_last_visited" as const,
    preferred_campaign_id: null,
    last_visited_campaign_id: lastVisited,
})

describe("resolveNavigationCampaign", () => {
    it("prefers the route campaign over every selection and preference", () => {
        const value = bootstrap({ startup_campaign_id: "third", campaign_preferences: preferences("second") })
        expect(resolveNavigationCampaign(value, "mundivita", null, "third")?.campaign_id).toBe("mundivita")
    })

    it("resolves the selected campaign on an unscoped route", () => {
        expect(resolveNavigationCampaign(bootstrap(), undefined, null, "second")?.campaign_id).toBe("second")
    })

    it("never guesses from the last-visited or startup campaign when nothing is selected", () => {
        const value = bootstrap({ startup_campaign_id: "third", campaign_preferences: preferences("second") })
        expect(resolveNavigationCampaign(value, undefined)).toBeNull()
        expect(resolveNavigationCampaign(value, undefined, null, null)).toBeNull()
    })

    it("never resolves an unauthorized route or selected campaign", () => {
        const value = bootstrap({ startup_campaign_id: "ghost-startup", campaign_preferences: preferences("ghost") })
        expect(resolveNavigationCampaign(value, "ghost-route", null, "second")).toBeNull()
        expect(resolveNavigationCampaign(value, undefined, null, "ghost-selected")).toBeNull()
    })

    it("does not replace a route that names an unauthorized campaign with a selection", () => {
        const value = bootstrap({ startup_campaign_id: "second", campaign_preferences: preferences("third") })
        expect(resolveNavigationCampaign(value, "ghost-route", null, "second")).toBeNull()
    })

    it("returns null with no campaigns", () => {
        expect(resolveNavigationCampaign(bootstrap({ campaigns: [] }), undefined, null, "second")).toBeNull()
    })
})

describe("resolveNavigationCampaign with a world route", () => {
    const inW1 = { ...first, campaign_id: "w1-a", world_id: "w1", timeline_id: "t1" }
    const inW1Other = { ...first, campaign_id: "w1-b", world_id: "w1", timeline_id: "t2" }
    const inW2 = { ...first, campaign_id: "w2-a", world_id: "w2", timeline_id: "t3" }

    function scope(overrides: Partial<NavigationWorldScope> = {}): NavigationWorldScope {
        return {
            routeNamesWorld: true,
            routeNamesTimeline: false,
            activeWorldId: "w2",
            activeTimelineId: null,
            ...overrides,
        }
    }

    const value = bootstrap({
        campaigns: [inW1, inW1Other, inW2],
        startup_campaign_id: "w1-a",
        campaign_preferences: preferences("w1-b"),
    })

    it("keeps the selected campaign only when it belongs to the confirmed world", () => {
        expect(resolveNavigationCampaign(value, undefined, scope({ activeWorldId: "w1" }), "w1-a")?.campaign_id).toBe("w1-a")
        expect(resolveNavigationCampaign(value, undefined, scope({ activeWorldId: "w2" }), "w1-a")).toBeNull()
    })

    it("ignores saved preferences and a world's only campaign when nothing is selected", () => {
        expect(resolveNavigationCampaign(value, undefined, scope({ activeWorldId: "w2" }), null)).toBeNull()
        expect(resolveNavigationCampaign(value, undefined, scope({ activeWorldId: "w1" }), null)).toBeNull()
    })

    it("narrows to the selected timeline", () => {
        const timelineScope = scope({ activeWorldId: "w1", routeNamesTimeline: true, activeTimelineId: "t2" })
        expect(resolveNavigationCampaign(value, undefined, timelineScope, "w1-b")?.campaign_id).toBe("w1-b")
        expect(resolveNavigationCampaign(value, undefined, timelineScope, "w1-a")).toBeNull()
    })

    it("resolves nothing while the route's world is unconfirmed", () => {
        expect(resolveNavigationCampaign(value, undefined, scope({ activeWorldId: null }), "w1-a")).toBeNull()
    })

    it("resolves nothing for a timeline that was named but not confirmed", () => {
        expect(
            resolveNavigationCampaign(
                value,
                undefined,
                scope({ activeWorldId: "w1", routeNamesTimeline: true, activeTimelineId: null }),
                "w1-a",
            ),
        ).toBeNull()
    })

    it("still prefers an authorized route campaign over the world route", () => {
        expect(resolveNavigationCampaign(value, "w2-a", scope({ activeWorldId: "w1" }), "w1-a")?.campaign_id).toBe("w2-a")
    })

    it("uses the selected campaign when the route names no world", () => {
        expect(
            resolveNavigationCampaign(
                value,
                undefined,
                scope({ routeNamesWorld: false, activeWorldId: null }),
                "w1-a",
            )?.campaign_id,
        ).toBe("w1-a")
    })
})

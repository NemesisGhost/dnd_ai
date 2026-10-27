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

describe("resolveNavigationCampaign", () => {
    it("prefers the route campaign", () => {
        const value = bootstrap({
            startup_campaign_id: "third",
            campaign_preferences: {
                startup_mode: "resume_last_visited",
                preferred_campaign_id: null,
                last_visited_campaign_id: "second",
            },
        })
        expect(resolveNavigationCampaign(value, "mundivita")?.campaign_id).toBe("mundivita")
    })

    it("falls back to last visited, then to the startup campaign", () => {
        const withBoth = bootstrap({
            startup_campaign_id: "third",
            campaign_preferences: {
                startup_mode: "resume_last_visited",
                preferred_campaign_id: null,
                last_visited_campaign_id: "second",
            },
        })
        expect(resolveNavigationCampaign(withBoth, undefined)?.campaign_id).toBe("second")

        const startupOnly = bootstrap({ startup_campaign_id: "third" })
        expect(resolveNavigationCampaign(startupOnly, undefined)?.campaign_id).toBe("third")
    })

    it("never resolves an unauthorized route or stored campaign", () => {
        const value = bootstrap({
            startup_campaign_id: "ghost-startup",
            campaign_preferences: {
                startup_mode: "resume_last_visited",
                preferred_campaign_id: null,
                last_visited_campaign_id: "ghost-visited",
            },
        })
        expect(resolveNavigationCampaign(value, "ghost-route")).toBeNull()
    })

    it("does not replace a route that names an unauthorized campaign with a valid fallback", () => {
        const value = bootstrap({
            startup_campaign_id: "second",
            campaign_preferences: {
                startup_mode: "resume_last_visited",
                preferred_campaign_id: null,
                last_visited_campaign_id: "third",
            },
        })
        expect(resolveNavigationCampaign(value, "ghost-route")).toBeNull()
        // No campaign in the route: the saved fallback still applies.
        expect(resolveNavigationCampaign(value, undefined)?.campaign_id).toBe("third")
    })

    it("returns null with no campaigns", () => {
        expect(resolveNavigationCampaign(bootstrap({ campaigns: [] }), undefined)).toBeNull()
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

    function withPreferences(lastVisited: string | null, startup: string | null = null) {
        return bootstrap({
            campaigns: [inW1, inW1Other, inW2],
            startup_campaign_id: startup,
            campaign_preferences: {
                startup_mode: "resume_last_visited",
                preferred_campaign_id: null,
                last_visited_campaign_id: lastVisited,
            },
        })
    }

    it("does not let a saved campaign from another world override the selected world", () => {
        const value = withPreferences("w1-a", "w1-b")
        expect(resolveNavigationCampaign(value, undefined, scope())?.campaign_id).toBe("w2-a")
    })

    it("uses a saved campaign that belongs to the selected world", () => {
        const value = withPreferences("w1-b", "w1-a")
        expect(
            resolveNavigationCampaign(value, undefined, scope({ activeWorldId: "w1" }))
                ?.campaign_id,
        ).toBe("w1-b")
        expect(
            resolveNavigationCampaign(
                withPreferences("w2-a", "w1-a"),
                undefined,
                scope({ activeWorldId: "w1" }),
            )?.campaign_id,
        ).toBe("w1-a")
    })

    it("resolves nothing when the world has several campaigns and no saved one belongs to it", () => {
        expect(
            resolveNavigationCampaign(
                withPreferences("w2-a"),
                undefined,
                scope({ activeWorldId: "w1" }),
            ),
        ).toBeNull()
    })

    it("narrows to the selected timeline", () => {
        expect(
            resolveNavigationCampaign(
                withPreferences("w1-a", "w1-b"),
                undefined,
                scope({ activeWorldId: "w1", activeTimelineId: "t2" }),
            )?.campaign_id,
        ).toBe("w1-b")
    })

    it("resolves nothing while the route's world is unconfirmed", () => {
        expect(
            resolveNavigationCampaign(
                withPreferences("w1-a"),
                undefined,
                scope({ activeWorldId: null }),
            ),
        ).toBeNull()
    })

    it("never falls back to saved defaults for a world that is not confirmed or usable", () => {
        // Still loading, unknown, denied, or failed all leave no active world.
        expect(
            resolveNavigationCampaign(
                withPreferences("w1-a", "w1-b"),
                undefined,
                scope({ activeWorldId: null }),
            ),
        ).toBeNull()
    })

    it("resolves nothing for a timeline that was named but not confirmed", () => {
        expect(
            resolveNavigationCampaign(
                withPreferences("w1-a", "w1-b"),
                undefined,
                scope({ activeWorldId: "w1", routeNamesTimeline: true, activeTimelineId: null }),
            ),
        ).toBeNull()
    })

    it("still prefers an authorized route campaign over the world route", () => {
        expect(
            resolveNavigationCampaign(withPreferences("w1-a"), "w2-a", scope({ activeWorldId: "w1" }))
                ?.campaign_id,
        ).toBe("w2-a")
    })

    it("uses saved defaults when the route names no world", () => {
        expect(
            resolveNavigationCampaign(
                withPreferences("w1-a"),
                undefined,
                scope({ routeNamesWorld: false, activeWorldId: null }),
            )?.campaign_id,
        ).toBe("w1-a")
    })
})

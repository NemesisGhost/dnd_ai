import { describe, expect, it } from "vitest"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import type { SessionBootstrap } from "../types/bootstrap"
import { resolveNavigationCampaign } from "./resolveNavigationCampaign"

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

    it("skips a bad route ID but still uses a valid fallback", () => {
        const value = bootstrap({ startup_campaign_id: "second" })
        expect(resolveNavigationCampaign(value, "ghost-route")?.campaign_id).toBe("second")
    })

    it("returns null with no campaigns", () => {
        expect(resolveNavigationCampaign(bootstrap({ campaigns: [] }), undefined)).toBeNull()
    })
})

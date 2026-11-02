import { screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import { CampaignSetupPage } from "./CampaignSetupPage"

function timeline(id: string, name: string, hosting: { eligible: boolean; reason: string | null }) {
    return {
        timeline_id: id,
        name,
        description: null,
        is_primary: id === "t1",
        parent_timeline_id: null,
        branch_point: null,
        lifecycle_status: "active",
        row_version: 1,
        campaign_hosting: hosting,
    }
}

function setup(timelines: ReturnType<typeof timeline>[]) {
    const server = installMockServer()
    server.on("GET", "/worlds/w1", {
        body: {
            world_id: "w1",
            name: "Eberron",
            description: null,
            lifecycle_status: "active",
            row_version: 1,
            primary_timeline_id: "t1",
            capabilities: ["world.view", "campaign.create"],
            default_ruleset_id: null,
            allowed_rulesets: [],
            timelines,
            managed_campaigns: [],
            available_actions: ["create_campaign"],
            blocked_actions: [],
        },
    })
    renderAuthoringRoutes({
        initialEntry: "/campaigns/new?worldId=w1",
        routes: [{ path: "/campaigns/new", element: <CampaignSetupPage /> }],
    })
}

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("CampaignSetupPage timeline step", () => {
    it("offers only the timelines the server says the caller may host a campaign on", async () => {
        setup([
            timeline("t1", "Primary Timeline", { eligible: false, reason: "timeline_in_use" }),
            timeline("t2", "A Branch For Me", { eligible: true, reason: null }),
        ])
        expect(await screen.findByRole("radio", { name: /A Branch For Me/ })).toBeInTheDocument()
        expect(screen.queryByRole("radio", { name: /Primary Timeline/ })).not.toBeInTheDocument()
        // The unavailable one is explained, not silently dropped.
        expect(screen.getByText(/Primary Timeline:/)).toHaveTextContent(
            "already hosts a campaign. Ask a world owner or editor to branch a timeline for you.",
        )
        expect(screen.getByRole("radio", { name: /A Branch For Me/ })).toBeChecked()
    })

    it("says so when no timeline is available", async () => {
        setup([timeline("t1", "Primary Timeline", { eligible: false, reason: "timeline_in_use" })])
        expect(
            await screen.findByText("No timeline in this world is available to you right now."),
        ).toBeInTheDocument()
        expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled()
    })
})

import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import {
    TEST_CSRF,
    bootstrapWith,
    installMockServer,
    renderAuthoringRoutes,
} from "../test/authoringHarness"
import { CampaignSettingsPage } from "./CampaignSettingsPage"
import { CampaignSetupPage } from "./CampaignSetupPage"
import { CampaignsPage } from "./CampaignsPage"
import { CampaignHomePage } from "./CampaignHomePage"

const worldSummary = (id: string, name: string, caps = ["campaign.create"]) => ({
    world_id: id,
    name,
    description: null,
    lifecycle_status: "active",
    row_version: 1,
    primary_timeline_id: "t1",
    capabilities: caps,
})

const worldDetail = {
    ...worldSummary("w1", "Eberron"),
    default_ruleset_id: "r1",
    allowed_rulesets: [
        {
            ruleset_id: "r1",
            code: "dnd5e",
            display_name: "D&D 5e",
            is_default: true,
            current_version: { ruleset_version_id: "rv1", version_label: "2024" },
        },
    ],
    timelines: [
        { timeline_id: "t1", name: "Main", description: null, is_primary: true, parent_timeline_id: null, branch_point: null, lifecycle_status: "active", row_version: 1 },
        { timeline_id: "t2", name: "Side", description: null, is_primary: false, parent_timeline_id: null, branch_point: null, lifecycle_status: "active", row_version: 1 },
        { timeline_id: "t3", name: "Old", description: null, is_primary: false, parent_timeline_id: null, branch_point: null, lifecycle_status: "archived", row_version: 1 },
    ],
    managed_campaigns: [],
    available_actions: ["update", "archive", "create_timeline", "create_campaign"],
    blocked_actions: [],
}

const routes = [
    { path: "/campaigns/new", element: <CampaignSetupPage /> },
    { path: "/campaigns", element: <p>Campaigns list</p> },
    { path: "/worlds/new", element: <p>New world page</p> },
    { path: "/app/:campaignId/home", element: <p>Campaign home page</p> },
]

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("CampaignSetupPage", () => {
    function setup(entry: string, options: { refreshes?: boolean } = {}) {
        const server = installMockServer()
        server.on("GET", /^\/worlds\?status=active/, {
            body: {
                items: [
                    worldSummary("w1", "Eberron"),
                    worldSummary("w2", "Readonly", ["world.view"]),
                ],
                next_cursor: null,
            },
        })
        server.on("GET", "/worlds/w1", { body: worldDetail })
        const created = {
            ...sessionBootstrapFixture.campaigns[0]!,
            campaign_id: "c-new",
            campaign_name: "Fresh",
        }
        const rendered = renderAuthoringRoutes({
            initialEntry: entry,
            routes,
            bootstrap: bootstrapWith(),
            onRefresh:
                options.refreshes === false
                    ? () => Promise.reject(new Error("offline"))
                    : async () => bootstrapWith({ campaigns: [created] }),
        })
        return { server, ...rendered }
    }

    it("step 1 offers only worlds the server says can host a campaign, plus creating a new one", async () => {
        setup("/campaigns/new")
        expect(await screen.findByRole("radio", { name: "Eberron" })).toBeInTheDocument()
        expect(screen.queryByRole("radio", { name: "Readonly" })).not.toBeInTheDocument()
        expect(screen.getByRole("link", { name: "Create a new world" })).toHaveAttribute(
            "href",
            "/worlds/new?returnTo=/campaigns/new",
        )
        expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled()
        expect(screen.getByRole("listitem", { current: "step" })).toHaveTextContent("1. World")
    })

    it("walks the steps through the URL so Back and refresh resume them", async () => {
        const { router } = setup("/campaigns/new")
        fireEvent.click(await screen.findByRole("radio", { name: "Eberron" }))
        fireEvent.click(screen.getByRole("button", { name: "Continue" }))
        await screen.findByRole("radio", { name: "Main (primary)" })
        expect(router.state.location.search).toBe("?worldId=w1")
        // The primary timeline is preselected; archived timelines are not offered.
        expect(screen.getByRole("radio", { name: "Main (primary)" })).toBeChecked()
        expect(screen.queryByRole("radio", { name: "Old" })).not.toBeInTheDocument()

        fireEvent.click(screen.getByRole("button", { name: "Continue" }))
        await screen.findByRole("textbox", { name: /Campaign name/ })
        expect(router.state.location.search).toBe("?worldId=w1&timelineId=t1")
        expect(screen.getByRole("listitem", { current: "step" })).toHaveTextContent("3. Details")
    })

    it("resumes directly at the details step from the URL", async () => {
        setup("/campaigns/new?worldId=w1&timelineId=t2")
        expect(await screen.findByRole("textbox", { name: /Campaign name/ })).toBeInTheDocument()
        // A single ruleset version is preselected.
        expect(screen.getByRole("combobox", { name: /Ruleset version/ })).toHaveValue("rv1")
    })

    it("rejects a timeline in the URL that is not an active timeline of the world", async () => {
        setup("/campaigns/new?worldId=w1&timelineId=t3")
        expect(await screen.findByRole("alert")).toHaveTextContent("not available for new campaigns")
    })

    it("validates, creates, refreshes the bootstrap, and navigates only once the campaign is listed", async () => {
        const { server, router } = setup("/campaigns/new?worldId=w1&timelineId=t1")
        server.on("POST", "/campaigns", {
            status: 201,
            body: { campaign_id: "c-new", campaign_membership_id: "m" },
        })
        await screen.findByRole("textbox", { name: /Campaign name/ })
        fireEvent.click(screen.getByRole("button", { name: "Create campaign" }))
        expect(await screen.findByRole("alert")).toHaveTextContent("Name is required.")
        expect(server.callsTo("POST", "/campaigns")).toHaveLength(0)

        fireEvent.change(screen.getByRole("textbox", { name: /Campaign name/ }), { target: { value: "Fresh" } })
        fireEvent.click(screen.getByRole("button", { name: "Create campaign" }))
        await screen.findByText("Campaign home page")
        expect(router.state.location.pathname).toBe("/app/c-new/home")
        expect(router.state.location.state).toEqual({ announce: "Campaign created" })
        const [call] = server.callsTo("POST", "/campaigns")
        expect(call!.headers["X-CSRF-Token"]).toBe(TEST_CSRF)
        expect(call!.body).toEqual({
            timeline_id: "t1",
            ruleset_version_id: "rv1",
            name: "Fresh",
            description: null,
        })
    })

    it("never navigates on a guess: if the bootstrap refresh fails it offers to open the campaign", async () => {
        const { server, router } = setup("/campaigns/new?worldId=w1&timelineId=t1", { refreshes: false })
        server.on("POST", "/campaigns", {
            status: 201,
            body: { campaign_id: "c-new", campaign_membership_id: "m" },
        })
        await screen.findByRole("textbox", { name: /Campaign name/ })
        fireEvent.change(screen.getByRole("textbox", { name: /Campaign name/ }), { target: { value: "Fresh" } })
        fireEvent.click(screen.getByRole("button", { name: "Create campaign" }))
        expect(await screen.findByRole("button", { name: "Open the campaign" })).toBeInTheDocument()
        expect(router.state.location.pathname).toBe("/campaigns/new")
        expect(screen.getByRole("alert")).toHaveTextContent("Campaign created.")
    })

    it("keeps input after a server failure and cancel returns to the list", async () => {
        const { server } = setup("/campaigns/new?worldId=w1&timelineId=t1")
        server.on("POST", "/campaigns", { status: 500 })
        await screen.findByRole("textbox", { name: /Campaign name/ })
        fireEvent.change(screen.getByRole("textbox", { name: /Campaign name/ }), { target: { value: "Keep me" } })
        fireEvent.click(screen.getByRole("button", { name: "Create campaign" }))
        expect(await screen.findByText(/input has been kept/)).toBeInTheDocument()
        expect(screen.getByRole("textbox", { name: /Campaign name/ })).toHaveValue("Keep me")

        fireEvent.click(screen.getByRole("button", { name: "Cancel" }))
        fireEvent.click(await screen.findByRole("button", { name: "Discard changes" }))
        await screen.findByText("Campaigns list")
    })
})

describe("CampaignSettingsPage", () => {
    const settings = (over: object = {}) => ({
        campaign_id: "mundivita",
        name: "Mundivita",
        description: null,
        lifecycle_status: "active",
        row_version: 4,
        world: { world_id: "w1", name: "Eberron" },
        timeline: { timeline_id: "t1", name: "Main" },
        ruleset_version: { ruleset_version_id: "rv1", ruleset_display_name: "D&D 5e", version_label: "2024" },
        available_actions: ["update", "archive"],
        blocked_actions: [],
        ...over,
    })
    const manager = {
        ...sessionBootstrapFixture.campaigns[0]!,
        campaign_id: "mundivita",
        capabilities: ["access.manage", "campaign.view"],
    }
    const routesWithSettings = [
        { path: "/app/:campaignId/settings", element: <CampaignSettingsPage /> },
        { path: "/campaigns", element: <p>Campaigns list</p> },
        { path: "/app/:campaignId/home", element: <p>Campaign home page</p> },
    ]

    it("is unavailable without access.manage in the bootstrap and sends no request", async () => {
        const server = installMockServer()
        renderAuthoringRoutes({
            initialEntry: "/app/mundivita/settings",
            routes: routesWithSettings,
            bootstrap: bootstrapWith({ campaigns: [{ ...manager, capabilities: ["campaign.view"] }] }),
        })
        expect(await screen.findByRole("alert")).toHaveTextContent("do not have permission")
        expect(server.calls).toHaveLength(0)
    })

    it("shows the fixed world/timeline/ruleset and saves edits with the row version", async () => {
        const server = installMockServer()
        server.on("GET", "/campaigns/mundivita/settings", () => ({ body: settings() }))
        server.on("POST", "/campaigns/mundivita/update", { body: { campaign_id: "mundivita", row_version: 5 } })
        renderAuthoringRoutes({
            initialEntry: "/app/mundivita/settings",
            routes: routesWithSettings,
            bootstrap: bootstrapWith({ campaigns: [manager] }),
            onRefresh: async () => bootstrapWith({ campaigns: [manager] }),
        })
        const name = await screen.findByRole("textbox", { name: /Campaign name/ })
        expect(screen.getByText("Eberron")).toBeInTheDocument()
        expect(screen.getByText("D&D 5e — 2024")).toBeInTheDocument()
        fireEvent.change(name, { target: { value: "Renamed" } })
        fireEvent.click(screen.getByRole("button", { name: "Save" }))
        await waitFor(() => expect(server.callsTo("POST", "/campaigns/mundivita/update")).toHaveLength(1))
        expect(server.callsTo("POST", "/campaigns/mundivita/update")[0]!.body).toEqual({
            expected_row_version: 4,
            name: "Renamed",
            description: null,
        })
    })

    it("archives through a confirmation, refreshes the bootstrap, and returns to Campaigns with an announcement", async () => {
        const server = installMockServer()
        server.on("GET", "/campaigns/mundivita/settings", { body: settings() })
        server.on("POST", "/campaigns/mundivita/archive", {
            body: { campaign_id: "mundivita", lifecycle_status: "archived", row_version: 5 },
        })
        const { router } = renderAuthoringRoutes({
            initialEntry: "/app/mundivita/settings",
            routes: routesWithSettings,
            bootstrap: bootstrapWith({ campaigns: [manager] }),
            onRefresh: async () => bootstrapWith({ campaigns: [] }),
        })
        await screen.findByRole("textbox", { name: /Campaign name/ })
        fireEvent.click(screen.getByRole("button", { name: "Archive campaign" }))
        const dialog = screen.getByRole("dialog", { name: "Archive this campaign?", hidden: true })
        fireEvent.click(within(dialog).getByRole("button", { name: "Archive campaign" }))
        await screen.findByText("Campaigns list")
        expect(router.state.location.state).toEqual({ announce: "Campaign archived" })
        expect(server.callsTo("POST", "/campaigns/mundivita/archive")[0]!.body).toEqual({
            expected_row_version: 4,
            reason: null,
        })
    })

    it("hides Archive when the server does not offer it and explains why", async () => {
        const server = installMockServer()
        server.on("GET", "/campaigns/mundivita/settings", {
            body: settings({ available_actions: ["update"], blocked_actions: [{ action: "archive", reason: "campaign_archived" }] }),
        })
        renderAuthoringRoutes({
            initialEntry: "/app/mundivita/settings",
            routes: routesWithSettings,
            bootstrap: bootstrapWith({ campaigns: [manager] }),
        })
        await screen.findByRole("textbox", { name: /Campaign name/ })
        expect(screen.queryByRole("button", { name: "Archive campaign" })).not.toBeInTheDocument()
        expect(screen.getByRole("list", { name: "Unavailable actions" })).toHaveTextContent("campaign is archived")
    })
})

describe("Campaigns page additions", () => {
    function renderCampaigns(archived: object[], bootstrap = bootstrapWith()) {
        const server = installMockServer()
        server.on("GET", /^\/campaigns\/archived/, () => ({ body: { items: archived, next_cursor: null } }))
        server.on("POST", /\/reactivate$/, { body: { campaign_id: "ca", row_version: 6, lifecycle_status: "active" } })
        const rendered = renderAuthoringRoutes({
            initialEntry: "/campaigns",
            routes: [{ path: "/campaigns", element: <CampaignsPage bootstrap={bootstrap} /> }],
            bootstrap,
            onRefresh: async () => bootstrap,
        })
        return { server, ...rendered }
    }

    it("offers Create campaign only with the server-computed capability", async () => {
        renderCampaigns([])
        expect(await screen.findByRole("link", { name: "Create campaign" })).toHaveAttribute("href", "/campaigns/new")
    })

    it("omits Create campaign without the capability", async () => {
        renderCampaigns([], bootstrapWith({ global_capabilities: [] }))
        await screen.findByRole("heading", { name: "Campaigns" })
        expect(screen.queryByRole("link", { name: "Create campaign" })).not.toBeInTheDocument()
    })

    it("lists archived campaigns the caller manages and reactivates one after confirmation", async () => {
        const { server } = renderCampaigns([
            { campaign_id: "ca", name: "Old Run", world_name: "Eberron", timeline_name: "Main", row_version: 5 },
        ])
        expect(await screen.findByRole("heading", { name: "Archived campaigns you manage" })).toBeInTheDocument()
        expect(screen.getByText("Eberron · Main")).toBeInTheDocument()
        fireEvent.click(screen.getByRole("button", { name: "Reactivate Old Run" }))
        const dialog = screen.getByRole("dialog", { name: "Reactivate this campaign?", hidden: true })
        fireEvent.click(within(dialog).getByRole("button", { name: "Reactivate campaign" }))
        await waitFor(() => expect(server.callsTo("POST", /\/reactivate$/)).toHaveLength(1))
        expect(server.callsTo("POST", /\/reactivate$/)[0]!.body).toEqual({ expected_row_version: 5 })
        await waitFor(() =>
            expect(screen.getByTestId("authoring-announcer")).toHaveTextContent("Campaign reactivated"),
        )
    })

    it("shows an actionable message when reactivation is blocked", async () => {
        const { server } = renderCampaigns([
            { campaign_id: "ca", name: "Old Run", world_name: "Eberron", timeline_name: "Main", row_version: 5 },
        ])
        server.on("POST", /\/reactivate$/, {
            status: 409,
            body: { error: { code: "world_archived", message: "m", correlation_id: "c" } },
        })
        fireEvent.click(await screen.findByRole("button", { name: "Reactivate Old Run" }))
        fireEvent.click(within(screen.getByRole("dialog", { hidden: true })).getByRole("button", { name: "Reactivate campaign" }))
        expect(await screen.findByText(/The world is archived/)).toBeInTheDocument()
    })
})

describe("Campaign Home Get started card", () => {
    const empty = { current_session: null, previous_session_recap: null, recent_events: [] }
    const manager = (caps: string[]) => ({
        ...sessionBootstrapFixture.campaigns[0]!,
        campaign_id: "mundivita",
        capabilities: caps,
    })

    function renderHome(summary: object, caps: string[]) {
        const server = installMockServer()
        server.on("GET", "/campaigns/mundivita/summary", { body: summary })
        return renderAuthoringRoutes({
            initialEntry: "/app/mundivita/home",
            routes: [{ path: "/app/:campaignId/home", element: <CampaignHomePage /> }],
            bootstrap: bootstrapWith({ campaigns: [manager(caps)] }),
        })
    }

    it("shows for a manager of an empty campaign with real next steps", async () => {
        renderHome(empty, ["access.manage", "campaign.view"])
        const card = await screen.findByRole("region", { name: "Get started" })
        expect(within(card).getByRole("link", { name: "Invite players" })).toHaveAttribute(
            "href",
            "/app/mundivita/access/invitations",
        )
        expect(within(card).getByRole("link", { name: "Review campaign settings" })).toHaveAttribute(
            "href",
            "/app/mundivita/settings",
        )
        // The rest of the empty Home still renders.
        expect(screen.getByText("No sessions have been recorded.")).toBeInTheDocument()
    })

    it("does not show for a player", async () => {
        renderHome(empty, ["campaign.view"])
        await screen.findByText("No sessions have been recorded.")
        expect(screen.queryByRole("region", { name: "Get started" })).not.toBeInTheDocument()
    })

    it("does not show once the campaign has content", async () => {
        renderHome({ ...empty, previous_session_recap: "They fought a dragon." }, ["access.manage", "campaign.view"])
        await screen.findByText("They fought a dragon.")
        expect(screen.queryByRole("region", { name: "Get started" })).not.toBeInTheDocument()
    })
})

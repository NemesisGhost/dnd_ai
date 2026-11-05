import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { openApp } from "./test/campaignRoutes"
import { installMockServer } from "./test/authoringHarness"
import type { MockServer } from "./test/authoringHarness"

// P02-7e: Campaign settings and Access. The shared breadcrumb (validated task, route defaults after a direct
// entry) replaces the settings page's unstyled bottom link and sits above the Invitations and Audit tabs.
// The pages' reads, guards and commands are unchanged. These run the whole App over a memory data router
// (jsdom): they prove destinations, carried state, requests and rendered authorized content, not real-browser
// keyboard, focus, zoom, screen-reader or native-dialog behavior.

vi.mock("./hooks/useSessionBootstrap", () => ({ useSessionBootstrap: vi.fn() }))
vi.mock("./api/userPreferences", () => ({
    recordLastVisitedCampaign: vi.fn(() => Promise.resolve()),
}))

const base = "/app/mundivita"
const API = "/campaigns/mundivita"

const settingsBody = (over: object = {}) => ({
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

let server: MockServer
// The first registered handler wins, so a test changes the settings answer through this gate.
let settingsGate: () => { status?: number; body: unknown }

beforeEach(() => {
    server = installMockServer()
    server.on("GET", /^\/campaigns\/mundivita\/world\/search/, { body: { items: [], next_cursor: null } })
    server.on("GET", /^\/campaigns\/mundivita\/summary/, {
        body: { current_session: null, previous_session_recap: null, recent_events: [] },
    })
    server.on("GET", /^\/worlds\?/, { body: { items: [], next_cursor: null } })
    settingsGate = () => ({ body: settingsBody() })
    server.on("GET", `${API}/settings`, () => settingsGate())
    server.on("GET", `${API}/invitations`, { body: { invitations: [] } })
    server.on("GET", /audit-history/, { body: { items: [], next_cursor: null, actors: [] } })
})

afterEach(() => {
    vi.unstubAllGlobals()
})

type Opened = ReturnType<typeof openApp>
const breadcrumb = () => within(screen.getByRole("navigation", { name: "Breadcrumb" }))
const trail = () => breadcrumb().getAllByRole("listitem").map((item) => item.textContent)
const trailLinks = () => breadcrumb().getAllByRole("link").map((link) => link.getAttribute("href"))
const entryState = (app: Pick<Opened, "router">) => app.router.state.location.state as { task?: { root: string } } | null
const gets = () => server.calls.filter((call) => call.method === "GET").map((call) => call.path)
const nonGets = () => server.calls.filter((call) => call.method !== "GET")

describe("Campaign settings", () => {
    it("shows Campaign Home then the page, after a direct entry too, and the link carries a task without a name", async () => {
        const app = openApp(`${base}/settings`)
        await screen.findByRole("textbox", { name: /Campaign name/ })
        expect(trail()).toEqual(["Campaign Home", "Campaign settings"])
        expect(trailLinks()).toEqual([`${base}/home`])
        expect(breadcrumb().getByText("Campaign settings")).toHaveAttribute("aria-current", "page")
        expect(screen.queryByRole("link", { name: "Back to Campaign Home" })).toBeNull()
        fireEvent.click(breadcrumb().getByRole("link", { name: "Campaign Home" }))
        await waitFor(() => expect(app.router.state.location.pathname).toBe(`${base}/home`))
        expect(entryState(app)?.task).toMatchObject({ root: "campaign" })
        expect(JSON.stringify(entryState(app))).not.toContain("Mundivita")
        // A new entry on top of the settings page, not a replacement of it.
        await app.router.navigate(-1)
        await screen.findByRole("textbox", { name: /Campaign name/ })
        expect(app.router.state.location.pathname).toBe(`${base}/settings`)
    })

    it("malformed, foreign and unsupported task state falls back to the same trail", async () => {
        const app = openApp(`${base}/home`)
        const crafted: unknown[] = [
            { task: { v: 1, root: "campaign", scope: { campaignId: "other" }, trail: [] } },
            { task: { v: 1, root: "nowhere", scope: { campaignId: "mundivita" }, trail: [] } },
            { task: { v: 1, root: "characters", scope: { campaignId: "mundivita" }, trail: [] } },
            { returnTo: { pathname: "//evil.example", search: "" } },
            { worldSearch: "?returnTo=https://evil" },
            "text",
        ]
        for (const state of crafted) {
            await waitFor(() => expect(app.router.state.navigation.state).toBe("idle"))
            await app.router.navigate(`${base}/settings`, { state })
            await screen.findByRole("textbox", { name: /Campaign name/ })
            expect(trail()).toEqual(["Campaign Home", "Campaign settings"])
            expect(trailLinks()).toEqual([`${base}/home`])
        }
    })

    it("a reader without access.manage gets the unavailable notice, the same trail and no settings request", async () => {
        openApp(`${base}/settings`, ["campaign.view"])
        expect(await screen.findByRole("alert")).toHaveTextContent("do not have permission")
        expect(trail()).toEqual(["Campaign Home", "Campaign settings"])
        expect(gets().some((path) => path.endsWith("/settings"))).toBe(false)
        expect(nonGets()).toEqual([])
    })

    it("adds no read for the breadcrumb: one settings read, nothing else beyond the shell's", async () => {
        openApp(`${base}/settings`)
        await screen.findByRole("textbox", { name: /Campaign name/ })
        expect(gets().filter((path) => path === `${API}/settings`)).toHaveLength(1)
        expect(gets().filter((path) => /access|invitations|audit|authoring|lifecycle/.test(path))).toEqual([])
        expect(nonGets()).toEqual([])
    })

    it("a read failure keeps the trail and offers a retry that only reads", async () => {
        settingsGate = () => ({ status: 500, body: { error: { code: "server_error", message: "m", correlation_id: "c" } } })
        openApp(`${base}/settings`)
        const notice = (await screen.findByText(/campaign settings could not be loaded/)).parentElement!
        const retry = within(notice).getByRole("button", { name: "Try again" })
        expect(trail()).toEqual(["Campaign Home", "Campaign settings"])
        settingsGate = () => ({ body: settingsBody() })
        fireEvent.click(retry)
        await screen.findByRole("textbox", { name: /Campaign name/ })
        expect(nonGets()).toEqual([])
    })

    it("a dirty form asks on the Campaign Home crumb: Stay keeps the draft and the entry, Leave goes once with no write", async () => {
        const app = openApp(`${base}/settings`)
        const name = await screen.findByRole("textbox", { name: /Campaign name/ })
        fireEvent.change(name, { target: { value: "Renamed" } })
        const key = app.router.state.location.key
        fireEvent.click(breadcrumb().getByRole("link", { name: "Campaign Home" }))
        fireEvent.click(await screen.findByRole("button", { name: "Keep editing" }))
        expect(app.router.state.location.pathname).toBe(`${base}/settings`)
        expect(app.router.state.location.key).toBe(key)
        expect(screen.getByRole("textbox", { name: /Campaign name/ })).toHaveValue("Renamed")
        fireEvent.click(breadcrumb().getByRole("link", { name: "Campaign Home" }))
        fireEvent.click(await screen.findByRole("button", { name: "Discard changes" }))
        await waitFor(() => expect(app.router.state.location.pathname).toBe(`${base}/home`))
        expect(entryState(app)?.task).toMatchObject({ root: "campaign" })
        expect(nonGets()).toEqual([])
    })
})

describe("Access: Invitations and Audit history", () => {
    it.each([
        ["invitations", "Invitations"],
        ["audit", "Access audit"],
    ])("%s shows Access then the page, after a direct entry too, and the Access link starts no other task", async (segment, label) => {
        const app = openApp(`${base}/access/${segment}`)
        await screen.findByRole("navigation", { name: "Breadcrumb" })
        expect(trail()).toEqual(["Access", label])
        expect(trailLinks()).toEqual([`${base}/access`])
        expect(screen.getByRole("navigation", { name: "Access" })).toBeInTheDocument()
        fireEvent.click(breadcrumb().getByRole("link", { name: "Access" }))
        await waitFor(() => expect(app.router.state.location.pathname).toBe(`${base}/access`))
        expect(entryState(app)?.task).toMatchObject({ root: "access" })
        expect(JSON.stringify(entryState(app))).not.toContain("Mundivita")
        await app.router.navigate(-1)
        await waitFor(() => expect(app.router.state.location.pathname).toBe(`${base}/access/${segment}`))
    })

    it("an unsupported or foreign task (another root, another campaign, a crafted return) is ignored for the default trail", async () => {
        const app = openApp(`${base}/home`)
        const crafted: unknown[] = [
            { task: { v: 1, root: "characters", scope: { campaignId: "mundivita" }, trail: [] } },
            { task: { v: 1, root: "access", scope: { campaignId: "other" }, trail: [] } },
            { returnTo: { pathname: "/app/other/characters/c1", search: "" } },
            { worldSearch: "?category=location" },
        ]
        for (const state of crafted) {
            await waitFor(() => expect(app.router.state.navigation.state).toBe("idle"))
            await app.router.navigate(`${base}/access/invitations`, { state })
            await screen.findByRole("navigation", { name: "Breadcrumb" })
            expect(trail()).toEqual(["Access", "Invitations"])
            expect(trailLinks()).toEqual([`${base}/access`])
        }
    })

    it("the tab links stay on the Access task with their own reads: Invitations reads invitations only, Audit reads audit history only", async () => {
        const app = openApp(`${base}/access/invitations`)
        await screen.findByRole("navigation", { name: "Breadcrumb" })
        await waitFor(() => expect(gets().some((path) => path.endsWith("/invitations"))).toBe(true))
        expect(gets().some((path) => /access-overview|audit-history/.test(path))).toBe(false)
        fireEvent.click(within(screen.getByRole("navigation", { name: "Access" })).getByRole("link", { name: "Audit history" }))
        await waitFor(() => expect(app.router.state.location.pathname).toBe(`${base}/access/audit`))
        await waitFor(() => expect(trail()).toEqual(["Access", "Access audit"]))
        expect(gets().some((path) => path.includes("access-overview"))).toBe(false)
        expect(nonGets()).toEqual([])
    })

    it("a refused read keeps the trail and the page's own unavailable state, with no other Access read or command", async () => {
        server.on("GET", `${API}/invitations`, {
            status: 403,
            body: { error: { code: "forbidden", message: "m", correlation_id: "c" } },
        })
        openApp(`${base}/access/invitations`, ["campaign.view"])
        await screen.findByRole("navigation", { name: "Breadcrumb" })
        await waitFor(() => expect(gets().some((path) => path.endsWith("/invitations"))).toBe(true))
        expect(trail()).toEqual(["Access", "Invitations"])
        expect(gets().some((path) => /audit-history|access-overview/.test(path))).toBe(false)
        expect(nonGets()).toEqual([])
    })
})

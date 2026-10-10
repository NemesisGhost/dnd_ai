import { fireEvent, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { WorldsPage } from "./WorldsPage"

const world = (id: string, name: string, extra: object = {}) => ({
    world_id: id,
    name,
    description: null,
    lifecycle_status: "active",
    row_version: 1,
    primary_timeline_id: null,
    capabilities: ["world.manage"],
    ...extra,
})

const campaign = (id: string, name: string, worldId: string, worldName: string) => ({
    ...sessionBootstrapFixture.campaigns[0],
    campaign_id: id,
    campaign_name: name,
    world_id: worldId,
    world_name: worldName,
    roles: ["player"],
    capabilities: ["campaign.view"],
})

// No campaigns unless a test adds them, so only GET /worlds contributes.
function render(bootstrap = bootstrapWith({ campaigns: [] })) {
    return renderAuthoringRoutes({
        initialEntry: "/worlds",
        routes: [{ path: "/worlds", element: <WorldsPage /> }],
        bootstrap,
    })
}

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("WorldsPage", () => {
    it("shows a loading state, then the worlds the server returned", async () => {
        const server = installMockServer()
        server.on("GET", /^\/worlds\?status=active/, {
            body: { items: [world("w1", "Eberron"), world("w2", "Faerûn")], next_cursor: null },
        })
        render()

        expect(screen.getByRole("status")).toHaveTextContent("Loading worlds")
        expect(await screen.findByRole("link", { name: "Eberron" })).toHaveAttribute("href", "/worlds/w1")
        expect(screen.getByRole("link", { name: "Faerûn" })).toBeInTheDocument()
        // No raw identifiers are displayed.
        expect(document.body.textContent).not.toContain("w1")
    })

    it("links each world by its own server-computed access and omits one without access", async () => {
        const server = installMockServer()
        server.on("GET", /^\/worlds\?status=active/, {
            body: {
                items: [
                    world("w1", "Editable", { capabilities: ["world.view", "world.manage"] }),
                    world("w2", "Viewable", { capabilities: ["world.view"] }),
                    world("w3", "Opaque", { capabilities: [] }),
                ],
                next_cursor: null,
            },
        })
        render(bootstrapWith({ global_capabilities: [], campaigns: [] }))

        // Editable: the authoring overview, with no "View only" marker.
        const editable = await screen.findByRole("link", { name: "Editable" })
        expect(editable).toHaveAttribute("href", "/worlds/w1")
        const editableItem = editable.closest("li")!
        expect(editableItem).not.toHaveTextContent("View only")

        // View-only: the read-only overview, marked as such.
        const viewable = screen.getByRole("link", { name: "Viewable" })
        expect(viewable).toHaveAttribute("href", "/worlds/w2")
        expect(viewable.closest("li")).toHaveTextContent("View only")

        // No world access and no campaign route: nowhere to go, so not listed.
        expect(screen.queryByText("Opaque")).not.toBeInTheDocument()

        // Only links for worlds the server returned, and no creation action.
        const hrefs = screen.getAllByRole("link").map((link) => link.getAttribute("href"))
        expect(hrefs).toEqual(["/worlds/w1", "/worlds/w2"])
    })

    it("focuses the page heading once loaded", async () => {
        installMockServer().on("GET", /^\/worlds/, { body: { items: [], next_cursor: null } })
        render()
        const heading = await screen.findByRole("heading", { level: 1, name: "Worlds" })
        await waitFor(() => expect(heading).toHaveFocus())
    })

    it("explains an empty list and offers creation only when the server granted world.create", async () => {
        installMockServer().on("GET", /^\/worlds/, { body: { items: [], next_cursor: null } })
        render()
        expect(await screen.findByText(/You do not have access to any worlds yet/)).toBeInTheDocument()
        expect(screen.getByRole("link", { name: "Create world" })).toHaveAttribute("href", "/worlds/new")
    })

    it("does not show Create world without the server-computed capability", async () => {
        installMockServer().on("GET", /^\/worlds/, { body: { items: [], next_cursor: null } })
        render(bootstrapWith({ global_capabilities: [], campaigns: [] }))
        await screen.findByText(/You do not have access to any worlds yet/)
        expect(screen.queryByRole("link", { name: "Create world" })).not.toBeInTheDocument()
    })

    it("switches to archived worlds and badges them with text", async () => {
        const server = installMockServer()
        server.on("GET", /^\/worlds\?status=active/, { body: { items: [], next_cursor: null } })
        server.on("GET", /^\/worlds\?status=archived/, {
            body: { items: [world("w9", "Old World", { lifecycle_status: "archived" })], next_cursor: null },
        })
        render()
        await screen.findByText(/You do not have access to any worlds yet/)
        fireEvent.click(screen.getByRole("radio", { name: "Archived" }))
        expect(await screen.findByRole("link", { name: "Old World" })).toBeInTheDocument()
        expect(screen.getByText("Archived", { selector: "span.authoring-badge" })).toBeInTheDocument()
    })

    it("lists a campaign-visible world read-only, opening the campaign's World Explorer", async () => {
        installMockServer().on("GET", /^\/worlds\?status=active/, {
            body: { items: [], next_cursor: null },
        })
        render(
            bootstrapWith({
                global_capabilities: [],
                campaigns: [campaign("camp-a", "Campaign A", "w-hosted", "Hosted World")],
            }),
        )

        const link = await screen.findByRole("link", { name: "Hosted World" })
        expect(link).toHaveAttribute("href", "/app/camp-a/world")
        const item = link.closest("li")!
        expect(item).toHaveTextContent("View only")
        expect(item).toHaveTextContent("Through campaign Campaign A")
        // campaign.view never yields a /worlds route, an edit, or creation.
        const hrefs = screen.getAllByRole("link").map((l) => l.getAttribute("href"))
        expect(hrefs).toEqual(["/app/camp-a/world"])
        expect(screen.queryByRole("link", { name: "Create world" })).not.toBeInTheDocument()
    })

    it("deduplicates by world: explicit authority wins, and one campaign is chosen deterministically", async () => {
        installMockServer().on("GET", /^\/worlds\?status=active/, {
            body: {
                items: [
                    world("w-owned", "Owned World", {
                        capabilities: ["world.view", "world.manage"],
                    }),
                ],
                next_cursor: null,
            },
        })
        render(
            bootstrapWith({
                campaigns: [
                    // Bootstrap order is (name, id); the first on a world is used.
                    campaign("camp-a", "Alpha", "w-shared", "Shared World"),
                    campaign("camp-b", "Beta", "w-shared", "Shared World"),
                    campaign("camp-c", "Gamma", "w-owned", "Owned World"),
                ],
            }),
        )

        const owned = await screen.findByRole("link", { name: "Owned World" })
        expect(owned).toHaveAttribute("href", "/worlds/w-owned")
        expect(owned.closest("li")).not.toHaveTextContent("View only")
        expect(screen.getAllByRole("link", { name: "Shared World" })).toHaveLength(1)
        expect(screen.getByRole("link", { name: "Shared World" })).toHaveAttribute(
            "href",
            "/app/camp-a/world",
        )
        expect(screen.getAllByRole("listitem").map((li) => li.querySelector("a")?.textContent)).toEqual([
            "Owned World",
            "Shared World",
        ])
    })

    it("does not list campaign-visible worlds under Archived", async () => {
        const server = installMockServer()
        server.on("GET", /^\/worlds\?status=active/, { body: { items: [], next_cursor: null } })
        server.on("GET", /^\/worlds\?status=archived/, { body: { items: [], next_cursor: null } })
        render(
            bootstrapWith({
                campaigns: [campaign("camp-a", "Campaign A", "w-hosted", "Hosted World")],
            }),
        )
        await screen.findByRole("link", { name: "Hosted World" })
        fireEvent.click(screen.getByRole("radio", { name: "Archived" }))
        expect(await screen.findByText(/You have no archived worlds/)).toBeInTheDocument()
        expect(screen.queryByRole("link", { name: "Hosted World" })).not.toBeInTheDocument()
    })

    it("shows an unavailable state for a denied or failed list", async () => {
        installMockServer().on("GET", /^\/worlds/, { status: 403 })
        render()
        expect(await screen.findByRole("alert")).toHaveTextContent("not available to you")
    })

    it("shows a recoverable error for a server failure", async () => {
        installMockServer().on("GET", /^\/worlds/, { status: 500 })
        render()
        expect(await screen.findByRole("alert")).toHaveTextContent("could not be loaded")
    })

    it("reloads the session when the server says it expired", async () => {
        installMockServer().on("GET", /^\/worlds/, { status: 401 })
        const { reload } = render()
        await waitFor(() => expect(reload).toHaveBeenCalled())
    })
})

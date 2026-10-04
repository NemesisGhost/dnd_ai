import { fireEvent, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
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

function render(bootstrap = bootstrapWith()) {
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

    it("focuses the page heading once loaded", async () => {
        installMockServer().on("GET", /^\/worlds/, { body: { items: [], next_cursor: null } })
        render()
        const heading = await screen.findByRole("heading", { level: 1, name: "Worlds" })
        await waitFor(() => expect(heading).toHaveFocus())
    })

    it("explains an empty list and offers creation only when the server granted world.create", async () => {
        installMockServer().on("GET", /^\/worlds/, { body: { items: [], next_cursor: null } })
        render()
        expect(await screen.findByText(/You do not own any worlds yet/)).toBeInTheDocument()
        expect(screen.getByRole("link", { name: "Create world" })).toHaveAttribute("href", "/worlds/new")
    })

    it("does not show Create world without the server-computed capability", async () => {
        installMockServer().on("GET", /^\/worlds/, { body: { items: [], next_cursor: null } })
        render(bootstrapWith({ global_capabilities: [] }))
        await screen.findByText(/You do not own any worlds yet/)
        expect(screen.queryByRole("link", { name: "Create world" })).not.toBeInTheDocument()
    })

    it("switches to archived worlds and badges them with text", async () => {
        const server = installMockServer()
        server.on("GET", /^\/worlds\?status=active/, { body: { items: [], next_cursor: null } })
        server.on("GET", /^\/worlds\?status=archived/, {
            body: { items: [world("w9", "Old World", { lifecycle_status: "archived" })], next_cursor: null },
        })
        render()
        await screen.findByText(/You do not own any worlds yet/)
        fireEvent.click(screen.getByRole("radio", { name: "Archived" }))
        expect(await screen.findByRole("link", { name: "Old World" })).toBeInTheDocument()
        expect(screen.getByText("Archived", { selector: "span.authoring-badge" })).toBeInTheDocument()
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

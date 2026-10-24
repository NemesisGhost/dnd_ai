import { screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import { WorldCanonPage } from "./WorldCanonPage"

const world = {
    world_id: "w1",
    name: "Eberron",
    description: null,
    lifecycle_status: "active",
    row_version: 1,
    primary_timeline_id: null,
    capabilities: ["world.view", "world.canon.read"],
    default_ruleset_id: null,
    allowed_rulesets: [],
    timelines: [],
    managed_campaigns: [],
    available_actions: [],
    blocked_actions: [],
}

function render(canon: { status?: number; body: unknown }) {
    const server = installMockServer()
    server.on("GET", "/worlds/w1", { body: world })
    server.on("GET", /^\/worlds\/w1\/canon/, canon)
    renderAuthoringRoutes({
        initialEntry: "/worlds/w1/canon",
        routes: [{ path: "/worlds/:worldId/canon", element: <WorldCanonPage /> }],
    })
    return server
}

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("WorldCanonPage", () => {
    it("lists the published canon cards the server returns", async () => {
        render({
            body: {
                items: [
                    { entity_id: "e1", category: "location", name: "Sharn", summary: "City of Towers" },
                    { entity_id: "e2", category: "religion", name: "Sovereign Host", summary: null },
                ],
                next_cursor: null,
            },
        })
        expect(await screen.findByText("Sharn")).toBeInTheDocument()
        expect(screen.getByText("City of Towers")).toBeInTheDocument()
        expect(screen.getByText("Sovereign Host")).toBeInTheDocument()
        expect(screen.getByText("Location")).toBeInTheDocument()
    })

    it("says so when nothing is published", async () => {
        render({ body: { items: [], next_cursor: null } })
        expect(await screen.findByText("No published canon matches.")).toBeInTheDocument()
    })

    it("shows a denial, never a list, when the server refuses", async () => {
        render({ status: 404, body: { error: { code: "not_found" } } })
        expect(await screen.findByText("You do not have access to this world's canon.")).toBeInTheDocument()
        expect(screen.queryByRole("textbox")).not.toBeInTheDocument()
    })
})

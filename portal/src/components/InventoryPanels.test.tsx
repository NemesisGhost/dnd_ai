import { fireEvent, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import { CharacterInventoryPanel, PartyInventoryPanel } from "./InventoryPanels"

afterEach(() => {
    vi.unstubAllGlobals()
})

const ROW = {
    item_instance_id: "i1",
    name: "Moonblade",
    display_name: "Longsword",
    item_category_code: "weapon",
    rarity: "rare",
    quantity: 3,
    condition_percentage: 60,
    is_equipped: true,
    is_destroyed: false,
}

function render(element: React.ReactElement, server = installMockServer()) {
    renderAuthoringRoutes({
        initialEntry: "/app/c1/x",
        bootstrap: bootstrapWith({
            campaigns: [{ ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c1" }],
        }),
        routes: [{ path: "/app/:campaignId/x", element }],
    })
    return server
}

describe("CharacterInventoryPanel", () => {
    it("lists what a character carries with links to the items", async () => {
        const server = installMockServer()
        server.on("GET", "/campaigns/c1/characters/n1/inventory", { body: [ROW] })
        render(<CharacterInventoryPanel campaignId="c1" characterId="n1" />, server)
        expect(await screen.findByRole("link", { name: "Moonblade" })).toHaveAttribute(
            "href",
            "/app/c1/world/item/i1",
        )
        expect(screen.getByText(/\(Longsword\), ×3, 60% condition, equipped/)).toBeInTheDocument()
    })

    it("says nothing is carried, and shows nothing when the read is refused", async () => {
        const server = installMockServer()
        server.on("GET", "/campaigns/c1/characters/n1/inventory", { body: [] })
        render(<CharacterInventoryPanel campaignId="c1" characterId="n1" />, server)
        expect(await screen.findByText("Nothing carried.")).toBeInTheDocument()
    })

    it("renders nothing for a refused read", async () => {
        const server = installMockServer()
        server.on("GET", "/campaigns/c1/characters/n2/inventory", { status: 403, body: { error: { code: "forbidden", message: "m", correlation_id: "c" } } })
        render(<CharacterInventoryPanel campaignId="c1" characterId="n2" />, server)
        await new Promise((resolve) => setTimeout(resolve, 50))
        expect(screen.queryByRole("heading", { name: "Inventory" })).not.toBeInTheDocument()
    })
})

describe("PartyInventoryPanel", () => {
    it("lists each current member's items", async () => {
        const server = installMockServer()
        server.on("GET", "/campaigns/c1/parties/p1/inventory", {
            body: {
                party_id: "p1",
                members: [
                    { character_id: "n1", character_name: "Aldric", items: [{ ...ROW, is_published: true, last_event_id: "e1" }] },
                    { character_id: "n2", character_name: "Bryn", items: [] },
                ],
            },
        })
        render(<PartyInventoryPanel campaignId="c1" partyId="p1" />, server)
        expect(await screen.findByRole("heading", { name: "Aldric" })).toBeInTheDocument()
        expect(screen.getByRole("link", { name: "Moonblade" })).toBeInTheDocument()
        expect(screen.getByRole("heading", { name: "Bryn" })).toBeInTheDocument()
        expect(screen.getByText("Nothing carried.")).toBeInTheDocument()
    })
})

describe("inventory read states", () => {
    const PATH = "/campaigns/c1/characters/n1/inventory"
    const refused = (status: number) => ({
        status,
        body: { error: { code: "forbidden", message: "m", correlation_id: "c" } },
    })

    it.each([
        [403, /You do not have access to the inventory/],
        [404, /The inventory is not available, or you can no longer access it/],
    ])("says plainly in a staged section that a %i read was refused, with no retry", async (status, text) => {
        const server = installMockServer()
        server.on("GET", PATH, refused(status))
        render(<CharacterInventoryPanel embedded campaignId="c1" characterId="n1" />, server)
        expect(await screen.findByRole("alert")).toHaveTextContent(text)
        expect(screen.queryByRole("button", { name: "Try again" })).toBeNull()
        expect(screen.queryByText("Nothing carried.")).toBeNull()
    })

    it("tells a failed read from an empty inventory, and retries by reading again", async () => {
        const server = installMockServer()
        let fail = true
        server.on("GET", PATH, () => (fail ? { status: 500, body: {} } : { body: [] }))
        render(<CharacterInventoryPanel campaignId="c1" characterId="n1" />, server)
        expect(await screen.findByRole("alert")).toHaveTextContent("The inventory could not be loaded.")
        expect(screen.queryByText("Nothing carried.")).toBeNull()
        fail = false
        fireEvent.click(screen.getByRole("button", { name: "Try again" }))
        expect(await screen.findByText("Nothing carried.")).toBeInTheDocument()
        expect(screen.queryByRole("alert")).toBeNull()
        expect(server.callsTo("GET", PATH)).toHaveLength(2)
    })

    it("shows a failed party inventory with a retry", async () => {
        const failing = installMockServer()
        failing.on("GET", "/campaigns/c1/parties/p1/inventory", { status: 500, body: {} })
        render(<PartyInventoryPanel campaignId="c1" partyId="p1" />, failing)
        expect(await screen.findByRole("alert")).toHaveTextContent("The party inventory could not be loaded.")
        expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument()
    })

    it("shows nothing for a party inventory the caller may not read", async () => {
        const refusedServer = installMockServer()
        refusedServer.on("GET", "/campaigns/c1/parties/p2/inventory", refused(403))
        render(<PartyInventoryPanel campaignId="c1" partyId="p2" />, refusedServer)
        await waitFor(() => expect(refusedServer.callsTo("GET", "/campaigns/c1/parties/p2/inventory")).toHaveLength(1))
        await new Promise((resolve) => setTimeout(resolve, 30))
        expect(screen.queryByRole("alert")).toBeNull()
        expect(screen.queryByRole("heading", { name: "Party inventory" })).toBeNull()
    })
})

import { screen } from "@testing-library/react"
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

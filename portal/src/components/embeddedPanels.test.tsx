import { screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import { CharacterInventoryPanel } from "./InventoryPanels"
import { OrganizationMembers } from "./OrganizationMembers"
import { RelationshipsPanel } from "./RelationshipsPanel"

// A staged section supplies the surface and the heading, so the panels it hosts render their
// content only (`embedded`) and, where a missing body would read as an empty record, say why.

const MEMBERS = "/campaigns/c1/organizations/o1/members"
const INVENTORY = "/campaigns/c1/characters/n1/inventory"

function render(element: React.ReactNode, mock: (server: ReturnType<typeof installMockServer>) => void) {
    const server = installMockServer()
    mock(server)
    renderAuthoringRoutes({
        initialEntry: "/app/c1/x",
        bootstrap: bootstrapWith({
            campaigns: [{ ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c1", capabilities: ["canon.edit"] }],
        }),
        routes: [{ path: "/app/:campaignId/x", element }],
    })
    return server
}

afterEach(() => vi.unstubAllGlobals())

describe("embedded panels", () => {
    const roster = { organization_id: "o1", status: null, can_edit: false, status_choices: [], members: [] }

    it("keeps the panel and its heading by default", async () => {
        render(<OrganizationMembers campaignId="c1" organizationId="o1" />, (s) => s.on("GET", MEMBERS, { body: roster }))
        expect(await screen.findByRole("heading", { level: 2, name: "Members and offices" })).toBeInTheDocument()
    })

    it("renders only the content when embedded", async () => {
        render(<OrganizationMembers embedded campaignId="c1" organizationId="o1" />, (s) => s.on("GET", MEMBERS, { body: roster }))
        expect(await screen.findByText("No members are known.")).toBeInTheDocument()
        expect(screen.queryByRole("heading", { name: "Members and offices" })).not.toBeInTheDocument()
    })

    it("says so when the roster cannot be read, instead of looking empty", async () => {
        render(<OrganizationMembers embedded campaignId="c1" organizationId="o1" />, (s) =>
            s.on("GET", MEMBERS, { status: 500, body: {} }),
        )
        expect(await screen.findByRole("alert")).toHaveTextContent("Members could not be loaded.")
    })

    it("renders nothing at all when it is not embedded and the read fails", async () => {
        render(<OrganizationMembers campaignId="c1" organizationId="o1" />, (s) => s.on("GET", MEMBERS, { status: 500, body: {} }))
        await new Promise((resolve) => setTimeout(resolve, 30))
        expect(screen.queryByRole("alert")).not.toBeInTheDocument()
    })

    it("renders the inventory without a panel when embedded, and says when it cannot be read", async () => {
        const ok = render(<CharacterInventoryPanel embedded campaignId="c1" characterId="n1" />, (s) =>
            s.on("GET", INVENTORY, { body: [] }),
        )
        expect(await screen.findByText("Nothing carried.")).toBeInTheDocument()
        expect(screen.queryByRole("heading", { name: "Inventory" })).not.toBeInTheDocument()
        expect(ok.calls).toHaveLength(1)
    })

    it("says the inventory could not be loaded when embedded", async () => {
        render(<CharacterInventoryPanel embedded campaignId="c1" characterId="n1" />, (s) =>
            s.on("GET", INVENTORY, { status: 500, body: {} }),
        )
        expect(await screen.findByRole("alert")).toHaveTextContent("The inventory could not be loaded.")
    })

    it("says the relationships could not be loaded when embedded", async () => {
        render(<RelationshipsPanel embedded campaignId="c1" entityId="e1" />, (s) => s.on("GET", /.*/, { status: 500, body: {} }))
        expect(await screen.findByRole("alert")).toHaveTextContent("Relationships could not be loaded.")
        expect(screen.queryByRole("heading", { name: "Relationships" })).not.toBeInTheDocument()
    })
})

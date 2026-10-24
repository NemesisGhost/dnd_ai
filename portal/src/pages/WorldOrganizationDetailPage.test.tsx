import { screen, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import type { MockServer } from "../test/authoringHarness"
import type { OrganizationDetail } from "../types/world"
import { WorldOrganizationDetailPage } from "./WorldOrganizationDetailPage"

afterEach(() => {
    vi.unstubAllGlobals()
})

const organization: OrganizationDetail = {
    organization_id: "3f2b8c1e-5d4a-4e7b-9c1d-2a6f8b0e4d11",
    name: "The Cartographers' Guild",
    summary: "Mapmakers of the realm.",
    kind_code: "business",
    organization_type_code: "business",
    public_description: "Sells maps and charts.",
    parent: { entity_id: "p-1", name: "The Crown" },
    headquarters: { entity_id: "h-1", name: "Mapmakers' Hall" },
    religion: null,
    status_code: "active",
}

const MEMBERS = (id: string) => `/campaigns/campaign-a/organizations/${id}/members`

const emptyRoster = (id: string) => ({
    organization_id: id,
    status: null,
    can_edit: false,
    as_of: null,
    status_choices: [],
    members: [],
})

// The page as a player sees it: the members section reads its own route, answered empty here.
function renderPage(value: OrganizationDetail, server: MockServer = installMockServer()) {
    server.on("GET", MEMBERS(value.organization_id), { body: emptyRoster(value.organization_id) })
    const bootstrap = bootstrapWith({
        campaigns: [
            { ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "campaign-a", capabilities: ["campaign.view"] },
        ],
    })
    const view = renderAuthoringRoutes({
        initialEntry: "/app/campaign-a/world/organization/x",
        bootstrap,
        routes: [
            {
                path: "/app/:campaignId/world/organization/:entityId",
                element: <WorldOrganizationDetailPage campaignId="campaign-a" organization={value} />,
            },
        ],
    })
    return { server, ...view }
}

const settled = () => screen.findByText("No members are known.")
const requested = (server: MockServer) => server.calls.map((c) => `${c.method} ${c.path}`)

describe("WorldOrganizationDetailPage", () => {
    it("has one h1 and a back link", async () => {
        renderPage(organization)
        await settled()
        expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1)
        expect(screen.getByRole("heading", { level: 1, name: "The Cartographers' Guild" })).toBeInTheDocument()
        expect(screen.getByRole("link", { name: "Back to World" })).toHaveAttribute(
            "href",
            "/app/campaign-a/world",
        )
    })

    it("shows related records by name and links them to their own details", async () => {
        renderPage({
            ...organization,
            religion: { entity_id: "r-1", name: "The Old Way" },
        })
        await settled()
        expect(screen.getByRole("link", { name: "The Crown" })).toHaveAttribute(
            "href",
            "/app/campaign-a/world/organization/p-1",
        )
        expect(screen.getByRole("link", { name: "Mapmakers' Hall" })).toHaveAttribute(
            "href",
            "/app/campaign-a/world/location/h-1",
        )
        expect(screen.getByRole("link", { name: "The Old Way" })).toHaveAttribute(
            "href",
            "/app/campaign-a/world/religion/r-1",
        )
    })

    it("never renders a raw identifier", async () => {
        renderPage(organization)
        await settled()
        expect(document.body.textContent).not.toContain(organization.organization_id)
        expect(document.body.textContent).not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}-/i)
    })

    it("omits the structure links the server did not name", async () => {
        renderPage({ ...organization, parent: null, headquarters: null })
        await settled()
        expect(screen.getByText("No related records to show.")).toBeInTheDocument()
        expect(screen.queryByRole("link", { name: "The Crown" })).toBeNull()
    })

    it("shows an editor-less visitor no edit link and sends no authoring request", async () => {
        const { server } = renderPage(organization)
        await settled()
        expect(screen.queryByRole("link", { name: /Edit organization/ })).toBeNull()
        expect(requested(server)).toEqual([`GET ${MEMBERS(organization.organization_id)}`])
    })

    it("states an unrecorded status plainly", async () => {
        renderPage({ ...organization, status_code: null, public_description: null })
        await settled()
        expect(screen.getByText("Not recorded")).toBeInTheDocument()
        expect(screen.getByText("No public description recorded.")).toBeInTheDocument()
    })

    it("shows the founding, dissolution and form of government the server returned", async () => {
        renderPage({
            ...organization,
            kind_code: "government",
            organization_type_code: "government",
            government_form: "Elected senate",
            founded: "Year 1480",
            dissolved: "Year 1490",
        })
        await settled()
        const overview = screen.getByRole("region", { name: "Overview" })
        for (const [label, value] of [
            ["Type", "Government"],
            ["Form of government", "Elected senate"],
            ["Founded", "Year 1480"],
            ["Dissolved", "Year 1490"],
        ] as const) {
            expect(within(overview).getByText(label)).toBeInTheDocument()
            expect(within(overview).getByText(value)).toBeInTheDocument()
        }
        expect(screen.queryByRole("region", { name: "Ideology" })).toBeNull()
    })

    it("leaves out facts the server did not return", async () => {
        renderPage({ ...organization, founded: null, dissolved: null, government_form: null, ideology: null })
        await settled()
        for (const label of ["Form of government", "Founded", "Dissolved"]) {
            expect(screen.queryByText(label)).toBeNull()
        }
        expect(screen.queryByRole("region", { name: "Ideology" })).toBeNull()
    })

    it("shows a political faction's ideology in its own panel", async () => {
        renderPage({ ...organization, kind_code: "political_faction", ideology: "Land for all" })
        await settled()
        const ideology = screen.getByRole("region", { name: "Ideology" })
        expect(within(ideology).getByText("Land for all")).toBeInTheDocument()
    })

    it("puts Members and offices inside the page's section as a second-level heading", async () => {
        renderPage(organization)
        await settled()
        const page = screen.getByRole("region", { name: organization.name })
        expect(within(page).getByRole("heading", { level: 2, name: "Members and offices" })).toBeInTheDocument()
        expect(screen.getAllByRole("heading", { name: "Members and offices" })).toHaveLength(1)
        expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1)
    })

    it("reads the same roster route whatever the organization's type or name says", async () => {
        const seen: string[][] = []
        for (const value of [
            organization,
            { ...organization, name: "Public Council", kind_code: "government", organization_type_code: "government" },
        ]) {
            const { server, unmount } = renderPage(value)
            await settled()
            seen.push(requested(server))
            unmount()
            vi.unstubAllGlobals()
        }
        expect(seen[0]).toEqual(seen[1])
    })
})

import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { describe, expect, it } from "vitest"
import type { OrganizationDetail } from "../types/world"
import { WorldOrganizationDetailPage } from "./WorldOrganizationDetailPage"

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

function renderPage(value: OrganizationDetail) {
    return render(
        <MemoryRouter>
            <WorldOrganizationDetailPage campaignId="campaign-a" organization={value} />
        </MemoryRouter>,
    )
}

describe("WorldOrganizationDetailPage", () => {
    it("has one h1 and a back link", () => {
        renderPage(organization)
        expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1)
        expect(screen.getByRole("heading", { level: 1, name: "The Cartographers' Guild" })).toBeInTheDocument()
        expect(screen.getByRole("link", { name: "Back to World" })).toHaveAttribute(
            "href",
            "/app/campaign-a/world",
        )
    })

    it("shows related records by name and links them to their own details", () => {
        renderPage({
            ...organization,
            religion: { entity_id: "r-1", name: "The Old Way" },
        })
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

    it("never renders a raw identifier", () => {
        renderPage(organization)
        expect(document.body.textContent).not.toContain(organization.organization_id)
        expect(document.body.textContent).not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}-/i)
    })

    it("omits the structure links the server did not name", () => {
        renderPage({ ...organization, parent: null, headquarters: null })
        expect(screen.getByText("No related records to show.")).toBeInTheDocument()
        expect(screen.queryByRole("link", { name: "The Crown" })).toBeNull()
    })

    it("shows an editor-less visitor no edit link and sends no authoring request", () => {
        renderPage(organization)
        expect(screen.queryByRole("link", { name: /Edit organization/ })).toBeNull()
    })

    it("states an unrecorded status plainly", () => {
        renderPage({ ...organization, status_code: null, public_description: null })
        expect(screen.getByText("Not recorded")).toBeInTheDocument()
        expect(screen.getByText("No public description recorded.")).toBeInTheDocument()
    })
})

import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { describe, expect, it } from "vitest"
import type { ReligionDetail } from "../types/world"
import { WorldReligionDetailPage } from "./WorldReligionDetailPage"

const religionFixture: ReligionDetail = {
    religion_id: "religion-a",
    name: "The Tidefather Communion",
    summary: "Worship of the sea's reclaiming tide.",
    pantheon_structure: "Single deity with lay orders.",
    serving_organization_ids: ["org-a", "org-b"],
}

function renderPage(religion: ReligionDetail) {
    return render(
        <MemoryRouter>
            <WorldReligionDetailPage campaignId="campaign-a" religion={religion} />
        </MemoryRouter>,
    )
}

describe("WorldReligionDetailPage", () => {
    it("renders one page heading, back link, and authorized fields", () => {
        renderPage(religionFixture)

        expect(
            screen.getByRole("heading", { level: 1, name: "The Tidefather Communion" }),
        ).toBeInTheDocument()

        expect(
            screen.getByRole("link", { name: "Back to World" }),
        ).toHaveAttribute("href", "/app/campaign-a/world")

        expect(
            screen.getByText("Worship of the sea's reclaiming tide."),
        ).toBeInTheDocument()
        expect(
            screen.getByText("Single deity with lay orders."),
        ).toBeInTheDocument()
    })

    it("never displays raw serving-organization UUIDs", () => {
        renderPage(religionFixture)

        expect(screen.queryByText("org-a")).not.toBeInTheDocument()
        expect(screen.queryByText("org-b")).not.toBeInTheDocument()
    })

    it("shows a deliberate empty state when the pantheon structure is absent", () => {
        renderPage({ ...religionFixture, pantheon_structure: null })

        expect(screen.getByText("Not recorded")).toBeInTheDocument()
    })
})

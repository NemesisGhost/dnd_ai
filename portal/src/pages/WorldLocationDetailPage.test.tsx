import { render, screen, within } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { describe, expect, it } from "vitest"
import type { LocationDetail } from "../types/world"
import { WorldLocationDetailPage } from "./WorldLocationDetailPage"

const locationFixture: LocationDetail = {
    location_id: "location-a",
    name: "The Sunken Archive",
    summary: "A flooded records hall beneath Hollowmere.",
    location_type_code: "building",
    parent_location_id: "location-parent",
    breadcrumbs: [
        { location_id: "loc-1", name: "Auremar", location_type_code: "continent" },
        { location_id: "loc-2", name: "The Ashen Vale", location_type_code: "region" },
        { location_id: "loc-3", name: "Hollowmere", location_type_code: "settlement" },
    ],
    population: null,
    building_use: "archive",
    danger_level: 3,
    is_searched: true,
    is_destroyed: false,
    alarm_level: 1,
    condition_notes: "Flooded lower level.",
}

function renderPage(location: LocationDetail) {
    return render(
        <MemoryRouter>
            <WorldLocationDetailPage campaignId="campaign-a" location={location} />
        </MemoryRouter>,
    )
}

describe("WorldLocationDetailPage", () => {
    it("renders one page heading, back link, and authorized summary", () => {
        renderPage(locationFixture)

        expect(
            screen.getByRole("heading", { level: 1, name: "The Sunken Archive" }),
        ).toBeInTheDocument()

        expect(
            screen.getByRole("link", { name: "Back to World" }),
        ).toHaveAttribute("href", "/app/campaign-a/world")

        expect(
            screen.getByText("A flooded records hall beneath Hollowmere."),
        ).toBeInTheDocument()
    })

    it("shows containment via breadcrumb names, never the raw parent_location_id", () => {
        renderPage(locationFixture)

        const containmentPanel = screen
            .getByText("Containment")
            .closest("section") as HTMLElement

        expect(
            within(containmentPanel).getByText(/Auremar/),
        ).toBeInTheDocument()
        expect(
            within(containmentPanel).getByText(/Hollowmere/),
        ).toBeInTheDocument()
        expect(
            screen.queryByText("location-parent"),
        ).not.toBeInTheDocument()
    })

    it("shows current state fields", () => {
        renderPage(locationFixture)

        expect(screen.getByText("Yes")).toBeInTheDocument()
        expect(screen.getByText("Flooded lower level.")).toBeInTheDocument()
    })

    it("shows deliberate null handling for sparse records", () => {
        renderPage({
            ...locationFixture,
            summary: null,
            breadcrumbs: [],
            population: null,
            building_use: null,
            danger_level: null,
            is_searched: null,
            is_destroyed: null,
            alarm_level: null,
            condition_notes: null,
        })

        expect(screen.getByText("No containment recorded.")).toBeInTheDocument()
        expect(screen.getAllByText("Not recorded").length).toBeGreaterThan(0)
    })

    it("never renders raw location ids as visible text", () => {
        renderPage(locationFixture)

        expect(screen.queryByText("location-a")).not.toBeInTheDocument()
        expect(screen.queryByText("loc-1")).not.toBeInTheDocument()
    })
})

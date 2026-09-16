import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { EntityCard } from "./EntityCard"

function renderWithRouter(ui: React.ReactElement) {
    return render(<MemoryRouter>{ui}</MemoryRouter>)
}

describe("EntityCard", () => {
    it("renders a navigable card as a real link with a descriptive name", () => {
        renderWithRouter(
            <ul>
                <EntityCard
                    eyebrow="Location"
                    title="The Sunken Archive"
                    summary="A flooded records hall."
                    to="/app/campaign-a/world/location/entity-a"
                />
            </ul>,
        )

        const link = screen.getByRole("link", { name: "The Sunken Archive" })
        expect(link).toHaveAttribute(
            "href",
            "/app/campaign-a/world/location/entity-a",
        )
        expect(screen.getByText("Location")).toBeInTheDocument()
        expect(
            screen.getByText("A flooded records hall."),
        ).toBeInTheDocument()
    })

    it("uses an explicit link label when provided", () => {
        renderWithRouter(
            <ul>
                <EntityCard
                    title="Hollowmere"
                    to="/app/campaign-a/world/location/entity-b"
                    linkLabel="Hollowmere, Location"
                />
            </ul>,
        )

        expect(
            screen.getByRole("link", { name: "Hollowmere, Location" }),
        ).toBeInTheDocument()
    })

    it("omits the summary paragraph entirely when absent", () => {
        renderWithRouter(
            <ul>
                <EntityCard title="No Summary" to="/x" />
            </ul>,
        )

        expect(screen.queryByText(/not recorded/i)).not.toBeInTheDocument()
    })

    it("renders compact metadata facts", () => {
        renderWithRouter(
            <ul>
                <EntityCard
                    title="With Metadata"
                    to="/x"
                    metadata={["Scope: Party", "Confidence: 85%"]}
                />
            </ul>,
        )

        expect(screen.getByText("Scope: Party")).toBeInTheDocument()
        expect(screen.getByText("Confidence: 85%")).toBeInTheDocument()
    })

    it("renders as a non-interactive surface without a link when no detail route exists", () => {
        renderWithRouter(
            <ul>
                <EntityCard title="No Detail Route" />
            </ul>,
        )

        expect(screen.queryByRole("link")).not.toBeInTheDocument()
        expect(screen.getByText("No Detail Route")).toBeInTheDocument()
    })

    it("never renders a raw UUID-shaped value unless explicitly passed as content", () => {
        renderWithRouter(
            <ul>
                <EntityCard
                    title="Safe Card"
                    to="/app/campaign-a/world/location/11111111-1111-1111-1111-111111111111"
                />
            </ul>,
        )

        // The UUID may appear in the href (the route contract requires it)
        // but never as visible text content.
        expect(
            screen.queryByText(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}/i),
        ).not.toBeInTheDocument()
    })
})

import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { describe, expect, it } from "vitest"
import type { WorldEntityCard } from "../types/world"
import { WorldCard } from "./WorldCard"

function renderCard(entity: WorldEntityCard) {
    return render(
        <MemoryRouter>
            <ul>
                <WorldCard campaignId="campaign-a" entity={entity} />
            </ul>
        </MemoryRouter>,
    )
}

describe("WorldCard", () => {
    it.each([
        ["location", "location-a"],
        ["character", "character-a"],
        ["religion", "religion-a"],
        ["item", "item-a"],
        ["event", "event-a"],
    ] as const)(
        "links a supported category (%s) to its campaign-scoped detail route",
        (category, entityId) => {
            renderCard({
                entity_id: entityId,
                category,
                entity_type_code: category,
                name: "Test Entity",
                summary: null,
            })

            expect(
                screen.getByRole("link", { name: /Test Entity/ }),
            ).toHaveAttribute(
                "href",
                `/app/campaign-a/world/${category}/${entityId}`,
            )
        },
    )

    it("renders organization as a non-interactive card", () => {
        renderCard({
            entity_id: "org-a",
            category: "organization",
            entity_type_code: "business",
            name: "The Cartographers' Guild",
            summary: null,
        })

        expect(screen.queryByRole("link")).not.toBeInTheDocument()
        expect(
            screen.getByText("The Cartographers' Guild"),
        ).toBeInTheDocument()
    })

    it("humanizes the entity type and omits it when identical to the category label", () => {
        renderCard({
            entity_id: "location-a",
            category: "location",
            entity_type_code: "location",
            name: "Plain Location",
            summary: null,
        })

        expect(screen.getByText("Location")).toBeInTheDocument()
        expect(screen.queryByText("Location - Location")).not.toBeInTheDocument()
    })

    it("shows the type distinctly when it differs from the category", () => {
        renderCard({
            entity_id: "location-a",
            category: "location",
            entity_type_code: "dungeon_area",
            name: "The Lantern Antechamber",
            summary: null,
        })

        expect(screen.getByText("Location - Dungeon Area")).toBeInTheDocument()
    })

    it("omits the summary paragraph when absent", () => {
        renderCard({
            entity_id: "location-a",
            category: "location",
            entity_type_code: "location",
            name: "No Summary",
            summary: null,
        })

        expect(screen.queryByText(/not recorded/i)).not.toBeInTheDocument()
    })

    it("never renders the raw entity id as visible text", () => {
        renderCard({
            entity_id: "11111111-1111-1111-1111-111111111111",
            category: "location",
            entity_type_code: "location",
            name: "Hidden Id",
            summary: null,
        })

        expect(
            screen.queryByText(/[0-9a-f]{8}-[0-9a-f]{4}/i),
        ).not.toBeInTheDocument()
    })
})

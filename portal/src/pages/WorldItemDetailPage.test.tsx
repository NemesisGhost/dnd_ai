import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { describe, expect, it } from "vitest"
import type { ItemDetail } from "../types/world"
import { WorldItemDetailPage } from "./WorldItemDetailPage"

const itemFixture: ItemDetail = {
    item_instance_id: "item-a",
    name: "The Warden's Lantern",
    summary: "A lantern that only lights for a Warden.",
    item_definition_id: "item-def-a",
    origin_notes: "Forged by the first Warden.",
    quantity: 1,
    condition_percentage: 90,
    charges_current: 3,
    charges_maximum: 5,
    is_equipped: true,
    is_destroyed: false,
}

function renderPage(item: ItemDetail) {
    return render(
        <MemoryRouter>
            <WorldItemDetailPage campaignId="campaign-a" item={item} />
        </MemoryRouter>,
    )
}

describe("WorldItemDetailPage", () => {
    it("renders one page heading, back link, and authorized state fields", () => {
        renderPage(itemFixture)

        expect(
            screen.getByRole("heading", { level: 1, name: "The Warden's Lantern" }),
        ).toBeInTheDocument()

        expect(
            screen.getByRole("link", { name: "Back to World" }),
        ).toHaveAttribute("href", "/app/campaign-a/world")

        expect(screen.getByText("90%")).toBeInTheDocument()
        expect(screen.getByText("3 / 5")).toBeInTheDocument()
        expect(screen.getByText("Forged by the first Warden.")).toBeInTheDocument()
    })

    it("never renders the raw item-definition UUID", () => {
        renderPage(itemFixture)

        expect(screen.queryByText("item-def-a")).not.toBeInTheDocument()
    })

    it("shows deliberate null handling for a sparse item", () => {
        renderPage({
            ...itemFixture,
            summary: null,
            origin_notes: null,
            quantity: null,
            condition_percentage: null,
            charges_current: null,
            charges_maximum: null,
            is_equipped: null,
            is_destroyed: null,
        })

        expect(screen.getAllByText("Not recorded").length).toBeGreaterThan(0)
    })
})

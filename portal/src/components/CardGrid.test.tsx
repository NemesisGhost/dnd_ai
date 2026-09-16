import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import { CardGrid } from "./CardGrid"

describe("CardGrid", () => {
    it("renders a labelled semantic list", () => {
        render(
            <CardGrid ariaLabel="Test cards">
                <li>One</li>
                <li>Two</li>
            </CardGrid>,
        )

        const list = screen.getByRole("list", { name: "Test cards" })
        expect(list.tagName).toBe("UL")
        expect(list.children).toHaveLength(2)
    })

    it("applies an additional class alongside the base grid class", () => {
        render(
            <CardGrid ariaLabel="Test cards" className="world-card-grid">
                <li>One</li>
            </CardGrid>,
        )

        const list = screen.getByRole("list", { name: "Test cards" })
        expect(list.className).toBe("card-grid world-card-grid")
    })
})

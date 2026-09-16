import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { FactGrid } from "./FactGrid"

describe("FactGrid", () => {
    it("renders a semantic description list of label/value facts", () => {
        const { container } = render(
            <FactGrid
                items={[
                    { key: "species", label: "Species", value: "Dragonborn" },
                    { key: "size", label: "Size", value: "Medium" },
                ]}
            />,
        )

        const list = container.querySelector("dl")
        expect(list).not.toBeNull()

        expect(screen.getByText("Species")).toBeInTheDocument()
        expect(screen.getByText("Dragonborn")).toBeInTheDocument()
        expect(screen.getByText("Size")).toBeInTheDocument()
        expect(screen.getByText("Medium")).toBeInTheDocument()
    })

    it("renders no rows when given an empty item list", () => {
        const { container } = render(<FactGrid items={[]} />)

        expect(
            container.querySelectorAll(".fact-grid__row"),
        ).toHaveLength(0)
    })
})

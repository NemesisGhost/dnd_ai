import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { StatCard } from "./StatCard"

describe("StatCard", () => {
    it("associates the label with the prominent value", () => {
        const { container } = render(
            <StatCard label="Proficiency bonus" value="+3" />,
        )

        const figure = container.querySelector("figure.stat-card")
        expect(figure).not.toBeNull()

        const caption = screen.getByText("Proficiency bonus")
        expect(caption.tagName).toBe("FIGCAPTION")
        expect(figure).toContainElement(caption)

        expect(screen.getByText("+3")).toBeInTheDocument()
    })

    it("renders optional secondary content", () => {
        render(
            <StatCard
                label="Death saves"
                value="1 / 0"
                secondary="Successes / failures"
            />,
        )

        expect(
            screen.getByText("Successes / failures"),
        ).toBeInTheDocument()
    })

    it("omits the value and secondary elements when not provided", () => {
        const { container } = render(<StatCard label="Movement" />)

        expect(
            container.querySelector(".stat-card__value"),
        ).not.toBeInTheDocument()

        expect(
            container.querySelector(".stat-card__secondary"),
        ).not.toBeInTheDocument()
    })

    it("renders custom child content such as a meter in place of a plain value", () => {
        render(
            <StatCard label="Hit points">
                <p role="meter" aria-label="Hit points">
                    6 / 12
                </p>
            </StatCard>,
        )

        expect(
            screen.getByRole("meter", { name: "Hit points" }),
        ).toBeInTheDocument()
    })
})

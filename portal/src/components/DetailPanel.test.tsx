import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { DetailPanel } from "./DetailPanel"

describe("DetailPanel", () => {
    it("associates the heading with the panel landmark", () => {
        render(
            <DetailPanel title="Skills">
                <p>Body content</p>
            </DetailPanel>,
        )

        const heading = screen.getByRole("heading", {
            level: 2,
            name: "Skills",
        })

        const region = screen.getByRole("region", {
            name: "Skills",
        })

        expect(region).toContainElement(heading)
        expect(screen.getByText("Body content")).toBeInTheDocument()
    })

    it("renders optional supporting description text", () => {
        render(
            <DetailPanel
                title="Senses"
                description="Passive perceptual ranges."
            >
                <p>Body content</p>
            </DetailPanel>,
        )

        expect(
            screen.getByText("Passive perceptual ranges."),
        ).toBeInTheDocument()
    })

    it("omits the description when not provided", () => {
        const { container } = render(
            <DetailPanel title="Senses">
                <p>Body content</p>
            </DetailPanel>,
        )

        expect(
            container.querySelector(".detail-panel__description"),
        ).not.toBeInTheDocument()
    })

    it("shows a default empty state when marked empty without content", () => {
        render(
            <DetailPanel title="Resources" isEmpty>
                <p>Never rendered</p>
            </DetailPanel>,
        )

        expect(
            screen.getByText("Nothing recorded."),
        ).toBeInTheDocument()

        expect(
            screen.queryByText("Never rendered"),
        ).not.toBeInTheDocument()
    })

    it("shows a custom empty state when provided", () => {
        render(
            <DetailPanel
                title="Resources"
                isEmpty
                emptyState={<p>No resources are currently recorded.</p>}
            >
                <p>Never rendered</p>
            </DetailPanel>,
        )

        expect(
            screen.getByText(
                "No resources are currently recorded.",
            ),
        ).toBeInTheDocument()
    })

    it("supports two panels with the same title without heading id collisions", () => {
        render(
            <>
                <DetailPanel title="Languages">
                    <p>First</p>
                </DetailPanel>
                <DetailPanel title="Languages">
                    <p>Second</p>
                </DetailPanel>
            </>,
        )

        const headings = screen.getAllByRole("heading", {
            level: 2,
            name: "Languages",
        })

        expect(headings).toHaveLength(2)
        expect(headings[0].id).not.toBe(headings[1].id)
    })
})

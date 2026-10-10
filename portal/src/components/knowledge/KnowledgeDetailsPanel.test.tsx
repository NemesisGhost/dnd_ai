import { render, screen, within } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { KnowledgeDetailsPanel } from "./KnowledgeDetailsPanel"

const labels = () =>
    screen
        .getAllByRole("term")
        .map((term) => term.textContent)

describe("KnowledgeDetailsPanel", () => {
    it("groups Kind, Awareness, Confidence and Willing to share in that order, label before value", () => {
        render(
            <KnowledgeDetailsPanel
                kindCode="claim"
                known={{
                    path: "party",
                    facts: [
                        { key: "awareness", label: "Awareness", value: "Aware" },
                        { key: "confidence", label: "Confidence", value: "70%" },
                        { key: "share", label: "Willing to share", value: "Yes" },
                    ],
                }}
            />,
        )
        const panel = screen.getByRole("region", { name: "Knowledge details" })
        expect(within(panel).getByRole("heading", { level: 2, name: "Knowledge details" })).toBeInTheDocument()
        expect(labels()).toEqual(["Kind", "Awareness", "Confidence", "Willing to share"])
        const values = screen.getAllByRole("definition").map((value) => value.textContent)
        expect(values).toEqual(["Claim", "Aware", "70%", "Yes"])
        // The origin explanation belongs to the panel, under its heading.
        expect(within(panel).getByText("Known through a party the character belongs to.")).toBeInTheDocument()
        expect(screen.queryByText(/Kind:/)).toBeNull()
    })

    it("lists only recorded values: missing confidence is not 0 and missing sharing is not No", () => {
        render(
            <KnowledgeDetailsPanel
                kindCode="fact"
                known={{ path: "public", facts: [{ key: "awareness", label: "Awareness", value: "Aware" }] }}
            />,
        )
        expect(labels()).toEqual(["Kind", "Awareness"])
        expect(screen.queryByText("0%")).toBeNull()
        expect(screen.queryByText("No")).toBeNull()
    })

    it("keeps the kind and explains a missing perspective or missing knowledge", () => {
        const { rerender } = render(<KnowledgeDetailsPanel kindCode="rumor" known={undefined} />)
        expect(labels()).toEqual(["Kind"])
        expect(screen.getByText(/Select a character perspective/)).toBeInTheDocument()
        rerender(<KnowledgeDetailsPanel kindCode="rumor" known={null} />)
        expect(screen.getByText(/no recorded knowledge of this claim/)).toBeInTheDocument()
        expect(labels()).toEqual(["Kind"])
    })

    it("uses the heading level it is given", () => {
        render(<KnowledgeDetailsPanel kindCode="fact" known={undefined} headingLevel={3} />)
        expect(screen.getByRole("heading", { level: 3, name: "Knowledge details" })).toBeInTheDocument()
    })
})

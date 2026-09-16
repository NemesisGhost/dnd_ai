import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { describe, expect, it } from "vitest"
import type { KnowledgeDetail } from "../types/knowledge"
import { KnowledgeDetailPage } from "./KnowledgeDetailPage"

const itemFixture: KnowledgeDetail = {
    knowledge_item_id: "knowledge-a",
    knowledge_type_code: "fact",
    statement: "The Glass Ossuary lies beneath the Rootspire.",
    truth_status_code: null,
    sensitivity: null,
    awareness_level: "understood",
    confidence: 85,
    willing_to_share: true,
}

function renderPage(item: KnowledgeDetail) {
    return render(
        <MemoryRouter>
            <KnowledgeDetailPage campaignId="campaign-a" item={item} />
        </MemoryRouter>,
    )
}

describe("KnowledgeDetailPage", () => {
    it("renders one page heading, back link, and type treatment", () => {
        renderPage(itemFixture)

        expect(
            screen.getByRole("heading", {
                level: 1,
                name: itemFixture.statement,
            }),
        ).toBeInTheDocument()

        expect(
            screen.getByRole("link", { name: "Back to Knowledge" }),
        ).toHaveAttribute("href", "/app/campaign-a/knowledge")

        expect(screen.getByText("Fact")).toBeInTheDocument()
    })

    it("shows awareness, confidence, and sharing", () => {
        renderPage(itemFixture)

        expect(screen.getByText("Understood")).toBeInTheDocument()
        expect(screen.getByText("85%")).toBeInTheDocument()
        expect(screen.getByText("Yes")).toBeInTheDocument()
    })

    it("omits the canonical panel when truth and sensitivity are both absent", () => {
        renderPage(itemFixture)

        expect(screen.queryByText("Canonical Information")).not.toBeInTheDocument()
    })

    it("shows canonical/truth information only when present", () => {
        renderPage({
            ...itemFixture,
            truth_status_code: "confirmed_false",
            sensitivity: "high",
        })

        expect(screen.getByText("Canonical Information")).toBeInTheDocument()
        expect(screen.getByText("Confirmed False")).toBeInTheDocument()
        expect(screen.getByText("High")).toBeInTheDocument()
    })

    it("shows deliberate null handling for nullable facts", () => {
        renderPage({
            ...itemFixture,
            awareness_level: null,
            confidence: null,
            willing_to_share: null,
        })

        expect(screen.getAllByText("Not recorded").length).toBeGreaterThan(0)
    })
})

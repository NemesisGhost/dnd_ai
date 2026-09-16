import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { describe, expect, it } from "vitest"
import type { KnowledgeListItem } from "../types/knowledge"
import { KnowledgeCard } from "./KnowledgeCard"

const baseItem: KnowledgeListItem = {
    knowledge_item_id: "knowledge-a",
    knowledge_type_code: "fact",
    statement: "The Glass Ossuary lies beneath the Rootspire.",
    truth_status_code: null,
    sensitivity: null,
    awareness_level: "understood",
    confidence: 85,
    willing_to_share: true,
    scope: "party",
    discovery_world_time_id: null,
    source_event_id: null,
    source_interaction_id: null,
    subject_entity_id: null,
}

function renderCard(
    item: KnowledgeListItem,
    characterId: string | null = null,
    partyId: string | null = null,
) {
    return render(
        <MemoryRouter>
            <ul>
                <KnowledgeCard
                    campaignId="campaign-a"
                    item={item}
                    characterId={characterId}
                    partyId={partyId}
                />
            </ul>
        </MemoryRouter>,
    )
}

describe("KnowledgeCard", () => {
    it("shows the statement, type, scope, awareness, confidence, and sharing", () => {
        renderCard(baseItem)

        expect(screen.getByText(baseItem.statement)).toBeInTheDocument()
        expect(screen.getByText("Fact")).toBeInTheDocument()
        expect(screen.getByText("Scope: Party")).toBeInTheDocument()
        expect(screen.getByText("Awareness: Understood")).toBeInTheDocument()
        expect(screen.getByText("Confidence: 85%")).toBeInTheDocument()
        expect(screen.getByText("Willing to share")).toBeInTheDocument()
    })

    it("links to the detail route without a query string when neither character nor party is selected", () => {
        renderCard(baseItem)

        expect(
            screen.getByRole("link", { name: baseItem.statement }),
        ).toHaveAttribute(
            "href",
            "/app/campaign-a/knowledge/knowledge-a",
        )
    })

    it("carries the selected character perspective into the detail link", () => {
        renderCard(baseItem, "character-a")

        expect(
            screen.getByRole("link", { name: baseItem.statement }),
        ).toHaveAttribute(
            "href",
            "/app/campaign-a/knowledge/knowledge-a?character_id=character-a",
        )
    })

    it("carries the selected party filter into the detail link", () => {
        renderCard(baseItem, null, "party-a")

        expect(
            screen.getByRole("link", { name: baseItem.statement }),
        ).toHaveAttribute(
            "href",
            "/app/campaign-a/knowledge/knowledge-a?party_id=party-a",
        )
    })

    it("carries both the selected character and party into the detail link", () => {
        renderCard(baseItem, "character-a", "party-a")

        expect(
            screen.getByRole("link", { name: baseItem.statement }),
        ).toHaveAttribute(
            "href",
            "/app/campaign-a/knowledge/knowledge-a?character_id=character-a&party_id=party-a",
        )
    })

    it("safely URL-encodes character and party ids", () => {
        renderCard(baseItem, "character a/b", "party a&b")

        expect(
            screen.getByRole("link", { name: baseItem.statement }),
        ).toHaveAttribute(
            "href",
            "/app/campaign-a/knowledge/knowledge-a?character_id=character+a%2Fb&party_id=party+a%26b",
        )
    })

    it("never shows the character or party id as card content or in the accessible name", () => {
        renderCard(baseItem, "character-a", "party-a")

        expect(screen.queryByText("character-a")).not.toBeInTheDocument()
        expect(screen.queryByText("party-a")).not.toBeInTheDocument()
        expect(
            screen.getByRole("link", { name: baseItem.statement }).textContent,
        ).not.toMatch(/character-a|party-a/)
    })

    it("omits nullable awareness/confidence/sharing facts rather than showing a placeholder", () => {
        renderCard({
            ...baseItem,
            awareness_level: null,
            confidence: null,
            willing_to_share: null,
        })

        expect(screen.queryByText(/Awareness:/)).not.toBeInTheDocument()
        expect(screen.queryByText(/Confidence:/)).not.toBeInTheDocument()
        expect(screen.queryByText(/willing to share/i)).not.toBeInTheDocument()
    })

    it("omits truth status when the API did not return it", () => {
        renderCard(baseItem)
        expect(screen.queryByText(/confirmed/i)).not.toBeInTheDocument()
    })

    it("shows truth status when the API intentionally returned it", () => {
        renderCard({ ...baseItem, truth_status_code: "confirmed_false" })
        expect(screen.getByText("Confirmed False")).toBeInTheDocument()
    })

    it("never displays source, subject, or discovery ids", () => {
        renderCard({
            ...baseItem,
            source_event_id: "event-a",
            subject_entity_id: "location-a",
            discovery_world_time_id: "world-time-a",
        })

        expect(screen.queryByText("event-a")).not.toBeInTheDocument()
        expect(screen.queryByText("location-a")).not.toBeInTheDocument()
        expect(screen.queryByText("world-time-a")).not.toBeInTheDocument()
    })
})

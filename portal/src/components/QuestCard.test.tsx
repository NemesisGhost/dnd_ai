import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { describe, expect, it } from "vitest"
import type { CampaignQuestListItem } from "../types/quest"
import { QuestCard } from "./QuestCard"

function renderCard(quest: CampaignQuestListItem) {
    return render(
        <MemoryRouter>
            <ul>
                <QuestCard campaignId="campaign-a" quest={quest} />
            </ul>
        </MemoryRouter>,
    )
}

describe("QuestCard", () => {
    it("shows the name and status, linked to the existing quest detail route", () => {
        renderCard({
            quest_id: "quest-a",
            name: "Restore the Lens Array",
            status_code: "active",
        })

        expect(
            screen.getByText("Restore the Lens Array"),
        ).toBeInTheDocument()
        expect(screen.getByText("active")).toBeInTheDocument()
        expect(
            screen.getByRole("link", { name: /Restore the Lens Array/ }),
        ).toHaveAttribute("href", "/app/campaign-a/quests/quest-a")
    })

    it("falls back to a no-status label when status is null", () => {
        renderCard({
            quest_id: "quest-b",
            name: "Unstructured Quest",
            status_code: null,
        })

        expect(screen.getByText("No status recorded")).toBeInTheDocument()
    })

    it("never renders the raw quest id as visible text", () => {
        renderCard({
            quest_id: "11111111-1111-1111-1111-111111111111",
            name: "Hidden Id Quest",
            status_code: null,
        })

        expect(
            screen.queryByText(/[0-9a-f]{8}-[0-9a-f]{4}/i),
        ).not.toBeInTheDocument()
    })

    it("does not invent description, objective, reward, or location content", () => {
        renderCard({
            quest_id: "quest-c",
            name: "Concise Quest",
            status_code: "active",
        })

        expect(screen.queryByText(/objective/i)).not.toBeInTheDocument()
        expect(screen.queryByText(/reward/i)).not.toBeInTheDocument()
    })
})

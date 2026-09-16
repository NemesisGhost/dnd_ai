import { render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter, Route, Routes } from "react-router"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { CharacterPerspectiveContext } from "../context/CharacterPerspectiveContext"
import type { KnowledgeDetail } from "../types/knowledge"
import { CampaignKnowledgeDetailPage } from "./CampaignKnowledgeDetailPage"

const { fetchKnowledgeDetailMock } = vi.hoisted(() => ({
    fetchKnowledgeDetailMock: vi.fn(),
}))

vi.mock("../api/knowledge", async (importOriginal) => {
    const actual = await importOriginal<typeof import("../api/knowledge")>()
    return {
        ...actual,
        fetchKnowledgeDetail: fetchKnowledgeDetailMock,
    }
})

vi.mock("../context/SessionContext", () => ({
    useSession: () => ({ reload: vi.fn() }),
}))

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

function renderAt(path: string, characterId: string | null = "character-a") {
    return render(
        <CharacterPerspectiveContext.Provider
            value={{
                getSelectedCharacterId: vi.fn(() => characterId),
                selectCharacter: vi.fn(),
            }}
        >
            <MemoryRouter initialEntries={[path]}>
                <Routes>
                    <Route
                        path="/app/:campaignId/knowledge/:knowledgeItemId"
                        element={<CampaignKnowledgeDetailPage />}
                    />
                    <Route
                        path="/app/:campaignId/knowledge"
                        element={<CampaignKnowledgeDetailPage />}
                    />
                </Routes>
            </MemoryRouter>
        </CharacterPerspectiveContext.Provider>,
    )
}

beforeEach(() => {
    fetchKnowledgeDetailMock.mockReset()
})

describe("CampaignKnowledgeDetailPage", () => {
    it("uses the selected character perspective from context, not the URL", async () => {
        fetchKnowledgeDetailMock.mockResolvedValue(itemFixture)

        renderAt("/app/campaign-a/knowledge/knowledge-a")

        await waitFor(() => {
            expect(fetchKnowledgeDetailMock).toHaveBeenCalledWith(
                "campaign-a",
                "knowledge-a",
                "character-a",
                null,
                expect.any(AbortSignal),
            )
        })

        expect(
            screen.getByRole("heading", {
                level: 1,
                name: itemFixture.statement,
            }),
        ).toBeInTheDocument()
    })

    it("carries the party filter from the URL query string", async () => {
        fetchKnowledgeDetailMock.mockResolvedValue(itemFixture)

        renderAt("/app/campaign-a/knowledge/knowledge-a?party_id=party-a")

        await waitFor(() => {
            expect(fetchKnowledgeDetailMock).toHaveBeenCalledWith(
                "campaign-a",
                "knowledge-a",
                "character-a",
                "party-a",
                expect.any(AbortSignal),
            )
        })
    })

    it("uses no perspective for a GM with no selected character", async () => {
        fetchKnowledgeDetailMock.mockResolvedValue(itemFixture)

        renderAt("/app/campaign-a/knowledge/knowledge-a", null)

        await waitFor(() => {
            expect(fetchKnowledgeDetailMock).toHaveBeenCalledWith(
                "campaign-a",
                "knowledge-a",
                null,
                null,
                expect.any(AbortSignal),
            )
        })
    })

    it("remains correct on a direct navigation without any router state", async () => {
        fetchKnowledgeDetailMock.mockResolvedValue(itemFixture)

        // A fresh MemoryRouter with only the URL entry simulates a direct
        // refresh/bookmark — no in-memory list/route state is available.
        renderAt("/app/campaign-a/knowledge/knowledge-a?party_id=party-a")

        await waitFor(() => {
            expect(
                screen.getByText(itemFixture.statement),
            ).toBeInTheDocument()
        })
    })

    it("fails closed when the knowledge item id is missing", () => {
        renderAt("/app/campaign-a/knowledge")

        expect(screen.getByText("Knowledge unavailable")).toBeInTheDocument()
        expect(fetchKnowledgeDetailMock).not.toHaveBeenCalled()
    })
})

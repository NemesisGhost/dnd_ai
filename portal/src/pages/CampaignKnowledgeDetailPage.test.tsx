import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { Link, MemoryRouter, Route, Routes } from "react-router"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { CharacterPerspectiveContext } from "../context/CharacterPerspectiveContext"
import type { KnowledgeDetail } from "../types/knowledge"
import { CampaignKnowledgeDetailPage } from "./CampaignKnowledgeDetailPage"

const { fetchKnowledgeDetailMock, reloadMock } = vi.hoisted(() => ({
    fetchKnowledgeDetailMock: vi.fn(),
    reloadMock: vi.fn(),
}))

vi.mock("../api/knowledge", async (importOriginal) => {
    const actual = await importOriginal<typeof import("../api/knowledge")>()
    return {
        ...actual,
        fetchKnowledgeDetail: fetchKnowledgeDetailMock,
    }
})

// A stable reload identity, matching the real useSessionBootstrap's
// useCallback-memoized reload — an unstable mock identity here would make
// useKnowledgeDetail's effect (which depends on reload) re-fire on every
// render for reasons unrelated to what these tests are exercising.
vi.mock("../context/SessionContext", () => ({
    useSession: () => ({ reload: reloadMock }),
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

const otherItemFixture: KnowledgeDetail = {
    knowledge_item_id: "knowledge-a",
    knowledge_type_code: "fact",
    statement: "The Drowned Shard hums when the tide turns.",
    truth_status_code: null,
    sensitivity: null,
    awareness_level: "heard",
    confidence: 40,
    willing_to_share: false,
}

function renderAt(
    path: string,
    characterId: string | null = "character-a",
    syncCharacterFromUrl: (
        campaignId: string,
        characterId: string,
    ) => void = vi.fn(),
) {
    return render(
        <CharacterPerspectiveContext.Provider
            value={{
                getSelectedCharacterId: vi.fn(() => characterId),
                selectCharacter: vi.fn(),
                syncCharacterFromUrl,
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
    reloadMock.mockReset()
})

describe("CampaignKnowledgeDetailPage", () => {
    it("prefers a character_id carried in the URL over the selected/default character", async () => {
        fetchKnowledgeDetailMock.mockResolvedValue(itemFixture)

        renderAt(
            "/app/campaign-a/knowledge/knowledge-a?character_id=character-b",
            "character-a",
        )

        await waitFor(() => {
            expect(fetchKnowledgeDetailMock).toHaveBeenCalledWith(
                "campaign-a",
                "knowledge-a",
                "character-b",
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

    it("falls back to the selected character when the URL has no character_id", async () => {
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

    it("carries both character_id and party_id from the URL to fetchKnowledgeDetail", async () => {
        fetchKnowledgeDetailMock.mockResolvedValue(itemFixture)

        renderAt(
            "/app/campaign-a/knowledge/knowledge-a?character_id=character-b&party_id=party-a",
            "character-a",
        )

        await waitFor(() => {
            expect(fetchKnowledgeDetailMock).toHaveBeenCalledWith(
                "campaign-a",
                "knowledge-a",
                "character-b",
                "party-a",
                expect.any(AbortSignal),
            )
        })
    })

    it("uses no perspective for a GM with no selected character and no URL character_id", async () => {
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

    it("remains correct on a direct navigation without any router state (refresh simulation)", async () => {
        fetchKnowledgeDetailMock.mockResolvedValue(itemFixture)

        // A fresh MemoryRouter with only the URL entry simulates a direct
        // refresh/bookmark — no in-memory list/route state is available.
        // The selected character passed to renderAt stands in for whatever
        // the bootstrap default would resolve to; the URL character must
        // still win.
        renderAt(
            "/app/campaign-a/knowledge/knowledge-a?character_id=character-b&party_id=party-a",
            "character-a",
        )

        await waitFor(() => {
            expect(fetchKnowledgeDetailMock).toHaveBeenCalledWith(
                "campaign-a",
                "knowledge-a",
                "character-b",
                "party-a",
                expect.any(AbortSignal),
            )
        })

        expect(
            screen.getByText(itemFixture.statement),
        ).toBeInTheDocument()
    })

    it("does not locally treat an unrecognized URL character_id as authorization — the server result still governs", async () => {
        fetchKnowledgeDetailMock.mockResolvedValue(itemFixture)

        const syncCharacterFromUrl = vi.fn()

        renderAt(
            "/app/campaign-a/knowledge/knowledge-a?character_id=character-unauthorized",
            "character-a",
            syncCharacterFromUrl,
        )

        // The raw URL value is still sent to the server — it decides, not
        // the client.
        await waitFor(() => {
            expect(fetchKnowledgeDetailMock).toHaveBeenCalledWith(
                "campaign-a",
                "knowledge-a",
                "character-unauthorized",
                null,
                expect.any(AbortSignal),
            )
        })
    })

    it("requests a new perspective and does not show the prior item while it loads", async () => {
        let resolveSecondRequest:
            | ((value: KnowledgeDetail) => void)
            | undefined

        fetchKnowledgeDetailMock
            .mockResolvedValueOnce(itemFixture)
            .mockImplementationOnce(
                () =>
                    new Promise<KnowledgeDetail>((resolve) => {
                        resolveSecondRequest = resolve
                    }),
            )

        render(
            <CharacterPerspectiveContext.Provider
                value={{
                    getSelectedCharacterId: vi.fn(() => "character-a"),
                    selectCharacter: vi.fn(),
                    syncCharacterFromUrl: vi.fn(),
                }}
            >
                <MemoryRouter
                    initialEntries={[
                        "/app/campaign-a/knowledge/knowledge-a?character_id=character-a",
                    ]}
                >
                    <Routes>
                        <Route
                            path="/app/:campaignId/knowledge/:knowledgeItemId"
                            element={
                                <>
                                    <CampaignKnowledgeDetailPage />
                                    <Link to="/app/campaign-a/knowledge/knowledge-a?character_id=character-b">
                                        Switch perspective
                                    </Link>
                                </>
                            }
                        />
                    </Routes>
                </MemoryRouter>
            </CharacterPerspectiveContext.Provider>,
        )

        await waitFor(() => {
            expect(
                screen.getByText(itemFixture.statement),
            ).toBeInTheDocument()
        })

        fireEvent.click(
            screen.getByRole("link", { name: "Switch perspective" }),
        )

        expect(
            screen.queryByText(itemFixture.statement),
        ).not.toBeInTheDocument()

        expect(resolveSecondRequest).toBeDefined()
        resolveSecondRequest?.(otherItemFixture)

        await waitFor(() => {
            expect(
                screen.getByText(otherItemFixture.statement),
            ).toBeInTheDocument()
        })
    })

    it("fails closed when the knowledge item id is missing", () => {
        renderAt("/app/campaign-a/knowledge")

        expect(screen.getByText("Knowledge unavailable")).toBeInTheDocument()
        expect(fetchKnowledgeDetailMock).not.toHaveBeenCalled()
    })

    describe("context consistency", () => {
        it("synchronizes the visible perspective to an authorized-looking URL character that differs from the selected one", () => {
            fetchKnowledgeDetailMock.mockResolvedValue(itemFixture)

            const syncCharacterFromUrl = vi.fn()

            renderAt(
                "/app/campaign-a/knowledge/knowledge-a?character_id=character-b",
                "character-a",
                syncCharacterFromUrl,
            )

            expect(syncCharacterFromUrl).toHaveBeenCalledWith(
                "campaign-a",
                "character-b",
            )
        })

        it("does not attempt to synchronize when the URL character already matches the selected one", () => {
            fetchKnowledgeDetailMock.mockResolvedValue(itemFixture)

            const syncCharacterFromUrl = vi.fn()

            renderAt(
                "/app/campaign-a/knowledge/knowledge-a?character_id=character-a",
                "character-a",
                syncCharacterFromUrl,
            )

            expect(syncCharacterFromUrl).not.toHaveBeenCalled()
        })

        it("does not attempt to synchronize when the URL has no character_id", () => {
            fetchKnowledgeDetailMock.mockResolvedValue(itemFixture)

            const syncCharacterFromUrl = vi.fn()

            renderAt(
                "/app/campaign-a/knowledge/knowledge-a",
                "character-a",
                syncCharacterFromUrl,
            )

            expect(syncCharacterFromUrl).not.toHaveBeenCalled()
        })

        it("does not repeatedly call synchronize (no render/reload loop) across rerenders with unchanged props", () => {
            fetchKnowledgeDetailMock.mockResolvedValue(itemFixture)

            const syncCharacterFromUrl = vi.fn()

            const { rerender } = render(
                <CharacterPerspectiveContext.Provider
                    value={{
                        getSelectedCharacterId: vi.fn(() => "character-a"),
                        selectCharacter: vi.fn(),
                        syncCharacterFromUrl,
                    }}
                >
                    <MemoryRouter
                        initialEntries={[
                            "/app/campaign-a/knowledge/knowledge-a?character_id=character-b",
                        ]}
                    >
                        <Routes>
                            <Route
                                path="/app/:campaignId/knowledge/:knowledgeItemId"
                                element={<CampaignKnowledgeDetailPage />}
                            />
                        </Routes>
                    </MemoryRouter>
                </CharacterPerspectiveContext.Provider>,
            )

            expect(syncCharacterFromUrl).toHaveBeenCalledTimes(1)

            rerender(
                <CharacterPerspectiveContext.Provider
                    value={{
                        getSelectedCharacterId: vi.fn(() => "character-a"),
                        selectCharacter: vi.fn(),
                        syncCharacterFromUrl,
                    }}
                >
                    <MemoryRouter
                        initialEntries={[
                            "/app/campaign-a/knowledge/knowledge-a?character_id=character-b",
                        ]}
                    >
                        <Routes>
                            <Route
                                path="/app/:campaignId/knowledge/:knowledgeItemId"
                                element={<CampaignKnowledgeDetailPage />}
                            />
                        </Routes>
                    </MemoryRouter>
                </CharacterPerspectiveContext.Provider>,
            )

            expect(syncCharacterFromUrl).toHaveBeenCalledTimes(1)
        })
    })
})

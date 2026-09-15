import {
    act,
    fireEvent,
    render,
    screen,
} from "@testing-library/react"
import {
    Link,
    MemoryRouter,
    Route,
    Routes,
} from "react-router"
import {
    afterEach,
    beforeEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import {
    CharacterPerspectiveContext,
} from "../context/CharacterPerspectiveContext"
import {
    useSession,
} from "../context/SessionContext"
import {
    useKnowledgeItems,
} from "../hooks/useKnowledgeItems"
import type {
    SessionBootstrapState,
} from "../hooks/useSessionBootstrap"
import { knowledgePageFixture } from "../fixtures/knowledge"
import type { AuthorizedParty } from "../types/bootstrap"
import {
    CampaignKnowledgePage,
} from "./CampaignKnowledgePage"

vi.mock("../hooks/useKnowledgeItems", () => ({
    useKnowledgeItems: vi.fn(),
}))

vi.mock("../context/SessionContext", () => ({
    useSession: vi.fn(),
}))

const useKnowledgeItemsMock =
    vi.mocked(useKnowledgeItems)
const useSessionMock = vi.mocked(useSession)

const partyPrimary: AuthorizedParty = {
    party_id: "party-primary",
    party_name: "The Adventuring Party",
}

const partyCouncil: AuthorizedParty = {
    party_id: "party-council",
    party_name: "The Merchant Council",
}

function buildSessionState(
    charactersToParties: Record<string, AuthorizedParty[]>,
): SessionBootstrapState {
    return {
        status: "authenticated",
        bootstrap: {
            user: {
                user_id: "user-a",
                display_name: "Test User",
            },
            csrf_token: "fixture-csrf-token",
            browser_session_id: "browser-session-a",
            selected_campaign_id: "campaign-a",
            campaigns: [
                {
                    campaign_id: "campaign-a",
                    campaign_name: "Campaign A",
                    world_id: null,
                    world_name: null,
                    timeline_id: null,
                    timeline_name: null,
                    roles: [],
                    character_perspectives: Object.entries(
                        charactersToParties,
                    ).map(
                        ([characterId, authorizedParties]) => ({
                            character_id: characterId,
                            character_name: characterId,
                            authorized_parties: authorizedParties,
                        }),
                    ),
                    selected_character_id: null,
                    capabilities: [],
                },
                {
                    campaign_id: "campaign-b",
                    campaign_name: "Campaign B",
                    world_id: null,
                    world_name: null,
                    timeline_id: null,
                    timeline_name: null,
                    roles: [],
                    character_perspectives: [],
                    selected_character_id: null,
                    capabilities: [],
                },
            ],
            features: {
                ask: false,
                ai_summaries: false,
                gm_briefs: false,
                cited_rules: false,
            },
        },
    }
}

beforeEach(() => {
    vi.useFakeTimers()

    useKnowledgeItemsMock.mockReset()

    useKnowledgeItemsMock.mockReturnValue({
        state: {
            status: "success",
            page: knowledgePageFixture,
        },
        retry: vi.fn(),
    })

    useSessionMock.mockReset()

    useSessionMock.mockReturnValue({
        state: buildSessionState({
            "character-a": [partyPrimary, partyCouncil],
        }),
        reload: vi.fn(),
    })
})

afterEach(() => {
    vi.useRealTimers()
})

function typeInSearch(value: string) {
    fireEvent.change(
        screen.getByRole("searchbox", {
            name: "Search",
        }),
        {
            target: {
                value,
            },
        },
    )

    act(() => {
        vi.advanceTimersByTime(180)
    })
}

function renderCampaignKnowledgePage(
    path = "/app/campaign-a/knowledge",
    characterId: string | null = "character-a",
) {
    const getSelectedCharacterId = vi.fn(
        () => characterId,
    )

    const view = render(
        <CharacterPerspectiveContext.Provider
            value={{
                getSelectedCharacterId,
                selectCharacter: vi.fn(),
            }}
        >
            <MemoryRouter initialEntries={[path]}>
                <Routes>
                    <Route
                        path="/app/:campaignId/knowledge"
                        element={<CampaignKnowledgePage />}
                    />
                    <Route
                        path="/knowledge"
                        element={<CampaignKnowledgePage />}
                    />
                </Routes>
            </MemoryRouter>
        </CharacterPerspectiveContext.Provider>,
    )

    return { ...view, getSelectedCharacterId }
}

describe("CampaignKnowledgePage", () => {
    it("requests the initial Knowledge page for the route campaign and perspective", () => {
        renderCampaignKnowledgePage()

        expect(
            useKnowledgeItemsMock,
        ).toHaveBeenCalledWith(
            "campaign-a",
            "known",
            "character-a",
            null,
            "",
            null,
            null,
        )

        expect(
            screen.getByRole("heading", {
                name: "Knowledge",
                level: 1,
            }),
        ).toBeInTheDocument()

        expect(
            screen.getByRole("heading", {
                name: knowledgePageFixture.items[0]
                    .statement,
                level: 2,
            }),
        ).toBeInTheDocument()
    })

    it("passes the selected character's authorized parties to the party selector", () => {
        renderCampaignKnowledgePage()

        const partySelect = screen.getByRole(
            "combobox",
            { name: "Party" },
        )

        expect(partySelect).toBeEnabled()

        expect(
            screen
                .getAllByRole("option")
                .filter((option) =>
                    partySelect.contains(option),
                )
                .map((option) => option.textContent),
        ).toEqual([
            "No party selected",
            "The Adventuring Party",
            "The Merchant Council",
        ])
    })

    it("applies filters and resets pagination", () => {
        renderCampaignKnowledgePage()

        fireEvent.click(
            screen.getByRole("button", {
                name: "Next page",
            }),
        )

        expect(
            useKnowledgeItemsMock,
        ).toHaveBeenLastCalledWith(
            "campaign-a",
            "known",
            "character-a",
            null,
            "",
            null,
            "next-knowledge-page",
        )

        fireEvent.change(
            screen.getByRole("combobox", {
                name: "View",
            }),
            {
                target: {
                    value: "rumors",
                },
            },
        )

        expect(
            useKnowledgeItemsMock,
        ).toHaveBeenLastCalledWith(
            "campaign-a",
            "rumors",
            "character-a",
            null,
            "",
            null,
            null,
        )

        typeInSearch("ossuary")

        expect(
            useKnowledgeItemsMock,
        ).toHaveBeenLastCalledWith(
            "campaign-a",
            "rumors",
            "character-a",
            null,
            "ossuary",
            null,
            null,
        )

        fireEvent.click(
            screen.getByRole("button", {
                name: "Next page",
            }),
        )

        fireEvent.change(
            screen.getByRole("combobox", {
                name: "Party",
            }),
            {
                target: {
                    value: "party-council",
                },
            },
        )

        expect(
            useKnowledgeItemsMock,
        ).toHaveBeenLastCalledWith(
            "campaign-a",
            "rumors",
            "character-a",
            "party-council",
            "ossuary",
            null,
            null,
        )
    })


    it("keeps showing previous results while a search refreshes", () => {
        renderCampaignKnowledgePage()

        expect(
            screen.getByText(
                knowledgePageFixture.items[0]
                    .statement,
            ),
        ).toBeInTheDocument()

        useKnowledgeItemsMock.mockReturnValue({
            state: {
                status: "refreshing",
                page: knowledgePageFixture,
            },
            retry: vi.fn(),
        })

        typeInSearch("ossuary")

        const resultsRegion = screen.getByRole(
            "region",
            {
                name: "Knowledge results",
            },
        )

        expect(resultsRegion).toHaveAttribute(
            "aria-busy",
            "true",
        )

        expect(
            screen.getByText(
                knowledgePageFixture.items[0]
                    .statement,
            ),
        ).toBeInTheDocument()

        expect(
            screen.queryByText("Updating results…"),
        ).not.toBeInTheDocument()

        act(() => {
            vi.advanceTimersByTime(200)
        })

        expect(
            screen.getByText("Updating results…"),
        ).toBeInTheDocument()
    })


    it("keeps a single page heading while the results region is loading", () => {
        useKnowledgeItemsMock.mockReturnValue({
            state: {
                status: "loading",
            },
            retry: vi.fn(),
        })

        renderCampaignKnowledgePage()

        expect(
            screen.getAllByRole("heading", {
                level: 1,
            }),
        ).toHaveLength(1)

        expect(
            screen.getByRole("heading", {
                name: "Knowledge",
                level: 1,
            }),
        ).toBeInTheDocument()

        expect(
            screen.getByRole("heading", {
                name: "Loading knowledge",
                level: 2,
            }),
        ).toBeInTheDocument()
    })

    it("keeps a single page heading while the results region shows an error", () => {
        useKnowledgeItemsMock.mockReturnValue({
            state: {
                status: "error",
                error: new Error("boom"),
            },
            retry: vi.fn(),
        })

        renderCampaignKnowledgePage()

        expect(
            screen.getAllByRole("heading", {
                level: 1,
            }),
        ).toHaveLength(1)

        expect(
            screen.getByRole("heading", {
                name: "Knowledge",
                level: 1,
            }),
        ).toBeInTheDocument()

        expect(
            screen.getByRole("heading", {
                name: "Knowledge information unavailable",
                level: 2,
            }),
        ).toBeInTheDocument()
    })

    it("does not reload on every keystroke while typing a search", () => {
        renderCampaignKnowledgePage()

        const searchInput =
            screen.getByRole("searchbox", {
                name: "Search",
            })

        fireEvent.change(searchInput, {
            target: {
                value: "o",
            },
        })

        act(() => {
            vi.advanceTimersByTime(100)
        })

        fireEvent.change(searchInput, {
            target: {
                value: "os",
            },
        })

        act(() => {
            vi.advanceTimersByTime(100)
        })

        fireEvent.change(searchInput, {
            target: {
                value: "oss",
            },
        })

        expect(
            useKnowledgeItemsMock,
        ).toHaveBeenLastCalledWith(
            "campaign-a",
            "known",
            "character-a",
            null,
            "",
            null,
            null,
        )

        act(() => {
            vi.advanceTimersByTime(300)
        })

        expect(
            useKnowledgeItemsMock,
        ).toHaveBeenLastCalledWith(
            "campaign-a",
            "known",
            "character-a",
            null,
            "oss",
            null,
            null,
        )
    })

    it("resets pagination and the party filter when the selected character perspective changes", () => {
        useSessionMock.mockReturnValue({
            state: buildSessionState({
                "character-a": [partyPrimary],
                "character-b": [partyCouncil],
            }),
            reload: vi.fn(),
        })

        const getSelectedCharacterId = vi.fn(
            () => "character-a",
        )

        function renderWithPerspective() {
            return render(
                <CharacterPerspectiveContext.Provider
                    value={{
                        getSelectedCharacterId,
                        selectCharacter: vi.fn(),
                    }}
                >
                    <MemoryRouter
                        initialEntries={[
                            "/app/campaign-a/knowledge",
                        ]}
                    >
                        <Routes>
                            <Route
                                path="/app/:campaignId/knowledge"
                                element={
                                    <CampaignKnowledgePage />
                                }
                            />
                        </Routes>
                    </MemoryRouter>
                </CharacterPerspectiveContext.Provider>,
            )
        }

        const { rerender } = renderWithPerspective()

        fireEvent.change(
            screen.getByRole("combobox", {
                name: "Party",
            }),
            {
                target: {
                    value: "party-primary",
                },
            },
        )

        fireEvent.click(
            screen.getByRole("button", {
                name: "Next page",
            }),
        )

        expect(
            useKnowledgeItemsMock,
        ).toHaveBeenLastCalledWith(
            "campaign-a",
            "known",
            "character-a",
            "party-primary",
            "",
            null,
            "next-knowledge-page",
        )

        getSelectedCharacterId.mockReturnValue(
            "character-b",
        )

        rerender(
            <CharacterPerspectiveContext.Provider
                value={{
                    getSelectedCharacterId,
                    selectCharacter: vi.fn(),
                }}
            >
                <MemoryRouter
                    initialEntries={[
                        "/app/campaign-a/knowledge",
                    ]}
                >
                    <Routes>
                        <Route
                            path="/app/:campaignId/knowledge"
                            element={
                                <CampaignKnowledgePage />
                            }
                        />
                    </Routes>
                </MemoryRouter>
            </CharacterPerspectiveContext.Provider>,
        )

        expect(
            useKnowledgeItemsMock,
        ).toHaveBeenLastCalledWith(
            "campaign-a",
            "known",
            "character-b",
            null,
            "",
            null,
            null,
        )

        expect(
            screen.getByRole("combobox", {
                name: "Party",
            }),
        ).toHaveValue("")
    })

    it("resets filters and pagination when the campaign changes", () => {
        render(
            <CharacterPerspectiveContext.Provider
                value={{
                    getSelectedCharacterId: vi.fn(
                        () => "character-a",
                    ),
                    selectCharacter: vi.fn(),
                }}
            >
                <MemoryRouter
                    initialEntries={[
                        "/app/campaign-a/knowledge",
                    ]}
                >
                    <Routes>
                        <Route
                            path="/app/:campaignId/knowledge"
                            element={
                                <>
                                    <CampaignKnowledgePage />
                                    <Link to="/app/campaign-b/knowledge">
                                        Switch campaign
                                    </Link>
                                </>
                            }
                        />
                    </Routes>
                </MemoryRouter>
            </CharacterPerspectiveContext.Provider>,
        )

        fireEvent.change(
            screen.getByRole("combobox", {
                name: "View",
            }),
            {
                target: {
                    value: "rumors",
                },
            },
        )

        typeInSearch("ossuary")

        fireEvent.click(
            screen.getByRole("button", {
                name: "Next page",
            }),
        )

        expect(
            useKnowledgeItemsMock,
        ).toHaveBeenLastCalledWith(
            "campaign-a",
            "rumors",
            "character-a",
            null,
            "ossuary",
            null,
            "next-knowledge-page",
        )

        fireEvent.click(
            screen.getByRole("link", {
                name: "Switch campaign",
            }),
        )

        expect(
            useKnowledgeItemsMock,
        ).toHaveBeenLastCalledWith(
            "campaign-b",
            "known",
            "character-a",
            null,
            "",
            null,
            null,
        )

        expect(
            screen.getByRole("searchbox", {
                name: "Search",
            }),
        ).toHaveValue("")

        expect(
            screen.getByRole("combobox", {
                name: "View",
            }),
        ).toHaveValue("known")
    })

    it("does not request Knowledge data without a campaign ID", () => {
        render(
            <CharacterPerspectiveContext.Provider
                value={{
                    getSelectedCharacterId: vi.fn(
                        () => "character-a",
                    ),
                    selectCharacter: vi.fn(),
                }}
            >
                <MemoryRouter
                    initialEntries={["/knowledge"]}
                >
                    <Routes>
                        <Route
                            path="/knowledge"
                            element={<CampaignKnowledgePage />}
                        />
                    </Routes>
                </MemoryRouter>
            </CharacterPerspectiveContext.Provider>,
        )

        expect(
            screen.getByRole("heading", {
                name: "Knowledge unavailable",
            }),
        ).toBeInTheDocument()

        expect(
            useKnowledgeItemsMock,
        ).not.toHaveBeenCalled()
    })
})

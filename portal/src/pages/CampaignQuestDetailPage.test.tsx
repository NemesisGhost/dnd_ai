import {
    MemoryRouter,
    Route,
    Routes,
} from "react-router"
import { render, screen } from "@testing-library/react"
import {
    beforeEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import {
    CharacterPerspectiveContext,
} from "../context/CharacterPerspectiveContext"
import { SessionContext } from "../context/SessionContext"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import {
    CampaignQuestDetailPage,
} from "./CampaignQuestDetailPage"

const { boundaryPropsSpy } = vi.hoisted(() => ({
    boundaryPropsSpy: vi.fn(),
}))

vi.mock(
    "../components/QuestDetailBoundary",
    () => ({
        QuestDetailBoundary: ({
            campaignId,
            questId,
            characterId,
            partyId,
        }: {
            campaignId: string
            questId: string
            characterId: string | null
            partyId?: string | null
        }) => {
            boundaryPropsSpy(
                campaignId,
                questId,
                characterId,
                partyId ?? null,
            )

            return <p>Quest boundary rendered</p>
        },
    }),
)

beforeEach(() => {
    boundaryPropsSpy.mockClear()
})

function renderPage(
    characterId: string | null,
    initialEntry =
        "/app/campaign-one/quests/quest-one",
) {
    const getSelectedCharacterId = vi.fn(
        () => characterId,
    )

    // character-one may take two parties' perspectives; character-two one.
    const session = {
        state: {
            status: "authenticated" as const,
            bootstrap: {
                ...sessionBootstrapFixture,
                campaigns: [
                    {
                        ...sessionBootstrapFixture.campaigns[0],
                        campaign_id: "campaign-one",
                        character_perspectives: [
                            {
                                character_id: "character-one",
                                character_name: "One",
                                authorized_parties: [
                                    { party_id: "party-a", party_name: "A" },
                                    { party_id: "party-b", party_name: "B" },
                                ],
                            },
                            {
                                character_id: "character-two",
                                character_name: "Two",
                                authorized_parties: [
                                    { party_id: "party-c", party_name: "C" },
                                ],
                            },
                        ],
                    },
                ],
            },
        },
        reload: vi.fn(),
        refresh: vi.fn(),
    }

    render(
        <SessionContext.Provider value={session}>
            <CharacterPerspectiveContext.Provider
                value={{
                    getSelectedCharacterId,
                    selectCharacter: vi.fn(),
                }}
            >
                <MemoryRouter initialEntries={[initialEntry]}>
                    <Routes>
                        <Route
                            path="/app/:campaignId/quests/:questId"
                            element={<CampaignQuestDetailPage />}
                        />

                        <Route
                            path="/quests/:questId"
                            element={<CampaignQuestDetailPage />}
                        />

                        <Route
                            path="/app/:campaignId/quests"
                            element={<CampaignQuestDetailPage />}
                        />
                    </Routes>
                </MemoryRouter>
            </CharacterPerspectiveContext.Provider>
        </SessionContext.Provider>,
    )

    return { getSelectedCharacterId }
}

describe("CampaignQuestDetailPage", () => {
    it("passes the route IDs and selected character to the boundary", () => {
        const { getSelectedCharacterId } =
            renderPage("character-one")

        expect(getSelectedCharacterId).toHaveBeenCalledWith(
            "campaign-one",
        )

        // Two authorized parties and no carried choice: no party is guessed.
        expect(boundaryPropsSpy).toHaveBeenCalledWith(
            "campaign-one",
            "quest-one",
            "character-one",
            null,
        )

        expect(
            screen.getByText("Quest boundary rendered"),
        ).toBeInTheDocument()
    })

    it("passes a null perspective to the boundary", () => {
        renderPage(null)

        expect(boundaryPropsSpy).toHaveBeenCalledWith(
            "campaign-one",
            "quest-one",
            null,
            null,
        )
    })

    it("uses the party perspective the quest list carried in the URL", () => {
        renderPage(
            "character-one",
            "/app/campaign-one/quests/quest-one?character_id=character-one&party_id=party-b",
        )

        expect(boundaryPropsSpy).toHaveBeenLastCalledWith(
            "campaign-one",
            "quest-one",
            "character-one",
            "party-b",
        )
    })

    it("drops a carried party once a different character is selected", () => {
        renderPage(
            "character-two",
            "/app/campaign-one/quests/quest-one?character_id=character-one&party_id=party-b",
        )

        // party-b was character-one's; character-two's only party is used.
        expect(boundaryPropsSpy).toHaveBeenLastCalledWith(
            "campaign-one",
            "quest-one",
            "character-two",
            "party-c",
        )
    })

    it.each([
        {
            description: "campaign ID",
            path: "/quests/quest-one",
        },
        {
            description: "quest ID",
            path: "/app/campaign-one/quests",
        },
    ])(
        "does not request a quest without a $description",
        ({ path }) => {
            const { getSelectedCharacterId } =
                renderPage("character-one", path)

            expect(
                screen.getByRole("heading", {
                    name: "Quest unavailable",
                }),
            ).toBeInTheDocument()

            expect(
                getSelectedCharacterId,
            ).not.toHaveBeenCalled()

            expect(
                boundaryPropsSpy,
            ).not.toHaveBeenCalled()
        },
    )
})
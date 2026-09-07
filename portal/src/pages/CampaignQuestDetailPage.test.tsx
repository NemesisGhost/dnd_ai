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
        }: {
            campaignId: string
            questId: string
            characterId: string | null
        }) => {
            boundaryPropsSpy(
                campaignId,
                questId,
                characterId,
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

    render(
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
        </CharacterPerspectiveContext.Provider>,
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

        expect(boundaryPropsSpy).toHaveBeenCalledWith(
            "campaign-one",
            "quest-one",
            "character-one",
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
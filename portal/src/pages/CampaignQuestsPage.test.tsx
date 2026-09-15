import type { ReactNode } from "react"
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
import { CampaignQuestsPage } from "./CampaignQuestsPage"

const { boundaryPropsSpy } = vi.hoisted(() => ({
    boundaryPropsSpy: vi.fn(),
}))

vi.mock(
    "../components/CampaignQuestsBoundary",
    () => ({
        CampaignQuestsBoundary: ({
            campaignId,
            characterId,
            children,
        }: {
            campaignId: string
            characterId: string | null
            children: (quests: []) => ReactNode
        }) => {
            boundaryPropsSpy(campaignId, characterId)
            return children([])
        },
    }),
)

beforeEach(() => {
    boundaryPropsSpy.mockClear()
})

function renderPage(
    characterId: string | null,
    initialEntry = "/app/campaign-one/quests",
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
                        path="/app/:campaignId/quests"
                        element={<CampaignQuestsPage />}
                    />

                    <Route
                        path="/quests"
                        element={<CampaignQuestsPage />}
                    />
                </Routes>
            </MemoryRouter>
        </CharacterPerspectiveContext.Provider>,
    )

    return { getSelectedCharacterId }
}

describe("CampaignQuestsPage", () => {
    it("passes the campaign and selected character to the boundary", () => {
        const { getSelectedCharacterId } =
            renderPage("character-one")

        expect(getSelectedCharacterId).toHaveBeenCalledWith(
            "campaign-one",
        )

        expect(boundaryPropsSpy).toHaveBeenCalledWith(
            "campaign-one",
            "character-one",
        )
    })

    it("passes a null perspective to the boundary", () => {
        renderPage(null)

        expect(boundaryPropsSpy).toHaveBeenCalledWith(
            "campaign-one",
            null,
        )
    })

    it("does not request quests without a campaign ID", () => {
        const { getSelectedCharacterId } =
            renderPage("character-one", "/quests")

        expect(
            screen.getByRole("heading", {
                name: "Quests unavailable",
            }),
        ).toBeInTheDocument()

        expect(
            getSelectedCharacterId,
        ).not.toHaveBeenCalled()

        expect(
            boundaryPropsSpy,
        ).not.toHaveBeenCalled()
    })
})
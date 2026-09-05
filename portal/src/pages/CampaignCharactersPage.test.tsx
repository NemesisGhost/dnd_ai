import {
    render,
    screen,
} from "@testing-library/react"
import {
    MemoryRouter,
    Route,
    Routes,
} from "react-router"
import {
    beforeEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import type { CharacterDetail } from "../types/character"
import { CampaignCharactersPage } from "./CampaignCharactersPage"

const {
    getSelectedCharacterIdMock,
    useCharacterMock,
} = vi.hoisted(() => ({
    getSelectedCharacterIdMock: vi.fn(),
    useCharacterMock: vi.fn(),
}))

vi.mock(
    "../context/CharacterPerspectiveContext",
    () => ({
        usePerspective: () => ({
            getSelectedCharacterId:
                getSelectedCharacterIdMock,
        }),
    }),
)

vi.mock("../hooks/useCharacter", () => ({
    useCharacter: useCharacterMock,
}))

const characterFixture: CharacterDetail = {
    character_id: "character-a",
    name: "Character A",
    species_code: "human",
    size_category: "medium",
    current_hit_points: 6,
    maximum_hit_points: 12,
    temporary_hit_points: 0,
    exhaustion_level: 0,
    death_save_successes: 0,
    death_save_failures: 0,
    current_location_id: null,
    active_encounter_id: null,
    conditions: [],
    resources: [],
}

function renderAt(
    initialPath: string,
    routePath: string,
) {
    render(
        <MemoryRouter initialEntries={[initialPath]}>
            <Routes>
                <Route
                    path={routePath}
                    element={<CampaignCharactersPage />}
                />
            </Routes>
        </MemoryRouter>,
    )
}

beforeEach(() => {
    getSelectedCharacterIdMock.mockReset()
    useCharacterMock.mockReset()
})

describe("CampaignCharactersPage", () => {
    it("fails closed when there is no campaign route parameter", () => {
        renderAt("/standalone", "/standalone")

        expect(
            screen.getByRole("heading", {
                name: "Character unavailable",
            }),
        ).toBeInTheDocument()

        expect(
            getSelectedCharacterIdMock,
        ).not.toHaveBeenCalled()

        expect(
            useCharacterMock,
        ).not.toHaveBeenCalled()
    })

    it("shows an empty state without requesting a character", () => {
        getSelectedCharacterIdMock.mockReturnValue(null)

        renderAt(
            "/app/campaign-a/characters",
            "/app/:campaignId/characters",
        )

        expect(
            screen.getByRole("heading", {
                name: "No character selected",
            }),
        ).toBeInTheDocument()

        expect(
            screen.getByText(
                "Select an available character perspective to view character information.",
            ),
        ).toBeInTheDocument()

        expect(
            getSelectedCharacterIdMock,
        ).toHaveBeenCalledWith("campaign-a")

        expect(
            useCharacterMock,
        ).not.toHaveBeenCalled()
    })

    it("loads the selected character for the current campaign", () => {
        getSelectedCharacterIdMock.mockReturnValue(
            "character-a",
        )

        useCharacterMock.mockReturnValue({
            state: {
                status: "success",
                character: characterFixture,
            },
            retry: vi.fn(),
        })

        renderAt(
            "/app/campaign-a/characters",
            "/app/:campaignId/characters",
        )

        expect(
            getSelectedCharacterIdMock,
        ).toHaveBeenCalledWith("campaign-a")

        expect(
            useCharacterMock,
        ).toHaveBeenCalledWith(
            "campaign-a",
            "character-a",
        )

        expect(
            screen.getByRole("heading", {
                name: "Character A",
            }),
        ).toBeInTheDocument()

        expect(
            screen.getByRole("meter", {
                name: "Hit points",
            }),
        ).toHaveAttribute("aria-valuenow", "6")
    })
})
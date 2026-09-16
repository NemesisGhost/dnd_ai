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
import { characterSheetFixture } from "../fixtures/characterSheet"
import type { CharacterDetail } from "../types/character"
import type { CharacterSheet } from "../types/characterSheet"
import { CampaignCharactersPage } from "./CampaignCharactersPage"

const {
    characterRetryMock,
    characterSheetRetryMock,
    getSelectedCharacterIdMock,
    useCharacterMock,
    useCharacterSheetMock,
} = vi.hoisted(() => ({
    characterRetryMock: vi.fn(),
    characterSheetRetryMock: vi.fn(),
    getSelectedCharacterIdMock: vi.fn(),
    useCharacterMock: vi.fn(),
    useCharacterSheetMock: vi.fn(),
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

vi.mock("../hooks/useCharacterSheet", () => ({
    useCharacterSheet: useCharacterSheetMock,
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

const sheetFixture = {
    ...characterSheetFixture,
    character_id: "character-a",
    name: "Character A",
} satisfies CharacterSheet

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
    characterRetryMock.mockReset()
    characterSheetRetryMock.mockReset()
    getSelectedCharacterIdMock.mockReset()
    useCharacterMock.mockReset()
    useCharacterSheetMock.mockReset()
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

        expect(
            useCharacterSheetMock,
        ).not.toHaveBeenCalled()
    })

    it("shows an empty state without requesting character data", () => {
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

        expect(
            useCharacterSheetMock,
        ).not.toHaveBeenCalled()
    })

    it("does not request the sheet while the character is loading", () => {
        getSelectedCharacterIdMock.mockReturnValue(
            "character-a",
        )

        useCharacterMock.mockReturnValue({
            state: {
                status: "loading",
            },
            retry: characterRetryMock,
        })

        renderAt(
            "/app/campaign-a/characters",
            "/app/:campaignId/characters",
        )

        expect(
            useCharacterMock,
        ).toHaveBeenCalledWith(
            "campaign-a",
            "character-a",
        )

        expect(
            useCharacterSheetMock,
        ).not.toHaveBeenCalled()

        expect(
            screen.queryByRole("heading", {
                name: "Character A",
            }),
        ).not.toBeInTheDocument()
    })

    it("does not request the sheet when the character is unavailable", () => {
        getSelectedCharacterIdMock.mockReturnValue(
            "character-a",
        )

        useCharacterMock.mockReturnValue({
            state: {
                status: "unavailable",
            },
            retry: characterRetryMock,
        })

        renderAt(
            "/app/campaign-a/characters",
            "/app/:campaignId/characters",
        )

        expect(
            screen.getByRole("heading", {
                name: "Character unavailable",
            }),
        ).toBeInTheDocument()

        expect(
            useCharacterSheetMock,
        ).not.toHaveBeenCalled()
    })

    it("requests the sheet after the character succeeds", () => {
        getSelectedCharacterIdMock.mockReturnValue(
            "character-a",
        )

        useCharacterMock.mockReturnValue({
            state: {
                status: "success",
                character: characterFixture,
            },
            retry: characterRetryMock,
        })

        useCharacterSheetMock.mockReturnValue({
            state: {
                status: "loading",
            },
            retry: characterSheetRetryMock,
        })

        renderAt(
            "/app/campaign-a/characters",
            "/app/:campaignId/characters",
        )

        expect(
            useCharacterSheetMock,
        ).toHaveBeenCalledWith(
            "campaign-a",
            "character-a",
        )

        expect(
            screen.queryByRole("heading", {
                name: "Character A",
            }),
        ).not.toBeInTheDocument()
    })

    it("renders the character sheet after both requests succeed", () => {
        getSelectedCharacterIdMock.mockReturnValue(
            "character-a",
        )

        useCharacterMock.mockReturnValue({
            state: {
                status: "success",
                character: characterFixture,
            },
            retry: characterRetryMock,
        })

        useCharacterSheetMock.mockReturnValue({
            state: {
                status: "success",
                sheet: sheetFixture,
            },
            retry: characterSheetRetryMock,
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
            useCharacterSheetMock,
        ).toHaveBeenCalledWith(
            "campaign-a",
            "character-a",
        )

        expect(
            screen.getByRole("heading", {
                level: 1,
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
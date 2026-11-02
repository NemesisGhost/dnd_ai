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
import { CampaignCharactersBrowsePage, CampaignCharactersPage } from "./CampaignCharactersPage"

const {
    canEditMock,
    characterRetryMock,
    characterSheetRetryMock,
    getSelectedCharacterIdMock,
    useCharacterMock,
    useCharacterSheetMock,
} = vi.hoisted(() => ({
    canEditMock: vi.fn(() => false),
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

vi.mock("../hooks/useCampaignCapability", () => ({
    useCampaignCapability: () => canEditMock(),
}))

vi.mock("../components/CharactersBrowser", () => ({
    CharactersBrowser: ({ campaignId }: { campaignId: string }) => (
        <p>Browser for {campaignId}</p>
    ),
}))

vi.mock("../hooks/useCharacter", () => ({
    useCharacter: useCharacterMock,
}))

vi.mock("../hooks/useCharacterSheet", () => ({
    useCharacterSheet: useCharacterSheetMock,
}))

const characterFixture: CharacterDetail = {
    character_id: "character-a",
    name: "Character A",
    character_kind: "character",
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
    character_kind: "character",
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
                    element={
                        routePath.endsWith("/all")
                            ? <CampaignCharactersBrowsePage />
                            : <CampaignCharactersPage />
                    }
                />
            </Routes>
        </MemoryRouter>,
    )
}

beforeEach(() => {
    canEditMock.mockReset()
    canEditMock.mockReturnValue(false)
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

    it("shows the character browser, not an empty placeholder, when no perspective is selected", () => {
        getSelectedCharacterIdMock.mockReturnValue(null)

        renderAt(
            "/app/campaign-a/characters",
            "/app/:campaignId/characters",
        )

        expect(screen.getByText("Browser for campaign-a")).toBeInTheDocument()
        expect(screen.queryByText("No character selected")).not.toBeInTheDocument()
        // Only the browser link: there is no selected character to go back to.
        expect(screen.queryByRole("link", { name: "Selected character" })).not.toBeInTheDocument()
        expect(screen.getByRole("link", { name: "All characters" })).toHaveAttribute(
            "href",
            "/app/campaign-a/characters/all",
        )

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

    it("offers both views when a perspective is selected, and keeps the sheet as the default", () => {
        getSelectedCharacterIdMock.mockReturnValue("character-a")
        useCharacterMock.mockReturnValue({
            state: { status: "success", character: characterFixture },
            retry: characterRetryMock,
        })
        useCharacterSheetMock.mockReturnValue({
            state: { status: "success", sheet: sheetFixture },
            retry: characterSheetRetryMock,
        })

        renderAt("/app/campaign-a/characters", "/app/:campaignId/characters")

        expect(screen.getByRole("link", { name: "Selected character" })).toHaveAttribute(
            "aria-current",
            "page",
        )
        expect(screen.getByRole("link", { name: "All characters" })).toHaveAttribute(
            "href",
            "/app/campaign-a/characters/all",
        )
        expect(screen.getByRole("heading", { level: 1, name: "Character A" })).toBeInTheDocument()
        expect(screen.queryByText("Browser for campaign-a")).not.toBeInTheDocument()
    })

    it("offers New PC to editors only, carrying the view to return to", () => {
        getSelectedCharacterIdMock.mockReturnValue(null)
        canEditMock.mockReturnValue(true)

        renderAt("/app/campaign-a/characters", "/app/:campaignId/characters")

        expect(screen.getByRole("link", { name: "New PC" })).toHaveAttribute(
            "href",
            "/app/campaign-a/characters/pc/new",
        )
        expect(screen.queryByRole("link", { name: "New character" })).not.toBeInTheDocument()
        expect(screen.queryByRole("link", { name: "New NPC" })).not.toBeInTheDocument()
    })

    it("hides New PC without canon.edit", () => {
        getSelectedCharacterIdMock.mockReturnValue(null)

        renderAt("/app/campaign-a/characters", "/app/:campaignId/characters")

        expect(screen.queryByRole("link", { name: "New PC" })).not.toBeInTheDocument()
    })

    it("shows the browser at /characters/all even with a perspective, marking it current", () => {
        getSelectedCharacterIdMock.mockReturnValue("character-a")

        renderAt("/app/campaign-a/characters/all", "/app/:campaignId/characters/all")

        expect(screen.getByText("Browser for campaign-a")).toBeInTheDocument()
        expect(screen.getByRole("link", { name: "All characters" })).toHaveAttribute(
            "aria-current",
            "page",
        )
        expect(screen.getByRole("link", { name: "Selected character" })).toHaveAttribute(
            "href",
            "/app/campaign-a/characters",
        )
        // Browsing requests no character data.
        expect(useCharacterMock).not.toHaveBeenCalled()
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
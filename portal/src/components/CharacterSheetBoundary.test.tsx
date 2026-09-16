import {
    fireEvent,
    render,
    screen,
} from "@testing-library/react"
import {
    beforeEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import { characterSheetFixture } from "../fixtures/characterSheet"
import type { CharacterSheet } from "../types/characterSheet"
import {
    CharacterSheetBoundary,
} from "./CharacterSheetBoundary"

const {
    retryMock,
    useCharacterSheetMock,
} = vi.hoisted(() => ({
    retryMock: vi.fn(),
    useCharacterSheetMock: vi.fn(),
}))

vi.mock("../hooks/useCharacterSheet", () => ({
    useCharacterSheet: useCharacterSheetMock,
}))

function renderBoundary() {
    render(
        <CharacterSheetBoundary
            campaignId="campaign-a"
            characterId="character-a"
        >
            {(sheet) => <p>{sheet.name}</p>}
        </CharacterSheetBoundary>,
    )
}

beforeEach(() => {
    retryMock.mockReset()
    useCharacterSheetMock.mockReset()
})

describe("CharacterSheetBoundary", () => {
    it("shows loading without rendering sheet content", () => {
        useCharacterSheetMock.mockReturnValue({
            state: {
                status: "loading",
            },
            retry: retryMock,
        })

        renderBoundary()

        expect(
            screen.getByRole("heading", {
                name: "Loading character sheet",
            }),
        ).toBeInTheDocument()

        expect(
            screen.queryByText("Ixamarra"),
        ).not.toBeInTheDocument()

        expect(
            useCharacterSheetMock,
        ).toHaveBeenCalledWith(
            "campaign-a",
            "character-a",
        )
    })

    it("shows a non-disclosing unavailable state", () => {
        useCharacterSheetMock.mockReturnValue({
            state: {
                status: "unavailable",
            },
            retry: retryMock,
        })

        renderBoundary()

        expect(
            screen.getByRole("heading", {
                name: "Character sheet unavailable",
            }),
        ).toBeInTheDocument()

        expect(
            screen.getByText(
                "The requested character sheet is not available.",
            ),
        ).toBeInTheDocument()

        expect(
            screen.queryByText("Ixamarra"),
        ).not.toBeInTheDocument()
    })

    it("shows a safe recoverable error and retries", () => {
        const diagnosticError = new Error(
            "Database connection failed for internal host",
        )

        useCharacterSheetMock.mockReturnValue({
            state: {
                status: "error",
                error: diagnosticError,
            },
            retry: retryMock,
        })

        renderBoundary()

        expect(
            screen.getByRole("heading", {
                name: "Character sheet unavailable",
            }),
        ).toBeInTheDocument()

        expect(
            screen.queryByText(
                diagnosticError.message,
            ),
        ).not.toBeInTheDocument()

        expect(
            screen.queryByText("Ixamarra"),
        ).not.toBeInTheDocument()

        fireEvent.click(
            screen.getByRole("button", {
                name: "Try again",
            }),
        )

        expect(retryMock).toHaveBeenCalledTimes(1)
    })

    it("renders the authorized sheet after success", () => {
        useCharacterSheetMock.mockReturnValue({
            state: {
                status: "success",
                sheet: characterSheetFixture,
            },
            retry: retryMock,
        })

        renderBoundary()

        expect(
            screen.getByText("Ixamarra"),
        ).toBeInTheDocument()

        expect(
            screen.queryByRole("button", {
                name: "Try again",
            }),
        ).not.toBeInTheDocument()
    })

    it("passes an authorized empty build to the page", () => {
        const emptyBuild = {
            ...characterSheetFixture,
            character_build_id: null,
            build_label: null,
            ruleset_code: null,
            ruleset_display_name: null,
            ruleset_version_id: null,
            ruleset_version_label: null,
            total_level: 0,
            proficiency_bonus: null,
            class_levels: [],
            ability_scores: [],
            skills: [],
            saving_throws: [],
            other_proficiencies: [],
            features: [],
            spellcasting_profiles: [],
        } satisfies CharacterSheet

        useCharacterSheetMock.mockReturnValue({
            state: {
                status: "success",
                sheet: emptyBuild,
            },
            retry: retryMock,
        })

        render(
            <CharacterSheetBoundary
                campaignId="campaign-a"
                characterId="character-a"
            >
                {(sheet) => (
                    <p>
                        {sheet.character_build_id ===
                            null
                            ? "No active build"
                            : sheet.name}
                    </p>
                )}
            </CharacterSheetBoundary>,
        )

        expect(
            screen.getByText("No active build"),
        ).toBeInTheDocument()

        expect(
            screen.queryByRole("heading", {
                name: "Character sheet unavailable",
            }),
        ).not.toBeInTheDocument()
    })
})
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
import type { CharacterDetail } from "../types/character"
import { CharacterBoundary } from "./CharacterBoundary"

const {
    retryMock,
    useCharacterMock,
} = vi.hoisted(() => ({
    retryMock: vi.fn(),
    useCharacterMock: vi.fn(),
}))

vi.mock("../hooks/useCharacter", () => ({
    useCharacter: useCharacterMock,
}))

const characterFixture: CharacterDetail = {
    character_id: "character-a",
    name: "Character A",
    species_code: "human",
    size_category: "medium",
    current_hit_points: 10,
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

function renderBoundary() {
    render(
        <CharacterBoundary
            campaignId="campaign-a"
            characterId="character-a"
        >
            {(character) => (
                <p>{character.name}</p>
            )}
        </CharacterBoundary>,
    )
}

beforeEach(() => {
    retryMock.mockReset()
    useCharacterMock.mockReset()
})

describe("CharacterBoundary", () => {
    it("shows a loading state without rendering character content", () => {
        useCharacterMock.mockReturnValue({
            state: {
                status: "loading",
            },
            retry: retryMock,
        })

        renderBoundary()

        expect(
            screen.getByRole("heading", {
                name: "Loading character",
            }),
        ).toBeInTheDocument()

        expect(
            screen.queryByText("Character A"),
        ).not.toBeInTheDocument()

        expect(useCharacterMock).toHaveBeenCalledWith(
            "campaign-a",
            "character-a",
        )
    })

    it("shows a non-disclosing unavailable state", () => {
        useCharacterMock.mockReturnValue({
            state: {
                status: "unavailable",
            },
            retry: retryMock,
        })

        renderBoundary()

        expect(
            screen.getByRole("heading", {
                name: "Character unavailable",
            }),
        ).toBeInTheDocument()

        expect(
            screen.getByText(
                "The requested character information is not available.",
            ),
        ).toBeInTheDocument()

        expect(
            screen.queryByText("Character A"),
        ).not.toBeInTheDocument()
    })

    it("shows a safe recoverable error and retries", () => {
        const diagnosticError = new Error(
            "Database connection failed for internal host",
        )

        useCharacterMock.mockReturnValue({
            state: {
                status: "error",
                error: diagnosticError,
            },
            retry: retryMock,
        })

        renderBoundary()

        expect(
            screen.getByRole("heading", {
                name: "Character information unavailable",
            }),
        ).toBeInTheDocument()

        expect(
            screen.queryByText(diagnosticError.message),
        ).not.toBeInTheDocument()

        expect(
            screen.queryByText("Character A"),
        ).not.toBeInTheDocument()

        fireEvent.click(
            screen.getByRole("button", {
                name: "Try again",
            }),
        )

        expect(retryMock).toHaveBeenCalledTimes(1)
    })

    it("renders character content after a successful request", () => {
        useCharacterMock.mockReturnValue({
            state: {
                status: "success",
                character: characterFixture,
            },
            retry: retryMock,
        })

        renderBoundary()

        expect(
            screen.getByText("Character A"),
        ).toBeInTheDocument()

        expect(
            screen.queryByRole("button", {
                name: "Try again",
            }),
        ).not.toBeInTheDocument()
    })
})
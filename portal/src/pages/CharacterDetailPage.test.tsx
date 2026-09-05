import {
    render,
    screen,
} from "@testing-library/react"
import {
    describe,
    expect,
    it,
} from "vitest"
import type { CharacterDetail } from "../types/character"
import { CharacterDetailPage } from "./CharacterDetailPage"

const fullCharacterFixture: CharacterDetail = {
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

describe("CharacterDetailPage", () => {
    it("renders the character overview without protected details", () => {
        const summaryCharacter: CharacterDetail = {
            ...fullCharacterFixture,
            current_hit_points: 6,
            maximum_hit_points: 12,
            temporary_hit_points: 3,
            exhaustion_level: 2,
            conditions: null,
            resources: null,
        }

        render(
            <CharacterDetailPage
                character={summaryCharacter}
            />,
        )

        expect(
            screen.getByRole("heading", {
                name: "Character A",
            }),
        ).toBeInTheDocument()

        expect(
            screen.getByRole("heading", {
                name: "Overview",
            }),
        ).toBeInTheDocument()

        expect(
            screen.getByText("human"),
        ).toBeInTheDocument()

        expect(
            screen.getByText("medium"),
        ).toBeInTheDocument()

        expect(
            screen.getByText(
                "Additional character details are not available.",
            ),
        ).toBeInTheDocument()

        expect(
            screen.queryByText("Hit points"),
        ).not.toBeInTheDocument()

        expect(
            screen.queryByText("Temporary hit points"),
        ).not.toBeInTheDocument()

        expect(
            screen.queryByText("Exhaustion level"),
        ).not.toBeInTheDocument()

        expect(
            screen.queryByRole("meter"),
        ).not.toBeInTheDocument()
    })

    it("renders full current-state details including zero values", () => {
        render(
            <CharacterDetailPage
                character={fullCharacterFixture}
            />,
        )

        expect(
            screen.getByRole("heading", {
                name: "Current state",
            }),
        ).toBeInTheDocument()

        expect(
            screen.getByRole("meter", {
                name: "Hit points",
            }),
        ).toHaveAttribute("aria-valuenow", "6")

        const temporaryHitPoints =
            screen.getByText(
                "Temporary hit points",
            ).nextElementSibling

        const exhaustionLevel =
            screen.getByText(
                "Exhaustion level",
            ).nextElementSibling

        expect(temporaryHitPoints).toHaveTextContent("0")
        expect(exhaustionLevel).toHaveTextContent("0")

        expect(
            screen.queryByText(
                "Additional character details are not available.",
            ),
        ).not.toBeInTheDocument()
    })

    it("shows a fallback when hit points are not recorded", () => {
        const characterWithoutHitPoints: CharacterDetail = {
            ...fullCharacterFixture,
            current_hit_points: null,
            maximum_hit_points: null,
        }

        render(
            <CharacterDetailPage
                character={characterWithoutHitPoints}
            />,
        )

        const hitPoints =
            screen.getByText(
                "Hit points",
            ).nextElementSibling

        expect(hitPoints).toHaveTextContent("Not recorded")

        expect(
            screen.queryByRole("meter"),
        ).not.toBeInTheDocument()
    })
})
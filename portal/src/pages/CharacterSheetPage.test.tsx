import { render, screen, within } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { characterSheetFixture } from "../fixtures/characterSheet"
import type { CharacterDetail } from "../types/character"
import type { CharacterSheet } from "../types/characterSheet"
import { CharacterSheetPage } from "./CharacterSheetPage"

const baseCharacter: CharacterDetail = {
    character_id: "character-ixamarra",
    name: "Ixamarra",
    species_code: "dragonborn",
    size_category: "medium",
    current_hit_points: 30,
    maximum_hit_points: 42,
    temporary_hit_points: 0,
    exhaustion_level: 0,
    death_save_successes: 0,
    death_save_failures: 0,
    current_location_id: null,
    active_encounter_id: null,
    conditions: [],
    resources: [],
}

function renderPage(
    sheet: CharacterSheet = characterSheetFixture,
    character: CharacterDetail = baseCharacter,
) {
    return render(
        <CharacterSheetPage sheet={sheet} character={character} />,
    )
}

describe("CharacterSheetPage", () => {
    it("renders the header facts", () => {
        renderPage()

        expect(
            screen.getByRole("heading", {
                level: 1,
                name: "Ixamarra",
            }),
        ).toBeInTheDocument()

        expect(screen.getByText("Dragonborn")).toBeInTheDocument()
        expect(screen.getByText("medium")).toBeInTheDocument()
        expect(screen.getByText("6")).toBeInTheDocument()
        expect(screen.getByText("+3")).toBeInTheDocument()
        expect(
            screen.getByText("Bard 6 – College of Lore"),
        ).toBeInTheDocument()
        expect(screen.getByText("Walk 30 ft")).toBeInTheDocument()
        expect(screen.getByText("Primary Build")).toBeInTheDocument()
        expect(
            screen.getByText("Dungeons & Dragons Fifth Edition"),
        ).toBeInTheDocument()
        expect(screen.getByText("2014 Core Rules")).toBeInTheDocument()
    })

    it("shows the hit points meter from the passed-in character", () => {
        renderPage()

        expect(
            screen.getByRole("meter", { name: "Hit points" }),
        ).toHaveAttribute("aria-valuenow", "30")
    })

    it("falls back to a not-recorded note when hit points are missing", () => {
        renderPage(characterSheetFixture, {
            ...baseCharacter,
            current_hit_points: null,
            maximum_hit_points: null,
        })

        const hitPoints = screen.getByText("Hit points").nextElementSibling
        expect(hitPoints).toHaveTextContent("Not recorded")
        expect(screen.queryByRole("meter")).not.toBeInTheDocument()
    })

    it("renders ability scores with their matching saving throws", () => {
        renderPage()

        const table = screen.getByRole("table", {
            name: "Ability scores and saving throws",
        })

        const charismaRow = within(table)
            .getByText("Charisma")
            .closest("tr")

        expect(charismaRow).not.toBeNull()
        const charismaCells = within(charismaRow as HTMLElement).getAllByRole(
            "cell",
        )
        expect(charismaCells.map((cell) => cell.textContent)).toEqual([
            "Charisma",
            "18",
            "+4",
            "Proficient",
            "+7",
        ])
    })

    it("splits skills across multiple tables preserving overall order", () => {
        renderPage()

        const columnOne = screen.getByRole("table", {
            name: "Skills (column 1)",
        })
        const columnTwo = screen.getByRole("table", {
            name: "Skills (column 2)",
        })
        const columnThree = screen.getByRole("table", {
            name: "Skills (column 3)",
        })

        expect(within(columnOne).getByText("Arcana")).toBeInTheDocument()
        expect(within(columnTwo).getByText("History")).toBeInTheDocument()
        expect(
            within(columnThree).getByText("Persuasion"),
        ).toBeInTheDocument()

        expect(screen.getAllByText("Expertise").length).toBeGreaterThan(0)
    })

    it("combines other proficiencies, languages, and senses in one table", () => {
        renderPage()

        const table = screen.getByRole("table", {
            name: "Other proficiencies, languages, and senses",
        })

        expect(within(table).getByText("Lute")).toBeInTheDocument()
        expect(within(table).getByText("Draconic")).toBeInTheDocument()
        expect(within(table).getByText("Darkvision")).toBeInTheDocument()
        expect(within(table).getByText("60 ft")).toBeInTheDocument()
    })

    it("renders features with their source and granted level", () => {
        renderPage()

        const row = screen
            .getByText("Cutting Words")
            .closest("tr") as HTMLElement

        const cells = within(row).getAllByRole("cell")
        expect(cells.map((cell) => cell.textContent)).toEqual([
            "Cutting Words",
            "Use Bardic Inspiration to distract another creature.",
            "Subclass",
            "3",
        ])
    })

    it("sorts spells by level and shows known/prepared indicators", () => {
        renderPage()

        const table = screen.getByRole("table", {
            name: "Bard spells",
        })

        const rows = within(table).getAllByRole("row").slice(1)
        const firstRowCells = within(rows[0]).getAllByRole("cell")
        expect(firstRowCells[0]).toHaveTextContent("Cantrip")
        expect(firstRowCells[1]).toHaveTextContent("Vicious Mockery")
        expect(firstRowCells[3]).toHaveTextContent("Known")
        expect(firstRowCells[4]).toHaveTextContent("Prepared")

        const secondRowCells = within(rows[1]).getAllByRole("cell")
        expect(secondRowCells[1]).toHaveTextContent("Detect Magic")
        expect(secondRowCells[4]).toHaveTextContent("Not prepared")
    })

    it("does not put the spellcasting profile id in the DOM", () => {
        renderPage()

        const profileId =
            characterSheetFixture.spellcasting_profiles[0]
                .character_spellcasting_profile_id

        expect(
            document.querySelector(`[id*="${profileId}"]`),
        ).not.toBeInTheDocument()
    })

    it("renders an empty-build note while preserving character-level collections", () => {
        const emptyBuild: CharacterSheet = {
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

        renderPage(emptyBuild)

        expect(
            screen.getByText(
                "No active character build is selected for this timeline.",
            ),
        ).toBeInTheDocument()

        expect(screen.getByText("No active build")).toBeInTheDocument()
        expect(screen.getByText("No ability scores recorded.")).toBeInTheDocument()
        expect(screen.getByText("No skills recorded.")).toBeInTheDocument()
        expect(screen.getByText("No features recorded.")).toBeInTheDocument()
        expect(
            screen.getByText("No spellcasting abilities recorded."),
        ).toBeInTheDocument()

        expect(screen.getByText("Draconic")).toBeInTheDocument()
        expect(screen.getByText("Darkvision")).toBeInTheDocument()
        expect(screen.getByText("Walk 30 ft")).toBeInTheDocument()
    })
})

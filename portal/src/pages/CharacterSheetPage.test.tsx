import { render, screen, within } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import {
    characterSheetFixture,
    sparseCharacterSheetFixture,
} from "../fixtures/characterSheet"
import type { CharacterDetail } from "../types/character"
import type {
    CharacterSheet,
    CharacterSheetSpell,
} from "../types/characterSheet"
import { CharacterSheetPage } from "./CharacterSheetPage"

const richCharacter: CharacterDetail = {
    character_id: "character-ixamarra",
    name: "Ixamarra",
    species_code: "dragonborn",
    size_category: "medium",
    current_hit_points: 30,
    maximum_hit_points: 42,
    temporary_hit_points: 5,
    exhaustion_level: 1,
    death_save_successes: 2,
    death_save_failures: 1,
    current_location_id: null,
    active_encounter_id: null,
    conditions: [
        {
            condition_code: "poisoned",
            source_description: "Giant spider bite",
        },
    ],
    resources: [
        {
            resource_code: "inspiration_die",
            current_amount: 2,
            maximum_amount: 5,
        },
    ],
}

const sparseCharacter: CharacterDetail = {
    character_id: "character-sparse",
    name: "Sparse Fighter",
    species_code: "human",
    size_category: "medium",
    current_hit_points: null,
    maximum_hit_points: null,
    temporary_hit_points: null,
    exhaustion_level: null,
    death_save_successes: null,
    death_save_failures: null,
    current_location_id: null,
    active_encounter_id: null,
    conditions: null,
    resources: null,
}

function renderPage(
    sheet: CharacterSheet = characterSheetFixture,
    character: CharacterDetail = richCharacter,
) {
    return render(
        <CharacterSheetPage sheet={sheet} character={character} />,
    )
}

describe("CharacterSheetPage", () => {
    it("has exactly one page heading identifying the character", () => {
        renderPage()

        const headings = screen.getAllByRole("heading", { level: 1 })
        expect(headings).toHaveLength(1)
        expect(headings[0]).toHaveTextContent("Ixamarra")
    })

    it("renders the character/build header facts", () => {
        renderPage()

        expect(screen.getByText("Dragonborn")).toBeInTheDocument()
        expect(screen.getByText("Medium")).toBeInTheDocument()
        expect(
            screen.getByText("Bard 6 — College of Lore — d8"),
        ).toBeInTheDocument()
        expect(screen.getByText("Primary Build")).toBeInTheDocument()
        expect(
            screen.getByText("Dungeons & Dragons Fifth Edition"),
        ).toBeInTheDocument()
        expect(screen.getByText("2014 Core Rules")).toBeInTheDocument()

        const characterLevelRow = screen.getByText(
            "Character level",
        ).closest(".fact-grid__row") as HTMLElement
        expect(
            within(characterLevelRow).getByText("6"),
        ).toBeInTheDocument()
    })

    it("keeps every multiclass entry in contract order and names the bounded header", () => {
        const fighter = {
            ...characterSheetFixture.class_levels[0],
            class_id: "class-fighter", class_display_name: "Fighter", level: 2,
            hit_die: 10, subclass_display_name: null,
        }
        renderPage({ ...characterSheetFixture, class_levels: [fighter, characterSheetFixture.class_levels[0]] })
        const header = screen.getByRole("banner", { name: "Ixamarra" })
        expect(within(header).getByRole("heading", { level: 1, name: "Ixamarra" })).toBeInTheDocument()
        expect(within(header).getAllByRole("listitem").map((item) => item.textContent))
            .toEqual(["Fighter 2 — d10", "Bard 6 — College of Lore — d8"])
    })

    it("keeps deliberate no-build fallbacks in Character Details", () => {
        renderPage(sparseCharacterSheetFixture, sparseCharacter)
        const header = screen.getByRole("banner", { name: "Sparse Fighter" })
        expect(header).toHaveTextContent("None recorded")
        expect(header).toHaveTextContent("No active build")
        expect(header).toHaveTextContent("RulesetNot recorded")
    })

    it("shows the primary stat cards including proficiency bonus and movement", () => {
        renderPage()

        expect(screen.getByText("Proficiency bonus")).toBeInTheDocument()
        expect(screen.getByText("+3")).toBeInTheDocument()
        expect(screen.getByText("Walk")).toBeInTheDocument()
        expect(screen.getByText("30 ft")).toBeInTheDocument()
    })

    it("renders every movement type and a missing-movement fallback", () => {
        const movements = [
            ...characterSheetFixture.movements,
            { movement_type: "fly", speed_feet: 60 },
            { movement_type: "swim", speed_feet: 20 },
        ]
        const { rerender } = renderPage({ ...characterSheetFixture, movements })
        const primary = screen.getByRole("region", { name: "Primary stats" })
        expect(primary).toHaveTextContent("Walk30 ft")
        expect(primary).toHaveTextContent("Fly60 ft")
        expect(primary).toHaveTextContent("Swim20 ft")
        rerender(<CharacterSheetPage sheet={{ ...characterSheetFixture, movements: [] }} character={richCharacter} />)
        expect(screen.getByRole("region", { name: "Primary stats" })).toHaveTextContent("MovementNot recorded")
    })

    it("shows the hit points meter from the passed-in CharacterDetail", () => {
        renderPage()

        expect(
            screen.getByRole("meter", { name: "Hit points" }),
        ).toHaveAttribute("aria-valuenow", "30")
    })

    it("falls back to a not-recorded note when hit points are missing", () => {
        renderPage(characterSheetFixture, sparseCharacter)

        expect(screen.queryByRole("meter")).not.toBeInTheDocument()

        const hitPointsCard = screen
            .getByText("Hit points")
            .closest("figure") as HTMLElement
        expect(hitPointsCard).toHaveTextContent("Not recorded")
    })

    it("keeps temporary HP with the meter and moves exhaustion and death saves into Current State", () => {
        renderPage()
        const hpCard = screen.getByText("Hit points").closest("figure") as HTMLElement
        expect(within(hpCard).getByRole("meter")).toHaveAttribute("aria-valuemax", "42")
        expect(hpCard).toHaveTextContent("Temporary hit points: 5")
        expect(screen.queryByText("Temporary hit points", { exact: true })).not.toBeInTheDocument()
        const currentState = screen.getByRole("region", { name: "Current State" })
        expect(currentState).toHaveTextContent("Exhaustion")
        expect(currentState).toHaveTextContent("1")
        expect(currentState).toHaveTextContent("Death saves")
        expect(currentState).toHaveTextContent("2 / 1")
    })

    it("preserves recorded zeroes and nullable current state", () => {
        const { rerender } = renderPage(characterSheetFixture, {
            ...richCharacter, temporary_hit_points: 0, exhaustion_level: 0,
        })
        expect(screen.getByText("Hit points").closest("figure")).toHaveTextContent("Temporary hit points: 0")
        expect(screen.getByRole("region", { name: "Current State" })).toHaveTextContent("Exhaustion0")
        rerender(<CharacterSheetPage sheet={characterSheetFixture} character={sparseCharacter} />)
        expect(screen.getByText("Hit points").closest("figure")).toHaveTextContent("Temporary hit points: Not recorded")
        expect(screen.getByRole("region", { name: "Current State" })).toHaveTextContent("Death savesNot recorded")
    })

    it("renders ability score cards with score, modifier, and matching saving throw", () => {
        renderPage()

        const card = screen.getByRole("article", { name: "Charisma" })

        expect(within(card).getByText("+4")).toBeInTheDocument()
        expect(within(card).getByText("Score 18")).toBeInTheDocument()
        expect(within(card).getByText("+7")).toBeInTheDocument()
        expect(within(card).getByText("Proficient")).toBeInTheDocument()
    })

    it("shows a non-proficient saving throw without inventing proficiency", () => {
        renderPage()

        const card = screen.getByRole("article", { name: "Strength" })

        expect(within(card).getByText("Not proficient")).toBeInTheDocument()
    })

    it("does not put any raw ability id in the DOM", () => {
        const { container } = renderPage()

        for (const ability of characterSheetFixture.ability_scores) {
            expect(
                container.innerHTML.includes(ability.ability_id),
            ).toBe(false)
        }
    })

    it("renders the skills panel with proficiency, expertise, and bonus", () => {
        renderPage()

        const table = screen.getByRole("table", { name: "Skills" })

        const historyRow = within(table)
            .getByText("History")
            .closest("tr") as HTMLElement

        expect(within(historyRow).getByText("INT")).toBeInTheDocument()
        expect(within(historyRow).getByText("+7")).toBeInTheDocument()
        expect(within(historyRow).getByText("17")).toBeInTheDocument()

        const checkbox = within(historyRow).getByRole("checkbox", {
            name: "Expertise",
        })
        expect(checkbox).toBeChecked()
        expect(checkbox).toBeDisabled()
        expect(within(historyRow).getByText("×2")).toBeInTheDocument()
    })

    it("groups other proficiencies, languages, senses, conditions, and resources into one Other Details panel", () => {
        renderPage()

        const panel = screen
            .getByRole("heading", { level: 2, name: "Other Details" })
            .closest(".detail-panel") as HTMLElement

        expect(
            within(panel).getByRole("heading", {
                level: 3,
                name: "Other Proficiencies",
            }),
        ).toBeInTheDocument()
        expect(within(panel).getByText("Lute")).toBeInTheDocument()

        expect(
            within(panel).getByRole("heading", {
                level: 3,
                name: "Languages",
            }),
        ).toBeInTheDocument()
        expect(within(panel).getByText("Draconic")).toBeInTheDocument()

        expect(
            within(panel).getByRole("heading", {
                level: 3,
                name: "Senses",
            }),
        ).toBeInTheDocument()
        expect(within(panel).getByText("Darkvision")).toBeInTheDocument()
        expect(within(panel).getByText("60 ft")).toBeInTheDocument()

        expect(
            within(panel).getByRole("heading", {
                level: 3,
                name: "Conditions",
            }),
        ).toBeInTheDocument()
        expect(within(panel).getByText("Poisoned")).toBeInTheDocument()
        expect(
            within(panel).getByText(/Giant spider bite/),
        ).toBeInTheDocument()

        expect(
            within(panel).getByRole("heading", {
                level: 3,
                name: "Resources",
            }),
        ).toBeInTheDocument()
        expect(
            within(panel).getByText("Inspiration Die"),
        ).toBeInTheDocument()
    })

    it("puts the Other Details panel before Features & Traits", () => {
        renderPage()

        const headings = screen
            .getAllByRole("heading", { level: 2 })
            .map((heading) => heading.textContent)

        const otherDetailsIndex = headings.indexOf("Other Details")
        const featuresIndex = headings.indexOf("Features & Traits")

        expect(otherDetailsIndex).toBeGreaterThanOrEqual(0)
        expect(featuresIndex).toBeGreaterThan(otherDetailsIndex)
    })

    it("preserves valid empty conditions and resources states", () => {
        renderPage(characterSheetFixture, {
            ...richCharacter,
            conditions: [],
            resources: [],
        })

        expect(
            screen.getByText("No conditions are currently recorded."),
        ).toBeInTheDocument()
        expect(
            screen.getByText("No resources are currently recorded."),
        ).toBeInTheDocument()
    })

    it("shows a neutral not-recorded state when conditions and resources are unavailable", () => {
        renderPage(characterSheetFixture, sparseCharacter)

        expect(screen.getAllByText("Not recorded.").length).toBe(2)
    })

    it("renders native feature disclosures with metadata and description", () => {
        renderPage()
        const card = screen.getByText("Cutting Words").closest("details") as HTMLElement
        expect(card.tagName).toBe("DETAILS")
        expect(within(card).getByText("Subclass")).toBeInTheDocument()
        expect(within(card).getByText("Granted at level 3")).toBeInTheDocument()
        expect(within(card).getByText("Use Bardic Inspiration to distract another creature.")).toBeInTheDocument()
    })

    it("groups spells by level, labeling level zero as Cantrips", () => {
        renderPage()

        expect(
            screen.getByRole("heading", { level: 4, name: "Cantrips" }),
        ).toBeInTheDocument()
        expect(
            screen.getByRole("heading", { level: 4, name: "Level 1" }),
        ).toBeInTheDocument()

        expect(screen.getByText("Vicious Mockery")).toBeInTheDocument()
        expect(screen.getByText("Detect Magic")).toBeInTheDocument()
    })

    it("preserves the backend's same-level spell order instead of alphabetizing by display name", () => {
        const zephyrStrike: CharacterSheetSpell = {
            ...characterSheetFixture.spellcasting_profiles[0].spells[1],
            spell_id: "spell-zephyr-strike",
            code: "zephyr_strike",
            display_name: "Zephyr Strike",
            level: 1,
        }

        const arcaneLock: CharacterSheetSpell = {
            ...characterSheetFixture.spellcasting_profiles[0].spells[1],
            spell_id: "spell-arcane-lock",
            code: "arcane_lock",
            display_name: "Arcane Lock",
            level: 1,
        }

        const sheetWithOrderedSpells: CharacterSheet = {
            ...characterSheetFixture,
            spellcasting_profiles: [
                {
                    ...characterSheetFixture.spellcasting_profiles[0],
                    // Server/code order is Zephyr Strike then Arcane
                    // Lock -- the reverse of alphabetical display-name
                    // order -- so a naive re-sort by name would be
                    // detectable here.
                    spells: [zephyrStrike, arcaneLock],
                },
            ],
        }

        renderPage(sheetWithOrderedSpells)

        const levelOneHeading = screen.getByRole("heading", {
            level: 4,
            name: "Level 1",
        })

        const levelOneGroup = levelOneHeading.closest(
            ".spellcasting-profile__level-group",
        ) as HTMLElement

        const spellNames = within(levelOneGroup).getAllByText(/Zephyr Strike|Arcane Lock/)
            .map((item) => item.textContent)

        expect(spellNames).toEqual(["Zephyr Strike", "Arcane Lock"])
    })

    it("shows known/prepared state explicitly for each spell", () => {
        renderPage()

        const vickedMockeryEntry = screen
            .getByText("Vicious Mockery")
            .closest("details") as HTMLElement
        expect(within(vickedMockeryEntry).getByText("Known")).toBeInTheDocument()
        expect(
            within(vickedMockeryEntry).getByText("Prepared"),
        ).toBeInTheDocument()

        const detectMagicEntry = screen
            .getByText("Detect Magic")
            .closest("details") as HTMLElement
        expect(within(detectMagicEntry).getByText("Known")).toBeInTheDocument()
        expect(
            within(detectMagicEntry).getByText("Not prepared"),
        ).toBeInTheDocument()
    })

    it("supports multiple spellcasting profiles without duplicate DOM ids", () => {
        const secondProfile = {
            ...characterSheetFixture.spellcasting_profiles[0],
            character_spellcasting_profile_id: "spellcasting-profile-feat",
            class_id: null,
            class_code: null,
            class_display_name: null,
        }

        const multiProfileSheet: CharacterSheet = {
            ...characterSheetFixture,
            spellcasting_profiles: [
                characterSheetFixture.spellcasting_profiles[0],
                secondProfile,
            ],
        }

        const { container } = renderPage(multiProfileSheet)

        const headings = screen.getAllByRole("heading", { level: 3 })
        const headingIds = headings.map((heading) => heading.id)
        expect(new Set(headingIds).size).toBe(headingIds.length)

        expect(
            container.innerHTML.includes(
                "spellcasting-profile-bard",
            ),
        ).toBe(false)
        expect(
            container.innerHTML.includes(
                "spellcasting-profile-feat",
            ),
        ).toBe(false)
    })

    it("does not put the spellcasting profile id or spell ids in the DOM", () => {
        const { container } = renderPage()

        const profileId =
            characterSheetFixture.spellcasting_profiles[0]
                .character_spellcasting_profile_id

        expect(container.innerHTML.includes(profileId)).toBe(false)

        for (const spell of characterSheetFixture
            .spellcasting_profiles[0].spells) {
            expect(container.innerHTML.includes(spell.spell_id)).toBe(
                false,
            )
        }
    })

    it("renders an empty-build note while preserving character-level facts (sparse Character B)", () => {
        renderPage(sparseCharacterSheetFixture, sparseCharacter)

        expect(
            screen.getByText(
                "No active character build is selected for this timeline.",
            ),
        ).toBeInTheDocument()

        expect(screen.getByText("No active build")).toBeInTheDocument()
        expect(
            screen.getByText("No ability scores recorded."),
        ).toBeInTheDocument()
        expect(screen.getByText("No skills recorded.")).toBeInTheDocument()
        expect(
            screen.getByText("No other proficiencies recorded."),
        ).toBeInTheDocument()
        expect(screen.getByText("No features recorded.")).toBeInTheDocument()
        expect(
            screen.getByText("No spellcasting abilities recorded."),
        ).toBeInTheDocument()

        expect(screen.getByText("Common")).toBeInTheDocument()
        expect(screen.getByText("Darkvision")).toBeInTheDocument()
        expect(screen.getByText("Walk")).toBeInTheDocument()
        expect(screen.getByText("30 ft")).toBeInTheDocument()

        expect(
            screen.getByRole("heading", { level: 1, name: "Sparse Fighter" }),
        ).toBeInTheDocument()
    })
})

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

        expect(screen.getByText("Dragonborn · Medium")).toBeInTheDocument()
        expect(
            screen.getByText("Bard 6 – College of Lore"),
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

    it("shows the primary stat cards including proficiency bonus and movement", () => {
        renderPage()

        expect(screen.getByText("Proficiency bonus")).toBeInTheDocument()
        expect(screen.getByText("+3")).toBeInTheDocument()
        expect(screen.getByText("Walk")).toBeInTheDocument()
        expect(screen.getByText("30 ft")).toBeInTheDocument()
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

    it("shows temporary hit points, exhaustion, and death saves from CharacterDetail", () => {
        renderPage()

        const tempHpCard = screen
            .getByText("Temporary hit points")
            .closest("figure") as HTMLElement
        expect(tempHpCard).toHaveTextContent("5")

        const exhaustionCard = screen
            .getByText("Exhaustion")
            .closest("figure") as HTMLElement
        expect(exhaustionCard).toHaveTextContent("1")

        const deathSavesCard = screen
            .getByText("Death saves")
            .closest("figure") as HTMLElement
        expect(deathSavesCard).toHaveTextContent("2 / 1")
    })

    it("shows zero temporary hit points and exhaustion as valid recorded states", () => {
        renderPage(characterSheetFixture, {
            ...richCharacter,
            temporary_hit_points: 0,
            exhaustion_level: 0,
        })

        const tempHpCard = screen
            .getByText("Temporary hit points")
            .closest("figure") as HTMLElement
        expect(tempHpCard).toHaveTextContent("0")

        const exhaustionCard = screen
            .getByText("Exhaustion")
            .closest("figure") as HTMLElement
        expect(exhaustionCard).toHaveTextContent("0")
    })

    it("shows not-recorded death saves and temp HP when the character detail lacks them", () => {
        renderPage(characterSheetFixture, sparseCharacter)

        const tempHpCard = screen
            .getByText("Temporary hit points")
            .closest("figure") as HTMLElement
        expect(tempHpCard).toHaveTextContent("Not recorded")

        const deathSavesCard = screen
            .getByText("Death saves")
            .closest("figure") as HTMLElement
        expect(deathSavesCard).toHaveTextContent("Not recorded")
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

        const cells = within(historyRow).getAllByRole("cell")
        expect(cells.map((cell) => cell.textContent)).toEqual([
            "History",
            "INT",
            "Expertise",
            "+7",
            "17",
        ])
    })

    it("shows separate panels for other proficiencies, languages, senses, conditions, and resources", () => {
        renderPage()

        expect(
            screen.getByRole("heading", {
                level: 2,
                name: "Other Proficiencies",
            }),
        ).toBeInTheDocument()
        expect(screen.getByText("Lute")).toBeInTheDocument()

        expect(
            screen.getByRole("heading", { level: 2, name: "Languages" }),
        ).toBeInTheDocument()
        expect(screen.getByText("Draconic")).toBeInTheDocument()

        expect(
            screen.getByRole("heading", { level: 2, name: "Senses" }),
        ).toBeInTheDocument()
        expect(screen.getByText("Darkvision")).toBeInTheDocument()
        expect(screen.getByText("60 ft")).toBeInTheDocument()

        expect(
            screen.getByRole("heading", { level: 2, name: "Conditions" }),
        ).toBeInTheDocument()
        expect(screen.getByText("Poisoned")).toBeInTheDocument()
        expect(screen.getByText(/Giant spider bite/)).toBeInTheDocument()

        expect(
            screen.getByRole("heading", { level: 2, name: "Resources" }),
        ).toBeInTheDocument()
        expect(screen.getByText("Inspiration Die")).toBeInTheDocument()
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

        const spellNames = within(levelOneGroup)
            .getAllByRole("listitem")
            .map(
                (item) =>
                    item.querySelector(
                        ".character-sheet__fact-list-primary",
                    )?.textContent,
            )

        expect(spellNames).toEqual(["Zephyr Strike", "Arcane Lock"])
    })

    it("shows known/prepared state explicitly for each spell", () => {
        renderPage()

        const vickedMockeryEntry = screen
            .getByText("Vicious Mockery")
            .closest("li") as HTMLElement
        expect(within(vickedMockeryEntry).getByText("Known")).toBeInTheDocument()
        expect(
            within(vickedMockeryEntry).getByText("Prepared"),
        ).toBeInTheDocument()

        const detectMagicEntry = screen
            .getByText("Detect Magic")
            .closest("li") as HTMLElement
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

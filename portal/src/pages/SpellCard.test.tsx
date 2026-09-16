import { render, screen, within } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { characterSheetFixture } from "../fixtures/characterSheet"
import { SpellCard } from "./SpellCard"

const spell = characterSheetFixture.spellcasting_profiles[0].spells[0]
describe("SpellCard", () => {
    it("exposes cantrip, school, independent state and expanded facts", () => {
        render(<SpellCard spell={{ ...spell, is_known: false, is_prepared: true }} />)
        const summary = screen.getByText(spell.display_name).closest("summary") as HTMLElement
        expect(within(summary).getByText("Cantrip")).toBeInTheDocument()
        expect(within(summary).getByText("Enchantment")).toBeInTheDocument()
        expect(within(summary).getByText("Not known")).toBeInTheDocument()
        expect(within(summary).getByText("Prepared")).toBeInTheDocument()
        expect(summary.closest("details")).toHaveTextContent("Psychic")
        expect(summary.closest("details")).toHaveTextContent(spell.description ?? "")
    })
    it("uses deliberate nullable-field fallbacks", () => {
        render(<SpellCard spell={{ ...spell, level: 2, school: null, casting_time: null,
            range: null, duration: null, damage_type_display_name: null, description: null }} />)
        expect(screen.getByText("Level 2")).toBeInTheDocument()
        expect(screen.getAllByText("Not recorded")).toHaveLength(4)
        expect(screen.getByText("No description recorded.")).toBeInTheDocument()
    })
})

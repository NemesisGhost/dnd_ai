import { render, screen, within } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { AbilityScoreCard } from "./AbilityScoreCard"

describe("AbilityScoreCard", () => {
    it("shows the score and prominent signed modifier", () => {
        render(
            <AbilityScoreCard
                abilityDisplayName="Charisma"
                score={18}
                modifier={4}
                savingThrow={{ bonus: 7, isProficient: true }}
            />,
        )

        const card = screen.getByRole("article", { name: "Charisma" })

        expect(within(card).getByText("+4")).toBeInTheDocument()
        expect(within(card).getByText("Score 18")).toBeInTheDocument()
    })

    it("shows a proficient saving throw with visible text", () => {
        render(
            <AbilityScoreCard
                abilityDisplayName="Dexterity"
                score={14}
                modifier={2}
                savingThrow={{ bonus: 5, isProficient: true }}
            />,
        )

        expect(screen.getByText("+5")).toBeInTheDocument()
        expect(screen.getByText("Proficient")).toBeInTheDocument()
    })

    it("shows a non-proficient saving throw with visible text", () => {
        render(
            <AbilityScoreCard
                abilityDisplayName="Strength"
                score={10}
                modifier={0}
                savingThrow={{ bonus: 0, isProficient: false }}
            />,
        )

        expect(screen.getByText("Not proficient")).toBeInTheDocument()
    })

    it("shows a neutral not-recorded state when no saving throw matches", () => {
        render(
            <AbilityScoreCard
                abilityDisplayName="Wisdom"
                score={11}
                modifier={0}
                savingThrow={null}
            />,
        )

        expect(screen.getByText("Not recorded")).toBeInTheDocument()
        expect(screen.queryByText("Proficient")).not.toBeInTheDocument()
    })

    it("does not put a raw ability id anywhere in the DOM", () => {
        const { container } = render(
            <AbilityScoreCard
                abilityDisplayName="Intelligence"
                score={12}
                modifier={1}
                savingThrow={null}
            />,
        )

        expect(
            container.innerHTML.includes("ability-intelligence"),
        ).toBe(false)
    })
})

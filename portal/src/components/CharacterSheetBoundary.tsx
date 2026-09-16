import type { ReactNode } from "react"
import { useCharacterSheet } from "../hooks/useCharacterSheet"
import PlaceholderPage from "../pages/PlaceholderPage"
import type { CharacterSheet } from "../types/characterSheet"

interface CharacterSheetBoundaryProps {
    campaignId: string
    characterId: string
    children: (sheet: CharacterSheet) => ReactNode
}

export function CharacterSheetBoundary({
    campaignId,
    characterId,
    children,
}: CharacterSheetBoundaryProps) {
    const { state, retry } = useCharacterSheet(
        campaignId,
        characterId,
    )

    if (state.status === "loading") {
        return (
            <PlaceholderPage
                title="Loading character sheet"
                description="Loading the latest authorized character sheet."
            />
        )
    }

    if (state.status === "unavailable") {
        return (
            <PlaceholderPage
                title="Character sheet unavailable"
                description="The requested character sheet is not available."
            />
        )
    }

    if (state.status === "error") {
        return (
            <section
                className="placeholder-page"
                aria-labelledby="character-sheet-error-heading"
            >
                <h1 id="character-sheet-error-heading">
                    Character sheet unavailable
                </h1>

                <p>
                    The portal could not load the character sheet.
                    Try again.
                </p>

                <button
                    type="button"
                    onClick={retry}
                >
                    Try again
                </button>
            </section>
        )
    }

    return <>{children(state.sheet)}</>
}
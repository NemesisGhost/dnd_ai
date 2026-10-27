import type { ReactNode } from "react"
import { useCharacterSheet } from "../hooks/useCharacterSheet"
import PlaceholderPage from "../pages/PlaceholderPage"
import type { CharacterSheet } from "../types/characterSheet"

interface CharacterSheetBoundaryProps {
    campaignId: string
    characterId: string
    children: (sheet: CharacterSheet) => ReactNode
    // What to show when the sheet is not available to this caller (a summary-tier reader gets the
    // same non-disclosing refusal as a missing sheet). Without it, the generic placeholder shows.
    fallback?: () => ReactNode
}

export function CharacterSheetBoundary({
    campaignId,
    characterId,
    children,
    fallback,
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
        if (fallback !== undefined) {
            return <>{fallback()}</>
        }

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
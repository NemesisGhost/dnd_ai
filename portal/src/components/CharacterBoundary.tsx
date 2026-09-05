import type { ReactNode } from "react"
import { useCharacter } from "../hooks/useCharacter"
import type { CharacterDetail } from "../types/character"
import PlaceholderPage from "../pages/PlaceholderPage"

interface CharacterBoundaryProps {
    campaignId: string
    characterId: string
    children: (character: CharacterDetail) => ReactNode
}

export function CharacterBoundary({
    campaignId,
    characterId,
    children,
}: CharacterBoundaryProps) {
    const { state, retry } = useCharacter(
        campaignId,
        characterId,
    )

    if (state.status === "loading") {
        return (
            <PlaceholderPage
                title="Loading character"
                description="Loading the latest authorized character information."
            />
        )
    }

    if (state.status === "unavailable") {
        return (
            <PlaceholderPage
                title="Character unavailable"
                description="The requested character information is not available."
            />
        )
    }

    if (state.status === "error") {
        return (
            <section
                className="placeholder-page"
                aria-labelledby="character-error-heading"
            >
                <h1 id="character-error-heading">
                    Character information unavailable
                </h1>

                <p>
                    The portal could not load the character information.
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

    return <>{children(state.character)}</>
}
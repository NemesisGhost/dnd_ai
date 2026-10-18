import type { ReactNode } from "react"
import { Link, useParams } from "react-router"
import { useCampaignCapability } from "../hooks/useCampaignCapability"
import { CharacterBoundary } from "../components/CharacterBoundary"
import { CharacterSheetBoundary } from "../components/CharacterSheetBoundary"
import { usePerspective } from "../context/CharacterPerspectiveContext"
import { CharacterSheetPage } from "./CharacterSheetPage"
import PlaceholderPage from "./PlaceholderPage"

// The same offer rule as the World's creation links: canon.edit from the
// bootstrap decides what to show, the server re-checks every request. It is
// independent of the selected character, so it is also there with none selected.
function CharactersHeader({ campaignId }: { campaignId: string }) {
    const canCreate = useCampaignCapability(campaignId, "canon.edit")
    if (!canCreate) {
        return null
    }
    return (
        <header className="characters-page__header">
            <nav aria-label="Create character" className="authoring-page__actions-row">
                <Link
                    to={`/app/${encodeURIComponent(campaignId)}/characters/new`}
                    className="authoring-button"
                >
                    New character
                </Link>
            </nav>
        </header>
    )
}

function WithCharactersHeader({
    campaignId,
    children,
}: {
    campaignId: string
    children: ReactNode
}) {
    return (
        <>
            <CharactersHeader campaignId={campaignId} />
            {children}
        </>
    )
}

export function CampaignCharactersPage() {
    const { campaignId } =
        useParams<{ campaignId: string }>()

    const { getSelectedCharacterId } =
        usePerspective()

    if (campaignId === undefined) {
        return (
            <PlaceholderPage
                title="Character unavailable"
                description="The requested character information is not available."
            />
        )
    }

    const characterId =
        getSelectedCharacterId(campaignId)

    if (characterId === null) {
        return (
            <WithCharactersHeader campaignId={campaignId}>
                <PlaceholderPage
                    title="No character selected"
                    description="Select an available character perspective to view character information."
                />
            </WithCharactersHeader>
        )
    }

    return (
        <WithCharactersHeader campaignId={campaignId}>
            <CharacterBoundary
                campaignId={campaignId}
                characterId={characterId}
            >
                {(character) => (
                    <CharacterSheetBoundary
                        campaignId={campaignId}
                        characterId={characterId}
                    >
                        {(sheet) => (
                            <CharacterSheetPage
                                sheet={sheet}
                                character={character}
                            />
                        )}
                    </CharacterSheetBoundary>
                )}
            </CharacterBoundary>
        </WithCharactersHeader>
    )
}

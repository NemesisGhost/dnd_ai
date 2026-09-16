import { useParams } from "react-router"
import { CharacterBoundary } from "../components/CharacterBoundary"
import { CharacterSheetBoundary } from "../components/CharacterSheetBoundary"
import { usePerspective } from "../context/CharacterPerspectiveContext"
import { CharacterSheetPage } from "./CharacterSheetPage"
import PlaceholderPage from "./PlaceholderPage"

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
            <PlaceholderPage
                title="No character selected"
                description="Select an available character perspective to view character information."
            />
        )
    }

    return (
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
    )
}
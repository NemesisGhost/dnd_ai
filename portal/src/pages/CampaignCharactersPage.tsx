import { useParams } from "react-router"
import { CharacterBoundary } from "../components/CharacterBoundary"
import { usePerspective } from "../context/CharacterPerspectiveContext"
import { CharacterDetailPage } from "./CharacterDetailPage"
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
                <CharacterDetailPage
                    character={character}
                />
            )}
        </CharacterBoundary>
    )
}
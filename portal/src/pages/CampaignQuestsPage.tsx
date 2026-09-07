import { useParams } from "react-router"
import { CampaignQuestsBoundary } from "../components/CampaignQuestsBoundary"
import { usePerspective } from "../context/CharacterPerspectiveContext"
import { QuestsPage } from "./QuestsPage"
import PlaceholderPage from "./PlaceholderPage"

export function CampaignQuestsPage() {
    const { campaignId } =
        useParams<{ campaignId: string }>()

    const { getSelectedCharacterId } =
        usePerspective()

    if (campaignId === undefined) {
        return (
            <PlaceholderPage
                title="Quests unavailable"
                description="The requested quest information is not available."
            />
        )
    }

    const characterId =
        getSelectedCharacterId(campaignId)

    return (
        <CampaignQuestsBoundary
            campaignId={campaignId}
            characterId={characterId}
        >
            {(quests) => (
                <QuestsPage
                    quests={quests}
                />
            )}
        </CampaignQuestsBoundary>
    )
}
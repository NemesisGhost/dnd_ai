import { useParams } from "react-router"
import { QuestDetailBoundary } from "../components/QuestDetailBoundary"
import { usePerspective } from "../context/CharacterPerspectiveContext"
import { QuestDetailPage } from "./QuestDetailPage"
import PlaceholderPage from "./PlaceholderPage"

export function CampaignQuestDetailPage() {
    const {
        campaignId,
        questId,
    } = useParams<{
        campaignId: string
        questId: string
    }>()

    const { getSelectedCharacterId } =
        usePerspective()

    if (
        campaignId === undefined ||
        questId === undefined
    ) {
        return (
            <PlaceholderPage
                title="Quest unavailable"
                description="The requested quest information is not available."
            />
        )
    }

    const characterId =
        getSelectedCharacterId(campaignId)

    return (
        <QuestDetailBoundary
            campaignId={campaignId}
            questId={questId}
            characterId={characterId}
        >
            {(quest) => (
                <QuestDetailPage quest={quest} />
            )}
        </QuestDetailBoundary>
    )
}
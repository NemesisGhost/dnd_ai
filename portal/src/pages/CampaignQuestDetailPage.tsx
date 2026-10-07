import { useParams } from "react-router"
import { questAuthoringPath } from "../api/questAuthoring"
import { AuthoringEditLink } from "../components/AuthoringEditLink"
import { QuestDetailBoundary } from "../components/QuestDetailBoundary"
import { useQuestPartyPerspective } from "../hooks/useQuestPartyPerspective"
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

    return <CampaignQuestDetailContent campaignId={campaignId} questId={questId} />
}

// The same (character, party) perspective the quest list used: the party
// pair the list's link carried in the URL, re-validated against the
// currently selected character (see useQuestPartyPerspective).
function CampaignQuestDetailContent({
    campaignId,
    questId,
}: {
    campaignId: string
    questId: string
}) {
    const { characterId, partyId } = useQuestPartyPerspective(campaignId)

    return (
        <QuestDetailBoundary
            campaignId={campaignId}
            questId={questId}
            characterId={characterId}
            partyId={partyId}
        >
            {(quest) => (
                <>
                    <QuestDetailPage campaignId={campaignId} quest={quest} />
                    <AuthoringEditLink
                        campaignId={campaignId}
                        noun="quest"
                        viewPath={questAuthoringPath(campaignId, questId)}
                        editPath={`/app/${encodeURIComponent(campaignId)}/quests/${encodeURIComponent(questId)}/edit`}
                        detail={quest}
                    />
                </>
            )}
        </QuestDetailBoundary>
    )
}
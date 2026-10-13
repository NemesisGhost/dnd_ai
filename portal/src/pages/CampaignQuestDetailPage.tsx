import { useParams } from "react-router"
import { QuestDetailBoundary } from "../components/QuestDetailBoundary"
import { QuestWorkspace } from "../components/quests/QuestWorkspace"
import { useCampaignCapability } from "../hooks/useCampaignCapability"
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

    // Keyed by quest, so nothing read or typed for one quest is ever shown under another.
    return <CampaignQuestDetailRoute key={questId} campaignId={campaignId} questId={questId} />
}

// People who can edit canon get the Quest workspace, which reads the quest through the authoring
// contract and so also opens a draft or a quest no party has started. Everyone else gets the
// audience-filtered reader and sends only the requests it always sent.
function CampaignQuestDetailRoute({
    campaignId,
    questId,
}: {
    campaignId: string
    questId: string
}) {
    const canEdit = useCampaignCapability(campaignId, "canon.edit")
    return canEdit ? (
        <QuestWorkspace campaignId={campaignId} questId={questId} />
    ) : (
        <CampaignQuestReader campaignId={campaignId} questId={questId} />
    )
}

// The same (character, party) perspective the quest list used: the party
// pair the list's link carried in the URL, re-validated against the
// currently selected character (see useQuestPartyPerspective).
function CampaignQuestReader({
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
            {(quest) => <QuestDetailPage campaignId={campaignId} quest={quest} />}
        </QuestDetailBoundary>
    )
}

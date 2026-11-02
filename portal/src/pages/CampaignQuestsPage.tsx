import { useParams } from "react-router"
import { CampaignQuestsBoundary } from "../components/CampaignQuestsBoundary"
import { useQuestPartyPerspective } from "../hooks/useQuestPartyPerspective"
import { QuestsPage } from "./QuestsPage"
import PlaceholderPage from "./PlaceholderPage"

function CampaignQuestsContent({ campaignId }: { campaignId: string }) {
    const { characterId, partyId, parties, partiesUndetermined, selectParty } =
        useQuestPartyPerspective(campaignId)

    return (
        <CampaignQuestsBoundary
            campaignId={campaignId}
            characterId={characterId}
            partyId={partyId}
        >
            {(quests) => (
                <QuestsPage
                    campaignId={campaignId}
                    quests={quests}
                    characterId={characterId}
                    partyId={partyId}
                    parties={parties}
                    partiesUndetermined={partiesUndetermined}
                    onPartyChange={selectParty}
                />
            )}
        </CampaignQuestsBoundary>
    )
}

export function CampaignQuestsPage() {
    const { campaignId } =
        useParams<{ campaignId: string }>()

    if (campaignId === undefined) {
        return (
            <PlaceholderPage
                title="Quests unavailable"
                description="The requested quest information is not available."
            />
        )
    }

    return <CampaignQuestsContent campaignId={campaignId} />
}

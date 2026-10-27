import { useParams } from "react-router"
import { QuestDetailBoundary } from "../components/QuestDetailBoundary"
import { QuestWorkspace } from "../components/quests/QuestWorkspace"
import { QuestProgressPanel } from "../components/quests/QuestProgressPanel"
import { useCampaignCapability } from "../hooks/useCampaignCapability"
import { useHeldWorldCapability, WORLD_CANON_READ_PRIVATE } from "../hooks/useWorldCapability"
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

// People who can edit canon and read the world's private side get the Quest workspace, which reads
// the quest through the authoring contract and so also opens a draft or a quest no party has
// started. A campaign GM with no world role is shown the published quest and the campaign's own
// progress on it (starting, completing, objectives), and nothing of the definition's preparation:
// the workspace's reads would all be refused. Everyone else gets the audience-filtered reader and
// sends only the requests it always sent.
function CampaignQuestDetailRoute({
    campaignId,
    questId,
}: {
    campaignId: string
    questId: string
}) {
    const canEdit = useCampaignCapability(campaignId, "canon.edit")
    const canPrepare = useHeldWorldCapability(campaignId, WORLD_CANON_READ_PRIVATE)
    if (canEdit && canPrepare) {
        return <QuestWorkspace campaignId={campaignId} questId={questId} />
    }
    return <CampaignQuestReader campaignId={campaignId} questId={questId} runs={canEdit} />
}

// The progress panel reports unsent input to a page guard the reader does not have.
const noUnsaved = (): void => undefined

// The same (character, party) perspective the quest list used: the party
// pair the list's link carried in the URL, re-validated against the
// currently selected character (see useQuestPartyPerspective).
function CampaignQuestReader({
    campaignId,
    questId,
    runs = false,
}: {
    campaignId: string
    questId: string
    // The caller runs this campaign (campaign `canon.edit`) but may not prepare the shared quest.
    runs?: boolean
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
                    {runs ? (
                        <section className="authoring-page" aria-label="Quest progress in this campaign">
                            <p className="authoring-note">
                                Preparing, reviewing and publishing this quest belong to the shared world and need a
                                world role; ask the world owner. What happens to it in this campaign is yours to run.
                            </p>
                            <QuestProgressPanel
                                campaignId={campaignId}
                                questId={questId}
                                blockedText={null}
                                refreshToken={0}
                                onUnsaved={noUnsaved}
                            />
                        </section>
                    ) : null}
                </>
            )}
        </QuestDetailBoundary>
    )
}

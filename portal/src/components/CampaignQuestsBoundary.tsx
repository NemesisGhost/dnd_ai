import type { ReactNode } from "react"
import { useCampaignQuests } from "../hooks/useCampaignQuests"
import PlaceholderPage from "../pages/PlaceholderPage"
import type {
    CampaignQuestListItem,
} from "../types/quest"

interface CampaignQuestsBoundaryProps {
    campaignId: string
    characterId: string | null
    children: (
        quests: CampaignQuestListItem[],
    ) => ReactNode
}

export function CampaignQuestsBoundary({
    campaignId,
    characterId,
    children,
}: CampaignQuestsBoundaryProps) {
    const { state, retry } = useCampaignQuests(
        campaignId,
        characterId,
    )

    if (state.status === "loading") {
        return (
            <PlaceholderPage
                title="Loading quests"
                description="Loading the latest authorized quest information."
            />
        )
    }

    if (state.status === "unavailable") {
        return (
            <PlaceholderPage
                title="Quests unavailable"
                description="The requested quest information is not available."
            />
        )
    }

    if (state.status === "error") {
        return (
            <section
                className="placeholder-page"
                aria-labelledby="quests-error-heading"
            >
                <h1 id="quests-error-heading">
                    Quest information unavailable
                </h1>

                <p>
                    The portal could not load the quest information.
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

    return <>{children(state.quests)}</>
}
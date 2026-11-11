import type { ReactNode } from "react"
import { useQuest } from "../hooks/useQuest"
import { useBreadcrumbLabel } from "../navigation/BreadcrumbLabelContext"
import PlaceholderPage from "../pages/PlaceholderPage"
import type {
    QuestDetail,
} from "../types/quest"

interface QuestDetailBoundaryProps {
    campaignId: string
    questId: string
    characterId: string | null
    partyId?: string | null
    children: (
        quest: QuestDetail,
    ) => ReactNode
}

export function QuestDetailBoundary({
    campaignId,
    questId,
    characterId,
    partyId = null,
    children,
}: QuestDetailBoundaryProps) {
    const { state, retry, authority } = useQuest(
        campaignId,
        questId,
        characterId,
        partyId,
    )
    // The quest's name, from this authorized read, for the breadcrumbs of the pages beneath it. An
    // unavailable (403/404) answer drops it; nothing is registered from any other state.
    useBreadcrumbLabel({
        route: "quests.detail",
        params: { campaignId, questId },
        name: state.status === "success" ? state.quest.name : undefined,
        denied: state.status === "unavailable",
        authority,
    })

    if (state.status === "loading") {
        return (
            <PlaceholderPage
                title="Loading quest"
                description="Loading the latest authorized quest information."
            />
        )
    }

    if (state.status === "unavailable") {
        return (
            <PlaceholderPage
                title="Quest unavailable"
                description="The requested quest information is not available."
            />
        )
    }

    if (state.status === "error") {
        return (
            <section
                className="placeholder-page"
                aria-labelledby="quest-error-heading"
            >
                <h1 id="quest-error-heading">
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

    return <>{children(state.quest)}</>
}
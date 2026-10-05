import { useId, useState } from "react"
import { Link } from "react-router"
import { AudiencePreviewSection } from "../components/AudiencePreviewSection"
import { CardGrid } from "../components/CardGrid"
import { QuestCard } from "../components/QuestCard"
import { useCampaignCapability } from "../hooks/useCampaignCapability"
import type { CampaignQuestListItem } from "../types/quest"
import { sortQuests } from "../utils/questSorting"
import type { QuestSortColumn } from "../utils/questSorting"
import type { SortDirection } from "../utils/sorting"

interface QuestsPageProps {
    campaignId: string
    quests: CampaignQuestListItem[]
}

export function QuestsPage({
    campaignId,
    quests,
}: QuestsPageProps) {
    const [sortColumn, setSortColumn] = useState<QuestSortColumn>("name")
    const [direction, setDirection] = useState<SortDirection>("asc")

    const sortColumnId = useId()
    const directionId = useId()
    // Offered from the bootstrap's capability list; the server re-checks.
    const canAuthor = useCampaignCapability(campaignId, "canon.edit")

    const sortedQuests = sortQuests(quests, sortColumn, direction)

    return (
        <section aria-labelledby="quests-heading">
            <h1 id="quests-heading">Quests</h1>

            {canAuthor ? (
                <p className="authoring-page__actions-row">
                    <Link
                        className="authoring-button"
                        to={`/app/${encodeURIComponent(campaignId)}/quests/new`}
                    >
                        New quest
                    </Link>
                </p>
            ) : null}

            <AudiencePreviewSection campaignId={campaignId} resourceType="quest" />

            {quests.length > 0 ? (
                <>
                    <div
                        className="quests-page__sort-controls"
                        role="group"
                        aria-label="Sort quests"
                    >
                        <div className="quests-page__sort-field">
                            <label htmlFor={sortColumnId}>Sort by</label>
                            <select
                                id={sortColumnId}
                                value={sortColumn}
                                onChange={(event) =>
                                    setSortColumn(
                                        event.currentTarget
                                            .value as QuestSortColumn,
                                    )
                                }
                            >
                                <option value="name">Name</option>
                                <option value="status">Status</option>
                            </select>
                        </div>

                        <div className="quests-page__sort-field">
                            <label htmlFor={directionId}>Direction</label>
                            <select
                                id={directionId}
                                value={direction}
                                onChange={(event) =>
                                    setDirection(
                                        event.currentTarget
                                            .value as SortDirection,
                                    )
                                }
                            >
                                <option value="asc">Ascending</option>
                                <option value="desc">Descending</option>
                            </select>
                        </div>
                    </div>

                    <CardGrid ariaLabel="Quests" className="quest-card-grid">
                        {sortedQuests.map((quest) => (
                            <QuestCard
                                key={quest.quest_id}
                                campaignId={campaignId}
                                quest={quest}
                            />
                        ))}
                    </CardGrid>
                </>
            ) : (
                <p>No quests are available for this campaign and perspective.</p>
            )}
        </section>
    )
}

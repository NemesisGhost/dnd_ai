import { useId, useState } from "react"
import { Link } from "react-router"
import { AudiencePreviewSection } from "../components/AudiencePreviewSection"
import { CardGrid } from "../components/CardGrid"
import { QuestCard } from "../components/QuestCard"
import { useCampaignCapability } from "../hooks/useCampaignCapability"
import type { AuthorizedParty } from "../types/bootstrap"
import type { CampaignQuestListItem } from "../types/quest"
import { sortQuests } from "../utils/questSorting"
import type { QuestSortColumn } from "../utils/questSorting"
import type { SortDirection } from "../utils/sorting"

interface QuestsPageProps {
    campaignId: string
    quests: CampaignQuestListItem[]
    characterId?: string | null
    partyId?: string | null
    parties?: AuthorizedParty[]
    onPartyChange?: (partyId: string | null) => void
}

export function QuestsPage({
    campaignId,
    quests,
    characterId = null,
    partyId = null,
    parties = [],
    onPartyChange,
}: QuestsPageProps) {
    const [sortColumn, setSortColumn] = useState<QuestSortColumn>("name")
    const [direction, setDirection] = useState<SortDirection>("asc")

    const sortColumnId = useId()
    const directionId = useId()
    const partySelectId = useId()
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

            {characterId !== null && onPartyChange !== undefined ? (
                // Campaign-wide quests always show; a party adds its own
                // quests and statuses. Only the selected character's
                // authorized parties are offered, and a single one is
                // already selected (see useQuestPartyPerspective).
                <div className="quests-page__sort-field">
                    <label htmlFor={partySelectId}>Party</label>
                    <select
                        id={partySelectId}
                        value={partyId ?? ""}
                        disabled={parties.length < 2}
                        onChange={(event) => {
                            const value = event.currentTarget.value
                            onPartyChange(value === "" ? null : value)
                        }}
                    >
                        {parties.length !== 1 ? (
                            <option value="">
                                {parties.length === 0
                                    ? "No party available"
                                    : "No party selected"}
                            </option>
                        ) : null}
                        {parties.map((party) => (
                            <option key={party.party_id} value={party.party_id}>
                                {party.party_name}
                            </option>
                        ))}
                    </select>
                </div>
            ) : null}

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
                                characterId={characterId}
                                partyId={partyId}
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

import { Link } from "react-router"
import { SortableTable } from "../components/SortableTable"
import type { SortableTableColumn } from "../components/SortableTable"
import type { CampaignQuestListItem } from "../types/quest"
import {
    applyDirection,
} from "../utils/sorting"
import type { SortDirection } from "../utils/sorting"

interface QuestsPageProps {
    quests: CampaignQuestListItem[]
}

function compareStatuses(
    a: CampaignQuestListItem,
    b: CampaignQuestListItem,
    direction: SortDirection,
): number {
    if (
        a.status_code === null &&
        b.status_code === null
    ) {
        return 0
    }

    if (a.status_code === null) {
        return 1
    }

    if (b.status_code === null) {
        return -1
    }

    return applyDirection(
        direction,
        a.status_code.localeCompare(
            b.status_code,
        ),
    )
}

const columns: SortableTableColumn<CampaignQuestListItem>[] = [
    {
        key: "quest_name",
        label: "Name",
        compare: (a, b, direction) =>
            applyDirection(
                direction,
                (a.name).localeCompare(b.name)
            ),
        render: (quest) => (
            <Link to={encodeURIComponent(quest.quest_id)}>{quest.name}</Link>
        ),
    },
    {
        key: "quest_status",
        label: "Status",
        compare: compareStatuses,
        render: (quest) => quest.status_code ?? "No status recorded",
    }
]

export function QuestsPage({
    quests
}: QuestsPageProps) {
    return (
        <section aria-labelledby="quests-heading">
            <h1 id="quests-heading">Quests</h1>
            {quests.length > 0 ? (
                <SortableTable
                    caption="Quests"
                    columns={columns}
                    rows={quests}
                    getRowKey={(quest) => quest.quest_id}
                    initialSort={{ column: "quest_name", direction: "asc" }}
                />
            ) : (
                <p>No quests are available for this campaign and perspective.</p>
            )}
        </section>
    )
}
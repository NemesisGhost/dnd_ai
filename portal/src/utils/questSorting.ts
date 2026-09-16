import type { CampaignQuestListItem } from "../types/quest"
import { applyDirection } from "./sorting"
import type { SortDirection } from "./sorting"

export type QuestSortColumn = "name" | "status"

function compareStatuses(
    a: CampaignQuestListItem,
    b: CampaignQuestListItem,
    direction: SortDirection,
): number {
    // Null status always sorts last, regardless of direction — the
    // established semantics of the table this replaces.
    if (a.status_code === null && b.status_code === null) {
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
        a.status_code.localeCompare(b.status_code),
    )
}

// Sorts a copy of `quests` — never mutates the caller's array/props.
export function sortQuests(
    quests: CampaignQuestListItem[],
    column: QuestSortColumn,
    direction: SortDirection,
): CampaignQuestListItem[] {
    const sorted = [...quests]

    sorted.sort((a, b) =>
        column === "name"
            ? applyDirection(direction, a.name.localeCompare(b.name))
            : compareStatuses(a, b, direction),
    )

    return sorted
}

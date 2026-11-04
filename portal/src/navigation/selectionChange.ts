import { isIdShaped } from "./contexts"

// The note a deliberate Infobox selection puts on the navigation it asks for (docs/UI_DESIGN.md §4.8.4).
// It says which level the person chose and which id; nothing else. It is ids only (no labels, no names),
// it is not authority, and nothing consults it to decide what is allowed: the departure blocker, the
// task and the context stamp decide that. It only lets the one owner of selection arrivals
// (SelectionArrivalProvider) announce and focus the change once the navigation is accepted and the
// selection is committed. A name is looked up then, from what the person may read at that moment.

export type SelectionLevel = "campaign" | "world" | "timeline" | "character"

export interface SelectionChange {
    level: SelectionLevel
    // The chosen campaign, world, timeline or character. `null` only for the explicit choice of no
    // character perspective.
    id: string | null
    // The campaign a character perspective belongs to.
    campaignId?: string
}

const LEVELS: readonly SelectionLevel[] = ["campaign", "world", "timeline", "character"]

function own(record: Record<string, unknown>, key: string): unknown {
    return Object.prototype.hasOwnProperty.call(record, key) ? record[key] : undefined
}

/** The selection a navigation state carries, or null when it carries none or anything malformed. */
export function readSelectionChange(state: unknown): SelectionChange | null {
    if (typeof state !== "object" || state === null) return null
    const raw = own(state as Record<string, unknown>, "selection")
    if (typeof raw !== "object" || raw === null) return null
    const record = raw as Record<string, unknown>
    const level = own(record, "level")
    const id = own(record, "id")
    const campaignId = own(record, "campaignId")
    if (!LEVELS.includes(level as SelectionLevel)) return null
    if (id === null) {
        if (level !== "character") return null
    } else if (!isIdShaped(id)) {
        return null
    }
    if (level === "character") {
        if (!isIdShaped(campaignId)) return null
        return { level: "character", id: id as string | null, campaignId }
    }
    return { level: level as SelectionLevel, id: id as string }
}

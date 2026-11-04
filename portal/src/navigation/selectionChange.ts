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

/**
 * The route scope an accepted selection lands in: the campaign or world its address names. Only the
 * ids the address itself carries, not authority.
 */
export interface SelectionScope {
    campaignId: string | null
    worldId: string | null
}

const SEGMENT = "([A-Za-z0-9_-]{1,64})"
const CAMPAIGN_HOME = new RegExp(`^/app/${SEGMENT}/home$`)
const CAMPAIGN_CHARACTER = new RegExp(`^/app/${SEGMENT}/characters/${SEGMENT}$`)
const CAMPAIGN_WORLD = new RegExp(`^/app/${SEGMENT}/world$`)
const WORLD_DETAILS = new RegExp(`^/worlds/${SEGMENT}$`)
const WORLD_TIMELINE = new RegExp(`^/worlds/${SEGMENT}/timelines/${SEGMENT}$`)

/**
 * The scope of the destination a selection note is allowed to ride on, or null when the note does not
 * belong to the address it arrived at. The destinations are exactly the ones the controls ask for
 * (navigation/selectionTransitions.ts and the Infobox/Navbar callers), so a well-formed note on any other
 * route (a stray, copied or forged state) is not an arrival:
 *
 *   campaign    /app/:id/home
 *   world       /worlds/:id, or /app/:c/world (a world the person may open only through a campaign of it)
 *   timeline    /worlds/:w/timelines/:id
 *   character   /app/:campaignId/characters/:id, or /app/:campaignId/characters/all for none
 */
export function selectionScope(change: SelectionChange, pathname: string): SelectionScope | null {
    switch (change.level) {
        case "campaign": {
            const match = CAMPAIGN_HOME.exec(pathname)
            return match !== null && match[1] === change.id ? { campaignId: match[1], worldId: null } : null
        }
        case "world": {
            const direct = WORLD_DETAILS.exec(pathname)
            if (direct !== null) return direct[1] === change.id ? { campaignId: null, worldId: direct[1] } : null
            const viaCampaign = CAMPAIGN_WORLD.exec(pathname)
            return viaCampaign === null ? null : { campaignId: viaCampaign[1], worldId: change.id }
        }
        case "timeline": {
            const match = WORLD_TIMELINE.exec(pathname)
            return match !== null && match[2] === change.id ? { campaignId: null, worldId: match[1] } : null
        }
        case "character": {
            const match = CAMPAIGN_CHARACTER.exec(pathname)
            if (match === null || match[1] !== change.campaignId) return null
            const wanted = change.id === null ? "all" : change.id
            if (match[2] !== wanted || (change.id !== null && change.id === "all")) return null
            return { campaignId: match[1], worldId: null }
        }
    }
}

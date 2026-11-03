import { entryContextStamp } from "./contexts"
import type { EntryContextV1, SelectedContext } from "./contexts"
import { navTaskState } from "./navStart"
import type { NavRoot } from "./routeMeta"
import type { TaskOriginV1 } from "./taskOrigin"

// What a deliberate Infobox selection asks the router for (docs/UI_DESIGN.md §4.8.4, plan §4.2, PD-6).
// A selection is a departure like any other link: it hands the router one destination with the task and
// context it would start, and writes nothing else. The existing departure blocker decides first; the
// selection, the task and the entry are committed from the accepted location, never ahead of it. Pure:
// no router, store or network is read here, and the destination is built only from the ids the person
// chose (never from the record on screen, and never from null: a cleared perspective has its own address).

export interface SelectionRequest {
    to: string
    state: { task?: TaskOriginV1; ctx?: EntryContextV1 }
}

/**
 * The character perspective the person chose, or none. A character opens that character's details and
 * starts a Characters task; none opens the Characters browser (`/characters/all`) with the same task root.
 * Nothing of the page left is carried: not its query, hash, task, list state or any other router state.
 */
export function perspectiveRequest(
    campaignId: string,
    characterId: string | null,
    context: Omit<SelectedContext, "characterId">,
): SelectionRequest {
    const base = `/app/${encodeURIComponent(campaignId)}/characters`
    const to = characterId === null ? `${base}/all` : `${base}/${encodeURIComponent(characterId)}`
    return {
        to,
        state: { ...navTaskState(to, "characters"), ctx: entryContextStamp({ ...context, characterId }) },
    }
}

/**
 * A campaign, world or timeline the person chose: the destination the control already opens, with a new
 * task rooted at the corresponding Navbar section. The selection itself follows the route that is accepted
 * (the route scope governs, UI_DESIGN §4.8.2).
 */
export function scopeRequest(to: string, root: Extract<NavRoot, "campaign" | "world">): SelectionRequest {
    return { to, state: { ...navTaskState(to, root) } }
}

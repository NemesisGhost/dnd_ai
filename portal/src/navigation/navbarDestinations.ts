import type { CampaignContext } from "../types/bootstrap"
import type { SelectedContextState } from "./selectedContextStore"
import { matchRouteMeta } from "./routeMeta"
import type { NavRoot } from "./routeMeta"

// What the Campaign, World and Characters Navbar controls do when activated (docs/UI_DESIGN.md §4.8.3,
// plan §4.1). Pure functions of already-validated inputs: nothing here reads the router, the store or
// the network, and nothing infers a selection. A destination is built only from the person's explicit
// selection (or, on a campaign route, the route's own scope), never from the record being viewed and
// never from a last-visited, startup or sole-campaign guess.

export type PrimaryAction =
    // The main control is a link to the selected context's default details. Following it starts a task
    // whose root is `root`. `detail` completes the accessible name after the visible label
    // ("Characters: open ‹detail›").
    | { kind: "link"; to: string; root: NavRoot; detail: string }
    // The main control is a button that toggles the menu, and never navigates:
    //   none           nothing applicable is selected (or it cannot be opened from here);
    //   at-destination the page shown already is the default details.
    | { kind: "button"; reason: "none" | "at-destination" }

interface Situation {
    pathname: string
}

function trimmed(pathname: string): string {
    return pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname
}

/**
 * Whether the page shown is the destination, by route and parameters rather than by string prefix: the
 * same route with the same ids, whatever its query or hash (a section or filter of the page it is on). A
 * deeper or different route (an edit page, another record) is a different destination.
 */
export function isSameDestination(currentPathname: string, destinationPathname: string): boolean {
    const current = matchRouteMeta(trimmed(currentPathname))
    const destination = matchRouteMeta(trimmed(destinationPathname))
    // The catch-all (not found) is not one destination: every unknown address would equal every other.
    if (current === null || destination === null || current.meta.pattern === "*" || destination.meta.pattern === "*") {
        return trimmed(currentPathname) === trimmed(destinationPathname)
    }
    if (current.meta.id !== destination.meta.id) return false
    const names = Object.keys(destination.params)
    return (
        names.length === Object.keys(current.params).length &&
        names.every((name) => current.params[name] === destination.params[name])
    )
}

// A destination that exists and is not the page shown is a link, whatever task the person is in: being in
// the section is not a reason to withhold the way to the selected record. Otherwise the control expands the menu.
function decide(situation: Situation, section: NavRoot, target: { to: string; detail: string } | null): PrimaryAction {
    if (target === null) return { kind: "button", reason: "none" }
    if (isSameDestination(situation.pathname, target.to)) return { kind: "button", reason: "at-destination" }
    return { kind: "link", to: target.to, root: section, detail: target.detail }
}

/** Campaign: the resolved campaign's Home. */
export function campaignAction(campaign: CampaignContext | null, situation: Situation): PrimaryAction {
    return decide(
        situation,
        "campaign",
        campaign === null ? null : { to: `/app/${campaign.campaign_id}/home`, detail: campaign.campaign_name },
    )
}

/**
 * The perspective character the Characters control may open: the explicit choice for this campaign; none
 * when the person chose none; the bootstrap's own default only while no choice has been made for it. A
 * character the bootstrap no longer lists for the campaign is not a selection.
 */
export function selectedCharacter(
    campaign: CampaignContext | null,
    selection: SelectedContextState,
): { characterId: string; name: string } | null {
    if (campaign === null) return null
    const choice =
        selection.campaignId === campaign.campaign_id && selection.characterId !== undefined
            ? selection.characterId
            : campaign.selected_character_id
    if (choice === null) return null
    const character = campaign.character_perspectives.find((candidate) => candidate.character_id === choice)
    return character === undefined ? null : { characterId: character.character_id, name: character.character_name }
}

/** Characters: the selected character's record shell in the resolved campaign. */
export function charactersAction(
    campaign: CampaignContext | null,
    character: { characterId: string; name: string } | null,
    situation: Situation,
): PrimaryAction {
    return decide(
        situation,
        "characters",
        campaign === null || character === null
            ? null
            : { to: `/app/${campaign.campaign_id}/characters/${character.characterId}`, detail: character.name },
    )
}

/**
 * World: the selected world's details when the caller is known to be able to view it
 * (`/worlds/:w`, PD-3), otherwise the campaign's own world page when a campaign of that world resolves.
 * With neither, the world's details are not offered rather than guessed.
 */
export function worldAction(
    world: { worldId: string; name: string | null; canView: boolean; campaignId: string | null } | null,
    situation: Situation,
): PrimaryAction {
    if (world === null) return decide(situation, "world", null)
    const detail = world.name ?? "selected world"
    if (world.canView) return decide(situation, "world", { to: `/worlds/${world.worldId}`, detail })
    if (world.campaignId !== null) {
        return decide(situation, "world", { to: `/app/${world.campaignId}/world`, detail })
    }
    return decide(situation, "world", null)
}

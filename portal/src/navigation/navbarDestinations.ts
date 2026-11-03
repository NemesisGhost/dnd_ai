import type { CampaignContext } from "../types/bootstrap"
import type { SelectedContextState } from "./selectedContextStore"
import type { NavRoot } from "./routeMeta"

// What the Campaign, World and Characters Navbar controls do when activated (docs/UI_DESIGN.md §4,
// plan §4.1). Pure functions of already-validated inputs: nothing here reads the router, the store or
// the network, and nothing infers a selection. A destination is built only from the person's explicit
// selection (or, on a campaign route, the route's own scope), never from the record being viewed and
// never from a last-visited, startup or sole-campaign guess.

export type PrimaryAction =
    // The main control is a link to the selected context's default details. Following it starts a task
    // whose root is `root`.
    | { kind: "link"; to: string; root: NavRoot; name: string }
    // The main control is a button that toggles the menu, and never navigates:
    //   none           nothing applicable is selected (or it cannot be opened from here);
    //   in-section     the current task already belongs to this section;
    //   at-destination the page shown already is the default details.
    | { kind: "button"; reason: "none" | "in-section" | "at-destination" }

interface Situation {
    pathname: string
    // The root of the task the current page belongs to; null on a page that is no task page.
    currentRoot: NavRoot | null
}

function same(left: string, right: string): boolean {
    const trim = (value: string) => (value.length > 1 ? value.replace(/\/+$/, "") : value)
    return trim(left) === trim(right)
}

function decide(
    situation: Situation,
    section: NavRoot,
    target: { to: string; name: string } | null,
): PrimaryAction {
    if (target === null) return { kind: "button", reason: "none" }
    if (same(situation.pathname, target.to)) return { kind: "button", reason: "at-destination" }
    if (situation.currentRoot === section) return { kind: "button", reason: "in-section" }
    return { kind: "link", to: target.to, root: section, name: target.name }
}

/** Campaign: the resolved campaign's Home. */
export function campaignAction(campaign: CampaignContext | null, situation: Situation): PrimaryAction {
    return decide(
        situation,
        "campaign",
        campaign === null
            ? null
            : { to: `/app/${campaign.campaign_id}/home`, name: `Open campaign ${campaign.campaign_name}` },
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
            : {
                  to: `/app/${campaign.campaign_id}/characters/${character.characterId}`,
                  name: `Open character ${character.name}`,
              },
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
    const name = world.name === null ? "Open selected world" : `Open world ${world.name}`
    if (world.canView) return decide(situation, "world", { to: `/worlds/${world.worldId}`, name })
    if (world.campaignId !== null) {
        return decide(situation, "world", { to: `/app/${world.campaignId}/world`, name })
    }
    return decide(situation, "world", null)
}

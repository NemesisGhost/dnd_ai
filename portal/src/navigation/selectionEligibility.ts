import type { SessionBootstrap } from "../types/bootstrap"
import type { SelectionArrival } from "./selectionArrival"
import type { SelectedContextState } from "./selectedContextStore"

// Whether an accepted selection arrival may speak and move focus yet: the committed selection must be the
// one the person chose AND agree with the scope of the route the choice arrived at (docs/UI_DESIGN.md
// §4.8.4). One predicate for both, so an announcement and a heading focus can never disagree about what
// happened. It reads nothing but the arrival's ids, the committed selection and the session's own lists;
// whether a name is readable only changes the wording, never the eligibility.
export function contextEligible(
    arrival: SelectionArrival,
    selection: SelectedContextState,
    bootstrap: SessionBootstrap,
): boolean {
    const { change, scope } = arrival
    switch (change.level) {
        case "campaign":
            return selection.campaignId === change.id
        case "world": {
            if (selection.worldId !== change.id) return false
            if (scope.campaignId === null) return true
            // A world opened through a campaign of it: that campaign must be in the person's session, be in
            // this world, and be the selected campaign.
            const through = bootstrap.campaigns.find((campaign) => campaign.campaign_id === scope.campaignId)
            return through?.world_id === change.id && selection.campaignId === scope.campaignId
        }
        case "timeline":
            return selection.timelineId === change.id && selection.worldId === scope.worldId
        case "character":
            return selection.campaignId === change.campaignId && selection.characterId === change.id
    }
}

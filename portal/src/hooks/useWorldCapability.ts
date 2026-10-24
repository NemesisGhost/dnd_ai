import { useContext } from "react"
import { SessionContext } from "../context/SessionContext"

// Whether the caller holds `capability` on the *world* of the campaign
// (docs/adr/0020-scoped-system-world-and-campaign-roles.md): independent of the
// campaign capabilities. Shared canon belongs to the world, so a campaign GM with no
// world role may run their game but is shown the authoring screens read-only.
//
// Reads the bootstrap's server-computed `world_capabilities`. When the field is absent
// nothing is hidden: the server decides. This only decides what to *offer*.
export function useWorldCapability(campaignId: string | undefined, capability: string): boolean {
    const state = useContext(SessionContext)?.state
    if (state?.status !== "authenticated") {
        return false
    }
    const worldCapabilities = state.bootstrap.campaigns.find(
        (c) => c.campaign_id === campaignId,
    )?.world_capabilities
    // No list to consult (an older bootstrap, or a page rendered outside a campaign the
    // bootstrap names): offer, and let the server answer 403 `world_authority_required`.
    return worldCapabilities === undefined ? true : worldCapabilities.includes(capability)
}

export const WORLD_CANON_EDIT = "world.canon.edit"
export const WORLD_CANON_REVIEW = "world.canon.review"

// The world capability a lifecycle action needs: preparing and withdrawing a draft is
// editing; approving, rejecting, publishing, superseding, archiving and restoring are
// reviewing. Player characters and item instances are campaign-originated records and
// need no world capability.
const CAMPAIGN_ORIGINATED_TYPES = new Set(["player_character", "item_instance"])
const EDIT_ACTIONS = new Set(["submit_for_review", "return_to_draft", "delete_draft"])

export function lifecycleActionNeeds(action: string, entityTypeCode: string): string | null {
    if (CAMPAIGN_ORIGINATED_TYPES.has(entityTypeCode)) {
        return null
    }
    return EDIT_ACTIONS.has(action) ? WORLD_CANON_EDIT : WORLD_CANON_REVIEW
}

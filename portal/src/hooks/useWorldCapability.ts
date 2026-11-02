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

// Whether the bootstrap says the caller holds `capability` on the campaign's world. Unlike
// `useWorldCapability` it fails closed: with no list to consult it answers false. Use it to decide
// whether to *send a request* (a read of the world's private side), never to decide what to offer.
export function useHeldWorldCapability(campaignId: string | undefined, capability: string): boolean {
    const state = useContext(SessionContext)?.state
    if (state?.status !== "authenticated") {
        return false
    }
    const worldCapabilities = state.bootstrap.campaigns.find(
        (c) => c.campaign_id === campaignId,
    )?.world_capabilities
    return worldCapabilities?.includes(capability) ?? false
}

export const WORLD_CANON_EDIT = "world.canon.edit"
export const WORLD_CANON_REVIEW = "world.canon.review"
export const WORLD_CANON_READ_PRIVATE = "world.canon.read_private"

import { useContext } from "react"
import { SessionContext } from "../context/SessionContext"

// Whether the bootstrap lists `capability` for the campaign. Reads the session
// tolerantly (false outside a provider) because the callers are optional
// extras on pages that must keep working without one. This only decides what
// to *offer*; the server re-checks on every request.
export function useCampaignCapability(campaignId: string | undefined, capability: string): boolean {
    const state = useContext(SessionContext)?.state
    return (
        state?.status === "authenticated" &&
        state.bootstrap.campaigns
            .find((campaign) => campaign.campaign_id === campaignId)
            ?.capabilities.includes(capability) === true
    )
}

import type { SessionBootstrapState } from "../hooks/useSessionBootstrap"
import type { AuthorizedParty } from "../types/bootstrap"

// The authorized-party list lives on the selected character's perspective
// in the session bootstrap, not on any resource API — a character can only
// take the perspective of a party the server already says it may
// (`dnd_ai.api.access.resolve_party_perspective` accepts exactly these
// pairs). It is a hint for what to offer, never a grant: the server
// re-authorizes the (character_id, party_id) pair on every request.
export function resolveAuthorizedParties(
    sessionState: SessionBootstrapState,
    campaignId: string,
    characterId: string | null,
): AuthorizedParty[] {
    if (sessionState.status !== "authenticated" || characterId === null) {
        return []
    }

    const campaign = sessionState.bootstrap.campaigns.find(
        (candidate) => candidate.campaign_id === campaignId,
    )

    if (campaign === undefined) {
        return []
    }

    const character = campaign.character_perspectives.find(
        (candidate) => candidate.character_id === characterId,
    )

    return character?.authorized_parties ?? []
}

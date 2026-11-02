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

// True only when the server said, for this campaign's own bootstrap entry, that it has no
// effective clock (`current_time_set === false`), so party membership is undetermined and an empty
// `authorized_parties` does not mean "no parties". A payload that omits the field (an older server
// or fixture) is unknown, not proof of a missing clock: it is treated as set, so the ordinary
// "No party available" wording stays. Never read another campaign's entry or a global flag.
export function partyMembershipUndetermined(
    sessionState: SessionBootstrapState,
    campaignId: string,
): boolean {
    if (sessionState.status !== "authenticated") return false
    return (
        sessionState.bootstrap.campaigns.find((campaign) => campaign.campaign_id === campaignId)
            ?.current_time_set === false
    )
}

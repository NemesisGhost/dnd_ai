import type { GrantRevealDelegationBody, GrantRevealDelegationReceipt, RevokeRevealDelegationReceipt } from "../types/revealDelegations"
import { apiRequest } from "./http"

// The reveal-delegation read and its two writes. Only the Access section's Reveal authority page calls anything
// under this path.
const enc = encodeURIComponent

export const revealDelegationsPath = (campaignId: string): string =>
    `/campaigns/${enc(campaignId)}/reveal-delegations`

// What the two writes are given. There is deliberately no idempotency key: the server ignores the header (a repeat
// re-executes against the current state and does not replay the first outcome), so sending one would suggest a
// protection that does not exist.
export interface RevealDelegationWriteContext {
    csrfToken: string
    signal?: AbortSignal
}

export function grantRevealDelegation(
    campaignId: string,
    body: GrantRevealDelegationBody,
    ctx: RevealDelegationWriteContext,
): Promise<GrantRevealDelegationReceipt> {
    return apiRequest<GrantRevealDelegationReceipt>("POST", revealDelegationsPath(campaignId), {
        body,
        csrfToken: ctx.csrfToken,
        signal: ctx.signal,
    })
}

export function revokeRevealDelegation(
    campaignId: string,
    granteeCampaignMembershipId: string,
    reason: string,
    ctx: RevealDelegationWriteContext,
): Promise<RevokeRevealDelegationReceipt> {
    return apiRequest<RevokeRevealDelegationReceipt>(
        "POST",
        `${revealDelegationsPath(campaignId)}/${enc(granteeCampaignMembershipId)}/revoke`,
        { body: { reason }, csrfToken: ctx.csrfToken, signal: ctx.signal },
    )
}

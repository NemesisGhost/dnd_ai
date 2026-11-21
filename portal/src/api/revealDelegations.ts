// The reveal-delegation read. Only the Access section's Reveal authority page calls anything under this path.
const enc = encodeURIComponent

export const revealDelegationsPath = (campaignId: string): string =>
    `/campaigns/${enc(campaignId)}/reveal-delegations`

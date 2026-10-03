// Builds the shareable single-link onboarding URL a campaign manager
// copies from InvitationsSection. Built from window.location.origin,
// never a forwarded/host header value -- correct today (the portal and
// API share one origin behind the Vite dev proxy) and correct behind a
// future same-origin reverse proxy, with no configuration key
// (PHASE13E_REMAINING_IMPLEMENTATION_PLAN.md §5.6/§8.2).
export function buildInvitationOnboardingLink(rawInvitationToken: string): string {
    return `${window.location.origin}/campaign-invitations/accept#token=${encodeURIComponent(rawInvitationToken)}`
}

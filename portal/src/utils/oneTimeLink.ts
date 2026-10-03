// Shared fragment-link builder for every one-time secret the admin
// accounts page hands off (activation, password reset) — built from
// window.location.origin, never a forwarded host, mirroring
// invitationLink.ts's identical reasoning for the same reason.
export function buildFragmentLink(path: string, rawToken: string): string {
    return `${window.location.origin}${path}#token=${encodeURIComponent(rawToken)}`
}

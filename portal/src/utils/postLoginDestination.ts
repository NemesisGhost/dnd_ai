// Safe deep-link continuation after login (navigation plan §2.4). Accepts
// only a same-origin, allowlisted portal path carried in router history
// state — never the URL — and falls back to the ordinary landing page for
// anything else. The destination re-authorizes on arrival (the
// authenticated-shell boundary, CampaignLayout's lookup, page-level
// gates, and the server), so this allowlist is a UX convenience, not a
// security boundary of its own.
const DEFAULT_DESTINATION = "/home"
const MAX_FROM_LENGTH = 2048

// home, campaigns, settings, account, platform/accounts, or any app/:campaignId
// route (including its subsections). Deliberately excludes /login and
// every other public route, which would otherwise create a redirect
// loop or leak a return path into an unrelated flow.
const ALLOWED_PATH_PATTERN =
    /^\/(home|campaigns|settings|account|platform\/accounts|app\/[^/]+(\/.*)?)$/

function hasControlCharacter(value: string): boolean {
    for (let index = 0; index < value.length; index += 1) {
        const code = value.charCodeAt(index)
        if (code <= 0x1f || code === 0x7f) {
            return true
        }
    }
    return false
}

export function resolvePostLoginDestination(state: unknown): string {
    if (
        state === null ||
        typeof state !== "object" ||
        !("from" in state)
    ) {
        return DEFAULT_DESTINATION
    }

    const { from } = state as { from: unknown }

    if (typeof from !== "string") {
        return DEFAULT_DESTINATION
    }

    if (from.length === 0 || from.length > MAX_FROM_LENGTH) {
        return DEFAULT_DESTINATION
    }

    if (!from.startsWith("/") || from.startsWith("//")) {
        return DEFAULT_DESTINATION
    }

    if (from.includes("\\") || hasControlCharacter(from)) {
        return DEFAULT_DESTINATION
    }

    let url: URL

    try {
        url = new URL(from, window.location.origin)
    } catch {
        return DEFAULT_DESTINATION
    }

    if (url.origin !== window.location.origin) {
        return DEFAULT_DESTINATION
    }

    if (!ALLOWED_PATH_PATTERN.test(url.pathname)) {
        return DEFAULT_DESTINATION
    }

    return `${url.pathname}${url.search}`
}

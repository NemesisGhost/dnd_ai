const _HASH_TOKEN_PREFIX = "#token="

// Captures a one-time token from the URL fragment. The fragment is removed
// from the address bar and history BEFORE the value is decoded, so a
// malformed encoding still leaves nothing behind. Returns null for a missing,
// empty, or malformed token -- callers treat all three as the same generic
// invalid-link state and must not issue a request.
export function captureFragmentToken(): string | null {
    const hash = window.location.hash
    if (hash === "") {
        return null
    }
    window.history.replaceState(null, "", window.location.pathname + window.location.search)
    if (!hash.startsWith(_HASH_TOKEN_PREFIX)) {
        return null
    }
    try {
        const token = decodeURIComponent(hash.slice(_HASH_TOKEN_PREFIX.length))
        return token === "" ? null : token
    } catch {
        return null
    }
}

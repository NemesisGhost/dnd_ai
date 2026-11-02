// The router-state plumbing the World, Items and Review "back to where you were" links share. A
// return address rides along as router state, never as something the page decides from the URL, and
// every reader here accepts only the shape it expects, so a crafted state cannot send the person
// anywhere else. What each domain carries (and where Back leads) stays in its own hook.

// A query string carried in router state, or undefined. Only a string that starts with "?" is
// honoured.
export function readQueryState(state: unknown, key: string): string | undefined {
    const value = (state as Record<string, unknown> | null | undefined)?.[key]
    return typeof value === "string" && value.startsWith("?") ? value : undefined
}

// The valid return keys of a location state, for forwarding through in-page links; undefined when
// there are none.
export function pickQueryStates<K extends string>(
    state: unknown,
    keys: readonly K[],
): Partial<Record<K, string>> | undefined {
    const picked: Partial<Record<K, string>> = {}
    for (const key of keys) {
        const value = readQueryState(state, key)
        if (value !== undefined) picked[key] = value
    }
    return Object.keys(picked).length === 0 ? undefined : picked
}

// Where an edit page's links lead back to: the address named by `returnTo` in the router state,
// only when it is one of `allowed` (the record's own pages, computed from the route and never taken
// from the state), with its query when that is a query. Anything else is `fallback`.
export function resolveReturnTo(state: unknown, allowed: readonly string[], fallback: string): string {
    const requested = (state as { returnTo?: { pathname?: unknown; search?: unknown } } | null | undefined)?.returnTo
    const pathname = typeof requested?.pathname === "string" ? requested.pathname : null
    if (pathname === null || !allowed.includes(pathname)) return fallback
    const search = typeof requested?.search === "string" && requested.search.startsWith("?") ? requested.search : ""
    return `${pathname}${search}`
}

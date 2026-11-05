// The router-state plumbing for the page's own Back target (`returnTo`) and for the legacy adapter's
// older query keys. A return address rides along as router state, never as something the page decides
// from the URL, and every reader here accepts only the shape it expects, so a crafted state cannot
// send the person anywhere else. Where a list was left is the task's list state (navigation/taskReturn).

// A query string carried in router state, or undefined. Only a string that starts with "?" is
// honoured.
export function readQueryState(state: unknown, key: string): string | undefined {
    const value = (state as Record<string, unknown> | null | undefined)?.[key]
    return typeof value === "string" && value.startsWith("?") ? value : undefined
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

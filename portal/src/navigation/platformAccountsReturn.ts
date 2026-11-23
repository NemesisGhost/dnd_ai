// The platform accounts list's address and the creation route's way back to it (docs/reference/portal-behavior.md
// §4.4). Platform Users is an unscoped page with no task model (portal-navigation §4.8.10), so the return is a
// page-local key with its own validator rather than a task origin. The only things that can come back are the
// list's pathname and a bounded `q`: no `returnTo` address is ever read, and the destination is always built
// from the constant path below plus a search this module rebuilt itself.

export const ACCOUNTS_LIST_PATH = "/platform/accounts"
export const ACCOUNTS_NEW_PATH = "/platform/accounts/new"

const MAX_QUERY_LENGTH = 200
const MAX_RETURN_LENGTH = 1024

// U+0000–U+001F and U+007F.
// eslint-disable-next-line no-control-regex
const CONTROL_CHARACTER = /[\u0000-\u001f\u007f]/

export function isValidAccountsQuery(query: string): boolean {
    return query.length <= MAX_QUERY_LENGTH && !CONTROL_CHARACTER.test(query)
}

// The list's search from its address: accepted only when bounded and free of control characters; anything else
// is an empty search and is never echoed.
export function readAccountsQuery(params: URLSearchParams): string {
    const query = params.get("q") ?? ""
    return isValidAccountsQuery(query) ? query : ""
}

// "" or "?q=…" for a search.
export function accountsSearch(query: string): string {
    return query === "" ? "" : `?${new URLSearchParams({ q: query }).toString()}`
}

// The router state the list's Create account link carries.
export interface AccountsReturnState {
    accountsReturn: string
}

export function accountsReturnState(query: string): AccountsReturnState {
    return { accountsReturn: accountsSearch(query) }
}

// What the creation route may return to: "" or a search that parses to exactly one `q` passing the rule above.
// Rebuilt from the parsed value, so nothing the state held is echoed as written.
export function readAccountsReturn(state: unknown): string {
    if (typeof state !== "object" || state === null) {
        return ""
    }
    const value = (state as { accountsReturn?: unknown }).accountsReturn
    if (typeof value !== "string" || value === "" || value.length > MAX_RETURN_LENGTH || !value.startsWith("?")) {
        return ""
    }
    if (CONTROL_CHARACTER.test(value)) {
        return ""
    }
    const entries = [...new URLSearchParams(value.slice(1)).entries()]
    if (entries.length !== 1 || entries[0]![0] !== "q") {
        return ""
    }
    const query = entries[0]![1]
    return isValidAccountsQuery(query) ? accountsSearch(query) : ""
}

// The list takes focus on its Create account link only for a PUSH arrival that carries this marker.
export const ACCOUNTS_FOCUS_STATE = { accountsFocus: "create" } as const

export function readAccountsFocus(state: unknown): boolean {
    return (
        typeof state === "object" &&
        state !== null &&
        (state as { accountsFocus?: unknown }).accountsFocus === "create"
    )
}

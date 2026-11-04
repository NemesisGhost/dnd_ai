import { readEntryContext } from "./contexts"

// What makes a REPLACE the *context stamp* of the entry it replaces (docs/UI_DESIGN.md §4.8.4), judged
// from the two entries alone. The selected-context owners write a stamp with navigation/replaceOwnEntry:
// the same address, the entry's own state carried over, and only `ctx` written. So a stamp is:
//
//   - the same path and hash, and the same query (optionally but for the `section` a staged record page
//     writes for itself);
//   - the same state except `ctx`, key for key, value for value;
//   - and it carries a well-formed `ctx` (a stamp always does; a distinct operation that replaces the
//     same address, with whatever state it brings, does not).
//
// That last point is what tells a stamp from a second, distinct operation that happens to repeat the
// same state, message included. Nothing here holds a name or a label.

export interface StampedEntry {
    pathname: string
    search: string
    hash: string
    state: unknown
}

function plain(value: unknown): Record<string, unknown> {
    return typeof value === "object" && value !== null ? (value as Record<string, unknown>) : {}
}

function sameSearch(a: string, b: string, tolerateSection: boolean): boolean {
    if (a === b) return true
    if (!tolerateSection) return false
    const left = new URLSearchParams(a)
    const right = new URLSearchParams(b)
    left.delete("section")
    right.delete("section")
    left.sort()
    right.sort()
    return left.toString() === right.toString()
}

function withoutCtx(state: unknown): Record<string, unknown> {
    return Object.fromEntries(Object.entries(plain(state)).filter(([key]) => key !== "ctx"))
}

function sameValue(a: unknown, b: unknown): boolean {
    if (a === b) return true
    if (typeof a !== "object" || typeof b !== "object" || a === null || b === null) return false
    if (Array.isArray(a) !== Array.isArray(b)) return false
    const left = a as Record<string, unknown>
    const right = b as Record<string, unknown>
    const keys = Object.keys(left)
    return keys.length === Object.keys(right).length && keys.every((key) => key in right && sameValue(left[key], right[key]))
}

export function isContextStamp(
    before: StampedEntry,
    after: StampedEntry,
    { tolerateSection = false }: { tolerateSection?: boolean } = {},
): boolean {
    if (after.pathname !== before.pathname || after.hash !== before.hash) return false
    if (!sameSearch(before.search, after.search, tolerateSection)) return false
    if (!sameValue(withoutCtx(before.state), withoutCtx(after.state))) return false
    return readEntryContext(after.state).kind !== "absent"
}

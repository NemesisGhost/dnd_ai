import type { Location } from "react-router"

// Helpers for a guard caller's `disposingQuery` declaration (hooks/useUnsavedChangesGuard).

/** The query parameters that carry a character perspective, and the party chosen under it. */
export const PERSPECTIVE_QUERY_KEYS = ["character_id", "party_id"] as const

/**
 * A `disposingQuery` predicate that is true when any of `keys` has a different value list in the next
 * location. Only the named keys are compared, so every other query change stays harmless.
 */
export function queryKeysChanged(...keys: readonly string[]): (current: Location, next: Location) => boolean {
    return (current, next) => {
        const before = new URLSearchParams(current.search)
        const after = new URLSearchParams(next.search)
        return keys.some((key) => {
            const left = before.getAll(key)
            const right = after.getAll(key)
            return left.length !== right.length || left.some((value, index) => value !== right[index])
        })
    }
}

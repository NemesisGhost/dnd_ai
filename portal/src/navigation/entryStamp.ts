// Which REPLACEs are the internal context stamp (docs/UI_DESIGN.md §4.8.4).
//
// The selected-context owners restate the entry they have just accepted with a same-entry REPLACE
// (navigation/replaceOwnEntry.ts, the one place that writes it). Nothing about such a state *looks* like a
// stamp in a way another navigation could not copy: an operation that replaces the same address with the
// same state, `ctx` and message included, is structurally the same thing. So the writer says what it
// wrote, in memory, and observers ask it.
//
//   - `markStamp(entry, state)` is called by the writer with the entry it is replacing and the exact state
//     object it is about to hand the router, BEFORE it navigates, so no observer can see the stamp
//     unmarked. The mark is the state object itself (a WeakMap key) plus the *root* of the chain it
//     belongs to: the first entry that was not itself a stamp. Chains of stamps keep one root, so an
//     observer that was batched past an intermediate stamp still recognises the last one.
//   - `stampRoot(state)` answers for a location's state: the root key if that very object was marked by
//     the writer, otherwise null.
//
// Why this is safe:
//   - Identity, not content: client-supplied state, a copy, a spread, a history round trip (Back, reload:
//     the browser hands back a clone) or a forged object can never be a marked object, so no value can
//     claim to be a stamp. A genuine same-address REPLACE by anyone else carries a new object, and is a
//     new operation whatever it repeats.
//   - Bound to its entry: a mark names the root entry it restates; an observer accepts it only for the
//     entry (or chain) it is rendered under.
//   - Nothing to release: a stamp the router never commits (blocked, superseded, abandoned) leaves a
//     marked object nobody holds, which is collected with it. There is no flag, queue or counter to leave
//     behind, so no later navigation can be suppressed by a stamp that never happened.
//   - Nothing private: the mark is outside router and history state; no name, label or id is stored.

const stamps = new WeakMap<object, string>()

export interface StampableEntry {
    key: string
    state: unknown
}

/** The writer's declaration, made before it navigates: `state` is a stamp of `entry`. */
export function markStamp(entry: StampableEntry, state: object): void {
    stamps.set(state, stampRoot(entry.state) ?? entry.key)
}

/** The root of the stamp chain this very state object was marked into by the writer; null for any other state. */
export function stampRoot(state: unknown): string | null {
    return typeof state === "object" && state !== null ? (stamps.get(state) ?? null) : null
}

/** The key the entry restarts a chain from: its own, unless its state is itself a marked stamp. */
export function entryRoot(entry: StampableEntry): string {
    return stampRoot(entry.state) ?? entry.key
}

function plain(value: unknown): Record<string, unknown> {
    return typeof value === "object" && value !== null ? (value as Record<string, unknown>) : {}
}

/** The same state, value for value. */
export function sameState(a: unknown, b: unknown): boolean {
    return sameValue(a, b)
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

/** The same state, ignoring only the context stamp. */
export function sameStateButCtx(a: unknown, b: unknown): boolean {
    const strip = (state: unknown) => Object.fromEntries(Object.entries(plain(state)).filter(([key]) => key !== "ctx"))
    return sameValue(strip(a), strip(b))
}

/** True when the queries differ only in `section` (and do differ): the default a staged record page writes for itself. */
export function differsOnlyInSection(a: string, b: string): boolean {
    if (a === b) return false
    const left = new URLSearchParams(a)
    const right = new URLSearchParams(b)
    left.delete("section")
    right.delete("section")
    left.sort()
    right.sort()
    return left.toString() === right.toString()
}

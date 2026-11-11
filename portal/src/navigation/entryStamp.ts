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
// A second writer is identified the same way, as a different kind of write with different permitted
// changes: the staged record pages' normalization of a missing or invalid `?section=`
// (components/staged/useStagedNavigation, `markNormalization`). A stamp restates the same address and
// changes only `ctx`; a normalization carries the state over and changes only `section` in the query.
// Neither kind is accepted for the other's changes, and an unmarked replacement is never either, however
// closely its address and state match.
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
//
// Requirement and limit: the mark survives only where the router keeps the state object it was given, as
// the data router the app ships (`createBrowserRouter`, main.tsx) does for every location it commits.
// Locations rebuilt from the browser's history (a reload, Back/Forward: the state is a structured clone)
// and the plain `<BrowserRouter>` hand back clones, so no mark is ever found there: an observer then
// treats a replacement as the operation it cannot prove it is not. For selection arrivals (data router
// only) that ends the arrival; for ordinary page arrivals it means a stamp could repeat a message.

type Kind = "stamp" | "normalization"
const marks = new WeakMap<object, { kind: Kind; root: string }>()

export interface StampableEntry {
    key: string
    state: unknown
}

/** The writer's declaration, made before it navigates: `state` is a stamp of `entry`. */
export function markStamp(entry: StampableEntry, state: object): void {
    marks.set(state, { kind: "stamp", root: entryRoot(entry) })
}

/** The staged section normalizer's declaration, made before it navigates: `state` is its write for `entry`. */
export function markNormalization(entry: StampableEntry, state: object): void {
    marks.set(state, { kind: "normalization", root: entryRoot(entry) })
}

function rootOf(state: unknown, kind: Kind): string | null {
    if (typeof state !== "object" || state === null) return null
    const mark = marks.get(state)
    return mark !== undefined && mark.kind === kind ? mark.root : null
}

/** The root of the chain this very state object was marked into as a context stamp; null for any other state. */
export function stampRoot(state: unknown): string | null {
    return rootOf(state, "stamp")
}

/** The root of the chain this very state object was marked into as a section normalization; null otherwise. */
export function normalizationRoot(state: unknown): string | null {
    return rootOf(state, "normalization")
}

/** The key the entry restarts a chain from: its own, unless its state is itself a marked write. */
export function entryRoot(entry: StampableEntry): string {
    if (typeof entry.state === "object" && entry.state !== null) {
        const mark = marks.get(entry.state)
        if (mark !== undefined) return mark.root
    }
    return entry.key
}

function plain(value: unknown): Record<string, unknown> {
    return typeof value === "object" && value !== null ? (value as Record<string, unknown>) : {}
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

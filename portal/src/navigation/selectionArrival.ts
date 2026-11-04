import { createContext, useContext } from "react"
import { readEntryContext } from "./contexts"
import type { SelectionChange, SelectionScope } from "./selectionChange"

// One accepted selection arrival (docs/UI_DESIGN.md §4.8.4): the Infobox choice the router has accepted
// and committed, up to the point a newer navigation replaces it. It holds ids and two one-shot claims
// (the announcement and the heading focus), never a name or a label, so nothing private is kept after
// the person loses access. SelectionArrivalProvider creates it from the accepted location; the
// destination (its boundaries) asks it to focus once the page has actually settled.

/** The page area a destination renders into (WorkspaceFrame). */
const CONTENT = ".campaign-workspace__content"

/** The Infobox, where the choice is made: focus still here (or nowhere) has not been moved on by the person. */
const ORIGIN = ".campaign-context-panel"

/** Set by a page that is still loading what it will show (PlaceholderPage `busy`). */
export const LOADING_ATTRIBUTE = "data-page-loading"

/** The parts of a committed location an arrival is judged by. */
export interface ArrivalEntry {
    key: string
    pathname: string
    search: string
    hash: string
    state: unknown
}

function plain(value: unknown): Record<string, unknown> {
    return typeof value === "object" && value !== null ? (value as Record<string, unknown>) : {}
}

// The one query difference a destination makes to its own address as it arrives: a staged record page
// writes its default `?section=` into the entry it has just opened (components/staged/useStagedNavigation).
// Any other parameter, added, changed or removed, makes it a different address.
function sameSearchButSection(a: string, b: string): boolean {
    if (a === b) return true
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

export class SelectionArrival {
    readonly change: SelectionChange
    // The campaign or world the destination's address names; what the committed selection must agree with.
    readonly scope: SelectionScope
    // The entry the arrival is currently rendered under (the accepted one, or its latest own stamp).
    private entry: ArrivalEntry
    // The history entries this arrival is rendered under: the location it was accepted at and the
    // stamp-only replacements of that same entry. A page still rendered under an older location, which
    // can happen for a moment while React catches up with the router, is not the destination.
    private readonly keys = new Set<string>()
    // The campaign selected when the choice was made, before anything was committed: what lets "the
    // campaign selection was cleared" be told apart from "there was none".
    readonly campaignBefore: string | null
    private announced = false
    private focused = false

    constructor(change: SelectionChange, scope: SelectionScope, entry: ArrivalEntry, campaignBefore: string | null) {
        this.change = change
        this.scope = scope
        this.entry = entry
        this.campaignBefore = campaignBefore
        this.keys.add(entry.key)
    }

    /** Whether `key` is an entry this arrival is (or was) rendered under. */
    owns(key: string): boolean {
        return this.keys.has(key)
    }

    /**
     * Whether `next`, a REPLACE, is the arrival's own stamp and nothing else: the context stamp the
     * selected-context owners write on the entry they have just accepted (navigation/replaceOwnEntry.ts).
     * That is the same address (path, hash and query, but for the `section` a staged record page writes
     * for itself) and the same state except for `ctx`, and a `ctx` that is a well-formed stamp. Any other same-path replacement, with another query, hash, marker,
     * task or list state, or without a stamp, is a different navigation and ends the arrival.
     */
    isOwnStamp(next: ArrivalEntry): boolean {
        const now = this.entry
        if (next.pathname !== now.pathname || next.hash !== now.hash || !sameSearchButSection(now.search, next.search)) return false
        if (!sameValue(withoutCtx(now.state), withoutCtx(next.state))) return false
        // The stamp may still name the selection from before the choice was committed (the owners stamp the
        // entry as soon as it is accepted, then again once the selection has followed), so it is judged by
        // being a well-formed stamp, not by which context it records.
        return readEntryContext(next.state).kind !== "absent"
    }

    /** A stamp-only replacement of the entry arrived at: still this arrival, now rendered under `entry`. */
    adopt(entry: ArrivalEntry): void {
        this.entry = entry
        this.keys.add(entry.key)
    }

    /** True exactly once: the first caller owns the announcement. */
    claimAnnouncement(): boolean {
        if (this.announced) return false
        this.announced = true
        return true
    }

    /**
     * Moves focus to the destination's heading, once. It acts only for the location the choice was
     * accepted at (as rendered, not as the router has since moved on), only when the page has stopped loading (nothing in the content is marked as loading)
     * and shows a heading, and not when the person has already moved focus somewhere else (anywhere
     * but the Infobox the choice was made in, or nowhere). A settled destination uses the claim up
     * whether or not focus moved, so a later read, a remount or a stamp never moves focus again.
     */
    focusHeading(locationKey: string): void {
        if (this.focused || !this.keys.has(locationKey)) return
        const content = document.querySelector<HTMLElement>(CONTENT)
        if (content === null || content.querySelector(`[${LOADING_ATTRIBUTE}]`) !== null) return
        const heading = content.querySelector<HTMLElement>("h1")
        if (heading === null) return
        this.focused = true
        const active = document.activeElement
        if (active instanceof HTMLElement && active !== document.body && active.closest(ORIGIN) === null) return
        if (!heading.hasAttribute("tabindex")) heading.setAttribute("tabindex", "-1")
        heading.focus()
    }
}

// The arrival in force with the location being rendered (a destination reads both without needing a
// router of its own).
export interface CurrentSelectionArrival {
    arrival: SelectionArrival
    // The key of the location this part of the tree is rendered under.
    locationKey: string
}

export const SelectionArrivalContext = createContext<CurrentSelectionArrival | null>(null)

/** The accepted selection arrival in force, or null (no choice, a superseded one, or outside the shell). */
export function useSelectionArrival(): CurrentSelectionArrival | null {
    return useContext(SelectionArrivalContext)
}

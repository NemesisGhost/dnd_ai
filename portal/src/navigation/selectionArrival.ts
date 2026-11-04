import { createContext, useContext } from "react"
import { activationFor, releaseActivation } from "./activationOwner"
import { differsOnlyInSection, sameState, sameStateButCtx, stampRoot } from "./entryStamp"
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

    // The location this arrival was accepted at: what a navigation request's activated control is bound to.
    private readonly acceptedKey: string

    constructor(change: SelectionChange, scope: SelectionScope, entry: ArrivalEntry, campaignBefore: string | null) {
        this.acceptedKey = entry.key
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
     * Whether `next`, a REPLACE, keeps this arrival: it is the context stamp the stamp writer made for the
     * entry this arrival is rendered under (navigation/entryStamp.ts: the writer marked that very state
     * object, as a stamp of a chain rooted at an entry of this arrival), at the same address; or it is the
     * default `?section=` a staged record page writes for itself into the entry it has just opened (the
     * same state but for `ctx`, only the section differing). Nothing that merely resembles a stamp keeps
     * it: any other replacement, even of the same path with the same state and `ctx`, ends the arrival.
     */
    isOwnStamp(next: ArrivalEntry): boolean {
        const now = this.entry
        if (next.pathname !== now.pathname || next.hash !== now.hash) return false
        if (next.search === now.search) {
            const root = stampRoot(next.state)
            if (root !== null && this.keys.has(root)) return true
            // The very same state restated (a page asking for the address it is already at, as StrictMode's
            // second effect does) changes nothing, so it is not another navigation.
            return sameState(now.state, next.state)
        }
        return differsOnlyInSection(now.search, next.search) && sameStateButCtx(now.state, next.state)
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
        // The control the accepted request was made with (the Navbar menu's link), if this arrival is its own.
        const origin = activationFor(this.acceptedKey)
        releaseActivation(this.acceptedKey)
        const active = document.activeElement
        if (
            active instanceof HTMLElement &&
            active !== document.body &&
            active !== origin &&
            active.closest(ORIGIN) === null
        ) {
            return
        }
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

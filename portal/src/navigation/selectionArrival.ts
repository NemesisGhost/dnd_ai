import { createContext, useContext } from "react"
import { activationFor, releaseActivation } from "./activationOwner"
import { differsOnlyInSection, entryRoot, normalizationRoot, sameStateButCtx, stampRoot } from "./entryStamp"
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
     * Whether `next`, a REPLACE, keeps this arrival: it was written by one of the two writers that restate
     * the entry the arrival is rendered under, and says so (navigation/entryStamp.ts marks the very state
     * object before the router sees it, with the chain root it restates, which must be one of this
     * arrival's own entries):
     *   - the context stamp (`replaceOwnEntry`): the same address; or
     *   - the staged record page's normalization of a missing or invalid `?section=`
     *     (`useStagedNavigation`): the same path and hash, a query that differs from the entry's only in
     *     `section`, and the entry's state carried over but for `ctx`.
     * Nothing that merely resembles one keeps it: any other replacement, even of the same address with
     * exactly the same state, ends the arrival, and a later look-alike does not revive it.
     */
    isOwnStamp(next: ArrivalEntry): boolean {
        const now = this.entry
        if (next.pathname !== now.pathname || next.hash !== now.hash) return false
        const stamp = stampRoot(next.state)
        if (stamp !== null) return next.search === now.search && this.keys.has(stamp)
        const normalization = normalizationRoot(next.state)
        if (normalization === null || !this.keys.has(normalization)) return false
        return (next.search === now.search || differsOnlyInSection(now.search, next.search)) && sameStateButCtx(now.state, next.state)
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

// A link arrival is a chain of entries that began with a PUSH: the entry the person's link created, and the
// stamp-only REPLACEs the selected-context owners write over it (navigation/entryStamp.ts) before a slow
// destination has settled. The shell notes each PUSH here as it is committed; a reload or Back/Forward
// (POP) is never noted, so it is never an arrival. Bounded: only recent entries can still be settling.
const pushedEntries: string[] = []
const PUSHED_LIMIT = 64
// The chain root a link arrival has already claimed. One navigation is one claim, so a remount, a re-read,
// a second boundary on the same page or a stamp never moves focus twice.
let claimedLinkArrival: string | null = null

/** The shell's declaration, made as each location is committed: `key` was reached by a PUSH. */
export function notePushedEntry(key: string): void {
    if (pushedEntries.includes(key)) return
    pushedEntries.push(key)
    if (pushedEntries.length > PUSHED_LIMIT) pushedEntries.shift()
}

/**
 * The heading focus of an ordinary link arrival (a Navbar link, a breadcrumb, an accepted departure after
 * Leave): a destination that settled with no selection arrival in force, under an entry that is, or only
 * restates, a PUSH. Like `focusHeading` it acts once, only when nothing in the content is still loading and
 * the page shows a heading. It takes focus from the page the person left (`body`, or a control outside the
 * content such as the Navbar link or the Infobox) and leaves focus the person has already placed inside the
 * content alone.
 */
export function focusLinkArrival(entry: { key: string; state: unknown }): void {
    const root = entryRoot(entry)
    if (claimedLinkArrival === root || !pushedEntries.includes(root)) return
    const content = document.querySelector<HTMLElement>(CONTENT)
    if (content === null || content.querySelector(`[${LOADING_ATTRIBUTE}]`) !== null) return
    const heading = content.querySelector<HTMLElement>("h1")
    if (heading === null) return
    claimedLinkArrival = root
    const active = document.activeElement
    if (active instanceof HTMLElement && active !== document.body && content.contains(active)) return
    if (!heading.hasAttribute("tabindex")) heading.setAttribute("tabindex", "-1")
    heading.focus()
}

// The arrival in force with the location being rendered (a destination reads both without needing a
// router of its own).
export interface CurrentSelectionArrival {
    arrival: SelectionArrival
    // The key of the location this part of the tree is rendered under.
    locationKey: string
}

export const SelectionArrivalContext = createContext<CurrentSelectionArrival | null>(null)

// The entry a destination is rendered under, offered for a link arrival only while no selection arrival of
// any kind is in force (an arrival that is pending or not eligible keeps its own rules and gets no fallback).
// Null outside the shell.
export const LinkArrivalContext = createContext<{ key: string; state: unknown } | null>(null)

/** The accepted selection arrival in force, or null (no choice, a superseded one, or outside the shell). */
export function useSelectionArrival(): CurrentSelectionArrival | null {
    return useContext(SelectionArrivalContext)
}

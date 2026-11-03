// The four navigation layers P02 keeps apart (docs/UI_DESIGN.md §4.8). Each is a different question,
// answered from a different source, and none of them grants authority: every read and command is
// authorized by the server, and a descriptor or history entry that names something only ever asks for
// it. Nothing here holds a label, a free-text value, a URL, a capability or an authorization outcome.
//
//   - ExecutionScope  : whose data does this route read and write? (route params)
//   - SelectedContext : what has the person explicitly chosen? (the Infobox; history-entry stamp)
//   - ViewedRecord    : which record is on screen? (route params; viewing never selects)
//   - task origin     : see taskOrigin.ts
//
// This module is pure. Production selection ownership is unchanged by it (P02-3 moves it).

/** An identifier as the API issues them (UUIDs) or as fixtures write them: no separators, dots or spaces. */
const ID_PATTERN = /^[A-Za-z0-9_-]{1,64}$/

export function isIdShaped(value: unknown): value is string {
    return typeof value === "string" && ID_PATTERN.test(value)
}

export type ExecutionScope =
    | { kind: "campaign"; campaignId: string }
    | { kind: "world"; worldId: string }
    | { kind: "none" }

/** What the person has explicitly selected. `null` is an explicit "nothing", never "unknown". */
export interface SelectedContext {
    campaignId: string | null
    worldId: string | null
    timelineId: string | null
    characterId: string | null
}

export const SELECTED_CONTEXT_KEYS = ["campaignId", "worldId", "timelineId", "characterId"] as const

/** The context a history entry was committed under, stored beside (never inside) a task descriptor. */
export interface EntryContextV1 extends SelectedContext {
    v: 1
}

/** The record a route shows: a type name and an id from the URL. Viewing a record never selects it. */
export interface ViewedRecord {
    type: string
    id: string
}

export type EntryContextRead =
    // No valid stamp: a direct entry, an older entry, tampered or malformed state.
    | { kind: "absent" }
    // The P02-0a stamp `{ v: 1, characterId }`. It records the perspective only; the other levels are
    // unrecorded (not "none"), so a comparison never treats them as having changed.
    | { kind: "legacy-perspective"; characterId: string | null }
    | { kind: "v1"; context: EntryContextV1 }

function has(record: object, key: string): boolean {
    return Object.prototype.hasOwnProperty.call(record, key)
}

function isIdOrNull(value: unknown): value is string | null {
    return value === null || isIdShaped(value)
}

/**
 * Reads the context stamp of a history entry's state (`state.ctx`). Shape and version only, plus
 * authorization of the perspective when the caller knows the authorized set: a stamp naming a
 * perspective that is not authorized is treated as no stamp at all, because it cannot be trusted.
 *
 * Compatibility rules, in order:
 *   1. `ctx` missing, not an object, or `v !== 1`                       -> absent
 *   2. all four keys present, each an id or null                        -> v1
 *   3. only `characterId` present (string or null; the P02-0a stamp)    -> legacy-perspective
 *   4. anything else (partial or mistyped v1 form)                      -> absent
 * A `characterId` of `null` is an explicit "no perspective" and is different from an absent stamp.
 */
export function readEntryContext(state: unknown, authorized?: ReadonlySet<string>): EntryContextRead {
    if (typeof state !== "object" || state === null || !has(state, "ctx")) return { kind: "absent" }
    const ctx = (state as { ctx?: unknown }).ctx
    if (typeof ctx !== "object" || ctx === null || Array.isArray(ctx)) return { kind: "absent" }
    if ((ctx as { v?: unknown }).v !== 1) return { kind: "absent" }

    const record = ctx as Record<string, unknown>
    const characterId = record.characterId
    const authorizedPerspective = (id: string | null): boolean =>
        id === null || authorized === undefined || authorized.has(id)

    if (SELECTED_CONTEXT_KEYS.every((key) => has(record, key))) {
        if (!SELECTED_CONTEXT_KEYS.every((key) => isIdOrNull(record[key]))) return { kind: "absent" }
        const context: EntryContextV1 = {
            v: 1,
            campaignId: record.campaignId as string | null,
            worldId: record.worldId as string | null,
            timelineId: record.timelineId as string | null,
            characterId: characterId as string | null,
        }
        return authorizedPerspective(context.characterId) ? { kind: "v1", context } : { kind: "absent" }
    }

    if (SELECTED_CONTEXT_KEYS.some((key) => key !== "characterId" && has(record, key))) return { kind: "absent" }
    if (characterId === null) return { kind: "legacy-perspective", characterId: null }
    if (typeof characterId !== "string") return { kind: "absent" }
    return authorizedPerspective(characterId)
        ? { kind: "legacy-perspective", characterId }
        : { kind: "absent" }
}

/** The stamp to write for a context: always the versioned form, with ids copied and nothing else. */
export function entryContextStamp(context: SelectedContext): EntryContextV1 {
    return {
        v: 1,
        campaignId: context.campaignId,
        worldId: context.worldId,
        timelineId: context.timelineId,
        characterId: context.characterId,
    }
}

import { humanizeCode } from "./humanize"

// One thing the person typed, for showing back to them after they lost the right to save it.
export interface RetainedChange {
    label: string
    value: string
}

function show(value: unknown): string {
    if (value === null || value === undefined) return "(cleared)"
    if (typeof value === "string") return value.trim() === "" ? "(cleared)" : value
    if (typeof value === "number" || typeof value === "boolean") return String(value)
    return JSON.stringify(value)
}

const same = (a: unknown, b: unknown): boolean => JSON.stringify(a) === JSON.stringify(b)

// A field name as a label: snake_case and camelCase both become words ("childType" -> "Child type").
const labelOf = (key: string): string => {
    const words = humanizeCode(key.replace(/([a-z0-9])([A-Z])/g, "$1_$2").toLowerCase())
    return words.charAt(0) + words.slice(1).toLowerCase()
}

// When someone loses the right to read or edit a record while an edit form is open, the form holds
// the whole record: every field was filled from the server's private read. Keeping all of it would
// preserve a private document merely by calling it an unsaved draft, so only what the person
// *changed* is kept: each field whose value differs from the value the server gave them, and the
// change note they wrote. A field left as loaded is dropped, and so is everything else the server
// had sent. Values that are not plain objects of fields cannot be told apart from the server's
// content, so nothing is kept for them.
export function retainedChanges(loaded: unknown, current: unknown, changeNote: string): RetainedChange[] {
    const out: RetainedChange[] = []
    if (
        typeof loaded === "object" &&
        loaded !== null &&
        typeof current === "object" &&
        current !== null &&
        !Array.isArray(loaded) &&
        !Array.isArray(current)
    ) {
        const before = loaded as Record<string, unknown>
        const after = current as Record<string, unknown>
        for (const key of Object.keys(after)) {
            if (!same(before[key], after[key])) out.push({ label: labelOf(key), value: show(after[key]) })
        }
    }
    if (changeNote.trim() !== "") out.push({ label: "Change note", value: changeNote.trim() })
    return out
}

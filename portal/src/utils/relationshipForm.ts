// Shared copy for the relationship editors (Phase 15 checkpoint 15.3A-2a).

export const RELATIONSHIP_CODE_MESSAGE: Readonly<Record<string, string>> = {
    relationship_invalid: "That is not a valid relationship.",
    participant_invalid: "Choose published places, organizations, religions or characters.",
    participant_incompatible: "That participant cannot take that role in this type of relationship.",
    relationship_time_invalid: "Choose times in this world, with the end after the start.",
    relationship_start_required: "Set when the relationship started before ending it.",
    relationship_archived: "This relationship is archived. Restore it first.",
    relationship_already_ended: "This relationship has already ended.",
    relationship_not_archived: "This relationship is not archived.",
    membership_overlap: "That member already belongs to this organization during that time.",
    membership_start_required: "Choose when the membership began.",
    perspective_holder_invalid: "Choose one of the relationship's participants.",
}

// ---- The roster's summaries -------------------------------------------------------------------
// Pure reads of what the server sent. Nothing here compares dates or parses a label: the period
// status is the server's, and no fact is inferred from another.

export interface PeriodFacts {
    started: string | null
    ended_at?: string | null
    // The detail names the end display `ended`; the summary uses `ended_at` because `ended` is a flag.
    ended?: string | null | boolean
    period_status?: string
}

// The recorded period in words: only dates that exist are named.
export function periodText(item: PeriodFacts): string {
    const end = item.ended_at ?? (typeof item.ended === "string" ? item.ended : null)
    if (item.started && end) return `${item.started} to ${end}`
    if (item.started) return `Since ${item.started}`
    if (end) return `Until ${end}`
    return "No dates recorded"
}

// Where the campaign clock sits against that period. An undated record says nothing more.
export function periodStatusPhrase(status: string | undefined): string | null {
    switch (status) {
        case "in_effect":
            return "in effect now"
        case "not_started":
            return "not started yet"
        case "ended":
            return "ended"
        case "clock_unset":
            return "campaign time not set"
        default:
            return null
    }
}

export function periodSummary(item: PeriodFacts): string {
    const phrase = periodStatusPhrase(item.period_status)
    return phrase === null ? periodText(item) : `${periodText(item)} — ${phrase}`
}

interface Named {
    entity_id: string
    name: string
    role_label: string
}

// The other participants, by name. A record stored as its own counterpart names itself once.
export function counterparts(participants: Named[], entityId: string): string {
    const others = participants.filter((p) => p.entity_id !== entityId).map((p) => p.name)
    if (others.length > 0) return others.join(" and ")
    const self = participants[0]?.name
    return self === undefined ? "this record" : `${self} (this record)`
}

// Every participant's role, in the server's order, with the opened record named "This record". The
// direction comes from the role labels alone, so it reads the same from either participant.
export function roleSummary(participants: Named[], entityId: string): string {
    return participants
        .map((p) => `${p.entity_id === entityId ? "This record" : p.name}: ${p.role_label}`)
        .join(" · ")
}

export interface VisibilityFacts {
    kind: string
    is_public: boolean | null
    is_hidden?: boolean | null
}

// What the record's own visibility setting says, by kind. No label claims a player can see the
// record: that also depends on both participants being discoverable and on the lifecycle.
export function relationshipVisibility(item: VisibilityFacts): string {
    if (item.kind === "ownership" || item.kind === "membership") {
        if (item.is_public === true) return "Known to the public"
        if (item.is_public === false) return "Editors only"
        return "Not recorded"
    }
    if (item.kind === "route") {
        if (item.is_hidden === true) return "Concealed: editors only"
        if (item.is_hidden === false) return "Not concealed"
        return "Not recorded"
    }
    return "No visibility setting"
}

export const humanizeCode = (code: string): string => code.replace(/_/g, " ")

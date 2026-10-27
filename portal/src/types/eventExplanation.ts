// Event explanation contract (Phase 15 checkpoint CP-9a): what happened, to whom and when, as the
// server resolved it for this caller. A reference carries an id and a name only when state is
// "named"; "unrecorded" means the event records no value, "unavailable" that there is one the
// caller may not see (or that no longer resolves). Names are current labels, not snapshots.

import type { TravelPlace } from "./campaignSession"

export type ExplanationRefState = "named" | "unrecorded" | "unavailable"

export interface ExplanationRef {
    state: ExplanationRefState
    kind: "character" | "party" | "build" | "event"
    entity_id: string | null
    name: string | null
    // Whether the caller may follow the reference to its own page.
    openable: boolean
}

export interface ExplanationClockTime {
    state: ExplanationRefState
    text: string | null
}

export type ExplanationRelationCode =
    | "follows_previous_clock_change"
    | "corrects_clock_change"
    | "corrected_by_clock_change"
    | "caused_by"
    | "corrected_by"
    | "replaced_by"
    | "corrects"
    | "replaces"

export interface ExplanationRelation {
    relation: ExplanationRelationCode
    event: ExplanationRef
    // Correction reason; editors only.
    reason: string | null
}

export interface ExplanationSession {
    session_id: string
    session_number: number
    title: string | null
}

export interface ExplanationLeg {
    traveler: { entity_id: string; name: string }
    from: TravelPlace
    to: TravelPlace
}

export type ExplanationFamily =
    | "party_member_joined"
    | "party_member_left"
    | "character_build_activated"
    | "campaign_clock_advanced"
    | "campaign_clock_corrected"
    | "location"
    | "travel"
    | "other"

export interface EventExplanation {
    event_id: string
    family: ExplanationFamily
    // Effective in-world time, formatted by the campaign calendar.
    in_world_time: string
    // Real recording time (ISO, UTC offset), shown separately from in-world time.
    recorded_at: string
    subject: ExplanationRef | null
    party: ExplanationRef | null
    // "full" when build labels may be shown to this caller, otherwise "generic".
    build_detail: "full" | "generic" | null
    previous_build: ExplanationRef | null
    new_build: ExplanationRef | null
    previous_time: ExplanationClockTime | null
    new_time: ExplanationClockTime | null
    // Clock advances recorded after CP-9b: "manual" or "event_cause". Null for an earlier advance
    // (never guessed) and for every other family.
    advance_origin: "manual" | "event_cause" | null
    // Written by the GM for the members who may view this event. Not the GM-only details.
    member_explanation: string | null
    travel: { legs: ExplanationLeg[] } | null
    session: ExplanationSession | null
    relations: ExplanationRelation[]
}

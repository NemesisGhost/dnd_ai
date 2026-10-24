import type { CharacterKind } from "./character"

export interface CampaignSessionListItem {
    session_id: string
    session_number: number
    title: string | null
    status_code: string
    started_at: string | null
    ended_at: string | null
    // Phase 15.2D-1: the planned start and the derived play status.
    scheduled_for?: string | null
    play_status?: "unscheduled" | "scheduled" | "in_progress" | "completed"
    // Editors only.
    row_version?: number | null
    available_actions?:
        | ("update" | "archive" | "restore" | "start" | "manage_participants" | "log" | "end")[]
        | null
}

export interface SessionReceipt {
    session_id: string
    session_number: number
    row_version: number
    created: boolean
    changed: boolean
}

export interface CampaignSessionEvent {
    event_id: string
    name: string
    summary: string | null
    event_type_code: string
    event_status_code: string
    world_time_id: string
    details: string | null
    // In-world time as display text (never a real-world timestamp). Absent from older servers.
    world_time?: string
}

// One end of a travel leg. A name is present only when state is "named"; "unrecorded" means
// the traveler had no earlier location, "unavailable" that the place cannot be shown to you.
export interface TravelPlace {
    state: "named" | "unrecorded" | "unavailable"
    entity_id?: string | null
    name?: string | null
}

export interface SessionTravelLeg {
    traveler: { entity_id: string; name: string }
    from: TravelPlace
    to: TravelPlace
}

// A travel event of the session, already filtered for the caller. `note` is the GM note
// (editors only, otherwise null).
export interface SessionTravelEntry {
    event_id: string
    world_time_id: string
    world_time: string
    note: string | null
    legs: SessionTravelLeg[]
}

export interface SessionParticipant {
    session_participant_id: string
    character_id: string
    character_name: string
    character_kind: CharacterKind
    participation_role: "player_character" | "npc" | "guest"
    added_at: string
    removed_at: string | null
}

// What the item and travel pickers need of a participant: who, and whether they are still present.
export type SessionParticipantPick = Omit<SessionParticipant, "character_kind">

export interface PlayReceipt {
    session_id: string
    row_version: number
    changed: boolean
    session_participant_id?: string
    event_id?: string
}

export interface CampaignSessionDetail
    extends CampaignSessionListItem {
    summary: string | null
    start_world_time_id: string | null
    end_world_time_id: string | null
    events: CampaignSessionEvent[]
    // Readable entries for the travel events above. Absent from older servers.
    travel?: SessionTravelEntry[]
    // Editors only.
    participants?: SessionParticipant[] | null
    // Editors only: the roles each kind of character may take (matching role first). Absent
    // from older servers, in which case no role is offered.
    participant_role_options?: Record<string, string[]> | null
}
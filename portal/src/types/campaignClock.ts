// The campaign clock (Phase 15 checkpoint 15.2W-2).

export interface ClockState {
    current: { world_time_id: string; display: string } | null
    // 0 when this campaign's timeline has no clock row of its own yet.
    row_version: number
    // True when the value is inherited from the parent timeline (a branch).
    inherited: boolean
    last_event_id: string | null
}

export interface ClockVersionBody {
    world_time_id: string
    expected_row_version: number
}

// Both optional inputs are left out of a plain manual advance.
export interface AdvanceClockBody extends ClockVersionBody {
    // An existing gameplay event of this campaign's own history that caused the advance.
    cause_event_id?: string
    // Written for the members who may view the resulting event; not the GM-only notes.
    explanation?: string
}

export interface CorrectClockBody extends ClockVersionBody {
    corrects_event_id: string
}

// Events the GM may name as the cause of an advance to the chosen time (never the clock's own
// events, voided ones, another campaign's or the original timeline's history).
export interface ClockCauseChoice {
    event_id: string
    name: string
    in_world_time: string
}

export interface ClockCauseChoices {
    choices: ClockCauseChoice[]
}

export const CLOCK_EXPLANATION_MAX_LENGTH = 500

export interface ClockReceipt {
    world_time_id: string
    event_id: string
    row_version: number
    created: boolean
    changed: boolean
}

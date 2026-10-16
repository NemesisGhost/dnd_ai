// The campaign clock (Phase 15 checkpoint 15.2W-2).

export interface ClockState {
    current: { world_time_id: string; display: string } | null
    // 0 when this campaign's timeline has no clock row of its own yet.
    row_version: number
    // True when the value is inherited from the parent timeline (a branch).
    inherited: boolean
    last_event_id: string | null
}

export interface AdvanceClockBody {
    world_time_id: string
    expected_row_version: number
}

export interface CorrectClockBody extends AdvanceClockBody {
    corrects_event_id: string
}

export interface ClockReceipt {
    world_time_id: string
    event_id: string
    row_version: number
    created: boolean
    changed: boolean
}

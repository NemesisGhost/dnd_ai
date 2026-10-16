// Event authoring and correction contracts (Phase 15 checkpoint 15.2E-1).

export interface EventParticipantView {
    entity_id: string
    name: string
    role: string
}

export interface EventEffectView {
    component: string
    target_entity_id: string | null
    previous: unknown
    new: unknown
    application_status: string
}

export interface EventCorrectionInfo {
    kind: "void" | "correct"
    // GM-only.
    reason: string
    correcting_event_id: string
    replacement_event_id: string | null
}

export interface EventAuthoringView {
    event_id: string
    name: string
    event_type_code: string
    status: "draft" | "recorded" | "voided" | "corrected"
    world_time_id: string
    world_time: string
    session_id: string | null
    details: string | null
    participants: EventParticipantView[]
    effects: EventEffectView[]
    correction: EventCorrectionInfo | null
    corrects_event_id: string | null
}

export interface EffectPreview {
    component: string
    target_entity_id: string | null
    reversible: boolean
    reason: "state_changed" | "unsupported_effect" | "effect_not_applied" | null
}

export interface CorrectionPreview {
    event_id: string
    status: string
    can_correct: boolean
    is_correction: boolean
    effects: EffectPreview[]
}

export interface EventReceipt {
    event_id: string
}

export interface CorrectionReceipt {
    event_id: string
    status: "voided" | "corrected"
    correction_id: string
    correcting_event_id: string
    replacement_event_id?: string
}

export interface RecordEventBody {
    world_time_id: string
    event_type_code: string
    name: string
    details: string | null
    session_id?: string | null
}

export interface ReplacementBody {
    event_type_code: string
    name: string
    details: string | null
    world_time_id: string | null
}

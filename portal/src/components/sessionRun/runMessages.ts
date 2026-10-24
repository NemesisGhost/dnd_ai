// What each session-run refusal means, in the session's own terms (the server only sends a code).
export const CODE_MESSAGE: Readonly<Record<string, string>> = {
    clock_required: "Set the campaign time first (the card on this page), or choose a time.",
    another_session_in_progress: "Another session of this campaign is already in progress.",
    session_already_started: "This session has already started.",
    session_not_in_progress: "This session is not in progress.",
    session_not_open: "This session has ended.",
    session_not_active:
        "This session is not active, so it cannot be changed. An archived session must be restored first.",
    session_end_not_after_start: "The end time must be later than when the session began.",
    session_participant_role_mismatch:
        "That role does not fit this character. Choose the matching role, or Guest.",
    session_participant_invalid:
        "That character cannot take part: only published, active characters of this world can.",
    session_participant_exists: "That character is already in this session.",
    session_participant_removed: "That participant has already been removed.",
    world_time_id_invalid: "That time is not available. Choose another.",
}

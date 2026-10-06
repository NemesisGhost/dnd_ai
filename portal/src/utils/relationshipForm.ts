// Shared copy for the relationship editors (Phase 15 checkpoint 15.3A-2a).

export const RELATIONSHIP_CODE_MESSAGE: Readonly<Record<string, string>> = {
    relationship_invalid: "That is not a valid relationship.",
    participant_invalid: "Choose published places, organizations, religions or characters.",
    relationship_time_invalid: "Choose times in this world, with the end after the start.",
    relationship_start_required: "Set when the relationship started before ending it.",
    relationship_archived: "This relationship is archived. Restore it first.",
    relationship_already_ended: "This relationship has already ended.",
    relationship_not_archived: "This relationship is not archived.",
    perspective_holder_invalid: "Choose one of the relationship's participants.",
}

import { ERROR_CODE_MESSAGE } from "./authoringValidation"

// Plain-language explanations for the server's closed `blocked_actions`
// reasons. Shown as sentence fragments after "<Action> unavailable: ".
export const BLOCKED_REASON: Readonly<Record<string, string>> = {
    wrong_canon_status: "not available at this canon status.",
    entity_archived: "the record is archived.",
    entity_not_archived: "the record is not archived.",
    review_in_progress: "it is awaiting review; return it to draft or finish the review first.",
    lifecycle_not_supported: "this kind of record is not managed through lifecycle actions.",
    reference_not_published:
        "a record it depends on, such as its parent, is not published yet. Publish that first.",
    quest_definition_incomplete:
        "a quest needs at least one stage with an objective before it can be published.",
    character_has_user_relationships:
        "a player or account is linked to this character. Remove those links first.",
}

export function describeBlockedReason(reason: string): string {
    return BLOCKED_REASON[reason] ?? ERROR_CODE_MESSAGE[reason] ?? "not allowed right now."
}

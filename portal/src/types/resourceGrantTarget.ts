// Mirrors dnd_ai.commands.access_grants._RESOURCE_GRANT_TARGET_FIELDS
// exactly, in the same order -- the six mutually exclusive target
// columns a resource grant may name (PHASE13E_REMAINING_IMPLEMENTATION_
// PLAN.md §8.5). Shared by both the direct (membership-grantee) and
// group-grantee resource-grant forms.
export type ResourceGrantTargetField =
    | "character_id"
    | "entity_id"
    | "knowledge_item_id"
    | "quest_id"
    | "session_id"
    | "event_id"

export interface ResourceGrantTarget {
    field: ResourceGrantTargetField
    id: string
}

export type ResourceGrantEffect = "allow" | "deny"

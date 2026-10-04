// Client-side mirrors of the server's structural constraints, so a field error
// shows before submit. The server remains authoritative and never sends a field
// location (docs/PLAN.md Phase 14, D15), so domain failures reach a field only
// through the stable `code` -> field map below.

export const NAME_MAX = 200
export const DESCRIPTION_MAX = 4000
export const REASON_MAX = 1000
export const LABEL_MAX = 200
export const MAX_ALLOWED_RULESETS = 10

export function validateName(value: string, label = "Name"): string | null {
    const trimmed = value.trim()
    if (trimmed.length === 0) {
        return `${label} is required.`
    }
    if (trimmed.length > NAME_MAX) {
        return `${label} must be ${NAME_MAX} characters or fewer.`
    }
    return null
}

export function validateDescription(value: string): string | null {
    if (value.trim().length > DESCRIPTION_MAX) {
        return `Description must be ${DESCRIPTION_MAX} characters or fewer.`
    }
    return null
}

export function validateReason(value: string, required: boolean): string | null {
    const trimmed = value.trim()
    if (required && trimmed.length === 0) {
        return "A reason is required."
    }
    if (trimmed.length > REASON_MAX) {
        return `Reason must be ${REASON_MAX} characters or fewer.`
    }
    return null
}

export function validateLabel(value: string): string | null {
    const trimmed = value.trim()
    if (trimmed.length === 0) {
        return "A label is required."
    }
    if (trimmed.length > LABEL_MAX) {
        return `Label must be ${LABEL_MAX} characters or fewer.`
    }
    return null
}

export function validateRulesetSelection(
    selected: readonly string[],
    defaultRulesetId: string,
): string | null {
    if (selected.length === 0) {
        return "Choose at least one ruleset."
    }
    if (selected.length > MAX_ALLOWED_RULESETS) {
        return `Choose at most ${MAX_ALLOWED_RULESETS} rulesets.`
    }
    if (!selected.includes(defaultRulesetId)) {
        return "The default ruleset must be one of the selected rulesets."
    }
    return null
}

// A stable server error code -> the form field it describes (D15).
export const ERROR_CODE_FIELD: Readonly<Record<string, string>> = {
    ruleset_not_available: "rulesets",
    branch_point_invalid: "branch-point",
    supersession_target_invalid: "replacement",
    parent_location_invalid: "location-parent",
    location_hierarchy_cycle: "location-parent",
    organization_parent_invalid: "org-parent",
    organization_hierarchy_cycle: "org-parent",
    headquarters_location_invalid: "org-headquarters",
    religion_invalid: "org-religion",
}

export function fieldForErrorCode(code: string | null): string | null {
    return code === null ? null : (ERROR_CODE_FIELD[code] ?? null)
}

// Plain-language copy for the stable domain codes a user can act on. Anything
// not listed falls back to the generic per-kind message.
export const ERROR_CODE_MESSAGE: Readonly<Record<string, string>> = {
    ruleset_not_available: "One of the selected rulesets is not available.",
    branch_point_invalid: "That branch point is not valid for this timeline.",
    supersession_target_invalid: "That replacement is not valid for this record.",
    world_archived: "The world is archived. Restore it first.",
    timeline_archived: "The timeline is archived. Restore it first.",
    campaign_archived: "The campaign is archived.",
    world_has_active_campaigns:
        "The world still has active campaigns. Archive them first.",
    timeline_has_active_campaigns:
        "The timeline still has active campaigns. Archive them first.",
    primary_timeline_not_archivable:
        "A world's primary timeline cannot be archived.",
    campaign_access_manager_required:
        "The campaign has no member who can manage its access, so it cannot be reactivated.",
    lifecycle_transition_not_allowed:
        "That change is not allowed from the record's current state.",
    lifecycle_not_supported:
        "This kind of record is not managed through lifecycle actions.",
    entity_referenced: "This record is referenced elsewhere and cannot be deleted.",
    subtype_incomplete: "This record is missing required details.",
    content_not_editable: "This record cannot be edited in its current state.",
    reference_not_published: "A record this one depends on is not published yet.",
    parent_location_invalid: "The selected parent location is not valid. Choose another.",
    location_hierarchy_cycle:
        "That parent would place the location inside itself. Choose a different parent.",
    organization_parent_invalid: "The selected parent organization is not valid. Choose another.",
    organization_hierarchy_cycle:
        "That parent would place the organization inside itself. Choose a different parent.",
    headquarters_location_invalid: "The selected headquarters is not valid. Choose another.",
    religion_invalid: "The selected religion is not valid. Choose another.",
}

// Shared copy and choices for the dungeon editors (Phase 15 checkpoint 15.3A-1).

export const DUNGEON_CODE_MESSAGE: Readonly<Record<string, string>> = {
    connection_invalid:
        "Choose two different areas, and describe the condition of a conditional connection.",
    connection_type_invalid: "Choose a valid connection type.",
    dungeon_not_draft: "Structure can be removed only while the dungeon is a draft.",
    dungeon_limit_reached: "This dungeon has reached its limit for that.",
    state_target_invalid: "That cannot be changed here.",
    clock_required: "Set the campaign time first.",
}

export const YES_NO = [
    { value: "yes", label: "Yes" },
    { value: "no", label: "No" },
]

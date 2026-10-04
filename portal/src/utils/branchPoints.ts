import type { BranchPointOption } from "../types/timelineAuthoring"

// A branch-point option described in words: its label, else its calendar date,
// else its position — never an identifier.
export function describeBranchPoint(option: BranchPointOption): string {
    if (option.label) {
        return option.label
    }
    if (option.year !== null) {
        const parts = [`Year ${option.year}`]
        if (option.month_number !== null) parts.push(`month ${option.month_number}`)
        if (option.day !== null) parts.push(`day ${option.day}`)
        return parts.join(", ")
    }
    return `Unlabeled point (position ${option.sort_key})`
}

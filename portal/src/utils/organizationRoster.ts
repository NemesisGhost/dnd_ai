import type { MemberRow } from "../types/organizationMembers"

// The period cell of a roster row, shared by the editor roster and the reader section.
export function memberPeriodText(m: MemberRow): string {
    if (m.lifecycle_status !== "active") {
        return `Archived (${m.started}${m.ended !== null ? ` to ${m.ended}` : ""})`
    }
    return m.ended !== null ? `${m.started} to ${m.ended}` : `Since ${m.started}`
}

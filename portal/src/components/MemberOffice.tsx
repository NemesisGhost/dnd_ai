import type { MemberRow } from "../types/organizationMembers"

// The office cell of a roster row: the membership's role, then its rank in parentheses. An office is
// text on its membership (decision D-19), so "No office recorded" speaks only for this row.
export function MemberOffice({ member }: { member: MemberRow }) {
    if (member.role === null && member.rank === null) {
        return <span className="member-roster__none">No office recorded</span>
    }
    return (
        <>
            {member.role ?? ""}
            {member.role !== null && member.rank !== null ? " " : ""}
            {member.rank !== null ? <span className="member-roster__rank">({member.rank})</span> : null}
        </>
    )
}

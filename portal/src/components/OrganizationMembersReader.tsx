import { Link } from "react-router"
import { organizationMembersPath } from "../api/organizationMembers"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import type { MemberRow, OrganizationMembers } from "../types/organizationMembers"
import { humanizeCode } from "../utils/humanize"
import { memberPeriodText } from "../utils/organizationRoster"
import { DetailPanel } from "./DetailPanel"
import { MemberOffice } from "./MemberOffice"
import { worldRecordPath } from "./world/worldPaths"

// The player-facing, read-only Members and offices section of an organization's page. It reads the
// roster route, which already filters to what this caller may see (active, public memberships of
// members they can discover, current and ended); it never fetches an editor response and hides
// fields in the browser, and it mounts no authoring control. A withheld membership arrives as
// nothing at all, so the section never counts, hints at or labels a vacancy: an office exists only
// on its membership (decision D-19).

const HEADING_ID = "organization-members-heading"

function memberPath(campaignId: string, m: MemberRow): string | null {
    if (m.can_open !== true || m.category === undefined || m.category === null) return null
    if (m.category === "character") {
        return `/app/${encodeURIComponent(campaignId)}/characters/${encodeURIComponent(m.member_entity_id)}`
    }
    return worldRecordPath(campaignId, m.category, m.member_entity_id)
}

function Row({ campaignId, member }: { campaignId: string; member: MemberRow }) {
    const to = memberPath(campaignId, member)
    return (
        <li className="member-roster__row" aria-label={member.member_name}>
            <span className="member-roster__who">
                <span className="member-roster__name">
                    {to === null ? member.member_name : <Link to={to}>{member.member_name}</Link>}
                </span>{" "}
                <span className="member-roster__type">{humanizeCode(member.member_type_code)}</span>
            </span>
            <span className="member-roster__office">
                <MemberOffice member={member} />
            </span>
            <span className="member-roster__period">
                {memberPeriodText(member)}
                {member.period_status === "ended" ? (
                    <>
                        {" "}
                        <span className="relationship-roster__badge">Ended</span>
                    </>
                ) : null}
                {member.period_status === "not_started" ? (
                    <>
                        {" "}
                        <span className="relationship-roster__badge">Not started</span>
                    </>
                ) : null}
            </span>
        </li>
    )
}

function Reader({ campaignId, organizationId }: { campaignId: string; organizationId: string }) {
    const { state, refetch } = useAuthoringResource<OrganizationMembers>(
        organizationMembersPath(campaignId, organizationId),
    )
    return (
        <DetailPanel title="Members and offices" headingId={HEADING_ID} className="organization-members">
            {state.kind === "loading" ? <p role="status">Loading members…</p> : null}
            {state.kind === "error" ? (
                <div role="alert">
                    <p>Members could not be loaded.</p>
                    <button type="button" className="authoring-button" onClick={() => void refetch()}>
                        Try again
                    </button>
                </div>
            ) : null}
            {state.kind === "denied" || state.kind === "unavailable" ? (
                <div role="alert">
                    <p>Members could not be loaded.</p>
                </div>
            ) : null}
            {state.kind === "ready" ? (
                <div className="member-roster">
                    {state.data.as_of ? <p className="member-roster__as-of">As of {state.data.as_of}</p> : null}
                    {state.data.members.length === 0 ? (
                        <p className="member-roster__empty">No members are known.</p>
                    ) : (
                        <>
                            <div className="member-roster__head" aria-hidden="true">
                                <span>Member</span>
                                <span>Office and rank</span>
                                <span>Period</span>
                            </div>
                            <ul className="member-roster__list">
                                {state.data.members.map((m) => (
                                    <Row key={m.relationship_id} campaignId={campaignId} member={m} />
                                ))}
                            </ul>
                        </>
                    )}
                </div>
            ) : null}
        </DetailPanel>
    )
}

export function OrganizationMembersReader({
    campaignId,
    organizationId,
}: {
    campaignId: string
    organizationId: string
}) {
    // Keyed by the record, so nothing from the previous organization or campaign survives a change.
    return <Reader key={`${campaignId}:${organizationId}`} campaignId={campaignId} organizationId={organizationId} />
}

import { useState } from "react"
import { createRelationship } from "../api/relationshipAuthoring"
import { organizationMembersPath, setOrganizationStatus } from "../api/organizationMembers"
import { fetchWorldEntities } from "../api/world"
import { useSession } from "../context/SessionContext"
import { useAuthoringMutation } from "../hooks/useAuthoringMutation"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import type { CreateRelationshipBody, RelationshipView } from "../types/relationshipAuthoring"
import type { OrganizationMembers as Roster, StatusReceipt } from "../types/organizationMembers"
import { useAnnounce } from "./authoring/announcer"
import { SelectField, TextField } from "./authoring/fields"
import { MutationStatusMessage, StaleWriteNotice } from "./authoring/feedback"
import { ReferenceCombobox } from "./authoring/ReferenceCombobox"
import type { ReferenceOption } from "./authoring/ReferenceCombobox"
import { WorldTimePicker } from "./authoring/WorldTimePicker"
import "./authoring/authoring.css"

interface Props {
    campaignId: string
    organizationId: string
}

const CODE_MESSAGE: Readonly<Record<string, string>> = {
    membership_overlap: "That member already belongs to this organization during that time.",
    membership_start_required: "Choose when the membership began.",
    participant_invalid: "Choose a published character or organization.",
    organization_status_unchanged: "The organization already has that status.",
    clock_required: "Choose a time.",
}

const humanize = (code: string): string => code.replace(/_/g, " ")

// The people and organizations that belong to an organization, with their offices. Everyone who
// can view the organization sees the public, current roster they can discover; an editor also
// sees private and ended stints, can add a member, and can set the organization's operational
// status. Offices are edited in the Relationships panel below (a membership is a relationship).
export function OrganizationMembers({ campaignId, organizationId }: Props) {
    const { state, refetch } = useAuthoringResource<Roster>(
        organizationMembersPath(campaignId, organizationId),
    )
    if (state.kind !== "ready") return null
    const roster = state.data
    return (
        <section className="authoring-aside" aria-labelledby="members-heading">
            <h2 id="members-heading">Members and offices</h2>
            {roster.members.length === 0 ? (
                <p>No members are known.</p>
            ) : (
                <ul className="authoring-choice-list">
                    {roster.members.map((m) => (
                        <li key={m.relationship_id}>
                            {m.member_name}
                            {m.role !== null ? `, ${m.role}` : ""}
                            {m.rank !== null ? ` (${m.rank})` : ""}: from {m.started}
                            {m.ended !== null ? ` until ${m.ended}` : ""}
                            {m.lifecycle_status !== "active" ? " (archived)" : ""}
                            {!m.is_public ? " (private)" : ""}
                        </li>
                    ))}
                </ul>
            )}
            {roster.can_edit ? (
                <>
                    <StatusControl
                        campaignId={campaignId}
                        organizationId={organizationId}
                        roster={roster}
                        onChanged={() => void refetch()}
                    />
                    <AddMember
                        campaignId={campaignId}
                        organizationId={organizationId}
                        onAdded={() => void refetch()}
                    />
                </>
            ) : null}
        </section>
    )
}

function StatusControl({
    campaignId,
    organizationId,
    roster,
    onChanged,
}: {
    campaignId: string
    organizationId: string
    roster: Roster
    onChanged: () => void
}) {
    const { reload } = useSession()
    const announce = useAnnounce()
    const [next, setNext] = useState("")
    const [when, setWhen] = useState("")
    const [problem, setProblem] = useState<string | null>(null)
    const mutation = useAuthoringMutation<
        { world_time_id: string; new_status_code: string; expected_status: string | null },
        StatusReceipt
    >({
        scopeKey: `org-status:${organizationId}`,
        request: (body, ctx) => setOrganizationStatus(campaignId, organizationId, body, ctx),
        onSuccess: () => {
            setNext("")
            onChanged()
            announce("Organization status saved")
        },
    })
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const explained = error?.code ? (CODE_MESSAGE[error.code] ?? null) : null
    return (
        <form
            noValidate
            aria-label="Organization status"
            className="authoring-form"
            onSubmit={(event) => {
                event.preventDefault()
                if (next === "" || when === "") {
                    setProblem("Choose the new status and when it changed.")
                    return
                }
                setProblem(null)
                mutation.submit({ world_time_id: when, new_status_code: next, expected_status: roster.status })
            }}
        >
            <h3>Operational status</h3>
            <p>Now: {roster.status === null ? "not recorded" : humanize(roster.status)}</p>
            {error?.kind === "stale" ? (
                <StaleWriteNotice
                    onLoadLatest={() => {
                        mutation.reset()
                        onChanged()
                    }}
                />
            ) : explained !== null ? (
                <p role="alert">{explained}</p>
            ) : error !== null ? (
                <MutationStatusMessage error={error} onRetry={mutation.retry} onCheckSession={reload} />
            ) : null}
            <SelectField
                id="org-status-next"
                label="New status"
                value={next}
                placeholder="Choose a status"
                options={roster.status_choices}
                error={problem}
                onChange={setNext}
            />
            <WorldTimePicker campaignId={campaignId} id="org-status-time" label="When" value={when} onChange={setWhen} />
            <button type="submit" className="authoring-button" disabled={mutation.status.kind === "pending"}>
                Set status
            </button>
        </form>
    )
}

function AddMember({
    campaignId,
    organizationId,
    onAdded,
}: {
    campaignId: string
    organizationId: string
    onAdded: () => void
}) {
    const { reload } = useSession()
    const announce = useAnnounce()
    const [member, setMember] = useState<ReferenceOption | null>(null)
    const [role, setRole] = useState("")
    const [rank, setRank] = useState("")
    const [isPublic, setIsPublic] = useState("yes")
    const [start, setStart] = useState("")
    const [problem, setProblem] = useState<string | null>(null)
    const mutation = useAuthoringMutation<CreateRelationshipBody, RelationshipView>({
        scopeKey: `add-member:${organizationId}`,
        request: (body, ctx) => createRelationship(campaignId, body, ctx),
        onSuccess: () => {
            setMember(null)
            setRole("")
            setRank("")
            onAdded()
            announce("Member added")
        },
    })
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const explained = error?.code ? (CODE_MESSAGE[error.code] ?? null) : null

    async function search(query: string, signal: AbortSignal): Promise<ReferenceOption[]> {
        const pages = await Promise.all(
            (["character", "organization"] as const).map((category) =>
                fetchWorldEntities(campaignId, { category, query, limit: 10 }, signal),
            ),
        )
        return pages
            .flatMap((page) => page.items)
            .filter((item) => item.entity_id !== organizationId)
            .map((item) => ({
                id: item.entity_id,
                label: item.name,
                detail: item.category === "organization" ? "Organization" : "Character",
            }))
    }

    return (
        <form
            noValidate
            aria-label="Add a member"
            className="authoring-form"
            onSubmit={(event) => {
                event.preventDefault()
                if (member === null || start === "") {
                    setProblem("Choose the member and when they joined.")
                    return
                }
                setProblem(null)
                mutation.submit({
                    kind: "membership",
                    relationship_type: "membership",
                    participants: [
                        { entity_id: member.id, role: "member" },
                        { entity_id: organizationId, role: "organization" },
                    ],
                    description: null,
                    started_world_time_id: start,
                    role: role.trim() === "" ? null : role.trim(),
                    rank: rank.trim() === "" ? null : rank.trim(),
                    is_public: isPublic === "yes",
                })
            }}
        >
            <h3>Add a member</h3>
            {explained !== null ? (
                <p role="alert">{explained}</p>
            ) : error !== null ? (
                <MutationStatusMessage error={error} onRetry={mutation.retry} onCheckSession={reload} />
            ) : null}
            <ReferenceCombobox
                id="member-search"
                label="Member"
                hint="A character or another organization."
                value={member}
                onChange={setMember}
                search={search}
                error={problem}
                placeholder="Search"
            />
            <TextField id="member-office" label="Office or role" value={role} onChange={setRole} />
            <TextField id="member-rank" label="Rank" value={rank} onChange={setRank} />
            <SelectField
                id="member-public"
                label="Known to the public"
                value={isPublic}
                options={[
                    { value: "yes", label: "Yes" },
                    { value: "no", label: "No, only editors see it" },
                ]}
                onChange={setIsPublic}
            />
            <WorldTimePicker campaignId={campaignId} id="member-start" label="Joined" value={start} onChange={setStart} />
            <button type="submit" className="authoring-button" disabled={mutation.status.kind === "pending"}>
                Add member
            </button>
        </form>
    )
}

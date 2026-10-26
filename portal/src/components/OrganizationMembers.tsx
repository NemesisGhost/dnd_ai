import { useEffect, useRef, useState } from "react"
import { createRelationship } from "../api/relationshipAuthoring"
import { organizationMembersPath, setOrganizationStatus } from "../api/organizationMembers"
import { fetchWorldEntities } from "../api/world"
import { useSession } from "../context/SessionContext"
import { useAuthoringMutation } from "../hooks/useAuthoringMutation"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import type { RefetchOutcome } from "../hooks/useAuthoringResource"
import { useConfirmedRefresh } from "../hooks/useConfirmedRefresh"
import type { CreateRelationshipBody, RelationshipView } from "../types/relationshipAuthoring"
import type { OrganizationMembers as Roster, StatusReceipt } from "../types/organizationMembers"
import { useAnnounce } from "./authoring/announcer"
import { SelectField, TextField } from "./authoring/fields"
import { MutationStatusMessage, StaleWriteNotice } from "./authoring/feedback"
import { ReferenceCombobox } from "./authoring/ReferenceCombobox"
import type { ReferenceOption } from "./authoring/ReferenceCombobox"
import { WorldTimePicker } from "./authoring/WorldTimePicker"
import "./authoring/authoring.css"
import { PanelFrame } from "./DetailPanel"
import { StaleReadNotice } from "./StaleReadNotice"
import { useKeptData, useRefetchOnChange } from "../hooks/useKeptData"
import { humanizeCode } from "../utils/humanize"
import { memberPeriodText } from "../utils/organizationRoster"
import { MemberOffice } from "./MemberOffice"
import { OrganizationMemberEditor } from "./OrganizationMemberEditor"

interface Props {
    campaignId: string
    organizationId: string
    // A staged section already supplies the surface and the heading: render the content only.
    embedded?: boolean
    // Changes when the record's status changed elsewhere on the page, so the roster is read again
    // without remounting the panel.
    refreshToken?: unknown
    // Called after a status or a member was recorded, so the page's own view agrees.
    onChanged?: () => void
    // The organization cannot take new members or a status now (not published, archived,
    // replaced): the roster stays readable, the commands are withheld.
    commandsBlocked?: boolean
}

const CODE_MESSAGE: Readonly<Record<string, string>> = {
    membership_overlap: "That member already belongs to this organization during that time.",
    membership_start_required: "Choose when the membership began.",
    participant_invalid: "Choose a published character or organization.",
    organization_status_unchanged: "The organization already has that status.",
    clock_required: "Choose a time.",
}

const humanize = (code: string): string => code.replace(/_/g, " ")

// The people and organizations that belong to an organization, with their offices, as a compact
// roster, for the editors' World workspace (readers get OrganizationMembersReader on the page). An
// editor sees private, ended and archived stints, can add a member, can correct, change the
// office of, or end a membership from its row, and can set the organization's operational status.
// The membership forms and the status form save independently and never reset each other.
export function OrganizationMembers({
    campaignId,
    organizationId,
    embedded,
    refreshToken,
    onChanged,
    commandsBlocked = false,
}: Props) {
    const { state, refetch } = useAuthoringResource<Roster>(
        organizationMembersPath(campaignId, organizationId),
    )
    useRefetchOnChange(refreshToken, refetch)
    const { data: kept, stale } = useKeptData(state)
    // A member or a status was saved: the roster is read again, and its outcome is what the form that
    // sent it reports (a write the roster was not read back for is not announced as done). The page's
    // own view agrees through `onChanged`, which reports its own failure.
    const changed = async (): Promise<RefetchOutcome> => {
        const read = await refetch()
        onChanged?.()
        return read
    }
    // What was saved without the roster being read back. It is kept here, not in the form: the form
    // that sent it closes once the change is saved.
    const [unread, setUnread] = useState<string | null>(null)
    const refreshed = useConfirmedRefresh({
        status: unread === null ? { kind: "idle" } : { kind: "confirmed", refresh: "failed" },
        reset: () => setUnread(null),
        what: "members and status",
        message: unread,
        read: refetch,
        pageStale: stale,
    })
    // The status names the status the roster showed, so nothing is sent from a roster that is behind.
    const writesHeld = refreshed.held || stale
    if (kept === null) {
        // Inside a staged section a missing body would read as "no members", so say why.
        if (embedded !== true) return null
        return state.kind === "loading" ? (
            <p role="status">Loading members…</p>
        ) : (
            <p role="alert">Members could not be loaded.</p>
        )
    }
    const roster = kept
    // Member and office changes edit shared world canon (`can_edit`: a campaign editor who also holds
    // the world Editor capability); the operational status is campaign state (`can_set_status`).
    // A campaign GM with no world role therefore sets the status and reads the same roster an
    // editor does, but is offered no member or office change. An older server sends only `can_edit`.
    const manage = roster.can_edit && !commandsBlocked
    const canSetStatus = (roster.can_set_status ?? roster.can_edit) && !commandsBlocked
    return (
        <PanelFrame embedded={embedded} title="Members and offices" headingId="members-heading">
            {stale ? <StaleReadNotice what="members and status" onRetry={() => void refetch()} /> : null}
            {refreshed.notice}
            <MemberRoster
                campaignId={campaignId}
                organizationId={organizationId}
                roster={roster}
                manage={manage}
                editorView={roster.can_set_status ?? roster.can_edit}
                held={writesHeld}
                onChanged={changed}
                onUnread={setUnread}
            />
            {canSetStatus ? (
                <StatusControl
                    campaignId={campaignId}
                    organizationId={organizationId}
                    roster={roster}
                    held={writesHeld}
                    onChanged={changed}
                    onUnread={setUnread}
                />
            ) : null}
        </PanelFrame>
    )
}

function MemberRoster({
    campaignId,
    organizationId,
    roster,
    manage,
    editorView,
    held,
    onChanged,
    onUnread,
}: {
    campaignId: string
    organizationId: string
    roster: Roster
    manage: boolean
    // The roster includes private and archived stints (a campaign editor's view).
    editorView: boolean
    // The roster shown is behind a change that was just saved, or its latest read failed.
    held: boolean
    onChanged: () => Promise<RefetchOutcome>
    onUnread: (message: string) => void
}) {
    const [adding, setAdding] = useState(false)
    const [editing, setEditing] = useState<string | null>(null)
    const returnTo = useRef<string | null>(null)
    // After a row editor closes, keyboard focus goes back to the row's Edit button.
    useEffect(() => {
        if (editing === null && returnTo.current !== null) {
            document.getElementById(returnTo.current)?.focus()
            returnTo.current = null
        }
    }, [editing])
    const close = (relationshipId: string) => {
        returnTo.current = `member-edit-${relationshipId}`
        setEditing(null)
    }
    return (
        <div className="member-roster">
            <div className="member-roster__bar">
                <h3>Roster</h3>
                {manage ? (
                    <button
                        type="button"
                        className="authoring-button"
                        aria-expanded={adding}
                        aria-controls="member-add-panel"
                        onClick={() => setAdding(!adding)}
                    >
                        Add a member
                    </button>
                ) : null}
            </div>
            {manage && adding ? (
                <div id="member-add-panel">
                    <AddMember
                        campaignId={campaignId}
                        organizationId={organizationId}
                        held={held}
                        onAdded={() => {
                            setAdding(false)
                            return onChanged()
                        }}
                        onUnread={onUnread}
                        onCancel={() => setAdding(false)}
                    />
                </div>
            ) : null}
            {roster.members.length === 0 ? (
                <p className="member-roster__empty">No members are known.</p>
            ) : (
                <>
                    <div
                        className={
                            editorView ? "member-roster__head member-roster__head--editor" : "member-roster__head"
                        }
                        aria-hidden="true"
                    >
                        <span>Member</span>
                        <span>Office and rank</span>
                        {editorView ? <span>Visible to</span> : null}
                        <span>Period</span>
                        {manage ? <span /> : null}
                    </div>
                    <ul className="member-roster__list">
                        {roster.members.map((m) => (
                            <li
                                key={m.relationship_id}
                                className={
                                    editorView
                                        ? "member-roster__row member-roster__row--editor"
                                        : "member-roster__row"
                                }
                                aria-label={m.member_name}
                            >
                                <span className="member-roster__who">
                                    <span className="member-roster__name">{m.member_name}</span>{" "}
                                    <span className="member-roster__type">{humanizeCode(m.member_type_code)}</span>
                                </span>
                                <span className="member-roster__office">
                                    <MemberOffice member={m} />
                                </span>
                                {editorView ? (
                                    <span className="member-roster__visibility">
                                        {m.is_public ? "Public" : "Editors only"}
                                    </span>
                                ) : null}
                                <span className="member-roster__period">
                                    {memberPeriodText(m)}
                                    {m.ended === null && m.lifecycle_status === "active" ? (
                                        <span className="member-roster__state"> (current)</span>
                                    ) : null}
                                </span>
                                {manage ? (
                                    <span className="member-roster__actions">
                                        {m.lifecycle_status === "active" ? (
                                            <button
                                                type="button"
                                                id={`member-edit-${m.relationship_id}`}
                                                className="authoring-button"
                                                aria-expanded={editing === m.relationship_id}
                                                aria-label={`Edit membership of ${m.member_name}`}
                                                onClick={() => {
                                                    if (editing === m.relationship_id) close(m.relationship_id)
                                                    else setEditing(m.relationship_id)
                                                }}
                                            >
                                                {editing === m.relationship_id ? "Close" : "Edit"}
                                            </button>
                                        ) : (
                                            <span className="member-roster__none">Restore in Relationships</span>
                                        )}
                                    </span>
                                ) : null}
                                {manage && editing === m.relationship_id ? (
                                    <OrganizationMemberEditor
                                        campaignId={campaignId}
                                        relationshipId={m.relationship_id}
                                        memberName={m.member_name}
                                        onSaved={() => {
                                            close(m.relationship_id)
                                            return onChanged()
                                        }}
                                        onUnread={onUnread}
                                        onCancel={() => close(m.relationship_id)}
                                    />
                                ) : null}
                            </li>
                        ))}
                    </ul>
                </>
            )}
        </div>
    )
}

function StatusControl({
    campaignId,
    organizationId,
    roster,
    held,
    onChanged,
    onUnread,
}: {
    campaignId: string
    organizationId: string
    roster: Roster
    held: boolean
    onChanged: () => Promise<RefetchOutcome>
    onUnread: (message: string) => void
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
        // The roster panel reports a status it could not read back, with its own notice.
        ownsRefreshNotice: true,
        onSuccess: async () => {
            setNext("")
            const outcome = await onChanged()
            if (outcome === "ok") announce("Organization status saved")
            else onUnread("Organization status saved")
            return outcome
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
                        void onChanged()
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
            <button type="submit" className="authoring-button" disabled={mutation.status.kind === "pending" || held}>
                Set status
            </button>
        </form>
    )
}

function AddMember({
    campaignId,
    organizationId,
    held,
    onAdded,
    onUnread,
    onCancel,
}: {
    campaignId: string
    organizationId: string
    held: boolean
    // Closes the form and reads the roster again; resolves with what that read did.
    onAdded: () => Promise<RefetchOutcome>
    onUnread: (message: string) => void
    onCancel: () => void
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
        // The roster panel reports a member it could not read back, with its own notice.
        ownsRefreshNotice: true,
        onSuccess: async () => {
            setMember(null)
            setRole("")
            setRank("")
            const outcome = await onAdded()
            if (outcome === "ok") announce("Member added")
            else onUnread("Member added")
            return outcome
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
            className="authoring-form member-roster__add"
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
            <div className="authoring-actions">
                <button
                    type="submit"
                    className="authoring-button authoring-button--primary"
                    disabled={mutation.status.kind === "pending" || held}
                >
                    Add member
                </button>
                <button
                    type="button"
                    className="authoring-button"
                    disabled={mutation.status.kind === "pending"}
                    onClick={onCancel}
                >
                    Cancel
                </button>
            </div>
        </form>
    )
}

import { useState } from "react"
import { Link, useParams } from "react-router"
import { addPartyMember, endPartyMembership, partyMembersPath } from "../api/parties"
import { fetchWorldEntities } from "../api/world"
import { ConfirmDialog } from "../components/authoring/ConfirmDialog"
import { useAnnounce } from "../components/authoring/announcer"
import { TextField } from "../components/authoring/fields"
import {
    AuthoringForm,
    ErrorSummary,
    FormActions,
    MutationStatusMessage,
    StaleWriteNotice,
} from "../components/authoring/feedback"
import type { FieldError } from "../components/authoring/feedback"
import { ReferenceCombobox } from "../components/authoring/ReferenceCombobox"
import type { ReferenceOption } from "../components/authoring/ReferenceCombobox"
import { WorldTimePicker } from "../components/authoring/WorldTimePicker"
import { PartyInventoryPanel } from "../components/InventoryPanels"
import { useSession } from "../context/SessionContext"
import { useAuthoringMutation } from "../hooks/useAuthoringMutation"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { usePageArrival } from "../hooks/usePageArrival"
import type { MembershipReceipt, PartyMember, PartyMembers } from "../types/parties"
import "../components/authoring/authoring.css"

const base = (campaignId: string): string => `/app/${encodeURIComponent(campaignId)}`

const CODE_MESSAGE: Readonly<Record<string, string>> = {
    party_membership_overlap: "That character is already a member of this party at that time.",
    party_member_invalid: "That character cannot join: only published characters can.",
    party_membership_end_not_after_start:
        "The end time must be later than when the membership began.",
    party_membership_not_open: "That membership has already ended.",
    party_not_active: "This party is archived. Restore it before adding members.",
    world_time_id_invalid: "That time is not available. Choose another.",
}

// /app/:campaignId/parties/:partyId: who is in the party now, and its history.
// Editors only (the read is a 403 for anyone else). Adding and ending a member
// each record a campaign event at the time the editor chooses.
export function PartyMembersPage() {
    const { campaignId = "", partyId = "" } = useParams()
    const resource = useAuthoringResource<PartyMembers>(partyMembersPath(campaignId, partyId))
    const headingRef = usePageArrival(resource.state.kind === "ready")
    const data = resource.state.kind === "ready" ? resource.state.data : null

    return (
        <section className="authoring-page" aria-labelledby="members-heading">
            <p className="authoring-page__breadcrumb">
                <Link to={`${base(campaignId)}/parties`}>Parties</Link>
            </p>
            <h1 id="members-heading" ref={headingRef} tabIndex={-1}>
                {data !== null ? data.party.name : "Party"}
            </h1>
            {resource.state.kind === "loading" ? (
                <p role="status">Loading members…</p>
            ) : resource.state.kind === "error" ? (
                <p role="alert">The members could not be loaded. Try reloading the page.</p>
            ) : data === null ? (
                <p role="alert">This party does not exist, or you do not have access to it.</p>
            ) : (
                <>
                    {data.party.lifecycle_status === "archived" ? (
                        <p className="authoring-note">
                            This party is archived. Members can be ended but not added.
                        </p>
                    ) : null}
                    <MemberTable
                        campaignId={campaignId}
                        data={data}
                        refetch={resource.refetch}
                        current
                    />
                    {data.party.lifecycle_status === "active" ? (
                        <AddMemberForm
                            campaignId={campaignId}
                            data={data}
                            refetch={resource.refetch}
                        />
                    ) : null}
                    <MemberTable
                        campaignId={campaignId}
                        data={data}
                        refetch={resource.refetch}
                        current={false}
                    />
                    <PartyInventoryPanel campaignId={campaignId} partyId={partyId} />
                </>
            )}
        </section>
    )
}

function MemberTable({
    campaignId,
    data,
    refetch,
    current,
}: {
    campaignId: string
    data: PartyMembers
    refetch: () => Promise<void>
    current: boolean
}) {
    const { reload } = useSession()
    const announce = useAnnounce()
    const rows = data.members.filter((m) => m.is_current === current)
    const [target, setTarget] = useState<PartyMember | null>(null)
    const [timeId, setTimeId] = useState("")
    const [reason, setReason] = useState("")
    const [timeError, setTimeError] = useState<string | null>(null)
    const mutation = useAuthoringMutation<PartyMember, MembershipReceipt>({
        scopeKey: `end-membership:${data.party.party_id}`,
        request: (member, ctx) =>
            endPartyMembership(
                campaignId,
                data.party.party_id,
                member.party_membership_id,
                {
                    effective_to_world_time_id: timeId,
                    expected_party_row_version: data.party.row_version,
                    reason: reason.trim() === "" ? null : reason.trim(),
                },
                ctx,
            ),
        onSuccess: async () => {
            setTarget(null)
            setTimeId("")
            setReason("")
            await refetch()
            announce("Membership ended")
        },
    })
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const message = error?.code ? (CODE_MESSAGE[error.code] ?? null) : null
    const headingId = current ? "current-members-heading" : "member-history-heading"

    return (
        <section aria-labelledby={headingId}>
            <h2 id={headingId}>{current ? "Current members" : "History"}</h2>
            {rows.length === 0 ? (
                <p>{current ? "No current members." : "No past members."}</p>
            ) : (
                <table className="authoring-table">
                    <caption className="visually-hidden">
                        {current ? "Current members" : "Past members"}
                    </caption>
                    <thead>
                        <tr>
                            <th scope="col">Character</th>
                            <th scope="col">Joined</th>
                            {!current ? <th scope="col">Left</th> : null}
                            {current ? (
                                <th scope="col">
                                    <span className="visually-hidden">Actions</span>
                                </th>
                            ) : null}
                        </tr>
                    </thead>
                    <tbody>
                        {rows.map((member) => (
                            <tr key={member.party_membership_id}>
                                <th scope="row">{member.character_name}</th>
                                <td>{member.joined_at}</td>
                                {!current ? <td>{member.left_at}</td> : null}
                                {current ? (
                                    <td>
                                        <button
                                            type="button"
                                            className="authoring-button"
                                            onClick={() => {
                                                mutation.reset()
                                                setTarget(member)
                                            }}
                                        >
                                            End membership of {member.character_name}
                                        </button>
                                    </td>
                                ) : null}
                            </tr>
                        ))}
                    </tbody>
                </table>
            )}
            {current ? (
                <ConfirmDialog
                    open={target !== null}
                    title="End this membership?"
                    description="The character leaves the party at the time you choose. The membership stays in the history of the party."
                    confirmLabel="End membership"
                    pending={mutation.status.kind === "pending"}
                    error={
                        error?.kind === "stale" ? (
                            <StaleWriteNotice
                                onLoadLatest={() => {
                                    mutation.reset()
                                    setTarget(null)
                                    void refetch()
                                }}
                            />
                        ) : message !== null ? (
                            <p role="alert">{message}</p>
                        ) : error !== null ? (
                            <MutationStatusMessage
                                error={error}
                                onRetry={mutation.retry}
                                onCheckSession={reload}
                            />
                        ) : null
                    }
                    reason={{
                        label: "Reason (optional)",
                        required: false,
                        value: reason,
                        onChange: setReason,
                    }}
                    onConfirm={() => {
                        if (timeId === "") {
                            setTimeError("Choose when the membership ends.")
                            return
                        }
                        setTimeError(null)
                        if (target !== null) mutation.submit(target)
                    }}
                    onCancel={() => {
                        setTarget(null)
                        setTimeId("")
                        setReason("")
                        setTimeError(null)
                        mutation.reset()
                    }}
                >
                    <WorldTimePicker
                        campaignId={campaignId}
                        id="end-time"
                        label="Ends at"
                        value={timeId}
                        onChange={(value) => {
                            setTimeId(value)
                            setTimeError(null)
                        }}
                        required
                        error={timeError}
                    />
                </ConfirmDialog>
            ) : null}
        </section>
    )
}

function AddMemberForm({
    campaignId,
    data,
    refetch,
}: {
    campaignId: string
    data: PartyMembers
    refetch: () => Promise<void>
}) {
    const { reload } = useSession()
    const announce = useAnnounce()
    const [character, setCharacter] = useState<ReferenceOption | null>(null)
    const [timeId, setTimeId] = useState("")
    const [reason, setReason] = useState("")
    const [errors, setErrors] = useState<FieldError[]>([])
    const [attempt, setAttempt] = useState(0)
    const mutation = useAuthoringMutation<
        { characterId: string; timeId: string; reason: string | null },
        MembershipReceipt
    >({
        scopeKey: `add-member:${data.party.party_id}`,
        request: (body, ctx) =>
            addPartyMember(
                campaignId,
                data.party.party_id,
                {
                    character_id: body.characterId,
                    effective_from_world_time_id: body.timeId,
                    expected_party_row_version: data.party.row_version,
                    reason: body.reason,
                },
                ctx,
            ),
        onSuccess: async () => {
            setCharacter(null)
            setTimeId("")
            setReason("")
            setErrors([])
            await refetch()
            announce("Member added")
        },
    })
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const message = error?.code ? (CODE_MESSAGE[error.code] ?? null) : null
    const errorFor = (id: string) => errors.find((e) => e.fieldId === id)?.message ?? null

    async function searchCharacters(
        query: string,
        signal: AbortSignal,
    ): Promise<ReferenceOption[]> {
        const page = await fetchWorldEntities(
            campaignId,
            { category: "character", query, limit: 20 },
            signal,
        )
        return page.items.map((item) => ({
            id: item.entity_id,
            label: item.name,
            detail: item.entity_type_code === "player_character" ? "Player character" : "NPC",
        }))
    }

    function submit() {
        const found: FieldError[] = []
        if (character === null) {
            found.push({ fieldId: "member-character", message: "Choose a character." })
        }
        if (timeId === "") {
            found.push({ fieldId: "member-time", message: "Choose when the character joins." })
        }
        setErrors(found)
        setAttempt((n) => n + 1)
        if (found.length > 0 || character === null) return
        mutation.submit({
            characterId: character.id,
            timeId,
            reason: reason.trim() === "" ? null : reason.trim(),
        })
    }

    return (
        <AuthoringForm label="Add a member" onSubmit={submit}>
            <h2>Add a member</h2>
            <ErrorSummary errors={errors} attempt={attempt} />
            {error?.kind === "stale" ? (
                <StaleWriteNotice onLoadLatest={() => void refetch()} />
            ) : message !== null ? (
                <p role="alert">{message}</p>
            ) : error !== null ? (
                <MutationStatusMessage
                    error={error}
                    onRetry={mutation.retry}
                    onCheckSession={reload}
                />
            ) : null}
            <ReferenceCombobox
                id="member-character"
                label="Character"
                hint="Only published characters can join."
                value={character}
                onChange={setCharacter}
                search={searchCharacters}
                error={errorFor("member-character")}
                placeholder="Search characters"
            />
            <WorldTimePicker
                campaignId={campaignId}
                id="member-time"
                label="Joins at"
                value={timeId}
                onChange={setTimeId}
                required
                error={errorFor("member-time")}
            />
            <TextField
                id="member-reason"
                label="Reason"
                hint="Optional. Visible only to people who can edit canon."
                value={reason}
                onChange={setReason}
            />
            <FormActions
                pending={mutation.status.kind === "pending"}
                saveLabel="Add member"
                onCancel={() => {
                    setCharacter(null)
                    setTimeId("")
                    setReason("")
                    setErrors([])
                }}
                cancelLabel="Clear"
            />
        </AuthoringForm>
    )
}

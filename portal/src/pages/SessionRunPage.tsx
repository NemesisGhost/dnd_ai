import { useEffect, useState } from "react"
import { Link, useParams } from "react-router"
import {
    addSessionParticipant,
    endSession,
    logSessionEntry,
    removeSessionParticipant,
    sessionPath,
    startSession,
} from "../api/sessionAuthoring"
import { fetchWorldEntities } from "../api/world"
import { CampaignClockCard } from "../components/CampaignClockCard"
import { ConfirmDialog } from "../components/authoring/ConfirmDialog"
import { useAnnounce } from "../components/authoring/announcer"
import { SelectField, TextAreaField, TextField } from "../components/authoring/fields"
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
import { useSession } from "../context/SessionContext"
import { AwardItemSection } from "../components/AwardItemSection"
import { SessionEncountersSection } from "../components/SessionEncountersSection"
import { TravelSection } from "../components/TravelSection"
import { useAuthoringMutation } from "../hooks/useAuthoringMutation"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { useCampaignCapability } from "../hooks/useCampaignCapability"
import { usePageArrival } from "../hooks/usePageArrival"
import type {
    CampaignSessionDetail,
    PlayReceipt,
    SessionParticipant,
} from "../types/campaignSession"
import "../components/authoring/authoring.css"

const base = (campaignId: string): string => `/app/${encodeURIComponent(campaignId)}`
const ENTRY_MAX = 500
const DETAILS_MAX = 4000

const CODE_MESSAGE: Readonly<Record<string, string>> = {
    clock_required: "Set the campaign time first (the card on this page), or choose a time.",
    another_session_in_progress: "Another session of this campaign is already in progress.",
    session_already_started: "This session has already started.",
    session_not_in_progress: "This session is not in progress.",
    session_not_open: "This session has ended.",
    session_not_active:
        "This session is not active, so it cannot be changed. An archived session must be restored first.",
    session_end_not_after_start: "The end time must be later than when the session began.",
    session_participant_invalid: "That character cannot take part: only published characters can.",
    session_participant_exists: "That character is already in this session.",
    session_participant_removed: "That participant has already been removed.",
    world_time_id_invalid: "That time is not available. Choose another.",
}

const STATUS_LABEL: Readonly<Record<string, string>> = {
    unscheduled: "Not scheduled",
    scheduled: "Scheduled",
    in_progress: "In progress",
    completed: "Completed",
}

// /app/:campaignId/sessions/:sessionId/run: start, participants, log, clock, end.
// Editors only; the server decides every outcome and each write answers with a
// receipt, after which this page refetches the authoritative session.
export function SessionRunPage() {
    const { campaignId = "", sessionId = "" } = useParams()
    const canEdit = useCampaignCapability(campaignId, "canon.edit")
    const detail = useAuthoringResource<CampaignSessionDetail>(sessionPath(campaignId, sessionId))
    const headingRef = usePageArrival(detail.state.kind === "ready")
    const data = detail.state.kind === "ready" ? detail.state.data : null

    return (
        <section className="authoring-page" aria-labelledby="run-session-heading">
            <p className="authoring-page__breadcrumb">
                <Link to={`${base(campaignId)}/sessions`}>Sessions</Link>
            </p>
            <h1 id="run-session-heading" ref={headingRef} tabIndex={-1}>
                {data !== null ? `Run: ${data.title ?? `Session ${data.session_number}`}` : "Run session"}
            </h1>
            {!canEdit ? (
                <p role="alert">You do not have permission to run sessions in this campaign.</p>
            ) : detail.state.kind === "loading" ? (
                <p role="status">Loading session…</p>
            ) : data === null ? (
                <p role="alert">This session does not exist, or you do not have access to it.</p>
            ) : (
                <RunBody campaignId={campaignId} session={data} refetch={detail.refetch} />
            )}
        </section>
    )
}

function RunBody({
    campaignId,
    session,
    refetch,
}: {
    campaignId: string
    session: CampaignSessionDetail
    refetch: () => Promise<void>
}) {
    const actions = session.available_actions ?? []
    const status = session.play_status ?? "unscheduled"
    return (
        <>
            <p>
                Status: <strong>{STATUS_LABEL[status] ?? status}</strong>
                {session.status_code === "archived" ? " (archived)" : ""}
            </p>
            <CampaignClockCard campaignId={campaignId} />
            {actions.includes("start") ? (
                <StartControl campaignId={campaignId} session={session} refetch={refetch} />
            ) : null}
            {session.status_code !== "active" && session.status_code !== "archived" ? (
                <p role="status">
                    This session is not active, so it cannot be started or changed.
                </p>
            ) : null}
            <Participants
                campaignId={campaignId}
                session={session}
                refetch={refetch}
                canManage={actions.includes("manage_participants")}
            />
            {actions.includes("log") ? (
                <TravelSection campaignId={campaignId} participants={session.participants ?? []} />
            ) : null}
            {actions.includes("log") ? (
                <AwardItemSection campaignId={campaignId} participants={session.participants ?? []} />
            ) : null}
            {actions.includes("log") ? (
                <SessionEncountersSection campaignId={campaignId} sessionId={session.session_id} />
            ) : null}
            <LogSection
                campaignId={campaignId}
                session={session}
                refetch={refetch}
                canLog={actions.includes("log")}
            />
            {actions.includes("end") ? (
                <EndControl campaignId={campaignId} session={session} refetch={refetch} />
            ) : null}
        </>
    )
}

function useMessage(error: { code?: string | null } | null): string | null {
    return error?.code ? (CODE_MESSAGE[error.code] ?? null) : null
}

function StartControl({
    campaignId,
    session,
    refetch,
}: {
    campaignId: string
    session: CampaignSessionDetail
    refetch: () => Promise<void>
}) {
    const { reload } = useSession()
    const announce = useAnnounce()
    const [timeId, setTimeId] = useState("")
    const mutation = useAuthoringMutation<void, PlayReceipt>({
        scopeKey: `start-session:${session.session_id}:${session.row_version ?? 0}`,
        request: (_unused, ctx) =>
            startSession(
                campaignId,
                session.session_id,
                {
                    expected_row_version: session.row_version ?? 1,
                    start_world_time_id: timeId === "" ? null : timeId,
                },
                ctx,
            ),
        onSuccess: async () => {
            await refetch()
            announce("Session started")
        },
    })
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const message = useMessage(error)
    return (
        <section className="session-run-start" aria-labelledby="start-heading">
            <h2 id="start-heading">Start</h2>
            <WorldTimePicker
                campaignId={campaignId}
                id="start-time"
                label="Starts at"
                hint="Leave empty to use the campaign time."
                value={timeId}
                onChange={setTimeId}
            />
            {error?.kind === "stale" ? (
                <StaleWriteNotice onLoadLatest={() => void refetch()} />
            ) : message !== null ? (
                <p role="alert">{message}</p>
            ) : error !== null ? (
                <MutationStatusMessage error={error} onRetry={mutation.retry} onCheckSession={reload} />
            ) : null}
            <button
                type="button"
                className="authoring-button authoring-button--primary"
                disabled={mutation.status.kind === "pending"}
                onClick={() => mutation.submit()}
            >
                Start session
            </button>
        </section>
    )
}

function Participants({
    campaignId,
    session,
    refetch,
    canManage,
}: {
    campaignId: string
    session: CampaignSessionDetail
    refetch: () => Promise<void>
    canManage: boolean
}) {
    const { reload } = useSession()
    const announce = useAnnounce()
    const [character, setCharacter] = useState<ReferenceOption | null>(null)
    const [role, setRole] = useState("guest")
    const [errors, setErrors] = useState<FieldError[]>([])
    const [attempt, setAttempt] = useState(0)
    const participants = session.participants ?? []
    const present = participants.filter((p) => p.removed_at === null)
    const gone = participants.filter((p) => p.removed_at !== null)

    const add = useAuthoringMutation<{ characterId: string; role: string }, PlayReceipt>({
        scopeKey: `add-participant:${session.session_id}`,
        request: (body, ctx) =>
            addSessionParticipant(
                campaignId,
                session.session_id,
                {
                    expected_row_version: session.row_version ?? 1,
                    character_id: body.characterId,
                    participation_role: body.role,
                },
                ctx,
            ),
        onSuccess: async () => {
            setCharacter(null)
            setErrors([])
            await refetch()
            announce("Participant added")
        },
    })
    const remove = useAuthoringMutation<SessionParticipant, PlayReceipt>({
        scopeKey: `remove-participant:${session.session_id}`,
        request: (participant, ctx) =>
            removeSessionParticipant(
                campaignId,
                session.session_id,
                participant.session_participant_id,
                { expected_row_version: session.row_version ?? 1 },
                ctx,
            ),
        onSuccess: async () => {
            await refetch()
            announce("Participant removed")
        },
    })
    const addError = add.status.kind === "error" ? add.status.error : null
    const removeError = remove.status.kind === "error" ? remove.status.error : null
    const addMessage = useMessage(addError)
    const removeMessage = useMessage(removeError)
    const presentIds = new Set(present.map((p) => p.character_id))

    // A duplicate means the roster this page shows is out of date: reload it. The
    // failure stays on screen (the mutation scope does not follow the row version).
    useEffect(() => {
        if (addError?.code === "session_participant_exists") {
            void refetch()
        }
    }, [addError, refetch])

    async function searchCharacters(query: string, signal: AbortSignal): Promise<ReferenceOption[]> {
        const page = await fetchWorldEntities(
            campaignId,
            { category: "character", query, limit: 20 },
            signal,
        )
        return page.items
            .filter((item) => !presentIds.has(item.entity_id))
            .map((item) => ({
                id: item.entity_id,
                label: item.name,
                detail: item.entity_type_code === "player_character" ? "Player character" : "NPC",
            }))
    }

    function submit() {
        if (character === null) {
            setErrors([{ fieldId: "participant-character", message: "Choose a character." }])
            setAttempt((n) => n + 1)
            return
        }
        if (presentIds.has(character.id)) {
            setErrors([{ fieldId: "participant-character", message: CODE_MESSAGE.session_participant_exists! }])
            setAttempt((n) => n + 1)
            return
        }
        setErrors([])
        add.submit({ characterId: character.id, role })
    }

    return (
        <section aria-labelledby="participants-heading">
            <h2 id="participants-heading">Participants</h2>
            {present.length === 0 ? (
                <p>No one is in this session yet.</p>
            ) : (
                <ul className="authoring-choice-list">
                    {present.map((p) => (
                        <li key={p.session_participant_id}>
                            {p.character_name} ({p.participation_role.replace("_", " ")}){" "}
                            {canManage ? (
                                <button
                                    type="button"
                                    className="authoring-button"
                                    onClick={() => {
                                        remove.reset()
                                        remove.submit(p)
                                    }}
                                >
                                    Remove {p.character_name}
                                </button>
                            ) : null}
                        </li>
                    ))}
                </ul>
            )}
            {removeError?.kind === "stale" ? (
                <StaleWriteNotice
                    onLoadLatest={() => {
                        // Clear the notice only once the new version is in, so a resubmit can't reuse the old one.
                        void refetch().then(() => remove.reset())
                    }}
                />
            ) : removeMessage !== null ? (
                <p role="alert">{removeMessage}</p>
            ) : removeError !== null ? (
                <MutationStatusMessage
                    error={removeError}
                    onRetry={remove.retry}
                    onCheckSession={reload}
                />
            ) : null}
            {gone.length > 0 ? (
                <p className="authoring-note">
                    Left: {gone.map((p) => p.character_name).join(", ")}
                </p>
            ) : null}
            {canManage ? (
                <AuthoringForm label="Add a participant" onSubmit={submit}>
                    <ErrorSummary errors={errors} attempt={attempt} />
                    {addError?.kind === "stale" ? (
                        <StaleWriteNotice
                            onLoadLatest={() => {
                                // Clear the notice only once the new version is in, so a resubmit can't reuse the old one.
                                void refetch().then(() => add.reset())
                            }}
                        />
                    ) : addMessage !== null ? (
                        <p role="alert">{addMessage}</p>
                    ) : addError !== null ? (
                        <MutationStatusMessage error={addError} onRetry={add.retry} onCheckSession={reload} />
                    ) : null}
                    <ReferenceCombobox
                        id="participant-character"
                        label="Character"
                        hint="Only published characters can take part."
                        value={character}
                        onChange={setCharacter}
                        search={searchCharacters}
                        error={errors.find((e) => e.fieldId === "participant-character")?.message ?? null}
                        placeholder="Search characters"
                    />
                    <SelectField
                        id="participant-role"
                        label="Role"
                        value={role}
                        options={[
                            { value: "player_character", label: "Player character" },
                            { value: "npc", label: "NPC" },
                            { value: "guest", label: "Guest" },
                        ]}
                        onChange={setRole}
                    />
                    <FormActions
                        pending={add.status.kind === "pending"}
                        saveLabel="Add participant"
                        onCancel={() => setCharacter(null)}
                        cancelLabel="Clear"
                    />
                </AuthoringForm>
            ) : null}
        </section>
    )
}

function LogSection({
    campaignId,
    session,
    refetch,
    canLog,
}: {
    campaignId: string
    session: CampaignSessionDetail
    refetch: () => Promise<void>
    canLog: boolean
}) {
    const { reload } = useSession()
    const announce = useAnnounce()
    const [entry, setEntry] = useState("")
    const [details, setDetails] = useState("")
    const [timeId, setTimeId] = useState("")
    const [errors, setErrors] = useState<FieldError[]>([])
    const [attempt, setAttempt] = useState(0)
    const mutation = useAuthoringMutation<
        { entry: string; details: string | null; timeId: string | null },
        PlayReceipt
    >({
        scopeKey: `log-entry:${session.session_id}`,
        request: (body, ctx) =>
            logSessionEntry(
                campaignId,
                session.session_id,
                { entry: body.entry, details: body.details, world_time_id: body.timeId },
                ctx,
            ),
        onSuccess: async () => {
            setEntry("")
            setDetails("")
            setErrors([])
            await refetch()
            announce("Entry recorded")
        },
    })
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const message = useMessage(error)
    const errorFor = (id: string) => errors.find((e) => e.fieldId === id)?.message ?? null

    function submit() {
        const found: FieldError[] = []
        if (entry.trim() === "") {
            found.push({ fieldId: "log-entry", message: "Enter what happened." })
        } else if (entry.trim().length > ENTRY_MAX) {
            found.push({ fieldId: "log-entry", message: `Entry must be ${ENTRY_MAX} characters or fewer.` })
        }
        if (details.trim().length > DETAILS_MAX) {
            found.push({ fieldId: "log-details", message: `Details must be ${DETAILS_MAX} characters or fewer.` })
        }
        setErrors(found)
        setAttempt((n) => n + 1)
        if (found.length > 0) return
        mutation.submit({
            entry: entry.trim(),
            details: details.trim() === "" ? null : details.trim(),
            timeId: timeId === "" ? null : timeId,
        })
    }

    return (
        <section aria-labelledby="log-heading">
            <h2 id="log-heading">Log</h2>
            {session.events.length === 0 ? (
                <p>Nothing has been recorded yet.</p>
            ) : (
                <ol className="authoring-choice-list" aria-label="Session log">
                    {session.events.map((event) => (
                        <li key={event.event_id}>
                            <Link
                                to={`${base(campaignId)}/events/${encodeURIComponent(event.event_id)}`}
                            >
                                {event.name}
                            </Link>
                            {event.details !== null ? (
                                <p className="authoring-note">GM notes: {event.details}</p>
                            ) : null}
                        </li>
                    ))}
                </ol>
            )}
            {canLog ? (
                <AuthoringForm label="Record an entry" onSubmit={submit}>
                    <ErrorSummary errors={errors} attempt={attempt} />
                    {message !== null ? (
                        <p role="alert">{message}</p>
                    ) : error !== null ? (
                        <MutationStatusMessage error={error} onRetry={mutation.retry} onCheckSession={reload} />
                    ) : null}
                    <TextField
                        id="log-entry"
                        label="What happened"
                        hint="Visible to everyone in the campaign."
                        value={entry}
                        onChange={setEntry}
                        required
                        maxLength={ENTRY_MAX}
                        error={errorFor("log-entry")}
                    />
                    <TextAreaField
                        id="log-details"
                        label="GM notes"
                        hint="Visible only to people who can edit canon."
                        value={details}
                        onChange={setDetails}
                        maxLength={DETAILS_MAX}
                        error={errorFor("log-details")}
                    />
                    <WorldTimePicker
                        campaignId={campaignId}
                        id="log-time"
                        label="When"
                        hint="Leave empty to use the campaign time."
                        value={timeId}
                        onChange={setTimeId}
                    />
                    <FormActions
                        pending={mutation.status.kind === "pending"}
                        saveLabel="Record entry"
                        pendingLabel="Recording…"
                        onCancel={() => {
                            setEntry("")
                            setDetails("")
                            setErrors([])
                        }}
                        cancelLabel="Clear"
                    />
                </AuthoringForm>
            ) : null}
        </section>
    )
}

function EndControl({
    campaignId,
    session,
    refetch,
}: {
    campaignId: string
    session: CampaignSessionDetail
    refetch: () => Promise<void>
}) {
    const { reload } = useSession()
    const announce = useAnnounce()
    const [open, setOpen] = useState(false)
    const [timeId, setTimeId] = useState("")
    const [recap, setRecap] = useState("")
    const mutation = useAuthoringMutation<void, PlayReceipt>({
        scopeKey: `end-session:${session.session_id}:${session.row_version ?? 0}`,
        request: (_unused, ctx) =>
            endSession(
                campaignId,
                session.session_id,
                {
                    expected_row_version: session.row_version ?? 1,
                    end_world_time_id: timeId === "" ? null : timeId,
                    summary: recap.trim() === "" ? null : recap.trim(),
                },
                ctx,
            ),
        onSuccess: async () => {
            setOpen(false)
            await refetch()
            announce("Session ended")
        },
    })
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const message = useMessage(error)
    return (
        <section aria-labelledby="end-heading">
            <h2 id="end-heading">End</h2>
            <button
                type="button"
                className="authoring-button"
                onClick={() => {
                    mutation.reset()
                    setOpen(true)
                }}
            >
                End session
            </button>
            <ConfirmDialog
                open={open}
                title="End this session?"
                description="The session is marked as completed and no more entries or participants can be added."
                confirmLabel="End session"
                pending={mutation.status.kind === "pending"}
                error={
                    error?.kind === "stale" ? (
                        <StaleWriteNotice
                            onLoadLatest={() => {
                                mutation.reset()
                                setOpen(false)
                                void refetch()
                            }}
                        />
                    ) : message !== null ? (
                        <p role="alert">{message}</p>
                    ) : error !== null ? (
                        <MutationStatusMessage error={error} onRetry={mutation.retry} onCheckSession={reload} />
                    ) : null
                }
                onConfirm={() => mutation.submit()}
                onCancel={() => {
                    setOpen(false)
                    mutation.reset()
                }}
            >
                <TextAreaField
                    id="end-recap"
                    label="Recap"
                    hint="Optional. Visible to everyone in the campaign."
                    value={recap}
                    onChange={setRecap}
                />
                <WorldTimePicker
                    campaignId={campaignId}
                    id="end-time-run"
                    label="Ends at"
                    hint="Leave empty to use the campaign time."
                    value={timeId}
                    onChange={setTimeId}
                />
            </ConfirmDialog>
        </section>
    )
}

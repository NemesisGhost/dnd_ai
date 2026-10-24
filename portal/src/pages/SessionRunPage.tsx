import { useEffect, useRef, useState } from "react"
import type { ReactNode } from "react"
import { Link, useParams } from "react-router"
import {
    endSession,
    logSessionEntry,
    removeSessionParticipant,
    sessionPath,
    startSession,
} from "../api/sessionAuthoring"
import { sessionEncountersPath } from "../api/encounters"
import { CampaignClockCard } from "../components/CampaignClockCard"
import { ConfirmDialog } from "../components/authoring/ConfirmDialog"
import { useAnnounce } from "../components/authoring/announcer"
import { TextAreaField, TextField } from "../components/authoring/fields"
import {
    AuthoringForm,
    ErrorSummary,
    FormActions,
    MutationStatusMessage,
    StaleWriteNotice,
} from "../components/authoring/feedback"
import type { FieldError } from "../components/authoring/feedback"
import { WorldTimePicker } from "../components/authoring/WorldTimePicker"
import { useSession } from "../context/SessionContext"
import { AwardItemSection } from "../components/AwardItemSection"
import { EncounterList } from "../components/EncounterList"
import { TravelSection } from "../components/TravelSection"
import { SessionEventList } from "../components/sessionRun/SessionActivity"
import { RunBreadcrumb, RunSectionNav, RunSectionPanel, RunStageNav } from "../components/sessionRun/RunNav"
import { CODE_MESSAGE } from "../components/sessionRun/runMessages"
import { ParticipantForm } from "../components/sessionRun/ParticipantForm"
import { RealWorldTime, SessionReview } from "../components/sessionRun/SessionReview"
import { SECTIONS, panelHeadingId } from "../components/sessionRun/runStages"
import type { SectionKey } from "../components/sessionRun/runStages"
import { useRunNavigation } from "../components/sessionRun/useRunNavigation"
import { useAuthoringMutation } from "../hooks/useAuthoringMutation"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import type { RefetchOutcome } from "../hooks/useAuthoringResource"
import { useCampaignCapability } from "../hooks/useCampaignCapability"
import { usePageArrival } from "../hooks/usePageArrival"
import type { EncounterSummary } from "../types/encounters"
import type {
    CampaignSessionDetail,
    PlayReceipt,
    SessionParticipant,
} from "../types/campaignSession"
import "../components/authoring/authoring.css"

const base = (campaignId: string): string => `/app/${encodeURIComponent(campaignId)}`
const ENTRY_MAX = 500
const DETAILS_MAX = 4000

const STATUS_LABEL: Readonly<Record<string, string>> = {
    unscheduled: "Not scheduled",
    scheduled: "Scheduled",
    in_progress: "In progress",
    completed: "Completed",
}

// /app/:campaignId/sessions/:sessionId/run[?section=…]: prepare, run and wrap up a session.
// Editors only; the server decides every outcome and each write answers with a receipt, after
// which this page refetches the authoritative session. The stages and sections are navigation
// only (the address holds the section): choosing one never acts on the session, and every
// section stays mounted so unfinished input survives a switch.
export function SessionRunPage() {
    const { campaignId = "", sessionId = "" } = useParams()
    const canEdit = useCampaignCapability(campaignId, "canon.edit")
    const detail = useAuthoringResource<CampaignSessionDetail>(sessionPath(campaignId, sessionId))
    const headingRef = usePageArrival(detail.state.kind === "ready")
    // A refresh that fails for a reason worth retrying keeps the last session that loaded on
    // screen, so the drafts in every section survive; missing or denied still fail closed.
    const [lastGood, setLastGood] = useState<CampaignSessionDetail | null>(null)
    if (detail.state.kind === "ready" && detail.state.data !== lastGood) {
        setLastGood(detail.state.data)
    }
    const refreshFailed = detail.state.kind === "error" && detail.state.retryable && lastGood !== null
    const data = detail.state.kind === "ready" ? detail.state.data : refreshFailed ? lastGood : null

    return (
        <section className="authoring-page" aria-labelledby="run-session-heading">
            <RunBreadcrumb
                campaignId={campaignId}
                sessionId={sessionId}
                title={data !== null ? (data.title ?? `Session ${data.session_number}`) : null}
            />
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
                <>
                    {refreshFailed ? (
                        <p role="alert">
                            The latest session data could not be loaded, so what you see may be out of date.{" "}
                            <button type="button" className="authoring-button" onClick={() => void detail.refetch()}>
                                Try again
                            </button>
                        </p>
                    ) : null}
                    <RunBody
                        campaignId={campaignId}
                        session={data}
                        refetch={detail.refetch}
                        refreshFailed={refreshFailed}
                    />
                </>
            )}
        </section>
    )
}

// Why a play action is not offered, in the session's own terms.
function whyNotPlayable(session: CampaignSessionDetail, doing: string): string {
    if (session.status_code !== "active") {
        return "This session is not active, so it cannot be changed. An archived session must be restored first."
    }
    return (session.play_status ?? "unscheduled") === "completed"
        ? `This session has ended, so you can no longer ${doing}.`
        : `Start the session to ${doing}.`
}

function RunBody({
    campaignId,
    session,
    refetch,
    refreshFailed,
}: {
    campaignId: string
    session: CampaignSessionDetail
    refetch: () => Promise<RefetchOutcome>
    // True when the latest read failed and `session` is the last one that loaded.
    refreshFailed: boolean
}) {
    const actions = session.available_actions ?? []
    const status = session.play_status ?? "unscheduled"
    const nav = useRunNavigation(session)
    const encounterList = useAuthoringResource<{ items: EncounterSummary[] }>(
        sessionEncountersPath(campaignId, session.session_id),
    )
    const encounters = encounterList.state.kind === "ready" ? encounterList.state.data.items : null
    const [notice, setNotice] = useState<"started" | "ended" | null>(null)
    const canLog = actions.includes("log")
    const participants = session.participants ?? []

    // Move focus to the section heading when the section changes after arrival (a link, Back or
    // Forward), so a keyboard or screen reader user lands on the new content.
    const lastSection = useRef(nav.section)
    useEffect(() => {
        if (lastSection.current !== nav.section) {
            lastSection.current = nav.section
            document.getElementById(panelHeadingId(nav.section))?.focus()
        }
    }, [nav.section])

    const canPrepareEncounters = session.status_code === "active" && status !== "completed"
    const pending = (encounters ?? []).filter((e) => e.status === "pending")
    const started = (encounters ?? []).filter((e) => e.status !== "pending")
    const logReason = whyNotPlayable(session, "record entries")
    const encountersList = (empty: string, items: EncounterSummary[]) =>
        encounterList.state.kind === "loading" ? (
            <p role="status">Loading encounters…</p>
        ) : encounters === null ? (
            <p role="alert">Encounters could not be loaded.</p>
        ) : (
            <EncounterList
                campaignId={campaignId}
                sessionId={session.session_id}
                items={items}
                emptyText={empty}
                prepareLink={canPrepareEncounters}
            />
        )

    const body: Record<SectionKey, ReactNode> = {
        participants: (
            <>
                {actions.includes("start") ? (
                    <p className="authoring-note">When the table is ready, go to Run session to start.</p>
                ) : null}
                <Participants
                    campaignId={campaignId}
                    session={session}
                    refetch={refetch}
                    refreshFailed={refreshFailed}
                    canManage={actions.includes("manage_participants")}
                />
            </>
        ),
        "encounter-prep": !canPrepareEncounters ? (
            <p className="authoring-note">
                {session.status_code !== "active"
                    ? "This session is not active, so encounters cannot be prepared."
                    : "This session has ended, so encounters can no longer be prepared."}
            </p>
        ) : (
            <>
                {encountersList("No encounter is waiting to be started.", pending)}
                {started.length > 0 ? (
                    <p>
                        <Link to={nav.sectionHref("encounters")}>
                            {started.length} started or finished: see Encounters
                        </Link>
                    </p>
                ) : null}
            </>
        ),
        log: (
            <LogSection
                campaignId={campaignId}
                session={session}
                refetch={refetch}
                canLog={canLog}
                reason={logReason}
            />
        ),
        travel: (
            <TravelSection
                campaignId={campaignId}
                sessionId={session.session_id}
                participants={participants}
                travel={session.travel ?? []}
                refetch={refetch}
                refreshFailed={refreshFailed}
                canRecord={canLog}
                reason={whyNotPlayable(session, "record travel")}
                active={nav.section === "travel"}
                eventHref={(id) => `${base(campaignId)}/events/${encodeURIComponent(id)}`}
                showHeading={false}
            />
        ),
        "award-item": canLog ? (
            <AwardItemSection campaignId={campaignId} participants={participants} showHeading={false} />
        ) : (
            <p className="authoring-note">{whyNotPlayable(session, "award items")}</p>
        ),
        encounters: (
            <>
                {encountersList("No encounter has started yet.", started)}
                {pending.length > 0 ? (
                    <p>
                        <Link to={nav.sectionHref("encounter-prep")}>
                            {pending.length} prepared and waiting: see Encounter preparation
                        </Link>
                    </p>
                ) : null}
            </>
        ),
        review: (
            <SessionReview
                campaignId={campaignId}
                session={session}
                encounters={encounters}
                sectionHref={nav.sectionHref}
                canPrepareEncounters={canPrepareEncounters}
                reasonLog={logReason}
                reasonTravel={whyNotPlayable(session, "record travel")}
            />
        ),
        end: actions.includes("end") ? (
            <EndControl
                campaignId={campaignId}
                session={session}
                refetch={refetch}
                onEnded={() => setNotice("ended")}
            />
        ) : (
            <>
                {notice === "ended" ? (
                    <p role="status">
                        Session ended. <Link to={nav.sectionHref("review")}>Go to the session review</Link>
                    </p>
                ) : null}
                <p className="authoring-note">
                    {session.status_code !== "active"
                        ? "This session is not active, so it cannot be changed."
                        : status === "completed"
                          ? "This session has ended."
                          : "The session has not started, so there is nothing to end yet."}
                </p>
            </>
        ),
    }

    return (
        <>
            <p>
                Status: <strong>{STATUS_LABEL[status] ?? status}</strong>
                {session.status_code === "archived" ? " (archived)" : ""}
                {session.started_at ? (
                    <>
                        {" · "}
                        <RealWorldTime label="Real-world start" value={session.started_at} />
                    </>
                ) : null}
                {session.ended_at ? (
                    <>
                        {" · "}
                        <RealWorldTime label="Real-world end" value={session.ended_at} />
                    </>
                ) : null}
            </p>
            {session.status_code !== "active" && session.status_code !== "archived" ? (
                <p role="status">This session is not active, so it cannot be started or changed.</p>
            ) : null}
            <CampaignClockCard campaignId={campaignId} variant="compact" actionsVisible={nav.stage === "run"} />
            <RunStageNav current={nav.stage} hrefFor={nav.stageHref} />
            <div className="staged-workspace">
                <div className="session-run__layout">
                    <RunSectionNav stage={nav.stage} current={nav.section} hrefFor={nav.sectionHref} />
                    <div className="session-run__content">
                        <div hidden={nav.stage !== "run"}>
                            {actions.includes("start") ? (
                                <StartControl
                                    campaignId={campaignId}
                                    session={session}
                                    refetch={refetch}
                                    onStarted={() => setNotice("started")}
                                />
                            ) : null}
                            {notice === "started" ? (
                                <p role="status">
                                    Session started. <Link to={nav.sectionHref("log")}>Go to the session log</Link>
                                </p>
                            ) : null}
                        </div>
                        {SECTIONS.map((section) => (
                            <RunSectionPanel key={section.key} section={section} active={section.key === nav.section}>
                                {body[section.key]}
                            </RunSectionPanel>
                        ))}
                    </div>
                </div>
            </div>
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
    onStarted,
}: {
    campaignId: string
    session: CampaignSessionDetail
    refetch: () => Promise<unknown>
    onStarted: () => void
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
            onStarted()
        },
    })
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const message = useMessage(error)
    return (
        <section className="session-run-start" aria-labelledby="start-heading">
            <h2 id="start-heading">Start the session</h2>
            <p className="authoring-page__lead">This session has not started. Start it when the table is ready.</p>
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
    refreshFailed,
    canManage,
}: {
    campaignId: string
    session: CampaignSessionDetail
    refetch: () => Promise<RefetchOutcome>
    // The latest read failed and `session` is the last one that loaded: its version may be behind.
    refreshFailed: boolean
    canManage: boolean
}) {
    const { reload } = useSession()
    const announce = useAnnounce()
    const participants = session.participants ?? []
    const present = participants.filter((p) => p.removed_at === null)
    const gone = participants.filter((p) => p.removed_at !== null)

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
            if ((await refetch()) === "failed") {
                return "failed"
            }
            announce("Participant removed")
        },
    })
    const removeError = remove.status.kind === "error" ? remove.status.error : null
    const removeMessage = useMessage(removeError)
    const presentIds = new Set(present.map((p) => p.character_id))

    return (
        <>
            {present.length === 0 ? (
                <p>No one is in this session yet.</p>
            ) : (
                <ul className="op-list">
                    {present.map((p) => (
                        <li key={p.session_participant_id}>
                            {p.character_name} ({p.participation_role.replace("_", " ")}){" "}
                            {canManage ? (
                                <button
                                    type="button"
                                    className="authoring-button"
                                    disabled={refreshFailed}
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
                <ParticipantForm
                    campaignId={campaignId}
                    session={session}
                    presentCharacterIds={presentIds}
                    refetch={refetch}
                    refreshFailed={refreshFailed}
                />
            ) : (
                <p className="authoring-note">
                    {session.status_code !== "active"
                        ? "This session is not active, so participants cannot be changed."
                        : "Participants can't be changed after the session ends."}
                </p>
            )}
        </>
    )
}

function LogSection({
    campaignId,
    session,
    refetch,
    canLog,
    reason,
}: {
    campaignId: string
    session: CampaignSessionDetail
    refetch: () => Promise<unknown>
    canLog: boolean
    reason: string
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
        <>
            {session.events.length === 0 ? (
                <p>Nothing has been recorded yet.</p>
            ) : (
                <SessionEventList
                    events={session.events}
                    travel={session.travel}
                    label="Session log"
                    ordered
                    eventHref={(id) => `${base(campaignId)}/events/${encodeURIComponent(id)}`}
                />
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
            ) : (
                <p className="authoring-note">{reason}</p>
            )}
        </>
    )
}

function EndControl({
    campaignId,
    session,
    refetch,
    onEnded,
}: {
    campaignId: string
    session: CampaignSessionDetail
    refetch: () => Promise<unknown>
    onEnded: () => void
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
            onEnded()
        },
    })
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const message = useMessage(error)
    return (
        <>
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
        </>
    )
}

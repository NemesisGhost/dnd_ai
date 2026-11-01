import { useState } from "react"
import { Link, useParams } from "react-router"
import { campaignCalendarsPath, fetchWorldTimes, worldTimesPath } from "../api/worldTime"
import { ConfirmDialog } from "../components/authoring/ConfirmDialog"
import { SavedNotice } from "../components/authoring/feedback"
import { FormDialog } from "../components/authoring/FormDialog"
import type { FormDialogPrompt } from "../components/authoring/FormDialog"
import { WorldTimeForm } from "../components/authoring/WorldTimeForm"
import { useAnnounce } from "../components/authoring/announcer"
import { StaleReadNotice } from "../components/StaleReadNotice"
import { retryFailedReads, useAuthoringResource } from "../hooks/useAuthoringResource"
import type { RefetchOutcome } from "../hooks/useAuthoringResource"
import type { AuthoringMutationStatus } from "../hooks/useAuthoringMutation"
import { useConfirmedRefresh, useUnreadWrite } from "../hooks/useConfirmedRefresh"
import { useUnsavedChangesGuard } from "../hooks/useUnsavedChangesGuard"
import { useKept } from "../hooks/useKeptResource"
import { useCampaignCapability } from "../hooks/useCampaignCapability"
import { usePageArrival } from "../hooks/usePageArrival"
import type { CalendarListResponse, WorldTimeItem, WorldTimePage } from "../types/worldTime"
import { ReadTerminal } from "../components/authoring/ReadState"
import "../components/authoring/authoring.css"

const PAGE_SIZE = 50

// /app/:campaignId/world-times — the points in fictional time recorded for this
// campaign's world, latest first, and a form to record another. Creating a
// calendar belongs to the world (its owner); this page only reads calendars.
// Editors only: the server answers anyone else with a denial.
export function WorldTimesPage() {
    const { campaignId } = useParams<{ campaignId: string }>()
    const id = campaignId ?? ""
    const canEdit = useCampaignCapability(campaignId, "canon.edit")
    const timesUrl = canEdit ? worldTimesPath(id, { limit: PAGE_SIZE }) : null
    const calendarsUrl = canEdit ? campaignCalendarsPath(id) : null
    const times = useAuthoringResource<WorldTimePage>(timesUrl)
    const calendars = useAuthoringResource<CalendarListResponse>(calendarsUrl)
    // The last lists that loaded stay through a failed re-read (after recording a time), so the page
    // that reports the save is not replaced by an error; a denied or missing answer drops them.
    const heldTimes = useKept(times.state, timesUrl ?? "")
    const heldCalendars = useKept(calendars.state, calendarsUrl ?? "")
    const stale = times.state.kind === "error" && heldTimes !== null
    const headingRef = usePageArrival(!canEdit || (times.state.kind !== "loading" && calendars.state.kind !== "loading"))

    return (
        <div className="authoring-page">
            <p className="authoring-page__breadcrumb">
                <Link to={`/app/${encodeURIComponent(id)}/home`}>Campaign home</Link>
            </p>
            <h1 ref={headingRef} tabIndex={-1}>
                World times
            </h1>
            {!canEdit ? (
                <p role="alert">You do not have permission to manage world times.</p>
            ) : times.state.kind === "loading" || calendars.state.kind === "loading" ? (
                <p role="status">Loading world times…</p>
            ) : heldTimes === null || heldCalendars === null ? (
                <ReadTerminal
                    states={[times.state, calendars.state]}
                    what="world times"
                    onRetry={() => retryFailedReads(times, calendars)}
                    back={{ to: `/app/${encodeURIComponent(id)}/home`, label: "Back to the campaign home" }}
                />
            ) : (
                <>
                    {stale ? <StaleReadNotice what="world times" onRetry={() => void times.refetch()} /> : null}
                    <WorldTimesContent
                        key={id}
                        campaignId={id}
                        page={heldTimes}
                        calendars={heldCalendars}
                        refetch={times.refetch}
                        pageStale={stale}
                    />
                </>
            )}
        </div>
    )
}

interface WorldTimesContentProps {
    campaignId: string
    page: WorldTimePage
    calendars: CalendarListResponse
    refetch: () => Promise<RefetchOutcome>
    // The latest read failed and `page` is the last that loaded.
    pageStale: boolean
}

function WorldTimesContent({ campaignId, page, calendars, refetch, pageStale }: WorldTimesContentProps) {
    const announce = useAnnounce()
    // A time that was recorded but is not in the list yet.
    const recorded = useUnreadWrite<true>()
    // Reading again starts the list from its first page, as it does after a time is recorded.
    const readFromTheStart = async (): Promise<RefetchOutcome> => {
        const outcome = await refetch()
        if (outcome === "ok") {
            setOlder([])
            setCursor(undefined)
        }
        return outcome
    }
    const refreshed = useConfirmedRefresh({
        status: recorded.status,
        reset: recorded.end,
        what: "world times",
        message: "World time recorded",
        read: readFromTheStart,
        pageStale,
    })
    const [older, setOlder] = useState<WorldTimeItem[]>([])
    // undefined: still on the first page's own cursor.
    const [cursor, setCursor] = useState<string | null | undefined>(undefined)
    const [loadingMore, setLoadingMore] = useState(false)
    const [moreFailed, setMoreFailed] = useState(false)

    // The Record-a-time dialog. Its form stays mounted while the dialog is closed, so a request whose
    // outcome is unknown (and its key and body) is owned by this page and survives closing the dialog.
    const [open, setOpen] = useState(false)
    // Changing the key starts a new, empty form; it is only done when nothing is unresolved.
    const [formKey, setFormKey] = useState(0)
    const [dirty, setDirty] = useState(false)
    const [status, setStatus] = useState<AuthoringMutationStatus>({ kind: "idle" })
    const [confirming, setConfirming] = useState<"discard" | "unresolved" | null>(null)
    // The time just recorded, for the visible confirmation.
    const [lastId, setLastId] = useState<string | null>(null)

    const pending = status.kind === "pending"
    // A network or server failure: the time may or may not have been recorded.
    const unresolved = status.kind === "error" && (status.error.kind === "network" || status.error.kind === "server")
    // Leaving the page would lose entered values, a request in flight, or the means to retry an uncertain one.
    // (A confirmed write whose list could not be read loses nothing but a notice, so it is not guarded.)
    const guard = useUnsavedChangesGuard(dirty || pending || unresolved)
    const leaveMessage = pending
        ? "A time is being recorded. If you leave now you will not see whether it was saved; check the list afterwards."
        : unresolved
          ? "A time you were recording may already have been recorded. If you leave you cannot retry it from here; check the list afterwards."
          : "You have entered a time that has not been recorded. If you leave, it is lost."

    const next = cursor === undefined ? page.next_cursor : cursor
    const shown = [...page.items, ...older]
    const calendarById = new Map(calendars.calendars.map((calendar) => [calendar.calendar_id, calendar]))

    function recordedTime(item: WorldTimeItem): string {
        if (item.calendar_id === null || item.year === null) return item.display

        const calendar = calendarById.get(item.calendar_id)
        const year = calendar?.epoch_label
            ? `Year ${item.year} (${calendar.epoch_label})`
            : `Year ${item.year}`
        const month = item.month_number === null
            ? null
            : calendar?.months.find((candidate) => candidate.month_number === item.month_number)?.name ?? null
        const parts = [year]
        if (month !== null) parts.push(`${month}${item.day === null ? "" : ` ${item.day}`}`)
        if (item.hour !== null) {
            parts.push(
                `${String(item.hour).padStart(2, "0")}:${String(item.minute ?? 0).padStart(2, "0")}`,
            )
        }
        const date = `${calendar?.name ?? "Calendar"}: ${parts.join(", ")}`
        return item.label ? `${date} — ${item.label}` : date
    }

    const savedItem = lastId === null ? undefined : shown.find((item) => item.world_time_id === lastId)

    // Cancel, Escape or the form's Cancel button. Never while a request is pending.
    function requestDismiss() {
        if (pending) return
        if (unresolved) setConfirming("unresolved")
        else if (dirty) setConfirming("discard")
        else setOpen(false)
    }

    const prompt: FormDialogPrompt | null = guard.blocked
        ? { message: leaveMessage, keepLabel: "Stay", confirmLabel: "Leave", onKeep: guard.stay, onConfirm: guard.discard }
        : confirming === "discard"
          ? {
                message: "Discard this time? What you entered will be lost.",
                keepLabel: "Keep editing",
                confirmLabel: "Discard",
                onKeep: () => setConfirming(null),
                onConfirm: () => {
                    setConfirming(null)
                    setOpen(false)
                    setFormKey((n) => n + 1)
                },
            }
          : confirming === "unresolved"
            ? {
                  message:
                      "This time may already have been recorded. Closing keeps it so you can retry the same request or check the list; nothing is discarded.",
                  keepLabel: "Keep editing",
                  confirmLabel: "Close and check later",
                  onKeep: () => setConfirming(null),
                  onConfirm: () => {
                      setConfirming(null)
                      setOpen(false)
                  },
              }
            : null

    async function loadMore() {
        if (next === null) return
        setLoadingMore(true)
        setMoreFailed(false)
        try {
            const more = await fetchWorldTimes(campaignId, { limit: PAGE_SIZE, cursor: next })
            setOlder((current) => [...current, ...more.items])
            setCursor(more.next_cursor)
        } catch {
            setMoreFailed(true)
        } finally {
            setLoadingMore(false)
        }
    }

    return (
        <>
            <section aria-labelledby="world-times-list-heading">
                <h2 id="world-times-list-heading">Recorded times</h2>
                {shown.length === 0 ? (
                    <p>No times have been recorded for this world yet.</p>
                ) : (
                    <ul className="world-times-list">
                        {shown.map((t) => (
                            <li key={t.world_time_id}>
                                {recordedTime(t)}
                                <span className="visually-hidden"> ({t.precision})</span>
                            </li>
                        ))}
                    </ul>
                )}
                {next !== null ? (
                    <button
                        type="button"
                        className="authoring-button"
                        onClick={() => void loadMore()}
                        disabled={loadingMore}
                        aria-busy={loadingMore}
                    >
                        {loadingMore ? "Loading…" : "Show earlier times"}
                    </button>
                ) : null}
                {moreFailed ? <p role="alert">Earlier times could not be loaded.</p> : null}
            </section>
            <section aria-labelledby="world-times-new-heading">
                <h2 id="world-times-new-heading">Record a new time</h2>
                {calendars.calendars.length === 0 ? (
                    <p>
                        This world has no calendar yet, so only narrative times can be placed. A
                        world owner can create a calendar from the world page.
                    </p>
                ) : null}
                <p>Recording a time adds it to this world&apos;s list. It does not change the campaign&apos;s current time.</p>
                {refreshed.notice}
                {lastId !== null && !open && !refreshed.held ? (
                    <SavedNotice>
                        <p>
                            World time recorded
                            {savedItem === undefined ? "." : `: ${recordedTime(savedItem)}`}
                        </p>
                    </SavedNotice>
                ) : null}
                {unresolved && !open ? (
                    <div className="authoring-message authoring-message--warning" role="status">
                        <div>
                            <p>
                                A time you were recording may or may not have been saved. The list can only show it if it
                                is on the page you are viewing, so reopening to retry the same request is the safe way to
                                find out.
                            </p>
                            <button type="button" className="authoring-button" onClick={() => setOpen(true)}>
                                Reopen to retry
                            </button>{" "}
                            <button type="button" className="authoring-button" onClick={() => void readFromTheStart()}>
                                Reload the list
                            </button>
                        </div>
                    </div>
                ) : null}
                <button
                    type="button"
                    className="authoring-button authoring-button--primary"
                    aria-disabled={refreshed.held}
                    aria-describedby={refreshed.held ? "world-times-held" : undefined}
                    onClick={() => {
                        if (refreshed.held) return
                        setLastId(null)
                        setOpen(true)
                    }}
                >
                    Record a time
                </button>
                {refreshed.held ? (
                    <p id="world-times-held" className="authoring-note">
                        Load the latest world times before recording another.
                    </p>
                ) : null}
                <FormDialog
                    open={open}
                    title="Record a world time"
                    description="Recording a time adds it to this world's list. It does not change the campaign's current time."
                    onDismiss={requestDismiss}
                    pending={pending}
                    prompt={prompt}
                >
                    <WorldTimeForm
                        key={formKey}
                        campaignId={campaignId}
                        calendars={calendars.calendars}
                        times={shown}
                        holdUnresolved
                        onDirtyChange={setDirty}
                        onStatusChange={setStatus}
                        onCreated={async (receipt) => {
                            setLastId(receipt.world_time_id)
                            const outcome = await refetch()
                            if (outcome === "ok") {
                                setOlder([])
                                setCursor(undefined)
                                announce("World time recorded")
                            } else {
                                // Recorded, but the list does not show it yet: said so, not announced as done.
                                recorded.mark(true)
                            }
                            setConfirming(null)
                            setOpen(false)
                            return outcome
                        }}
                        onCancel={requestDismiss}
                    />
                </FormDialog>
                {/* Leaving while the dialog is closed (an uncertain request, or kept input) is asked here;
                    while it is open the same question is asked inside it. */}
                <ConfirmDialog
                    open={guard.blocked && !open}
                    title="Leave this page?"
                    description={leaveMessage}
                    confirmLabel="Leave"
                    cancelLabel="Stay"
                    onConfirm={guard.discard}
                    onCancel={guard.stay}
                />
            </section>
        </>
    )
}

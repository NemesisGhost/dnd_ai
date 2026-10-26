import { useState } from "react"
import { Link, useParams } from "react-router"
import { campaignCalendarsPath, fetchWorldTimes, worldTimesPath } from "../api/worldTime"
import { WorldTimeForm } from "../components/authoring/WorldTimeForm"
import { useAnnounce } from "../components/authoring/announcer"
import { StaleReadNotice } from "../components/StaleReadNotice"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import type { RefetchOutcome } from "../hooks/useAuthoringResource"
import { useConfirmedRefresh } from "../hooks/useConfirmedRefresh"
import { useKept } from "../hooks/useKeptResource"
import { useCampaignCapability } from "../hooks/useCampaignCapability"
import { usePageArrival } from "../hooks/usePageArrival"
import type { CalendarListResponse, WorldTimeItem, WorldTimePage } from "../types/worldTime"
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
    const headingRef = usePageArrival(!canEdit || times.state.kind !== "loading")

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
                <p role="alert">World times could not be loaded. Try reloading the page.</p>
            ) : (
                <>
                    {stale ? <StaleReadNotice what="world times" onRetry={() => void times.refetch()} /> : null}
                    <WorldTimesContent
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
    const [recorded, setRecorded] = useState(false)
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
        status: recorded ? { kind: "confirmed", refresh: "failed" } : { kind: "idle" },
        reset: () => setRecorded(false),
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
                {refreshed.notice}
                <WorldTimeForm
                    campaignId={campaignId}
                    calendars={calendars.calendars}
                    times={shown}
                    onCreated={async () => {
                        const outcome = await refetch()
                        if (outcome === "ok") {
                            setOlder([])
                            setCursor(undefined)
                            announce("World time recorded")
                        } else {
                            // Recorded, but the list does not show it yet: said so, not announced as done.
                            setRecorded(true)
                        }
                        return outcome
                    }}
                    onCancel={() => undefined}
                />
            </section>
        </>
    )
}

import { useState } from "react"
import { Link, useParams } from "react-router"
import { campaignCalendarsPath, fetchWorldTimes, worldTimesPath } from "../api/worldTime"
import { WorldTimeForm } from "../components/authoring/WorldTimeForm"
import { useAnnounce } from "../components/authoring/announcer"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
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
    const times = useAuthoringResource<WorldTimePage>(
        canEdit ? worldTimesPath(id, { limit: PAGE_SIZE }) : null,
    )
    const calendars = useAuthoringResource<CalendarListResponse>(
        canEdit ? campaignCalendarsPath(id) : null,
    )
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
            ) : times.state.kind !== "ready" || calendars.state.kind !== "ready" ? (
                <p role="alert">World times could not be loaded. Try reloading the page.</p>
            ) : (
                <WorldTimesContent
                    campaignId={id}
                    page={times.state.data}
                    calendars={calendars.state.data}
                    refetch={times.refetch}
                />
            )}
        </div>
    )
}

interface WorldTimesContentProps {
    campaignId: string
    page: WorldTimePage
    calendars: CalendarListResponse
    refetch: () => Promise<void>
}

function WorldTimesContent({ campaignId, page, calendars, refetch }: WorldTimesContentProps) {
    const announce = useAnnounce()
    const [older, setOlder] = useState<WorldTimeItem[]>([])
    // undefined: still on the first page's own cursor.
    const [cursor, setCursor] = useState<string | null | undefined>(undefined)
    const [loadingMore, setLoadingMore] = useState(false)
    const [moreFailed, setMoreFailed] = useState(false)

    const next = cursor === undefined ? page.next_cursor : cursor
    const shown = [...page.items, ...older]

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
                                {t.display}
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
                <WorldTimeForm
                    campaignId={campaignId}
                    calendars={calendars.calendars}
                    times={shown}
                    onCreated={() => {
                        void refetch().then(() => {
                            setOlder([])
                            setCursor(undefined)
                            announce("World time recorded")
                        })
                    }}
                    onCancel={() => undefined}
                />
            </section>
        </>
    )
}

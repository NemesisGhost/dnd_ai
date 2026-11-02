import { useEffect, useState } from "react"
import { Link, useLocation, useParams, useSearchParams } from "react-router"
import { comparePath, fetchReviewPage, reviewQueuePath, revisionsPath } from "../api/review"
import { SelectField } from "../components/authoring/fields"
import { LifecycleBadge } from "../components/authoring/feedback"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { useCampaignCapability } from "../hooks/useCampaignCapability"
import { usePageArrival } from "../hooks/usePageArrival"
import { useHeldWorldCapability, WORLD_CANON_READ_PRIVATE } from "../hooks/useWorldCapability"
import type {
    ReviewQueue,
    ReviewRow,
    RevisionComparison,
    RevisionHistory,
} from "../types/review"
import { pickWorldReturnState } from "../hooks/useWorldBackPath"
import { humanizeCode } from "../utils/humanize"
import { recordPath, reviewTarget } from "../utils/reviewTarget"
import "../components/authoring/authoring.css"

const humanize = (code: string): string => code.replace(/_/g, " ")
const when = (value: string): string => new Date(value).toLocaleString()
const base = (campaignId: string): string => `/app/${encodeURIComponent(campaignId)}`
// A kind of record in words; "NPC" is an acronym, not a word to capitalise.
const kindLabel = (code: string): string => (code === "npc" ? "NPC" : humanizeCode(code))

const historyPath = (campaignId: string, category: string | null, entityId: string): string =>
    `${base(campaignId)}/world/${encodeURIComponent(category ?? "record")}/${encodeURIComponent(entityId)}/history`

// /app/:campaignId/review: the world's definitions that are not yet published, by where they
// stand, for people who can edit canon. Each row opens the record's own workspace at the section
// where it is reviewed; the decision itself is taken there, never in this list. A reviewer can
// approve their own work (it is audited); the queue says when the latest change was theirs.
// The filters live in the address, so Back from a record returns to the same list.
const DEFAULT_STATUS = "in_review"
const STATUS_ORDER = ["in_review", "approved", "pending", "draft", "rejected", "archived"]
// The statuses whose counts add up to "needs attention".
const PENDING_PARTS = ["draft", "in_review", "approved", "rejected"]

function orderedStatuses(statuses: ReviewQueue["statuses"]): ReviewQueue["statuses"] {
    const rank = (value: string) => {
        const index = STATUS_ORDER.indexOf(value)
        return index === -1 ? STATUS_ORDER.length : index
    }
    return [...statuses].sort((a, b) => rank(a.value) - rank(b.value))
}

// What the counts can honestly say. The server counts every kind of record, so they are shown only
// while no kind is chosen; "needs attention" is the sum of the four statuses it covers.
function countFor(counts: Record<string, number>, status: string): number | undefined {
    if (counts[status] !== undefined) return counts[status]
    if (status === "pending" && PENDING_PARTS.every((part) => counts[part] !== undefined)) {
        return PENDING_PARTS.reduce((sum, part) => sum + (counts[part] ?? 0), 0)
    }
    return undefined
}

const EMPTY_COPY: Record<string, string> = {
    in_review: "Nothing is waiting for review. Records appear here when someone submits them for review.",
    approved: "Nothing is approved and waiting to be published.",
}

export function ReviewQueuePage() {
    const { campaignId = "" } = useParams()
    const canEdit = useCampaignCapability(campaignId, "canon.edit")
    // The queue is the shared world's drafts and work in progress, which the server reads only for
    // a holder of the world's private-read authority. Without it nothing is requested.
    const canReadPrivate = useHeldWorldCapability(campaignId, WORLD_CANON_READ_PRIVATE)
    return (
        <section className="authoring-page" aria-labelledby="review-heading">
            {canEdit && canReadPrivate ? (
                <Queue campaignId={campaignId} />
            ) : (
                <>
                    <h1 id="review-heading" tabIndex={-1}>
                        Review queue
                    </h1>
                    <p role="alert">
                        {canEdit
                            ? "The review queue lists the shared world's drafts and work in progress, which need a world role to read. You can still use the published records in this campaign; ask the world owner for a world role to review."
                            : "You do not have permission to review records."}
                    </p>
                </>
            )}
        </section>
    )
}

function Queue({ campaignId }: { campaignId: string }) {
    const [params, setParams] = useSearchParams()
    const rawStatus = params.get("status")
    const status = rawStatus !== null && STATUS_ORDER.includes(rawStatus) ? rawStatus : DEFAULT_STATUS
    const type = params.get("type") ?? ""
    const first = useAuthoringResource<ReviewQueue>(reviewQueuePath(campaignId, { status, type }))
    const headingRef = usePageArrival(first.state.kind === "ready")
    const data = first.state.kind === "ready" ? first.state.data : null
    // The filter choices of the last page read, so the form stays while a new filter loads.
    const [meta, setMeta] = useState<ReviewQueue | null>(null)
    if (data !== null && meta !== data) setMeta(data)
    const shown = data ?? meta

    // A missing or unknown value is corrected in place (not pushed), so Back does not revisit it.
    useEffect(() => {
        const unknownKind = shown !== null && type !== "" && !shown.types.includes(type)
        if (rawStatus === status && !unknownKind) return
        const next = new URLSearchParams(params)
        next.set("status", status)
        if (unknownKind) next.delete("type")
        setParams(next, { replace: true })
    }, [rawStatus, status, type, shown, params, setParams])

    const change = (key: "status" | "type", value: string) => {
        const next = new URLSearchParams(params)
        next.set("status", status)
        if (key === "status") next.set("status", value)
        else if (value === "") next.delete("type")
        else next.set("type", value)
        setParams(next)
    }
    // What a record opened from here leads back to: this list, as it is now.
    const reviewSearch = `?${new URLSearchParams({ status, ...(type === "" ? {} : { type }) }).toString()}`

    return (
        <>
            <h1 id="review-heading" ref={headingRef} tabIndex={-1}>
                Review queue
            </h1>
            <p className="authoring-page__lead">
                Records of this world that are waiting for a review decision or for publication. Open one to
                review it in its own workspace.
            </p>
            {shown === null && first.state.kind === "loading" ? (
                <p role="status">Loading…</p>
            ) : shown === null ? (
                <QueueError onRetry={() => void first.refetch()} />
            ) : (
                <>
                    <form noValidate aria-label="Filter the review queue" className="authoring-form">
                        <SelectField
                            id="review-status"
                            label="Show"
                            value={status}
                            options={orderedStatuses(shown.statuses).map((s) => {
                                const count = type === "" ? countFor(shown.counts, s.value) : undefined
                                return {
                                    value: s.value,
                                    label: count === undefined ? s.label : `${s.label} (${count})`,
                                }
                            })}
                            onChange={(value) => change("status", value)}
                        />
                        <SelectField
                            id="review-type"
                            label="Kind of record"
                            value={type}
                            placeholder="All kinds"
                            options={shown.types.map((t) => ({ value: t, label: kindLabel(t) }))}
                            onChange={(value) => change("type", value)}
                        />
                    </form>
                    {data === null ? (
                        first.state.kind === "loading" ? (
                            <p role="status">Loading…</p>
                        ) : (
                            <QueueError onRetry={() => void first.refetch()} />
                        )
                    ) : (
                        <QueueList
                            key={`${status}|${type}|${data.next_cursor ?? ""}|${data.items.length}`}
                            campaignId={campaignId}
                            status={status}
                            type={type}
                            data={data}
                            reviewSearch={reviewSearch}
                            onShowAllKinds={() => change("type", "")}
                        />
                    )}
                </>
            )}
        </>
    )
}

function QueueError({ onRetry }: { onRetry: () => void }) {
    return (
        <div role="alert">
            <p>The review queue could not be loaded.</p>
            <button type="button" className="authoring-button" onClick={onRetry}>
                Try again
            </button>
        </div>
    )
}

function QueueList({
    campaignId,
    status,
    type,
    data,
    reviewSearch,
    onShowAllKinds,
}: {
    campaignId: string
    status: string
    type: string
    data: ReviewQueue
    reviewSearch: string
    onShowAllKinds: () => void
}) {
    const [more, setMore] = useState<ReviewRow[]>([])
    const [cursor, setCursor] = useState<string | null>(data.next_cursor)
    const [loadingMore, setLoadingMore] = useState(false)
    const [failed, setFailed] = useState(false)
    const rows = [...data.items, ...more]

    async function loadMore() {
        if (cursor === null) return
        setLoadingMore(true)
        setFailed(false)
        try {
            const page = await fetchReviewPage(campaignId, { status, type, cursor })
            setMore((current) => [...current, ...page.items])
            setCursor(page.next_cursor)
        } catch {
            setFailed(true)
        } finally {
            setLoadingMore(false)
        }
    }

    return (
        <>
            {rows.length === 0 ? (
                <div>
                    <p>
                        {EMPTY_COPY[status] !== undefined && type === ""
                            ? EMPTY_COPY[status]
                            : "No records match this filter."}
                    </p>
                    {type !== "" ? (
                        <button type="button" className="authoring-button" onClick={onShowAllKinds}>
                            Show all kinds
                        </button>
                    ) : null}
                </div>
            ) : (
                <ul className="op-list" aria-label="Records">
                    {rows.map((row) => {
                        const target = reviewTarget(campaignId, row)
                        // The record's own page learns the queue only where it supports a way back; the
                        // history page always does, whatever kind of record this is.
                        const state = target?.carriesReturn ? { reviewSearch } : undefined
                        const queueState = { reviewSearch }
                        return (
                            <li key={row.entity_id}>
                                {target !== null ? (
                                    <Link to={target.path} state={state}>
                                        {row.name}
                                    </Link>
                                ) : (
                                    <strong>{row.name}</strong>
                                )}{" "}
                                ({kindLabel(row.entity_type_code)}){" "}
                                <LifecycleBadge
                                    status={row.lifecycle_status === "archived" ? "archived" : row.canon_status}
                                />
                                . Last changed {when(row.updated_at)}
                                {row.last_change_by !== null ? ` by ${row.last_change_by}` : ""}
                                {row.last_change_by_me ? " (you)" : ""}.
                                <div className="row-actions">
                                    {target !== null ? (
                                        <Link
                                            className="authoring-button"
                                            to={target.path}
                                            state={state}
                                            aria-label={`${target.action} ${row.name}`}
                                        >
                                            {target.action}
                                        </Link>
                                    ) : null}
                                    <Link
                                        className="authoring-button"
                                        to={historyPath(campaignId, row.category, row.entity_id)}
                                        state={queueState}
                                        aria-label={`History of ${row.name}`}
                                    >
                                        History
                                    </Link>
                                </div>
                            </li>
                        )
                    })}
                </ul>
            )}
            {failed ? <p role="alert">More could not be loaded. Try again.</p> : null}
            {cursor !== null ? (
                <p>
                    <button
                        type="button"
                        className="authoring-button"
                        disabled={loadingMore}
                        onClick={() => void loadMore()}
                    >
                        Load more
                    </button>
                </p>
            ) : null}
        </>
    )
}

// /app/:campaignId/world/:category/:entityId/history: every revision of a record, and a
// comparison of any two. The comparison reads the authored fields (a lifecycle revision holds
// only statuses, so it stands for the latest authored version at or before it). The two versions
// compared are in the address (`?from=&to=`), so a comparison can be linked to.
export function RevisionHistoryPage() {
    const { campaignId = "" } = useParams()
    const canEdit = useCampaignCapability(campaignId, "canon.edit")
    const canReadPrivate = useHeldWorldCapability(campaignId, WORLD_CANON_READ_PRIVATE)
    return (
        <section className="authoring-page" aria-labelledby="history-heading">
            {canEdit && canReadPrivate ? (
                <LoadedHistory />
            ) : (
                <>
                    <h1 id="history-heading" tabIndex={-1}>
                        Revision history
                    </h1>
                    <p role="alert">
                        {canEdit
                            ? "A record's revision history is part of the shared world's private side and needs a world role to read. Ask the world owner for a world role."
                            : "You do not have permission to see the history of this record."}
                    </p>
                </>
            )}
        </section>
    )
}

function LoadedHistory() {
    const { campaignId = "", category = "", entityId = "" } = useParams()
    const { state } = useAuthoringResource<RevisionHistory>(revisionsPath(campaignId, entityId))
    const headingRef = usePageArrival(state.kind === "ready")
    const { state: routerState } = useLocation()
    // Where the person came from (the Review queue's filters, the World browser), validated; it
    // rides along every link out of this page and every comparison.
    const returnState = pickWorldReturnState(routerState)
    const queueHref = `${base(campaignId)}/review${returnState?.reviewSearch ?? ""}`
    const detail =
        state.kind === "ready" ? recordPath(campaignId, entityId, state.data.entity_type_code, category) : null
    return (
        <>
            <p className="authoring-page__breadcrumb">
                <Link to={queueHref}>Review queue</Link>
                {state.kind === "ready" && detail !== null ? (
                    <>
                        {" / "}
                        <Link to={detail} state={returnState}>
                            {state.data.name}
                        </Link>
                    </>
                ) : null}
            </p>
            <h1 id="history-heading" ref={headingRef} tabIndex={-1}>
                Revision history
            </h1>
            {state.kind === "loading" ? (
                <p role="status">Loading…</p>
            ) : state.kind !== "ready" ? (
                <p role="alert">This record does not exist, or you do not have access to it.</p>
            ) : (
                <History campaignId={campaignId} history={state.data} />
            )}
        </>
    )
}

function describe(revision: RevisionHistory["revisions"][number]): string {
    const what =
        revision.kind === "created"
            ? "Created"
            : revision.kind === "updated"
              ? "Edited"
              : `Status ${revision.canon_status !== null ? humanize(revision.canon_status) : ""}${revision.lifecycle_status === "archived" ? ", archived" : ""}`
    return `Version ${revision.row_version}: ${what}, ${when(revision.created_at)}${
        revision.created_by_name !== null ? ` by ${revision.created_by_name}` : ""
    }`
}

function History({ campaignId, history }: { campaignId: string; history: RevisionHistory }) {
    const versions = history.revisions
    const [params, setParams] = useSearchParams()
    const { state: routerState } = useLocation()
    const known = new Set(versions.map((r) => r.row_version))
    // The versions named in the address, when both are versions of this record; anything else is
    // ignored.
    const requested = (() => {
        const from = Number(params.get("from"))
        const to = Number(params.get("to"))
        return Number.isInteger(from) && Number.isInteger(to) && known.has(from) && known.has(to)
            ? { from, to }
            : null
    })()
    const [from, setFrom] = useState(
        requested !== null
            ? String(requested.from)
            : versions.length > 1
              ? String(versions[1]!.row_version)
              : "",
    )
    const [to, setTo] = useState(
        requested !== null ? String(requested.to) : versions.length > 0 ? String(versions[0]!.row_version) : "",
    )
    const options = versions.map((r) => ({ value: String(r.row_version), label: describe(r) }))
    return (
        <>
            <p>
                <strong>{history.name}</strong> is at version {history.row_version}.
            </p>
            <ol className="record-list" aria-label="Revisions">
                {versions.map((r) => (
                    <li key={r.row_version}>{describe(r)}</li>
                ))}
            </ol>
            {versions.length > 1 ? (
                <>
                    <form
                        noValidate
                        aria-label="Compare two versions"
                        className="authoring-form"
                        onSubmit={(event) => {
                            event.preventDefault()
                            if (from === "" || to === "") return
                            // The comparison lives in the address; choosing it replaces the entry, so
                            // Back leaves the page rather than stepping through comparisons.
                            const next = new URLSearchParams(params)
                            next.set("from", from)
                            next.set("to", to)
                            setParams(next, { replace: true, state: routerState })
                        }}
                    >
                        <SelectField id="compare-from" label="Compare" value={from} options={options} onChange={setFrom} />
                        <SelectField id="compare-to" label="With" value={to} options={options} onChange={setTo} />
                        <button type="submit" className="authoring-button">
                            Compare versions
                        </button>
                    </form>
                    {requested !== null ? (
                        <Comparison
                            key={`${requested.from}-${requested.to}`}
                            campaignId={campaignId}
                            entityId={history.entity_id}
                            from={requested.from}
                            to={requested.to}
                        />
                    ) : null}
                </>
            ) : (
                <p>There is only one version, so there is nothing to compare yet.</p>
            )}
        </>
    )
}

function show(value: unknown): string {
    if (value === null || value === undefined) return "(empty)"
    if (typeof value === "string") return value === "" ? "(empty)" : value
    return JSON.stringify(value)
}

const KIND_LABEL = { added: "Added", removed: "Removed", changed: "Changed" } as const

function Comparison({
    campaignId,
    entityId,
    from,
    to,
}: {
    campaignId: string
    entityId: string
    from: number
    to: number
}) {
    const { state } = useAuthoringResource<RevisionComparison>(comparePath(campaignId, entityId, from, to))
    if (state.kind === "loading") return <p role="status">Comparing…</p>
    if (state.kind !== "ready") return <p role="alert">Those versions could not be compared.</p>
    const result = state.data
    return (
        <section aria-labelledby="comparison-heading">
            <h2 id="comparison-heading">
                Version {result.from_version} compared with version {result.to_version}
            </h2>
            {result.changes.length === 0 ? (
                <p>No differences in the authored fields.</p>
            ) : (
                <div className="authoring-table-scroll">
                    <table className="authoring-table">
                        <caption>
                            {result.changes.length} {result.changes.length === 1 ? "difference" : "differences"} in
                            the authored fields
                        </caption>
                        <thead>
                            <tr>
                                <th scope="col">Field</th>
                                <th scope="col">Change</th>
                                <th scope="col">Version {result.from_version}</th>
                                <th scope="col">Version {result.to_version}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {result.changes.map((c) => (
                                <tr key={c.path}>
                                    <th scope="row">{c.path}</th>
                                    <td>{KIND_LABEL[c.kind]}</td>
                                    <td>{c.kind === "added" ? "(none)" : show(c.before)}</td>
                                    <td>
                                        {c.kind === "removed" ? "(none)" : show(c.after)}
                                        {c.truncated ? " (cut short)" : ""}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
        </section>
    )
}

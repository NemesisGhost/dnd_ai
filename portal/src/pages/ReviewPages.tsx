import { useState } from "react"
import { Link, useParams } from "react-router"
import { comparePath, fetchReviewPage, reviewQueuePath, revisionsPath } from "../api/review"
import { SelectField } from "../components/authoring/fields"
import { LifecycleBadge } from "../components/authoring/feedback"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { useCampaignCapability } from "../hooks/useCampaignCapability"
import { usePageArrival } from "../hooks/usePageArrival"
import type {
    ReviewQueue,
    ReviewRow,
    RevisionComparison,
    RevisionHistory,
} from "../types/review"
import "../components/authoring/authoring.css"

const humanize = (code: string): string => code.replace(/_/g, " ")
const when = (value: string): string => new Date(value).toLocaleString()
const base = (campaignId: string): string => `/app/${encodeURIComponent(campaignId)}`

const historyPath = (campaignId: string, category: string | null, entityId: string): string =>
    `${base(campaignId)}/world/${encodeURIComponent(category ?? "record")}/${encodeURIComponent(entityId)}/history`

// /app/:campaignId/review: the world's definitions that are not yet published, by where they
// stand, for people who can edit canon. A reviewer can approve their own work (it is audited);
// the queue says when the latest change was theirs.
export function ReviewQueuePage() {
    const { campaignId = "" } = useParams()
    const canEdit = useCampaignCapability(campaignId, "canon.edit")
    const [status, setStatus] = useState("pending")
    const [type, setType] = useState("")
    const first = useAuthoringResource<ReviewQueue>(reviewQueuePath(campaignId, { status, type }))
    const headingRef = usePageArrival(first.state.kind === "ready")
    const data = first.state.kind === "ready" ? first.state.data : null
    // The filter choices of the last page read, so the form stays while a new filter loads.
    const [meta, setMeta] = useState<ReviewQueue | null>(null)
    if (data !== null && meta !== data) setMeta(data)
    const shown = data ?? meta
    return (
        <section className="authoring-page" aria-labelledby="review-heading">
            <h1 id="review-heading" ref={headingRef} tabIndex={-1}>
                Review
            </h1>
            {!canEdit ? (
                <p role="alert">You do not have permission to review records.</p>
            ) : shown === null && first.state.kind === "loading" ? (
                <p role="status">Loading…</p>
            ) : shown === null ? (
                <p role="alert">The review queue could not be loaded.</p>
            ) : (
                <>
                    <form noValidate aria-label="Filter the review queue" className="authoring-form">
                        <SelectField
                            id="review-status"
                            label="Show"
                            value={status}
                            options={shown.statuses.map((s) => ({
                                value: s.value,
                                label:
                                    shown.counts[s.value] === undefined
                                        ? s.label
                                        : `${s.label} (${shown.counts[s.value]})`,
                            }))}
                            onChange={setStatus}
                        />
                        <SelectField
                            id="review-type"
                            label="Kind of record"
                            value={type}
                            placeholder="All kinds"
                            options={shown.types.map((t) => ({ value: t, label: humanize(t) }))}
                            onChange={setType}
                        />
                    </form>
                    {data === null ? (
                        first.state.kind === "loading" ? (
                            <p role="status">Loading…</p>
                        ) : (
                            <p role="alert">The review queue could not be loaded.</p>
                        )
                    ) : (
                        <QueueList
                            key={`${status}|${type}|${data.next_cursor ?? ""}|${data.items.length}`}
                            campaignId={campaignId}
                            status={status}
                            type={type}
                            data={data}
                        />
                    )}
                </>
            )}
        </section>
    )
}

function QueueList({
    campaignId,
    status,
    type,
    data,
}: {
    campaignId: string
    status: string
    type: string
    data: ReviewQueue
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
                <p>Nothing here.</p>
            ) : (
                <ul className="authoring-choice-list" aria-label="Records">
                    {rows.map((row) => (
                        <li key={row.entity_id}>
                            {row.category !== null ? (
                                <Link
                                    to={`${base(campaignId)}/world/${encodeURIComponent(row.category)}/${encodeURIComponent(row.entity_id)}`}
                                >
                                    {row.name}
                                </Link>
                            ) : (
                                <strong>{row.name}</strong>
                            )}{" "}
                            ({humanize(row.entity_type_code)}){" "}
                            <LifecycleBadge
                                status={row.lifecycle_status === "archived" ? "archived" : row.canon_status}
                            />
                            . Changed {when(row.updated_at)}
                            {row.last_change_by !== null ? ` by ${row.last_change_by}` : ""}
                            {row.last_change_by_me ? " (you)" : ""}.{" "}
                            <Link to={historyPath(campaignId, row.category, row.entity_id)}>
                                History of {row.name}
                            </Link>
                        </li>
                    ))}
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
// only statuses, so it stands for the latest authored version at or before it).
export function RevisionHistoryPage() {
    const { campaignId = "", category = "", entityId = "" } = useParams()
    const canEdit = useCampaignCapability(campaignId, "canon.edit")
    const { state } = useAuthoringResource<RevisionHistory>(revisionsPath(campaignId, entityId))
    const headingRef = usePageArrival(state.kind === "ready")
    const detailPath = `${base(campaignId)}/world/${encodeURIComponent(category)}/${encodeURIComponent(entityId)}`
    return (
        <section className="authoring-page" aria-labelledby="history-heading">
            <p className="authoring-page__breadcrumb">
                <Link to={`${base(campaignId)}/review`}>Review</Link>
                {state.kind === "ready" && category !== "record" ? (
                    <>
                        {" / "}
                        <Link to={detailPath}>{state.data.name}</Link>
                    </>
                ) : null}
            </p>
            <h1 id="history-heading" ref={headingRef} tabIndex={-1}>
                Revision history
            </h1>
            {!canEdit ? (
                <p role="alert">You do not have permission to see the history of this record.</p>
            ) : state.kind === "loading" ? (
                <p role="status">Loading…</p>
            ) : state.kind !== "ready" ? (
                <p role="alert">This record does not exist, or you do not have access to it.</p>
            ) : (
                <History campaignId={campaignId} history={state.data} />
            )}
        </section>
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
    const [from, setFrom] = useState(versions.length > 1 ? String(versions[1]!.row_version) : "")
    const [to, setTo] = useState(versions.length > 0 ? String(versions[0]!.row_version) : "")
    const [shown, setShown] = useState<{ from: number; to: number } | null>(null)
    const options = versions.map((r) => ({ value: String(r.row_version), label: describe(r) }))
    return (
        <>
            <p>
                <strong>{history.name}</strong> is at version {history.row_version}.
            </p>
            <ol className="authoring-choice-list" aria-label="Revisions">
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
                            if (from !== "" && to !== "") setShown({ from: Number(from), to: Number(to) })
                        }}
                    >
                        <SelectField id="compare-from" label="Compare" value={from} options={options} onChange={setFrom} />
                        <SelectField id="compare-to" label="With" value={to} options={options} onChange={setTo} />
                        <button type="submit" className="authoring-button">
                            Compare versions
                        </button>
                    </form>
                    {shown !== null ? (
                        <Comparison
                            key={`${shown.from}-${shown.to}`}
                            campaignId={campaignId}
                            entityId={history.entity_id}
                            from={shown.from}
                            to={shown.to}
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

import { Link, useParams } from "react-router"
import { provenancePath } from "../api/sources"
import { LifecycleBadge } from "../components/authoring/feedback"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { useCampaignCapability } from "../hooks/useCampaignCapability"
import { usePageArrival } from "../hooks/usePageArrival"
import type { Provenance } from "../types/provenance"
import { isWorldDetailCategory } from "../types/world"
import "../components/authoring/authoring.css"

const when = (value: string): string => new Date(value).toLocaleString()
const humanize = (code: string): string => code.replace(/_/g, " ")

// /app/:campaignId/world/:category/:entityId/provenance: where a record came from and what has
// happened to it, for people who can edit canon. Reference text is GM-only and shown here.
export function ProvenancePage() {
    const { campaignId = "", category = "", entityId = "" } = useParams()
    const canEdit = useCampaignCapability(campaignId, "canon.edit")
    const { state } = useAuthoringResource<Provenance>(provenancePath(campaignId, entityId))
    const headingRef = usePageArrival(state.kind === "ready")
    // A record with no World detail page (a quest, a dungeon) links back to the World list.
    const detailPath = isWorldDetailCategory(category)
        ? `/app/${encodeURIComponent(campaignId)}/world/${encodeURIComponent(category)}/${encodeURIComponent(entityId)}`
        : `/app/${encodeURIComponent(campaignId)}/world`
    return (
        <section className="authoring-page" aria-labelledby="provenance-heading">
            <p className="authoring-page__breadcrumb">
                <Link to={detailPath}>{state.kind === "ready" ? state.data.name : "Record"}</Link>
            </p>
            <h1 id="provenance-heading" ref={headingRef} tabIndex={-1}>
                Provenance
            </h1>
            {!canEdit ? (
                <p role="alert">You do not have permission to see where this record came from.</p>
            ) : state.kind === "loading" ? (
                <p role="status">Loading…</p>
            ) : state.kind !== "ready" ? (
                <p role="alert">This record does not exist, or you do not have access to it.</p>
            ) : (
                <Loaded view={state.data} campaignId={campaignId} category={category} />
            )}
        </section>
    )
}

function Loaded({ view, campaignId, category }: { view: Provenance; campaignId: string; category: string }) {
    const current = view.links.filter((l) => l.is_attached)
    const past = view.links.filter((l) => !l.is_attached)
    return (
        <>
            <dl className="authoring-fact-list">
                <dt>Record</dt>
                <dd>
                    {view.name} ({humanize(view.entity_type_code)}){" "}
                    <LifecycleBadge status={view.lifecycle_status === "archived" ? "archived" : view.canon_status} />
                </dd>
                <dt>Created</dt>
                <dd>
                    {when(view.created_at)}
                    {view.created_by_name !== null ? ` by ${view.created_by_name}` : ""}
                </dd>
                <dt>Created from</dt>
                <dd>
                    {view.origin === null
                        ? "An unrecorded source"
                        : `${view.origin.title} (${view.origin.source_type_label})`}
                </dd>
            </dl>

            <h2>Sources attached now</h2>
            {current.length === 0 ? <p>None.</p> : null}
            <ul className="authoring-choice-list">
                {current.map((l) => (
                    <li key={`${l.source_id}-${l.attached_at}`}>
                        {l.title} ({l.source_type_label})
                        {l.reference !== null ? `: ${l.reference}` : ""}. Attached {when(l.attached_at)}
                        {l.attached_by_name !== null ? ` by ${l.attached_by_name}` : ""}.
                    </li>
                ))}
            </ul>

            {past.length > 0 ? (
                <>
                    <h2>Sources detached</h2>
                    <ul className="authoring-choice-list">
                        {past.map((l) => (
                            <li key={`${l.source_id}-${l.attached_at}`}>
                                {l.title} ({l.source_type_label}). Attached {when(l.attached_at)}
                                {l.attached_by_name !== null ? ` by ${l.attached_by_name}` : ""}, detached{" "}
                                {l.detached_at === null ? "" : when(l.detached_at)}
                                {l.detached_by_name !== null ? ` by ${l.detached_by_name}` : ""}.
                            </li>
                        ))}
                    </ul>
                </>
            ) : null}

            <p>
                <Link
                    to={`/app/${encodeURIComponent(campaignId)}/world/${encodeURIComponent(category === "" ? "record" : category)}/${encodeURIComponent(view.entity_id)}/history`}
                >
                    Revision history and comparison
                </Link>
            </p>
            <h2>History</h2>
            {view.transitions.length === 0 ? <p>No lifecycle changes recorded.</p> : null}
            <ol className="authoring-choice-list">
                {view.transitions.map((t) => (
                    <li key={`${t.recorded_at}-${t.label}`}>
                        {t.label}
                        {t.previous_status !== null && t.new_status !== null
                            ? ` (${humanize(t.previous_status)} to ${humanize(t.new_status)})`
                            : ""}
                        , {when(t.recorded_at)}
                        {t.actor_name !== null ? ` by ${t.actor_name}` : ""}
                    </li>
                ))}
            </ol>

            {view.superseded_by !== null ? (
                <p>Superseded by {view.superseded_by.name}.</p>
            ) : null}
            {view.supersedes.length > 0 ? (
                <p>Replaces {view.supersedes.map((r) => r.name).join(", ")}.</p>
            ) : null}
        </>
    )
}

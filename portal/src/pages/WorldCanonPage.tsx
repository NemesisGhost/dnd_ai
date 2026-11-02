import { useEffect, useState } from "react"
import { Link, useParams } from "react-router"
import { fetchWorldCanon } from "../api/worldSharing"
import { worldPath } from "../api/worlds"
import { TextField } from "../components/authoring/fields"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { usePageArrival } from "../hooks/usePageArrival"
import type { WorldDetail } from "../types/worldAuthoring"
import type { WorldCanonItem } from "../types/worldSharing"
import "../components/authoring/authoring.css"

type State =
    | { kind: "loading" }
    | { kind: "ready"; items: WorldCanonItem[]; nextCursor: string | null }
    | { kind: "denied" }
    | { kind: "error" }

const CATEGORY_LABEL: Record<string, string> = {
    location: "Location",
    organization: "Organization",
    religion: "Religion",
}

// The world Reader surface: published canon only, as cards (name, kind, summary). It shows
// nothing from any campaign and none of a record's private side (drafts, GM-only fields,
// revisions, provenance); the server filters, this page only renders what it returns.
export function WorldCanonPage() {
    const { worldId = "" } = useParams()
    const world = useAuthoringResource<WorldDetail>(worldPath(worldId))
    const [query, setQuery] = useState("")
    const [debounced, setDebounced] = useState("")
    const [cursor, setCursor] = useState<string | null>(null)
    const [state, setState] = useState<State>({ kind: "loading" })
    const headingRef = usePageArrival(state.kind !== "loading")

    useEffect(() => {
        const handle = window.setTimeout(() => {
            setDebounced(query)
            setCursor(null)
        }, 200)
        return () => window.clearTimeout(handle)
    }, [query])

    useEffect(() => {
        const controller = new AbortController()
        void fetchWorldCanon(worldId, debounced, cursor, controller.signal)
            .then((page) => {
                if (controller.signal.aborted) return
                setState((previous) => ({
                    kind: "ready",
                    items:
                        cursor !== null && previous.kind === "ready"
                            ? [...previous.items, ...page.items]
                            : page.items,
                    nextCursor: page.next_cursor,
                }))
            })
            .catch((cause: unknown) => {
                if (controller.signal.aborted) return
                const status = (cause as { status?: number }).status
                setState(status === 403 || status === 404 ? { kind: "denied" } : { kind: "error" })
            })
        return () => controller.abort()
    }, [worldId, debounced, cursor])

    return (
        <div className="world-page">
            <div className="authoring-page">
                <p className="authoring-page__breadcrumb">
                    <Link to="/worlds">Worlds</Link>
                    {" / "}
                    <Link to={`/worlds/${worldId}`}>
                        {world.state.kind === "ready" ? world.state.data.name : "World"}
                    </Link>
                </p>
                <h1 ref={headingRef} tabIndex={-1}>
                    Published canon
                </h1>
                <p className="authoring-page__lead">
                    What this world's published canon shows to a reader. Drafts and campaign
                    material are not part of it.
                </p>
                {state.kind === "denied" ? (
                    <p role="alert">You do not have access to this world's canon.</p>
                ) : (
                    <>
                        <TextField label="Search by name or summary" value={query} onChange={setQuery} />
                        {state.kind === "loading" ? <p role="status">Loading…</p> : null}
                        {state.kind === "error" ? <p role="alert">The canon could not be loaded.</p> : null}
                        {state.kind === "ready" ? (
                            <>
                                {state.items.length === 0 ? (
                                    <p>No published canon matches.</p>
                                ) : (
                                    <ul className="authoring-list">
                                        {state.items.map((item) => (
                                            <li className="authoring-list__item" key={item.entity_id}>
                                                <strong>{item.name}</strong>{" "}
                                                <span className="authoring-badge">
                                                    {CATEGORY_LABEL[item.category] ?? item.category}
                                                </span>
                                                {item.summary ? <p>{item.summary}</p> : null}
                                            </li>
                                        ))}
                                    </ul>
                                )}
                                {state.nextCursor !== null ? (
                                    <button
                                        type="button"
                                        className="authoring-button"
                                        onClick={() => setCursor(state.nextCursor)}
                                    >
                                        Load more
                                    </button>
                                ) : null}
                            </>
                        ) : null}
                    </>
                )}
            </div>
        </div>
    )
}

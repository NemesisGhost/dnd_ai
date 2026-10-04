import { Link, useSearchParams } from "react-router"
import { worldsListPath } from "../api/worlds"
import { RadioGroupField } from "../components/authoring/fields"
import { LifecycleBadge } from "../components/authoring/feedback"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { usePageArrival } from "../hooks/usePageArrival"
import { useAuthenticatedSession } from "../layouts/useAuthenticatedSession"
import type { WorldListResponse } from "../types/worldAuthoring"
import "../components/authoring/authoring.css"

type StatusFilter = "active" | "archived"

const FILTER_OPTIONS = [
    { value: "active", label: "Active" },
    { value: "archived", label: "Archived" },
] as const

function readFilter(value: string | null): StatusFilter {
    return value === "archived" ? "archived" : "active"
}

// The worlds the signed-in user owns, from GET /worlds. The list is filtered by
// the server (only worlds the user holds authority over are ever returned), and
// the "Create world" action appears only when the bootstrap's server-computed
// `global_capabilities` includes `world.create` — never inferred.
export function WorldsPage() {
    const { bootstrap } = useAuthenticatedSession()
    const [params, setParams] = useSearchParams()
    const filter = readFilter(params.get("status"))
    const { state } = useAuthoringResource<WorldListResponse>(
        `${worldsListPath(filter)}&limit=100`,
    )
    const headingRef = usePageArrival(state.kind !== "loading")
    const canCreate = bootstrap.global_capabilities?.includes("world.create") === true

    return (
        <div className="world-page">
            <div className="authoring-page">
                <h1 ref={headingRef} tabIndex={-1}>
                    Worlds
                </h1>
                <p className="authoring-page__lead">
                    Worlds you own. A world holds its timelines and the campaigns played on
                    them.
                </p>

                {canCreate ? (
                    <p>
                        <Link className="authoring-button authoring-button--primary" to="/worlds/new">
                            Create world
                        </Link>
                    </p>
                ) : null}

                <RadioGroupField
                    legend="Show"
                    value={filter}
                    options={FILTER_OPTIONS}
                    onChange={(value) => {
                        setParams(value === "archived" ? { status: "archived" } : {}, {
                            replace: true,
                        })
                    }}
                />

                {state.kind === "loading" ? (
                    <p role="status">Loading worlds…</p>
                ) : state.kind === "denied" || state.kind === "unavailable" ? (
                    <p role="alert">Worlds are not available to you.</p>
                ) : state.kind === "error" ? (
                    <p role="alert">Worlds could not be loaded. Try reloading the page.</p>
                ) : state.data.items.length === 0 ? (
                    <p>
                        {filter === "archived"
                            ? "You have no archived worlds."
                            : "You do not own any worlds yet."}
                        {canCreate && filter === "active"
                            ? " Create one to start a campaign."
                            : ""}
                    </p>
                ) : (
                    <>
                        <ul className="authoring-list" aria-label="Worlds">
                            {state.data.items.map((world) => (
                                <li className="authoring-list__item" key={world.world_id}>
                                    <div>
                                        <h2>
                                            <Link to={`/worlds/${world.world_id}`}>{world.name}</Link>
                                        </h2>
                                        {world.description ? (
                                            <p className="authoring-field__hint">{world.description}</p>
                                        ) : null}
                                    </div>
                                    {world.lifecycle_status === "archived" ? (
                                        <LifecycleBadge status="archived" />
                                    ) : null}
                                </li>
                            ))}
                        </ul>
                        {state.data.next_cursor !== null ? (
                            <p className="authoring-note">Only the first 100 worlds are shown.</p>
                        ) : null}
                    </>
                )}
            </div>
        </div>
    )
}

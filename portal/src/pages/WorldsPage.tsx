import { Link, useSearchParams } from "react-router"
import { worldsListPath } from "../api/worlds"
import { RadioGroupField } from "../components/authoring/fields"
import { LifecycleBadge } from "../components/authoring/feedback"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { usePageArrival } from "../hooks/usePageArrival"
import { useAuthenticatedSession } from "../layouts/useAuthenticatedSession"
import type { WorldListResponse, WorldSummary } from "../types/worldAuthoring"
import { canCreateWorlds, worldAccess, worldDestination } from "../utils/worldAccess"
import "../components/authoring/authoring.css"

type StatusFilter = "active" | "archived"

const FILTER_OPTIONS = [
    { value: "active", label: "Active" },
    { value: "archived", label: "Archived" },
] as const

function readFilter(value: string | null): StatusFilter {
    return value === "archived" ? "archived" : "active"
}

// The worlds the signed-in user holds authority over, from GET /worlds. The list
// is filtered by the server; nothing here links to a world it did not return.
// Each world links by its own server-computed capabilities: one the caller
// manages opens its authoring overview, a view-only one opens the read-only
// overview (marked "View only"), and one with no world access is not linked.
// "Create world" appears only when the bootstrap's server-computed
// `global_capabilities` includes `world.create` — never inferred.
export function WorldsPage() {
    const { bootstrap } = useAuthenticatedSession()
    const [params, setParams] = useSearchParams()
    const filter = readFilter(params.get("status"))
    const { state } = useAuthoringResource<WorldListResponse>(
        `${worldsListPath(filter)}&limit=100`,
    )
    const headingRef = usePageArrival(state.kind !== "loading")
    const canCreate = canCreateWorlds(bootstrap)

    return (
        <div className="world-page">
            <div className="authoring-page">
                <h1 ref={headingRef} tabIndex={-1}>
                    Worlds
                </h1>
                <p className="authoring-page__lead">
                    Worlds you have access to. A world holds its timelines and the campaigns
                    played on them.
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
                                            <WorldName world={world} />
                                        </h2>
                                        {world.description ? (
                                            <p className="authoring-field__hint">{world.description}</p>
                                        ) : null}
                                    </div>
                                    {worldAccess(world) === "view" ? (
                                        <span className="authoring-badge">View only</span>
                                    ) : null}
                                    {roleLabels(world) !== "" ? (
                                        <span className="authoring-badge">{roleLabels(world)}</span>
                                    ) : null}
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

const ROLE_LABEL: Record<string, string> = {
    world_owner: "Owner",
    world_editor: "Editor",
    world_reviewer: "Reviewer",
    world_reader: "Reader",
}

// "Owner", "Editor · Reviewer", "Reader", "Can host campaigns" (display only; every gate
// reads the world's `capabilities`, never these labels).
function roleLabels(world: WorldSummary): string {
    const labels = (world.role_codes ?? []).map((code) => ROLE_LABEL[code] ?? code)
    if (world.has_use_grant === true) labels.push("Can host campaigns")
    return labels.join(" · ")
}

function WorldName({ world }: { world: WorldSummary }) {
    const to = worldDestination(world)
    return to === null ? <>{world.name}</> : <Link to={to}>{world.name}</Link>
}

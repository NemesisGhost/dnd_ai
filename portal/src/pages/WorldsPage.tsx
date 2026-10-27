import { Link, useSearchParams } from "react-router"
import { worldsListPath } from "../api/worlds"
import { RadioGroupField } from "../components/authoring/fields"
import { LifecycleBadge } from "../components/authoring/feedback"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { usePageArrival } from "../hooks/usePageArrival"
import { useAuthenticatedSession } from "../layouts/useAuthenticatedSession"
import type { WorldListResponse } from "../types/worldAuthoring"
import { buildWorldChoices, canCreateWorlds } from "../utils/worldAccess"
import type { WorldChoice } from "../utils/worldAccess"
import "../components/authoring/authoring.css"

type StatusFilter = "active" | "archived"

const FILTER_OPTIONS = [
    { value: "active", label: "Active" },
    { value: "archived", label: "Archived" },
] as const

function readFilter(value: string | null): StatusFilter {
    return value === "archived" ? "archived" : "active"
}

// Every world the signed-in user can see, from two server sources merged by
// `buildWorldChoices`: GET /worlds (explicit world authority) and the
// bootstrap's campaigns (campaign-scoped visibility). Nothing here links to a
// world neither returned. A world the caller manages opens its authoring
// overview; one held by a view-only world role opens the read-only overview;
// one visible only through a campaign opens that campaign's read-only World
// Explorer (/app/{campaignId}/world) and never a /worlds route. Both read-only
// kinds are marked "View only". Campaign visibility is listed under Active
// only: bootstrap campaigns are active, and an active campaign keeps its
// world from being archived. "Create world" appears only when the bootstrap's
// server-computed `global_capabilities` includes `world.create`.
export function WorldsPage() {
    const { bootstrap } = useAuthenticatedSession()
    const [params, setParams] = useSearchParams()
    const filter = readFilter(params.get("status"))
    const { state } = useAuthoringResource<WorldListResponse>(
        `${worldsListPath(filter)}&limit=100`,
    )
    const headingRef = usePageArrival(state.kind !== "loading")
    const canCreate = canCreateWorlds(bootstrap)
    const choices =
        state.kind === "ready"
            ? buildWorldChoices(
                  state.data.items,
                  filter === "active" ? bootstrap.campaigns : [],
              )
            : []

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
                ) : choices.length === 0 ? (
                    <p>
                        {filter === "archived"
                            ? "You have no archived worlds."
                            : "You do not have access to any worlds yet."}
                        {canCreate && filter === "active"
                            ? " Create one to start a campaign."
                            : ""}
                    </p>
                ) : (
                    <>
                        <ul className="authoring-list" aria-label="Worlds">
                            {choices.map((world) => (
                                <li className="authoring-list__item" key={world.world_id}>
                                    <div>
                                        <h2>
                                            <Link to={world.to}>{world.name}</Link>
                                        </h2>
                                        {world.description ? (
                                            <p className="authoring-field__hint">{world.description}</p>
                                        ) : null}
                                        <WorldSourceHint world={world} />
                                    </div>
                                    {world.access === "view" ? (
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
    world_viewer: "Viewer",
    world_editor: "Editor",
    world_reviewer: "Reviewer",
    world_reader: "Reader",
}

// "Owner", "Editor · Reviewer", "Reader", "Can host campaigns" (display only; every gate
// reads the world's `capabilities`, never these labels).
function roleLabels(world: WorldChoice): string {
    const labels = (world.role_codes ?? []).map((code) => ROLE_LABEL[code] ?? code)
    if (world.has_use_grant === true) labels.push("Can host campaigns")
    return labels.join(" · ")
}

function WorldSourceHint({ world }: { world: WorldChoice }) {
    return world.source === "campaign" ? (
        <p className="authoring-field__hint">Through campaign {world.campaign_name}</p>
    ) : null
}

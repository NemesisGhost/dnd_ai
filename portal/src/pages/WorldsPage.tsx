import { useEffect, useRef } from "react"
import { Link, useSearchParams } from "react-router"
import { worldsListPath } from "../api/worlds"
import { useAnnounce } from "../components/authoring/announcer"
import { LifecycleBadge } from "../components/authoring/feedback"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { usePageArrival } from "../hooks/usePageArrival"
import { useAuthenticatedSession } from "../layouts/useAuthenticatedSession"
import type { WorldListResponse } from "../types/worldAuthoring"
import { buildWorldChoices, canCreateWorlds } from "../utils/worldAccess"
import type { WorldChoice } from "../utils/worldAccess"
import "../components/authoring/authoring.css"

// `?archived=1` is the checked state. The earlier `?status=archived` (old bookmarks and Back entries) is
// read as checked too: the union shows a superset of what that address showed.
function readIncludeArchived(params: URLSearchParams): boolean {
    return params.get("archived") === "1" || params.get("status") === "archived"
}

function worldCount(count: number): string {
    return count === 1 ? "1 world" : `${count} worlds`
}

// Every world the signed-in user can see, from two server sources merged by
// `buildWorldChoices`: GET /worlds (explicit world authority) and the
// bootstrap's campaigns (campaign-scoped visibility). Nothing here links to a
// world neither returned. A world the caller manages opens its authoring
// overview; one held by a view-only world role opens the read-only overview;
// one visible only through a campaign opens that campaign's read-only World
// Explorer (/app/{campaignId}/world) and never a /worlds route. Both read-only
// kinds are marked "View only". The one checkbox "Include archived worlds" chooses
// which server list is read (active, or the server's own active-plus-archived
// union); campaign visibility is added in both states, because bootstrap
// campaigns are active and an active campaign keeps its world from being
// archived, so a campaign-visible world is never hidden by the filter. "Create
// world" appears only when the bootstrap's server-computed `global_capabilities`
// includes `world.create`.
export function WorldsPage() {
    const { bootstrap } = useAuthenticatedSession()
    const [params, setParams] = useSearchParams()
    const includeArchived = readIncludeArchived(params)
    const { state } = useAuthoringResource<WorldListResponse>(
        `${worldsListPath(includeArchived ? "all" : "active")}&limit=100`,
    )
    // Once per path: a change of the filter only changes the query and must leave focus on the checkbox.
    const headingRef = usePageArrival(state.kind !== "loading", "path")
    const canCreate = canCreateWorlds(bootstrap)
    const choices =
        state.kind === "ready" ? buildWorldChoices(state.data.items, bootstrap.campaigns) : []

    // A change the person made waits for the list it asks for. The list is path-keyed, so only an answer
    // for the state now chosen can be ready; a newer choice replaces the wait, and a failed read ends it
    // without a count. The result is announced once, from the list actually displayed.
    const announce = useAnnounce()
    const awaiting = useRef<boolean | null>(null)
    const settledCount = choices.length
    useEffect(() => {
        if (awaiting.current === null) return
        if (state.kind === "loading") return
        const wanted = awaiting.current
        awaiting.current = null
        if (state.kind !== "ready" || wanted !== includeArchived) return
        announce(
            includeArchived
                ? `Showing ${worldCount(settledCount)}, including archived.`
                : `Showing ${settledCount === 1 ? "1 active world" : `${settledCount} active worlds`}.`,
        )
    }, [state.kind, includeArchived, settledCount, announce])

    function changeIncludeArchived(next: boolean) {
        awaiting.current = next
        const nextParams = new URLSearchParams(params)
        nextParams.delete("status")
        if (next) nextParams.set("archived", "1")
        else nextParams.delete("archived")
        setParams(nextParams, { replace: true })
    }
    const viaCampaign = choices.some((world) => world.source === "campaign")

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

                <p>
                    <label>
                        <input
                            type="checkbox"
                            checked={includeArchived}
                            onChange={(event) => changeIncludeArchived(event.currentTarget.checked)}
                        />{" "}
                        Include archived worlds
                    </label>
                </p>

                {state.kind === "loading" ? (
                    <p role="status">Loading worlds…</p>
                ) : state.kind === "denied" || state.kind === "unavailable" ? (
                    <p role="alert">Worlds are not available to you.</p>
                ) : state.kind === "error" ? (
                    <p role="alert">Worlds could not be loaded. Try reloading the page.</p>
                ) : choices.length === 0 ? (
                    <p>
                        You do not have access to any worlds yet.
                        {canCreate && !includeArchived ? " Create one to start a campaign." : ""}
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
                            <p className="authoring-note">
                                Only the first 100 worlds are shown.
                                {includeArchived ? " Archived worlds count toward this limit." : ""}
                                {viaCampaign ? " Worlds visible through a campaign are listed in addition." : ""}
                            </p>
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

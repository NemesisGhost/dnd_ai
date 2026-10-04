import { useState } from "react"
import type { RefObject } from "react"
import { Link, useParams } from "react-router"
import { archiveWorld, restoreWorld, worldPath } from "../api/worlds"
import { ConfirmDialog } from "../components/authoring/ConfirmDialog"
import { LifecycleBadge, MutationStatusMessage } from "../components/authoring/feedback"
import { TimelineTree } from "../components/TimelineTree"
import { useAnnounce } from "../components/authoring/announcer"
import { useSession } from "../context/SessionContext"
import { useAuthoringMutation } from "../hooks/useAuthoringMutation"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { usePageArrival } from "../hooks/usePageArrival"
import type { TransitionRequest, WorldDetail, WorldMutationResponse } from "../types/worldAuthoring"
import { ERROR_CODE_MESSAGE, validateReason } from "../utils/authoringValidation"
import "../components/authoring/authoring.css"

type PendingAction = "archive" | "restore" | null

// A world's overview: details, its timelines as a lineage, the campaigns the
// caller manages on it, and the actions the *server* says are available. A
// blocked action is explained with the server's stable reason instead of being
// hidden or silently disabled.
export function WorldOverviewPage() {
    const { worldId = "" } = useParams()
    const { state, refetch } = useAuthoringResource<WorldDetail>(worldPath(worldId))
    const headingRef = usePageArrival(state.kind === "ready")

    return (
        <main className="app-main">
            <div className="authoring-page">
                <p className="authoring-page__breadcrumb">
                    <Link to="/worlds">Worlds</Link>
                </p>
                {state.kind === "loading" ? (
                    <>
                        <h1 ref={headingRef} tabIndex={-1}>
                            World
                        </h1>
                        <p role="status">Loading world…</p>
                    </>
                ) : state.kind === "unavailable" || state.kind === "denied" ? (
                    <>
                        <h1 ref={headingRef} tabIndex={-1}>
                            World not available
                        </h1>
                        <p role="alert">
                            This world does not exist, or you do not have access to it.
                        </p>
                        <p>
                            <Link to="/worlds">Back to your worlds</Link>
                        </p>
                    </>
                ) : state.kind === "error" ? (
                    <>
                        <h1 ref={headingRef} tabIndex={-1}>
                            World
                        </h1>
                        <p role="alert">The world could not be loaded. Try reloading the page.</p>
                    </>
                ) : (
                    <WorldOverview
                        world={state.data}
                        headingRef={headingRef}
                        refetch={refetch}
                    />
                )}
            </div>
        </main>
    )
}

interface WorldOverviewProps {
    world: WorldDetail
    headingRef: RefObject<HTMLHeadingElement | null>
    refetch: () => Promise<void>
}

function WorldOverview({ world, headingRef, refetch }: WorldOverviewProps) {
    const announce = useAnnounce()
    const { reload } = useSession()
    const [pendingAction, setPendingAction] = useState<PendingAction>(null)
    const [reason, setReason] = useState("")
    const [reasonError, setReasonError] = useState<string | null>(null)

    const available = new Set(world.available_actions)
    // A transition blocked only because the record is in the wrong state is
    // obvious from the state itself; every other reason is worth explaining.
    const blockedReasons = world.blocked_actions.filter(
        (b) => b.reason !== "lifecycle_transition_not_allowed",
    )
    const primary = world.timelines.find((t) => t.is_primary)

    const mutation = useAuthoringMutation<TransitionRequest, WorldMutationResponse>({
        scopeKey: `${pendingAction ?? "none"}:${world.world_id}`,
        request: (body, ctx) =>
            pendingAction === "restore"
                ? restoreWorld(world.world_id, body, ctx)
                : archiveWorld(world.world_id, body, ctx),
        onSuccess: async () => {
            const message = pendingAction === "restore" ? "World restored" : "World archived"
            await refetch()
            setPendingAction(null)
            setReason("")
            announce(message)
        },
    })

    function openDialog(action: Exclude<PendingAction, null>) {
        mutation.reset()
        setReason("")
        setReasonError(null)
        setPendingAction(action)
    }

    function closeDialog() {
        setPendingAction(null)
    }

    function confirm() {
        const error = validateReason(reason, false)
        setReasonError(error)
        if (error) {
            return
        }
        mutation.submit({
            expected_row_version: world.row_version,
            reason: reason.trim() === "" ? null : reason.trim(),
        })
    }

    const error = mutation.status.kind === "error" ? mutation.status.error : null

    return (
        <>
            <h1 ref={headingRef} tabIndex={-1}>
                {world.name}
            </h1>
            <p>
                {world.lifecycle_status === "archived" ? <LifecycleBadge status="archived" /> : null}
            </p>
            {world.description ? <p>{world.description}</p> : null}

            <div className="authoring-actions">
                {available.has("update") ? (
                    <Link className="authoring-button" to={`/worlds/${world.world_id}/edit`}>
                        Edit world
                    </Link>
                ) : null}
                {available.has("create_timeline") ? (
                    <Link
                        className="authoring-button"
                        to={`/worlds/${world.world_id}/timelines/new`}
                    >
                        New timeline
                    </Link>
                ) : null}
                {available.has("create_campaign") ? (
                    <Link
                        className="authoring-button authoring-button--primary"
                        to={`/campaigns/new?worldId=${encodeURIComponent(world.world_id)}${
                            primary ? `&timelineId=${encodeURIComponent(primary.timeline_id)}` : ""
                        }`}
                    >
                        New campaign
                    </Link>
                ) : null}
                {available.has("archive") ? (
                    <button
                        type="button"
                        className="authoring-button"
                        onClick={() => openDialog("archive")}
                    >
                        Archive world
                    </button>
                ) : null}
                {available.has("restore") ? (
                    <button
                        type="button"
                        className="authoring-button"
                        onClick={() => openDialog("restore")}
                    >
                        Restore world
                    </button>
                ) : null}
            </div>

            {blockedReasons.length > 0 ? (
                <ul className="authoring-note" aria-label="Unavailable actions">
                    {blockedReasons.map((blocked) => (
                        <li key={blocked.action}>
                            {blocked.action.replace(/_/g, " ")} unavailable:{" "}
                            {ERROR_CODE_MESSAGE[blocked.reason] ?? "not allowed right now."}
                        </li>
                    ))}
                </ul>
            ) : null}

            <section className="authoring-section" aria-labelledby="world-rulesets-heading">
                <h2 id="world-rulesets-heading">Rulesets</h2>
                <ul>
                    {world.allowed_rulesets.map((ruleset) => (
                        <li key={ruleset.ruleset_id}>
                            {ruleset.display_name}
                            {ruleset.is_default ? " (default)" : ""}
                            {ruleset.current_version ? ` — ${ruleset.current_version.version_label}` : ""}
                        </li>
                    ))}
                </ul>
            </section>

            <section className="authoring-section" aria-labelledby="world-timelines-heading">
                <h2 id="world-timelines-heading">Timelines</h2>
                <TimelineTree worldId={world.world_id} timelines={world.timelines} />
            </section>

            <section className="authoring-section" aria-labelledby="world-campaigns-heading">
                <h2 id="world-campaigns-heading">Your campaigns in this world</h2>
                {world.managed_campaigns.length === 0 ? (
                    <p>You do not manage any campaigns in this world yet.</p>
                ) : (
                    <ul className="authoring-list">
                        {world.managed_campaigns.map((campaign) => (
                            <li className="authoring-list__item" key={campaign.campaign_id}>
                                {campaign.lifecycle_status === "active" ? (
                                    <Link to={`/app/${campaign.campaign_id}/home`}>
                                        {campaign.name}
                                    </Link>
                                ) : (
                                    <span>{campaign.name}</span>
                                )}
                                {campaign.lifecycle_status === "archived" ? (
                                    <LifecycleBadge status="archived" />
                                ) : null}
                            </li>
                        ))}
                    </ul>
                )}
            </section>

            <ConfirmDialog
                open={pendingAction !== null}
                title={pendingAction === "restore" ? "Restore this world?" : "Archive this world?"}
                description={
                    pendingAction === "restore"
                        ? "The world becomes editable again. Its timelines and campaigns are not changed."
                        : "An archived world is read-only until it is restored. Its timelines and campaigns are not changed, and it cannot be archived while it has active campaigns."
                }
                confirmLabel={pendingAction === "restore" ? "Restore world" : "Archive world"}
                onConfirm={confirm}
                onCancel={closeDialog}
                pending={mutation.status.kind === "pending"}
                reason={{
                    label: "Reason (optional)",
                    required: false,
                    value: reason,
                    onChange: setReason,
                    error: reasonError,
                }}
                error={
                    error === null ? null : error.kind === "stale" ? (
                        <div role="alert" className="authoring-message authoring-message--warning">
                            <p>
                                Someone else changed this world. Reload it to see the latest version.
                            </p>
                            <button
                                type="button"
                                className="authoring-button"
                                onClick={() => {
                                    mutation.reset()
                                    void refetch()
                                }}
                            >
                                Load latest version
                            </button>
                        </div>
                    ) : (
                        <MutationStatusMessage
                            error={error}
                            onRetry={mutation.retry}
                            onCheckSession={reload}
                        />
                    )
                }
            />
        </>
    )
}

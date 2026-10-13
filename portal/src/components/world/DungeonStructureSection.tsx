import { useEffect, useRef } from "react"
import { Link } from "react-router"
import { dungeonAuthoringPath } from "../../api/dungeonAuthoring"
import { useAuthoringResource } from "../../hooks/useAuthoringResource"
import type { DungeonAuthoringView } from "../../types/dungeonAuthoring"
import { describeBlockedReason } from "../../utils/blockedReason"
import { LifecycleBadge } from "../authoring/feedback"
import { worldRecordPath } from "./worldPaths"

interface Props {
    campaignId: string
    dungeonId: string
    // Changes when the record was refreshed (a lifecycle step, a save), so the list never outlives
    // the state that allowed the edit link.
    refreshToken: unknown
    // Opening an area or the editor from here keeps where the person came from.
    linkState?: object
    editHref: string
    editState?: object
}

// The areas of a dungeon and the connections between them, read-only. Adding, changing and
// connecting areas happens on the dungeon's edit page, which is offered only while the server says
// the dungeon can be edited.
export function DungeonStructureSection({ campaignId, dungeonId, refreshToken, linkState, editHref, editState }: Props) {
    const { state, refetch } = useAuthoringResource<DungeonAuthoringView>(dungeonAuthoringPath(campaignId, dungeonId))
    const first = useRef(true)
    useEffect(() => {
        if (first.current) {
            first.current = false
            return
        }
        void refetch()
    }, [refreshToken, refetch])

    if (state.kind === "loading") return <p role="status">Loading the dungeon&apos;s areas…</p>
    if (state.kind !== "ready") return <p role="alert">The dungeon&apos;s areas could not be loaded.</p>
    const view = state.data
    const canEdit = view.available_actions.includes("update")
    const blocked = view.blocked_actions.find((b) => b.action === "update")?.reason
    return (
        <>
            {view.areas.length === 0 ? (
                <p>No areas yet.</p>
            ) : (
                <ul className="op-list" aria-label="Areas">
                    {view.areas.map((area) => (
                        <li key={area.dungeon_area_id}>
                            <Link to={worldRecordPath(campaignId, "location", area.dungeon_area_id)} state={linkState}>
                                {area.name}
                            </Link>
                            {area.area_type !== null ? ` (${area.area_type})` : ""}{" "}
                            <LifecycleBadge
                                status={area.lifecycle_status === "archived" ? "archived" : area.canon_status}
                            />
                            . {area.feature_count} {area.feature_count === 1 ? "feature" : "features"},{" "}
                            {area.hazard_count} {area.hazard_count === 1 ? "hazard" : "hazards"},{" "}
                            {area.interactable_count} {area.interactable_count === 1 ? "interactable" : "interactables"}.
                        </li>
                    ))}
                </ul>
            )}
            {view.connections.length > 0 ? (
                <>
                    <h3>Connections</h3>
                    <ul className="record-list" aria-label="Connections">
                        {view.connections.map((c) => (
                            <li key={c.area_connection_id}>
                                {c.from_area.name} {c.is_one_way ? "to" : "and"} {c.to_area.name}:{" "}
                                {c.connection_type_label}
                                {c.is_hidden ? " (hidden)" : ""}
                            </li>
                        ))}
                    </ul>
                </>
            ) : null}
            {canEdit ? (
                <p className="authoring-page__actions-row">
                    <Link className="authoring-button" to={editHref} state={editState}>
                        Edit dungeon structure
                    </Link>
                </p>
            ) : blocked !== undefined ? (
                <p className="authoring-note">Editing unavailable: {describeBlockedReason(blocked)}</p>
            ) : null}
        </>
    )
}

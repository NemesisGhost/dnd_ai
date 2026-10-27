import type { RefreshOutcome } from "../../hooks/useAuthoringMutation"
import { useCallback, useState } from "react"
import { LocationCurrentState } from "../../pages/WorldLocationDetailPage"
import type { EntityLifecycleView } from "../../types/entityLifecycle"
import type { DungeonChoice, SetStateBody } from "../../types/dungeonAuthoring"
import type { LocationDetail } from "../../types/world"
import { focusSoon } from "../authoring/focusSoon"
import { useDungeonCommand } from "../authoring/useDungeonCommand"
import type { ReportUnsaved } from "../quests/useUnsavedReport"
import { AreaFactsEditor, StatusEditor } from "./AreaStateEditors"
import type { AreaRuntimeRead } from "./useDungeonRead"
import { playBlockedText } from "./worldStages"

interface Props {
    campaignId: string
    areaId: string
    location: LocationDetail
    // The area's canon and lifecycle status: the lifecycle read when the caller has one, else the
    // audience-safe detail's (a campaign GM with no world role has no lifecycle read). `null` only
    // when neither is known.
    lifecycleView: Pick<EntityLifecycleView, "canon_status" | "lifecycle_status"> | null
    read: AreaRuntimeRead
    // Reads the area again, and the facts above (the page's own detail).
    refresh: () => Promise<RefreshOutcome>
    onUnsaved: ReportUnsaved
}

const FEATURE_CHOICES: DungeonChoice[] = [
    { value: "intact", label: "Intact" },
    { value: "destroyed", label: "Destroyed" },
]

const labelOf = (choices: DungeonChoice[], value: string | null): string =>
    value === null ? "Not recorded" : (choices.find((c) => c.value === value)?.label ?? value.replace(/_/g, " "))

// A row of the recording list: what it is, what is true now, and the one control that changes it.
interface Row {
    // Where the editor's state is kept: unique within the section.
    key: string
    kind: string
    name: string
    current: string
    status: string | null
    stateEventId: string | null
    choices: DungeonChoice[]
    build: (status: string, expectedLastEventId: string | null) => SetStateBody
    message: string
}

const editButtonId = (key: string): string => `state-edit-${key}`

// What is true of a dungeon area in this campaign's timeline (searched, destroyed, alarm level,
// notes, and the status of each connection, feature, hazard and interactable), and the controls
// that record it. It is timeline state, recorded as events and apart from the area's definition; it
// can be recorded only for a published area in a published dungeon, which the server decides
// (`can_set_state`). Each Change opens one small editor under its row and records the event it was
// opened from, so a save never overwrites a newer state it has not seen.
export function AreaNowSection({ campaignId, areaId, location, lifecycleView, read, refresh, onUnsaved }: Props) {
    const [editing, setEditing] = useState<string | null>(null)
    const [editorDirty, setEditorDirty] = useState(false)
    const dungeonId = read.view?.dungeon.entity_id ?? ""
    const command = useDungeonCommand({ campaignId, dungeonId, areaId, scope: "state", refetch: refresh, pageStale: read.stale })
    const report = useCallback<ReportUnsaved>(
        (source, labels) => {
            if (source.startsWith("state-")) setEditorDirty(labels.length > 0)
            onUnsaved(source, labels)
        },
        [onUnsaved],
    )
    const blocked = playBlockedText(lifecycleView, "area")
    const { view } = read

    function open(key: string) {
        if (editing === key) {
            command.clear()
            setEditing(null)
            focusSoon(editButtonId(key))
            return
        }
        if (editing !== null && editorDirty) {
            // The open editor holds unsent input: show it instead of discarding it.
            focusSoon(editing === "area" ? "state-searched" : `state-${editing}-status`)
            return
        }
        setEditorDirty(false)
        command.clear()
        setEditing(key)
    }

    function close(key: string) {
        command.clear()
        setEditing(null)
        setEditorDirty(false)
        focusSoon(editButtonId(key))
    }

    const controls = (): React.ReactNode => {
        if (read.status === "loading") return <p role="status">Loading what can be recorded…</p>
        if (read.status === "unavailable") {
            return (
                <p className="authoring-note" role="status">
                    What is happening in this area is not available to you.
                </p>
            )
        }
        if (read.status !== "ready" || view === null) {
            return (
                <div role="alert">
                    <p>What can be recorded here could not be loaded.</p>
                    {read.status === "failed" ? (
                        <button type="button" className="authoring-button" onClick={() => void read.reload()}>
                            Try again
                        </button>
                    ) : null}
                </div>
            )
        }
        if (!view.can_set_state) {
            return (
                <p className="authoring-note">
                    Publish {view.dungeon.name} first. What is happening in an area can be recorded only once the area
                    and its dungeon are both published.
                </p>
            )
        }
        const choices = view.state_choices
        const connectionChoices = choices.connection_status ?? []
        const connectionName = (c: (typeof view.connections)[number]): string =>
            `${c.from_area.name} ${c.is_one_way ? "to" : "and"} ${c.to_area.name}`
        const rows: Row[] = [
            ...view.connections.map((c) => ({
                key: `connection-${c.area_connection_id}`,
                kind: "Connection",
                name: connectionName(c),
                current: labelOf(connectionChoices, c.status),
                status: c.status,
                stateEventId: c.state_event_id,
                choices: connectionChoices,
                build: (status: string, expected: string | null): SetStateBody => ({
                    kind: "connection",
                    target_id: c.area_connection_id,
                    expected_last_event_id: expected,
                    connection_status: status,
                }),
                message: "Connection status saved",
            })),
            ...view.hazards.map((h) => ({
                key: `hazard-${h.child_id}`,
                kind: "Hazard",
                name: h.child_type ?? "Hazard",
                current: labelOf(choices.hazard_status ?? [], h.status),
                status: h.status,
                stateEventId: h.state_event_id,
                choices: choices.hazard_status ?? [],
                build: (status: string, expected: string | null): SetStateBody => ({
                    kind: "hazard",
                    target_id: h.child_id,
                    expected_last_event_id: expected,
                    hazard_status: status,
                }),
                message: "Hazard status saved",
            })),
            ...view.interactables.map((i) => ({
                key: `interactable-${i.child_id}`,
                kind: "Interactable",
                name: i.child_type ?? "Interactable",
                current: labelOf(choices.interactable_status ?? [], i.status),
                status: i.status,
                stateEventId: i.state_event_id,
                choices: choices.interactable_status ?? [],
                build: (status: string, expected: string | null): SetStateBody => ({
                    kind: "interactable",
                    target_id: i.child_id,
                    expected_last_event_id: expected,
                    interactable_status: status,
                }),
                message: "Interactable status saved",
            })),
            ...view.features.map((f) => {
                const status = f.is_destroyed === true ? "destroyed" : f.is_destroyed === false ? "intact" : null
                return {
                    key: `feature-${f.child_id}`,
                    kind: "Feature",
                    name: f.child_type ?? "Feature",
                    current: labelOf(FEATURE_CHOICES, status),
                    status,
                    stateEventId: f.state_event_id,
                    choices: FEATURE_CHOICES,
                    build: (chosen: string, expected: string | null): SetStateBody => ({
                        kind: "feature",
                        target_id: f.child_id,
                        expected_last_event_id: expected,
                        is_destroyed: chosen === "destroyed",
                    }),
                    message: "Feature state saved",
                }
            }),
        ]
        // Two parts may share a name; the later ones are numbered so each control has its own name.
        const counts = new Map<string, number>()
        const seen = new Map<string, number>()
        for (const row of rows) counts.set(`${row.kind}:${row.name}`, (counts.get(`${row.kind}:${row.name}`) ?? 0) + 1)
        const named = rows.map((row) => {
            const id = `${row.kind}:${row.name}`
            if ((counts.get(id) ?? 0) < 2) return { row, label: row.name }
            const index = (seen.get(id) ?? 0) + 1
            seen.set(id, index)
            return { row, label: `${row.name} (${index})` }
        })
        const s = view.state
        return (
            <div className="area-section">
                {read.stale ? (
                    <p className="authoring-note" role="status">
                        The latest state could not be loaded, so what is shown may be out of date.{" "}
                        <button type="button" className="authoring-button" onClick={() => void read.reload()}>
                            Try again
                        </button>
                    </p>
                ) : null}
                {command.savedNotice}
                <p className="authoring-note">
                    Recording what is happening here does not change the area itself. Each change is recorded for this
                    campaign only.
                </p>
                <ul className="op-list connection-list" aria-label="What can be recorded">
                    <li>
                        <div className="connection-list__row">
                            <span className="connection-list__main">
                                <span className="connection-list__ends">The area</span>
                                <span className="connection-list__what">
                                    {s.state_event_id === null
                                        ? "Nothing has been recorded for this area yet."
                                        : `Searched: ${s.is_searched ? "Yes" : "No"} · Destroyed: ${s.is_destroyed ? "Yes" : "No"} · Alarm level: ${s.alarm_level} · Notes: ${s.condition_notes ?? "None"}`}
                                </span>
                            </span>
                            <span className="connection-list__actions">
                                <button
                                    type="button"
                                    id={editButtonId("area")}
                                    className="authoring-button"
                                    aria-label="Change the area's current state"
                                    aria-expanded={editing === "area"}
                                    aria-controls="state-area-form"
                                    onClick={() => open("area")}
                                >
                                    Change
                                </button>
                            </span>
                        </div>
                        {editing === "area" ? (
                            <div id="state-area-form">
                                <AreaFactsEditor
                                    areaId={areaId}
                                    state={s}
                                    options={view}
                                    command={command}
                                    onClose={() => close("area")}
                                    onUnsaved={report}
                                />
                            </div>
                        ) : null}
                    </li>
                    {named.map(({ row, label }) => (
                        <li key={row.key}>
                            <div className="connection-list__row">
                                <span className="connection-list__main">
                                    <span className="connection-list__ends">{label}</span>
                                    <span className="connection-list__what">
                                        {row.kind}: {row.current}
                                    </span>
                                </span>
                                <span className="connection-list__actions">
                                    <button
                                        type="button"
                                        id={editButtonId(row.key)}
                                        className="authoring-button"
                                        aria-label={`Change status of ${label}`}
                                        aria-expanded={editing === row.key}
                                        aria-controls={`state-${row.key}-form`}
                                        onClick={() => open(row.key)}
                                    >
                                        Change
                                    </button>
                                </span>
                            </div>
                            {editing === row.key ? (
                                <div id={`state-${row.key}-form`}>
                                    <StatusEditor
                                        source={`state-${row.key}`}
                                        label={label}
                                        current={row.status}
                                        stateEventId={row.stateEventId}
                                        choices={row.choices}
                                        build={row.build}
                                        successMessage={row.message}
                                        command={command}
                                        onClose={() => close(row.key)}
                                        onUnsaved={report}
                                    />
                                </div>
                            ) : null}
                        </li>
                    ))}
                </ul>
            </div>
        )
    }

    return (
        <>
            <LocationCurrentState location={location} embedded />
            {blocked !== null ? (
                <p className="authoring-note">{blocked}</p>
            ) : lifecycleView === null ? (
                <p className="authoring-note" role="status">
                    The area&apos;s status could not be loaded, so recording what happens here is not offered.
                </p>
            ) : (
                controls()
            )}
        </>
    )
}

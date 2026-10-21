import { useEffect, useState } from "react"
import type { DungeonChoice, DungeonOptions, SetStateBody } from "../../types/dungeonAuthoring"
import { YES_NO } from "../../utils/dungeonForm"
import { SelectField, TextAreaField, TextField } from "../authoring/fields"
import { focusSoon } from "../authoring/focusSoon"
import type { DungeonCommandHandle } from "../authoring/useDungeonCommand"
import { useRowDraft } from "../authoring/useRowDraft"
import { DraftConflict } from "../quests/DraftConflict"
import { useUnsavedReport } from "../quests/useUnsavedReport"
import type { ReportUnsaved } from "../quests/useUnsavedReport"
import "../authoring/authoring.css"

// The event a state was last written by travels in the draft as a field, so an untouched editor
// follows the latest and a dirty one whose state moved on pauses. What is sent is the event the
// editor last agreed with, never a later one read behind its back.
const eventOf = (id: string | null): string => id ?? ""
const eventToken = (event: string): string | null => (event === "" ? null : event)

interface AreaFacts {
    searched: string
    destroyed: string
    alarm: string
    notes: string
    event: string
    [field: string]: string
}

// The editor of the area's own current state (searched, destroyed, alarm level, notes). It records
// the campaign's state apart from the area's definition, as one event.
export function AreaFactsEditor({
    areaId,
    state,
    options,
    command,
    onClose,
    onUnsaved,
}: {
    areaId: string
    state: { is_searched: boolean; is_destroyed: boolean; alarm_level: number; condition_notes: string | null; state_event_id: string | null }
    options: DungeonOptions
    command: DungeonCommandHandle
    onClose: () => void
    onUnsaved: ReportUnsaved
}) {
    const draft = useRowDraft<AreaFacts>({
        searched: state.is_searched ? "yes" : "no",
        destroyed: state.is_destroyed ? "yes" : "no",
        alarm: String(state.alarm_level),
        notes: state.condition_notes ?? "",
        event: eventOf(state.state_event_id),
    })
    const [problem, setProblem] = useState<string | null>(null)
    useUnsavedReport(onUnsaved, "state-area", draft.dirty ? ["the area's state"] : [])
    useEffect(() => focusSoon("state-searched"), [])
    const set = (key: string, value: string) => draft.setValues({ ...draft.values, [key]: value })
    return (
        <form
            noValidate
            aria-label="Change the area's current state"
            className="inset-group dungeon-editor"
            onSubmit={(event) => {
                event.preventDefault()
                if (draft.conflict) return
                const level = Number(draft.values.alarm)
                if (
                    draft.values.alarm.trim() === "" ||
                    !Number.isInteger(level) ||
                    level < 0 ||
                    level > options.limits.alarm_level_max
                ) {
                    setProblem(`Alarm level is a whole number from 0 to ${options.limits.alarm_level_max}.`)
                    focusSoon("state-alarm")
                    return
                }
                setProblem(null)
                const body: SetStateBody = {
                    kind: "area",
                    target_id: areaId,
                    expected_last_event_id: eventToken(draft.agreed.event),
                    is_searched: draft.values.searched === "yes",
                    is_destroyed: draft.values.destroyed === "yes",
                    alarm_level: level,
                    condition_notes: draft.values.notes.trim() === "" ? null : draft.values.notes.trim(),
                }
                command.send({ op: "set_state", body }, "Area state saved", onClose)
            }}
        >
            {draft.conflict ? (
                <DraftConflict what="This state" onLatest={draft.loadLatest} onKeep={draft.keepMine} />
            ) : null}
            {command.notice}
            <div className="dungeon-editor__fields">
                <SelectField id="state-searched" label="Searched" value={draft.values.searched} options={YES_NO} onChange={(v) => set("searched", v)} />
                <SelectField id="state-destroyed" label="Destroyed" value={draft.values.destroyed} options={YES_NO} onChange={(v) => set("destroyed", v)} />
                <TextField id="state-alarm" label="Alarm level" value={draft.values.alarm} onChange={(v) => set("alarm", v)} error={problem} />
                <TextAreaField id="state-notes" label="Condition notes" value={draft.values.notes} onChange={(v) => set("notes", v)} />
            </div>
            <div className="row-actions">
                <button type="submit" className="authoring-button authoring-button--primary" disabled={command.busy || draft.conflict}>
                    Save area state
                </button>
                <button type="button" className="authoring-button" onClick={onClose}>
                    Cancel
                </button>
            </div>
        </form>
    )
}

interface StatusFields {
    status: string
    event: string
    [field: string]: string
}

// The editor of one part's status (a connection, feature, hazard or interactable): one select.
export function StatusEditor({
    source,
    label,
    current,
    stateEventId,
    choices,
    build,
    successMessage,
    command,
    onClose,
    onUnsaved,
}: {
    // The reporter name for the page's unsent-input guard.
    source: string
    // "Spike trap": what the row calls the part.
    label: string
    current: string | null
    stateEventId: string | null
    choices: DungeonChoice[]
    // The state body for the chosen status, given the event the editor last agreed with.
    build: (status: string, expectedLastEventId: string | null) => SetStateBody
    successMessage: string
    command: DungeonCommandHandle
    onClose: () => void
    onUnsaved: ReportUnsaved
}) {
    const draft = useRowDraft<StatusFields>({ status: current ?? "", event: eventOf(stateEventId) })
    const [problem, setProblem] = useState<string | null>(null)
    const id = `${source}-status`
    useUnsavedReport(onUnsaved, source, draft.dirty ? ["a status"] : [])
    useEffect(() => focusSoon(id), [id])
    return (
        <form
            noValidate
            aria-label={`Change status of ${label}`}
            className="inset-group dungeon-editor"
            onSubmit={(event) => {
                event.preventDefault()
                if (draft.conflict) return
                if (draft.values.status === "") {
                    setProblem("Choose a status.")
                    focusSoon(id)
                    return
                }
                setProblem(null)
                command.send(
                    { op: "set_state", body: build(draft.values.status, eventToken(draft.agreed.event)) },
                    successMessage,
                    onClose,
                )
            }}
        >
            {draft.conflict ? (
                <DraftConflict what="This status" onLatest={draft.loadLatest} onKeep={draft.keepMine} />
            ) : null}
            {command.notice}
            <div className="dungeon-editor__fields">
                <SelectField
                    id={id}
                    label={`New status for ${label}`}
                    value={draft.values.status}
                    placeholder="Choose a status"
                    options={choices}
                    error={problem}
                    onChange={(status) => draft.setValues({ ...draft.values, status })}
                />
            </div>
            <div className="row-actions">
                <button type="submit" className="authoring-button authoring-button--primary" disabled={command.busy || draft.conflict}>
                    Save status
                </button>
                <button type="button" className="authoring-button" onClick={onClose}>
                    Cancel
                </button>
            </div>
        </form>
    )
}

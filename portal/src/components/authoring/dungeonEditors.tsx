import { useEffect, useState } from "react"
import type { ConnectionView, DungeonOptions } from "../../types/dungeonAuthoring"
import { YES_NO } from "../../utils/dungeonForm"
import { DraftConflict } from "../quests/DraftConflict"
import { useUnsavedReport } from "../quests/useUnsavedReport"
import type { ReportUnsaved } from "../quests/useUnsavedReport"
import { connectionDraftOf, connectionFields, connectionProblem } from "./connectionDraft"
import type { ConnectionDraft } from "./connectionDraft"
import type { DungeonCommandHandle } from "./useDungeonCommand"
import { focusSoon } from "./focusSoon"
import { SelectField, TextAreaField } from "./fields"
import { useRowDraft } from "./useRowDraft"
import "./authoring.css"

export function ConnectionFormFields({
    prefix,
    options,
    draft,
    onChange,
    problem,
}: {
    prefix: string
    options: DungeonOptions
    draft: ConnectionDraft
    onChange: (next: ConnectionDraft) => void
    problem: string | null
}) {
    const set = (key: string, value: string) => onChange({ ...draft, [key]: value })
    return (
        <>
            <SelectField
                id={`${prefix}-type`}
                label="Kind of connection"
                value={draft.kind}
                placeholder="Choose a kind"
                required
                options={options.connection_types}
                error={problem}
                onChange={(value) => set("kind", value)}
            />
            <SelectField
                id={`${prefix}-oneway`}
                label="One way only"
                value={draft.oneWay}
                options={YES_NO}
                onChange={(value) => set("oneWay", value)}
            />
            <SelectField
                id={`${prefix}-hidden`}
                label="Built to be concealed"
                value={draft.hidden}
                options={YES_NO}
                onChange={(value) => set("hidden", value)}
            />
            <TextAreaField
                id={`${prefix}-description`}
                label="Description"
                value={draft.description}
                onChange={(value) => set("description", value)}
            />
            <SelectField
                id={`${prefix}-conditional`}
                label="Only passable under a condition"
                value={draft.conditional}
                options={YES_NO}
                onChange={(value) => set("conditional", value)}
            />
            {draft.conditional === "yes" ? (
                <TextAreaField
                    id={`${prefix}-condition`}
                    label="The condition"
                    value={draft.condition}
                    onChange={(value) => set("condition", value)}
                />
            ) : null}
        </>
    )
}

// The editor of one connection, opened under its row. It starts from the row as the page last read
// it, follows the saved row while untouched, and when the row changed elsewhere under unsent edits
// pauses saving until the person chooses. It closes only when the server accepted the save.
export function ConnectionEditor({
    connection,
    label,
    options,
    version,
    command,
    onClose,
    onUnsaved,
}: {
    connection: ConnectionView
    // "Entry Hall and Vault": the connection's name for labels.
    label: string
    options: DungeonOptions
    // The dungeon version the page last read; every structural command names it.
    version: number
    command: DungeonCommandHandle
    onClose: () => void
    onUnsaved: ReportUnsaved
}) {
    const draft = useRowDraft<ConnectionDraft>(connectionDraftOf(connection))
    const [problem, setProblem] = useState<string | null>(null)
    const prefix = `conn-${connection.area_connection_id}`
    useUnsavedReport(onUnsaved, prefix, draft.dirty ? ["a connection"] : [])
    useEffect(() => focusSoon(`${prefix}-type`), [prefix])
    return (
        <form
            noValidate
            aria-label={`Edit connection ${label}`}
            className="inset-group dungeon-editor"
            onSubmit={(event) => {
                event.preventDefault()
                if (draft.conflict) return
                const found = connectionProblem(draft.values)
                setProblem(found)
                if (found !== null) return
                command.send(
                    {
                        op: "update_connection",
                        connectionId: connection.area_connection_id,
                        body: { expected_row_version: version, ...connectionFields(draft.values) },
                    },
                    "Connection saved",
                    onClose,
                )
            }}
        >
            {draft.conflict ? (
                <DraftConflict what="This connection" onLatest={draft.loadLatest} onKeep={draft.keepMine} />
            ) : null}
            {command.notice}
            <div className="dungeon-editor__fields">
                <ConnectionFormFields
                    prefix={prefix}
                    options={options}
                    draft={draft.values}
                    onChange={draft.setValues}
                    problem={problem}
                />
            </div>
            <div className="row-actions">
                <button
                    type="submit"
                    className="authoring-button authoring-button--primary"
                    disabled={command.busy || draft.conflict}
                >
                    Save connection
                </button>
                <button type="button" className="authoring-button" onClick={onClose}>
                    Cancel
                </button>
            </div>
        </form>
    )
}

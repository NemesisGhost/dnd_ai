import { useEffect, useState } from "react"
import type { ChildKind, ChildView, DungeonOptions } from "../../types/dungeonAuthoring"
import { YES_NO } from "../../utils/dungeonForm"
import { DraftConflict } from "../quests/DraftConflict"
import { useUnsavedReport } from "../quests/useUnsavedReport"
import type { ReportUnsaved } from "../quests/useUnsavedReport"
import { childDraftOf, childFields, childProblem } from "./childDraft"
import type { ChildDraft } from "./childDraft"
import { SelectField, TextAreaField, TextField } from "./fields"
import { focusSoon } from "./focusSoon"
import type { DungeonCommandHandle } from "./useDungeonCommand"
import { changedFields, useRetainedInput } from "./permissionLoss"
import { useRowDraft } from "./useRowDraft"
import "./authoring.css"

export function ChildFormFields({
    prefix,
    kind,
    typeLabel,
    options,
    draft,
    onChange,
    problem,
}: {
    prefix: string
    kind: ChildKind
    typeLabel: string
    options: DungeonOptions
    draft: ChildDraft
    onChange: (next: ChildDraft) => void
    problem: string | null
}) {
    const set = (key: string, value: string) => onChange({ ...draft, [key]: value })
    return (
        <>
            <TextField
                id={`${prefix}-type`}
                label={typeLabel}
                value={draft.childType}
                onChange={(value) => set("childType", value)}
                maxLength={options.limits.short_text_max_length}
            />
            <TextAreaField
                id={`${prefix}-description`}
                label="Description"
                value={draft.description}
                onChange={(value) => set("description", value)}
                maxLength={options.limits.notes_max_length}
            />
            <SelectField
                id={`${prefix}-hidden`}
                label="Built to be concealed"
                hint="A fact about the object itself, not about whether anyone has found it."
                value={draft.hidden}
                options={YES_NO}
                onChange={(value) => set("hidden", value)}
            />
            {kind === "hazard" ? (
                <TextField
                    id={`${prefix}-severity`}
                    label={`Severity (${options.limits.rating_min} to ${options.limits.rating_max})`}
                    value={draft.severity}
                    onChange={(value) => set("severity", value)}
                    error={problem}
                />
            ) : null}
        </>
    )
}

// The editor of one feature, hazard or interactable, opened under its row. Like a connection's, it
// follows the saved row while untouched, pauses on a conflict, and closes only on success. Children
// are structure of the dungeon, so a save names the dungeon's version.
export function ChildEditor({
    child,
    singular,
    name,
    typeLabel,
    options,
    version,
    command,
    onClose,
    onUnsaved,
}: {
    child: ChildView
    singular: string
    // What the row calls the child ("Spike trap").
    name: string
    typeLabel: string
    options: DungeonOptions
    // The dungeon version the page last read.
    version: number
    command: DungeonCommandHandle
    onClose: () => void
    onUnsaved: ReportUnsaved
}) {
    const draft = useRowDraft<ChildDraft>(childDraftOf(child))
    const [problem, setProblem] = useState<string | null>(null)
    const prefix = `child-${child.child_id}`
    useUnsavedReport(onUnsaved, prefix, draft.dirty ? [`a ${singular}`] : [])
    useRetainedInput(prefix, `${singular.charAt(0).toUpperCase()}${singular.slice(1)} ${name}`, draft.dirty ? changedFields(draft.agreed, draft.values) : [])
    useEffect(() => focusSoon(`${prefix}-type`), [prefix])
    return (
        <form
            noValidate
            aria-label={`Edit ${singular} ${name}`}
            className="inset-group dungeon-editor"
            onSubmit={(event) => {
                event.preventDefault()
                if (draft.conflict) return
                const found = childProblem(draft.values, child.kind, options.limits.rating_min, options.limits.rating_max)
                setProblem(found)
                if (found !== null) return
                command.send(
                    {
                        op: "update_child",
                        kind: child.kind,
                        childId: child.child_id,
                        body: { ...childFields(draft.values, child.kind), expected_row_version: version },
                    },
                    `${singular.charAt(0).toUpperCase()}${singular.slice(1)} saved`,
                    onClose,
                )
            }}
        >
            {draft.conflict ? (
                <DraftConflict what={`This ${singular}`} onLatest={draft.loadLatest} onKeep={draft.keepMine} />
            ) : null}
            {command.notice}
            <div className="dungeon-editor__fields">
                <ChildFormFields
                    prefix={prefix}
                    kind={child.kind}
                    typeLabel={typeLabel}
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
                    Save {singular}
                </button>
                <button type="button" className="authoring-button" onClick={onClose}>
                    Cancel
                </button>
            </div>
        </form>
    )
}

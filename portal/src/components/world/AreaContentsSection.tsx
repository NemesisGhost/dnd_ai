import { useCallback, useState } from "react"
import { Link } from "react-router"
import type { AreaAuthoringView, ChildKind, ChildView, ConnectionView } from "../../types/dungeonAuthoring"
import { CHILD_KINDS, EMPTY_CHILD, childFields, childProblem } from "../authoring/childDraft"
import type { ChildDraft } from "../authoring/childDraft"
import { ChildEditor, ChildFormFields } from "../authoring/childEditors"
import { ConfirmDialog } from "../authoring/ConfirmDialog"
import { focusSoon } from "../authoring/focusSoon"
import { changedFields, useRetainedInput } from "../authoring/permissionLoss"
import { useDungeonCommand } from "../authoring/useDungeonCommand"
import type { DungeonCommandHandle } from "../authoring/useDungeonCommand"
import { useUnsavedReport } from "../quests/useUnsavedReport"
import type { ReportUnsaved } from "../quests/useUnsavedReport"
import type { AreaRead } from "./useDungeonRead"

interface Props {
    campaignId: string
    areaId: string
    read: AreaRead
    // Reads the area, its lifecycle and its revisions again after a change.
    refresh: () => Promise<void>
    // The dungeon's Connections section, where an area's connections are managed.
    connectionsHref: string
    linkState?: object
    onUnsaved: ReportUnsaved
}

// How a canon status reads in a sentence about what can be edited.
const STATUS_WORDS: Readonly<Record<string, string>> = {
    draft: "a draft",
    proposed: "in review",
    approved: "approved but not published",
    canon: "published",
    rejected: "rejected",
    superseded: "replaced",
}
const statusWords = (ref: { canon_status: string; lifecycle_status: string }): string =>
    ref.lifecycle_status === "archived" ? "archived" : (STATUS_WORDS[ref.canon_status] ?? ref.canon_status)

const nameOf = (child: ChildView, singular: string): string =>
    child.child_type ?? `${singular.charAt(0).toUpperCase()}${singular.slice(1)}`

// Two hazards may both be "Spike trap": the later ones are numbered so every row, and the buttons
// in it, can be told apart by name.
function rowNames(children: ChildView[], singular: string): string[] {
    const seen = new Map<string, number>()
    const total = new Map<string, number>()
    for (const child of children) total.set(nameOf(child, singular), (total.get(nameOf(child, singular)) ?? 0) + 1)
    return children.map((child) => {
        const base = nameOf(child, singular)
        if ((total.get(base) ?? 0) < 2) return base
        const index = (seen.get(base) ?? 0) + 1
        seen.set(base, index)
        return `${base} (${index})`
    })
}

const flagsOf = (child: ChildView): string =>
    [child.is_hidden ? "Concealed" : null, child.severity !== null ? `Severity ${child.severity}` : null]
        .filter((part) => part !== null)
        .join(" · ")

const connectionName = (c: ConnectionView): string =>
    `${c.from_area.name} ${c.is_one_way ? "to" : "and"} ${c.to_area.name}`

const addToggleId = (kind: ChildKind): string => `contents-add-${kind}`
const addTypeId = (kind: ChildKind): string => `contents-new-${kind}-type`
const editButtonId = (id: string): string => `child-edit-${id}`

type Origin = ChildKind | "edit" | "remove"

// What an area holds: its features, hazards and interactables, in three compact groups, and the
// connections it has (managed from the dungeon). These are the definition: what each is, never
// whether it has been triggered or destroyed in this campaign (that is Area now). Children are
// structure of the dungeon, so every change names the dungeon's version.
export function AreaContentsSection({ campaignId, areaId, read, refresh, connectionsHref, linkState, onUnsaved }: Props) {
    const [open, setOpen] = useState<Record<ChildKind, boolean>>({ feature: false, hazard: false, interactable: false })
    const [drafts, setDrafts] = useState<Record<ChildKind, ChildDraft>>({
        feature: EMPTY_CHILD,
        hazard: EMPTY_CHILD,
        interactable: EMPTY_CHILD,
    })
    const [problems, setProblems] = useState<Record<ChildKind, string | null>>({
        feature: null,
        hazard: null,
        interactable: null,
    })
    const [editing, setEditing] = useState<string | null>(null)
    const [editorDirty, setEditorDirty] = useState(false)
    const [removing, setRemoving] = useState<{ child: ChildView; singular: string; name: string } | null>(null)
    const [origin, setOrigin] = useState<Origin>("edit")
    const dungeonId = read.view?.dungeon.entity_id ?? ""
    const base = useDungeonCommand({ campaignId, dungeonId, areaId, scope: "contents", refetch: refresh })
    const commandFor = (from: Origin): DungeonCommandHandle => ({
        busy: base.busy,
        notice: origin === from ? base.notice : null,
        clear: base.clear,
        send: (command, message, after) => {
            setOrigin(from)
            base.send(command, message, after)
        },
    })
    useUnsavedReport(
        onUnsaved,
        "new-contents",
        CHILD_KINDS.filter(({ kind }) => JSON.stringify(drafts[kind]) !== JSON.stringify(EMPTY_CHILD)).map(
            ({ singular }) => `a new ${singular}`,
        ),
    )
    useRetainedInput(
        "new-contents",
        "New contents",
        CHILD_KINDS.flatMap(({ kind, singular }) =>
            changedFields(EMPTY_CHILD, drafts[kind]).map((c) => ({ ...c, label: `${singular} · ${c.label}` })),
        ),
    )
    const report = useCallback<ReportUnsaved>(
        (source, labels) => {
            // Only the open editor reports under a child's own source.
            if (source.startsWith("child-")) setEditorDirty(labels.length > 0)
            onUnsaved(source, labels)
        },
        [onUnsaved],
    )

    const { view, options } = read
    if (read.status === "loading") return <p role="status">Loading the area&apos;s contents…</p>
    if (read.status !== "ready" || view === null || options === null) {
        return (
            <div role="alert">
                <p>The area&apos;s contents could not be loaded.</p>
                {read.status === "failed" ? (
                    <button type="button" className="authoring-button" onClick={() => void read.reload()}>
                        Try again
                    </button>
                ) : null}
            </div>
        )
    }

    const can = (action: string): boolean => view.structure_actions.includes(action)
    const lists: Record<ChildKind, ChildView[]> = {
        feature: view.features,
        hazard: view.hazards,
        interactable: view.interactables,
    }
    const dungeon = view.dungeon
    const canChange = view.structure_actions.length > 0
    const canRemoveAny = CHILD_KINDS.some(({ kind }) => can(`remove_${kind}`))
    const hasChildren = CHILD_KINDS.some(({ kind }) => lists[kind].length > 0)

    function openEditor(id: string) {
        if (editing === id) {
            base.clear()
            setEditing(null)
            focusSoon(editButtonId(id))
            return
        }
        if (editing !== null && editorDirty) {
            // The open editor holds unsent edits: show it instead of discarding them.
            focusSoon(`child-${editing}-type`)
            return
        }
        setEditorDirty(false)
        base.clear()
        setEditing(id)
    }

    function closeEditor(id: string) {
        base.clear()
        setEditing(null)
        setEditorDirty(false)
        focusSoon(editButtonId(id))
    }

    function submitNew(kind: ChildKind, singular: string, area: AreaAuthoringView) {
        const found = childProblem(drafts[kind], kind, options!.limits.rating_min, options!.limits.rating_max)
        setProblems({ ...problems, [kind]: found })
        if (found !== null) {
            focusSoon(`contents-new-${kind}-severity`)
            return
        }
        commandFor(kind).send(
            {
                op: "add_child",
                kind,
                body: {
                    ...childFields(drafts[kind], kind),
                    expected_row_version: area.dungeon_row_version,
                    dungeon_area_id: area.dungeon_area_id,
                },
            },
            `${singular.charAt(0).toUpperCase()}${singular.slice(1)} added`,
            () => {
                setDrafts((current) => ({ ...current, [kind]: EMPTY_CHILD }))
                setProblems((current) => ({ ...current, [kind]: null }))
                focusSoon(addTypeId(kind))
            },
        )
    }

    return (
        <div className="area-section">
            {read.stale ? (
                <p className="authoring-note" role="status">
                    The latest contents could not be loaded, so this list may be out of date.{" "}
                    <button type="button" className="authoring-button" onClick={() => void read.reload()}>
                        Try again
                    </button>
                </p>
            ) : null}
            {!canChange ? (
                <p className="authoring-note">
                    Contents can be changed while both this area and {dungeon.name} can be edited. This area is{" "}
                    {statusWords(view)}; {dungeon.name} is {statusWords(dungeon)}.
                </p>
            ) : !canRemoveAny && hasChildren ? (
                <p className="authoring-note">Contents can be removed only while the dungeon is a draft.</p>
            ) : null}

            {CHILD_KINDS.map(({ kind, plural: groupName, singular, typeLabel }) => {
                const children = lists[kind]
                const names = rowNames(children, singular)
                const noun = groupName.toLowerCase()
                return (
                    <section key={kind} aria-label={groupName} className="contents-group">
                        <div className="area-bar">
                            <h3 className="area-bar__count">
                                {groupName} ({children.length})
                            </h3>
                            {can(`add_${kind}`) ? (
                                <button
                                    type="button"
                                    id={addToggleId(kind)}
                                    className="authoring-button"
                                    aria-expanded={open[kind]}
                                    aria-controls={`contents-add-${kind}-form`}
                                    onClick={() => {
                                        setOpen({ ...open, [kind]: !open[kind] })
                                        if (!open[kind]) focusSoon(addTypeId(kind))
                                    }}
                                >
                                    {open[kind] ? `Close the add ${singular} form` : `Add ${singular}`}
                                </button>
                            ) : null}
                        </div>
                        {commandFor(kind).notice}
                        {can(`add_${kind}`) && open[kind] ? (
                            <form
                                id={`contents-add-${kind}-form`}
                                noValidate
                                aria-label={`Add a ${singular}`}
                                className="inset-group dungeon-editor"
                                onSubmit={(event) => {
                                    event.preventDefault()
                                    submitNew(kind, singular, view)
                                }}
                            >
                                <div className="dungeon-editor__fields">
                                    <ChildFormFields
                                        prefix={`contents-new-${kind}`}
                                        kind={kind}
                                        typeLabel={typeLabel}
                                        options={options}
                                        draft={drafts[kind]}
                                        onChange={(next) => setDrafts({ ...drafts, [kind]: next })}
                                        problem={problems[kind]}
                                    />
                                </div>
                                <div className="row-actions">
                                    <button
                                        type="submit"
                                        className="authoring-button authoring-button--primary"
                                        disabled={base.busy}
                                    >
                                        Add {singular}
                                    </button>
                                    <button
                                        type="button"
                                        className="authoring-button"
                                        onClick={() => {
                                            setOpen({ ...open, [kind]: false })
                                            focusSoon(addToggleId(kind))
                                        }}
                                    >
                                        Done
                                    </button>
                                </div>
                            </form>
                        ) : null}
                        {children.length === 0 ? (
                            <p className="member-roster__empty">No {noun} yet.</p>
                        ) : (
                            <ul className="op-list connection-list" aria-label={groupName}>
                                {children.map((child, index) => {
                                    const name = names[index]!
                                    const isOpen = editing === child.child_id
                                    return (
                                        <li key={child.child_id}>
                                            <div className="connection-list__row">
                                                <span className="connection-list__main">
                                                    <span className="connection-list__ends">{name}</span>
                                                    {flagsOf(child) !== "" ? (
                                                        <span className="connection-list__what">{flagsOf(child)}</span>
                                                    ) : null}
                                                    {child.description !== null ? (
                                                        <span className="area-list__summary">{child.description}</span>
                                                    ) : null}
                                                </span>
                                                <span className="connection-list__actions">
                                                    {can(`update_${kind}`) ? (
                                                        <button
                                                            type="button"
                                                            id={editButtonId(child.child_id)}
                                                            className="authoring-button"
                                                            aria-label={`Edit ${singular} ${name}`}
                                                            aria-expanded={isOpen}
                                                            aria-controls={`child-${child.child_id}-form`}
                                                            onClick={() => openEditor(child.child_id)}
                                                        >
                                                            Edit
                                                        </button>
                                                    ) : null}
                                                    {can(`remove_${kind}`) ? (
                                                        <button
                                                            type="button"
                                                            className="authoring-button"
                                                            aria-label={`Remove ${singular} ${name}`}
                                                            onClick={() => setRemoving({ child, singular, name })}
                                                        >
                                                            Remove
                                                        </button>
                                                    ) : null}
                                                </span>
                                            </div>
                                            {isOpen ? (
                                                <div id={`child-${child.child_id}-form`}>
                                                    <ChildEditor
                                                        child={child}
                                                        singular={singular}
                                                        name={name}
                                                        typeLabel={typeLabel}
                                                        options={options}
                                                        version={view.dungeon_row_version}
                                                        command={commandFor("edit")}
                                                        onClose={() => closeEditor(child.child_id)}
                                                        onUnsaved={report}
                                                    />
                                                </div>
                                            ) : null}
                                        </li>
                                    )
                                })}
                            </ul>
                        )}
                    </section>
                )
            })}

            <section aria-label="Connections of this area" className="contents-group">
                <div className="area-bar">
                    <h3 className="area-bar__count">Connections of this area ({view.connections.length})</h3>
                    <Link to={connectionsHref} state={linkState}>
                        Manage in the dungeon&apos;s Connections
                    </Link>
                </div>
                {view.connections.length === 0 ? (
                    <p className="member-roster__empty">No connections. Add them in the dungeon&apos;s Connections.</p>
                ) : (
                    <ul className="op-list connection-list" aria-label="Connections of this area">
                        {view.connections.map((c) => (
                            <li key={c.area_connection_id}>
                                <span className="connection-list__ends">{connectionName(c)}</span>{" "}
                                <span className="connection-list__what">
                                    {[c.connection_type_label, c.is_one_way ? "one way" : null, c.is_hidden ? "concealed" : null]
                                        .filter((part) => part !== null)
                                        .join(" · ")}
                                </span>
                            </li>
                        ))}
                    </ul>
                )}
            </section>

            <ConfirmDialog
                open={removing !== null}
                title={removing === null ? "" : `Remove this ${removing.singular}?`}
                description={
                    removing === null
                        ? ""
                        : `The ${removing.singular} ${removing.name} will be removed from this area. This cannot be undone.`
                }
                confirmLabel={removing === null ? "Remove" : `Remove ${removing.singular}`}
                pending={base.busy}
                error={removing === null ? null : commandFor("remove").notice}
                onConfirm={() => {
                    if (removing === null) return
                    const target = removing
                    commandFor("remove").send(
                        {
                            op: "remove_child",
                            kind: target.child.kind,
                            childId: target.child.child_id,
                            expected_row_version: view.dungeon_row_version,
                        },
                        `${target.singular.charAt(0).toUpperCase()}${target.singular.slice(1)} ${target.name} removed`,
                        () => {
                            setRemoving(null)
                            if (editing === target.child.child_id) setEditing(null)
                            focusSoon(can(`add_${target.child.kind}`) ? addToggleId(target.child.kind) : "world-section-contents-heading")
                        },
                    )
                }}
                onCancel={() => setRemoving(null)}
            />
        </div>
    )
}

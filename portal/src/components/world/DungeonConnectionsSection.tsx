import type { RefreshOutcome } from "../../hooks/useAuthoringMutation"
import { useCallback, useState } from "react"
import { Link } from "react-router"
import type { ConnectionView } from "../../types/dungeonAuthoring"
import { describeBlockedReason } from "../../utils/blockedReason"
import { ConfirmDialog } from "../authoring/ConfirmDialog"
import { EMPTY_CONNECTION, connectionFields, connectionProblem } from "../authoring/connectionDraft"
import type { ConnectionDraft } from "../authoring/connectionDraft"
import { ConnectionEditor, ConnectionFormFields } from "../authoring/dungeonEditors"
import { focusSoon } from "../authoring/focusSoon"
import { changedFields, useRetainedInput } from "../authoring/permissionLoss"
import { useDungeonCommand } from "../authoring/useDungeonCommand"
import type { DungeonCommandHandle } from "../authoring/useDungeonCommand"
import { SelectField } from "../authoring/fields"
import { useUnsavedReport } from "../quests/useUnsavedReport"
import type { ReportUnsaved } from "../quests/useUnsavedReport"
import { plural } from "./areaText"
import type { DungeonRead } from "./useDungeonRead"

interface Props {
    campaignId: string
    dungeonId: string
    read: DungeonRead
    refresh: () => Promise<RefreshOutcome>
    // The Areas section, for the line that says connections need two areas.
    areasHref: string
    linkState?: object
    onUnsaved: ReportUnsaved
}

// "Entry Hall and Vault", or "Entry Hall to Vault" for a one-way passage.
const connectionName = (c: ConnectionView): string =>
    `${c.from_area.name} ${c.is_one_way ? "to" : "and"} ${c.to_area.name}`

// What sets the connection apart, in words: its kind and then each property that applies.
function describeConnection(c: ConnectionView): string {
    return [
        c.connection_type_label,
        c.is_one_way ? "one way" : null,
        c.is_hidden ? "concealed" : null,
        c.is_conditional ? `only if: ${c.condition_description ?? "a condition holds"}` : null,
    ]
        .filter((part) => part !== null)
        .join(" · ")
}

const ADD_FROM_ID = "conn-add-from"
const ADD_TOGGLE_ID = "conn-add-toggle"
const editButtonId = (id: string): string => `conn-edit-${id}`

// The passages between a dungeon's areas, one ruled row each. Edit opens one editor under its row
// (one at a time); Add reveals a form above the list; Remove asks first and exists only while the
// dungeon is a draft. A connection's runtime status belongs to an area's Area now, not here.
export function DungeonConnectionsSection({ campaignId, dungeonId, read, refresh, areasHref, linkState, onUnsaved }: Props) {
    const [adding, setAdding] = useState(false)
    const [from, setFrom] = useState("")
    const [to, setTo] = useState("")
    const [draft, setDraft] = useState<ConnectionDraft>(EMPTY_CONNECTION)
    const [problem, setProblem] = useState<string | null>(null)
    const [editing, setEditing] = useState<string | null>(null)
    const [editorDirty, setEditorDirty] = useState(false)
    const [removing, setRemoving] = useState<ConnectionView | null>(null)
    // One mutation for the section; the failure notice appears where the command was sent from.
    const [origin, setOrigin] = useState<"add" | "edit" | "remove">("add")
    const base = useDungeonCommand({ campaignId, dungeonId, areaId: null, scope: "connections", refetch: refresh, pageStale: read.stale })
    const commandFor = (from: typeof origin): DungeonCommandHandle => ({
        busy: base.busy,
        notice: origin === from ? base.notice : null,
        savedNotice: null,
        clear: base.clear,
        send: (command, message, after) => {
            setOrigin(from)
            base.send(command, message, after)
        },
    })
    const dirtyNew =
        from !== "" ||
        to !== "" ||
        Object.keys(EMPTY_CONNECTION).some((key) => draft[key]!.trim() !== EMPTY_CONNECTION[key]!)
    useUnsavedReport(onUnsaved, "new-connection", dirtyNew ? ["a connection"] : [])
    // The chosen areas are shown only as chosen: their names come from the private read, which a
    // permission loss discards, so no server-loaded name is copied into what is retained.
    useRetainedInput("new-connection", "New connection", [
        ...(from === "" ? [] : [{ label: "From area", value: "Selected" }]),
        ...(to === "" ? [] : [{ label: "To area", value: "Selected" }]),
        ...changedFields(EMPTY_CONNECTION, draft),
    ])
    // The open editor reports its own unsent edits; remember whether it holds any, so opening a
    // second editor over them is refused rather than discarding them.
    const report = useCallback<ReportUnsaved>(
        (source, labels) => {
            // Only the open editor reports under a connection's own source.
            if (source.startsWith("conn-")) setEditorDirty(labels.length > 0)
            onUnsaved(source, labels)
        },
        [onUnsaved],
    )

    const { view, options } = read
    if (read.status === "loading") return <p role="status">Loading the dungeon&apos;s connections…</p>
    if (read.status !== "ready" || view === null || options === null) {
        return (
            <div role="alert">
                <p>The dungeon&apos;s connections could not be loaded.</p>
                {read.status === "failed" ? (
                    <button type="button" className="authoring-button" onClick={() => void read.reload()}>
                        Try again
                    </button>
                ) : null}
            </div>
        )
    }

    const can = (action: string): boolean => view.available_actions.includes(action)
    const blocked = (action: string): string | undefined => view.blocked_actions.find((b) => b.action === action)?.reason
    const areaOptions = view.areas.map((a) => ({ value: a.dungeon_area_id, label: a.name }))
    
    function openEditor(id: string) {
        if (editing === id) {
            setEditing(null)
            focusSoon(editButtonId(id))
            return
        }
        if (editing !== null && editorDirty) {
            // The open editor holds unsent edits: show it instead of discarding them.
            focusSoon(`conn-${editing}-type`)
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

    function submitNew() {
        const found =
            from === "" || to === ""
                ? "Choose both areas."
                : from === to
                  ? "Choose two different areas."
                  : connectionProblem(draft)
        setProblem(found)
        if (found !== null) return
        const named = `${view?.areas.find((a) => a.dungeon_area_id === from)?.name ?? "The first area"} and ${view?.areas.find((a) => a.dungeon_area_id === to)?.name ?? "the second"}`
        commandFor("add").send(
            {
                op: "add_connection",
                body: {
                    expected_row_version: view!.row_version,
                    from_area_id: from,
                    to_area_id: to,
                    ...connectionFields(draft),
                },
            },
            `Connection between ${named} added`,
            () => {
                setFrom("")
                setTo("")
                setDraft(EMPTY_CONNECTION)
                setProblem(null)
                focusSoon(ADD_FROM_ID)
            },
        )
    }

    return (
        <div className="area-section">
            {read.stale ? (
                <p className="authoring-note" role="status">
                    The latest connections could not be loaded, so this list may be out of date.{" "}
                    <button type="button" className="authoring-button" onClick={() => void read.reload()}>
                        Try again
                    </button>
                </p>
            ) : null}
            {base.savedNotice}
            <div className="area-bar">
                <p className="area-bar__count">
                    <strong>{plural(view.connections.length, "connection", "connections")}</strong>
                </p>
                {can("add_connection") && view.areas.length >= 2 ? (
                    <button
                        type="button"
                        id={ADD_TOGGLE_ID}
                        className="authoring-button"
                        aria-expanded={adding}
                        aria-controls="conn-add-form"
                        onClick={() => {
                            setAdding(!adding)
                            if (!adding) focusSoon(ADD_FROM_ID)
                        }}
                    >
                        {adding ? "Close the add connection form" : "Add connection"}
                    </button>
                ) : null}
            </div>
            {!can("add_connection") ? (
                <p className="authoring-note">
                    {blocked("update") !== undefined
                        ? `Adding a connection is unavailable: ${describeBlockedReason(blocked("update")!)}`
                        : "Adding a connection is unavailable right now."}
                </p>
            ) : view.areas.length < 2 ? (
                <p className="authoring-note">
                    Add at least two areas to connect them.{" "}
                    <Link to={areasHref} state={linkState}>
                        Go to Areas
                    </Link>
                </p>
            ) : null}
            {commandFor("add").notice}

            {can("add_connection") && view.areas.length >= 2 && adding ? (
                <form
                    id="conn-add-form"
                    noValidate
                    aria-label="Add a connection"
                    className="inset-group dungeon-editor"
                    onSubmit={(event) => {
                        event.preventDefault()
                        submitNew()
                    }}
                >
                    <div className="dungeon-editor__fields">
                        <SelectField
                            id={ADD_FROM_ID}
                            label="From area"
                            value={from}
                            placeholder="Choose an area"
                            required
                            options={areaOptions}
                            onChange={setFrom}
                        />
                        <SelectField
                            id="conn-add-to"
                            label="To area"
                            value={to}
                            placeholder="Choose an area"
                            required
                            options={areaOptions}
                            onChange={setTo}
                        />
                        <ConnectionFormFields
                            prefix="conn-new"
                            options={options}
                            draft={draft}
                            onChange={setDraft}
                            problem={problem}
                        />
                    </div>
                    <div className="row-actions">
                        <button
                            type="submit"
                            className="authoring-button authoring-button--primary"
                            disabled={base.busy}
                        >
                            Add connection
                        </button>
                        <button
                            type="button"
                            className="authoring-button"
                            onClick={() => {
                                setAdding(false)
                                focusSoon(ADD_TOGGLE_ID)
                            }}
                        >
                            Done
                        </button>
                    </div>
                </form>
            ) : null}

            {view.connections.length === 0 ? (
                <p className="member-roster__empty">No connections yet.</p>
            ) : (
                <ul className="op-list connection-list" aria-label="Connections">
                    {view.connections.map((connection) => {
                        const id = connection.area_connection_id
                        const label = connectionName(connection)
                        const open = editing === id
                        return (
                            <li key={id}>
                                <div className="connection-list__row">
                                    <span className="connection-list__main">
                                        <span className="connection-list__ends">
                                            <span aria-hidden="true">
                                                {connection.from_area.name} {connection.is_one_way ? "→" : "↔"}{" "}
                                                {connection.to_area.name}
                                            </span>
                                            <span className="visually-hidden">{label}</span>
                                        </span>
                                        <span className="connection-list__what">{describeConnection(connection)}</span>
                                        {connection.description !== null ? (
                                            <span className="area-list__summary">{connection.description}</span>
                                        ) : null}
                                    </span>
                                    <span className="connection-list__actions">
                                        {can("update_connection") ? (
                                            <button
                                                type="button"
                                                id={editButtonId(id)}
                                                className="authoring-button"
                                                aria-label={`Edit connection ${label}`}
                                                aria-expanded={open}
                                                aria-controls={`conn-${id}-form`}
                                                onClick={() => openEditor(id)}
                                            >
                                                Edit
                                            </button>
                                        ) : null}
                                        {can("remove_connection") ? (
                                            <button
                                                type="button"
                                                className="authoring-button"
                                                aria-label={`Remove connection ${label}`}
                                                onClick={() => setRemoving(connection)}
                                            >
                                                Remove
                                            </button>
                                        ) : null}
                                    </span>
                                </div>
                                {open ? (
                                    <div id={`conn-${id}-form`}>
                                        <ConnectionEditor
                                            connection={connection}
                                            label={label}
                                            options={options}
                                            version={view.row_version}
                                            command={commandFor("edit")}
                                            onClose={() => closeEditor(id)}
                                            onUnsaved={report}
                                        />
                                    </div>
                                ) : null}
                            </li>
                        )
                    })}
                </ul>
            )}
            {view.connections.length > 0 && !can("remove_connection") && blocked("remove_connection") === "dungeon_not_draft" ? (
                <p className="authoring-note">Connections can be removed only while the dungeon is a draft.</p>
            ) : null}

            <ConfirmDialog
                open={removing !== null}
                title="Remove this connection?"
                description={
                    removing === null
                        ? ""
                        : `The connection between ${connectionName(removing)} will be removed from the dungeon. This cannot be undone.`
                }
                confirmLabel="Remove connection"
                pending={base.busy}
                error={removing === null ? null : commandFor("remove").notice}
                onConfirm={() => {
                    if (removing === null) return
                    const target = removing
                    commandFor("remove").send(
                        {
                            op: "remove_connection",
                            connectionId: target.area_connection_id,
                            expected_row_version: view.row_version,
                        },
                        `Connection between ${connectionName(target)} removed`,
                        () => {
                            setRemoving(null)
                            if (editing === target.area_connection_id) setEditing(null)
                            focusSoon(view.areas.length >= 2 && can("add_connection") ? ADD_TOGGLE_ID : "world-section-connections-heading")
                        },
                    )
                }}
                onCancel={() => setRemoving(null)}
            />
        </div>
    )
}

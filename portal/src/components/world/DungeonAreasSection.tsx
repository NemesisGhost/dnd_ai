import type { RefreshOutcome } from "../../hooks/useAuthoringMutation"
import { useRef, useState } from "react"
import { Link } from "react-router"
import type { DungeonAuthoringView } from "../../types/dungeonAuthoring"
import { describeBlockedReason } from "../../utils/blockedReason"
import { focusSoon } from "../authoring/focusSoon"
import { useRetainedInput } from "../authoring/permissionLoss"
import { useDungeonCommand } from "../authoring/useDungeonCommand"
import { contentsText, plural } from "./areaText"
import { TextAreaField, TextField } from "../authoring/fields"
import { LifecycleBadge } from "../authoring/feedback"
import { useUnsavedReport } from "../quests/useUnsavedReport"
import type { ReportUnsaved } from "../quests/useUnsavedReport"
import type { DungeonRead } from "./useDungeonRead"
import { worldRecordPath } from "./worldPaths"

interface Props {
    campaignId: string
    dungeonId: string
    read: DungeonRead
    // Reads the dungeon, its lifecycle and its revisions again after a change.
    refresh: () => Promise<RefreshOutcome>
    // Opening an area from here keeps where the person came from.
    linkState?: object
    // The state for an area's edit page, which names this section as the place to return to.
    editState?: object
    onUnsaved: ReportUnsaved
}

const connectionCount = (view: DungeonAuthoringView, areaId: string): number =>
    view.connections.filter((c) => c.from_area.entity_id === areaId || c.to_area.entity_id === areaId).length

const ADD_AREA_NAME_ID = "area-add-name"

type AreaField = "name" | "summary" | "kind" | "dimensions" | "environment"
const AREA_FIELDS: readonly AreaField[] = ["name", "summary", "kind", "dimensions", "environment"]
const AREA_FIELD_ID: Readonly<Record<AreaField, string>> = {
    name: ADD_AREA_NAME_ID,
    summary: "area-add-summary",
    kind: "area-add-kind",
    dimensions: "area-add-dimensions",
    environment: "area-add-environment",
}

// The areas of a dungeon as a compact list in the server's order (by name; areas do not nest and
// have no stored order). Each area is its own record with its own status, so nothing here implies
// the dungeon's publication reaches them. Adding an area reveals one small form above the list and
// stays on the list; opening or editing an area is a link to it.
export function DungeonAreasSection({ campaignId, dungeonId, read, refresh, linkState, editState, onUnsaved }: Props) {
    const [open, setOpen] = useState(false)
    const [name, setName] = useState("")
    const [summary, setSummary] = useState("")
    const [kind, setKind] = useState("")
    const [dimensions, setDimensions] = useState("")
    const [environment, setEnvironment] = useState("")
    const [problem, setProblem] = useState<string | null>(null)
    // How many times each field has been edited. A successful create clears only the fields whose count
    // is what it was at the submission: the fields stay editable while the request is pending, and what
    // was typed after it is not part of it. Counting edits (not comparing values) keeps a field changed
    // and changed back, or by whitespace only, as newer input.
    const edits = useRef<Record<AreaField, number>>({ name: 0, summary: 0, kind: 0, dimensions: 0, environment: 0 })
    const command = useDungeonCommand({ campaignId, dungeonId, areaId: null, scope: "areas", refetch: refresh, pageStale: read.stale })
    const typed = [name, summary, kind, dimensions, environment].some((value) => value.trim() !== "")
    useUnsavedReport(onUnsaved, "new-area", typed ? ["a new area"] : [])
    useRetainedInput(
        "new-area",
        "New area",
        [
            { label: "Name", value: name.trim() },
            { label: "Summary", value: summary.trim() },
            { label: "Kind", value: kind.trim() },
            { label: "Size", value: dimensions.trim() },
            { label: "Environment", value: environment.trim() },
        ].filter((c) => c.value !== ""),
    )

    const { view, options } = read
    if (read.status === "loading") return <p role="status">Loading the dungeon&apos;s areas…</p>
    if (read.status !== "ready" || view === null || options === null) {
        return (
            <div role="alert">
                <p>The dungeon&apos;s areas could not be loaded.</p>
                {read.status === "failed" ? (
                    <button type="button" className="authoring-button" onClick={() => void read.reload()}>
                        Try again
                    </button>
                ) : null}
            </div>
        )
    }

    const canAdd = view.available_actions.includes("add_area")
    const blocked = view.blocked_actions.find((b) => b.action === "update")?.reason
    const root = `/app/${encodeURIComponent(campaignId)}/world/dungeon/${encodeURIComponent(dungeonId)}`

    // Every change a person makes counts as an edit, whatever the new value is.
    function edit(field: AreaField, set: (value: string) => void, value: string) {
        edits.current[field] += 1
        set(value)
    }

    function submit() {
        const clean = name.trim()
        if (clean === "") {
            setProblem("Enter a name.")
            focusSoon(ADD_AREA_NAME_ID)
            return
        }
        setProblem(null)
        const submitted = { ...edits.current }
        const optional = (value: string) => (value.trim() === "" ? null : value.trim())
        command.send(
            {
                op: "add_area",
                body: {
                    name: clean,
                    summary: optional(summary),
                    area_type: optional(kind),
                    dimensions: optional(dimensions),
                    environmental_properties: optional(environment),
                },
            },
            `Area ${clean} added as a draft`,
            () => {
                const unchanged = (field: AreaField) => edits.current[field] === submitted[field]
                if (unchanged("name")) setName("")
                if (unchanged("summary")) setSummary("")
                if (unchanged("kind")) setKind("")
                if (unchanged("dimensions")) setDimensions("")
                if (unchanged("environment")) setEnvironment("")
                // Focus goes back to Area name, except from a field that holds newer input.
                const focused = document.activeElement?.id
                const typingNewer = AREA_FIELDS.some((f) => !unchanged(f) && AREA_FIELD_ID[f] === focused)
                if (!typingNewer) focusSoon(ADD_AREA_NAME_ID)
            },
        )
    }

    return (
        <div className="area-section">
            {read.stale ? (
                <p className="authoring-note" role="status">
                    The latest areas could not be loaded, so this list may be out of date.{" "}
                    <button type="button" className="authoring-button" onClick={() => void read.reload()}>
                        Try again
                    </button>
                </p>
            ) : null}
            <div className="area-bar">
                <p className="area-bar__count">
                    <strong>{plural(view.areas.length, "area", "areas")}</strong>, listed by name.
                </p>
                {canAdd ? (
                    <button
                        type="button"
                        id="area-add-toggle"
                        className="authoring-button"
                        aria-expanded={open}
                        aria-controls="area-add-form"
                        onClick={() => {
                            setOpen(!open)
                            if (!open) focusSoon(ADD_AREA_NAME_ID)
                        }}
                    >
                        {open ? "Close the add area form" : "Add area"}
                    </button>
                ) : null}
            </div>
            {!canAdd ? (
                <p className="authoring-note">
                    {blocked !== undefined
                        ? `Adding an area is unavailable: ${describeBlockedReason(blocked)}`
                        : "Adding an area is unavailable right now."}
                </p>
            ) : null}
            {command.savedNotice}
            {command.notice}

            {canAdd && open ? (
                <form
                    id="area-add-form"
                    noValidate
                    aria-label="Add an area"
                    className="inset-group dungeon-editor"
                    onSubmit={(event) => {
                        event.preventDefault()
                        submit()
                    }}
                >
                    <div className="dungeon-editor__fields">
                        <TextField
                            id={ADD_AREA_NAME_ID}
                            label="Area name"
                            required
                            value={name}
                            onChange={(value) => edit("name", setName, value)}
                            maxLength={options.limits.name_max_length}
                            error={problem}
                        />
                        <TextAreaField
                            id="area-add-summary"
                            label="Summary"
                            value={summary}
                            onChange={(value) => edit("summary", setSummary, value)}
                            maxLength={options.limits.summary_max_length}
                        />
                        <TextField
                            id="area-add-kind"
                            label="Kind of area"
                            hint="A room, corridor, cavern…"
                            value={kind}
                            onChange={(value) => edit("kind", setKind, value)}
                            maxLength={options.limits.short_text_max_length}
                        />
                        <TextField
                            id="area-add-dimensions"
                            label="Size"
                            hint="For example 30 ft by 40 ft."
                            value={dimensions}
                            onChange={(value) => edit("dimensions", setDimensions, value)}
                            maxLength={options.limits.short_text_max_length}
                        />
                        <TextAreaField
                            id="area-add-environment"
                            label="Environment"
                            value={environment}
                            onChange={(value) => edit("environment", setEnvironment, value)}
                            maxLength={options.limits.notes_max_length}
                        />
                    </div>
                    <div className="row-actions">
                        <button
                            type="submit"
                            className="authoring-button authoring-button--primary"
                            disabled={command.busy}
                        >
                            Add area
                        </button>
                        <button
                            type="button"
                            className="authoring-button"
                            onClick={() => {
                                setOpen(false)
                                focusSoon("area-add-toggle")
                            }}
                        >
                            Done
                        </button>
                    </div>
                </form>
            ) : null}

            {view.areas.length === 0 ? (
                <p className="member-roster__empty">No areas yet.</p>
            ) : (
                <>
                    <div className="area-list__head" aria-hidden="true">
                        <span>Name</span>
                        <span>Kind</span>
                        <span>Status</span>
                        <span>Contents</span>
                        <span>Connections</span>
                        <span />
                    </div>
                    <ul className="op-list area-list" aria-label="Areas">
                        {view.areas.map((area) => {
                            const links = connectionCount(view, area.dungeon_area_id)
                            return (
                                <li key={area.dungeon_area_id}>
                                    <span className="area-list__name">
                                        <Link
                                            to={worldRecordPath(campaignId, "location", area.dungeon_area_id)}
                                            state={linkState}
                                        >
                                            {area.name}
                                        </Link>
                                        {area.summary !== null ? (
                                            <span className="area-list__summary">{area.summary}</span>
                                        ) : null}
                                    </span>
                                    <span className="area-list__meta">
                                        <span className="area-list__kind">
                                            <span className="visually-hidden">Kind: </span>
                                            {area.area_type !== null ? (
                                                area.area_type
                                            ) : (
                                                <>
                                                    <span aria-hidden="true">—</span>
                                                    <span className="visually-hidden">not set</span>
                                                </>
                                            )}
                                        </span>
                                        <span className="area-list__status">
                                            <span className="visually-hidden">Status: </span>
                                            <LifecycleBadge
                                                status={
                                                    area.lifecycle_status === "archived" ? "archived" : area.canon_status
                                                }
                                            />
                                        </span>
                                        <span className="area-list__contents">
                                            <span className="visually-hidden">Contents: </span>
                                            {contentsText(area)}
                                        </span>
                                        <span className="area-list__links">
                                            <span className="visually-hidden">Connections: </span>
                                            {plural(links, "connection", "connections")}
                                        </span>
                                    </span>
                                    <span className="area-list__actions">
                                        {area.available_actions.includes("update") ? (
                                            <Link
                                                className="authoring-button"
                                                to={`${root}/areas/${encodeURIComponent(area.dungeon_area_id)}/edit`}
                                                state={editState}
                                                aria-label={`Edit ${area.name}`}
                                            >
                                                Edit
                                            </Link>
                                        ) : null}
                                    </span>
                                </li>
                            )
                        })}
                    </ul>
                </>
            )}
        </div>
    )
}

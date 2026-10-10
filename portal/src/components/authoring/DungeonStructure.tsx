import { useState } from "react"
import { Link, useNavigate } from "react-router"
import { runDungeonCommand } from "../../api/dungeonAuthoring"
import { useSession } from "../../context/SessionContext"
import { useAuthoringMutation } from "../../hooks/useAuthoringMutation"
import type {
    ConnectionFields,
    ConnectionView,
    DungeonAuthoringView,
    DungeonCommand,
    DungeonOptions,
} from "../../types/dungeonAuthoring"
import { DUNGEON_CODE_MESSAGE as CODE_MESSAGE, YES_NO } from "../../utils/dungeonForm"
import { statusDetail } from "../../utils/locationForm"
import { useAnnounce } from "./announcer"
import { SelectField, TextAreaField, TextField } from "./fields"
import { MutationStatusMessage, StaleWriteNotice } from "./feedback"
import "./authoring.css"

interface Props {
    campaignId: string
    view: DungeonAuthoringView
    options: DungeonOptions
    refetch: () => Promise<void>
}

const base = (campaignId: string): string => `/app/${encodeURIComponent(campaignId)}`

// The structure of a dungeon: its areas and the connections between them. Every change is one
// idempotent command that names the dungeon version the editor saw (decision D-31).
export function DungeonStructure({ campaignId, view, options, refetch }: Props) {
    const { reload } = useSession()
    const announce = useAnnounce()
    const navigate = useNavigate()
    const [done, setDone] = useState<string | null>(null)
    const mutation = useAuthoringMutation<DungeonCommand, unknown>({
        scopeKey: `dungeon-structure:${view.dungeon_id}`,
        request: (command, ctx) => runDungeonCommand(campaignId, view.dungeon_id, null, command, ctx),
        onSuccess: async (result) => {
            const message = done
            setDone(null)
            const created = (result as { dungeon_area_id?: string } | null)?.dungeon_area_id
            if (message === "Area added" && created !== undefined) {
                void navigate(
                    `${base(campaignId)}/world/dungeon/${encodeURIComponent(view.dungeon_id)}/areas/${encodeURIComponent(created)}/edit`,
                )
                return
            }
            await refetch()
            if (message !== null) announce(message)
        },
    })
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const busy = mutation.status.kind === "pending"
    const can = (action: string) => view.available_actions.includes(action)
    const run = (command: DungeonCommand, message: string) => {
        setDone(message)
        mutation.submit(command)
    }
    const explained = error?.code ? (CODE_MESSAGE[error.code] ?? null) : null

    if (!can("update")) return null
    return (
        <section aria-labelledby="dungeon-structure-heading">
            <h2 id="dungeon-structure-heading">Areas and connections</h2>
            {error?.kind === "stale" ? (
                <StaleWriteNotice
                    onLoadLatest={() => {
                        mutation.reset()
                        void refetch()
                    }}
                />
            ) : explained !== null ? (
                <p role="alert">{explained}</p>
            ) : error !== null ? (
                <MutationStatusMessage error={error} onRetry={mutation.retry} onCheckSession={reload} />
            ) : null}

            <h3>Areas</h3>
            {view.areas.length === 0 ? (
                <p>No areas yet.</p>
            ) : (
                <ul className="authoring-choice-list">
                    {view.areas.map((area) => (
                        <li key={area.dungeon_area_id}>
                            <Link
                                to={`${base(campaignId)}/world/dungeon/${encodeURIComponent(view.dungeon_id)}/areas/${encodeURIComponent(area.dungeon_area_id)}/edit`}
                            >
                                {area.name}
                            </Link>{" "}
                            ({statusDetail(area.canon_status, area.lifecycle_status)}
                            {area.area_type !== null ? `, ${area.area_type}` : ""}; {area.feature_count}{" "}
                            features, {area.hazard_count} hazards, {area.interactable_count} interactables)
                        </li>
                    ))}
                </ul>
            )}
            {can("add_area") ? <AddArea busy={busy} options={options} run={run} /> : null}

            <h3>Connections</h3>
            {view.connections.length === 0 ? (
                <p>No connections yet.</p>
            ) : (
                view.connections.map((connection) => (
                    <ConnectionCard
                        key={connection.area_connection_id}
                        connection={connection}
                        view={view}
                        options={options}
                        busy={busy}
                        run={run}
                        canEdit={can("update_connection")}
                        canRemove={can("remove_connection")}
                    />
                ))
            )}
            {can("add_connection") && view.areas.length >= 2 ? (
                <AddConnection view={view} options={options} busy={busy} run={run} />
            ) : null}
        </section>
    )
}

type Run = (command: DungeonCommand, message: string) => void

function AddArea({ busy, options, run }: { busy: boolean; options: DungeonOptions; run: Run }) {
    const [name, setName] = useState("")
    const [areaType, setAreaType] = useState("")
    const [problem, setProblem] = useState<string | null>(null)
    return (
        <form
            noValidate
            aria-label="Add an area"
            className="authoring-form"
            onSubmit={(event) => {
                event.preventDefault()
                if (name.trim() === "") {
                    setProblem("Enter a name.")
                    return
                }
                setProblem(null)
                run(
                    {
                        op: "add_area",
                        body: { name: name.trim(), area_type: areaType.trim() === "" ? null : areaType.trim() },
                    },
                    "Area added",
                )
            }}
        >
            <TextField
                id="area-name"
                label="Area name"
                value={name}
                onChange={setName}
                required
                maxLength={options.limits.name_max_length}
                error={problem}
            />
            <TextField
                id="area-kind"
                label="Kind of area"
                hint="A room, corridor, cavern…"
                value={areaType}
                onChange={setAreaType}
                maxLength={options.limits.short_text_max_length}
            />
            <button type="submit" className="authoring-button" disabled={busy}>
                Add area
            </button>
        </form>
    )
}

function fieldsOf(
    kind: string,
    oneWay: string,
    hidden: string,
    description: string,
    conditional: string,
    condition: string,
): ConnectionFields {
    return {
        connection_type: kind,
        is_one_way: oneWay === "yes",
        is_hidden: hidden === "yes",
        description: description.trim() === "" ? null : description.trim(),
        is_conditional: conditional === "yes",
        condition_description: conditional === "yes" && condition.trim() !== "" ? condition.trim() : null,
    }
}

function ConnectionFormFields({
    prefix,
    options,
    state,
}: {
    prefix: string
    options: DungeonOptions
    state: {
        kind: [string, (v: string) => void]
        oneWay: [string, (v: string) => void]
        hidden: [string, (v: string) => void]
        description: [string, (v: string) => void]
        conditional: [string, (v: string) => void]
        condition: [string, (v: string) => void]
        problem: string | null
    }
}) {
    return (
        <>
            <SelectField
                id={`${prefix}-type`}
                label="Kind of connection"
                value={state.kind[0]}
                placeholder="Choose a kind"
                required
                options={options.connection_types}
                error={state.problem}
                onChange={state.kind[1]}
            />
            <SelectField
                id={`${prefix}-oneway`}
                label="One way only"
                value={state.oneWay[0]}
                options={YES_NO}
                onChange={state.oneWay[1]}
            />
            <SelectField
                id={`${prefix}-hidden`}
                label="Built to be concealed"
                value={state.hidden[0]}
                options={YES_NO}
                onChange={state.hidden[1]}
            />
            <TextAreaField
                id={`${prefix}-description`}
                label="Description"
                value={state.description[0]}
                onChange={state.description[1]}
            />
            <SelectField
                id={`${prefix}-conditional`}
                label="Only passable under a condition"
                value={state.conditional[0]}
                options={YES_NO}
                onChange={state.conditional[1]}
            />
            {state.conditional[0] === "yes" ? (
                <TextAreaField
                    id={`${prefix}-condition`}
                    label="The condition"
                    value={state.condition[0]}
                    onChange={state.condition[1]}
                />
            ) : null}
        </>
    )
}

function AddConnection({
    view,
    options,
    busy,
    run,
}: {
    view: DungeonAuthoringView
    options: DungeonOptions
    busy: boolean
    run: Run
}) {
    const [from, setFrom] = useState("")
    const [to, setTo] = useState("")
    const [kind, setKind] = useState("")
    const [oneWay, setOneWay] = useState("no")
    const [hidden, setHidden] = useState("no")
    const [description, setDescription] = useState("")
    const [conditional, setConditional] = useState("no")
    const [condition, setCondition] = useState("")
    const [problem, setProblem] = useState<string | null>(null)
    const areaOptions = view.areas.map((a) => ({ value: a.dungeon_area_id, label: a.name }))
    return (
        <form
            noValidate
            aria-label="Add a connection"
            className="authoring-form"
            onSubmit={(event) => {
                event.preventDefault()
                if (from === "" || to === "" || kind === "") {
                    setProblem("Choose both areas and a kind.")
                    return
                }
                if (from === to) {
                    setProblem("Choose two different areas.")
                    return
                }
                if (conditional === "yes" && condition.trim() === "") {
                    setProblem("Describe the condition.")
                    return
                }
                setProblem(null)
                run(
                    {
                        op: "add_connection",
                        body: {
                            expected_row_version: view.row_version,
                            from_area_id: from,
                            to_area_id: to,
                            ...fieldsOf(kind, oneWay, hidden, description, conditional, condition),
                        },
                    },
                    "Connection added",
                )
            }}
        >
            <SelectField
                id="conn-from"
                label="From area"
                value={from}
                placeholder="Choose an area"
                required
                options={areaOptions}
                onChange={setFrom}
            />
            <SelectField
                id="conn-to"
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
                state={{
                    kind: [kind, setKind],
                    oneWay: [oneWay, setOneWay],
                    hidden: [hidden, setHidden],
                    description: [description, setDescription],
                    conditional: [conditional, setConditional],
                    condition: [condition, setCondition],
                    problem,
                }}
            />
            <button type="submit" className="authoring-button" disabled={busy}>
                Add connection
            </button>
        </form>
    )
}

function ConnectionCard({
    connection,
    view,
    options,
    busy,
    run,
    canEdit,
    canRemove,
}: {
    connection: ConnectionView
    view: DungeonAuthoringView
    options: DungeonOptions
    busy: boolean
    run: Run
    canEdit: boolean
    canRemove: boolean
}) {
    const [editing, setEditing] = useState(false)
    const [kind, setKind] = useState(connection.connection_type)
    const [oneWay, setOneWay] = useState(connection.is_one_way ? "yes" : "no")
    const [hidden, setHidden] = useState(connection.is_hidden ? "yes" : "no")
    const [description, setDescription] = useState(connection.description ?? "")
    const [conditional, setConditional] = useState(connection.is_conditional ? "yes" : "no")
    const [condition, setCondition] = useState(connection.condition_description ?? "")
    const [problem, setProblem] = useState<string | null>(null)
    const label = `${connection.from_area.name} to ${connection.to_area.name}`
    return (
        <article className="authoring-card" aria-label={`Connection ${label}`}>
            <h4>{label}</h4>
            <p>
                {connection.connection_type_label}
                {connection.is_one_way ? ", one way" : ""}
                {connection.is_hidden ? ", concealed" : ""}
                {connection.is_conditional ? `, only if: ${connection.condition_description ?? ""}` : ""}
            </p>
            {connection.description !== null ? <p>{connection.description}</p> : null}
            <div className="authoring-actions">
                {canEdit ? (
                    <button type="button" className="authoring-button" onClick={() => setEditing(!editing)}>
                        {editing ? "Cancel" : `Edit connection ${label}`}
                    </button>
                ) : null}
                {canRemove ? (
                    <button
                        type="button"
                        className="authoring-button"
                        disabled={busy}
                        onClick={() =>
                            run(
                                {
                                    op: "remove_connection",
                                    connectionId: connection.area_connection_id,
                                    expected_row_version: view.row_version,
                                },
                                "Connection removed",
                            )
                        }
                    >
                        Remove connection {label}
                    </button>
                ) : null}
            </div>
            {editing ? (
                <form
                    noValidate
                    aria-label={`Edit connection ${label}`}
                    className="authoring-form"
                    onSubmit={(event) => {
                        event.preventDefault()
                        if (kind === "") {
                            setProblem("Choose a kind.")
                            return
                        }
                        if (conditional === "yes" && condition.trim() === "") {
                            setProblem("Describe the condition.")
                            return
                        }
                        setProblem(null)
                        run(
                            {
                                op: "update_connection",
                                connectionId: connection.area_connection_id,
                                body: {
                                    expected_row_version: view.row_version,
                                    ...fieldsOf(kind, oneWay, hidden, description, conditional, condition),
                                },
                            },
                            "Connection saved",
                        )
                        setEditing(false)
                    }}
                >
                    <ConnectionFormFields
                        prefix={`conn-${connection.area_connection_id}`}
                        options={options}
                        state={{
                            kind: [kind, setKind],
                            oneWay: [oneWay, setOneWay],
                            hidden: [hidden, setHidden],
                            description: [description, setDescription],
                            conditional: [conditional, setConditional],
                            condition: [condition, setCondition],
                            problem,
                        }}
                    />
                    <button type="submit" className="authoring-button" disabled={busy}>
                        Save connection
                    </button>
                </form>
            ) : null}
        </article>
    )
}

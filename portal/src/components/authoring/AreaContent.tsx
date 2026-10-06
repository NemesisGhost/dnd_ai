import { useState } from "react"
import { runDungeonCommand } from "../../api/dungeonAuthoring"
import { useSession } from "../../context/SessionContext"
import { useAuthoringMutation } from "../../hooks/useAuthoringMutation"
import type {
    AreaAuthoringView,
    ChildKind,
    ChildView,
    ConnectionView,
    DungeonChoice,
    DungeonCommand,
    DungeonOptions,
    SetStateBody,
} from "../../types/dungeonAuthoring"
import { DUNGEON_CODE_MESSAGE as CODE_MESSAGE, YES_NO } from "../../utils/dungeonForm"
import { useAnnounce } from "./announcer"
import { SelectField, TextAreaField, TextField } from "./fields"
import { MutationStatusMessage, StaleWriteNotice } from "./feedback"
import "./authoring.css"

interface Props {
    campaignId: string
    view: AreaAuthoringView
    options: DungeonOptions
    refetch: () => Promise<void>
}

const KINDS: { kind: ChildKind; plural: string; singular: string; typeLabel: string }[] = [
    { kind: "feature", plural: "Features", singular: "feature", typeLabel: "Kind of feature" },
    { kind: "hazard", plural: "Hazards", singular: "hazard", typeLabel: "Kind of hazard" },
    {
        kind: "interactable",
        plural: "Interactables",
        singular: "interactable",
        typeLabel: "Kind of interactable",
    },
]

type Run = (command: DungeonCommand, message: string) => void

// The contents of one area: its features, hazards and interactables (structural children of the
// dungeon, edited against the dungeon version), and what is currently true in this timeline.
export function AreaContent({ campaignId, view, options, refetch }: Props) {
    const { reload } = useSession()
    const announce = useAnnounce()
    const [done, setDone] = useState<string | null>(null)
    const mutation = useAuthoringMutation<DungeonCommand, unknown>({
        scopeKey: `dungeon-area:${view.dungeon_area_id}`,
        request: (command, ctx) =>
            runDungeonCommand(campaignId, view.dungeon.entity_id, view.dungeon_area_id, command, ctx),
        onSuccess: async () => {
            const message = done
            setDone(null)
            await refetch()
            if (message !== null) announce(message)
        },
    })
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const busy = mutation.status.kind === "pending"
    const explained = error?.code ? (CODE_MESSAGE[error.code] ?? null) : null
    const run: Run = (command, message) => {
        setDone(message)
        mutation.submit(command)
    }
    const can = (action: string) => view.structure_actions.includes(action)
    const lists: Record<ChildKind, ChildView[]> = {
        feature: view.features,
        hazard: view.hazards,
        interactable: view.interactables,
    }

    return (
        <section aria-labelledby="area-content-heading">
            <h2 id="area-content-heading">Features, hazards and interactables</h2>
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
            {KINDS.map(({ kind, plural, singular, typeLabel }) => (
                <section key={kind} aria-label={plural}>
                    <h3>{plural}</h3>
                    {lists[kind].length === 0 ? <p>No {plural.toLowerCase()} yet.</p> : null}
                    {lists[kind].map((child) => (
                        <ChildCard
                            key={child.child_id}
                            child={child}
                            singular={singular}
                            typeLabel={typeLabel}
                            options={options}
                            view={view}
                            busy={busy}
                            run={run}
                            canEdit={can(`update_${kind}`)}
                            canRemove={can(`remove_${kind}`)}
                        />
                    ))}
                    {can(`add_${kind}`) ? (
                        <ChildForm
                            label={`Add a ${singular}`}
                            typeLabel={typeLabel}
                            kind={kind}
                            options={options}
                            busy={busy}
                            submitLabel={`Add ${singular}`}
                            onSubmit={(fields) =>
                                run(
                                    {
                                        op: "add_child",
                                        kind,
                                        body: {
                                            ...fields,
                                            expected_row_version: view.dungeon_row_version,
                                            dungeon_area_id: view.dungeon_area_id,
                                        },
                                    },
                                    `${plural.slice(0, -1)} added`,
                                )
                            }
                        />
                    ) : null}
                </section>
            ))}
            <h3>Connections of this area</h3>
            {view.connections.length === 0 ? (
                <p>No connections. Add them on the dungeon page.</p>
            ) : (
                <ul className="authoring-choice-list">
                    {view.connections.map((c) => (
                        <li key={c.area_connection_id}>
                            {c.from_area.name} to {c.to_area.name} ({c.connection_type_label}
                            {c.is_hidden ? ", concealed" : ""})
                        </li>
                    ))}
                </ul>
            )}
            {view.can_set_state ? (
                <StatePanel view={view} options={options} busy={busy} run={run} />
            ) : (
                <p className="authoring-note">
                    Publish the dungeon and this area to record what is happening in them.
                </p>
            )}
        </section>
    )
}

function ChildForm({
    label,
    typeLabel,
    kind,
    options,
    busy,
    submitLabel,
    initial,
    onSubmit,
}: {
    label: string
    typeLabel: string
    kind: ChildKind
    options: DungeonOptions
    busy: boolean
    submitLabel: string
    initial?: ChildView
    onSubmit: (fields: {
        child_type: string | null
        description: string | null
        is_hidden: boolean
        severity: number | null
    }) => void
}) {
    const prefix = initial === undefined ? `new-${kind}` : `edit-${initial.child_id}`
    const [childType, setChildType] = useState(initial?.child_type ?? "")
    const [description, setDescription] = useState(initial?.description ?? "")
    const [hidden, setHidden] = useState(initial?.is_hidden ? "yes" : "no")
    const [severity, setSeverity] = useState(initial?.severity == null ? "" : String(initial.severity))
    const [problem, setProblem] = useState<string | null>(null)
    return (
        <form
            noValidate
            aria-label={label}
            className="authoring-form"
            onSubmit={(event) => {
                event.preventDefault()
                const rating = severity.trim() === "" ? null : Number(severity)
                const { rating_min: min, rating_max: max } = options.limits
                if (rating !== null && (!Number.isInteger(rating) || rating < min || rating > max)) {
                    setProblem(`Severity is a whole number from ${min} to ${max}.`)
                    return
                }
                setProblem(null)
                onSubmit({
                    child_type: childType.trim() === "" ? null : childType.trim(),
                    description: description.trim() === "" ? null : description.trim(),
                    is_hidden: hidden === "yes",
                    severity: kind === "hazard" ? rating : null,
                })
            }}
        >
            <TextField
                id={`${prefix}-type`}
                label={typeLabel}
                value={childType}
                onChange={setChildType}
                maxLength={options.limits.short_text_max_length}
            />
            <TextAreaField
                id={`${prefix}-description`}
                label="Description"
                value={description}
                onChange={setDescription}
                maxLength={options.limits.notes_max_length}
            />
            <SelectField
                id={`${prefix}-hidden`}
                label="Built to be concealed"
                hint="A fact about the object itself, not about whether anyone has found it."
                value={hidden}
                options={YES_NO}
                onChange={setHidden}
            />
            {kind === "hazard" ? (
                <TextField
                    id={`${prefix}-severity`}
                    label="Severity (1 to 10)"
                    value={severity}
                    onChange={setSeverity}
                    error={problem}
                />
            ) : null}
            <button type="submit" className="authoring-button" disabled={busy}>
                {submitLabel}
            </button>
        </form>
    )
}

function ChildCard({
    child,
    singular,
    typeLabel,
    options,
    view,
    busy,
    run,
    canEdit,
    canRemove,
}: {
    child: ChildView
    singular: string
    typeLabel: string
    options: DungeonOptions
    view: AreaAuthoringView
    busy: boolean
    run: Run
    canEdit: boolean
    canRemove: boolean
}) {
    const [editing, setEditing] = useState(false)
    const name = child.child_type ?? singular
    return (
        <article className="authoring-card" aria-label={`${singular} ${name}`}>
            <h4>{name}</h4>
            {child.description !== null ? <p>{child.description}</p> : null}
            <p>
                {child.is_hidden ? "Concealed. " : ""}
                {child.severity !== null ? `Severity ${child.severity}. ` : ""}
                {child.status !== null ? `Now: ${child.status.replace(/_/g, " ")}. ` : ""}
                {child.is_destroyed === true ? "Destroyed. " : ""}
            </p>
            <div className="authoring-actions">
                {canEdit ? (
                    <button type="button" className="authoring-button" onClick={() => setEditing(!editing)}>
                        {editing ? "Cancel" : `Edit ${singular} ${name}`}
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
                                    op: "remove_child",
                                    kind: child.kind,
                                    childId: child.child_id,
                                    expected_row_version: view.dungeon_row_version,
                                },
                                `${singular} removed`,
                            )
                        }
                    >
                        Remove {singular} {name}
                    </button>
                ) : null}
            </div>
            {editing ? (
                <ChildForm
                    label={`Edit ${singular} ${name}`}
                    typeLabel={typeLabel}
                    kind={child.kind}
                    options={options}
                    busy={busy}
                    submitLabel={`Save ${singular}`}
                    initial={child}
                    onSubmit={(fields) => {
                        run(
                            {
                                op: "update_child",
                                kind: child.kind,
                                childId: child.child_id,
                                body: { ...fields, expected_row_version: view.dungeon_row_version },
                            },
                            `${singular} saved`,
                        )
                        setEditing(false)
                    }}
                />
            ) : null}
        </article>
    )
}

function StatusRow({
    label,
    current,
    choices,
    busy,
    onSet,
}: {
    label: string
    current: string | null
    choices: DungeonChoice[]
    busy: boolean
    onSet: (value: string) => void
}) {
    const [value, setValue] = useState(current ?? "")
    return (
        <li>
            {label}: {current === null ? "not recorded" : (choices.find((c) => c.value === current)?.label ?? current)}
            <SelectField
                id={`state-${label.replace(/\s+/g, "-")}`}
                label={`New status for ${label}`}
                value={value}
                placeholder="Choose a status"
                options={choices}
                onChange={setValue}
            />
            <button
                type="button"
                className="authoring-button"
                disabled={busy || value === ""}
                onClick={() => onSet(value)}
            >
                Set status of {label}
            </button>
        </li>
    )
}

function StatePanel({
    view,
    options,
    busy,
    run,
}: {
    view: AreaAuthoringView
    options: DungeonOptions
    busy: boolean
    run: Run
}) {
    const [searched, setSearched] = useState(view.state.is_searched ? "yes" : "no")
    const [destroyed, setDestroyed] = useState(view.state.is_destroyed ? "yes" : "no")
    const [alarm, setAlarm] = useState(String(view.state.alarm_level))
    const [notes, setNotes] = useState(view.state.condition_notes ?? "")
    const [problem, setProblem] = useState<string | null>(null)
    const set = (body: SetStateBody, message: string) => run({ op: "set_state", body }, message)
    const choices = view.state_choices
    return (
        <section aria-labelledby="area-state-heading">
            <h3 id="area-state-heading">What is happening here now</h3>
            <p className="authoring-note">
                These record the current campaign only. The dungeon itself is not changed.
            </p>
            <form
                noValidate
                aria-label="The area now"
                className="authoring-form"
                onSubmit={(event) => {
                    event.preventDefault()
                    const level = Number(alarm)
                    if (!Number.isInteger(level) || level < 0 || level > options.limits.alarm_level_max) {
                        setProblem(`Alarm level is a whole number from 0 to ${options.limits.alarm_level_max}.`)
                        return
                    }
                    setProblem(null)
                    set(
                        {
                            kind: "area",
                            target_id: view.dungeon_area_id,
                            expected_last_event_id: view.state.state_event_id,
                            is_searched: searched === "yes",
                            is_destroyed: destroyed === "yes",
                            alarm_level: level,
                            condition_notes: notes.trim() === "" ? null : notes.trim(),
                        },
                        "Area state saved",
                    )
                }}
            >
                <SelectField id="state-searched" label="Searched" value={searched} options={YES_NO} onChange={setSearched} />
                <SelectField id="state-destroyed" label="Destroyed" value={destroyed} options={YES_NO} onChange={setDestroyed} />
                <TextField id="state-alarm" label="Alarm level" value={alarm} onChange={setAlarm} error={problem} />
                <TextAreaField id="state-notes" label="Condition notes" value={notes} onChange={setNotes} />
                <button type="submit" className="authoring-button" disabled={busy}>
                    Save area state
                </button>
            </form>
            <ul className="authoring-choice-list">
                {view.connections.map((c: ConnectionView) => (
                    <StatusRow
                        key={c.area_connection_id}
                        label={`${c.from_area.name} to ${c.to_area.name}`}
                        current={c.status}
                        choices={choices.connection_status ?? []}
                        busy={busy}
                        onSet={(value) =>
                            set(
                                {
                                    kind: "connection",
                                    target_id: c.area_connection_id,
                                    expected_last_event_id: c.state_event_id,
                                    connection_status: value,
                                },
                                "Connection status saved",
                            )
                        }
                    />
                ))}
                {view.features.map((f) => (
                    <StatusRow
                        key={f.child_id}
                        label={f.child_type ?? "feature"}
                        current={f.is_destroyed === true ? "destroyed" : f.is_destroyed === false ? "intact" : null}
                        choices={[
                            { value: "intact", label: "Intact" },
                            { value: "destroyed", label: "Destroyed" },
                        ]}
                        busy={busy}
                        onSet={(value) =>
                            set(
                                {
                                    kind: "feature",
                                    target_id: f.child_id,
                                    expected_last_event_id: f.state_event_id,
                                    is_destroyed: value === "destroyed",
                                },
                                "Feature state saved",
                            )
                        }
                    />
                ))}
                {view.hazards.map((h) => (
                    <StatusRow
                        key={h.child_id}
                        label={h.child_type ?? "hazard"}
                        current={h.status}
                        choices={choices.hazard_status ?? []}
                        busy={busy}
                        onSet={(value) =>
                            set(
                                {
                                    kind: "hazard",
                                    target_id: h.child_id,
                                    expected_last_event_id: h.state_event_id,
                                    hazard_status: value,
                                },
                                "Hazard status saved",
                            )
                        }
                    />
                ))}
                {view.interactables.map((i) => (
                    <StatusRow
                        key={i.child_id}
                        label={i.child_type ?? "interactable"}
                        current={i.status}
                        choices={choices.interactable_status ?? []}
                        busy={busy}
                        onSet={(value) =>
                            set(
                                {
                                    kind: "interactable",
                                    target_id: i.child_id,
                                    expected_last_event_id: i.state_event_id,
                                    interactable_status: value,
                                },
                                "Interactable status saved",
                            )
                        }
                    />
                ))}
            </ul>
        </section>
    )
}

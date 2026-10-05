import { useState } from "react"
import { fetchQuestTargetOptions, runQuestCommand } from "../../api/questAuthoring"
import { fetchWorldEntities } from "../../api/world"
import { useSession } from "../../context/SessionContext"
import { useAuthoringMutation } from "../../hooks/useAuthoringMutation"
import type { QuestReceipt } from "../../types/contentAuthoring"
import type {
    QuestAuthoringView,
    QuestCommand,
    QuestOptions,
    QuestOutcomeView,
} from "../../types/questAuthoring"
import { useAnnounce } from "./announcer"
import { SelectField, TextAreaField, TextField } from "./fields"
import { MutationStatusMessage, StaleWriteNotice } from "./feedback"
import { ReferenceCombobox } from "./ReferenceCombobox"
import type { ReferenceOption } from "./ReferenceCombobox"
import "./authoring.css"

const CODE_MESSAGE: Readonly<Record<string, string>> = {
    quest_has_progress:
        "This quest already has recorded progress, so its structure can no longer change.",
    objective_dependency_cycle: "That prerequisite would create a loop of objectives that wait on each other.",
    objective_dependency_invalid: "Choose two different objectives of this quest.",
    objective_dependency_exists: "That dependency already exists.",
    quest_participant_invalid: "That participant is not valid: choose a published character or an organization.",
    quest_participant_exists: "That participant already has that role in this quest.",
    quest_outcome_code_exists: "Another outcome of this quest already uses that code.",
    reward_knowledge_invalid: "A knowledge reward needs a valid knowledge item, and other rewards must not name one.",
}

const CODE_PATTERN = /^[a-z][a-z0-9_]{0,63}$/

interface Props {
    campaignId: string
    view: QuestAuthoringView
    options: QuestOptions
    refetch: () => Promise<void>
}

// The completion sections of the quest editor: GM planning notes, dependencies between
// objectives, participants, and outcomes with their rewards. Every change is one
// idempotent command (the server returns the whole aggregate, which the page refetches).
// Dependencies are structural and lock once the quest has progress; the rest stay editable.
export function QuestCompletionEditor({ campaignId, view, options, refetch }: Props) {
    const { reload } = useSession()
    const announce = useAnnounce()
    const [message, setMessage] = useState<string | null>(null)
    const mutation = useAuthoringMutation<QuestCommand, QuestReceipt>({
        scopeKey: `quest-completion:${view.quest_id}`,
        request: (command, ctx) => runQuestCommand(campaignId, view.quest_id, command, ctx),
        onSuccess: async () => {
            const done = message
            setMessage(null)
            await refetch()
            if (done !== null) announce(done)
        },
    })
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const text = error?.code ? (CODE_MESSAGE[error.code] ?? null) : null
    const busy = mutation.status.kind === "pending"
    const version = view.row_version
    const can = (action: string) => view.available_actions.includes(action)
    const send = (command: QuestCommand, done: string) => {
        setMessage(done)
        mutation.submit(command)
    }

    if (!view.available_actions.includes("update")) return null
    const objectives = view.stages.flatMap((s) =>
        s.objectives.map((o) => ({ id: o.quest_objective_id, label: `${s.name}: ${o.name}` })),
    )
    const objectiveLabel = (id: string) => objectives.find((o) => o.id === id)?.label ?? "an objective"

    return (
        <section aria-labelledby="quest-completion-heading">
            <h2 id="quest-completion-heading">Dependencies, participants, outcomes and notes</h2>
            {error?.kind === "stale" ? (
                <StaleWriteNotice
                    onLoadLatest={() => {
                        mutation.reset()
                        void refetch()
                    }}
                />
            ) : text !== null ? (
                <p role="alert">{text}</p>
            ) : error !== null ? (
                <MutationStatusMessage error={error} onRetry={mutation.retry} onCheckSession={reload} />
            ) : null}

            <Notes view={view} options={options} busy={busy} send={send} />

            <Dependencies
                view={view}
                options={options}
                objectives={objectives}
                objectiveLabel={objectiveLabel}
                version={version}
                busy={busy}
                allowed={can("add_dependency")}
                send={send}
            />

            <Participants
                campaignId={campaignId}
                view={view}
                options={options}
                version={version}
                busy={busy}
                send={send}
            />

            <Outcomes
                campaignId={campaignId}
                view={view}
                options={options}
                version={version}
                busy={busy}
                send={send}
            />
        </section>
    )
}

type Send = (command: QuestCommand, done: string) => void

function Notes({
    view,
    options,
    busy,
    send,
}: {
    view: QuestAuthoringView
    options: QuestOptions
    busy: boolean
    send: Send
}) {
    const [notes, setNotes] = useState(view.gm_notes ?? "")
    const max = options.limits.gm_notes_max_length
    const tooLong = notes.trim().length > max
    return (
        <form
            noValidate
            aria-label="GM notes"
            className="authoring-form"
            onSubmit={(event) => {
                event.preventDefault()
                if (tooLong) return
                send(
                    {
                        op: "update_quest",
                        body: {
                            expected_row_version: view.row_version,
                            name: view.name,
                            summary: view.summary,
                            gm_notes: notes.trim() === "" ? null : notes.trim(),
                        },
                    },
                    "GM notes saved",
                )
            }}
        >
            <h3>GM notes</h3>
            <TextAreaField
                id="quest-gm-notes"
                label="Planning notes"
                hint="Visible only to people who can edit canon. Never shown to players."
                value={notes}
                onChange={setNotes}
                maxLength={max}
                error={tooLong ? `Notes must be ${max} characters or fewer.` : null}
            />
            <button type="submit" className="authoring-button" disabled={busy || tooLong}>
                Save notes
            </button>
        </form>
    )
}

function Dependencies({
    view,
    options,
    objectives,
    objectiveLabel,
    version,
    busy,
    allowed,
    send,
}: {
    view: QuestAuthoringView
    options: QuestOptions
    objectives: { id: string; label: string }[]
    objectiveLabel: (id: string) => string
    version: number
    busy: boolean
    allowed: boolean
    send: Send
}) {
    const [objective, setObjective] = useState("")
    const [dependsOn, setDependsOn] = useState("")
    const [kind, setKind] = useState("prerequisite")
    const [problem, setProblem] = useState<string | null>(null)
    const dependencies = view.dependencies ?? []
    return (
        <section aria-labelledby="deps-heading">
            <h3 id="deps-heading">Dependencies between objectives</h3>
            {!allowed ? (
                <p className="authoring-note">
                    This quest has recorded progress, so dependencies can no longer change.
                </p>
            ) : null}
            {dependencies.length === 0 ? (
                <p>No dependencies.</p>
            ) : (
                <ul className="authoring-choice-list">
                    {dependencies.map((d) => (
                        <li key={d.objective_dependency_id}>
                            {objectiveLabel(d.objective_id)} depends on {objectiveLabel(d.depends_on_objective_id)} (
                            {d.dependency_type})
                            {allowed ? (
                                <>
                                    {" "}
                                    <button
                                        type="button"
                                        className="authoring-button"
                                        disabled={busy}
                                        onClick={() =>
                                            send(
                                                {
                                                    op: "remove_dependency",
                                                    dependencyId: d.objective_dependency_id,
                                                    expected_row_version: version,
                                                },
                                                "Dependency removed",
                                            )
                                        }
                                    >
                                        Remove dependency
                                    </button>
                                </>
                            ) : null}
                        </li>
                    ))}
                </ul>
            )}
            {allowed && objectives.length >= 2 ? (
                <form
                    noValidate
                    aria-label="Add a dependency"
                    className="authoring-form"
                    onSubmit={(event) => {
                        event.preventDefault()
                        if (objective === "" || dependsOn === "") {
                            setProblem("Choose both objectives.")
                            return
                        }
                        if (objective === dependsOn) {
                            setProblem("Choose two different objectives.")
                            return
                        }
                        setProblem(null)
                        send(
                            {
                                op: "add_dependency",
                                body: {
                                    expected_row_version: version,
                                    objective_id: objective,
                                    depends_on_objective_id: dependsOn,
                                    dependency_type: kind,
                                },
                            },
                            "Dependency added",
                        )
                    }}
                >
                    <SelectField
                        id="dep-objective"
                        label="Objective"
                        value={objective}
                        placeholder="Choose an objective"
                        required
                        options={objectives.map((o) => ({ value: o.id, label: o.label }))}
                        onChange={setObjective}
                    />
                    <SelectField
                        id="dep-kind"
                        label="Relation"
                        value={kind}
                        options={options.dependency_types}
                        onChange={setKind}
                    />
                    <SelectField
                        id="dep-on"
                        label="Depends on"
                        value={dependsOn}
                        placeholder="Choose an objective"
                        required
                        options={objectives.map((o) => ({ value: o.id, label: o.label }))}
                        error={problem}
                        onChange={setDependsOn}
                    />
                    <button type="submit" className="authoring-button" disabled={busy}>
                        Add dependency
                    </button>
                </form>
            ) : null}
        </section>
    )
}

function Participants({
    campaignId,
    view,
    options,
    version,
    busy,
    send,
}: {
    campaignId: string
    view: QuestAuthoringView
    options: QuestOptions
    version: number
    busy: boolean
    send: Send
}) {
    const [who, setWho] = useState<ReferenceOption | null>(null)
    const [role, setRole] = useState("involved")
    const [problem, setProblem] = useState<string | null>(null)
    const participants = view.participants ?? []

    async function search(query: string, signal: AbortSignal): Promise<ReferenceOption[]> {
        const [people, groups] = await Promise.all(
            (["character", "organization"] as const).map((category) =>
                fetchWorldEntities(campaignId, { category, query, limit: 10 }, signal),
            ),
        )
        return [...people!.items, ...groups!.items].map((item) => ({
            id: item.entity_id,
            label: item.name,
            detail: item.category === "organization" ? "Organization" : "Character",
        }))
    }

    return (
        <section aria-labelledby="participants-heading-q">
            <h3 id="participants-heading-q">Participants</h3>
            {participants.length === 0 ? (
                <p>No participants.</p>
            ) : (
                <ul className="authoring-choice-list">
                    {participants.map((p) => (
                        <li key={p.quest_participant_id}>
                            {p.participant?.name ?? "Unknown"} ({p.participant_role.replace("_", " ")}){" "}
                            <button
                                type="button"
                                className="authoring-button"
                                disabled={busy}
                                onClick={() =>
                                    send(
                                        {
                                            op: "remove_participant",
                                            participantId: p.quest_participant_id,
                                            expected_row_version: version,
                                        },
                                        "Participant removed",
                                    )
                                }
                            >
                                Remove {p.participant?.name ?? "participant"}
                            </button>
                        </li>
                    ))}
                </ul>
            )}
            <form
                noValidate
                aria-label="Add a participant"
                className="authoring-form"
                onSubmit={(event) => {
                    event.preventDefault()
                    if (who === null) {
                        setProblem("Choose a character or organization.")
                        return
                    }
                    setProblem(null)
                    send(
                        {
                            op: "add_participant",
                            body: {
                                expected_row_version: version,
                                participant_entity_id: who.id,
                                participant_role: role,
                            },
                        },
                        "Participant added",
                    )
                    setWho(null)
                }}
            >
                <ReferenceCombobox
                    id="participant-search"
                    label="Participant"
                    hint="A character or an organization."
                    value={who}
                    onChange={setWho}
                    search={search}
                    error={problem}
                    placeholder="Search"
                />
                <SelectField
                    id="participant-role-q"
                    label="Role in the quest"
                    value={role}
                    options={options.participant_roles}
                    onChange={setRole}
                />
                <button type="submit" className="authoring-button" disabled={busy}>
                    Add participant
                </button>
            </form>
        </section>
    )
}

function Outcomes({
    campaignId,
    view,
    options,
    version,
    busy,
    send,
}: {
    campaignId: string
    view: QuestAuthoringView
    options: QuestOptions
    version: number
    busy: boolean
    send: Send
}) {
    const [code, setCode] = useState("")
    const [name, setName] = useState("")
    const [description, setDescription] = useState("")
    const [category, setCategory] = useState("success")
    const [errors, setErrors] = useState<Record<string, string>>({})
    const outcomes = view.outcomes ?? []

    function add() {
        const found: Record<string, string> = {}
        if (!CODE_PATTERN.test(code.trim())) {
            found.code = "Use lowercase letters, digits and underscores, starting with a letter."
        }
        if (name.trim() === "") found.name = "Enter a name."
        setErrors(found)
        if (Object.keys(found).length > 0) return
        send(
            {
                op: "add_outcome",
                body: {
                    expected_row_version: version,
                    code: code.trim(),
                    name: name.trim(),
                    description: description.trim() === "" ? null : description.trim(),
                    outcome_category: category,
                },
            },
            "Outcome added",
        )
        setCode("")
        setName("")
        setDescription("")
    }

    return (
        <section aria-labelledby="outcomes-heading">
            <h3 id="outcomes-heading">Outcomes and rewards</h3>
            {outcomes.length === 0 ? <p>No outcomes.</p> : null}
            {outcomes.map((outcome) => (
                <OutcomeCard
                    key={outcome.quest_outcome_id}
                    campaignId={campaignId}
                    outcome={outcome}
                    options={options}
                    version={version}
                    busy={busy}
                    send={send}
                />
            ))}
            <form
                noValidate
                aria-label="Add an outcome"
                className="authoring-form"
                onSubmit={(event) => {
                    event.preventDefault()
                    add()
                }}
            >
                <TextField
                    id="outcome-code"
                    label="Code"
                    hint="A short permanent name, such as saved_the_village. It cannot change later."
                    value={code}
                    onChange={setCode}
                    required
                    error={errors.code ?? null}
                />
                <TextField
                    id="outcome-name"
                    label="Outcome name"
                    value={name}
                    onChange={setName}
                    required
                    error={errors.name ?? null}
                />
                <TextAreaField
                    id="outcome-description"
                    label="Outcome description"
                    value={description}
                    onChange={setDescription}
                    maxLength={options.limits.outcome_description_max_length}
                />
                <SelectField
                    id="outcome-category"
                    label="Kind of outcome"
                    value={category}
                    options={options.outcome_categories}
                    onChange={setCategory}
                />
                <button type="submit" className="authoring-button" disabled={busy}>
                    Add outcome
                </button>
            </form>
        </section>
    )
}

function OutcomeCard({
    campaignId,
    outcome,
    options,
    version,
    busy,
    send,
}: {
    campaignId: string
    outcome: QuestOutcomeView
    options: QuestOptions
    version: number
    busy: boolean
    send: Send
}) {
    const [editing, setEditing] = useState(false)
    const [name, setName] = useState(outcome.name)
    const [description, setDescription] = useState(outcome.description ?? "")
    const [category, setCategory] = useState(outcome.outcome_category)
    const [rewardType, setRewardType] = useState("other")
    const [rewardText, setRewardText] = useState("")
    const [item, setItem] = useState<ReferenceOption | null>(null)
    const [problem, setProblem] = useState<string | null>(null)

    async function searchKnowledge(query: string, signal: AbortSignal): Promise<ReferenceOption[]> {
        const page = await fetchQuestTargetOptions(campaignId, query, signal)
        return page.items
            .filter((i) => i.kind === "knowledge_item")
            .map((i) => ({ id: i.entity_id, label: i.name, detail: i.canon_status }))
    }

    function addReward() {
        if (rewardText.trim() === "") {
            setProblem("Describe the reward.")
            return
        }
        if (rewardType === "knowledge" && item === null) {
            setProblem("Choose the knowledge item.")
            return
        }
        setProblem(null)
        send(
            {
                op: "add_reward",
                outcomeId: outcome.quest_outcome_id,
                body: {
                    expected_row_version: version,
                    reward_type: rewardType,
                    description: rewardText.trim(),
                    reward_knowledge_item_id: rewardType === "knowledge" ? (item?.id ?? null) : null,
                },
            },
            "Reward added",
        )
        setRewardText("")
        setItem(null)
    }

    return (
        <article className="authoring-card" aria-label={`Outcome ${outcome.name}`}>
            <h4>
                {outcome.name} <span className="authoring-note">({outcome.code}, {outcome.outcome_category.replace("_", " ")})</span>
            </h4>
            {outcome.description !== null ? <p>{outcome.description}</p> : null}
            <ul className="authoring-choice-list">
                {outcome.rewards.map((r) => (
                    <li key={r.quest_reward_id}>
                        {r.reward_type}: {r.description}
                        {r.knowledge !== null ? ` (${r.knowledge.name})` : ""}{" "}
                        <button
                            type="button"
                            className="authoring-button"
                            disabled={busy}
                            onClick={() =>
                                send(
                                    { op: "remove_reward", rewardId: r.quest_reward_id, expected_row_version: version },
                                    "Reward removed",
                                )
                            }
                        >
                            Remove reward {r.description}
                        </button>
                    </li>
                ))}
            </ul>
            <div className="authoring-actions">
                <button type="button" className="authoring-button" onClick={() => setEditing(!editing)}>
                    {editing ? "Cancel editing" : `Edit ${outcome.name}`}
                </button>
                <button
                    type="button"
                    className="authoring-button"
                    disabled={busy}
                    onClick={() =>
                        send(
                            { op: "remove_outcome", outcomeId: outcome.quest_outcome_id, expected_row_version: version },
                            "Outcome removed",
                        )
                    }
                >
                    Remove {outcome.name}
                </button>
            </div>
            {editing ? (
                <form
                    noValidate
                    aria-label={`Edit outcome ${outcome.name}`}
                    className="authoring-form"
                    onSubmit={(event) => {
                        event.preventDefault()
                        if (name.trim() === "") return
                        send(
                            {
                                op: "update_outcome",
                                outcomeId: outcome.quest_outcome_id,
                                body: {
                                    expected_row_version: version,
                                    name: name.trim(),
                                    description: description.trim() === "" ? null : description.trim(),
                                    outcome_category: category,
                                },
                            },
                            "Outcome saved",
                        )
                        setEditing(false)
                    }}
                >
                    <TextField id={`o-name-${outcome.quest_outcome_id}`} label="Name" value={name} onChange={setName} required />
                    <TextAreaField
                        id={`o-desc-${outcome.quest_outcome_id}`}
                        label="Description"
                        value={description}
                        onChange={setDescription}
                    />
                    <SelectField
                        id={`o-cat-${outcome.quest_outcome_id}`}
                        label="Kind of outcome"
                        value={category}
                        options={options.outcome_categories}
                        onChange={setCategory}
                    />
                    <button type="submit" className="authoring-button" disabled={busy}>
                        Save outcome
                    </button>
                </form>
            ) : null}
            <form
                noValidate
                aria-label={`Add a reward to ${outcome.name}`}
                className="authoring-form"
                onSubmit={(event) => {
                    event.preventDefault()
                    addReward()
                }}
            >
                <SelectField
                    id={`r-type-${outcome.quest_outcome_id}`}
                    label="Reward kind"
                    value={rewardType}
                    options={options.reward_types}
                    onChange={setRewardType}
                />
                <TextField
                    id={`r-text-${outcome.quest_outcome_id}`}
                    label="Reward"
                    value={rewardText}
                    onChange={setRewardText}
                    required
                    error={problem}
                />
                {rewardType === "knowledge" ? (
                    <ReferenceCombobox
                        id={`r-item-${outcome.quest_outcome_id}`}
                        label="Knowledge item"
                        value={item}
                        onChange={setItem}
                        search={searchKnowledge}
                        placeholder="Search knowledge"
                    />
                ) : null}
                <button type="submit" className="authoring-button" disabled={busy}>
                    Add reward
                </button>
            </form>
        </article>
    )
}

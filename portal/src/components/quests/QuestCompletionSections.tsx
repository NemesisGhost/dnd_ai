import { useState } from "react"
import type { RefreshOutcome } from "../../hooks/useAuthoringMutation"
import { fetchQuestTargetOptions } from "../../api/questAuthoring"
import { fetchWorldEntities } from "../../api/world"
import type { QuestAuthoringView, QuestOptions, QuestOutcomeView } from "../../types/questAuthoring"
import { SelectField, TextAreaField, TextField } from "../authoring/fields"
import { ReferenceCombobox } from "../authoring/ReferenceCombobox"
import type { ReferenceOption } from "../authoring/ReferenceCombobox"
import { DraftConflict } from "./DraftConflict"
import { useQuestCommand } from "./useQuestCommand"
import { useSyncedDraft } from "./useSyncedDraft"
import { useUnsavedReport } from "./useUnsavedReport"
import type { ReportUnsaved } from "./useUnsavedReport"
import "../authoring/authoring.css"

// The completion design of a quest: dependencies between objectives, participants, and outcomes
// with their rewards. Each is its own section with its own saves, errors and unsent input. Every
// change is one idempotent command (the server returns the whole aggregate, which the page reads
// again). Nothing is keyed on the quest's row version: another section's save never discards what
// is half-typed here, and a form clears only what its own successful command consumed.
// Dependencies are structural and lock once the quest has progress; the rest stay editable.

const DEFAULT_DEPENDENCY = "prerequisite"
const DEFAULT_ROLE = "involved"
const DEFAULT_OUTCOME = "success"
const DEFAULT_REWARD = "other"
const CODE_PATTERN = /^[a-z][a-z0-9_]{0,63}$/

interface SectionProps {
    campaignId: string
    view: QuestAuthoringView
    options: QuestOptions
    // Reads the quest again (and whatever else depends on its version).
    refetch: () => Promise<RefreshOutcome>
    onUnsaved: ReportUnsaved
}

const objectivesOf = (view: QuestAuthoringView) =>
    view.stages.flatMap((s) =>
        s.objectives.map((o) => ({ id: o.quest_objective_id, label: `${s.name}: ${o.name}` })),
    )

// --- Dependencies ---------------------------------------------------------------------------------

export function QuestDependencies({ campaignId, view, options, refetch, onUnsaved }: SectionProps) {
    const command = useQuestCommand({ campaignId, questId: view.quest_id, scope: "dependencies", refetch })
    const [objective, setObjective] = useState("")
    const [dependsOn, setDependsOn] = useState("")
    const [kind, setKind] = useState(DEFAULT_DEPENDENCY)
    const [problem, setProblem] = useState<string | null>(null)
    useUnsavedReport(
        onUnsaved,
        "dependencies",
        objective !== "" || dependsOn !== "" || kind !== DEFAULT_DEPENDENCY ? ["a dependency"] : [],
    )

    const objectives = objectivesOf(view)
    const label = (id: string) => objectives.find((o) => o.id === id)?.label ?? "an objective"
    const allowed = view.available_actions.includes("add_dependency")
    const dependencies = view.dependencies ?? []
    const locked = view.has_progress
    return (
        <>
            {locked ? (
                <p className="authoring-note">
                    This quest has recorded progress, so dependencies can no longer change.
                </p>
            ) : null}
            {command.notice}
            {dependencies.length === 0 ? (
                <p>No dependencies.</p>
            ) : (
                <ul className="op-list">
                    {dependencies.map((d) => (
                        <li key={d.objective_dependency_id}>
                            {label(d.objective_id)} depends on {label(d.depends_on_objective_id)} ({d.dependency_type})
                            {allowed ? (
                                <>
                                    {" "}
                                    <button
                                        type="button"
                                        className="authoring-button"
                                        disabled={command.busy}
                                        onClick={() =>
                                            command.send(
                                                {
                                                    op: "remove_dependency",
                                                    dependencyId: d.objective_dependency_id,
                                                    expected_row_version: view.row_version,
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
                        command.send(
                            {
                                op: "add_dependency",
                                body: {
                                    expected_row_version: view.row_version,
                                    objective_id: objective,
                                    depends_on_objective_id: dependsOn,
                                    dependency_type: kind,
                                },
                            },
                            "Dependency added",
                            () => {
                                setObjective("")
                                setDependsOn("")
                                setKind(DEFAULT_DEPENDENCY)
                            },
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
                    <button type="submit" className="authoring-button" disabled={command.busy}>
                        Add dependency
                    </button>
                </form>
            ) : null}
        </>
    )
}

// --- Participants ---------------------------------------------------------------------------------

export function QuestParticipants({ campaignId, view, options, refetch, onUnsaved }: SectionProps) {
    const command = useQuestCommand({ campaignId, questId: view.quest_id, scope: "participants", refetch })
    const [who, setWho] = useState<ReferenceOption | null>(null)
    const [role, setRole] = useState(DEFAULT_ROLE)
    const [problem, setProblem] = useState<string | null>(null)
    useUnsavedReport(onUnsaved, "participants", who !== null || role !== DEFAULT_ROLE ? ["a participant"] : [])
    const editable = view.available_actions.includes("add_participant")
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
        <>
            {command.notice}
            {participants.length === 0 ? (
                <p>No participants.</p>
            ) : (
                <ul className="op-list">
                    {participants.map((p) => (
                        <li key={p.quest_participant_id}>
                            {p.participant?.name ?? "Unknown"} ({p.participant_role.replace("_", " ")}){" "}
                            {editable ? (
                                <button
                                    type="button"
                                    className="authoring-button"
                                    disabled={command.busy}
                                    onClick={() =>
                                        command.send(
                                            {
                                                op: "remove_participant",
                                                participantId: p.quest_participant_id,
                                                expected_row_version: view.row_version,
                                            },
                                            "Participant removed",
                                        )
                                    }
                                >
                                    Remove {p.participant?.name ?? "participant"}
                                </button>
                            ) : null}
                        </li>
                    ))}
                </ul>
            )}
            {editable ? (
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
                        command.send(
                            {
                                op: "add_participant",
                                body: {
                                    expected_row_version: view.row_version,
                                    participant_entity_id: who.id,
                                    participant_role: role,
                                },
                            },
                            "Participant added",
                            () => {
                                setWho(null)
                                setRole(DEFAULT_ROLE)
                            },
                        )
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
                    <button type="submit" className="authoring-button" disabled={command.busy}>
                        Add participant
                    </button>
                </form>
            ) : null}
        </>
    )
}

// --- Outcomes and rewards -------------------------------------------------------------------------

export function QuestOutcomes({ campaignId, view, options, refetch, onUnsaved }: SectionProps) {
    const command = useQuestCommand({ campaignId, questId: view.quest_id, scope: "outcomes", refetch })
    const [code, setCode] = useState("")
    const [name, setName] = useState("")
    const [description, setDescription] = useState("")
    const [category, setCategory] = useState(DEFAULT_OUTCOME)
    const [errors, setErrors] = useState<Record<string, string>>({})
    useUnsavedReport(
        onUnsaved,
        "outcomes",
        code.trim() !== "" || name.trim() !== "" || description.trim() !== "" || category !== DEFAULT_OUTCOME
            ? ["an outcome"]
            : [],
    )
    const editable = view.available_actions.includes("add_outcome")
    const outcomes = view.outcomes ?? []

    function add() {
        const found: Record<string, string> = {}
        if (!CODE_PATTERN.test(code.trim())) {
            found.code = "Use lowercase letters, digits and underscores, starting with a letter."
        }
        if (name.trim() === "") found.name = "Enter a name."
        setErrors(found)
        if (Object.keys(found).length > 0) return
        command.send(
            {
                op: "add_outcome",
                body: {
                    expected_row_version: view.row_version,
                    code: code.trim(),
                    name: name.trim(),
                    description: description.trim() === "" ? null : description.trim(),
                    outcome_category: category,
                },
            },
            "Outcome added",
            () => {
                setCode("")
                setName("")
                setDescription("")
                setCategory(DEFAULT_OUTCOME)
            },
        )
    }

    return (
        <>
            {command.notice}
            {outcomes.length === 0 ? <p>No outcomes.</p> : null}
            {outcomes.map((outcome) => (
                <OutcomeCard
                    key={outcome.quest_outcome_id}
                    campaignId={campaignId}
                    outcome={outcome}
                    options={options}
                    view={view}
                    editable={view.available_actions.includes("update_outcome")}
                    command={command}
                    onUnsaved={onUnsaved}
                />
            ))}
            {editable ? (
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
                    <button type="submit" className="authoring-button" disabled={command.busy}>
                        Add outcome
                    </button>
                </form>
            ) : null}
        </>
    )
}

function OutcomeCard({
    campaignId,
    outcome,
    options,
    view,
    editable,
    command,
    onUnsaved,
}: {
    campaignId: string
    outcome: QuestOutcomeView
    options: QuestOptions
    view: QuestAuthoringView
    editable: boolean
    command: ReturnType<typeof useQuestCommand>
    onUnsaved: ReportUnsaved
}) {
    const [editing, setEditing] = useState(false)
    const [rewardType, setRewardType] = useState(DEFAULT_REWARD)
    const [rewardText, setRewardText] = useState("")
    const [item, setItem] = useState<ReferenceOption | null>(null)
    const [problem, setProblem] = useState<string | null>(null)
    // The edit form follows the outcome's saved fields while untouched; its draft is kept, and if
    // those fields changed elsewhere meanwhile the person chooses before saving over them.
    const draft = useSyncedDraft(
        { name: outcome.name, description: outcome.description ?? "", category: outcome.outcome_category },
        view.row_version,
    )
    const { name, description, category } = draft.values
    const version = draft.version
    const addVersion = view.row_version
    useUnsavedReport(onUnsaved, `outcome-${outcome.quest_outcome_id}`, [
        ...(editing && draft.dirty ? ["an outcome"] : []),
        ...(rewardText.trim() !== "" || item !== null || rewardType !== DEFAULT_REWARD ? ["a reward"] : []),
    ])

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
        command.send(
            {
                op: "add_reward",
                outcomeId: outcome.quest_outcome_id,
                body: {
                    expected_row_version: addVersion,
                    reward_type: rewardType,
                    description: rewardText.trim(),
                    reward_knowledge_item_id: rewardType === "knowledge" ? (item?.id ?? null) : null,
                },
            },
            "Reward added",
            () => {
                setRewardText("")
                setItem(null)
                setRewardType(DEFAULT_REWARD)
            },
        )
    }

    return (
        <article className="authoring-card" aria-label={`Outcome ${outcome.name}`}>
            <h3>
                {outcome.name}{" "}
                <span className="authoring-note">
                    ({outcome.code}, {outcome.outcome_category.replace("_", " ")})
                </span>
            </h3>
            {outcome.description !== null ? <p>{outcome.description}</p> : null}
            <ul className="op-list">
                {outcome.rewards.map((r) => (
                    <li key={r.quest_reward_id}>
                        {r.reward_type}: {r.description}
                        {r.knowledge !== null ? ` (${r.knowledge.name})` : ""}{" "}
                        {editable ? (
                            <button
                                type="button"
                                className="authoring-button"
                                disabled={command.busy}
                                onClick={() =>
                                    command.send(
                                        { op: "remove_reward", rewardId: r.quest_reward_id, expected_row_version: addVersion },
                                        "Reward removed",
                                    )
                                }
                            >
                                Remove reward {r.description}
                            </button>
                        ) : null}
                    </li>
                ))}
            </ul>
            {editable ? (
                <>
                    <div className="authoring-actions">
                        <button type="button" className="authoring-button" onClick={() => setEditing(!editing)}>
                            {editing ? "Cancel editing" : `Edit ${outcome.name}`}
                        </button>
                        <button
                            type="button"
                            className="authoring-button"
                            disabled={command.busy}
                            onClick={() =>
                                command.send(
                                    {
                                        op: "remove_outcome",
                                        outcomeId: outcome.quest_outcome_id,
                                        expected_row_version: addVersion,
                                    },
                                    "Outcome removed",
                                )
                            }
                        >
                            Remove {outcome.name}
                        </button>
                    </div>
                    {editing && draft.conflict ? (
                        <DraftConflict what={`Outcome ${outcome.name}`} onLatest={draft.loadLatest} onKeep={draft.keepMine} />
                    ) : null}
                    {editing ? (
                        <form
                            noValidate
                            aria-label={`Edit outcome ${outcome.name}`}
                            className="authoring-form"
                            onSubmit={(event) => {
                                event.preventDefault()
                                if (name.trim() === "" || draft.conflict) return
                                draft.submitting({ name: name.trim(), description: description.trim(), category })
                                command.send(
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
                                    () => setEditing(false),
                                )
                            }}
                        >
                            <TextField
                                id={`o-name-${outcome.quest_outcome_id}`}
                                label="Name"
                                value={name}
                                onChange={(next) => draft.setValues({ ...draft.values, name: next })}
                                required
                            />
                            <TextAreaField
                                id={`o-desc-${outcome.quest_outcome_id}`}
                                label="Description"
                                value={description}
                                onChange={(next) => draft.setValues({ ...draft.values, description: next })}
                            />
                            <SelectField
                                id={`o-cat-${outcome.quest_outcome_id}`}
                                label="Kind of outcome"
                                value={category}
                                options={options.outcome_categories}
                                onChange={(next) => draft.setValues({ ...draft.values, category: next })}
                            />
                            <button type="submit" className="authoring-button" disabled={command.busy || draft.conflict}>
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
                        <button type="submit" className="authoring-button" disabled={command.busy}>
                            Add reward
                        </button>
                    </form>
                </>
            ) : null}
        </article>
    )
}

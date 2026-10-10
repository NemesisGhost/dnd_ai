import { useState } from "react"
import {
    relationshipAuthoringPath,
    runRelationshipCommand,
} from "../../api/relationshipAuthoring"
import { useSession } from "../../context/SessionContext"
import { useAuthoringMutation } from "../../hooks/useAuthoringMutation"
import { useAuthoringResource } from "../../hooks/useAuthoringResource"
import type {
    PerspectiveView,
    RelationshipCommand,
    RelationshipOptions,
    RelationshipView,
    TypedFields,
} from "../../types/relationshipAuthoring"
import { RELATIONSHIP_CODE_MESSAGE } from "../../utils/relationshipForm"
import { useAnnounce } from "./announcer"
import { SelectField, TextAreaField, TextField } from "./fields"
import { MutationStatusMessage, StaleWriteNotice } from "./feedback"
import { WorldTimePicker } from "./WorldTimePicker"
import "./authoring.css"

interface Props {
    campaignId: string
    relationshipId: string
    options: RelationshipOptions
    onChanged: () => void
}

const num = (value: string): number | null => (value.trim() === "" ? null : Number(value))
const text = (value: unknown): string => (value === null || value === undefined ? "" : String(value))

// One relationship, expanded: its fields, how it ends, archive and restore, and the baseline
// view each participant holds of it. Every change names the version the editor saw.
export function RelationshipEditor({ campaignId, relationshipId, options, onChanged }: Props) {
    const { reload } = useSession()
    const announce = useAnnounce()
    const { state, refetch } = useAuthoringResource<RelationshipView>(
        relationshipAuthoringPath(campaignId, relationshipId),
    )
    const [done, setDone] = useState<string | null>(null)
    const mutation = useAuthoringMutation<RelationshipCommand, RelationshipView>({
        scopeKey: `relationship:${relationshipId}`,
        request: (command, ctx) => runRelationshipCommand(campaignId, relationshipId, command, ctx),
        onSuccess: async () => {
            const message = done
            setDone(null)
            await refetch()
            onChanged()
            if (message !== null) announce(message)
        },
    })
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const busy = mutation.status.kind === "pending"
    const explained = error?.code ? (RELATIONSHIP_CODE_MESSAGE[error.code] ?? null) : null
    const run = (command: RelationshipCommand, message: string) => {
        setDone(message)
        mutation.submit(command)
    }

    if (state.kind === "loading") return <p role="status">Loading the relationship…</p>
    if (state.kind !== "ready") return <p role="alert">This relationship could not be loaded.</p>
    const view = state.data
    const can = (action: string) => view.available_actions.includes(action)

    return (
        <div className="authoring-card" aria-label={`Relationship ${view.relationship_type_label}`}>
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
            <p>
                {view.kind_label}: {view.relationship_type_label}
                {view.started !== null ? `, from ${view.started}` : ""}
                {view.ended !== null ? ` until ${view.ended}` : ""}
                {view.current_status !== null ? `. Now: ${view.current_status.replace(/_/g, " ")}` : ""}
            </p>
            <ul className="authoring-choice-list">
                {view.participants.map((p) => (
                    <li key={`${p.entity_id}-${p.role}`}>
                        {p.name} ({p.role_label})
                    </li>
                ))}
            </ul>
            {can("update") ? (
                <DetailsForm key={view.row_version} view={view} options={options} busy={busy} run={run} campaignId={campaignId} />
            ) : null}
            {can("end") ? (
                <EndForm view={view} busy={busy} run={run} campaignId={campaignId} />
            ) : null}
            <div className="authoring-actions">
                {can("archive") ? (
                    <button
                        type="button"
                        className="authoring-button"
                        disabled={busy}
                        onClick={() =>
                            run({ op: "archive", body: { expected_row_version: view.row_version } }, "Relationship archived")
                        }
                    >
                        Archive relationship
                    </button>
                ) : null}
                {can("restore") ? (
                    <button
                        type="button"
                        className="authoring-button"
                        disabled={busy}
                        onClick={() =>
                            run({ op: "restore", body: { expected_row_version: view.row_version } }, "Relationship restored")
                        }
                    >
                        Restore relationship
                    </button>
                ) : null}
            </div>
            {can("set_perspective") ? (
                <PerspectiveSection view={view} options={options} busy={busy} run={run} />
            ) : null}
        </div>
    )
}

type Run = (command: RelationshipCommand, message: string) => void

function DetailsForm({
    view,
    options,
    busy,
    run,
    campaignId,
}: {
    view: RelationshipView
    options: RelationshipOptions
    busy: boolean
    run: Run
    campaignId: string
}) {
    const [description, setDescription] = useState(view.description ?? "")
    const [start, setStart] = useState(view.started_world_time_id ?? "")
    const [unit, setUnit] = useState(text(view.typed.family_unit_name))
    const [title, setTitle] = useState(text(view.typed.job_title))
    const [share, setShare] = useState(text(view.typed.ownership_share))
    const [isPublic, setIsPublic] = useState(view.typed.is_public === false ? "no" : "yes")
    const [active, setActive] = useState(view.typed.is_active === false ? "no" : "yes")
    const [terms, setTerms] = useState(text(view.typed.treaty_terms))
    const [distance, setDistance] = useState(text(view.typed.distance_text))
    const [duration, setDuration] = useState(text(view.typed.travel_time_text))
    const [mode, setMode] = useState(text(view.typed.travel_mode))
    const [hidden, setHidden] = useState(view.typed.is_hidden === true ? "yes" : "no")
    const [office, setOffice] = useState(text(view.typed.role))
    const [rank, setRank] = useState(text(view.typed.rank))
    const [problem, setProblem] = useState<string | null>(null)

    function typedFields(): TypedFields {
        const typed: TypedFields = {}
        if (view.kind === "family") typed.family_unit_name = unit.trim() === "" ? null : unit.trim()
        if (view.kind === "employment") typed.job_title = title.trim() === "" ? null : title.trim()
        if (view.kind === "ownership") {
            typed.ownership_share = num(share)
            typed.is_public = isPublic === "yes"
        }
        if (view.kind === "route") {
            typed.distance_text = distance.trim() === "" ? null : distance.trim()
            typed.travel_time_text = duration.trim() === "" ? null : duration.trim()
            typed.travel_mode = mode.trim() === "" ? null : mode.trim()
            typed.is_hidden = hidden === "yes"
        }
        if (view.kind === "membership") {
            typed.role = office.trim() === "" ? null : office.trim()
            typed.rank = rank.trim() === "" ? null : rank.trim()
            typed.is_public = isPublic === "yes"
        }
        if (view.kind === "political") {
            typed.is_active = active === "yes"
            typed.treaty_terms = terms.trim() === "" ? null : terms.trim()
        }
        return typed
    }

    return (
        <form
            noValidate
            aria-label="Edit relationship"
            className="authoring-form"
            onSubmit={(event) => {
                event.preventDefault()
                const parsed = num(share)
                if (view.kind === "ownership" && parsed !== null && (!Number.isInteger(parsed) || parsed < 0 || parsed > 100)) {
                    setProblem("Share is a whole number from 0 to 100.")
                    return
                }
                setProblem(null)
                run(
                    {
                        op: "update",
                        body: {
                            expected_row_version: view.row_version,
                            description: description.trim() === "" ? null : description.trim(),
                            started_world_time_id: start === "" ? null : start,
                            ...typedFields(),
                        },
                    },
                    "Relationship saved",
                )
            }}
        >
            <TextAreaField
                id={`rel-description-${view.relationship_id}`}
                label="Description"
                value={description}
                onChange={setDescription}
                maxLength={options.limits.text_max_length}
            />
            <WorldTimePicker
                campaignId={campaignId}
                id={`rel-start-${view.relationship_id}`}
                label="Started"
                value={start}
                onChange={setStart}
            />
            {view.kind === "family" ? (
                <TextField id={`rel-unit-${view.relationship_id}`} label="Family name" value={unit} onChange={setUnit} />
            ) : null}
            {view.kind === "employment" ? (
                <TextField id={`rel-title-${view.relationship_id}`} label="Job title" value={title} onChange={setTitle} />
            ) : null}
            {view.kind === "ownership" ? (
                <>
                    <TextField
                        id={`rel-share-${view.relationship_id}`}
                        label="Share (0 to 100)"
                        value={share}
                        onChange={setShare}
                        error={problem}
                    />
                    <SelectField
                        id={`rel-public-${view.relationship_id}`}
                        label="Known to the public"
                        value={isPublic}
                        options={[
                            { value: "yes", label: "Yes" },
                            { value: "no", label: "No, only editors see it" },
                        ]}
                        onChange={setIsPublic}
                    />
                </>
            ) : null}
            {view.kind === "route" ? (
                <>
                    <TextField id={`rel-distance-${view.relationship_id}`} label="Distance" value={distance} onChange={setDistance} />
                    <TextField id={`rel-duration-${view.relationship_id}`} label="Travel time" value={duration} onChange={setDuration} />
                    <TextField id={`rel-mode-${view.relationship_id}`} label="Mode of travel" value={mode} onChange={setMode} />
                    <SelectField
                        id={`rel-hidden-${view.relationship_id}`}
                        label="Concealed"
                        hint="Only editors see a concealed route."
                        value={hidden}
                        options={[
                            { value: "no", label: "No" },
                            { value: "yes", label: "Yes" },
                        ]}
                        onChange={setHidden}
                    />
                </>
            ) : null}
            {view.kind === "membership" ? (
                <>
                    <TextField id={`rel-office-${view.relationship_id}`} label="Office or role" value={office} onChange={setOffice} />
                    <TextField id={`rel-rank-${view.relationship_id}`} label="Rank" value={rank} onChange={setRank} />
                    <SelectField
                        id={`rel-public-${view.relationship_id}`}
                        label="Known to the public"
                        value={isPublic}
                        options={[
                            { value: "yes", label: "Yes" },
                            { value: "no", label: "No, only editors see it" },
                        ]}
                        onChange={setIsPublic}
                    />
                </>
            ) : null}
            {view.kind === "political" ? (
                <>
                    <SelectField
                        id={`rel-active-${view.relationship_id}`}
                        label="In force"
                        value={active}
                        options={[
                            { value: "yes", label: "Yes" },
                            { value: "no", label: "No" },
                        ]}
                        onChange={setActive}
                    />
                    <TextAreaField id={`rel-terms-${view.relationship_id}`} label="Terms" value={terms} onChange={setTerms} />
                </>
            ) : null}
            <button type="submit" className="authoring-button" disabled={busy}>
                Save relationship
            </button>
        </form>
    )
}

function EndForm({
    view,
    busy,
    run,
    campaignId,
}: {
    view: RelationshipView
    busy: boolean
    run: Run
    campaignId: string
}) {
    const [when, setWhen] = useState("")
    const [problem, setProblem] = useState<string | null>(null)
    return (
        <form
            noValidate
            aria-label="End relationship"
            className="authoring-form"
            onSubmit={(event) => {
                event.preventDefault()
                if (when === "") {
                    setProblem("Choose when it ended.")
                    return
                }
                setProblem(null)
                run(
                    { op: "end", body: { expected_row_version: view.row_version, ended_world_time_id: when } },
                    "Relationship ended",
                )
            }}
        >
            <WorldTimePicker
                campaignId={campaignId}
                id={`rel-end-${view.relationship_id}`}
                label="Ended"
                value={when}
                onChange={setWhen}
                error={problem}
            />
            <button type="submit" className="authoring-button" disabled={busy}>
                End relationship
            </button>
        </form>
    )
}

function PerspectiveSection({
    view,
    options,
    busy,
    run,
}: {
    view: RelationshipView
    options: RelationshipOptions
    busy: boolean
    run: Run
}) {
    const first = view.participants[0]?.entity_id ?? ""
    const [holder, setHolder] = useState(first)
    const existing: PerspectiveView | undefined = view.perspectives.find((p) => p.holder_entity_id === holder)
    return (
        <section aria-label="Perspectives">
            <h4>How each participant sees it</h4>
            <SelectField
                id={`persp-holder-${view.relationship_id}`}
                label="Participant"
                value={holder}
                options={view.participants.map((p) => ({ value: p.entity_id, label: p.name }))}
                onChange={setHolder}
            />
            <PerspectiveForm key={holder + view.row_version} view={view} holder={holder} existing={existing} options={options} busy={busy} run={run} />
        </section>
    )
}

function PerspectiveForm({
    view,
    holder,
    existing,
    options,
    busy,
    run,
}: {
    view: RelationshipView
    holder: string
    existing: PerspectiveView | undefined
    options: RelationshipOptions
    busy: boolean
    run: Run
}) {
    const [values, setValues] = useState({
        affinity: text(existing?.affinity),
        trust: text(existing?.trust),
        respect: text(existing?.respect),
        fear: text(existing?.fear),
        obligation: text(existing?.obligation),
    })
    const [tone, setTone] = useState(existing?.emotional_tone ?? "")
    const [interpretation, setInterpretation] = useState(existing?.private_interpretation ?? "")
    const [problem, setProblem] = useState<string | null>(null)
    const { stance_min: min, stance_max: max } = options.limits
    return (
        <form
            noValidate
            aria-label="Set perspective"
            className="authoring-form"
            onSubmit={(event) => {
                event.preventDefault()
                const parsed = Object.values(values).map(num)
                if (parsed.some((n) => n !== null && (!Number.isInteger(n) || n < min || n > max))) {
                    setProblem(`Each rating is a whole number from ${min} to ${max}.`)
                    return
                }
                setProblem(null)
                run(
                    {
                        op: "perspective",
                        body: {
                            expected_row_version: view.row_version,
                            holder_entity_id: holder,
                            affinity: num(values.affinity),
                            trust: num(values.trust),
                            respect: num(values.respect),
                            fear: num(values.fear),
                            obligation: num(values.obligation),
                            emotional_tone: tone.trim() === "" ? null : tone.trim(),
                            private_interpretation: interpretation.trim() === "" ? null : interpretation.trim(),
                        },
                    },
                    "Perspective saved",
                )
            }}
        >
            {(["affinity", "trust", "respect", "fear", "obligation"] as const).map((name) => (
                <TextField
                    key={name}
                    id={`persp-${name}-${view.relationship_id}`}
                    label={name[0]!.toUpperCase() + name.slice(1)}
                    value={values[name]}
                    onChange={(value) => setValues({ ...values, [name]: value })}
                    error={name === "affinity" ? problem : null}
                />
            ))}
            <TextField id={`persp-tone-${view.relationship_id}`} label="Emotional tone" value={tone} onChange={setTone} />
            <TextAreaField
                id={`persp-private-${view.relationship_id}`}
                label="Private interpretation"
                hint="Only editors see this."
                value={interpretation}
                onChange={setInterpretation}
            />
            <button type="submit" className="authoring-button" disabled={busy}>
                Save perspective
            </button>
        </form>
    )
}

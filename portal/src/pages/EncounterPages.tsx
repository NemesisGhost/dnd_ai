import { useState } from "react"
import { Link, useNavigate, useParams } from "react-router"
import {
    abortEncounter,
    addParticipant,
    encounterOptionsPath,
    endEncounter,
    prepareEncounter,
    preparedEncounterPath,
    recordTurn,
    removeParticipant,
    startEncounter,
    updateEncounter,
    updateParticipant,
} from "../api/encounters"
import type { TurnBody } from "../api/encounters"
import { fetchWorldEntities } from "../api/world"
import { useAnnounce } from "../components/authoring/announcer"
import { ConfirmDialog } from "../components/authoring/ConfirmDialog"
import { SelectField, TextAreaField, TextField } from "../components/authoring/fields"
import { MutationStatusMessage } from "../components/authoring/feedback"
import { ReferenceCombobox } from "../components/authoring/ReferenceCombobox"
import type { ReferenceOption } from "../components/authoring/ReferenceCombobox"
import { useSession } from "../context/SessionContext"
import { useAuthoringMutation } from "../hooks/useAuthoringMutation"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { useCampaignCapability } from "../hooks/useCampaignCapability"
import { usePageArrival } from "../hooks/usePageArrival"
import type { EncounterOptions, PreparedEncounter } from "../types/encounters"
import type { WorldCategory } from "../types/world"
import "../components/authoring/authoring.css"

const CODE_MESSAGE: Readonly<Record<string, string>> = {
    encounter_not_pending: "This encounter has already started or finished, so it can no longer be prepared.",
    encounter_participant_exists: "That character is already in this encounter.",
    encounter_participant_invalid: "Choose a published character or place in this world.",
    encounter_full: "This encounter has as many participants as it can hold.",
    encounter_not_ready: "Add at least one participant before starting the encounter.",
    encounter_finished: "This encounter has already finished.",
    conflict: "That could not be recorded: the encounter is not active, or that character has already taken a turn this round.",
    session_not_usable: "Encounters cannot be prepared in an archived session.",
    clock_required: "Set the campaign time first.",
}

const base = (campaignId: string): string => `/app/${encodeURIComponent(campaignId)}`
const runPath = (campaignId: string, sessionId: string, section?: string): string =>
    `${base(campaignId)}/sessions/${encodeURIComponent(sessionId)}/run${section ? `?section=${section}` : ""}`
const encounterPath = (campaignId: string, sessionId: string, encounterId: string): string =>
    `${base(campaignId)}/sessions/${encodeURIComponent(sessionId)}/encounters/${encodeURIComponent(encounterId)}`

const humanize = (code: string): string => code.replace(/_/g, " ")

function useSearch(campaignId: string, category: WorldCategory) {
    return async (query: string, signal: AbortSignal): Promise<ReferenceOption[]> => {
        const page = await fetchWorldEntities(campaignId, { category, query, limit: 10 }, signal)
        return page.items
            .filter((i) => i.canon_status === undefined || i.canon_status === "canon")
            .map((i) => ({ id: i.entity_id, label: i.name, detail: humanize(i.entity_type_code) }))
    }
}

// Parses an optional whole-number initiative; `undefined` means the box holds something else.
function parseInitiative(value: string, min: number, max: number): number | null | undefined {
    const trimmed = value.trim()
    if (trimmed === "") return null
    const parsed = Number(trimmed)
    return Number.isInteger(parsed) && parsed >= min && parsed <= max ? parsed : undefined
}

// /app/:campaignId/sessions/:sessionId/encounters/new: prepare a pending encounter.
export function PrepareEncounterPage() {
    const { campaignId = "", sessionId = "" } = useParams()
    const canEdit = useCampaignCapability(campaignId, "canon.edit")
    const navigate = useNavigate()
    const { reload } = useSession()
    const announce = useAnnounce()
    const options = useAuthoringResource<EncounterOptions>(encounterOptionsPath(campaignId))
    const headingRef = usePageArrival(options.state.kind === "ready")
    const [place, setPlace] = useState<ReferenceOption | null>(null)
    const [summary, setSummary] = useState("")
    const searchPlaces = useSearch(campaignId, "location")
    const mutation = useAuthoringMutation<
        { location_id: string | null; summary: string | null },
        PreparedEncounter
    >({
        scopeKey: `prepare-encounter:${sessionId}`,
        request: (body, ctx) => prepareEncounter(campaignId, { session_id: sessionId, ...body }, ctx),
        onSuccess: (created) => {
            announce("Encounter prepared")
            void navigate(encounterPath(campaignId, sessionId, created.encounter_id), { replace: true })
        },
    })
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const explained = error?.code ? (CODE_MESSAGE[error.code] ?? null) : null
    const max = options.state.kind === "ready" ? options.state.data.limits.summary_max_length : 4000
    const tooLong = summary.trim().length > max
    return (
        <section className="authoring-page" aria-labelledby="prepare-encounter-heading">
            <p className="authoring-page__breadcrumb">
                <Link to={runPath(campaignId, sessionId, "encounter-prep")}>Run the session</Link>
            </p>
            <h1 id="prepare-encounter-heading" ref={headingRef} tabIndex={-1}>
                Prepare an encounter
            </h1>
            {!canEdit ? (
                <p role="alert">You do not have permission to prepare encounters.</p>
            ) : (
                <>
                    <p>
                        A prepared encounter is saved as pending. Add who takes part and which side they
                        are on; starting it comes later.
                    </p>
                    {explained !== null ? (
                        <p role="alert">{explained}</p>
                    ) : error !== null ? (
                        <MutationStatusMessage error={error} onRetry={mutation.retry} onCheckSession={reload} />
                    ) : null}
                    <form
                        noValidate
                        aria-label="Prepare an encounter"
                        className="authoring-form"
                        onSubmit={(event) => {
                            event.preventDefault()
                            if (tooLong) return
                            mutation.submit({
                                location_id: place?.id ?? null,
                                summary: summary.trim() === "" ? null : summary.trim(),
                            })
                        }}
                    >
                        <ReferenceCombobox
                            id="encounter-place"
                            label="Where it happens (optional)"
                            value={place}
                            onChange={setPlace}
                            search={searchPlaces}
                            placeholder="Search places"
                        />
                        <TextAreaField
                            id="encounter-summary"
                            label="Summary (optional)"
                            value={summary}
                            onChange={setSummary}
                            maxLength={max}
                            error={tooLong ? `Summary must be ${max} characters or fewer.` : null}
                        />
                        <button type="submit" className="authoring-button" disabled={mutation.status.kind === "pending"}>
                            Prepare encounter
                        </button>
                    </form>
                </>
            )}
        </section>
    )
}

type Command =
    | { op: "update"; location_id: string | null; summary: string | null }
    | { op: "add"; participant_entity_id: string; side: string; initiative: number | null }
    | { op: "change"; participant_id: string; side: string; initiative: number | null }
    | { op: "remove"; participant_id: string }
    | { op: "start" }
    | { op: "abort" }
    | { op: "turn"; body: TurnBody }
    | { op: "end"; outcomes: { participant_entity_id: string; outcome: string }[]; summary: string | null }

// /app/:campaignId/sessions/:sessionId/encounters/:encounterId: a prepared encounter.
export function PreparedEncounterPage() {
    const { campaignId = "", sessionId = "", encounterId = "" } = useParams()
    const canEdit = useCampaignCapability(campaignId, "canon.edit")
    const resource = useAuthoringResource<PreparedEncounter>(preparedEncounterPath(campaignId, encounterId))
    const options = useAuthoringResource<EncounterOptions>(encounterOptionsPath(campaignId))
    const headingRef = usePageArrival(resource.state.kind === "ready")
    return (
        <section className="authoring-page" aria-labelledby="encounter-heading">
            <p className="authoring-page__breadcrumb">
                <Link
                    to={runPath(
                        campaignId,
                        sessionId,
                        resource.state.kind === "ready"
                            ? resource.state.data.status === "pending"
                                ? "encounter-prep"
                                : "encounters"
                            : undefined,
                    )}
                >
                    Run the session
                </Link>
            </p>
            <h1 id="encounter-heading" ref={headingRef} tabIndex={-1}>
                Encounter
            </h1>
            {!canEdit ? (
                <p role="alert">You do not have permission to prepare encounters.</p>
            ) : resource.state.kind === "loading" || options.state.kind === "loading" ? (
                <p role="status">Loading…</p>
            ) : resource.state.kind !== "ready" || options.state.kind !== "ready" ? (
                <p role="alert">This encounter does not exist, or you do not have access to it.</p>
            ) : (
                <Loaded
                    campaignId={campaignId}
                    view={resource.state.data}
                    options={options.state.data}
                    refetch={resource.refetch}
                />
            )}
        </section>
    )
}

function Loaded({
    campaignId,
    view,
    options,
    refetch,
}: {
    campaignId: string
    view: PreparedEncounter
    options: EncounterOptions
    refetch: () => Promise<void>
}) {
    const { reload } = useSession()
    const announce = useAnnounce()
    const searchPlaces = useSearch(campaignId, "location")
    const searchCharacters = useSearch(campaignId, "character")
    const [place, setPlace] = useState<ReferenceOption | null>(
        view.location_id === null ? null : { id: view.location_id, label: view.location_name ?? "" },
    )
    const [summary, setSummary] = useState(view.summary ?? "")
    const [who, setWho] = useState<ReferenceOption | null>(null)
    const [side, setSide] = useState("party")
    const [initiative, setInitiative] = useState("")
    const [edits, setEdits] = useState<Record<string, { side: string; initiative: string }>>({})
    const [problem, setProblem] = useState<string | null>(null)
    const [done, setDone] = useState<string | null>(null)
    const { initiative_min: low, initiative_max: high } = options.limits
    const [actor, setActor] = useState("")
    const [action, setAction] = useState("attack")
    const [target, setTarget] = useState("")
    const [result, setResult] = useState("")
    const [damage, setDamage] = useState("")
    const [round, setRound] = useState("")
    const [outcomes, setOutcomes] = useState<Record<string, string>>({})
    const [endSummary, setEndSummary] = useState("")
    const [confirmAbort, setConfirmAbort] = useState(false)

    const mutation = useAuthoringMutation<Command, unknown>({
        scopeKey: `encounter:${view.encounter_id}`,
        request: (command, ctx) => {
            switch (command.op) {
                case "update":
                    return updateEncounter(
                        campaignId,
                        view.encounter_id,
                        { location_id: command.location_id, summary: command.summary },
                        ctx,
                    )
                case "add":
                    return addParticipant(
                        campaignId,
                        view.encounter_id,
                        {
                            participant_entity_id: command.participant_entity_id,
                            side: command.side,
                            initiative: command.initiative,
                        },
                        ctx,
                    )
                case "change":
                    return updateParticipant(
                        campaignId,
                        view.encounter_id,
                        command.participant_id,
                        { side: command.side, initiative: command.initiative },
                        ctx,
                    )
                case "remove":
                    return removeParticipant(campaignId, view.encounter_id, command.participant_id, ctx)
                case "start":
                    return startEncounter(campaignId, view.encounter_id, ctx)
                case "abort":
                    return abortEncounter(campaignId, view.encounter_id, ctx)
                case "turn":
                    return recordTurn(campaignId, view.encounter_id, command.body, ctx)
                case "end":
                    return endEncounter(
                        campaignId,
                        view.encounter_id,
                        {
                            outcomes: command.outcomes,
                            ...(command.summary === null ? {} : { summary: command.summary }),
                        },
                        ctx,
                    )
            }
        },
        onSuccess: async () => {
            const message = done
            setDone(null)
            setWho(null)
            setInitiative("")
            setEdits({})
            setActor("")
            setTarget("")
            setResult("")
            setDamage("")
            setConfirmAbort(false)
            await refetch()
            if (message !== null) announce(message)
        },
    })
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const explained = error?.code ? (CODE_MESSAGE[error.code] ?? null) : null
    const busy = mutation.status.kind === "pending"
    const run = (command: Command, message: string) => {
        setProblem(null)
        setDone(message)
        mutation.submit(command)
    }

    return (
        <>
            <p>
                Status: <strong>{view.status}</strong>
                {view.can_prepare ? "" : ". Preparation is over; this encounter can no longer be changed here."}
            </p>
            {explained !== null ? (
                <p role="alert">{explained}</p>
            ) : error !== null ? (
                <MutationStatusMessage error={error} onRetry={mutation.retry} onCheckSession={reload} />
            ) : null}
            {problem !== null ? <p role="alert">{problem}</p> : null}

            {view.can_prepare ? (
                <form
                    noValidate
                    aria-label="Encounter details"
                    className="authoring-form"
                    onSubmit={(event) => {
                        event.preventDefault()
                        run(
                            {
                                op: "update",
                                location_id: place?.id ?? null,
                                summary: summary.trim() === "" ? null : summary.trim(),
                            },
                            "Encounter saved",
                        )
                    }}
                >
                    <ReferenceCombobox
                        id="encounter-details-place"
                        label="Where it happens"
                        value={place}
                        onChange={setPlace}
                        search={searchPlaces}
                        placeholder="Search places"
                    />
                    <TextAreaField
                        id="encounter-details-summary"
                        label="Summary"
                        value={summary}
                        onChange={setSummary}
                        maxLength={options.limits.summary_max_length}
                    />
                    <button type="submit" className="authoring-button" disabled={busy}>
                        Save details
                    </button>
                </form>
            ) : (
                <dl className="authoring-fact-list">
                    <dt>Where</dt>
                    <dd>{view.location_name ?? "Nowhere in particular"}</dd>
                    <dt>Summary</dt>
                    <dd>{view.summary ?? "(none)"}</dd>
                </dl>
            )}

            <h2>Participants</h2>
            {view.participants.length === 0 ? <p>Nobody has been added yet.</p> : null}
            <ul className="authoring-choice-list">
                {view.participants.map((p) => {
                    const edit = edits[p.encounter_participant_id] ?? {
                        side: p.side,
                        initiative: p.initiative === null ? "" : String(p.initiative),
                    }
                    return (
                        <li key={p.encounter_participant_id}>
                            <strong>{p.name}</strong> ({humanize(p.entity_type_code)})
                            {view.can_prepare ? (
                                <form
                                    noValidate
                                    aria-label={`Change ${p.name}`}
                                    className="authoring-form"
                                    onSubmit={(event) => {
                                        event.preventDefault()
                                        const value = parseInitiative(edit.initiative, low, high)
                                        if (value === undefined) {
                                            setProblem(`Initiative must be a whole number from ${low} to ${high}.`)
                                            return
                                        }
                                        run(
                                            {
                                                op: "change",
                                                participant_id: p.encounter_participant_id,
                                                side: edit.side,
                                                initiative: value,
                                            },
                                            `${p.name} updated`,
                                        )
                                    }}
                                >
                                    <SelectField
                                        id={`side-${p.encounter_participant_id}`}
                                        label={`Side of ${p.name}`}
                                        value={edit.side}
                                        options={options.sides}
                                        onChange={(value) =>
                                            setEdits({
                                                ...edits,
                                                [p.encounter_participant_id]: { ...edit, side: value },
                                            })
                                        }
                                    />
                                    <TextField
                                        id={`initiative-${p.encounter_participant_id}`}
                                        label={`Initiative of ${p.name}`}
                                        value={edit.initiative}
                                        onChange={(value) =>
                                            setEdits({
                                                ...edits,
                                                [p.encounter_participant_id]: { ...edit, initiative: value },
                                            })
                                        }
                                    />
                                    <button type="submit" className="authoring-button" disabled={busy}>
                                        Save {p.name}
                                    </button>{" "}
                                    <button
                                        type="button"
                                        className="authoring-button"
                                        disabled={busy}
                                        onClick={() =>
                                            run(
                                                { op: "remove", participant_id: p.encounter_participant_id },
                                                `${p.name} removed`,
                                            )
                                        }
                                    >
                                        Remove {p.name}
                                    </button>
                                </form>
                            ) : (
                                <>
                                    {", "}
                                    {humanize(p.side)}
                                    {p.initiative !== null ? `, initiative ${p.initiative}` : ""}
                                    {p.current_hit_points !== null
                                        ? `, ${p.current_hit_points} of ${p.maximum_hit_points} hit points`
                                        : ""}
                                    {p.outcome !== null ? `, ${humanize(p.outcome)}` : ""}
                                </>
                            )}
                        </li>
                    )
                })}
            </ul>

            {view.can_prepare ? (
                <form
                    noValidate
                    aria-label="Add a participant"
                    className="authoring-form"
                    onSubmit={(event) => {
                        event.preventDefault()
                        const value = parseInitiative(initiative, low, high)
                        if (who === null) {
                            setProblem("Choose a character to add.")
                            return
                        }
                        if (value === undefined) {
                            setProblem(`Initiative must be a whole number from ${low} to ${high}.`)
                            return
                        }
                        run(
                            { op: "add", participant_entity_id: who.id, side, initiative: value },
                            `${who.label} added`,
                        )
                    }}
                >
                    <ReferenceCombobox
                        id="encounter-add-who"
                        label="Character"
                        value={who}
                        onChange={setWho}
                        search={searchCharacters}
                        placeholder="Search characters"
                    />
                    <SelectField id="encounter-add-side" label="Side" value={side} options={options.sides} onChange={setSide} />
                    <TextField
                        id="encounter-add-initiative"
                        label="Initiative (optional)"
                        value={initiative}
                        onChange={setInitiative}
                    />
                    <button type="submit" className="authoring-button" disabled={busy}>
                        Add participant
                    </button>
                </form>
            ) : null}

            {view.can_prepare ? (
                <p>
                    <button
                        type="button"
                        className="authoring-button"
                        disabled={busy}
                        onClick={() => run({ op: "start" }, "Encounter started")}
                    >
                        Start encounter
                    </button>{" "}
                    <button
                        type="button"
                        className="authoring-button"
                        disabled={busy}
                        onClick={() => setConfirmAbort(true)}
                    >
                        Discard encounter
                    </button>
                </p>
            ) : null}

            {view.status === "active" ? (
                <>
                    <h2>Round {view.current_round}</h2>
                    <form
                        noValidate
                        aria-label="Record a turn"
                        className="authoring-form"
                        onSubmit={(event) => {
                            event.preventDefault()
                            if (actor === "") {
                                setProblem("Choose who is taking the turn.")
                                return
                            }
                            const points = damage.trim() === "" ? null : Number(damage)
                            if (points !== null && (!Number.isInteger(points) || points < 0)) {
                                setProblem("Damage must be a whole number, zero or more.")
                                return
                            }
                            const roundNumber = round.trim() === "" ? null : Number(round)
                            if (roundNumber !== null && (!Number.isInteger(roundNumber) || roundNumber < 1)) {
                                setProblem("The round must be a whole number from 1.")
                                return
                            }
                            run(
                                {
                                    op: "turn",
                                    body: {
                                        actor_entity_id: actor,
                                        action_kind: action,
                                        ...(roundNumber === null ? {} : { round_number: roundNumber }),
                                        ...(target === "" ? {} : { target_entity_id: target }),
                                        ...(result === "" ? {} : { hit: result === "hit" }),
                                        ...(points === null ? {} : { damage_amount: points }),
                                    },
                                },
                                "Turn recorded",
                            )
                        }}
                    >
                        <SelectField
                            id="turn-actor"
                            label="Who acts"
                            value={actor}
                            placeholder="Choose a participant"
                            options={view.participants.map((p) => ({ value: p.participant_entity_id, label: p.name }))}
                            onChange={setActor}
                        />
                        <SelectField
                            id="turn-action"
                            label="Action"
                            value={action}
                            options={options.action_kinds}
                            onChange={setAction}
                        />
                        <SelectField
                            id="turn-target"
                            label="Target (optional)"
                            value={target}
                            placeholder="No target"
                            options={view.participants.map((p) => ({ value: p.participant_entity_id, label: p.name }))}
                            onChange={setTarget}
                        />
                        <SelectField
                            id="turn-result"
                            label="Result"
                            value={result}
                            placeholder="Not reported"
                            options={[
                                { value: "hit", label: "Hit" },
                                { value: "miss", label: "Miss" },
                            ]}
                            onChange={setResult}
                        />
                        <TextField
                            id="turn-damage"
                            label="Damage (optional)"
                            hint="A hit that damages a tracked character lowers their hit points."
                            value={damage}
                            onChange={setDamage}
                        />
                        <TextField
                            id="turn-round"
                            label="Round (optional)"
                            hint={`Leave empty for round ${view.current_round}.`}
                            value={round}
                            onChange={setRound}
                        />
                        <button type="submit" className="authoring-button" disabled={busy}>
                            Record turn
                        </button>
                    </form>

                    <form
                        noValidate
                        aria-label="End the encounter"
                        className="authoring-form"
                        onSubmit={(event) => {
                            event.preventDefault()
                            run(
                                {
                                    op: "end",
                                    outcomes: Object.entries(outcomes)
                                        .filter(([, outcome]) => outcome !== "")
                                        .map(([participant_entity_id, outcome]) => ({
                                            participant_entity_id,
                                            outcome,
                                        })),
                                    summary: endSummary.trim() === "" ? null : endSummary.trim(),
                                },
                                "Encounter ended",
                            )
                        }}
                    >
                        <h3>End the encounter</h3>
                        {view.participants.map((p) => (
                            <SelectField
                                key={p.encounter_participant_id}
                                id={`outcome-${p.encounter_participant_id}`}
                                label={`Outcome for ${p.name}`}
                                value={outcomes[p.participant_entity_id] ?? ""}
                                placeholder="No tracked outcome"
                                options={options.outcomes}
                                onChange={(value) =>
                                    setOutcomes({ ...outcomes, [p.participant_entity_id]: value })
                                }
                            />
                        ))}
                        <TextAreaField
                            id="end-summary"
                            label="How it ended (optional)"
                            value={endSummary}
                            onChange={setEndSummary}
                            maxLength={options.limits.summary_max_length}
                        />
                        <button type="submit" className="authoring-button" disabled={busy}>
                            End encounter
                        </button>{" "}
                        <button
                            type="button"
                            className="authoring-button"
                            disabled={busy}
                            onClick={() => setConfirmAbort(true)}
                        >
                            Abort encounter
                        </button>
                    </form>
                </>
            ) : null}

            {view.rounds.length > 0 ? (
                <>
                    <h2>Turns</h2>
                    {view.rounds.map((r) => (
                        <section key={r.round_number} aria-label={`Round ${r.round_number}`}>
                            <h3>Round {r.round_number}</h3>
                            <ol className="authoring-choice-list">
                                {r.turns.map((t) => (
                                    <li key={t.turn_order}>
                                        {t.actor_name}: {humanize(t.action_kind ?? "turn")}
                                        {t.target_name !== null ? ` at ${t.target_name}` : ""}
                                        {t.hit === true ? ", hit" : t.hit === false ? ", miss" : ""}
                                        {t.damage_amount !== null && t.damage_amount > 0
                                            ? `, ${t.damage_amount} damage`
                                            : ""}
                                    </li>
                                ))}
                            </ol>
                        </section>
                    ))}
                </>
            ) : null}

            <ConfirmDialog
                open={confirmAbort}
                title={view.status === "pending" ? "Discard this encounter?" : "Abort this encounter?"}
                description={
                    view.status === "pending"
                        ? "The prepared encounter is closed without ever starting. Nothing is recorded."
                        : "The encounter ends without a result. Turns already recorded stay in the history."
                }
                confirmLabel={view.status === "pending" ? "Discard encounter" : "Abort encounter"}
                pending={busy}
                onConfirm={() => run({ op: "abort" }, "Encounter closed")}
                onCancel={() => setConfirmAbort(false)}
            />
        </>
    )
}

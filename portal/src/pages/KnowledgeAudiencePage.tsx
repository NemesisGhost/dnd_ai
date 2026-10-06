import { useState } from "react"
import { Link, useParams } from "react-router"
import { knowledgeAudiencePath, runKnowledgeCommand } from "../api/knowledgeRuntime"
import { partiesPath } from "../api/parties"
import { fetchWorldEntities } from "../api/world"
import { useAnnounce } from "../components/authoring/announcer"
import { SelectField, TextAreaField, TextField } from "../components/authoring/fields"
import { MutationStatusMessage, StaleWriteNotice } from "../components/authoring/feedback"
import { ReferenceCombobox } from "../components/authoring/ReferenceCombobox"
import type { ReferenceOption } from "../components/authoring/ReferenceCombobox"
import { useSession } from "../context/SessionContext"
import { useAuthoringMutation } from "../hooks/useAuthoringMutation"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { useCampaignCapability } from "../hooks/useCampaignCapability"
import { usePageArrival } from "../hooks/usePageArrival"
import type { PartyList } from "../types/parties"
import type {
    KnowerAudience,
    KnowledgeAudience,
    KnowledgeCommand,
    KnowledgeRuntimeReceipt,
} from "../types/knowledgeRuntime"
import type { WorldCategory } from "../types/world"
import "../components/authoring/authoring.css"

const AWARENESS_LABEL: Readonly<Record<string, string>> = {
    aware: "Aware",
    rumored: "Has heard a rumor",
    suspected: "Suspects",
}

const METHOD_LABEL: Readonly<Record<string, string>> = {
    dialogue: "Conversation",
    written_message: "Written message",
    public_announcement: "Public announcement",
    rumor: "Rumor",
    telepathy: "Telepathy",
    magical_vision: "Magical vision",
    other: "Other",
}

const CODE_MESSAGE: Readonly<Record<string, string>> = {
    clock_required: "Set the campaign time first.",
    knower_invalid: "Choose a published character, NPC or organization.",
    knower_already_knows: "That knower already has this claim. Change their belief instead.",
    source_does_not_know: "The source does not know this claim.",
    knowledge_already_public: "This claim is already public at that location.",
    location_invalid: "Choose a published location.",
}

const choices = (values: readonly string[], labels: Readonly<Record<string, string>>) =>
    values.map((value) => ({ value, label: labels[value] ?? value }))

// /app/:campaignId/knowledge/:knowledgeItemId/audience — who knows this claim, and the
// explicit commands that change it. A belief never changes the claim's truth.
export function KnowledgeAudiencePage() {
    const { campaignId = "", knowledgeItemId = "" } = useParams()
    const { reload } = useSession()
    const announce = useAnnounce()
    const canEdit = useCampaignCapability(campaignId, "canon.edit")
    const { state, refetch } = useAuthoringResource<KnowledgeAudience>(
        knowledgeAudiencePath(campaignId, knowledgeItemId),
    )
    const parties = useAuthoringResource<PartyList>(partiesPath(campaignId))
    const headingRef = usePageArrival(state.kind === "ready")
    const [done, setDone] = useState<string | null>(null)
    const mutation = useAuthoringMutation<KnowledgeCommand, KnowledgeRuntimeReceipt>({
        scopeKey: `knowledge-audience:${knowledgeItemId}`,
        request: (command, ctx) => runKnowledgeCommand(campaignId, knowledgeItemId, command, ctx),
        onSuccess: async (receipt) => {
            const message = receipt.changed ? done : "Nothing changed"
            setDone(null)
            await refetch()
            if (message !== null) announce(message)
        },
    })
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const busy = mutation.status.kind === "pending"
    const explained = error?.code ? (CODE_MESSAGE[error.code] ?? null) : null
    const run = (command: KnowledgeCommand, message: string) => {
        setDone(message)
        mutation.submit(command)
    }

    async function searchWorld(
        categories: WorldCategory[],
        query: string,
        signal: AbortSignal,
    ): Promise<ReferenceOption[]> {
        const pages = await Promise.all(
            categories.map((category) =>
                fetchWorldEntities(campaignId, { category, query, limit: 10 }, signal),
            ),
        )
        return pages.flatMap((page) =>
            page.items.map((item) => ({
                id: item.entity_id,
                label: item.name,
                detail: item.category === "organization" ? "Organization" : item.category === "location" ? "Location" : "Character",
            })),
        )
    }

    return (
        <section className="authoring-page" aria-labelledby="knowledge-audience-heading">
            <p className="authoring-page__breadcrumb">
                <Link to={`/app/${encodeURIComponent(campaignId)}/knowledge`}>Knowledge</Link>
            </p>
            <h1 id="knowledge-audience-heading" ref={headingRef} tabIndex={-1}>
                Who knows this
            </h1>
            {!canEdit ? (
                <p role="alert">You do not have permission to manage who knows what.</p>
            ) : state.kind === "loading" ? (
                <p role="status">Loading…</p>
            ) : state.kind !== "ready" ? (
                <p role="alert">This claim does not exist, or you do not have access to it.</p>
            ) : (
                <>
                    <p>
                        <Link
                            to={`/app/${encodeURIComponent(campaignId)}/knowledge/${encodeURIComponent(knowledgeItemId)}/edit`}
                        >
                            Edit the claim
                        </Link>
                    </p>
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
                        <MutationStatusMessage
                            error={error}
                            onRetry={mutation.retry}
                            onCheckSession={reload}
                        />
                    ) : null}
                    <PartiesSection
                        audience={state.data}
                        parties={parties.state.kind === "ready" ? parties.state.data : null}
                        busy={busy}
                        run={run}
                    />
                    <KnowersSection
                        audience={state.data}
                        busy={busy}
                        run={run}
                        search={(query, signal) =>
                            searchWorld(["character", "organization"], query, signal)
                        }
                    />
                    <PublicSection
                        audience={state.data}
                        busy={busy}
                        run={run}
                        search={(query, signal) => searchWorld(["location"], query, signal)}
                    />
                </>
            )}
        </section>
    )
}

type Run = (command: KnowledgeCommand, message: string) => void

function PartiesSection({
    audience,
    parties,
    busy,
    run,
}: {
    audience: KnowledgeAudience
    parties: PartyList | null
    busy: boolean
    run: Run
}) {
    const [party, setParty] = useState("")
    const [awareness, setAwareness] = useState("aware")
    const [problem, setProblem] = useState<string | null>(null)
    const known = new Set(audience.parties.map((p) => p.party_id))
    const open = (parties?.items ?? []).filter(
        (p) => p.lifecycle_status === "active" && !known.has(p.party_id),
    )
    return (
        <section aria-labelledby="audience-parties">
            <h2 id="audience-parties">Parties</h2>
            {audience.parties.length === 0 ? (
                <p>No party knows this yet.</p>
            ) : (
                <ul className="authoring-choice-list">
                    {audience.parties.map((p) => (
                        <li key={p.party_knowledge_id}>
                            {p.party_name}: {AWARENESS_LABEL[p.awareness_level] ?? p.awareness_level}
                        </li>
                    ))}
                </ul>
            )}
            {open.length > 0 ? (
                <form
                    noValidate
                    aria-label="Tell a party"
                    className="authoring-form"
                    onSubmit={(event) => {
                        event.preventDefault()
                        if (party === "") {
                            setProblem("Choose a party.")
                            return
                        }
                        setProblem(null)
                        run({ op: "reveal", party_id: party, awareness_level: awareness }, "Party told")
                    }}
                >
                    <SelectField
                        id="reveal-party"
                        label="Party"
                        value={party}
                        placeholder="Choose a party"
                        required
                        error={problem}
                        options={open.map((p) => ({ value: p.party_id, label: p.name }))}
                        onChange={setParty}
                    />
                    <SelectField
                        id="reveal-awareness"
                        label="What the party learns"
                        value={awareness}
                        options={choices(audience.awareness_levels, AWARENESS_LABEL)}
                        onChange={setAwareness}
                    />
                    <button type="submit" className="authoring-button" disabled={busy}>
                        Tell party
                    </button>
                </form>
            ) : null}
        </section>
    )
}

function KnowersSection({
    audience,
    busy,
    run,
    search,
}: {
    audience: KnowledgeAudience
    busy: boolean
    run: Run
    search: (query: string, signal: AbortSignal) => Promise<ReferenceOption[]>
}) {
    const [who, setWho] = useState<ReferenceOption | null>(null)
    const [awareness, setAwareness] = useState("aware")
    const [confidence, setConfidence] = useState("")
    const [interpretation, setInterpretation] = useState("")
    const [problem, setProblem] = useState<string | null>(null)
    const [source, setSource] = useState("")
    const [recipient, setRecipient] = useState<ReferenceOption | null>(null)
    const [method, setMethod] = useState("dialogue")
    const [conveyed, setConveyed] = useState("")
    const [tellProblem, setTellProblem] = useState<string | null>(null)

    function learn() {
        const parsed = confidence.trim() === "" ? null : Number(confidence)
        if (who === null) {
            setProblem("Choose who learned it.")
            return
        }
        if (parsed !== null && (!Number.isInteger(parsed) || parsed < 0 || parsed > 100)) {
            setProblem("Confidence is a whole number from 0 to 100.")
            return
        }
        setProblem(null)
        run(
            {
                op: "learn",
                knower_entity_id: who.id,
                awareness_level: awareness,
                confidence: parsed,
                interpretation: interpretation.trim() === "" ? null : interpretation.trim(),
            },
            "Knowledge recorded",
        )
        setWho(null)
        setInterpretation("")
        setConfidence("")
    }

    return (
        <section aria-labelledby="audience-knowers">
            <h2 id="audience-knowers">Characters, NPCs and organizations</h2>
            {audience.knowers.length === 0 ? (
                <p>No one has recorded this yet.</p>
            ) : (
                audience.knowers.map((k) => (
                    <KnowerCard key={k.entity_knowledge_id} knower={k} audience={audience} busy={busy} run={run} />
                ))
            )}
            <form
                noValidate
                aria-label="Record that someone learned this"
                className="authoring-form"
                onSubmit={(event) => {
                    event.preventDefault()
                    learn()
                }}
            >
                <h3>Record that someone learned this</h3>
                <ReferenceCombobox
                    id="learn-who"
                    label="Who learned it"
                    hint="A character, NPC or organization."
                    value={who}
                    onChange={setWho}
                    search={search}
                    error={problem}
                    placeholder="Search"
                />
                <SelectField
                    id="learn-awareness"
                    label="How they hold it"
                    value={awareness}
                    options={choices(audience.awareness_levels, AWARENESS_LABEL)}
                    onChange={setAwareness}
                />
                <TextField id="learn-confidence" label="Confidence (0 to 100)" value={confidence} onChange={setConfidence} />
                <TextAreaField
                    id="learn-interpretation"
                    label="What they believe"
                    hint="Their own version, which may be wrong."
                    value={interpretation}
                    onChange={setInterpretation}
                />
                <button type="submit" className="authoring-button" disabled={busy}>
                    Record knowledge
                </button>
            </form>
            {audience.knowers.length > 0 ? (
                <form
                    noValidate
                    aria-label="Record that someone told another"
                    className="authoring-form"
                    onSubmit={(event) => {
                        event.preventDefault()
                        if (source === "" || recipient === null) {
                            setTellProblem("Choose who told and who was told.")
                            return
                        }
                        setTellProblem(null)
                        run(
                            {
                                op: "transfer",
                                source_entity_id: source,
                                recipient_entity_id: recipient.id,
                                transfer_method: method,
                                awareness_level: awareness,
                                modified_interpretation: conveyed.trim() === "" ? null : conveyed.trim(),
                            },
                            "Telling recorded",
                        )
                        setRecipient(null)
                        setConveyed("")
                    }}
                >
                    <h3>Record that someone told another</h3>
                    <SelectField
                        id="tell-source"
                        label="Who told"
                        value={source}
                        placeholder="Choose who told"
                        required
                        options={audience.knowers.map((k) => ({ value: k.knower_entity_id, label: k.knower_name }))}
                        onChange={setSource}
                    />
                    <ReferenceCombobox
                        id="tell-recipient"
                        label="Who was told"
                        value={recipient}
                        onChange={setRecipient}
                        search={search}
                        error={tellProblem}
                        placeholder="Search"
                    />
                    <SelectField
                        id="tell-method"
                        label="How"
                        value={method}
                        options={choices(audience.transfer_methods, METHOD_LABEL)}
                        onChange={setMethod}
                    />
                    <TextAreaField
                        id="tell-conveyed"
                        label="What was actually said"
                        hint="Leave empty when they heard it as the source believes it."
                        value={conveyed}
                        onChange={setConveyed}
                    />
                    <button type="submit" className="authoring-button" disabled={busy}>
                        Record telling
                    </button>
                </form>
            ) : null}
        </section>
    )
}

function KnowerCard({
    knower,
    audience,
    busy,
    run,
}: {
    knower: KnowerAudience
    audience: KnowledgeAudience
    busy: boolean
    run: Run
}) {
    const [editing, setEditing] = useState(false)
    const [awareness, setAwareness] = useState(knower.awareness_level)
    const [confidence, setConfidence] = useState(knower.confidence === null ? "" : String(knower.confidence))
    const [interpretation, setInterpretation] = useState(knower.interpretation ?? "")
    const [problem, setProblem] = useState<string | null>(null)

    function save() {
        const parsed = confidence.trim() === "" ? null : Number(confidence)
        if (parsed !== null && (!Number.isInteger(parsed) || parsed < 0 || parsed > 100)) {
            setProblem("Confidence is a whole number from 0 to 100.")
            return
        }
        setProblem(null)
        run(
            {
                op: "belief",
                entity_knowledge_id: knower.entity_knowledge_id,
                expected_last_event_id: knower.last_event_id,
                changes: {
                    awareness_level: awareness,
                    confidence: parsed,
                    interpretation: interpretation.trim() === "" ? null : interpretation.trim(),
                },
            },
            "Belief changed",
        )
        setEditing(false)
    }

    return (
        <article className="authoring-card" aria-label={`Belief of ${knower.knower_name}`}>
            <h3>{knower.knower_name}</h3>
            <p>
                {AWARENESS_LABEL[knower.awareness_level] ?? knower.awareness_level}
                {knower.confidence !== null ? `, ${knower.confidence}% sure` : ""}
            </p>
            {knower.interpretation !== null ? <p>{knower.interpretation}</p> : null}
            <button type="button" className="authoring-button" onClick={() => setEditing(!editing)}>
                {editing ? "Cancel" : `Change belief of ${knower.knower_name}`}
            </button>
            {editing ? (
                <form
                    noValidate
                    aria-label={`Change belief of ${knower.knower_name}`}
                    className="authoring-form"
                    onSubmit={(event) => {
                        event.preventDefault()
                        save()
                    }}
                >
                    <SelectField
                        id={`b-awareness-${knower.entity_knowledge_id}`}
                        label="How they hold it"
                        value={awareness}
                        options={choices(audience.awareness_levels, AWARENESS_LABEL)}
                        onChange={setAwareness}
                    />
                    <TextField
                        id={`b-confidence-${knower.entity_knowledge_id}`}
                        label="Confidence (0 to 100)"
                        value={confidence}
                        onChange={setConfidence}
                        error={problem}
                    />
                    <TextAreaField
                        id={`b-interpretation-${knower.entity_knowledge_id}`}
                        label="What they believe"
                        value={interpretation}
                        onChange={setInterpretation}
                    />
                    <button type="submit" className="authoring-button" disabled={busy}>
                        Save belief
                    </button>
                </form>
            ) : null}
        </article>
    )
}

function PublicSection({
    audience,
    busy,
    run,
    search,
}: {
    audience: KnowledgeAudience
    busy: boolean
    run: Run
    search: (query: string, signal: AbortSignal) => Promise<ReferenceOption[]>
}) {
    const [place, setPlace] = useState<ReferenceOption | null>(null)
    const [awareness, setAwareness] = useState("aware")
    const [problem, setProblem] = useState<string | null>(null)
    return (
        <section aria-labelledby="audience-public">
            <h2 id="audience-public">Public places</h2>
            {audience.public.length === 0 ? (
                <p>Not public anywhere yet.</p>
            ) : (
                <ul className="authoring-choice-list">
                    {audience.public.map((p) => (
                        <li key={p.public_knowledge_id}>
                            {p.location_name}: {AWARENESS_LABEL[p.awareness_level] ?? p.awareness_level}
                        </li>
                    ))}
                </ul>
            )}
            <form
                noValidate
                aria-label="Make this public"
                className="authoring-form"
                onSubmit={(event) => {
                    event.preventDefault()
                    if (place === null) {
                        setProblem("Choose a location.")
                        return
                    }
                    setProblem(null)
                    run({ op: "public", location_id: place.id, awareness_level: awareness }, "Made public")
                    setPlace(null)
                }}
            >
                <ReferenceCombobox
                    id="public-place"
                    label="Location"
                    value={place}
                    onChange={setPlace}
                    search={search}
                    error={problem}
                    placeholder="Search"
                />
                <SelectField
                    id="public-awareness"
                    label="How it is known there"
                    value={awareness}
                    options={choices(audience.awareness_levels, AWARENESS_LABEL)}
                    onChange={setAwareness}
                />
                <button type="submit" className="authoring-button" disabled={busy}>
                    Make public
                </button>
            </form>
        </section>
    )
}

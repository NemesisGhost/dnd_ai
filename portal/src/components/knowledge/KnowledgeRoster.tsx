import { useState } from "react"
import { knowledgeAudiencePath, runKnowledgeCommand } from "../../api/knowledgeRuntime"
import { partiesPath } from "../../api/parties"
import { fetchWorldEntities } from "../../api/world"
import { useSession } from "../../context/SessionContext"
import { useAuthoringMutation } from "../../hooks/useAuthoringMutation"
import { useAuthoringResource } from "../../hooks/useAuthoringResource"
import { useCampaignCapability } from "../../hooks/useCampaignCapability"
import type { PartyList } from "../../types/parties"
import type {
    KnowerAudience,
    KnowledgeAudience,
    KnowledgeCommand,
    KnowledgeRuntimeReceipt,
} from "../../types/knowledgeRuntime"
import type { WorldCategory } from "../../types/world"
import { humanizeCode } from "../../utils/humanize"
import { useAnnounce } from "../authoring/announcer"
import { SelectField, TextAreaField, TextField } from "../authoring/fields"
import { MutationStatusMessage, StaleWriteNotice } from "../authoring/feedback"
import { ReferenceCombobox } from "../authoring/ReferenceCombobox"
import type { ReferenceOption } from "../authoring/ReferenceCombobox"
import "../authoring/authoring.css"

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

type Kind = "party" | "learn" | "transfer" | "public" | "belief"
type Group = "parties" | "knowers" | "public"
const GROUP_OF: Readonly<Record<Kind, Group>> = {
    party: "parties",
    learn: "knowers",
    transfer: "knowers",
    belief: "knowers",
    public: "public",
}

type Run = (command: KnowledgeCommand, kind: Kind, message: string, belief?: string) => void

function parseConfidence(value: string): number | null | undefined {
    if (value.trim() === "") return null
    const parsed = Number(value)
    return Number.isInteger(parsed) && parsed >= 0 && parsed <= 100 ? parsed : undefined
}

const stateText = (awareness: string, confidence: number | null): string =>
    `${AWARENESS_LABEL[awareness] ?? humanizeCode(awareness)}${confidence !== null ? `, ${confidence}% sure` : ""}`

// "Who knows this": a compact roster of the parties, individuals and public places that hold
// this claim, with each group's actions beside its heading. Only people who can edit canon can
// read or change it (the audience endpoint requires it), so nobody else gets a request or any of
// its content. Every action saves on its own and refreshes only this roster: it never touches an
// unsaved claim edit, and a failed action keeps the form (and what was typed) open.
export function KnowledgeRoster({
    campaignId,
    knowledgeItemId,
}: {
    campaignId: string
    knowledgeItemId: string
}) {
    const canManage = useCampaignCapability(campaignId, "canon.edit")
    if (!canManage) return null
    return <RosterBody campaignId={campaignId} knowledgeItemId={knowledgeItemId} />
}

function RosterBody({ campaignId, knowledgeItemId }: { campaignId: string; knowledgeItemId: string }) {
    const { reload } = useSession()
    const announce = useAnnounce()
    const { state, refetch } = useAuthoringResource<KnowledgeAudience>(
        knowledgeAudiencePath(campaignId, knowledgeItemId),
    )
    const parties = useAuthoringResource<PartyList>(partiesPath(campaignId))
    const [open, setOpen] = useState<Kind | null>(null)
    const [openKnower, setOpenKnower] = useState<string | null>(null)
    const [inflight, setInflight] = useState<{ kind: Kind; message: string } | null>(null)

    const mutation = useAuthoringMutation<KnowledgeCommand, KnowledgeRuntimeReceipt>({
        scopeKey: `knowledge-audience:${knowledgeItemId}`,
        request: (command, ctx) => runKnowledgeCommand(campaignId, knowledgeItemId, command, ctx),
        onSuccess: async (receipt) => {
            const finished = inflight
            setInflight(null)
            if (finished?.kind === "belief") setOpenKnower(null)
            else setOpen(null)
            await refetch()
            announce(receipt.changed ? (finished?.message ?? "Saved") : "Nothing changed")
        },
    })
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const busy = mutation.status.kind === "pending"
    const explained = error?.code ? (CODE_MESSAGE[error.code] ?? null) : null
    const failedGroup = error !== null && inflight !== null ? GROUP_OF[inflight.kind] : null

    const run: Run = (command, kind, message) => {
        setInflight({ kind, message })
        mutation.submit(command)
    }

    const notice = (group: Group) =>
        failedGroup !== group || error === null ? null : error.kind === "stale" ? (
            <StaleWriteNotice
                onLoadLatest={() => {
                    mutation.reset()
                    void refetch()
                }}
            />
        ) : explained !== null ? (
            <p role="alert">{explained}</p>
        ) : (
            <MutationStatusMessage error={error} onRetry={mutation.retry} onCheckSession={reload} />
        )

    async function searchWorld(
        categories: WorldCategory[],
        query: string,
        signal: AbortSignal,
    ): Promise<ReferenceOption[]> {
        const pages = await Promise.all(
            categories.map((category) => fetchWorldEntities(campaignId, { category, query, limit: 10 }, signal)),
        )
        return pages.flatMap((page) =>
            page.items.map((item) => ({
                id: item.entity_id,
                label: item.name,
                detail:
                    item.category === "organization"
                        ? "Organization"
                        : item.category === "location"
                          ? "Location"
                          : "Character",
            })),
        )
    }

    if (state.kind === "loading") return <p role="status">Loading who knows this…</p>
    // Absent for anyone who may not read it: no heading, no message that it exists.
    if (state.kind === "denied" || state.kind === "unavailable") return null
    if (state.kind === "error") return <p role="alert">Who knows this could not be loaded. Try reloading the page.</p>

    const audience = state.data
    const known = new Set(audience.parties.map((p) => p.party_id))
    const openParties = (parties.state.kind === "ready" ? parties.state.data.items : []).filter(
        (p) => p.lifecycle_status === "active" && !known.has(p.party_id),
    )
    const toggle = (kind: Kind) => setOpen(open === kind ? null : kind)

    return (
        <section id="who-knows" className="knowledge-section" aria-labelledby="who-knows-heading">
            <h2 id="who-knows-heading" tabIndex={-1}>
                Who knows this
            </h2>
            <p className="knowledge-roster__lead">Recorded separately from the claim. Changes here save on their own.</p>

            <div className="knowledge-roster__group">
                <div className="knowledge-roster__head">
                    <h3>Parties</h3>
                    {openParties.length > 0 ? (
                        <button
                            type="button"
                            className="authoring-button"
                            aria-expanded={open === "party"}
                            onClick={() => toggle("party")}
                        >
                            Tell a party
                        </button>
                    ) : null}
                </div>
                {open === "party" ? (
                    <PartyForm
                        audience={audience}
                        parties={openParties}
                        busy={busy}
                        run={run}
                        onCancel={() => setOpen(null)}
                    />
                ) : null}
                {notice("parties")}
                {audience.parties.length === 0 ? (
                    <p className="knowledge-roster__empty">No party knows this yet.</p>
                ) : (
                    <ul className="knowledge-roster__list">
                        {audience.parties.map((p) => (
                            <li key={p.party_knowledge_id} className="knowledge-roster__row">
                                <span className="knowledge-roster__name">{p.party_name}</span>
                                <span className="knowledge-roster__state">
                                    {AWARENESS_LABEL[p.awareness_level] ?? humanizeCode(p.awareness_level)}
                                </span>
                            </li>
                        ))}
                    </ul>
                )}
            </div>

            <div className="knowledge-roster__group">
                <div className="knowledge-roster__head">
                    <h3>Characters, NPCs and organizations</h3>
                    <div className="knowledge-roster__actions">
                        <button
                            type="button"
                            className="authoring-button"
                            aria-expanded={open === "learn"}
                            onClick={() => toggle("learn")}
                        >
                            Record who learned this
                        </button>
                        {audience.knowers.length > 0 ? (
                            <button
                                type="button"
                                className="authoring-button"
                                aria-expanded={open === "transfer"}
                                onClick={() => toggle("transfer")}
                            >
                                Record a telling
                            </button>
                        ) : null}
                    </div>
                </div>
                {open === "learn" ? (
                    <LearnForm
                        audience={audience}
                        busy={busy}
                        run={run}
                        search={(query, signal) => searchWorld(["character", "organization"], query, signal)}
                        onCancel={() => setOpen(null)}
                    />
                ) : null}
                {open === "transfer" ? (
                    <TellForm
                        audience={audience}
                        busy={busy}
                        run={run}
                        search={(query, signal) => searchWorld(["character", "organization"], query, signal)}
                        onCancel={() => setOpen(null)}
                    />
                ) : null}
                {notice("knowers")}
                {audience.knowers.length === 0 ? (
                    <p className="knowledge-roster__empty">No one has recorded this yet.</p>
                ) : (
                    <ul className="knowledge-roster__list">
                        {audience.knowers.map((k) => (
                            <KnowerRow
                                key={k.entity_knowledge_id}
                                knower={k}
                                audience={audience}
                                expanded={openKnower === k.entity_knowledge_id}
                                onToggle={() =>
                                    setOpenKnower(openKnower === k.entity_knowledge_id ? null : k.entity_knowledge_id)
                                }
                                busy={busy}
                                run={run}
                            />
                        ))}
                    </ul>
                )}
            </div>

            <div className="knowledge-roster__group">
                <div className="knowledge-roster__head">
                    <h3>Public places</h3>
                    <button
                        type="button"
                        className="authoring-button"
                        aria-expanded={open === "public"}
                        onClick={() => toggle("public")}
                    >
                        Make public
                    </button>
                </div>
                {open === "public" ? (
                    <PublicForm
                        audience={audience}
                        busy={busy}
                        run={run}
                        search={(query, signal) => searchWorld(["location"], query, signal)}
                        onCancel={() => setOpen(null)}
                    />
                ) : null}
                {notice("public")}
                {audience.public.length === 0 ? (
                    <p className="knowledge-roster__empty">Not public anywhere yet.</p>
                ) : (
                    <ul className="knowledge-roster__list">
                        {audience.public.map((p) => (
                            <li key={p.public_knowledge_id} className="knowledge-roster__row">
                                <span className="knowledge-roster__name">{p.location_name}</span>
                                <span className="knowledge-roster__state">
                                    {AWARENESS_LABEL[p.awareness_level] ?? humanizeCode(p.awareness_level)}
                                </span>
                            </li>
                        ))}
                    </ul>
                )}
            </div>
        </section>
    )
}

function FormButtons({ busy, label, onCancel }: { busy: boolean; label: string; onCancel: () => void }) {
    return (
        <div className="authoring-actions">
            <button type="submit" className="authoring-button authoring-button--primary" disabled={busy}>
                {label}
            </button>
            <button type="button" className="authoring-button" disabled={busy} onClick={onCancel}>
                Cancel
            </button>
        </div>
    )
}

function PartyForm({
    audience,
    parties,
    busy,
    run,
    onCancel,
}: {
    audience: KnowledgeAudience
    parties: PartyList["items"]
    busy: boolean
    run: Run
    onCancel: () => void
}) {
    const [party, setParty] = useState("")
    const [awareness, setAwareness] = useState("aware")
    const [problem, setProblem] = useState<string | null>(null)
    return (
        <form
            noValidate
            aria-label="Tell a party"
            className="authoring-form knowledge-roster__form"
            onSubmit={(event) => {
                event.preventDefault()
                if (party === "") {
                    setProblem("Choose a party.")
                    return
                }
                setProblem(null)
                run({ op: "reveal", party_id: party, awareness_level: awareness }, "party", "Party told")
            }}
        >
            <SelectField
                id="reveal-party"
                label="Party"
                value={party}
                placeholder="Choose a party"
                required
                error={problem}
                options={parties.map((p) => ({ value: p.party_id, label: p.name }))}
                onChange={setParty}
            />
            <SelectField
                id="reveal-awareness"
                label="What the party learns"
                value={awareness}
                options={choices(audience.awareness_levels, AWARENESS_LABEL)}
                onChange={setAwareness}
            />
            <FormButtons busy={busy} label="Tell party" onCancel={onCancel} />
        </form>
    )
}

function LearnForm({
    audience,
    busy,
    run,
    search,
    onCancel,
}: {
    audience: KnowledgeAudience
    busy: boolean
    run: Run
    search: (query: string, signal: AbortSignal) => Promise<ReferenceOption[]>
    onCancel: () => void
}) {
    const [who, setWho] = useState<ReferenceOption | null>(null)
    const [awareness, setAwareness] = useState("aware")
    const [confidence, setConfidence] = useState("")
    const [interpretation, setInterpretation] = useState("")
    const [problem, setProblem] = useState<string | null>(null)
    return (
        <form
            noValidate
            aria-label="Record that someone learned this"
            className="authoring-form knowledge-roster__form"
            onSubmit={(event) => {
                event.preventDefault()
                const parsed = parseConfidence(confidence)
                if (who === null) {
                    setProblem("Choose who learned it.")
                    return
                }
                if (parsed === undefined) {
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
                    "learn",
                    "Knowledge recorded",
                )
            }}
        >
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
            <FormButtons busy={busy} label="Record knowledge" onCancel={onCancel} />
        </form>
    )
}

function TellForm({
    audience,
    busy,
    run,
    search,
    onCancel,
}: {
    audience: KnowledgeAudience
    busy: boolean
    run: Run
    search: (query: string, signal: AbortSignal) => Promise<ReferenceOption[]>
    onCancel: () => void
}) {
    const [source, setSource] = useState("")
    const [recipient, setRecipient] = useState<ReferenceOption | null>(null)
    const [method, setMethod] = useState("dialogue")
    const [awareness, setAwareness] = useState("aware")
    const [conveyed, setConveyed] = useState("")
    const [problem, setProblem] = useState<string | null>(null)
    return (
        <form
            noValidate
            aria-label="Record that someone told another"
            className="authoring-form knowledge-roster__form"
            onSubmit={(event) => {
                event.preventDefault()
                if (source === "" || recipient === null) {
                    setProblem("Choose who told and who was told.")
                    return
                }
                setProblem(null)
                run(
                    {
                        op: "transfer",
                        source_entity_id: source,
                        recipient_entity_id: recipient.id,
                        transfer_method: method,
                        awareness_level: awareness,
                        modified_interpretation: conveyed.trim() === "" ? null : conveyed.trim(),
                    },
                    "transfer",
                    "Telling recorded",
                )
            }}
        >
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
                error={problem}
                placeholder="Search"
            />
            <SelectField
                id="tell-method"
                label="How"
                value={method}
                options={choices(audience.transfer_methods, METHOD_LABEL)}
                onChange={setMethod}
            />
            <SelectField
                id="tell-awareness"
                label="How they hold it"
                value={awareness}
                options={choices(audience.awareness_levels, AWARENESS_LABEL)}
                onChange={setAwareness}
            />
            <TextAreaField
                id="tell-conveyed"
                label="What was actually said"
                hint="Leave empty when they heard it as the source believes it."
                value={conveyed}
                onChange={setConveyed}
            />
            <FormButtons busy={busy} label="Record telling" onCancel={onCancel} />
        </form>
    )
}

function PublicForm({
    audience,
    busy,
    run,
    search,
    onCancel,
}: {
    audience: KnowledgeAudience
    busy: boolean
    run: Run
    search: (query: string, signal: AbortSignal) => Promise<ReferenceOption[]>
    onCancel: () => void
}) {
    const [place, setPlace] = useState<ReferenceOption | null>(null)
    const [awareness, setAwareness] = useState("aware")
    const [problem, setProblem] = useState<string | null>(null)
    return (
        <form
            noValidate
            aria-label="Make this public"
            className="authoring-form knowledge-roster__form"
            onSubmit={(event) => {
                event.preventDefault()
                if (place === null) {
                    setProblem("Choose a location.")
                    return
                }
                setProblem(null)
                run({ op: "public", location_id: place.id, awareness_level: awareness }, "public", "Made public")
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
            <FormButtons busy={busy} label="Make public" onCancel={onCancel} />
        </form>
    )
}

function KnowerRow({
    knower,
    audience,
    expanded,
    onToggle,
    busy,
    run,
}: {
    knower: KnowerAudience
    audience: KnowledgeAudience
    expanded: boolean
    onToggle: () => void
    busy: boolean
    run: Run
}) {
    const [awareness, setAwareness] = useState(knower.awareness_level)
    const [confidence, setConfidence] = useState(knower.confidence === null ? "" : String(knower.confidence))
    const [interpretation, setInterpretation] = useState(knower.interpretation ?? "")
    const [problem, setProblem] = useState<string | null>(null)
    const panelId = `knower-${knower.entity_knowledge_id}`

    return (
        <li className="knowledge-roster__row knowledge-roster__row--knower" aria-label={knower.knower_name}>
            <span className="knowledge-roster__name">
                {knower.knower_name}{" "}
                <span className="knowledge-roster__type">{humanizeCode(knower.knower_type)}</span>
            </span>
            <span className="knowledge-roster__state">{stateText(knower.awareness_level, knower.confidence)}</span>
            <button
                type="button"
                className="authoring-button knowledge-roster__toggle"
                aria-expanded={expanded}
                aria-controls={panelId}
                aria-label={`Details for ${knower.knower_name}`}
                onClick={onToggle}
            >
                {expanded ? "Hide" : "Details"}
            </button>
            {expanded ? (
                <div id={panelId} className="knowledge-roster__details">
                    {knower.interpretation !== null ? (
                        <p>
                            <strong>Believes:</strong> {knower.interpretation}
                        </p>
                    ) : null}
                    <p>{knower.willing_to_share ? "Willing to share." : "Not willing to share."}</p>
                    <form
                        noValidate
                        aria-label={`Change belief of ${knower.knower_name}`}
                        className="authoring-form"
                        onSubmit={(event) => {
                            event.preventDefault()
                            const parsed = parseConfidence(confidence)
                            if (parsed === undefined) {
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
                                "belief",
                                "Belief changed",
                            )
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
                        <div className="authoring-actions">
                            <button type="submit" className="authoring-button authoring-button--primary" disabled={busy}>
                                Save belief
                            </button>
                        </div>
                    </form>
                </div>
            ) : null}
        </li>
    )
}

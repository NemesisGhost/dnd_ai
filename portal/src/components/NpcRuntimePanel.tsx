import { useState } from "react"
import { npcAuthoringPath } from "../api/npcAuthoring"
import { npcRuntimeOptionsPath } from "../api/npcPortrayal"
import { apiRequest } from "../api/http"
import { recordTravel } from "../api/travel"
import { fetchWorldEntities } from "../api/world"
import { useSession } from "../context/SessionContext"
import { useAuthoringMutation } from "../hooks/useAuthoringMutation"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import { useCampaignCapability } from "../hooks/useCampaignCapability"
import type { CharacterDetail } from "../types/character"
import type { NpcAuthoringView } from "../types/npcAuthoring"
import type { RuntimeOptions } from "../types/npcPortrayal"
import { useAnnounce } from "./authoring/announcer"
import { SelectField, TextField } from "./authoring/fields"
import { MutationStatusMessage } from "./authoring/feedback"
import { ReferenceCombobox } from "./authoring/ReferenceCombobox"
import type { ReferenceOption } from "./authoring/ReferenceCombobox"
import { WorldTimePicker } from "./authoring/WorldTimePicker"
import "./authoring/authoring.css"

interface Props {
    campaignId: string
    characterId: string
}

type Command =
    | { op: "hp"; delta: number }
    | { op: "add_condition"; conditionId: string; source: string | null }
    | { op: "remove_condition"; conditionId: string }
    | { op: "resource"; resourceId: string; delta: number }
    | { op: "move"; destination: string }

const CODE_MESSAGE: Readonly<Record<string, string>> = {
    travel_invalid: "Choose a published destination.",
    travel_time_invalid: "Choose a time after this NPC arrived where they are.",
    clock_required: "Choose a time.",
}

const humanize = (code: string): string => code.replace(/_/g, " ")

// GM controls for a published NPC: hit points, conditions, resources and location, each one
// idempotent command that records an event at the chosen time. The routes are the same ones the
// character-state adapters use; this panel only gives a human GM a way to reach them.
export function NpcRuntimePanel({ campaignId, characterId }: Props) {
    if (!useCampaignCapability(campaignId, "canon.edit")) return null
    return <Loaded campaignId={campaignId} characterId={characterId} />
}

function Loaded({ campaignId, characterId }: Props) {
    const npc = useAuthoringResource<NpcAuthoringView>(npcAuthoringPath(campaignId, characterId))
    const options = useAuthoringResource<RuntimeOptions>(npcRuntimeOptionsPath(campaignId))
    const character = useAuthoringResource<CharacterDetail>(
        `/campaigns/${encodeURIComponent(campaignId)}/characters/${encodeURIComponent(characterId)}`,
    )
    if (npc.state.kind !== "ready" || options.state.kind !== "ready" || character.state.kind !== "ready") {
        return null
    }
    if (npc.state.data.canon_status !== "canon") {
        return (
            <section className="authoring-aside" aria-labelledby="npc-runtime-heading">
                <h2 id="npc-runtime-heading">Run this NPC</h2>
                <p>Publish this NPC to change their hit points, conditions, resources or location.</p>
            </section>
        )
    }
    return (
        <Panel
            campaignId={campaignId}
            characterId={characterId}
            options={options.state.data}
            detail={character.state.data}
            refetch={character.refetch}
        />
    )
}

function Panel({
    campaignId,
    characterId,
    options,
    detail,
    refetch,
}: Props & { options: RuntimeOptions; detail: CharacterDetail; refetch: () => Promise<void> }) {
    const { reload } = useSession()
    const announce = useAnnounce()
    const base = `/campaigns/${encodeURIComponent(campaignId)}/characters/${encodeURIComponent(characterId)}`
    const [when, setWhen] = useState("")
    const [delta, setDelta] = useState("")
    const [condition, setCondition] = useState("")
    const [source, setSource] = useState("")
    const [resource, setResource] = useState("")
    const [resourceDelta, setResourceDelta] = useState("")
    const [destination, setDestination] = useState<ReferenceOption | null>(null)
    const [problem, setProblem] = useState<string | null>(null)
    const [done, setDone] = useState<string | null>(null)

    const mutation = useAuthoringMutation<Command, unknown>({
        scopeKey: `npc-runtime:${characterId}`,
        request: (command, ctx) => {
            const body = { world_time_id: when === "" ? null : when }
            switch (command.op) {
                case "hp":
                    return apiRequest("POST", `${base}/hit-points`, {
                        body: { ...body, delta: command.delta },
                        ...ctx,
                    })
                case "add_condition":
                    return apiRequest("POST", `${base}/conditions`, {
                        body: { ...body, condition_id: command.conditionId, source_description: command.source },
                        ...ctx,
                    })
                case "remove_condition":
                    return apiRequest("POST", `${base}/conditions/${encodeURIComponent(command.conditionId)}/remove`, {
                        body,
                        ...ctx,
                    })
                case "resource":
                    return apiRequest("POST", `${base}/resources`, {
                        body: { ...body, resource_definition_id: command.resourceId, delta: command.delta },
                        ...ctx,
                    })
                case "move":
                    return recordTravel(
                        campaignId,
                        {
                            destination_location_id: command.destination,
                            character_ids: [characterId],
                            party_id: null,
                            route_id: null,
                            ...(when === "" ? {} : { world_time_id: when }),
                        },
                        ctx,
                    )
            }
        },
        onSuccess: async () => {
            const message = done
            setDone(null)
            setDelta("")
            setResourceDelta("")
            setSource("")
            await refetch()
            if (message !== null) announce(message)
        },
    })
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const explained = error?.code ? (CODE_MESSAGE[error.code] ?? null) : null
    const busy = mutation.status.kind === "pending"
    const run = (command: Command, message: string) => {
        if (when === "") {
            setProblem("Choose when this happens first.")
            return
        }
        setProblem(null)
        setDone(message)
        mutation.submit(command)
    }

    const integer = (value: string): number | null => {
        const parsed = Number(value)
        return value.trim() !== "" && Number.isInteger(parsed) && parsed !== 0 ? parsed : null
    }

    async function searchPlaces(query: string, signal: AbortSignal): Promise<ReferenceOption[]> {
        const page = await fetchWorldEntities(campaignId, { category: "location", query, limit: 10 }, signal)
        return page.items.map((item) => ({
            id: item.entity_id,
            label: item.name,
            detail: humanize(item.entity_type_code),
        }))
    }

    const conditionByCode = new Map(options.conditions.map((c) => [c.code, c]))
    return (
        <section className="authoring-aside" aria-labelledby="npc-runtime-heading">
            <h2 id="npc-runtime-heading">Run this NPC</h2>
            {explained !== null ? (
                <p role="alert">{explained}</p>
            ) : error !== null ? (
                <MutationStatusMessage error={error} onRetry={mutation.retry} onCheckSession={reload} />
            ) : null}
            <WorldTimePicker
                campaignId={campaignId}
                id="npc-runtime-when"
                label="When this happens"
                value={when}
                onChange={setWhen}
                error={problem}
            />

            <h3>Hit points</h3>
            <p>
                {detail.current_hit_points === null
                    ? "Not tracked yet."
                    : `${detail.current_hit_points} of ${detail.maximum_hit_points ?? "?"}`}
            </p>
            <form
                noValidate
                aria-label="Adjust hit points"
                className="authoring-form"
                onSubmit={(event) => {
                    event.preventDefault()
                    const value = integer(delta)
                    if (value === null) {
                        setProblem("Enter a whole number other than zero, such as -5 for damage.")
                        return
                    }
                    run({ op: "hp", delta: value }, "Hit points changed")
                }}
            >
                <TextField id="npc-hp-delta" label="Change (negative for damage)" value={delta} onChange={setDelta} />
                <button type="submit" className="authoring-button" disabled={busy}>
                    Apply hit point change
                </button>
            </form>

            <h3>Conditions</h3>
            {(detail.conditions ?? []).length === 0 ? <p>None.</p> : null}
            <ul className="authoring-choice-list">
                {(detail.conditions ?? []).map((c) => {
                    const known = conditionByCode.get(c.condition_code)
                    return (
                        <li key={c.condition_code}>
                            {humanize(c.condition_code)}
                            {c.source_description !== null ? ` (${c.source_description})` : ""}{" "}
                            {known !== undefined ? (
                                <button
                                    type="button"
                                    className="authoring-button"
                                    disabled={busy}
                                    onClick={() =>
                                        run({ op: "remove_condition", conditionId: known.value }, "Condition removed")
                                    }
                                >
                                    Remove {known.label}
                                </button>
                            ) : null}
                        </li>
                    )
                })}
            </ul>
            <form
                noValidate
                aria-label="Add a condition"
                className="authoring-form"
                onSubmit={(event) => {
                    event.preventDefault()
                    if (condition === "") {
                        setProblem("Choose a condition.")
                        return
                    }
                    run(
                        {
                            op: "add_condition",
                            conditionId: condition,
                            source: source.trim() === "" ? null : source.trim(),
                        },
                        "Condition added",
                    )
                }}
            >
                <SelectField
                    id="npc-condition"
                    label="Condition"
                    value={condition}
                    placeholder="Choose a condition"
                    options={options.conditions}
                    onChange={setCondition}
                />
                <TextField id="npc-condition-source" label="Source (optional)" value={source} onChange={setSource} />
                <button type="submit" className="authoring-button" disabled={busy}>
                    Add condition
                </button>
            </form>

            <h3>Resources</h3>
            {(detail.resources ?? []).length === 0 ? <p>None tracked.</p> : null}
            <ul className="authoring-choice-list">
                {(detail.resources ?? []).map((r) => (
                    <li key={r.resource_code}>
                        {humanize(r.resource_code)}: {r.current_amount} of {r.maximum_amount}
                    </li>
                ))}
            </ul>
            <form
                noValidate
                aria-label="Adjust a resource"
                className="authoring-form"
                onSubmit={(event) => {
                    event.preventDefault()
                    const value = integer(resourceDelta)
                    if (resource === "" || value === null) {
                        setProblem("Choose a resource and a whole number other than zero.")
                        return
                    }
                    run({ op: "resource", resourceId: resource, delta: value }, "Resource changed")
                }}
            >
                <SelectField
                    id="npc-resource"
                    label="Resource"
                    value={resource}
                    placeholder="Choose a resource"
                    options={options.resources}
                    onChange={setResource}
                />
                <TextField
                    id="npc-resource-delta"
                    label="Change (negative to spend)"
                    value={resourceDelta}
                    onChange={setResourceDelta}
                />
                <button type="submit" className="authoring-button" disabled={busy}>
                    Adjust resource
                </button>
            </form>

            <h3>Location</h3>
            <form
                noValidate
                aria-label="Move this NPC"
                className="authoring-form"
                onSubmit={(event) => {
                    event.preventDefault()
                    if (destination === null) {
                        setProblem("Choose a destination.")
                        return
                    }
                    run({ op: "move", destination: destination.id }, "NPC moved")
                    setDestination(null)
                }}
            >
                <ReferenceCombobox
                    id="npc-destination"
                    label="Move to"
                    value={destination}
                    onChange={setDestination}
                    search={searchPlaces}
                    placeholder="Search places"
                />
                <button type="submit" className="authoring-button" disabled={busy}>
                    Move NPC
                </button>
            </form>
        </section>
    )
}

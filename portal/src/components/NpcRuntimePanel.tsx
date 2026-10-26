import { useState } from "react"
import { Link } from "react-router"
import { npcRuntimeOptionsPath } from "../api/npcPortrayal"
import { apiRequest } from "../api/http"
import { recordTravel } from "../api/travel"
import { fetchWorldEntities } from "../api/world"
import { useSession } from "../context/SessionContext"
import { useAuthoringMutation } from "../hooks/useAuthoringMutation"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import type { RefetchOutcome } from "../hooks/useAuthoringResource"
import { useConfirmedRefresh } from "../hooks/useConfirmedRefresh"
import { useCampaignCapability } from "../hooks/useCampaignCapability"
import type { CharacterDetail } from "../types/character"
import type { RuntimeOptions } from "../types/npcPortrayal"
import { useAnnounce } from "./authoring/announcer"
import { SelectField, TextField } from "./authoring/fields"
import { MutationStatusMessage } from "./authoring/feedback"
import { ReferenceCombobox } from "./authoring/ReferenceCombobox"
import type { ReferenceOption } from "./authoring/ReferenceCombobox"
import { WorldTimePicker } from "./authoring/WorldTimePicker"
import "./authoring/authoring.css"
import { PanelFrame } from "./DetailPanel"
import { StaleReadNotice } from "./StaleReadNotice"
import { useKeptData, useRefetchOnChange } from "../hooks/useKeptData"

interface Props {
    campaignId: string
    characterId: string
    // A staged section already supplies the surface and the heading: render the content only.
    embedded?: boolean
    // Changes when the record's status changed elsewhere on the page (publishing, restoring), so
    // eligibility is read again without remounting the panel.
    refreshToken?: unknown
    // Called after a command took effect, so the page's own view of the character agrees.
    onChanged?: () => void
    // What the page already knows, from its own successful read of the record's status: the reason
    // the commands are not offered (not published, archived, replaced), or `null` when it knows the
    // record takes them. It wins over this panel's own read, which may be a retained one after a
    // failed refresh. Absent (`undefined`) when the page does not know, and the panel's read decides.
    blockedText?: string | null
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
    character_state_not_initialized:
        "This NPC has no starting hit points yet. Set their starting state first, then change their hit points.",
}

const humanize = (code: string): string => code.replace(/_/g, " ")

// GM controls for a published NPC: hit points, conditions, resources and location, each one
// idempotent command that records an event at the chosen time. The routes are the same ones the
// character-state adapters use; this panel only gives a human GM a way to reach them.
export function NpcRuntimePanel({ campaignId, characterId, embedded, refreshToken, onChanged, blockedText }: Props) {
    if (!useCampaignCapability(campaignId, "canon.edit")) return null
    return (
        <Loaded
            campaignId={campaignId}
            characterId={characterId}
            embedded={embedded}
            refreshToken={refreshToken}
            onChanged={onChanged}
            blockedText={blockedText}
        />
    )
}

function Loaded({ campaignId, characterId, embedded, refreshToken, onChanged, blockedText }: Props) {
    // Nothing here reads the NPC's authoring view: that is the world's private side (a world role is
    // needed), and a campaign GM with no world role runs the NPC. The character's own read carries
    // its status, so the panel decides from that and from what the page already knows.
    const options = useAuthoringResource<RuntimeOptions>(npcRuntimeOptionsPath(campaignId))
    const character = useAuthoringResource<CharacterDetail>(
        `/campaigns/${encodeURIComponent(campaignId)}/characters/${encodeURIComponent(characterId)}`,
    )
    useRefetchOnChange(refreshToken, character.refetch)
    const { data: optionsView, stale: optionsStale } = useKeptData(options.state)
    const { data: characterView, stale: characterStale } = useKeptData(character.state)
    // Only the character's own read is the panel: the options just fill the condition and resource
    // choices. A failed options read leaves the panel (status, hit points, location) up with those
    // two controls withheld and a way to read them again; a read still loading shows nothing yet.
    if (characterView === null || (optionsView === null && options.state.kind === "loading")) {
        return null
    }
    // Reads only: trying again never repeats a command.
    const notice =
        optionsStale || characterStale ? (
            <StaleReadNotice
                what="NPC information"
                onRetry={() => {
                    void options.refetch()
                    void character.refetch()
                }}
            />
        ) : null
    // The server accepts these commands only for a published, active NPC. The page's own successful
    // read of the status wins over the panel's; a status the answer does not carry is unknown, and
    // the server stays the authority (it refuses a command it will not take).
    const blocked =
        blockedText !== undefined
            ? blockedText
            : (characterView.lifecycle_status !== undefined && characterView.lifecycle_status !== "active"
            ? "This NPC is archived. Restore it before changing their hit points, conditions, resources or location."
            : characterView.canon_status !== undefined && characterView.canon_status !== "canon"
              ? "Publish this NPC to change their hit points, conditions, resources or location."
              : null)
    if (blocked !== null) {
        return (
            <>
                {notice}
                <PanelFrame embedded={embedded} title="Run this NPC" headingId="npc-runtime-heading">
                    <p>{blocked}</p>
                </PanelFrame>
            </>
        )
    }
    return (
        <>
            {notice}
            <Panel
            campaignId={campaignId}
            characterId={characterId}
            embedded={embedded}
            options={optionsView}
            optionsRetry={options.state.kind === "error" ? () => void options.refetch() : null}
            detail={characterView}
            refetch={character.refetch}
            pageStale={characterStale}
            onChanged={onChanged}
            />
        </>
    )
}

function Panel({
    campaignId,
    characterId,
    options,
    optionsRetry,
    detail,
    refetch,
    pageStale,
    embedded,
    onChanged,
}: Props & {
    // `null` when the choices could not be read; `optionsRetry` is then how to read them again
    // (`null` too when a retry cannot help, such as a denied or missing answer).
    options: RuntimeOptions | null
    optionsRetry: (() => void) | null
    detail: CharacterDetail
    refetch: () => Promise<RefetchOutcome>
    // The character read failed and `detail` is the last that loaded.
    pageStale: boolean
}) {
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
    // What the last confirmed command said, for the notice if the character could not be read back.
    const [saved, setSaved] = useState<string | null>(null)

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
            setSaved(message)
            const outcome = await refetch()
            // The page's own view of the character is read by the page, which reports it if it fails.
            onChanged?.()
            if (outcome === "ok" && message !== null) announce(message)
            return outcome
        },
    })
    const refreshed = useConfirmedRefresh({
        status: mutation.status,
        reset: mutation.reset,
        what: "NPC information",
        message: saved,
        read: refetch,
        pageStale,
    })
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const explained = error?.code ? (CODE_MESSAGE[error.code] ?? null) : null
    // Hit points, conditions and resources change relative to what the server holds. Until the
    // character is read again the panel shows the values from before, so a second change is held
    // rather than typed against numbers that are no longer true.
    const busy = mutation.status.kind === "pending" || refreshed.held || pageStale
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

    const conditionByCode = new Map((options?.conditions ?? []).map((c) => [c.code, c]))
    const choicesMissing = (
        <div className="authoring-form">
            <p>
                {options === null && optionsRetry !== null
                    ? "The choices for this could not be loaded. Hit points and location still work."
                    : "The choices for this are not available. Hit points and location still work."}
            </p>
            {optionsRetry !== null ? (
                <button type="button" className="authoring-button" onClick={optionsRetry}>
                    Try loading the choices again
                </button>
            ) : null}
        </div>
    )
    return (
        <PanelFrame embedded={embedded} title="Run this NPC" headingId="npc-runtime-heading">
            {refreshed.notice}
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
            {detail.current_hit_points === null ? (
                // No starting state on this timeline: the server refuses a change (it never invents
                // hit points or creates the state as a side effect), so none is offered.
                <>
                    <p>Not tracked yet. Set this NPC&apos;s starting hit points before changing them.</p>
                    <p>
                        <Link
                            className="authoring-button"
                            to={`/app/${encodeURIComponent(campaignId)}/characters/${encodeURIComponent(characterId)}/builds`}
                        >
                            Set starting state
                        </Link>
                    </p>
                </>
            ) : (
                <>
                    <p>{`${detail.current_hit_points} of ${detail.maximum_hit_points ?? "?"}`}</p>
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
                        <TextField
                            id="npc-hp-delta"
                            label="Change (negative for damage)"
                            value={delta}
                            onChange={setDelta}
                        />
                        <button type="submit" className="authoring-button" disabled={busy}>
                            Apply hit point change
                        </button>
                    </form>
                </>
            )}

            <h3>Conditions</h3>
            {(detail.conditions ?? []).length === 0 ? <p>None.</p> : null}
            <ul className="op-list">
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
            {options === null ? (
                choicesMissing
            ) : (
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
                        options={options?.conditions ?? []}
                        onChange={setCondition}
                    />
                    <TextField id="npc-condition-source" label="Source (optional)" value={source} onChange={setSource} />
                    <button type="submit" className="authoring-button" disabled={busy}>
                        Add condition
                    </button>
                </form>
            )}

            <h3>Resources</h3>
            {(detail.resources ?? []).length === 0 ? <p>None tracked.</p> : null}
            <ul className="record-list">
                {(detail.resources ?? []).map((r) => (
                    <li key={r.resource_code}>
                        {humanize(r.resource_code)}: {r.current_amount} of {r.maximum_amount}
                    </li>
                ))}
            </ul>
            {options === null ? (
                <p>Available once the choices load.</p>
            ) : (
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
                        options={options?.resources ?? []}
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
            )}

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
        </PanelFrame>
    )
}

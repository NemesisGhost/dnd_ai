import { useEffect, useState } from "react"
import { clockPath } from "../api/campaignClock"
import { partiesPath, partyMembersPath } from "../api/parties"
import { recordSessionTravel, routesPath } from "../api/travel"
import type { RouteItem, TravelBody, TravelReceipt } from "../api/travel"
import { fetchWorldEntities } from "../api/world"
import { useSession } from "../context/SessionContext"
import { useAuthoringMutation } from "../hooks/useAuthoringMutation"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import type { ClockState } from "../types/campaignClock"
import type { PartyList, PartyMembers } from "../types/parties"
import type { SessionParticipant, SessionTravelEntry } from "../types/campaignSession"
import { useAnnounce } from "./authoring/announcer"
import { SelectField, TextAreaField } from "./authoring/fields"
import { MutationStatusMessage } from "./authoring/feedback"
import { ReferenceCombobox } from "./authoring/ReferenceCombobox"
import type { ReferenceOption } from "./authoring/ReferenceCombobox"
import { WorldTimePicker } from "./authoring/WorldTimePicker"
import { TravelHistory } from "./sessionRun/SessionActivity"
import "./authoring/authoring.css"

const NOTE_MAX = 4000

interface Props {
    campaignId: string
    sessionId: string
    participants: SessionParticipant[]
    // The session's travel, already filtered for the caller, shown beneath the form.
    travel: SessionTravelEntry[]
    // Re-reads the session (and so its travel). Resolves whether or not the read succeeded.
    refetch: () => Promise<void>
    // True while the page's latest read of the session failed and it is showing older data.
    refreshFailed?: boolean
    // False when recording is not offered (the session is not in progress); the reason is shown
    // and the history stays readable.
    canRecord: boolean
    reason: string
    // True while this section is the one on screen, so the clock line is current.
    active?: boolean
    eventHref?: (eventId: string) => string | null
    // False when a surrounding panel supplies the section heading.
    showHeading?: boolean
}

const CODE_MESSAGE: Readonly<Record<string, string>> = {
    travel_invalid: "Choose a published destination and at least one published traveler.",
    route_mismatch: "That route does not join where the travelers are to where they are going.",
    travel_time_invalid:
        "Choose a later in-world time: the travelers arrived there at or after it. Nothing was recorded.",
    clock_required: "Set the campaign time first, or choose an in-world time below.",
    session_not_in_progress: "This session has ended or changed; reloading it. Nothing was recorded.",
    session_not_active: "This session has ended or changed; reloading it. Nothing was recorded.",
    not_found: "This session has ended or changed; reloading it. Nothing was recorded.",
}
const RELOAD_CODES = new Set(["session_not_in_progress", "session_not_active", "not_found"])

function arrivedText(receipt: TravelReceipt): string {
    if (!receipt.changed) return "Everyone was already there. Nothing was recorded."
    const moved = receipt.moved.length
    const there = receipt.already_there.length
    return (
        `${moved} traveler${moved === 1 ? "" : "s"} arrived and the journey was recorded.` +
        (there > 0 ? ` ${there} ${there === 1 ? "was" : "were"} already there.` : "")
    )
}

// Records characters arriving at a place together, from the run page, as part of the session.
// The campaign clock supplies the time unless an in-world time is chosen (which never moves the
// clock). The travelers are the characters ticked here together with a chosen party's current
// members; an optional route must join the travelers' current place to the destination. One
// event covers the whole journey, linked to this session, and the history sits beneath the form.
export function TravelSection({
    campaignId,
    sessionId,
    participants,
    travel,
    refetch,
    refreshFailed = false,
    canRecord,
    reason,
    active = true,
    eventHref,
    showHeading = true,
}: Props) {
    const Wrapper = showHeading ? "section" : "div"
    return (
        <Wrapper aria-labelledby={showHeading ? "travel-heading" : undefined}>
            {showHeading ? <h2 id="travel-heading">Travel</h2> : null}
            {canRecord ? (
                <TravelForm
                    campaignId={campaignId}
                    sessionId={sessionId}
                    participants={participants}
                    refetch={refetch}
                    refreshFailed={refreshFailed}
                    active={active}
                />
            ) : (
                <p className="authoring-note">{reason}</p>
            )}
            <h3 id="travel-history-heading">Travel in this session</h3>
            {travel.length === 0 ? (
                <p>No travel recorded in this session yet.</p>
            ) : (
                <TravelHistory
                    travel={travel}
                    label="Travel in this session"
                    eventHref={eventHref ?? (() => null)}
                />
            )}
        </Wrapper>
    )
}

function TravelForm({
    campaignId,
    sessionId,
    participants,
    refetch,
    refreshFailed,
    active,
}: Pick<Props, "campaignId" | "sessionId" | "participants" | "refetch" | "active"> & {
    refreshFailed: boolean
}) {
    const { reload } = useSession()
    const announce = useAnnounce()
    const present = participants.filter((p) => p.removed_at === null)
    const parties = useAuthoringResource<PartyList>(partiesPath(campaignId))
    const clock = useAuthoringResource<ClockState>(clockPath(campaignId))
    const [destination, setDestination] = useState<ReferenceOption | null>(null)
    const [chosen, setChosen] = useState<string[]>([])
    const [party, setParty] = useState("")
    const [route, setRoute] = useState("")
    const [timeId, setTimeId] = useState("")
    const [note, setNote] = useState("")
    const [problem, setProblem] = useState<string | null>(null)
    const [noteProblem, setNoteProblem] = useState<string | null>(null)
    // What the last accepted request did, kept on screen until the next attempt.
    const [outcome, setOutcome] = useState<TravelReceipt | null>(null)
    const routes = useAuthoringResource<{ items: RouteItem[] }>(
        routesPath(campaignId, destination?.id ?? "00000000-0000-0000-0000-000000000000"),
    )
    const members = useAuthoringResource<PartyMembers>(
        party === "" ? null : partyMembersPath(campaignId, party),
    )
    const clockRefetch = clock.refetch

    // The clock may have been advanced elsewhere on the page while this section was hidden.
    useEffect(() => {
        if (active) void clockRefetch()
    }, [active, clockRefetch])

    const mutation = useAuthoringMutation<TravelBody, TravelReceipt>({
        scopeKey: `travel:${sessionId}`,
        request: (body, ctx) => recordSessionTravel(campaignId, sessionId, body, ctx),
        onSuccess: async (receipt) => {
            setOutcome(receipt)
            if (receipt.changed) {
                // Only what the command consumed is cleared; the destination and party stay.
                setChosen([])
                setRoute("")
                setNote("")
                setTimeId("")
                await refetch()
            }
            announce(arrivedText(receipt))
        },
    })
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const explained = error?.code ? (CODE_MESSAGE[error.code] ?? null) : null
    const reloadNeeded = error?.code != null && RELOAD_CODES.has(error.code)

    // A stale session means this page's copy is out of date: reload it so the form can go.
    useEffect(() => {
        if (reloadNeeded) void refetch()
    }, [reloadNeeded, refetch])

    async function searchPlaces(query: string, signal: AbortSignal): Promise<ReferenceOption[]> {
        const page = await fetchWorldEntities(campaignId, { category: "location", query, limit: 10 }, signal)
        return page.items.map((item) => ({
            id: item.entity_id,
            label: item.name,
            detail: item.entity_type_code.replace(/_/g, " "),
        }))
    }

    const routeItems =
        destination === null || routes.state.kind !== "ready" ? [] : routes.state.data.items
    const partyItems = parties.state.kind === "ready" ? parties.state.data.items : []
    const presentIds = new Set(present.map((p) => p.character_id))
    const partyMembers =
        party === "" || members.state.kind !== "ready"
            ? []
            : members.state.data.members.filter((m) => m.is_current)
    const partyUnreadable = party !== "" && members.state.kind !== "ready" && members.state.kind !== "loading"
    // The same union the server computes: the ticked characters and the party's current members.
    const willMove = new Map<string, string>()
    for (const p of present) {
        if (chosen.includes(p.character_id)) willMove.set(p.character_id, p.character_name)
    }
    for (const m of partyMembers) willMove.set(m.character_id, m.character_name)
    const clockText =
        clock.state.kind === "ready"
            ? clock.state.data.current === null
                ? null
                : clock.state.data.current.display
            : undefined

    return (
        <>
            <form
                noValidate
                aria-label="Record travel"
                className="authoring-form"
                onSubmit={(event) => {
                    event.preventDefault()
                    let bad = false
                    if (destination === null || (chosen.length === 0 && party === "")) {
                        setProblem("Choose a destination and who is travelling.")
                        bad = true
                    } else {
                        setProblem(null)
                    }
                    if (note.trim().length > NOTE_MAX) {
                        setNoteProblem(`GM notes must be ${NOTE_MAX} characters or fewer.`)
                        bad = true
                    } else {
                        setNoteProblem(null)
                    }
                    if (bad || destination === null) return
                    setOutcome(null)
                    mutation.submit({
                        destination_location_id: destination.id,
                        character_ids: chosen,
                        party_id: party === "" ? null : party,
                        route_id: route === "" ? null : route,
                        world_time_id: timeId === "" ? null : timeId,
                        note: note.trim() === "" ? null : note.trim(),
                    })
                }}
            >
                {explained !== null ? (
                    <p role="alert">{explained}</p>
                ) : error !== null ? (
                    <MutationStatusMessage error={error} onRetry={mutation.retry} onCheckSession={reload} />
                ) : null}
                <p className="authoring-note" id="travel-when">
                    {timeId !== ""
                        ? "Arrives at the in-world time chosen below."
                        : clockText === undefined
                          ? "Uses the campaign time."
                          : clockText === null
                            ? "Set the campaign time first, or choose an in-world time below."
                            : `Uses the campaign time: ${clockText}`}
                </p>
                <ReferenceCombobox
                    id="travel-destination"
                    label="Destination"
                    value={destination}
                    onChange={(value) => {
                        setDestination(value)
                        setRoute("")
                    }}
                    search={searchPlaces}
                    error={problem}
                    placeholder="Search places"
                />
                <fieldset>
                    <legend>Who is travelling</legend>
                    {present.length === 0 ? <p>No one is taking part yet.</p> : null}
                    {present.map((p) => (
                        <label key={p.character_id} className="authoring-checkbox">
                            <input
                                type="checkbox"
                                checked={chosen.includes(p.character_id)}
                                onChange={(event) =>
                                    setChosen(
                                        event.target.checked
                                            ? [...chosen, p.character_id]
                                            : chosen.filter((id) => id !== p.character_id),
                                    )
                                }
                            />{" "}
                            {p.character_name}
                        </label>
                    ))}
                    {partyItems.length > 0 ? (
                        <SelectField
                            id="travel-party"
                            label="Add a party"
                            hint="Everyone ticked above and the party's current members travel together."
                            value={party}
                            placeholder="No party"
                            options={partyItems
                                .filter((p) => p.lifecycle_status === "active")
                                .map((p) => ({ value: p.party_id, label: p.name }))}
                            onChange={setParty}
                        />
                    ) : null}
                </fieldset>
                <div aria-live="polite">
                    <p id="travel-preview-heading">These characters will move</p>
                    {willMove.size === 0 ? (
                        <p className="authoring-note">No one selected yet.</p>
                    ) : (
                        <ul className="record-list" aria-labelledby="travel-preview-heading">
                            {[...willMove.entries()].map(([id, name]) => (
                                <li key={id}>
                                    {name}
                                    {presentIds.has(id) ? "" : " (not in this session)"}
                                </li>
                            ))}
                        </ul>
                    )}
                    {partyUnreadable ? (
                        <p className="authoring-note">
                            The party&apos;s members could not be listed here. The server still moves all of its
                            current members.
                        </p>
                    ) : null}
                    <p className="authoring-note">
                        A preview only: the server decides who moves when you record, and anyone already at the
                        destination stays put.
                    </p>
                </div>
                {routeItems.length > 0 ? (
                    <SelectField
                        id="travel-route"
                        label="By route (optional)"
                        value={route}
                        placeholder="No route"
                        options={routeItems.map((r) => ({
                            value: r.relationship_id,
                            label: `${r.origin?.name ?? "?"} to ${r.destination?.name ?? "?"}`,
                        }))}
                        onChange={setRoute}
                    />
                ) : null}
                <WorldTimePicker
                    campaignId={campaignId}
                    id="travel-time"
                    label="In-world time (optional)"
                    hint="Leave empty to use the campaign time. Choosing a time does not change the campaign time."
                    value={timeId}
                    onChange={setTimeId}
                />
                <TextAreaField
                    id="travel-note"
                    label="GM notes (optional)"
                    hint="Visible only to people who can edit canon."
                    value={note}
                    onChange={setNote}
                    maxLength={NOTE_MAX}
                    error={noteProblem}
                />
                <p className="authoring-note">
                    Recording travel also moves each traveler&apos;s current location, and a location change
                    cannot be undone by correcting the event.
                </p>
                <button type="submit" className="authoring-button" disabled={mutation.status.kind === "pending"}>
                    Record travel
                </button>
            </form>
            {outcome !== null ? (
                <p role="status">
                    {arrivedText(outcome)}
                    {outcome.changed && refreshFailed
                        ? " The session could not be refreshed, so the history below may be out of date. Do not record this journey again."
                        : ""}
                </p>
            ) : null}
        </>
    )
}

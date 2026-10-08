import { useState } from "react"
import { partiesPath } from "../api/parties"
import { recordTravel, routesPath } from "../api/travel"
import type { RouteItem, TravelBody, TravelReceipt } from "../api/travel"
import { fetchWorldEntities } from "../api/world"
import { useSession } from "../context/SessionContext"
import { useAuthoringMutation } from "../hooks/useAuthoringMutation"
import { useAuthoringResource } from "../hooks/useAuthoringResource"
import type { PartyList } from "../types/parties"
import type { SessionParticipant } from "../types/campaignSession"
import { useAnnounce } from "./authoring/announcer"
import { SelectField } from "./authoring/fields"
import { MutationStatusMessage } from "./authoring/feedback"
import { ReferenceCombobox } from "./authoring/ReferenceCombobox"
import type { ReferenceOption } from "./authoring/ReferenceCombobox"
import "./authoring/authoring.css"

interface Props {
    campaignId: string
    participants: SessionParticipant[]
    // False when a surrounding panel supplies the section heading.
    showHeading?: boolean
}

const CODE_MESSAGE: Readonly<Record<string, string>> = {
    travel_invalid: "Choose a published destination and at least one published traveler.",
    route_mismatch: "That route does not join where the travelers are to where they are going.",
    travel_time_invalid: "Move the campaign time forward: the travelers arrived there at or after it.",
    clock_required: "Set the campaign time first.",
}

// Records characters arriving at a place together, from the run page. The campaign clock
// supplies the time; a party moves as its current members, and an optional route must join
// the travelers' current place to the destination. One event covers the whole journey.
export function TravelSection({ campaignId, participants, showHeading = true }: Props) {
    const { reload } = useSession()
    const announce = useAnnounce()
    const present = participants.filter((p) => p.removed_at === null)
    const parties = useAuthoringResource<PartyList>(partiesPath(campaignId))
    const [destination, setDestination] = useState<ReferenceOption | null>(null)
    const [chosen, setChosen] = useState<string[]>([])
    const [party, setParty] = useState("")
    const [route, setRoute] = useState("")
    const [problem, setProblem] = useState<string | null>(null)
    const routes = useAuthoringResource<{ items: RouteItem[] }>(
        routesPath(campaignId, destination?.id ?? "00000000-0000-0000-0000-000000000000"),
    )
    const mutation = useAuthoringMutation<TravelBody, TravelReceipt>({
        scopeKey: `travel:${campaignId}`,
        request: (body, ctx) => recordTravel(campaignId, body, ctx),
        onSuccess: (receipt) => {
            announce(
                receipt.changed
                    ? `${receipt.moved.length} traveler${receipt.moved.length === 1 ? "" : "s"} arrived`
                    : "Everyone was already there",
            )
            setChosen([])
        },
    })
    const error = mutation.status.kind === "error" ? mutation.status.error : null
    const explained = error?.code ? (CODE_MESSAGE[error.code] ?? null) : null

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
    // A surrounding panel supplies the heading and landmark when this one is hidden.
    const Wrapper = showHeading ? "section" : "div"
    const partyItems = parties.state.kind === "ready" ? parties.state.data.items : []

    return (
        <Wrapper aria-labelledby={showHeading ? "travel-heading" : undefined}>
            {showHeading ? <h2 id="travel-heading">Travel</h2> : null}
            <form
                noValidate
                aria-label="Record travel"
                className="authoring-form"
                onSubmit={(event) => {
                    event.preventDefault()
                    if (destination === null || (chosen.length === 0 && party === "")) {
                        setProblem("Choose a destination and who is travelling.")
                        return
                    }
                    setProblem(null)
                    mutation.submit({
                        destination_location_id: destination.id,
                        character_ids: chosen,
                        party_id: party === "" ? null : party,
                        route_id: route === "" ? null : route,
                    })
                }}
            >
                {explained !== null ? (
                    <p role="alert">{explained}</p>
                ) : error !== null ? (
                    <MutationStatusMessage error={error} onRetry={mutation.retry} onCheckSession={reload} />
                ) : null}
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
                    <legend>Travelers</legend>
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
                </fieldset>
                {partyItems.length > 0 ? (
                    <SelectField
                        id="travel-party"
                        label="Or a whole party"
                        value={party}
                        placeholder="No party"
                        options={partyItems
                            .filter((p) => p.lifecycle_status === "active")
                            .map((p) => ({ value: p.party_id, label: p.name }))}
                        onChange={setParty}
                    />
                ) : null}
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
                <button type="submit" className="authoring-button" disabled={mutation.status.kind === "pending"}>
                    Record travel
                </button>
            </form>
        </Wrapper>
    )
}

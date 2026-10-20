import { Link } from "react-router"
import type {
    CampaignSessionEvent,
    SessionTravelEntry,
    SessionTravelLeg,
    TravelPlace,
} from "../../types/campaignSession"

const NO_EARLIER = "No earlier location recorded"
const UNAVAILABLE = "A place you cannot see"

function placeText(place: TravelPlace): string {
    if (place.state === "named" && place.name) return place.name
    return place.state === "unrecorded" ? NO_EARLIER : UNAVAILABLE
}

const placeKey = (place: TravelPlace): string => `${place.state}:${place.entity_id ?? ""}`

interface LegGroup {
    key: string
    names: string[]
    from: TravelPlace
    to: TravelPlace
}

// Travelers who made the same journey share a line; one with a different origin gets its own.
// The legs are never assumed to share an origin.
function groupLegs(legs: SessionTravelLeg[]): LegGroup[] {
    const groups: LegGroup[] = []
    for (const leg of legs) {
        const key = `${placeKey(leg.from)}>${placeKey(leg.to)}`
        const found = groups.find((g) => g.key === key)
        if (found) {
            found.names.push(leg.traveler.name)
        } else {
            groups.push({ key, names: [leg.traveler.name], from: leg.from, to: leg.to })
        }
    }
    return groups
}

function legLine(group: LegGroup): string {
    const names = group.names.join(", ")
    if (group.from.state === "unrecorded") {
        return `${names}: arrived at ${placeText(group.to)} (${NO_EARLIER.toLowerCase()})`
    }
    return `${names}: ${placeText(group.from)} to ${placeText(group.to)}`
}

// In-world time, labelled so it is never read as one of the real-world timestamps.
export function InWorldTime({ value }: { value: string | undefined }) {
    return value ? <span className="session-activity__time">In-world: {value}</span> : null
}

// The journey lines for one travel event, without a heading. `showNote` is for the surfaces that
// are editors-only; the server already returns a null note to everyone else.
export function TravelSummary({ entry, showNote = true }: { entry: SessionTravelEntry; showNote?: boolean }) {
    const groups = groupLegs(entry.legs)
    return (
        <>
            {groups.length === 0 ? (
                <p className="authoring-note">Travel was recorded.</p>
            ) : (
                <ul className="session-activity__legs">
                    {groups.map((group) => (
                        <li key={group.key}>{legLine(group)}</li>
                    ))}
                </ul>
            )}
            {showNote && entry.note !== null ? <p className="authoring-note">GM notes: {entry.note}</p> : null}
        </>
    )
}

// One travel entry: heading (a link to the event when the caller may open it), time, journeys.
export function TravelEntry({
    entry,
    href,
    showNote = true,
}: {
    entry: SessionTravelEntry
    href?: string | null
    showNote?: boolean
}) {
    return (
        <>
            <strong>{href ? <Link to={href}>Travel</Link> : "Travel"}</strong>{" "}
            <InWorldTime value={entry.world_time} />
            <TravelSummary entry={entry} showNote={showNote} />
        </>
    )
}

// The session's recorded events in order: a travel event reads as its journeys, any other event
// as its name and GM notes, and every entry shows its in-world time. `eventHref` returns the
// event's page for people who may open it, or null.
export function SessionEventList({
    events,
    travel,
    label,
    ordered = false,
    eventHref,
}: {
    events: CampaignSessionEvent[]
    travel: SessionTravelEntry[] | undefined
    label: string
    ordered?: boolean
    eventHref: (eventId: string) => string | null
}) {
    const byEvent = new Map((travel ?? []).map((entry) => [entry.event_id, entry]))
    const Tag = ordered ? "ol" : "ul"
    return (
        <Tag className="record-list" aria-label={label}>
            {events.map((event) => {
                const entry = byEvent.get(event.event_id)
                const href = eventHref(event.event_id)
                return (
                    <li key={event.event_id}>
                        {entry !== undefined ? (
                            <TravelEntry entry={entry} href={href} />
                        ) : (
                            <>
                                {href ? <Link to={href}>{event.name}</Link> : event.name}{" "}
                                <InWorldTime value={event.world_time} />
                                {event.details !== null ? (
                                    <p className="authoring-note">GM notes: {event.details}</p>
                                ) : null}
                            </>
                        )}
                    </li>
                )
            })}
        </Tag>
    )
}

// A read-only history of just the travel, for the Travel section and the review.
export function TravelHistory({
    travel,
    label,
    eventHref,
}: {
    travel: SessionTravelEntry[]
    label: string
    eventHref: (eventId: string) => string | null
}) {
    return (
        <ul className="record-list" aria-label={label}>
            {travel.map((entry) => (
                <li key={entry.event_id}>
                    <TravelEntry entry={entry} href={eventHref(entry.event_id)} />
                </li>
            ))}
        </ul>
    )
}

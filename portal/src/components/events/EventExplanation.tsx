import { Link } from "react-router"
import type {
    EventExplanation as EventExplanationData,
    ExplanationRef,
    ExplanationRelation,
    ExplanationRelationCode,
} from "../../types/eventExplanation"
import { formatRecordedAt } from "../../utils/recordedAt"
import { TravelLegs } from "../sessionRun/SessionActivity"
import { buildName, explanationSentence, timeName } from "./explanationSentence"

const NOT_RECORDED = "not recorded"

const RELATION_LABEL: Readonly<Record<ExplanationRelationCode, string>> = {
    follows_previous_clock_change: "Follows the previous clock change",
    corrects_clock_change: "Corrects the earlier clock change",
    corrected_by_clock_change: "Later corrected by the clock change",
    caused_by: "Recorded cause",
    corrected_by: "Corrected by",
    replaced_by: "Replaced by",
    corrects: "Corrects",
    replaces: "Replaces",
}

interface EventExplanationProps {
    explanation: EventExplanationData
    // "compact" for lists (one sentence and the in-world time); "detail" for an event's own page
    // (times, before and after, session and links).
    density?: "compact" | "detail"
    // Needed by the detail density, which links characters, parties and the session.
    campaignId?: string
    // Compact only: omit the in-world time where the host already shows it.
    showTime?: boolean
    // The page for an event the caller may open, or null. Differs by surface (the world page or
    // the GM correction page), so the host supplies it.
    eventHref?: (eventId: string) => string | null
}

const enc = encodeURIComponent
const base = (campaignId: string): string => `/app/${enc(campaignId)}`

function refHref(campaignId: string, ref: ExplanationRef): string | null {
    if (ref.state !== "named" || !ref.openable || ref.entity_id === null) return null
    if (ref.kind === "character") return `${base(campaignId)}/characters/${enc(ref.entity_id)}`
    if (ref.kind === "party") return `${base(campaignId)}/parties/${enc(ref.entity_id)}`
    return null
}

// A name, a link when the caller may open it, or an honest placeholder (never an id).
function RefText({ campaignId, target, fallback }: { campaignId: string; target: ExplanationRef | null; fallback: string }) {
    if (target === null || target.state !== "named" || target.name === null) {
        return <>{target?.state === "unrecorded" ? NOT_RECORDED : fallback}</>
    }
    const href = refHref(campaignId, target)
    return href ? <Link to={href}>{target.name}</Link> : <>{target.name}</>
}

function RelationLine({
    relation,
    eventHref,
}: {
    relation: ExplanationRelation
    eventHref?: (eventId: string) => string | null
}) {
    const ref = relation.event
    const href = ref.state === "named" && ref.openable && ref.entity_id !== null ? (eventHref?.(ref.entity_id) ?? null) : null
    const name = ref.state === "named" && ref.name !== null ? ref.name : "an event that is not available"
    return (
        <li>
            {RELATION_LABEL[relation.relation]}: {href ? <Link to={href}>{name}</Link> : name}
            {relation.reason !== null ? <span className="authoring-note"> Reason: {relation.reason}</span> : null}
        </li>
    )
}

// What the sentence cannot say as plainly: the before and after of a build or clock change, as
// their own rows so a reader can compare them.
function BeforeAfter({ x }: { x: EventExplanationData }) {
    if (x.family === "character_build_activated" && x.build_detail === "full") {
        return (
            <>
                <div className="fact-grid__row">
                    <dt>Previous build</dt>
                    <dd>{buildName(x.previous_build)}</dd>
                </div>
                <div className="fact-grid__row">
                    <dt>New build</dt>
                    <dd>{buildName(x.new_build)}</dd>
                </div>
            </>
        )
    }
    if (x.family === "campaign_clock_advanced" || x.family === "campaign_clock_corrected") {
        return (
            <>
                <div className="fact-grid__row">
                    <dt>Previous campaign time</dt>
                    <dd>{timeName(x.previous_time)}</dd>
                </div>
                <div className="fact-grid__row">
                    <dt>New campaign time</dt>
                    <dd>{timeName(x.new_time)}</dd>
                </div>
            </>
        )
    }
    return null
}

// How a clock advance recorded under CP-9b came about. An earlier advance has no origin and says
// nothing: lacking a cause does not make it manual.
function advanceCause(x: EventExplanationData): string | null {
    if (x.advance_origin === "manual") return "Manual advance"
    if (x.advance_origin === "event_cause") {
        return x.relations.some((r) => r.relation === "caused_by")
            ? "A recorded event (linked below)"
            : "A recorded event that is not available to you"
    }
    return null
}

// The shared explanation of an event. The two times are always separate and labelled: "In-world"
// is the effective fictional time, "Recorded" the real moment the event was written down.
export function EventExplanation({ explanation: x, density = "compact", campaignId = "", showTime = true, eventHref }: EventExplanationProps) {
    const sentence = explanationSentence(x)
    const isTravel = (x.family === "travel" || x.family === "location") && x.travel !== null

    if (density === "compact") {
        return (
            <div className="event-explanation event-explanation--compact">
                {sentence !== null ? <p className="event-explanation__sentence">{sentence}</p> : null}
                {x.advance_origin === "manual" ? (
                    <p className="event-explanation__origin">Manual advance</p>
                ) : null}
                {x.member_explanation !== null ? (
                    <p className="event-explanation__note">{x.member_explanation}</p>
                ) : null}
                {isTravel ? <TravelLegs legs={x.travel!.legs} /> : null}
                {showTime ? <span className="session-activity__time">In-world: {x.in_world_time}</span> : null}
            </div>
        )
    }

    return (
        <div className="event-explanation event-explanation--detail">
            {sentence !== null ? (
                <p className="event-explanation__sentence">
                    {renderLinked(x, campaignId) ?? sentence}
                </p>
            ) : null}
            {isTravel ? <TravelLegs legs={x.travel!.legs} /> : null}
            <dl className="fact-grid">
                <div className="fact-grid__row">
                    <dt>In-world time</dt>
                    <dd>{x.in_world_time}</dd>
                </div>
                <div className="fact-grid__row">
                    <dt>Recorded</dt>
                    <dd>
                        <time dateTime={x.recorded_at}>{formatRecordedAt(x.recorded_at)}</time>
                    </dd>
                </div>
                <BeforeAfter x={x} />
                {advanceCause(x) !== null ? (
                    <div className="fact-grid__row">
                        <dt>Cause</dt>
                        <dd>{advanceCause(x)}</dd>
                    </div>
                ) : null}
                {x.member_explanation !== null ? (
                    <div className="fact-grid__row">
                        <dt>Explanation</dt>
                        <dd className="event-explanation__note">{x.member_explanation}</dd>
                    </div>
                ) : null}
                {x.session !== null ? (
                    <div className="fact-grid__row">
                        <dt>Session</dt>
                        <dd>
                            <Link to={`${base(campaignId)}/sessions/${enc(x.session.session_id)}`}>
                                {x.session.title ?? `Session ${x.session.session_number}`}
                            </Link>
                        </dd>
                    </div>
                ) : null}
            </dl>
            {x.relations.length > 0 ? (
                <ul className="record-list event-explanation__relations" aria-label="Related events">
                    {x.relations.map((relation, index) => (
                        <RelationLine key={`${relation.relation}-${index}`} relation={relation} eventHref={eventHref} />
                    ))}
                </ul>
            ) : null}
        </div>
    )
}

// The party families link the character and the party inside the sentence.
function renderLinked(x: EventExplanationData, campaignId: string) {
    if (x.family !== "party_member_joined" && x.family !== "party_member_left") return null
    return (
        <>
            <RefText campaignId={campaignId} target={x.subject} fallback="A character" />
            {x.family === "party_member_joined" ? " joined " : " left "}
            <RefText campaignId={campaignId} target={x.party} fallback="a party" />.
        </>
    )
}

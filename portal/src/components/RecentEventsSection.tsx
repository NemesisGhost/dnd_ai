import { useState } from "react"
import type { RecentCampaignEvent } from "../types/campaignSummary"

const NO_TIME = "World time unassigned"
const NO_DESCRIPTION = "No event description is available."

interface RecentEventsSectionProps {
    events: RecentCampaignEvent[]
}

function timeText(event: RecentCampaignEvent): string {
    return event.world_time_display?.trim() || NO_TIME
}

// Summary first, then the fuller details when they add something new.
function descriptionParagraphs(event: RecentCampaignEvent): string[] {
    const summary = event.summary?.trim() ?? ""
    const details = event.details?.trim() ?? ""
    const paragraphs = [summary]
    if (details !== "" && details !== summary) {
        paragraphs.push(details)
    }
    const present = paragraphs.filter((text) => text !== "")
    return present.length > 0 ? present : [NO_DESCRIPTION]
}

export function RecentEventsSection({ events }: RecentEventsSectionProps) {
    const [selectedId, setSelectedId] = useState<string | null>(null)

    // The selection is stored (implicit initial choice included) and
    // normalized against the current list during render: a still-present
    // selection is kept however the list is reordered or grown, a vanished one
    // is replaced by the first remaining event and cannot return if its id
    // reappears, and an empty list clears it. Campaign changes remount this
    // section (see CampaignHomePage), so no selection crosses campaigns.
    const stillPresent =
        selectedId !== null && events.some((event) => event.event_id === selectedId)
    const effectiveId = stillPresent ? selectedId : (events[0]?.event_id ?? null)
    if (effectiveId !== selectedId) {
        setSelectedId(effectiveId)
    }
    const selected = events.find((event) => event.event_id === effectiveId) ?? null

    return (
        <section aria-labelledby="recent-events-heading">
            <h2 id="recent-events-heading">Recent events</h2>

            {selected === null ? (
                <p>No recent events are available.</p>
            ) : (
                <div className="recent-events">
                    <ul className="recent-events__list" aria-label="Recent events list">
                        {events.map((event) => {
                            const isSelected = event.event_id === selected.event_id
                            return (
                                <li key={event.event_id}>
                                    <button
                                        type="button"
                                        className="recent-events__item"
                                        aria-current={isSelected ? "true" : undefined}
                                        onClick={() => setSelectedId(event.event_id)}
                                    >
                                        <span className="recent-events__item-title">
                                            {event.name}
                                        </span>
                                        <span className="recent-events__item-time">
                                            {timeText(event)}
                                        </span>
                                    </button>
                                </li>
                            )
                        })}
                    </ul>

                    <article
                        className="recent-events__detail"
                        aria-labelledby="recent-event-detail-heading"
                    >
                        <h3 id="recent-event-detail-heading">{selected.name}</h3>
                        <p className="recent-events__detail-time">{timeText(selected)}</p>
                        {descriptionParagraphs(selected).map((text, index) => (
                            <p key={index}>{text}</p>
                        ))}
                    </article>
                </div>
            )}
        </section>
    )
}

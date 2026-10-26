import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { describe, expect, it } from "vitest"
import type { CampaignSessionEvent, SessionTravelEntry } from "../../types/campaignSession"
import type { EventExplanation } from "../../types/eventExplanation"
import { SessionEventList, TravelEntry } from "./SessionActivity"

const entry = (legs: SessionTravelEntry["legs"], note: string | null = null): SessionTravelEntry => ({
    event_id: "e1",
    world_time_id: "t1",
    world_time: "Year 3",
    note,
    legs,
})

const event = (extra: Partial<CampaignSessionEvent> = {}): CampaignSessionEvent => ({
    event_id: "e2",
    name: "A feast",
    summary: null,
    event_type_code: "session_narrative",
    event_status_code: "recorded",
    world_time_id: "t2",
    details: null,
    ...extra,
})

const clockExplanation: EventExplanation = {
    event_id: "e2",
    family: "campaign_clock_advanced",
    in_world_time: "Year 2",
    recorded_at: "2026-10-25T03:04:05+00:00",
    subject: null,
    party: null,
    build_detail: null,
    previous_build: null,
    new_build: null,
    previous_time: { state: "named", text: "Year 1" },
    new_time: { state: "named", text: "Year 2" },
    travel: null,
    session: null,
    relations: [],
}

describe("TravelEntry", () => {
    it("says travel was recorded when no traveler may be shown, and never shows a count", () => {
        render(<TravelEntry entry={entry([])} />)
        expect(screen.getByText("Travel was recorded.")).toBeInTheDocument()
        expect(screen.getByText("In-world: Year 3")).toBeInTheDocument()
    })

    it("words an unavailable origin honestly and shows no GM note when there is none", () => {
        render(
            <TravelEntry
                entry={entry([
                    {
                        traveler: { entity_id: "a", name: "Aldric" },
                        from: { state: "unavailable" },
                        to: { state: "named", entity_id: "l", name: "Southmark" },
                    },
                ])}
            />,
        )
        expect(screen.getByText("Aldric: A place you cannot see to Southmark")).toBeInTheDocument()
        expect(screen.queryByText(/GM notes/)).toBeNull()
    })
})

describe("SessionEventList", () => {
    it("shows in-world time for every event and plain events as before", () => {
        render(
            <MemoryRouter>
                <SessionEventList
                    events={[event({ world_time: "Year 2", details: "Secret" }), event({ event_id: "e3", name: "Old", world_time: undefined })]}
                    travel={undefined}
                    label="Entries"
                    eventHref={(id) => `/events/${id}`}
                />
            </MemoryRouter>,
        )
        expect(screen.getByRole("link", { name: "A feast" })).toHaveAttribute("href", "/events/e2")
        expect(screen.getByText("In-world: Year 2")).toBeInTheDocument()
        expect(screen.getByText("GM notes: Secret")).toBeInTheDocument()
        expect(screen.getAllByText(/In-world:/)).toHaveLength(1)
    })

    it("renders a name without a link when the event cannot be opened", () => {
        render(
            <MemoryRouter>
                <SessionEventList events={[event()]} travel={undefined} label="Entries" eventHref={() => null} />
            </MemoryRouter>,
        )
        expect(screen.queryByRole("link")).toBeNull()
        expect(screen.getByText("A feast")).toBeInTheDocument()
    })

    it("keeps the event's title and GM notes and adds the explanation for an explained event", () => {
        render(
            <MemoryRouter>
                <SessionEventList
                    events={[event({ name: "The campaign clock advanced", details: "Secret" })]}
                    travel={undefined}
                    explanations={[clockExplanation]}
                    label="Entries"
                    eventHref={(id) => `/events/${id}`}
                />
            </MemoryRouter>,
        )
        expect(screen.getByRole("link", { name: "The campaign clock advanced" })).toHaveAttribute(
            "href",
            "/events/e2",
        )
        expect(screen.getByText("The campaign clock advanced from Year 1 to Year 2.")).toBeInTheDocument()
        expect(screen.getByText("In-world: Year 2")).toBeInTheDocument()
        expect(screen.getByText("GM notes: Secret")).toBeInTheDocument()
    })

    it("treats an explanation with no adapter as a plain event, and still prefers travel entries", () => {
        render(
            <MemoryRouter>
                <SessionEventList
                    events={[event({ world_time: "Year 2" })]}
                    travel={undefined}
                    explanations={[{ ...clockExplanation, family: "other" }]}
                    label="Entries"
                    eventHref={() => null}
                />
            </MemoryRouter>,
        )
        expect(screen.getAllByText(/In-world:/)).toHaveLength(1)
        expect(screen.queryByText(/campaign clock/)).toBeNull()
    })
})

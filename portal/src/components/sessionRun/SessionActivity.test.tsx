import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { describe, expect, it } from "vitest"
import type { CampaignSessionEvent, SessionTravelEntry } from "../../types/campaignSession"
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
})

import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { describe, expect, it } from "vitest"
import type { EventDetail } from "../types/world"
import { WorldEventDetailPage } from "./WorldEventDetailPage"

const eventFixture: EventDetail = {
    event_id: "event-a",
    name: "The Sundering of the Vale",
    summary: "A magical catastrophe split the Ashen Vale.",
    event_type_code: "historical_event",
    event_status_code: "recorded",
    world_time_id: "world-time-a",
    details: "Occurred during the Second Age.",
    session_id: "session-a",
    participants: [{ entity_id: "character-a", role_code: "instigator" }],
    locations: [{ location_id: "location-a", role: "epicenter" }],
}

function renderPage(event: EventDetail) {
    return render(
        <MemoryRouter>
            <WorldEventDetailPage campaignId="campaign-a" event={event} />
        </MemoryRouter>,
    )
}

describe("WorldEventDetailPage", () => {
    it("renders one page heading, back link, and authorized descriptive fields", () => {
        renderPage(eventFixture)

        expect(
            screen.getByRole("heading", { level: 1, name: "The Sundering of the Vale" }),
        ).toBeInTheDocument()

        expect(
            screen.getByRole("link", { name: "Back to World" }),
        ).toHaveAttribute("href", "/app/campaign-a/world")

        expect(
            screen.getByText("A magical catastrophe split the Ashen Vale."),
        ).toBeInTheDocument()
        expect(screen.getByText("Occurred during the Second Age.")).toBeInTheDocument()
        expect(screen.getByText("Recorded")).toBeInTheDocument()
    })

    it("never renders participant, location, world-time, or session ids, and invents no names", () => {
        renderPage(eventFixture)

        expect(screen.queryByText("character-a")).not.toBeInTheDocument()
        expect(screen.queryByText("location-a")).not.toBeInTheDocument()
        expect(screen.queryByText("world-time-a")).not.toBeInTheDocument()
        expect(screen.queryByText("session-a")).not.toBeInTheDocument()
        expect(screen.queryByText("instigator")).not.toBeInTheDocument()
        expect(screen.queryByText("epicenter")).not.toBeInTheDocument()
    })

    it("shows a deliberate null state for missing details", () => {
        renderPage({ ...eventFixture, details: null, summary: null })

        expect(screen.getByText("Not recorded")).toBeInTheDocument()
    })
})

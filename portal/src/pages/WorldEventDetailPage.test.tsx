import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { describe, expect, it } from "vitest"
import type { EventExplanation } from "../types/eventExplanation"
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

const joinExplanation: EventExplanation = {
    event_id: "event-a",
    family: "party_member_joined",
    in_world_time: "Common Reckoning: Year 1",
    recorded_at: "2026-10-25T03:04:05+00:00",
    subject: { state: "named", kind: "character", entity_id: "char-1", name: "Aldric", openable: true },
    party: { state: "named", kind: "party", entity_id: "party-1", name: "The Company", openable: true },
    build_detail: null,
    previous_build: null,
    new_build: null,
    previous_time: null,
    new_time: null,
    advance_origin: null,
    member_explanation: null,
    travel: null,
    session: null,
    relations: [],
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

    it("explains what happened with the shared explanation and both times", () => {
        renderPage({ ...eventFixture, explanation: joinExplanation })
        expect(screen.getByRole("heading", { name: "What happened" })).toBeInTheDocument()
        expect(screen.getByRole("link", { name: "Aldric" })).toHaveAttribute(
            "href",
            "/app/campaign-a/characters/char-1",
        )
        expect(screen.getByText("In-world time")).toBeInTheDocument()
        expect(screen.getAllByText("Recorded").length).toBe(2) // status and recording time
        expect(screen.getByText("Occurred during the Second Age.")).toBeInTheDocument()
    })

    it("shows no explanation panel when the server sent none", () => {
        renderPage(eventFixture)
        expect(screen.queryByRole("heading", { name: "What happened" })).toBeNull()
    })
})

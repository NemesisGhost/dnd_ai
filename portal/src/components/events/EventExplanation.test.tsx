import { render, screen, within } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { describe, expect, it } from "vitest"
import type {
    EventExplanation as Data,
    ExplanationRef,
} from "../../types/eventExplanation"
import { EventExplanation } from "./EventExplanation"
import { explanationSentence } from "./explanationSentence"

const named = (kind: ExplanationRef["kind"], name: string, openable = true): ExplanationRef => ({
    state: "named",
    kind,
    entity_id: `${kind}-1`,
    name,
    openable,
})
const unavailable = (kind: ExplanationRef["kind"]): ExplanationRef => ({
    state: "unavailable",
    kind,
    entity_id: null,
    name: null,
    openable: false,
})

const base: Data = {
    event_id: "e1",
    family: "other",
    in_world_time: "Common Reckoning: Year 3",
    recorded_at: "2026-10-25T03:04:05+00:00",
    subject: null,
    party: null,
    build_detail: null,
    previous_build: null,
    new_build: null,
    previous_time: null,
    new_time: null,
    travel: null,
    session: null,
    relations: [],
}

const renderDetail = (x: Data) =>
    render(
        <MemoryRouter>
            <EventExplanation
                explanation={x}
                density="detail"
                campaignId="c1"
                eventHref={(id) => `/events/${id}`}
            />
        </MemoryRouter>,
    )

describe("EventExplanation", () => {
    it("reads a join as a sentence with linked character and party and two labelled times", () => {
        renderDetail({
            ...base,
            family: "party_member_joined",
            subject: named("character", "Aldric"),
            party: named("party", "The Company"),
        })
        expect(screen.getByRole("link", { name: "Aldric" })).toHaveAttribute(
            "href",
            "/app/c1/characters/character-1",
        )
        expect(screen.getByRole("link", { name: "The Company" })).toHaveAttribute(
            "href",
            "/app/c1/parties/party-1",
        )
        expect(screen.getByText("In-world time")).toBeInTheDocument()
        expect(screen.getByText("Common Reckoning: Year 3")).toBeInTheDocument()
        expect(screen.getByText("Recorded")).toBeInTheDocument()
        // The real recording time carries the reader's timezone and is not the in-world time.
        const recorded = document.querySelector("time")!
        expect(recorded).toHaveAttribute("datetime", "2026-10-25T03:04:05+00:00")
        expect(recorded.textContent).not.toContain("Year 3")
        expect(recorded.textContent).toMatch(/[A-Z]{2,5}|GMT[+-]\d+|UTC/)
    })

    it("names a leave and does not link a character or party the reader cannot open", () => {
        renderDetail({
            ...base,
            family: "party_member_left",
            subject: named("character", "Aldric", false),
            party: unavailable("party"),
        })
        expect(screen.queryByRole("link")).toBeNull()
        expect(screen.getByText(/Aldric left a party\./)).toBeInTheDocument()
    })

    it("never prints an id or a name for an unavailable character", () => {
        const { container } = renderDetail({
            ...base,
            family: "party_member_joined",
            subject: unavailable("character"),
            party: named("party", "The Company"),
        })
        expect(container.textContent).toContain("A character joined The Company.")
        expect(container.textContent).not.toMatch(/character-1/)
    })

    it("shows previous and new build labels only with full detail, otherwise a generic change", () => {
        const full: Data = {
            ...base,
            family: "character_build_activated",
            subject: named("character", "Aldric"),
            build_detail: "full",
            previous_build: named("build", "Fighter 1"),
            new_build: named("build", "Fighter 2"),
        }
        const { unmount } = renderDetail(full)
        expect(screen.getByText("Previous build")).toBeInTheDocument()
        expect(screen.getAllByText(/Fighter 1/).length).toBeGreaterThan(0)
        expect(screen.getAllByText(/Fighter 2/).length).toBeGreaterThan(0)
        unmount()
        const { container } = renderDetail({
            ...full,
            build_detail: "generic",
            previous_build: null,
            new_build: null,
        })
        expect(container.textContent).toContain("Aldric's build changed.")
        expect(container.textContent).not.toContain("Fighter")
        expect(screen.queryByText("Previous build")).toBeNull()
    })

    it("words a missing earlier build and an unavailable one differently", () => {
        const x: Data = {
            ...base,
            family: "character_build_activated",
            subject: named("character", "Aldric"),
            build_detail: "full",
            previous_build: { ...unavailable("build") },
            new_build: named("build", "Fighter 2"),
        }
        expect(explanationSentence(x)).toBe(
            "Aldric's active build changed from a build that is not available to Fighter 2.",
        )
        expect(
            explanationSentence({
                ...x,
                previous_build: { state: "unrecorded", kind: "build", entity_id: null, name: null, openable: false },
            }),
        ).toContain("from no earlier build recorded")
    })

    it("shows the clock's previous and new time and labels the chain as following, not causing", () => {
        renderDetail({
            ...base,
            family: "campaign_clock_advanced",
            previous_time: { state: "named", text: "Year 1" },
            new_time: { state: "named", text: "Year 2" },
            relations: [
                {
                    relation: "follows_previous_clock_change",
                    event: named("event", "The campaign clock advanced"),
                    reason: null,
                },
            ],
        })
        expect(screen.getByText("Previous campaign time")).toBeInTheDocument()
        expect(screen.getByText("Year 1")).toBeInTheDocument()
        expect(screen.getByText("Year 2")).toBeInTheDocument()
        expect(screen.getByText(/Follows the previous clock change:/)).toBeInTheDocument()
        expect(screen.queryByText(/caused/i)).toBeNull()
        expect(screen.getByRole("link", { name: "The campaign clock advanced" })).toHaveAttribute(
            "href",
            "/events/event-1",
        )
    })

    it("says a first clock setting has no earlier time recorded", () => {
        expect(
            explanationSentence({
                ...base,
                family: "campaign_clock_advanced",
                previous_time: { state: "unrecorded", text: null },
                new_time: { state: "named", text: "Year 1" },
            }),
        ).toBe("The campaign clock was set to Year 1 (no earlier time recorded).")
    })

    it("links the session and shows correction relations with the editor-only reason", () => {
        renderDetail({
            ...base,
            session: { session_id: "s1", session_number: 4, title: null },
            relations: [
                { relation: "corrects", event: named("event", "The door is locked"), reason: "Typo" },
                { relation: "replaced_by", event: unavailable("event"), reason: null },
            ],
        })
        expect(screen.getByRole("link", { name: "Session 4" })).toHaveAttribute(
            "href",
            "/app/c1/sessions/s1",
        )
        const related = screen.getByRole("list", { name: "Related events" })
        expect(within(related).getByText(/Reason: Typo/)).toBeInTheDocument()
        expect(within(related).getByText(/an event that is not available/)).toBeInTheDocument()
    })

    it("renders the generic fallback for an unsupported family without breaking", () => {
        renderDetail(base)
        expect(screen.getByText("Common Reckoning: Year 3")).toBeInTheDocument()
        expect(screen.queryByRole("list")).toBeNull()
    })

    it("keeps the compact form to a sentence and the in-world time, and reuses the travel lines", () => {
        const { container } = render(
            <MemoryRouter>
                <EventExplanation
                    explanation={{
                        ...base,
                        family: "travel",
                        travel: {
                            legs: [
                                {
                                    traveler: { entity_id: "a", name: "Aldric" },
                                    from: { state: "unrecorded", entity_id: null, name: null },
                                    to: { state: "named", entity_id: "l", name: "Southmark" },
                                },
                            ],
                        },
                    }}
                />
            </MemoryRouter>,
        )
        expect(
            screen.getByText("Aldric: arrived at Southmark (no earlier location recorded)"),
        ).toBeInTheDocument()
        expect(screen.getByText("In-world: Common Reckoning: Year 3")).toBeInTheDocument()
        expect(container.querySelector("time")).toBeNull()
        expect(screen.queryByText("Recorded")).toBeNull()
    })
})

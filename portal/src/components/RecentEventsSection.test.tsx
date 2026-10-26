import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import type { RecentCampaignEvent } from "../types/campaignSummary"
import type { EventExplanation } from "../types/eventExplanation"
import { RecentEventsSection } from "./RecentEventsSection"

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

function makeEvent(id: string, overrides: Partial<RecentCampaignEvent> = {}): RecentCampaignEvent {
    return {
        event_id: id,
        name: `Event ${id}`,
        summary: `Summary ${id}`,
        event_type_code: "other",
        event_status_code: "recorded",
        world_time_id: `time-${id}`,
        world_time_display: `Year ${id}`,
        details: null,
        ...overrides,
    }
}

const selectedTitle = () => screen.getByRole("heading", { level: 3 })

describe("RecentEventsSection", () => {
    it("selects the first event, switches on click, and never shows ids", () => {
        render(
            <RecentEventsSection
                events={[makeEvent("1"), makeEvent("2", { world_time_display: null })]}
            />,
        )

        expect(selectedTitle()).toHaveTextContent("Event 1")
        expect(screen.getByRole("button", { name: /Event 1/ })).toHaveAttribute("aria-current", "true")

        fireEvent.click(screen.getByRole("button", { name: /Event 2/ }))

        expect(selectedTitle()).toHaveTextContent("Event 2")
        expect(screen.getByRole("button", { name: /Event 1/ })).not.toHaveAttribute("aria-current")
        expect(screen.getAllByText("World time unassigned")).toHaveLength(2)
        expect(screen.queryByText(/time-/)).not.toBeInTheDocument()
    })

    it("shows details once, only when they add to the summary", () => {
        const { rerender } = render(
            <RecentEventsSection events={[makeEvent("1", { summary: "Same", details: "Same" })]} />,
        )
        expect(screen.getAllByText("Same")).toHaveLength(1)

        rerender(
            <RecentEventsSection events={[makeEvent("1", { summary: "Short", details: "Long account" })]} />,
        )
        expect(screen.getByText("Short")).toBeInTheDocument()
        expect(screen.getByText("Long account")).toBeInTheDocument()

        rerender(<RecentEventsSection events={[makeEvent("1", { summary: null, details: null })]} />)
        expect(screen.getByText("No event description is available.")).toBeInTheDocument()
    })

    it("keeps the implicit initial selection when events are prepended or reordered", () => {
        const { rerender } = render(<RecentEventsSection events={[makeEvent("1"), makeEvent("2")]} />)

        rerender(<RecentEventsSection events={[makeEvent("0"), makeEvent("1"), makeEvent("2")]} />)
        expect(selectedTitle()).toHaveTextContent("Event 1")

        rerender(<RecentEventsSection events={[makeEvent("2"), makeEvent("0"), makeEvent("1")]} />)
        expect(selectedTitle()).toHaveTextContent("Event 1")
    })

    it("keeps an explicit selection on refresh and adopts the first event when it disappears", () => {
        const { rerender } = render(
            <RecentEventsSection events={[makeEvent("1"), makeEvent("2"), makeEvent("3")]} />,
        )
        fireEvent.click(screen.getByRole("button", { name: /Event 2/ }))

        rerender(<RecentEventsSection events={[makeEvent("0"), makeEvent("2"), makeEvent("3")]} />)
        expect(selectedTitle()).toHaveTextContent("Event 2")

        rerender(<RecentEventsSection events={[makeEvent("0"), makeEvent("3")]} />)
        expect(selectedTitle()).toHaveTextContent("Event 0")
    })

    it("does not restore a removed selection when its id reappears", () => {
        const { rerender } = render(
            <RecentEventsSection events={[makeEvent("1"), makeEvent("2"), makeEvent("3")]} />,
        )
        fireEvent.click(screen.getByRole("button", { name: /Event 3/ }))

        rerender(<RecentEventsSection events={[makeEvent("1"), makeEvent("2")]} />)
        expect(selectedTitle()).toHaveTextContent("Event 1")

        rerender(<RecentEventsSection events={[makeEvent("1"), makeEvent("2"), makeEvent("3")]} />)
        expect(selectedTitle()).toHaveTextContent("Event 1")
    })

    it("clears the panel when no events remain and selects fresh when refilled", () => {
        const { rerender } = render(<RecentEventsSection events={[makeEvent("1"), makeEvent("2")]} />)
        fireEvent.click(screen.getByRole("button", { name: /Event 2/ }))

        rerender(<RecentEventsSection events={[]} />)
        expect(screen.getByText("No recent events are available.")).toBeInTheDocument()
        expect(screen.queryByRole("heading", { level: 3 })).not.toBeInTheDocument()

        rerender(<RecentEventsSection events={[makeEvent("1"), makeEvent("2")]} />)
        expect(selectedTitle()).toHaveTextContent("Event 1")
    })

    it("adds one compact sentence per explained row and the same sentence in the detail", () => {
        render(
            <RecentEventsSection
                events={[makeEvent("1", { explanation: joinExplanation }), makeEvent("2")]}
            />,
        )
        const row = screen.getByRole("button", { name: /Event 1/ })
        expect(row).toHaveTextContent("Aldric joined The Company.")
        expect(screen.getByRole("button", { name: /Event 2/ })).not.toHaveTextContent("joined")
        // The detail shows the sentence once, without repeating the in-world time or links.
        expect(screen.getAllByText("Aldric joined The Company.")).toHaveLength(2)
        expect(screen.queryByRole("link")).toBeNull()
        expect(screen.queryByText(/In-world:/)).toBeNull()
    })

    it("leaves an event with no adapter as before", () => {
        render(
            <RecentEventsSection
                events={[makeEvent("1", { explanation: { ...joinExplanation, family: "other" } })]}
            />,
        )
        expect(screen.getByRole("button", { name: /Event 1/ })).not.toHaveTextContent("joined")
        expect(screen.getByText("Summary 1")).toBeInTheDocument()
    })
})

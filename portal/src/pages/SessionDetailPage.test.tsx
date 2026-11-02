import { fireEvent, screen, within } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { renderAuthoringRoutes } from "../test/authoringHarness"
import { bootstrapFor } from "../test/campaignRoutes"
import type { CampaignSessionDetail } from "../types/campaignSession"
import { SessionDetailPage } from "./SessionDetailPage"

const sessionFixture = {
    session_id: "session-12",
    session_number: 12,
    title: "The Glass Ossuary",
    status_code: "ended",
    started_at: "2026-08-30T18:00:00Z",
    ended_at: "2026-08-30T22:00:00Z",
    summary: "The party entered the dormant facility.",
    start_world_time_id: "world-time-start",
    end_world_time_id: "world-time-end",
    events: [
        {
            event_id: "event-zeta",
            name: "Zeta Event",
            summary: "The first authorized event.",
            event_type_code: "discovery",
            event_status_code: "resolved",
            world_time_id: "world-time-1",
            details: "The party crossed the threshold.",
        },
        {
            event_id: "event-alpha",
            name: "Alpha Event",
            summary: "The second authorized event.",
            event_type_code: "decision",
            event_status_code: "resolved",
            world_time_id: "world-time-2",
            details: "The party activated the mechanism.",
        },
    ],
} satisfies CampaignSessionDetail

const editable: CampaignSessionDetail = {
    ...sessionFixture,
    status_code: "active",
    started_at: null,
    ended_at: null,
    scheduled_for: null,
    play_status: "unscheduled",
    row_version: 3,
    available_actions: ["update", "archive"],
}

function renderSessionDetail(
    session: CampaignSessionDetail,
    capabilities: string[] = ["campaign.view"],
) {
    return renderAuthoringRoutes({
        initialEntry: `/app/mundivita/sessions/${session.session_id}`,
        bootstrap: bootstrapFor(capabilities),
        routes: [
            {
                path: "/app/:campaignId/sessions/:sessionId",
                element: (
                    <SessionDetailPage
                        campaignId="mundivita"
                        session={session}
                        refresh={() => Promise.resolve(true)}
                    />
                ),
            },
        ],
    })
}

describe("SessionDetailPage", () => {
    it("renders the details, overview and events in server order for a viewer", () => {
        const { container } = renderSessionDetail(sessionFixture)

        expect(
            screen.getByRole("heading", { level: 1, name: "The Glass Ossuary" }),
        ).toBeInTheDocument()
        expect(screen.getByLabelText("Summary")).toHaveValue(
            "The party entered the dormant facility.",
        )
        expect(screen.getAllByText("The party entered the dormant facility.")).toHaveLength(1)
        expect(container.querySelector('time[datetime="2026-08-30T18:00:00Z"]')).toBeInTheDocument()
        expect(container.querySelector('time[datetime="2026-08-30T22:00:00Z"]')).toBeInTheDocument()

        const eventTable = screen.getByRole("table", { name: "Session events" })
        const names = within(eventTable)
            .getAllByRole("row")
            .slice(1)
            .map((row) => within(row).getAllByRole("cell")[0]?.textContent)
        expect(names).toEqual(["Zeta Event", "Alpha Event"])
        expect(screen.getByText("The party crossed the threshold.")).toBeInTheDocument()
        expect(screen.getByRole("link", { name: "Back to sessions" })).toHaveAttribute(
            "href",
            "/app/mundivita/sessions",
        )
    })

    it("shows a viewer the same fields read-only, with no way to submit", () => {
        renderSessionDetail(sessionFixture)
        for (const label of ["Title", "Planned start", "Summary"]) {
            expect(screen.getByLabelText(label)).toHaveAttribute("readonly")
        }
        fireEvent.change(screen.getByLabelText("Summary"), { target: { value: "tampered" } })
        fireEvent.submit(screen.getByRole("form", { name: "Session details" }))
        expect(screen.queryByRole("button", { name: "Save" })).toBeNull()
        expect(screen.getByText(/do not have permission to edit/)).toBeInTheDocument()
    })

    it("renders safe fallbacks for an untitled session with missing optional data", () => {
        renderSessionDetail({
            ...sessionFixture,
            session_id: "session-13",
            session_number: 13,
            title: null,
            started_at: null,
            ended_at: null,
            summary: null,
            start_world_time_id: null,
            end_world_time_id: null,
            events: [],
        })
        expect(screen.getByRole("heading", { level: 1, name: "Session 13" })).toBeInTheDocument()
        expect(screen.getAllByText("Not recorded")).toHaveLength(2)
        expect(screen.getByLabelText("Summary")).toHaveValue("")
        expect(screen.getByText("No events are recorded for this session.")).toBeInTheDocument()
        expect(screen.queryByRole("table")).not.toBeInTheDocument()
    })

    it("lets an editor change a field and offers Save and Discard changes", () => {
        renderSessionDetail(editable, ["canon.edit"])
        expect(screen.getByLabelText("Title")).not.toHaveAttribute("readonly")
        expect(screen.queryByRole("button", { name: "Save" })).toBeNull()
        fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Renamed" } })
        expect(screen.getByRole("button", { name: "Save" })).toBeEnabled()
        fireEvent.click(screen.getByRole("button", { name: "Discard changes" }))
        expect(screen.getByLabelText("Title")).toHaveValue("The Glass Ossuary")
        expect(screen.queryByRole("button", { name: "Save" })).toBeNull()
    })

    it("does not grant editing from the capability when the update action is missing", () => {
        renderSessionDetail({ ...editable, available_actions: ["archive"] }, ["canon.edit"])
        expect(screen.getByLabelText("Title")).toHaveAttribute("readonly")
        expect(screen.getByLabelText("Summary")).toHaveAttribute("readonly")
        expect(screen.getByText("This session cannot be edited right now.")).toBeInTheDocument()
    })

    it("does not grant editing when action metadata is absent entirely", () => {
        renderSessionDetail(
            { ...editable, available_actions: undefined, row_version: undefined },
            ["canon.edit"],
        )
        expect(screen.getByLabelText("Title")).toHaveAttribute("readonly")
        expect(screen.getByLabelText("Planned start")).toHaveAttribute("readonly")
    })

    it("does not grant editing from the update action without the capability", () => {
        renderSessionDetail(editable, ["campaign.view"])
        expect(screen.getByLabelText("Title")).toHaveAttribute("readonly")
        expect(screen.queryByRole("button", { name: "Archive session" })).toBeNull()
    })

    it("locks the planned start of a started session but keeps title and summary editable", () => {
        renderSessionDetail(
            {
                ...editable,
                started_at: "2026-10-12T19:30:00Z",
                scheduled_for: "2026-10-12T19:30:00Z",
                play_status: "in_progress",
                available_actions: ["update"],
            },
            ["canon.edit"],
        )
        expect(screen.getByLabelText("Planned start")).toHaveAttribute("readonly")
        expect(screen.getByLabelText("Title")).not.toHaveAttribute("readonly")
        expect(screen.getByLabelText("Summary")).not.toHaveAttribute("readonly")
        expect(
            screen.getByText(/has started, so its planned start cannot change/),
        ).toBeInTheDocument()
        expect(screen.getByText("End the session before archiving it.")).toBeInTheDocument()
    })

    it("shows an archived session read-only and offers Restore only when authorized", () => {
        const archived: CampaignSessionDetail = {
            ...editable,
            status_code: "archived",
            available_actions: ["update", "restore"],
        }
        const { unmount } = renderSessionDetail(archived, ["canon.edit"])
        expect(screen.getByLabelText("Title")).toHaveAttribute("readonly")
        expect(screen.getByText(/archived, so its fields are read-only/)).toBeInTheDocument()
        expect(screen.getByRole("button", { name: "Restore session" })).toBeInTheDocument()
        unmount()

        renderSessionDetail(archived, ["campaign.view"])
        expect(screen.queryByRole("button", { name: "Restore session" })).toBeNull()
    })
    it("shows in-world time and readable travel in the events table, without a GM note for a viewer", () => {
        const travelEvent = {
            event_id: "event-travel",
            name: "Characters traveled",
            summary: null,
            event_type_code: "characters_traveled",
            event_status_code: "recorded",
            world_time_id: "world-time-3",
            world_time: "Year 2, Day 9",
            details: null,
        }
        const entry = {
            event_id: "event-travel",
            world_time_id: "world-time-3",
            world_time: "Year 2, Day 9",
            note: null,
            legs: [
                {
                    traveler: { entity_id: "a", name: "Aldric" },
                    from: { state: "named" as const, entity_id: "l1", name: "Northmark" },
                    to: { state: "named" as const, entity_id: "l2", name: "Southmark" },
                },
            ],
        }
        renderSessionDetail({ ...sessionFixture, events: [travelEvent], travel: [entry] })
        const table = screen.getByRole("table", { name: "Session events" })
        expect(within(table).getByRole("columnheader", { name: /In-world time/ })).toBeInTheDocument()
        expect(within(table).getByText("Year 2, Day 9")).toBeInTheDocument()
        expect(within(table).getByText("Aldric: Northmark to Southmark")).toBeInTheDocument()
        expect(within(table).queryByText(/GM notes/)).toBeNull()
    })
})

describe("SessionDetailPage participants", () => {
    const stint = (id: string, name: string, kind: "npc" | "player_character", role: string, removed: string | null = null) => ({
        session_participant_id: id,
        character_id: `c-${name}`,
        character_name: name,
        character_kind: kind,
        participation_role: role as "player_character" | "npc" | "guest",
        added_at: "2026-10-12T19:00:00Z",
        removed_at: removed,
    })
    const withRoster = (extra: Partial<CampaignSessionDetail>): CampaignSessionDetail => ({
        ...editable,
        participants: [
            stint("p1", "Aldric", "player_character", "player_character"),
            stint("p2", "Mira", "npc", "npc", "2026-10-12T20:00:00Z"),
            stint("p3", "Mira", "npc", "guest"),
        ],
        ...extra,
    })
    const runLink = () => screen.queryByRole("link", { name: "Change participants in Run session" })

    it("shows the shared read-only roster, with the same row details as Run, and no controls", () => {
        renderSessionDetail(withRoster({ play_status: "scheduled", available_actions: ["update", "start", "manage_participants", "archive"] }), ["canon.edit"])
        const section = screen.getByRole("region", { name: "Participants" })
        const rows = within(section).getAllByRole("listitem")
        expect(rows).toHaveLength(3)
        expect(rows[0]).toHaveTextContent("Aldric (Player character; role: Player character). Present.")
        expect(rows[1]).toHaveTextContent("Mira (NPC; role: Guest). Present.")
        expect(rows[2]).toHaveTextContent("Mira (NPC; role: NPC). Left.")
        expect(within(section).queryByRole("button")).toBeNull()
        expect(within(section).queryByRole("combobox")).toBeNull()
    })

    it("links to Run only where the server offers a play action, and for running sessions too", () => {
        const { unmount } = renderSessionDetail(
            withRoster({ play_status: "scheduled", available_actions: ["update", "start", "manage_participants", "archive"] }),
            ["canon.edit"],
        )
        expect(runLink()).toHaveAttribute("href", "/app/mundivita/sessions/session-12/run?section=participants")
        unmount()
        const running = renderSessionDetail(
            withRoster({ play_status: "in_progress", available_actions: ["update", "manage_participants", "log", "end"] }),
            ["canon.edit"],
        )
        expect(runLink()).toBeInTheDocument()
        running.unmount()
        // A completed session keeps its roster but offers no Run link.
        renderSessionDetail(withRoster({ play_status: "completed", available_actions: ["update", "archive"] }), ["canon.edit"])
        expect(within(screen.getByRole("region", { name: "Participants" })).getAllByRole("listitem")).toHaveLength(3)
        expect(runLink()).toBeNull()
    })

    it("shows a member only the participants returned, linking only those the server says open", () => {
        renderSessionDetail({
            ...sessionFixture,
            participants: [
                { ...stint("p1", "Aldric", "player_character", "player_character"), can_open_character: true },
                { ...stint("p3", "Mira", "npc", "guest"), can_open_character: false },
            ],
        })
        const section = screen.getByRole("region", { name: "Participants" })
        const rows = within(section).getAllByRole("listitem")
        expect(rows).toHaveLength(2)
        expect(rows[0]).toHaveTextContent("Aldric (Player character; role: Player character). Present.")
        expect(within(rows[0]).getByRole("link", { name: "Aldric" })).toBeInTheDocument()
        expect(rows[1]).toHaveTextContent("Mira (NPC; role: Guest). Present.")
        expect(within(rows[1]).queryByRole("link")).toBeNull()
        expect(within(section).queryByRole("button")).toBeNull()
        expect(within(section).queryByRole("combobox")).toBeNull()
        expect(section).not.toHaveTextContent(/hidden|\d+ (more|others)/i)
        expect(runLink()).toBeNull()
    })

    it("tells a member with no visible participants so, without implying anyone is hidden", () => {
        renderSessionDetail({ ...sessionFixture, participants: [] })
        const section = screen.getByRole("region", { name: "Participants" })
        expect(within(section).getByText("No participants in this session are visible to you.")).toBeInTheDocument()
        expect(within(section).queryByRole("listitem")).toBeNull()
    })

    it("keeps the GM's empty roster wording", () => {
        renderSessionDetail(withRoster({ participants: [] }), ["canon.edit"])
        expect(within(screen.getByRole("region", { name: "Participants" })).getByText("No one is in this session yet.")).toBeInTheDocument()
    })

    it("shows no roster to a member, whose response carries none", () => {
        renderSessionDetail({ ...sessionFixture, participants: null })
        expect(screen.queryByRole("region", { name: "Participants" })).toBeNull()
        expect(runLink()).toBeNull()
    })
})

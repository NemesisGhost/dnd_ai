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
})

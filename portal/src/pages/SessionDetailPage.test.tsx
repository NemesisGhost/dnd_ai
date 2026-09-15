import {
    render,
    screen,
    within,
} from "@testing-library/react"
import {
    MemoryRouter,
    Route,
    Routes,
} from "react-router"
import {
    describe,
    expect,
    it,
} from "vitest"
import type {
    CampaignSessionDetail,
} from "../types/campaignSession"
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

function renderSessionDetail(
    session: CampaignSessionDetail,
) {
    return render(
        <MemoryRouter
            initialEntries={[
                `/app/test-campaign/sessions/${session.session_id}`,
            ]}
        >
            <Routes>
                <Route
                    path="/app/:campaignId/sessions/:sessionId"
                    element={
                        <SessionDetailPage session={session} />
                    }
                />
            </Routes>
        </MemoryRouter>,
    )
}

describe("SessionDetailPage", () => {
    it("renders authorized session details and preserves the server event order", () => {
        const { container } =
            renderSessionDetail(sessionFixture)

        expect(
            screen.getByRole("heading", {
                level: 1,
                name: "The Glass Ossuary",
            }),
        ).toBeInTheDocument()

        expect(
            screen.getByText(
                "The party entered the dormant facility.",
            ),
        ).toBeInTheDocument()

        expect(
            screen.getByText(
                "The party crossed the threshold.",
            ),
        ).toBeInTheDocument()

        expect(
            screen.getByText(
                "The party activated the mechanism.",
            ),
        ).toBeInTheDocument()

        expect(
            container.querySelector(
                'time[datetime="2026-08-30T18:00:00Z"]',
            ),
        ).toBeInTheDocument()

        expect(
            container.querySelector(
                'time[datetime="2026-08-30T22:00:00Z"]',
            ),
        ).toBeInTheDocument()

        const eventTable = screen.getByRole("table", {
            name: "Session events",
        })

        const eventRows =
            within(eventTable).getAllByRole("row").slice(1)

        const eventNames = eventRows.map((row) =>
            within(row).getAllByRole("cell")[0]?.textContent,
        )

        expect(eventNames).toEqual([
            "Zeta Event",
            "Alpha Event",
        ])

        expect(
            screen.getByRole("link", {
                name: "Back to sessions",
            }),
        ).toHaveAttribute(
            "href",
            "/app/test-campaign/sessions",
        )
    })

    it("renders safe fallbacks for an untitled session with missing optional data", () => {
        const sessionWithoutOptionalData = {
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
        } satisfies CampaignSessionDetail

        renderSessionDetail(
            sessionWithoutOptionalData,
        )

        expect(
            screen.getByRole("heading", {
                level: 1,
                name: "Session 13",
            }),
        ).toBeInTheDocument()

        expect(
            screen.getAllByText("Not recorded"),
        ).toHaveLength(2)

        expect(
            screen.getByText(
                "No summary is recorded for this session.",
            ),
        ).toBeInTheDocument()

        expect(
            screen.getByText(
                "No events are recorded for this session.",
            ),
        ).toBeInTheDocument()

        expect(
            screen.queryByRole("table"),
        ).not.toBeInTheDocument()
    })
})
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
import type { CampaignSessionListItem } from "../types/campaignSession"
import { SessionsPage } from "./SessionsPage"

const sessions: CampaignSessionListItem[] = [
    {
        session_id: "older-session",
        session_number: 1,
        title: "The Older Session",
        status_code: "completed",
        started_at: "2026-01-01T18:00:00Z",
        ended_at: "2026-01-01T22:00:00Z",
    },
    {
        session_id: "not-started-session",
        session_number: 3,
        title: "The Unscheduled Session",
        status_code: "planned",
        started_at: null,
        ended_at: null,
    },
    {
        session_id: "newer-session",
        session_number: 2,
        title: "The Newer Session",
        status_code: "completed",
        started_at: "2026-02-01T18:00:00Z",
        ended_at: "2026-02-01T22:00:00Z",
    },
]

function renderSessionsPage(
    pageSessions: CampaignSessionListItem[],
) {
    render(
        <MemoryRouter
            initialEntries={["/app/test-campaign/sessions"]}
        >
            <Routes>
                <Route
                    path="/app/:campaignId/sessions"
                    element={<SessionsPage sessions={pageSessions} />}
                />
            </Routes>
        </MemoryRouter>,
    )
}

describe("SessionsPage", () => {
    it("shows an empty state when no sessions are available", () => {
        renderSessionsPage([])

        expect(
            screen.getByRole("heading", { name: "Sessions" }),
        ).toBeInTheDocument()

        expect(
            screen.getByText(
                "No sessions are available for this campaign.",
            ),
        ).toBeInTheDocument()

        expect(
            screen.queryByRole("table"),
        ).not.toBeInTheDocument()
    })

    it("initially sorts sessions by descending start time with missing timestamps last", () => {
        renderSessionsPage(sessions)

        const table = screen.getByRole("table", {
            name: "Sessions",
        })

        const links = within(table).getAllByRole("link")

        expect(
            links.map((link) => link.textContent),
        ).toEqual([
            "The Newer Session",
            "The Older Session",
            "The Unscheduled Session",
        ])
    })

    it("links each session to its campaign-relative detail route", () => {
        renderSessionsPage(sessions)

        expect(
            screen.getByRole("link", {
                name: "The Newer Session",
            }),
        ).toHaveAttribute(
            "href",
            "/app/test-campaign/sessions/newer-session",
        )
    })
})
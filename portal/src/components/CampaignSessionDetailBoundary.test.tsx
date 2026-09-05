import {
    fireEvent,
    render,
    screen,
} from "@testing-library/react"
import {
    beforeEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import type {
    CampaignSessionDetail,
} from "../types/campaignSession"
import {
    CampaignSessionDetailBoundary,
} from "./CampaignSessionDetailBoundary"

const {
    retryMock,
    useCampaignSessionMock,
} = vi.hoisted(() => ({
    retryMock: vi.fn(),
    useCampaignSessionMock: vi.fn(),
}))

vi.mock("../hooks/useCampaignSession", () => ({
    useCampaignSession: useCampaignSessionMock,
}))

const sessionFixture: CampaignSessionDetail = {
    session_id: "session-a",
    session_number: 1,
    title: "The Glass Ossuary",
    status_code: "ended",
    started_at: "2026-01-01T18:00:00Z",
    ended_at: "2026-01-01T22:00:00Z",
    summary: "The party entered the dormant facility.",
    start_world_time_id: "world-time-start",
    end_world_time_id: "world-time-end",
    events: [],
}

function renderBoundary() {
    render(
        <CampaignSessionDetailBoundary
            campaignId="campaign-a"
            sessionId="session-a"
        >
            {(session) => (
                <p>{session.title}</p>
            )}
        </CampaignSessionDetailBoundary>,
    )
}

beforeEach(() => {
    retryMock.mockReset()
    useCampaignSessionMock.mockReset()
})

describe("CampaignSessionDetailBoundary", () => {
    it("shows a loading state without rendering session content", () => {
        useCampaignSessionMock.mockReturnValue({
            state: {
                status: "loading",
            },
            retry: retryMock,
        })

        renderBoundary()

        expect(
            screen.getByRole("heading", {
                name: "Loading session",
            }),
        ).toBeInTheDocument()

        expect(
            screen.queryByText("The Glass Ossuary"),
        ).not.toBeInTheDocument()

        expect(
            useCampaignSessionMock,
        ).toHaveBeenCalledWith(
            "campaign-a",
            "session-a",
        )
    })

    it("shows a non-disclosing unavailable state", () => {
        useCampaignSessionMock.mockReturnValue({
            state: {
                status: "unavailable",
            },
            retry: retryMock,
        })

        renderBoundary()

        expect(
            screen.getByRole("heading", {
                name: "Session unavailable",
            }),
        ).toBeInTheDocument()

        expect(
            screen.getByText(
                "The requested session information is not available.",
            ),
        ).toBeInTheDocument()

        expect(
            screen.queryByText("The Glass Ossuary"),
        ).not.toBeInTheDocument()
    })

    it("shows a safe recoverable error and retries", () => {
        const diagnosticError = new Error(
            "Database connection failed for internal host",
        )

        useCampaignSessionMock.mockReturnValue({
            state: {
                status: "error",
                error: diagnosticError,
            },
            retry: retryMock,
        })

        renderBoundary()

        expect(
            screen.getByRole("heading", {
                name: "Session information unavailable",
            }),
        ).toBeInTheDocument()

        expect(
            screen.queryByText(diagnosticError.message),
        ).not.toBeInTheDocument()

        expect(
            screen.queryByText("The Glass Ossuary"),
        ).not.toBeInTheDocument()

        fireEvent.click(
            screen.getByRole("button", {
                name: "Try again",
            }),
        )

        expect(retryMock).toHaveBeenCalledTimes(1)
    })

    it("renders session content after a successful request", () => {
        useCampaignSessionMock.mockReturnValue({
            state: {
                status: "success",
                session: sessionFixture,
            },
            retry: retryMock,
        })

        renderBoundary()

        expect(
            screen.getByText("The Glass Ossuary"),
        ).toBeInTheDocument()

        expect(
            screen.queryByRole("button", {
                name: "Try again",
            }),
        ).not.toBeInTheDocument()
    })
})
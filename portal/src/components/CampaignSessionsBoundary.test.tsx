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
    CampaignSessionListItem,
} from "../types/campaignSession"
import { CampaignSessionsBoundary } from "./CampaignSessionsBoundary"

const {
    retryMock,
    useCampaignSessionsMock,
} = vi.hoisted(() => ({
    retryMock: vi.fn(),
    useCampaignSessionsMock: vi.fn(),
}))

vi.mock("../hooks/useCampaignSessions", () => ({
    useCampaignSessions:
        useCampaignSessionsMock,
}))

const sessionsFixture: CampaignSessionListItem[] = [
    {
        session_id: "session-12",
        session_number: 12,
        title: "The Glass Ossuary",
        status_code: "ended",
        started_at: "2026-08-30T18:00:00Z",
        ended_at: "2026-08-30T22:00:00Z",
    },
]

function renderBoundary() {
    render(
        <CampaignSessionsBoundary campaignId="campaign-a" >
    {(sessions) =>(
        <p>
        { sessions.length } authorized session
    </p>
    )
}
</CampaignSessionsBoundary>,
  )
}

beforeEach(() => {
    retryMock.mockReset()
    useCampaignSessionsMock.mockReset()
})

describe("CampaignSessionsBoundary", () => {
    it("shows loading without rendering session content", () => {
        useCampaignSessionsMock.mockReturnValue({
            state: {
                status: "loading",
            },
            retry: retryMock,
        })

        renderBoundary()

        expect(
            screen.getByRole("heading", {
                name: "Loading sessions",
            }),
        ).toBeInTheDocument()

        expect(
            screen.queryByText("1 authorized session"),
        ).not.toBeInTheDocument()

        expect(
            useCampaignSessionsMock,
        ).toHaveBeenCalledWith("campaign-a")
    })

    it("shows a non-disclosing unavailable state", () => {
        useCampaignSessionsMock.mockReturnValue({
            state: {
                status: "unavailable",
            },
            retry: retryMock,
        })

        renderBoundary()

        expect(
            screen.getByRole("heading", {
                name: "Sessions unavailable",
            }),
        ).toBeInTheDocument()

        expect(
            screen.getByText(
                "The requested session information is not available.",
            ),
        ).toBeInTheDocument()

        expect(
            screen.queryByText("1 authorized session"),
        ).not.toBeInTheDocument()
    })

    it("shows a safe recoverable error and retries", () => {
        const diagnosticError = new Error(
            "Internal database connection failed",
        )

        useCampaignSessionsMock.mockReturnValue({
            state: {
                status: "error",
                error: diagnosticError,
            },
            retry: retryMock,
        })

        renderBoundary()

        expect(
            screen.getByRole("heading", {
                name: "Sessions unavailable",
            }),
        ).toBeInTheDocument()

        expect(
            screen.queryByText(diagnosticError.message),
        ).not.toBeInTheDocument()

        fireEvent.click(
            screen.getByRole("button", {
                name: "Try again",
            }),
        )

        expect(retryMock).toHaveBeenCalledTimes(1)
    })

    it("delivers an authorized session list to its child", () => {
        useCampaignSessionsMock.mockReturnValue({
            state: {
                status: "success",
                sessions: sessionsFixture,
            },
            retry: retryMock,
        })

        renderBoundary()

        expect(
            screen.getByText("1 authorized session"),
        ).toBeInTheDocument()

        expect(
            screen.queryByRole("button", {
                name: "Try again",
            }),
        ).not.toBeInTheDocument()
    })
})
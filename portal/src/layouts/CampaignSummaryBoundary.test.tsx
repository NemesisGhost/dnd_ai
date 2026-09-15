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
import { useCampaignSummary } from "../hooks/useCampaignSummary"
import type { CampaignSummary } from "../types/campaignSummary"
import { CampaignSummaryBoundary } from "./CampaignSummaryBoundary"

vi.mock("../hooks/useCampaignSummary", () => ({
    useCampaignSummary: vi.fn(),
}))

const useCampaignSummaryMock =
    vi.mocked(useCampaignSummary)

const campaignSummaryFixture = {
    current_session: null,
    previous_session_recap:
        "The party entered the dormant facility.",
    recent_events: [],
} satisfies CampaignSummary

function renderBoundary() {
    return render(
        <CampaignSummaryBoundary campaignId="campaign-a">
            {(summary) => (
                <p>{summary.previous_session_recap}</p>
            )}
        </CampaignSummaryBoundary>,
    )
}

beforeEach(() => {
    useCampaignSummaryMock.mockReset()
})

describe("CampaignSummaryBoundary", () => {
    it("hides campaign data while loading", () => {
        useCampaignSummaryMock.mockReturnValue({
            state: {
                status: "loading",
            },
            retry: vi.fn(),
        })

        renderBoundary()

        expect(
            screen.getByRole("heading", {
                name: "Loading campaign",
            }),
        ).toBeInTheDocument()

        expect(
            screen.queryByText(
                "The party entered the dormant facility.",
            ),
        ).not.toBeInTheDocument()
    })

    it("shows the same safe state for unavailable information", () => {
        useCampaignSummaryMock.mockReturnValue({
            state: {
                status: "unavailable",
            },
            retry: vi.fn(),
        })

        renderBoundary()

        expect(
            screen.getByRole("heading", {
                name: "Campaign information unavailable",
            }),
        ).toBeInTheDocument()

        expect(
            screen.getByText(
                "The requested campaign information is unavailable or you do not have access to it.",
            ),
        ).toBeInTheDocument()

        expect(
            screen.queryByText(
                "The party entered the dormant facility.",
            ),
        ).not.toBeInTheDocument()
    })

    it("shows a safe recoverable error and retries", () => {
        const retry = vi.fn()

        useCampaignSummaryMock.mockReturnValue({
            state: {
                status: "error",
                error: new Error(
                    "Sensitive backend diagnostic",
                ),
            },
            retry,
        })

        renderBoundary()

        expect(
            screen.getByRole("heading", {
                name: "Campaign information unavailable",
            }),
        ).toBeInTheDocument()

        expect(
            screen.queryByText(
                "Sensitive backend diagnostic",
            ),
        ).not.toBeInTheDocument()

        expect(
            screen.queryByText(
                "The party entered the dormant facility.",
            ),
        ).not.toBeInTheDocument()

        fireEvent.click(
            screen.getByRole("button", {
                name: "Try again",
            }),
        )

        expect(retry).toHaveBeenCalledTimes(1)
    })

    it("renders campaign data only after success", () => {
        useCampaignSummaryMock.mockReturnValue({
            state: {
                status: "success",
                summary: campaignSummaryFixture,
            },
            retry: vi.fn(),
        })

        renderBoundary()

        expect(
            useCampaignSummaryMock,
        ).toHaveBeenCalledWith("campaign-a")

        expect(
            screen.getByText(
                "The party entered the dormant facility.",
            ),
        ).toBeInTheDocument()

        expect(
            screen.queryByRole("button", {
                name: "Try again",
            }),
        ).not.toBeInTheDocument()
    })
})
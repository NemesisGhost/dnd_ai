import {
    render,
    screen,
} from "@testing-library/react"
import {
    MemoryRouter,
    Route,
    Routes,
} from "react-router"
import {
    beforeEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import { useCampaignSummary } from "../hooks/useCampaignSummary"
import type { CampaignSummary } from "../types/campaignSummary"
import { CampaignHomePage } from "./CampaignHomePage"

vi.mock("../hooks/useCampaignSummary", () => ({
    useCampaignSummary: vi.fn(),
}))

const useCampaignSummaryMock =
    vi.mocked(useCampaignSummary)

const emptySummary = {
    current_session: null,
    previous_session_recap: null,
    recent_events: [],
} satisfies CampaignSummary

beforeEach(() => {
    useCampaignSummaryMock.mockReset()

    useCampaignSummaryMock.mockReturnValue({
        state: {
            status: "success",
            summary: emptySummary,
        },
        retry: vi.fn(),
    })
})

describe("CampaignHomePage", () => {
    it("loads and displays the requested campaign summary", () => {
        render(
            <MemoryRouter
                initialEntries={["/app/mundivita/home"]}
            >
                <Routes>
                    <Route
                        path="/app/:campaignId/home"
                        element={<CampaignHomePage />}
                    />
                </Routes>
            </MemoryRouter>,
        )

        expect(
            useCampaignSummaryMock,
        ).toHaveBeenCalledWith("mundivita")

        expect(
            screen.getByRole("heading", {
                level: 1,
                name: "Home",
            }),
        ).toBeInTheDocument()

        expect(
            screen.getByText(
                "No sessions have been recorded.",
            ),
        ).toBeInTheDocument()

        expect(
            screen.getByText(
                "No previous session recap is available.",
            ),
        ).toBeInTheDocument()
    })

    it("fails closed when no campaign route parameter exists", () => {
        render(
            <MemoryRouter initialEntries={["/home"]}>
                <CampaignHomePage />
            </MemoryRouter>,
        )

        expect(
            screen.getByRole("heading", {
                name: "Campaign information unavailable",
            }),
        ).toBeInTheDocument()

        expect(
            useCampaignSummaryMock,
        ).not.toHaveBeenCalled()
    })
})
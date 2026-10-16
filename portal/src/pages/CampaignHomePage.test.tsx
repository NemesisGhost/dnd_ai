import {
    fireEvent,
    render,
    screen,
} from "@testing-library/react"
import {
    Link,
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
                name: "Campaign Home",
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

    it("does not carry an event selection from one campaign to another", () => {
        const eventsFor = (campaign: string): CampaignSummary => ({
            ...emptySummary,
            recent_events: ["a", "b"].map((key) => ({
                event_id: `${campaign}-${key}`,
                name: `${campaign} event ${key}`,
                summary: null,
                event_type_code: "other",
                event_status_code: "recorded",
                world_time_id: `time-${campaign}-${key}`,
                world_time_display: null,
                details: null,
            })),
        })
        useCampaignSummaryMock.mockImplementation((id: string) => ({
            state: { status: "success", summary: eventsFor(id) },
            retry: vi.fn(),
        }))

        render(
            <MemoryRouter initialEntries={["/app/c1/home"]}>
                <Link to="/app/c2/home">go c2</Link>
                <Routes>
                    <Route path="/app/:campaignId/home" element={<CampaignHomePage />} />
                </Routes>
            </MemoryRouter>,
        )
        fireEvent.click(screen.getByRole("button", { name: /c1 event b/ }))
        expect(screen.getByRole("heading", { level: 3 })).toHaveTextContent("c1 event b")

        fireEvent.click(screen.getByText("go c2"))
        expect(screen.getByRole("heading", { level: 3 })).toHaveTextContent("c2 event a")
    })
})

import type { ReactNode } from "react"
import {
    MemoryRouter,
    Route,
    Routes,
} from "react-router"
import { render, screen } from "@testing-library/react"
import {
    beforeEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import type { CampaignAccessOverview } from "../types/accessOverview"
import { CampaignAccessPage } from "./CampaignAccessPage"

const { boundaryPropsSpy } = vi.hoisted(() => ({
    boundaryPropsSpy: vi.fn(),
}))

vi.mock(
    "../components/AccessOverviewBoundary",
    () => ({
        AccessOverviewBoundary: ({
            campaignId,
            children,
        }: {
            campaignId: string
            children: (
                overview: CampaignAccessOverview,
            ) => ReactNode
        }) => {
            boundaryPropsSpy(campaignId)
            return children({ members: [] })
        },
    }),
)

beforeEach(() => {
    boundaryPropsSpy.mockClear()
})

function renderPage(
    initialEntry = "/app/campaign-one/access",
) {
    render(
        <MemoryRouter initialEntries={[initialEntry]}>
            <Routes>
                <Route
                    path="/app/:campaignId/access"
                    element={<CampaignAccessPage />}
                />

                <Route
                    path="/access"
                    element={<CampaignAccessPage />}
                />
            </Routes>
        </MemoryRouter>,
    )
}

describe("CampaignAccessPage", () => {
    it("passes the active campaign ID to the boundary", () => {
        renderPage()

        expect(boundaryPropsSpy).toHaveBeenCalledWith(
            "campaign-one",
        )
    })

    it("does not request access data without a campaign ID", () => {
        renderPage("/access")

        expect(
            screen.getByRole("heading", {
                name: "Access unavailable",
            }),
        ).toBeInTheDocument()

        expect(
            boundaryPropsSpy,
        ).not.toHaveBeenCalled()
    })
})

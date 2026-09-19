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
import { SessionContext } from "../context/SessionContext"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import type { CampaignAccessOverview } from "../types/accessOverview"
import { CampaignAccessPage } from "./CampaignAccessPage"

const { boundaryPropsSpy, retryMock } = vi.hoisted(() => ({
    boundaryPropsSpy: vi.fn(),
    retryMock: vi.fn(),
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
                retry: () => void,
            ) => ReactNode
        }) => {
            boundaryPropsSpy(campaignId)
            return children(
                {
                    members: [],
                    assignable_roles: [],
                    assignable_characters: [],
                    assignable_relationship_types: [],
                },
                retryMock,
            )
        },
    }),
)

beforeEach(() => {
    boundaryPropsSpy.mockClear()
    retryMock.mockClear()
})

function renderPage(
    initialEntry = "/app/campaign-one/access",
) {
    render(
        <SessionContext.Provider
            value={{
                state: {
                    status: "authenticated",
                    bootstrap: sessionBootstrapFixture,
                },
                reload: vi.fn(),
            }}
        >
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
            </MemoryRouter>
        </SessionContext.Provider>,
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

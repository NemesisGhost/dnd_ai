import type { ReactNode } from "react"
import { MemoryRouter, Route, Routes } from "react-router"
import { render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { SessionContext } from "../context/SessionContext"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import type { CampaignAccessOverview } from "../types/accessOverview"
import { CampaignAccessAuditPage } from "./CampaignAccessAuditPage"

const { boundaryPropsSpy } = vi.hoisted(() => ({
    boundaryPropsSpy: vi.fn(),
}))

vi.mock("../components/AccessOverviewBoundary", () => ({
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
                members: [
                    { user_id: "user-1", display_name: "Player One" } as CampaignAccessOverview["members"][number],
                ],
                assignable_roles: [],
                assignable_characters: [],
                assignable_relationship_types: [],
                grantable_resource_capabilities: [],
                access_groups: [],
            },
            vi.fn(),
        )
    },
}))

function jsonResponse(body: unknown): Response {
    return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
    })
}

beforeEach(() => {
    boundaryPropsSpy.mockClear()
})

function renderPage(initialEntry = "/app/campaign-one/access/audit") {
    render(
        <SessionContext.Provider
            value={{
                state: { status: "authenticated", bootstrap: sessionBootstrapFixture },
                reload: vi.fn(),
            }}
        >
            <MemoryRouter initialEntries={[initialEntry]}>
                <Routes>
                    <Route
                        path="/app/:campaignId/access/audit"
                        element={<CampaignAccessAuditPage />}
                    />
                    <Route path="/access/audit" element={<CampaignAccessAuditPage />} />
                </Routes>
            </MemoryRouter>
        </SessionContext.Provider>,
    )
}

describe("CampaignAccessAuditPage", () => {
    it("passes the active campaign ID to the boundary and renders the audit history heading", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(
                jsonResponse({ items: [], next_cursor: null }),
            ),
        )

        renderPage()

        expect(boundaryPropsSpy).toHaveBeenCalledWith("campaign-one")
        await waitFor(() => {
            expect(
                screen.getByRole("heading", { level: 1, name: "Audit history" }),
            ).toBeInTheDocument()
        })

        vi.unstubAllGlobals()
    })

    it("does not request access data without a campaign ID", () => {
        renderPage("/access/audit")

        expect(
            screen.getByRole("heading", { name: "Access unavailable" }),
        ).toBeInTheDocument()
        expect(boundaryPropsSpy).not.toHaveBeenCalled()
    })

    it("supports a direct reload of the audit route and marks 'Audit history' as the current tab", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(
                jsonResponse({ items: [], next_cursor: null }),
            ),
        )

        renderPage()

        await waitFor(() => {
            expect(
                screen.getByRole("link", { name: "Audit history" }),
            ).toHaveAttribute("aria-current", "page")
        })
        expect(
            screen.getByRole("link", { name: "Access management" }),
        ).not.toHaveAttribute("aria-current")

        vi.unstubAllGlobals()
    })
})

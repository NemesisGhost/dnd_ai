import { MemoryRouter, Route, Routes } from "react-router"
import { render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { SessionContext } from "../context/SessionContext"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { CampaignInvitationsPage } from "./CampaignInvitationsPage"

function jsonResponse(body: unknown, status = 200): Response {
    return new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
    })
}

afterEach(() => {
    vi.unstubAllGlobals()
})

function renderPage(initialEntry = "/app/campaign-one/access/invitations") {
    return render(
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
                        path="/app/:campaignId/access/invitations"
                        element={<CampaignInvitationsPage />}
                    />
                    <Route
                        path="/access/invitations"
                        element={<CampaignInvitationsPage />}
                    />
                </Routes>
            </MemoryRouter>
        </SessionContext.Provider>,
    )
}

describe("CampaignInvitationsPage", () => {
    it("renders the Invitations heading as the sole page-level heading", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(jsonResponse({ invitations: [] })),
        )

        renderPage()

        await waitFor(() => {
            expect(
                screen.getAllByRole("heading", { level: 1 }),
            ).toHaveLength(1)
        })

        expect(
            screen.getByRole("heading", { level: 1, name: "Invitations" }),
        ).toBeInTheDocument()
    })

    it("does not request access data without a campaign ID", () => {
        const fetchMock = vi.fn()
        vi.stubGlobal("fetch", fetchMock)

        renderPage("/access/invitations")

        expect(
            screen.getByRole("heading", { name: "Access unavailable" }),
        ).toBeInTheDocument()
        expect(fetchMock).not.toHaveBeenCalled()
    })

    it("supports a direct reload of the invitations route and marks 'Invitations' as the current tab", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(jsonResponse({ invitations: [] })),
        )

        renderPage()

        await waitFor(() => {
            expect(
                screen.getByRole("link", { name: "Invitations" }),
            ).toHaveAttribute("aria-current", "page")
        })
        expect(
            screen.getByRole("link", { name: "Access management" }),
        ).not.toHaveAttribute("aria-current")
        expect(
            screen.getByRole("link", { name: "Audit history" }),
        ).not.toHaveAttribute("aria-current")
    })

    it("never requests /access-overview", async () => {
        const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ invitations: [] }))
        vi.stubGlobal("fetch", fetchMock)

        renderPage()

        await waitFor(() => {
            expect(fetchMock).toHaveBeenCalled()
        })

        const requestedUrls = fetchMock.mock.calls.map((call) => String(call[0]))
        expect(requestedUrls.every((url) => !url.includes("/access-overview"))).toBe(true)
    })
})

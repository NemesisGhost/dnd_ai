import { MemoryRouter, Route, Routes } from "react-router"
import { render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { SessionContext } from "../context/SessionContext"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { CampaignAccessAuditPage } from "./CampaignAccessAuditPage"

function jsonResponse(body: unknown, status = 200): Response {
    return new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
    })
}

const historyPage = { items: [], next_cursor: null }
const actorsFacet = {
    actors: [{ user_id: "user-1", display_name: "Player One" }],
}

// A single fetch mock that distinguishes the audit-history list request
// from the actors-facet request by URL -- exactly what a portal caller
// sees, and the shape every test below inspects to prove the audit route
// never reaches for /access-overview at all.
function stubFetch(overrides: {
    history?: () => Response
    actors?: () => Response
}): ReturnType<typeof vi.fn> {
    const fetchMock = vi.fn((input: string | URL | Request) => {
        const url = String(input)
        if (url.includes("/audit-history/actors")) {
            return Promise.resolve(overrides.actors?.() ?? jsonResponse(actorsFacet))
        }
        if (url.includes("/audit-history")) {
            return Promise.resolve(overrides.history?.() ?? jsonResponse(historyPage))
        }
        return Promise.reject(new Error(`unexpected fetch: ${url}`))
    })
    vi.stubGlobal("fetch", fetchMock)
    return fetchMock
}

beforeEach(() => {
    vi.unstubAllGlobals()
})

function renderPage(initialEntry = "/app/campaign-one/access/audit") {
    return render(
        <SessionContext.Provider
            value={{
                state: { status: "authenticated", bootstrap: sessionBootstrapFixture },
                reload: vi.fn(), refresh: vi.fn(),
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
    it("renders the audit history heading for the active campaign", async () => {
        stubFetch({})

        renderPage()

        await waitFor(() => {
            expect(
                screen.getByRole("heading", { level: 1, name: "Audit history" }),
            ).toBeInTheDocument()
        })
    })

    it("does not request access data without a campaign ID", () => {
        const fetchMock = stubFetch({})

        renderPage("/access/audit")

        expect(
            screen.getByRole("heading", { name: "Access unavailable" }),
        ).toBeInTheDocument()
        expect(fetchMock).not.toHaveBeenCalled()
    })

    it("supports a direct reload of the audit route and marks 'Audit history' as the current tab", async () => {
        stubFetch({})

        renderPage()

        await waitFor(() => {
            expect(
                screen.getByRole("link", { name: "Audit history" }),
            ).toHaveAttribute("aria-current", "page")
        })
        expect(
            screen.getByRole("link", { name: "Access management" }),
        ).not.toHaveAttribute("aria-current")
    })

    // --- Audit-actor-contract fix: no more /access-overview dependency ---

    it("never requests /access-overview, only audit history and the actor facet", async () => {
        const fetchMock = stubFetch({})

        renderPage()

        await waitFor(() => {
            expect(screen.getByLabelText("Actor")).toBeInTheDocument()
        })

        const requestedUrls = fetchMock.mock.calls.map((call) => String(call[0]))
        expect(requestedUrls.every((url) => !url.includes("/access-overview"))).toBe(true)
        expect(requestedUrls.some((url) => url.includes("/audit-history/actors"))).toBe(true)
        expect(
            requestedUrls.some(
                (url) => url.includes("/audit-history") && !url.includes("/actors"),
            ),
        ).toBe(true)
    })

    it("populates the actor filter from the actor facet's response", async () => {
        stubFetch({})

        renderPage()

        await waitFor(() => {
            expect(
                screen.getByRole("option", { name: "Player One" }),
            ).toBeInTheDocument()
        })
    })

    it("still renders audit history when the actor-facet request fails", async () => {
        stubFetch({ actors: () => jsonResponse({ detail: "denied" }, 403) })

        renderPage()

        await waitFor(() => {
            expect(
                screen.getByRole("heading", { level: 1, name: "Audit history" }),
            ).toBeInTheDocument()
        })
        // The actor filter is simply omitted -- never an error blocking
        // the page, and never a retry button for this secondary facet.
        expect(screen.queryByLabelText("Actor")).not.toBeInTheDocument()
        expect(
            screen.queryByText("The portal could not load audit history. Try again."),
        ).not.toBeInTheDocument()
    })

    it("still renders audit history when the actor-facet request errors outright", async () => {
        stubFetch({
            actors: () => {
                throw new Error("network down")
            },
        })

        renderPage()

        await waitFor(() => {
            expect(
                screen.getByRole("heading", { level: 1, name: "Audit history" }),
            ).toBeInTheDocument()
        })
        expect(screen.queryByLabelText("Actor")).not.toBeInTheDocument()
    })

    // The underlying campaign-switch guarantee (aborting the previous
    // campaign's request and never exposing its actors while the new
    // campaign's own request is pending) is proven directly against
    // useAuditActors in useAuditActors.test.ts, the same way
    // useAccessOverview.test.ts proves it for that hook rather than
    // re-deriving it through a page-level route navigation.
})

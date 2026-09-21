import {
    act,
    fireEvent,
    render,
    screen,
    waitFor,
} from "@testing-library/react"
import {
    Link,
    MemoryRouter,
    Route,
    Routes,
} from "react-router"
import {
    afterEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import { SessionContext } from "../context/SessionContext"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { CampaignAccessPage } from "./CampaignAccessPage"

const CAMPAIGN_ID = sessionBootstrapFixture.campaigns[0].campaign_id
const OTHER_CAMPAIGN_ID = "other-campaign"

const overview = {
    members: [],
    assignable_roles: [],
    assignable_characters: [],
    assignable_relationship_types: [],
    grantable_resource_capabilities: [],
    access_groups: [],
}

function jsonResponse(body: unknown, status = 200): Response {
    return new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
    })
}

function requestUrl(input: RequestInfo | URL): string {
    return typeof input === "string" ? input : input.toString()
}

function renderAtCampaign(fetchMock: ReturnType<typeof vi.fn>) {
    vi.stubGlobal("fetch", fetchMock)

    return render(
        <SessionContext.Provider
            value={{
                state: {
                    status: "authenticated",
                    bootstrap: sessionBootstrapFixture,
                },
                reload: vi.fn().mockResolvedValue(undefined),
            }}
        >
            <MemoryRouter initialEntries={[`/app/${CAMPAIGN_ID}/access`]}>
                <Routes>
                    <Route path="/app/:campaignId/access" element={<CampaignAccessPage />} />
                </Routes>
            </MemoryRouter>
        </SessionContext.Provider>,
    )
}

function renderAcrossCampaigns(fetchMock: ReturnType<typeof vi.fn>) {
    vi.stubGlobal("fetch", fetchMock)

    return render(
        <SessionContext.Provider
            value={{
                state: {
                    status: "authenticated",
                    bootstrap: {
                        ...sessionBootstrapFixture,
                        campaigns: [
                            ...sessionBootstrapFixture.campaigns,
                            {
                                ...sessionBootstrapFixture.campaigns[0],
                                campaign_id: OTHER_CAMPAIGN_ID,
                                campaign_name: "Other Campaign",
                            },
                        ],
                    },
                },
                reload: vi.fn().mockResolvedValue(undefined),
            }}
        >
            <MemoryRouter initialEntries={[`/app/${CAMPAIGN_ID}/access`]}>
                <Link to={`/app/${OTHER_CAMPAIGN_ID}/access`}>Switch campaign</Link>
                <Routes>
                    <Route path="/app/:campaignId/access" element={<CampaignAccessPage />} />
                </Routes>
            </MemoryRouter>
        </SessionContext.Provider>,
    )
}

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("CampaignAccessPage invitations integration", () => {
    it("loads pending invitations, issues one new token, keeps it visible through the refetch, and never renders raw ids as text", async () => {
        const clipboardWriteText = vi.fn().mockResolvedValue(undefined)
        vi.stubGlobal("navigator", { clipboard: { writeText: clipboardWriteText } })

        let invitationsCallCount = 0
        const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
            const url = requestUrl(input)
            const method = init?.method ?? "GET"

            if (method === "GET" && url.includes("/access-overview")) {
                return Promise.resolve(jsonResponse(overview))
            }

            if (method === "GET" && url.includes("/invitations")) {
                invitationsCallCount += 1
                if (invitationsCallCount === 1) {
                    return Promise.resolve(
                        jsonResponse({
                            invitations: [
                                {
                                    campaign_invitation_id: "11111111-1111-1111-1111-111111111111",
                                    invited_email: null,
                                    invited_by_display_name: "Aria the GM",
                                    created_at: "2026-01-01T00:00:00Z",
                                    expires_at: "2026-01-08T00:00:00Z",
                                },
                            ],
                        }),
                    )
                }
                return Promise.resolve(
                    jsonResponse({
                        invitations: [
                            {
                                campaign_invitation_id: "22222222-2222-2222-2222-222222222222",
                                invited_email: "player@example.com",
                                invited_by_display_name: "Aria the GM",
                                created_at: "2026-01-02T00:00:00Z",
                                expires_at: "2026-01-09T00:00:00Z",
                            },
                        ],
                    }),
                )
            }

            if (method === "POST" && url.endsWith(`/campaigns/${CAMPAIGN_ID}/invitations`)) {
                return Promise.resolve(
                    jsonResponse(
                        {
                            campaign_invitation_id: "new-invitation-id",
                            token: "one-time-token",
                        },
                        201,
                    ),
                )
            }

            return Promise.reject(new Error(`unexpected fetch: ${method} ${url}`))
        })

        const { container } = renderAtCampaign(fetchMock)

        expect(await screen.findByRole("heading", { name: "Access" })).toBeInTheDocument()
        expect(await screen.findByRole("heading", { name: "Invitations" })).toBeInTheDocument()
        expect(await screen.findByText("No email label")).toBeInTheDocument()
        expect(container.textContent).not.toContain("11111111-1111-1111-1111-111111111111")

        fireEvent.change(screen.getByLabelText("Optional email label"), {
            target: { value: "player@example.com" },
        })
        fireEvent.click(screen.getByRole("button", { name: "Issue invitation" }))

        expect(await screen.findByDisplayValue("one-time-token")).toBeInTheDocument()
        expect(await screen.findByText("This token is shown once and cannot be recovered later.")).toBeInTheDocument()
        expect(await screen.findByText("player@example.com")).toBeInTheDocument()

        fireEvent.click(screen.getByRole("button", { name: "Copy token" }))
        await waitFor(() => {
            expect(clipboardWriteText).toHaveBeenCalledWith("one-time-token")
        })
        expect(screen.getByText("Token copied.")).toBeInTheDocument()
    })

    it("clears an issued token synchronously when routing from campaign A to campaign B", async () => {
        const clipboardWriteText = vi.fn().mockResolvedValue(undefined)
        vi.stubGlobal("navigator", { clipboard: { writeText: clipboardWriteText } })

        const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
            const url = requestUrl(input)
            const method = init?.method ?? "GET"

            if (method === "GET" && url.includes("/access-overview")) {
                return Promise.resolve(jsonResponse(overview))
            }

            if (method === "GET" && url.endsWith(`/campaigns/${CAMPAIGN_ID}/invitations`)) {
                return Promise.resolve(jsonResponse({ invitations: [] }))
            }

            if (method === "GET" && url.endsWith(`/campaigns/${OTHER_CAMPAIGN_ID}/invitations`)) {
                return Promise.resolve(
                    jsonResponse({
                        invitations: [
                            {
                                campaign_invitation_id: "33333333-3333-3333-3333-333333333333",
                                invited_email: "other@example.com",
                                invited_by_display_name: "Aria the GM",
                                created_at: "2026-01-03T00:00:00Z",
                                expires_at: "2026-01-10T00:00:00Z",
                            },
                        ],
                    }),
                )
            }

            if (method === "POST" && url.endsWith(`/campaigns/${CAMPAIGN_ID}/invitations`)) {
                return Promise.resolve(
                    jsonResponse(
                        {
                            campaign_invitation_id: "a-issued-id",
                            token: "campaign-a-token",
                        },
                        201,
                    ),
                )
            }

            return Promise.reject(new Error(`unexpected fetch: ${method} ${url}`))
        })

        renderAcrossCampaigns(fetchMock)

        expect(await screen.findByRole("heading", { name: "Access" })).toBeInTheDocument()

        fireEvent.click(screen.getByRole("button", { name: "Issue invitation" }))
        expect(await screen.findByDisplayValue("campaign-a-token")).toBeInTheDocument()

        await act(async () => {
            fireEvent.click(screen.getByRole("link", { name: "Switch campaign" }))
        })

        expect(await screen.findByText("other@example.com")).toBeInTheDocument()
        expect(screen.queryByDisplayValue("campaign-a-token")).not.toBeInTheDocument()
        expect(screen.queryByRole("button", { name: "Copy token" })).not.toBeInTheDocument()

        fireEvent.click(screen.getByRole("button", { name: "Issue invitation" }))
        expect(clipboardWriteText).not.toHaveBeenCalled()
    })
})

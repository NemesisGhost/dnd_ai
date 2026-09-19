import {
    act,
    fireEvent,
    render,
    screen,
    waitFor,
} from "@testing-library/react"
import { MemoryRouter, Route, Routes } from "react-router"
import {
    afterEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import { SessionContext } from "../context/SessionContext"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import type { CampaignAccessOverview } from "../types/accessOverview"
import { CampaignAccessPage } from "./CampaignAccessPage"

// The add-role/revoke-role counterpart to CampaignAccessPage.roleChange.
// integration.test.tsx: exercises the REAL CampaignAccessPage/
// AccessOverviewBoundary/AccessPage/AddMemberRole/RevokeMemberRole/
// useAssignMembershipRole/useRevokeMembershipRole chain, proving each
// control's own persistent "Role added."/"Role removed." announcement
// survives the same overview-refresh unmount that file already proved for
// "Role updated." — see that file's own docstring for the full defect this
// pattern guards against.

const CAMPAIGN_ID = "campaign-a"
const OWNER_ROLE_ID = "role-owner"
const CURATOR_ROLE_ID = "role-curator"
const MEMBERSHIP_ID = "membership-a"
const MEMBERSHIP_ROLE_ID = "membership-role-a-1"

function baseOverview(): CampaignAccessOverview {
    return {
        members: [
            {
                campaign_membership_id: MEMBERSHIP_ID,
                user_id: sessionBootstrapFixture.user.user_id,
                display_name: "Aria the GM",
                status_code: "active",
                status_display_name: "Active",
                joined_at: "2026-01-01T00:00:00Z",
                roles: [
                    {
                        membership_role_id: MEMBERSHIP_ROLE_ID,
                        role_id: OWNER_ROLE_ID,
                        code: "campaign_owner",
                        display_name: "Campaign Owner",
                    },
                ],
                character_relationships: [],
                grants: [],
            },
        ],
        assignable_roles: [
            {
                role_id: OWNER_ROLE_ID,
                code: "campaign_owner",
                display_name: "Campaign Owner",
            },
            {
                role_id: CURATOR_ROLE_ID,
                code: "rules_curator",
                display_name: "Rules Curator",
            },
        ],
    }
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

function renderAtCampaign() {
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
                    <Route
                        path="/app/:campaignId/access"
                        element={<CampaignAccessPage />}
                    />
                </Routes>
            </MemoryRouter>
        </SessionContext.Provider>,
    )
}

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("CampaignAccessPage add-role success announcement", () => {
    it("keeps 'Role added.' observable through the overview's own loading transition", async () => {
        let overviewCallCount = 0
        let resolveSecondOverview!: (response: Response) => void
        const secondOverviewPromise = new Promise<Response>((resolve) => {
            resolveSecondOverview = resolve
        })

        const fetchMock = vi.fn(
            (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
                const url = requestUrl(input)
                const method = init?.method ?? "GET"

                if (method === "GET" && url.includes("/access-overview")) {
                    overviewCallCount += 1
                    if (overviewCallCount === 2) {
                        return secondOverviewPromise
                    }
                    return Promise.resolve(jsonResponse(baseOverview()))
                }

                if (
                    method === "POST" &&
                    url.endsWith(`/memberships/${MEMBERSHIP_ID}/roles`)
                ) {
                    return Promise.resolve(
                        jsonResponse(
                            { membership_role_id: "new-membership-role" },
                            201,
                        ),
                    )
                }

                return Promise.reject(
                    new Error(`unexpected fetch in test: ${method} ${url}`),
                )
            },
        )
        vi.stubGlobal("fetch", fetchMock)

        renderAtCampaign()

        expect(
            await screen.findByRole("heading", { name: "Access" }),
        ).toBeInTheDocument()

        fireEvent.click(
            screen.getByRole("button", { name: "Add role" }),
        )
        fireEvent.click(screen.getByRole("button", { name: "Add" }))

        await waitFor(() => {
            expect(
                screen.getByRole("heading", { name: "Loading access" }),
            ).toBeInTheDocument()
        })

        expect(screen.getByRole("status")).toHaveTextContent(
            "Role added.",
        )

        await act(async () => {
            resolveSecondOverview(jsonResponse(baseOverview()))
        })

        await waitFor(() => {
            expect(
                screen.getByRole("heading", { name: "Access" }),
            ).toBeInTheDocument()
        })
        expect(screen.getByRole("status")).toHaveTextContent(
            "Role added.",
        )
    })
})

describe("CampaignAccessPage revoke-role success announcement", () => {
    it("keeps 'Role removed.' observable through the overview's own loading transition", async () => {
        let overviewCallCount = 0
        let resolveSecondOverview!: (response: Response) => void
        const secondOverviewPromise = new Promise<Response>((resolve) => {
            resolveSecondOverview = resolve
        })

        const fetchMock = vi.fn(
            (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
                const url = requestUrl(input)
                const method = init?.method ?? "GET"

                if (method === "GET" && url.includes("/access-overview")) {
                    overviewCallCount += 1
                    if (overviewCallCount === 2) {
                        return secondOverviewPromise
                    }
                    return Promise.resolve(jsonResponse(baseOverview()))
                }

                if (
                    method === "POST" &&
                    url.endsWith(
                        `/memberships/roles/${MEMBERSHIP_ROLE_ID}/revoke`,
                    )
                ) {
                    return Promise.resolve(
                        jsonResponse(
                            { membership_role_id: MEMBERSHIP_ROLE_ID },
                            200,
                        ),
                    )
                }

                return Promise.reject(
                    new Error(`unexpected fetch in test: ${method} ${url}`),
                )
            },
        )
        vi.stubGlobal("fetch", fetchMock)

        renderAtCampaign()

        expect(
            await screen.findByRole("heading", { name: "Access" }),
        ).toBeInTheDocument()

        fireEvent.click(
            screen.getByRole("button", { name: "Remove role" }),
        )
        fireEvent.click(
            screen.getByRole("button", { name: "Confirm" }),
        )

        await waitFor(() => {
            expect(
                screen.getByRole("heading", { name: "Loading access" }),
            ).toBeInTheDocument()
        })

        expect(screen.getByRole("status")).toHaveTextContent(
            "Role removed.",
        )

        await act(async () => {
            resolveSecondOverview(jsonResponse(baseOverview()))
        })

        await waitFor(() => {
            expect(
                screen.getByRole("heading", { name: "Access" }),
            ).toBeInTheDocument()
        })
        expect(screen.getByRole("status")).toHaveTextContent(
            "Role removed.",
        )
    })
})

// The persistent announcement region is queried by its own class here,
// rather than by role="status", because a row-level control (AddMemberRole/
// MemberRoleEditor/RevokeMemberRole) mounts its own role="status" paragraph
// while expanded — getByRole("status") would then be ambiguous. Row-level
// text is still asserted with getByText/findByText as elsewhere in this
// file.
function persistentAnnouncement(container: HTMLElement): HTMLElement | null {
    return container.querySelector(".campaign-access-page__announcement")
}

describe("CampaignAccessPage cross-operation announcement lifecycle", () => {
    it("clears a stale success announcement the moment a different mutation starts, and keeps it cleared through that mutation's failure — successful add followed by a failed revoke", async () => {
        let resolveRevoke!: (response: Response) => void
        const revokePromise = new Promise<Response>((resolve) => {
            resolveRevoke = resolve
        })

        const fetchMock = vi.fn(
            (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
                const url = requestUrl(input)
                const method = init?.method ?? "GET"

                if (method === "GET" && url.includes("/access-overview")) {
                    return Promise.resolve(jsonResponse(baseOverview()))
                }

                if (
                    method === "POST" &&
                    url.endsWith(`/memberships/${MEMBERSHIP_ID}/roles`)
                ) {
                    return Promise.resolve(
                        jsonResponse(
                            { membership_role_id: "new-membership-role" },
                            201,
                        ),
                    )
                }

                if (
                    method === "POST" &&
                    url.endsWith(
                        `/memberships/roles/${MEMBERSHIP_ROLE_ID}/revoke`,
                    )
                ) {
                    return revokePromise
                }

                return Promise.reject(
                    new Error(`unexpected fetch in test: ${method} ${url}`),
                )
            },
        )
        vi.stubGlobal("fetch", fetchMock)

        const { container } = renderAtCampaign()

        expect(
            await screen.findByRole("heading", { name: "Access" }),
        ).toBeInTheDocument()

        // 1. Complete an add-role mutation successfully, and let its own
        // authoritative overview reload finish — the normal Access view is
        // showing again, with "Role added." as the current announcement.
        fireEvent.click(
            screen.getByRole("button", { name: "Add role" }),
        )
        fireEvent.click(screen.getByRole("button", { name: "Add" }))

        await waitFor(() => {
            expect(persistentAnnouncement(container)).toHaveTextContent(
                "Role added.",
            )
        })
        expect(
            await screen.findByRole("heading", { name: "Access" }),
        ).toBeInTheDocument()

        // 2. Begin a different, unrelated mutation — revoke the member's
        // existing role — without waiting for this one to resolve.
        fireEvent.click(
            screen.getByRole("button", { name: "Remove role" }),
        )
        fireEvent.click(screen.getByRole("button", { name: "Confirm" }))

        // 3. The stale "Role added." success is cleared the instant the
        // new mutation is submitted, while this row's own pending state is
        // shown — never both at once, and never the overview's own
        // success-triggered refetch (there was none here) clearing it.
        await waitFor(() => {
            expect(
                screen.getByText("Removing role…"),
            ).toBeInTheDocument()
        })
        expect(persistentAnnouncement(container)).toHaveTextContent("")

        // 4. The revoke fails.
        await act(async () => {
            resolveRevoke(new Response(null, { status: 500 }))
        })

        // 5. The old success stays cleared; the current row presents its
        // own recoverable error — never a stale, now-misleading success.
        await waitFor(() => {
            expect(
                screen.getByText(
                    "The role could not be removed. Try again.",
                ),
            ).toBeInTheDocument()
        })
        expect(persistentAnnouncement(container)).toHaveTextContent("")
    })
})

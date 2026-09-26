import {
    act,
    fireEvent,
    render,
    screen,
    waitFor,
} from "@testing-library/react"
import { MemoryRouter, Route, Routes } from "react-router"
import { afterEach, describe, expect, it, vi } from "vitest"
import { SessionContext } from "../context/SessionContext"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import type { CampaignAccessOverview } from "../types/accessOverview"
import { CampaignAccessPage } from "./CampaignAccessPage"

vi.mock("../components/InvitationsSection", () => ({
    InvitationsSection: () => null,
}))

// Exercises the REAL Access page -> AccessOverviewBoundary -> AccessPage ->
// access-group components -> access-group hooks -> API client chain —
// nothing here is mocked except the network boundary (global fetch) and
// the session context. Mirrors
// CampaignAccessPage.resourceGrant.integration.test.tsx's own shape and
// reasoning for why the isolated AccessPage.test.tsx coverage alone cannot
// prove the persistent-announcement-survives-refetch behavior.

const CAMPAIGN_ID = "campaign-a"
const GROUP_ID = "group-1"
const MEMBERSHIP_ID = "membership-a"
const GROUP_MEMBERSHIP_ID = "group-membership-1"

function baseOverview(
    accessGroups: CampaignAccessOverview["access_groups"],
): CampaignAccessOverview {
    return {
        members: [
            {
                campaign_membership_id: MEMBERSHIP_ID,
                user_id: sessionBootstrapFixture.user.user_id,
                display_name: "Aria the GM",
                status_code: "active",
                status_display_name: "Active",
                joined_at: "2026-01-01T00:00:00Z",
                account_is_active: true,
                roles: [],
                character_relationships: [],
                grants: [],
            },
        ],
        assignable_roles: [],
        assignable_characters: [],
        assignable_relationship_types: [],
        grantable_resource_capabilities: [],
        access_groups: accessGroups,
    }
}

const noGroupsOverview = baseOverview([])
const oneActiveGroupOverview = baseOverview([
    {
        access_group_id: GROUP_ID,
        name: "Lore Circle",
        description: null,
        status_code: "active",
        status_display_name: "Active",
        created_at: "2026-01-01T00:00:00Z",
        members: [],
        grants: [],
    },
])
const archivedGroupOverview = baseOverview([
    {
        access_group_id: GROUP_ID,
        name: "Lore Circle",
        description: null,
        status_code: "archived",
        status_display_name: "Archived",
        created_at: "2026-01-01T00:00:00Z",
        members: [],
        grants: [],
    },
])
const groupWithMemberOverview = baseOverview([
    {
        access_group_id: GROUP_ID,
        name: "Lore Circle",
        description: null,
        status_code: "active",
        status_display_name: "Active",
        created_at: "2026-01-01T00:00:00Z",
        members: [
            {
                access_group_membership_id: GROUP_MEMBERSHIP_ID,
                campaign_membership_id: MEMBERSHIP_ID,
                display_name: "Aria the GM",
                added_at: "2026-01-02T00:00:00Z",
            },
        ],
        grants: [],
    },
])

function jsonResponse(body: unknown, status = 200): Response {
    return new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
    })
}

function renderAtCampaign(
    fetchMock: ReturnType<typeof vi.fn>,
    reload: () => Promise<void> = vi.fn().mockResolvedValue(undefined),
) {
    vi.stubGlobal("fetch", fetchMock)
    return render(
        <SessionContext.Provider
            value={{
                state: {
                    status: "authenticated",
                    bootstrap: sessionBootstrapFixture,
                },
                reload,
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

function persistentAnnouncement(container: HTMLElement): HTMLElement | null {
    return container.querySelector(".campaign-access-page__announcement")
}

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("CampaignAccessPage create-access-group success announcement", () => {
    it("keeps 'Access group created.' observable through the overview's own loading transition", async () => {
        let overviewCallCount = 0
        let resolveSecondOverview: ((response: Response) => void) | null = null
        const secondOverviewPromise = new Promise<Response>((resolve) => {
            resolveSecondOverview = resolve
        })

        const fetchMock = vi.fn(
            (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
                const url = typeof input === "string" ? input : input.toString()
                const method = init?.method ?? "GET"

                if (method === "GET" && url.includes("/access-overview")) {
                    overviewCallCount += 1
                    if (overviewCallCount === 2) {
                        return secondOverviewPromise
                    }
                    return Promise.resolve(jsonResponse(noGroupsOverview))
                }

                if (method === "POST" && url.endsWith("/access-groups")) {
                    return Promise.resolve(
                        jsonResponse(
                            { access_group_id: GROUP_ID, name: "Lore Circle" },
                            201,
                        ),
                    )
                }

                return Promise.reject(
                    new Error(`unexpected fetch in test: ${method} ${url}`),
                )
            },
        )

        const { container } = renderAtCampaign(fetchMock)

        expect(
            await screen.findByRole("heading", { name: "Access" }),
        ).toBeInTheDocument()

        fireEvent.click(
            screen.getByRole("button", { name: "Create access group" }),
        )
        fireEvent.change(screen.getByLabelText(/New access group name/), {
            target: { value: "Lore Circle" },
        })
        fireEvent.click(screen.getByRole("button", { name: "Save" }))

        await waitFor(() => {
            expect(
                screen.getByRole("heading", { name: "Loading access" }),
            ).toBeInTheDocument()
        })

        expect(persistentAnnouncement(container)).toHaveTextContent(
            "Access group created.",
        )

        await act(async () => {
            resolveSecondOverview?.(jsonResponse(oneActiveGroupOverview))
        })

        await waitFor(() => {
            expect(
                screen.getByRole("heading", { name: "Access" }),
            ).toBeInTheDocument()
        })
        expect(container.textContent).toContain("Lore Circle")
        expect(persistentAnnouncement(container)).toHaveTextContent(
            "Access group created.",
        )
    })
})

describe("CampaignAccessPage deactivate/reactivate-access-group lifecycle", () => {
    it("deactivating shows Reactivate instead of Edit/Deactivate, and reactivating restores the active controls", async () => {
        let overviewCallCount = 0

        const fetchMock = vi.fn(
            (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
                const url = typeof input === "string" ? input : input.toString()
                const method = init?.method ?? "GET"

                if (method === "GET" && url.includes("/access-overview")) {
                    overviewCallCount += 1
                    if (overviewCallCount === 1) {
                        return Promise.resolve(jsonResponse(oneActiveGroupOverview))
                    }
                    if (overviewCallCount === 2) {
                        return Promise.resolve(jsonResponse(archivedGroupOverview))
                    }
                    return Promise.resolve(jsonResponse(oneActiveGroupOverview))
                }

                if (method === "POST" && url.includes("/deactivate")) {
                    return Promise.resolve(
                        jsonResponse({ access_group_id: GROUP_ID, name: "Lore Circle" }),
                    )
                }

                if (method === "POST" && url.includes("/reactivate")) {
                    return Promise.resolve(
                        jsonResponse({ access_group_id: GROUP_ID, name: "Lore Circle" }),
                    )
                }

                return Promise.reject(
                    new Error(`unexpected fetch in test: ${method} ${url}`),
                )
            },
        )

        renderAtCampaign(fetchMock)

        expect(
            await screen.findByRole("heading", { name: "Access" }),
        ).toBeInTheDocument()

        fireEvent.click(screen.getByRole("button", { name: "Deactivate" }))
        fireEvent.click(screen.getByRole("button", { name: "Confirm" }))

        await waitFor(() => {
            expect(
                screen.getByRole("button", { name: "Reactivate" }),
            ).toBeInTheDocument()
        })
        expect(
            screen.queryByRole("button", { name: "Deactivate" }),
        ).not.toBeInTheDocument()
        expect(screen.getByText("Archived")).toBeInTheDocument()

        fireEvent.click(screen.getByRole("button", { name: "Reactivate" }))

        await waitFor(() => {
            expect(
                screen.getByRole("button", { name: "Deactivate" }),
            ).toBeInTheDocument()
        })
    })
})

describe("CampaignAccessPage add/remove access-group member lifecycle", () => {
    it("adding then removing a member updates the group's member list through each refetch", async () => {
        let overviewCallCount = 0

        const fetchMock = vi.fn(
            (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
                const url = typeof input === "string" ? input : input.toString()
                const method = init?.method ?? "GET"

                if (method === "GET" && url.includes("/access-overview")) {
                    overviewCallCount += 1
                    if (overviewCallCount === 1) {
                        return Promise.resolve(jsonResponse(oneActiveGroupOverview))
                    }
                    if (overviewCallCount === 2) {
                        return Promise.resolve(jsonResponse(groupWithMemberOverview))
                    }
                    return Promise.resolve(jsonResponse(oneActiveGroupOverview))
                }

                if (method === "POST" && url.includes("/members")) {
                    return Promise.resolve(
                        jsonResponse(
                            {
                                access_group_membership_id:
                                    GROUP_MEMBERSHIP_ID,
                                access_group_membership_ids: [
                                    GROUP_MEMBERSHIP_ID,
                                ],
                                added_count: 1,
                            },
                            201,
                        ),
                    )
                }

                if (method === "POST" && url.includes("/access-group-memberships")) {
                    return Promise.resolve(
                        jsonResponse({
                            access_group_membership_id: GROUP_MEMBERSHIP_ID,
                        }),
                    )
                }

                return Promise.reject(
                    new Error(`unexpected fetch in test: ${method} ${url}`),
                )
            },
        )

        const { container } = renderAtCampaign(fetchMock)

        expect(
            await screen.findByRole("heading", { name: "Access" }),
        ).toBeInTheDocument()

        fireEvent.click(
            screen.getByRole("button", {
                name: "Add members",
            }),
        )

        fireEvent.click(
            screen.getByRole("checkbox", {
                name: "Aria the GM",
            }),
        )

        fireEvent.click(
            screen.getByRole("button", {
                name: "Add selected members",
            }),
        )

        await waitFor(() => {
            expect(
                persistentAnnouncement(container),
            ).toHaveTextContent(
                "1 member added to group.",
            )
        })
        await waitFor(() => {
            expect(
                screen.getByRole("button", { name: "Remove from group" }),
            ).toBeInTheDocument()
        })

        fireEvent.click(
            screen.getByRole("button", { name: "Remove from group" }),
        )
        fireEvent.click(screen.getByRole("button", { name: "Confirm" }))

        await waitFor(() => {
            expect(persistentAnnouncement(container)).toHaveTextContent(
                "Member removed from group.",
            )
        })
        await waitFor(() => {
            expect(
                screen.queryByRole("button", { name: "Remove from group" }),
            ).not.toBeInTheDocument()
        })
    })
})

describe("CampaignAccessPage access-group cross-operation announcement lifecycle", () => {
    it("clears a stale success announcement the moment a different mutation starts, and keeps it cleared through that mutation's failure", async () => {
        let overviewCallCount = 0

        const fetchMock = vi.fn(
            (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
                const url = typeof input === "string" ? input : input.toString()
                const method = init?.method ?? "GET"

                if (method === "GET" && url.includes("/access-overview")) {
                    overviewCallCount += 1
                    return Promise.resolve(
                        jsonResponse(
                            overviewCallCount === 1
                                ? noGroupsOverview
                                : oneActiveGroupOverview,
                        ),
                    )
                }

                if (method === "POST" && url.endsWith("/access-groups")) {
                    return Promise.resolve(
                        jsonResponse(
                            { access_group_id: GROUP_ID, name: "Lore Circle" },
                            201,
                        ),
                    )
                }

                if (method === "POST" && url.includes("/deactivate")) {
                    return Promise.resolve(new Response(null, { status: 403 }))
                }

                return Promise.reject(
                    new Error(`unexpected fetch in test: ${method} ${url}`),
                )
            },
        )

        const { container } = renderAtCampaign(fetchMock)

        expect(
            await screen.findByRole("heading", { name: "Access" }),
        ).toBeInTheDocument()

        // First mutation: create, succeeds.
        fireEvent.click(
            screen.getByRole("button", { name: "Create access group" }),
        )
        fireEvent.change(screen.getByLabelText(/New access group name/), {
            target: { value: "Lore Circle" },
        })
        fireEvent.click(screen.getByRole("button", { name: "Save" }))

        await waitFor(() => {
            expect(persistentAnnouncement(container)).toHaveTextContent(
                "Access group created.",
            )
        })
        await waitFor(() => {
            expect(container.textContent).toContain("Lore Circle")
        })

        // Second mutation: deactivate, starts (clearing the stale success)
        // and then fails (403) — the stale "created" announcement must
        // never resurface.
        fireEvent.click(screen.getByRole("button", { name: "Deactivate" }))
        fireEvent.click(screen.getByRole("button", { name: "Confirm" }))

        await waitFor(() => {
            expect(
                screen.getByText(
                    "You do not have permission to make this change.",
                ),
            ).toBeInTheDocument()
        })
        expect(persistentAnnouncement(container)).toHaveTextContent("")
        expect(
            screen.queryByText("Access group created."),
        ).not.toBeInTheDocument()
    })
})

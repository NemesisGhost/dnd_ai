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

// Exercises the REAL Access page -> AccessOverviewBoundary -> AccessPage ->
// AddResourceGrant/RevokeResourceGrant -> useAdd/RevokeResourceGrant -> API
// client chain — nothing here is mocked except the network boundary
// (global fetch) and the session context. Mirrors
// CampaignAccessPage.characterRelationship.integration.test.tsx's own shape
// and reasoning for why the isolated AccessPage.test.tsx coverage alone
// cannot prove the persistent-announcement-survives-refetch behavior.

const CAMPAIGN_ID = "campaign-a"
const CHARACTER_ID = "character-kestrel"
const CAPABILITY_CODE = "character.view_full"
const GRANT_ID = "grant-1"
const MEMBERSHIP_ID = "membership-a"

function baseOverview(
    grants: CampaignAccessOverview["members"][number]["grants"],
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
                roles: [],
                character_relationships: [],
                grants,
            },
        ],
        assignable_roles: [],
        assignable_characters: [
            { character_id: CHARACTER_ID, display_name: "Kestrel Vane" },
        ],
        assignable_relationship_types: [],
        grantable_resource_capabilities: [
            {
                capability_id: "capability-1",
                code: CAPABILITY_CODE,
                display_name: "View Character Full Detail",
                target_type: "character",
            },
        ],
    }
}

const emptyOverview = baseOverview([])
const withGrantOverview = baseOverview([
    {
        resource_grant_id: GRANT_ID,
        capability_code: CAPABILITY_CODE,
        capability_display_name: "View Character Full Detail",
        effect: "allow",
        target_type: "character",
        target_id: CHARACTER_ID,
        target_display_name: "Kestrel Vane",
        reason: null,
        granted_at: "2026-01-02T00:00:00Z",
        expires_at: null,
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

// The page-level persistent announcement is not the only role="status"
// region once a row's own mutation control is showing an error (each
// editor/confirm control has its own status paragraph too) — scoped
// lookup by class, mirroring
// CampaignAccessPage.characterRelationship.integration.test.tsx's identical
// helper, rather than screen.getByRole("status"), which would then match
// more than one element.
function persistentAnnouncement(container: HTMLElement): HTMLElement | null {
    return container.querySelector(
        ".campaign-access-page__announcement",
    )
}

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("CampaignAccessPage add-resource-grant success announcement", () => {
    it("keeps 'Resource access added.' observable through the overview's own loading transition", async () => {
        let overviewCallCount = 0
        let resolveSecondOverview: ((response: Response) => void) | null =
            null
        const secondOverviewPromise = new Promise<Response>((resolve) => {
            resolveSecondOverview = resolve
        })

        const fetchMock = vi.fn(
            (
                input: RequestInfo | URL,
                init?: RequestInit,
            ): Promise<Response> => {
                const url =
                    typeof input === "string" ? input : input.toString()
                const method = init?.method ?? "GET"

                if (method === "GET" && url.includes("/access-overview")) {
                    overviewCallCount += 1
                    if (overviewCallCount === 2) {
                        return secondOverviewPromise
                    }
                    return Promise.resolve(jsonResponse(emptyOverview))
                }

                if (
                    method === "POST" &&
                    url.includes("/resource-grants") &&
                    !url.includes("/revoke")
                ) {
                    return Promise.resolve(
                        jsonResponse({ resource_grant_id: GRANT_ID }, 201),
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
                name: "Add direct resource access",
            }),
        )
        fireEvent.click(screen.getByRole("button", { name: "Add" }))

        await waitFor(() => {
            expect(
                screen.getByRole("heading", { name: "Loading access" }),
            ).toBeInTheDocument()
        })
        expect(
            screen.queryByRole("button", { name: "Add" }),
        ).not.toBeInTheDocument()

        expect(persistentAnnouncement(container)).toHaveTextContent(
            "Resource access added.",
        )

        await act(async () => {
            resolveSecondOverview?.(jsonResponse(withGrantOverview))
        })

        await waitFor(() => {
            expect(
                screen.getByRole("heading", { name: "Access" }),
            ).toBeInTheDocument()
        })
        expect(container.textContent).toContain(
            "View Character Full Detail",
        )
        expect(container.textContent).toContain("Kestrel Vane")
        expect(persistentAnnouncement(container)).toHaveTextContent(
            "Resource access added.",
        )
    })
})

describe("CampaignAccessPage revoke-resource-grant success announcement", () => {
    it("keeps 'Resource access revoked.' observable through the overview's own loading transition", async () => {
        let overviewCallCount = 0
        let resolveSecondOverview: ((response: Response) => void) | null =
            null
        const secondOverviewPromise = new Promise<Response>((resolve) => {
            resolveSecondOverview = resolve
        })

        const fetchMock = vi.fn(
            (
                input: RequestInfo | URL,
                init?: RequestInit,
            ): Promise<Response> => {
                const url =
                    typeof input === "string" ? input : input.toString()
                const method = init?.method ?? "GET"

                if (method === "GET" && url.includes("/access-overview")) {
                    overviewCallCount += 1
                    if (overviewCallCount === 2) {
                        return secondOverviewPromise
                    }
                    return Promise.resolve(jsonResponse(withGrantOverview))
                }

                if (method === "POST" && url.includes("/revoke")) {
                    return Promise.resolve(
                        jsonResponse({ resource_grant_id: GRANT_ID }),
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
            screen.getByRole("button", { name: "Revoke access" }),
        )
        fireEvent.click(screen.getByRole("button", { name: "Confirm" }))

        await waitFor(() => {
            expect(
                screen.getByRole("heading", { name: "Loading access" }),
            ).toBeInTheDocument()
        })

        expect(persistentAnnouncement(container)).toHaveTextContent(
            "Resource access revoked.",
        )

        await act(async () => {
            resolveSecondOverview?.(jsonResponse(emptyOverview))
        })

        await waitFor(() => {
            expect(
                screen.getByRole("heading", { name: "Access" }),
            ).toBeInTheDocument()
        })
        expect(
            screen.getByText("No direct resource access."),
        ).toBeInTheDocument()
        expect(persistentAnnouncement(container)).toHaveTextContent(
            "Resource access revoked.",
        )
    })
})

// A "deny" grant is an explicit block, not a permission — removing one
// restores access from elsewhere rather than taking it away, so the whole
// page->component->hook->API chain must use deny-aware wording, not the
// allow-oriented copy the two describe blocks above exercise
// (checkpoint-5 correction).
const withDenyGrantOverview = baseOverview([
    {
        resource_grant_id: GRANT_ID,
        capability_code: CAPABILITY_CODE,
        capability_display_name: "View Character Full Detail",
        effect: "deny",
        target_type: "character",
        target_id: CHARACTER_ID,
        target_display_name: "Kestrel Vane",
        reason: null,
        granted_at: "2026-01-02T00:00:00Z",
        expires_at: null,
    },
])

describe("CampaignAccessPage revoke-resource-grant deny effect (checkpoint-5 correction)", () => {
    it("uses deny-aware trigger/confirmation/success wording and keeps the deny-specific announcement observable through the overview's own loading transition", async () => {
        let overviewCallCount = 0
        let resolveSecondOverview: ((response: Response) => void) | null =
            null
        const secondOverviewPromise = new Promise<Response>((resolve) => {
            resolveSecondOverview = resolve
        })

        const fetchMock = vi.fn(
            (
                input: RequestInfo | URL,
                init?: RequestInit,
            ): Promise<Response> => {
                const url =
                    typeof input === "string" ? input : input.toString()
                const method = init?.method ?? "GET"

                if (method === "GET" && url.includes("/access-overview")) {
                    overviewCallCount += 1
                    if (overviewCallCount === 2) {
                        return secondOverviewPromise
                    }
                    return Promise.resolve(jsonResponse(withDenyGrantOverview))
                }

                if (method === "POST" && url.includes("/revoke")) {
                    return Promise.resolve(
                        jsonResponse({ resource_grant_id: GRANT_ID }),
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

        expect(
            screen.queryByRole("button", { name: "Revoke access" }),
        ).not.toBeInTheDocument()

        fireEvent.click(
            screen.getByRole("button", { name: "Remove denial" }),
        )

        expect(
            screen.getByText(/Access may be restored from another role, relationship, group, or allow grant\./),
        ).toBeInTheDocument()

        fireEvent.click(screen.getByRole("button", { name: "Confirm" }))

        await waitFor(() => {
            expect(
                screen.getByRole("heading", { name: "Loading access" }),
            ).toBeInTheDocument()
        })

        const successMessage =
            "Explicit denial removed. Access may be restored from another role, relationship, group, or allow grant."
        expect(persistentAnnouncement(container)).toHaveTextContent(
            successMessage,
        )

        await act(async () => {
            resolveSecondOverview?.(jsonResponse(emptyOverview))
        })

        await waitFor(() => {
            expect(
                screen.getByRole("heading", { name: "Access" }),
            ).toBeInTheDocument()
        })
        expect(
            screen.getByText("No direct resource access."),
        ).toBeInTheDocument()
        expect(persistentAnnouncement(container)).toHaveTextContent(
            successMessage,
        )
    })
})

describe("CampaignAccessPage resource-grant cross-operation announcement lifecycle", () => {
    it("clears a stale success announcement the moment a different mutation starts, and keeps it cleared through that mutation's failure", async () => {
        let overviewCallCount = 0

        const fetchMock = vi.fn(
            (
                input: RequestInfo | URL,
                init?: RequestInit,
            ): Promise<Response> => {
                const url =
                    typeof input === "string" ? input : input.toString()
                const method = init?.method ?? "GET"

                if (method === "GET" && url.includes("/access-overview")) {
                    overviewCallCount += 1
                    return Promise.resolve(
                        jsonResponse(
                            overviewCallCount === 1
                                ? emptyOverview
                                : withGrantOverview,
                        ),
                    )
                }

                if (
                    method === "POST" &&
                    url.includes("/resource-grants") &&
                    !url.includes("/revoke")
                ) {
                    return Promise.resolve(
                        jsonResponse({ resource_grant_id: GRANT_ID }, 201),
                    )
                }

                if (method === "POST" && url.includes("/revoke")) {
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

        // First mutation: add, succeeds.
        fireEvent.click(
            screen.getByRole("button", {
                name: "Add direct resource access",
            }),
        )
        fireEvent.click(screen.getByRole("button", { name: "Add" }))

        await waitFor(() => {
            expect(persistentAnnouncement(container)).toHaveTextContent(
                "Resource access added.",
            )
        })

        await waitFor(() => {
            expect(container.textContent).toContain("Kestrel Vane")
        })

        // Second mutation: revoke, starts (clearing the stale success) and
        // then fails (403) — the stale "added" announcement must never
        // resurface.
        fireEvent.click(
            screen.getByRole("button", { name: "Revoke access" }),
        )
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
            screen.queryByText("Resource access added."),
        ).not.toBeInTheDocument()
    })
})

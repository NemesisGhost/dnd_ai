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
// AddCharacterRelationship/CharacterRelationshipEditor/
// RevokeCharacterRelationship -> useAdd/Change/RevokeCharacterRelationship
// -> API client chain — nothing here is mocked except the network boundary
// (global fetch) and the session context. Mirrors
// CampaignAccessPage.roleAddRevoke.integration.test.tsx's own shape and
// reasoning for why the isolated AccessPage.test.tsx coverage alone cannot
// prove the persistent-announcement-survives-refetch behavior.

const CAMPAIGN_ID = "campaign-a"
const CHARACTER_ID = "character-kestrel"
const RELATIONSHIP_TYPE_ID = "type-viewer"
const RELATIONSHIP_ID = "relationship-1"
const MEMBERSHIP_ID = "membership-a"

function baseOverview(
    relationships: CampaignAccessOverview["members"][number]["character_relationships"],
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
                character_relationships: relationships,
                grants: [],
            },
        ],
        assignable_roles: [],
        assignable_characters: [
            { character_id: CHARACTER_ID, display_name: "Kestrel Vane" },
        ],
        assignable_relationship_types: [
            {
                character_relationship_type_id: RELATIONSHIP_TYPE_ID,
                code: "viewer",
                display_name: "Viewer",
            },
        ],
        grantable_resource_capabilities: [],
        access_groups: [],
    }
}

const emptyOverview = baseOverview([])
const withRelationshipOverview = baseOverview([
    {
        membership_character_relationship_id: RELATIONSHIP_ID,
        character_id: CHARACTER_ID,
        character_display_name: "Kestrel Vane",
        relationship_type_code: "viewer",
        relationship_type_display_name: "Viewer",
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
// CampaignAccessPage.roleAddRevoke.integration.test.tsx's identical
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

describe("CampaignAccessPage add-character-relationship success announcement", () => {
    it("keeps 'Character relationship added.' observable through the overview's own loading transition", async () => {
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
                    url.includes("/character-relationships") &&
                    !url.includes("/revoke") &&
                    !url.includes("/change")
                ) {
                    return Promise.resolve(
                        jsonResponse(
                            {
                                membership_character_relationship_id:
                                    RELATIONSHIP_ID,
                            },
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
            screen.getByRole("button", {
                name: "Add character relationship",
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
            "Character relationship added.",
        )

        await act(async () => {
            resolveSecondOverview?.(jsonResponse(withRelationshipOverview))
        })

        await waitFor(() => {
            expect(
                screen.getByRole("heading", { name: "Access" }),
            ).toBeInTheDocument()
        })
        expect(
            screen.getByText("Kestrel Vane — Viewer"),
        ).toBeInTheDocument()
        expect(persistentAnnouncement(container)).toHaveTextContent(
            "Character relationship added.",
        )
    })
})

describe("CampaignAccessPage revoke-character-relationship success announcement", () => {
    it("keeps 'Character relationship revoked.' observable through the overview's own loading transition", async () => {
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
                    return Promise.resolve(
                        jsonResponse(withRelationshipOverview),
                    )
                }

                if (method === "POST" && url.includes("/revoke")) {
                    return Promise.resolve(
                        jsonResponse({
                            membership_character_relationship_id:
                                RELATIONSHIP_ID,
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
            screen.getByRole("button", { name: "Revoke relationship" }),
        )
        fireEvent.click(screen.getByRole("button", { name: "Confirm" }))

        await waitFor(() => {
            expect(
                screen.getByRole("heading", { name: "Loading access" }),
            ).toBeInTheDocument()
        })

        expect(persistentAnnouncement(container)).toHaveTextContent(
            "Character relationship revoked.",
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
            screen.getByText("No character relationships."),
        ).toBeInTheDocument()
        expect(persistentAnnouncement(container)).toHaveTextContent(
            "Character relationship revoked.",
        )
    })
})

describe("CampaignAccessPage character-relationship cross-operation announcement lifecycle", () => {
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
                                : withRelationshipOverview,
                        ),
                    )
                }

                if (
                    method === "POST" &&
                    url.includes("/character-relationships") &&
                    !url.includes("/revoke") &&
                    !url.includes("/change")
                ) {
                    return Promise.resolve(
                        jsonResponse(
                            {
                                membership_character_relationship_id:
                                    RELATIONSHIP_ID,
                            },
                            201,
                        ),
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
                name: "Add character relationship",
            }),
        )
        fireEvent.click(screen.getByRole("button", { name: "Add" }))

        await waitFor(() => {
            expect(persistentAnnouncement(container)).toHaveTextContent(
                "Character relationship added.",
            )
        })

        await waitFor(() => {
            expect(
                screen.getByText("Kestrel Vane — Viewer"),
            ).toBeInTheDocument()
        })

        // Second mutation: revoke, starts (clearing the stale success) and
        // then fails (403) — the stale "added" announcement must never
        // resurface.
        fireEvent.click(
            screen.getByRole("button", { name: "Revoke relationship" }),
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
            screen.queryByText("Character relationship added."),
        ).not.toBeInTheDocument()
    })
})

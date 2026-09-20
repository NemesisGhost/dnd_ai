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
import type { CampaignAccessOverview } from "../types/accessOverview"
import { CampaignAccessPage } from "./CampaignAccessPage"

// This file exercises the REAL CampaignAccessPage/AccessOverviewBoundary/
// AccessPage/MemberRoleEditor/useChangeMembershipRole chain — nothing here
// is mocked except the network boundary (global fetch) and the session
// context. The isolated AccessPage.test.tsx role-change test passes a bare
// vi.fn() as onChanged, which never drives AccessOverviewBoundary into its
// own loading state, so it cannot reproduce the defect this file covers:
// a role-change success and the resulting authoritative overview refresh
// are batched into the same React commit that unmounts MemberRoleEditor
// (and its own "Role updated." status paragraph) — without a live region
// that survives that unmount, the announcement is never actually
// observable. See CampaignAccessPage's own persistent announcement.

const CAMPAIGN_A_ID = "campaign-a"
const CAMPAIGN_B_ID = "campaign-b"

const OWNER_ROLE_ID = "role-owner"
const CURATOR_ROLE_ID = "role-curator"
const MEMBERSHIP_ROLE_ID = "membership-role-a-1"

function makeOverview(memberDisplayName: string): CampaignAccessOverview {
    return {
        members: [
            {
                campaign_membership_id: "membership-a",
                user_id: sessionBootstrapFixture.user.user_id,
                display_name: memberDisplayName,
                status_code: "active",
                status_display_name: "Active",
                joined_at: "2026-01-01T00:00:00Z",
                account_is_active: true,
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
        assignable_characters: [],
        assignable_relationship_types: [],
        grantable_resource_capabilities: [],
        access_groups: [],
    }
}

const campaignAOverview = makeOverview("Aria the GM")
const campaignBOverview = makeOverview("Bram of Campaign B")

function campaignIdFromOverviewUrl(url: string): string {
    const match = /\/campaigns\/([^/]+)\/access-overview/.exec(url)
    if (match === null) {
        throw new Error(`unexpected access-overview URL: ${url}`)
    }
    return decodeURIComponent(match[1])
}

function jsonResponse(body: unknown, status = 200): Response {
    return new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
    })
}

// The second Campaign A overview fetch (the authoritative refresh a
// role-change success triggers) is held pending until the test
// deliberately resolves it — the only reliable way to observe the
// boundary's own loading state and the still-mounted announcement before
// the refreshed data replaces it, rather than racing a promise
// microtask.
function makeFetchMock() {
    let campaignAOverviewCallCount = 0
    let resolveSecondCampaignAOverview:
        | ((response: Response) => void)
        | null = null
    const secondCampaignAOverviewPromise = new Promise<Response>(
        (resolve) => {
            resolveSecondCampaignAOverview = resolve
        },
    )

    const fetchMock = vi.fn(
        (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
            const url =
                typeof input === "string" ? input : input.toString()
            const method = init?.method ?? "GET"

            if (method === "GET" && url.includes("/access-overview")) {
                const campaignId = campaignIdFromOverviewUrl(url)

                if (campaignId === CAMPAIGN_B_ID) {
                    return Promise.resolve(jsonResponse(campaignBOverview))
                }

                campaignAOverviewCallCount += 1
                if (campaignAOverviewCallCount === 2) {
                    return secondCampaignAOverviewPromise
                }
                return Promise.resolve(jsonResponse(campaignAOverview))
            }

            if (
                method === "POST" &&
                url.includes("/roles/") &&
                url.includes("/change")
            ) {
                return Promise.resolve(
                    jsonResponse(
                        { membership_role_id: MEMBERSHIP_ROLE_ID },
                        201,
                    ),
                )
            }

            return Promise.reject(
                new Error(`unexpected fetch in test: ${method} ${url}`),
            )
        },
    )

    return {
        fetchMock,
        resolveTheAuthoritativeRefresh: () => {
            resolveSecondCampaignAOverview?.(jsonResponse(campaignAOverview))
        },
    }
}

function renderAtCampaignA(reload: () => Promise<void>) {
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
            <MemoryRouter initialEntries={[`/app/${CAMPAIGN_A_ID}/access`]}>
                <Link to={`/app/${CAMPAIGN_B_ID}/access`}>
                    Switch to Campaign B
                </Link>

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

describe("CampaignAccessPage role-change success announcement", () => {
    it(
        "keeps the success announcement observable through the overview's own " +
            "loading transition, then clears it on navigation to another campaign",
        async () => {
            const { fetchMock, resolveTheAuthoritativeRefresh } =
                makeFetchMock()
            vi.stubGlobal("fetch", fetchMock)
            const reload = vi.fn().mockResolvedValue(undefined)

            renderAtCampaignA(reload)

            // Initial load.
            expect(
                await screen.findByRole("heading", { name: "Access" }),
            ).toBeInTheDocument()
            expect(
                screen.getByText("Aria the GM"),
            ).toBeInTheDocument()

            // Open the editor and choose a different role.
            fireEvent.click(
                screen.getByRole("button", { name: "Change role" }),
            )
            fireEvent.change(screen.getByRole("combobox"), {
                target: { value: CURATOR_ROLE_ID },
            })

            // 1. The role change succeeds, 2. its success callback starts
            // the authoritative overview refresh (held pending above), and
            // 3. the boundary enters loading and unmounts the editor.
            fireEvent.click(screen.getByRole("button", { name: "Save" }))

            await waitFor(() => {
                expect(
                    screen.getByRole("heading", { name: "Loading access" }),
                ).toBeInTheDocument()
            })
            expect(
                screen.queryByRole("combobox"),
            ).not.toBeInTheDocument()
            expect(
                screen.queryByRole("button", { name: "Save" }),
            ).not.toBeInTheDocument()

            // The authoritative refresh actually started a second request
            // — never a locally-guessed update.
            expect(
                fetchMock.mock.calls.filter(
                    (call) =>
                        (call[1]?.method ?? "GET") === "GET" &&
                        (
                            (typeof call[0] === "string"
                                ? call[0]
                                : call[0].toString())
                        ).includes(`/campaigns/${CAMPAIGN_A_ID}/access-overview`),
                ).length,
            ).toBe(2)

            // 4. A mounted role="status" region still contains the success
            // message, even though MemberRoleEditor (and its own status
            // paragraph) has just been unmounted, and while the overview
            // refresh is still pending.
            expect(
                screen.getByRole("status"),
            ).toHaveTextContent("Role updated.")

            // 7. The existing session-bootstrap reload behavior is
            // preserved alongside the new persistent announcement, and
            // does not wait for the overview refresh to complete.
            expect(reload).toHaveBeenCalledTimes(1)

            // 6. The refreshed Access overview eventually renders again.
            await act(async () => {
                resolveTheAuthoritativeRefresh()
            })

            await waitFor(() => {
                expect(
                    screen.getByRole("heading", { name: "Access" }),
                ).toBeInTheDocument()
            })
            expect(
                screen.getByText("Aria the GM"),
            ).toBeInTheDocument()

            // The announcement is still present after the refresh
            // completes, for the same campaign.
            expect(
                screen.getByRole("status"),
            ).toHaveTextContent("Role updated.")

            // 5. Navigating to a different campaign must never display or
            // retain this campaign's announcement.
            fireEvent.click(
                screen.getByRole("link", { name: "Switch to Campaign B" }),
            )

            await waitFor(() => {
                expect(
                    screen.getByText("Bram of Campaign B"),
                ).toBeInTheDocument()
            })
            expect(
                screen.getByRole("status"),
            ).toHaveTextContent("")
            expect(
                screen.queryByText("Role updated."),
            ).not.toBeInTheDocument()
        },
    )
})

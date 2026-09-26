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

vi.mock("../components/InvitationsSection", () => ({
    InvitationsSection: () => null,
}))

// The add-member/remove-member counterpart to CampaignAccessPage.
// roleAddRevoke.integration.test.tsx: exercises the REAL CampaignAccessPage/
// AccessOverviewBoundary/AccessPage/AddCampaignMember/RemoveCampaignMember/
// useEligibleAccountLookup/useAddCampaignMember/useRemoveCampaignMembership
// chain — nothing here is mocked except the network boundary (global
// fetch) and the session context.

const CAMPAIGN_ID = "campaign-a"
const OWNER_ROLE_ID = "role-owner"
const CURATOR_ROLE_ID = "role-curator"
const MEMBERSHIP_ID = "membership-a"
const MEMBERSHIP_ROLE_ID = "membership-role-a-1"
const OTHER_MEMBERSHIP_ID = "membership-b"

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
            {
                campaign_membership_id: OTHER_MEMBERSHIP_ID,
                user_id: "user-quiet-observer",
                display_name: "Quiet Observer",
                status_code: "active",
                status_display_name: "Active",
                joined_at: "2026-01-02T00:00:00Z",
                account_is_active: true,
                roles: [],
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

function persistentAnnouncement(container: HTMLElement): HTMLElement | null {
    return container.querySelector(".campaign-access-page__announcement")
}

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("CampaignAccessPage add-member flow", () => {
    it("selects an existing account and an initial role, disables Save until both are valid, and shows the authoritative success announcement", async () => {
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
                    method === "GET" &&
                    url.includes("/eligible-accounts")
                ) {
                    expect(url).toContain("login_name=player.one")
                    return Promise.resolve(
                        jsonResponse({
                            account: {
                                user_id: "user-player-one",
                                display_name: "Player One",
                            },
                        }),
                    )
                }

                if (
                    method === "POST" &&
                    url.endsWith(`/campaigns/${CAMPAIGN_ID}/memberships`)
                ) {
                    const body = JSON.parse(String(init?.body)) as {
                        user_id: string
                        role_id: string
                    }
                    expect(body).toEqual({
                        user_id: "user-player-one",
                        role_id: CURATOR_ROLE_ID,
                    })
                    return Promise.resolve(
                        jsonResponse(
                            {
                                campaign_membership_id: "new-membership",
                                membership_role_id: "new-membership-role",
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
        vi.stubGlobal("fetch", fetchMock)

        const { container } = renderAtCampaign()

        expect(
            await screen.findByRole("heading", { name: "Access" }),
        ).toBeInTheDocument()

        fireEvent.click(
            screen.getByRole("button", { name: "Add campaign member" }),
        )

        // No account resolved yet — Save is not even offered.
        expect(
            screen.queryByRole("button", { name: "Save" }),
        ).not.toBeInTheDocument()

        fireEvent.change(screen.getByLabelText("Login name"), {
            target: { value: "player.one" },
        })
        fireEvent.click(
            screen.getByRole("button", { name: "Find account" }),
        )

        expect(
            await screen.findByText("Player One"),
        ).toBeInTheDocument()

        const saveButton = await screen.findByRole("button", {
            name: "Save",
        })
        expect(saveButton).toBeEnabled()

        fireEvent.change(screen.getByLabelText("Initial role"), {
            target: { value: CURATOR_ROLE_ID },
        })
        fireEvent.click(saveButton)

        // Duplicate submission while pending is prevented.
        fireEvent.click(saveButton)

        await waitFor(() => {
            expect(
                screen.getByRole("heading", { name: "Loading access" }),
            ).toBeInTheDocument()
        })

        expect(persistentAnnouncement(container)).toHaveTextContent(
            "Member added.",
        )

        await act(async () => {
            resolveSecondOverview(jsonResponse(baseOverview()))
        })

        await waitFor(() => {
            expect(
                screen.getByRole("heading", { name: "Access" }),
            ).toBeInTheDocument()
        })
        expect(persistentAnnouncement(container)).toHaveTextContent(
            "Member added.",
        )

        // Exactly one add-member POST, regardless of the duplicate click.
        const addCalls = fetchMock.mock.calls.filter(
            ([input, init]) =>
                (init?.method ?? "GET") === "POST" &&
                requestUrl(input).endsWith(
                    `/campaigns/${CAMPAIGN_ID}/memberships`,
                ),
        )
        expect(addCalls).toHaveLength(1)
    })

    it("shows a clear empty state for no eligible account, and Cancel discards the in-progress selection without any mutation", async () => {
        const fetchMock = vi.fn(
            (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
                const url = requestUrl(input)
                const method = init?.method ?? "GET"

                if (method === "GET" && url.includes("/access-overview")) {
                    return Promise.resolve(jsonResponse(baseOverview()))
                }

                if (
                    method === "GET" &&
                    url.includes("/eligible-accounts")
                ) {
                    return Promise.resolve(jsonResponse({ account: null }))
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
            screen.getByRole("button", { name: "Add campaign member" }),
        )
        fireEvent.change(screen.getByLabelText("Login name"), {
            target: { value: "nonexistent" },
        })
        fireEvent.click(
            screen.getByRole("button", { name: "Find account" }),
        )

        expect(
            await screen.findByText(
                "No eligible account found for that login name.",
            ),
        ).toBeInTheDocument()
        expect(
            screen.queryByRole("button", { name: "Save" }),
        ).not.toBeInTheDocument()

        fireEvent.click(screen.getByRole("button", { name: "Cancel" }))

        expect(
            screen.queryByLabelText("Login name"),
        ).not.toBeInTheDocument()

        const mutationCalls = fetchMock.mock.calls.filter(
            ([, init]) => (init?.method ?? "GET") === "POST",
        )
        expect(mutationCalls).toHaveLength(0)
    })

    it("reports a denied add for a member without access.manage, without adding the row optimistically", async () => {
        const fetchMock = vi.fn(
            (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
                const url = requestUrl(input)
                const method = init?.method ?? "GET"

                if (method === "GET" && url.includes("/access-overview")) {
                    return Promise.resolve(jsonResponse(baseOverview()))
                }

                if (
                    method === "GET" &&
                    url.includes("/eligible-accounts")
                ) {
                    return Promise.resolve(
                        jsonResponse({
                            account: {
                                user_id: "user-player-one",
                                display_name: "Player One",
                            },
                        }),
                    )
                }

                if (
                    method === "POST" &&
                    url.endsWith(`/campaigns/${CAMPAIGN_ID}/memberships`)
                ) {
                    return Promise.resolve(new Response(null, { status: 403 }))
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
            screen.getByRole("button", { name: "Add campaign member" }),
        )
        fireEvent.change(screen.getByLabelText("Login name"), {
            target: { value: "player.one" },
        })
        fireEvent.click(
            screen.getByRole("button", { name: "Find account" }),
        )

        const saveButton = await screen.findByRole("button", {
            name: "Save",
        })
        fireEvent.click(saveButton)

        expect(
            await screen.findByText(
                "You do not have permission to make this change.",
            ),
        ).toBeInTheDocument()

        // Never optimistically added — the member list still shows only
        // the two members the overview actually returned, never a third
        // row for the rejected add.
        expect(
            screen.getAllByRole("listitem").filter((item) =>
                item.querySelector(".access-member-card"),
            ),
        ).toHaveLength(2)
    })

    it("reports a conflict for an account/campaign/role that changed underneath the request", async () => {
        const fetchMock = vi.fn(
            (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
                const url = requestUrl(input)
                const method = init?.method ?? "GET"

                if (method === "GET" && url.includes("/access-overview")) {
                    return Promise.resolve(jsonResponse(baseOverview()))
                }

                if (
                    method === "GET" &&
                    url.includes("/eligible-accounts")
                ) {
                    return Promise.resolve(
                        jsonResponse({
                            account: {
                                user_id: "user-player-one",
                                display_name: "Player One",
                            },
                        }),
                    )
                }

                if (
                    method === "POST" &&
                    url.endsWith(`/campaigns/${CAMPAIGN_ID}/memberships`)
                ) {
                    return Promise.resolve(new Response(null, { status: 409 }))
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
            screen.getByRole("button", { name: "Add campaign member" }),
        )
        fireEvent.change(screen.getByLabelText("Login name"), {
            target: { value: "player.one" },
        })
        fireEvent.click(
            screen.getByRole("button", { name: "Find account" }),
        )
        fireEvent.click(
            await screen.findByRole("button", { name: "Save" }),
        )

        expect(
            await screen.findByText(
                "This account can no longer be added — it may already be a member, or the campaign or role may no longer be available. Reload the page to see the current state.",
            ),
        ).toBeInTheDocument()
    })
})

describe("CampaignAccessPage remove-member flow", () => {
    it("requires explicit confirmation naming the member, and Cancel discards it without any mutation", async () => {
        const fetchMock = vi.fn(
            (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
                const url = requestUrl(input)
                const method = init?.method ?? "GET"

                if (method === "GET" && url.includes("/access-overview")) {
                    return Promise.resolve(jsonResponse(baseOverview()))
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

        const removeButtons = screen.getAllByRole("button", {
            name: "Remove member",
        })
        fireEvent.click(removeButtons[1])

        expect(
            screen.getByText(
                "Remove Quiet Observer from this campaign? Their access will end immediately.",
            ),
        ).toBeInTheDocument()

        fireEvent.click(screen.getByRole("button", { name: "Cancel" }))

        expect(
            screen.queryByText(
                "Remove Quiet Observer from this campaign? Their access will end immediately.",
            ),
        ).not.toBeInTheDocument()

        const mutationCalls = fetchMock.mock.calls.filter(
            ([, init]) => (init?.method ?? "GET") === "POST",
        )
        expect(mutationCalls).toHaveLength(0)
    })

    it("moves focus to Confirm when Remove member is activated by keyboard, instead of dropping it when the trigger unmounts", async () => {
        const fetchMock = vi.fn(
            (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
                const url = requestUrl(input)
                const method = init?.method ?? "GET"

                if (method === "GET" && url.includes("/access-overview")) {
                    return Promise.resolve(jsonResponse(baseOverview()))
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

        const removeButtons = screen.getAllByRole("button", {
            name: "Remove member",
        })
        const trigger = removeButtons[1]

        // Establish keyboard focus on the trigger, the way Tab would, then
        // activate it the way a browser translates a focused native
        // <button>'s Enter/Space keypress into a click (jsdom does not
        // perform that translation itself, so it is simulated explicitly
        // here — the property under test is what happens to focus once
        // the trigger's own onClick fires, not the browser's native key-
        // to-click translation).
        trigger.focus()
        expect(document.activeElement).toBe(trigger)
        fireEvent.click(trigger)

        const confirmButton = await screen.findByRole("button", {
            name: "Confirm",
        })
        expect(document.activeElement).toBe(confirmButton)
    })

    it("names self-removal distinctly, succeeds, refreshes the overview and the session bootstrap, and keeps the announcement observable through the reload", async () => {
        let overviewCallCount = 0
        let resolveSecondOverview!: (response: Response) => void
        const secondOverviewPromise = new Promise<Response>((resolve) => {
            resolveSecondOverview = resolve
        })

        const reloadMock = vi.fn().mockResolvedValue(undefined)

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
                    url.endsWith(`/memberships/${MEMBERSHIP_ID}/end`)
                ) {
                    return Promise.resolve(
                        jsonResponse(
                            { campaign_membership_id: MEMBERSHIP_ID },
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

        const { container } = render(
            <SessionContext.Provider
                value={{
                    state: {
                        status: "authenticated",
                        bootstrap: sessionBootstrapFixture,
                    },
                    reload: reloadMock,
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

        expect(
            await screen.findByRole("heading", { name: "Access" }),
        ).toBeInTheDocument()

        const removeButtons = screen.getAllByRole("button", {
            name: "Remove member",
        })
        fireEvent.click(removeButtons[0])

        expect(
            screen.getByText(
                "Remove your own access to this campaign? You will lose access immediately.",
            ),
        ).toBeInTheDocument()

        fireEvent.click(screen.getByRole("button", { name: "Confirm" }))

        await waitFor(() => {
            expect(
                screen.getByRole("heading", { name: "Loading access" }),
            ).toBeInTheDocument()
        })

        expect(persistentAnnouncement(container)).toHaveTextContent(
            "Member removed.",
        )

        await act(async () => {
            resolveSecondOverview(jsonResponse(baseOverview()))
        })

        await waitFor(() => {
            expect(
                screen.getByRole("heading", { name: "Access" }),
            ).toBeInTheDocument()
        })
        expect(persistentAnnouncement(container)).toHaveTextContent(
            "Member removed.",
        )
        expect(reloadMock).toHaveBeenCalled()
    })

    it("shows the last-manager rejection distinctly", async () => {
        const fetchMock = vi.fn(
            (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
                const url = requestUrl(input)
                const method = init?.method ?? "GET"

                if (method === "GET" && url.includes("/access-overview")) {
                    return Promise.resolve(jsonResponse(baseOverview()))
                }

                if (
                    method === "POST" &&
                    url.endsWith(`/memberships/${MEMBERSHIP_ID}/end`)
                ) {
                    return Promise.resolve(new Response(null, { status: 400 }))
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

        const removeButtons = screen.getAllByRole("button", {
            name: "Remove member",
        })
        fireEvent.click(removeButtons[0])
        fireEvent.click(screen.getByRole("button", { name: "Confirm" }))

        expect(
            await screen.findByText(
                "This member cannot be removed — the campaign must always retain at least one access manager.",
            ),
        ).toBeInTheDocument()
    })
})

describe("CampaignAccessPage add/remove-member cross-operation announcement lifecycle", () => {
    it("clears a stale success announcement the moment a different mutation starts, and keeps it cleared through that mutation's failure — successful add followed by a failed removal", async () => {
        let resolveRemove!: (response: Response) => void
        const removePromise = new Promise<Response>((resolve) => {
            resolveRemove = resolve
        })

        const fetchMock = vi.fn(
            (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
                const url = requestUrl(input)
                const method = init?.method ?? "GET"

                if (method === "GET" && url.includes("/access-overview")) {
                    return Promise.resolve(jsonResponse(baseOverview()))
                }

                if (
                    method === "GET" &&
                    url.includes("/eligible-accounts")
                ) {
                    return Promise.resolve(
                        jsonResponse({
                            account: {
                                user_id: "user-player-one",
                                display_name: "Player One",
                            },
                        }),
                    )
                }

                if (
                    method === "POST" &&
                    url.endsWith(`/campaigns/${CAMPAIGN_ID}/memberships`)
                ) {
                    return Promise.resolve(
                        jsonResponse(
                            {
                                campaign_membership_id: "new-membership",
                                membership_role_id: "new-membership-role",
                            },
                            201,
                        ),
                    )
                }

                if (
                    method === "POST" &&
                    url.endsWith(
                        `/memberships/${OTHER_MEMBERSHIP_ID}/end`,
                    )
                ) {
                    return removePromise
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

        // 1. Complete an add-member mutation successfully, and let its own
        // authoritative overview reload finish.
        fireEvent.click(
            screen.getByRole("button", { name: "Add campaign member" }),
        )
        fireEvent.change(screen.getByLabelText("Login name"), {
            target: { value: "player.one" },
        })
        fireEvent.click(
            screen.getByRole("button", { name: "Find account" }),
        )
        fireEvent.click(
            await screen.findByRole("button", { name: "Save" }),
        )

        await waitFor(() => {
            expect(persistentAnnouncement(container)).toHaveTextContent(
                "Member added.",
            )
        })
        expect(
            await screen.findByRole("heading", { name: "Access" }),
        ).toBeInTheDocument()

        // 2. Begin a different, unrelated mutation — remove the second
        // member — without waiting for this one to resolve.
        const removeButtons = screen.getAllByRole("button", {
            name: "Remove member",
        })
        fireEvent.click(removeButtons[1])
        fireEvent.click(screen.getByRole("button", { name: "Confirm" }))

        // 3. The stale "Member added." success is cleared the instant the
        // new mutation is submitted.
        await waitFor(() => {
            expect(
                screen.getByText("Removing member…"),
            ).toBeInTheDocument()
        })
        expect(persistentAnnouncement(container)).toHaveTextContent("")

        // 4. The removal fails.
        await act(async () => {
            resolveRemove(new Response(null, { status: 500 }))
        })

        // 5. The old success stays cleared; the current control presents
        // its own recoverable error — never a stale, now-misleading
        // success.
        await waitFor(() => {
            expect(
                screen.getByText(
                    "The member could not be removed. Try again.",
                ),
            ).toBeInTheDocument()
        })
        expect(persistentAnnouncement(container)).toHaveTextContent("")
    })
})

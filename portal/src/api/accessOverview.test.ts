import {
    afterEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import type {
    CampaignAccessOverview,
} from "../types/accessOverview"
import {
    AccessOverviewRequestError,
    fetchCampaignAccessOverview,
} from "./accessOverview"

const overviewFixture: CampaignAccessOverview = {
    members: [
        {
            campaign_membership_id: "membership-a",
            user_id: "user-a",
            display_name: "Player One",
            status_code: "active",
            status_display_name: "Active",
            joined_at: "2026-01-01T00:00:00Z",
            roles: [
                {
                    membership_role_id: "membership-role-a",
                    role_id: "role-a",
                    code: "player",
                    display_name: "Player",
                },
            ],
            character_relationships: [],
            grants: [],
        },
    ],
    assignable_roles: [
        {
            role_id: "role-a",
            code: "player",
            display_name: "Player",
        },
    ],
    assignable_characters: [],
    assignable_relationship_types: [],
    grantable_resource_capabilities: [],
}

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("fetchCampaignAccessOverview", () => {
    it("requests the campaign-scoped access overview and returns the typed response", async () => {
        const controller = new AbortController()

        const fetchMock = vi.fn().mockResolvedValue(
            new Response(
                JSON.stringify(overviewFixture),
                {
                    status: 200,
                    headers: {
                        "Content-Type": "application/json",
                    },
                },
            ),
        )

        vi.stubGlobal("fetch", fetchMock)

        await expect(
            fetchCampaignAccessOverview(
                "campaign/a b",
                controller.signal,
            ),
        ).resolves.toEqual(overviewFixture)

        expect(fetchMock).toHaveBeenCalledTimes(1)

        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaigns/campaign%2Fa%20b/access-overview",
            {
                method: "GET",
                headers: {
                    Accept: "application/json",
                },
                cache: "no-store",
                signal: controller.signal,
            },
        )
    })

    it("passes no signal when the caller supplies none", async () => {
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(
                JSON.stringify({ members: [] }),
                {
                    status: 200,
                    headers: {
                        "Content-Type": "application/json",
                    },
                },
            ),
        )

        vi.stubGlobal("fetch", fetchMock)

        await expect(
            fetchCampaignAccessOverview("campaign-a"),
        ).resolves.toEqual({ members: [] })

        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaigns/campaign-a/access-overview",
            {
                method: "GET",
                headers: {
                    Accept: "application/json",
                },
                cache: "no-store",
                signal: undefined,
            },
        )
    })

    it("throws a typed error for an unauthenticated response", async () => {
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(null, { status: 401 }),
        )

        vi.stubGlobal("fetch", fetchMock)

        const request =
            fetchCampaignAccessOverview("campaign-a")

        await expect(request).rejects.toBeInstanceOf(
            AccessOverviewRequestError,
        )

        await expect(request).rejects.toMatchObject({
            name: "AccessOverviewRequestError",
            status: 401,
        })
    })

    it("throws the same typed error for a non-disclosing forbidden/not-found response", async () => {
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(null, { status: 403 }),
        )

        vi.stubGlobal("fetch", fetchMock)

        const request =
            fetchCampaignAccessOverview("campaign-a")

        await expect(request).rejects.toBeInstanceOf(
            AccessOverviewRequestError,
        )

        await expect(request).rejects.toMatchObject({
            name: "AccessOverviewRequestError",
            status: 403,
            message:
                "Access overview request failed with status 403",
        })
    })

    it("throws a typed error for a recoverable server failure", async () => {
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(null, { status: 500 }),
        )

        vi.stubGlobal("fetch", fetchMock)

        const request =
            fetchCampaignAccessOverview("campaign-a")

        await expect(request).rejects.toMatchObject({
            name: "AccessOverviewRequestError",
            status: 500,
        })
    })

    it("propagates an abort so callers can distinguish it from a request failure", async () => {
        const controller = new AbortController()

        const fetchMock = vi.fn().mockImplementation(
            (
                _input: RequestInfo | URL,
                init?: RequestInit,
            ) =>
                new Promise((_resolve, reject) => {
                    init?.signal?.addEventListener(
                        "abort",
                        () => {
                            reject(
                                new DOMException(
                                    "Aborted",
                                    "AbortError",
                                ),
                            )
                        },
                    )
                }),
        )

        vi.stubGlobal("fetch", fetchMock)

        const request = fetchCampaignAccessOverview(
            "campaign-a",
            controller.signal,
        )

        controller.abort()

        await expect(request).rejects.toMatchObject({
            name: "AbortError",
        })
    })
})

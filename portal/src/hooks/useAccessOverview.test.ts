import {
    act,
    renderHook,
    waitFor,
} from "@testing-library/react"
import {
    beforeEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import {
    AccessOverviewRequestError,
} from "../api/accessOverview"
import type {
    CampaignAccessOverview,
} from "../types/accessOverview"
import { useAccessOverview } from "./useAccessOverview"

const {
    fetchCampaignAccessOverviewMock,
    reloadMock,
} = vi.hoisted(() => ({
    fetchCampaignAccessOverviewMock: vi.fn(),
    reloadMock: vi.fn(),
}))

vi.mock(
    "../api/accessOverview",
    async (importOriginal) => {
        const actual =
            await importOriginal<
                typeof import("../api/accessOverview")
            >()

        return {
            ...actual,
            fetchCampaignAccessOverview:
                fetchCampaignAccessOverviewMock,
        }
    },
)

vi.mock("../context/SessionContext", () => ({
    useSession: () => ({
        reload: reloadMock,
    }),
}))

const firstCampaignOverview: CampaignAccessOverview = {
    members: [
        {
            campaign_membership_id: "membership-a",
            user_id: "user-a",
            display_name: "Player One",
            status_code: "active",
            status_display_name: "Active",
            joined_at: "2026-01-01T00:00:00Z",
            roles: [],
            character_relationships: [],
            grants: [],
        },
    ],
    assignable_roles: [],
    assignable_characters: [],
    assignable_relationship_types: [],
}

const secondCampaignOverview: CampaignAccessOverview = {
    members: [
        {
            campaign_membership_id: "membership-b",
            user_id: "user-b",
            display_name: "Player Two",
            status_code: "active",
            status_display_name: "Active",
            joined_at: "2026-01-02T00:00:00Z",
            roles: [],
            character_relationships: [],
            grants: [],
        },
    ],
    assignable_roles: [],
    assignable_characters: [],
    assignable_relationship_types: [],
}

beforeEach(() => {
    fetchCampaignAccessOverviewMock.mockReset()
    reloadMock.mockReset()
    reloadMock.mockResolvedValue(undefined)
})

describe("useAccessOverview", () => {
    it("loads the authorized campaign access overview", async () => {
        fetchCampaignAccessOverviewMock.mockResolvedValue(
            firstCampaignOverview,
        )

        const { result } = renderHook(() =>
            useAccessOverview("campaign-a"),
        )

        expect(result.current.state).toEqual({
            status: "loading",
        })

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                overview: firstCampaignOverview,
            })
        })

        expect(
            fetchCampaignAccessOverviewMock,
        ).toHaveBeenCalledWith(
            "campaign-a",
            expect.any(AbortSignal),
        )
    })

    it("treats an empty member list as a successful, empty overview", async () => {
        fetchCampaignAccessOverviewMock.mockResolvedValue({
            members: [],
        })

        const { result } = renderHook(() =>
            useAccessOverview("campaign-a"),
        )

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                overview: { members: [] },
            })
        })
    })

    it.each([403, 404])(
        "treats HTTP %s as unavailable",
        async (status) => {
            fetchCampaignAccessOverviewMock.mockRejectedValue(
                new AccessOverviewRequestError(status),
            )

            const { result } = renderHook(() =>
                useAccessOverview("campaign-a"),
            )

            await waitFor(() => {
                expect(result.current.state).toEqual({
                    status: "unavailable",
                })
            })
        },
    )

    it("reloads the browser session after an unauthorized response", async () => {
        fetchCampaignAccessOverviewMock.mockRejectedValue(
            new AccessOverviewRequestError(401),
        )

        const { result } = renderHook(() =>
            useAccessOverview("campaign-a"),
        )

        await waitFor(() => {
            expect(reloadMock).toHaveBeenCalledTimes(1)
        })

        expect(result.current.state).toEqual({
            status: "loading",
        })
    })

    it("returns a recoverable error for other failures", async () => {
        const requestError = new Error(
            "The access overview service is unavailable",
        )

        fetchCampaignAccessOverviewMock.mockRejectedValue(
            requestError,
        )

        const { result } = renderHook(() =>
            useAccessOverview("campaign-a"),
        )

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "error",
                error: requestError,
            })
        })
    })

    it("retries the access overview request", async () => {
        const requestError = new Error(
            "The access overview service is unavailable",
        )

        fetchCampaignAccessOverviewMock
            .mockRejectedValueOnce(requestError)
            .mockResolvedValueOnce(
                firstCampaignOverview,
            )

        const { result } = renderHook(() =>
            useAccessOverview("campaign-a"),
        )

        await waitFor(() => {
            expect(result.current.state.status).toBe(
                "error",
            )
        })

        act(() => {
            result.current.retry()
        })

        expect(result.current.state).toEqual({
            status: "loading",
        })

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                overview: firstCampaignOverview,
            })
        })

        expect(
            fetchCampaignAccessOverviewMock,
        ).toHaveBeenCalledTimes(2)
    })

    it("clears the previous campaign's overview and aborts its request when the campaign changes", async () => {
        let resolveSecondRequest:
            | ((
                overview: CampaignAccessOverview,
            ) => void)
            | undefined

        const secondRequest =
            new Promise<CampaignAccessOverview>(
                (resolve) => {
                    resolveSecondRequest = resolve
                },
            )

        fetchCampaignAccessOverviewMock
            .mockResolvedValueOnce(
                firstCampaignOverview,
            )
            .mockReturnValueOnce(secondRequest)

        const { result, rerender } = renderHook(
            ({ campaignId }) =>
                useAccessOverview(campaignId),
            {
                initialProps: {
                    campaignId: "campaign-a",
                },
            },
        )

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                overview: firstCampaignOverview,
            })
        })

        const firstSignal =
            fetchCampaignAccessOverviewMock.mock
                .calls[0]?.[1] as AbortSignal

        rerender({
            campaignId: "campaign-b",
        })

        // The previous campaign's request is aborted and its overview is
        // no longer exposed while the new campaign's request is pending —
        // access data must never leak across a campaign change.
        expect(firstSignal.aborted).toBe(true)

        expect(result.current.state).toEqual({
            status: "loading",
        })

        act(() => {
            resolveSecondRequest?.(
                secondCampaignOverview,
            )
        })

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                overview: secondCampaignOverview,
            })
        })
    })

    it("ignores a late response from a stale campaign request", async () => {
        let resolveFirstRequest:
            | ((
                overview: CampaignAccessOverview,
            ) => void)
            | undefined

        const firstRequest =
            new Promise<CampaignAccessOverview>(
                (resolve) => {
                    resolveFirstRequest = resolve
                },
            )

        fetchCampaignAccessOverviewMock
            .mockReturnValueOnce(firstRequest)
            .mockResolvedValueOnce(
                secondCampaignOverview,
            )

        const { result, rerender } = renderHook(
            ({ campaignId }) =>
                useAccessOverview(campaignId),
            {
                initialProps: {
                    campaignId: "campaign-a",
                },
            },
        )

        rerender({
            campaignId: "campaign-b",
        })

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                overview: secondCampaignOverview,
            })
        })

        act(() => {
            resolveFirstRequest?.(
                firstCampaignOverview,
            )
        })

        // The stale campaign-a response must never overwrite campaign-b's
        // already-rendered overview.
        expect(result.current.state).toEqual({
            status: "success",
            overview: secondCampaignOverview,
        })
    })

    it("aborts the request when the hook unmounts", () => {
        fetchCampaignAccessOverviewMock.mockReturnValue(
            new Promise<CampaignAccessOverview>(
                () => { },
            ),
        )

        const { unmount } = renderHook(() =>
            useAccessOverview("campaign-a"),
        )

        const signal =
            fetchCampaignAccessOverviewMock.mock
                .calls[0]?.[1] as AbortSignal

        expect(signal.aborted).toBe(false)

        unmount()

        expect(signal.aborted).toBe(true)
    })
})

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
import { CampaignSessionsRequestError } from "../api/campaignSessions"
import type {
    CampaignSessionListItem,
} from "../types/campaignSession"
import { useCampaignSessions } from "./useCampaignSessions"

const {
    fetchCampaignSessionsMock,
    reloadMock,
} = vi.hoisted(() => ({
    fetchCampaignSessionsMock: vi.fn(),
    reloadMock: vi.fn(),
}))

vi.mock(
    "../api/campaignSessions",
    async (importOriginal) => {
        const actual =
            await importOriginal<
                typeof import("../api/campaignSessions")
            >()

        return {
            ...actual,
            fetchCampaignSessions:
                fetchCampaignSessionsMock,
        }
    },
)

vi.mock("../context/SessionContext", () => ({
    useSession: () => ({
        reload: reloadMock,
    }),
}))

const sessionsFixture: CampaignSessionListItem[] = [
    {
        session_id: "session-12",
        session_number: 12,
        title: "The Glass Ossuary",
        status_code: "ended",
        started_at: "2026-08-30T18:00:00Z",
        ended_at: "2026-08-30T22:00:00Z",
    },
]

const secondCampaignSessionsFixture:
    CampaignSessionListItem[] = [
        {
            session_id: "session-3",
            session_number: 3,
            title: "A Different Campaign",
            status_code: "active",
            started_at: "2026-09-04T18:00:00Z",
            ended_at: null,
        },
    ]

beforeEach(() => {
    fetchCampaignSessionsMock.mockReset()
    reloadMock.mockReset()
    reloadMock.mockResolvedValue(undefined)
})

describe("useCampaignSessions", () => {
    it("loads an authorized session list", async () => {
        fetchCampaignSessionsMock.mockResolvedValue(
            sessionsFixture,
        )

        const { result } = renderHook(() =>
            useCampaignSessions("campaign-a"),
        )

        expect(result.current.state).toEqual({
            status: "loading",
        })

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                sessions: sessionsFixture,
            })
        })

        expect(
            fetchCampaignSessionsMock,
        ).toHaveBeenCalledWith(
            "campaign-a",
            expect.any(AbortSignal),
        )
    })

    it("preserves an authorized empty list as success", async () => {
        fetchCampaignSessionsMock.mockResolvedValue([])

        const { result } = renderHook(() =>
            useCampaignSessions("campaign-a"),
        )

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                sessions: [],
            })
        })
    })

    it.each([403, 404])(
        "treats HTTP %s as unavailable",
        async (status) => {
            fetchCampaignSessionsMock.mockRejectedValue(
                new CampaignSessionsRequestError(status),
            )

            const { result } = renderHook(() =>
                useCampaignSessions("campaign-a"),
            )

            await waitFor(() => {
                expect(result.current.state).toEqual({
                    status: "unavailable",
                })
            })
        },
    )

    it("reloads the session after an unauthorized response", async () => {
        fetchCampaignSessionsMock.mockRejectedValue(
            new CampaignSessionsRequestError(401),
        )

        const { result } = renderHook(() =>
            useCampaignSessions("campaign-a"),
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
            "The sessions service is unavailable",
        )

        fetchCampaignSessionsMock.mockRejectedValue(
            requestError,
        )

        const { result } = renderHook(() =>
            useCampaignSessions("campaign-a"),
        )

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "error",
                error: requestError,
            })
        })
    })

    it("retries the session-list request", async () => {
        const requestError = new Error(
            "The sessions service is unavailable",
        )

        fetchCampaignSessionsMock
            .mockRejectedValueOnce(requestError)
            .mockResolvedValueOnce(sessionsFixture)

        const { result } = renderHook(() =>
            useCampaignSessions("campaign-a"),
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
                sessions: sessionsFixture,
            })
        })

        expect(
            fetchCampaignSessionsMock,
        ).toHaveBeenCalledTimes(2)
    })

    it("hides the previous campaign list while the next campaign loads", async () => {
        let resolveSecondCampaign:
            | ((
                sessions: CampaignSessionListItem[],
            ) => void)
            | undefined

        const secondCampaignRequest =
            new Promise<CampaignSessionListItem[]>(
                (resolve) => {
                    resolveSecondCampaign = resolve
                },
            )

        fetchCampaignSessionsMock
            .mockResolvedValueOnce(sessionsFixture)
            .mockReturnValueOnce(secondCampaignRequest)

        const { result, rerender } = renderHook(
            ({ campaignId }) =>
                useCampaignSessions(campaignId),
            {
                initialProps: {
                    campaignId: "campaign-a",
                },
            },
        )

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                sessions: sessionsFixture,
            })
        })

        const firstSignal =
            fetchCampaignSessionsMock.mock.calls[0]?.[1] as
            AbortSignal

        rerender({
            campaignId: "campaign-b",
        })

        expect(firstSignal.aborted).toBe(true)

        expect(result.current.state).toEqual({
            status: "loading",
        })

        act(() => {
            resolveSecondCampaign?.(
                secondCampaignSessionsFixture,
            )
        })

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                sessions: secondCampaignSessionsFixture,
            })
        })
    })

    it("aborts the request when the hook unmounts", () => {
        fetchCampaignSessionsMock.mockReturnValue(
            new Promise<CampaignSessionListItem[]>(
                () => { },
            ),
        )

        const { unmount } = renderHook(() =>
            useCampaignSessions("campaign-a"),
        )

        const signal =
            fetchCampaignSessionsMock.mock.calls[0]?.[1] as
            AbortSignal

        expect(signal.aborted).toBe(false)

        unmount()

        expect(signal.aborted).toBe(true)
    })
})
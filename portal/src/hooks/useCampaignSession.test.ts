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
    CampaignSessionsRequestError,
} from "../api/campaignSessions"
import type {
    CampaignSessionDetail,
} from "../types/campaignSession"
import { useCampaignSession } from "./useCampaignSession"

const {
    fetchCampaignSessionMock,
    reloadMock,
} = vi.hoisted(() => ({
    fetchCampaignSessionMock: vi.fn(),
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
            fetchCampaignSession:
                fetchCampaignSessionMock,
        }
    },
)

vi.mock("../context/SessionContext", () => ({
    useSession: () => ({
        reload: reloadMock,
    }),
}))

const sessionFixture: CampaignSessionDetail = {
    session_id: "session-a",
    session_number: 1,
    title: "Session A",
    status_code: "ended",
    started_at: "2026-01-01T18:00:00Z",
    ended_at: "2026-01-01T22:00:00Z",
    summary: "The party entered the ruins.",
    start_world_time_id: "world-time-start-a",
    end_world_time_id: "world-time-end-a",
    events: [],
}

const secondSessionFixture: CampaignSessionDetail = {
    ...sessionFixture,
    session_id: "session-b",
    session_number: 2,
    title: "Session B",
    summary: "The party discovered the sealed chamber.",
    start_world_time_id: "world-time-start-b",
    end_world_time_id: "world-time-end-b",
}

beforeEach(() => {
    fetchCampaignSessionMock.mockReset()
    reloadMock.mockReset()
    reloadMock.mockResolvedValue(undefined)
})

describe("useCampaignSession", () => {
    it("loads an authorized session", async () => {
        fetchCampaignSessionMock.mockResolvedValue(
            sessionFixture,
        )

        const { result } = renderHook(() =>
            useCampaignSession(
                "campaign-a",
                "session-a",
            ),
        )

        expect(result.current.state).toEqual({
            status: "loading",
        })

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                session: sessionFixture,
            })
        })

        expect(
            fetchCampaignSessionMock,
        ).toHaveBeenCalledWith(
            "campaign-a",
            "session-a",
            expect.any(AbortSignal),
        )
    })

    it.each([403, 404])(
        "treats HTTP %s as unavailable",
        async (status) => {
            fetchCampaignSessionMock.mockRejectedValue(
                new CampaignSessionsRequestError(status),
            )

            const { result } = renderHook(() =>
                useCampaignSession(
                    "campaign-a",
                    "session-a",
                ),
            )

            await waitFor(() => {
                expect(result.current.state).toEqual({
                    status: "unavailable",
                })
            })
        },
    )

    it("reloads the browser session after an unauthorized response", async () => {
        fetchCampaignSessionMock.mockRejectedValue(
            new CampaignSessionsRequestError(401),
        )

        const { result } = renderHook(() =>
            useCampaignSession(
                "campaign-a",
                "session-a",
            ),
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
            "The session service is unavailable",
        )

        fetchCampaignSessionMock.mockRejectedValue(
            requestError,
        )

        const { result } = renderHook(() =>
            useCampaignSession(
                "campaign-a",
                "session-a",
            ),
        )

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "error",
                error: requestError,
            })
        })
    })

    it("retries the session request", async () => {
        const requestError = new Error(
            "The session service is unavailable",
        )

        fetchCampaignSessionMock
            .mockRejectedValueOnce(requestError)
            .mockResolvedValueOnce(sessionFixture)

        const { result } = renderHook(() =>
            useCampaignSession(
                "campaign-a",
                "session-a",
            ),
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
                session: sessionFixture,
            })
        })

        expect(
            fetchCampaignSessionMock,
        ).toHaveBeenCalledTimes(2)
    })

    it("hides the previous session while a new session loads", async () => {
        let resolveSecondSession:
            | ((session: CampaignSessionDetail) => void)
            | undefined

        const secondSessionRequest =
            new Promise<CampaignSessionDetail>(
                (resolve) => {
                    resolveSecondSession = resolve
                },
            )

        fetchCampaignSessionMock
            .mockResolvedValueOnce(sessionFixture)
            .mockReturnValueOnce(secondSessionRequest)

        const { result, rerender } = renderHook(
            ({ sessionId }) =>
                useCampaignSession(
                    "campaign-a",
                    sessionId,
                ),
            {
                initialProps: {
                    sessionId: "session-a",
                },
            },
        )

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                session: sessionFixture,
            })
        })

        const firstSignal =
            fetchCampaignSessionMock.mock
                .calls[0]?.[2] as AbortSignal

        rerender({
            sessionId: "session-b",
        })

        expect(firstSignal.aborted).toBe(true)

        expect(result.current.state).toEqual({
            status: "loading",
        })

        act(() => {
            resolveSecondSession?.(
                secondSessionFixture,
            )
        })

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                session: secondSessionFixture,
            })
        })
    })

    it("aborts the request when the hook unmounts", () => {
        fetchCampaignSessionMock.mockReturnValue(
            new Promise<CampaignSessionDetail>(
                () => { },
            ),
        )

        const { unmount } = renderHook(() =>
            useCampaignSession(
                "campaign-a",
                "session-a",
            ),
        )

        const signal =
            fetchCampaignSessionMock.mock
                .calls[0]?.[2] as AbortSignal

        expect(signal.aborted).toBe(false)

        unmount()

        expect(signal.aborted).toBe(true)
    })
})
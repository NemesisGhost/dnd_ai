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
    CampaignSummaryRequestError,
    fetchCampaignSummary,
} from "../api/campaignSummary"
import { useSession } from "../context/SessionContext"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import type { CampaignSummary } from "../types/campaignSummary"
import { useCampaignSummary } from "./useCampaignSummary"

vi.mock(
    "../api/campaignSummary",
    async (importOriginal) => {
        const original =
            await importOriginal<
                typeof import("../api/campaignSummary")
            >()

        return {
            ...original,
            fetchCampaignSummary: vi.fn(),
        }
    },
)

vi.mock("../context/SessionContext", () => ({
    useSession: vi.fn(),
}))

const fetchCampaignSummaryMock =
    vi.mocked(fetchCampaignSummary)

const useSessionMock = vi.mocked(useSession)

const reloadSession = vi.fn()

const campaignSummaryFixture = {
    current_session: null,
    previous_session_recap:
        "The party entered the dormant facility.",
    recent_events: [],
} satisfies CampaignSummary

beforeEach(() => {
    fetchCampaignSummaryMock.mockReset()
    useSessionMock.mockReset()
    reloadSession.mockReset()

    useSessionMock.mockReturnValue({
        state: {
            status: "authenticated",
            bootstrap: sessionBootstrapFixture,
        },
        reload: reloadSession,
    })
})

describe("useCampaignSummary", () => {
    it("moves from loading to success", async () => {
        fetchCampaignSummaryMock.mockResolvedValue(
            campaignSummaryFixture,
        )

        const { result } = renderHook(() =>
            useCampaignSummary("campaign-a"),
        )

        expect(result.current.state).toEqual({
            status: "loading",
        })

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                summary: campaignSummaryFixture,
            })
        })

        expect(
            fetchCampaignSummaryMock,
        ).toHaveBeenCalledWith(
            "campaign-a",
            expect.any(AbortSignal),
        )
    })

    it.each([403, 404])(
        "maps status %s to the same unavailable state",
        async (status) => {
            fetchCampaignSummaryMock.mockRejectedValue(
                new CampaignSummaryRequestError(status),
            )

            const { result } = renderHook(() =>
                useCampaignSummary("campaign-a"),
            )

            await waitFor(() => {
                expect(result.current.state).toEqual({
                    status: "unavailable",
                })
            })

            expect(reloadSession).not.toHaveBeenCalled()
        },
    )

    it("reloads the session after an unauthorized response", async () => {
        fetchCampaignSummaryMock.mockRejectedValue(
            new CampaignSummaryRequestError(401),
        )

        const { result } = renderHook(() =>
            useCampaignSummary("campaign-a"),
        )

        await waitFor(() => {
            expect(reloadSession).toHaveBeenCalledTimes(1)
        })

        expect(result.current.state).toEqual({
            status: "loading",
        })
    })

    it("exposes a recoverable error for other failures", async () => {
        const networkError = new TypeError(
            "Failed to fetch",
        )

        fetchCampaignSummaryMock.mockRejectedValue(
            networkError,
        )

        const { result } = renderHook(() =>
            useCampaignSummary("campaign-a"),
        )

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "error",
                error: networkError,
            })
        })

        expect(reloadSession).not.toHaveBeenCalled()
    })

    it("returns to loading and requests fresh data when retried", async () => {
        let completeRetry:
            | ((summary: CampaignSummary) => void)
            | undefined

        const retryRequest = new Promise<CampaignSummary>(
            (resolve) => {
                completeRetry = resolve
            },
        )

        fetchCampaignSummaryMock
            .mockResolvedValueOnce(campaignSummaryFixture)
            .mockReturnValueOnce(retryRequest)

        const { result } = renderHook(() =>
            useCampaignSummary("campaign-a"),
        )

        await waitFor(() => {
            expect(result.current.state.status).toBe(
                "success",
            )
        })

        act(() => {
            result.current.retry()
        })

        expect(result.current.state).toEqual({
            status: "loading",
        })

        await waitFor(() => {
            expect(
                fetchCampaignSummaryMock,
            ).toHaveBeenCalledTimes(2)
        })

        const resolveRetry = completeRetry

        if (resolveRetry === undefined) {
            throw new Error(
                "Expected the retry request to be pending",
            )
        }

        await act(async () => {
            resolveRetry({
                ...campaignSummaryFixture,
                previous_session_recap:
                    "The refreshed recap.",
            })
        })

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                summary: {
                    ...campaignSummaryFixture,
                    previous_session_recap:
                        "The refreshed recap.",
                },
            })
        })
    })

    it("aborts the request when the hook unmounts", () => {
        let receivedSignal: AbortSignal | undefined

        fetchCampaignSummaryMock.mockImplementation(
            (_campaignId, signal) => {
                receivedSignal = signal

                return new Promise<CampaignSummary>(
                    () => undefined,
                )
            },
        )

        const { unmount } = renderHook(() =>
            useCampaignSummary("campaign-a"),
        )

        if (receivedSignal === undefined) {
            throw new Error(
                "Expected the hook to provide an AbortSignal",
            )
        }

        expect(receivedSignal.aborted).toBe(false)

        unmount()

        expect(receivedSignal.aborted).toBe(true)
    })
})
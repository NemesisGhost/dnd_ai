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
    WorldRequestError,
} from "../api/world"
import type {
    WorldCategory,
    WorldEntityPage,
} from "../types/world"
import { useWorldEntities } from "./useWorldEntities"

const {
    fetchWorldEntitiesMock,
    reloadMock,
} = vi.hoisted(() => ({
    fetchWorldEntitiesMock: vi.fn(),
    reloadMock: vi.fn(),
}))

vi.mock(
    "../api/world",
    async (importOriginal) => {
        const actual =
            await importOriginal<
                typeof import("../api/world")
            >()

        return {
            ...actual,
            fetchWorldEntities:
                fetchWorldEntitiesMock,
        }
    },
)

vi.mock("../context/SessionContext", () => ({
    useSession: () => ({
        reload: reloadMock,
    }),
}))

const firstPage: WorldEntityPage = {
    items: [
        {
            entity_id: "location-1",
            category: "location",
            entity_type_code: "city",
            name: "First location",
            summary: null,
        },
    ],
    next_cursor: "next-cursor",
}

const secondPage: WorldEntityPage = {
    items: [
        {
            entity_id: "event-1",
            category: "event",
            entity_type_code: "historical_event",
            name: "Second result",
            summary: null,
        },
    ],
    next_cursor: null,
}

beforeEach(() => {
    fetchWorldEntitiesMock.mockReset()
    reloadMock.mockReset()
    reloadMock.mockResolvedValue(undefined)
})

describe("useWorldEntities", () => {
    it("loads an authorized page", async () => {
        fetchWorldEntitiesMock.mockResolvedValue(
            firstPage,
        )

        const { result } = renderHook(() =>
            useWorldEntities(
                "campaign-a",
                "location",
                "glass",
            ),
        )

        expect(result.current.state).toEqual({
            status: "loading",
        })

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                page: firstPage,
            })
        })

        expect(
            fetchWorldEntitiesMock,
        ).toHaveBeenCalledWith(
            "campaign-a",
            {
                category: "location",
                query: "glass",
                cursor: null,
            },
            expect.any(AbortSignal),
        )
    })

    it.each([403, 404])(
        "treats HTTP %s as unavailable",
        async (status) => {
            fetchWorldEntitiesMock.mockRejectedValue(
                new WorldRequestError(status),
            )

            const { result } = renderHook(() =>
                useWorldEntities(
                    "campaign-a",
                    null,
                    "",
                ),
            )

            await waitFor(() => {
                expect(result.current.state).toEqual({
                    status: "unavailable",
                })
            })
        },
    )

    it("reloads the session after an unauthorized response", async () => {
        fetchWorldEntitiesMock.mockRejectedValue(
            new WorldRequestError(401),
        )

        const { result } = renderHook(() =>
            useWorldEntities(
                "campaign-a",
                null,
                "",
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
            "The World service is unavailable",
        )

        fetchWorldEntitiesMock.mockRejectedValue(
            requestError,
        )

        const { result } = renderHook(() =>
            useWorldEntities(
                "campaign-a",
                null,
                "",
            ),
        )

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "error",
                error: requestError,
            })
        })
    })

    it("retries the request", async () => {
        const requestError = new Error(
            "The World service is unavailable",
        )

        fetchWorldEntitiesMock
            .mockRejectedValueOnce(requestError)
            .mockResolvedValueOnce(firstPage)

        const { result } = renderHook(() =>
            useWorldEntities(
                "campaign-a",
                "location",
                "",
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
                page: firstPage,
            })
        })

        expect(
            fetchWorldEntitiesMock,
        ).toHaveBeenCalledTimes(2)
    })

    it("keeps the previous page visible while refreshing within the same campaign", async () => {
        let resolveSecondRequest:
            | ((page: WorldEntityPage) => void)
            | undefined

        const pendingSecondRequest =
            new Promise<WorldEntityPage>(
                (resolve) => {
                    resolveSecondRequest = resolve
                },
            )

        fetchWorldEntitiesMock
            .mockResolvedValueOnce(firstPage)
            .mockReturnValueOnce(
                pendingSecondRequest,
            )

        const { result, rerender } = renderHook(
            ({ category, query }) =>
                useWorldEntities(
                    "campaign-a",
                    category,
                    query,
                ),
            {
                initialProps: {
                    category: "location" as WorldCategory,
                    query: "",
                },
            },
        )

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                page: firstPage,
            })
        })

        const firstSignal =
            fetchWorldEntitiesMock.mock
                .calls[0]?.[2] as AbortSignal

        rerender({
            category: "event",
            query: "sundering",
        })

        expect(firstSignal.aborted).toBe(true)

        expect(result.current.state).toEqual({
            status: "refreshing",
            page: firstPage,
        })

        act(() => {
            resolveSecondRequest?.(secondPage)
        })

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                page: secondPage,
            })
        })
    })

    it("clears the previous page immediately on a campaign change", async () => {
        fetchWorldEntitiesMock.mockResolvedValueOnce(
            firstPage,
        )

        const { result, rerender } = renderHook(
            ({ campaignId }) =>
                useWorldEntities(
                    campaignId,
                    null,
                    "",
                ),
            {
                initialProps: {
                    campaignId: "campaign-a",
                },
            },
        )

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                page: firstPage,
            })
        })

        fetchWorldEntitiesMock.mockReturnValueOnce(
            new Promise<WorldEntityPage>(() => { }),
        )

        rerender({
            campaignId: "campaign-b",
        })

        expect(result.current.state).toEqual({
            status: "loading",
        })
    })

    it("discards a retained page when the refresh fails", async () => {
        fetchWorldEntitiesMock.mockResolvedValueOnce(
            firstPage,
        )

        const { result, rerender } = renderHook(
            ({ query }) =>
                useWorldEntities(
                    "campaign-a",
                    null,
                    query,
                ),
            {
                initialProps: {
                    query: "",
                },
            },
        )

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                page: firstPage,
            })
        })

        fetchWorldEntitiesMock.mockRejectedValueOnce(
            new WorldRequestError(404),
        )

        rerender({
            query: "sundering",
        })

        expect(result.current.state).toEqual({
            status: "refreshing",
            page: firstPage,
        })

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "unavailable",
            })
        })
    })

    it("requests the supplied next-page cursor", async () => {
        fetchWorldEntitiesMock.mockResolvedValue(
            secondPage,
        )

        const { result } = renderHook(() =>
            useWorldEntities(
                "campaign-a",
                "event",
                "",
                "next-page-cursor",
            ),
        )

        await waitFor(() => {
            expect(result.current.state.status).toBe(
                "success",
            )
        })

        expect(
            fetchWorldEntitiesMock,
        ).toHaveBeenCalledWith(
            "campaign-a",
            {
                category: "event",
                query: "",
                cursor: "next-page-cursor",
            },
            expect.any(AbortSignal),
        )
    })

    it("aborts the request when the hook unmounts", () => {
        fetchWorldEntitiesMock.mockReturnValue(
            new Promise<WorldEntityPage>(
                () => { },
            ),
        )

        const { unmount } = renderHook(() =>
            useWorldEntities(
                "campaign-a",
                null,
                "",
            ),
        )

        const signal =
            fetchWorldEntitiesMock.mock
                .calls[0]?.[2] as AbortSignal

        expect(signal.aborted).toBe(false)

        unmount()

        expect(signal.aborted).toBe(true)
    })
})
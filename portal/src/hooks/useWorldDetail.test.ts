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
import { WorldRequestError } from "../api/world"
import { useWorldDetail } from "./useWorldDetail"

const { reloadMock } = vi.hoisted(() => ({
    reloadMock: vi.fn(),
}))

vi.mock("../context/SessionContext", () => ({
    useSession: () => ({
        reload: reloadMock,
    }),
}))

interface Fixture {
    id: string
}

const fixtureA: Fixture = { id: "a" }
const fixtureB: Fixture = { id: "b" }

beforeEach(() => {
    reloadMock.mockReset()
    reloadMock.mockResolvedValue(undefined)
})

describe("useWorldDetail", () => {
    it("loads an authorized detail record", async () => {
        const fetchDetail = vi.fn().mockResolvedValue(fixtureA)

        const { result } = renderHook(() =>
            useWorldDetail(fetchDetail, "campaign-a", "entity-a"),
        )

        expect(result.current.state).toEqual({ status: "loading" })

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                detail: fixtureA,
            })
        })

        expect(fetchDetail).toHaveBeenCalledWith(
            "campaign-a",
            "entity-a",
            expect.any(AbortSignal),
        )
    })

    it.each([403, 404])(
        "treats HTTP %s as unavailable",
        async (status) => {
            const fetchDetail = vi
                .fn()
                .mockRejectedValue(new WorldRequestError(status))

            const { result } = renderHook(() =>
                useWorldDetail(fetchDetail, "campaign-a", "entity-a"),
            )

            await waitFor(() => {
                expect(result.current.state).toEqual({
                    status: "unavailable",
                })
            })
        },
    )

    it("reloads the session after an unauthorized response", async () => {
        const fetchDetail = vi
            .fn()
            .mockRejectedValue(new WorldRequestError(401))

        const { result } = renderHook(() =>
            useWorldDetail(fetchDetail, "campaign-a", "entity-a"),
        )

        await waitFor(() => {
            expect(reloadMock).toHaveBeenCalledTimes(1)
        })

        expect(result.current.state).toEqual({ status: "loading" })
    })

    it("returns a recoverable error for other failures", async () => {
        const requestError = new Error("The service is unavailable")
        const fetchDetail = vi.fn().mockRejectedValue(requestError)

        const { result } = renderHook(() =>
            useWorldDetail(fetchDetail, "campaign-a", "entity-a"),
        )

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "error",
                error: requestError,
            })
        })
    })

    it("retries the request", async () => {
        const requestError = new Error("The service is unavailable")
        const fetchDetail = vi
            .fn()
            .mockRejectedValueOnce(requestError)
            .mockResolvedValueOnce(fixtureA)

        const { result } = renderHook(() =>
            useWorldDetail(fetchDetail, "campaign-a", "entity-a"),
        )

        await waitFor(() => {
            expect(result.current.state.status).toBe("error")
        })

        act(() => {
            result.current.retry()
        })

        expect(result.current.state).toEqual({ status: "loading" })

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                detail: fixtureA,
            })
        })

        expect(fetchDetail).toHaveBeenCalledTimes(2)
    })

    it("never shows the previous record while a new entity id loads", async () => {
        let resolveSecond: ((value: Fixture) => void) | undefined
        const secondRequest = new Promise<Fixture>((resolve) => {
            resolveSecond = resolve
        })

        const fetchDetail = vi
            .fn()
            .mockResolvedValueOnce(fixtureA)
            .mockReturnValueOnce(secondRequest)

        const { result, rerender } = renderHook(
            ({ entityId }) =>
                useWorldDetail(fetchDetail, "campaign-a", entityId),
            { initialProps: { entityId: "entity-a" } },
        )

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                detail: fixtureA,
            })
        })

        const firstSignal = fetchDetail.mock.calls[0]?.[2] as AbortSignal

        rerender({ entityId: "entity-b" })

        expect(firstSignal.aborted).toBe(true)
        expect(result.current.state).toEqual({ status: "loading" })

        act(() => {
            resolveSecond?.(fixtureB)
        })

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                detail: fixtureB,
            })
        })
    })

    it("aborts the request when the hook unmounts", () => {
        const fetchDetail = vi
            .fn()
            .mockReturnValue(new Promise<Fixture>(() => {}))

        const { unmount } = renderHook(() =>
            useWorldDetail(fetchDetail, "campaign-a", "entity-a"),
        )

        const signal = fetchDetail.mock.calls[0]?.[2] as AbortSignal

        expect(signal.aborted).toBe(false)

        unmount()

        expect(signal.aborted).toBe(true)
    })
})

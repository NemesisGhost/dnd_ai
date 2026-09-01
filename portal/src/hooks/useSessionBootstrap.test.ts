import {
    act,
    renderHook,
    waitFor,
} from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { fetchSessionBootstrap } from "../api/session"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { useSessionBootstrap } from "./useSessionBootstrap"

vi.mock("../api/session", () => ({
    fetchSessionBootstrap: vi.fn(),
}))

const fetchSessionBootstrapMock = vi.mocked(
    fetchSessionBootstrap,
)

beforeEach(() => {
    fetchSessionBootstrapMock.mockReset()
})

describe("useSessionBootstrap", () => {
    it("moves from loading to authenticated", async () => {
        fetchSessionBootstrapMock.mockResolvedValue(
            sessionBootstrapFixture,
        )

        const { result } = renderHook(() => useSessionBootstrap())

        expect(result.current.state).toEqual({
            status: "loading",
        })

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "authenticated",
                bootstrap: sessionBootstrapFixture,
            })
        })
    })

    it("moves from loading to unauthenticated", async () => {
        fetchSessionBootstrapMock.mockResolvedValue(null)

        const { result } = renderHook(() => useSessionBootstrap())

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "unauthenticated",
            })
        })
    })

    it("moves from loading to error when the request fails", async () => {
        const error = new Error("Backend unavailable")

        fetchSessionBootstrapMock.mockRejectedValue(error)

        const { result } = renderHook(() => useSessionBootstrap())

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "error",
                error,
            })
        })
    })

    it("aborts the request when the hook unmounts", () => {
        let receivedSignal: AbortSignal | undefined

        fetchSessionBootstrapMock.mockImplementation((signal) => {
            receivedSignal = signal
            return new Promise<never>(() => { })
        })

        const { unmount } = renderHook(() => useSessionBootstrap())

        if (receivedSignal === undefined) {
            throw new Error("Expected the hook to provide an AbortSignal")
        }

        expect(receivedSignal.aborted).toBe(false)

        unmount()

        expect(receivedSignal.aborted).toBe(true)
    })

    it("returns to loading and requests fresh state when reloaded", async () => {
        let resolveReload: (() => void) | undefined

        const reloadRequest = new Promise<null>((resolve) => {
            resolveReload = () => {
                resolve(null)
            }
        })

        fetchSessionBootstrapMock
            .mockResolvedValueOnce(sessionBootstrapFixture)
            .mockReturnValueOnce(reloadRequest)

        const { result } = renderHook(() => useSessionBootstrap())

        await waitFor(() => {
            expect(result.current.state.status).toBe("authenticated")
        })

        act(() => {
            result.current.reload()
        })

        expect(result.current.state).toEqual({
            status: "loading",
        })

        expect(fetchSessionBootstrapMock).toHaveBeenCalledTimes(2)

        const completeReload = resolveReload

        if (completeReload === undefined) {
            throw new Error("Expected the reload request to be pending")
        }

        await act(async () => {
            completeReload()
        })

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "unauthenticated",
            })
        })
    })
})
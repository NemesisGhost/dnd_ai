import { act, renderHook, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { OwnSessionsRequestError } from "../api/ownSessions"
import { useRevokeOwnSession } from "./useRevokeOwnSession"

const { revokeOwnSessionMock, sessionStateRef } = vi.hoisted(() => ({
    revokeOwnSessionMock: vi.fn(),
    sessionStateRef: {
        current: {
            status: "authenticated" as const,
            bootstrap: { csrf_token: "fixture-csrf-token" },
        },
    },
}))

vi.mock("../api/ownSessions", async (importOriginal) => {
    const actual = await importOriginal<typeof import("../api/ownSessions")>()
    return { ...actual, revokeOwnSession: revokeOwnSessionMock }
})
vi.mock("../context/SessionContext", () => ({
    useSession: () => ({ state: sessionStateRef.current, reload: vi.fn() }),
}))

beforeEach(() => {
    revokeOwnSessionMock.mockReset()
    sessionStateRef.current = {
        status: "authenticated",
        bootstrap: { csrf_token: "fixture-csrf-token" },
    }
})

describe("useRevokeOwnSession", () => {
    it("revokes another session and reports isCurrent=false", async () => {
        revokeOwnSessionMock.mockResolvedValue(undefined)
        const onSuccess = vi.fn()
        const { result } = renderHook(() => useRevokeOwnSession(onSuccess))

        act(() => {
            result.current.submit("session-2", false)
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "success" })
        })
        expect(onSuccess).toHaveBeenCalledWith("session-2", false)
    })

    it("revokes the current session and reports isCurrent=true", async () => {
        revokeOwnSessionMock.mockResolvedValue(undefined)
        const onSuccess = vi.fn()
        const { result } = renderHook(() => useRevokeOwnSession(onSuccess))

        act(() => {
            result.current.submit("session-1", true)
        })

        await waitFor(() => {
            expect(onSuccess).toHaveBeenCalledWith("session-1", true)
        })
    })

    it("maps a 404 to denied", async () => {
        revokeOwnSessionMock.mockRejectedValue(new OwnSessionsRequestError(404, "not found"))
        const { result } = renderHook(() => useRevokeOwnSession(vi.fn()))

        act(() => {
            result.current.submit("session-2", false)
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "denied" })
        })
    })
})

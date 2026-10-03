import { act, renderHook, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { PlatformAccountsRequestError } from "../api/platformAccounts"
import { useRevokeAllSessions } from "./useRevokeAllSessions"

const { revokeAllSessionsMock, reloadMock, sessionStateRef } = vi.hoisted(() => ({
    revokeAllSessionsMock: vi.fn(),
    reloadMock: vi.fn(),
    sessionStateRef: {
        current: {
            status: "authenticated" as const,
            bootstrap: { csrf_token: "fixture-csrf-token" },
        },
    },
}))

vi.mock("../api/revokeAllSessions", () => ({ revokeAllSessions: revokeAllSessionsMock }))
vi.mock("../context/SessionContext", () => ({
    useSession: () => ({ state: sessionStateRef.current, reload: reloadMock }),
}))

beforeEach(() => {
    revokeAllSessionsMock.mockReset()
    reloadMock.mockReset()
    sessionStateRef.current = {
        status: "authenticated",
        bootstrap: { csrf_token: "fixture-csrf-token" },
    }
})

describe("useRevokeAllSessions", () => {
    it("revokes successfully", async () => {
        revokeAllSessionsMock.mockResolvedValue({ user_id: "user-1", revoked_count: 2 })

        const { result } = renderHook(() => useRevokeAllSessions(vi.fn()))
        act(() => {
            result.current.submit("user-1")
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "success" })
        })
    })

    it("maps a 404 to denied", async () => {
        revokeAllSessionsMock.mockRejectedValue(new PlatformAccountsRequestError(404, "denied"))
        const { result } = renderHook(() => useRevokeAllSessions(vi.fn()))

        act(() => {
            result.current.submit("user-1")
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "denied" })
        })
    })
})

import { act, renderHook, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { PlatformAccountsRequestError } from "../api/platformAccounts"
import { useReactivateAccount } from "./useReactivateAccount"

const { reactivateAccountMock, reloadMock, sessionStateRef } = vi.hoisted(() => ({
    reactivateAccountMock: vi.fn(),
    reloadMock: vi.fn(),
    sessionStateRef: {
        current: {
            status: "authenticated" as const,
            bootstrap: { csrf_token: "fixture-csrf-token" },
        },
    },
}))

vi.mock("../api/reactivateAccount", () => ({ reactivateAccount: reactivateAccountMock }))
vi.mock("../context/SessionContext", () => ({
    useSession: () => ({ state: sessionStateRef.current, reload: reloadMock }),
}))

beforeEach(() => {
    reactivateAccountMock.mockReset()
    reloadMock.mockReset()
    sessionStateRef.current = {
        status: "authenticated",
        bootstrap: { csrf_token: "fixture-csrf-token" },
    }
})

describe("useReactivateAccount", () => {
    it("reactivates successfully", async () => {
        reactivateAccountMock.mockResolvedValue({
            user_id: "user-1",
            previous_lifecycle_status: "inactive",
            new_lifecycle_status: "active",
        })

        const { result } = renderHook(() => useReactivateAccount(vi.fn()))
        act(() => {
            result.current.submit("user-1")
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "success" })
        })
    })

    it("maps a 404 to denied", async () => {
        reactivateAccountMock.mockRejectedValue(new PlatformAccountsRequestError(404, "denied"))
        const { result } = renderHook(() => useReactivateAccount(vi.fn()))

        act(() => {
            result.current.submit("user-1")
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "denied" })
        })
    })
})

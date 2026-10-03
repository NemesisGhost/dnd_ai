import { act, renderHook, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { PlatformAccountsRequestError } from "../api/platformAccounts"
import { useDisableAccount } from "./useDisableAccount"

const { disableAccountMock, reloadMock, sessionStateRef } = vi.hoisted(() => ({
    disableAccountMock: vi.fn(),
    reloadMock: vi.fn(),
    sessionStateRef: {
        current: {
            status: "authenticated" as const,
            bootstrap: { csrf_token: "fixture-csrf-token" },
        },
    },
}))

vi.mock("../api/disableAccount", () => ({ disableAccount: disableAccountMock }))
vi.mock("../context/SessionContext", () => ({
    useSession: () => ({ state: sessionStateRef.current, reload: reloadMock }),
}))

beforeEach(() => {
    disableAccountMock.mockReset()
    reloadMock.mockReset()
    sessionStateRef.current = {
        status: "authenticated",
        bootstrap: { csrf_token: "fixture-csrf-token" },
    }
})

describe("useDisableAccount", () => {
    it("disables successfully", async () => {
        const onSuccess = vi.fn()
        disableAccountMock.mockResolvedValue({
            user_id: "user-1",
            previous_lifecycle_status: "active",
            new_lifecycle_status: "inactive",
        })

        const { result } = renderHook(() => useDisableAccount(onSuccess))
        act(() => {
            result.current.submit("user-1")
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "success" })
        })
    })

    it("maps a 409 last-active-administrator conflict to a specific message", async () => {
        disableAccountMock.mockRejectedValue(new PlatformAccountsRequestError(409, "conflict"))
        const { result } = renderHook(() => useDisableAccount(vi.fn()))

        act(() => {
            result.current.submit("user-1")
        })

        await waitFor(() => {
            expect(result.current.status.kind).toBe("conflict")
        })
    })
})

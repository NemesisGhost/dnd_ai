import { act, renderHook, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { PlatformAccountsRequestError } from "../api/platformAccounts"
import { useCreateAccount } from "./useCreateAccount"

const { createAccountMock, reloadMock, sessionStateRef } = vi.hoisted(() => ({
    createAccountMock: vi.fn(),
    reloadMock: vi.fn(),
    sessionStateRef: {
        current: {
            status: "authenticated" as const,
            bootstrap: { csrf_token: "fixture-csrf-token" },
        },
    },
}))

vi.mock("../api/createAccount", () => ({ createAccount: createAccountMock }))
vi.mock("../context/SessionContext", () => ({
    useSession: () => ({ state: sessionStateRef.current, reload: reloadMock }),
}))

beforeEach(() => {
    createAccountMock.mockReset()
    reloadMock.mockReset()
    sessionStateRef.current = {
        status: "authenticated",
        bootstrap: { csrf_token: "fixture-csrf-token" },
    }
})

describe("useCreateAccount", () => {
    it("creates successfully with the session csrf token", async () => {
        const onSuccess = vi.fn()
        createAccountMock.mockResolvedValue({
            user_id: "user-1",
            login_name: "new.gm",
            raw_activation_token: "raw-token",
            expires_at: "2026-10-01T00:00:00Z",
        })

        const { result } = renderHook(() => useCreateAccount(onSuccess))
        act(() => {
            result.current.submit("new.gm", "New GM", null)
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "success" })
        })
        expect(createAccountMock).toHaveBeenCalledWith(
            "new.gm",
            "New GM",
            null,
            "fixture-csrf-token",
            expect.anything(),
        )
        expect(onSuccess).toHaveBeenCalled()
    })

    it("maps a 404 to denied", async () => {
        createAccountMock.mockRejectedValue(new PlatformAccountsRequestError(404, "denied"))
        const { result } = renderHook(() => useCreateAccount(vi.fn()))

        act(() => {
            result.current.submit("new.gm", "New GM", null)
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "denied" })
        })
    })

    it("does nothing when not authenticated", () => {
        sessionStateRef.current = { status: "unauthenticated" } as never
        const { result } = renderHook(() => useCreateAccount(vi.fn()))

        act(() => {
            result.current.submit("new.gm", "New GM", null)
        })

        expect(createAccountMock).not.toHaveBeenCalled()
    })
})

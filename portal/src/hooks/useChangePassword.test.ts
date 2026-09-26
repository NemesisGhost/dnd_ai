import { act, renderHook, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { ChangePasswordRequestError } from "../api/changePassword"
import { useChangePassword } from "./useChangePassword"

const { changePasswordMock, sessionStateRef } = vi.hoisted(() => ({
    changePasswordMock: vi.fn(),
    sessionStateRef: {
        current: {
            status: "authenticated" as const,
            bootstrap: { csrf_token: "fixture-csrf-token" },
        },
    },
}))

vi.mock("../api/changePassword", async (importOriginal) => {
    const actual = await importOriginal<typeof import("../api/changePassword")>()
    return { ...actual, changePassword: changePasswordMock }
})
vi.mock("../context/SessionContext", () => ({
    useSession: () => ({ state: sessionStateRef.current, reload: vi.fn() }),
}))

beforeEach(() => {
    changePasswordMock.mockReset()
    sessionStateRef.current = {
        status: "authenticated",
        bootstrap: { csrf_token: "fixture-csrf-token" },
    }
})

describe("useChangePassword", () => {
    it("changes successfully", async () => {
        changePasswordMock.mockResolvedValue(undefined)
        const onSuccess = vi.fn()
        const { result } = renderHook(() => useChangePassword(onSuccess))

        act(() => {
            result.current.submit("old-password-15-chars", "new-password-15-chars")
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "success" })
        })
        expect(changePasswordMock).toHaveBeenCalledWith(
            "old-password-15-chars",
            "new-password-15-chars",
            "fixture-csrf-token",
            expect.anything(),
        )
    })

    it("maps a wrong current password (401) to denied", async () => {
        changePasswordMock.mockRejectedValue(new ChangePasswordRequestError(401, "wrong"))
        const { result } = renderHook(() => useChangePassword(vi.fn()))

        act(() => {
            result.current.submit("wrong", "new-password-15-chars")
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "denied" })
        })
    })

    it("maps a weak new password (400) to policy_violation", async () => {
        changePasswordMock.mockRejectedValue(new ChangePasswordRequestError(400, "weak"))
        const { result } = renderHook(() => useChangePassword(vi.fn()))

        act(() => {
            result.current.submit("old-password-15-chars", "weak")
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "policy_violation" })
        })
    })
})

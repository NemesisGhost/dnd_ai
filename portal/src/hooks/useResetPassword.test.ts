import { act, renderHook, waitFor } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { ResetPasswordRequestError } from "../api/resetPassword"
import { useResetPassword } from "./useResetPassword"

const { resetPasswordMock } = vi.hoisted(() => ({ resetPasswordMock: vi.fn() }))

vi.mock("../api/resetPassword", async (importOriginal) => {
    const actual = await importOriginal<typeof import("../api/resetPassword")>()
    return { ...actual, resetPassword: resetPasswordMock }
})

describe("useResetPassword", () => {
    it("resets successfully", async () => {
        resetPasswordMock.mockResolvedValue({ user_id: "user-1", sessions_revoked: true })
        const { result } = renderHook(() => useResetPassword())

        act(() => {
            result.current.submit("raw-token", "new-password-15-chars")
        })

        await waitFor(() => {
            expect(result.current.status.kind).toBe("success")
        })
    })

    it("maps a 429 to rate_limited", async () => {
        resetPasswordMock.mockRejectedValue(new ResetPasswordRequestError(429, "too many"))
        const { result } = renderHook(() => useResetPassword())

        act(() => {
            result.current.submit("raw-token", "new-password-15-chars")
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "rate_limited" })
        })
    })
})

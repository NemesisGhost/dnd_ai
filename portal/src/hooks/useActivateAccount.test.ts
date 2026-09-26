import { act, renderHook, waitFor } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { ActivateAccountRequestError } from "../api/activateAccount"
import { useActivateAccount } from "./useActivateAccount"

const { activateAccountMock } = vi.hoisted(() => ({ activateAccountMock: vi.fn() }))

vi.mock("../api/activateAccount", async (importOriginal) => {
    const actual = await importOriginal<typeof import("../api/activateAccount")>()
    return { ...actual, activateAccount: activateAccountMock }
})

describe("useActivateAccount", () => {
    it("activates successfully", async () => {
        activateAccountMock.mockResolvedValue({ user_id: "user-1", login_name: "new.gm" })
        const { result } = renderHook(() => useActivateAccount())

        act(() => {
            result.current.submit("raw-token", "correct-password-15-chars")
        })

        await waitFor(() => {
            expect(result.current.status.kind).toBe("success")
        })
        expect(activateAccountMock).toHaveBeenCalledWith(
            "raw-token",
            "correct-password-15-chars",
            expect.anything(),
        )
    })

    it("maps a 400 to policy_violation and a 404 to unavailable", async () => {
        activateAccountMock.mockRejectedValueOnce(new ActivateAccountRequestError(400, "weak"))
        const { result } = renderHook(() => useActivateAccount())
        act(() => {
            result.current.submit("raw-token", "weak")
        })
        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "policy_violation" })
        })

        act(() => {
            result.current.reset()
        })
        activateAccountMock.mockRejectedValueOnce(new ActivateAccountRequestError(404, "gone"))
        act(() => {
            result.current.submit("raw-token", "correct-password-15-chars")
        })
        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "unavailable" })
        })
    })
})

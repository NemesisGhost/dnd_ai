import { act, renderHook, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { PlatformAccountsRequestError } from "../api/platformAccounts"
import { useIssuePasswordReset } from "./useIssuePasswordReset"

const { issuePasswordResetMock, reloadMock, sessionStateRef } = vi.hoisted(() => ({
    issuePasswordResetMock: vi.fn(),
    reloadMock: vi.fn(),
    sessionStateRef: {
        current: {
            status: "authenticated" as const,
            bootstrap: { csrf_token: "fixture-csrf-token" },
        },
    },
}))

vi.mock("../api/issuePasswordReset", () => ({ issuePasswordReset: issuePasswordResetMock }))
vi.mock("../context/SessionContext", () => ({
    useSession: () => ({ state: sessionStateRef.current, reload: reloadMock }),
}))

beforeEach(() => {
    issuePasswordResetMock.mockReset()
    reloadMock.mockReset()
    sessionStateRef.current = {
        status: "authenticated",
        bootstrap: { csrf_token: "fixture-csrf-token" },
    }
})

describe("useIssuePasswordReset", () => {
    it("issues a reset successfully", async () => {
        const onSuccess = vi.fn()
        issuePasswordResetMock.mockResolvedValue({
            user_id: "user-1",
            raw_reset_token: "raw-token",
            expires_at: "2026-10-01T00:00:00Z",
        })

        const { result } = renderHook(() => useIssuePasswordReset(onSuccess))
        act(() => {
            result.current.submit("user-1", true)
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "success" })
        })
        expect(issuePasswordResetMock).toHaveBeenCalledWith(
            "user-1",
            true,
            "fixture-csrf-token",
            expect.anything(),
        )
    })

    it("maps a 404 to denied", async () => {
        issuePasswordResetMock.mockRejectedValue(new PlatformAccountsRequestError(404, "denied"))
        const { result } = renderHook(() => useIssuePasswordReset(vi.fn()))

        act(() => {
            result.current.submit("user-1", true)
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "denied" })
        })
    })
})

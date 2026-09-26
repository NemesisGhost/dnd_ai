import { act, renderHook, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { InvitationOnboardingRequestError } from "../api/invitationOnboarding"
import { useCompleteInvitationOnboarding } from "./useCompleteInvitationOnboarding"

const { completeInvitationOnboardingMock, reloadMock, sessionStateRef } = vi.hoisted(() => ({
    completeInvitationOnboardingMock: vi.fn(),
    reloadMock: vi.fn(),
    sessionStateRef: {
        current: {
            status: "authenticated" as const,
            bootstrap: { csrf_token: "fixture-csrf-token" },
        },
    },
}))

vi.mock("../api/invitationOnboarding", async (importOriginal) => {
    const actual = await importOriginal<typeof import("../api/invitationOnboarding")>()
    return {
        ...actual,
        completeInvitationOnboarding: completeInvitationOnboardingMock,
    }
})

vi.mock("../context/SessionContext", () => ({
    useSession: () => ({
        state: sessionStateRef.current,
        reload: reloadMock,
    }),
}))

beforeEach(() => {
    completeInvitationOnboardingMock.mockReset()
    reloadMock.mockReset()
    sessionStateRef.current = {
        status: "authenticated",
        bootstrap: { csrf_token: "fixture-csrf-token" },
    }
})

describe("useCompleteInvitationOnboarding", () => {
    it("completes successfully with the session csrf token", async () => {
        completeInvitationOnboardingMock.mockResolvedValue({
            campaign_display_name: "Fixture Campaign",
        })

        const { result } = renderHook(() => useCompleteInvitationOnboarding())

        act(() => {
            result.current.submit()
        })

        await waitFor(() => {
            expect(result.current.status.kind).toBe("success")
        })
        expect(completeInvitationOnboardingMock).toHaveBeenCalledWith(
            "fixture-csrf-token",
            expect.anything(),
        )
    })

    it("maps a 401 to session_expired and reloads, without navigating", async () => {
        completeInvitationOnboardingMock.mockRejectedValue(
            new InvitationOnboardingRequestError(401, "expired"),
        )

        const { result } = renderHook(() => useCompleteInvitationOnboarding())

        act(() => {
            result.current.submit()
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "session_expired" })
        })
        expect(reloadMock).toHaveBeenCalledTimes(1)
    })

    it("maps a 404 to unavailable", async () => {
        completeInvitationOnboardingMock.mockRejectedValue(
            new InvitationOnboardingRequestError(404, "unavailable"),
        )

        const { result } = renderHook(() => useCompleteInvitationOnboarding())

        act(() => {
            result.current.submit()
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "unavailable" })
        })
    })

    it("does nothing when not authenticated", () => {
        sessionStateRef.current = { status: "unauthenticated" } as never

        const { result } = renderHook(() => useCompleteInvitationOnboarding())

        act(() => {
            result.current.submit()
        })

        expect(completeInvitationOnboardingMock).not.toHaveBeenCalled()
        expect(result.current.status).toEqual({ kind: "idle" })
    })
})

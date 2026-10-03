import { act, render, renderHook, screen, waitFor } from "@testing-library/react"
import { StrictMode, useEffect, useRef } from "react"
import { describe, expect, it, vi } from "vitest"
import { InvitationOnboardingRequestError } from "../api/invitationOnboarding"
import type { BeginInvitationOnboardingResponse } from "../types/invitationOnboarding"
import { useBeginInvitationOnboarding } from "./useBeginInvitationOnboarding"

// Mirrors AcceptCampaignInvitationPage's own mount effect: submit() is
// called from a ref-guarded effect with an empty dependency array, exactly
// the pattern that exposed the StrictMode double-invoke bug (submit fires
// during the tree's real *first* mount pass, which is the pass StrictMode
// replays).
function AutoSubmitHarness({ token }: { token: string }) {
    const submittedRef = useRef(false)
    const { status, submit } = useBeginInvitationOnboarding()

    useEffect(() => {
        if (submittedRef.current) {
            return
        }
        submittedRef.current = true
        submit(token)
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    return <p>status:{status.kind}</p>
}

const { beginInvitationOnboardingMock } = vi.hoisted(() => ({
    beginInvitationOnboardingMock: vi.fn(),
}))

vi.mock("../api/invitationOnboarding", async (importOriginal) => {
    const actual = await importOriginal<typeof import("../api/invitationOnboarding")>()
    return {
        ...actual,
        beginInvitationOnboarding: beginInvitationOnboardingMock,
    }
})

describe("useBeginInvitationOnboarding", () => {
    it("begins successfully", async () => {
        beginInvitationOnboardingMock.mockResolvedValue({
            campaign_display_name: "Fixture Campaign",
            invitation_expires_at: "2026-10-01T00:00:00Z",
            onboarding_expires_at: "2026-09-25T00:20:00Z",
            onboarding_csrf_token: "onboarding-csrf",
            next_action: "sign_in_or_register",
            signed_in_display_name: null,
        })

        const { result } = renderHook(() => useBeginInvitationOnboarding())

        act(() => {
            result.current.submit("raw-invitation-token")
        })

        expect(result.current.status).toEqual({ kind: "pending" })

        await waitFor(() => {
            expect(result.current.status.kind).toBe("success")
        })
        expect(beginInvitationOnboardingMock).toHaveBeenCalledWith(
            "raw-invitation-token",
            expect.anything(),
        )
    })

    it("maps a 404 to unavailable", async () => {
        beginInvitationOnboardingMock.mockRejectedValue(
            new InvitationOnboardingRequestError(404, "not available"),
        )

        const { result } = renderHook(() => useBeginInvitationOnboarding())

        act(() => {
            result.current.submit("raw-invitation-token")
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "unavailable" })
        })
    })

    it("maps a 429 to rate_limited", async () => {
        beginInvitationOnboardingMock.mockRejectedValue(
            new InvitationOnboardingRequestError(429, "too many"),
        )

        const { result } = renderHook(() => useBeginInvitationOnboarding())

        act(() => {
            result.current.submit("raw-invitation-token")
        })

        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "rate_limited" })
        })
    })

    it("reset returns to idle", async () => {
        beginInvitationOnboardingMock.mockRejectedValue(
            new InvitationOnboardingRequestError(404, "not available"),
        )

        const { result } = renderHook(() => useBeginInvitationOnboarding())

        act(() => {
            result.current.submit("raw-invitation-token")
        })
        await waitFor(() => {
            expect(result.current.status).toEqual({ kind: "unavailable" })
        })

        act(() => {
            result.current.reset()
        })
        expect(result.current.status).toEqual({ kind: "idle" })
    })

    it("resolves a mount-effect-driven submit under StrictMode's double-invoked effects", async () => {
        beginInvitationOnboardingMock.mockClear()
        let resolveRequest: ((value: BeginInvitationOnboardingResponse) => void) | null = null
        beginInvitationOnboardingMock.mockImplementation(
            () =>
                new Promise<BeginInvitationOnboardingResponse>((resolve) => {
                    resolveRequest = resolve
                }),
        )

        render(
            <StrictMode>
                <AutoSubmitHarness token="raw-invitation-token" />
            </StrictMode>,
        )

        // Exactly one live request should remain after StrictMode's replay
        // aborts the first attempt: two invocations is the pre-fix
        // regression signature (a second, real submit), zero is a request
        // that silently never fires.
        expect(beginInvitationOnboardingMock).toHaveBeenCalledTimes(1)
        expect(await screen.findByText("status:pending")).toBeInTheDocument()

        act(() => {
            resolveRequest?.({
                campaign_display_name: "Fixture Campaign",
                invitation_expires_at: "2026-10-01T00:00:00Z",
                onboarding_expires_at: "2026-09-25T00:20:00Z",
                onboarding_csrf_token: "onboarding-csrf",
                next_action: "sign_in_or_register",
                signed_in_display_name: null,
            })
        })

        expect(await screen.findByText("status:success")).toBeInTheDocument()
    })
})

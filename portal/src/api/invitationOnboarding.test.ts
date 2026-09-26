import { afterEach, describe, expect, it, vi } from "vitest"
import {
    beginInvitationOnboarding,
    cancelInvitationOnboarding,
    completeInvitationOnboarding,
    fetchInvitationOnboardingStatus,
    InvitationOnboardingRequestError,
    registerInvitedAccount,
} from "./invitationOnboarding"

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("invitation onboarding API", () => {
    it("posts the invitation token only, in the body, on start", async () => {
        const controller = new AbortController()
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(
                JSON.stringify({
                    campaign_display_name: "Onboarding Campaign",
                    invitation_expires_at: "2026-10-01T00:00:00Z",
                    onboarding_expires_at: "2026-09-25T00:20:00Z",
                    onboarding_csrf_token: "onboarding-csrf",
                    next_action: "sign_in_or_register",
                    signed_in_display_name: null,
                }),
                { status: 201, headers: { "Content-Type": "application/json" } },
            ),
        )
        vi.stubGlobal("fetch", fetchMock)

        await expect(
            beginInvitationOnboarding("raw-invitation-token", controller.signal),
        ).resolves.toEqual({
            campaign_display_name: "Onboarding Campaign",
            invitation_expires_at: "2026-10-01T00:00:00Z",
            onboarding_expires_at: "2026-09-25T00:20:00Z",
            onboarding_csrf_token: "onboarding-csrf",
            next_action: "sign_in_or_register",
            signed_in_display_name: null,
        })

        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaign-invitations/onboarding/start",
            {
                method: "POST",
                credentials: "same-origin",
                cache: "no-store",
                signal: controller.signal,
                headers: {
                    Accept: "application/json",
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({ token: "raw-invitation-token" }),
            },
        )
    })

    it("gets status with no body and same-origin credentials", async () => {
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(
                JSON.stringify({
                    campaign_display_name: "Onboarding Campaign",
                    invitation_expires_at: "2026-10-01T00:00:00Z",
                    onboarding_expires_at: "2026-09-25T00:20:00Z",
                    next_action: "confirm",
                    signed_in_display_name: "Existing User",
                }),
                { status: 200, headers: { "Content-Type": "application/json" } },
            ),
        )
        vi.stubGlobal("fetch", fetchMock)

        await expect(fetchInvitationOnboardingStatus()).resolves.toMatchObject({
            next_action: "confirm",
            signed_in_display_name: "Existing User",
        })

        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaign-invitations/onboarding/status",
            {
                method: "GET",
                credentials: "same-origin",
                cache: "no-store",
                signal: undefined,
                headers: { Accept: "application/json" },
            },
        )
    })

    it("posts registration with the onboarding CSRF header, never the session one", async () => {
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(
                JSON.stringify({
                    csrf_token: "session-csrf",
                    campaign_display_name: "Onboarding Campaign",
                }),
                { status: 201, headers: { "Content-Type": "application/json" } },
            ),
        )
        vi.stubGlobal("fetch", fetchMock)

        await expect(
            registerInvitedAccount(
                "new.player",
                "New Player",
                "correct-onboarding-password-15",
                "onboarding-csrf",
            ),
        ).resolves.toEqual({
            csrf_token: "session-csrf",
            campaign_display_name: "Onboarding Campaign",
        })

        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaign-invitations/onboarding/register",
            {
                method: "POST",
                credentials: "same-origin",
                cache: "no-store",
                signal: undefined,
                headers: {
                    Accept: "application/json",
                    "Content-Type": "application/json",
                    "X-Onboarding-CSRF-Token": "onboarding-csrf",
                },
                body: JSON.stringify({
                    login_name: "new.player",
                    display_name: "New Player",
                    password: "correct-onboarding-password-15",
                }),
            },
        )
    })

    it("posts completion with the session CSRF header and no body", async () => {
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(
                JSON.stringify({ campaign_display_name: "Onboarding Campaign" }),
                { status: 200, headers: { "Content-Type": "application/json" } },
            ),
        )
        vi.stubGlobal("fetch", fetchMock)

        await expect(completeInvitationOnboarding("session-csrf")).resolves.toEqual({
            campaign_display_name: "Onboarding Campaign",
        })

        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaign-invitations/onboarding/complete",
            {
                method: "POST",
                credentials: "same-origin",
                cache: "no-store",
                signal: undefined,
                headers: {
                    Accept: "application/json",
                    "X-CSRF-Token": "session-csrf",
                },
            },
        )
    })

    it("posts cancellation with the onboarding CSRF header", async () => {
        const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
        vi.stubGlobal("fetch", fetchMock)

        await expect(cancelInvitationOnboarding("onboarding-csrf")).resolves.toBeUndefined()

        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaign-invitations/onboarding/cancel",
            {
                method: "POST",
                credentials: "same-origin",
                cache: "no-store",
                signal: undefined,
                headers: { "X-Onboarding-CSRF-Token": "onboarding-csrf" },
            },
        )
    })

    it("throws a typed request error for a non-disclosing rejection", async () => {
        vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 404 })))

        await expect(fetchInvitationOnboardingStatus()).rejects.toMatchObject({
            name: "InvitationOnboardingRequestError",
            status: 404,
        } satisfies Partial<InvitationOnboardingRequestError>)
    })

    it("propagates aborts from start", async () => {
        const controller = new AbortController()
        vi.stubGlobal(
            "fetch",
            vi.fn().mockImplementation(
                (_input: RequestInfo | URL, init?: RequestInit) =>
                    new Promise((_resolve, reject) => {
                        init?.signal?.addEventListener("abort", () => {
                            reject(new DOMException("Aborted", "AbortError"))
                        })
                    }),
            ),
        )

        const request = beginInvitationOnboarding("raw-token", controller.signal)
        controller.abort()

        await expect(request).rejects.toMatchObject({ name: "AbortError" })
    })
})

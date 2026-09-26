import { fireEvent, render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { InvitationOnboardingConfirm } from "./InvitationOnboardingConfirm"

const { completeStatusRef, submitMock, logoutMock, reloadMock, sessionStateRef } = vi.hoisted(
    () => ({
        completeStatusRef: { current: { kind: "idle" as string } },
        submitMock: vi.fn(),
        logoutMock: vi.fn(),
        reloadMock: vi.fn(),
        sessionStateRef: {
            current: {
                status: "authenticated" as const,
                bootstrap: { csrf_token: "session-csrf" },
            },
        },
    }),
)

vi.mock("../hooks/useCompleteInvitationOnboarding", () => ({
    useCompleteInvitationOnboarding: () => ({
        status: completeStatusRef.current,
        submit: submitMock,
        reset: vi.fn(),
    }),
}))

vi.mock("../api/logout", () => ({
    logout: logoutMock,
    LogoutRequestError: class LogoutRequestError extends Error {},
}))

vi.mock("../context/SessionContext", () => ({
    useSession: () => ({ state: sessionStateRef.current, reload: reloadMock }),
}))

beforeEach(() => {
    completeStatusRef.current = { kind: "idle" }
    submitMock.mockReset()
    logoutMock.mockReset()
    reloadMock.mockReset()
    sessionStateRef.current = {
        status: "authenticated",
        bootstrap: { csrf_token: "session-csrf" },
    }
})

describe("InvitationOnboardingConfirm", () => {
    it("names the campaign and the signed-in account, and never submits without a click", () => {
        render(
            <InvitationOnboardingConfirm
                campaignDisplayName="Fixture Campaign"
                signedInDisplayName="Existing User"
                onCompleted={vi.fn()}
                onNeedsStatusRefresh={vi.fn()}
            />,
        )

        expect(screen.getByText("Existing User", { exact: false })).toBeInTheDocument()
        expect(screen.getByRole("heading", { name: "Join Fixture Campaign?" })).toBeInTheDocument()
        expect(submitMock).not.toHaveBeenCalled()
    })

    it("submits only on an explicit click of the join button", () => {
        render(
            <InvitationOnboardingConfirm
                campaignDisplayName="Fixture Campaign"
                signedInDisplayName="Existing User"
                onCompleted={vi.fn()}
                onNeedsStatusRefresh={vi.fn()}
            />,
        )

        fireEvent.click(screen.getByRole("button", { name: /join fixture campaign/i }))
        expect(submitMock).toHaveBeenCalledTimes(1)
    })

    it("calls onCompleted once the hook reports success", () => {
        completeStatusRef.current = {
            kind: "success",
            result: { campaign_display_name: "Fixture Campaign" },
        } as never
        const onCompleted = vi.fn()

        render(
            <InvitationOnboardingConfirm
                campaignDisplayName="Fixture Campaign"
                signedInDisplayName="Existing User"
                onCompleted={onCompleted}
                onNeedsStatusRefresh={vi.fn()}
            />,
        )

        expect(onCompleted).toHaveBeenCalledWith({ campaign_display_name: "Fixture Campaign" })
    })

    it("logs out and requests a status refresh on 'use a different account', never a silent switch", async () => {
        logoutMock.mockResolvedValue(undefined)
        const onNeedsStatusRefresh = vi.fn()

        render(
            <InvitationOnboardingConfirm
                campaignDisplayName="Fixture Campaign"
                signedInDisplayName="Existing User"
                onCompleted={vi.fn()}
                onNeedsStatusRefresh={onNeedsStatusRefresh}
            />,
        )

        fireEvent.click(screen.getByRole("button", { name: "Use a different account" }))

        await vi.waitFor(() => {
            expect(logoutMock).toHaveBeenCalledWith("session-csrf")
        })
        expect(reloadMock).toHaveBeenCalledTimes(1)
        expect(onNeedsStatusRefresh).toHaveBeenCalledTimes(1)
        expect(submitMock).not.toHaveBeenCalled()
    })

    it("requests a status refresh, never navigating, when the session expires mid-flow", () => {
        completeStatusRef.current = { kind: "session_expired" }
        const onNeedsStatusRefresh = vi.fn()

        render(
            <InvitationOnboardingConfirm
                campaignDisplayName="Fixture Campaign"
                signedInDisplayName="Existing User"
                onCompleted={vi.fn()}
                onNeedsStatusRefresh={onNeedsStatusRefresh}
            />,
        )

        expect(onNeedsStatusRefresh).toHaveBeenCalledTimes(1)
    })
})

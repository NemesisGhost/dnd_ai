import { fireEvent, render, screen } from "@testing-library/react"
import { StrictMode } from "react"
import { MemoryRouter, Route, Routes } from "react-router"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { SessionContext } from "../context/SessionContext"
import type { SessionBootstrapState } from "../hooks/useSessionBootstrap"
import type { AcceptCampaignInvitationStatus } from "../hooks/useAcceptCampaignInvitation"
import type { BeginInvitationOnboardingStatus } from "../hooks/useBeginInvitationOnboarding"
import type { InvitationOnboardingStatusState } from "../hooks/useInvitationOnboardingStatus"
import { AcceptCampaignInvitationPage } from "./AcceptCampaignInvitationPage"

const {
    acceptHookRef,
    beginHookRef,
    beginSubmitMock,
    statusHookRef,
    statusRetryMock,
    reloadMock,
} = vi.hoisted(() => ({
    acceptHookRef: {
        current: {
            status: { kind: "idle" as AcceptCampaignInvitationStatus["kind"] },
            submit: vi.fn(),
            reset: vi.fn(),
        },
    },
    beginHookRef: {
        current: {
            status: { kind: "idle" as BeginInvitationOnboardingStatus["kind"] },
        },
    },
    beginSubmitMock: vi.fn(),
    statusHookRef: {
        current: {
            state: { status: "unavailable" } as InvitationOnboardingStatusState,
        },
    },
    statusRetryMock: vi.fn(),
    reloadMock: vi.fn(),
}))

vi.mock("../hooks/useAcceptCampaignInvitation", () => ({
    useAcceptCampaignInvitation: () => acceptHookRef.current,
}))

vi.mock("../hooks/useBeginInvitationOnboarding", () => ({
    useBeginInvitationOnboarding: () => ({
        status: beginHookRef.current.status,
        submit: beginSubmitMock,
        reset: vi.fn(),
    }),
}))

vi.mock("../hooks/useInvitationOnboardingStatus", () => ({
    useInvitationOnboardingStatus: () => ({
        state: statusHookRef.current.state,
        retry: statusRetryMock,
    }),
}))

vi.mock("../components/InvitationOnboardingSignIn", () => ({
    InvitationOnboardingSignIn: ({ onSignedIn }: { onSignedIn: () => void }) => (
        <button type="button" onClick={onSignedIn}>
            fake-sign-in-success
        </button>
    ),
}))

vi.mock("../components/InvitationOnboardingRegister", () => ({
    InvitationOnboardingRegister: ({
        onRegistered,
    }: {
        onRegistered: (result: { campaign_display_name: string }) => void
    }) => (
        <button
            type="button"
            onClick={() => onRegistered({ campaign_display_name: "Fixture Campaign" })}
        >
            fake-register-success
        </button>
    ),
}))

vi.mock("../components/InvitationOnboardingConfirm", () => ({
    InvitationOnboardingConfirm: ({
        onCompleted,
    }: {
        onCompleted: (result: { campaign_display_name: string }) => void
    }) => (
        <button
            type="button"
            onClick={() => onCompleted({ campaign_display_name: "Fixture Campaign" })}
        >
            fake-confirm-success
        </button>
    ),
}))

beforeEach(() => {
    acceptHookRef.current = { status: { kind: "idle" }, submit: vi.fn(), reset: vi.fn() }
    beginHookRef.current = { status: { kind: "idle" } }
    beginSubmitMock.mockReset()
    statusHookRef.current = { state: { status: "unavailable" } }
    statusRetryMock.mockReset()
    reloadMock.mockReset()
    window.history.replaceState(null, "", "/campaign-invitations/accept")
})

afterEach(() => {
    window.history.replaceState(null, "", "/campaign-invitations/accept")
})

function renderPage(sessionState: SessionBootstrapState, path = "/campaign-invitations/accept") {
    return render(
        <SessionContext.Provider value={{ state: sessionState, reload: reloadMock }}>
            <MemoryRouter initialEntries={[path]}>
                <Routes>
                    <Route
                        path="/campaign-invitations/accept"
                        element={<AcceptCampaignInvitationPage />}
                    />
                    <Route path="/login" element={<p>Login page</p>} />
                </Routes>
            </MemoryRouter>
        </SessionContext.Provider>,
    )
}

describe("AcceptCampaignInvitationPage — no onboarding cookie (legacy manual path)", () => {
    it("redirects an unauthenticated visitor with no onboarding cookie to login", async () => {
        renderPage({ status: "unauthenticated" })

        expect(await screen.findByText("Login page")).toBeInTheDocument()
    })

    it("renders the manual-token fallback for an authenticated visitor with no cookie", () => {
        renderPage({ status: "authenticated", bootstrap: sessionBootstrapFixture })

        expect(
            screen.getByRole("heading", { name: "Accept campaign invitation" }),
        ).toBeInTheDocument()
        const input = screen.getByLabelText("Invitation token")
        expect(input).toHaveAttribute("type", "password")
    })
})

describe("AcceptCampaignInvitationPage — hash-driven onboarding", () => {
    it("consumes the token fragment once, clears it, and begins onboarding", () => {
        window.history.replaceState(null, "", "/campaign-invitations/accept#token=raw-token")

        renderPage({ status: "unauthenticated" })

        expect(beginSubmitMock).toHaveBeenCalledWith("raw-token")
        expect(beginSubmitMock).toHaveBeenCalledTimes(1)
        expect(window.location.hash).toBe("")
    })

    it("starts exactly one onboarding session under StrictMode's double-invoked effects", () => {
        window.history.replaceState(null, "", "/campaign-invitations/accept#token=raw-token")

        render(
            <StrictMode>
                <SessionContext.Provider
                    value={{ state: { status: "unauthenticated" }, reload: reloadMock }}
                >
                    <MemoryRouter initialEntries={["/campaign-invitations/accept"]}>
                        <Routes>
                            <Route
                                path="/campaign-invitations/accept"
                                element={<AcceptCampaignInvitationPage />}
                            />
                        </Routes>
                    </MemoryRouter>
                </SessionContext.Provider>
            </StrictMode>,
        )

        expect(beginSubmitMock).toHaveBeenCalledTimes(1)
    })

    it("shows a loading state while the hash-driven begin request is in flight", () => {
        window.history.replaceState(null, "", "/campaign-invitations/accept#token=raw-token")
        beginHookRef.current = { status: { kind: "pending" } }

        renderPage({ status: "unauthenticated" })

        expect(screen.getByText("Opening your invitation")).toBeInTheDocument()
    })

    it("renders a calm terminal state when begin reports the invitation unavailable, never an error with retry", () => {
        beginHookRef.current = { status: { kind: "unavailable" } }

        renderPage({ status: "unauthenticated" })

        expect(
            screen.getByRole("heading", { name: "This invitation is no longer available" }),
        ).toBeInTheDocument()
        expect(screen.queryByRole("button", { name: /try again/i })).not.toBeInTheDocument()
    })
})

describe("AcceptCampaignInvitationPage — sign-in/register and confirm", () => {
    it("renders inline sign-in and register panels, never navigating to /login", () => {
        statusHookRef.current = {
            state: {
                status: "success",
                data: {
                    campaign_display_name: "Fixture Campaign",
                    invitation_expires_at: "2026-10-01T00:00:00Z",
                    onboarding_expires_at: "2026-09-25T00:20:00Z",
                    onboarding_csrf_token: "onboarding-csrf",
                    next_action: "sign_in_or_register",
                    signed_in_display_name: null,
                },
            },
        }

        renderPage({ status: "unauthenticated" })

        expect(screen.getByRole("heading", { name: "Join Fixture Campaign" })).toBeInTheDocument()
        expect(screen.getByText("fake-sign-in-success")).toBeInTheDocument()
        expect(screen.getByText("fake-register-success")).toBeInTheDocument()
        expect(screen.queryByText("Login page")).not.toBeInTheDocument()
    })

    it("shows the completion screen once registration succeeds", () => {
        statusHookRef.current = {
            state: {
                status: "success",
                data: {
                    campaign_display_name: "Fixture Campaign",
                    invitation_expires_at: "2026-10-01T00:00:00Z",
                    onboarding_expires_at: "2026-09-25T00:20:00Z",
                    onboarding_csrf_token: "onboarding-csrf",
                    next_action: "sign_in_or_register",
                    signed_in_display_name: null,
                },
            },
        }

        renderPage({ status: "unauthenticated" })
        fireEvent.click(screen.getByText("fake-register-success"))

        expect(
            screen.getByRole("heading", { name: "You joined Fixture Campaign" }),
        ).toBeInTheDocument()
        expect(screen.getByRole("link", { name: "Go to campaigns" })).toHaveAttribute(
            "href",
            "/campaigns",
        )
    })

    it("renders the confirm panel naming the signed-in account", () => {
        statusHookRef.current = {
            state: {
                status: "success",
                data: {
                    campaign_display_name: "Fixture Campaign",
                    invitation_expires_at: "2026-10-01T00:00:00Z",
                    onboarding_expires_at: "2026-09-25T00:20:00Z",
                    onboarding_csrf_token: "onboarding-csrf",
                    next_action: "confirm",
                    signed_in_display_name: "Existing User",
                },
            },
        }

        renderPage({ status: "authenticated", bootstrap: sessionBootstrapFixture })

        expect(screen.getByText("fake-confirm-success")).toBeInTheDocument()
    })

    it("shows the completion screen once confirm succeeds", () => {
        statusHookRef.current = {
            state: {
                status: "success",
                data: {
                    campaign_display_name: "Fixture Campaign",
                    invitation_expires_at: "2026-10-01T00:00:00Z",
                    onboarding_expires_at: "2026-09-25T00:20:00Z",
                    onboarding_csrf_token: "onboarding-csrf",
                    next_action: "confirm",
                    signed_in_display_name: "Existing User",
                },
            },
        }

        renderPage({ status: "authenticated", bootstrap: sessionBootstrapFixture })
        fireEvent.click(screen.getByText("fake-confirm-success"))

        expect(
            screen.getByRole("heading", { name: "You joined Fixture Campaign" }),
        ).toBeInTheDocument()
    })
})

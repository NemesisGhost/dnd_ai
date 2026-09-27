import { useEffect, useRef, useState } from "react"
import { Link, Navigate } from "react-router"
import { InvitationOnboardingConfirm } from "../components/InvitationOnboardingConfirm"
import { InvitationOnboardingRegister } from "../components/InvitationOnboardingRegister"
import { InvitationOnboardingSignIn } from "../components/InvitationOnboardingSignIn"
import { useSession } from "../context/SessionContext"
import { useAcceptCampaignInvitation } from "../hooks/useAcceptCampaignInvitation"
import { useBeginInvitationOnboarding } from "../hooks/useBeginInvitationOnboarding"
import { useInvitationOnboardingStatus } from "../hooks/useInvitationOnboardingStatus"
import PlaceholderPage from "./PlaceholderPage"
import type { AcceptCampaignInvitationResponse } from "../types/campaignInvitations"
import type {
    CompleteInvitationOnboardingResponse,
    RegisterInvitedAccountResponse,
} from "../types/invitationOnboarding"

const _HASH_TOKEN_PREFIX = "#token="

function manualStatusMessage(kind: "pending" | "denied" | "unacceptable" | "error"): string {
    switch (kind) {
        case "pending":
            return "Accepting invitation…"
        case "denied":
            return "You are not allowed to accept invitations from this session."
        case "unacceptable":
            return "That invitation token could not be accepted. Check the token and try again."
        case "error":
            return "The invitation could not be accepted. Try again."
    }
}

// Public multi-state route (no AuthenticatedSessionBoundary — see App.tsx):
// opening a single-link invitation with no account yet must work for a
// visitor with no session at all. Never completes on a bare page load
// (PHASE13E_REMAINING_IMPLEMENTATION_PLAN.md §7.1 S-1) — the token in the
// URL fragment only ever *begins* an onboarding session; joining the
// campaign always requires one further explicit action (register or
// confirm), rendered by the two dedicated child components below.
export function AcceptCampaignInvitationPage() {
    const { state: sessionState, reload } = useSession()

    // Read window.location.hash exactly once. A ref (not a bare
    // conditional) survives React 18 StrictMode's mount → cleanup →
    // remount double-invocation of this same effect within one component
    // instance (R-1): the second invocation sees the latch already set
    // and returns immediately, so a StrictMode dev build can never begin
    // two onboarding sessions for one link open. history.replaceState
    // removes the fragment before any await, so Back never resurrects the
    // token (R-2) and it is never visible in the address bar or history.
    const hashConsumedRef = useRef(false)
    // Lazy initializer: reads window.location.hash exactly once, before
    // the mount effect below clears it, and never changes afterward — a
    // fixed snapshot of "did this page load with a token fragment",
    // usable during render without touching a ref there (refs may only
    // be read inside effects/handlers, never during render).
    const [hadHashToken] = useState(() => window.location.hash.startsWith(_HASH_TOKEN_PREFIX))
    // Kept only in memory, for the life of this component, so a transient
    // failure (network drop, rate limit) can offer a "Try again" that
    // resubmits the same captured token without ever writing it back to
    // the URL, storage, or PostgreSQL.
    const capturedTokenRef = useRef<string | null>(null)

    const begin = useBeginInvitationOnboarding()
    const onboardingStatus = useInvitationOnboardingStatus()

    const [completedCampaignName, setCompletedCampaignName] = useState<string | null>(null)

    // Manual-token fallback, retained unchanged from the pre-checkpoint-8
    // page (docs/PLAN.md §13E) — reachable when there is no onboarding
    // cookie/fragment at all, for a signed-in visitor who received a raw
    // token some other way.
    const [manualToken, setManualToken] = useState("")
    const [manualAcceptedResult, setManualAcceptedResult] =
        useState<AcceptCampaignInvitationResponse | null>(null)
    const manualAccept = useAcceptCampaignInvitation((result) => {
        setManualAcceptedResult(result)
        setManualToken("")
        // The new membership won't show up on /campaigns until the
        // session bootstrap that page reads is refetched.
        reload()
    })

    useEffect(() => {
        if (hashConsumedRef.current) {
            return
        }
        const hash = window.location.hash
        if (!hash.startsWith(_HASH_TOKEN_PREFIX)) {
            return
        }
        hashConsumedRef.current = true
        const invitationToken = decodeURIComponent(hash.slice(_HASH_TOKEN_PREFIX.length))
        window.history.replaceState(null, "", window.location.pathname + window.location.search)
        capturedTokenRef.current = invitationToken
        begin.submit(invitationToken)
        // Intentionally run-once: hashConsumedRef, not the dependency
        // array, is what makes this idempotent (see the ref's own comment
        // above) — including begin.submit here would retrigger on every
        // status change without changing behavior, since the ref guard
        // already blocks a second invocation.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    useEffect(() => {
        if (begin.status.kind === "success") {
            onboardingStatus.retry()
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [begin.status])

    // Derived, not stored: gates rendering while a hash-driven begin
    // request is still in flight, without a redundant setState in either
    // effect above.
    const hasPendingHashBegin =
        hadHashToken && (begin.status.kind === "idle" || begin.status.kind === "pending")

    if (completedCampaignName !== null) {
        return (
            <main className="app-main">
                <section className="placeholder-page" aria-labelledby="onboarding-success-heading">
                    <h1 id="onboarding-success-heading">You joined {completedCampaignName}</h1>
                    <p>Your campaign membership was accepted.</p>
                    <p>
                        A GM may still need to assign a role or additional access before every
                        campaign page is available.
                    </p>
                    <p>
                        <Link to="/campaigns">Go to campaigns</Link>
                    </p>
                </section>
            </main>
        )
    }

    if (manualAcceptedResult !== null) {
        return (
            <main className="app-main">
                <section
                    className="placeholder-page"
                    aria-labelledby="accept-invitation-success-heading"
                >
                    <h1 id="accept-invitation-success-heading">Invitation accepted</h1>
                    <p>Your campaign membership was accepted.</p>
                    <p>
                        A GM may still need to assign a role or additional access before every
                        campaign page is available.
                    </p>
                    <p>
                        <Link to="/campaigns">Go to campaigns</Link>
                    </p>
                </section>
            </main>
        )
    }

    if (hasPendingHashBegin) {
        return (
            <main className="app-main">
                <PlaceholderPage
                    title="Opening your invitation"
                    description="Checking the invitation link."
                />
            </main>
        )
    }

    if (
        begin.status.kind === "denied" ||
        begin.status.kind === "rate_limited" ||
        begin.status.kind === "error"
    ) {
        // Rate limiting and generic errors are recoverable — retry
        // resubmits the token this component already captured in memory
        // (never re-read from the URL, which was cleared long ago).
        // "denied" is not a transient condition, so it gets no retry.
        const canRetry = begin.status.kind === "rate_limited" || begin.status.kind === "error"
        return (
            <main className="app-main">
                <section
                    className="placeholder-page"
                    aria-labelledby="onboarding-begin-error-heading"
                >
                    <h1 id="onboarding-begin-error-heading">This invitation link could not be opened</h1>
                    <p>
                        {begin.status.kind === "rate_limited"
                            ? "Too many attempts. Wait a while and try again."
                            : begin.status.kind === "denied"
                              ? "You are not allowed to accept invitations from this session."
                              : "Something went wrong opening this link. Try again."}
                    </p>
                    {canRetry && (
                        <button
                            type="button"
                            onClick={() => {
                                const token = capturedTokenRef.current
                                if (token !== null) {
                                    begin.submit(token)
                                }
                            }}
                        >
                            Try again
                        </button>
                    )}
                </section>
            </main>
        )
    }

    if (begin.status.kind === "unavailable") {
        // R-2: a calm terminal state, not an error with a retry button —
        // the link's own token has already been consumed by this attempt
        // and cannot become valid again by retrying.
        return (
            <main className="app-main">
                <section className="placeholder-page" aria-labelledby="onboarding-unavailable-heading">
                    <h1 id="onboarding-unavailable-heading">This invitation is no longer available</h1>
                    <p>It may have expired, been revoked, or already been used.</p>
                </section>
            </main>
        )
    }

    if (onboardingStatus.state.status === "loading") {
        return (
            <main className="app-main">
                <PlaceholderPage title="Loading invitation" description="Checking this invitation link." />
            </main>
        )
    }

    if (onboardingStatus.state.status === "error") {
        return (
            <main className="app-main">
                <section className="placeholder-page" aria-labelledby="onboarding-status-error-heading">
                    <h1 id="onboarding-status-error-heading">Invitation unavailable</h1>
                    <p>This invitation link could not be checked. Try again.</p>
                    <button type="button" onClick={onboardingStatus.retry}>
                        Try again
                    </button>
                </section>
            </main>
        )
    }

    if (onboardingStatus.state.status === "unavailable") {
        if (sessionState.status === "loading") {
            return (
                <main className="app-main">
                    <PlaceholderPage title="Loading portal" description="Checking your session." />
                </main>
            )
        }

        if (sessionState.status === "error") {
            return (
                <main className="app-main">
                    <section className="placeholder-page" aria-labelledby="accept-invitation-error-heading">
                        <h1 id="accept-invitation-error-heading">Invitation acceptance unavailable</h1>
                        <p>Your session could not be checked. Try again.</p>
                        <button type="button" onClick={reload}>
                            Try again
                        </button>
                    </section>
                </main>
            )
        }

        // R-3: LoginPage's own Navigate to="/campaigns" needs no change —
        // there is no return-URL to thread. A visitor who lands here with
        // no onboarding cookie and no session simply signs in normally
        // and, if they hold a raw token some other way, returns to this
        // page to use the manual fallback below.
        if (sessionState.status !== "authenticated") {
            return <Navigate to="/login" replace />
        }

        return (
            <main className="app-main">
                <section className="placeholder-page" aria-labelledby="accept-invitation-heading">
                    <h1 id="accept-invitation-heading">Accept campaign invitation</h1>
                    <p>Paste the invitation token exactly as it was given to you.</p>

                    <form
                        className="access-role-editor"
                        onSubmit={(event) => {
                            event.preventDefault()
                            if (manualToken.trim() === "") {
                                return
                            }
                            manualAccept.submit(manualToken)
                        }}
                    >
                        <label htmlFor="campaign-invitation-token">Invitation token</label>
                        <input
                            id="campaign-invitation-token"
                            type="password"
                            value={manualToken}
                            spellCheck={false}
                            autoComplete="off"
                            disabled={manualAccept.status.kind === "pending"}
                            onChange={(event) => {
                                setManualToken(event.currentTarget.value)
                                if (manualAccept.status.kind !== "idle") {
                                    manualAccept.reset()
                                }
                            }}
                        />

                        <div className="access-role-editor__actions">
                            <button
                                type="submit"
                                disabled={
                                    manualToken.trim() === "" || manualAccept.status.kind === "pending"
                                }
                            >
                                {manualAccept.status.kind === "pending" ? "Accepting…" : "Accept invitation"}
                            </button>
                        </div>

                        <p
                            className={
                                manualAccept.status.kind === "denied" ||
                                manualAccept.status.kind === "unacceptable" ||
                                manualAccept.status.kind === "error"
                                    ? "access-role-editor__status access-role-editor__status--error"
                                    : "access-role-editor__status"
                            }
                            role="status"
                            aria-live="polite"
                        >
                            {manualAccept.status.kind === "idle" || manualAccept.status.kind === "success"
                                ? ""
                                : manualStatusMessage(manualAccept.status.kind)}
                        </p>
                    </form>
                </section>
            </main>
        )
    }

    const data = onboardingStatus.state.data

    if (data.next_action === "confirm" && data.signed_in_display_name !== null) {
        return (
            <main className="app-main">
                <InvitationOnboardingConfirm
                    campaignDisplayName={data.campaign_display_name}
                    signedInDisplayName={data.signed_in_display_name}
                    onCompleted={(result: CompleteInvitationOnboardingResponse) => {
                        setCompletedCampaignName(result.campaign_display_name)
                        // Same reasoning as the manual-accept path above:
                        // refresh the bootstrap the campaigns list reads.
                        reload()
                    }}
                    onNeedsStatusRefresh={onboardingStatus.retry}
                />
            </main>
        )
    }

    return (
        <main className="app-main">
            <section className="login-page" aria-labelledby="onboarding-heading">
                <div className="login-container">
                    <h1 id="onboarding-heading">Join {data.campaign_display_name}</h1>
                    <p className="login-subtitle">
                        Sign in to an existing account, or create a new one, to accept this invitation.
                    </p>

                    <div className="login-box">
                        <h2>Sign in</h2>
                        <InvitationOnboardingSignIn onSignedIn={onboardingStatus.retry} />
                    </div>

                    <div className="login-box">
                        <h2>Create an account</h2>
                        <InvitationOnboardingRegister
                            onboardingCsrfToken={data.onboarding_csrf_token}
                            onRegistered={(result: RegisterInvitedAccountResponse) => {
                                setCompletedCampaignName(result.campaign_display_name)
                                reload()
                            }}
                        />
                    </div>
                </div>
            </section>
        </main>
    )
}

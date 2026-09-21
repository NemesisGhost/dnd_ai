import { Link, Navigate } from "react-router"
import { useState } from "react"
import { useAcceptCampaignInvitation } from "../hooks/useAcceptCampaignInvitation"
import { useSession } from "../context/SessionContext"
import PlaceholderPage from "./PlaceholderPage"
import type { AcceptCampaignInvitationResponse } from "../types/campaignInvitations"

function statusMessage(kind: "pending" | "denied" | "unacceptable" | "error"): string {
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

export function AcceptCampaignInvitationPage() {
    const { state, reload } = useSession()
    const [token, setToken] = useState("")
    const [acceptedResult, setAcceptedResult] = useState<AcceptCampaignInvitationResponse | null>(
        null,
    )

    const { status, submit, reset } = useAcceptCampaignInvitation((result) => {
        setAcceptedResult(result)
        setToken("")
    })

    if (acceptedResult !== null) {
        return (
            <main className="app-main">
                <section className="placeholder-page" aria-labelledby="accept-invitation-success-heading">
                    <h1 id="accept-invitation-success-heading">Invitation accepted</h1>
                    <p>Your campaign membership was accepted.</p>
                    <p>A GM may still need to assign a role or additional access before every campaign page is available.</p>
                    <p>
                        <Link to="/campaigns">Go to campaigns</Link>
                    </p>
                </section>
            </main>
        )
    }

    if (state.status === "loading") {
        return (
            <main className="app-main">
                <PlaceholderPage
                    title="Loading invitation acceptance"
                    description="Checking your session before accepting a campaign invitation."
                />
            </main>
        )
    }

    if (state.status === "unauthenticated") {
        return <Navigate to="/login" replace />
    }

    if (state.status === "error") {
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

    return (
        <main className="app-main">
            <section className="placeholder-page" aria-labelledby="accept-invitation-heading">
                <h1 id="accept-invitation-heading">Accept campaign invitation</h1>
                <p>Paste the invitation token exactly as it was given to you.</p>

                <form
                    className="access-role-editor"
                    onSubmit={(event) => {
                        event.preventDefault()
                        if (token.trim() === "") {
                            return
                        }
                        submit(token)
                    }}
                >
                    <label htmlFor="campaign-invitation-token">Invitation token</label>
                    <input
                        id="campaign-invitation-token"
                        type="password"
                        value={token}
                        spellCheck={false}
                        autoComplete="off"
                        disabled={status.kind === "pending"}
                        onChange={(event) => {
                            setToken(event.currentTarget.value)
                            if (status.kind !== "idle") {
                                reset()
                            }
                        }}
                    />

                    <div className="access-role-editor__actions">
                        <button type="submit" disabled={token.trim() === "" || status.kind === "pending"}>
                            {status.kind === "pending" ? "Accepting…" : "Accept invitation"}
                        </button>
                    </div>

                    <p
                        className={
                            status.kind === "denied" ||
                            status.kind === "unacceptable" ||
                            status.kind === "error"
                                ? "access-role-editor__status access-role-editor__status--error"
                                : "access-role-editor__status"
                        }
                        role="status"
                        aria-live="polite"
                    >
                        {status.kind === "idle" || status.kind === "success"
                            ? ""
                            : statusMessage(status.kind)}
                    </p>
                </form>
            </section>
        </main>
    )
}
import type { OwnBrowserSession } from "../types/accountSessions"

export class OwnSessionsRequestError extends Error {
    readonly status: number

    constructor(status: number, message: string) {
        super(message)
        this.name = "OwnSessionsRequestError"
        this.status = status
    }
}

export async function fetchOwnSessions(signal?: AbortSignal): Promise<OwnBrowserSession[]> {
    const response = await fetch("/api/auth/sessions", {
        method: "GET",
        credentials: "same-origin",
        cache: "no-store",
        signal,
        headers: {
            Accept: "application/json",
        },
    })

    if (!response.ok) {
        throw new OwnSessionsRequestError(
            response.status,
            `Own sessions request failed with status ${response.status}`,
        )
    }

    return (await response.json()) as OwnBrowserSession[]
}

// The routes take no target user -- this always revokes the caller's own
// session, and revoke_browser_session (dnd_ai.commands.local_auth)
// already raises ForeignBrowserSessionError for another user's session id.
export async function revokeOwnSession(
    browserSessionId: string,
    csrfToken: string,
    signal?: AbortSignal,
): Promise<void> {
    const encodedSessionId = encodeURIComponent(browserSessionId)

    const response = await fetch(`/api/auth/sessions/${encodedSessionId}`, {
        method: "DELETE",
        credentials: "same-origin",
        cache: "no-store",
        signal,
        headers: {
            "X-CSRF-Token": csrfToken,
        },
    })

    if (!response.ok) {
        throw new OwnSessionsRequestError(
            response.status,
            `Revoke own session request failed with status ${response.status}`,
        )
    }
}

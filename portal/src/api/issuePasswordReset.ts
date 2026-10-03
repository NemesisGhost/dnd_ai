import { PlatformAccountsRequestError } from "./platformAccounts"
import type { IssuePasswordResetResponse } from "../types/platformAccounts"

export async function issuePasswordReset(
    targetUserId: string,
    revokeSessions: boolean,
    csrfToken: string,
    signal?: AbortSignal,
): Promise<IssuePasswordResetResponse> {
    const encodedUserId = encodeURIComponent(targetUserId)

    const response = await fetch(`/api/admin/accounts/${encodedUserId}/password-reset`, {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        signal,
        headers: {
            Accept: "application/json",
            "Content-Type": "application/json",
            "X-CSRF-Token": csrfToken,
        },
        body: JSON.stringify({ revoke_sessions: revokeSessions }),
    })

    if (!response.ok) {
        throw new PlatformAccountsRequestError(
            response.status,
            `Issue password reset request failed with status ${response.status}`,
        )
    }

    return (await response.json()) as IssuePasswordResetResponse
}

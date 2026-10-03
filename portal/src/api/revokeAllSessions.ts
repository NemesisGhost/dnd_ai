import { PlatformAccountsRequestError } from "./platformAccounts"
import type { RevokeAllSessionsResponse } from "../types/platformAccounts"

export async function revokeAllSessions(
    targetUserId: string,
    csrfToken: string,
    signal?: AbortSignal,
): Promise<RevokeAllSessionsResponse> {
    const encodedUserId = encodeURIComponent(targetUserId)

    const response = await fetch(`/api/admin/accounts/${encodedUserId}/revoke-sessions`, {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        signal,
        headers: {
            Accept: "application/json",
            "X-CSRF-Token": csrfToken,
        },
    })

    if (!response.ok) {
        throw new PlatformAccountsRequestError(
            response.status,
            `Revoke all sessions request failed with status ${response.status}`,
        )
    }

    return (await response.json()) as RevokeAllSessionsResponse
}

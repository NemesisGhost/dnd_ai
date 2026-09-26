import { PlatformAccountsRequestError } from "./platformAccounts"
import type { AccountLifecycleResponse } from "../types/platformAccounts"

export async function disableAccount(
    targetUserId: string,
    csrfToken: string,
    signal?: AbortSignal,
): Promise<AccountLifecycleResponse> {
    const encodedUserId = encodeURIComponent(targetUserId)

    const response = await fetch(`/api/admin/accounts/${encodedUserId}/disable`, {
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
            `Disable account request failed with status ${response.status}`,
        )
    }

    return (await response.json()) as AccountLifecycleResponse
}

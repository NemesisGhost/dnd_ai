import { PlatformAccountsRequestError } from "./platformAccounts"
import type { CreateAccountResponse } from "../types/platformAccounts"

export async function createAccount(
    loginName: string,
    displayName: string,
    email: string | null,
    csrfToken: string,
    signal?: AbortSignal,
): Promise<CreateAccountResponse> {
    const response = await fetch("/api/admin/accounts", {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        signal,
        headers: {
            Accept: "application/json",
            "Content-Type": "application/json",
            "X-CSRF-Token": csrfToken,
        },
        body: JSON.stringify({
            login_name: loginName,
            display_name: displayName,
            email,
        }),
    })

    if (!response.ok) {
        throw new PlatformAccountsRequestError(
            response.status,
            `Create account request failed with status ${response.status}`,
        )
    }

    return (await response.json()) as CreateAccountResponse
}

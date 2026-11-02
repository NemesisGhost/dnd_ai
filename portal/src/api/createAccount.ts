import { PlatformAccountsRequestError } from "./platformAccounts"
import type { CreateAccountResponse } from "../types/platformAccounts"
import type { SystemRoleCode } from "../utils/systemAccess"

export async function createAccount(
    loginName: string,
    displayName: string,
    email: string | null,
    systemRoleCodes: readonly SystemRoleCode[],
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
            system_role_codes: systemRoleCodes,
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

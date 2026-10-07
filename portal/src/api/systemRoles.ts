import { PlatformAccountsRequestError } from "./platformAccounts"
import type { SystemRoleChangeResponse } from "../types/platformAccounts"
import type { SystemRoleCode } from "../utils/systemAccess"

async function send(
    path: string,
    body: unknown,
    csrfToken: string,
    signal?: AbortSignal,
): Promise<SystemRoleChangeResponse> {
    const response = await fetch(path, {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        signal,
        headers: {
            Accept: "application/json",
            "Content-Type": "application/json",
            "X-CSRF-Token": csrfToken,
        },
        body: JSON.stringify(body),
    })

    if (!response.ok) {
        throw new PlatformAccountsRequestError(
            response.status,
            `System role request failed with status ${response.status}`,
        )
    }

    return (await response.json()) as SystemRoleChangeResponse
}

export function assignSystemRole(
    targetUserId: string,
    roleCode: SystemRoleCode,
    csrfToken: string,
    signal?: AbortSignal,
): Promise<SystemRoleChangeResponse> {
    return send(
        `/api/admin/accounts/${encodeURIComponent(targetUserId)}/system-roles`,
        { system_role_code: roleCode },
        csrfToken,
        signal,
    )
}

export function revokeSystemRole(
    targetUserId: string,
    roleCode: SystemRoleCode,
    csrfToken: string,
    signal?: AbortSignal,
): Promise<SystemRoleChangeResponse> {
    return send(
        `/api/admin/accounts/${encodeURIComponent(targetUserId)}/system-roles/${encodeURIComponent(roleCode)}/revoke`,
        {},
        csrfToken,
        signal,
    )
}

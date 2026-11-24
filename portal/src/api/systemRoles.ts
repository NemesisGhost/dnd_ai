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
            await readErrorCode(response),
        )
    }

    // A 2xx that cannot be read is not a refusal and not a confirmed result: it is thrown as an ordinary Error,
    // which the caller treats as an unknown outcome.
    let parsed: unknown
    try {
        parsed = await response.json()
    } catch {
        throw new Error("The system role response could not be read.")
    }
    if (typeof parsed !== "object" || parsed === null || typeof (parsed as { changed?: unknown }).changed !== "boolean") {
        throw new Error("The system role response was not a role change.")
    }
    return parsed as SystemRoleChangeResponse
}

// The error envelope's `error.code`, best effort: an empty or non-JSON body leaves it undefined.
async function readErrorCode(response: Response): Promise<string | undefined> {
    try {
        const parsed = (await response.json()) as { error?: { code?: unknown } } | null
        const code = parsed?.error?.code
        return typeof code === "string" ? code : undefined
    } catch {
        return undefined
    }
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

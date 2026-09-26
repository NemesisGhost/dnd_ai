import type { PlatformAccountList } from "../types/platformAccounts"

export class PlatformAccountsRequestError extends Error {
    readonly status: number

    constructor(status: number, message: string) {
        super(message)
        this.name = "PlatformAccountsRequestError"
        this.status = status
    }
}

export interface FetchPlatformAccountsParams {
    q?: string
    status?: string
    limit?: number
    cursor?: string
}

export async function fetchPlatformAccounts(
    params: FetchPlatformAccountsParams,
    signal?: AbortSignal,
): Promise<PlatformAccountList> {
    const query = new URLSearchParams()
    if (params.q) {
        query.set("q", params.q)
    }
    if (params.status) {
        query.set("status", params.status)
    }
    if (params.limit !== undefined) {
        query.set("limit", String(params.limit))
    }
    if (params.cursor) {
        query.set("cursor", params.cursor)
    }
    const queryString = query.toString()

    const response = await fetch(`/api/admin/accounts${queryString ? `?${queryString}` : ""}`, {
        method: "GET",
        credentials: "same-origin",
        cache: "no-store",
        signal,
        headers: {
            Accept: "application/json",
        },
    })

    if (!response.ok) {
        throw new PlatformAccountsRequestError(
            response.status,
            `Platform accounts request failed with status ${response.status}`,
        )
    }

    return (await response.json()) as PlatformAccountList
}

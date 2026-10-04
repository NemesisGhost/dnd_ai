// Shared HTTP helper for the Phase 14 authoring requests. It always sends
// same-origin credentials, `no-store`, and JSON headers; unsafe methods also
// send the session CSRF token and (when given) an Idempotency-Key. A failed
// response is parsed into an ApiRequestError carrying the status and the
// server's stable error `code` (never a field location — the server
// deliberately never sends one) plus the correlation id for support.
//
// Existing access-management requests keep their own per-verb modules; only
// the authoring surface uses this helper (docs/UI_DESIGN.md §5.11).

export class ApiRequestError extends Error {
    readonly status: number
    readonly code: string | null
    readonly correlationId: string | null

    constructor(status: number, code: string | null, correlationId: string | null) {
        super(`API request failed with status ${status}${code ? ` (${code})` : ""}`)
        this.name = "ApiRequestError"
        this.status = status
        this.code = code
        this.correlationId = correlationId
    }
}

export type ApiMethod = "GET" | "POST"

export interface ApiRequestOptions {
    body?: unknown
    csrfToken?: string
    idempotencyKey?: string
    signal?: AbortSignal
}

interface ErrorEnvelope {
    error?: { code?: unknown; correlation_id?: unknown }
}

async function parseErrorEnvelope(
    response: Response,
): Promise<{ code: string | null; correlationId: string | null }> {
    try {
        const parsed = (await response.json()) as ErrorEnvelope
        const code = parsed?.error?.code
        const correlationId = parsed?.error?.correlation_id
        return {
            code: typeof code === "string" ? code : null,
            correlationId: typeof correlationId === "string" ? correlationId : null,
        }
    } catch {
        // A non-JSON body (a proxy error page, an empty 502) is tolerated.
        return { code: null, correlationId: null }
    }
}

export async function apiRequest<T>(
    method: ApiMethod,
    path: string,
    options: ApiRequestOptions = {},
): Promise<T> {
    const headers: Record<string, string> = { Accept: "application/json" }
    if (options.body !== undefined) {
        headers["Content-Type"] = "application/json"
    }
    if (method !== "GET") {
        if (options.csrfToken !== undefined) {
            headers["X-CSRF-Token"] = options.csrfToken
        }
        if (options.idempotencyKey !== undefined) {
            headers["Idempotency-Key"] = options.idempotencyKey
        }
    }

    let response: Response
    try {
        response = await fetch(`/api${path}`, {
            method,
            credentials: "same-origin",
            cache: "no-store",
            signal: options.signal,
            headers,
            body:
                options.body === undefined
                    ? undefined
                    : JSON.stringify(options.body),
        })
    } catch (cause) {
        if (options.signal?.aborted) {
            throw cause
        }
        // fetch itself rejected: the network is down or the server is
        // unreachable. Status 0 is the portal's "no response" marker.
        throw new ApiRequestError(0, "network_error", null)
    }

    if (!response.ok) {
        const { code, correlationId } = await parseErrorEnvelope(response)
        throw new ApiRequestError(response.status, code, correlationId)
    }

    if (response.status === 204) {
        return undefined as T
    }
    return (await response.json()) as T
}

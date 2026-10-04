import { ApiRequestError } from "../api/http"

// How a failed authoring request should be presented and recovered from.
// Distinct kinds, because the right recovery differs:
//
//   invalid      the request itself is wrong (fix the input)
//   stale        someone else changed the record (reload, re-apply)
//   conflict     a state precondition or idempotency conflict (explain)
//   denied       the signed-in user may not do this (403)
//   unavailable  the record does not exist or is not accessible (404)
//   expired      the session ended (401)
//   network      no response (retry)
//   server       the server failed (retry)
export type AuthoringErrorKind =
    | "invalid"
    | "stale"
    | "conflict"
    | "denied"
    | "unavailable"
    | "expired"
    | "network"
    | "server"

export interface AuthoringError {
    kind: AuthoringErrorKind
    status: number
    // The server's stable error code, when it sent one.
    code: string | null
    correlationId: string | null
}

export function classifyApiError(cause: unknown): AuthoringError {
    if (!(cause instanceof ApiRequestError)) {
        return { kind: "network", status: 0, code: null, correlationId: null }
    }

    const { status, code, correlationId } = cause
    const base = { status, code, correlationId }

    if (status === 0) {
        return { kind: "network", ...base }
    }
    if (status === 401) {
        return { kind: "expired", ...base }
    }
    if (status === 403) {
        return { kind: "denied", ...base }
    }
    if (status === 404) {
        return { kind: "unavailable", ...base }
    }
    if (status === 409) {
        return { kind: code === "stale_write" ? "stale" : "conflict", ...base }
    }
    if (status === 400 || status === 422) {
        return { kind: "invalid", ...base }
    }
    return { kind: "server", ...base }
}

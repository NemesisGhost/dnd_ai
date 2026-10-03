// Advisory, read-only validity check for a password-reset link. Never
// authoritative: POST /auth/password-reset repeats every check. The token
// travels only in the JSON body and is never retained here.
export class PasswordResetStatusError extends Error {
    // True only for HTTP 429, so the page can say "wait" without implying
    // anything about the link itself.
    readonly rateLimited: boolean

    constructor(message: string, rateLimited = false) {
        super(message)
        this.name = "PasswordResetStatusError"
        this.rateLimited = rateLimited
    }
}

const TIMEOUT_MS = 15_000

// Resolves true/false for a definitive answer. Throws PasswordResetStatusError
// for anything recoverable (network failure, timeout, 408/429/5xx, unreadable
// body) so callers can offer Try again instead of claiming the link is
// invalid. Rejects with the caller's abort reason when `signal` aborts.
export async function checkPasswordResetLink(token: string, signal?: AbortSignal): Promise<boolean> {
    const controller = new AbortController()
    let timedOut = false
    const timer = setTimeout(() => {
        timedOut = true
        controller.abort()
    }, TIMEOUT_MS)
    const forwardAbort = () => controller.abort()
    signal?.addEventListener("abort", forwardAbort)
    if (signal?.aborted) {
        controller.abort()
    }

    try {
        const response = await fetch("/api/auth/password-reset-status", {
            method: "POST",
            credentials: "same-origin",
            cache: "no-store",
            signal: controller.signal,
            headers: {
                Accept: "application/json",
                "Content-Type": "application/json",
            },
            body: JSON.stringify({ token }),
        })

        if (response.status === 429) {
            throw new PasswordResetStatusError("Password-reset status check was rate limited", true)
        }
        if (response.status === 408 || response.status >= 500) {
            throw new PasswordResetStatusError(`Password-reset status check failed with status ${response.status}`)
        }
        if (!response.ok) {
            return false
        }
        const body = (await response.json()) as { valid?: unknown }
        if (typeof body.valid !== "boolean") {
            throw new PasswordResetStatusError("Password-reset status response was not understood")
        }
        return body.valid
    } catch (cause) {
        if (cause instanceof PasswordResetStatusError) {
            throw cause
        }
        if (signal?.aborted) {
            throw cause
        }
        throw new PasswordResetStatusError(
            timedOut ? "Password-reset status check timed out" : "Password-reset status check failed",
        )
    } finally {
        clearTimeout(timer)
        signal?.removeEventListener("abort", forwardAbort)
    }
}

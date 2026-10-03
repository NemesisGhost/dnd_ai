// Advisory, read-only validity check for an activation link. Never
// authoritative: POST /auth/activate repeats every check. The token travels
// only in the JSON body and is never retained here.
export class ActivationStatusError extends Error {
    constructor(message: string) {
        super(message)
        this.name = "ActivationStatusError"
    }
}

const TIMEOUT_MS = 15_000

// Resolves true/false for a definitive answer. Throws ActivationStatusError for
// anything recoverable (network failure, timeout, 408/429/5xx, unreadable body)
// so callers can offer Retry instead of claiming the link is invalid. Rejects
// with the caller's abort reason when `signal` aborts.
export async function checkActivationLink(token: string, signal?: AbortSignal): Promise<boolean> {
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
        const response = await fetch("/api/auth/activation-status", {
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

        if (response.status === 408 || response.status === 429 || response.status >= 500) {
            throw new ActivationStatusError(`Activation status check failed with status ${response.status}`)
        }
        if (!response.ok) {
            return false
        }
        const body = (await response.json()) as { valid?: unknown }
        if (typeof body.valid !== "boolean") {
            throw new ActivationStatusError("Activation status response was not understood")
        }
        return body.valid
    } catch (cause) {
        if (cause instanceof ActivationStatusError) {
            throw cause
        }
        if (signal?.aborted) {
            throw cause
        }
        throw new ActivationStatusError(timedOut ? "Activation status check timed out" : "Activation status check failed")
    } finally {
        clearTimeout(timer)
        signal?.removeEventListener("abort", forwardAbort)
    }
}

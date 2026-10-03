import { useCallback, useEffect, useState } from "react"
import { checkPasswordResetLink, PasswordResetStatusError } from "../api/passwordResetStatus"

export type PasswordResetLinkCheckStatus = "checking" | "valid" | "invalid" | "error" | "rate_limited"

interface CheckResult {
    key: string
    outcome: Exclude<PasswordResetLinkCheckStatus, "checking">
}

// Runs the advisory check once per (token, attempt). A result is only honoured
// when its key matches the current one, so a slow answer for an earlier
// attempt can never surface -- and "checking" is derived rather than set
// synchronously inside the effect. `onInvalid` lets the caller drop its copy
// of a token now known to be unusable. A null token starts no request.
export function usePasswordResetLinkCheck(token: string | null, onInvalid?: () => void) {
    const [attempt, setAttempt] = useState(0)
    const [result, setResult] = useState<CheckResult | null>(null)
    const key = `attempt:${attempt}`

    useEffect(() => {
        if (token === null) {
            return
        }
        const controller = new AbortController()
        checkPasswordResetLink(token, controller.signal)
            .then((valid) => {
                if (!controller.signal.aborted) {
                    setResult({ key, outcome: valid ? "valid" : "invalid" })
                    if (!valid) {
                        onInvalid?.()
                    }
                }
            })
            .catch((cause: unknown) => {
                if (!controller.signal.aborted) {
                    const rateLimited = cause instanceof PasswordResetStatusError && cause.rateLimited
                    setResult({ key, outcome: rateLimited ? "rate_limited" : "error" })
                }
            })
        return () => controller.abort()
    }, [token, key, onInvalid])

    const retry = useCallback(() => {
        setAttempt((n) => n + 1)
    }, [])

    const status: PasswordResetLinkCheckStatus = result?.key === key ? result.outcome : "checking"
    return { status, retry }
}

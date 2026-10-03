import { useCallback, useEffect, useState } from "react"
import { checkActivationLink } from "../api/activationStatus"

export type ActivationLinkCheckStatus = "checking" | "valid" | "invalid" | "error"

interface CheckResult {
    key: string
    outcome: Exclude<ActivationLinkCheckStatus, "checking">
}

// Runs the advisory check once per (link, attempt). A result is only honoured
// when its key matches the current one, so a slow answer for an older link or
// an earlier attempt can never surface -- and "checking" is derived rather
// than set synchronously inside the effect. `onInvalid` lets the caller drop
// its copy of a token that is now known to be unusable. A null token (discarded) starts no request and leaves the last result in place.
export function useActivationLinkCheck(
    linkId: number,
    token: string | null,
    onInvalid?: (linkId: number) => void,
) {
    const [attempt, setAttempt] = useState(0)
    const [result, setResult] = useState<CheckResult | null>(null)
    const key = `${linkId}:${attempt}`

    useEffect(() => {
        if (token === null) {
            return
        }
        const controller = new AbortController()
        checkActivationLink(token, controller.signal)
            .then((valid) => {
                if (!controller.signal.aborted) {
                    setResult({ key, outcome: valid ? "valid" : "invalid" })
                    if (!valid) {
                        onInvalid?.(linkId)
                    }
                }
            })
            .catch(() => {
                if (!controller.signal.aborted) {
                    setResult({ key, outcome: "error" })
                }
            })
        return () => controller.abort()
    }, [token, key, linkId, onInvalid])

    const retry = useCallback(() => {
        setAttempt((n) => n + 1)
    }, [])

    const status: ActivationLinkCheckStatus = result?.key === key ? result.outcome : "checking"
    return { status, retry }
}

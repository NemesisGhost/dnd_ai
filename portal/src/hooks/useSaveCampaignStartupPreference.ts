import { useCallback, useEffect, useRef, useState } from "react"
import {
    setCampaignStartupPreference,
    UserPreferenceRequestError,
} from "../api/userPreferences"
import { useSession } from "../context/SessionContext"

export type SaveCampaignStartupStatus =
    | { kind: "idle" }
    | { kind: "pending" }
    | { kind: "success" }
    // 404: the chosen campaign is no longer accessible to the caller.
    | { kind: "unavailable" }
    // 401/403: session expired or the request was refused.
    | { kind: "denied" }
    // The PUT was CONFIRMED (the server accepted it) but the authoritative bootstrap was not
    // applied afterwards - the re-read failed, was superseded by a newer session read, or the
    // session ended - so the new value is not yet shown. Never "denied": the save happened.
    | { kind: "unconfirmed" }
    | { kind: "error" }

export interface UseSaveCampaignStartupPreferenceResult {
    status: SaveCampaignStartupStatus
    // `null` clears the fixed choice ("Resume my last visited campaign").
    save: (preferredCampaignId: string | null) => void
    reset: () => void
}

const idleStatus: SaveCampaignStartupStatus = { kind: "idle" }

export function useSaveCampaignStartupPreference(): UseSaveCampaignStartupPreferenceResult {
    const { state: sessionState, refresh } = useSession()
    const controllerRef = useRef<AbortController | null>(null)
    const [status, setStatus] = useState<SaveCampaignStartupStatus>(idleStatus)

    useEffect(() => {
        return () => {
            controllerRef.current?.abort()
        }
    }, [])

    const save = useCallback(
        (preferredCampaignId: string | null) => {
            if (status.kind === "pending") {
                return
            }
            if (sessionState.status !== "authenticated") {
                return
            }

            const controller = new AbortController()
            controllerRef.current = controller
            setStatus({ kind: "pending" })

            void setCampaignStartupPreference(
                preferredCampaignId,
                sessionState.bootstrap.csrf_token,
                controller.signal,
            )
                .then(async () => {
                    if (controller.signal.aborted) {
                        return
                    }
                    // Success is reported only once the shared session
                    // bootstrap holds the server's own view of the saved
                    // preference; nothing local is treated as authoritative.
                    let applied: boolean
                    try {
                        applied = await refresh(controller.signal)
                    } catch {
                        if (!controller.signal.aborted) {
                            setStatus({ kind: "unconfirmed" })
                        }
                        return
                    }
                    if (controller.signal.aborted) {
                        return
                    }
                    // `false` is "not applied" (superseded, or the session ended and the sign-in
                    // boundary takes over), not a refusal of the save that was just confirmed. The
                    // PUT is never repeated to repair the read.
                    setStatus(applied ? { kind: "success" } : { kind: "unconfirmed" })
                })
                .catch((cause: unknown) => {
                    if (controller.signal.aborted) {
                        return
                    }
                    if (cause instanceof UserPreferenceRequestError) {
                        if (cause.status === 404) {
                            setStatus({ kind: "unavailable" })
                            return
                        }
                        if (cause.status === 401 || cause.status === 403) {
                            setStatus({ kind: "denied" })
                            return
                        }
                    }
                    setStatus({ kind: "error" })
                })
        },
        [sessionState, refresh, status.kind],
    )

    const reset = useCallback(() => {
        setStatus(idleStatus)
    }, [])

    return { status, save, reset }
}

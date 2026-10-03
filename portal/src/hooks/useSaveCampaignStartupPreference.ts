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
    | { kind: "error" }

export interface UseSaveCampaignStartupPreferenceResult {
    status: SaveCampaignStartupStatus
    // `null` clears the fixed choice ("Resume my last visited campaign").
    save: (preferredCampaignId: string | null) => void
    reset: () => void
}

const idleStatus: SaveCampaignStartupStatus = { kind: "idle" }

export function useSaveCampaignStartupPreference(): UseSaveCampaignStartupPreferenceResult {
    const { state: sessionState } = useSession()
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
                .then(() => {
                    if (controller.signal.aborted) {
                        return
                    }
                    setStatus({ kind: "success" })
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
        [sessionState, status.kind],
    )

    const reset = useCallback(() => {
        setStatus(idleStatus)
    }, [])

    return { status, save, reset }
}

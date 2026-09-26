import { useCallback, useEffect, useRef, useState } from "react"
import {
    CampaignInvitationsRequestError,
    acceptCampaignInvitation,
} from "../api/campaignInvitations"
import { useSession } from "../context/SessionContext"
import type { AcceptCampaignInvitationResponse } from "../types/campaignInvitations"

export type AcceptCampaignInvitationStatus =
    | { kind: "idle" }
    | { kind: "pending" }
    | { kind: "success" }
    | { kind: "denied" }
    | { kind: "unacceptable" }
    | { kind: "error" }

export interface UseAcceptCampaignInvitationResult {
    status: AcceptCampaignInvitationStatus
    submit: (token: string) => void
    reset: () => void
}

const idleStatus: AcceptCampaignInvitationStatus = { kind: "idle" }

export function useAcceptCampaignInvitation(
    onSuccess: (result: AcceptCampaignInvitationResponse) => void,
): UseAcceptCampaignInvitationResult {
    const { state: sessionState, reload } = useSession()
    const controllerRef = useRef<AbortController | null>(null)
    const [status, setStatus] = useState<AcceptCampaignInvitationStatus>(idleStatus)

    useEffect(() => {
        return () => {
            controllerRef.current?.abort()
        }
    }, [])

    const submit = useCallback(
        (token: string) => {
            if (status.kind === "pending") {
                return
            }
            if (sessionState.status !== "authenticated") {
                return
            }

            const controller = new AbortController()
            controllerRef.current = controller
            setStatus({ kind: "pending" })

            void acceptCampaignInvitation(
                token,
                sessionState.bootstrap.csrf_token,
                controller.signal,
            )
                .then((result) => {
                    if (controller.signal.aborted) {
                        return
                    }

                    setStatus({ kind: "success" })
                    onSuccess(result)
                    reload()
                })
                .catch((cause: unknown) => {
                    if (controller.signal.aborted) {
                        return
                    }

                    if (cause instanceof CampaignInvitationsRequestError) {
                        if (cause.status === 401) {
                            setStatus(idleStatus)
                            reload()
                            return
                        }
                        if (cause.status === 403) {
                            setStatus({ kind: "denied" })
                            return
                        }
                        if (cause.status === 404) {
                            setStatus({ kind: "unacceptable" })
                            return
                        }
                    }

                    setStatus({ kind: "error" })
                })
        },
        [onSuccess, reload, sessionState, status.kind],
    )

    const reset = useCallback(() => {
        setStatus(idleStatus)
    }, [])

    return { status, submit, reset }
}
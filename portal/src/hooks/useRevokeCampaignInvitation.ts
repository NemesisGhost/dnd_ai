import { useCallback, useEffect, useRef, useState } from "react"
import {
    CampaignInvitationsRequestError,
    revokeCampaignInvitation,
} from "../api/campaignInvitations"
import { useSession } from "../context/SessionContext"

export type RevokeCampaignInvitationStatus =
    | { kind: "idle" }
    | { kind: "pending" }
    | { kind: "success" }
    | { kind: "denied" }
    | { kind: "conflict" }
    | { kind: "error" }

export interface UseRevokeCampaignInvitationResult {
    status: RevokeCampaignInvitationStatus
    submit: (campaignInvitationId: string) => void
    reset: () => void
}

interface Snapshot {
    campaignId: string
    status: RevokeCampaignInvitationStatus
}

interface IdempotencyReservation {
    campaignInvitationId: string
    key: string
}

const idleStatus: RevokeCampaignInvitationStatus = { kind: "idle" }

export function useRevokeCampaignInvitation(
    campaignId: string,
    onSuccess: () => void,
): UseRevokeCampaignInvitationResult {
    const { state: sessionState, reload } = useSession()
    const controllerRef = useRef<AbortController | null>(null)
    const idempotencyRef = useRef<IdempotencyReservation | null>(null)

    const [snapshot, setSnapshot] = useState<Snapshot>(() => ({
        campaignId,
        status: idleStatus,
    }))

    useEffect(() => {
        return () => {
            controllerRef.current?.abort()
            idempotencyRef.current = null
        }
    }, [campaignId])

    const resolveIdempotencyKey = useCallback((campaignInvitationId: string): string => {
        const reserved = idempotencyRef.current
        if (
            reserved !== null &&
            reserved.campaignInvitationId === campaignInvitationId
        ) {
            return reserved.key
        }

        const key = globalThis.crypto.randomUUID()
        idempotencyRef.current = { campaignInvitationId, key }
        return key
    }, [])

    const status = snapshot.campaignId === campaignId ? snapshot.status : idleStatus

    const submit = useCallback(
        (campaignInvitationId: string) => {
            if (status.kind === "pending") {
                return
            }
            if (sessionState.status !== "authenticated") {
                return
            }

            const requestCampaignId = campaignId
            const controller = new AbortController()
            const csrfToken = sessionState.bootstrap.csrf_token
            const idempotencyKey = resolveIdempotencyKey(campaignInvitationId)

            controllerRef.current = controller
            setSnapshot({
                campaignId: requestCampaignId,
                status: { kind: "pending" },
            })

            void revokeCampaignInvitation(
                requestCampaignId,
                campaignInvitationId,
                csrfToken,
                idempotencyKey,
                controller.signal,
            )
                .then(() => {
                    if (controller.signal.aborted) {
                        return
                    }

                    idempotencyRef.current = null
                    setSnapshot({
                        campaignId: requestCampaignId,
                        status: { kind: "success" },
                    })
                    onSuccess()
                    void reload()
                })
                .catch((cause: unknown) => {
                    if (controller.signal.aborted) {
                        return
                    }

                    if (cause instanceof CampaignInvitationsRequestError) {
                        if (cause.status === 401) {
                            setSnapshot({
                                campaignId: requestCampaignId,
                                status: idleStatus,
                            })
                            void reload()
                            return
                        }
                        if (cause.status === 403 || cause.status === 404) {
                            setSnapshot({
                                campaignId: requestCampaignId,
                                status: { kind: "denied" },
                            })
                            return
                        }
                        if (cause.status === 409) {
                            setSnapshot({
                                campaignId: requestCampaignId,
                                status: { kind: "conflict" },
                            })
                            return
                        }
                    }

                    setSnapshot({
                        campaignId: requestCampaignId,
                        status: { kind: "error" },
                    })
                })
        },
        [campaignId, onSuccess, reload, resolveIdempotencyKey, sessionState, status.kind],
    )

    const reset = useCallback(() => {
        setSnapshot({ campaignId, status: idleStatus })
    }, [campaignId])

    return { status, submit, reset }
}
import { useCallback, useEffect, useRef, useState } from "react"
import {
    CampaignInvitationsRequestError,
    createCampaignInvitation,
} from "../api/campaignInvitations"
import { useSession } from "../context/SessionContext"
import type { CreateCampaignInvitationResponse } from "../types/campaignInvitations"

export type CreateCampaignInvitationStatus =
    | { kind: "idle" }
    | { kind: "pending" }
    | { kind: "success" }
    | { kind: "replayed" }
    | { kind: "denied" }
    | { kind: "conflict" }
    | { kind: "error" }

export interface UseCreateCampaignInvitationResult {
    status: CreateCampaignInvitationStatus
    submit: (invitedEmail: string | null) => void
    reset: () => void
}

interface Snapshot {
    campaignId: string
    status: CreateCampaignInvitationStatus
}

interface IdempotencyReservation {
    invitedEmail: string | null
    key: string
}

const idleStatus: CreateCampaignInvitationStatus = { kind: "idle" }

export function useCreateCampaignInvitation(
    campaignId: string,
    onSuccess: (result: CreateCampaignInvitationResponse) => void,
): UseCreateCampaignInvitationResult {
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

    const resolveIdempotencyKey = useCallback((invitedEmail: string | null): string => {
        const reserved = idempotencyRef.current
        if (reserved !== null && reserved.invitedEmail === invitedEmail) {
            return reserved.key
        }

        const key = globalThis.crypto.randomUUID()
        idempotencyRef.current = { invitedEmail, key }
        return key
    }, [])

    const status = snapshot.campaignId === campaignId ? snapshot.status : idleStatus

    const submit = useCallback(
        (invitedEmail: string | null) => {
            if (status.kind === "pending") {
                return
            }
            if (sessionState.status !== "authenticated") {
                return
            }

            const requestCampaignId = campaignId
            const controller = new AbortController()
            const csrfToken = sessionState.bootstrap.csrf_token
            const idempotencyKey = resolveIdempotencyKey(invitedEmail)

            controllerRef.current = controller
            setSnapshot({
                campaignId: requestCampaignId,
                status: { kind: "pending" },
            })

            void createCampaignInvitation(
                requestCampaignId,
                invitedEmail,
                csrfToken,
                idempotencyKey,
                controller.signal,
            )
                .then((result) => {
                    if (controller.signal.aborted) {
                        return
                    }

                    idempotencyRef.current = null
                    setSnapshot({
                        campaignId: requestCampaignId,
                        status: {
                            kind: result.token === null ? "replayed" : "success",
                        },
                    })
                    onSuccess(result)
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
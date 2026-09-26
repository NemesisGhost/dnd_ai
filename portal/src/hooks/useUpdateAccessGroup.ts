import { useCallback, useEffect, useRef, useState } from "react"
import {
    UpdateAccessGroupRequestError,
    updateAccessGroup,
} from "../api/updateAccessGroup"
import { useSession } from "../context/SessionContext"

export type UpdateAccessGroupStatus =
    | { kind: "idle" }
    | { kind: "pending" }
    | { kind: "success" }
    | { kind: "denied" }
    | { kind: "conflict" }
    | { kind: "error" }

export interface UseUpdateAccessGroupResult {
    status: UpdateAccessGroupStatus
    submit: (
        accessGroupId: string,
        name: string,
        description: string | null,
    ) => void
    reset: () => void
}

interface Snapshot {
    campaignId: string
    status: UpdateAccessGroupStatus
}

interface IdempotencyReservation {
    accessGroupId: string
    name: string
    description: string | null
    key: string
}

const idleStatus: UpdateAccessGroupStatus = { kind: "idle" }

// Mirrors useCreateAccessGroup's shape exactly (Phase 13E-B checkpoint 6's
// "Edit access group" control).
export function useUpdateAccessGroup(
    campaignId: string,
    onSuccess: () => void,
): UseUpdateAccessGroupResult {
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

    const resolveIdempotencyKey = useCallback(
        (
            accessGroupId: string,
            name: string,
            description: string | null,
        ): string => {
            const reserved = idempotencyRef.current
            if (
                reserved !== null &&
                reserved.accessGroupId === accessGroupId &&
                reserved.name === name &&
                reserved.description === description
            ) {
                return reserved.key
            }

            const key = globalThis.crypto.randomUUID()
            idempotencyRef.current = { accessGroupId, name, description, key }
            return key
        },
        [],
    )

    const status =
        snapshot.campaignId === campaignId ? snapshot.status : idleStatus

    const submit = useCallback(
        (accessGroupId: string, name: string, description: string | null) => {
            if (status.kind === "pending") {
                return
            }
            if (sessionState.status !== "authenticated") {
                return
            }

            const requestCampaignId = campaignId
            const csrfToken = sessionState.bootstrap.csrf_token
            const idempotencyKey = resolveIdempotencyKey(
                accessGroupId,
                name,
                description,
            )
            const controller = new AbortController()
            controllerRef.current = controller
            setSnapshot({
                campaignId: requestCampaignId,
                status: { kind: "pending" },
            })

            void updateAccessGroup(
                requestCampaignId,
                accessGroupId,
                name,
                description,
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
                    reload()
                })
                .catch((cause: unknown) => {
                    if (controller.signal.aborted) {
                        return
                    }

                    if (cause instanceof UpdateAccessGroupRequestError) {
                        if (cause.status === 401) {
                            setSnapshot({
                                campaignId: requestCampaignId,
                                status: idleStatus,
                            })
                            reload()
                            return
                        }
                        if (cause.status === 403 || cause.status === 404) {
                            setSnapshot({
                                campaignId: requestCampaignId,
                                status: { kind: "denied" },
                            })
                            return
                        }
                        if (cause.status === 409 || cause.status === 400) {
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
        [status.kind, sessionState, campaignId, onSuccess, reload, resolveIdempotencyKey],
    )

    const reset = useCallback(() => {
        setSnapshot({ campaignId, status: idleStatus })
    }, [campaignId])

    return { status, submit, reset }
}

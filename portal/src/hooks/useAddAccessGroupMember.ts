import { useCallback, useEffect, useRef, useState } from "react"
import {
    AddAccessGroupMemberRequestError,
    addAccessGroupMember,
} from "../api/addAccessGroupMember"
import { useSession } from "../context/SessionContext"

export type AddAccessGroupMemberStatus =
    | { kind: "idle" }
    | { kind: "pending" }
    | { kind: "success" }
    | { kind: "denied" }
    | { kind: "conflict" }
    | { kind: "error" }

export interface UseAddAccessGroupMemberResult {
    status: AddAccessGroupMemberStatus
    submit: (accessGroupId: string, campaignMembershipId: string) => void
    reset: () => void
}

interface Snapshot {
    campaignId: string
    status: AddAccessGroupMemberStatus
}

interface IdempotencyReservation {
    accessGroupId: string
    campaignMembershipId: string
    key: string
}

const idleStatus: AddAccessGroupMemberStatus = { kind: "idle" }

// Mirrors useAssignMembershipRole's shape exactly (Phase 13E-B checkpoint
// 6's "Add member to group" control) — one hook instance per group's
// Add-member control.
export function useAddAccessGroupMember(
    campaignId: string,
    onSuccess: () => void,
): UseAddAccessGroupMemberResult {
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
        (accessGroupId: string, campaignMembershipId: string): string => {
            const reserved = idempotencyRef.current
            if (
                reserved !== null &&
                reserved.accessGroupId === accessGroupId &&
                reserved.campaignMembershipId === campaignMembershipId
            ) {
                return reserved.key
            }

            const key = globalThis.crypto.randomUUID()
            idempotencyRef.current = {
                accessGroupId,
                campaignMembershipId,
                key,
            }
            return key
        },
        [],
    )

    const status =
        snapshot.campaignId === campaignId ? snapshot.status : idleStatus

    const submit = useCallback(
        (accessGroupId: string, campaignMembershipId: string) => {
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
                campaignMembershipId,
            )
            const controller = new AbortController()
            controllerRef.current = controller
            setSnapshot({
                campaignId: requestCampaignId,
                status: { kind: "pending" },
            })

            void addAccessGroupMember(
                requestCampaignId,
                accessGroupId,
                campaignMembershipId,
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

                    if (cause instanceof AddAccessGroupMemberRequestError) {
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
        [status.kind, sessionState, campaignId, onSuccess, reload, resolveIdempotencyKey],
    )

    const reset = useCallback(() => {
        setSnapshot({ campaignId, status: idleStatus })
    }, [campaignId])

    return { status, submit, reset }
}

import { useCallback, useEffect, useRef, useState } from "react"
import {
    RemoveAccessGroupMemberRequestError,
    removeAccessGroupMember,
} from "../api/removeAccessGroupMember"
import { useSession } from "../context/SessionContext"

export type RemoveAccessGroupMemberStatus =
    | { kind: "idle" }
    | { kind: "pending" }
    | { kind: "success" }
    | { kind: "denied" }
    | { kind: "conflict" }
    | { kind: "error" }

export interface UseRemoveAccessGroupMemberResult {
    status: RemoveAccessGroupMemberStatus
    submit: (accessGroupMembershipId: string) => void
    reset: () => void
}

interface Snapshot {
    campaignId: string
    status: RemoveAccessGroupMemberStatus
}

interface IdempotencyReservation {
    accessGroupMembershipId: string
    key: string
}

const idleStatus: RemoveAccessGroupMemberStatus = { kind: "idle" }

// Mirrors useRemoveCampaignMembership's shape (Phase 13E-B checkpoint 6's
// "Remove from group" control) — one hook instance per group member's
// Remove control.
export function useRemoveAccessGroupMember(
    campaignId: string,
    onSuccess: () => void,
): UseRemoveAccessGroupMemberResult {
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
        (accessGroupMembershipId: string): string => {
            const reserved = idempotencyRef.current
            if (
                reserved !== null &&
                reserved.accessGroupMembershipId === accessGroupMembershipId
            ) {
                return reserved.key
            }

            const key = globalThis.crypto.randomUUID()
            idempotencyRef.current = { accessGroupMembershipId, key }
            return key
        },
        [],
    )

    const status =
        snapshot.campaignId === campaignId ? snapshot.status : idleStatus

    const submit = useCallback(
        (accessGroupMembershipId: string) => {
            if (status.kind === "pending") {
                return
            }
            if (sessionState.status !== "authenticated") {
                return
            }

            const requestCampaignId = campaignId
            const csrfToken = sessionState.bootstrap.csrf_token
            const idempotencyKey = resolveIdempotencyKey(
                accessGroupMembershipId,
            )
            const controller = new AbortController()
            controllerRef.current = controller
            setSnapshot({
                campaignId: requestCampaignId,
                status: { kind: "pending" },
            })

            void removeAccessGroupMember(
                requestCampaignId,
                accessGroupMembershipId,
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
                    // Self-removal from a group can remove the caller's
                    // own group-derived access — never manufacture the
                    // updated capability set locally, always re-derive it
                    // from a fresh bootstrap.
                    reload()
                })
                .catch((cause: unknown) => {
                    if (controller.signal.aborted) {
                        return
                    }

                    if (cause instanceof RemoveAccessGroupMemberRequestError) {
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

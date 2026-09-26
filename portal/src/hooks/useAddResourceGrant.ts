import { useCallback, useEffect, useRef, useState } from "react"
import { AddResourceGrantRequestError, addResourceGrant } from "../api/addResourceGrant"
import { useSession } from "../context/SessionContext"
import type { ResourceGrantEffect, ResourceGrantTarget } from "../types/resourceGrantTarget"

export type AddResourceGrantStatus =
    | { kind: "idle" }
    | { kind: "pending" }
    | { kind: "success" }
    | { kind: "denied" }
    | { kind: "conflict" }
    | { kind: "error" }

export interface UseAddResourceGrantResult {
    status: AddResourceGrantStatus
    submit: (
        campaignMembershipId: string,
        target: ResourceGrantTarget,
        capabilityCode: string,
        effect: ResourceGrantEffect,
    ) => void
    reset: () => void
}

interface Snapshot {
    campaignId: string
    status: AddResourceGrantStatus
}

interface IdempotencyReservation {
    campaignMembershipId: string
    target: ResourceGrantTarget
    capabilityCode: string
    effect: ResourceGrantEffect
    key: string
}

const idleStatus: AddResourceGrantStatus = { kind: "idle" }

// Mirrors useAddCharacterRelationship's shape exactly (checkpoint 5's own
// "Add direct resource access" counterpart) — one hook instance per
// member's Add-grant control, so double-submit prevention and independent
// row state both fall out the same way. See that hook's own comments for
// the full reasoning behind the idempotency-key/campaign-scoping/abort-on-
// unmount design; not re-derived here to avoid drifting the two copies
// apart in prose while their behavior stays identical.
export function useAddResourceGrant(
    campaignId: string,
    onSuccess: () => void,
): UseAddResourceGrantResult {
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
            campaignMembershipId: string,
            target: ResourceGrantTarget,
            capabilityCode: string,
            effect: ResourceGrantEffect,
        ): string => {
            const reserved = idempotencyRef.current
            if (
                reserved !== null &&
                reserved.campaignMembershipId === campaignMembershipId &&
                reserved.target.field === target.field &&
                reserved.target.id === target.id &&
                reserved.capabilityCode === capabilityCode &&
                reserved.effect === effect
            ) {
                return reserved.key
            }

            const key = globalThis.crypto.randomUUID()
            idempotencyRef.current = { campaignMembershipId, target, capabilityCode, effect, key }
            return key
        },
        [],
    )

    const status = snapshot.campaignId === campaignId ? snapshot.status : idleStatus

    const submit = useCallback(
        (
            campaignMembershipId: string,
            target: ResourceGrantTarget,
            capabilityCode: string,
            effect: ResourceGrantEffect,
        ) => {
            if (status.kind === "pending") {
                return
            }
            if (sessionState.status !== "authenticated") {
                return
            }

            const requestCampaignId = campaignId
            const csrfToken = sessionState.bootstrap.csrf_token
            const idempotencyKey = resolveIdempotencyKey(
                campaignMembershipId,
                target,
                capabilityCode,
                effect,
            )
            const controller = new AbortController()
            controllerRef.current = controller
            setSnapshot({ campaignId: requestCampaignId, status: { kind: "pending" } })

            void addResourceGrant(
                requestCampaignId,
                campaignMembershipId,
                target,
                capabilityCode,
                effect,
                csrfToken,
                idempotencyKey,
                controller.signal,
            )
                .then(() => {
                    if (controller.signal.aborted) {
                        return
                    }

                    idempotencyRef.current = null
                    setSnapshot({ campaignId: requestCampaignId, status: { kind: "success" } })
                    onSuccess()
                    // A new grant can affect the caller's own effective
                    // access (self-grant) — never manufacture the updated
                    // capability set locally, always re-derive it from a
                    // fresh bootstrap.
                    reload()
                })
                .catch((cause: unknown) => {
                    if (controller.signal.aborted) {
                        return
                    }

                    if (cause instanceof AddResourceGrantRequestError) {
                        if (cause.status === 401) {
                            setSnapshot({ campaignId: requestCampaignId, status: idleStatus })
                            reload()
                            return
                        }
                        if (cause.status === 403 || cause.status === 404) {
                            setSnapshot({ campaignId: requestCampaignId, status: { kind: "denied" } })
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

                    setSnapshot({ campaignId: requestCampaignId, status: { kind: "error" } })
                })
        },
        [status.kind, sessionState, campaignId, onSuccess, reload, resolveIdempotencyKey],
    )

    const reset = useCallback(() => {
        setSnapshot({ campaignId, status: idleStatus })
    }, [campaignId])

    return { status, submit, reset }
}

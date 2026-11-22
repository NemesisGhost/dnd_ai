import { useCallback, useEffect, useRef, useState } from "react"
import { AddResourceGrantRequestError, addResourceGrant } from "../api/addResourceGrant"
import { useSession } from "../context/SessionContext"
import { useAccessAuthorityRecheck, useAccessWriteCompletion } from "./useAccessWriteCompletion"
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
    // The HTTP status behind a `denied` outcome (403 or 404), for a form that tells the two apart; null otherwise.
    failureStatus: number | null
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
    failureStatus?: number
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
    // Confirmed write: reload the session, or re-read it in place when the write cannot affect the caller
    // (hooks/useAccessWriteCompletion).
    const completeWrite = useAccessWriteCompletion()
    // A 403 may mean access.manage is gone: the session is read again in place so the page can unmount (D-4).
    const recheckAuthority = useAccessAuthorityRecheck()
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
                    completeWrite()
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
                            setSnapshot({
                                campaignId: requestCampaignId,
                                status: { kind: "denied" },
                                failureStatus: cause.status,
                            })
                            if (cause.status === 403) {
                                recheckAuthority()
                            }
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
        [status.kind, sessionState, campaignId, onSuccess, reload, completeWrite, recheckAuthority, resolveIdempotencyKey],
    )

    const reset = useCallback(() => {
        setSnapshot({ campaignId, status: idleStatus })
    }, [campaignId])

    const failureStatus =
        snapshot.campaignId === campaignId && status.kind === "denied"
            ? (snapshot.failureStatus ?? null)
            : null

    return { status, failureStatus, submit, reset }
}

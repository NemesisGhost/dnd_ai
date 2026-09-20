import { useCallback, useEffect, useRef, useState } from "react"
import {
    AddGroupResourceGrantRequestError,
    addGroupResourceGrant,
} from "../api/addGroupResourceGrant"
import { useSession } from "../context/SessionContext"

export type AddGroupResourceGrantStatus =
    | { kind: "idle" }
    | { kind: "pending" }
    | { kind: "success" }
    | { kind: "denied" }
    | { kind: "conflict" }
    | { kind: "error" }

export interface UseAddGroupResourceGrantResult {
    status: AddGroupResourceGrantStatus
    submit: (
        accessGroupId: string,
        characterId: string,
        capabilityCode: string,
    ) => void
    reset: () => void
}

interface Snapshot {
    campaignId: string
    status: AddGroupResourceGrantStatus
}

interface IdempotencyReservation {
    accessGroupId: string
    characterId: string
    capabilityCode: string
    key: string
}

const idleStatus: AddGroupResourceGrantStatus = { kind: "idle" }

// Mirrors useAddResourceGrant's shape exactly (Phase 13E-B checkpoint 6's
// "Add group resource access" counterpart) — one hook instance per group's
// Add-grant control.
export function useAddGroupResourceGrant(
    campaignId: string,
    onSuccess: () => void,
): UseAddGroupResourceGrantResult {
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
            characterId: string,
            capabilityCode: string,
        ): string => {
            const reserved = idempotencyRef.current
            if (
                reserved !== null &&
                reserved.accessGroupId === accessGroupId &&
                reserved.characterId === characterId &&
                reserved.capabilityCode === capabilityCode
            ) {
                return reserved.key
            }

            const key = globalThis.crypto.randomUUID()
            idempotencyRef.current = {
                accessGroupId,
                characterId,
                capabilityCode,
                key,
            }
            return key
        },
        [],
    )

    const status =
        snapshot.campaignId === campaignId ? snapshot.status : idleStatus

    const submit = useCallback(
        (accessGroupId: string, characterId: string, capabilityCode: string) => {
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
                characterId,
                capabilityCode,
            )
            const controller = new AbortController()
            controllerRef.current = controller
            setSnapshot({
                campaignId: requestCampaignId,
                status: { kind: "pending" },
            })

            void addGroupResourceGrant(
                requestCampaignId,
                accessGroupId,
                characterId,
                capabilityCode,
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
                    // A new group-owned grant can affect the caller's own
                    // effective access if the caller is itself a member of
                    // the group — never manufacture the updated capability
                    // set locally, always re-derive it from a fresh
                    // bootstrap.
                    reload()
                })
                .catch((cause: unknown) => {
                    if (controller.signal.aborted) {
                        return
                    }

                    if (cause instanceof AddGroupResourceGrantRequestError) {
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

import {
    useCallback,
    useEffect,
    useRef,
    useState,
} from "react"
import {
    AddCharacterRelationshipRequestError,
    addCharacterRelationship,
} from "../api/addCharacterRelationship"
import { useSession } from "../context/SessionContext"

export type AddCharacterRelationshipStatus =
    | { kind: "idle" }
    | { kind: "pending" }
    | { kind: "success" }
    | { kind: "denied" }
    | { kind: "conflict" }
    | { kind: "error" }

export interface UseAddCharacterRelationshipResult {
    status: AddCharacterRelationshipStatus
    submit: (
        campaignMembershipId: string,
        characterId: string,
        relationshipTypeCode: string,
    ) => void
    reset: () => void
}

interface Snapshot {
    campaignId: string
    status: AddCharacterRelationshipStatus
}

interface IdempotencyReservation {
    campaignMembershipId: string
    characterId: string
    relationshipTypeCode: string
    key: string
}

const idleStatus: AddCharacterRelationshipStatus = {
    kind: "idle",
}

// Mirrors useAssignMembershipRole's shape exactly (the character-
// relationship-management checkpoint's own "Add character relationship"
// counterpart) — one hook instance per member's Add-relationship control,
// so double-submit prevention and independent row state both fall out the
// same way. See that hook's own comments for the full reasoning behind the
// idempotency-key/campaign-scoping/abort-on-unmount design; not re-derived
// here to avoid drifting the two copies apart in prose while their
// behavior stays identical.
export function useAddCharacterRelationship(
    campaignId: string,
    onSuccess: () => void,
): UseAddCharacterRelationshipResult {
    const { state: sessionState, reload } = useSession()
    const controllerRef =
        useRef<AbortController | null>(null)
    const idempotencyRef =
        useRef<IdempotencyReservation | null>(null)

    const [snapshot, setSnapshot] = useState<Snapshot>(
        () => ({ campaignId, status: idleStatus }),
    )

    useEffect(() => {
        return () => {
            controllerRef.current?.abort()
            idempotencyRef.current = null
        }
    }, [campaignId])

    const resolveIdempotencyKey = useCallback(
        (
            campaignMembershipId: string,
            characterId: string,
            relationshipTypeCode: string,
        ): string => {
            const reserved = idempotencyRef.current
            if (
                reserved !== null &&
                reserved.campaignMembershipId === campaignMembershipId &&
                reserved.characterId === characterId &&
                reserved.relationshipTypeCode === relationshipTypeCode
            ) {
                return reserved.key
            }

            const key = globalThis.crypto.randomUUID()
            idempotencyRef.current = {
                campaignMembershipId,
                characterId,
                relationshipTypeCode,
                key,
            }
            return key
        },
        [],
    )

    const status =
        snapshot.campaignId === campaignId
            ? snapshot.status
            : idleStatus

    const submit = useCallback(
        (
            campaignMembershipId: string,
            characterId: string,
            relationshipTypeCode: string,
        ) => {
            if (status.kind === "pending") {
                return
            }
            if (sessionState.status !== "authenticated") {
                return
            }

            const requestCampaignId = campaignId
            const csrfToken =
                sessionState.bootstrap.csrf_token
            const idempotencyKey = resolveIdempotencyKey(
                campaignMembershipId,
                characterId,
                relationshipTypeCode,
            )
            const controller = new AbortController()
            controllerRef.current = controller
            setSnapshot({
                campaignId: requestCampaignId,
                status: { kind: "pending" },
            })

            void addCharacterRelationship(
                requestCampaignId,
                campaignMembershipId,
                characterId,
                relationshipTypeCode,
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
                    // A new relationship can affect the caller's own
                    // visible character perspectives (self-grant) — never
                    // manufacture the updated perspective set locally,
                    // always re-derive it from a fresh bootstrap.
                    reload()
                })
                .catch((cause: unknown) => {
                    if (controller.signal.aborted) {
                        return
                    }

                    if (
                        cause instanceof
                        AddCharacterRelationshipRequestError
                    ) {
                        if (cause.status === 401) {
                            setSnapshot({
                                campaignId: requestCampaignId,
                                status: idleStatus,
                            })
                            reload()
                            return
                        }
                        if (
                            cause.status === 403 ||
                            cause.status === 404
                        ) {
                            setSnapshot({
                                campaignId: requestCampaignId,
                                status: { kind: "denied" },
                            })
                            return
                        }
                        if (
                            cause.status === 409 ||
                            cause.status === 400
                        ) {
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
        [
            status.kind,
            sessionState,
            campaignId,
            onSuccess,
            reload,
            resolveIdempotencyKey,
        ],
    )

    const reset = useCallback(() => {
        setSnapshot({ campaignId, status: idleStatus })
    }, [campaignId])

    return { status, submit, reset }
}

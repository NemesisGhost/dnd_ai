import {
    useCallback,
    useEffect,
    useRef,
    useState,
} from "react"
import {
    ChangeCharacterRelationshipRequestError,
    changeCharacterRelationship,
} from "../api/changeCharacterRelationship"
import { useSession } from "../context/SessionContext"

export type ChangeCharacterRelationshipStatus =
    | { kind: "idle" }
    | { kind: "pending" }
    | { kind: "success" }
    | { kind: "denied" }
    | { kind: "conflict" }
    | { kind: "validation" }
    | { kind: "error" }

export interface UseChangeCharacterRelationshipResult {
    status: ChangeCharacterRelationshipStatus
    submit: (
        membershipCharacterRelationshipId: string,
        newRelationshipTypeId: string,
    ) => void
    reset: () => void
}

interface Snapshot {
    campaignId: string
    status: ChangeCharacterRelationshipStatus
}

interface IdempotencyReservation {
    membershipCharacterRelationshipId: string
    newRelationshipTypeId: string
    key: string
}

const idleStatus: ChangeCharacterRelationshipStatus = {
    kind: "idle",
}

// Mirrors useChangeMembershipRole's shape exactly (the character-
// relationship-management checkpoint's own "Change relationship type"
// counterpart) — one hook instance per active relationship row, so
// double-submit prevention and independent row state both fall out the
// same way. See that hook's own comments for the full reasoning behind the
// idempotency-key/campaign-scoping/abort-on-unmount design; not re-derived
// here to avoid drifting the two copies apart in prose while their
// behavior stays identical.
export function useChangeCharacterRelationship(
    campaignId: string,
    onSuccess: () => void,
): UseChangeCharacterRelationshipResult {
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
            membershipCharacterRelationshipId: string,
            newRelationshipTypeId: string,
        ): string => {
            const reserved = idempotencyRef.current
            if (
                reserved !== null &&
                reserved.membershipCharacterRelationshipId ===
                    membershipCharacterRelationshipId &&
                reserved.newRelationshipTypeId === newRelationshipTypeId
            ) {
                return reserved.key
            }

            const key = globalThis.crypto.randomUUID()
            idempotencyRef.current = {
                membershipCharacterRelationshipId,
                newRelationshipTypeId,
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
            membershipCharacterRelationshipId: string,
            newRelationshipTypeId: string,
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
                membershipCharacterRelationshipId,
                newRelationshipTypeId,
            )
            const controller = new AbortController()
            controllerRef.current = controller
            setSnapshot({
                campaignId: requestCampaignId,
                status: { kind: "pending" },
            })

            void changeCharacterRelationship(
                requestCampaignId,
                membershipCharacterRelationshipId,
                newRelationshipTypeId,
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
                    // A changed relationship type can affect the caller's
                    // own visible character perspectives (self-change) —
                    // never manufacture the updated perspective set
                    // locally, always re-derive it from a fresh bootstrap.
                    reload()
                })
                .catch((cause: unknown) => {
                    if (controller.signal.aborted) {
                        return
                    }

                    if (
                        cause instanceof
                        ChangeCharacterRelationshipRequestError
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
                        if (cause.status === 409) {
                            setSnapshot({
                                campaignId: requestCampaignId,
                                status: { kind: "conflict" },
                            })
                            return
                        }
                        if (cause.status === 422) {
                            setSnapshot({
                                campaignId: requestCampaignId,
                                status: { kind: "validation" },
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

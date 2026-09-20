import {
    useCallback,
    useEffect,
    useRef,
    useState,
} from "react"
import {
    RevokeCharacterRelationshipRequestError,
    revokeCharacterRelationship,
} from "../api/revokeCharacterRelationship"
import { useSession } from "../context/SessionContext"

export type RevokeCharacterRelationshipStatus =
    | { kind: "idle" }
    | { kind: "pending" }
    | { kind: "success" }
    | { kind: "denied" }
    | { kind: "conflict" }
    | { kind: "error" }

export interface UseRevokeCharacterRelationshipResult {
    status: RevokeCharacterRelationshipStatus
    submit: (membershipCharacterRelationshipId: string) => void
    reset: () => void
}

interface Snapshot {
    campaignId: string
    status: RevokeCharacterRelationshipStatus
}

interface IdempotencyReservation {
    membershipCharacterRelationshipId: string
    key: string
}

const idleStatus: RevokeCharacterRelationshipStatus = {
    kind: "idle",
}

// Mirrors useRevokeMembershipRole's shape exactly (the character-
// relationship-management checkpoint's own "Revoke character relationship"
// counterpart) — one hook instance per active relationship row's Revoke
// control. Reusing the same durable Idempotency-Key here matches
// dnd_ai.api.access_grants.revoke_character_relationship_endpoint's own
// hardening: the backend command is already state-idempotent on an
// already-revoked row, but only a reused key (never re-running the
// command at all) also keeps the *audit trail* free of a second row on an
// ordinary retry with an unknown network outcome — see that route's own
// docstring.
export function useRevokeCharacterRelationship(
    campaignId: string,
    onSuccess: () => void,
): UseRevokeCharacterRelationshipResult {
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
        (membershipCharacterRelationshipId: string): string => {
            const reserved = idempotencyRef.current
            if (
                reserved !== null &&
                reserved.membershipCharacterRelationshipId ===
                    membershipCharacterRelationshipId
            ) {
                return reserved.key
            }

            const key = globalThis.crypto.randomUUID()
            idempotencyRef.current = {
                membershipCharacterRelationshipId,
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
        (membershipCharacterRelationshipId: string) => {
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
            )
            const controller = new AbortController()
            controllerRef.current = controller
            setSnapshot({
                campaignId: requestCampaignId,
                status: { kind: "pending" },
            })

            void revokeCharacterRelationship(
                requestCampaignId,
                membershipCharacterRelationshipId,
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
                    // Revocation can remove the caller's own visible
                    // character perspective (self-revoke) — never
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
                        RevokeCharacterRelationshipRequestError
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

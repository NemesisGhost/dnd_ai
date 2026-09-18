import {
    useCallback,
    useEffect,
    useRef,
    useState,
} from "react"
import {
    RevokeMembershipRoleRequestError,
    revokeMembershipRole,
} from "../api/revokeMembershipRole"
import { useSession } from "../context/SessionContext"

export type RevokeMembershipRoleStatus =
    | { kind: "idle" }
    | { kind: "pending" }
    | { kind: "success" }
    | { kind: "denied" }
    | { kind: "conflict" }
    | { kind: "error" }

export interface UseRevokeMembershipRoleResult {
    status: RevokeMembershipRoleStatus
    submit: (membershipRoleId: string) => void
    reset: () => void
}

interface Snapshot {
    campaignId: string
    status: RevokeMembershipRoleStatus
}

interface IdempotencyReservation {
    membershipRoleId: string
    key: string
}

const idleStatus: RevokeMembershipRoleStatus = {
    kind: "idle",
}

// Mirrors useChangeMembershipRole/useAssignMembershipRole's shape (Phase
// 13E-B checkpoint 2's "Revoke role" counterpart) — one hook instance per
// active role row's Revoke control. Reusing the same durable
// Idempotency-Key here matches dnd_ai.api.memberships.
// revoke_membership_role_endpoint's own hardening: the backend command is
// already state-idempotent on an already-revoked row, but only a reused
// key (never re-running the command at all) also keeps the *audit trail*
// free of a second row on an ordinary retry with an unknown network
// outcome — see that route's own docstring.
export function useRevokeMembershipRole(
    campaignId: string,
    onSuccess: () => void,
): UseRevokeMembershipRoleResult {
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
        (membershipRoleId: string): string => {
            const reserved = idempotencyRef.current
            if (
                reserved !== null &&
                reserved.membershipRoleId === membershipRoleId
            ) {
                return reserved.key
            }

            const key = globalThis.crypto.randomUUID()
            idempotencyRef.current = { membershipRoleId, key }
            return key
        },
        [],
    )

    const status =
        snapshot.campaignId === campaignId
            ? snapshot.status
            : idleStatus

    const submit = useCallback(
        (membershipRoleId: string) => {
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
                membershipRoleId,
            )
            const controller = new AbortController()
            controllerRef.current = controller
            setSnapshot({
                campaignId: requestCampaignId,
                status: { kind: "pending" },
            })

            void revokeMembershipRole(
                requestCampaignId,
                membershipRoleId,
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
                    // Self-revocation can remove the caller's own
                    // access.manage capability — never manufacture the
                    // updated capability set locally, always re-derive it
                    // from a fresh bootstrap.
                    reload()
                })
                .catch((cause: unknown) => {
                    if (controller.signal.aborted) {
                        return
                    }

                    if (
                        cause instanceof
                        RevokeMembershipRoleRequestError
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

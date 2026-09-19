import {
    useCallback,
    useEffect,
    useRef,
    useState,
} from "react"
import {
    AssignMembershipRoleRequestError,
    assignMembershipRole,
} from "../api/assignMembershipRole"
import { useSession } from "../context/SessionContext"

export type AssignMembershipRoleStatus =
    | { kind: "idle" }
    | { kind: "pending" }
    | { kind: "success" }
    | { kind: "denied" }
    | { kind: "conflict" }
    | { kind: "error" }

export interface UseAssignMembershipRoleResult {
    status: AssignMembershipRoleStatus
    submit: (
        campaignMembershipId: string,
        roleId: string,
    ) => void
    reset: () => void
}

interface Snapshot {
    campaignId: string
    status: AssignMembershipRoleStatus
}

interface IdempotencyReservation {
    campaignMembershipId: string
    roleId: string
    key: string
}

const idleStatus: AssignMembershipRoleStatus = {
    kind: "idle",
}

// Mirrors useChangeMembershipRole's shape exactly (Phase 13E-B checkpoint
// 2's "Add role" counterpart) — one hook instance per member's Add-role
// control, so double-submit prevention and independent row state both fall
// out the same way. See that hook's own comments for the full reasoning
// behind the idempotency-key/campaign-scoping/abort-on-unmount design;
// not re-derived here to avoid drifting the two copies apart in prose
// while their behavior stays identical.
export function useAssignMembershipRole(
    campaignId: string,
    onSuccess: () => void,
): UseAssignMembershipRoleResult {
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
        (campaignMembershipId: string, roleId: string): string => {
            const reserved = idempotencyRef.current
            if (
                reserved !== null &&
                reserved.campaignMembershipId === campaignMembershipId &&
                reserved.roleId === roleId
            ) {
                return reserved.key
            }

            const key = globalThis.crypto.randomUUID()
            idempotencyRef.current = {
                campaignMembershipId,
                roleId,
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
        (campaignMembershipId: string, roleId: string) => {
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
                roleId,
            )
            const controller = new AbortController()
            controllerRef.current = controller
            setSnapshot({
                campaignId: requestCampaignId,
                status: { kind: "pending" },
            })

            void assignMembershipRole(
                requestCampaignId,
                campaignMembershipId,
                roleId,
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
                    // A new role can affect the caller's own visible
                    // capabilities/navigation (self-assign) — never
                    // manufacture the updated capability set locally,
                    // always re-derive it from a fresh bootstrap.
                    reload()
                })
                .catch((cause: unknown) => {
                    if (controller.signal.aborted) {
                        return
                    }

                    if (
                        cause instanceof
                        AssignMembershipRoleRequestError
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

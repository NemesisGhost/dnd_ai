import {
    useCallback,
    useEffect,
    useRef,
    useState,
} from "react"
import {
    AddCampaignMemberRequestError,
    addCampaignMember,
} from "../api/addCampaignMember"
import { useSession } from "../context/SessionContext"

export type AddCampaignMemberStatus =
    | { kind: "idle" }
    | { kind: "pending" }
    | { kind: "success" }
    | { kind: "denied" }
    | { kind: "conflict" }
    | { kind: "error" }

export interface UseAddCampaignMemberResult {
    status: AddCampaignMemberStatus
    submit: (userId: string, roleId: string) => void
    reset: () => void
}

interface Snapshot {
    campaignId: string
    status: AddCampaignMemberStatus
}

interface IdempotencyReservation {
    userId: string
    roleId: string
    key: string
}

const idleStatus: AddCampaignMemberStatus = {
    kind: "idle",
}

// Mirrors useAssignMembershipRole's shape (Phase 13E-B checkpoint 3's
// "Add campaign member" counterpart) — one hook instance for the Access
// page's single Add-member control. See that hook's own comments for the
// full reasoning behind the idempotency-key/campaign-scoping/abort-on-
// unmount design; not re-derived here to avoid drifting the two copies
// apart in prose while their behavior stays identical.
export function useAddCampaignMember(
    campaignId: string,
    onSuccess: () => void,
): UseAddCampaignMemberResult {
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
        (userId: string, roleId: string): string => {
            const reserved = idempotencyRef.current
            if (
                reserved !== null &&
                reserved.userId === userId &&
                reserved.roleId === roleId
            ) {
                return reserved.key
            }

            const key = globalThis.crypto.randomUUID()
            idempotencyRef.current = { userId, roleId, key }
            return key
        },
        [],
    )

    const status =
        snapshot.campaignId === campaignId
            ? snapshot.status
            : idleStatus

    const submit = useCallback(
        (userId: string, roleId: string) => {
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
                userId,
                roleId,
            )
            const controller = new AbortController()
            controllerRef.current = controller
            setSnapshot({
                campaignId: requestCampaignId,
                status: { kind: "pending" },
            })

            void addCampaignMember(
                requestCampaignId,
                userId,
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
                })
                .catch((cause: unknown) => {
                    if (controller.signal.aborted) {
                        return
                    }

                    if (
                        cause instanceof
                        AddCampaignMemberRequestError
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

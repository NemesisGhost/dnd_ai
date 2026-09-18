import {
    useCallback,
    useEffect,
    useRef,
    useState,
} from "react"
import {
    ChangeMembershipRoleRequestError,
    changeMembershipRole,
} from "../api/changeMembershipRole"
import { useSession } from "../context/SessionContext"

export type ChangeMembershipRoleStatus =
    | { kind: "idle" }
    | { kind: "pending" }
    | { kind: "success" }
    | { kind: "denied" }
    | { kind: "conflict" }
    | { kind: "validation" }
    | { kind: "error" }

export interface UseChangeMembershipRoleResult {
    status: ChangeMembershipRoleStatus
    submit: (
        membershipRoleId: string,
        newRoleId: string,
    ) => void
    reset: () => void
}

interface Snapshot {
    campaignId: string
    status: ChangeMembershipRoleStatus
}

interface IdempotencyReservation {
    membershipRoleId: string
    newRoleId: string
    key: string
}

const idleStatus: ChangeMembershipRoleStatus = {
    kind: "idle",
}

// One hook instance per role row (the caller owns exactly one), so
// double-submit prevention and "keep unrelated rows usable" both fall out
// naturally — every row's pending/error state is already independent.
//
// Mirrors useAccessOverview's snapshot/derived-status shape: the status a
// caller sees is only ever the one recorded *for the campaign the request
// was submitted against* (`snapshot.campaignId`) — a campaign change
// never keeps showing a stale pending/error/success state, and `onSuccess`
// is never called for a response that resolves after the viewer has
// already navigated to a different campaign's Access page.
export function useChangeMembershipRole(
    campaignId: string,
    onSuccess: () => void,
): UseChangeMembershipRoleResult {
    const { state: sessionState, reload } = useSession()
    const controllerRef =
        useRef<AbortController | null>(null)
    // One reservation for "one logical campaign/assignment/new-role edit"
    // (finding 2): reused verbatim across a retry of the *same* selection
    // (a network outcome the caller never confirmed), regenerated the
    // moment the selection changes (a different role row or a different
    // new_role_id), and cleared entirely on success — so a later edit,
    // even one that happens to choose the identical role again, always
    // gets a fresh key rather than risking a replay of a stale cached
    // response. See resolveIdempotencyKey below.
    const idempotencyRef =
        useRef<IdempotencyReservation | null>(null)

    const [snapshot, setSnapshot] = useState<Snapshot>(
        () => ({ campaignId, status: idleStatus }),
    )

    // A campaign change invalidates any in-flight mutation for the
    // previous campaign — abort it so a late response can never act on
    // (or set status for) the newly-selected campaign's page. The same
    // cleanup covers unmount. It also drops any reserved idempotency key:
    // a key is scoped to one campaign's own edit, never carried across a
    // campaign change. The *displayed* status is derived below rather
    // than reset here, so this effect never calls setState.
    useEffect(() => {
        return () => {
            controllerRef.current?.abort()
            idempotencyRef.current = null
        }
    }, [campaignId])

    const resolveIdempotencyKey = useCallback(
        (membershipRoleId: string, newRoleId: string): string => {
            const reserved = idempotencyRef.current
            if (
                reserved !== null &&
                reserved.membershipRoleId === membershipRoleId &&
                reserved.newRoleId === newRoleId
            ) {
                // Retrying the identical selection (an unknown network
                // outcome, or a caller-initiated retry after a recoverable
                // error) — reuse the same key so the backend's own
                // idempotent-replay contract applies.
                return reserved.key
            }

            // A different role row, a different new_role_id for the same
            // row, or no reservation at all (first attempt, or the
            // previous one succeeded and was cleared) — a genuinely new
            // logical edit, so a fresh key.
            const key = globalThis.crypto.randomUUID()
            idempotencyRef.current = { membershipRoleId, newRoleId, key }
            return key
        },
        [],
    )

    const status =
        snapshot.campaignId === campaignId
            ? snapshot.status
            : idleStatus

    const submit = useCallback(
        (membershipRoleId: string, newRoleId: string) => {
            // Double-submit prevention: a second call while one is already
            // pending is a no-op, not a queued/replacing request.
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
                newRoleId,
            )
            const controller = new AbortController()
            controllerRef.current = controller
            setSnapshot({
                campaignId: requestCampaignId,
                status: { kind: "pending" },
            })

            void changeMembershipRole(
                requestCampaignId,
                membershipRoleId,
                newRoleId,
                csrfToken,
                idempotencyKey,
                controller.signal,
            )
                .then(() => {
                    if (controller.signal.aborted) {
                        return
                    }

                    // A confirmed success — this exact edit is done, so its
                    // key must never be reused, even if a later edit
                    // happens to choose the identical role again.
                    idempotencyRef.current = null
                    setSnapshot({
                        campaignId: requestCampaignId,
                        status: { kind: "success" },
                    })
                    onSuccess()
                    // Role changes can affect the caller's own visible
                    // capabilities/navigation (self-change) — never
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
                        ChangeMembershipRoleRequestError
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

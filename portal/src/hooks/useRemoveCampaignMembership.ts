import {
    useCallback,
    useEffect,
    useRef,
    useState,
} from "react"
import {
    RemoveCampaignMembershipRequestError,
    removeCampaignMembership,
} from "../api/removeCampaignMembership"
import { useSession } from "../context/SessionContext"

export type RemoveCampaignMembershipStatus =
    | { kind: "idle" }
    | { kind: "pending" }
    | { kind: "success" }
    | { kind: "denied" }
    | { kind: "last_manager" }
    | { kind: "conflict" }
    | { kind: "error" }

export interface UseRemoveCampaignMembershipResult {
    status: RemoveCampaignMembershipStatus
    submit: (campaignMembershipId: string) => void
    reset: () => void
}

interface Snapshot {
    campaignId: string
    status: RemoveCampaignMembershipStatus
}

interface IdempotencyReservation {
    campaignMembershipId: string
    key: string
}

const idleStatus: RemoveCampaignMembershipStatus = {
    kind: "idle",
}

// Mirrors useRevokeMembershipRole's shape (Phase 13E-B checkpoint 3's
// "Remove member" counterpart) — one hook instance per member's Remove
// control. See that hook's own comments for the full reasoning behind the
// idempotency-key/campaign-scoping/abort-on-unmount design; not re-derived
// here. The backend's last-manager rejection (400, dnd_ai.commands.
// memberships.end_campaign_membership's retention invariant) is
// distinguished from every other 4xx here as its own status kind ("last_
// manager") so the control can present it distinctly rather than folding
// it into the generic recoverable-error message.
export function useRemoveCampaignMembership(
    campaignId: string,
    onSuccess: () => void,
): UseRemoveCampaignMembershipResult {
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
        (campaignMembershipId: string): string => {
            const reserved = idempotencyRef.current
            if (
                reserved !== null &&
                reserved.campaignMembershipId ===
                    campaignMembershipId
            ) {
                return reserved.key
            }

            const key = globalThis.crypto.randomUUID()
            idempotencyRef.current = {
                campaignMembershipId,
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
        (campaignMembershipId: string) => {
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
            )
            const controller = new AbortController()
            controllerRef.current = controller
            setSnapshot({
                campaignId: requestCampaignId,
                status: { kind: "pending" },
            })

            void removeCampaignMembership(
                requestCampaignId,
                campaignMembershipId,
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
                    // Self-removal can remove the caller's own
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
                        RemoveCampaignMembershipRequestError
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
                        if (cause.status === 400) {
                            setSnapshot({
                                campaignId: requestCampaignId,
                                status: { kind: "last_manager" },
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

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

    const [snapshot, setSnapshot] = useState<Snapshot>(
        () => ({ campaignId, status: idleStatus }),
    )

    // A campaign change invalidates any in-flight mutation for the
    // previous campaign — abort it so a late response can never act on
    // (or set status for) the newly-selected campaign's page. The same
    // cleanup covers unmount. The *displayed* status is derived below
    // rather than reset here, so this effect never calls setState.
    useEffect(() => {
        return () => {
            controllerRef.current?.abort()
        }
    }, [campaignId])

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
                controller.signal,
            )
                .then(() => {
                    if (controller.signal.aborted) {
                        return
                    }

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
        [status.kind, sessionState, campaignId, onSuccess, reload],
    )

    const reset = useCallback(() => {
        setSnapshot({ campaignId, status: idleStatus })
    }, [campaignId])

    return { status, submit, reset }
}

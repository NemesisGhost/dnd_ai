import { useCallback, useEffect, useRef, useState } from "react"
import { PlatformAccountsRequestError } from "../api/platformAccounts"
import { assignSystemRole, revokeSystemRole } from "../api/systemRoles"
import { useSession } from "../context/SessionContext"
import type { SystemRoleChangeResponse } from "../types/platformAccounts"
import type { SystemRoleCode } from "../utils/systemAccess"

export type SystemRoleChangeStatus =
    | { kind: "idle" }
    | { kind: "pending" }
    | { kind: "success" }
    | { kind: "denied" }
    | { kind: "conflict"; message: string }
    | { kind: "error" }

export interface UseSystemRoleChangeResult {
    status: SystemRoleChangeStatus
    change: (targetUserId: string, roleCode: SystemRoleCode, assign: boolean) => void
}

const idleStatus: SystemRoleChangeStatus = { kind: "idle" }

// One hook for both directions: the server owns the rules (the last-
// administrator guard, the in-app Administrator-grant switch); this only reports
// the outcome and asks the caller to refetch.
export function useSystemRoleChange(
    onSuccess: (result: SystemRoleChangeResponse) => void,
): UseSystemRoleChangeResult {
    const { state: sessionState, reload } = useSession()
    const controllerRef = useRef<AbortController | null>(null)
    const [status, setStatus] = useState<SystemRoleChangeStatus>(idleStatus)

    useEffect(() => {
        return () => {
            controllerRef.current?.abort()
        }
    }, [])

    const change = useCallback(
        (targetUserId: string, roleCode: SystemRoleCode, assign: boolean) => {
            if (status.kind === "pending" || sessionState.status !== "authenticated") {
                return
            }

            const controller = new AbortController()
            controllerRef.current = controller
            setStatus({ kind: "pending" })

            const csrf = sessionState.bootstrap.csrf_token
            const request = assign
                ? assignSystemRole(targetUserId, roleCode, csrf, controller.signal)
                : revokeSystemRole(targetUserId, roleCode, csrf, controller.signal)

            void request
                .then((result) => {
                    if (controller.signal.aborted) {
                        return
                    }
                    setStatus({ kind: "success" })
                    onSuccess(result)
                })
                .catch((cause: unknown) => {
                    if (controller.signal.aborted) {
                        return
                    }
                    if (cause instanceof PlatformAccountsRequestError) {
                        if (cause.status === 401) {
                            setStatus(idleStatus)
                            void reload()
                            return
                        }
                        if (cause.status === 403 || cause.status === 404) {
                            setStatus({ kind: "denied" })
                            return
                        }
                        if (cause.status === 409) {
                            setStatus({
                                kind: "conflict",
                                message:
                                    "This is the platform's only active administrator and cannot lose the Administrator role.",
                            })
                            return
                        }
                    }
                    setStatus({ kind: "error" })
                })
        },
        [onSuccess, reload, sessionState, status.kind],
    )

    return { status, change }
}

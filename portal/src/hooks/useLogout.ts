import {
    useEffect,
    useRef,
    useState,
} from "react"
import { useNavigate } from "react-router"
import { useSession } from "../context/SessionContext"
import { logout, LogoutRequestError } from "../api/logout"

export type LogoutStatus =
    | { kind: "idle" }
    | { kind: "pending" }
    | { kind: "error"; message: string }

export interface UseLogoutResult {
    status: LogoutStatus
    logout: () => Promise<void>
}

const idleStatus: LogoutStatus = { kind: "idle" }

// Extracted from the former LogoutButton so the profile menu (and any
// other future trigger) can drive the same request, abort-on-unmount,
// and error-message behavior. On success it reloads session state and
// then explicitly navigates to /login with no continuation state, so a
// different user signing in next always lands on /home rather than the
// page the previous user was on (UI_DESIGN §4.2, navigation plan §2.4).
export function useLogout(): UseLogoutResult {
    const { state, reload } = useSession()
    const navigate = useNavigate()
    const [status, setStatus] = useState<LogoutStatus>(idleStatus)
    const controllerRef = useRef<AbortController | null>(null)

    useEffect(() => {
        return () => {
            controllerRef.current?.abort()
        }
    }, [])

    async function handleLogout(): Promise<void> {
        if (state.status !== "authenticated") {
            return
        }

        setStatus({ kind: "pending" })

        const controller = new AbortController()
        controllerRef.current = controller

        try {
            await logout(state.bootstrap.csrf_token, controller.signal)

            if (controller.signal.aborted) {
                return
            }

            // Never keep the csrf token or any session credential around
            // once logout succeeds — reload() re-derives protected UI from
            // a fresh GET /auth/session rather than local assumptions
            // about the old one. The explicit navigate() that follows
            // carries no state, which is what keeps a later login from
            // landing on the signed-out user's old page.
            setStatus(idleStatus)
            reload()
            navigate("/login", { replace: true })
        } catch (cause: unknown) {
            if (controller.signal.aborted) {
                return
            }

            const message =
                cause instanceof LogoutRequestError
                    ? `Log out failed (status ${cause.status}). Please try again.`
                    : "Log out failed. Check your connection and try again."

            setStatus({ kind: "error", message })
        }
    }

    return {
        status,
        logout: handleLogout,
    }
}

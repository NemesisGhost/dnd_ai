import { useEffect, useRef, useState } from "react"
import { useSession } from "../context/SessionContext"
import { logout, LogoutRequestError } from "../api/logout"

type LogoutStatus =
  | { kind: "idle" }
  | { kind: "pending" }
  | { kind: "error"; message: string }

const idleStatus: LogoutStatus = { kind: "idle" }

export function LogoutButton() {
  const { state, reload } = useSession()
  const [status, setStatus] = useState<LogoutStatus>(idleStatus)
  const controllerRef = useRef<AbortController | null>(null)

  useEffect(() => {
    return () => {
      controllerRef.current?.abort()
    }
  }, [])

  if (state.status !== "authenticated") {
    return null
  }

  const csrfToken = state.bootstrap.csrf_token

  async function handleLogout(): Promise<void> {
    setStatus({ kind: "pending" })

    const controller = new AbortController()
    controllerRef.current = controller

    try {
      await logout(csrfToken, controller.signal)

      if (controller.signal.aborted) {
        return
      }

      // Never keep the csrf token or any session credential around once
      // logout succeeds — reload() re-derives protected UI from a fresh
      // GET /auth/session rather than local assumptions about the old one.
      setStatus(idleStatus)
      reload()
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

  return (
    <div className="logout-control">
      <button
        type="button"
        className="logout-control__button"
        onClick={() => void handleLogout()}
        disabled={status.kind === "pending"}
        aria-busy={status.kind === "pending"}
      >
        {status.kind === "pending" ? "Logging out…" : "Log out"}
      </button>

      {status.kind === "error" && (
        <p className="logout-control__error" role="alert">
          {status.message}
        </p>
      )}
    </div>
  )
}

import {
  useCallback,
  useEffect,
  useState,
} from "react"
import { SESSION_EXPIRED_EVENT } from "../api/http"
import { fetchSessionBootstrap } from "../api/session"
import type { SessionBootstrap } from "../types/bootstrap"

export type SessionBootstrapState =
  | {
      status: "loading"
    }
  | {
      status: "authenticated"
      bootstrap: SessionBootstrap
    }
  | {
      status: "unauthenticated"
    }
  | {
      status: "error"
      error: Error
    }

export interface UseSessionBootstrapResult {
  state: SessionBootstrapState
  reload: () => void
  // Re-fetches the authoritative bootstrap and replaces it in place,
  // WITHOUT passing through the "loading" state (which would unmount the
  // current page). Resolves true when the fresh bootstrap was applied,
  // false when the session turned out to be unauthenticated (state becomes
  // "unauthenticated"); rejects on a failed request, leaving the previous
  // bootstrap untouched. Used after a mutation changes bootstrap-visible
  // state (e.g. a saved startup preference).
  refresh: (signal?: AbortSignal) => Promise<boolean>
}

const initialState: SessionBootstrapState = {
  status: "loading",
}

export function useSessionBootstrap():
  UseSessionBootstrapResult {
  const [state, setState] =
    useState<SessionBootstrapState>(initialState)

  const [requestVersion, setRequestVersion] = useState(0)

  const reload = useCallback(() => {
    setState({
      status: "loading",
    })

    setRequestVersion((currentVersion) => currentVersion + 1)
  }, [])

  const refresh = useCallback(
    async (signal?: AbortSignal): Promise<boolean> => {
      const bootstrap = await fetchSessionBootstrap(signal)

      if (signal?.aborted) {
        return false
      }

      if (bootstrap === null) {
        setState({ status: "unauthenticated" })
        return false
      }

      setState({ status: "authenticated", bootstrap })
      return true
    },
    [],
  )

  useEffect(() => {
    const controller = new AbortController()

    void fetchSessionBootstrap(controller.signal)
      .then((bootstrap) => {
        if (controller.signal.aborted) {
          return
        }

        if (bootstrap === null) {
          setState({
            status: "unauthenticated",
          })
          return
        }

        setState({
          status: "authenticated",
          bootstrap,
        })
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) {
          return
        }

        const error =
          cause instanceof Error
            ? cause
            : new Error("Session bootstrap request failed")

        setState({
          status: "error",
          error,
        })
      })

    return () => {
      controller.abort()
    }
  }, [requestVersion])

  // Leave the signed-in UI the moment the session lapses, rather than on
  // the next failing request. The idle window slides server-side, so when
  // the local deadline passes we ask the server (which also renews a
  // still-valid session) and only sign out on a 401.
  const authenticatedBootstrap =
    state.status === "authenticated" ? state.bootstrap : null

  useEffect(() => {
    if (authenticatedBootstrap === null) {
      return
    }

    const idleMs =
      (authenticatedBootstrap.session_idle_timeout_seconds ?? 0) * 1000
    const absoluteMs = authenticatedBootstrap.session_absolute_expires_at
      ? Date.parse(authenticatedBootstrap.session_absolute_expires_at)
      : Number.NaN
    let idleDeadline = idleMs > 0 ? Date.now() + idleMs : Number.NaN
    let timer: ReturnType<typeof setTimeout> | undefined
    let disposed = false

    const expire = () => {
      if (!disposed) {
        setState({ status: "unauthenticated" })
      }
    }

    const deadline = () =>
      Math.min(
        Number.isNaN(idleDeadline) ? Infinity : idleDeadline,
        Number.isNaN(absoluteMs) ? Infinity : absoluteMs,
      )

    const schedule = () => {
      clearTimeout(timer)
      const remaining = deadline() - Date.now()
      if (!Number.isFinite(remaining)) {
        return
      }
      // setTimeout caps at ~24.8 days; sessions are far shorter.
      timer = setTimeout(check, Math.max(remaining, 0) + 1000)
    }

    const check = () => {
      if (disposed || Date.now() < deadline()) {
        schedule()
        return
      }
      if (!Number.isNaN(absoluteMs) && Date.now() >= absoluteMs) {
        expire()
        return
      }
      void fetchSessionBootstrap()
        .then((fresh) => {
          if (disposed) {
            return
          }
          if (fresh === null) {
            expire()
            return
          }
          idleDeadline = Date.now() + idleMs
          schedule()
        })
        .catch(() => {
          // Network trouble says nothing about the session; retry later.
          if (!disposed) {
            timer = setTimeout(check, 30_000)
          }
        })
    }

    const onWake = () => {
      if (document.visibilityState !== "hidden") {
        check()
      }
    }

    schedule()
    window.addEventListener(SESSION_EXPIRED_EVENT, expire)
    window.addEventListener("focus", onWake)
    window.addEventListener("pageshow", onWake)
    document.addEventListener("visibilitychange", onWake)

    return () => {
      disposed = true
      clearTimeout(timer)
      window.removeEventListener(SESSION_EXPIRED_EVENT, expire)
      window.removeEventListener("focus", onWake)
      window.removeEventListener("pageshow", onWake)
      document.removeEventListener("visibilitychange", onWake)
    }
  }, [authenticatedBootstrap])

  return {
    state,
    reload,
    refresh,
  }
}
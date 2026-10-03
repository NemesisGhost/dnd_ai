import {
  useCallback,
  useEffect,
  useState,
} from "react"
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

  return {
    state,
    reload,
    refresh,
  }
}
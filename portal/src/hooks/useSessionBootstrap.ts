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
  }
}
import {
  useCallback,
  useEffect,
  useRef,
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
  //
  // `false` also means "not applied": the request was superseded (a reload, an expiry, an unmount
  // or a newer session request decided first) or aborted. A superseded request never publishes
  // state and never reports its data as applied, whether it succeeded or failed.
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

  // Request ownership. Every session read (the initial load, a reload, a refresh) takes a ticket in
  // the order it STARTS. A read may publish its result only if
  //   - no reload, expiry or unmount has invalidated it (its ticket is at least `floor`), and
  //   - nothing that started after it has already published (its ticket is above `applied`).
  // So an older read that finishes late - authenticated or unauthenticated, successful or failed -
  // can neither restore a session that a newer result or an expiry ended, nor end one that a newer
  // result established. Aborting a request is only cleanup; it is not what guarantees freshness.
  const issued = useRef(0)
  const floor = useRef(1)
  const applied = useRef(0)

  const takeTicket = useCallback((): number => {
    issued.current += 1
    return issued.current
  }, [])

  const owns = useCallback(
    (ticket: number): boolean => ticket >= floor.current && ticket > applied.current,
    [],
  )

  // Invalidate every read started so far (reload, expiry, sign-out, unmount).
  const invalidate = useCallback(() => {
    floor.current = issued.current + 1
  }, [])

  const publish = useCallback(
    (ticket: number, next: SessionBootstrapState): boolean => {
      if (!owns(ticket)) {
        return false
      }
      applied.current = ticket
      setState(next)
      return true
    },
    [owns],
  )

  const reload = useCallback(() => {
    invalidate()

    setState({
      status: "loading",
    })

    setRequestVersion((currentVersion) => currentVersion + 1)
  }, [invalidate])

  // Argument-free refreshes (eligibility after a confirmed write, or after a party-scoped
  // not-found) share one request while it is still the owner of its result, so several callers
  // cause one read. A request that has been invalidated or overtaken is never joined: the next
  // caller starts a fresh one. A request clears only its own entry when it settles.
  const inFlight = useRef<{ ticket: number; promise: Promise<boolean> } | null>(null)

  const refresh = useCallback(
    (signal?: AbortSignal): Promise<boolean> => {
      if (signal === undefined && inFlight.current !== null && owns(inFlight.current.ticket)) {
        return inFlight.current.promise
      }

      const ticket = takeTicket()

      const run = async (): Promise<boolean> => {
        let bootstrap: SessionBootstrap | null
        try {
          bootstrap = await fetchSessionBootstrap(signal)
        } catch (cause) {
          // An obsolete failure is not news: it is ignored, not thrown.
          if (!owns(ticket)) {
            return false
          }
          throw cause
        }

        if (signal?.aborted) {
          return false
        }

        if (bootstrap === null) {
          publish(ticket, { status: "unauthenticated" })
          return false
        }

        return publish(ticket, { status: "authenticated", bootstrap })
      }

      const promise = run()

      if (signal === undefined) {
        const entry = { ticket, promise }
        inFlight.current = entry
        const clear = () => {
          if (inFlight.current === entry) {
            inFlight.current = null
          }
        }
        promise.then(clear, clear)
      }

      return promise
    },
    [owns, publish, takeTicket],
  )

  useEffect(() => {
    const controller = new AbortController()
    const ticket = takeTicket()

    void fetchSessionBootstrap(controller.signal)
      .then((bootstrap) => {
        if (controller.signal.aborted) {
          return
        }

        if (bootstrap === null) {
          publish(ticket, {
            status: "unauthenticated",
          })
          return
        }

        publish(ticket, {
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

        publish(ticket, {
          status: "error",
          error,
        })
      })

    return () => {
      controller.abort()
    }
  }, [requestVersion, takeTicket, publish])

  // Nothing started before the hook goes away may publish afterwards.
  useEffect(() => {
    return () => {
      invalidate()
    }
  }, [invalidate])

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
        // The session is over: no read that started before now may bring it back.
        invalidate()
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
  }, [authenticatedBootstrap, invalidate])

  return {
    state,
    reload,
    refresh,
  }
}
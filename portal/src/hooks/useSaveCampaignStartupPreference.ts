import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react"
import {
    setCampaignStartupPreference,
    UserPreferenceRequestError,
} from "../api/userPreferences"
import { useSession } from "../context/SessionContext"

export type SaveCampaignStartupStatus =
    | { kind: "idle" }
    | { kind: "pending" }
    | { kind: "success" }
    // 404: the chosen campaign is no longer accessible to the caller.
    | { kind: "unavailable" }
    // 401/403: session expired or the request was refused.
    | { kind: "denied" }
    // The PUT was CONFIRMED (the server accepted it) but the authoritative bootstrap was not
    // applied afterwards - the re-read failed, was superseded by a newer session read, or the
    // session ended - so the new value is not yet shown. Never "denied": the save happened.
    | { kind: "unconfirmed" }
    | { kind: "error" }

export interface UseSaveCampaignStartupPreferenceResult {
    status: SaveCampaignStartupStatus
    // `null` clears the fixed choice ("Resume my last visited campaign").
    save: (preferredCampaignId: string | null) => void
    // Clears the last request's transient status. It never ends an outstanding episode.
    reset: () => void
    // A confirmed save whose read-back was not applied is waiting for the shared session to show its value
    // for the same user. It ends only on confirmation, a newer confirmed save, an account change or unmount.
    outstanding: boolean
    // That episode was confirmed by a later read while another request's status (a rejected newer save) is
    // still showing, so `status` could not carry it.
    confirmed: boolean
    // Reads the session again in place for the outstanding episode (never a reload, never a PUT).
    check: () => void
    checking: boolean
    // The last check for the outstanding episode failed.
    checkFailed: boolean
}

const idleStatus: SaveCampaignStartupStatus = { kind: "idle" }

// A confirmed PUT whose authoritative read-back was not applied: `submitted` is what was sent, for the user
// who sent it. Each episode is its own object, so a late callback from an ended one cannot touch a newer one.
interface Episode {
    id: number
    userId: string
    submitted: string | null
    // The bootstrap the session held when this save was sent. Only a bootstrap published after it can show
    // the save: the one that was there before the PUT says nothing about it.
    before: unknown
}

interface Check {
    episodeId: number
    phase: "checking" | "failed"
}

export function useSaveCampaignStartupPreference(): UseSaveCampaignStartupPreferenceResult {
    const { state: sessionState, refresh } = useSession()
    const controllerRef = useRef<AbortController | null>(null)
    const [status, setStatus] = useState<SaveCampaignStartupStatus>(idleStatus)
    const [episode, setEpisode] = useState<Episode | null>(null)
    const [confirmed, setConfirmed] = useState(false)
    const [check, setCheck] = useState<Check | null>(null)
    const nextId = useRef(0)
    // The episode that is outstanding now, readable by callbacks that outlive a render.
    const live = useRef<Episode | null>(null)
    const checkController = useRef<AbortController | null>(null)
    useLayoutEffect(() => {
        live.current = episode
    })

    useEffect(() => {
        return () => {
            controllerRef.current?.abort()
        }
    }, [])
    // A check belongs to its episode: it is aborted when the episode ends (or the page is left).
    useEffect(() => {
        return () => {
            checkController.current?.abort()
            checkController.current = null
        }
    }, [episode])

    // Reconciliation, from the shared session state and nothing else: another account ends the episode, and the
    // same account showing the submitted value confirms it (null equals null). Anything else leaves it alone.
    if (episode !== null && sessionState.status === "authenticated") {
        const { user, campaign_preferences: preferences } = sessionState.bootstrap
        if (user.user_id !== episode.userId) {
            setEpisode(null)
            setCheck(null)
            setConfirmed(false)
            setStatus(idleStatus)
        } else if (
            sessionState.bootstrap !== episode.before &&
            preferences.preferred_campaign_id === episode.submitted
        ) {
            setEpisode(null)
            setCheck(null)
            if (status.kind === "idle" || status.kind === "unconfirmed") {
                setStatus({ kind: "success" })
            } else if (status.kind !== "pending" && status.kind !== "success") {
                setConfirmed(true)
            }
        }
    }

    const save = useCallback(
        (preferredCampaignId: string | null) => {
            if (status.kind === "pending") {
                return
            }
            if (sessionState.status !== "authenticated") {
                return
            }
            const userId = sessionState.bootstrap.user.user_id
            const before: unknown = sessionState.bootstrap

            const controller = new AbortController()
            controllerRef.current = controller
            setStatus({ kind: "pending" })
            setConfirmed(false)

            void setCampaignStartupPreference(
                preferredCampaignId,
                sessionState.bootstrap.csrf_token,
                controller.signal,
            )
                .then(async () => {
                    if (controller.signal.aborted) {
                        return
                    }
                    // A newer confirmed save ends the earlier episode; this save's own outcome governs now.
                    live.current = null
                    setEpisode(null)
                    setCheck(null)
                    // Success is reported only once the shared session
                    // bootstrap holds the server's own view of the saved
                    // preference; nothing local is treated as authoritative.
                    const unconfirmed = () => {
                        const next: Episode = { id: ++nextId.current, userId, submitted: preferredCampaignId, before }
                        live.current = next
                        setEpisode(next)
                        setStatus({ kind: "unconfirmed" })
                    }
                    let applied: boolean
                    try {
                        applied = await refresh(controller.signal)
                    } catch {
                        if (!controller.signal.aborted) {
                            unconfirmed()
                        }
                        return
                    }
                    if (controller.signal.aborted) {
                        return
                    }
                    // `false` is "not applied" (superseded, or the session ended and the sign-in
                    // boundary takes over), not a refusal of the save that was just confirmed. The
                    // PUT is never repeated to repair the read.
                    if (applied) {
                        setStatus({ kind: "success" })
                    } else {
                        unconfirmed()
                    }
                })
                .catch((cause: unknown) => {
                    if (controller.signal.aborted) {
                        return
                    }
                    if (cause instanceof UserPreferenceRequestError) {
                        if (cause.status === 404) {
                            setStatus({ kind: "unavailable" })
                            return
                        }
                        if (cause.status === 401 || cause.status === 403) {
                            setStatus({ kind: "denied" })
                            return
                        }
                    }
                    setStatus({ kind: "error" })
                })
        },
        [sessionState, refresh, status.kind],
    )

    const reset = useCallback(() => {
        setStatus(idleStatus)
        setConfirmed(false)
    }, [])

    // Reads the session again in place for the outstanding episode. The shared bootstrap is what confirms it
    // (above); a failure is reported, "not applied" waits for what was published.
    const checkSession = useCallback(() => {
        const target = live.current
        if (target === null || checkController.current !== null) {
            return
        }
        const controller = new AbortController()
        checkController.current = controller
        setCheck({ episodeId: target.id, phase: "checking" })
        const finish = (failed: boolean) => {
            if (controller.signal.aborted || live.current?.id !== target.id) {
                return
            }
            checkController.current = null
            setCheck(failed ? { episodeId: target.id, phase: "failed" } : null)
        }
        refresh(controller.signal).then(
            () => finish(false),
            () => finish(true),
        )
    }, [refresh])

    const current = episode !== null && check?.episodeId === episode.id ? check : null
    return {
        status,
        save,
        reset,
        outstanding: episode !== null,
        confirmed,
        check: checkSession,
        checking: current?.phase === "checking",
        checkFailed: current?.phase === "failed",
    }
}

import { useCallback, useEffect, useLayoutEffect, useRef } from "react"
import { useBlocker } from "react-router"
import type { Blocker } from "react-router"
import { anyNavigationHold, holdNavigationQuestion, isGuardedTransition, registerPageGuard } from "./navigationHolds"

export interface UnsavedChangesGuard {
    // True while an in-app navigation is held waiting for the user's decision.
    blocked: boolean
    // Leave anyway: discards the edits and completes the held navigation.
    discard: () => void
    // Stay on the form.
    stay: () => void
    // Call immediately before a deliberate navigation after a successful save,
    // so the save's own redirect is not mistaken for abandoning the form.
    release: () => void
}

// Protects entered-but-unsaved form input (docs/UI_DESIGN.md §5.11).
//
// - In-app navigation that changes the path is held by react-router's blocker
//   (this needs a data router, which main.tsx provides); the page renders a
//   ConfirmDialog from `blocked`/`discard`/`stay`.
// - Closing or reloading the tab sets a `beforeunload` prompt while dirty.
// - A change of character perspective keeps the path but is a context
//   transition: it is held the same way (see isGuardedTransition), including
//   Back/Forward between same-path entries recorded under different perspectives.
// - A query-string-only change (the setup wizard moving between steps) is not
//   a departure and is never blocked.
//
// Entered values are deliberately never written to browser storage, so an
// expired session loses them; that is an accepted limitation, not an oversight.
export function useUnsavedChangesGuard(isDirty: boolean): UnsavedChangesGuard {
    const dirtyRef = useRef(isDirty)

    useEffect(() => {
        dirtyRef.current = isDirty
    }, [isDirty])

    // Counted so a component with state of its own to protect (see navigationHolds) adds to this guard's
    // question instead of installing a second blocker; its holds block here too.
    useEffect(() => registerPageGuard(), [])

    // When the page goes away with its question still open (permission loss removes it), the held
    // navigation is cancelled through the blocker's own reset, which also tells the router's
    // subscribers that the blocker is gone; the departure is never approved. Declared before
    // useBlocker so it runs before that hook's cleanup deletes the blocker.
    const blockerRef = useRef<Blocker | null>(null)
    // Set when the person chose to leave: the blocker then proceeds, and is not reset on the way out.
    const leaving = useRef(false)
    useEffect(
        () => () => {
            if (!leaving.current && blockerRef.current?.state === "blocked") blockerRef.current.reset()
        },
        [],
    )

    const blocker = useBlocker(
        (transition) => (dirtyRef.current || anyNavigationHold()) && isGuardedTransition(transition),
    )

    useLayoutEffect(() => {
        blockerRef.current = blocker
    })

    // While the question is on screen, modals of components that hold state (a picker's dialog) step aside.
    const asking = blocker.state === "blocked"
    useLayoutEffect(() => (asking ? holdNavigationQuestion() : undefined), [asking])

    useEffect(() => {
        if (!isDirty) {
            return
        }
        function handleBeforeUnload(event: BeforeUnloadEvent): void {
            if (dirtyRef.current) {
                event.preventDefault()
            }
        }
        window.addEventListener("beforeunload", handleBeforeUnload)
        return () => {
            window.removeEventListener("beforeunload", handleBeforeUnload)
        }
    }, [isDirty])

    const release = useCallback(() => {
        dirtyRef.current = false
    }, [])

    const discard = useCallback(() => {
        dirtyRef.current = false
        if (blocker.state === "blocked") {
            leaving.current = true
            blocker.proceed()
        }
    }, [blocker])

    const stay = useCallback(() => {
        if (blocker.state === "blocked") {
            blocker.reset()
        }
    }, [blocker])

    return { blocked: blocker.state === "blocked", discard, stay, release }
}

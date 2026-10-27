import { useCallback, useLayoutEffect, useRef } from "react"
import type { RefObject } from "react"

// Bounded focus recovery for a retry button (docs/UI_DESIGN.md §5.11). A read that failed offers
// "Try again"; when the person activated it and the read then succeeds, the button is replaced by
// the content it was guarding, which would drop focus to the page. The button hands focus to the
// heading of the page it was in, but only when all of these still hold: the person used the retry
// control, it still owned focus when it was removed, and focus then has nowhere else to be (nothing
// else took it, as a navigation or a background refresh would). A failed retry keeps the same
// button, so focus never moves; a re-render, a refresh or a button nobody used never moves it.
export function useRetryFocus<E extends HTMLElement>(): {
    ref: RefObject<E | null>
    // Call from the click handler.
    used: () => void
    // Call from the blur handler: moving away cancels the recovery.
    left: () => void
} {
    const ref = useRef<E>(null)
    const active = useRef(false)
    const element = useRef<E | null>(null)

    useLayoutEffect(() => {
        element.current = ref.current
        return () => {
            const button = element.current
            // Layout cleanup runs before the node leaves the document, so focus is still readable.
            if (!active.current || button === null || document.activeElement !== button) {
                return
            }
            const heading = button
                .closest<HTMLElement>(".authoring-page, section, main")
                ?.querySelector<HTMLElement>("h1")
            if (heading === null || heading === undefined) {
                return
            }
            setTimeout(() => {
                const focused = document.activeElement
                if (heading.isConnected && (focused === null || focused === document.body)) {
                    heading.focus()
                }
            }, 0)
        }
    }, [])

    const used = useCallback(() => {
        active.current = true
    }, [])
    const left = useCallback(() => {
        active.current = false
    }, [])
    return { ref, used, left }
}

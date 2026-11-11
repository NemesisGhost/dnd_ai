import { useCallback, useLayoutEffect, useRef } from "react"
import type { RefObject } from "react"

// Bounded focus recovery for a retry button (docs/UI_DESIGN.md §5.11). A read that failed offers
// "Try again"; when the person activated it and the read then succeeds, the button is replaced by
// the content it was guarding, which would drop focus to the page. The button hands focus to the
// heading of the page it was in, but only when all of these still hold: the person used the retry
// control, it still owned focus when it was removed, and focus then has nowhere else to be (nothing
// else took it, as a navigation or a background refresh would). A failed retry keeps the same
// button, so focus never moves; a re-render, a refresh or a button nobody used never moves it.
//
// A retry that sits inside a group of controls rather than a page may pass `resolveTarget`: it receives the
// `<section>` that held the button and returns where focus goes instead of the page heading (the Infobox
// passes "that level's select when usable, otherwise its reason text"). It runs after the commit, so it
// sees what replaced the button.
export function useRetryFocus<E extends HTMLElement>(
    resolveTarget?: (section: HTMLElement) => HTMLElement | null,
): {
    ref: RefObject<E | null>
    // Call from the click handler.
    used: () => void
    // Call from the blur handler: moving away cancels the recovery.
    left: () => void
} {
    const ref = useRef<E>(null)
    const active = useRef(false)
    const element = useRef<E | null>(null)
    const resolver = useRef(resolveTarget)
    useLayoutEffect(() => {
        resolver.current = resolveTarget
    })

    useLayoutEffect(() => {
        element.current = ref.current
        return () => {
            const button = element.current
            // Layout cleanup runs before the node leaves the document, so focus is still readable.
            if (!active.current || button === null || document.activeElement !== button) {
                return
            }
            const resolve = resolver.current
            const section = button.closest<HTMLElement>("section")
            const heading = resolve
                ? null
                : button
                      .closest<HTMLElement>(".authoring-page, section, main")
                      ?.querySelector<HTMLElement>("h1")
            if (resolve ? section === null : heading === null || heading === undefined) {
                return
            }
            setTimeout(() => {
                const focused = document.activeElement
                if (focused !== null && focused !== document.body) {
                    return
                }
                const target = resolve ? (section?.isConnected ? resolve(section) : null) : heading
                if (target?.isConnected) {
                    target.focus()
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

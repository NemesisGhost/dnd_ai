import { useCallback, useRef, useState } from "react"
import type { RefObject } from "react"

// Open state for the narrow-viewport sidebar drawer. Shared between the
// header's toggle button and the sidebar through props from
// AuthenticatedAppLayout (no context, no state library). Local state on
// purpose: the drawer is always closed after a remount.
export interface NavigationDrawerControl {
    open: boolean
    toggle: () => void
    close: () => void
    // Close and return focus to the header toggle (Escape/backdrop).
    closeAndFocusToggle: () => void
}

export interface NavigationDrawer {
    control: NavigationDrawerControl
    // Kept beside (not inside) the control so render code never reads a
    // ref through the control object.
    toggleRef: RefObject<HTMLButtonElement | null>
}

export function useNavigationDrawer(): NavigationDrawer {
    const [open, setOpen] = useState(false)
    const toggleRef = useRef<HTMLButtonElement>(null)

    const toggle = useCallback(() => setOpen((current) => !current), [])
    const close = useCallback(() => setOpen(false), [])
    const closeAndFocusToggle = useCallback(() => {
        setOpen(false)
        toggleRef.current?.focus()
    }, [])

    return {
        control: { open, toggle, close, closeAndFocusToggle },
        toggleRef,
    }
}

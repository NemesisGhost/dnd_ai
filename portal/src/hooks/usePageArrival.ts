import { useEffect, useRef } from "react"
import type { RefObject } from "react"
import { useLocation } from "react-router"
import { readAnnounceMessage, useAnnounce } from "../components/authoring/announcer"

// Focus and announcement on arrival (docs/UI_DESIGN.md §5.11). Once a page's
// authoritative data has loaded (`ready`), focus moves to its <h1> and, if the
// navigation carried a success message, it is announced — after the fetch that
// proves the write, so the message survives the refetch. Runs once per
// navigation (keyed by location.key).
export function usePageArrival(ready: boolean): RefObject<HTMLHeadingElement | null> {
    const headingRef = useRef<HTMLHeadingElement>(null)
    const location = useLocation()
    const announce = useAnnounce()
    const arrivedFor = useRef<string | null>(null)

    useEffect(() => {
        if (!ready || arrivedFor.current === location.key) {
            return
        }
        arrivedFor.current = location.key
        headingRef.current?.focus()
        const message = readAnnounceMessage(location.state)
        if (message !== null) {
            announce(message)
        }
    }, [ready, location.key, location.state, announce])

    return headingRef
}

import { useEffect, useRef } from "react"
import type { RefObject } from "react"
import { useLocation } from "react-router"
import { readAnnounceMessage, useAnnounce } from "../components/authoring/announcer"

// Focus and announcement on arrival (docs/UI_DESIGN.md §5.11). Once a page's
// authoritative data has loaded (`ready`), focus moves to its <h1> and, if the
// navigation carried a success message, it is announced — after the fetch that
// proves the write, so the message survives the refetch. Runs once per
// navigation (keyed by location.key), or, for a page whose own links only change the query (a
// staged workspace that moves focus to its section heading), once per path (`keyBy: "path"`).
export function usePageArrival(
    ready: boolean,
    keyBy: "navigation" | "path" = "navigation",
): RefObject<HTMLHeadingElement | null> {
    const headingRef = useRef<HTMLHeadingElement>(null)
    const location = useLocation()
    const announce = useAnnounce()
    const arrivedFor = useRef<string | null>(null)

    useEffect(() => {
        const arrival = keyBy === "path" ? location.pathname : location.key
        if (!ready || arrivedFor.current === arrival) {
            return
        }
        arrivedFor.current = arrival
        headingRef.current?.focus()
        const message = readAnnounceMessage(location.state)
        if (message !== null) {
            announce(message)
        }
    }, [ready, keyBy, location.key, location.pathname, location.state, announce])

    return headingRef
}

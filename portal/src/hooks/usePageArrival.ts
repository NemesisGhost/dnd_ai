import { useEffect, useRef } from "react"
import type { RefObject } from "react"
import { NavigationType, useLocation, useNavigationType } from "react-router"
import { readAnnounceMessage, useAnnounce } from "../components/authoring/announcer"
import { entryRoot, stampRoot } from "../navigation/entryStamp"

// Focus and announcement on arrival (docs/UI_DESIGN.md §5.11). Once a page's
// authoritative data has loaded (`ready`), focus moves to its <h1> and, if the
// navigation carried a success message, it is announced — after the fetch that
// proves the write, so the message survives the refetch. Runs once per
// navigation (keyed by location.key), or, for a page whose own links only change the query (a
// staged workspace that moves focus to its section heading), once per path (`keyBy: "path"`).
//
// A REPLACE of the entry already arrived at (same path and query) that has nothing to announce only
// restates its state: the context stamp and task clean-up the selected-context owners write in the
// background. A REPLACE that carries a message is that stamp only when the stamp writer says so: its state
// is an object the writer marked (navigation/entryStamp.ts) as a stamp of the chain this page arrived at.
// Such a restating is not an arrival, so it moves focus nowhere, repeats no announcement, and an open
// menu or a field in use keeps it. Any other replacement of the same address, whatever its state or
// message text repeats, is a new operation and gets its own feedback: resemblance is never the evidence.
export function usePageArrival(
    ready: boolean,
    keyBy: "navigation" | "path" = "navigation",
): RefObject<HTMLHeadingElement | null> {
    const headingRef = useRef<HTMLHeadingElement>(null)
    const location = useLocation()
    const navigationType = useNavigationType()
    const announce = useAnnounce()
    const arrivedFor = useRef<string | null>(null)
    const arrivedAt = useRef<string | null>(null)
    // The root of the chain of entries this page arrived at (the entry itself, or what its stamps restate).
    const arrivedRoot = useRef<string | null>(null)

    useEffect(() => {
        const arrival = keyBy === "path" ? location.pathname : location.key
        if (!ready || arrivedFor.current === arrival) {
            return
        }
        const address = `${location.pathname}${location.search}`
        const message = readAnnounceMessage(location.state)
        if (
            keyBy === "navigation" &&
            arrivedFor.current !== null &&
            navigationType === NavigationType.Replace &&
            arrivedAt.current === address &&
            (message === null || (arrivedRoot.current !== null && stampRoot(location.state) === arrivedRoot.current))
        ) {
            arrivedFor.current = arrival
            return
        }
        arrivedFor.current = arrival
        arrivedAt.current = address
        arrivedRoot.current = entryRoot({ key: location.key, state: location.state })
        headingRef.current?.focus()
        if (message !== null) {
            announce(message)
        }
    }, [ready, keyBy, navigationType, location.key, location.pathname, location.search, location.hash, location.state, announce])

    return headingRef
}

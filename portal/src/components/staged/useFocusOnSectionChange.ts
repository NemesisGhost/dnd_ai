import { useEffect, useRef } from "react"

// Moves focus when the section changes after arrival (a link, Back or Forward), so a keyboard or
// screen reader user lands on the new content. Arrival itself never moves focus, and neither does
// a section that changed without the person asking.
//
// - `ready: false` holds the hook back; the section the page settles on is the arrival.
// - `keep(previous)` says whether the section just left is still one the person could be on. A
//   section withdrawn from under them (a refused command, a lost role) falls back to another
//   without a request; focus then stays where it is, as the panel explaining the loss takes it.
// - `focus(section)` moves focus to that section's content.
export function useFocusOnSectionChange<K extends string>(
    section: K,
    focus: (section: K) => void,
    { ready = true, keep }: { ready?: boolean; keep?: (previous: K) => boolean } = {},
): void {
    const last = useRef<K | null>(ready ? section : null)
    const latest = useRef({ focus, keep })
    useEffect(() => {
        latest.current = { focus, keep }
    })
    useEffect(() => {
        if (!ready) return
        if (last.current === null) {
            last.current = section
            return
        }
        if (last.current === section) return
        const previous = last.current
        last.current = section
        if (latest.current.keep?.(previous) ?? true) latest.current.focus(section)
    }, [ready, section])
}

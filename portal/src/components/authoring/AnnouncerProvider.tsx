import { useCallback, useMemo, useRef, useState } from "react"
import type { PropsWithChildren } from "react"
import { AnnouncerContext } from "./announcer"

// Renders the one polite live region (aria-live, deliberately without
// role="status" so it never collides with a page's own status region) and provides `announce`. The message is
// cleared and re-set across two states so announcing the same text twice in a
// row is still read by assistive technology.
export function AnnouncerProvider({ children }: PropsWithChildren) {
    const [message, setMessage] = useState("")
    const [toggle, setToggle] = useState(false)

    // Which announcement the region shows now; every announce makes a newer one.
    const latest = useRef(0)

    const announce = useCallback((next: string) => {
        latest.current += 1
        setMessage(next)
        setToggle((current) => !current)
    }, [])

    const announceOwned = useCallback(
        (next: string) => {
            announce(next)
            const mine = latest.current
            return () => {
                if (latest.current !== mine) return
                latest.current += 1
                setMessage("")
            }
        },
        [announce],
    )

    const value = useMemo(() => ({ announce, announceOwned }), [announce, announceOwned])

    return (
        <AnnouncerContext.Provider value={value}>
            {children}
            <div
                className="visually-hidden"
                aria-live="polite"
                aria-atomic="true"
                data-testid="authoring-announcer"
            >
                {/* Two alternating nodes force a re-announcement of identical text. */}
                {toggle ? <span>{message}</span> : <p>{message}</p>}
            </div>
        </AnnouncerContext.Provider>
    )
}

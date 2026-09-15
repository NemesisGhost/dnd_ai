import {
    useEffect,
    useState,
} from "react"

// How long a refresh must run before this indicator appears, so a fast
// reload doesn't just flash it on and off. Mounted only while refreshing
// (see WorldEntityList), so unmounting always clears its own timer.
const UPDATING_INDICATOR_DELAY_MS = 200

export function UpdatingIndicator() {
    const [visible, setVisible] = useState(false)

    useEffect(() => {
        const timeoutId = window.setTimeout(() => {
            setVisible(true)
        }, UPDATING_INDICATOR_DELAY_MS)

        return () => window.clearTimeout(timeoutId)
    }, [])

    if (!visible) {
        return null
    }

    return (
        <p
            className="world-entity-list__status"
            role="status"
        >
            Updating results…
        </p>
    )
}

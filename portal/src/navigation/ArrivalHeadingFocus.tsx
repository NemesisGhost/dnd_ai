import { useEffect } from "react"
import { useSelectionArrival } from "./selectionArrival"

// Rendered by a destination where it has stopped loading and shows its heading (a boundary's settled
// branch, a page that needs no read). Mounting is the signal that the page actually rendered: it asks
// the accepted selection arrival, if there is one for the location it renders under, to focus the
// heading. Anything else (no selection arrival, a superseded one, another location) does nothing.
export function ArrivalHeadingFocus() {
    const current = useSelectionArrival()
    useEffect(() => {
        current?.arrival.focusHeading(current.locationKey)
    }, [current])
    return null
}

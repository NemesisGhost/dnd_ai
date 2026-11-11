import { useContext, useEffect } from "react"
import { LinkArrivalContext, focusLinkArrival, useSelectionArrival } from "./selectionArrival"

// Rendered by a destination where it has stopped loading and shows its heading (a boundary's settled
// branch, a page that needs no read). Mounting is the signal that the page actually rendered. With an
// accepted selection arrival for the location it renders under, it asks that arrival to focus the
// heading. With none, a link arrival (an entry created by a PUSH: a Navbar link, a breadcrumb, a Leave that
// completes the held navigation, or only its stamp-only restatements) gets the same heading focus once.
// A reload and Back/Forward are not arrivals and move nothing.
export function ArrivalHeadingFocus() {
    const current = useSelectionArrival()
    const entry = useContext(LinkArrivalContext)
    useEffect(() => {
        if (current !== null) {
            current.arrival.focusHeading(current.locationKey)
        } else if (entry !== null) {
            focusLinkArrival(entry)
        }
    }, [current, entry])
    return null
}

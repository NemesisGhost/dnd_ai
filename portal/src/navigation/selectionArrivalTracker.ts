import type { DataRouter } from "react-router"
import { SelectionArrival } from "./selectionArrival"
import { readSelectionChange } from "./selectionChange"

// Which accepted selection arrival is in force, judged from the router's own committed locations rather
// than from what React happened to render: React may batch the commit of an accepted location with the
// stamp the selected-context owners write on it a moment later, and a choice must not be lost (or
// repeated) because of that.
//
//   PUSH with a selection   a choice the router accepted: a new arrival, noting the campaign that was
//                           selected before anything was committed for it.
//   REPLACE, same address   a stamp or clean-up of the entry already arrived at: the arrival stays.
//   anything else           a link, Back/Forward, a reload, another REPLACE: no arrival (a superseded
//                           one is dropped, so it is never announced or focused late).
//
// Pure of React; the router and the selected campaign are read through the arguments.

type RouterState = DataRouter["state"]

export interface ArrivalTracker {
    getSnapshot: () => SelectionArrival | null
    subscribe: (listener: () => void) => () => void
}

export function createArrivalTracker(
    router: Pick<DataRouter, "state" | "subscribe">,
    selectedCampaign: () => string | null,
): ArrivalTracker {
    let lastKey: string | null = null
    let current: SelectionArrival | null = null

    // The arrival a committed location leaves in force. Idempotent for a location already seen.
    const next = (state: RouterState): SelectionArrival | null => {
        const { location, historyAction } = state
        if (location.key === lastKey) return current
        lastKey = location.key
        if (historyAction === "REPLACE") {
            if (current === null || current.path !== location.pathname) return null
            current.adopt(location.key)
            return current
        }
        const change = historyAction === "PUSH" ? readSelectionChange(location.state) : null
        return change === null ? null : new SelectionArrival(change, location.key, location.pathname, selectedCampaign())
    }

    // The location the tracker is created under counts too: a campaign scope change remounts the shell in
    // the very commit that brings the accepted location.
    current = next(router.state)

    return {
        getSnapshot: () => current,
        subscribe(listener) {
            const observe = (state: RouterState): void => {
                const arrival = next(state)
                if (arrival !== current) {
                    current = arrival
                    listener()
                }
            }
            const unsubscribe = router.subscribe(observe)
            // Anything committed between creation and subscription.
            observe(router.state)
            return unsubscribe
        },
    }
}

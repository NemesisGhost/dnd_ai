import { useCallback, useContext, useEffect, useLayoutEffect, useState } from "react"
import { IDLE_BLOCKER, UNSAFE_DataRouterContext, UNSAFE_DataRouterStateContext } from "react-router"
import type { Blocker, BlockerFunction } from "react-router"

// A data-router blocker that is registered in the commit that first renders it.
//
// react-router's own `useBlocker` (8.3.0) takes two passive-effect passes to register: its first effect only
// chooses the blocker's key and sets state, and a second effect, after that state update has rendered and
// committed, calls `router.getBlocker`. A navigation attempted after the first commit but before the second
// effect (a click straight after a one-time link appears, a navigation from a sibling's layout effect) is not
// held at all. That is the window this hook closes:
//
// - The key is chosen when the component first renders (no state update is needed).
// - The blocker function is registered in a layout effect, which runs synchronously inside the commit that
//   put the component on screen and before the browser can deliver another event or run any other task.
//   The function is re-registered in the same phase whenever its identity changes, which never resets a
//   blocked state (`getBlocker` only stores the function).
// - The blocker is deleted in a passive cleanup, as `useBlocker` did, so a caller's own earlier passive cleanup
//   (the guard's reset of an open question) still runs while the blocker exists.
//
// Behavior otherwise follows `useBlocker`: it requires a data router (the same error message), strips a
// non-root basename before the predicate sees a location, and returns IDLE until the router reports a state.

const DATA_ROUTER_MESSAGE =
    "useBlocker must be used within a data router.  See https://reactrouter.com/en/main/routers/picking-a-router."

let nextKey = 0

function stripBasename(pathname: string, basename: string): string {
    if (basename === "/") return pathname
    if (!pathname.toLowerCase().startsWith(basename.toLowerCase())) return pathname
    return pathname.slice(basename.length) || "/"
}

export function useCommittedBlocker(shouldBlock: BlockerFunction): Blocker {
    const dataRouter = useContext(UNSAFE_DataRouterContext)
    const routerState = useContext(UNSAFE_DataRouterStateContext)
    if (dataRouter === null || dataRouter === undefined || routerState === null || routerState === undefined) {
        throw new Error(DATA_ROUTER_MESSAGE)
    }
    const { router, basename } = dataRouter
    const [key] = useState(() => `committed-blocker-${++nextKey}`)

    const blockerFunction = useCallback<BlockerFunction>(
        (args) => {
            if (basename === "/") return shouldBlock(args)
            const { currentLocation, nextLocation, historyAction } = args
            return shouldBlock({
                currentLocation: { ...currentLocation, pathname: stripBasename(currentLocation.pathname, basename) },
                nextLocation: { ...nextLocation, pathname: stripBasename(nextLocation.pathname, basename) },
                historyAction,
            })
        },
        [basename, shouldBlock],
    )

    useLayoutEffect(() => {
        router.getBlocker(key, blockerFunction)
    }, [router, key, blockerFunction])

    useEffect(() => () => router.deleteBlocker(key), [router, key])

    return routerState.blockers.get(key) ?? IDLE_BLOCKER
}

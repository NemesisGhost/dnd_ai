import { createContext, useCallback, useContext } from "react"
import { useSession } from "../context/SessionContext"

// What an Access write may have changed for the CALLER. A write can change the caller's own authority
// (their capabilities, roles, character perspectives, or membership), which must be re-derived from the
// server, never inferred. The Access page names the write's subject: a control inside another member's
// card, or a group the caller is not in, cannot change the caller's own bootstrap by itself. The default,
// with no scope around a control, is the conservative one: the write may affect the caller.
export interface AccessWriteScope {
    affectsCaller: boolean
}

export const AccessWriteScopeContext = createContext<AccessWriteScope>({ affectsCaller: true })

// Called by an Access mutation hook once its write is confirmed, in place of reloading the session.
//
//   - The write may affect the caller: the session is reloaded exactly as before (the page is replaced by
//     "Loading portal" and mounts again from the fresh bootstrap). Fail closed.
//   - It cannot: the authoritative bootstrap is read again IN PLACE (`refresh`), so the Access page stays
//     mounted and its open cards and explanations, and the page's status-line announcement, continue.
//
// `refresh()` resolving is not the same as "fresh state was applied": it resolves `false` when the read was
// not published (the session turned out to be unauthenticated, or a reload, an expiry or a newer read took
// ownership of the result), and it rejects when the read failed. Neither is treated as success. Every such
// outcome falls back to the full `reload()`, which is the pre-existing behavior.
//
// The read is made with a signal of its own so that it can never join a read that was already in flight:
// a joined read might have started before this write committed, and would then report an older state.
// The signal is never aborted, so leaving the page does not cancel the confirmation of a committed write.
export function useAccessWriteCompletion(): () => void {
    const { refresh, reload } = useSession()
    const { affectsCaller } = useContext(AccessWriteScopeContext)

    return useCallback(() => {
        if (affectsCaller) {
            reload()
            return
        }
        let read: Promise<boolean>
        try {
            read = Promise.resolve(refresh(new AbortController().signal))
        } catch {
            reload()
            return
        }
        void read.then(
            (applied) => {
                if (applied !== true) {
                    reload()
                }
            },
            () => reload(),
        )
    }, [affectsCaller, refresh, reload])
}

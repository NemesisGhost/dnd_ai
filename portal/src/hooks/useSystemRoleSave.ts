import { useCallback, useEffect, useRef, useState } from "react"
import { fetchPlatformAccounts, PlatformAccountsRequestError } from "../api/platformAccounts"
import { assignSystemRole, revokeSystemRole } from "../api/systemRoles"
import { useSession } from "../context/SessionContext"
import type { PlatformAccount } from "../types/platformAccounts"
import type { SystemRoleCode } from "../utils/systemAccess"
import { bootstrapRefreshOutcome } from "../utils/refreshOutcome"
import { confirmFromRoles, draftAfterSave } from "../utils/systemRoleStaging"
import type { LedgerStep, StagedChange } from "../utils/systemRoleStaging"

// Saving one account's staged system-role changes. The server has no multi-role or atomic operation, so a save is
// a sequence of separate requests, sent one at a time, each with its own outcome; partial success is a normal,
// reported result and nothing here claims the changes were applied together. Nothing is sent without a Save
// press, nothing is ever retried or replayed automatically, and a retry is only a later Save of what still
// differs after the account's roles were read again.

export type SavePhase =
    | "idle"
    | "saving"
    // The account's current roles are being read to settle the ledger.
    | "reconciling"
    // That read did not settle (failed, or the account was not in the answer): Save stays off until it does.
    | "check_failed"
    // Settled: the ledger is final until the next Save.
    | "done"
    // The read was refused as not found: the signed-in account may have lost access.
    | "access_unknown"

export interface SaveState {
    phase: SavePhase
    userId: string | null
    ledger: LedgerStep[]
    // True while a read the person asked for (Check current roles) is under way.
    checking: boolean
}

const IDLE: SaveState = { phase: "idle", userId: null, ledger: [], checking: false }

export const LAST_ADMIN_TEXT =
    "This is the platform's only active administrator and cannot lose the Administrator role."
export const GRANT_DISABLED_TEXT = "Granting Administrator is done by the operator script on this deployment."
export const PERMISSION_TEXT = "You do not have permission to make this change."
const REFUSED_TEXT = "This change was refused."

interface SaveContext {
    account: PlatformAccount
    ownAccount: boolean
}

interface UseSystemRoleSaveOptions {
    csrfToken: string
    selfUserId: string
    // The account's roles as the server now reports them, and the draft that is still outstanding. Called only
    // for the account the save was for, and only while this hook is still current.
    onReconciled: (account: PlatformAccount, draft: SystemRoleCode[]) => void
}

export interface UseSystemRoleSaveResult {
    state: SaveState
    save: (account: PlatformAccount, changes: readonly StagedChange[]) => void
    // Repeats only the read of the account's roles (one GET per press, never a write).
    checkAgain: () => void
    // Forgets the result and stops anything outstanding (nothing further is sent).
    clear: () => void
    // True when the signed-in account's own Administrator removal was saved.
    ownAdminRemoved: boolean
}

type StepAnswer =
    | { kind: "saved"; strandedWorlds: number }
    | { kind: "already" }
    | { kind: "refused"; reason: string; stop: boolean }
    | { kind: "unauthenticated" }
    | { kind: "unknown" }

function classify(error: unknown, change: StagedChange): StepAnswer {
    if (!(error instanceof PlatformAccountsRequestError)) return { kind: "unknown" }
    const { status, code } = error
    if (status === 401) return { kind: "unauthenticated" }
    if (status >= 500) return { kind: "unknown" }
    if (status === 409 && code === "last_active_platform_administrator") {
        return { kind: "refused", reason: LAST_ADMIN_TEXT, stop: false }
    }
    if (status === 403 && code === "admin_grant_disabled" && change.code === "admin") {
        return { kind: "refused", reason: GRANT_DISABLED_TEXT, stop: false }
    }
    if (status === 403 || status === 404) return { kind: "refused", reason: PERMISSION_TEXT, stop: true }
    return { kind: "refused", reason: REFUSED_TEXT, stop: false }
}

export function useSystemRoleSave({ csrfToken, selfUserId, onReconciled }: UseSystemRoleSaveOptions): UseSystemRoleSaveResult {
    const { reload, refresh } = useSession()
    const [state, setState] = useState<SaveState>(IDLE)
    const controllerRef = useRef<AbortController | null>(null)
    // Held from the Save press until the result is settled, so a second press cannot start a second batch.
    const busyRef = useRef(false)
    const contextRef = useRef<SaveContext | null>(null)
    const ledgerRef = useRef<LedgerStep[]>([])
    const latest = useRef({ csrfToken, selfUserId, onReconciled, reload, refresh })
    useEffect(() => {
        latest.current = { csrfToken, selfUserId, onReconciled, reload, refresh }
    })

    useEffect(() => {
        return () => {
            controllerRef.current?.abort()
        }
    }, [])

    const clear = useCallback(() => {
        controllerRef.current?.abort()
        controllerRef.current = null
        busyRef.current = false
        contextRef.current = null
        ledgerRef.current = []
        setState(IDLE)
    }, [])

    // Reads the account's roles and settles the ledger from them. Returns after publishing a result.
    const reconcile = useCallback(async (controller: AbortController, checking: boolean) => {
        const context = contextRef.current
        if (context === null) return
        const { account } = context
        setState((current) => ({ ...current, phase: "reconciling", checking }))
        try {
            const result = await fetchPlatformAccounts(
                { q: account.login_name ?? account.display_name, limit: 100 },
                controller.signal,
            )
            if (controller.signal.aborted) return
            const found = result.items.find((item) => item.user_id === account.user_id)
            if (found === undefined) {
                busyRef.current = false
                setState((current) => ({ ...current, phase: "check_failed", checking: false }))
                return
            }
            const settled = confirmFromRoles(ledgerRef.current, found.system_roles)
            ledgerRef.current = settled
            busyRef.current = false
            setState({ phase: "done", userId: account.user_id, ledger: settled, checking: false })
            latest.current.onReconciled(found, draftAfterSave(found.system_roles, settled))
            // Another confirmed change to the signed-in account's own roles: the bootstrap is read again once,
            // without leaving the page.
            if (context.ownAccount && settled.some((step) => step.result === "saved" || step.result === "confirmed")) {
                void bootstrapRefreshOutcome(latest.current.refresh)
            }
        } catch (error) {
            if (controller.signal.aborted) return
            busyRef.current = false
            if (error instanceof PlatformAccountsRequestError && error.status === 401) {
                setState((current) => ({ ...current, phase: "done", checking: false }))
                latest.current.reload()
                return
            }
            if (error instanceof PlatformAccountsRequestError && error.status === 404) {
                setState((current) => ({ ...current, phase: "access_unknown", checking: false }))
                return
            }
            setState((current) => ({ ...current, phase: "check_failed", checking: false }))
        }
    }, [])

    const save = useCallback(
        (account: PlatformAccount, changes: readonly StagedChange[]) => {
            if (busyRef.current || changes.length === 0) return
            busyRef.current = true
            const controller = new AbortController()
            controllerRef.current = controller
            const ownAccount = account.user_id === latest.current.selfUserId
            contextRef.current = { account, ownAccount }
            ledgerRef.current = []
            setState({ phase: "saving", userId: account.user_id, ledger: [], checking: false })

            void (async () => {
                const ledger: LedgerStep[] = []
                let stopped = false
                let sent = 0
                let unauthenticated = false
                for (const change of changes) {
                    if (stopped) {
                        ledger.push({ change, result: "not_sent" })
                        continue
                    }
                    if (controller.signal.aborted) return
                    sent += 1
                    const send = change.action === "add" ? assignSystemRole : revokeSystemRole
                    let answer: StepAnswer
                    try {
                        const response = await send(account.user_id, change.code, latest.current.csrfToken, controller.signal)
                        if (controller.signal.aborted) return
                        answer = response.changed
                            ? { kind: "saved", strandedWorlds: response.stranded_world_ids?.length ?? 0 }
                            : { kind: "already" }
                    } catch (error) {
                        if (controller.signal.aborted) return
                        answer = classify(error, change)
                    }
                    switch (answer.kind) {
                        case "saved":
                            ledger.push({ change, result: "saved", strandedWorlds: answer.strandedWorlds })
                            break
                        case "already":
                            ledger.push({ change, result: "already" })
                            break
                        case "refused":
                            ledger.push({ change, result: "refused", reason: answer.reason })
                            stopped = answer.stop
                            break
                        case "unauthenticated":
                            // This step was not answered, and nothing more is sent.
                            ledger.push({ change, result: "not_sent" })
                            sent -= 1
                            unauthenticated = true
                            stopped = true
                            break
                        case "unknown":
                            ledger.push({ change, result: "not_confirmed" })
                            stopped = true
                            break
                    }
                }
                if (controller.signal.aborted) return
                ledgerRef.current = ledger
                if (unauthenticated) {
                    busyRef.current = false
                    setState({ phase: "done", userId: account.user_id, ledger, checking: false })
                    latest.current.reload()
                    return
                }
                const ownAdminSaved = ownAccount && ledger.some((step) => step.change.code === "admin" && step.change.action === "remove" && step.result === "saved")
                if (sent === 0 || ownAdminSaved) {
                    // Nothing was sent, or the account that would be read has just lost the right to read it:
                    // the ledger is final as it stands.
                    busyRef.current = false
                    setState({ phase: "done", userId: account.user_id, ledger, checking: false })
                    return
                }
                setState({ phase: "reconciling", userId: account.user_id, ledger, checking: false })
                await reconcile(controller, false)
            })()
        },
        [reconcile],
    )

    const checkAgain = useCallback(() => {
        if (busyRef.current || contextRef.current === null) return
        busyRef.current = true
        const controller = new AbortController()
        controllerRef.current = controller
        void reconcile(controller, true)
    }, [reconcile])

    const ownAdminRemoved =
        state.phase === "done" &&
        state.userId === selfUserId &&
        state.ledger.some((step) => step.change.code === "admin" && step.change.action === "remove" && step.result === "saved")

    return { state, save, checkAgain, clear, ownAdminRemoved }
}

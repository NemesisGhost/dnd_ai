import { useEffect, useId, useRef } from "react"
import type { SavePhase } from "../hooks/useSystemRoleSave"
import type { PlatformAccount } from "../types/platformAccounts"
import { SYSTEM_ROLE_OPTIONS } from "../utils/systemAccess"
import type { SystemRoleCode } from "../utils/systemAccess"
import { describeChange, isDirty, ledgerText, saveSentence, stagedChanges } from "../utils/systemRoleStaging"
import type { LedgerStep } from "../utils/systemRoleStaging"

interface SystemRolesPanelProps {
    // The roles the account held when editing began (the baseline); never changed by ticking.
    account: PlatformAccount
    draft: readonly SystemRoleCode[]
    // True when this is the signed-in account (its own Administrator removal is ordered last).
    ownAccount: boolean
    // True only while the server reports `system_roles.grant_admin`.
    canGrantAdmin: boolean
    // The id the page's disabled Edit roles buttons point at to explain why they are disabled.
    reasonId: string
    // Changes every time Edit roles is pressed for this account, so the heading takes focus again.
    focusSignal: number
    // Where a save stands, and the per-change result of the last one (empty before the first save).
    phase: SavePhase
    checking: boolean
    ledger: readonly LedgerStep[]
    onToggle: (code: SystemRoleCode, checked: boolean) => void
    onSave: () => void
    // Repeats only the read of the account's current roles; never writes.
    onCheck: () => void
    // Cancel (dirty) restores the baseline and closes; Close (clean) just closes. Neither sends anything.
    onCancel: () => void
    onClose: () => void
}

const ADMIN_NOTE = "Granting Administrator is done by the operator script on this deployment."

// One account's system roles, staged locally and saved only on request. It sits above the accounts table
// (never inside a row), so a list reload cannot unmount it. A system role never grants membership in a campaign
// or authority over a world, and the changes are separate requests: some can be saved while others are not.
export function SystemRolesPanel({
    account,
    draft,
    ownAccount,
    canGrantAdmin,
    reasonId,
    focusSignal,
    phase,
    checking,
    ledger,
    onToggle,
    onSave,
    onCheck,
    onCancel,
    onClose,
}: SystemRolesPanelProps) {
    const headingId = useId()
    const noteId = useId()
    const changesId = useId()
    const resultId = useId()
    const headingRef = useRef<HTMLHeadingElement>(null)
    const resultRef = useRef<HTMLHeadingElement>(null)
    const saveRef = useRef<HTMLButtonElement>(null)

    useEffect(() => {
        headingRef.current?.focus()
    }, [focusSignal])

    // When a save settles, the Result heading takes focus only if focus was lost with the controls that went away
    // (the body, or the Save button that was disabled while saving); a control the person moved to keeps it.
    const previousPhase = useRef(phase)
    useEffect(() => {
        const before = previousPhase.current
        previousPhase.current = phase
        if ((before !== "saving" && before !== "reconciling") || (phase !== "done" && phase !== "check_failed")) {
            return
        }
        const active = document.activeElement
        if (active === null || active === document.body || active === saveRef.current) {
            resultRef.current?.focus()
        }
    }, [phase])

    const saving = phase === "saving"
    const busy = saving || phase === "reconciling"
    const dirty = isDirty(account.system_roles, draft)
    const changes = stagedChanges(account.system_roles, draft, ownAccount)
    const baseline = new Set(account.system_roles)
    const locked = dirty || busy || phase === "check_failed"
    const showResult =
        ledger.length > 0 &&
        (phase === "done" || phase === "check_failed" || phase === "access_unknown" || (phase === "reconciling" && checking))
    const showCheck = phase === "check_failed" || (phase === "reconciling" && checking)

    let status = ""
    if (saving) {
        status = "Saving changes…"
    } else if (phase === "reconciling") {
        status = "Checking this account's current roles…"
    } else if (showResult) {
        status = saveSentence(ledger)
    }
    if (phase === "check_failed") {
        status = `${status} We could not check this account's current roles.`.trim()
    }

    return (
        <section aria-labelledby={headingId} className="admin-accounts__roles-panel">
            <h2 id={headingId} ref={headingRef} tabIndex={-1}>
                System roles for {account.display_name}
            </h2>
            <fieldset aria-describedby={noteId} className="admin-accounts__roles" disabled={busy}>
                <legend>Roles</legend>
                {SYSTEM_ROLE_OPTIONS.map((option) => {
                    const checked = draft.includes(option.code)
                    // An already-held Administrator role may always be removed; only a new grant is gated by the
                    // deployment setting.
                    const adminLocked = option.code === "admin" && !baseline.has("admin") && !canGrantAdmin
                    return (
                        <label key={option.code}>
                            <input
                                type="checkbox"
                                checked={checked}
                                disabled={adminLocked || busy}
                                onChange={(event) => onToggle(option.code, event.currentTarget.checked)}
                            />{" "}
                            {option.label}
                        </label>
                    )
                })}
                <p id={noteId} className="admin-accounts__roles-note">
                    {canGrantAdmin ? "" : `${ADMIN_NOTE} `}A system role never grants access to any campaign or world.
                </p>
            </fieldset>
            <p>Changes are saved one at a time; some can be saved while others are not.</p>

            {dirty ? (
                <>
                    <p id={changesId}>Changes not saved yet</p>
                    <ul aria-labelledby={changesId}>
                        {changes.map((change) => (
                            <li key={change.code}>{describeChange(change)}</li>
                        ))}
                    </ul>
                </>
            ) : (
                <p>No changes</p>
            )}
            {locked && <p id={reasonId}>Save or cancel these changes before editing another account.</p>}

            <div className="authoring-actions">
                <button
                    ref={saveRef}
                    type="button"
                    className="authoring-button authoring-button--primary"
                    disabled={!dirty || busy || phase === "check_failed"}
                    onClick={onSave}
                >
                    Save changes
                </button>
                {dirty ? (
                    <button type="button" className="authoring-button" disabled={saving} onClick={onCancel}>
                        Cancel
                    </button>
                ) : (
                    <button type="button" className="authoring-button" onClick={onClose}>
                        Close
                    </button>
                )}
                {showCheck && (
                    <button type="button" className="authoring-button" aria-busy={checking} onClick={onCheck}>
                        Check current roles
                    </button>
                )}
            </div>

            <p role="status" aria-live="polite">
                {status}
            </p>

            {showResult && (
                <>
                    <h3 id={resultId} ref={resultRef} tabIndex={-1}>
                        Result
                    </h3>
                    <RoleLedger ledger={ledger} labelledBy={resultId} />
                </>
            )}
        </section>
    )
}

// What each change did. Not live: the polite status sentence carries the announcement.
function RoleLedger({ ledger, labelledBy }: { ledger: readonly LedgerStep[]; labelledBy: string }) {
    return (
        <ul aria-labelledby={labelledBy}>
            {ledger.map((step) => (
                <li key={step.change.code}>{ledgerText(step)}</li>
            ))}
        </ul>
    )
}

interface SystemRolesReceiptProps {
    kind: "removed" | "unknown"
    ledger: readonly LedgerStep[]
    onContinue: () => void
}

// Shown in place of the list once the signed-in account's own Administrator role was removed, or its access can
// no longer be checked. The bootstrap is refreshed only when the person continues, so this receipt is read first.
export function SystemRolesReceipt({ kind, ledger, onContinue }: SystemRolesReceiptProps) {
    const headingId = useId()
    const listId = useId()
    const headingRef = useRef<HTMLHeadingElement>(null)
    useEffect(() => {
        headingRef.current?.focus()
    }, [])
    return (
        <section aria-labelledby={headingId}>
            <h2 id={headingId} ref={headingRef} tabIndex={-1}>
                {kind === "removed"
                    ? "Your Administrator role was removed"
                    : "Your access to platform accounts may have changed"}
            </h2>
            <p>
                {kind === "removed"
                    ? "Platform accounts will close when you continue."
                    : "We could not check the result. Continue to update your access."}
            </p>
            <p id={listId}>Result</p>
            <RoleLedger ledger={ledger} labelledBy={listId} />
            <button type="button" className="authoring-button" onClick={onContinue}>
                Continue
            </button>
        </section>
    )
}

import { SYSTEM_ROLE_OPTIONS } from "./systemAccess"
import type { SystemRoleCode } from "./systemAccess"

// Pure rules for staging an account's system-role changes locally before anything is sent. Nothing here
// touches the network or the DOM.

export interface StagedChange {
    code: SystemRoleCode
    action: "add" | "remove"
}

function held(codes: readonly string[]): Set<string> {
    return new Set(codes)
}

// What differs between the roles the account holds (`baseline`) and the roles ticked (`draft`): grants first,
// then removals, each in the option order. A removal of Administrator from the signed-in account's own
// account (`ownAccount`) is always last, so the person keeps their authority while the rest is done.
export function stagedChanges(
    baseline: readonly string[],
    draft: readonly string[],
    ownAccount = false,
): StagedChange[] {
    const before = held(baseline)
    const after = held(draft)
    const adds: StagedChange[] = []
    const removes: StagedChange[] = []
    for (const { code } of SYSTEM_ROLE_OPTIONS) {
        if (after.has(code) && !before.has(code)) {
            adds.push({ code, action: "add" })
        } else if (!after.has(code) && before.has(code)) {
            removes.push({ code, action: "remove" })
        }
    }
    if (ownAccount) {
        const own = removes.filter((change) => change.code === "admin")
        return [...adds, ...removes.filter((change) => change.code !== "admin"), ...own]
    }
    return [...adds, ...removes]
}

export function isDirty(baseline: readonly string[], draft: readonly string[]): boolean {
    return stagedChanges(baseline, draft).length > 0
}

export function roleLabel(code: SystemRoleCode): string {
    return SYSTEM_ROLE_OPTIONS.find((option) => option.code === code)?.label ?? code
}

// "Add Game master" / "Remove Player".
export function describeChange(change: StagedChange): string {
    return `${change.action === "add" ? "Add" : "Remove"} ${roleLabel(change.code)}`
}

// The role codes this module understands, in option order, from whatever the server listed (an unknown code is
// not offered a checkbox and is never staged).
export function knownRoles(codes: readonly string[]): SystemRoleCode[] {
    const present = held(codes)
    return SYSTEM_ROLE_OPTIONS.filter((option) => present.has(option.code)).map((option) => option.code)
}

// ---- What a save did, change by change (the ledger) ----

export type StepResult =
    // The server answered `changed: true`.
    | "saved"
    // The server answered `changed: false`: the role was already so.
    | "already"
    // The server refused this change (or the whole route); `reason` says why.
    | "refused"
    // No answer, a server error or an unreadable answer: the portal cannot tell whether it was applied.
    | "not_confirmed"
    // Never sent, because an earlier step stopped the batch.
    | "not_sent"
    // Was not confirmed or not sent, and a later read of the account's roles shows it applied.
    | "confirmed"

export interface LedgerStep {
    change: StagedChange
    result: StepResult
    reason?: string
    // Worlds a Game master removal left without a manageable Owner: a count only, never identifiers.
    strandedWorlds?: number
}

export function ledgerText(step: LedgerStep): string {
    const label = roleLabel(step.change.code)
    const added = step.change.action === "add"
    switch (step.result) {
        case "saved": {
            const stranded =
                step.strandedWorlds !== undefined && step.strandedWorlds > 0
                    ? ` ${step.strandedWorlds} world(s) this account owns now have no manageable Owner.`
                    : ""
            return `${label} ${added ? "added" : "removed"}${stranded === "" ? "" : `.${stranded}`}`
        }
        case "already":
            return added ? `Already had ${label}` : `Already did not have ${label}`
        case "refused":
            return `${describeChange(step.change)}: refused. ${step.reason ?? "This change was refused."}`
        case "not_confirmed":
            return `${describeChange(step.change)}: not confirmed. We could not tell whether it was saved.`
        case "not_sent":
            return `${describeChange(step.change)}: not sent.`
        case "confirmed":
            return `${describeChange(step.change)}: confirmed from current roles.`
    }
}

// The one polite sentence for a settled save. "Already so" and "confirmed from current roles" count as saved.
export function saveSentence(ledger: readonly LedgerStep[]): string {
    const count = (...results: StepResult[]) => ledger.filter((step) => results.includes(step.result)).length
    const saved = count("saved", "already", "confirmed")
    let sentence = `${saved} of ${ledger.length} ${ledger.length === 1 ? "change" : "changes"} saved.`
    const refused = count("refused")
    const unconfirmed = count("not_confirmed")
    const notSent = count("not_sent")
    if (refused > 0) sentence += ` ${refused} refused.`
    if (unconfirmed > 0) sentence += ` ${unconfirmed} could not be confirmed.`
    if (notSent > 0) sentence += ` ${notSent} not sent.`
    return sentence
}

// Whether anything was sent that may have been applied (so "not saved" would be untrue).
export function mayHaveBeenSent(ledger: readonly LedgerStep[]): boolean {
    return ledger.some((step) => step.result === "saved" || step.result === "not_confirmed" || step.result === "confirmed")
}

// Relabels the steps the portal could not settle by the account's current roles: an unconfirmed or unsent step
// whose effect those roles already show is confirmed. Every other step keeps its result.
export function confirmFromRoles(ledger: readonly LedgerStep[], current: readonly string[]): LedgerStep[] {
    const roles = held(current)
    return ledger.map((step) => {
        if (step.result !== "not_confirmed" && step.result !== "not_sent") return step
        const applied = step.change.action === "add" ? roles.has(step.change.code) : !roles.has(step.change.code)
        return applied ? { ...step, result: "confirmed" } : step
    })
}

// The draft after a save: the account's current roles plus every intended change that was not refused (a
// refused change is dropped, a change already in effect adds nothing). What is left over is exactly what a
// deliberate second Save would send.
export function draftAfterSave(current: readonly string[], ledger: readonly LedgerStep[]): SystemRoleCode[] {
    const draft = held(knownRoles(current))
    for (const step of ledger) {
        if (step.result === "refused") continue
        if (step.change.action === "add") draft.add(step.change.code)
        else draft.delete(step.change.code)
    }
    return knownRoles([...draft])
}

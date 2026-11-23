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

import type { RefreshOutcome } from "../hooks/useAuthoringMutation"
import type { RefetchOutcome } from "../hooks/useAuthoringResource"

// What re-reading the session bootstrap did, for a write whose result the bootstrap carries (a
// campaign name, its lifecycle). `refresh` resolves true when the fresh bootstrap was applied, false
// when it was not applied (the session ended and the sign-in boundary takes over, or a newer session
// read decided first), and rejects when the current request failed, leaving the previous bootstrap
// in place. Not applied is never read as a refusal of the write.
export async function bootstrapRefreshOutcome(refresh: () => Promise<boolean>): Promise<RefreshOutcome> {
    try {
        return (await refresh()) ? "ok" : "superseded"
    } catch {
        return "failed"
    }
}

// What re-reading several records after one write amounts to. A write whose follow-up reads one
// record or many is confirmed either way, so the hook needs one answer: "ok" only when every read
// was applied, "failed" when any was not, otherwise "superseded" (a newer read will answer).
export function combineRefetchOutcomes(outcomes: readonly RefetchOutcome[]): RefreshOutcome {
    if (outcomes.includes("failed")) return "failed"
    return outcomes.includes("superseded") ? "superseded" : "ok"
}

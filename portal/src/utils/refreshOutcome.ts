import type { RefreshOutcome } from "../hooks/useAuthoringMutation"
import type { RefetchOutcome } from "../hooks/useAuthoringResource"

// What re-reading the session bootstrap did, for a write whose result the bootstrap carries (a
// campaign name, its lifecycle). `refresh` resolves true when the fresh bootstrap was applied, false
// when the session ended (the sign-in boundary takes over, so there is nothing to explain), and
// rejects when the request failed, leaving the previous bootstrap in place.
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

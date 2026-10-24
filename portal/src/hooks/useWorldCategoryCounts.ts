import { useEffect, useState } from "react"
import { fetchWorldCategoryCounts } from "../api/world"
import type { WorldCategoryCounts } from "../types/world"

function isCounts(value: unknown): value is WorldCategoryCounts {
    const candidate = value as Partial<WorldCategoryCounts> | null

    return (
        typeof candidate?.total === "number" &&
        typeof candidate.counts === "object" &&
        candidate.counts !== null
    )
}

interface Loaded {
    key: string
    counts: WorldCategoryCounts
}

// Authorized per-category totals for the current search, from the server (never
// counted from loaded pages). Returns `null` — shown as no count, never as a
// zero — while the totals for the *current* search are loading, after a
// failure, and for a stale answer. Only the search, the draft preview and the
// campaign change the request; a category or page change reuses the totals.
// A superseded request is aborted and its answer ignored.
export function useWorldCategoryCounts(
    campaignId: string,
    query: string,
    includeHidden: boolean,
): WorldCategoryCounts | null {
    const key = `${campaignId}\u0000${query}\u0000${includeHidden}`
    const [loaded, setLoaded] = useState<Loaded | null>(null)

    useEffect(() => {
        const controller = new AbortController()

        fetchWorldCategoryCounts(
            campaignId,
            { query, includeHidden },
            controller.signal,
        )
            .then((counts) => {
                if (!controller.signal.aborted && isCounts(counts)) {
                    setLoaded({ key, counts })
                }
            })
            .catch(() => {
                // Aborted, unauthorized or failed: no count rather than a wrong one.
            })

        return () => controller.abort()
    }, [campaignId, query, includeHidden, key])

    return loaded !== null && loaded.key === key ? loaded.counts : null
}

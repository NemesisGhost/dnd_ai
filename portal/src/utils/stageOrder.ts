// Pure ordering helpers for the quest stage list. The server stays
// authoritative: these only compute the `stage_ids` order to request.

// The order after moving `dragId` before or after `targetId`, or null when the
// move would leave the order unchanged (or names an unknown stage).
export function reorderedStageIds(
    ids: string[],
    dragId: string,
    targetId: string,
    after: boolean,
): string[] | null {
    if (dragId === targetId || !ids.includes(dragId) || !ids.includes(targetId)) return null
    const rest = ids.filter((id) => id !== dragId)
    const at = rest.indexOf(targetId) + (after ? 1 : 0)
    const next = [...rest.slice(0, at), dragId, ...rest.slice(at)]
    return next.every((id, i) => id === ids[i]) ? null : next
}

// The order after moving the stage at `index` one place, or null at an edge.
export function steppedStageIds(ids: string[], index: number, delta: -1 | 1): string[] | null {
    const target = index + delta
    if (index < 0 || index >= ids.length || target < 0 || target >= ids.length) return null
    const next = [...ids]
    ;[next[index], next[target]] = [next[target]!, next[index]!]
    return next
}

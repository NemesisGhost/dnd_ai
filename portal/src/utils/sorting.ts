export type SortDirection = "asc" | "desc"

export function applyDirection(
    direction: SortDirection,
    comparison: number,
): number {
    return direction === "asc" ? comparison : -comparison
}

export function compareNullableTimestamps(
    a: string | null,
    b: string | null,
    direction: SortDirection,
): number {
    if (a === null && b === null) {
        return 0
    }
    if (a === null) {
        return 1
    }
    if (b === null) {
        return -1
    }
    return applyDirection(direction, new Date(a).getTime() - new Date(b).getTime())
}

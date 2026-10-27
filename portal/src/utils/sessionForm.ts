// An ISO timestamp as the value of a datetime-local input (the viewer's zone).
export function toLocalInput(iso: string | null): string {
    if (iso === null) return ""
    const date = new Date(iso)
    const pad = (n: number) => String(n).padStart(2, "0")
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

export function fromLocalInput(value: string): string | null {
    if (value.trim() === "") return null
    const date = new Date(value)
    return Number.isNaN(date.getTime()) ? null : date.toISOString()
}

// Stable server error codes for session writes, with the sentence to show.
export const SESSION_ERROR_MESSAGE: Readonly<Record<string, string>> = {
    session_not_active:
        "This session is not active, so it cannot be changed. An archived session must be restored first.",
    session_not_archived: "This session is not archived.",
    session_in_progress: "End the session before archiving it.",
    session_already_started: "This session has already started, so its planned start cannot change.",
}

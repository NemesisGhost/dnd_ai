const STATUS_LABEL: Readonly<Record<string, string>> = {
    unavailable: "Not available",
    available: "Available",
    active: "Active",
    suspended: "Suspended",
    completed: "Completed",
    failed: "Failed",
    abandoned: "Abandoned",
    hidden: "Hidden",
    skipped: "Skipped",
    superseded: "Replaced",
}

// The words for a quest's or an objective's status; no status yet means it has not been started.
export const statusLabel = (status: string | null): string =>
    status === null ? "Not started" : (STATUS_LABEL[status] ?? status)

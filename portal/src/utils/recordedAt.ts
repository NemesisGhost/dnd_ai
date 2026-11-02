// The real-world moment an event was recorded, in the reader's own timezone and labelled with it
// so it is never read as in-world time. An unparsable value is shown as received.
export function formatRecordedAt(value: string): string {
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) return value
    return date.toLocaleString(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
        timeZoneName: "short",
    })
}

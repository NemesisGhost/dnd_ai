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

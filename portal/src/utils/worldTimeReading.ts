import type { Calendar, WorldTimeItem } from "../types/worldTime"

// How one world-time point reads wherever a person chooses or records it: the calendar, the date, the
// clock time and the label, so points on the same day can be told apart. The server's `display` has no
// clock time or calendar name and is kept only for narrative points and as the fallback.

function clock(item: WorldTimeItem): string | null {
    if (item.hour === null) return null
    return `${String(item.hour).padStart(2, "0")}:${String(item.minute ?? 0).padStart(2, "0")}`
}

export function worldTimeReading(
    item: WorldTimeItem,
    calendars: readonly Calendar[],
): string {
    if (item.calendar_id === null || item.year === null) return item.display

    const calendar = calendars.find((candidate) => candidate.calendar_id === item.calendar_id)
    // A calendar that is not in the loaded list is never guessed: `display` and the clock time only.
    if (calendar === undefined) {
        const time = clock(item)
        return time === null ? item.display : `${item.display}, ${time}`
    }

    const year = calendar.epoch_label
        ? `Year ${item.year} (${calendar.epoch_label})`
        : `Year ${item.year}`
    const month =
        item.month_number === null
            ? null
            : (calendar.months.find((candidate) => candidate.month_number === item.month_number)
                  ?.name ?? null)
    const parts = [year]
    if (month !== null) parts.push(`${month}${item.day === null ? "" : ` ${item.day}`}`)
    const time = clock(item)
    if (time !== null) parts.push(time)
    const date = `${calendar.name}: ${parts.join(", ")}`
    return item.label ? `${date} — ${item.label}` : date
}

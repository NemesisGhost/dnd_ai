import type { Calendar, WorldTimeItem } from "../types/worldTime"

// How one world-time point reads wherever a person chooses or records it: the calendar, the date, the
// clock time and the label, so points on the same day can be told apart. The server's `display` has no
// clock time or calendar name and is kept only for narrative points and as the fallback.

function clock(item: WorldTimeItem): string | null {
    if (item.hour === null) return null
    return `${String(item.hour).padStart(2, "0")}:${String(item.minute ?? 0).padStart(2, "0")}`
}

// `pageFallback` is for the World times page only: it keeps the reading that page had before this
// formatter existed for a point whose calendar is not loaded ("Calendar: Year N, ..." with no epoch or
// month name). Pickers, forms and receipts leave it off and get the display-text fallback below.
export function worldTimeReading(
    item: WorldTimeItem,
    calendars: readonly Calendar[],
    options: { pageFallback?: boolean } = {},
): string {
    if (item.calendar_id === null || item.year === null) return item.display

    const calendar = calendars.find((candidate) => candidate.calendar_id === item.calendar_id)
    // A calendar that is not in the loaded list is never guessed: `display` and the clock time only.
    if (calendar === undefined && options.pageFallback !== true) {
        const time = clock(item)
        return time === null ? item.display : `${item.display}, ${time}`
    }

    const year = calendar?.epoch_label
        ? `Year ${item.year} (${calendar.epoch_label})`
        : `Year ${item.year}`
    const month =
        item.month_number === null
            ? null
            : (calendar?.months.find((candidate) => candidate.month_number === item.month_number)
                  ?.name ?? null)
    const parts = [year]
    if (month !== null) parts.push(`${month}${item.day === null ? "" : ` ${item.day}`}`)
    const time = clock(item)
    if (time !== null) parts.push(time)
    const date = `${calendar?.name ?? "Calendar"}: ${parts.join(", ")}`
    return item.label ? `${date} — ${item.label}` : date
}

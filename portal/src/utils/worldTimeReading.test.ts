import { describe, expect, it } from "vitest"
import type { Calendar, WorldTimeItem } from "../types/worldTime"
import { worldTimeReading } from "./worldTimeReading"

const COMMON: Calendar = {
    calendar_id: "cal-1",
    code: "common",
    name: "Common Reckoning",
    description: null,
    days_per_week: 7,
    epoch_label: "Founding",
    months: [
        { month_number: 1, name: "Frost", day_count: 30 },
        { month_number: 2, name: "Bloom", day_count: 28 },
    ],
}
const PLAIN: Calendar = { ...COMMON, calendar_id: "cal-2", name: "Short Count", epoch_label: null }

const item = (over: Partial<WorldTimeItem>): WorldTimeItem => ({
    world_time_id: "t",
    calendar_id: "cal-1",
    year: 3,
    month_number: null,
    day: null,
    hour: null,
    minute: null,
    label: null,
    precision: "exact",
    sort_key: 1,
    display: "Year 3 (Founding), Bloom 5",
    ...over,
})

describe("worldTimeReading (E5, E15)", () => {
    it("reads each kind of item exactly as the World times page did", () => {
        const calendars = [COMMON, PLAIN]
        expect(worldTimeReading(item({ calendar_id: null, year: null, display: "The sack of Vael" }), calendars)).toBe(
            "The sack of Vael",
        )
        expect(worldTimeReading(item({}), calendars)).toBe("Common Reckoning: Year 3 (Founding)")
        expect(worldTimeReading(item({ month_number: 2 }), calendars)).toBe(
            "Common Reckoning: Year 3 (Founding), Bloom",
        )
        expect(worldTimeReading(item({ month_number: 2, day: 5 }), calendars)).toBe(
            "Common Reckoning: Year 3 (Founding), Bloom 5",
        )
        expect(worldTimeReading(item({ month_number: 2, day: 5, hour: 9, minute: 5 }), calendars)).toBe(
            "Common Reckoning: Year 3 (Founding), Bloom 5, 09:05",
        )
        expect(worldTimeReading(item({ month_number: 2, day: 5, hour: 14 }), calendars)).toBe(
            "Common Reckoning: Year 3 (Founding), Bloom 5, 14:00",
        )
        expect(worldTimeReading(item({ calendar_id: "cal-2", month_number: 1, day: 2 }), calendars)).toBe(
            "Short Count: Year 3, Frost 2",
        )
        expect(worldTimeReading(item({ month_number: 2, day: 5, hour: 14, label: "The feast" }), calendars)).toBe(
            "Common Reckoning: Year 3 (Founding), Bloom 5, 14:00 — The feast",
        )
    })

    it("falls back to the display text and the clock time, never inventing a calendar or month", () => {
        const unknown = item({ calendar_id: "cal-gone", month_number: 2, day: 5, hour: 14, minute: 30 })
        expect(worldTimeReading(unknown, [PLAIN])).toBe("Year 3 (Founding), Bloom 5, 14:30")
        expect(worldTimeReading(unknown, [])).toBe("Year 3 (Founding), Bloom 5, 14:30")
        expect(worldTimeReading(item({ calendar_id: "cal-gone" }), [PLAIN])).toBe("Year 3 (Founding), Bloom 5")
    })

    it("gives the World times page its own unchanged fallback, and only when asked (C09-S01-1)", () => {
        const unknown = item({ calendar_id: "cal-gone", month_number: 2, day: 5, hour: 14, minute: 30, label: "The feast" })
        expect(worldTimeReading(unknown, [PLAIN], { pageFallback: true })).toBe("Calendar: Year 3, 14:30 — The feast")
        expect(worldTimeReading(unknown, [PLAIN])).toBe("Year 3 (Founding), Bloom 5, 14:30")
        // A loaded calendar reads the same either way.
        const known = item({ month_number: 2, day: 5, hour: 9 })
        expect(worldTimeReading(known, [COMMON], { pageFallback: true })).toBe(worldTimeReading(known, [COMMON]))
        expect(worldTimeReading(item({ calendar_id: null, year: null, display: "Vael" }), [], { pageFallback: true })).toBe("Vael")
    })
})

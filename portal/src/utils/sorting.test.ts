import {
    describe,
    expect,
    it,
} from "vitest"
import {
    applyDirection,
    compareNullableTimestamps,
} from "./sorting"

describe("applyDirection", () => {
    it("returns the comparison unchanged for ascending", () => {
        expect(applyDirection("asc", 5)).toBe(5)
        expect(applyDirection("asc", -5)).toBe(-5)
    })

    it("negates the comparison for descending", () => {
        expect(applyDirection("desc", 5)).toBe(-5)
        expect(applyDirection("desc", -5)).toBe(5)
    })
})

describe("compareNullableTimestamps", () => {
    it("orders earlier timestamps before later ones when ascending", () => {
        expect(
            compareNullableTimestamps(
                "2026-01-01T00:00:00Z",
                "2026-02-01T00:00:00Z",
                "asc",
            ),
        ).toBeLessThan(0)
    })

    it("orders later timestamps before earlier ones when descending", () => {
        expect(
            compareNullableTimestamps(
                "2026-01-01T00:00:00Z",
                "2026-02-01T00:00:00Z",
                "desc",
            ),
        ).toBeGreaterThan(0)
    })

    it.each([["asc"], ["desc"]] as const)(
        "sorts null after any real timestamp regardless of comparison order (%s)",
        (direction) => {
            expect(
                compareNullableTimestamps(null, "2026-01-01T00:00:00Z", direction),
            ).toBeGreaterThan(0)
            expect(
                compareNullableTimestamps("2026-01-01T00:00:00Z", null, direction),
            ).toBeLessThan(0)
        },
    )

    it.each([["asc"], ["desc"]] as const)(
        "treats two nulls as equal (%s)",
        (direction) => {
            expect(compareNullableTimestamps(null, null, direction)).toBe(0)
        },
    )
})

import { describe, expect, it } from "vitest"
import { toCalendarBody } from "../../utils/worldTimeForm"
import {
    COMPOSER_NAME_ID,
    blockingForm,
    calendarReducer,
    initialDraft,
    monthDaysId,
    monthKeyOfField,
    monthNameId,
    stepForField,
    unappliedForms,
    validateCalendarDraft,
    yearLength,
    yearLengthText,
} from "./calendarDraft"
import type { CalendarDraft, DraftAction } from "./calendarDraft"

function run(draft: CalendarDraft, ...actions: DraftAction[]): CalendarDraft {
    return actions.reduce(calendarReducer, draft)
}

// Adds a committed month through the composer, as a person would.
function addMonth(draft: CalendarDraft, name: string, dayCount = "30"): CalendarDraft {
    return run(
        draft,
        { type: "composer", patch: { name, dayCount } },
        { type: "applyComposer" },
    )
}

// A draft with one month and a calendar name, the Add a month panel ready.
function named(name = "Frost"): CalendarDraft {
    return run(addMonth(initialDraft(), name), { type: "field", field: "name", value: "Reckoning" })
}

const ids = (draft: CalendarDraft) => validateCalendarDraft(draft).map((e) => e.fieldId)

describe("initial draft", () => {
    it("has no months, only the Add a month panel (a blank 30-day month), nothing touched and nothing seeded", () => {
        const draft = initialDraft()
        expect(draft.months).toEqual([])
        expect(draft.editing).toBeNull()
        expect(draft.composer).toEqual({ name: "", dayCount: "30", errors: [] })
        expect(draft.name).toBe("")
        expect(draft.description).toBe("")
        expect(draft.epochLabel).toBe("")
        expect(draft.daysPerWeek).toBe("")
        expect(draft.touched).toBe(false)
        expect(unappliedForms(draft)).toEqual([])
        expect(yearLengthText(draft)).toBe("Add at least one month to see the year length.")
    })

    it("cannot be created without a month, and says so on the Months heading", () => {
        const errors = validateCalendarDraft({ ...initialDraft(), name: "Common" })
        expect(errors).toEqual([{ fieldId: "calendar-months", message: expect.stringMatching(/at least one month/) }])
    })
})

describe("add", () => {
    it("opens a blank 30-day form, appends on apply with a new key, and stays open for the next", () => {
        const draft = addMonth(named(), "Thaw", "31")
        expect(draft.months.map((m) => [m.key, m.name, m.dayCount])).toEqual([
            ["m1", "Frost", "30"],
            ["m2", "Thaw", "31"],
        ])
        expect(draft.composer).toEqual({ name: "", dayCount: "30", errors: [] })
        expect(draft.touched).toBe(true)
    })

    it("refuses an invalid month and keeps the form and its values", () => {
        const base = named()
        for (const [name, days] of [
            ["", "30"],
            ["X", "0"],
            ["X", "401"],
            ["X", "2.5"],
            ["X", "abc"],
            ["X", ""],
            ["frost", "30"],
            [" FROST ", "30"],
            ["x".repeat(101), "30"],
        ] as const) {
            const draft = run(base, { type: "composer", patch: { name, dayCount: days } }, { type: "applyComposer" })
            expect(draft.months).toHaveLength(1)
            expect(draft.composer?.errors.length).toBeGreaterThan(0)
            expect(draft.composer?.name).toBe(name)
        }
    })

    it("accepts the inclusive bounds 1 and 400 and a 100-character name", () => {
        let draft = addMonth(named(), "a", "1")
        draft = addMonth(draft, "b", "400")
        draft = addMonth(draft, "c".repeat(100), " 12 ")
        expect(draft.months.map((m) => m.dayCount)).toEqual(["30", "1", "400", "12"])
    })

    it("stops at 60 months and hides the Add a month panel", () => {
        let draft = named()
        for (let i = 2; i <= 60; i += 1) draft = addMonth(draft, `Month ${i}`)
        expect(draft.months).toHaveLength(60)
        expect(draft.composer).toBeNull()
        // The panel returns, empty, as soon as there is room again.
        expect(run(draft, { type: "remove", key: "m60" }).composer).toEqual({ name: "", dayCount: "30", errors: [] })
    })
})

describe("edit", () => {
    it("changes only the buffer until applied, and the row's own name is not a duplicate", () => {
        let draft = addMonth(named(), "Thaw")
        draft = run(draft, { type: "openEdit", key: "m2" }, { type: "edit", patch: { name: "Melt" } })
        expect(draft.months[1]!.name).toBe("Thaw")
        draft = run(draft, { type: "edit", patch: { name: "thaw" } }, { type: "applyEdit" })
        expect(draft.months[1]!.name).toBe("thaw")
        expect(draft.editing).toBeNull()
    })

    it("rejects a name another month has and keeps the editor open", () => {
        let draft = addMonth(named(), "Thaw")
        draft = run(draft, { type: "openEdit", key: "m2" }, { type: "edit", patch: { name: "FROST" } }, { type: "applyEdit" })
        expect(draft.editing?.buffer.errors.map((e) => e.fieldId)).toEqual([monthNameId("m2")])
        expect(draft.months[1]!.name).toBe("Thaw")
    })

    it("cancel leaves the row as it was", () => {
        const draft = run(
            named(),
            { type: "openEdit", key: "m1" },
            { type: "edit", patch: { name: "Other", dayCount: "9" } },
            { type: "cancelEdit" },
        )
        expect(draft.months[0]).toEqual({ key: "m1", name: "Frost", dayCount: "30" })
        expect(draft.editing).toBeNull()
    })

    it("never lets the Add a month panel block or be replaced by a row editor", () => {
        const draft = run(named(), { type: "composer", patch: { name: "Half" } }, { type: "openEdit", key: "m1" })
        expect(draft.editing?.key).toBe("m1")
        expect(draft.composer?.name).toBe("Half")
        expect(draft.notice).toBeNull()
        expect(blockingForm(draft)).toBeNull()
    })

    it("opens one row editor at a time: an unchanged one is closed, one with unapplied values blocks with a notice", () => {
        let draft = addMonth(named(), "Thaw")
                // Unchanged editor on m1 is replaced by m2's.
        draft = run(draft, { type: "openEdit", key: "m1" }, { type: "openEdit", key: "m2" })
        expect(draft.editing?.key).toBe("m2")
        // A changed editor on m2 blocks opening m1.
        draft = run(draft, { type: "edit", patch: { name: "Melt" } }, { type: "openEdit", key: "m1" })
        expect(draft.editing?.key).toBe("m2")
        expect(draft.notice).toMatch(/month 2/)
        expect(draft.composer).not.toBeNull()
        expect(blockingForm(draft)).toEqual({ kind: "edit", key: "m2", position: 2 })
    })
})

describe("remove", () => {
    it("keeps the other rows' keys, values and error ids on the same rows", () => {
        let draft = addMonth(addMonth(named(), "Thaw"), "Bloom", "28")
        draft = run(draft, { type: "remove", key: "m2" })
        expect(draft.months.map((m) => [m.key, m.name, m.dayCount])).toEqual([
            ["m1", "Frost", "30"],
            ["m3", "Bloom", "28"],
        ])
        const broken = run(draft, { type: "openEdit", key: "m3" }, { type: "edit", patch: { dayCount: "0" } }, { type: "applyEdit" })
        expect(broken.editing?.buffer.errors.map((e) => e.fieldId)).toEqual([monthDaysId("m3")])
    })

    it("never reuses a key", () => {
        let draft = addMonth(named(), "Thaw")
        draft = run(draft, { type: "remove", key: "m2" })
        expect(addMonth(draft, "Again").months.map((m) => m.key)).toEqual(["m1", "m3"])
    })

    it("can remove the last month, leaving none, and drops the editor of a removed row", () => {
        const empty = run(named(), { type: "remove", key: "m1" })
        expect(empty.months).toEqual([])
        expect(ids({ ...empty, name: "Common" })).toEqual(["calendar-months"])
        let draft = addMonth(named(), "Thaw")
        draft = run(draft, { type: "openEdit", key: "m2" }, { type: "remove", key: "m2" })
        expect(draft.editing).toBeNull()
    })
})

describe("year length", () => {
    it("sums the committed months and ignores an open form", () => {
        const draft = run(addMonth(named(), "Thaw", "31"), { type: "composer", patch: { name: "Half", dayCount: "100" } })
        expect(yearLength(draft)).toEqual({ kind: "known", days: 61 })
        expect(yearLengthText(draft)).toBe("Year length: 61 days.")
        expect(yearLengthText(named())).toBe("Year length: 30 days.")
    })

    it("says which months are not countable instead of totalling a guess", () => {
        const draft: CalendarDraft = {
            ...named(),
            months: [
                { key: "a", name: "A", dayCount: "10" },
                { key: "b", name: "B", dayCount: "" },
                { key: "c", name: "C", dayCount: "401" },
            ],
        }
        expect(yearLength(draft)).toEqual({ kind: "unknown", positions: [2, 3] })
        expect(yearLengthText(draft)).toMatch(/not known yet: months 2, 3 need/)
    })
})

describe("whole-draft validation", () => {
    it("is clean for a valid draft", () => {
        expect(validateCalendarDraft(named())).toEqual([])
    })

    it("reports every step at once, in step order", () => {
        const draft: CalendarDraft = {
            ...initialDraft(),
            daysPerWeek: "31",
            epochLabel: "e".repeat(201),
            description: "d".repeat(4001),
        }
        expect(ids(draft)).toEqual([
            "calendar-name",
            "calendar-description",
            "calendar-epoch",
            "calendar-days-per-week",
            "calendar-months",
        ])
    })

    it("checks days per week: blank is fine, 1 and 30 are fine, 0, 31 and 7.5 are not", () => {
        for (const ok of ["", " ", "1", "30"]) expect(ids({ ...named(), daysPerWeek: ok })).toEqual([])
        for (const bad of ["0", "31", "7.5", "x", "-1"]) {
            expect(ids({ ...named(), daysPerWeek: bad })).toEqual(["calendar-days-per-week"])
        }
    })

    it("flags repeated names case-insensitively on the later month, with its current position", () => {
        let draft = addMonth(addMonth(named(), "Thaw"), "Bloom")
        draft = run(draft, { type: "remove", key: "m2" })
        const duplicated: CalendarDraft = {
            ...draft,
            months: [...draft.months, { key: "m9", name: " frost ", dayCount: "5" }],
        }
        const errors = validateCalendarDraft(duplicated)
        expect(errors).toEqual([
            { fieldId: monthNameId("m9"), message: "Month 3 repeats a name. Month names must be unique." },
        ])
    })

    it("refuses to drop an unapplied month form: it is reported, not ignored", () => {
        const composing = run(named(), { type: "composer", patch: { name: "Thaw" } })
        expect(ids(composing)).toEqual([COMPOSER_NAME_ID])
        const editing = run(named(), { type: "openEdit", key: "m1" }, { type: "edit", patch: { dayCount: "9" } })
        expect(ids(editing)).toEqual([monthNameId("m1")])
        expect(validateCalendarDraft(editing)[0]!.message).toMatch(/Month 1 has changes/)
    })

    it("does not report an untouched open form, and reports each field once", () => {
        expect(ids(named())).toEqual([])
        const unnamedEdited = run(initialDraft(), { type: "edit", patch: { name: "X" } })
        const list = ids(unnamedEdited)
        expect(new Set(list).size).toBe(list.length)
    })
})

describe("request body", () => {
    it("is the ordered, trimmed calendar with nulls for blanks, and only committed months", () => {
        let draft = run(
            addMonth(named(" Frost "), "Thaw", "31"),
            { type: "composer", patch: { name: "Unfinished" } },
            { type: "field", field: "name", value: " Common " },
            { type: "field", field: "daysPerWeek", value: " 7 " },
            { type: "field", field: "epochLabel", value: "  " },
        )
        draft = run(draft, { type: "field", field: "description", value: " " })
        expect(toCalendarBody(draft)).toEqual({
            name: "Common",
            description: null,
            days_per_week: 7,
            epoch_label: null,
            months: [
                { name: "Frost", day_count: 30 },
                { name: "Thaw", day_count: 31 },
            ],
        })
    })
})

describe("field ids", () => {
    it("maps a field to its step and month", () => {
        expect(stepForField("calendar-name")).toBe("basics")
        expect(stepForField("calendar-days-per-week")).toBe("basics")
        expect(stepForField("calendar-months")).toBe("months")
        expect(stepForField(COMPOSER_NAME_ID)).toBe("months")
        expect(stepForField(monthDaysId("m4"))).toBe("months")
        expect(monthKeyOfField(monthDaysId("m4"))).toBe("m4")
        expect(monthKeyOfField("calendar-name")).toBeNull()
    })
})

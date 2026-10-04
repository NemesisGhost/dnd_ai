import { describe, expect, it } from "vitest"
import type { LocationAuthoringView, LocationCategoryOption } from "../types/locationAuthoring"
import {
    EMPTY_LOCATION_FORM,
    sameValues,
    statusDetail,
    toFieldsBody,
    validateLocationForm,
    valuesFromView,
} from "./locationForm"

const settlement: LocationCategoryOption = {
    code: "settlement",
    label: "Settlement",
    fields: [
        { name: "population", kind: "integer", label: "Population", max_length: null, minimum: 0, maximum: 2147483647 },
    ],
}
const region: LocationCategoryOption = { code: "region", label: "Region", fields: [] }
const building: LocationCategoryOption = {
    code: "building",
    label: "Building",
    fields: [
        { name: "building_use", kind: "text", label: "Use", max_length: 200, minimum: null, maximum: null },
    ],
}

const filled = { ...EMPTY_LOCATION_FORM, category: "settlement", name: "Hollow" }

describe("validateLocationForm", () => {
    it("requires a category on create and a name always", () => {
        const ids = validateLocationForm(EMPTY_LOCATION_FORM, undefined, { requireCategory: true }).map(
            (e) => e.fieldId,
        )
        expect(ids).toEqual(["location-category", "location-name"])
        expect(
            validateLocationForm(EMPTY_LOCATION_FORM, undefined, { requireCategory: false }).map((e) => e.fieldId),
        ).toEqual(["location-name"])
    })

    it("checks population only when the category carries it", () => {
        for (const bad of ["-1", "1.5", "abc", "2147483648", "1e3"]) {
            const errors = validateLocationForm({ ...filled, population: bad }, settlement, {
                requireCategory: true,
            })
            expect(errors.map((e) => e.fieldId)).toEqual(["location-population"])
        }
        expect(validateLocationForm({ ...filled, population: "1200" }, settlement, { requireCategory: true })).toEqual([])
        expect(validateLocationForm({ ...filled, population: "abc" }, region, { requireCategory: true })).toEqual([])
    })

    it("bounds the summary, the use, and the change note", () => {
        expect(
            validateLocationForm({ ...filled, summary: "x".repeat(4001) }, region, { requireCategory: true })[0]!
                .message,
        ).toMatch(/^Summary must be 4000/)
        expect(
            validateLocationForm({ ...filled, buildingUse: "x".repeat(201) }, building, { requireCategory: true })[0]!
                .fieldId,
        ).toBe("location-building-use")
        expect(
            validateLocationForm({ ...filled, changeNote: "x".repeat(1001) }, region, { requireCategory: true })[0]!
                .message,
        ).toMatch(/^Change note must be 1000/)
    })
})

describe("toFieldsBody", () => {
    it("trims, nulls blanks, and parses population", () => {
        expect(
            toFieldsBody({ ...filled, name: "  Hollow  ", summary: "  ", population: " 1200 " }, settlement),
        ).toEqual({
            name: "Hollow",
            summary: null,
            parent_location_id: null,
            population: 1200,
            building_use: null,
        })
    })

    it("never sends a typed field the category does not carry", () => {
        const body = toFieldsBody({ ...filled, population: "50", buildingUse: "inn" }, region)
        expect(body.population).toBeNull()
        expect(body.building_use).toBeNull()
    })

    it("sends the chosen parent's id", () => {
        const body = toFieldsBody({ ...filled, parent: { id: "p1", label: "Vale" } }, settlement)
        expect(body.parent_location_id).toBe("p1")
    })
})

describe("form state helpers", () => {
    const view: LocationAuthoringView = {
        location_id: "l1",
        name: "Hollow",
        summary: null,
        category: { code: "settlement", label: "Settlement" },
        parent: { location_id: "p1", name: "Vale", canon_status: "canon", lifecycle_status: "archived" },
        population: 10,
        building_use: null,
        canon_status: "draft",
        lifecycle_status: "active",
        row_version: 2,
        available_actions: ["update"],
        blocked_actions: [],
        field_locks: [],
    }

    it("maps a view to form values, labelling an archived parent", () => {
        expect(valuesFromView(view)).toEqual({
            category: "settlement",
            name: "Hollow",
            summary: "",
            parent: { id: "p1", label: "Vale", detail: "Archived" },
            population: "10",
            buildingUse: "",
            changeNote: "",
        })
    })

    it("compares values ignoring surrounding whitespace", () => {
        const base = valuesFromView(view)
        expect(sameValues(base, { ...base, name: "  Hollow " })).toBe(true)
        expect(sameValues(base, { ...base, population: "11" })).toBe(false)
        expect(sameValues(base, { ...base, parent: null })).toBe(false)
    })

    it("describes statuses in words", () => {
        expect(statusDetail("proposed", "active")).toBe("In review")
        expect(statusDetail("canon", "archived")).toBe("Archived")
    })
})

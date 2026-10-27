import { describe, expect, it } from "vitest"
import type { WorldCategory } from "../types/world"
import {
    parseWorldCategory,
    WORLD_CATEGORY_NAV,
    worldCategoryNavItem,
} from "./worldCategories"

// Every category the API returns (and the type union names). Typed as a
// Record so adding a WorldCategory without listing it here fails to compile.
const everyApiCategory: Record<WorldCategory, true> = {
    location: true,
    character: true,
    organization: true,
    religion: true,
    item: true,
    event: true,
}

describe("World category navigation", () => {
    it("starts with All entries and keeps every API category reachable exactly once", () => {
        expect(WORLD_CATEGORY_NAV[0]).toMatchObject({ category: null, label: "All entries" })

        const reachable = WORLD_CATEGORY_NAV.flatMap((item) =>
            item.category === null ? [] : [item.category],
        )

        expect([...reachable].sort()).toEqual(Object.keys(everyApiCategory).sort())
    })

    it("names the readable groups", () => {
        expect(WORLD_CATEGORY_NAV.map((item) => [item.category, item.label])).toEqual([
            [null, "All entries"],
            ["location", "Locations"],
            ["character", "People"],
            ["organization", "Organizations"],
            ["religion", "Faiths"],
            ["item", "Items"],
            ["event", "Events"],
        ])
    })

    it("parses valid category values and falls back to All entries for anything else", () => {
        for (const category of Object.keys(everyApiCategory)) {
            expect(parseWorldCategory(category)).toBe(category)
        }

        expect(parseWorldCategory(null)).toBeNull()
        expect(parseWorldCategory("")).toBeNull()
        expect(parseWorldCategory("relationship")).toBeNull()
        expect(parseWorldCategory("Location")).toBeNull()
        expect(parseWorldCategory("constructor")).toBeNull()
    })

    it("looks up the nav entry for a category", () => {
        expect(worldCategoryNavItem("religion").label).toBe("Faiths")
        expect(worldCategoryNavItem(null).label).toBe("All entries")
    })
})

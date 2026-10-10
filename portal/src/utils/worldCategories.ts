import type { WorldCategory } from "../types/world"

// The World browser's local category navigation. Each entry maps a readable
// group onto exactly one server-side World Explorer category (the API's
// `WORLD_CATEGORY_TYPE_CODES` groups many entity types under each), so the
// navigation never needs a schema or API change. "All entries" is `null`.
export interface WorldCategoryNavItem {
    category: WorldCategory | null
    label: string
    // Shown in empty states: "No <noun> match ..." / "...in <noun>".
    noun: string
}

export const WORLD_CATEGORY_NAV: readonly WorldCategoryNavItem[] = [
    { category: null, label: "All entries", noun: "entries" },
    { category: "location", label: "Locations", noun: "locations" },
    { category: "character", label: "People", noun: "people" },
    { category: "organization", label: "Organizations", noun: "organizations" },
    { category: "religion", label: "Faiths", noun: "faiths" },
    { category: "item", label: "Items", noun: "items" },
    { category: "event", label: "Events", noun: "events" },
]

const categoryByValue: ReadonlyMap<string, WorldCategory> = new Map(
    WORLD_CATEGORY_NAV.flatMap((item) =>
        item.category === null ? [] : [[item.category, item.category] as const],
    ),
)

/** Reads a `?category=` value; anything unknown falls back to All entries. */
export function parseWorldCategory(raw: string | null): WorldCategory | null {
    return raw === null ? null : (categoryByValue.get(raw) ?? null)
}

export function worldCategoryNavItem(
    category: WorldCategory | null,
): WorldCategoryNavItem {
    return (
        WORLD_CATEGORY_NAV.find((item) => item.category === category) ??
        WORLD_CATEGORY_NAV[0]!
    )
}

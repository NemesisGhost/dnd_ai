import type { ItemView } from "../types/items"
import { humanizeCode } from "./humanize"

// How an item's runtime state is worded, for the editor's In play summary and the reader's.
// Both read `campaign.item_state` and friends on the campaign's timeline. Nothing here invents a
// value: a field the record does not hold is absent, never replaced by a default.

// Whether the timeline records anything about the item. The authoring read fills in a quantity of 1
// and "not equipped" when there is no state row (`COALESCE`), so those defaults are not evidence.
// A last-event token proves a command ran (even one that left the item unplaced, which is a
// supported release). Rows written without an event (seed data, an older import) still hold real
// custody, so the facts that can exist solely as a record count too: a place, an owner, an
// attunement, damage, a non-default quantity, equipped or destroyed.
export function hasRecordedState(
    view: Pick<
        ItemView,
        | "last_event_id"
        | "holder"
        | "container"
        | "location"
        | "owner"
        | "attuned_to"
        | "condition_percentage"
        | "quantity"
        | "is_equipped"
        | "is_destroyed"
    >,
): boolean {
    return (
        view.last_event_id !== null ||
        isPlaced(view) ||
        view.owner !== null ||
        view.attuned_to !== null ||
        view.condition_percentage !== null ||
        view.quantity !== 1 ||
        view.is_equipped ||
        view.is_destroyed
    )
}

// The condition is empty until a damage or repair is first recorded. That is "no damage recorded",
// which is not the same as a recorded 100%, so the two are worded differently.
export function conditionText(percentage: number | null): string {
    return percentage === null ? "No damage recorded" : `${percentage}%`
}

export type PlacementKind = "carried" | "inside" | "lying" | "unplaced"

export function placementOf(view: Pick<ItemView, "holder" | "container" | "location">): {
    kind: PlacementKind
    text: string
} {
    if (view.holder !== null) return { kind: "carried", text: `Carried by ${view.holder.name}` }
    if (view.container !== null) return { kind: "inside", text: `Inside ${view.container.name}` }
    if (view.location !== null) return { kind: "lying", text: `Lying at ${view.location.name}` }
    return { kind: "unplaced", text: "Not placed" }
}

export const isPlaced = (view: Pick<ItemView, "holder" | "container" | "location">): boolean =>
    placementOf(view).kind !== "unplaced"

// What taking the item out of its present place means, said before the person chooses.
export function leavesText(view: Pick<ItemView, "holder" | "container" | "location">): string | null {
    if (view.holder !== null) return `${view.holder.name} will no longer carry it.`
    if (view.container !== null) return `It will be taken out of ${view.container.name}.`
    if (view.location !== null) return `It will no longer lie at ${view.location.name}.`
    return null
}

export const ownerName = (owner: ItemView["owner"]): string => (owner === null ? "No owner recorded" : owner.name)

export const rarityText = (rarity: string): string => humanizeCode(rarity)

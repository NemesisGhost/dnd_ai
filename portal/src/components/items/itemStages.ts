import type { ItemView } from "../../types/items"
import { isPlaced } from "../../utils/itemState"

// The item page is organised into stages, each with local sections. Stages and sections organise
// the interface only: they are never persisted, never call the API and are not lifecycle statuses.
// The item's real status is shown in the page header.

export type ItemStage = "prepare" | "publish" | "play"

export type ItemSection = "details" | "sources" | "publication" | "move" | "equipment" | "condition"

export interface ItemSectionInfo {
    key: ItemSection
    stage: ItemStage
    label: string
    purpose: string
}

export const ITEM_STAGES: readonly { key: ItemStage; label: string }[] = [
    { key: "prepare", label: "Prepare" },
    { key: "publish", label: "Review & publish" },
    { key: "play", label: "Use in play" },
]

export const ITEM_SECTIONS: readonly ItemSectionInfo[] = [
    {
        key: "details",
        stage: "prepare",
        label: "Details",
        purpose: "What this particular object is. The kind of item is fixed once it is created.",
    },
    {
        key: "sources",
        stage: "prepare",
        label: "Sources",
        purpose: "Where this item came from.",
    },
    {
        key: "publication",
        stage: "publish",
        label: "Publication",
        purpose: "Where the item is in its life, and the steps available to you.",
    },
    {
        key: "move",
        stage: "play",
        label: "Give or place",
        purpose: "Who has it, or where it lies. Each change is recorded as an event and saves on its own.",
    },
    {
        key: "equipment",
        stage: "play",
        label: "Equip & attune",
        purpose: "Whether the character carrying it has it equipped or is attuned to it.",
    },
    {
        key: "condition",
        stage: "play",
        label: "Use & condition",
        purpose: "Using it up, damaging or repairing it, or destroying it.",
    },
]

export const itemHeadingId = (key: ItemSection): string => `item-section-${key}-heading`

export const itemSectionInfo = (key: ItemSection): ItemSectionInfo =>
    ITEM_SECTIONS.find((s) => s.key === key) as ItemSectionInfo

export const itemStageOf = (key: ItemSection): ItemStage => itemSectionInfo(key).stage

export const itemSectionsOf = (stage: ItemStage): ItemSectionInfo[] =>
    ITEM_SECTIONS.filter((s) => s.stage === stage)

export const itemStageLabel = (stage: ItemStage): string =>
    (ITEM_STAGES.find((s) => s.key === stage) as { label: string }).label

// A valid section key, or null for anything missing or unknown.
export function parseItemSection(raw: string | null | undefined): ItemSection | null {
    return ITEM_SECTIONS.find((s) => s.key === raw)?.key ?? null
}

type StatusView = Pick<ItemView, "canon_status" | "lifecycle_status">

// Where an editor lands when the address names no section. Derived from the loaded record only;
// `null` (the read failed) opens the details.
export function defaultItemSection(view: StatusView | null): ItemSection {
    if (view === null) return "details"
    if (view.lifecycle_status === "archived") return "publication"
    switch (view.canon_status) {
        case "proposed":
        case "approved":
        case "superseded":
            return "publication"
        case "canon":
            return "move"
        default:
            return "details"
    }
}

export interface ItemGuidance {
    text: string
    section: ItemSection
}

type GuidanceView = Pick<
    ItemView,
    | "canon_status"
    | "lifecycle_status"
    | "available_actions"
    | "is_destroyed"
    | "holder"
    | "container"
    | "location"
    | "last_event_id"
>

// The one next step that is actually available, from the server's own lifecycle actions. Navigation
// only: the target is where the step lives, never an action.
export function itemGuidance(view: GuidanceView): ItemGuidance | null {
    const available = new Set(view.available_actions)
    const at = (text: string, section: ItemSection): ItemGuidance => ({ text, section })
    if (view.lifecycle_status === "archived") {
        return available.has("restore") ? at("Restore it", "publication") : null
    }
    if (view.canon_status === "superseded") return null
    if (available.has("publish")) return at("Publish it", "publication")
    if (available.has("approve")) return at("Approve it", "publication")
    if (available.has("submit_for_review")) return at("Submit for review", "publication")
    if (view.canon_status === "rejected" && available.has("return_to_draft")) {
        return at("Return it to draft to rework it", "publication")
    }
    if (view.canon_status === "canon" && !view.is_destroyed && !isPlaced(view)) {
        return at("Give it to someone or place it", "move")
    }
    return null
}

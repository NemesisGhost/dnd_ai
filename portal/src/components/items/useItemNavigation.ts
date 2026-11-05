import { useStagedNavigation } from "../staged/useStagedNavigation"
import { ITEM_SECTIONS, itemStageOf } from "./itemStages"
import type { ItemSection, ItemStage } from "./itemStages"

const SECTIONS = ITEM_SECTIONS.map((section) => ({ key: section.key, stage: itemStageOf(section.key) }))

export interface ItemNavigation {
    section: ItemSection
    stage: ItemStage
    // The address (query only) that opens a section. Every other query parameter is carried along.
    sectionHref: (key: ItemSection) => string
    // The address of a stage: its remembered section, else its first.
    stageHref: (stage: ItemStage) => string
}

// The current section lives in `?section=`; the stage follows from it. The shared staged navigation
// owns the mechanics: a user's change pushes a history entry (Back and Forward walk the sections);
// fixing a missing or unknown value replaces it and keeps the entry's state (the task, the
// collection the item was opened from, the entry stamp). The query is the only thing that changes,
// so the page stays mounted and drafts survive. `ready` holds the normalisation back until the
// default can be derived from the loaded record.
export function useItemNavigation(defaultSection: ItemSection, { ready }: { ready: boolean }): ItemNavigation {
    return useStagedNavigation<ItemStage, ItemSection>(SECTIONS, defaultSection, { ready })
}

import { useEffect, useState } from "react"
import { useLocation, useSearchParams } from "react-router"
import { itemSectionsOf, itemStageOf, parseItemSection } from "./itemStages"
import type { ItemSection, ItemStage } from "./itemStages"

type Remembered = Partial<Record<ItemStage, ItemSection>>

export interface ItemNavigation {
    section: ItemSection
    stage: ItemStage
    // The address (query only) that opens a section. Every other query parameter is carried along.
    sectionHref: (key: ItemSection) => string
    // The address of a stage: its remembered section, else its first.
    stageHref: (stage: ItemStage) => string
}

// The current section lives in `?section=`; the stage follows from it. A user's change pushes a
// history entry (Back and Forward walk the sections); fixing a missing or unknown value replaces
// it. The query is the only thing that changes, so the page stays mounted and drafts survive.
// `ready` holds the normalisation back until the default can be derived from the loaded record.
export function useItemNavigation(defaultSection: ItemSection, { ready }: { ready: boolean }): ItemNavigation {
    const [params, setParams] = useSearchParams()
    // The router state names where the item was opened from; replacing the address must keep it.
    const { state } = useLocation()
    const parsed = parseItemSection(params.get("section"))
    const section = parsed ?? defaultSection
    const stage = itemStageOf(section)
    const [remembered, setRemembered] = useState<Remembered>({})

    useEffect(() => {
        if (ready && parsed === null) {
            const next = new URLSearchParams(params)
            next.set("section", section)
            setParams(next, { replace: true, state })
        }
    }, [ready, parsed, section, params, setParams, state])

    // Remember the section last shown in each stage (adjusted during render, not in an effect).
    if (remembered[stage] !== section) {
        setRemembered({ ...remembered, [stage]: section })
    }

    const sectionHref = (key: ItemSection): string => {
        const next = new URLSearchParams(params)
        next.set("section", key)
        return `?${next.toString()}`
    }
    const stageHref = (target: ItemStage): string =>
        sectionHref(target === stage ? section : (remembered[target] ?? itemSectionsOf(target)[0]!.key))
    return { section, stage, sectionHref, stageHref }
}

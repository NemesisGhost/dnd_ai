import { useEffect, useState } from "react"
import { useSearchParams } from "react-router"
import type { CampaignSessionDetail } from "../../types/campaignSession"
import { defaultSection, parseSection, sectionsOf, stageOf } from "./runStages"
import type { SectionKey, Stage } from "./runStages"

type Remembered = Partial<Record<Stage, SectionKey>>

export interface RunNavigation {
    section: SectionKey
    stage: Stage
    // The address (query only) that opens a section.
    sectionHref: (key: SectionKey) => string
    // The address of a stage: its remembered section, else its first.
    stageHref: (stage: Stage) => string
}

// The current section lives in `?section=`; the stage follows from it. A user's change pushes a
// history entry (Back and Forward walk the sections); fixing a missing or unknown value replaces
// it. The query is the only thing that changes, so the page stays mounted and drafts survive.
export function useRunNavigation(
    session: Pick<CampaignSessionDetail, "status_code" | "play_status">,
): RunNavigation {
    const [params, setParams] = useSearchParams()
    const parsed = parseSection(params.get("section"))
    const section = parsed ?? defaultSection(session)
    const stage = stageOf(section)
    const [remembered, setRemembered] = useState<Remembered>({})

    useEffect(() => {
        if (parsed === null) {
            setParams({ section }, { replace: true })
        }
    }, [parsed, section, setParams])

    // Remember the section last shown in each stage (adjusted during render, not in an effect).
    if (remembered[stage] !== section) {
        setRemembered({ ...remembered, [stage]: section })
    }

    const sectionHref = (key: SectionKey): string => `?section=${key}`
    const stageHref = (target: Stage): string =>
        sectionHref(target === stage ? section : (remembered[target] ?? sectionsOf(target)[0]!.key))
    return { section, stage, sectionHref, stageHref }
}

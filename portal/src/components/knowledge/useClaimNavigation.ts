import { useEffect, useState } from "react"
import { useLocation, useSearchParams } from "react-router"
import { claimSectionsOf, claimStageOf, parseClaimSection } from "./claimStages"
import type { ClaimSection, ClaimStage } from "./claimStages"

type Remembered = Partial<Record<ClaimStage, ClaimSection>>

export interface ClaimNavigation {
    section: ClaimSection
    stage: ClaimStage
    // The address (query only) that opens a section. Every other query parameter (the character
    // and party perspective) is carried along.
    sectionHref: (key: ClaimSection) => string
    // The address of a stage: its remembered section, else its first.
    stageHref: (stage: ClaimStage) => string
}

// The old fragments (#claim, #who-knows) name a section too.
const sectionOfHash = (hash: string): ClaimSection | null => parseClaimSection(hash.replace(/^#/, ""))

// The current section lives in `?section=`; the stage follows from it. A user's change pushes a
// history entry (Back and Forward walk the sections); fixing a missing or unknown value, or an old
// fragment, replaces it. The query is the only thing that changes, so the page stays mounted and
// drafts survive. `ready` holds the normalisation back until the default can be derived from the
// loaded record, and `enabled` is false for a reader, whose address is left alone.
export function useClaimNavigation(
    defaultSection: ClaimSection,
    { ready, enabled }: { ready: boolean; enabled: boolean },
): ClaimNavigation {
    const [params, setParams] = useSearchParams()
    const { hash } = useLocation()
    const parsed = parseClaimSection(params.get("section"))
    const legacy = parsed === null ? sectionOfHash(hash) : null
    const section = parsed ?? legacy ?? defaultSection
    const stage = claimStageOf(section)
    const [remembered, setRemembered] = useState<Remembered>({})

    useEffect(() => {
        if (enabled && ready && parsed === null) {
            const next = new URLSearchParams(params)
            next.set("section", section)
            setParams(next, { replace: true })
        }
    }, [enabled, ready, parsed, section, params, setParams])

    // Remember the section last shown in each stage (adjusted during render, not in an effect).
    if (remembered[stage] !== section) {
        setRemembered({ ...remembered, [stage]: section })
    }

    const sectionHref = (key: ClaimSection): string => {
        const next = new URLSearchParams(params)
        next.set("section", key)
        return `?${next.toString()}`
    }
    const stageHref = (target: ClaimStage): string =>
        sectionHref(target === stage ? section : (remembered[target] ?? claimSectionsOf(target)[0]!.key))
    return { section, stage, sectionHref, stageHref }
}

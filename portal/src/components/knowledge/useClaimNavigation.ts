import { useLocation, useSearchParams } from "react-router"
import { retainedState } from "../../navigation/breadcrumbModel"
import type { CrumbState } from "../../navigation/breadcrumbModel"
import { useStagedNavigation } from "../staged/useStagedNavigation"
import { CLAIM_SECTIONS, claimStageOf, parseClaimSection } from "./claimStages"
import type { ClaimSection, ClaimStage } from "./claimStages"

export interface ClaimNavigation {
    section: ClaimSection
    stage: ClaimStage
    // The address (query only) that opens a section. Every other query parameter (the character and
    // party perspective) is carried along.
    sectionHref: (key: ClaimSection) => string
    // The address of a stage: its remembered section, else its first.
    stageHref: (stage: ClaimStage) => string
    // The router state every in-page link carries so that moving between sections keeps the task the
    // claim was opened in (undefined after a direct entry, where the destination's defaults apply).
    linkState: CrumbState | undefined
}

// The old fragments (#claim, #who-knows) name a section too.
const sectionOfHash = (hash: string): ClaimSection | null => parseClaimSection(hash.replace(/^#/, ""))

// The current section lives in `?section=`; the stage follows from it. The shared staged navigation
// owns the mechanics (a user's change pushes a history entry; fixing a missing or unknown value
// replaces it and keeps the entry's state, the task and the stamp; the query is the only thing that
// changes, so the page stays mounted and drafts survive). Claim-specific: `ready` holds the
// normalisation back until the default can be derived from the loaded record, `enabled` is false for a
// reader, whose address is left alone, and `allowed` limits the sections the caller may use (any other
// named by the address is unknown and replaced by the default). An old fragment names the default when
// the address names no usable section.
export function useClaimNavigation(
    defaultSection: ClaimSection,
    {
        ready,
        enabled,
        allowed,
    }: {
        ready: boolean
        enabled: boolean
        // Omitted means every section.
        allowed?: readonly ClaimSection[]
    },
): ClaimNavigation {
    const [params] = useSearchParams()
    const { pathname, state, hash } = useLocation()
    const sections = CLAIM_SECTIONS.filter((section) => allowed === undefined || allowed.includes(section.key)).map(
        (section) => ({ key: section.key, stage: claimStageOf(section.key) }),
    )
    const named = parseClaimSection(params.get("section"))
    const namedUsable = named !== null && sections.some((section) => section.key === named)
    const legacy = namedUsable ? null : sectionOfHash(hash)
    const legacyUsable = legacy !== null && sections.some((section) => section.key === legacy) ? legacy : null
    const nav = useStagedNavigation<ClaimStage, ClaimSection>(sections, legacyUsable ?? defaultSection, {
        ready: enabled && ready,
    })
    return { ...nav, linkState: retainedState(pathname, state) ?? undefined }
}

import { useLocation } from "react-router"
import { retainedState } from "../../navigation/breadcrumbModel"
import type { CrumbState } from "../../navigation/breadcrumbModel"
import { useStagedNavigation } from "../staged/useStagedNavigation"
import type { CampaignSessionDetail } from "../../types/campaignSession"
import { SECTIONS, defaultSection } from "./runStages"
import type { SectionKey, Stage } from "./runStages"

export interface RunNavigation {
    section: SectionKey
    stage: Stage
    // The address (query only) that opens a section.
    sectionHref: (key: SectionKey) => string
    // The address of a stage: its remembered section, else its first.
    stageHref: (stage: Stage) => string
    // The router state every in-page link carries so that moving between sections keeps the task the
    // session was opened in (null after a direct entry, where the destination's defaults apply).
    linkState: CrumbState | undefined
}

// The current section lives in `?section=`; the stage follows from it. The shared staged navigation
// owns the mechanics: a user's change pushes a history entry (Back and Forward walk the sections),
// fixing a missing or unknown value replaces it and keeps the entry's state (the task, and a selection
// arrival's stamp), and the query is the only thing that changes, so the page stays mounted and drafts
// survive.
export function useRunNavigation(
    session: Pick<CampaignSessionDetail, "status_code" | "play_status">,
): RunNavigation {
    const { pathname, state } = useLocation()
    const nav = useStagedNavigation<Stage, SectionKey>(SECTIONS, defaultSection(session), { ready: true })
    return { ...nav, linkState: retainedState(pathname, state) ?? undefined }
}

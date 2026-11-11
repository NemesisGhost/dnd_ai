import type { ReactNode } from "react"
import { SectionNav, SectionPanel, StageNav } from "../staged/StagedNav"
import { STAGES, panelHeadingId, sectionsOf, stageLabel } from "./runStages"
import type { SectionInfo, SectionKey, Stage } from "./runStages"

// The three stages. Links, because choosing one changes the address; none of them acts on the session.
export function RunStageNav({
    current,
    hrefFor,
    linkState,
}: {
    current: Stage
    hrefFor: (stage: Stage) => string
    linkState?: object
}) {
    return (
        <StageNav
            ariaLabel="Session stages"
            stages={STAGES}
            current={current}
            hrefFor={hrefFor}
            linkState={linkState}
        />
    )
}

// The sections of the current stage only.
export function RunSectionNav({
    stage,
    current,
    hrefFor,
    linkState,
}: {
    stage: Stage
    current: SectionKey
    hrefFor: (key: SectionKey) => string
    linkState?: object
}) {
    return (
        <SectionNav
            ariaLabel={`${stageLabel(stage)} sections`}
            sections={sectionsOf(stage)}
            current={current}
            hrefFor={hrefFor}
            linkState={linkState}
        />
    )
}

// One section: heading, purpose line and a visible boundary. Always mounted; the inactive ones
// are `hidden`, so a half-filled form keeps its state while another section is shown.
export function RunSectionPanel({
    section,
    active,
    children,
}: {
    section: SectionInfo
    active: boolean
    children: ReactNode
}) {
    return (
        <SectionPanel
            headingId={panelHeadingId(section.key)}
            label={section.label}
            purpose={section.purpose}
            active={active}
        >
            {children}
        </SectionPanel>
    )
}

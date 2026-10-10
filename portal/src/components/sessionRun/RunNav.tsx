import type { ReactNode } from "react"
import { Link } from "react-router"
import { SectionNav, SectionPanel, StageNav } from "../staged/StagedNav"
import { STAGES, panelHeadingId, sectionsOf, stageLabel } from "./runStages"
import type { SectionInfo, SectionKey, Stage } from "./runStages"

const enc = encodeURIComponent

// Sessions > [session title] > Run session. Page navigation only: the campaign context (world,
// timeline, campaign, perspective) is shown by the workspace frame and is not part of it.
export function RunBreadcrumb({
    campaignId,
    sessionId,
    title,
    from,
}: {
    campaignId: string
    sessionId: string
    title: string | null
    // Set on pages reached from the run page: the run page becomes a link back (to a section)
    // and `label` names the current page.
    from?: { section?: string; label: string }
}) {
    const campaign = `/app/${enc(campaignId)}`
    return (
        <nav className="authoring-page__breadcrumb" aria-label="Breadcrumb">
            <ol className="session-run__breadcrumb">
                <li>
                    <Link to={`${campaign}/sessions`}>Sessions</Link>
                </li>
                <li>
                    {title !== null ? (
                        <Link to={`${campaign}/sessions/${enc(sessionId)}`}>{title}</Link>
                    ) : (
                        "Session"
                    )}
                </li>
                {from === undefined ? (
                    <li aria-current="page">Run session</li>
                ) : (
                    <>
                        <li>
                            <Link
                                to={`${campaign}/sessions/${enc(sessionId)}/run${from.section ? `?section=${from.section}` : ""}`}
                            >
                                Run session
                            </Link>
                        </li>
                        <li aria-current="page">{from.label}</li>
                    </>
                )}
            </ol>
        </nav>
    )
}

// The three stages. Links, because choosing one changes the address; none of them acts on the session.
export function RunStageNav({ current, hrefFor }: { current: Stage; hrefFor: (stage: Stage) => string }) {
    return <StageNav ariaLabel="Session stages" stages={STAGES} current={current} hrefFor={hrefFor} />
}

// The sections of the current stage only.
export function RunSectionNav({
    stage,
    current,
    hrefFor,
}: {
    stage: Stage
    current: SectionKey
    hrefFor: (key: SectionKey) => string
}) {
    return (
        <SectionNav
            ariaLabel={`${stageLabel(stage)} sections`}
            sections={sectionsOf(stage)}
            current={current}
            hrefFor={hrefFor}
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

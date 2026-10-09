import type { ReactNode } from "react"
import { Link } from "react-router"
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
export function RunStageNav({
    current,
    hrefFor,
}: {
    current: Stage
    hrefFor: (stage: Stage) => string
}) {
    return (
        <nav aria-label="Session stages" className="session-run__stages">
            <ol>
                {STAGES.map((stage, index) => (
                    <li key={stage.key}>
                        <Link
                            to={hrefFor(stage.key)}
                            aria-current={stage.key === current ? "step" : undefined}
                            className={
                                stage.key === current
                                    ? "session-run__stage session-run__stage--current"
                                    : "session-run__stage"
                            }
                        >
                            {index + 1}. {stage.label}
                        </Link>
                    </li>
                ))}
            </ol>
        </nav>
    )
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
        <nav aria-label={`${stageLabel(stage)} sections`} className="session-run__sections">
            <ul>
                {sectionsOf(stage).map((section) => (
                    <li key={section.key}>
                        <Link
                            to={hrefFor(section.key)}
                            aria-current={section.key === current ? "page" : undefined}
                            className={
                                section.key === current
                                    ? "session-run__section-link session-run__section-link--current"
                                    : "session-run__section-link"
                            }
                        >
                            {section.label}
                        </Link>
                    </li>
                ))}
            </ul>
        </nav>
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
        <section
            className="session-run__panel"
            aria-labelledby={panelHeadingId(section.key)}
            hidden={!active}
        >
            <h2 id={panelHeadingId(section.key)} tabIndex={-1}>
                {section.label}
            </h2>
            <p className="authoring-page__lead">{section.purpose}</p>
            {children}
        </section>
    )
}

import type { ReactNode } from "react"
import { Link } from "react-router"

// Stage and section navigation shared by the staged pages (Run Session, Knowledge claim). The
// markup keeps the `session-run__*` classes so the one stylesheet serves both pages. Stages and
// sections are presentation only: these are links that change the address, never actions.

export interface StageDef<S extends string> {
    key: S
    label: string
}

export interface SectionDef<K extends string> {
    key: K
    label: string
    purpose: string
}

// The stages. Links, because choosing one changes the address and nothing else.
export function StageNav<S extends string>({
    ariaLabel,
    stages,
    current,
    hrefFor,
}: {
    ariaLabel: string
    stages: readonly StageDef<S>[]
    current: S
    hrefFor: (stage: S) => string
}) {
    return (
        <nav aria-label={ariaLabel} className="session-run__stages">
            <ol>
                {stages.map((stage, index) => (
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
export function SectionNav<K extends string>({
    ariaLabel,
    sections,
    current,
    hrefFor,
}: {
    ariaLabel: string
    sections: readonly SectionDef<K>[]
    current: K
    hrefFor: (key: K) => string
}) {
    return (
        <nav aria-label={ariaLabel} className="session-run__sections">
            <ul>
                {sections.map((section) => (
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
export function SectionPanel({
    headingId,
    label,
    purpose,
    active,
    wide = false,
    children,
}: {
    headingId: string
    label: string
    purpose: string
    active: boolean
    // Fill the content column instead of the Run Session panel's reading width.
    wide?: boolean
    children: ReactNode
}) {
    return (
        <section
            className={wide ? "session-run__panel session-run__panel--wide" : "session-run__panel"}
            aria-labelledby={headingId}
            hidden={!active}
        >
            <h2 id={headingId} tabIndex={-1}>
                {label}
            </h2>
            <p className="authoring-page__lead">{purpose}</p>
            {children}
        </section>
    )
}

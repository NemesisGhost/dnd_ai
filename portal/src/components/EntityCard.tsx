import type { ReactNode } from "react"
import { Link } from "react-router"

export interface EntityCardProps {
    /** Category/type label shown above the title. */
    eyebrow?: string
    title: string
    /** Optional short summary; omitted entirely when absent rather than
     * filling the card with a "Not recorded" placeholder. */
    summary?: string | null
    /** Two to four compact metadata facts. */
    metadata?: ReactNode[]
    status?: string | null
    /**
     * Detail route for the card's single navigation link. When omitted the
     * card renders as a non-interactive, visually consistent surface (used
     * when no independently reloadable detail contract exists yet).
     */
    to?: string
    /** Accessible name for the link; defaults to the title. */
    linkLabel?: string
    /** Router state carried on the card's link (e.g. where "Back" returns to). */
    linkState?: unknown
    /** Show the eyebrow under the title, as secondary information. */
    eyebrowAfterTitle?: boolean
    /** Content rendered below the card's link, never inside it — the place
     * for a secondary link of the card's own (e.g. a Knowledge subject). */
    footer?: ReactNode
    className?: string
}

// Shared collection-card visual primitive. Renders one <li> so CardGrid's
// <ul> stays a semantic list. A single real Link covers the card body when
// `to` is supplied; there is never a nested link or button inside it (a
// secondary link goes in `footer`, a sibling of that Link). Never
// accepts an arbitrary API object — every field here is explicitly selected
// by a domain-specific wrapper (WorldCard, KnowledgeCard, QuestCard, ...).
export function EntityCard({
    eyebrow,
    title,
    summary,
    metadata,
    status,
    to,
    linkLabel,
    linkState,
    eyebrowAfterTitle = false,
    footer,
    className,
}: EntityCardProps) {
    const cardClassName = className ? `entity-card ${className}` : "entity-card"

    const eyebrowElement = eyebrow !== undefined && (
        <p className="entity-card__eyebrow">{eyebrow}</p>
    )

    const body = (
        <>
            {!eyebrowAfterTitle && eyebrowElement}

            <p className="entity-card__title">{title}</p>

            {eyebrowAfterTitle && eyebrowElement}

            {summary !== undefined && summary !== null && summary !== "" && (
                <p className="entity-card__summary">{summary}</p>
            )}

            {metadata !== undefined && metadata.length > 0 && (
                <ul className="entity-card__metadata">
                    {metadata.map((item, index) => (
                        // Static, caller-ordered facts — index keys are safe.
                        <li key={index}>{item}</li>
                    ))}
                </ul>
            )}

            {status !== undefined && status !== null && (
                <p className="entity-card__status">{status}</p>
            )}
        </>
    )

    if (to !== undefined) {
        return (
            <li className={cardClassName}>
                <Link
                    to={to}
                    state={linkState}
                    className="entity-card__link"
                    aria-label={linkLabel ?? title}
                >
                    {body}
                </Link>
                {footer !== undefined && footer !== null && (
                    <div className="entity-card__footer">{footer}</div>
                )}
            </li>
        )
    }

    return (
        <li className={`${cardClassName} entity-card--static`}>
            {body}
            {footer !== undefined && footer !== null && footer}
        </li>
    )
}

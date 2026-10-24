import type { ReactNode } from "react"
import { Link } from "react-router"
import type { KnowledgeSubject } from "../types/knowledge"
import { knowledgeSubjectHref } from "../utils/knowledgeSubject"
import { describeWorldType } from "../utils/worldTypeLabel"

interface KnowledgeSubjectLinkProps {
    campaignId: string
    /** The server's authorized subject summary; nothing is rendered when
     * absent, so "no subject" and "a subject you may not see" look alike. */
    subject: KnowledgeSubject | null | undefined
    /** The perspective the Knowledge view was requested under — forwarded
     * only to a destination that reads it (a quest's party perspective). */
    characterId: string | null
    partyId: string | null
    /** "card" is the compact labelled area on a collection card; "claim"
     * is the prominent block on the claim page. */
    variant?: "card" | "claim"
    /** The claim page's subject editor, shown inside the same block as the link
     * (the block then appears even when there is no linked subject yet). */
    children?: ReactNode
    /** Claim page, editors: the name is plain text and opening the World entry is its own button,
     * so changing the subject and opening it are clearly different actions. */
    separateOpen?: boolean
    /** Buttons that sit with the selected subject (Change, Clear). */
    actions?: ReactNode
}

function describeSubjectType(subject: KnowledgeSubject): string {
    return subject.category === "quest"
        ? "Quest"
        : describeWorldType(subject.category, subject.entity_type_code)
}

// The labelled "About" area shared by Knowledge cards and the claim page: the
// subject's name (a real link to its own detail route, which re-authorizes it
// on arrival) and its type. Never shows a raw id.
export function KnowledgeSubjectLink({
    campaignId,
    subject,
    characterId,
    partyId,
    variant = "card",
    children,
    separateOpen = false,
    actions,
}: KnowledgeSubjectLinkProps) {
    const hasSubject = subject !== null && subject !== undefined
    if (!hasSubject && children === undefined) {
        return null
    }

    const label = variant === "claim" ? "About this World entry" : "About"
    if (!hasSubject) {
        return (
            <div className={`knowledge-about knowledge-about--${variant}`}>
                <p className="knowledge-about__label">{label}</p>
                {children}
            </div>
        )
    }

    const typeLabel = describeSubjectType(subject)
    const to = knowledgeSubjectHref(campaignId, subject, characterId, partyId)

    return (
        <div className={`knowledge-about knowledge-about--${variant}`}>
            <p className="knowledge-about__label">{label}</p>
            <div className="knowledge-about__row">
                <p className="knowledge-about__subject">
                    {separateOpen ? (
                        <strong className="knowledge-about__name">{subject.name}</strong>
                    ) : (
                        <Link to={to} className="knowledge-about__name">
                            {subject.name}
                        </Link>
                    )}{" "}
                    <span className="knowledge-about__type">{typeLabel}</span>
                </p>
                {separateOpen || actions !== undefined ? (
                    <div className="knowledge-about__actions">
                        {separateOpen ? (
                            <Link to={to} className="authoring-button">
                                Open World entry
                            </Link>
                        ) : null}
                        {actions}
                    </div>
                ) : null}
            </div>
            {children}
        </div>
    )
}

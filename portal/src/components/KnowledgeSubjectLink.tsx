import { Link } from "react-router"
import { questPerspectiveSearch } from "../hooks/useQuestPartyPerspective"
import type { KnowledgeSubject } from "../types/knowledge"
import { knowledgeSubjectPath } from "../utils/knowledgeSubject"
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
}: KnowledgeSubjectLinkProps) {
    if (subject === null || subject === undefined) {
        return null
    }

    const typeLabel = describeSubjectType(subject)
    const path = knowledgeSubjectPath(campaignId, subject)
    const to =
        subject.category === "quest"
            ? `${path}${questPerspectiveSearch(characterId, partyId)}`
            : path

    return (
        <div className={`knowledge-about knowledge-about--${variant}`}>
            <p className="knowledge-about__label">
                {variant === "claim" ? "About this World entry" : "About"}
            </p>
            <p className="knowledge-about__subject">
                <Link to={to} className="knowledge-about__name">
                    {subject.name}
                </Link>{" "}
                <span className="knowledge-about__type">{typeLabel}</span>
            </p>
        </div>
    )
}

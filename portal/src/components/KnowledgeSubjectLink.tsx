import { Link } from "react-router"
import { questPerspectiveSearch } from "../hooks/useQuestPartyPerspective"
import type { KnowledgeSubject } from "../types/knowledge"
import { knowledgeSubjectPath } from "../utils/knowledgeSubject"
import { describeWorldType } from "../utils/worldTypeLabel"

interface KnowledgeSubjectLinkProps {
    campaignId: string
    /** The server's authorized subject summary; the row is omitted when
     * absent, so "no subject" and "a subject you may not see" look alike. */
    subject: KnowledgeSubject | null | undefined
    /** The perspective the Knowledge view was requested under — forwarded
     * only to a destination that reads it (a quest's party perspective). */
    characterId: string | null
    partyId: string | null
}

function describeSubjectType(subject: KnowledgeSubject): string {
    return subject.category === "quest"
        ? "Quest"
        : describeWorldType(subject.category, subject.entity_type_code)
}

// The compact "About: <subject>" row shared by Knowledge cards and the
// Knowledge detail page. A real link to the subject's own detail route,
// which re-authorizes it on arrival; never shows a raw id.
export function KnowledgeSubjectLink({
    campaignId,
    subject,
    characterId,
    partyId,
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
        <p className="knowledge-subject">
            <span className="knowledge-subject__label">About:</span>{" "}
            <Link to={to}>{subject.name}</Link>{" "}
            <span className="knowledge-subject__type">({typeLabel})</span>
        </p>
    )
}

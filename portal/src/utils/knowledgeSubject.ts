import type { KnowledgeSubject } from "../types/knowledge"
import { questPerspectiveSearch } from "../hooks/useQuestPartyPerspective"

/** The existing detail route for a Knowledge subject: a World Explorer
 * entity under `world/:category/:id`, a quest under `quests/:id`. Carries no
 * perspective; a quest link adds its own (see KnowledgeSubjectLink). */
export function knowledgeSubjectPath(
    campaignId: string,
    subject: KnowledgeSubject,
): string {
    const base = `/app/${encodeURIComponent(campaignId)}`
    const id = encodeURIComponent(subject.entity_id)

    return subject.category === "quest"
        ? `${base}/quests/${id}`
        : `${base}/world/${subject.category}/${id}`
}

/** Where the subject's own page is, as the claim page links to it: the detail route, plus the
 * party perspective a quest reads. */
export function knowledgeSubjectHref(
    campaignId: string,
    subject: KnowledgeSubject,
    characterId: string | null,
    partyId: string | null,
): string {
    const path = knowledgeSubjectPath(campaignId, subject)
    return subject.category === "quest" ? `${path}${questPerspectiveSearch(characterId, partyId)}` : path
}

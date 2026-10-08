import type { KnowledgeSubject } from "../types/knowledge"

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

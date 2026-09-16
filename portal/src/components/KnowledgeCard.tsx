import type { KnowledgeListItem } from "../types/knowledge"
import { humanizeCode } from "../utils/humanize"
import { EntityCard } from "./EntityCard"

interface KnowledgeCardProps {
    campaignId: string
    item: KnowledgeListItem
    /** The currently selected party filter, carried into the detail link's
     * URL so a direct refresh/bookmark reproduces the same authorized
     * party-filtered view (UI_STYLE_GUIDE.md §11.2). */
    partyId: string | null
}

function buildDetailPath(
    campaignId: string,
    knowledgeItemId: string,
    partyId: string | null,
): string {
    const path =
        `/app/${encodeURIComponent(campaignId)}` +
        `/knowledge/${encodeURIComponent(knowledgeItemId)}`

    if (partyId === null) {
        return path
    }

    const searchParameters = new URLSearchParams({
        party_id: partyId,
    })

    return `${path}?${searchParameters.toString()}`
}

// Domain-specific wrapper mapping one authorized KnowledgeListItem into the
// shared EntityCard primitive. Never infers canonical truth from scope,
// sensitivity, confidence, or a null value — truth_status_code is shown
// only when the API itself returned it (UI_DESIGN.md §5.6).
export function KnowledgeCard({
    campaignId,
    item,
    partyId,
}: KnowledgeCardProps) {
    const metadata: string[] = [`Scope: ${humanizeCode(item.scope)}`]

    if (item.awareness_level !== null) {
        metadata.push(`Awareness: ${humanizeCode(item.awareness_level)}`)
    }

    if (item.confidence !== null) {
        metadata.push(`Confidence: ${item.confidence}%`)
    }

    if (item.willing_to_share !== null) {
        metadata.push(
            item.willing_to_share
                ? "Willing to share"
                : "Not willing to share",
        )
    }

    const status =
        item.truth_status_code !== null
            ? humanizeCode(item.truth_status_code)
            : null

    return (
        <EntityCard
            eyebrow={humanizeCode(item.knowledge_type_code)}
            title={item.statement}
            metadata={metadata}
            status={status}
            to={buildDetailPath(
                campaignId,
                item.knowledge_item_id,
                partyId,
            )}
            linkLabel={item.statement}
        />
    )
}

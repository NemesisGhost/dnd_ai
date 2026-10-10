import type { KnowledgeListItem } from "../types/knowledge"
import { humanizeCode } from "../utils/humanize"
import { EntityCard } from "./EntityCard"
import { KnowledgeSubjectLink } from "./KnowledgeSubjectLink"

interface KnowledgeCardProps {
    campaignId: string
    item: KnowledgeListItem
    /** The currently selected character perspective, carried into the
     * detail link's URL so a direct refresh/bookmark reproduces the same
     * authorized character-dependent view (UI_STYLE_GUIDE.md §11.2). */
    characterId: string | null
    /** The currently selected party filter, carried into the detail link's
     * URL so a direct refresh/bookmark reproduces the same authorized
     * party-filtered view (UI_STYLE_GUIDE.md §11.2). */
    partyId: string | null
    /** Opens the claim somewhere else (the Member preview keeps its own context in the address).
     * The subject link is then left out, because it would leave that context. */
    detailHref?: string
}

function buildDetailPath(
    campaignId: string,
    knowledgeItemId: string,
    characterId: string | null,
    partyId: string | null,
): string {
    const path =
        `/app/${encodeURIComponent(campaignId)}` +
        `/knowledge/${encodeURIComponent(knowledgeItemId)}`

    const searchParameters = new URLSearchParams()

    if (characterId !== null) {
        searchParameters.set("character_id", characterId)
    }

    if (partyId !== null) {
        searchParameters.set("party_id", partyId)
    }

    const query = searchParameters.toString()

    return query === "" ? path : `${path}?${query}`
}

// Domain-specific wrapper mapping one authorized KnowledgeListItem into the
// shared EntityCard primitive. The claim text is the card's content and its
// one link; the claim kind is a quiet secondary label. Scope and canonical
// truth are not repeated here: they live on the claim page, and truth is
// never inferred from scope, sensitivity, confidence, or a null value
// (UI_DESIGN.md §5.6). The labelled "About" area sits below the card's own
// link and appears only for the server's authorized subject summary, so
// opening the claim and opening its subject are separate actions.
export function KnowledgeCard({
    campaignId,
    item,
    characterId,
    partyId,
    detailHref,
}: KnowledgeCardProps) {
    const metadata: string[] = [humanizeCode(item.knowledge_type_code)]

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

    return (
        <EntityCard
            className="knowledge-card"
            title={item.statement}
            metadata={metadata}
            to={
                detailHref ??
                buildDetailPath(campaignId, item.knowledge_item_id, characterId, partyId)
            }
            linkLabel={item.statement}
            footer={
                detailHref !== undefined ||
                item.subject === null ||
                item.subject === undefined ? undefined : (
                    <KnowledgeSubjectLink
                        campaignId={campaignId}
                        subject={item.subject}
                        characterId={characterId}
                        partyId={partyId}
                        variant="card"
                    />
                )
            }
        />
    )
}

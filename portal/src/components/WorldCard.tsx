import type { WorldEntityCard } from "../types/world"
import { isWorldDetailCategory } from "../types/world"
import { describeWorldType } from "../utils/worldTypeLabel"
import { LifecycleBadge } from "./authoring/feedback"
import { EntityCard } from "./EntityCard"

interface WorldCardProps {
    campaignId: string
    entity: WorldEntityCard
}

// Domain-specific wrapper mapping one authorized WorldEntityCard list item
// into the shared EntityCard primitive. Becomes a navigable card only for
// categories with an independently loadable detail contract
// (UI_STYLE_GUIDE.md §10.2); "organization" (no display name in the detail
// response yet — see this workstream's report) stays a non-interactive,
// visually consistent card.
export function WorldCard({ campaignId, entity }: WorldCardProps) {
    const eyebrow = describeWorldType(entity.category, entity.entity_type_code)
    // Only a canon.edit holder's preview ever returns a non-canon or archived
    // row; the badge says so in text, never by color alone.
    const hiddenStatus =
        entity.lifecycle_status === "archived"
            ? "archived"
            : entity.canon_status !== undefined && entity.canon_status !== "canon"
              ? entity.canon_status
              : null

    const to = isWorldDetailCategory(entity.category)
        ? `/app/${encodeURIComponent(campaignId)}/world/${entity.category}/${encodeURIComponent(entity.entity_id)}`
        : undefined

    return (
        <EntityCard
            eyebrow={eyebrow}
            title={entity.name}
            summary={entity.summary}
            to={to}
            linkLabel={
                hiddenStatus === null
                    ? `${entity.name}, ${eyebrow}`
                    : `${entity.name}, ${eyebrow}, ${hiddenStatus}`
            }
            metadata={
                hiddenStatus === null ? undefined : [<LifecycleBadge key="status" status={hiddenStatus} />]
            }
        />
    )
}

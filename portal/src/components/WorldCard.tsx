import type { WorldCategory, WorldEntityCard } from "../types/world"
import { isWorldDetailCategory } from "../types/world"
import { humanizeCode } from "../utils/humanize"
import { EntityCard } from "./EntityCard"

const categoryLabels: Record<WorldCategory, string> = {
    location: "Location",
    character: "Character",
    organization: "Organization",
    religion: "Religion",
    item: "Item",
    event: "Event",
}

function describeEntity(entity: WorldEntityCard): string {
    const categoryLabel = categoryLabels[entity.category]
    const typeLabel = humanizeCode(entity.entity_type_code)

    return typeLabel === categoryLabel
        ? categoryLabel
        : `${categoryLabel} - ${typeLabel}`
}

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
    const eyebrow = describeEntity(entity)

    const to = isWorldDetailCategory(entity.category)
        ? `/app/${encodeURIComponent(campaignId)}/world/${entity.category}/${encodeURIComponent(entity.entity_id)}`
        : undefined

    return (
        <EntityCard
            eyebrow={eyebrow}
            title={entity.name}
            summary={entity.summary}
            to={to}
            linkLabel={`${entity.name}, ${eyebrow}`}
        />
    )
}

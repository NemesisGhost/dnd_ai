import type { WorldCategory } from "../types/world"
import { humanizeCode } from "./humanize"

const categoryLabels: Record<WorldCategory, string> = {
    location: "Location",
    character: "Character",
    organization: "Organization",
    religion: "Religion",
    item: "Item",
    event: "Event",
}

/** "Location - Settlement", or just "Religion" when the entity type adds
 * nothing to its World category. */
export function describeWorldType(
    category: WorldCategory,
    entityTypeCode: string,
): string {
    const categoryLabel = categoryLabels[category]
    const typeLabel = humanizeCode(entityTypeCode)

    return typeLabel === categoryLabel
        ? categoryLabel
        : `${categoryLabel} - ${typeLabel}`
}

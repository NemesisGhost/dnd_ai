import type {
    WorldCategory,
    WorldEntityCard,
    WorldEntityPage,
} from "../types/world"
import { UpdatingIndicator } from "./UpdatingIndicator"

const categoryLabels: Record<WorldCategory, string> = {
    location: "Location",
    character: "Character",
    organization: "Organization",
    religion: "Religion",
    item: "Item",
    event: "Event",
}

function formatEntityType(entityTypeCode: string): string {
    return entityTypeCode
        .split("_")
        .filter((word) => word.length > 0)
        .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
        .join(" ")
}

function describeEntity(entity: WorldEntityCard): string {
    const categoryLabel = categoryLabels[entity.category]
    const typeLabel = formatEntityType(entity.entity_type_code)

    return typeLabel === categoryLabel
        ? categoryLabel
        : `${categoryLabel} - ${typeLabel}`
}

interface WorldEntityListProps {
    page: WorldEntityPage
    refreshing?: boolean
    onNextPage: () => void
}

export function WorldEntityList({
    page,
    refreshing = false,
    onNextPage,
}: WorldEntityListProps) {
    return (
        <div
            role="region"
            aria-label="World entities results"
            aria-busy={refreshing}
        >
            {refreshing && <UpdatingIndicator />}

            {page.items.length > 0 ? (
                <ul aria-label="World entities">
                    {page.items.map((entity) => (
                        <li key={entity.entity_id}>
                            <h2>{entity.name}</h2>
                            {" "}
                            <p>{describeEntity(entity)}</p>
                            <p>
                                {entity.summary ?? "No summary recorded."}
                            </p>
                        </li>
                    ))}
                </ul>
            ) : (
                <p>No world entities match the current search.</p>
            )}

            {page.next_cursor !== null && (
                <button
                    type="button"
                    disabled={refreshing}
                    onClick={onNextPage}
                >
                    Next page
                </button>
            )}
        </div>
    )
}

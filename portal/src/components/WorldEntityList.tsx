import {
    useEffect,
    useState,
} from "react"
import type {
    WorldCategory,
    WorldEntityCard,
    WorldEntityPage,
} from "../types/world"

const categoryLabels: Record<WorldCategory, string> = {
    location: "Location",
    character: "Character",
    organization: "Organization",
    religion: "Religion",
    item: "Item",
    event: "Event",
}

// How long a refresh must run before the "Updating results…" indicator
// appears, so a fast reload doesn't just flash it on and off.
const UPDATING_INDICATOR_DELAY_MS = 200

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
    const [showUpdatingIndicator, setShowUpdatingIndicator] =
        useState(false)

    useEffect(() => {
        if (!refreshing) {
            setShowUpdatingIndicator(false)
            return
        }

        const timeoutId = window.setTimeout(() => {
            setShowUpdatingIndicator(true)
        }, UPDATING_INDICATOR_DELAY_MS)

        return () => window.clearTimeout(timeoutId)
    }, [refreshing])

    return (
        <div
            role="region"
            aria-label="World entities results"
            aria-busy={refreshing}
        >
            {showUpdatingIndicator && (
                <p
                    className="world-entity-list__status"
                    role="status"
                >
                    Updating results…
                </p>
            )}

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
                    onClick={onNextPage}
                >
                    Next page
                </button>
            )}
        </div>
    )
}

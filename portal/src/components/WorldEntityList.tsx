import type {
    WorldEntityPage,
} from "../types/world"
import { CardGrid } from "./CardGrid"
import { UpdatingIndicator } from "./UpdatingIndicator"
import { WorldCard } from "./WorldCard"

interface WorldEntityListProps {
    campaignId: string
    page: WorldEntityPage
    refreshing?: boolean
    hasPreviousPage?: boolean
    onPreviousPage?: () => void
    onNextPage: () => void
}

export function WorldEntityList({
    campaignId,
    page,
    refreshing = false,
    hasPreviousPage = false,
    onPreviousPage,
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
                <CardGrid ariaLabel="World entities" className="world-card-grid">
                    {page.items.map((entity) => (
                        <WorldCard
                            key={entity.entity_id}
                            campaignId={campaignId}
                            entity={entity}
                        />
                    ))}
                </CardGrid>
            ) : (
                <p>No world entities match the current search.</p>
            )}

            {hasPreviousPage && onPreviousPage !== undefined && (
                <button
                    type="button"
                    disabled={refreshing}
                    onClick={onPreviousPage}
                >
                    Previous page
                </button>
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

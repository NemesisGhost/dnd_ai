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
    // 1-based number of the page shown.
    pageNumber?: number
    hasPreviousPage?: boolean
    onPreviousPage?: () => void
    onNextPage: () => void
    // Current search text and selected category noun, for the empty state.
    query?: string
    categoryNoun?: string
    onClearSearch?: () => void
    returnSearch?: string
}

export function WorldEntityList({
    campaignId,
    page,
    refreshing = false,
    pageNumber = 1,
    hasPreviousPage = false,
    onPreviousPage,
    onNextPage,
    query = "",
    categoryNoun = "entries",
    onClearSearch,
    returnSearch,
}: WorldEntityListProps) {
    const hasNextPage = page.next_cursor !== null
    const searching = query !== ""

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
                            returnSearch={returnSearch}
                        />
                    ))}
                </CardGrid>
            ) : (
                <div className="world-empty">
                    <p>
                        {searching
                            ? `No ${categoryNoun} match “${query}”.`
                            : `No ${categoryNoun} to show here yet.`}
                    </p>
                    {searching && onClearSearch !== undefined && (
                        <button type="button" onClick={onClearSearch}>
                            Clear search
                        </button>
                    )}
                </div>
            )}

            {(hasPreviousPage || hasNextPage) && (
                <nav aria-label="World pagination" className="world-pager">
                    <button
                        type="button"
                        disabled={refreshing || !hasPreviousPage || onPreviousPage === undefined}
                        onClick={onPreviousPage}
                    >
                        Previous page
                    </button>
                    <span className="world-pager__position">Page {pageNumber}</span>
                    <button
                        type="button"
                        disabled={refreshing || !hasNextPage}
                        onClick={onNextPage}
                    >
                        Next page
                    </button>
                </nav>
            )}
        </div>
    )
}

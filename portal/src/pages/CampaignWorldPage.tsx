import {
    useEffect,
    useState,
} from "react"
import {
    useParams,
} from "react-router"
import {
    WorldEntitiesBoundary,
} from "../components/WorldEntitiesBoundary"
import {
    WorldEntityList,
} from "../components/WorldEntityList"
import type {
    WorldCategory,
} from "../types/world"
import PlaceholderPage from "./PlaceholderPage"
import { WorldPage } from "./WorldPage"

// Short debounce: long enough to collapse per-keystroke requests, short
// enough that live search still feels immediate. Only the request start is
// delayed — WorldEntitiesBoundary/useWorldEntities keep the previous
// results visible (as "refreshing") while the new one is in flight.
const SEARCH_DEBOUNCE_MS = 180

interface CampaignWorldContentProps {
    campaignId: string
}

function CampaignWorldContent({
    campaignId,
}: CampaignWorldContentProps) {
    const [category, setCategory] =
        useState<WorldCategory | null>(null)
    const [searchInputValue, setSearchInputValue] =
        useState("")
    const [debouncedQuery, setDebouncedQuery] =
        useState("")
    const [cursor, setCursor] =
        useState<string | null>(null)

    useEffect(() => {
        if (searchInputValue === debouncedQuery) {
            return
        }

        const timeoutId = window.setTimeout(() => {
            setDebouncedQuery(searchInputValue)
            setCursor(null)
        }, SEARCH_DEBOUNCE_MS)

        return () => window.clearTimeout(timeoutId)
    }, [searchInputValue, debouncedQuery])

    function handleCategoryChange(
        nextCategory: WorldCategory | null,
    ) {
        setCategory(nextCategory)
        setCursor(null)
    }

    return (
        <WorldPage
            category={category}
            query={searchInputValue}
            onCategoryChange={handleCategoryChange}
            onQueryChange={setSearchInputValue}
        >
            <WorldEntitiesBoundary
                campaignId={campaignId}
                category={category}
                query={debouncedQuery}
                cursor={cursor}
            >
                {(page, refreshing) => (
                    <WorldEntityList
                        page={page}
                        refreshing={refreshing}
                        onNextPage={() =>
                            setCursor(page.next_cursor)
                        }
                    />
                )}
            </WorldEntitiesBoundary>
        </WorldPage>
    )
}

export function CampaignWorldPage() {
    const { campaignId } =
        useParams<{ campaignId: string }>()

    if (campaignId === undefined) {
        return (
            <PlaceholderPage
                title="World unavailable"
                description="The requested world information is not available."
            />
        )
    }

    return (
        <CampaignWorldContent
            key={campaignId}
            campaignId={campaignId}
        />
    )
}

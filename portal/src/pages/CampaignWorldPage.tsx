import {
    useEffect,
    useState,
} from "react"
import {
    useParams,
} from "react-router"
import { useCampaignCapability } from "../hooks/useCampaignCapability"
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
    // The list API pages forward only (each page carries just a
    // `next_cursor`), so the cursors that produced the pages already
    // visited are kept here: the last entry is the current page's cursor,
    // the first is always `null` (the first page). "Previous page" pops
    // back to the cursor that produced the earlier page. Any change to the
    // inputs a cursor was issued for (category, search, hidden preview)
    // discards the whole history, never just the current entry.
    const [cursorHistory, setCursorHistory] =
        useState<readonly (string | null)[]>([null])
    const cursor = cursorHistory[cursorHistory.length - 1]
    const resetPagination = () => setCursorHistory([null])
    const [showHidden, setShowHidden] = useState(false)
    // The toggle is offered from the bootstrap's capability list; the server
    // re-checks and ignores the flags for anyone without canon.edit.
    const canPreviewHidden = useCampaignCapability(campaignId, "canon.edit")

    useEffect(() => {
        if (searchInputValue === debouncedQuery) {
            return
        }

        const timeoutId = window.setTimeout(() => {
            setDebouncedQuery(searchInputValue)
            setCursorHistory([null])
        }, SEARCH_DEBOUNCE_MS)

        return () => window.clearTimeout(timeoutId)
    }, [searchInputValue, debouncedQuery])

    function handleCategoryChange(
        nextCategory: WorldCategory | null,
    ) {
        setCategory(nextCategory)
        resetPagination()
    }

    return (
        <WorldPage
            category={category}
            query={searchInputValue}
            onCategoryChange={handleCategoryChange}
            onQueryChange={setSearchInputValue}
            canPreviewHidden={canPreviewHidden}
            showHidden={showHidden && canPreviewHidden}
            onShowHiddenChange={(value) => {
                setShowHidden(value)
                resetPagination()
            }}
            createLinks={
                canPreviewHidden
                    ? [
                          {
                              label: "New location",
                              to: `/app/${encodeURIComponent(campaignId)}/world/location/new`,
                          },
                          {
                              label: "New dungeon",
                              to: `/app/${encodeURIComponent(campaignId)}/world/dungeon/new`,
                          },
                          {
                              label: "New organization",
                              to: `/app/${encodeURIComponent(campaignId)}/world/organization/new`,
                          },
                          {
                              label: "New character",
                              to: `/app/${encodeURIComponent(campaignId)}/characters/new`,
                          },
                          {
                              label: "New religion",
                              to: `/app/${encodeURIComponent(campaignId)}/world/religion/new`,
                          },
                      ]
                    : []
            }
        >
            <WorldEntitiesBoundary
                campaignId={campaignId}
                category={category}
                query={debouncedQuery}
                cursor={cursor}
                includeHidden={showHidden && canPreviewHidden}
            >
                {(page, refreshing) => (
                    <WorldEntityList
                        campaignId={campaignId}
                        page={page}
                        refreshing={refreshing}
                        hasPreviousPage={cursorHistory.length > 1}
                        onPreviousPage={() =>
                            setCursorHistory((history) =>
                                history.length > 1
                                    ? history.slice(0, -1)
                                    : history,
                            )
                        }
                        onNextPage={() => {
                            const nextCursor = page.next_cursor
                            if (nextCursor !== null) {
                                setCursorHistory((history) => [
                                    ...history,
                                    nextCursor,
                                ])
                            }
                        }}
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

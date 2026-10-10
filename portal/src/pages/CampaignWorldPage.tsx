import {
    useEffect,
    useState,
} from "react"
import {
    useParams,
} from "react-router"
import { useCampaignCapability } from "../hooks/useCampaignCapability"
import { useWorldBrowseState } from "../hooks/useWorldBrowseState"
import {
    WorldEntitiesBoundary,
} from "../components/WorldEntitiesBoundary"
import {
    WorldEntityList,
} from "../components/WorldEntityList"
import { worldCategoryNavItem } from "../utils/worldCategories"
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
    // Category, search, page trail and draft preview live in the address (see
    // useWorldBrowseState), so entries return to the same view and Back,
    // Forward and deep links work. Only the text being typed is local.
    const browse = useWorldBrowseState()
    const [searchInputValue, setSearchInputValue] = useState(browse.query)
    const [seenUrlQuery, setSeenUrlQuery] = useState(browse.query)
    if (browse.query !== seenUrlQuery) {
        // Back/Forward or a link changed the address: the field follows it.
        setSeenUrlQuery(browse.query)
        setSearchInputValue(browse.query)
    }
    // The toggle is offered from the bootstrap's capability list; the server
    // re-checks and ignores the flags for anyone without canon.edit.
    const canPreviewHidden = useCampaignCapability(campaignId, "canon.edit")
    const includeHidden = browse.showHidden && canPreviewHidden
    const { setQuery } = browse

    useEffect(() => {
        if (searchInputValue === browse.query) {
            return
        }

        const timeoutId = window.setTimeout(
            () => setQuery(searchInputValue),
            SEARCH_DEBOUNCE_MS,
        )

        return () => window.clearTimeout(timeoutId)
    }, [searchInputValue, browse.query, setQuery])

    const categoryItem = worldCategoryNavItem(browse.category)

    function clearSearch() {
        setSearchInputValue("")
        browse.setQuery("")
    }

    return (
        <WorldPage
            category={browse.category}
            query={searchInputValue}
            onQueryChange={setSearchInputValue}
            categoryHref={(category) => browse.hrefFor({ category }) || "?"}
            canPreviewHidden={canPreviewHidden}
            showHidden={includeHidden}
            onShowHiddenChange={browse.setShowHidden}
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
                category={browse.category}
                query={browse.query}
                cursor={browse.cursor}
                includeHidden={includeHidden}
            >
                {(page, refreshing) => (
                    <WorldEntityList
                        campaignId={campaignId}
                        page={page}
                        refreshing={refreshing}
                        pageNumber={browse.pageNumber}
                        hasPreviousPage={browse.cursors.length > 0}
                        onPreviousPage={browse.goToPreviousPage}
                        onNextPage={() => {
                            if (page.next_cursor !== null) {
                                browse.goToNextPage(page.next_cursor)
                            }
                        }}
                        query={browse.query}
                        categoryNoun={categoryItem.noun}
                        onClearSearch={clearSearch}
                        returnSearch={browse.returnSearch}
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

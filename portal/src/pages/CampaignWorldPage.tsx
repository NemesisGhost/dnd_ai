import {
    useEffect,
    useState,
} from "react"
import {
    useParams,
} from "react-router"
import { useCampaignCapability } from "../hooks/useCampaignCapability"
import { useWorldCapability, WORLD_CANON_EDIT } from "../hooks/useWorldCapability"
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
    const [showHidden, setShowHidden] = useState(false)
    // The toggle is offered from the bootstrap's capability list; the server
    // re-checks and ignores the flags for anyone without canon.edit.
    const hasCanonEdit = useCampaignCapability(campaignId, "canon.edit")
    // Unpublished definitions belong to the world: previewing them needs the world's private-read
    // capability as well, and creating shared canon needs the world Editor role (ADR 0020).
    const canReadPrivate = useWorldCapability(campaignId, "world.canon.read_private")
    const canAuthorWorld = useWorldCapability(campaignId, WORLD_CANON_EDIT)
    const canPreviewHidden = hasCanonEdit && canReadPrivate

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
            canPreviewHidden={canPreviewHidden}
            showHidden={showHidden && canPreviewHidden}
            onShowHiddenChange={(value) => {
                setShowHidden(value)
                setCursor(null)
            }}
            createLinks={
                hasCanonEdit && canAuthorWorld
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

import {
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

interface CampaignWorldContentProps {
    campaignId: string
}

function CampaignWorldContent({
    campaignId,
}: CampaignWorldContentProps) {
    const [category, setCategory] =
        useState<WorldCategory | null>(null)
    const [query, setQuery] = useState("")
    const [cursor, setCursor] =
        useState<string | null>(null)

    function handleCategoryChange(
        nextCategory: WorldCategory | null,
    ) {
        setCategory(nextCategory)
        setCursor(null)
    }

    function handleQueryChange(
        nextQuery: string,
    ) {
        setQuery(nextQuery)
        setCursor(null)
    }

    return (
        <WorldPage
            category={category}
            query={query}
            onCategoryChange={handleCategoryChange}
            onQueryChange={handleQueryChange}
        >
            <WorldEntitiesBoundary
                campaignId={campaignId}
                category={category}
                query={query}
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
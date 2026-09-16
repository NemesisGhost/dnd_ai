import {
    useEffect,
    useState,
} from "react"
import {
    useParams,
} from "react-router"
import {
    CardGrid,
} from "../components/CardGrid"
import {
    KnowledgeCard,
} from "../components/KnowledgeCard"
import {
    KnowledgeItemsBoundary,
} from "../components/KnowledgeItemsBoundary"
import {
    UpdatingIndicator,
} from "../components/UpdatingIndicator"
import {
    usePerspective,
} from "../context/CharacterPerspectiveContext"
import {
    useSession,
} from "../context/SessionContext"
import type {
    SessionBootstrapState,
} from "../hooks/useSessionBootstrap"
import type {
    AuthorizedParty,
} from "../types/bootstrap"
import type {
    KnowledgePage as KnowledgeResultsPage,
    KnowledgeView,
} from "../types/knowledge"
import PlaceholderPage from "./PlaceholderPage"
import { KnowledgePage } from "./KnowledgePage"

// Short debounce: long enough to collapse per-keystroke requests, short
// enough that live search still feels immediate. Only the request start is
// delayed — KnowledgeItemsBoundary/useKnowledgeItems keep the previous
// results visible (as "refreshing") while the new one is in flight.
const SEARCH_DEBOUNCE_MS = 180

// The authorized-party list lives on the selected character's perspective
// in the session bootstrap, not the knowledge API itself — a character can
// only filter by a party they are actually authorized to see.
function resolveAuthorizedParties(
    sessionState: SessionBootstrapState,
    campaignId: string,
    characterId: string | null,
): AuthorizedParty[] {
    if (sessionState.status !== "authenticated") {
        return []
    }

    const campaign = sessionState.bootstrap.campaigns.find(
        (candidate) => candidate.campaign_id === campaignId,
    )

    if (campaign === undefined) {
        return []
    }

    const character = campaign.character_perspectives.find(
        (candidate) => candidate.character_id === characterId,
    )

    return character?.authorized_parties ?? []
}

interface KnowledgeItemListProps {
    campaignId: string
    characterId: string | null
    partyId: string | null
    page: KnowledgeResultsPage
    refreshing: boolean
    onNextPage: () => void
}

function KnowledgeItemList({
    campaignId,
    characterId,
    partyId,
    page,
    refreshing,
    onNextPage,
}: KnowledgeItemListProps) {
    return (
        <div
            role="region"
            aria-label="Knowledge results"
            aria-busy={refreshing}
        >
            {refreshing && <UpdatingIndicator />}

            {page.items.length > 0 ? (
                <CardGrid
                    ariaLabel="Knowledge items"
                    className="knowledge-card-grid"
                >
                    {page.items.map((item) => (
                        <KnowledgeCard
                            key={item.knowledge_item_id}
                            campaignId={campaignId}
                            item={item}
                            characterId={characterId}
                            partyId={partyId}
                        />
                    ))}
                </CardGrid>
            ) : (
                <p>No knowledge matches the current search.</p>
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

interface CampaignKnowledgeContentProps {
    campaignId: string
}

function CampaignKnowledgeContent({
    campaignId,
}: CampaignKnowledgeContentProps) {
    const { getSelectedCharacterId } = usePerspective()
    const characterId = getSelectedCharacterId(campaignId)

    const { state: sessionState } = useSession()
    const parties = resolveAuthorizedParties(
        sessionState,
        campaignId,
        characterId,
    )

    const [view, setView] =
        useState<KnowledgeView>("known")
    const [partyId, setPartyId] =
        useState<string | null>(null)
    const [searchInputValue, setSearchInputValue] =
        useState("")
    const [debouncedQuery, setDebouncedQuery] =
        useState("")
    const [cursor, setCursor] =
        useState<string | null>(null)

    // A perspective switch changes what's authorized to see, same as a
    // category change: never leave a stale cursor (or a party filter that
    // may no longer be authorized) pointed at a page that belonged to the
    // previous character. Reset during render (rather than in an effect)
    // so it lands before the boundary below re-requests.
    const [
        characterIdAtLastRender,
        setCharacterIdAtLastRender,
    ] = useState(characterId)

    const selectedPartyIsAvailable =
        partyId === null ||
        parties.some(
            (party) => party.party_id === partyId,
        )

    if (characterId !== characterIdAtLastRender) {
        setCharacterIdAtLastRender(characterId)
        setCursor(null)
        setPartyId(null)
    } else if (!selectedPartyIsAvailable) {
        setCursor(null)
        setPartyId(null)
    }

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

    function handleViewChange(nextView: KnowledgeView) {
        setView(nextView)
        setCursor(null)
    }

    function handlePartyChange(nextPartyId: string | null) {
        setPartyId(nextPartyId)
        setCursor(null)
    }

    return (
        <KnowledgePage
            view={view}
            query={searchInputValue}
            partyId={partyId}
            parties={parties}
            onViewChange={handleViewChange}
            onQueryChange={setSearchInputValue}
            onPartyChange={handlePartyChange}
        >
            <KnowledgeItemsBoundary
                campaignId={campaignId}
                view={view}
                characterId={characterId}
                partyId={partyId}
                query={debouncedQuery}
                knowledgeType={null}
                cursor={cursor}
            >
                {(page, refreshing) => (
                    <KnowledgeItemList
                        campaignId={campaignId}
                        characterId={characterId}
                        partyId={partyId}
                        page={page}
                        refreshing={refreshing}
                        onNextPage={() =>
                            setCursor(page.next_cursor)
                        }
                    />
                )}
            </KnowledgeItemsBoundary>
        </KnowledgePage>
    )
}

export function CampaignKnowledgePage() {
    const { campaignId } =
        useParams<{ campaignId: string }>()

    if (campaignId === undefined) {
        return (
            <PlaceholderPage
                title="Knowledge unavailable"
                description="The requested knowledge is not available."
            />
        )
    }

    return (
        <CampaignKnowledgeContent
            key={campaignId}
            campaignId={campaignId}
        />
    )
}

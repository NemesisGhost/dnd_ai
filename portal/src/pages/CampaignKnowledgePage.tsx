import {
    useCallback,
    useEffect,
    useRef,
    useState,
} from "react"
import {
    useParams,
    useSearchParams,
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
    KnowledgeLifecycle,
    KnowledgePage as KnowledgeResultsPage,
    KnowledgeView,
} from "../types/knowledge"
import { resolveAuthorizedParties } from "../utils/authorizedParties"
import PlaceholderPage from "./PlaceholderPage"
import { KnowledgePage } from "./KnowledgePage"

// Short debounce: long enough to collapse per-keystroke requests, short
// enough that live search still feels immediate. Only the request start is
// delayed — KnowledgeItemsBoundary/useKnowledgeItems keep the previous
// results visible (as "refreshing") while the new one is in flight.
const SEARCH_DEBOUNCE_MS = 180

interface KnowledgeItemListProps {
    campaignId: string
    characterId: string | null
    partyId: string | null
    page: KnowledgeResultsPage
    refreshing: boolean
    lifecycle: KnowledgeLifecycle
    onArchiveBrowseAvailable: (available: boolean) => void
    onNextPage: () => void
}

function KnowledgeItemList({
    campaignId,
    characterId,
    partyId,
    page,
    refreshing,
    lifecycle,
    onArchiveBrowseAvailable,
    onNextPage,
}: KnowledgeItemListProps) {
    const archiveBrowseAvailable =
        page.archive_browse_available === true

    useEffect(() => {
        onArchiveBrowseAvailable(archiveBrowseAvailable)
    }, [archiveBrowseAvailable, onArchiveBrowseAvailable])

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
                <p>
                    {lifecycle === "archived"
                        ? "No archived knowledge matches the current search."
                        : "No knowledge matches the current search."}
                </p>
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

const knowledgeViews: readonly KnowledgeView[] = [
    "known",
    "rumors",
    "party_shared",
    "character_private",
    "recent",
    "public",
]

const knowledgeLifecycles: readonly KnowledgeLifecycle[] = [
    "active",
    "archived",
    "all",
]

// The address carries the list's own state (view, search, party, lifecycle) so Back and a
// reload reproduce it. An unknown value is the default, never an error. The character
// perspective stays in its own persisted selection.
function viewFromAddress(value: string | null): KnowledgeView {
    return knowledgeViews.find((view) => view === value) ?? "known"
}

function lifecycleFromAddress(value: string | null): KnowledgeLifecycle {
    return knowledgeLifecycles.find((lifecycle) => lifecycle === value) ?? "active"
}

function setOrRemove(
    parameters: URLSearchParams,
    key: string,
    value: string | null,
) {
    if (value === null || value === "") {
        parameters.delete(key)
    } else {
        parameters.set(key, value)
    }
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

    const [searchParams, setSearchParams] = useSearchParams()
    const view = viewFromAddress(searchParams.get("view"))
    const lifecycle = lifecycleFromAddress(
        searchParams.get("lifecycle"),
    )
    const debouncedQuery = searchParams.get("q") ?? ""
    const addressPartyId = searchParams.get("party_id")

    // A party that is not (or no longer) authorized for the selected character is no filter at
    // all; the address is cleaned below.
    const partyId =
        addressPartyId !== null &&
            parties.some(
                (party) => party.party_id === addressPartyId,
            )
            ? addressPartyId
            : null

    const [searchInputValue, setSearchInputValue] =
        useState(debouncedQuery)
    // Public knowledge is part of every view by default, whatever the
    // perspective; leaving it out is only ever the user's explicit choice.
    const [includePublic, setIncludePublic] =
        useState(true)
    // Whether the server offers archive browsing, learned from the latest page it returned.
    const [archiveBrowseAvailable, setArchiveBrowseAvailable] =
        useState(false)

    // A cursor belongs to exactly one filter combination: it is honoured only while the filters
    // that produced it are unchanged, so any change (including Back, a perspective switch or a
    // lifecycle change) starts again from the first page.
    const filterSignature = JSON.stringify([
        view,
        characterId,
        partyId,
        debouncedQuery,
        includePublic,
        lifecycle,
    ])
    const [cursorState, setCursorState] = useState<{
        signature: string
        cursor: string | null
    }>({ signature: filterSignature, cursor: null })
    const cursor =
        cursorState.signature === filterSignature
            ? cursorState.cursor
            : null

    const updateAddress = useCallback(
        (
            change: (parameters: URLSearchParams) => void,
            replace: boolean,
        ) => {
            setSearchParams(
                (previous) => {
                    const next = new URLSearchParams(previous)
                    change(next)
                    return next
                },
                { replace },
            )
        },
        [setSearchParams],
    )

    useEffect(() => {
        if (addressPartyId !== null && partyId === null) {
            updateAddress(
                (parameters) => parameters.delete("party_id"),
                true,
            )
        }
    }, [addressPartyId, partyId, updateAddress])

    // The last query this page wrote to the address; a different one arriving (Back/Forward)
    // is shown in the search box.
    const committedQuery = useRef(debouncedQuery)

    useEffect(() => {
        if (debouncedQuery !== committedQuery.current) {
            committedQuery.current = debouncedQuery
            setSearchInputValue(debouncedQuery)
        }
    }, [debouncedQuery])

    useEffect(() => {
        if (searchInputValue === debouncedQuery) {
            return
        }

        const timeoutId = window.setTimeout(() => {
            committedQuery.current = searchInputValue
            updateAddress(
                (parameters) =>
                    setOrRemove(parameters, "q", searchInputValue),
                true,
            )
        }, SEARCH_DEBOUNCE_MS)

        return () => window.clearTimeout(timeoutId)
    }, [searchInputValue, debouncedQuery, updateAddress])

    function handleViewChange(nextView: KnowledgeView) {
        updateAddress(
            (parameters) =>
                setOrRemove(
                    parameters,
                    "view",
                    nextView === "known" ? null : nextView,
                ),
            false,
        )
    }

    function handlePartyChange(nextPartyId: string | null) {
        updateAddress(
            (parameters) =>
                setOrRemove(parameters, "party_id", nextPartyId),
            false,
        )
    }

    function handleLifecycleChange(nextLifecycle: KnowledgeLifecycle) {
        updateAddress(
            (parameters) =>
                setOrRemove(
                    parameters,
                    "lifecycle",
                    nextLifecycle === "active" ? null : nextLifecycle,
                ),
            false,
        )
    }

    // The server refused archive browsing for this caller (a hand-edited address, or a role
    // withdrawn since): fall back to the active list.
    const handleLifecycleRejected = useCallback(() => {
        setArchiveBrowseAvailable(false)
        updateAddress(
            (parameters) => parameters.delete("lifecycle"),
            true,
        )
    }, [updateAddress, setArchiveBrowseAvailable])

    return (
        <KnowledgePage
            campaignId={campaignId}
            view={view}
            query={searchInputValue}
            partyId={partyId}
            parties={parties}
            includePublic={includePublic}
            archiveBrowseAvailable={archiveBrowseAvailable}
            lifecycle={lifecycle}
            onViewChange={handleViewChange}
            onQueryChange={setSearchInputValue}
            onPartyChange={handlePartyChange}
            onIncludePublicChange={setIncludePublic}
            onLifecycleChange={handleLifecycleChange}
        >
            <KnowledgeItemsBoundary
                campaignId={campaignId}
                view={view}
                characterId={characterId}
                partyId={partyId}
                query={debouncedQuery}
                knowledgeType={null}
                cursor={cursor}
                // The Public view *is* the public-only filter, so the
                // opt-out never applies to it.
                includePublic={includePublic || view === "public"}
                lifecycle={lifecycle}
                onLifecycleRejected={handleLifecycleRejected}
            >
                {(page, refreshing) => (
                    <KnowledgeItemList
                        campaignId={campaignId}
                        characterId={characterId}
                        partyId={partyId}
                        page={page}
                        refreshing={refreshing}
                        lifecycle={lifecycle}
                        onArchiveBrowseAvailable={setArchiveBrowseAvailable}
                        onNextPage={() =>
                            setCursorState({
                                signature: filterSignature,
                                cursor: page.next_cursor,
                            })
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

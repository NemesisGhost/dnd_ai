import { useEffect, useId, useState } from "react"
import { Link } from "react-router"
import { useCampaignCapability } from "../hooks/useCampaignCapability"
import { useCharactersBrowseState } from "../hooks/useCharactersBrowseState"
import { characterKindLabel, characterKindOfTypeCode } from "../utils/characterKind"
import type { CharacterType } from "../types/world"
import { LifecycleBadge } from "./authoring/feedback"
import { CardGrid } from "./CardGrid"
import { EntityCard } from "./EntityCard"
import { UpdatingIndicator } from "./UpdatingIndicator"
import { WorldEntitiesBoundary } from "./WorldEntitiesBoundary"

// Same short debounce as the World search: collapse per-keystroke requests, keep the previous
// results visible (as "refreshing") while the new ones load.
const SEARCH_DEBOUNCE_MS = 180

const TYPE_FILTERS: readonly { type: CharacterType | null; label: string }[] = [
    { type: null, label: "All" },
    { type: "player_character", label: "Player characters" },
    { type: "npc", label: "NPCs" },
]

// Browse the characters this person may discover, as the World's People category does, with a
// type filter. Opening a row shows that character's sheet; it never changes the selected
// perspective (which is derived from the person's own character access).
export function CharactersBrowser({ campaignId }: { campaignId: string }) {
    const browse = useCharactersBrowseState()
    const searchId = useId()
    const [input, setInput] = useState(browse.query)
    const [seenUrlQuery, setSeenUrlQuery] = useState(browse.query)
    if (browse.query !== seenUrlQuery) {
        // Back/Forward or a link changed the address: the field follows it.
        setSeenUrlQuery(browse.query)
        setInput(browse.query)
    }
    // Offered from the bootstrap capability list; the server re-checks and ignores the flags for
    // anyone without canon.edit.
    const canPreviewHidden = useCampaignCapability(campaignId, "canon.edit")
    const includeHidden = browse.showHidden && canPreviewHidden
    const { setQuery } = browse

    useEffect(() => {
        if (input === browse.query) return
        const id = window.setTimeout(() => setQuery(input), SEARCH_DEBOUNCE_MS)
        return () => window.clearTimeout(id)
    }, [input, browse.query, setQuery])

    const base = `/app/${encodeURIComponent(campaignId)}/characters`
    const noun =
        browse.type === "npc"
            ? "NPCs"
            : browse.type === "player_character"
              ? "player characters"
              : "characters"

    return (
        <section aria-labelledby="characters-browser-heading" className="world-page characters-browser">
            <h2 id="characters-browser-heading">All characters</h2>
            <div className="world-page__toolbar">
                <div role="search" aria-label="Character search" className="world-page__search">
                    <div className="world-page__field">
                        <label htmlFor={searchId}>Search characters</label>
                        <input
                            id={searchId}
                            type="search"
                            value={input}
                            onChange={(event) => setInput(event.currentTarget.value)}
                        />
                    </div>
                    {canPreviewHidden ? (
                        <label className="world-page__toggle">
                            <input
                                type="checkbox"
                                checked={includeHidden}
                                onChange={(event) => browse.setShowHidden(event.currentTarget.checked)}
                            />{" "}
                            Show drafts and archived
                        </label>
                    ) : null}
                </div>
            </div>
            <nav aria-label="Character type" className="world-categories">
                <ul className="world-categories__list characters-browser__filters">
                    {TYPE_FILTERS.map((filter) => (
                        <li key={filter.type ?? "all"}>
                            <Link
                                to={browse.hrefFor({ type: filter.type })}
                                className="world-categories__link"
                                aria-current={filter.type === browse.type ? "page" : undefined}
                            >
                                {filter.label}
                            </Link>
                        </li>
                    ))}
                </ul>
            </nav>
            <div className="world-page__results">
                <WorldEntitiesBoundary
                    campaignId={campaignId}
                    category="character"
                    query={browse.query}
                    cursor={browse.cursor}
                    includeHidden={includeHidden}
                    characterType={browse.type ?? undefined}
                >
                    {(page, refreshing) => (
                        <div role="region" aria-label="Character results" aria-busy={refreshing}>
                            {refreshing && <UpdatingIndicator />}
                            {page.items.length > 0 ? (
                                <CardGrid ariaLabel="Characters" className="world-card-grid">
                                    {page.items.map((entity) => {
                                        const label = characterKindLabel(
                                            characterKindOfTypeCode(entity.entity_type_code),
                                        )
                                        const hiddenStatus =
                                            entity.lifecycle_status === "archived"
                                                ? "archived"
                                                : entity.canon_status !== undefined &&
                                                    entity.canon_status !== "canon"
                                                  ? entity.canon_status
                                                  : null
                                        return (
                                            <EntityCard
                                                key={entity.entity_id}
                                                eyebrow={label}
                                                title={entity.name}
                                                summary={entity.summary}
                                                to={`${base}/${encodeURIComponent(entity.entity_id)}`}
                                                linkState={{ charactersReturn: browse.returnTo }}
                                                eyebrowAfterTitle
                                                className="world-card"
                                                linkLabel={
                                                    hiddenStatus === null
                                                        ? `${entity.name}, ${label}`
                                                        : `${entity.name}, ${label}, ${hiddenStatus}`
                                                }
                                                metadata={
                                                    hiddenStatus === null
                                                        ? undefined
                                                        : [<LifecycleBadge key="status" status={hiddenStatus} />]
                                                }
                                            />
                                        )
                                    })}
                                </CardGrid>
                            ) : (
                                <div className="world-empty">
                                    <p>
                                        {browse.query !== ""
                                            ? `No ${noun} match “${browse.query}”.`
                                            : `No ${noun} to show here yet.`}
                                    </p>
                                    {browse.query !== "" && (
                                        <button
                                            type="button"
                                            onClick={() => {
                                                setInput("")
                                                browse.setQuery("")
                                            }}
                                        >
                                            Clear search
                                        </button>
                                    )}
                                </div>
                            )}
                            {(browse.cursors.length > 0 || page.next_cursor !== null) && (
                                <nav aria-label="Characters pagination" className="world-pager">
                                    <button
                                        type="button"
                                        disabled={refreshing || browse.cursors.length === 0}
                                        onClick={browse.goToPreviousPage}
                                    >
                                        Previous page
                                    </button>
                                    <span className="world-pager__position">Page {browse.pageNumber}</span>
                                    <button
                                        type="button"
                                        disabled={refreshing || page.next_cursor === null}
                                        onClick={() => {
                                            if (page.next_cursor !== null) browse.goToNextPage(page.next_cursor)
                                        }}
                                    >
                                        Next page
                                    </button>
                                </nav>
                            )}
                        </div>
                    )}
                </WorldEntitiesBoundary>
            </div>
        </section>
    )
}

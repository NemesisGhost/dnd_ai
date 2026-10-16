import { useId } from "react"
import type { ReactNode } from "react"
import { Link } from "react-router"
import type { WorldCategory, WorldCategoryCounts } from "../types/world"
import { WORLD_CATEGORY_NAV } from "../utils/worldCategories"

interface WorldPageProps {
    category: WorldCategory | null
    query: string
    onQueryChange: (query: string) => void
    // The address a category link opens: it keeps the search and draft
    // preview, and restarts paging.
    categoryHref: (category: WorldCategory | null) => string
    // Authorized totals for the current search, or null while unknown (loading
    // or failed): no count is shown then, never a zero.
    counts?: WorldCategoryCounts | null
    // Offered only to canon.edit holders; players never see the toggle.
    canPreviewHidden?: boolean
    showHidden?: boolean
    onShowHiddenChange?: (value: boolean) => void
    // Creation entry points, offered only to canon.edit holders. The server
    // re-checks on every request; these links only decide what to offer.
    createLinks?: readonly { label: string; to: string }[]
    children: ReactNode
}

export function WorldPage({
    category,
    query,
    onQueryChange,
    categoryHref,
    counts = null,
    canPreviewHidden = false,
    showHidden = false,
    onShowHiddenChange,
    createLinks = [],
    children,
}: WorldPageProps) {
    const searchInputId = useId()

    return (
        <section aria-labelledby="world-heading" className="world-page">
            <h1 id="world-heading">Campaign World</h1>

            <div className="world-page__toolbar">
                <div role="search" aria-label="World search" className="world-page__search">
                    <div className="world-page__field">
                        <label htmlFor={searchInputId}>Search</label>
                        <input
                            id={searchInputId}
                            type="search"
                            value={query}
                            onChange={(event) => onQueryChange(event.currentTarget.value)}
                        />
                    </div>
                    {canPreviewHidden ? (
                        <label className="world-page__toggle">
                            <input
                                type="checkbox"
                                checked={showHidden}
                                onChange={(event) =>
                                    onShowHiddenChange?.(event.currentTarget.checked)
                                }
                            />{" "}
                            Show drafts and archived
                        </label>
                    ) : null}
                </div>

                {createLinks.length > 0 ? (
                    <nav aria-label="Create world content" className="authoring-page__actions-row">
                        {createLinks.map((link) => (
                            <Link key={link.to} to={link.to} className="authoring-button">
                                {link.label}
                            </Link>
                        ))}
                    </nav>
                ) : null}
            </div>

            <div className="world-page__body">
                <nav aria-label="World categories" className="world-categories">
                    <ul className="world-categories__list">
                        {WORLD_CATEGORY_NAV.map((item) => {
                            const selected = item.category === category
                            return (
                                <li key={item.category ?? "all"}>
                                    <Link
                                        to={categoryHref(item.category)}
                                        className="world-categories__link"
                                        aria-current={selected ? "page" : undefined}
                                    >
                                        <span>{item.label}</span>
                                        {counts !== null && " "}
                                        {counts !== null && (
                                            <span className="world-categories__count">
                                                {"("}
                                                {item.category === null
                                                    ? counts.total
                                                    : counts.counts[item.category]}
                                                {")"}
                                            </span>
                                        )}
                                    </Link>
                                </li>
                            )
                        })}
                    </ul>
                </nav>

                <div className="world-page__results">{children}</div>
            </div>
        </section>
    )
}

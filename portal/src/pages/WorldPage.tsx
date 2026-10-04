import { useId } from "react"
import type { ReactNode } from "react"
import { Link } from "react-router"
import type { WorldCategory } from "../types/world"

interface WorldPageProps {
    category: WorldCategory | null
    query: string
    onQueryChange: (query: string) => void
    onCategoryChange: (category: WorldCategory | null) => void
    // Offered only to canon.edit holders; players never see the toggle.
    canPreviewHidden?: boolean
    showHidden?: boolean
    onShowHiddenChange?: (value: boolean) => void
    // Creation entry points, offered only to canon.edit holders. The server
    // re-checks on every request; these links only decide what to offer.
    createLinks?: readonly { label: string; to: string }[]
    children: ReactNode
}

interface CategoryOption {
    value: WorldCategory | ""
    label: string
}

const categoryOptions: CategoryOption[] = [
    { value: "", label: "All" },
    { value: "location", label: "Locations" },
    { value: "character", label: "Characters" },
    { value: "organization", label: "Organizations" },
    { value: "religion", label: "Religions" },
    { value: "item", label: "Items" },
    { value: "event", label: "Events" },
]

export function WorldPage({
    category,
    query,
    onQueryChange,
    onCategoryChange,
    canPreviewHidden = false,
    showHidden = false,
    onShowHiddenChange,
    createLinks = [],
    children,
}: WorldPageProps) {
    const searchInputId = useId()
    const categorySelectId = useId()

    return (
        <section aria-labelledby="world-heading">
            <h1 id="world-heading">World</h1>

            {createLinks.length > 0 ? (
                <nav aria-label="Create world content" className="authoring-page__actions-row">
                    {createLinks.map((link) => (
                        <Link key={link.to} to={link.to} className="authoring-button">
                            {link.label}
                        </Link>
                    ))}
                </nav>
            ) : null}

            <div
                className="world-page__filters"
                role="search"
                aria-label="World search"
            >
                <div className="world-page__field">
                    <label htmlFor={searchInputId}>
                        Search
                    </label>
                    <input
                        id={searchInputId}
                        type="search"
                        value={query}
                        onChange={(event) =>
                            onQueryChange(event.currentTarget.value)
                        }
                    />
                </div>

                <div className="world-page__field">
                    <label htmlFor={categorySelectId}>
                        Category
                    </label>
                    <select
                        id={categorySelectId}
                        value={category ?? ""}
                        onChange={(event) => {
                            const value = event.currentTarget.value

                            onCategoryChange(
                                value === ""
                                    ? null
                                    : (value as WorldCategory),
                            )
                        }}
                    >
                        {categoryOptions.map((option) => (
                            <option
                                key={option.value || "all"}
                                value={option.value}
                            >
                                {option.label}
                            </option>
                        ))}
                    </select>
                </div>
                {canPreviewHidden ? (
                    <div className="world-page__field">
                        <label>
                            <input
                                type="checkbox"
                                checked={showHidden}
                                onChange={(event) =>
                                    onShowHiddenChange?.(event.currentTarget.checked)
                                }
                            />{" "}
                            Show drafts and archived
                        </label>
                    </div>
                ) : null}
            </div>

            {children}
        </section>
    )
}

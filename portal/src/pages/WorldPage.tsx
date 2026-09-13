import {
    useEffect,
    useId,
    useState,
} from "react"
import type { ReactNode } from "react"
import type { WorldCategory } from "../types/world"

interface WorldPageProps {
    category: WorldCategory | null
    query: string
    onQueryChange: (query: string) => void
    onCategoryChange: (category: WorldCategory | null) => void
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

// Short debounce: long enough to collapse per-keystroke requests, short
// enough that live search still feels immediate (see WorldEntitiesBoundary
// for how an in-flight request keeps the previous results visible).
const SEARCH_DEBOUNCE_MS = 180

export function WorldPage({
    category,
    query,
    onQueryChange,
    onCategoryChange,
    children,
}: WorldPageProps) {
    const searchInputId = useId()
    const categorySelectId = useId()

    const [searchInputValue, setSearchInputValue] =
        useState(query)

    useEffect(() => {
        setSearchInputValue(query)
    }, [query])

    useEffect(() => {
        if (searchInputValue === query) {
            return
        }

        const timeoutId = window.setTimeout(() => {
            onQueryChange(searchInputValue)
        }, SEARCH_DEBOUNCE_MS)

        return () => window.clearTimeout(timeoutId)
    }, [searchInputValue, query, onQueryChange])

    return (
        <section aria-labelledby="world-heading">
            <h1 id="world-heading">World</h1>

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
                        value={searchInputValue}
                        onChange={(event) =>
                            setSearchInputValue(
                                event.currentTarget.value,
                            )
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
            </div>

            {children}
        </section>
    )
}

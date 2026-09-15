import { useId } from "react"
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

export function WorldPage({
    category,
    query,
    onQueryChange,
    onCategoryChange,
    children,
}: WorldPageProps) {
    const searchInputId = useId()
    const categorySelectId = useId()

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
            </div>

            {children}
        </section>
    )
}

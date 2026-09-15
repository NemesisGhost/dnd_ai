import {
    fireEvent,
    render,
    screen,
} from "@testing-library/react"
import {
    describe,
    expect,
    it,
    vi,
} from "vitest"
import type { WorldCategory } from "../types/world"
import { WorldPage } from "./WorldPage"

interface RenderOverrides {
    category?: WorldCategory | null
    query?: string
    onQueryChange?: (query: string) => void
    onCategoryChange?: (category: WorldCategory | null) => void
    children?: React.ReactNode
}

function renderPage(overrides: RenderOverrides = {}) {
    const props = {
        category: null,
        query: "",
        onQueryChange: vi.fn(),
        onCategoryChange: vi.fn(),
        children: <p>World results go here.</p>,
        ...overrides,
    }

    const view = render(<WorldPage {...props} />)

    return { ...props, ...view }
}

describe("WorldPage", () => {
    it("renders the heading and labelled search controls", () => {
        renderPage()

        expect(
            screen.getByRole("heading", {
                name: "World",
                level: 1,
            }),
        ).toBeInTheDocument()

        expect(
            screen.getByRole("search", {
                name: "World search",
            }),
        ).toBeInTheDocument()

        expect(
            screen.getByRole("searchbox", {
                name: "Search",
            }),
        ).toHaveValue("")

        const categorySelect =
            screen.getByRole("combobox", {
                name: "Category",
            })

        expect(categorySelect).toHaveValue("")

        expect(
            screen
                .getAllByRole("option")
                .map((option) => option.textContent),
        ).toEqual([
            "All",
            "Locations",
            "Characters",
            "Organizations",
            "Religions",
            "Items",
            "Events",
        ])
    })

    it("renders the supplied children", () => {
        renderPage({
            children: <p>World results go here.</p>,
        })

        expect(
            screen.getByText("World results go here."),
        ).toBeInTheDocument()
    })

    it("is a controlled search input: it reflects the query prop and reports every change immediately", () => {
        const onQueryChange = vi.fn()

        renderPage({
            query: "glass",
            onQueryChange,
        })

        const searchInput =
            screen.getByRole("searchbox", {
                name: "Search",
            })

        expect(searchInput).toHaveValue("glass")

        fireEvent.change(searchInput, {
            target: {
                value: "harbor",
            },
        })

        // WorldPage does not debounce or hold its own copy of the value:
        // it reports the raw change and waits for a new `query` prop.
        expect(onQueryChange).toHaveBeenCalledTimes(1)
        expect(onQueryChange).toHaveBeenCalledWith(
            "harbor",
        )
        expect(searchInput).toHaveValue("glass")
    })

    it("reports category selections and maps All to null", () => {
        const onCategoryChange = vi.fn()

        renderPage({
            category: "location",
            onCategoryChange,
        })

        const categorySelect =
            screen.getByRole("combobox", {
                name: "Category",
            })

        expect(categorySelect).toHaveValue("location")

        fireEvent.change(categorySelect, {
            target: {
                value: "event",
            },
        })

        expect(
            onCategoryChange,
        ).toHaveBeenLastCalledWith("event")

        fireEvent.change(categorySelect, {
            target: {
                value: "",
            },
        })

        expect(
            onCategoryChange,
        ).toHaveBeenLastCalledWith(null)
    })

    it("keeps the search input mounted and focused when its children change", () => {
        const { rerender } = render(
            <WorldPage
                category={null}
                query=""
                onQueryChange={vi.fn()}
                onCategoryChange={vi.fn()}
            >
                <p>Loading world results.</p>
            </WorldPage>,
        )

        const searchInput =
            screen.getByRole("searchbox", {
                name: "Search",
            })

        searchInput.focus()
        expect(searchInput).toHaveFocus()

        rerender(
            <WorldPage
                category={null}
                query="g"
                onQueryChange={vi.fn()}
                onCategoryChange={vi.fn()}
            >
                <p>World results go here.</p>
            </WorldPage>,
        )

        expect(
            screen.getByRole("searchbox", {
                name: "Search",
            }),
        ).toHaveFocus()

        expect(
            screen.getByText("World results go here."),
        ).toBeInTheDocument()
    })
})

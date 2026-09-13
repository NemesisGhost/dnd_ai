import {
    act,
    fireEvent,
    render,
    screen,
} from "@testing-library/react"
import {
    afterEach,
    beforeEach,
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
    beforeEach(() => {
        vi.useFakeTimers()
    })

    afterEach(() => {
        vi.useRealTimers()
    })

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

    it("reports search-query changes", () => {
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

        expect(searchInput).toHaveValue("harbor")
        expect(onQueryChange).not.toHaveBeenCalled()

        act(() => {
            vi.advanceTimersByTime(180)
        })

        expect(onQueryChange).toHaveBeenCalledWith(
            "harbor",
        )
    })

    it("restarts the debounce when a query change lands before the prior one commits", () => {
        const onQueryChange = vi.fn()

        renderPage({
            query: "",
            onQueryChange,
        })

        const searchInput =
            screen.getByRole("searchbox", {
                name: "Search",
            })

        fireEvent.change(searchInput, {
            target: {
                value: "ha",
            },
        })

        act(() => {
            vi.advanceTimersByTime(100)
        })

        fireEvent.change(searchInput, {
            target: {
                value: "harbor",
            },
        })

        act(() => {
            vi.advanceTimersByTime(100)
        })

        expect(onQueryChange).not.toHaveBeenCalled()

        act(() => {
            vi.advanceTimersByTime(100)
        })

        expect(onQueryChange).toHaveBeenCalledTimes(1)
        expect(onQueryChange).toHaveBeenCalledWith(
            "harbor",
        )
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

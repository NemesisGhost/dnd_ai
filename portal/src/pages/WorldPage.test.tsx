import {
    fireEvent,
    render,
    screen,
    within,
} from "@testing-library/react"
import { MemoryRouter } from "react-router"
import {
    describe,
    expect,
    it,
    vi,
} from "vitest"
import type { WorldCategory, WorldCategoryCounts } from "../types/world"
import { WorldPage } from "./WorldPage"

interface RenderOverrides {
    category?: WorldCategory | null
    query?: string
    onQueryChange?: (query: string) => void
    canPreviewHidden?: boolean
    createLinks?: { label: string; to: string }[]
    counts?: WorldCategoryCounts | null
    children?: React.ReactNode
}

function renderPage(overrides: RenderOverrides = {}) {
    const props = {
        category: null,
        query: "",
        onQueryChange: vi.fn(),
        categoryHref: (category: WorldCategory | null) =>
            category === null ? "?" : `?category=${category}`,
        children: <p>World results go here.</p>,
        ...overrides,
    }

    const view = render(
        <MemoryRouter>
            <WorldPage {...props} />
        </MemoryRouter>,
    )

    return { ...props, ...view }
}

describe("WorldPage", () => {
    it("renders the heading, the labelled search and the category navigation", () => {
        renderPage()

        expect(
            screen.getByRole("heading", { name: "Campaign World", level: 1 }),
        ).toBeInTheDocument()
        expect(screen.getByRole("search", { name: "World search" })).toBeInTheDocument()
        expect(screen.getByRole("searchbox", { name: "Search" })).toHaveValue("")

        const nav = screen.getByRole("navigation", { name: "World categories" })

        expect(
            within(nav)
                .getAllByRole("link")
                .map((link) => link.textContent),
        ).toEqual([
            "All entries",
            "Locations",
            "People",
            "Organizations",
            "Faiths",
            "Items",
            "Events",
        ])
    })

    it("links each category to its address and marks only the selected one current", () => {
        renderPage({ category: "religion" })

        expect(screen.getByRole("link", { name: "Faiths" })).toHaveAttribute(
            "aria-current",
            "page",
        )
        expect(screen.getByRole("link", { name: "Faiths" })).toHaveAttribute(
            "href",
            "/?category=religion",
        )
        expect(screen.getByRole("link", { name: "People" })).toHaveAttribute(
            "href",
            "/?category=character",
        )
        expect(screen.getByRole("link", { name: "All entries" })).not.toHaveAttribute(
            "aria-current",
        )
        expect(document.querySelectorAll('[aria-current="page"]')).toHaveLength(1)
    })

    it("shows each category's total beside it, zero included, and none while unknown", () => {
        const counts: WorldCategoryCounts = {
            counts: { location: 9, character: 1, organization: 0, religion: 2, item: 3, event: 10 },
            total: 25,
        }
        const { unmount } = renderPage({ category: "location", counts })

        expect(screen.getByRole("link", { name: "All entries (25)" })).toBeInTheDocument()
        expect(screen.getByRole("link", { name: "Locations (9)" })).toHaveAttribute("aria-current", "page")
        expect(screen.getByRole("link", { name: "People (1)" })).toBeInTheDocument()
        // A zero-count category keeps its link and shows its zero.
        expect(screen.getByRole("link", { name: "Organizations (0)" })).toHaveAttribute(
            "href",
            "/?category=organization",
        )
        unmount()

        renderPage({ counts: null })
        expect(screen.getByRole("link", { name: "Organizations" })).toBeInTheDocument()
        expect(screen.queryByText(/\(\d+\)/)).not.toBeInTheDocument()
    })

    it("selects All entries when no category is chosen", () => {
        renderPage({ category: null })

        expect(screen.getByRole("link", { name: "All entries" })).toHaveAttribute(
            "aria-current",
            "page",
        )
    })

    it("renders the supplied children", () => {
        renderPage()

        expect(screen.getByText("World results go here.")).toBeInTheDocument()
    })

    it("is a controlled search input: it reflects the query prop and reports every change immediately", () => {
        const onQueryChange = vi.fn()

        renderPage({ query: "glass", onQueryChange })

        const searchInput = screen.getByRole("searchbox", { name: "Search" })

        expect(searchInput).toHaveValue("glass")

        fireEvent.change(searchInput, { target: { value: "harbor" } })

        // WorldPage does not debounce or hold its own copy of the value:
        // it reports the raw change and waits for a new `query` prop.
        expect(onQueryChange).toHaveBeenCalledTimes(1)
        expect(onQueryChange).toHaveBeenCalledWith("harbor")
        expect(searchInput).toHaveValue("glass")
    })

    it("offers authoring actions and the draft toggle only when supplied for a permitted user", () => {
        const { unmount } = renderPage()

        expect(
            screen.queryByRole("navigation", { name: "Create world content" }),
        ).not.toBeInTheDocument()
        expect(screen.queryByLabelText(/Show drafts and archived/)).not.toBeInTheDocument()
        unmount()

        renderPage({
            canPreviewHidden: true,
            createLinks: [{ label: "New location", to: "/app/c/world/location/new" }],
        })

        expect(screen.getByRole("link", { name: "New location" })).toBeInTheDocument()
        expect(screen.getByLabelText(/Show drafts and archived/)).toBeInTheDocument()
    })

    it("keeps the search input mounted and focused when its children change", () => {
        const base = {
            category: null,
            onQueryChange: vi.fn(),
            categoryHref: () => "?",
        }
        const { rerender } = render(
            <MemoryRouter>
                <WorldPage {...base} query="">
                    <p>Loading world results.</p>
                </WorldPage>
            </MemoryRouter>,
        )

        const searchInput = screen.getByRole("searchbox", { name: "Search" })

        searchInput.focus()
        expect(searchInput).toHaveFocus()

        rerender(
            <MemoryRouter>
                <WorldPage {...base} query="g">
                    <p>World results go here.</p>
                </WorldPage>
            </MemoryRouter>,
        )

        expect(screen.getByRole("searchbox", { name: "Search" })).toHaveFocus()
        expect(screen.getByText("World results go here.")).toBeInTheDocument()
    })
})

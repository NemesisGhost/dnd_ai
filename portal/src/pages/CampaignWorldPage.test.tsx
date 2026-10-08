import {
    act,
    fireEvent,
    render,
    screen,
} from "@testing-library/react"
import {
    Link,
    MemoryRouter,
    Route,
    Routes,
} from "react-router"
import {
    afterEach,
    beforeEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import {
    useWorldEntities,
} from "../hooks/useWorldEntities"
import type {
    WorldEntityPage,
} from "../types/world"
import {
    CampaignWorldPage,
} from "./CampaignWorldPage"

vi.mock("../hooks/useWorldEntities", () => ({
    useWorldEntities: vi.fn(),
}))

const useWorldEntitiesMock =
    vi.mocked(useWorldEntities)

const worldPage: WorldEntityPage = {
    items: [
        {
            entity_id: "location-1",
            category: "location",
            entity_type_code: "city",
            name: "Glass Harbor",
            summary: "A harbor surrounded by ancient glass towers.",
        },
    ],
    next_cursor: "next-cursor",
}

beforeEach(() => {
    vi.useFakeTimers()

    useWorldEntitiesMock.mockReset()

    useWorldEntitiesMock.mockReturnValue({
        state: {
            status: "success",
            page: worldPage,
        },
        retry: vi.fn(),
    })
})

afterEach(() => {
    vi.useRealTimers()
})

function typeInSearch(value: string) {
    fireEvent.change(
        screen.getByRole("searchbox", {
            name: "Search",
        }),
        {
            target: {
                value,
            },
        },
    )

    act(() => {
        vi.advanceTimersByTime(180)
    })
}

function renderCampaignWorldPage(
    path = "/app/campaign-a/world",
) {
    return render(
        <MemoryRouter initialEntries={[path]}>
            <Routes>
                <Route
                    path="/app/:campaignId/world"
                    element={<CampaignWorldPage />}
                />
            </Routes>
        </MemoryRouter>,
    )
}

describe("CampaignWorldPage", () => {
    it("requests the initial World page for the route campaign", () => {
        renderCampaignWorldPage()

        expect(
            useWorldEntitiesMock,
        ).toHaveBeenCalledWith(
            "campaign-a",
            null,
            "",
            null,
            false,
        )

        expect(
            screen.getByRole("heading", {
                name: "World",
                level: 1,
            }),
        ).toBeInTheDocument()

        expect(
            screen.getByText("Glass Harbor"),
        ).toBeInTheDocument()
    })

    it("applies filters and resets pagination", () => {
        renderCampaignWorldPage()

        fireEvent.click(
            screen.getByRole("button", {
                name: "Next page",
            }),
        )

        expect(
            useWorldEntitiesMock,
        ).toHaveBeenLastCalledWith(
            "campaign-a",
            null,
            "",
            "next-cursor",
            false,
        )

        fireEvent.change(
            screen.getByRole("combobox", {
                name: "Category",
            }),
            {
                target: {
                    value: "event",
                },
            },
        )

        expect(
            useWorldEntitiesMock,
        ).toHaveBeenLastCalledWith(
            "campaign-a",
            "event",
            "",
            null,
            false,
        )

        typeInSearch("sundering")

        expect(
            useWorldEntitiesMock,
        ).toHaveBeenLastCalledWith(
            "campaign-a",
            "event",
            "sundering",
            null,
            false,
        )
    })

    describe("paging back", () => {
        const secondPage: WorldEntityPage = {
            items: [
                {
                    entity_id: "event-1",
                    category: "event",
                    entity_type_code: "historical_event",
                    name: "The Sundering",
                    summary: null,
                },
            ],
            next_cursor: "third-cursor",
        }

        // Each cursor yields its own page, as the server's keyset would.
        beforeEach(() => {
            useWorldEntitiesMock.mockImplementation(
                (_campaignId, _category, _query, cursor) => ({
                    state: {
                        status: "success",
                        page: cursor === null ? worldPage : secondPage,
                    },
                    retry: vi.fn(),
                }),
            )
        })

        function clickPager(name: "Next page" | "Previous page") {
            fireEvent.click(screen.getByRole("button", { name }))
        }

        it("returns from the next page to the original results", () => {
            renderCampaignWorldPage()

            expect(
                screen.queryByRole("button", { name: "Previous page" }),
            ).not.toBeInTheDocument()

            clickPager("Next page")

            expect(screen.getByText("The Sundering")).toBeInTheDocument()
            expect(screen.queryByText("Glass Harbor")).not.toBeInTheDocument()

            clickPager("Previous page")

            expect(
                useWorldEntitiesMock,
            ).toHaveBeenLastCalledWith(
                "campaign-a",
                null,
                "",
                null,
                false,
            )
            expect(screen.getByText("Glass Harbor")).toBeInTheDocument()
            expect(screen.queryByText("The Sundering")).not.toBeInTheDocument()
            expect(
                screen.queryByRole("button", { name: "Previous page" }),
            ).not.toBeInTheDocument()
        })

        it("steps back one page at a time through deeper history", () => {
            renderCampaignWorldPage()

            clickPager("Next page")
            clickPager("Next page")

            expect(
                useWorldEntitiesMock,
            ).toHaveBeenLastCalledWith(
                "campaign-a",
                null,
                "",
                "third-cursor",
                false,
            )

            clickPager("Previous page")

            expect(
                useWorldEntitiesMock,
            ).toHaveBeenLastCalledWith(
                "campaign-a",
                null,
                "",
                "next-cursor",
                false,
            )
            expect(
                screen.getByRole("button", { name: "Previous page" }),
            ).toBeInTheDocument()
        })

        it("discards the page history when a filter or search changes", () => {
            renderCampaignWorldPage()

            clickPager("Next page")
            clickPager("Next page")

            fireEvent.change(
                screen.getByRole("combobox", { name: "Category" }),
                { target: { value: "event" } },
            )

            expect(
                useWorldEntitiesMock,
            ).toHaveBeenLastCalledWith(
                "campaign-a",
                "event",
                "",
                null,
                false,
            )
            expect(
                screen.queryByRole("button", { name: "Previous page" }),
            ).not.toBeInTheDocument()

            // A fresh history under the new filter steps back to its own
            // first page, never to a cursor issued for the old filter.
            clickPager("Next page")
            typeInSearch("sundering")

            expect(
                screen.queryByRole("button", { name: "Previous page" }),
            ).not.toBeInTheDocument()

            clickPager("Next page")
            clickPager("Previous page")

            expect(
                useWorldEntitiesMock,
            ).toHaveBeenLastCalledWith(
                "campaign-a",
                "event",
                "sundering",
                null,
                false,
            )
            expect(
                useWorldEntitiesMock.mock.calls.some(
                    ([, category, , cursor]) =>
                        category === "event" && cursor === "third-cursor",
                ),
            ).toBe(false)
        })
    })

    it("keeps showing the previous results, busy, while a filter change refreshes", () => {
        renderCampaignWorldPage()

        expect(
            screen.getByText("Glass Harbor"),
        ).toBeInTheDocument()

        useWorldEntitiesMock.mockReturnValue({
            state: {
                status: "refreshing",
                page: worldPage,
            },
            retry: vi.fn(),
        })

        fireEvent.change(
            screen.getByRole("combobox", {
                name: "Category",
            }),
            {
                target: {
                    value: "event",
                },
            },
        )

        const resultsRegion = screen.getByRole(
            "region",
            {
                name: "World entities results",
            },
        )

        expect(resultsRegion).toHaveAttribute(
            "aria-busy",
            "true",
        )

        expect(
            screen.getByText("Glass Harbor"),
        ).toBeInTheDocument()

        expect(
            screen.queryByText("Updating results…"),
        ).not.toBeInTheDocument()

        act(() => {
            vi.advanceTimersByTime(200)
        })

        expect(
            screen.getByText("Updating results…"),
        ).toBeInTheDocument()
    })

    it("keeps a single page heading while the results region is loading", () => {
        useWorldEntitiesMock.mockReturnValue({
            state: {
                status: "loading",
            },
            retry: vi.fn(),
        })

        renderCampaignWorldPage()

        expect(
            screen.getAllByRole("heading", {
                level: 1,
            }),
        ).toHaveLength(1)

        expect(
            screen.getByRole("heading", {
                name: "World",
                level: 1,
            }),
        ).toBeInTheDocument()

        expect(
            screen.getByRole("heading", {
                name: "Loading world",
                level: 2,
            }),
        ).toBeInTheDocument()
    })

    it("keeps a single page heading while the results region shows an error", () => {
        useWorldEntitiesMock.mockReturnValue({
            state: {
                status: "error",
                error: new Error("boom"),
            },
            retry: vi.fn(),
        })

        renderCampaignWorldPage()

        expect(
            screen.getAllByRole("heading", {
                level: 1,
            }),
        ).toHaveLength(1)

        expect(
            screen.getByRole("heading", {
                name: "World",
                level: 1,
            }),
        ).toBeInTheDocument()

        expect(
            screen.getByRole("heading", {
                name: "World information unavailable",
                level: 2,
            }),
        ).toBeInTheDocument()
    })

    it("does not reload on every keystroke while typing a search", () => {
        renderCampaignWorldPage()

        const searchInput =
            screen.getByRole("searchbox", {
                name: "Search",
            })

        fireEvent.change(searchInput, {
            target: {
                value: "s",
            },
        })

        act(() => {
            vi.advanceTimersByTime(100)
        })

        fireEvent.change(searchInput, {
            target: {
                value: "su",
            },
        })

        act(() => {
            vi.advanceTimersByTime(100)
        })

        fireEvent.change(searchInput, {
            target: {
                value: "sun",
            },
        })

        expect(
            useWorldEntitiesMock,
        ).toHaveBeenLastCalledWith(
            "campaign-a",
            null,
            "",
            null,
            false,
        )

        act(() => {
            vi.advanceTimersByTime(300)
        })

        expect(
            useWorldEntitiesMock,
        ).toHaveBeenLastCalledWith(
            "campaign-a",
            null,
            "sun",
            null,
            false,
        )
    })

    it("keeps the search input mounted and focused while a new page loads", () => {
        // The mock stands in for the real hook, which only changes its
        // returned state once the (debounced) query it was called with
        // actually changes — key the mock off that argument so the test
        // reflects that instead of asserting on render-count timing.
        useWorldEntitiesMock.mockImplementation(
            (_campaignId, _category, query) =>
                query === ""
                    ? {
                        state: {
                            status: "success",
                            page: worldPage,
                        },
                        retry: vi.fn(),
                    }
                    : {
                        state: {
                            status: "loading",
                        },
                        retry: vi.fn(),
                    },
        )

        renderCampaignWorldPage()

        const searchInput =
            screen.getByRole("searchbox", {
                name: "Search",
            })

        searchInput.focus()
        expect(searchInput).toHaveFocus()

        fireEvent.change(searchInput, {
            target: {
                value: "g",
            },
        })

        expect(searchInput).toHaveValue("g")

        // The debounce hasn't elapsed: the hook is still being called with
        // the previous (empty) query, so its previous page remains.
        expect(
            useWorldEntitiesMock,
        ).toHaveBeenLastCalledWith(
            "campaign-a",
            null,
            "",
            null,
            false,
        )

        expect(
            screen.getByText("Glass Harbor"),
        ).toBeInTheDocument()

        act(() => {
            vi.advanceTimersByTime(180)
        })

        expect(
            useWorldEntitiesMock,
        ).toHaveBeenLastCalledWith(
            "campaign-a",
            null,
            "g",
            null,
            false,
        )

        expect(
            screen.getByRole("heading", {
                name: "World",
                level: 1,
            }),
        ).toBeInTheDocument()

        expect(
            screen.getByRole("searchbox", {
                name: "Search",
            }),
        ).toHaveFocus()

        expect(
            screen.queryByText("Glass Harbor"),
        ).not.toBeInTheDocument()
    })

    it("resets filters and pagination when the campaign changes", () => {
        render(
            <MemoryRouter
                initialEntries={[
                    "/app/campaign-a/world",
                ]}
            >
                <Routes>
                    <Route
                        path="/app/:campaignId/world"
                        element={
                            <>
                                <CampaignWorldPage />
                                <Link to="/app/campaign-b/world">
                                    Switch campaign
                                </Link>
                            </>
                        }
                    />
                </Routes>
            </MemoryRouter>,
        )

        fireEvent.change(
            screen.getByRole("combobox", {
                name: "Category",
            }),
            {
                target: {
                    value: "event",
                },
            },
        )

        typeInSearch("sundering")

        fireEvent.click(
            screen.getByRole("button", {
                name: "Next page",
            }),
        )

        expect(
            useWorldEntitiesMock,
        ).toHaveBeenLastCalledWith(
            "campaign-a",
            "event",
            "sundering",
            "next-cursor",
            false,
        )

        fireEvent.click(
            screen.getByRole("link", {
                name: "Switch campaign",
            }),
        )

        expect(
            useWorldEntitiesMock,
        ).toHaveBeenLastCalledWith(
            "campaign-b",
            null,
            "",
            null,
            false,
        )

        expect(
            screen.getByRole("searchbox", {
                name: "Search",
            }),
        ).toHaveValue("")

        expect(
            screen.getByRole("combobox", {
                name: "Category",
            }),
        ).toHaveValue("")
    })

    it("does not request World data without a campaign ID", () => {
        render(
            <MemoryRouter
                initialEntries={["/world"]}
            >
                <Routes>
                    <Route
                        path="/world"
                        element={<CampaignWorldPage />}
                    />
                </Routes>
            </MemoryRouter>,
        )

        expect(
            screen.getByRole("heading", {
                name: "World unavailable",
            }),
        ).toBeInTheDocument()

        expect(
            useWorldEntitiesMock,
        ).not.toHaveBeenCalled()
    })
})
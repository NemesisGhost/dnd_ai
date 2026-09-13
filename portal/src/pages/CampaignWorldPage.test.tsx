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
        )

        expect(
            screen.getByRole("heading", {
                name: "World",
                level: 1,
            }),
        ).toBeInTheDocument()

        expect(
            screen.getByRole("heading", {
                name: "Glass Harbor",
                level: 2,
            }),
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
        )

        typeInSearch("sundering")

        expect(
            useWorldEntitiesMock,
        ).toHaveBeenLastCalledWith(
            "campaign-a",
            "event",
            "sundering",
            null,
        )
    })

    it("keeps showing the previous results, busy, while a filter change refreshes", () => {
        renderCampaignWorldPage()

        expect(
            screen.getByRole("heading", {
                name: "Glass Harbor",
            }),
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
            screen.getByRole("heading", {
                name: "Glass Harbor",
            }),
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
        )
    })

    it("keeps the search input mounted and focused while a new page loads", () => {
        renderCampaignWorldPage()

        const searchInput =
            screen.getByRole("searchbox", {
                name: "Search",
            })

        searchInput.focus()
        expect(searchInput).toHaveFocus()

        useWorldEntitiesMock.mockReturnValue({
            state: {
                status: "loading",
            },
            retry: vi.fn(),
        })

        fireEvent.change(searchInput, {
            target: {
                value: "g",
            },
        })

        expect(searchInput).toHaveValue("g")

        expect(
            screen.getByRole("heading", {
                name: "Glass Harbor",
            }),
        ).toBeInTheDocument()

        act(() => {
            vi.advanceTimersByTime(300)
        })

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
            screen.queryByRole("heading", {
                name: "Glass Harbor",
            }),
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
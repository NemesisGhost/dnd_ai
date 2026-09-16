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
import { MemoryRouter } from "react-router"
import type { WorldEntityPage } from "../types/world"
import { WorldEntityList } from "./WorldEntityList"

const page: WorldEntityPage = {
    items: [
        {
            entity_id: "location-1",
            category: "location",
            entity_type_code: "city",
            name: "Glass Harbor",
            summary: "A harbor built around ancient glass towers.",
        },
        {
            entity_id: "event-1",
            category: "event",
            entity_type_code: "historical_event",
            name: "The Sundering",
            summary: null,
        },
        {
            entity_id: "org-1",
            category: "organization",
            entity_type_code: "business",
            name: "The Cartographers' Guild",
            summary: null,
        },
    ],
    next_cursor: "next-page-cursor",
}

function renderList(props: Partial<React.ComponentProps<typeof WorldEntityList>> = {}) {
    return render(
        <MemoryRouter>
            <WorldEntityList
                campaignId="campaign-a"
                page={page}
                onNextPage={vi.fn()}
                {...props}
            />
        </MemoryRouter>,
    )
}

describe("WorldEntityList", () => {
    it("renders each entity's name, readable category/type, and summary as a card", () => {
        renderList()

        expect(screen.getByText("Glass Harbor")).toBeInTheDocument()
        expect(screen.getByText("Location - City")).toBeInTheDocument()
        expect(
            screen.getByText(
                "A harbor built around ancient glass towers.",
            ),
        ).toBeInTheDocument()

        expect(screen.getByText("The Sundering")).toBeInTheDocument()
        expect(screen.getByText("Event - Historical Event")).toBeInTheDocument()

        expect(screen.queryByText("location-1")).not.toBeInTheDocument()
        expect(screen.queryByText("event-1")).not.toBeInTheDocument()
    })

    it("links supported categories to a campaign-scoped World detail route", () => {
        renderList()

        expect(
            screen.getByRole("link", { name: /Glass Harbor/ }),
        ).toHaveAttribute(
            "href",
            "/app/campaign-a/world/location/location-1",
        )

        expect(
            screen.getByRole("link", { name: /The Sundering/ }),
        ).toHaveAttribute("href", "/app/campaign-a/world/event/event-1")
    })

    it("renders an unsupported category (organization) as a non-interactive card", () => {
        renderList()

        expect(
            screen.queryByRole("link", {
                name: /The Cartographers' Guild/,
            }),
        ).not.toBeInTheDocument()
        expect(
            screen.getByText("The Cartographers' Guild"),
        ).toBeInTheDocument()
    })

    it("renders an empty state without disclosing entities", () => {
        renderList({
            page: {
                items: [],
                next_cursor: null,
            },
        })

        expect(
            screen.getByText(
                "No world entities match the current search.",
            ),
        ).toBeInTheDocument()

        expect(screen.queryByRole("list")).not.toBeInTheDocument()

        expect(
            screen.queryByRole("button", {
                name: "Next page",
            }),
        ).not.toBeInTheDocument()
    })

    it("requests the next page only when a cursor is available", () => {
        const onNextPage = vi.fn()

        const { rerender } = render(
            <MemoryRouter>
                <WorldEntityList
                    campaignId="campaign-a"
                    page={page}
                    onNextPage={onNextPage}
                />
            </MemoryRouter>,
        )

        fireEvent.click(
            screen.getByRole("button", {
                name: "Next page",
            }),
        )

        expect(onNextPage).toHaveBeenCalledTimes(1)

        rerender(
            <MemoryRouter>
                <WorldEntityList
                    campaignId="campaign-a"
                    page={{
                        ...page,
                        next_cursor: null,
                    }}
                    onNextPage={onNextPage}
                />
            </MemoryRouter>,
        )

        expect(
            screen.queryByRole("button", {
                name: "Next page",
            }),
        ).not.toBeInTheDocument()
    })

    describe("refreshing", () => {
        beforeEach(() => {
            vi.useFakeTimers()
        })

        afterEach(() => {
            vi.useRealTimers()
        })

        it("marks the results region busy and keeps the previous page visible", () => {
            renderList({ refreshing: true })

            expect(
                screen.getByRole("region", {
                    name: "World entities results",
                }),
            ).toHaveAttribute("aria-busy", "true")

            expect(screen.getByText("Glass Harbor")).toBeInTheDocument()
        })

        it("disables Next page while refreshing and re-enables it once settled", () => {
            const { rerender } = render(
                <MemoryRouter>
                    <WorldEntityList
                        campaignId="campaign-a"
                        page={page}
                        refreshing
                        onNextPage={vi.fn()}
                    />
                </MemoryRouter>,
            )

            expect(
                screen.getByRole("button", {
                    name: "Next page",
                }),
            ).toBeDisabled()

            rerender(
                <MemoryRouter>
                    <WorldEntityList
                        campaignId="campaign-a"
                        page={page}
                        refreshing={false}
                        onNextPage={vi.fn()}
                    />
                </MemoryRouter>,
            )

            expect(
                screen.getByRole("button", {
                    name: "Next page",
                }),
            ).toBeEnabled()
        })

        it("does not show the updating indicator immediately", () => {
            renderList({ refreshing: true })

            expect(
                screen.queryByText("Updating results…"),
            ).not.toBeInTheDocument()
        })

        it("shows the updating indicator once the refresh runs long enough to notice", () => {
            renderList({ refreshing: true })

            act(() => {
                vi.advanceTimersByTime(200)
            })

            expect(
                screen.getByText("Updating results…"),
            ).toBeInTheDocument()
        })

        it("hides the updating indicator once the refresh finishes", () => {
            const { rerender } = render(
                <MemoryRouter>
                    <WorldEntityList
                        campaignId="campaign-a"
                        page={page}
                        refreshing
                        onNextPage={vi.fn()}
                    />
                </MemoryRouter>,
            )

            act(() => {
                vi.advanceTimersByTime(200)
            })

            expect(
                screen.getByText("Updating results…"),
            ).toBeInTheDocument()

            rerender(
                <MemoryRouter>
                    <WorldEntityList
                        campaignId="campaign-a"
                        page={page}
                        refreshing={false}
                        onNextPage={vi.fn()}
                    />
                </MemoryRouter>,
            )

            expect(
                screen.queryByText("Updating results…"),
            ).not.toBeInTheDocument()

            expect(
                screen.getByRole("region", {
                    name: "World entities results",
                }),
            ).toHaveAttribute("aria-busy", "false")
        })
    })
})

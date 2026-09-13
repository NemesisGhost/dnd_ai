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
    ],
    next_cursor: "next-page-cursor",
}

describe("WorldEntityList", () => {
    it("renders each entity's name, readable category/type, and summary", () => {
        render(
            <WorldEntityList
                page={page}
                onNextPage={vi.fn()}
            />,
        )

        expect(
            screen.getByRole("heading", {
                name: "Glass Harbor",
                level: 2,
            }),
        ).toBeInTheDocument()

        expect(
            screen.getByText("Location - City"),
        ).toBeInTheDocument()

        expect(
            screen.getByText(
                "A harbor built around ancient glass towers.",
            ),
        ).toBeInTheDocument()

        expect(
            screen.getByRole("heading", {
                name: "The Sundering",
                level: 2,
            }),
        ).toBeInTheDocument()

        expect(
            screen.getByText(
                "Event - Historical Event",
            ),
        ).toBeInTheDocument()

        expect(
            screen.getByText("No summary recorded."),
        ).toBeInTheDocument()

        expect(
            screen.queryByText("location-1"),
        ).not.toBeInTheDocument()
        expect(
            screen.queryByText("event-1"),
        ).not.toBeInTheDocument()
    })

    it("renders an empty state without disclosing entities", () => {
        render(
            <WorldEntityList
                page={{
                    items: [],
                    next_cursor: null,
                }}
                onNextPage={vi.fn()}
            />,
        )

        expect(
            screen.getByText(
                "No world entities match the current search.",
            ),
        ).toBeInTheDocument()

        expect(
            screen.queryByRole("list"),
        ).not.toBeInTheDocument()

        expect(
            screen.queryByRole("button", {
                name: "Next page",
            }),
        ).not.toBeInTheDocument()
    })

    it("requests the next page only when a cursor is available", () => {
        const onNextPage = vi.fn()

        const { rerender } = render(
            <WorldEntityList
                page={page}
                onNextPage={onNextPage}
            />,
        )

        fireEvent.click(
            screen.getByRole("button", {
                name: "Next page",
            }),
        )

        expect(onNextPage).toHaveBeenCalledTimes(1)

        rerender(
            <WorldEntityList
                page={{
                    ...page,
                    next_cursor: null,
                }}
                onNextPage={onNextPage}
            />,
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
            render(
                <WorldEntityList
                    page={page}
                    refreshing
                    onNextPage={vi.fn()}
                />,
            )

            expect(
                screen.getByRole("region", {
                    name: "World entities results",
                }),
            ).toHaveAttribute("aria-busy", "true")

            expect(
                screen.getByRole("heading", {
                    name: "Glass Harbor",
                }),
            ).toBeInTheDocument()
        })

        it("disables Next page while refreshing and re-enables it once settled", () => {
            const { rerender } = render(
                <WorldEntityList
                    page={page}
                    refreshing
                    onNextPage={vi.fn()}
                />,
            )

            expect(
                screen.getByRole("button", {
                    name: "Next page",
                }),
            ).toBeDisabled()

            rerender(
                <WorldEntityList
                    page={page}
                    refreshing={false}
                    onNextPage={vi.fn()}
                />,
            )

            expect(
                screen.getByRole("button", {
                    name: "Next page",
                }),
            ).toBeEnabled()
        })

        it("does not show the updating indicator immediately", () => {
            render(
                <WorldEntityList
                    page={page}
                    refreshing
                    onNextPage={vi.fn()}
                />,
            )

            expect(
                screen.queryByText("Updating results…"),
            ).not.toBeInTheDocument()
        })

        it("shows the updating indicator once the refresh runs long enough to notice", () => {
            render(
                <WorldEntityList
                    page={page}
                    refreshing
                    onNextPage={vi.fn()}
                />,
            )

            act(() => {
                vi.advanceTimersByTime(200)
            })

            expect(
                screen.getByText("Updating results…"),
            ).toBeInTheDocument()
        })

        it("hides the updating indicator once the refresh finishes", () => {
            const { rerender } = render(
                <WorldEntityList
                    page={page}
                    refreshing
                    onNextPage={vi.fn()}
                />,
            )

            act(() => {
                vi.advanceTimersByTime(200)
            })

            expect(
                screen.getByText("Updating results…"),
            ).toBeInTheDocument()

            rerender(
                <WorldEntityList
                    page={page}
                    refreshing={false}
                    onNextPage={vi.fn()}
                />,
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

import {
    fireEvent,
    render,
    screen,
} from "@testing-library/react"
import {
    beforeEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import type {
    WorldEntityPage,
} from "../types/world"
import {
    WorldEntitiesBoundary,
} from "./WorldEntitiesBoundary"

const {
    retryMock,
    useWorldEntitiesMock,
} = vi.hoisted(() => ({
    retryMock: vi.fn(),
    useWorldEntitiesMock: vi.fn(),
}))

vi.mock("../hooks/useWorldEntities", () => ({
    useWorldEntities: useWorldEntitiesMock,
}))

const worldPageFixture = {
    items: [
        {
            entity_id: "location-a",
            category: "location",
            entity_type_code: "dungeon",
            name: "The Glass Ossuary",
            summary: "An ancient facility.",
        },
        {
            entity_id: "event-a",
            category: "event",
            entity_type_code: "event",
            name: "The Sundering",
            summary: null,
        },
    ],
    next_cursor: "next-world-page",
} satisfies WorldEntityPage

function renderBoundary() {
    render(
        <WorldEntitiesBoundary
            campaignId="campaign-a"
            category="location"
            query="glass"
            cursor="world-cursor"
        >
            {(page) => (
                <ul>
                    {page.items.map((entity) => (
                        <li key={entity.entity_id}>
                            {entity.name}
                        </li>
                    ))}
                </ul>
            )}
        </WorldEntitiesBoundary>,
    )
}

beforeEach(() => {
    retryMock.mockReset()
    useWorldEntitiesMock.mockReset()
})

describe("WorldEntitiesBoundary", () => {
    it("shows loading without rendering stale content", () => {
        useWorldEntitiesMock.mockReturnValue({
            state: {
                status: "loading",
            },
            retry: retryMock,
        })

        renderBoundary()

        expect(
            screen.getByRole("heading", {
                name: "Loading world",
            }),
        ).toBeInTheDocument()

        expect(
            screen.queryByText("The Glass Ossuary"),
        ).not.toBeInTheDocument()

        expect(
            useWorldEntitiesMock,
        ).toHaveBeenCalledWith(
            "campaign-a",
            "location",
            "glass",
            "world-cursor",
        )
    })

    it("shows a non-disclosing unavailable state", () => {
        useWorldEntitiesMock.mockReturnValue({
            state: {
                status: "unavailable",
            },
            retry: retryMock,
        })

        renderBoundary()

        expect(
            screen.getByRole("heading", {
                name: "World unavailable",
            }),
        ).toBeInTheDocument()

        expect(
            screen.getByText(
                "The requested world information is not available.",
            ),
        ).toBeInTheDocument()

        expect(
            screen.queryByText("The Glass Ossuary"),
        ).not.toBeInTheDocument()
    })

    it("shows a safe recoverable error and retries", () => {
        const diagnosticError = new Error(
            "Database failure on an internal host",
        )

        useWorldEntitiesMock.mockReturnValue({
            state: {
                status: "error",
                error: diagnosticError,
            },
            retry: retryMock,
        })

        renderBoundary()

        expect(
            screen.getByRole("heading", {
                name: "World information unavailable",
            }),
        ).toBeInTheDocument()

        expect(
            screen.queryByText(
                diagnosticError.message,
            ),
        ).not.toBeInTheDocument()

        expect(
            screen.queryByText("The Glass Ossuary"),
        ).not.toBeInTheDocument()

        fireEvent.click(
            screen.getByRole("button", {
                name: "Try again",
            }),
        )

        expect(retryMock).toHaveBeenCalledTimes(1)
    })

    it("renders only the successful authorized page", () => {
        useWorldEntitiesMock.mockReturnValue({
            state: {
                status: "success",
                page: worldPageFixture,
            },
            retry: retryMock,
        })

        renderBoundary()

        expect(
            screen.getByText("The Glass Ossuary"),
        ).toBeInTheDocument()

        expect(
            screen.getByText("The Sundering"),
        ).toBeInTheDocument()

        expect(
            screen.queryByRole("button", {
                name: "Try again",
            }),
        ).not.toBeInTheDocument()
    })

    it("passes a false refreshing flag alongside a successful page", () => {
        useWorldEntitiesMock.mockReturnValue({
            state: {
                status: "success",
                page: worldPageFixture,
            },
            retry: retryMock,
        })

        const childrenSpy = vi.fn(() => <p>Rendered</p>)

        render(
            <WorldEntitiesBoundary
                campaignId="campaign-a"
                category="location"
                query="glass"
            >
                {childrenSpy}
            </WorldEntitiesBoundary>,
        )

        expect(childrenSpy).toHaveBeenCalledWith(
            worldPageFixture,
            false,
        )
    })

    it("keeps the previous page visible with a true refreshing flag while refreshing", () => {
        useWorldEntitiesMock.mockReturnValue({
            state: {
                status: "refreshing",
                page: worldPageFixture,
            },
            retry: retryMock,
        })

        const childrenSpy = vi.fn(() => <p>Rendered</p>)

        render(
            <WorldEntitiesBoundary
                campaignId="campaign-a"
                category="location"
                query="glass"
            >
                {childrenSpy}
            </WorldEntitiesBoundary>,
        )

        expect(childrenSpy).toHaveBeenCalledWith(
            worldPageFixture,
            true,
        )
    })
})
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
import {
    knowledgePageFixture,
} from "../fixtures/knowledge"
import {
    KnowledgeItemsBoundary,
} from "./KnowledgeItemsBoundary"

const {
    retryMock,
    useKnowledgeItemsMock,
} = vi.hoisted(() => ({
    retryMock: vi.fn(),
    useKnowledgeItemsMock: vi.fn(),
}))

vi.mock("../hooks/useKnowledgeItems", () => ({
    useKnowledgeItems: useKnowledgeItemsMock,
}))

function renderBoundary() {
    render(
        <KnowledgeItemsBoundary
            campaignId="campaign-a"
            view="party_shared"
            characterId="character-a"
            partyId="party-a"
            query="glass"
            knowledgeType="fact"
            cursor="knowledge-cursor"
        >
            {(page) => (
                <ul>
                    {page.items.map((item) => (
                        <li
                            key={
                                item.knowledge_item_id
                            }
                        >
                            {item.statement}
                        </li>
                    ))}
                </ul>
            )}
        </KnowledgeItemsBoundary>,
    )
}

beforeEach(() => {
    retryMock.mockReset()
    useKnowledgeItemsMock.mockReset()
})

describe("KnowledgeItemsBoundary", () => {
    it("shows loading without rendering retained content", () => {
        useKnowledgeItemsMock.mockReturnValue({
            state: {
                status: "loading",
            },
            retry: retryMock,
        })

        renderBoundary()

        expect(
            screen.getByRole("region", {
                name: "Knowledge results",
            }),
        ).toHaveAttribute("aria-busy", "true")

        expect(
            screen.getByRole("heading", {
                name: "Loading knowledge",
                level: 2,
            }),
        ).toBeInTheDocument()

        expect(
            screen.queryByText(
                knowledgePageFixture.items[0]
                    .statement,
            ),
        ).not.toBeInTheDocument()

        expect(
            useKnowledgeItemsMock,
        ).toHaveBeenCalledWith(
            "campaign-a",
            "party_shared",
            "character-a",
            "party-a",
            "glass",
            "fact",
            "knowledge-cursor",
        )
    })

    it("shows a non-disclosing unavailable state", () => {
        useKnowledgeItemsMock.mockReturnValue({
            state: {
                status: "unavailable",
            },
            retry: retryMock,
        })

        renderBoundary()

        expect(
            screen.getByRole("heading", {
                name: "Knowledge unavailable",
                level: 2,
            }),
        ).toBeInTheDocument()

        expect(
            screen.getByText(
                "The requested knowledge is not available.",
            ),
        ).toBeInTheDocument()

        expect(
            screen.queryByText(
                knowledgePageFixture.items[0]
                    .statement,
            ),
        ).not.toBeInTheDocument()
    })

    it("shows a safe recoverable error and retries", () => {
        const diagnosticError = new Error(
            "Database failure on internal-host-7",
        )

        useKnowledgeItemsMock.mockReturnValue({
            state: {
                status: "error",
                error: diagnosticError,
            },
            retry: retryMock,
        })

        renderBoundary()

        expect(
            screen.getByRole("heading", {
                name: "Knowledge information unavailable",
                level: 2,
            }),
        ).toBeInTheDocument()

        expect(
            screen.queryByText(
                diagnosticError.message,
            ),
        ).not.toBeInTheDocument()

        expect(
            screen.queryByText(
                knowledgePageFixture.items[0]
                    .statement,
            ),
        ).not.toBeInTheDocument()

        fireEvent.click(
            screen.getByRole("button", {
                name: "Try again",
            }),
        )

        expect(retryMock).toHaveBeenCalledTimes(1)
    })

    it("renders the successful authorized page", () => {
        useKnowledgeItemsMock.mockReturnValue({
            state: {
                status: "success",
                page: knowledgePageFixture,
            },
            retry: retryMock,
        })

        renderBoundary()

        expect(
            screen.getByText(
                knowledgePageFixture.items[0]
                    .statement,
            ),
        ).toBeInTheDocument()

        expect(
            screen.getByText(
                knowledgePageFixture.items[1]
                    .statement,
            ),
        ).toBeInTheDocument()

        expect(
            screen.queryByRole("button", {
                name: "Try again",
            }),
        ).not.toBeInTheDocument()
    })

    it("passes false to children for a completed page", () => {
        useKnowledgeItemsMock.mockReturnValue({
            state: {
                status: "success",
                page: knowledgePageFixture,
            },
            retry: retryMock,
        })

        const childrenSpy = vi.fn(
            () => <p>Rendered</p>,
        )

        render(
            <KnowledgeItemsBoundary
                campaignId="campaign-a"
                view="known"
                characterId="character-a"
                partyId="party-a"
                query=""
                knowledgeType={null}
            >
                {childrenSpy}
            </KnowledgeItemsBoundary>,
        )

        expect(childrenSpy).toHaveBeenCalledWith(
            knowledgePageFixture,
            false,
        )
    })

    it("passes true to children while retaining a refreshing page", () => {
        useKnowledgeItemsMock.mockReturnValue({
            state: {
                status: "refreshing",
                page: knowledgePageFixture,
            },
            retry: retryMock,
        })

        const childrenSpy = vi.fn(
            () => <p>Rendered</p>,
        )

        render(
            <KnowledgeItemsBoundary
                campaignId="campaign-a"
                view="known"
                characterId="character-a"
                partyId="party-a"
                query="updated search"
                knowledgeType={null}
            >
                {childrenSpy}
            </KnowledgeItemsBoundary>,
        )

        expect(childrenSpy).toHaveBeenCalledWith(
            knowledgePageFixture,
            true,
        )
    })
})
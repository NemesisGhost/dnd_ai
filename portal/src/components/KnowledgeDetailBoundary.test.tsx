import { render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { KnowledgeRequestError } from "../api/knowledge"
import type { KnowledgeDetail } from "../types/knowledge"
import { KnowledgeDetailBoundary } from "./KnowledgeDetailBoundary"

const { fetchKnowledgeDetailMock, reloadMock } = vi.hoisted(() => ({
    fetchKnowledgeDetailMock: vi.fn(),
    reloadMock: vi.fn(),
}))

vi.mock("../api/knowledge", async (importOriginal) => {
    const actual = await importOriginal<typeof import("../api/knowledge")>()
    return {
        ...actual,
        fetchKnowledgeDetail: fetchKnowledgeDetailMock,
    }
})

vi.mock("../context/SessionContext", () => ({
    useSession: () => ({ reload: reloadMock }),
}))

const itemFixture: KnowledgeDetail = {
    knowledge_item_id: "knowledge-a",
    knowledge_type_code: "fact",
    statement: "The Glass Ossuary lies beneath the Rootspire.",
    truth_status_code: null,
    sensitivity: null,
    awareness_level: "understood",
    confidence: 85,
    willing_to_share: true,
}

beforeEach(() => {
    fetchKnowledgeDetailMock.mockReset()
    reloadMock.mockReset()
})

describe("KnowledgeDetailBoundary", () => {
    it("shows a loading state, then the loaded item", async () => {
        fetchKnowledgeDetailMock.mockResolvedValue(itemFixture)

        render(
            <KnowledgeDetailBoundary
                campaignId="campaign-a"
                knowledgeItemId="knowledge-a"
                characterId={null}
                partyId={null}
            >
                {(item) => <p>{item.statement}</p>}
            </KnowledgeDetailBoundary>,
        )

        expect(screen.getByText("Loading knowledge")).toBeInTheDocument()

        await waitFor(() => {
            expect(screen.getByText(itemFixture.statement)).toBeInTheDocument()
        })
    })

    it.each([403, 404])(
        "shows a non-disclosing unavailable state for HTTP %s",
        async (status) => {
            fetchKnowledgeDetailMock.mockRejectedValue(
                new KnowledgeRequestError(status),
            )

            render(
                <KnowledgeDetailBoundary
                    campaignId="campaign-a"
                    knowledgeItemId="knowledge-a"
                    characterId={null}
                    partyId={null}
                >
                    {(item) => <p>{item.statement}</p>}
                </KnowledgeDetailBoundary>,
            )

            await waitFor(() => {
                expect(
                    screen.getByText("Knowledge unavailable"),
                ).toBeInTheDocument()
            })
        },
    )

    it("shows a recoverable error with a retry action", async () => {
        fetchKnowledgeDetailMock.mockRejectedValue(new Error("boom"))

        render(
            <KnowledgeDetailBoundary
                campaignId="campaign-a"
                knowledgeItemId="knowledge-a"
                characterId={null}
                partyId={null}
            >
                {(item) => <p>{item.statement}</p>}
            </KnowledgeDetailBoundary>,
        )

        await waitFor(() => {
            expect(
                screen.getByText("Knowledge information unavailable"),
            ).toBeInTheDocument()
        })

        expect(
            screen.getByRole("button", { name: "Try again" }),
        ).toBeInTheDocument()
    })
})

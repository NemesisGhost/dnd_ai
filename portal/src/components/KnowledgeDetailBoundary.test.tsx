import { render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { KnowledgeRequestError } from "../api/knowledge"
import type { KnowledgeDetail } from "../types/knowledge"
import { KnowledgeDetailBoundary } from "./KnowledgeDetailBoundary"

const { fetchKnowledgeDetailMock, reloadMock, refreshMock, sessionRef } = vi.hoisted(() => ({
    fetchKnowledgeDetailMock: vi.fn(),
    reloadMock: vi.fn(),
    refreshMock: vi.fn(),
    // The session state the boundary compares a rechecked party against (absent in isolation).
    sessionRef: { state: undefined as unknown },
}))

vi.mock("../api/knowledge", async (importOriginal) => {
    const actual = await importOriginal<typeof import("../api/knowledge")>()
    return {
        ...actual,
        fetchKnowledgeDetail: fetchKnowledgeDetailMock,
    }
})

vi.mock("../context/SessionContext", () => ({
    useSession: () => ({ reload: reloadMock, refresh: refreshMock, state: sessionRef.state }),
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
    refreshMock.mockReset()
    refreshMock.mockResolvedValue(true)
    sessionRef.state = undefined
})

function sessionWith(partyIds: string[], extra: Record<string, unknown> = {}) {
    sessionRef.state = {
        status: "authenticated",
        bootstrap: {
            campaigns: [
                {
                    campaign_id: "campaign-a",
                    character_perspectives: [
                        {
                            character_id: "char",
                            character_name: "Aria",
                            authorized_parties: partyIds.map((id) => ({ party_id: id, party_name: id })),
                        },
                    ],
                    ...extra,
                },
            ],
        },
    }
}

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

describe("KnowledgeDetailBoundary: a party-scoped not-found", () => {
    function renderParty(onPartyRevoked: (id: string) => void) {
        return render(
            <KnowledgeDetailBoundary
                campaignId="campaign-a"
                knowledgeItemId="knowledge-a"
                characterId="char"
                partyId="p1"
                onPartyRevoked={onPartyRevoked}
            >
                {(item) => <p>{item.statement}</p>}
            </KnowledgeDetailBoundary>,
        )
    }

    it("asks the page to drop the party once a refreshed bootstrap no longer authorizes it", async () => {
        sessionWith(["p2"])
        fetchKnowledgeDetailMock.mockRejectedValue(new KnowledgeRequestError(404))
        const onPartyRevoked = vi.fn()
        renderParty(onPartyRevoked)

        await waitFor(() => expect(onPartyRevoked).toHaveBeenCalledWith("p1"))
        expect(refreshMock).toHaveBeenCalledTimes(1)
        expect(fetchKnowledgeDetailMock).toHaveBeenCalledTimes(1)
    })

    it("keeps a genuine 'unavailable' and does not drop a party that is still authorized", async () => {
        sessionWith(["p1", "p2"])
        fetchKnowledgeDetailMock.mockRejectedValue(new KnowledgeRequestError(404))
        const onPartyRevoked = vi.fn()
        renderParty(onPartyRevoked)

        expect(await screen.findByText("Knowledge unavailable")).toBeInTheDocument()
        expect(onPartyRevoked).not.toHaveBeenCalled()
        expect(refreshMock).toHaveBeenCalledTimes(1)
    })

    it("treats a failed eligibility refresh as uncertainty: a retry action, no clearing", async () => {
        sessionWith(["p2"])
        refreshMock.mockRejectedValue(new Error("offline"))
        fetchKnowledgeDetailMock.mockRejectedValue(new KnowledgeRequestError(404))
        const onPartyRevoked = vi.fn()
        renderParty(onPartyRevoked)

        expect(await screen.findByRole("button", { name: "Try again" })).toBeInTheDocument()
        expect(onPartyRevoked).not.toHaveBeenCalled()
    })

    it("compares against the route campaign's own character, not another campaign's parties", async () => {
        sessionRef.state = {
            status: "authenticated",
            bootstrap: {
                campaigns: [
                    { campaign_id: "other", character_perspectives: [{ character_id: "char", character_name: "Aria", authorized_parties: [{ party_id: "p1", party_name: "p1" }] }] },
                    { campaign_id: "campaign-a", character_perspectives: [{ character_id: "char", character_name: "Aria", authorized_parties: [] }] },
                ],
            },
        }
        fetchKnowledgeDetailMock.mockRejectedValue(new KnowledgeRequestError(404))
        const onPartyRevoked = vi.fn()
        renderParty(onPartyRevoked)
        await waitFor(() => expect(onPartyRevoked).toHaveBeenCalledWith("p1"))
    })
})

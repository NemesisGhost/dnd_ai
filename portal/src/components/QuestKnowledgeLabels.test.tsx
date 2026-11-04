import { act, render, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { QuestRequestError } from "../api/quests"
import { KnowledgeRequestError } from "../api/knowledge"
import { BreadcrumbLabelContext, LabelRegistry } from "../navigation/BreadcrumbLabelContext"
import { labelKey } from "../navigation/labelRegistry"
import type { QuestDetail } from "../types/quest"
import type { KnowledgeDetail } from "../types/knowledge"
import { KnowledgeDetailBoundary } from "./KnowledgeDetailBoundary"
import { QuestDetailBoundary } from "./QuestDetailBoundary"

// P02-7b: the quest's name and the claim's statement are registered as breadcrumb labels from the read
// the boundary already makes, into the registry that was in force when the request STARTED, and are
// dropped by a refused answer. Nothing is registered from any other state.

const { fetchQuestMock, fetchKnowledgeDetailMock, sessionMock } = vi.hoisted(() => ({
    fetchQuestMock: vi.fn(),
    fetchKnowledgeDetailMock: vi.fn(),
    // One stable value: the hooks depend on `reload`, so a new one per render would read forever.
    sessionMock: { reload: vi.fn(), refresh: vi.fn(async () => false), state: { status: "loading" } },
}))

vi.mock("../api/quests", async (importOriginal) => ({
    ...(await importOriginal<typeof import("../api/quests")>()),
    fetchQuest: fetchQuestMock,
}))
vi.mock("../api/knowledge", async (importOriginal) => ({
    ...(await importOriginal<typeof import("../api/knowledge")>()),
    fetchKnowledgeDetail: fetchKnowledgeDetailMock,
}))
vi.mock("../context/SessionContext", () => ({
    useSession: () => sessionMock,
}))

const quest = { quest_id: "q1", name: "The Siege", status_code: "active", stages: [] } as unknown as QuestDetail
const claim = { knowledge_item_id: "k1", statement: "The duke is a vampire." } as unknown as KnowledgeDetail
const questKey = labelKey("quests.detail", { campaignId: "c1", questId: "q1" })
const claimKey = labelKey("knowledge.detail", { campaignId: "c1", knowledgeItemId: "k1" })

function renderIn(registry: LabelRegistry, node: React.ReactNode) {
    return render(<BreadcrumbLabelContext.Provider value={registry}>{node}</BreadcrumbLabelContext.Provider>)
}

const questBoundary = () => (
    <QuestDetailBoundary campaignId="c1" questId="q1" characterId={null}>
        {() => <p>quest</p>}
    </QuestDetailBoundary>
)
const claimBoundary = () => (
    <KnowledgeDetailBoundary campaignId="c1" knowledgeItemId="k1" characterId={null} partyId={null}>
        {() => <p>claim</p>}
    </KnowledgeDetailBoundary>
)

beforeEach(() => {
    fetchQuestMock.mockReset()
    fetchKnowledgeDetailMock.mockReset()
})

describe("quest and claim labels", () => {
    it("registers the quest's name from its authorized read, and only then", async () => {
        const registry = new LabelRegistry()
        let answer: (value: QuestDetail) => void = () => undefined
        fetchQuestMock.mockReturnValue(new Promise<QuestDetail>((resolve) => (answer = resolve)))
        renderIn(registry, questBoundary())
        expect(registry.labelFor(questKey)).toBeUndefined()
        await act(async () => {
            answer(quest)
        })
        await waitFor(() => expect(registry.labelFor(questKey)).toBe("The Siege"))
    })

    it("registers the claim's statement, and drops it when the read is refused", async () => {
        const registry = new LabelRegistry()
        fetchKnowledgeDetailMock.mockResolvedValue(claim)
        const view = renderIn(registry, claimBoundary())
        await waitFor(() => expect(registry.labelFor(claimKey)).toBe("The duke is a vampire."))
        // A later read of the same claim is refused (access ended): the label goes.
        fetchKnowledgeDetailMock.mockRejectedValue(new KnowledgeRequestError(404))
        view.unmount()
        const again = renderIn(registry, claimBoundary())
        await waitFor(() => expect(registry.labelFor(claimKey)).toBeUndefined())
        again.unmount()
    })

    it("a quest answer that arrives after the authority changed is ignored: it reaches the closed registry", async () => {
        const first = new LabelRegistry()
        const second = new LabelRegistry()
        let answer: (value: QuestDetail) => void = () => undefined
        fetchQuestMock.mockReturnValue(new Promise<QuestDetail>((resolve) => (answer = resolve)))
        const view = renderIn(first, questBoundary())
        // The authority changes while the page stays mounted: a new registry, the old one closed.
        first.close()
        view.rerender(<BreadcrumbLabelContext.Provider value={second}>{questBoundary()}</BreadcrumbLabelContext.Provider>)
        await act(async () => {
            answer(quest)
        })
        await waitFor(() => expect(fetchQuestMock).toHaveBeenCalled())
        expect(first.labelFor(questKey)).toBeUndefined()
        expect(second.labelFor(questKey)).toBeUndefined()
    })

    it("a claim answer that arrives after the authority changed is ignored too", async () => {
        const first = new LabelRegistry()
        const second = new LabelRegistry()
        let answer: (value: KnowledgeDetail) => void = () => undefined
        fetchKnowledgeDetailMock.mockReturnValue(new Promise<KnowledgeDetail>((resolve) => (answer = resolve)))
        const view = renderIn(first, claimBoundary())
        first.close()
        view.rerender(<BreadcrumbLabelContext.Provider value={second}>{claimBoundary()}</BreadcrumbLabelContext.Provider>)
        await act(async () => {
            answer(claim)
        })
        expect(first.labelFor(claimKey)).toBeUndefined()
        expect(second.labelFor(claimKey)).toBeUndefined()
    })

    it("registers nothing for an unavailable or failed quest read", async () => {
        const registry = new LabelRegistry()
        fetchQuestMock.mockRejectedValue(new QuestRequestError(404))
        renderIn(registry, questBoundary())
        await waitFor(() => expect(fetchQuestMock).toHaveBeenCalled())
        await act(async () => undefined)
        expect(registry.labelFor(questKey)).toBeUndefined()
    })
})

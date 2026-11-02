import { act, renderHook, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { KnowledgeRequestError } from "../api/knowledge"
import { QuestRequestError } from "../api/quests"
import type { CampaignQuestListItem } from "../types/quest"
import { useCampaignQuests } from "./useCampaignQuests"
import { useKnowledgeDetail } from "./useKnowledgeDetail"
import { useKnowledgeItems } from "./useKnowledgeItems"
import { useQuest } from "./useQuest"

const mocks = vi.hoisted(() => ({
    fetchCampaignQuests: vi.fn(),
    fetchQuest: vi.fn(),
    fetchKnowledgeItems: vi.fn(),
    fetchKnowledgeDetail: vi.fn(),
    reload: vi.fn(),
    refresh: vi.fn(),
}))

vi.mock("../api/quests", async (importOriginal) => ({
    ...(await importOriginal<typeof import("../api/quests")>()),
    fetchCampaignQuests: mocks.fetchCampaignQuests,
    fetchQuest: mocks.fetchQuest,
}))
vi.mock("../api/knowledge", async (importOriginal) => ({
    ...(await importOriginal<typeof import("../api/knowledge")>()),
    fetchKnowledgeItems: mocks.fetchKnowledgeItems,
    fetchKnowledgeDetail: mocks.fetchKnowledgeDetail,
}))
vi.mock("../context/SessionContext", () => ({
    useSession: () => ({ reload: mocks.reload, refresh: mocks.refresh }),
}))

const PARTY_QUESTS: CampaignQuestListItem[] = [{ quest_id: "q-party", name: "Party-private quest", status_code: "active" }]
const PLAIN_QUESTS: CampaignQuestListItem[] = [{ quest_id: "q-open", name: "Campaign-wide quest", status_code: "active" }]

interface Deferred<T> {
    promise: Promise<T>
    resolve: (value: T) => void
    reject: (error: unknown) => void
}

function deferred<T>(): Deferred<T> {
    let resolve!: (value: T) => void
    let reject!: (error: unknown) => void
    const promise = new Promise<T>((res, rej) => {
        resolve = res
        reject = rej
    })
    return { promise, resolve, reject }
}

beforeEach(() => {
    for (const mock of Object.values(mocks)) mock.mockReset()
    mocks.reload.mockResolvedValue(undefined)
    mocks.refresh.mockResolvedValue(true)
})

describe("party-scoped not-found recovery: quest list", () => {
    const render = (initial: { party: string | null }) =>
        renderHook(({ party }) => useCampaignQuests("c1", "char", party), { initialProps: initial })

    it("refreshes eligibility once, and when the party stays authorized keeps a plain 'unavailable' without broadening the request", async () => {
        mocks.fetchCampaignQuests.mockRejectedValue(new QuestRequestError(404))
        const { result } = render({ party: "p1" })

        await waitFor(() => expect(result.current.state).toEqual({ status: "unavailable" }))
        expect(mocks.refresh).toHaveBeenCalledTimes(1)
        expect(mocks.fetchCampaignQuests).toHaveBeenCalledTimes(1)
        expect(mocks.fetchCampaignQuests.mock.calls[0]!.slice(0, 3)).toEqual(["c1", "char", "p1"])
    })

    it("keeps nothing of the party while the refresh is pending, then reads the no-party view once when the party is gone", async () => {
        const refresh = deferred<boolean>()
        mocks.refresh.mockReturnValue(refresh.promise)
        mocks.fetchCampaignQuests.mockImplementation((_c: string, _ch: string, party: string | null) =>
            party === null ? Promise.resolve(PLAIN_QUESTS) : Promise.reject(new QuestRequestError(404)),
        )
        const { result, rerender } = render({ party: "p1" })

        await waitFor(() => expect(mocks.refresh).toHaveBeenCalledTimes(1))
        // Pending: still loading, no party-scoped content and no second request.
        expect(result.current.state).toEqual({ status: "loading" })
        expect(mocks.fetchCampaignQuests).toHaveBeenCalledTimes(1)

        // The refreshed bootstrap no longer authorizes the party, so the page derives no party.
        rerender({ party: null })
        await act(async () => refresh.resolve(true))
        await waitFor(() => expect(result.current.state).toEqual({ status: "success", quests: PLAIN_QUESTS }))
        expect(mocks.fetchCampaignQuests).toHaveBeenCalledTimes(2)
        expect(mocks.fetchCampaignQuests.mock.calls[1]!.slice(0, 3)).toEqual(["c1", "char", null])
        expect(mocks.refresh).toHaveBeenCalledTimes(1)
    })

    it("shows actionable recovery, not a fallback, when the refresh fails; Try again is a new episode", async () => {
        mocks.refresh.mockRejectedValueOnce(new Error("offline"))
        mocks.fetchCampaignQuests.mockRejectedValue(new QuestRequestError(404))
        const { result } = render({ party: "p1" })

        await waitFor(() => expect(result.current.state.status).toBe("error"))
        expect(mocks.fetchCampaignQuests).toHaveBeenCalledTimes(1)
        expect(mocks.refresh).toHaveBeenCalledTimes(1)

        act(() => result.current.retry())
        await waitFor(() => expect(result.current.state.status).toBe("unavailable"))
        expect(mocks.refresh).toHaveBeenCalledTimes(2)
        expect(mocks.fetchCampaignQuests).toHaveBeenCalledTimes(2)
    })

    it("does not refresh again for the same episode when the page re-renders", async () => {
        mocks.fetchCampaignQuests.mockRejectedValue(new QuestRequestError(404))
        const { result, rerender } = render({ party: "p1" })
        await waitFor(() => expect(result.current.state.status).toBe("unavailable"))
        rerender({ party: "p1" })
        rerender({ party: "p1" })
        expect(mocks.refresh).toHaveBeenCalledTimes(1)
        expect(mocks.fetchCampaignQuests).toHaveBeenCalledTimes(1)
    })

    it("ignores a late recovery from an obsolete party and never overwrites a newer deliberate selection", async () => {
        const refresh = deferred<boolean>()
        mocks.refresh.mockReturnValue(refresh.promise)
        mocks.fetchCampaignQuests.mockImplementation((_c: string, _ch: string, party: string | null) =>
            party === "p2" ? Promise.resolve(PARTY_QUESTS) : Promise.reject(new QuestRequestError(404)),
        )
        const { result, rerender } = render({ party: "p1" })
        await waitFor(() => expect(mocks.refresh).toHaveBeenCalledTimes(1))

        // The user deliberately picks another party while the recheck is pending.
        rerender({ party: "p2" })
        await waitFor(() => expect(result.current.state).toEqual({ status: "success", quests: PARTY_QUESTS }))
        await act(async () => refresh.resolve(true))
        expect(result.current.state).toEqual({ status: "success", quests: PARTY_QUESTS })
        expect(mocks.refresh).toHaveBeenCalledTimes(1)
    })

    it.each([403, 500])("does not treat a %i as a stale party", async (status) => {
        mocks.fetchCampaignQuests.mockRejectedValue(new QuestRequestError(status))
        const { result } = render({ party: "p1" })
        await waitFor(() => expect(result.current.state.status).not.toBe("loading"))
        expect(mocks.refresh).not.toHaveBeenCalled()
        expect(mocks.fetchCampaignQuests).toHaveBeenCalledTimes(1)
    })

    it("a 401 signs in again and is never treated as a stale party", async () => {
        mocks.fetchCampaignQuests.mockRejectedValue(new QuestRequestError(401))
        render({ party: "p1" })
        await waitFor(() => expect(mocks.reload).toHaveBeenCalledTimes(1))
        expect(mocks.refresh).not.toHaveBeenCalled()
    })

    it("does not treat a network failure, or a 404 without a party perspective, as a stale party", async () => {
        mocks.fetchCampaignQuests.mockRejectedValueOnce(new TypeError("network"))
        const first = render({ party: "p1" })
        await waitFor(() => expect(first.result.current.state.status).toBe("error"))
        first.unmount()

        mocks.fetchCampaignQuests.mockRejectedValueOnce(new QuestRequestError(404))
        const second = render({ party: null })
        await waitFor(() => expect(second.result.current.state.status).toBe("unavailable"))
        expect(mocks.refresh).not.toHaveBeenCalled()
    })

    it("does not recover a party perspective without a character", async () => {
        mocks.fetchCampaignQuests.mockRejectedValue(new QuestRequestError(404))
        const { result } = renderHook(() => useCampaignQuests("c1", null, "p1"))
        await waitFor(() => expect(result.current.state.status).toBe("unavailable"))
        expect(mocks.refresh).not.toHaveBeenCalled()
    })

    it("a sign-out during the recheck changes nothing here", async () => {
        mocks.refresh.mockResolvedValue(false)
        mocks.fetchCampaignQuests.mockRejectedValue(new QuestRequestError(404))
        const { result } = render({ party: "p1" })
        await waitFor(() => expect(mocks.refresh).toHaveBeenCalledTimes(1))
        await act(async () => undefined)
        expect(result.current.state).toEqual({ status: "loading" })
    })

    it("a different campaign or character is a different scope and a different episode", async () => {
        mocks.fetchCampaignQuests.mockRejectedValue(new QuestRequestError(404))
        const { result, rerender } = renderHook(
            ({ campaign, character }) => useCampaignQuests(campaign, character, "p1"),
            { initialProps: { campaign: "c1", character: "char" } },
        )
        await waitFor(() => expect(result.current.state.status).toBe("unavailable"))
        rerender({ campaign: "c2", character: "char" })
        await waitFor(() => expect(mocks.refresh).toHaveBeenCalledTimes(2))
        rerender({ campaign: "c2", character: "other" })
        await waitFor(() => expect(mocks.refresh).toHaveBeenCalledTimes(3))
    })
})

describe("party-scoped not-found recovery: quest detail", () => {
    it("refreshes once and reads the record again without the party once it is not offered", async () => {
        mocks.fetchQuest.mockImplementation((_c: string, _q: string, _ch: string, party: string | null) =>
            party === null ? Promise.resolve({ quest_id: "q1" }) : Promise.reject(new QuestRequestError(404)),
        )
        const { result, rerender } = renderHook(({ party }) => useQuest("c1", "q1", "char", party), {
            initialProps: { party: "p1" as string | null },
        })
        await waitFor(() => expect(mocks.refresh).toHaveBeenCalledTimes(1))
        rerender({ party: null })
        await waitFor(() => expect(result.current.state.status).toBe("success"))
        expect(mocks.refresh).toHaveBeenCalledTimes(1)
    })

    it("keeps a genuine not-found when the party is still offered (a missing record)", async () => {
        mocks.fetchQuest.mockRejectedValue(new QuestRequestError(404))
        const { result } = renderHook(() => useQuest("c1", "q1", "char", "p1"))
        await waitFor(() => expect(result.current.state).toEqual({ status: "unavailable" }))
        expect(mocks.fetchQuest).toHaveBeenCalledTimes(1)
        expect(mocks.refresh).toHaveBeenCalledTimes(1)
    })
})

describe("party-scoped not-found recovery: Knowledge", () => {
    const items = (party: string | null) =>
        renderHook(
            ({ p }) => useKnowledgeItems("c1", "party_shared", "char", p, "", null, null, true, "active"),
            { initialProps: { p: party } },
        )

    it("drops the party's results at once (no refreshing page), refreshes once, then reads without the party", async () => {
        const page = { items: [{ knowledge_item_id: "k1" }], next_cursor: null }
        const refresh = deferred<boolean>()
        mocks.refresh.mockReturnValue(refresh.promise)
        let phase: "ok" | "revoked" = "ok"
        mocks.fetchKnowledgeItems.mockImplementation((_c: string, request: { partyId: string | null }) =>
            request.partyId === null || phase === "ok"
                ? Promise.resolve(page)
                : Promise.reject(new KnowledgeRequestError(404)),
        )
        const { result, rerender } = items("p1")
        await waitFor(() => expect(result.current.state.status).toBe("success"))

        // The party stops being authorized; the same view is read again and now gets the 404.
        phase = "revoked"
        act(() => result.current.retry())
        await waitFor(() => expect(mocks.refresh).toHaveBeenCalledTimes(1))
        // Not "refreshing": the earlier party-private page is gone while eligibility is rechecked.
        expect(result.current.state).toEqual({ status: "loading" })

        rerender({ p: null })
        await act(async () => refresh.resolve(true))
        await waitFor(() => expect(result.current.state.status).toBe("success"))
        expect(mocks.refresh).toHaveBeenCalledTimes(1)
        expect(mocks.fetchKnowledgeItems.mock.calls.at(-1)![1]).toMatchObject({ partyId: null })
    })

    it("shows a retryable error, not 'unavailable', when the eligibility refresh fails", async () => {
        mocks.refresh.mockRejectedValue(new Error("offline"))
        mocks.fetchKnowledgeItems.mockRejectedValue(new KnowledgeRequestError(404))
        const { result } = items("p1")
        await waitFor(() => expect(result.current.state.status).toBe("error"))
        expect(mocks.fetchKnowledgeItems).toHaveBeenCalledTimes(1)
    })

    it("does not reinterpret a 403 (including a rejected lifecycle) as a stale party", async () => {
        mocks.fetchKnowledgeItems.mockRejectedValue(new KnowledgeRequestError(403))
        const { result } = items("p1")
        await waitFor(() => expect(result.current.state.status).toBe("unavailable"))
        expect(mocks.refresh).not.toHaveBeenCalled()
    })

    it("a view change while the recheck is pending is its own scope and its own episode; the late answer for the old view is ignored", async () => {
        const first = deferred<boolean>()
        mocks.refresh.mockReturnValueOnce(first.promise).mockResolvedValue(true)
        mocks.fetchKnowledgeItems.mockRejectedValue(new KnowledgeRequestError(404))
        const { result, rerender } = renderHook(
            ({ view }) => useKnowledgeItems("c1", view, "char", "p1", "", null, null, true, "active"),
            { initialProps: { view: "party_shared" as "party_shared" | "known" } },
        )
        await waitFor(() => expect(mocks.refresh).toHaveBeenCalledTimes(1))

        rerender({ view: "known" })
        await waitFor(() => expect(result.current.state.status).toBe("unavailable"))
        expect(mocks.refresh).toHaveBeenCalledTimes(2)

        // The old view's refresh finishing late changes nothing about the current view's state.
        await act(async () => first.resolve(true))
        expect(result.current.state.status).toBe("unavailable")
        expect(mocks.refresh).toHaveBeenCalledTimes(2)
    })

    it("detail: marks the rechecked party so the page can drop it, and never refreshes twice", async () => {
        mocks.fetchKnowledgeDetail.mockRejectedValue(new KnowledgeRequestError(404))
        const { result, rerender } = renderHook(() => useKnowledgeDetail("c1", "k1", "char", "p1"))
        await waitFor(() =>
            expect(result.current.state).toEqual({ status: "unavailable", recheckedPartyId: "p1" }),
        )
        rerender()
        expect(mocks.refresh).toHaveBeenCalledTimes(1)
        expect(mocks.fetchKnowledgeDetail).toHaveBeenCalledTimes(1)
    })

    it("detail: a 404 without a party perspective is an ordinary unavailable", async () => {
        mocks.fetchKnowledgeDetail.mockRejectedValue(new KnowledgeRequestError(404))
        const { result } = renderHook(() => useKnowledgeDetail("c1", "k1", "char", null))
        await waitFor(() => expect(result.current.state).toEqual({ status: "unavailable" }))
        expect(mocks.refresh).not.toHaveBeenCalled()
    })
})

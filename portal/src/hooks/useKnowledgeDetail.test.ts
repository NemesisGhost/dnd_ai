import {
    act,
    renderHook,
    waitFor,
} from "@testing-library/react"
import {
    beforeEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import { KnowledgeRequestError } from "../api/knowledge"
import type { KnowledgeDetail } from "../types/knowledge"
import { useKnowledgeDetail } from "./useKnowledgeDetail"

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
    reloadMock.mockResolvedValue(undefined)
})

describe("useKnowledgeDetail", () => {
    it("loads an authorized item with the character and party perspective", async () => {
        fetchKnowledgeDetailMock.mockResolvedValue(itemFixture)

        const { result } = renderHook(() =>
            useKnowledgeDetail(
                "campaign-a",
                "knowledge-a",
                "character-a",
                "party-a",
            ),
        )

        expect(result.current.state).toEqual({ status: "loading" })

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                item: itemFixture,
            })
        })

        expect(fetchKnowledgeDetailMock).toHaveBeenCalledWith(
            "campaign-a",
            "knowledge-a",
            "character-a",
            "party-a",
            expect.any(AbortSignal),
        )
    })

    it("loads with no perspective for a GM canonical view", async () => {
        fetchKnowledgeDetailMock.mockResolvedValue(itemFixture)

        renderHook(() =>
            useKnowledgeDetail("campaign-a", "knowledge-a", null, null),
        )

        await waitFor(() => {
            expect(fetchKnowledgeDetailMock).toHaveBeenCalledWith(
                "campaign-a",
                "knowledge-a",
                null,
                null,
                expect.any(AbortSignal),
            )
        })
    })

    it.each([403, 404])(
        "treats a missing, foreign, or cross-campaign item (HTTP %s) as the same non-disclosing unavailable state",
        async (status) => {
            fetchKnowledgeDetailMock.mockRejectedValue(
                new KnowledgeRequestError(status),
            )

            const { result } = renderHook(() =>
                useKnowledgeDetail(
                    "campaign-a",
                    "knowledge-a",
                    null,
                    null,
                ),
            )

            await waitFor(() => {
                expect(result.current.state).toEqual({
                    status: "unavailable",
                })
            })
        },
    )

    it("reloads the session after an unauthorized response", async () => {
        fetchKnowledgeDetailMock.mockRejectedValue(
            new KnowledgeRequestError(401),
        )

        renderHook(() =>
            useKnowledgeDetail("campaign-a", "knowledge-a", null, null),
        )

        await waitFor(() => {
            expect(reloadMock).toHaveBeenCalledTimes(1)
        })
    })

    it("re-requests when the party perspective changes", async () => {
        fetchKnowledgeDetailMock.mockResolvedValue(itemFixture)

        const { rerender } = renderHook(
            ({ partyId }) =>
                useKnowledgeDetail(
                    "campaign-a",
                    "knowledge-a",
                    "character-a",
                    partyId,
                ),
            { initialProps: { partyId: null as string | null } },
        )

        await waitFor(() => {
            expect(fetchKnowledgeDetailMock).toHaveBeenCalledTimes(1)
        })

        rerender({ partyId: "party-b" })

        await waitFor(() => {
            expect(fetchKnowledgeDetailMock).toHaveBeenLastCalledWith(
                "campaign-a",
                "knowledge-a",
                "character-a",
                "party-b",
                expect.any(AbortSignal),
            )
        })
    })

    it("retries after a recoverable error", async () => {
        const requestError = new Error("The service is unavailable")

        fetchKnowledgeDetailMock
            .mockRejectedValueOnce(requestError)
            .mockResolvedValueOnce(itemFixture)

        const { result } = renderHook(() =>
            useKnowledgeDetail("campaign-a", "knowledge-a", null, null),
        )

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "error",
                error: requestError,
            })
        })

        act(() => {
            result.current.retry()
        })

        await waitFor(() => {
            expect(result.current.state).toEqual({
                status: "success",
                item: itemFixture,
            })
        })
    })

    it("refreshes in place, keeping the current item on screen while it reloads", async () => {
        fetchKnowledgeDetailMock.mockResolvedValueOnce(itemFixture)
        const { result } = renderHook(() =>
            useKnowledgeDetail("campaign-a", "knowledge-a", null, null),
        )
        await waitFor(() => expect(result.current.state.status).toBe("success"))

        let release: (item: KnowledgeDetail) => void = () => {}
        fetchKnowledgeDetailMock.mockReturnValueOnce(
            new Promise<KnowledgeDetail>((resolve) => {
                release = resolve
            }),
        )
        act(() => {
            result.current.refresh()
        })
        expect(fetchKnowledgeDetailMock).toHaveBeenCalledTimes(2)
        expect(result.current.state).toEqual({ status: "success", item: itemFixture })

        const updated = { ...itemFixture, statement: "Changed." }
        await act(async () => {
            release(updated)
        })
        await waitFor(() =>
            expect(result.current.state).toEqual({ status: "success", item: updated }),
        )
    })

    describe("refresh outcomes", () => {
        const loaded = async () => {
            fetchKnowledgeDetailMock.mockResolvedValueOnce(itemFixture)
            const hook = renderHook(() => useKnowledgeDetail("campaign-a", "knowledge-a", null, null))
            await waitFor(() => expect(hook.result.current.state.status).toBe("success"))
            return hook
        }

        it("resolves ok once the new item is applied", async () => {
            const { result } = await loaded()
            const updated = { ...itemFixture, statement: "Changed." }
            fetchKnowledgeDetailMock.mockResolvedValueOnce(updated)
            let outcome: string | undefined
            await act(async () => {
                outcome = await result.current.refresh()
            })
            expect(outcome).toBe("ok")
            expect(result.current.state).toEqual({ status: "success", item: updated })
        })

        it("resolves failed and keeps the item shown when the read fails recoverably", async () => {
            const { result } = await loaded()
            fetchKnowledgeDetailMock.mockRejectedValueOnce(new KnowledgeRequestError(500))
            let outcome: string | undefined
            await act(async () => {
                outcome = await result.current.refresh()
            })
            expect(outcome).toBe("failed")
            expect(result.current.state).toEqual({ status: "success", item: itemFixture })
        })

        it("fails closed when the read says the item is no longer available", async () => {
            const { result } = await loaded()
            fetchKnowledgeDetailMock.mockRejectedValueOnce(new KnowledgeRequestError(403))
            let outcome: string | undefined
            await act(async () => {
                outcome = await result.current.refresh()
            })
            expect(outcome).toBe("failed")
            expect(result.current.state).toEqual({ status: "unavailable" })
        })

        it("resolves superseded when a newer refresh replaces it, and applies only the newer", async () => {
            const { result } = await loaded()
            let releaseFirst: (item: KnowledgeDetail) => void = () => {}
            fetchKnowledgeDetailMock.mockImplementationOnce(
                (_c: string, _k: string, _ch: string | null, _p: string | null, signal: AbortSignal) =>
                    new Promise<KnowledgeDetail>((resolve, reject) => {
                        releaseFirst = resolve
                        signal.addEventListener("abort", () => reject(new DOMException("x", "AbortError")))
                    }),
            )
            const newer = { ...itemFixture, statement: "Newer." }
            fetchKnowledgeDetailMock.mockResolvedValueOnce(newer)
            let first: Promise<string> | undefined
            let second: string | undefined
            await act(async () => {
                first = result.current.refresh()
                second = await result.current.refresh()
            })
            releaseFirst({ ...itemFixture, statement: "Older." })
            expect(await first).toBe("superseded")
            expect(second).toBe("ok")
            expect(result.current.state).toEqual({ status: "success", item: newer })
        })
    })

    it("aborts the request when the hook unmounts", () => {
        fetchKnowledgeDetailMock.mockReturnValue(
            new Promise<KnowledgeDetail>(() => {}),
        )

        const { unmount } = renderHook(() =>
            useKnowledgeDetail("campaign-a", "knowledge-a", null, null),
        )

        const signal = fetchKnowledgeDetailMock.mock.calls[0]?.[4] as AbortSignal

        expect(signal.aborted).toBe(false)

        unmount()

        expect(signal.aborted).toBe(true)
    })
})

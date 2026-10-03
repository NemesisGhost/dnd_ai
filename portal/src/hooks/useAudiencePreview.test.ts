import { act, renderHook, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { AudiencePreviewRequestError } from "../api/audiencePreview"
import type { AudiencePreviewResult } from "../types/audiencePreview"
import { useAudiencePreview } from "./useAudiencePreview"

const { fetchAudiencePreviewMock, reloadMock } = vi.hoisted(() => ({
    fetchAudiencePreviewMock: vi.fn(),
    reloadMock: vi.fn(),
}))

vi.mock("../api/audiencePreview", async (importOriginal) => {
    const actual = await importOriginal<typeof import("../api/audiencePreview")>()
    return {
        ...actual,
        fetchAudiencePreview: fetchAudiencePreviewMock,
    }
})

vi.mock("../context/SessionContext", () => ({
    useSession: () => ({ reload: reloadMock }),
}))

const questResult: AudiencePreviewResult = {
    resourceType: "quest",
    quest: { quest_id: "quest-1", name: "Find the Amulet", status_code: "active", stages: [] },
}

const knowledgeResult: AudiencePreviewResult = {
    resourceType: "knowledge_item",
    knowledgeItem: {
        knowledge_item_id: "item-1",
        knowledge_type_code: "fact",
        statement: "A hidden truth.",
        truth_status_code: "true",
        sensitivity: null,
        awareness_level: "aware",
        confidence: 90,
        willing_to_share: null,
    },
}

beforeEach(() => {
    fetchAudiencePreviewMock.mockReset()
    reloadMock.mockReset()
    reloadMock.mockResolvedValue(undefined)
})

describe("useAudiencePreview", () => {
    it("loads the preview for the given member and resource", async () => {
        fetchAudiencePreviewMock.mockResolvedValue(questResult)

        const { result } = renderHook(() =>
            useAudiencePreview("campaign-a", "membership-a", "quest", "quest-1"),
        )

        expect(result.current.state).toEqual({ status: "loading" })

        await waitFor(() => {
            expect(result.current.state).toEqual({ status: "success", result: questResult })
        })

        expect(fetchAudiencePreviewMock).toHaveBeenCalledWith(
            "campaign-a",
            "membership-a",
            "quest",
            "quest-1",
            expect.any(AbortSignal),
        )
    })

    it.each([403, 404])("treats HTTP %s as unavailable", async (status) => {
        fetchAudiencePreviewMock.mockRejectedValue(new AudiencePreviewRequestError(status))

        const { result } = renderHook(() =>
            useAudiencePreview("campaign-a", "membership-a", "quest", "quest-1"),
        )

        await waitFor(() => {
            expect(result.current.state).toEqual({ status: "unavailable" })
        })
    })

    it("reloads the browser session after an unauthorized response", async () => {
        fetchAudiencePreviewMock.mockRejectedValue(new AudiencePreviewRequestError(401))

        renderHook(() => useAudiencePreview("campaign-a", "membership-a", "quest", "quest-1"))

        await waitFor(() => {
            expect(reloadMock).toHaveBeenCalledTimes(1)
        })
    })

    it("clears the previous result and aborts its request when the resource changes", async () => {
        let resolveSecondRequest: ((result: AudiencePreviewResult) => void) | undefined

        const secondRequest = new Promise<AudiencePreviewResult>((resolve) => {
            resolveSecondRequest = resolve
        })

        fetchAudiencePreviewMock
            .mockResolvedValueOnce(questResult)
            .mockReturnValueOnce(secondRequest)

        const { result, rerender } = renderHook(
            ({ resourceId }: { resourceId: string }) =>
                useAudiencePreview("campaign-a", "membership-a", "quest", resourceId),
            { initialProps: { resourceId: "quest-1" } },
        )

        await waitFor(() => {
            expect(result.current.state).toEqual({ status: "success", result: questResult })
        })

        const firstSignal = fetchAudiencePreviewMock.mock.calls[0]?.[4] as AbortSignal

        rerender({ resourceId: "quest-2" })

        expect(firstSignal.aborted).toBe(true)
        expect(result.current.state).toEqual({ status: "loading" })

        act(() => {
            resolveSecondRequest?.(knowledgeResult)
        })

        await waitFor(() => {
            expect(result.current.state).toEqual({ status: "success", result: knowledgeResult })
        })
    })

    it("aborts the request when the hook unmounts", () => {
        fetchAudiencePreviewMock.mockReturnValue(new Promise<AudiencePreviewResult>(() => {}))

        const { unmount } = renderHook(() =>
            useAudiencePreview("campaign-a", "membership-a", "quest", "quest-1"),
        )

        const signal = fetchAudiencePreviewMock.mock.calls[0]?.[4] as AbortSignal

        expect(signal.aborted).toBe(false)

        unmount()

        expect(signal.aborted).toBe(true)
    })
})

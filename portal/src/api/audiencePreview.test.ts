import { afterEach, describe, expect, it, vi } from "vitest"
import { AudiencePreviewRequestError, fetchAudiencePreview } from "./audiencePreview"

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("fetchAudiencePreview", () => {
    it("requests the quest preview route and wraps the result as a quest", async () => {
        const controller = new AbortController()
        const questBody = { quest_id: "quest-1", name: "Find the Amulet", status_code: "active", stages: [] }

        const fetchMock = vi.fn().mockResolvedValue(
            new Response(JSON.stringify(questBody), {
                status: 200,
                headers: { "Content-Type": "application/json" },
            }),
        )
        vi.stubGlobal("fetch", fetchMock)

        await expect(
            fetchAudiencePreview("campaign/a", "membership/b", "quest", "quest-1", controller.signal),
        ).resolves.toEqual({ resourceType: "quest", quest: questBody })

        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaigns/campaign%2Fa/members/membership%2Fb/preview/quests/quest-1",
            {
                method: "GET",
                headers: { Accept: "application/json" },
                cache: "no-store",
                signal: controller.signal,
            },
        )
    })

    it("requests the knowledge preview route and wraps the result as a knowledge item", async () => {
        const knowledgeBody = {
            knowledge_item_id: "item-1",
            knowledge_type_code: "fact",
            statement: "The idol grants wishes.",
            truth_status_code: "false",
            sensitivity: null,
            awareness_level: "aware",
            confidence: 60,
            willing_to_share: null,
        }

        const fetchMock = vi.fn().mockResolvedValue(
            new Response(JSON.stringify(knowledgeBody), {
                status: 200,
                headers: { "Content-Type": "application/json" },
            }),
        )
        vi.stubGlobal("fetch", fetchMock)

        await expect(
            fetchAudiencePreview("campaign-a", "membership-a", "knowledge_item", "item-1"),
        ).resolves.toEqual({ resourceType: "knowledge_item", knowledgeItem: knowledgeBody })

        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaigns/campaign-a/members/membership-a/preview/knowledge/item-1",
            {
                method: "GET",
                headers: { Accept: "application/json" },
                cache: "no-store",
                signal: undefined,
            },
        )
    })

    it("throws a typed error carrying the response status for a failed request", async () => {
        const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 404 }))
        vi.stubGlobal("fetch", fetchMock)

        await expect(
            fetchAudiencePreview("campaign-a", "membership-a", "quest", "quest-1"),
        ).rejects.toSatisfy(
            (error: unknown) => error instanceof AudiencePreviewRequestError && error.status === 404,
        )
    })
})

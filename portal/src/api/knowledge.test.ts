import {
    afterEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import type { KnowledgeDetail, KnowledgePage } from "../types/knowledge"
import {
    fetchKnowledgeDetail,
    fetchKnowledgeItems,
    KnowledgeRequestError,
} from "./knowledge"

const knowledgePageFixture = {
    items: [
        {
            knowledge_item_id: "knowledge-a",
            knowledge_type_code: "fact",
            statement:
                "The Glass Ossuary lies beneath the Rootspire.",
            truth_status_code: null,
            sensitivity: null,
            awareness_level: "known",
            confidence: 95,
            willing_to_share: true,
            scope: "party",
            discovery_world_time_id: "world-time-a",
            source_event_id: "event-a",
            source_interaction_id: null,
            subject_entity_id: "location-a",
        },
        {
            knowledge_item_id: "knowledge-b",
            knowledge_type_code: "rumor",
            statement:
                "The Drowned Shard may open the western vault.",
            truth_status_code: null,
            sensitivity: null,
            awareness_level: "rumor",
            confidence: 40,
            willing_to_share: null,
            scope: "party",
            discovery_world_time_id: null,
            source_event_id: null,
            source_interaction_id: null,
            subject_entity_id: null,
        },
    ],
    next_cursor: "next-knowledge-page",
} satisfies KnowledgePage

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("fetchKnowledgeItems", () => {
    it("returns an authorized page and safely encodes every parameter", async () => {
        const controller = new AbortController()

        const fetchMock = vi.fn().mockResolvedValue(
            new Response(
                JSON.stringify(knowledgePageFixture),
                {
                    status: 200,
                    headers: {
                        "Content-Type": "application/json",
                    },
                },
            ),
        )

        vi.stubGlobal("fetch", fetchMock)

        await expect(
            fetchKnowledgeItems(
                "campaign/a b",
                {
                    view: "party_shared",
                    characterId: "character/a b",
                    partyId: "party/a b",
                    query: "glass forge",
                    knowledgeType: "ancient rumor",
                    cursor: "opaque+/=",
                    limit: 50,
                },
                controller.signal,
            ),
        ).resolves.toEqual(knowledgePageFixture)

        expect(fetchMock).toHaveBeenCalledTimes(1)

        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaigns/campaign%2Fa%20b/knowledge?view=party_shared&character_id=character%2Fa+b&party_id=party%2Fa+b&q=glass+forge&type=ancient+rumor&cursor=opaque%2B%2F%3D&limit=50",
            {
                method: "GET",
                headers: {
                    Accept: "application/json",
                },
                cache: "no-store",
                signal: controller.signal,
            },
        )
    })

    it("omits empty optional parameters while preserving the required view", async () => {
        const emptyPage = {
            items: [],
            next_cursor: null,
        } satisfies KnowledgePage

        const fetchMock = vi.fn().mockResolvedValue(
            new Response(JSON.stringify(emptyPage), {
                status: 200,
                headers: {
                    "Content-Type": "application/json",
                },
            }),
        )

        vi.stubGlobal("fetch", fetchMock)

        await expect(
            fetchKnowledgeItems("campaign-a", {
                view: "known",
                characterId: null,
                partyId: null,
                query: "",
                knowledgeType: null,
            }),
        ).resolves.toEqual(emptyPage)

        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaigns/campaign-a/knowledge?view=known",
            {
                method: "GET",
                headers: {
                    Accept: "application/json",
                },
                cache: "no-store",
                signal: undefined,
            },
        )
    })

    it("passes an opaque cursor without interpreting it", async () => {
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(
                JSON.stringify({
                    items: [],
                    next_cursor: null,
                }),
                {
                    status: 200,
                    headers: {
                        "Content-Type": "application/json",
                    },
                },
            ),
        )

        vi.stubGlobal("fetch", fetchMock)

        await fetchKnowledgeItems("campaign-a", {
            view: "recent",
            characterId: "character-a",
            partyId: null,
            query: "",
            knowledgeType: null,
            cursor: "eyJvcGFxdWUiOiJjdXJzb3IifQ",
        })

        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaigns/campaign-a/knowledge?view=recent&character_id=character-a&cursor=eyJvcGFxdWUiOiJjdXJzb3IifQ",
            expect.objectContaining({
                method: "GET",
                cache: "no-store",
            }),
        )
    })

    it("throws a typed error for an unsuccessful response", async () => {
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(null, {
                status: 403,
            }),
        )

        vi.stubGlobal("fetch", fetchMock)

        const request = fetchKnowledgeItems(
            "campaign-a",
            {
                view: "character_private",
                characterId: "character-a",
                partyId: null,
                query: "",
                knowledgeType: null,
            },
        )

        await expect(request).rejects.toMatchObject({
            name: "KnowledgeRequestError",
            status: 403,
            message:
                "Knowledge request failed with status 403",
        })

        await expect(request).rejects.toBeInstanceOf(
            KnowledgeRequestError,
        )
    })
})

describe("fetchKnowledgeDetail", () => {
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

    afterEach(() => {
        vi.unstubAllGlobals()
    })

    it("requests the detail route with no perspective parameters when none are given", async () => {
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(JSON.stringify(itemFixture), {
                status: 200,
                headers: { "Content-Type": "application/json" },
            }),
        )

        vi.stubGlobal("fetch", fetchMock)

        await expect(
            fetchKnowledgeDetail("campaign-a", "knowledge-a", null, null),
        ).resolves.toEqual(itemFixture)

        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaigns/campaign-a/knowledge/knowledge-a",
            {
                method: "GET",
                headers: { Accept: "application/json" },
                cache: "no-store",
                signal: undefined,
            },
        )
    })

    it("encodes the character and party perspective as query parameters", async () => {
        const fetchMock = vi.fn().mockResolvedValue(
            new Response(JSON.stringify(itemFixture), {
                status: 200,
                headers: { "Content-Type": "application/json" },
            }),
        )

        vi.stubGlobal("fetch", fetchMock)

        await fetchKnowledgeDetail(
            "campaign/a b",
            "knowledge:c d",
            "character-a",
            "party-a",
        )

        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaigns/campaign%2Fa%20b/knowledge/knowledge%3Ac%20d" +
                "?character_id=character-a&party_id=party-a",
            expect.objectContaining({ method: "GET" }),
        )
    })

    it("throws a typed error for an unsuccessful response, matching missing and unauthorized alike", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(new Response(null, { status: 404 })),
        )

        await expect(
            fetchKnowledgeDetail("campaign-a", "missing-item", null, null),
        ).rejects.toBeInstanceOf(KnowledgeRequestError)
    })
})
import {
    afterEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import type {
    WorldEntityPage,
} from "../types/world"
import {
    fetchWorldEntities,
    WorldRequestError,
} from "./world"

const worldPageFixture = {
    items: [
        {
            entity_id: "location-a",
            category: "location",
            entity_type_code: "dungeon",
            name: "The Glass Ossuary",
            summary:
                "An ancient facility beneath the Rootspire.",
        },
        {
            entity_id: "character-a",
            category: "character",
            entity_type_code: "npc",
            name: "Ixamarra",
            summary: "The Seer-Archivist.",
        },
    ],
    next_cursor: "next-page-cursor",
} satisfies WorldEntityPage

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("fetchWorldEntities", () => {
    it("returns an authorized page and safely encodes every parameter", async () => {
        const controller = new AbortController()

        const fetchMock = vi.fn().mockResolvedValue(
            new Response(
                JSON.stringify(worldPageFixture),
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
            fetchWorldEntities(
                "campaign/a b",
                {
                    category: "location",
                    query: "glass forge",
                    cursor: "opaque+/=",
                    limit: 50,
                },
                controller.signal,
            ),
        ).resolves.toEqual(worldPageFixture)

        expect(fetchMock).toHaveBeenCalledTimes(1)

        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaigns/campaign%2Fa%20b/world/search?category=location&q=glass+forge&cursor=opaque%2B%2F%3D&limit=50",
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

    it("omits empty optional parameters", async () => {
        const emptyPage = {
            items: [],
            next_cursor: null,
        } satisfies WorldEntityPage

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
            fetchWorldEntities("campaign-a", {
                category: null,
                query: "",
            }),
        ).resolves.toEqual(emptyPage)

        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaigns/campaign-a/world/search",
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

    it("does not alter an opaque cursor", async () => {
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

        await fetchWorldEntities("campaign-a", {
            category: "event",
            query: "",
            cursor: "eyJvcGFxdWUiOiJjdXJzb3IifQ",
        })

        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaigns/campaign-a/world/search?category=event&cursor=eyJvcGFxdWUiOiJjdXJzb3IifQ",
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

        await expect(
            fetchWorldEntities("campaign-a", {
                category: null,
                query: "",
            }),
        ).rejects.toMatchObject({
            name: "WorldRequestError",
            status: 403,
            message:
                "World request failed with status 403",
        })

        await expect(
            fetchWorldEntities("campaign-a", {
                category: null,
                query: "",
            }),
        ).rejects.toBeInstanceOf(WorldRequestError)
    })
})
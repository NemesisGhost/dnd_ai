import {
    afterEach,
    describe,
    expect,
    it,
    vi,
} from "vitest"
import type {
    EventDetail,
    ItemDetail,
    LocationDetail,
    ReligionDetail,
    WorldEntityPage,
} from "../types/world"
import {
    fetchEventDetail,
    fetchItemDetail,
    fetchLocationDetail,
    fetchReligionDetail,
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

describe("fetchLocationDetail", () => {
    it("requests the campaign-scoped location detail route with encoded ids", async () => {
        const locationFixture: LocationDetail = {
            location_id: "location-a",
            name: "The Sunken Archive",
            summary: null,
            location_type_code: "building",
            parent_location_id: null,
            breadcrumbs: [],
            population: null,
            building_use: null,
            danger_level: null,
            is_searched: null,
            is_destroyed: null,
            alarm_level: null,
            condition_notes: null,
        }

        const fetchMock = vi.fn().mockResolvedValue(
            new Response(JSON.stringify(locationFixture), {
                status: 200,
                headers: { "Content-Type": "application/json" },
            }),
        )

        vi.stubGlobal("fetch", fetchMock)

        await expect(
            fetchLocationDetail("campaign/a b", "location:c d"),
        ).resolves.toEqual(locationFixture)

        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaigns/campaign%2Fa%20b/world/locations/location%3Ac%20d",
            {
                method: "GET",
                headers: { Accept: "application/json" },
                cache: "no-store",
                signal: undefined,
            },
        )
    })

    it("throws a typed error for an unsuccessful response", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(new Response(null, { status: 404 })),
        )

        await expect(
            fetchLocationDetail("campaign-a", "location-a"),
        ).rejects.toBeInstanceOf(WorldRequestError)
    })
})

describe("fetchReligionDetail", () => {
    it("requests the campaign-scoped religion detail route", async () => {
        const religionFixture: ReligionDetail = {
            religion_id: "religion-a",
            name: "The Tidefather Communion",
            summary: null,
            pantheon_structure: null,
            serving_organization_ids: [],
        }

        const fetchMock = vi.fn().mockResolvedValue(
            new Response(JSON.stringify(religionFixture), {
                status: 200,
                headers: { "Content-Type": "application/json" },
            }),
        )

        vi.stubGlobal("fetch", fetchMock)

        await expect(
            fetchReligionDetail("campaign-a", "religion-a"),
        ).resolves.toEqual(religionFixture)

        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaigns/campaign-a/world/religions/religion-a",
            expect.objectContaining({ method: "GET" }),
        )
    })
})

describe("fetchItemDetail", () => {
    it("requests the campaign-scoped item detail route", async () => {
        const itemFixture: ItemDetail = {
            item_instance_id: "item-a",
            name: "The Warden's Lantern",
            summary: null,
            item_definition_id: null,
            origin_notes: null,
            quantity: 1,
            condition_percentage: null,
            charges_current: null,
            charges_maximum: null,
            is_equipped: null,
            is_destroyed: null,
        }

        const fetchMock = vi.fn().mockResolvedValue(
            new Response(JSON.stringify(itemFixture), {
                status: 200,
                headers: { "Content-Type": "application/json" },
            }),
        )

        vi.stubGlobal("fetch", fetchMock)

        await expect(
            fetchItemDetail("campaign-a", "item-a"),
        ).resolves.toEqual(itemFixture)

        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaigns/campaign-a/world/items/item-a",
            expect.objectContaining({ method: "GET" }),
        )
    })
})

describe("fetchEventDetail", () => {
    it("requests the campaign-scoped event detail route", async () => {
        const eventFixture: EventDetail = {
            event_id: "event-a",
            name: "The Sundering of the Vale",
            summary: null,
            event_type_code: "historical_event",
            event_status_code: "recorded",
            world_time_id: "world-time-a",
            details: null,
            session_id: null,
            participants: [],
            locations: [],
        }

        const fetchMock = vi.fn().mockResolvedValue(
            new Response(JSON.stringify(eventFixture), {
                status: 200,
                headers: { "Content-Type": "application/json" },
            }),
        )

        vi.stubGlobal("fetch", fetchMock)

        await expect(
            fetchEventDetail("campaign-a", "event-a"),
        ).resolves.toEqual(eventFixture)

        expect(fetchMock).toHaveBeenCalledWith(
            "/api/campaigns/campaign-a/world/events/event-a",
            expect.objectContaining({ method: "GET" }),
        )
    })

    it("forwards the provided abort signal and never sends a CSRF header", async () => {
        const controller = new AbortController()

        const fetchMock = vi.fn().mockResolvedValue(
            new Response(null, { status: 404 }),
        )

        vi.stubGlobal("fetch", fetchMock)

        await expect(
            fetchEventDetail("campaign-a", "event-a", controller.signal),
        ).rejects.toBeInstanceOf(WorldRequestError)

        const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
        expect(init.signal).toBe(controller.signal)
        expect(
            Object.keys(init.headers as Record<string, string>),
        ).not.toContain("X-CSRF-Token")
    })
})
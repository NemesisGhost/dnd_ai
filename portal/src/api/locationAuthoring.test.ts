import { afterEach, describe, expect, it, vi } from "vitest"
import {
    createLocation,
    fetchLocationParentOptions,
    locationAuthoringPath,
    locationOptionsPath,
    locationParentOptionsPath,
    updateLocation,
} from "./locationAuthoring"
import { ApiRequestError } from "./http"

const ctx = { csrfToken: "csrf-1", idempotencyKey: "key-1" }

function stubFetch(status: number, body: unknown) {
    const stub = vi.fn(
        async () =>
            new Response(body === undefined ? null : JSON.stringify(body), {
                status,
                headers: { "Content-Type": "application/json" },
            }),
    )
    vi.stubGlobal("fetch", stub)
    return stub
}

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("location authoring paths", () => {
    it("scopes every path to the campaign and encodes ids", () => {
        expect(locationOptionsPath("c 1")).toBe("/campaigns/c%201/authoring/locations/options")
        expect(locationAuthoringPath("c1", "l/1")).toBe("/campaigns/c1/authoring/locations/l%2F1")
        expect(locationParentOptionsPath("c1", "  ash  ", "l1")).toBe(
            "/campaigns/c1/authoring/locations/parent-options?limit=25&q=ash&for=l1",
        )
        expect(locationParentOptionsPath("c1", "", null)).toBe(
            "/campaigns/c1/authoring/locations/parent-options?limit=25",
        )
    })
})

describe("location authoring requests", () => {
    const fields = {
        name: "Hollow",
        summary: null,
        parent_location_id: null,
        population: null,
        building_use: null,
    }

    it("creates with POST, the CSRF token, and the idempotency key, sending only the typed body", async () => {
        const stub = stubFetch(201, { location_id: "l1" })
        await createLocation("c1", { category: "region", ...fields }, ctx)

        const [url, init] = stub.mock.calls[0] as unknown as [string, RequestInit]
        expect(url).toBe("/api/campaigns/c1/authoring/locations")
        expect(init.method).toBe("POST")
        expect(init.credentials).toBe("same-origin")
        expect(init.cache).toBe("no-store")
        expect(init.headers).toMatchObject({
            "X-CSRF-Token": "csrf-1",
            "Idempotency-Key": "key-1",
        })
        expect(JSON.parse(String(init.body))).toEqual({ category: "region", ...fields })
    })

    it("updates the named location with the expected row version", async () => {
        const stub = stubFetch(200, { location_id: "l1" })
        await updateLocation("c1", "l1", { expected_row_version: 4, ...fields }, ctx)

        const [url, init] = stub.mock.calls[0] as unknown as [string, RequestInit]
        expect(url).toBe("/api/campaigns/c1/authoring/locations/l1/update")
        expect(JSON.parse(String(init.body))).toMatchObject({ expected_row_version: 4 })
    })

    it("searches parent options with a GET and no mutation headers", async () => {
        const stub = stubFetch(200, { items: [], next_cursor: null })
        const controller = new AbortController()
        await fetchLocationParentOptions("c1", "ash", "l1", controller.signal)

        const [url, init] = stub.mock.calls[0] as unknown as [string, RequestInit]
        expect(url).toBe("/api/campaigns/c1/authoring/locations/parent-options?limit=25&q=ash&for=l1")
        expect(init.method).toBe("GET")
        expect(init.signal).toBe(controller.signal)
        expect(init.headers).not.toHaveProperty("X-CSRF-Token")
    })

    it("surfaces the server's stable error code", async () => {
        stubFetch(409, { error: { code: "location_hierarchy_cycle", correlation_id: "c" } })
        await expect(
            updateLocation("c1", "l1", { expected_row_version: 1, ...fields }, ctx),
        ).rejects.toMatchObject({ status: 409, code: "location_hierarchy_cycle" })
        await expect(
            updateLocation("c1", "l1", { expected_row_version: 1, ...fields }, ctx),
        ).rejects.toBeInstanceOf(ApiRequestError)
    })
})

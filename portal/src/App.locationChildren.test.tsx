import { fireEvent, screen, within } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { useSessionBootstrap } from "./hooks/useSessionBootstrap"
import { installCampaignShellMocks, openApp } from "./test/campaignRoutes"
import type { MockServer } from "./test/authoringHarness"

// P15-C08-S02: the Location path links, "Places within" and the way back, through the whole App over a
// memory data router (jsdom): they prove destinations, carried state and requests, not real-browser
// behavior.

vi.mock("./hooks/useSessionBootstrap", () => ({ useSessionBootstrap: vi.fn() }))
vi.mock("./api/userPreferences", () => ({
    recordLastVisitedCampaign: vi.fn(() => Promise.resolve()),
}))

const base = "/app/mundivita"
const API = "/campaigns/mundivita"
const READER = ["access.manage"]

const crumb = (id: string, name: string, type: string) => ({ location_id: id, name, location_type_code: type })
const place = (id: string, name: string, type: string, breadcrumbs: object[] = []) => ({
    location_id: id,
    name,
    summary: null,
    location_type_code: type,
    parent_location_id: null,
    breadcrumbs,
    population: null,
    building_use: null,
    danger_level: null,
    is_searched: null,
    is_destroyed: null,
    alarm_level: null,
    condition_notes: null,
})
const child = (id: string, name: string, type: string, path: object[] = []) => ({
    location_id: id,
    name,
    location_type_code: type,
    summary: null,
    canon_status: "canon",
    lifecycle_status: "active",
    path,
})
const card = (id: string, name: string) => ({
    entity_id: id,
    category: "location",
    entity_type_code: "region",
    name,
    summary: null,
})

const kids = (id: string, query = "") => `${API}/world/locations/${id}/children?limit=25${query}`
const childReads = (server: MockServer) => server.calls.filter((c) => c.path.includes("/children")).map((c) => c.path)
const breadcrumb = () => within(screen.getByRole("navigation", { name: "Breadcrumb" }))
const trail = () => breadcrumb().getAllByRole("listitem").map((item) => item.textContent)

const ASHEN = place("r1", "Ashen Vale", "region")
const HOLLOW = place("h1", "Hollowmere", "settlement", [crumb("r1", "Ashen Vale", "region")])
const MILL = place("m1", "Old Mill", "building", [crumb("r1", "Ashen Vale", "region"), crumb("h1", "Hollowmere", "settlement")])

let server: MockServer

beforeEach(() => {
    server = installCampaignShellMocks()
    server.on("GET", /^\/campaigns\/mundivita\/world\/search/, {
        body: { items: [card("r1", "Ashen Vale")], next_cursor: null },
    })
    for (const p of [ASHEN, HOLLOW, MILL]) {
        server.on("GET", `${API}/world/locations/${p.location_id}`, { body: p })
    }
    server.on("GET", kids("r1"), { body: { items: [child("h1", "Hollowmere", "settlement")], next_cursor: null } })
    server.on("GET", kids("h1"), { body: { items: [child("m1", "Old Mill", "building")], next_cursor: null } })
    server.on("GET", kids("m1"), { body: { items: [], next_cursor: null } })
})

afterEach(() => {
    vi.unstubAllGlobals()
    vi.mocked(useSessionBootstrap).mockReset()
})

describe("Location path and places within", () => {
    it("N7: Back from an opened child returns to the parent with the search applied and the first page read again", async () => {
        server.on("GET", kids("r1", "&q=hollow"), {
            body: { items: [child("h1", "Hollowmere", "settlement")], next_cursor: null },
        })
        const app = openApp(`${base}/world/location/r1`, READER)
        await screen.findByRole("heading", { level: 2, name: "Places within Ashen Vale" })
        fireEvent.change(await screen.findByRole("searchbox", { name: "Search places within Ashen Vale" }), { target: { value: "hollow" } })
        fireEvent.click(screen.getByRole("button", { name: "Search" }))
        fireEvent.click(await screen.findByRole("link", { name: "Hollowmere" }))
        await screen.findByRole("heading", { level: 1, name: "Hollowmere" })
        expect(app.router.state.location.pathname).toBe(`${base}/world/location/h1`)
        await app.router.navigate(-1)
        await screen.findByRole("heading", { level: 1, name: "Ashen Vale" })
        expect(new URLSearchParams(app.router.state.location.search).get("within")).toBe("hollow")
        expect(await screen.findByRole("searchbox", { name: "Search places within Ashen Vale" })).toHaveValue("hollow")
        await screen.findByRole("link", { name: "Hollowmere" })
        expect(childReads(server).filter((p) => p === kids("r1", "&q=hollow")).length).toBeGreaterThanOrEqual(2)
    })

    it("N16: the Location path links to each visible ancestor with the page's task, a hidden ancestor never appears, and the task breadcrumb is unchanged", async () => {
        server.on("GET", `${API}/world/locations/m1`, { body: place("m1", "Old Mill", "building", [crumb("h1", "Hollowmere", "settlement")]) })
        server.on("GET", /^\/campaigns\/mundivita\/world\/search/, {
            body: { items: [card("m1", "Old Mill")], next_cursor: null },
        })
        const app = openApp(`${base}/world?category=location&q=mill`, READER)
        fireEvent.click(await screen.findByRole("link", { name: /Old Mill/ }))
        await screen.findByRole("heading", { level: 1, name: "Old Mill" })
        const path = await screen.findByRole("list", { name: "Location path" })
        expect(within(path).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["Hollowmere (Settlement)"])
        expect(within(path).getByRole("link", { name: "Hollowmere (Settlement)" })).toHaveAttribute("href", `${base}/world/location/h1`)
        expect(document.body.textContent).not.toContain("Ashen Vale")
        expect(trail()).toEqual(["World", "Old Mill"])
        fireEvent.click(within(path).getByRole("link", { name: "Hollowmere (Settlement)" }))
        await screen.findByRole("heading", { level: 1, name: "Hollowmere" })
        expect(app.router.state.location.pathname).toBe(`${base}/world/location/h1`)
        expect((app.router.state.location.state as { task?: { root: string } } | null)?.task?.root).toBe("world")
        expect(screen.getByRole("link", { name: "World" })).toBeVisible()
    })

    it("N19: a walk from World search to a region, a child, a grandchild and back up the Location path sends only each page's reads", async () => {
        const app = openApp(`${base}/world?category=location&q=ashen`, READER)
        fireEvent.click(await screen.findByRole("link", { name: /Ashen Vale/ }))
        await screen.findByRole("heading", { level: 1, name: "Ashen Vale" })
        fireEvent.click(await screen.findByRole("link", { name: "Hollowmere" }))
        await screen.findByRole("heading", { level: 1, name: "Hollowmere" })
        fireEvent.click(await screen.findByRole("link", { name: "Old Mill" }))
        await screen.findByRole("heading", { level: 1, name: "Old Mill" })
        const path = await screen.findByRole("list", { name: "Location path" })
        expect(within(path).getAllByRole("link").map((l) => l.textContent)).toEqual(["Ashen Vale (Region)", "Hollowmere (Settlement)"])
        fireEvent.click(within(path).getByRole("link", { name: "Ashen Vale (Region)" }))
        await screen.findByRole("heading", { level: 1, name: "Ashen Vale" })
        await screen.findByRole("heading", { level: 2, name: "Places within Ashen Vale" })
        expect(app.router.state.location.pathname).toBe(`${base}/world/location/r1`)
        expect(childReads(server)).toEqual([kids("r1"), kids("h1"), kids("m1"), kids("r1")])
        // The World browser's own reads come first; from the first record's read on, only the pages' reads.
        const all = server.calls.map((c) => c.path.split("?")[0]!)
        const paths = all.slice(all.indexOf(`${API}/world/locations/r1`))
        expect(paths.filter((p) => /\/authoring\/|\/lifecycle|\/counts/.test(p))).toEqual([])
        expect(paths.filter((p) => p.includes("/world/search"))).toEqual([])
        expect(server.calls.filter((c) => c.method !== "GET")).toEqual([])
    })
})

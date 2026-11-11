import { fireEvent, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { EditLocationPage } from "../../pages/EditLocationPage"
import { installMockServer, renderAuthoringRoutes } from "../../test/authoringHarness"
import { worldEditNavigation } from "./editNavigation"

const navigate = worldEditNavigation("location")
const ctx = (state: unknown) => ({ campaignId: "c1", entityId: "l1", pathname: "/app/c1/world/location/l1/edit", state })

// The task a link out of a list carries (the entry's own, as the producers write it).
const taskOf = (root: string, list: { route: string; search: string }, trail: object[] = []) => ({
    v: 1,
    root,
    scope: { campaignId: "c1" },
    trail,
    list,
})

describe("worldEditNavigation", () => {
    it("returns to the World page of the record when it was opened some other way", () => {
        expect(navigate(ctx(null))).toEqual({
            listPath: "/app/c1/world",
            detail: { to: "/app/c1/world/location/l1", state: undefined },
        })
    })

    it("returns to the workspace section the person left, and carries where they started", () => {
        expect(
            navigate(
                ctx({
                    returnTo: { pathname: "/app/c1/world/location/l1", search: "?section=details" },
                    task: taskOf("world", { route: "campaign.world", search: "?category=location" }),
                }),
            ),
        ).toEqual({
            listPath: "/app/c1/world?category=location",
            detail: {
                to: "/app/c1/world/location/l1?section=details",
                state: { task: taskOf("world", { route: "campaign.world", search: "?category=location" }) },
            },
        })
    })

    it("hands a Review-queue origin back to the record although this route accepts no Review task", () => {
        const review = taskOf("review", { route: "review.queue", search: "?status=draft" })
        const result = navigate(ctx({ task: review }))
        expect(result.listPath).toBe("/app/c1/world")
        expect(result.detail.state).toEqual({ task: review })
    })

    it("drops a task that names another campaign, and a transition hint", () => {
        const foreign = { ...taskOf("world", { route: "campaign.world", search: "?category=location" }), scope: { campaignId: "c2" } }
        expect(navigate(ctx({ task: foreign })).detail.state).toBeUndefined()
        const hinted = { ...taskOf("world", { route: "campaign.world", search: "?category=location" }), transition: "context" }
        expect(navigate(ctx({ task: hinted })).detail.state).toEqual({
            task: taskOf("world", { route: "campaign.world", search: "?category=location" }),
        })
    })

    it("still carries the origin of an entry written before the task existed", () => {
        const result = navigate(ctx({ worldSearch: "?category=location" }))
        expect(result.listPath).toBe("/app/c1/world?category=location")
        expect(result.detail.state).toMatchObject({ task: { root: "world" } })
    })

    it("honours only an address of this very record", () => {
        const other = navigate(ctx({ returnTo: { pathname: "/app/c1/world/location/other", search: "?section=details" } }))
        expect(other.detail.to).toBe("/app/c1/world/location/l1")
        const elsewhere = navigate(ctx({ returnTo: { pathname: "https://evil.example/", search: "?x=1" } }))
        expect(elsewhere.detail.to).toBe("/app/c1/world/location/l1")
        const badSearch = navigate(ctx({ returnTo: { pathname: "/app/c1/world/location/l1", search: "section=x" } }))
        expect(badSearch.detail.to).toBe("/app/c1/world/location/l1")
    })
})

describe("worldEditNavigation with extra return addresses", () => {
    const area = worldEditNavigation("location", ({ campaignId, params }) =>
        params.dungeonId === undefined ? [] : [`/app/${campaignId}/world/location/${params.dungeonId}`],
    )
    const state = { returnTo: { pathname: "/app/c1/world/location/d1", search: "?section=areas" } }

    it("also returns to the address the page's own route names", () => {
        expect(area({ campaignId: "c1", entityId: "a1", state, params: { dungeonId: "d1" } }).detail.to).toBe(
            "/app/c1/world/location/d1?section=areas",
        )
    })

    it("never trusts a dungeon that only the state names", () => {
        expect(area({ campaignId: "c1", entityId: "a1", state, params: { dungeonId: "other" } }).detail.to).toBe(
            "/app/c1/world/location/a1",
        )
        expect(area({ campaignId: "c1", entityId: "a1", state, params: {} }).detail.to).toBe("/app/c1/world/location/a1")
    })
})

describe("the location edit page", () => {
    afterEach(() => vi.unstubAllGlobals())

    function open(state: unknown) {
        const server = installMockServer()
        server.on("GET", "/campaigns/c1/authoring/locations/l1", {
            body: {
                location_id: "l1",
                name: "Hollow",
                summary: null,
                category: { code: "region", label: "Region" },
                parent: null,
                population: null,
                building_use: null,
                canon_status: "draft",
                lifecycle_status: "active",
                row_version: 3,
                available_actions: ["update"],
                blocked_actions: [],
                field_locks: [],
            },
        })
        server.on("GET", "/campaigns/c1/authoring/locations/options", {
            body: {
                can_create: true,
                categories: [{ code: "region", label: "Region", fields: [] }],
                limits: { name_max_length: 200, summary_max_length: 4000, change_note_max_length: 1000 },
            },
        })
        server.on("GET", /parent-options/, { body: { items: [], next_cursor: null } })
        return renderAuthoringRoutes({
            initialEntry: { pathname: "/app/c1/world/location/l1/edit", state },
            routes: [
                { path: "/app/:campaignId/world/location/:entityId/edit", element: <EditLocationPage /> },
                { path: "/app/:campaignId/world/location/:entityId", element: <p>Location page</p> },
                { path: "/app/:campaignId/world", element: <p>World page</p> },
            ],
        })
    }

    it("sends Cancel back to the workspace section it was opened from", async () => {
        const { router } = open({
            returnTo: { pathname: "/app/c1/world/location/l1", search: "?section=details" },
            task: taskOf("review", { route: "review.queue", search: "?status=draft" }),
        })
        fireEvent.click(await screen.findByRole("button", { name: "Cancel" }))
        await screen.findByText("Location page")
        expect(router.state.location.pathname).toBe("/app/c1/world/location/l1")
        expect(router.state.location.search).toBe("?section=details")
        expect(router.state.location.state).toMatchObject({
            task: { root: "review", list: { route: "review.queue", search: "?status=draft" } },
        })
    })

    it.each<[string, () => object]>([
        ["a foreign explicit task", () => ({ task: { ...taskOf("world", { route: "campaign.world", search: "?category=location" }), scope: { campaignId: "c2" } } })],
        ["an explicit task whose list its root does not own", () => ({ task: taskOf("review", { route: "items.list", search: "" }) })],
        ["a malformed explicit task", () => ({ task: { v: 2 } })],
    ])("hands the historical Review origin back to the record when %s sits beside it", async (_name, explicit) => {
        const { router } = open({ ...explicit(), reviewSearch: "?status=draft" })
        fireEvent.click(await screen.findByRole("button", { name: "Cancel" }))
        await screen.findByText("Location page")
        expect(router.state.location.pathname).toBe("/app/c1/world/location/l1")
        expect(router.state.location.state).toEqual({ task: taskOf("review", { route: "review.queue", search: "?status=draft" }) })
    })

    it("a valid explicit task is handed back as it is, over a conflicting historical origin", async () => {
        const explicit = taskOf("world", { route: "campaign.world", search: "?category=location" })
        const { router } = open({ task: explicit, reviewSearch: "?status=draft" })
        fireEvent.click(await screen.findByRole("button", { name: "Cancel" }))
        await screen.findByText("Location page")
        expect(router.state.location.state).toEqual({ task: explicit })
    })

    it("hands back nothing when the explicit task and the historical state are both invalid", async () => {
        const { router } = open({ task: { v: 2 }, reviewSearch: "?status=draft&redirect=/x" })
        fireEvent.click(await screen.findByRole("button", { name: "Cancel" }))
        await screen.findByText("Location page")
        expect(router.state.location.state).toBeNull()
    })

    it("still goes to the plain location page when opened any other way", async () => {
        const { router } = open(null)
        fireEvent.click(await screen.findByRole("button", { name: "Cancel" }))
        await screen.findByText("Location page")
        expect(router.state.location.search).toBe("")
    })

    it("builds its breadcrumb from the same place", async () => {
        // Opened from the record inside World's task: the record is in the trail, so the shared breadcrumb names it.
        open({
            returnTo: { pathname: "/app/c1/world/location/l1", search: "?section=details" },
            task: taskOf("world", { route: "campaign.world", search: "?category=location" }, [
                { route: "world.record", params: { campaignId: "c1", category: "location", entityId: "l1" } },
            ]),
        })
        expect(await screen.findByRole("link", { name: "World" })).toHaveAttribute("href", "/app/c1/world?category=location")
        expect(screen.getByRole("link", { name: "Record" })).toHaveAttribute("href", "/app/c1/world/location/l1")
    })
})

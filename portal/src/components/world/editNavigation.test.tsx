import { fireEvent, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { EditLocationPage } from "../../pages/EditLocationPage"
import { installMockServer, renderAuthoringRoutes } from "../../test/authoringHarness"
import { worldEditNavigation } from "./editNavigation"

const navigate = worldEditNavigation("location")
const ctx = (state: unknown) => ({ campaignId: "c1", entityId: "l1", state })

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
                    worldSearch: "?category=location",
                    reviewSearch: "?status=draft",
                }),
            ),
        ).toEqual({
            listPath: "/app/c1/world?category=location",
            detail: {
                to: "/app/c1/world/location/l1?section=details",
                state: { worldSearch: "?category=location", reviewSearch: "?status=draft" },
            },
        })
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
            reviewSearch: "?status=draft",
        })
        fireEvent.click(await screen.findByRole("button", { name: "Cancel" }))
        await screen.findByText("Location page")
        expect(router.state.location.pathname).toBe("/app/c1/world/location/l1")
        expect(router.state.location.search).toBe("?section=details")
        expect(router.state.location.state).toMatchObject({ reviewSearch: "?status=draft" })
    })

    it("still goes to the plain location page when opened any other way", async () => {
        const { router } = open(null)
        fireEvent.click(await screen.findByRole("button", { name: "Cancel" }))
        await screen.findByText("Location page")
        expect(router.state.location.search).toBe("")
    })

    it("builds its breadcrumb from the same place", async () => {
        open({ returnTo: { pathname: "/app/c1/world/location/l1", search: "?section=details" }, worldSearch: "?category=location" })
        expect(await screen.findByRole("link", { name: "World" })).toHaveAttribute("href", "/app/c1/world?category=location")
        expect(screen.getByRole("link", { name: "Hollow" })).toHaveAttribute("href", "/app/c1/world/location/l1?section=details")
    })
})

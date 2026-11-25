import { act, fireEvent, screen, waitFor, within } from "@testing-library/react"
import type { ReactNode } from "react"
import { useParams } from "react-router"
import { afterEach, describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../../fixtures/sessionBootstrap"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../../test/authoringHarness"
import type { MockResponse, MockServer } from "../../test/authoringHarness"
import { useSession } from "../../context/SessionContext"
import { FULL_RECORD_AUTHORING } from "../../test/recordAuthoring"
import { installRecordReads } from "../../test/worldWorkspaceMocks"
import { CampaignWorldDetailPage } from "../../pages/CampaignWorldDetailPage"

// P15-C08-S02: "Places within" on a place's page (reader and editor workspace). These run the real hosts
// over the mock server in jsdom: they prove requests, rendered authorized content, addresses and focus
// order, not real-browser keyboard, zoom or screen-reader behavior.

const C = "c1"
const NOT_FOUND: MockResponse = { status: 404, body: { error: { code: "not_found", message: "m", correlation_id: "x" } } }
const FORBIDDEN: MockResponse = { status: 403, body: { error: { code: "forbidden", message: "m", correlation_id: "x" } } }
const UNAUTHORIZED: MockResponse = { status: 401, body: { error: { code: "unauthenticated", message: "m", correlation_id: "x" } } }
const BROKEN: MockResponse = { status: 500, body: { error: { code: "server_error", message: "m", correlation_id: "x" } } }

const detail = (id: string, name: string, over: object = {}) => ({
    authoring: FULL_RECORD_AUTHORING,
    location_id: id,
    name,
    summary: null,
    location_type_code: "region",
    parent_location_id: null,
    breadcrumbs: [],
    population: null,
    building_use: null,
    danger_level: null,
    is_searched: null,
    is_destroyed: null,
    alarm_level: null,
    condition_notes: null,
    ...over,
})

const child = (id: string, name: string, over: object = {}) => ({
    location_id: id,
    name,
    location_type_code: "building",
    summary: null,
    canon_status: "canon",
    lifecycle_status: "active",
    path: [] as object[],
    ...over,
})

const page = (items: object[], next: string | null = null): MockResponse => ({ body: { items, next_cursor: next } })
const childPath = (id: string, query = "") => `/campaigns/${C}/world/locations/${id}/children?limit=25${query}`
const kidsCalls = (server: MockServer) => server.calls.filter((c) => c.method === "GET" && c.path.includes("/children"))
const kidPaths = (server: MockServer) => kidsCalls(server).map((c) => c.path)

function deferred() {
    let resolve: (response: MockResponse) => void = () => undefined
    const promise = new Promise<MockResponse>((r) => {
        resolve = r
    })
    return { promise, resolve }
}

interface Options {
    capabilities?: string[]
    entry?: string | { pathname: string; search?: string; state?: unknown }
    places?: Record<string, object>
    onRefresh?: () => Promise<ReturnType<typeof bootstrapWith>>
    extra?: ReactNode
}

function setup(options: Options = {}) {
    const server = installMockServer()
    server.on("GET", /.*/, NOT_FOUND)
    const places = options.places ?? { l1: detail("l1", "The Vale") }
    for (const [id, place] of Object.entries(places)) {
        installRecordReads(server, { campaignId: C, entityId: id, entityTypeCode: "settlement", canon: "draft" })
        server.on("GET", `/campaigns/${C}/world/locations/${id}`, { body: place })
        server.on("GET", `/campaigns/${C}/entities/${id}/lifecycle`, {
            body: {
                entity_id: id,
                entity_type_code: "region",
                canonical_name: "x",
                canon_status: "draft",
                lifecycle_status: "active",
                row_version: 2,
                lifecycle_managed: true,
                superseded_by: null,
                available_actions: [],
                blocked_actions: [],
            },
        })
        server.on("GET", `/campaigns/${C}/authoring/locations/${id}`, { body: { available_actions: ["update"], blocked_actions: [] } })
    }
    const rendered = renderAuthoringRoutes({
        onRefresh: options.onRefresh,
        initialEntry: options.entry ?? `/app/${C}/world/location/l1`,
        bootstrap: bootstrapWith({
            campaigns: [
                {
                    ...sessionBootstrapFixture.campaigns[0]!,
                    campaign_id: C,
                    capabilities: options.capabilities ?? ["campaign.view"],
                },
            ],
        }),
        routes: [
            {
                path: "/app/:campaignId/world/:category/:entityId",
                element: (
                    <>
                        {options.extra}
                        <CampaignWorldDetailPage />
                    </>
                ),
            },
            { path: "/app/:campaignId/world", element: <p>World browser</p> },
        ],
    })
    return { server, ...rendered }
}

const EDITOR = ["canon.edit", "campaign.view"]
const listOf = (name: string) => screen.getByRole("list", { name: `Places within ${name}` })
const namesIn = (name: string) =>
    within(listOf(name))
        .getAllByRole("listitem")
        .map((li) => within(li).getAllByRole("link")[0]!.textContent)
const searchbox = (name: string) => screen.getByRole("searchbox", { name: `Search places within ${name}` })
const search = (name: string, text: string) => {
    fireEvent.change(searchbox(name), { target: { value: text } })
    fireEvent.click(screen.getByRole("button", { name: "Search" }))
}
const panelOpened = (name: string) => screen.findByRole("heading", { level: 2, name: `Places within ${name}` })

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("Places within a place", () => {
    it("N1: the reader lists the places inside, in the server's order, from one read of the first page", async () => {
        const { server } = setup()
        server.on("GET", childPath("l1"), page([child("b1", "Brook Mill"), child("a1", "Ash Hall", { location_type_code: "settlement" })]))
        await panelOpened("The Vale")
        await waitFor(() => expect(namesIn("The Vale")).toEqual(["Brook Mill", "Ash Hall"]))
        const links = within(listOf("The Vale")).getAllByRole("link")
        expect(links.map((l) => l.getAttribute("href"))).toEqual([`/app/${C}/world/location/b1`, `/app/${C}/world/location/a1`])
        expect(within(listOf("The Vale")).getByText("Settlement")).toBeVisible()
        expect(kidPaths(server)).toEqual([childPath("l1")])
    })

    it("N2: the editor's Details asks for drafts and archived places and shows status badges; the reader never does", async () => {
        const editor = setup({ capabilities: EDITOR })
        editor.server.on(
            "GET",
            childPath("l1", "&include_noncanon=true&include_archived=true"),
            page([child("d1", "Draft Hall", { canon_status: "draft" }), child("x1", "Old Keep", { lifecycle_status: "archived" })]),
        )
        await panelOpened("The Vale")
        await waitFor(() => expect(namesIn("The Vale")).toEqual(["Draft Hall", "Old Keep"]))
        const rows = within(listOf("The Vale")).getAllByRole("listitem")
        expect(within(rows[0]!).getByText("Draft")).toBeVisible()
        expect(within(rows[1]!).getByText("Archived")).toBeVisible()
        expect(kidPaths(editor.server)).toEqual([childPath("l1", "&include_noncanon=true&include_archived=true")])
    })

    it("N2: a reader's reads never carry the preview flags", async () => {
        const { server } = setup()
        server.on("GET", childPath("l1"), page([child("b1", "Brook Mill")]))
        await panelOpened("The Vale")
        await waitFor(() => expect(namesIn("The Vale")).toEqual(["Brook Mill"]))
        search("The Vale", "mill")
        await waitFor(() => expect(kidPaths(server)).toHaveLength(2))
        expect(kidPaths(server).some((p) => p.includes("include_"))).toBe(false)
    })

    it("N3: Show more sends the exact cursor, appends without duplicates and ends with no further control", async () => {
        const { server } = setup()
        server.on("GET", childPath("l1"), page([child("a", "Alder"), child("b", "Birch")], "cur1"))
        server.on("GET", childPath("l1", "&cursor=cur1"), page([child("b", "Birch"), child("c", "Cedar")], "cur2"))
        server.on("GET", childPath("l1", "&cursor=cur2"), page([child("d", "Dogwood")]))
        await panelOpened("The Vale")
        fireEvent.click(await screen.findByRole("button", { name: "Show more places" }))
        await waitFor(() => expect(namesIn("The Vale")).toEqual(["Alder", "Birch", "Cedar"]))
        fireEvent.click(screen.getByRole("button", { name: "Show more places" }))
        await waitFor(() => expect(namesIn("The Vale")).toEqual(["Alder", "Birch", "Cedar", "Dogwood"]))
        expect(screen.queryByRole("button", { name: "Show more places" })).toBeNull()
        expect(kidPaths(server)).toEqual([childPath("l1"), childPath("l1", "&cursor=cur1"), childPath("l1", "&cursor=cur2")])
        expect(server.calls.filter((c) => /\/world\/search|\/counts/.test(c.path))).toEqual([])
    })

    it("N4: the controls come in order — search field, Search, each result, Show more — and Show more moves focus to the first new result", async () => {
        const { server } = setup()
        server.on("GET", childPath("l1"), page([child("a", "Alder"), child("b", "Birch")], "cur1"))
        server.on("GET", childPath("l1", "&cursor=cur1"), page([child("c", "Cedar")]))
        await panelOpened("The Vale")
        const more = await screen.findByRole("button", { name: "Show more places" })
        const region = screen.getByRole("region", { name: "Places within The Vale" })
        const order = [...region.querySelectorAll<HTMLElement>("input, button, a[href]")].map((e) => (e.tagName === "INPUT" ? "search field" : e.textContent))
        expect(order).toEqual(["search field", "Search", "Alder", "Birch", "Show more places"])
        more.focus()
        fireEvent.click(more)
        await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("link", { name: "Cedar" })))
    })

    it("N4: Show more that adds nothing puts focus on the status line", async () => {
        const { server } = setup()
        server.on("GET", childPath("l1"), page([child("a", "Alder")], "cur1"))
        server.on("GET", childPath("l1", "&cursor=cur1"), page([child("a", "Alder")]))
        await panelOpened("The Vale")
        const more = await screen.findByRole("button", { name: "Show more places" })
        more.focus()
        fireEvent.click(more)
        await waitFor(() => expect(screen.getByText("Showing 1 place.")).toBeVisible())
        await waitFor(() => expect(document.activeElement).toBe(screen.getByText("Showing 1 place.")))
    })

    it("N5: submitting a search sets within by replacing the entry, keeps the other parameters and the state, and sends q; typing alone sends nothing", async () => {
        const task = { task: { v: 1, root: "world", scope: { campaignId: C }, trail: [] as object[] } }
        const { server, router } = setup({
            capabilities: EDITOR,
            entry: { pathname: `/app/${C}/world/location/l1`, search: "?section=details", state: task },
        })
        server.on("GET", childPath("l1", "&include_noncanon=true&include_archived=true"), page([child("a", "Alder")]))
        server.on("GET", childPath("l1", "&q=cave+mouth&include_noncanon=true&include_archived=true"), page([child("m", "Cave Mouth")]))
        await panelOpened("The Vale")
        await waitFor(() => expect(namesIn("The Vale")).toEqual(["Alder"]))
        const sent = kidPaths(server).length
        fireEvent.change(searchbox("The Vale"), { target: { value: "cave mouth" } })
        expect(kidPaths(server)).toHaveLength(sent)
        fireEvent.click(screen.getByRole("button", { name: "Search" }))
        await waitFor(() => expect(namesIn("The Vale")).toEqual(["Cave Mouth"]))
        const here = router.state.location
        expect(new URLSearchParams(here.search).get("within")).toBe("cave mouth")
        expect(new URLSearchParams(here.search).get("section")).toBe("details")
        expect(router.state.historyAction).toBe("REPLACE")
        expect(here.state).toMatchObject(task)
        await waitFor(() => expect(document.activeElement).toBe(searchbox("The Vale")))
    })

    it("N6: a deep result shows where it sits as plain text, and its link opens that place", async () => {
        const { server } = setup()
        server.on("GET", childPath("l1"), page([]))
        server.on(
            "GET",
            childPath("l1", "&q=cellar"),
            page([
                child("d1", "Wine Cellar", {
                    path: [
                        { location_id: "r1", name: "Ashen Vale", location_type_code: "region" },
                        { location_id: "h1", name: "Hollowmere", location_type_code: "settlement" },
                    ],
                }),
            ]),
        )
        await panelOpened("The Vale")
        search("The Vale", "cellar")
        const row = (await screen.findByRole("link", { name: "Wine Cellar" })).closest("li")!
        expect(row).toHaveTextContent("in Ashen Vale › Hollowmere")
        expect(within(row).getAllByRole("link")).toHaveLength(1)
        expect(within(row).getByRole("link", { name: "Wine Cellar" })).toHaveAttribute("href", `/app/${C}/world/location/d1`)
    })

    it("N8: the status line says empty, empty for a query, more available and none left — never a total", async () => {
        const { server } = setup()
        server.on("GET", childPath("l1"), page([]))
        server.on("GET", childPath("l1", "&q=zzz"), page([]))
        await panelOpened("The Vale")
        expect(await screen.findByText("No places within The Vale.")).toBeVisible()
        search("The Vale", "zzz")
        expect(await screen.findByText("No places within The Vale match “zzz”.")).toBeVisible()
        server.on("GET", childPath("l1", "&q=a"), page([child("a", "Alder"), child("b", "Ash")], "cur1"))
        server.on("GET", childPath("l1", "&q=a&cursor=cur1"), page([child("c", "Aspen")]))
        search("The Vale", "a")
        expect(await screen.findByText("Showing 2 places. More are available.")).toBeVisible()
        fireEvent.click(screen.getByRole("button", { name: "Show more places" }))
        expect(await screen.findByText("Showing 3 places.")).toBeVisible()
        expect(document.body.textContent).not.toMatch(/\btotal\b/i)
    })

    it("N9: a late answer to a superseded query is never shown", async () => {
        const { server } = setup()
        const slow = deferred()
        server.on("GET", childPath("l1"), page([]))
        server.on("GET", childPath("l1", "&q=a"), () => slow.promise)
        server.on("GET", childPath("l1", "&q=b"), page([child("b", "Bravo")]))
        await panelOpened("The Vale")
        search("The Vale", "a")
        await waitFor(() => expect(kidPaths(server)).toContain(childPath("l1", "&q=a")))
        search("The Vale", "b")
        await waitFor(() => expect(namesIn("The Vale")).toEqual(["Bravo"]))
        await act(async () => {
            slow.resolve(page([child("a", "Stale Answer")]))
        })
        expect(screen.queryByText("Stale Answer")).toBeNull()
        expect(namesIn("The Vale")).toEqual(["Bravo"])
    })

    it("N10: a late answer for another place never renders under the place now shown", async () => {
        // Rendered directly with the place taken from the route, so the same panel stays mounted across places.
        const mod = "./LocationChildren"
        const { LocationChildren } = (await import(/* @vite-ignore */ mod)) as typeof import("./LocationChildren")
        const names: Record<string, string> = { p1: "Parent", p2: "Other" }
        function Host() {
            const { entityId = "p1" } = useParams()
            return <LocationChildren campaignId={C} location={{ location_id: entityId, name: names[entityId]! }} includeHidden={false} />
        }
        const server = installMockServer()
        const slow = deferred()
        server.on("GET", childPath("p1"), () => slow.promise)
        server.on("GET", childPath("p2"), page([child("o1", "Other Child")]))
        const { router } = renderAuthoringRoutes({
            initialEntry: `/app/${C}/world/location/p1`,
            routes: [{ path: "/app/:campaignId/world/location/:entityId", element: <Host /> }],
        })
        await waitFor(() => expect(kidPaths(server)).toHaveLength(1))
        await act(() => router.navigate(`/app/${C}/world/location/p2`))
        await waitFor(() => expect(namesIn("Other")).toEqual(["Other Child"]))
        await act(async () => {
            slow.resolve(page([child("p9", "Parent Row")]))
        })
        expect(screen.queryByText("Parent Row")).toBeNull()
        expect(namesIn("Other")).toEqual(["Other Child"])
    })

    it("N11: a Show more answered 404 clears every loaded row and says the places are not available", async () => {
        const { server } = setup()
        server.on("GET", childPath("l1"), page([child("a", "Alder")], "cur1"))
        server.on("GET", childPath("l1", "&cursor=cur1"), NOT_FOUND)
        await panelOpened("The Vale")
        fireEvent.click(await screen.findByRole("button", { name: "Show more places" }))
        expect(await screen.findByText("Places within this place are not available.")).toBeVisible()
        expect(screen.queryByText("Alder")).toBeNull()
        expect(screen.queryByRole("list", { name: "Places within The Vale" })).toBeNull()
        expect(screen.queryByRole("button", { name: "Show more places" })).toBeNull()
    })

    it("N12: a first page answered 403 lists nothing and says so; a 401 asks the session to reload and lists nothing", async () => {
        const forbidden = setup()
        forbidden.server.on("GET", childPath("l1"), FORBIDDEN)
        await panelOpened("The Vale")
        expect(await screen.findByText("Places within this place are not available.")).toBeVisible()
        expect(screen.queryByRole("list", { name: "Places within The Vale" })).toBeNull()
        forbidden.unmount()

        const expired = setup()
        expired.server.on("GET", childPath("l1"), UNAUTHORIZED)
        await panelOpened("The Vale")
        await waitFor(() => expect(expired.reload).toHaveBeenCalled())
        expect(screen.queryByRole("list", { name: "Places within The Vale" })).toBeNull()
        expect(screen.queryByText("Places within this place are not available.")).toBeNull()
    })

    it("N13: when canon.edit is lost the reader requests without the flags and no draft from the editor's list remains", async () => {
        function Refresh() {
            const { refresh } = useSession()
            return (
                <button type="button" onClick={() => void refresh()}>
                    Refresh session
                </button>
            )
        }
        const { server } = setup({
            capabilities: EDITOR,
            extra: <Refresh />,
            onRefresh: async () =>
                bootstrapWith({
                    campaigns: [{ ...sessionBootstrapFixture.campaigns[0]!, campaign_id: C, capabilities: ["campaign.view"] }],
                }),
        })
        server.on("GET", childPath("l1", "&include_noncanon=true&include_archived=true"), page([child("d1", "Secret Draft"), child("p1", "Public Hall")]))
        server.on("GET", childPath("l1"), page([child("p1", "Public Hall")]))
        await panelOpened("The Vale")
        await waitFor(() => expect(namesIn("The Vale")).toEqual(["Secret Draft", "Public Hall"]))
        fireEvent.click(screen.getByRole("button", { name: "Refresh session" }))
        await waitFor(() => expect(kidPaths(server).at(-1)).toBe(childPath("l1")))
        await waitFor(() => expect(namesIn("The Vale")).toEqual(["Public Hall"]))
        expect(screen.queryByText("Secret Draft")).toBeNull()
    })

    it("N14: a 500 on Show more keeps the loaded rows with an alert, and Try again sends the identical request once", async () => {
        const { server } = setup()
        server.on("GET", childPath("l1"), page([child("a", "Alder")], "cur1"))
        server.on("GET", childPath("l1", "&cursor=cur1"), BROKEN)
        await panelOpened("The Vale")
        fireEvent.click(await screen.findByRole("button", { name: "Show more places" }))
        const alert = await screen.findByRole("alert")
        expect(alert).toHaveTextContent("could not be loaded")
        expect(namesIn("The Vale")).toEqual(["Alder"])
        server.on("GET", childPath("l1", "&cursor=cur1"), page([child("b", "Birch")]))
        fireEvent.click(within(alert).getByRole("button", { name: "Try again" }))
        await waitFor(() => expect(namesIn("The Vale")).toEqual(["Alder", "Birch"]))
        expect(kidPaths(server).filter((p) => p === childPath("l1", "&cursor=cur1"))).toHaveLength(2)
        expect(screen.queryByRole("alert")).toBeNull()
    })

    it("N15: a dungeon area has no Places within panel and sends no children request — in the reader and the workspace", async () => {
        const area = detail("a1", "Crypt Room", { location_type_code: "dungeon_area" })
        const reader = setup({ places: { a1: area }, entry: `/app/${C}/world/location/a1` })
        await screen.findByRole("heading", { level: 1, name: "Crypt Room" })
        await screen.findByRole("heading", { level: 2, name: "Containment" })
        expect(screen.queryByRole("heading", { name: /Places within/ })).toBeNull()
        expect(kidsCalls(reader.server)).toEqual([])
        reader.unmount()

        const editor = setup({ places: { a1: area }, capabilities: EDITOR, entry: `/app/${C}/world/location/a1` })
        await screen.findByRole("heading", { level: 1, name: "Crypt Room" })
        await screen.findByRole("heading", { level: 2, name: "Containment" })
        expect(screen.queryByRole("heading", { name: /Places within/ })).toBeNull()
        expect(kidsCalls(editor.server)).toEqual([])
    })

    it("N17: changing the query clears the old rows at once, before the new answer arrives", async () => {
        const { server } = setup()
        const slow = deferred()
        server.on("GET", childPath("l1"), page([child("a", "Alder")]))
        server.on("GET", childPath("l1", "&q=b"), () => slow.promise)
        await panelOpened("The Vale")
        await waitFor(() => expect(namesIn("The Vale")).toEqual(["Alder"]))
        search("The Vale", "b")
        await waitFor(() => expect(kidPaths(server)).toContain(childPath("l1", "&q=b")))
        expect(screen.queryByText("Alder")).toBeNull()
        expect(screen.getByText("Loading places…")).toBeVisible()
        await act(async () => {
            slow.resolve(page([child("b", "Birch")]))
        })
        await waitFor(() => expect(namesIn("The Vale")).toEqual(["Birch"]))
    })

    it("N18: Clear search removes within and lists the direct children again, with focus on the search field", async () => {
        const { server, router } = setup({
            entry: `/app/${C}/world/location/l1?within=cave&r=1`,
        })
        server.on("GET", childPath("l1", "&q=cave"), page([child("m", "Cave Mouth")]))
        server.on("GET", childPath("l1"), page([child("a", "Alder")]))
        await panelOpened("The Vale")
        await waitFor(() => expect(namesIn("The Vale")).toEqual(["Cave Mouth"]))
        expect(searchbox("The Vale")).toHaveValue("cave")
        fireEvent.click(screen.getByRole("button", { name: "Clear search" }))
        await waitFor(() => expect(namesIn("The Vale")).toEqual(["Alder"]))
        const params = new URLSearchParams(router.state.location.search)
        expect(params.has("within")).toBe(false)
        expect(params.get("r")).toBe("1")
        expect(searchbox("The Vale")).toHaveValue("")
        expect(screen.queryByRole("button", { name: "Clear search" })).toBeNull()
        await waitFor(() => expect(document.activeElement).toBe(searchbox("The Vale")))
    })
})

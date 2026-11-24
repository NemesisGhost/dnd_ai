import { act, fireEvent, screen, waitFor } from "@testing-library/react"
import { Link } from "react-router"
import { afterEach, describe, expect, it, vi } from "vitest"
import { AnnouncerContext } from "../components/authoring/announcer"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import { WorldsPage } from "./WorldsPage"

// P15-C06-S01-T01: one "Include archived worlds" checkbox that unions the server's active and
// archived worlds (status=all) with the bootstrap's campaign-visible worlds, keeps its state in the
// address, keeps focus on the control and announces one settled result per change.

const world = (id: string, name: string, extra: object = {}) => ({
    world_id: id,
    name,
    description: null,
    lifecycle_status: "active",
    row_version: 1,
    primary_timeline_id: null,
    capabilities: ["world.manage"],
    ...extra,
})

const archivedWorld = (id: string, name: string, extra: object = {}) =>
    world(id, name, { lifecycle_status: "archived", ...extra })

const campaign = (id: string, name: string, worldId: string, worldName: string) => ({
    ...sessionBootstrapFixture.campaigns[0],
    campaign_id: id,
    campaign_name: name,
    world_id: worldId,
    world_name: worldName,
    roles: ["player"],
    capabilities: ["campaign.view"],
})

const page = (items: object[], next_cursor: string | null = null) => ({ body: { items, next_cursor } })

const CHECKBOX = "Include archived worlds"

function render(
    options: { entry?: string; bootstrap?: ReturnType<typeof bootstrapWith>; announce?: (m: string) => void } = {},
) {
    const announce = options.announce ?? vi.fn()
    const view = renderAuthoringRoutes({
        initialEntry: options.entry ?? "/worlds",
        routes: [
            {
                path: "/worlds",
                element: (
                    <AnnouncerContext.Provider value={{ announce }}>
                        <WorldsPage />
                        <Link to="/elsewhere">Elsewhere</Link>
                    </AnnouncerContext.Provider>
                ),
            },
            { path: "/elsewhere", element: <p>Elsewhere page</p> },
        ],
        bootstrap: options.bootstrap ?? bootstrapWith({ campaigns: [] }),
    })
    return { ...view, announce }
}

function names(): (string | null | undefined)[] {
    return screen.getAllByRole("listitem").map((li) => li.querySelector("a")?.textContent)
}

function listCalls(server: ReturnType<typeof installMockServer>) {
    return server.callsTo("GET", /^\/worlds\?/).map((c) => c.path)
}

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("WorldsPage filter", () => {
    it("F1: checking Include archived worlds requests status=all and lists active and archived together", async () => {
        const server = installMockServer()
        server.on("GET", /^\/worlds\?status=active/, page([world("w1", "Eberron")]))
        server.on(
            "GET",
            /^\/worlds\?status=all/,
            page([world("w1", "Eberron"), archivedWorld("w9", "Old World")]),
        )
        render()
        await screen.findByRole("link", { name: "Eberron" })
        expect(screen.getByRole("checkbox", { name: CHECKBOX })).not.toBeChecked()
        expect(screen.queryByRole("radio")).not.toBeInTheDocument()

        fireEvent.click(screen.getByRole("checkbox", { name: CHECKBOX }))

        await screen.findByRole("link", { name: "Old World" })
        expect(names()).toEqual(["Eberron", "Old World"])
        expect(screen.getByText("Archived", { selector: "span.authoring-badge" })).toBeInTheDocument()
        expect(screen.getByRole("link", { name: "Old World" }).closest("li")).toHaveTextContent("Archived")
        expect(screen.getByRole("link", { name: "Eberron" }).closest("li")).not.toHaveTextContent("Archived")
        expect(listCalls(server)).toEqual(["/worlds?status=active&limit=100", "/worlds?status=all&limit=100"])
    })

    it("F2: with the box checked a campaign-visible world is still listed, view only, with no archived badge", async () => {
        const server = installMockServer()
        server.on("GET", /^\/worlds\?status=active/, page([world("w1", "Eberron")]))
        server.on("GET", /^\/worlds\?status=all/, page([world("w1", "Eberron"), archivedWorld("w9", "Old World")]))
        render({
            bootstrap: bootstrapWith({
                global_capabilities: [],
                campaigns: [campaign("camp-a", "Campaign A", "w-hosted", "Hosted World")],
            }),
        })
        await screen.findByRole("link", { name: "Hosted World" })
        fireEvent.click(screen.getByRole("checkbox", { name: CHECKBOX }))
        await screen.findByRole("link", { name: "Old World" })

        const hosted = screen.getByRole("link", { name: "Hosted World" })
        expect(hosted).toHaveAttribute("href", "/app/camp-a/world")
        const item = hosted.closest("li")!
        expect(item).toHaveTextContent("View only")
        expect(item).toHaveTextContent("Through campaign Campaign A")
        expect(item).not.toHaveTextContent("Archived")
    })

    it("F3: a world that is both explicit and campaign-visible appears once with its explicit link, in the checked state", async () => {
        const server = installMockServer()
        server.on("GET", /^\/worlds\?status=active/, page([]))
        server.on(
            "GET",
            /^\/worlds\?status=all/,
            page([
                archivedWorld("w-arch", "Archived Shared", { capabilities: ["world.view", "world.manage"] }),
                world("w-act", "Active Shared", { capabilities: ["world.view", "world.manage"] }),
            ]),
        )
        render({
            entry: "/worlds?archived=1",
            bootstrap: bootstrapWith({
                campaigns: [
                    campaign("camp-a", "Alpha", "w-arch", "Archived Shared"),
                    campaign("camp-b", "Beta", "w-act", "Active Shared"),
                ],
            }),
        })
        await screen.findByRole("link", { name: "Archived Shared" })
        expect(screen.getAllByRole("link", { name: "Archived Shared" })).toHaveLength(1)
        expect(screen.getAllByRole("link", { name: "Active Shared" })).toHaveLength(1)
        expect(screen.getByRole("link", { name: "Archived Shared" })).toHaveAttribute("href", "/worlds/w-arch")
        expect(screen.getByRole("link", { name: "Active Shared" })).toHaveAttribute("href", "/worlds/w-act")
        expect(screen.getByRole("link", { name: "Archived Shared" }).closest("li")).toHaveTextContent("Archived")
        expect(names()).toHaveLength(2)
    })

    it("F4: checking writes ?archived=1 by REPLACE and unchecking removes it, keeping other parameters", async () => {
        const server = installMockServer()
        server.on("GET", /^\/worlds\?/, page([world("w1", "Eberron")]))
        const { router } = render({ entry: "/worlds?q=x&status=archived" })
        await screen.findByRole("link", { name: "Eberron" })
        const start = window.history.length

        // The legacy status parameter is dropped when writing; other parameters stay.
        fireEvent.click(screen.getByRole("checkbox", { name: CHECKBOX }))
        await waitFor(() => expect(router.state.location.search).toBe("?q=x"))
        expect(screen.getByRole("checkbox", { name: CHECKBOX })).not.toBeChecked()

        fireEvent.click(screen.getByRole("checkbox", { name: CHECKBOX }))
        await waitFor(() => expect(router.state.location.search).toBe("?q=x&archived=1"))
        expect(router.state.historyAction).toBe("REPLACE")
        expect(window.history.length).toBe(start)

        fireEvent.click(screen.getByRole("checkbox", { name: CHECKBOX }))
        await waitFor(() => expect(router.state.location.search).toBe("?q=x"))
        expect(router.state.historyAction).toBe("REPLACE")
    })

    it("F4: the entry is replaced, so Back leaves the page instead of stepping through filter states", async () => {
        installMockServer().on("GET", /^\/worlds\?/, page([world("w1", "Eberron")]))
        const { router } = render()
        await screen.findByRole("link", { name: "Eberron" })
        const entries: string[] = []
        const unsubscribe = router.subscribe((s) => entries.push(`${s.historyAction}${s.location.search}`))
        fireEvent.click(screen.getByRole("checkbox", { name: CHECKBOX }))
        await waitFor(() => expect(router.state.location.search).toBe("?archived=1"))
        unsubscribe()
        expect(entries).toContain("REPLACE?archived=1")
        expect(entries.some((e) => e.startsWith("PUSH"))).toBe(false)
    })

    it.each([
        ["/worlds?archived=1", true, "all"],
        ["/worlds?status=archived", true, "all"],
        ["/worlds?status=active", false, "active"],
        ["/worlds", false, "active"],
    ])("F5: %s opens %s and requests status=%s", async (entry, checked, status) => {
        const server = installMockServer()
        server.on("GET", /^\/worlds\?/, page([world("w1", "Eberron")]))
        render({ entry })
        await screen.findByRole("link", { name: "Eberron" })
        const box = screen.getByRole("checkbox", { name: CHECKBOX })
        if (checked) expect(box).toBeChecked()
        else expect(box).not.toBeChecked()
        expect(listCalls(server)).toEqual([`/worlds?status=${status}&limit=100`])
    })

    // Guard cases (F6, F9, F11, F12, F14) are written against the address, not the new control, so they
    // run unchanged at the baseline: the legacy ?status=archived address already selects the archived
    // state there and, after the change, the checked one.
    it.each(["/worlds?status=archived", "/worlds?archived=1"])(
        "F6 (guard on the legacy address; the new address is also checked below): Back and Forward from %s restore the list",
        async (entry) => {
            const server = installMockServer()
            server.on("GET", /^\/worlds\?status=active/, page([world("w1", "Eberron")]))
            server.on("GET", /^\/worlds\?status=(archived|all)/, page([archivedWorld("w9", "Old World")]))
            const { router } = render({ entry })
            if (entry.includes("archived=1")) {
                // Only the new address needs the checkbox; at baseline this entry is not a guard.
                await screen.findByRole("checkbox", { name: CHECKBOX })
            }
            await screen.findByRole("link", { name: "Old World" })
            await act(async () => {
                await router.navigate("/elsewhere")
            })
            expect(await screen.findByText("Elsewhere page")).toBeInTheDocument()
            await act(async () => {
                await router.navigate(-1)
            })
            await screen.findByRole("link", { name: "Old World" })
            expect(router.state.location.search).toBe(entry.slice(entry.indexOf("?")))
            expect(names()).toEqual(["Old World"])
            if (entry.includes("archived=1")) {
                expect(screen.getByRole("checkbox", { name: CHECKBOX })).toBeChecked()
            }
        },
    )

    it("F7: a filter change keeps focus on the checkbox; arriving still focuses the heading once", async () => {
        const server = installMockServer()
        server.on("GET", /^\/worlds\?status=active/, page([world("w1", "Eberron")]))
        server.on("GET", /^\/worlds\?status=all/, page([world("w1", "Eberron"), archivedWorld("w9", "Old World")]))
        render()
        const heading = await screen.findByRole("heading", { level: 1, name: "Worlds" })
        await waitFor(() => expect(heading).toHaveFocus())

        const box = screen.getByRole("checkbox", { name: CHECKBOX })
        box.focus()
        fireEvent.click(box)
        await screen.findByRole("link", { name: "Old World" })
        await act(async () => {
            await Promise.resolve()
        })
        expect(screen.getByRole("checkbox", { name: CHECKBOX })).toHaveFocus()
        expect(heading).not.toHaveFocus()

        screen.getByRole("checkbox", { name: CHECKBOX }).focus()
        fireEvent.click(screen.getByRole("checkbox", { name: CHECKBOX }))
        await waitFor(() => expect(screen.queryByRole("link", { name: "Old World" })).not.toBeInTheDocument())
        expect(screen.getByRole("checkbox", { name: CHECKBOX })).toHaveFocus()
    })

    it("F8: one announcement per settled change, none on arrival", async () => {
        const server = installMockServer()
        server.on("GET", /^\/worlds\?status=active/, page([world("w1", "Eberron"), world("w2", "Faerûn")]))
        server.on(
            "GET",
            /^\/worlds\?status=all/,
            page([world("w1", "Eberron"), world("w2", "Faerûn"), archivedWorld("w9", "Old World")]),
        )
        const { announce } = render()
        await screen.findByRole("link", { name: "Eberron" })
        await act(async () => {
            await Promise.resolve()
        })
        expect(announce).not.toHaveBeenCalled()

        fireEvent.click(screen.getByRole("checkbox", { name: CHECKBOX }))
        await screen.findByRole("link", { name: "Old World" })
        await waitFor(() => expect(announce).toHaveBeenCalledTimes(1))
        expect(announce).toHaveBeenLastCalledWith("Showing 3 worlds, including archived.")

        fireEvent.click(screen.getByRole("checkbox", { name: CHECKBOX }))
        await waitFor(() => expect(screen.queryByRole("link", { name: "Old World" })).not.toBeInTheDocument())
        await waitFor(() => expect(announce).toHaveBeenCalledTimes(2))
        expect(announce).toHaveBeenLastCalledWith("Showing 2 active worlds.")
        await act(async () => {
            await Promise.resolve()
        })
        expect(announce).toHaveBeenCalledTimes(2)
    })

    it("F8: counts the deduplicated worlds actually displayed, campaign-visible ones included, and says 1 world", async () => {
        const server = installMockServer()
        server.on("GET", /^\/worlds\?status=active/, page([world("w1", "Eberron")]))
        server.on("GET", /^\/worlds\?status=all/, page([world("w1", "Eberron"), archivedWorld("w9", "Old World")]))
        const { announce } = render({
            bootstrap: bootstrapWith({
                campaigns: [
                    campaign("camp-a", "Alpha", "w1", "Eberron"),
                    campaign("camp-b", "Beta", "w-hosted", "Hosted World"),
                    campaign("camp-c", "Gamma", "w-hosted", "Hosted World"),
                ],
            }),
        })
        await screen.findByRole("link", { name: "Hosted World" })
        fireEvent.click(screen.getByRole("checkbox", { name: CHECKBOX }))
        await screen.findByRole("link", { name: "Old World" })
        await waitFor(() => expect(announce).toHaveBeenCalledTimes(1))
        // Eberron (explicit, once), Old World, Hosted World (campaign, once).
        expect(announce).toHaveBeenLastCalledWith("Showing 3 worlds, including archived.")
        fireEvent.click(screen.getByRole("checkbox", { name: CHECKBOX }))
        await waitFor(() => expect(announce).toHaveBeenCalledTimes(2))
        expect(announce).toHaveBeenLastCalledWith("Showing 2 active worlds.")
    })

    it("F8: a single world is announced as 1 world", async () => {
        const server = installMockServer()
        server.on("GET", /^\/worlds\?status=active/, page([]))
        server.on("GET", /^\/worlds\?status=all/, page([archivedWorld("w9", "Old World")]))
        const { announce } = render()
        await screen.findByText(/You do not have access to any worlds yet/)
        fireEvent.click(screen.getByRole("checkbox", { name: CHECKBOX }))
        await waitFor(() => expect(announce).toHaveBeenCalledWith("Showing 1 world, including archived."))
    })

    it("F8: rapid changes announce only the settled final state and never a superseded result", async () => {
        const server = installMockServer()
        let releaseAll: (() => void) | undefined
        const allHeld = new Promise<void>((resolve) => {
            releaseAll = resolve
        })
        server.on("GET", /^\/worlds\?status=active/, page([world("w1", "Eberron")]))
        server.on("GET", /^\/worlds\?status=all/, async () => {
            await allHeld
            return page([world("w1", "Eberron"), archivedWorld("w9", "Old World")])
        })
        const { announce } = render()
        await screen.findByRole("link", { name: "Eberron" })

        const box = screen.getByRole("checkbox", { name: CHECKBOX })
        box.focus()
        fireEvent.click(box) // archived: held
        await screen.findByText("Loading worlds…")
        fireEvent.click(screen.getByRole("checkbox", { name: CHECKBOX })) // back to active before the answer
        await screen.findByRole("link", { name: "Eberron" })
        releaseAll?.()
        await act(async () => {
            await new Promise((r) => setTimeout(r, 20))
        })
        expect(screen.queryByRole("link", { name: "Old World" })).not.toBeInTheDocument()
        expect(announce).toHaveBeenCalledTimes(1)
        expect(announce).toHaveBeenLastCalledWith("Showing 1 active world.")
        expect(announce).not.toHaveBeenCalledWith(expect.stringContaining("including archived"))
        expect(screen.getByRole("checkbox", { name: CHECKBOX })).toHaveFocus()
    })

    it("F8: a failed read announces no new count", async () => {
        const server = installMockServer()
        server.on("GET", /^\/worlds\?status=active/, page([world("w1", "Eberron")]))
        server.on("GET", /^\/worlds\?status=all/, { status: 500 })
        const { announce } = render()
        await screen.findByRole("link", { name: "Eberron" })
        fireEvent.click(screen.getByRole("checkbox", { name: CHECKBOX }))
        expect(await screen.findByRole("alert")).toHaveTextContent("could not be loaded")
        await act(async () => {
            await new Promise((r) => setTimeout(r, 20))
        })
        expect(announce).not.toHaveBeenCalled()
        // The failed state does not leave a stale announcement waiting for a later list.
        fireEvent.click(screen.getByRole("checkbox", { name: CHECKBOX }))
        await screen.findByRole("link", { name: "Eberron" })
        await waitFor(() => expect(announce).toHaveBeenCalledTimes(1))
        expect(announce).toHaveBeenLastCalledWith("Showing 1 active world.")
    })

    it("F9 (guard): a late answer for the previous state never replaces the current list", async () => {
        const server = installMockServer()
        let release: (() => void) | undefined
        const held = new Promise<void>((resolve) => {
            release = resolve
        })
        server.on("GET", /^\/worlds\?status=active/, page([world("w1", "Eberron")]))
        server.on("GET", /^\/worlds\?status=(archived|all)/, async () => {
            await held
            return page([archivedWorld("w9", "Old World")])
        })
        const { router } = render()
        await screen.findByRole("link", { name: "Eberron" })
        await act(async () => {
            await router.navigate("/worlds?status=archived", { replace: true })
        })
        await screen.findByText("Loading worlds…")
        await act(async () => {
            await router.navigate("/worlds", { replace: true })
        })
        await screen.findByRole("link", { name: "Eberron" })
        release?.()
        await act(async () => {
            await new Promise((r) => setTimeout(r, 20))
        })
        expect(names()).toEqual(["Eberron"])
    })

    it("F10: empty states: checked has the general text, unchecked keeps today's text and Create hint", async () => {
        const server = installMockServer()
        server.on("GET", /^\/worlds\?/, page([]))
        render()
        expect(await screen.findByText(/You do not have access to any worlds yet\. Create one to start a campaign\./)).toBeInTheDocument()
        fireEvent.click(screen.getByRole("checkbox", { name: CHECKBOX }))
        await waitFor(() => expect(screen.getByRole("checkbox", { name: CHECKBOX })).toBeChecked())
        expect(await screen.findByText(/You do not have access to any worlds yet/)).toBeInTheDocument()
        expect(screen.queryByText(/no archived worlds/)).not.toBeInTheDocument()
        expect(listCalls(server)).toContain("/worlds?status=all&limit=100")
    })

    it("F11 (guard): the first-100 note follows next_cursor in the active and archived addresses, one request per state", async () => {
        const server = installMockServer()
        server.on("GET", /^\/worlds\?status=active/, page([world("w1", "Eberron")], "cur-a"))
        server.on("GET", /^\/worlds\?status=(archived|all)/, page([archivedWorld("w9", "Old World")], "cur-b"))
        const { router } = render()
        expect(await screen.findByText(/^Only the first 100 worlds are shown\./)).toBeInTheDocument()
        await act(async () => {
            await router.navigate("/worlds?status=archived", { replace: true })
        })
        await screen.findByRole("link", { name: "Old World" })
        expect(screen.getByText(/^Only the first 100 worlds are shown\./)).toBeInTheDocument()
        expect(listCalls(server)).toHaveLength(2)
        expect(listCalls(server)[0]).toBe("/worlds?status=active&limit=100")
    })

    it("F11: checked adds the archived-count sentence; unchecked does not; one request per state", async () => {
        const server = installMockServer()
        server.on("GET", /^\/worlds\?status=active/, page([world("w1", "Eberron")], "cur-a"))
        server.on("GET", /^\/worlds\?status=all/, page([world("w1", "Eberron"), archivedWorld("w9", "Old World")], "cur-b"))
        render()
        expect(await screen.findByText("Only the first 100 worlds are shown.")).toBeInTheDocument()
        expect(screen.queryByText(/Archived worlds count toward this limit/)).not.toBeInTheDocument()
        fireEvent.click(screen.getByRole("checkbox", { name: CHECKBOX }))
        await screen.findByRole("link", { name: "Old World" })
        expect(
            screen.getByText(/Only the first 100 worlds are shown\. Archived worlds count toward this limit\./),
        ).toBeInTheDocument()
        expect(listCalls(server)).toEqual(["/worlds?status=active&limit=100", "/worlds?status=all&limit=100"])
    })

    it("F11: the note is absent without next_cursor", async () => {
        const server = installMockServer()
        server.on("GET", /^\/worlds\?/, page([world("w1", "Eberron")]))
        render({ entry: "/worlds?archived=1" })
        await screen.findByRole("link", { name: "Eberron" })
        expect(screen.queryByText(/Only the first 100/)).not.toBeInTheDocument()
    })

    it("F11: campaign-visible worlds are added to a limited response, and the note says so truthfully", async () => {
        const server = installMockServer()
        server.on("GET", /^\/worlds\?/, page([world("w1", "Eberron")], "cur"))
        const { announce } = render({
            bootstrap: bootstrapWith({
                campaigns: [campaign("camp-a", "Campaign A", "w-hosted", "Hosted World")],
            }),
        })
        await screen.findByRole("link", { name: "Hosted World" })
        expect(
            screen.getByText(/Only the first 100 worlds are shown\..*Worlds visible through a campaign are listed in addition\./),
        ).toBeInTheDocument()
        fireEvent.click(screen.getByRole("checkbox", { name: CHECKBOX }))
        await waitFor(() => expect(announce).toHaveBeenCalledWith("Showing 2 worlds, including archived."))
        expect(screen.getByText(/Archived worlds count toward this limit\./)).toBeInTheDocument()
        expect(screen.getByText(/Worlds visible through a campaign are listed in addition\./)).toBeInTheDocument()
    })

    it.each([
        ["denied", 403, "not available to you"],
        ["unavailable", 404, "not available to you"],
        ["error", 500, "could not be loaded"],
    ])("F12 (guard): a %s read keeps today's state on the archived address", async (_kind, status, text) => {
        installMockServer().on("GET", /^\/worlds\?/, { status })
        render({ entry: "/worlds?status=archived" })
        expect(await screen.findByRole("alert")).toHaveTextContent(text)
    })

    it("F12 (guard): an expired session reloads on the archived address", async () => {
        installMockServer().on("GET", /^\/worlds\?/, { status: 401 })
        const { reload } = render({ entry: "/worlds?status=archived" })
        await waitFor(() => expect(reload).toHaveBeenCalled())
    })

    it("F14 (guard): lists no identifier, nothing without access, and Create world still needs world.create", async () => {
        const server = installMockServer()
        server.on(
            "GET",
            /^\/worlds\?/,
            page([
                world("w-secret-id-1", "Visible", { capabilities: ["world.view"] }),
                archivedWorld("w-secret-id-2", "Opaque", { capabilities: [] }),
            ]),
        )
        render({
            entry: "/worlds?status=archived",
            bootstrap: bootstrapWith({ global_capabilities: [], campaigns: [] }),
        })
        await screen.findByRole("link", { name: "Visible" })
        expect(screen.queryByText("Opaque")).not.toBeInTheDocument()
        expect(document.body.textContent).not.toContain("w-secret-id")
        expect(screen.queryByRole("link", { name: "Create world" })).not.toBeInTheDocument()
    })

    it("F14: Create world is offered with world.create in the checked state", async () => {
        installMockServer().on("GET", /^\/worlds\?/, page([]))
        render({ entry: "/worlds?archived=1" })
        expect(await screen.findByRole("link", { name: "Create world" })).toHaveAttribute("href", "/worlds/new")
    })
})

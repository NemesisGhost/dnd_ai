import { fireEvent, screen, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import { ReviewQueuePage, RevisionHistoryPage } from "./ReviewPages"

const QUEUE = "/campaigns/c1/review-queue"
const REVISIONS = "/campaigns/c1/entities/e1/revisions"

const row = (id: string, name: string, overrides: object = {}) => ({
    entity_id: id,
    name,
    entity_type_code: "settlement",
    category: "location",
    canon_status: "proposed",
    lifecycle_status: "active",
    row_version: 2,
    updated_at: "2026-01-02T10:00:00Z",
    last_change_by: "Gina",
    last_change_by_me: false,
    ...overrides,
})

const STATUSES = [
    { value: "pending", label: "Needs attention" },
    { value: "draft", label: "Drafts" },
    { value: "in_review", label: "In review" },
    { value: "approved", label: "Approved, not yet published" },
    { value: "rejected", label: "Rejected" },
    { value: "archived", label: "Archived" },
]

function page(items: object[], next: string | null = null, status = "in_review") {
    return {
        items,
        next_cursor: next,
        status,
        statuses: STATUSES,
        types: ["settlement", "quest", "knowledge_item", "item_instance"],
        counts: { draft: 2, in_review: 1, approved: 3, rejected: 4, archived: 0 },
    }
}

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("ReviewQueuePage", () => {
    function setup(capabilities = ["canon.edit"], entry = "/app/c1/review") {
        const server = installMockServer()
        server.on("GET", `${QUEUE}?status=in_review`, () => ({
            body: page(
                [
                    row("e1", "Stonebridge", { last_change_by_me: true }),
                    row("e2", "Dead Duke's Claim", { category: null, entity_type_code: "knowledge_item" }),
                    row("e3", "Find the Duke", { category: null, entity_type_code: "quest" }),
                    row("e4", "Sunblade", { category: "item", entity_type_code: "item_instance" }),
                ],
                "CUR1",
            ),
        }))
        server.on("GET", `${QUEUE}?status=in_review&cursor=CUR1`, { body: page([row("e5", "Third Town")]) })
        server.on("GET", `${QUEUE}?status=draft`, {
            body: page([row("e6", "Old Mill", { canon_status: "draft" })], null, "draft"),
        })
        server.on("GET", `${QUEUE}?status=pending`, { body: page([row("e6", "Old Mill", { canon_status: "draft" })], null, "pending") })
        server.on("GET", `${QUEUE}?status=in_review&type=quest`, { body: page([]) })
        server.on("GET", `${QUEUE}?status=approved`, { body: page([], null, "approved") })
        const view = renderAuthoringRoutes({
            initialEntry: entry,
            bootstrap: bootstrapWith({
                campaigns: [{ ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c1", capabilities }],
            }),
            routes: [{ path: "/app/:campaignId/review", element: <ReviewQueuePage /> }],
        })
        return { server, ...view }
    }

    it("opens on In review and says so in the address", async () => {
        const { server, router } = setup()
        expect(await screen.findByRole("heading", { level: 1, name: "Review queue" })).toBeInTheDocument()
        await screen.findByRole("link", { name: "Stonebridge" })
        expect(server.callsTo("GET", `${QUEUE}?status=in_review`)).toHaveLength(1)
        expect(router.state.location.search).toBe("?status=in_review")
        expect(screen.getByRole("combobox", { name: "Show" })).toHaveValue("in_review")
    })

    it("corrects an unknown status without adding a history entry", async () => {
        const { router } = setup(["canon.edit"], "/app/c1/review?status=bogus")
        await screen.findByRole("link", { name: "Stonebridge" })
        expect(router.state.location.search).toBe("?status=in_review")
        expect(router.state.historyAction).toBe("REPLACE")
    })

    it("links each row to its record's review section and says who changed it", async () => {
        setup()
        expect(await screen.findByRole("link", { name: "Stonebridge" })).toHaveAttribute(
            "href",
            "/app/c1/world/location/e1?section=review",
        )
        expect(screen.getByRole("link", { name: "Dead Duke's Claim" })).toHaveAttribute(
            "href",
            "/app/c1/knowledge/e2?section=review",
        )
        expect(screen.getByRole("link", { name: "Find the Duke" })).toHaveAttribute("href", "/app/c1/quests/e3?section=review")
        expect(screen.getByRole("link", { name: "Sunblade" })).toHaveAttribute(
            "href",
            "/app/c1/items/e4?section=publication",
        )
        expect(screen.getByRole("link", { name: "Review Stonebridge" })).toHaveAttribute(
            "href",
            "/app/c1/world/location/e1?section=review",
        )
        expect(screen.getAllByText(/Last changed .* by Gina/)).toHaveLength(4)
        expect(screen.getByText(/by Gina \(you\)\./)).toBeInTheDocument()
        expect(screen.getByRole("link", { name: "History of Find the Duke" })).toHaveAttribute(
            "href",
            "/app/c1/world/record/e3/history",
        )
        expect(screen.getByRole("link", { name: "History of Stonebridge" })).toHaveAttribute(
            "href",
            "/app/c1/world/location/e1/history",
        )
    })

    it("opens a draft at its details and carries the list it was left on", async () => {
        const { router } = setup(["canon.edit"], "/app/c1/review?status=draft")
        const link = await screen.findByRole("link", { name: "Old Mill" })
        expect(link).toHaveAttribute("href", "/app/c1/world/location/e6?section=details")
        expect(screen.getByRole("link", { name: "Open Old Mill" })).toBeInTheDocument()
        fireEvent.click(link)
        await vi.waitFor(() => expect(router.state.location.pathname).toBe("/app/c1/world/location/e6"))
        expect(router.state.location.state).toEqual({ reviewSearch: "?status=draft" })
    })

    it("shows the count of each status, in the order a reviewer works", async () => {
        setup()
        await screen.findByRole("link", { name: "Stonebridge" })
        const options = within(screen.getByRole("combobox", { name: "Show" }))
            .getAllByRole("option")
            .map((o) => o.textContent)
        expect(options).toEqual([
            "In review (1)",
            "Approved, not yet published (3)",
            "Needs attention (10)",
            "Drafts (2)",
            "Rejected (4)",
            "Archived (0)",
        ])
    })

    it("shows no counts while a kind is chosen, because they cover every kind", async () => {
        setup(["canon.edit"], "/app/c1/review?status=in_review&type=quest")
        await screen.findByText("No records match this filter.")
        const options = within(screen.getByRole("combobox", { name: "Show" }))
            .getAllByRole("option")
            .map((o) => o.textContent)
        expect(options[0]).toBe("In review")
        expect(options.join()).not.toMatch(/\(\d+\)/)
    })

    it("keeps the filters in the address so Back restores them", async () => {
        const { server, router } = setup()
        await screen.findByRole("link", { name: "Stonebridge" })
        fireEvent.change(screen.getByRole("combobox", { name: "Show" }), { target: { value: "draft" } })
        await vi.waitFor(() => expect(server.callsTo("GET", `${QUEUE}?status=draft`)).toHaveLength(1))
        expect(router.state.location.search).toBe("?status=draft")
        expect(screen.getByRole("combobox", { name: "Show" })).toHaveValue("draft")
        await router.navigate(-1)
        await vi.waitFor(() => expect(router.state.location.search).toBe("?status=in_review"))
        expect(await screen.findByRole("link", { name: "Stonebridge" })).toBeInTheDocument()
    })

    it("filters by kind and offers to show every kind when none match", async () => {
        const { router } = setup()
        await screen.findByRole("link", { name: "Stonebridge" })
        fireEvent.change(screen.getByRole("combobox", { name: "Kind of record" }), { target: { value: "quest" } })
        expect(await screen.findByText("No records match this filter.")).toBeInTheDocument()
        expect(router.state.location.search).toBe("?status=in_review&type=quest")
        fireEvent.click(screen.getByRole("button", { name: "Show all kinds" }))
        expect(await screen.findByRole("link", { name: "Stonebridge" })).toBeInTheDocument()
        expect(router.state.location.search).toBe("?status=in_review")
    })

    it("explains an empty queue without inventing a count", async () => {
        setup(["canon.edit"], "/app/c1/review?status=approved")
        expect(await screen.findByText("Nothing is approved and waiting to be published.")).toBeInTheDocument()
    })

    it("loads the next page", async () => {
        const { server } = setup()
        fireEvent.click(await screen.findByRole("button", { name: "Load more" }))
        expect(await screen.findByRole("link", { name: "Third Town" })).toBeInTheDocument()
        expect(server.callsTo("GET", `${QUEUE}?status=in_review&cursor=CUR1`)).toHaveLength(1)
        expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument()
    })

    it("offers Try again when the queue cannot be loaded", async () => {
        const server = installMockServer()
        let attempts = 0
        server.on("GET", `${QUEUE}?status=in_review`, () => {
            attempts += 1
            return attempts === 1 ? { status: 500, body: {} } : { body: page([row("e1", "Stonebridge")]) }
        })
        renderAuthoringRoutes({
            initialEntry: "/app/c1/review",
            bootstrap: bootstrapWith({
                campaigns: [{ ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c1", capabilities: ["canon.edit"] }],
            }),
            routes: [{ path: "/app/:campaignId/review", element: <ReviewQueuePage /> }],
        })
        expect(await screen.findByText("The review queue could not be loaded.")).toBeInTheDocument()
        fireEvent.click(screen.getByRole("button", { name: "Try again" }))
        expect(await screen.findByRole("link", { name: "Stonebridge" })).toBeInTheDocument()
    })

    it("sends the queue to every History link, whatever the kind of record", async () => {
        const { router } = setup(["canon.edit"], "/app/c1/review?status=in_review")
        for (const name of ["Stonebridge", "Dead Duke's Claim", "Find the Duke", "Sunblade"]) {
            await router.navigate("/app/c1/review?status=in_review")
            fireEvent.click(await screen.findByRole("link", { name: `History of ${name}` }))
            await vi.waitFor(() => expect(router.state.location.pathname).toMatch(/\/history$/))
            expect(router.state.location.state).toEqual({ reviewSearch: "?status=in_review" })
        }
    })

    it("writes NPC as an acronym in the kind filter and on the row", async () => {
        const server = installMockServer()
        server.on("GET", `${QUEUE}?status=in_review`, {
            body: {
                ...page([row("e9", "Harbormaster", { category: "character", entity_type_code: "npc" })]),
                types: ["npc", "dungeon_area"],
            },
        })
        renderAuthoringRoutes({
            initialEntry: "/app/c1/review",
            bootstrap: bootstrapWith({
                campaigns: [{ ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c1", capabilities: ["canon.edit"] }],
            }),
            routes: [{ path: "/app/:campaignId/review", element: <ReviewQueuePage /> }],
        })
        expect(await screen.findByText(/\(NPC\)/)).toBeInTheDocument()
        const kinds = within(screen.getByRole("combobox", { name: "Kind of record" }))
            .getAllByRole("option")
            .map((o) => o.textContent)
        expect(kinds).toEqual(["All kinds", "NPC", "Dungeon Area"])
    })

    it("refuses people without canon.edit and sends no request", async () => {
        const { server } = setup([])
        expect(await screen.findByRole("alert")).toHaveTextContent(/do not have permission/)
        expect(server.calls).toHaveLength(0)
    })
})

describe("RevisionHistoryPage", () => {
    const history = {
        entity_id: "e1",
        name: "Stonebridge",
        entity_type_code: "settlement",
        canon_status: "proposed",
        lifecycle_status: "active",
        row_version: 3,
        revisions: [
            { row_version: 3, kind: "lifecycle", created_at: "2026-01-03T10:00:00Z", created_by_name: "Gina", canon_status: "proposed", lifecycle_status: "active" },
            { row_version: 2, kind: "updated", created_at: "2026-01-02T10:00:00Z", created_by_name: "Gina", canon_status: null, lifecycle_status: null },
            { row_version: 1, kind: "created", created_at: "2026-01-01T10:00:00Z", created_by_name: "Gina", canon_status: null, lifecycle_status: null },
        ],
    }

    function setup(
        view: object = history,
        capabilities = ["canon.edit"],
        entry: string | { pathname: string; search?: string; state?: unknown } = "/app/c1/world/location/e1/history",
    ) {
        const server = installMockServer()
        server.on("GET", REVISIONS, { body: view })
        server.on("GET", `${REVISIONS}/compare?from=2&to=3`, {
            body: {
                entity_id: "e1",
                name: "Stonebridge",
                from_version: 2,
                to_version: 3,
                from_authored_version: 2,
                to_authored_version: 2,
                changes: [],
            },
        })
        server.on("GET", `${REVISIONS}/compare?from=1&to=3`, {
            body: {
                entity_id: "e1",
                name: "Stonebridge",
                from_version: 1,
                to_version: 3,
                from_authored_version: 1,
                to_authored_version: 2,
                changes: [
                    { path: "summary", kind: "added", before: null, after: "A river town", truncated: false },
                    { path: "name", kind: "changed", before: "Stonebrige", after: "Stonebridge", truncated: false },
                    { path: "tags[1]", kind: "removed", before: "old", after: null, truncated: false },
                    { path: "notes", kind: "changed", before: "a", after: "long…", truncated: true },
                ],
            },
        })
        const view2 = renderAuthoringRoutes({
            initialEntry: entry,
            bootstrap: bootstrapWith({
                campaigns: [{ ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c1", capabilities }],
            }),
            routes: [{ path: "/app/:campaignId/world/:category/:entityId/history", element: <RevisionHistoryPage /> }],
        })
        return { server, ...view2 }
    }

    it("lists every revision with what it was and who made it", async () => {
        setup()
        const list = await screen.findByRole("list", { name: "Revisions" })
        const items = within(list).getAllByRole("listitem").map((i) => i.textContent)
        expect(items[0]).toMatch(/Version 3: Status proposed, .* by Gina/)
        expect(items[1]).toMatch(/Version 2: Edited/)
        expect(items[2]).toMatch(/Version 1: Created/)
    })

    it("compares two versions as a table of differences and records the choice in the address", async () => {
        const { server, router } = setup()
        const form = await screen.findByRole("form", { name: "Compare two versions" })
        fireEvent.change(within(form).getByRole("combobox", { name: "Compare" }), { target: { value: "1" } })
        fireEvent.click(within(form).getByRole("button", { name: "Compare versions" }))
        const table = await screen.findByRole("table", { name: /4 differences in the authored fields/ })
        expect(server.callsTo("GET", `${REVISIONS}/compare?from=1&to=3`)).toHaveLength(1)
        expect(router.state.location.search).toBe("?from=1&to=3")
        const rows = within(table)
            .getAllByRole("row")
            .slice(1)
            .map((r) => Array.from(r.children).map((c) => c.textContent))
        expect(rows).toEqual([
            ["summary", "Added", "(none)", "A river town"],
            ["name", "Changed", "Stonebrige", "Stonebridge"],
            ["tags[1]", "Removed", "old", "(none)"],
            ["notes", "Changed", "a", "long… (cut short)"],
        ])
    })

    it("opens a linked comparison and preselects its versions", async () => {
        const { server } = setup(history, ["canon.edit"], "/app/c1/world/location/e1/history?from=1&to=3")
        expect(await screen.findByRole("table", { name: /4 differences/ })).toBeInTheDocument()
        expect(server.callsTo("GET", `${REVISIONS}/compare?from=1&to=3`)).toHaveLength(1)
        expect(screen.getByRole("combobox", { name: "Compare" })).toHaveValue("1")
        expect(screen.getByRole("combobox", { name: "With" })).toHaveValue("3")
    })

    it("ignores versions that are not versions of this record", async () => {
        const { server } = setup(history, ["canon.edit"], "/app/c1/world/location/e1/history?from=1&to=9")
        await screen.findByRole("form", { name: "Compare two versions" })
        expect(screen.queryByText(/compared with version/)).not.toBeInTheDocument()
        expect(server.calls.filter((c) => c.path.includes("compare"))).toHaveLength(0)
    })

    it("says when two versions do not differ", async () => {
        setup()
        const form = await screen.findByRole("form", { name: "Compare two versions" })
        fireEvent.click(within(form).getByRole("button", { name: "Compare versions" }))
        expect(await screen.findByText(/No differences in the authored fields/)).toBeInTheDocument()
    })

    it("has nothing to compare for a record with one version", async () => {
        setup({ ...history, revisions: [history.revisions[2]] })
        expect(await screen.findByText(/only one version/)).toBeInTheDocument()
        expect(screen.queryByRole("form", { name: "Compare two versions" })).not.toBeInTheDocument()
    })

    it("leads back to the review queue it came from and to the record", async () => {
        setup()
        expect(await screen.findByRole("link", { name: "Review queue" })).toHaveAttribute("href", "/app/c1/review")
        expect(screen.getByRole("link", { name: "Stonebridge" })).toHaveAttribute("href", "/app/c1/world/location/e1")
    })

    it("keeps the queue it came from through a comparison, and into the record", async () => {
        const state = { reviewSearch: "?status=approved&type=npc" }
        const { router } = setup(history, ["canon.edit"], { pathname: "/app/c1/world/location/e1/history", state })
        expect(await screen.findByRole("link", { name: "Review queue" })).toHaveAttribute(
            "href",
            "/app/c1/review?status=approved&type=npc",
        )
        fireEvent.click(screen.getByRole("button", { name: "Compare versions" }))
        await screen.findByText(/No differences in the authored fields/)
        expect(router.state.location.state).toEqual(state)
        expect(screen.getByRole("link", { name: "Review queue" })).toHaveAttribute(
            "href",
            "/app/c1/review?status=approved&type=npc",
        )
        fireEvent.click(screen.getByRole("link", { name: "Stonebridge" }))
        await vi.waitFor(() => expect(router.state.location.pathname).toBe("/app/c1/world/location/e1"))
        expect(router.state.location.state).toEqual(state)
    })

    it("ignores a crafted return state", async () => {
        setup(history, ["canon.edit"], { pathname: "/app/c1/world/location/e1/history", state: { reviewSearch: "//evil.example" } })
        expect(await screen.findByRole("link", { name: "Review queue" })).toHaveAttribute("href", "/app/c1/review")
    })

    it("links a quest's history back to the quest, which has no World page", async () => {
        setup({ ...history, entity_type_code: "quest", name: "Find the Duke" }, ["canon.edit"], "/app/c1/world/record/e1/history")
        expect(await screen.findByRole("link", { name: "Find the Duke" })).toHaveAttribute("href", "/app/c1/quests/e1")
    })

    it("links a knowledge claim's history back to the claim", async () => {
        setup({ ...history, entity_type_code: "knowledge_item", name: "A claim" }, ["canon.edit"], "/app/c1/world/record/e1/history")
        expect(await screen.findByRole("link", { name: "A claim" })).toHaveAttribute("href", "/app/c1/knowledge/e1")
    })

    it("refuses people without canon.edit and sends no request", async () => {
        const { server } = setup(history, [])
        expect(await screen.findByRole("alert")).toHaveTextContent(/do not have permission/)
        expect(server.calls).toHaveLength(0)
    })
})

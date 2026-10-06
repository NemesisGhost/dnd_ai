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
    canon_status: "draft",
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
    { value: "archived", label: "Archived" },
]

function page(items: object[], next: string | null = null) {
    return {
        items,
        next_cursor: next,
        status: "pending",
        statuses: STATUSES,
        types: ["settlement", "quest"],
        counts: { draft: 2, in_review: 1, archived: 0 },
    }
}

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("ReviewQueuePage", () => {
    function setup(capabilities = ["canon.edit"]) {
        const server = installMockServer()
        server.on("GET", `${QUEUE}?status=pending`, () => ({
            body: page([row("e1", "Stonebridge", { last_change_by_me: true }), row("e2", "Quest", { category: null, entity_type_code: "quest", canon_status: "proposed" })], "CUR1"),
        }))
        server.on("GET", `${QUEUE}?status=pending&cursor=CUR1`, { body: page([row("e3", "Third Town")]) })
        server.on("GET", `${QUEUE}?status=draft`, { body: { ...page([row("e1", "Stonebridge")]), status: "draft" } })
        server.on("GET", `${QUEUE}?status=pending&type=quest`, { body: page([]) })
        renderAuthoringRoutes({
            initialEntry: "/app/c1/review",
            bootstrap: bootstrapWith({
                campaigns: [{ ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c1", capabilities }],
            }),
            routes: [{ path: "/app/:campaignId/review", element: <ReviewQueuePage /> }],
        })
        return server
    }

    it("lists records with their state, who changed them, and links", async () => {
        setup()
        expect(await screen.findByRole("link", { name: "Stonebridge" })).toHaveAttribute(
            "href",
            "/app/c1/world/location/e1",
        )
        expect(screen.getByText(/Changed .* by Gina \(you\)\./)).toBeInTheDocument()
        expect(screen.getByRole("link", { name: "History of Quest" })).toHaveAttribute(
            "href",
            "/app/c1/world/record/e2/history",
        )
        expect(screen.getByText("Quest", { selector: "strong" })).toBeInTheDocument()
    })

    it("shows the count of each status in the filter", async () => {
        setup()
        await screen.findByRole("link", { name: "Stonebridge" })
        const options = within(screen.getByRole("combobox", { name: "Show" })).getAllByRole("option").map((o) => o.textContent)
        expect(options).toEqual(["Needs attention", "Drafts (2)", "In review (1)", "Archived (0)"])
    })

    it("changes the filter and keeps the form while the new list loads", async () => {
        const server = setup()
        await screen.findByRole("link", { name: "Stonebridge" })
        fireEvent.change(screen.getByRole("combobox", { name: "Show" }), { target: { value: "draft" } })
        await vi.waitFor(() => expect(server.callsTo("GET", `${QUEUE}?status=draft`)).toHaveLength(1))
        expect(screen.getByRole("combobox", { name: "Show" })).toHaveValue("draft")
        fireEvent.change(screen.getByRole("combobox", { name: "Show" }), { target: { value: "pending" } })
        fireEvent.change(screen.getByRole("combobox", { name: "Kind of record" }), { target: { value: "quest" } })
        expect(await screen.findByText("Nothing here.")).toBeInTheDocument()
    })

    it("loads the next page", async () => {
        const server = setup()
        fireEvent.click(await screen.findByRole("button", { name: "Load more" }))
        expect(await screen.findByRole("link", { name: "Third Town" })).toBeInTheDocument()
        expect(server.callsTo("GET", `${QUEUE}?status=pending&cursor=CUR1`)).toHaveLength(1)
        expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument()
    })

    it("refuses people without canon.edit", async () => {
        setup([])
        expect(await screen.findByRole("alert")).toHaveTextContent(/do not have permission/)
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

    function setup(view: object = history, capabilities = ["canon.edit"]) {
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
        renderAuthoringRoutes({
            initialEntry: "/app/c1/world/location/e1/history",
            bootstrap: bootstrapWith({
                campaigns: [{ ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c1", capabilities }],
            }),
            routes: [{ path: "/app/:campaignId/world/:category/:entityId/history", element: <RevisionHistoryPage /> }],
        })
        return server
    }

    it("lists every revision with what it was and who made it", async () => {
        setup()
        const list = await screen.findByRole("list", { name: "Revisions" })
        const items = within(list).getAllByRole("listitem").map((i) => i.textContent)
        expect(items[0]).toMatch(/Version 3: Status proposed, .* by Gina/)
        expect(items[1]).toMatch(/Version 2: Edited/)
        expect(items[2]).toMatch(/Version 1: Created/)
    })

    it("compares two versions as a table of differences", async () => {
        const server = setup()
        const form = await screen.findByRole("form", { name: "Compare two versions" })
        fireEvent.change(within(form).getByRole("combobox", { name: "Compare" }), { target: { value: "1" } })
        fireEvent.click(within(form).getByRole("button", { name: "Compare versions" }))
        const table = await screen.findByRole("table", { name: /4 differences in the authored fields/ })
        expect(server.callsTo("GET", `${REVISIONS}/compare?from=1&to=3`)).toHaveLength(1)
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

    it("refuses people without canon.edit", async () => {
        setup(history, [])
        expect(await screen.findByRole("alert")).toHaveTextContent(/do not have permission/)
    })
})

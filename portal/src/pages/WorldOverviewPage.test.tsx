import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { TEST_CSRF, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import type { WorldDetail } from "../types/worldAuthoring"
import { WorldOverviewPage } from "./WorldOverviewPage"

function worldDetail(overrides: Partial<WorldDetail> = {}): WorldDetail {
    return {
        world_id: "w1",
        name: "Eberron",
        description: "A world of intrigue",
        lifecycle_status: "active",
        row_version: 3,
        primary_timeline_id: "t1",
        capabilities: ["world.manage"],
        default_ruleset_id: "r1",
        allowed_rulesets: [
            {
                ruleset_id: "r1",
                code: "dnd5e",
                display_name: "D&D 5e (2024)",
                is_default: true,
                current_version: { ruleset_version_id: "rv1", version_label: "2024" },
            },
        ],
        timelines: [
            {
                timeline_id: "t1",
                name: "Main Timeline",
                description: null,
                is_primary: true,
                parent_timeline_id: null,
                branch_point: null,
                lifecycle_status: "active",
                row_version: 1,
            },
            {
                timeline_id: "t2",
                name: "Bridge Branch",
                description: null,
                is_primary: false,
                parent_timeline_id: "t1",
                branch_point: { world_time_id: "wt1", label: "The Night the Bridge Fell", sort_key: 0 },
                lifecycle_status: "active",
                row_version: 1,
            },
        ],
        managed_campaigns: [
            { campaign_id: "c1", name: "Skyfall", lifecycle_status: "active", timeline_id: "t1" },
            { campaign_id: "c2", name: "Old Run", lifecycle_status: "archived", timeline_id: "t1" },
        ],
        available_actions: ["update", "archive", "create_timeline", "create_campaign"],
        blocked_actions: [{ action: "restore", reason: "lifecycle_transition_not_allowed" }],
        ...overrides,
    }
}

function setup(detail: WorldDetail) {
    const server = installMockServer()
    server.on("GET", "/worlds/w1", () => ({ body: detail }))
    const rendered = renderAuthoringRoutes({
        initialEntry: "/worlds/w1",
        routes: [
            { path: "/worlds/:worldId", element: <WorldOverviewPage /> },
            { path: "/worlds", element: <p>Worlds list page</p> },
        ],
    })
    return { server, ...rendered }
}

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("WorldOverviewPage", () => {
    it("renders the details, rulesets, lineage, and managed campaigns without raw identifiers", async () => {
        setup(worldDetail())
        expect(await screen.findByRole("heading", { level: 1, name: "Eberron" })).toBeInTheDocument()
        expect(screen.getByText("A world of intrigue")).toBeInTheDocument()
        expect(screen.getByText(/D&D 5e \(2024\) \(default\) — 2024/)).toBeInTheDocument()
        expect(screen.getByRole("link", { name: "Main Timeline" })).toHaveAttribute(
            "href",
            "/worlds/w1/timelines/t1",
        )
        expect(screen.getByText(/branched at The Night the Bridge Fell/)).toBeInTheDocument()
        expect(screen.getByRole("link", { name: "Skyfall" })).toHaveAttribute("href", "/app/c1/home")
        expect(screen.queryByRole("link", { name: "Old Run" })).not.toBeInTheDocument()
        expect(document.body.textContent).not.toMatch(/\bw1\b|\bt1\b|\bc1\b/)
    })

    it("offers only the actions the server reports as available", async () => {
        setup(worldDetail())
        await screen.findByRole("heading", { level: 1, name: "Eberron" })
        expect(screen.getByRole("link", { name: "Edit world" })).toHaveAttribute("href", "/worlds/w1/edit")
        expect(screen.getByRole("link", { name: "New timeline" })).toBeInTheDocument()
        expect(screen.getByRole("link", { name: "New campaign" })).toHaveAttribute(
            "href",
            "/campaigns/new?worldId=w1&timelineId=t1",
        )
        expect(screen.getByRole("button", { name: "Archive world" })).toBeInTheDocument()
        expect(screen.queryByRole("button", { name: "Restore world" })).not.toBeInTheDocument()
    })

    it("explains a blocked action with the server's reason instead of hiding it", async () => {
        setup(
            worldDetail({
                available_actions: ["update", "create_timeline", "create_campaign"],
                blocked_actions: [
                    { action: "archive", reason: "world_has_active_campaigns" },
                    { action: "restore", reason: "lifecycle_transition_not_allowed" },
                ],
            }),
        )
        await screen.findByRole("heading", { level: 1, name: "Eberron" })
        const note = screen.getByRole("list", { name: "Unavailable actions" })
        expect(note).toHaveTextContent("archive unavailable: The world still has active campaigns")
        expect(note).not.toHaveTextContent("restore")
        expect(screen.queryByRole("button", { name: "Archive world" })).not.toBeInTheDocument()
    })

    it("shows an archived world with a badge and only Restore", async () => {
        setup(
            worldDetail({
                lifecycle_status: "archived",
                available_actions: ["restore"],
                blocked_actions: [{ action: "update", reason: "world_archived" }],
            }),
        )
        await screen.findByRole("heading", { level: 1, name: "Eberron" })
        // The world's own badge plus the archived campaign in the list.
        expect(screen.getAllByText("Archived", { selector: "span.authoring-badge" })).toHaveLength(2)
        expect(screen.getByRole("button", { name: "Restore world" })).toBeInTheDocument()
        expect(screen.queryByRole("link", { name: "Edit world" })).not.toBeInTheDocument()
    })

    it("archives through a confirmation, refetches authoritatively, then announces", async () => {
        const { server } = setup(worldDetail())
        let archived = false
        server.on("GET", "/worlds/w1", () => ({
            body: archived
                ? worldDetail({
                      lifecycle_status: "archived",
                      row_version: 4,
                      available_actions: ["restore"],
                      blocked_actions: [],
                  })
                : worldDetail(),
        }))
        server.on("POST", "/worlds/w1/archive", () => {
            archived = true
            return { body: { world_id: "w1", lifecycle_status: "archived", row_version: 4 } }
        })
        await screen.findByRole("heading", { level: 1, name: "Eberron" })

        fireEvent.click(screen.getByRole("button", { name: "Archive world" }))
        const dialog = screen.getByRole("dialog", { name: "Archive this world?", hidden: true })
        fireEvent.change(within(dialog).getByRole("textbox", { name: /Reason/ }), {
            target: { value: "season over" },
        })
        fireEvent.click(within(dialog).getByRole("button", { name: "Archive world" }))

        await waitFor(
            () => expect(screen.getByRole("button", { name: "Restore world" })).toBeInTheDocument(),
            { timeout: 4000 },
        )
        const [post] = server.callsTo("POST", "/worlds/w1/archive")
        expect(post!.headers["X-CSRF-Token"]).toBe(TEST_CSRF)
        expect(post!.body).toEqual({ expected_row_version: 3, reason: "season over" })
        expect(screen.getByTestId("authoring-announcer")).toHaveTextContent("World archived")
        expect(screen.queryByRole("dialog", { hidden: false })).not.toBeInTheDocument()
    })

    it("keeps a failed archive inside the dialog with a recoverable message", async () => {
        const { server } = setup(worldDetail())
        server.on("POST", "/worlds/w1/archive", {
            status: 409,
            body: { error: { code: "world_has_active_campaigns", message: "m", correlation_id: "c" } },
        })
        await screen.findByRole("heading", { level: 1, name: "Eberron" })
        fireEvent.click(screen.getByRole("button", { name: "Archive world" }))
        const dialog = screen.getByRole("dialog", { hidden: true })
        fireEvent.click(within(dialog).getByRole("button", { name: "Archive world" }))
        expect(await within(dialog).findByRole("alert")).toHaveTextContent("still has active campaigns")
        expect(screen.getByRole("heading", { level: 1, name: "Eberron" })).toBeInTheDocument()
    })

    it("offers a reload when the archive hits a stale version", async () => {
        const { server } = setup(worldDetail())
        server.on("POST", "/worlds/w1/archive", {
            status: 409,
            body: { error: { code: "stale_write", message: "m", correlation_id: "c" } },
        })
        await screen.findByRole("heading", { level: 1, name: "Eberron" })
        fireEvent.click(screen.getByRole("button", { name: "Archive world" }))
        fireEvent.click(within(screen.getByRole("dialog", { hidden: true })).getByRole("button", { name: "Archive world" }))
        expect(await screen.findByRole("button", { name: "Load latest version" })).toBeInTheDocument()
    })

    it("restores through a confirmation", async () => {
        const { server } = setup(
            worldDetail({ lifecycle_status: "archived", available_actions: ["restore"], blocked_actions: [] }),
        )
        server.on("POST", "/worlds/w1/restore", {
            body: { world_id: "w1", lifecycle_status: "active", row_version: 4 },
        })
        await screen.findByRole("heading", { level: 1, name: "Eberron" })
        fireEvent.click(screen.getByRole("button", { name: "Restore world" }))
        const dialog = screen.getByRole("dialog", { name: "Restore this world?", hidden: true })
        fireEvent.click(within(dialog).getByRole("button", { name: "Restore world" }))
        await waitFor(() => expect(server.callsTo("POST", "/worlds/w1/restore")).toHaveLength(1))
    })

    it("shows a non-disclosing unavailable state for a missing or inaccessible world", async () => {
        const server = installMockServer()
        server.on("GET", "/worlds/w1", { status: 404 })
        renderAuthoringRoutes({
            initialEntry: "/worlds/w1",
            routes: [{ path: "/worlds/:worldId", element: <WorldOverviewPage /> }],
        })
        expect(await screen.findByRole("heading", { level: 1, name: "World not available" })).toBeInTheDocument()
        expect(screen.getByRole("alert")).toHaveTextContent("does not exist, or you do not have access")
        expect(screen.getByRole("link", { name: "Back to your worlds" })).toHaveAttribute("href", "/worlds")
    })

    it("omits Edit world when the server does not report update", async () => {
        setup(worldDetail({ available_actions: ["create_timeline"] }))
        await screen.findByRole("heading", { level: 1, name: "Eberron" })
        expect(screen.queryByRole("link", { name: "Edit world" })).not.toBeInTheDocument()
        expect(screen.getByRole("link", { name: "New timeline" })).toBeInTheDocument()
    })

    it("renders a view-only world read-only, with no authoring controls or destinations", async () => {
        // Even if a response carried actions, a world without world.manage is
        // presented read-only.
        setup(
            worldDetail({
                capabilities: ["world.view"],
                available_actions: [],
                blocked_actions: [],
            }),
        )
        await screen.findByRole("heading", { level: 1, name: "Eberron" })
        expect(screen.getByText("View only")).toBeInTheDocument()
        expect(screen.getByText("A world of intrigue")).toBeInTheDocument()
        expect(screen.getByText("Main Timeline")).toBeInTheDocument()
        for (const name of ["Edit world", "New timeline", "New calendar", "New campaign"]) {
            expect(screen.queryByRole("link", { name })).not.toBeInTheDocument()
        }
        for (const name of ["Archive world", "Restore world"]) {
            expect(screen.queryByRole("button", { name })).not.toBeInTheDocument()
        }
        // Timelines are names, not links into timeline authoring; managed
        // campaigns are not listed.
        expect(screen.queryByRole("link", { name: "Main Timeline" })).not.toBeInTheDocument()
        expect(screen.queryByText("Skyfall")).not.toBeInTheDocument()
        const links = screen.getAllByRole("link").map((link) => link.getAttribute("href"))
        expect(links).toEqual(["/worlds"])
    })

    it("keeps a view-only world read-only even if the server listed actions", async () => {
        setup(worldDetail({ capabilities: ["world.view"] }))
        await screen.findByRole("heading", { level: 1, name: "Eberron" })
        expect(screen.queryByRole("link", { name: "Edit world" })).not.toBeInTheDocument()
        expect(screen.queryByRole("button", { name: "Archive world" })).not.toBeInTheDocument()
        expect(screen.queryByRole("link", { name: "New campaign" })).not.toBeInTheDocument()
    })
})

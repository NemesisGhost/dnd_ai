import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../../fixtures/sessionBootstrap"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../../test/authoringHarness"
import type { MockServer } from "../../test/authoringHarness"
import { installRecordReads } from "../../test/worldWorkspaceMocks"
import type { RevisionFixture } from "../../test/worldWorkspaceMocks"
import { CampaignWorldDetailPage } from "../../pages/CampaignWorldDetailPage"

const C = "c1"
const NOT_FOUND = { status: 404, body: { error: { code: "not_found", message: "m", correlation_id: "x" } } }

const lifecycle = (over: object = {}) => ({
    entity_id: "l1",
    entity_type_code: "building",
    canonical_name: "Old Mill",
    canon_status: "draft",
    lifecycle_status: "active",
    row_version: 2,
    lifecycle_managed: true,
    superseded_by: null,
    available_actions: ["submit_for_review", "archive"],
    blocked_actions: [],
    ...over,
})

const locationDetail = (over: object = {}) => ({
    location_id: "l1",
    name: "Old Mill",
    summary: "A quiet mill.",
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
    ...over,
})

const organizationDetail = {
    organization_id: "o1",
    name: "The Guild",
    summary: "Merchants.",
    kind_code: "business",
    organization_type_code: "guild",
    status_code: null,
    public_description: null,
    parent: null,
    headquarters: null,
    religion: null,
}

const characterDetail = (name = "Mira") => ({
    character_id: "n1",
    name,
    species_code: "human",
    size_category: "medium",
    current_hit_points: null,
    maximum_hit_points: null,
    temporary_hit_points: null,
    exhaustion_level: null,
    death_save_successes: null,
    death_save_failures: null,
    current_location_id: null,
    active_encounter_id: null,
    conditions: null,
    resources: null,
})

type Handler = object | (() => object)

interface Options {
    entry?: string | { pathname: string; search?: string; state?: unknown }
    capabilities?: string[]
    entityId?: string
    category?: string
    detailPath?: string
    detail?: Handler
    lifecycle?: Handler
    typeCode?: string
    canon?: string
    revisions?: RevisionFixture[]
    editView?: object
    extra?: (server: MockServer) => void
}

const resolve = (value: Handler) => () => ({ body: typeof value === "function" ? value() : value })

function setup(options: Options = {}) {
    const entityId = options.entityId ?? "l1"
    const category = options.category ?? "location"
    const server = installMockServer()
    // Anything not named below is not found, like an authoring read for the other kind of record.
    server.on("GET", /.*/, NOT_FOUND)
    installRecordReads(server, {
        campaignId: C,
        entityId,
        entityTypeCode: options.typeCode ?? "building",
        canon: options.canon ?? "draft",
        revisions: options.revisions,
    })
    server.on("GET", options.detailPath ?? `/campaigns/${C}/world/locations/${entityId}`, resolve(options.detail ?? locationDetail()))
    server.on("GET", `/campaigns/${C}/entities/${entityId}/lifecycle`, resolve(options.lifecycle ?? lifecycle()))
    server.on(
        "GET",
        `/campaigns/${C}/authoring/locations/${entityId}`,
        { body: options.editView ?? { available_actions: ["update"], blocked_actions: [] } },
    )
    options.extra?.(server)
    const rendered = renderAuthoringRoutes({
        initialEntry: options.entry ?? `/app/${C}/world/${category}/${entityId}`,
        bootstrap: bootstrapWith({
            campaigns: [
                {
                    ...sessionBootstrapFixture.campaigns[0]!,
                    campaign_id: C,
                    capabilities: options.capabilities ?? ["canon.edit", "campaign.view"],
                },
            ],
        }),
        routes: [
            { path: "/app/:campaignId/world/:category/:entityId", element: <CampaignWorldDetailPage /> },
            { path: "/app/:campaignId/world/:category/:entityId/history", element: <p>History page</p> },
            { path: "/app/:campaignId/world/location/:entityId/edit", element: <p>Location edit page</p> },
            {
                path: "/app/:campaignId/world/dungeon/:dungeonId/areas/:areaId/edit",
                element: <p>Area edit page</p>,
            },
            { path: "/app/:campaignId/world/dungeon/:dungeonId/edit", element: <p>Dungeon edit page</p> },
            { path: "/app/:campaignId/review", element: <p>Review queue page</p> },
            { path: "/app/:campaignId/world", element: <p>World browser</p> },
        ],
    })
    return { server, ...rendered }
}

const writes = (server: MockServer) => server.calls.filter((c) => c.method !== "GET")
const stageLinks = () =>
    within(screen.getByRole("navigation", { name: "Record stages" }))
        .getAllByRole("link")
        .map((l) => l.textContent)
const sectionLinks = (stage: string) =>
    within(screen.getByRole("navigation", { name: `${stage} sections` }))
        .getAllByRole("link")
        .map((l) => l.textContent)

// The record's heading appears as soon as its details are read; the stages and sections only once its
// lifecycle has been read too, so a test that goes on to use them waits for both.
async function opened(name: string) {
    await screen.findByRole("heading", { level: 1, name })
    await screen.findByRole("navigation", { name: "Record stages" })
}

const shown = (text: string | RegExp) => waitFor(() => expect(screen.getByText(text)).toBeVisible())

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("World record workspace: a place", () => {
    it("gives an editor the workspace, opened at the details of a draft, with the reader's own panels", async () => {
        const { server } = setup()
        await opened("Old Mill")
        expect(stageLinks()).toEqual(["1. Prepare", "2. Review & publish"])
        expect(sectionLinks("Prepare")).toEqual(["Details", "Sources", "Relationships"])
        expect(screen.getByRole("heading", { level: 2, name: "Details" })).toBeVisible()
        expect(screen.getByRole("heading", { level: 2, name: "Overview" })).toBeVisible()
        expect(screen.getByRole("heading", { level: 2, name: "Containment" })).toBeVisible()
        expect(screen.getByRole("group", { name: "Record status" })).toHaveTextContent("Draft")
        expect(await screen.findByRole("link", { name: "Edit location" })).toHaveAttribute(
            "href",
            "/app/c1/world/location/l1/edit",
        )
        expect(writes(server)).toHaveLength(0)
    })

    it("puts the section in the address without adding a history entry", async () => {
        const { router } = setup()
        await opened("Old Mill")
        await waitFor(() => expect(router.state.location.search).toBe("?section=details"))
        expect(router.state.historyAction).toBe("REPLACE")
    })

    it("walks stages and sections with links that send no write and add history entries", async () => {
        const { server, router } = setup()
        await opened("Old Mill")
        fireEvent.click(screen.getByRole("link", { name: "Sources" }))
        await waitFor(() => expect(router.state.location.search).toBe("?section=sources"))
        expect(router.state.historyAction).toBe("PUSH")
        expect(screen.getByRole("heading", { level: 2, name: "Sources" })).toBeVisible()
        expect(screen.getByRole("link", { name: "Sources" })).toHaveAttribute("aria-current", "page")
        fireEvent.click(screen.getByRole("link", { name: "2. Review & publish" }))
        await screen.findByRole("heading", { level: 2, name: "Review" })
        expect(sectionLinks("Review & publish")).toEqual(["Review", "Publication"])
        fireEvent.click(screen.getByRole("link", { name: "Publication" }))
        await screen.findByRole("heading", { level: 2, name: "Publication" })
        expect(writes(server)).toHaveLength(0)
        await router.navigate(-1)
        await screen.findByRole("heading", { level: 2, name: "Review" })
    })

    it("moves focus to the section heading when the section changes", async () => {
        setup()
        await opened("Old Mill")
        fireEvent.click(screen.getByRole("link", { name: "Relationships" }))
        await waitFor(() => expect(screen.getByRole("heading", { level: 2, name: "Relationships" })).toHaveFocus())
    })

    it.each([
        ["draft", "details"],
        ["rejected", "details"],
        ["canon", "details"],
        ["proposed", "review"],
        ["approved", "review"],
    ])("opens a %s record at %s", async (canon, section) => {
        const { router } = setup({ lifecycle: lifecycle({ canon_status: canon, available_actions: [] }), canon })
        await opened("Old Mill")
        await waitFor(() => expect(router.state.location.search).toBe(`?section=${section}`))
    })

    it("opens an archived record at Publication", async () => {
        const { router } = setup({
            lifecycle: lifecycle({ canon_status: "canon", lifecycle_status: "archived", available_actions: ["restore"] }),
        })
        await opened("Old Mill")
        await waitFor(() => expect(router.state.location.search).toBe("?section=publication"))
        expect(screen.getByRole("group", { name: "Record status" })).toHaveTextContent("Archived")
    })

    it("honours a section named in the address and replaces an unknown one", async () => {
        const named = setup({ entry: "/app/c1/world/location/l1?section=publication" })
        await screen.findByRole("heading", { level: 2, name: "Publication" })
        expect(named.router.state.location.search).toBe("?section=publication")
        named.unmount()
        const unknown = setup({ entry: "/app/c1/world/location/l1?section=run" })
        await opened("Old Mill")
        await waitFor(() => expect(unknown.router.state.location.search).toBe("?section=details"))
    })

    it("names only the next step the server offers, as a link that does not act", async () => {
        const { server } = setup()
        const next = await screen.findByRole("link", { name: /Submit for review/ })
        expect(next.getAttribute("href")).toMatch(/\?section=publication$/)
        expect(next.closest(".item-header__next")).toHaveTextContent("Next:")
        expect(writes(server)).toHaveLength(0)
    })

    it("names no next step when the person is offered none", async () => {
        setup({ lifecycle: lifecycle({ canon_status: "proposed", available_actions: [] }) })
        await opened("Old Mill")
        expect(screen.queryByText(/Next:/)).not.toBeInTheDocument()
    })

    it("explains why editing is unavailable instead of offering it", async () => {
        setup({
            lifecycle: lifecycle({ canon_status: "proposed", available_actions: ["approve"] }),
            editView: {
                available_actions: [],
                blocked_actions: [{ action: "update", reason: "review_in_progress" }],
            },
            entry: "/app/c1/world/location/l1?section=details",
        })
        expect(await screen.findByText(/Editing unavailable/)).toBeInTheDocument()
        expect(screen.queryByRole("link", { name: "Edit location" })).not.toBeInTheDocument()
    })

    it("carries where it was opened from to the edit page, and back", async () => {
        const { router } = setup({
            entry: { pathname: "/app/c1/world/location/l1", search: "?section=details", state: { worldSearch: "?category=location" } },
        })
        fireEvent.click(await screen.findByRole("link", { name: "Edit location" }))
        await screen.findByText("Location edit page")
        expect(router.state.location.state).toEqual({
            worldSearch: "?category=location",
            returnTo: { pathname: "/app/c1/world/location/l1", search: "?section=details" },
        })
    })
})

describe("World record workspace: where it leads back to", () => {
    it("leads back to the World browser the record was opened from", async () => {
        setup({ entry: { pathname: "/app/c1/world/location/l1", state: { worldSearch: "?category=location&q=mill" } } })
        expect(await screen.findByRole("link", { name: "Back to World" })).toHaveAttribute(
            "href",
            "/app/c1/world?category=location&q=mill",
        )
    })

    it("leads back to the Review queue, with its filters, when opened from there", async () => {
        setup({ entry: { pathname: "/app/c1/world/location/l1", state: { reviewSearch: "?status=approved&type=settlement" } } })
        expect(await screen.findByRole("link", { name: "Back to Review queue" })).toHaveAttribute(
            "href",
            "/app/c1/review?status=approved&type=settlement",
        )
        expect(screen.queryByRole("link", { name: "Back to World" })).not.toBeInTheDocument()
    })

    it("keeps the return state on its own links", async () => {
        const { router } = setup({
            entry: { pathname: "/app/c1/world/location/l1", state: { reviewSearch: "?status=draft" } },
        })
        await opened("Old Mill")
        fireEvent.click(screen.getByRole("link", { name: "Sources" }))
        await waitFor(() => expect(router.state.location.search).toBe("?section=sources"))
        expect(router.state.location.state).toEqual({ reviewSearch: "?status=draft" })
    })
})

describe("World record workspace: Review and Publication", () => {
    const revisions: RevisionFixture[] = [
        { row_version: 3, kind: "lifecycle", created_at: "2026-01-03T10:00:00Z", created_by_name: "Gina", canon_status: "proposed", lifecycle_status: "active" },
        { row_version: 2, kind: "updated", created_at: "2026-01-02T10:00:00Z", created_by_name: "Sam", canon_status: null, lifecycle_status: null },
        { row_version: 1, kind: "created", created_at: "2026-01-01T10:00:00Z", created_by_name: "Sam", canon_status: null, lifecycle_status: null },
    ]
    const proposed = lifecycle({
        canon_status: "proposed",
        available_actions: ["approve", "reject", "return_to_draft"],
        row_version: 3,
    })

    it("shows what a reviewer decides on: the status, the latest change and a comparison", async () => {
        setup({ lifecycle: proposed, canon: "proposed", revisions })
        const review = (await screen.findByRole("heading", { level: 2, name: "Review" })).closest("section")!
        expect(within(review).getByText(/In review\. A reviewer can approve or reject it/)).toBeInTheDocument()
        expect(await within(review).findByText(/Version 3, status changed to proposed, .* by Gina/)).toBeInTheDocument()
        expect(within(review).getByRole("link", { name: "Compare version 3 with version 2" })).toHaveAttribute(
            "href",
            "/app/c1/world/location/l1/history?from=2&to=3",
        )
    })

    it("offers Approve from Review without taking it until it is confirmed", async () => {
        const { server } = setup({ lifecycle: proposed, canon: "proposed", revisions })
        fireEvent.click(await screen.findByRole("button", { name: "Approve" }))
        const dialog = screen.getByRole("dialog", { name: "Approve this record?", hidden: true })
        expect(dialog).toBeInTheDocument()
        expect(writes(server)).toHaveLength(0)
    })

    it("offers Publish from Review for an approved record, and nothing to someone who is offered neither", async () => {
        const approved = setup({
            lifecycle: lifecycle({ canon_status: "approved", available_actions: ["publish", "return_to_draft"] }),
            canon: "approved",
        })
        expect(await screen.findByRole("button", { name: "Publish as canon" })).toBeInTheDocument()
        approved.unmount()
        setup({ lifecycle: lifecycle({ canon_status: "proposed", available_actions: [] }), canon: "proposed" })
        await screen.findByRole("heading", { level: 2, name: "Review" })
        expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument()
        expect(screen.queryByRole("button", { name: "Publish as canon" })).not.toBeInTheDocument()
    })

    it("takes the decision from the server's actions, never from the stage", async () => {
        // Opened at Review, but the draft offers no approval: no decision button is invented.
        setup({ entry: "/app/c1/world/location/l1?section=review" })
        await screen.findByRole("heading", { level: 2, name: "Review" })
        expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument()
        expect(screen.queryByRole("button", { name: "Publish as canon" })).not.toBeInTheDocument()
    })

    it("shows the actionable reason a step is unavailable", async () => {
        setup({
            lifecycle: lifecycle({
                canon_status: "approved",
                available_actions: ["return_to_draft"],
                blocked_actions: [{ action: "publish", reason: "reference_not_published" }],
            }),
            canon: "approved",
        })
        expect(await screen.findByRole("list", { name: "Actions that need something first" })).toHaveTextContent(
            "Publish as canon unavailable",
        )
    })

    it("says so when the revision history cannot be read, and still offers the decision", async () => {
        setup({
            lifecycle: proposed,
            canon: "proposed",
            extra: (server) => server.on("GET", `/campaigns/${C}/entities/l1/revisions`, { status: 500, body: {} }),
        })
        expect(await screen.findByText("The revision history could not be loaded.")).toBeInTheDocument()
        expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument()
    })

    it("approves, refreshes in place and keeps what was typed in Sources", async () => {
        let current = proposed
        const { server } = setup({
            lifecycle: () => current,
            canon: "proposed",
            revisions,
            extra: (server) =>
                server.on("POST", `/campaigns/${C}/entities/l1/lifecycle/approve`, () => {
                    current = lifecycle({ canon_status: "approved", row_version: 4, available_actions: ["publish", "return_to_draft"] })
                    return { body: { entity_id: "l1", canon_status: "approved", lifecycle_status: "active", row_version: 4 } }
                }),
        })
        await screen.findByRole("heading", { level: 2, name: "Review" })
        // Type into the hidden Sources form, then take the decision from Review.
        fireEvent.click(screen.getByRole("link", { name: "1. Prepare" }))
        fireEvent.click(await screen.findByRole("link", { name: "Sources" }))
        fireEvent.click(await screen.findByRole("button", { name: "Add source" }))
        fireEvent.change(screen.getByLabelText("Title"), { target: { value: "The ledger" } })
        fireEvent.click(screen.getByRole("link", { name: "2. Review & publish" }))
        await screen.findByRole("heading", { level: 2, name: "Review" })
        const detailReads = server.callsTo("GET", `/campaigns/${C}/world/locations/l1`).length
        const revisionReads = server.callsTo("GET", `/campaigns/${C}/entities/l1/revisions`).length
        fireEvent.click(screen.getByRole("button", { name: "Approve" }))
        const dialog = screen.getByRole("dialog", { name: "Approve this record?", hidden: true })
        fireEvent.click(within(dialog).getByRole("button", { name: "Approve" }))
        await screen.findByRole("button", { name: "Publish as canon" })
        expect(server.callsTo("POST", `/campaigns/${C}/entities/l1/lifecycle/approve`)[0]!.body).toEqual({
            expected_row_version: 3,
        })
        // The record and its history were read again, and the page never went back to loading.
        await waitFor(() => expect(server.callsTo("GET", `/campaigns/${C}/world/locations/l1`).length).toBeGreaterThan(detailReads))
        await waitFor(() => expect(server.callsTo("GET", `/campaigns/${C}/entities/l1/revisions`).length).toBeGreaterThan(revisionReads))
        expect(screen.getByRole("heading", { level: 1, name: "Old Mill" })).toBeInTheDocument()
        expect(screen.getByLabelText("Title")).toHaveValue("The ledger")
        expect(screen.getByRole("group", { name: "Record status" })).toHaveTextContent("Approved")
    })

    it("keeps the workspace and what was typed when a refresh fails, and offers Try again", async () => {
        let reads = 0
        const { server } = setup({
            // The first read of the record succeeds; every later one fails until reset.
            extra: (server) => {
                server.on("GET", `/campaigns/${C}/world/locations/l1`, () =>
                    ++reads > 1 ? { status: 500, body: {} } : { body: locationDetail() },
                )
                server.on("POST", `/campaigns/${C}/entities/l1/lifecycle/submit-for-review`, {
                    body: { entity_id: "l1", canon_status: "proposed", lifecycle_status: "active", row_version: 3 },
                })
            },
        })
        await opened("Old Mill")
        fireEvent.click(screen.getByRole("link", { name: "Sources" }))
        fireEvent.click(await screen.findByRole("button", { name: "Add source" }))
        fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Kept title" } })
        fireEvent.click(screen.getByRole("link", { name: "2. Review & publish" }))
        fireEvent.click(await screen.findByRole("link", { name: "Publication" }))
        fireEvent.click(await screen.findByRole("button", { name: "Submit for review" }))
        expect(await screen.findByText(/could not be loaded, so what is shown may be out of date/)).toBeInTheDocument()
        expect(screen.getByRole("heading", { level: 1, name: "Old Mill" })).toBeInTheDocument()
        expect(screen.getByLabelText("Title")).toHaveValue("Kept title")
        expect(server.callsTo("POST", `/campaigns/${C}/entities/l1/lifecycle/submit-for-review`)).toHaveLength(1)
        reads = 0
        fireEvent.click(screen.getByRole("button", { name: "Try again" }))
        await waitFor(() => expect(screen.queryByText(/may be out of date/)).not.toBeInTheDocument())
    })

    it("lists every step the server offers in Publication, with the history link", async () => {
        setup({ entry: "/app/c1/world/location/l1?section=publication" })
        const group = await screen.findByRole("group", { name: "Lifecycle" })
        expect(within(group).getByRole("button", { name: "Submit for review" })).toBeVisible()
        expect(screen.getByRole("link", { name: "Revision history and comparison" })).toHaveAttribute(
            "href",
            "/app/c1/world/location/l1/history",
        )
    })

    it("still shows the record when its lifecycle cannot be read, and offers no step", async () => {
        setup({
            entry: "/app/c1/world/location/l1?section=publication",
            extra: (server) => server.on("GET", `/campaigns/${C}/entities/l1/lifecycle`, { status: 500, body: {} }),
        })
        expect(await screen.findByText(/lifecycle could not be loaded, so no step is shown/)).toBeInTheDocument()
        expect(screen.getByRole("heading", { level: 1, name: "Old Mill" })).toBeInTheDocument()
        expect(screen.queryByRole("group", { name: "Record status" })).not.toBeInTheDocument()
        expect(screen.queryByRole("button", { name: "Submit for review" })).not.toBeInTheDocument()
        expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument()
    })
})

describe("World record workspace: failing closed", () => {
    it("says the record is unavailable for a missing or inaccessible one, with no lifecycle write", async () => {
        const { server } = setup({
            extra: (s) => s.on("GET", `/campaigns/${C}/world/locations/l1`, NOT_FOUND),
        })
        expect(await screen.findByRole("heading", { level: 1, name: "Location unavailable" })).toBeInTheDocument()
        expect(screen.getByRole("alert")).toHaveTextContent("does not exist, or you do not have access to it")
        expect(screen.getByRole("link", { name: "Back to World" })).toBeInTheDocument()
        expect(screen.queryByRole("navigation", { name: "Record stages" })).not.toBeInTheDocument()
        expect(writes(server)).toHaveLength(0)
    })

    it("offers Try again when the first read fails", async () => {
        let attempts = 0
        setup({
            extra: (s) =>
                s.on("GET", `/campaigns/${C}/world/locations/l1`, () =>
                    ++attempts === 1 ? { status: 500, body: {} } : { body: locationDetail() },
                ),
        })
        fireEvent.click(await screen.findByRole("button", { name: "Try again" }))
        await opened("Old Mill")
    })
})

describe("World record workspace: a dungeon", () => {
    const dungeonView = {
        dungeon_id: "l1",
        name: "Crypt",
        summary: null,
        danger_level: 3,
        parent: null,
        canon_status: "draft",
        lifecycle_status: "active",
        row_version: 2,
        available_actions: ["update"],
        blocked_actions: [],
        field_locks: [],
        areas: [
            { dungeon_area_id: "a1", name: "Entry hall", area_type: "hall", canon_status: "draft", lifecycle_status: "active", row_version: 1, feature_count: 1, hazard_count: 0, interactable_count: 2 },
        ],
        connections: [
            { area_connection_id: "x1", from_area: { entity_id: "a1", name: "Entry hall", canon_status: "draft", lifecycle_status: "active" }, to_area: { entity_id: "a2", name: "Vault", canon_status: "draft", lifecycle_status: "active" }, connection_type: "door", connection_type_label: "Door", is_one_way: false, is_hidden: true, description: null, is_conditional: false, condition_description: null, status: null, state_event_id: null },
        ],
    }

    function dungeon(editView: object = dungeonView) {
        return setup({
            typeCode: "dungeon",
            detail: locationDetail({ name: "Crypt", location_type_code: "dungeon" }),
            lifecycle: lifecycle({ entity_type_code: "dungeon", canonical_name: "Crypt" }),
            extra: (server) => {
                server.on("GET", `/campaigns/${C}/authoring/dungeons/l1`, { body: editView })
            },
        })
    }

    it("has a Structure section listing its areas and connections, and no Use in play", async () => {
        dungeon()
        await opened("Crypt")
        expect(stageLinks()).toEqual(["1. Prepare", "2. Review & publish"])
        expect(sectionLinks("Prepare")).toEqual(["Details", "Structure", "Sources", "Relationships"])
        fireEvent.click(screen.getByRole("link", { name: "Structure" }))
        const areas = await screen.findByRole("list", { name: "Areas" })
        expect(within(areas).getByRole("link", { name: "Entry hall" })).toHaveAttribute("href", "/app/c1/world/location/a1")
        expect(areas).toHaveTextContent("1 feature, 0 hazards, 2 interactables")
        expect(screen.getByRole("list", { name: "Connections" })).toHaveTextContent("Entry hall and Vault: Door (hidden)")
        expect(screen.getByRole("link", { name: "Edit dungeon structure" })).toHaveAttribute(
            "href",
            "/app/c1/world/dungeon/l1/edit",
        )
    })

    it("offers editing the dungeon from Details through the dungeon editor", async () => {
        dungeon()
        expect(await screen.findByRole("link", { name: "Edit dungeon" })).toHaveAttribute("href", "/app/c1/world/dungeon/l1/edit")
    })

    it("explains why the structure cannot be edited while it is in review", async () => {
        dungeon({
            ...dungeonView,
            available_actions: [],
            blocked_actions: [{ action: "update", reason: "review_in_progress" }],
        })
        await opened("Crypt")
        fireEvent.click(screen.getByRole("link", { name: "Structure" }))
        expect((await screen.findAllByText(/Editing unavailable/)).length).toBeGreaterThan(0)
        expect(screen.queryByRole("link", { name: "Edit dungeon structure" })).not.toBeInTheDocument()
    })
})

describe("World record workspace: a dungeon area", () => {
    function area(canon: string, lifecycleStatus = "active") {
        return setup({
            typeCode: "dungeon_area",
            canon,
            detail: locationDetail({
                name: "Entry hall",
                location_type_code: "dungeon_area",
                parent_location_id: "d1",
                is_searched: true,
                is_destroyed: false,
                alarm_level: 2,
                condition_notes: "Dusty",
            }),
            lifecycle: lifecycle({
                entity_type_code: "dungeon_area",
                canon_status: canon,
                lifecycle_status: lifecycleStatus,
                available_actions: [],
            }),
            extra: (server) =>
                server.on("GET", `/campaigns/${C}/authoring/dungeon-areas/l1`, {
                    body: { available_actions: ["update"], blocked_actions: [] },
                }),
        })
    }

    it("has Use in play with the area's timeline state, kept out of its details", async () => {
        area("canon")
        await opened("Entry hall")
        expect(stageLinks()).toEqual(["1. Prepare", "2. Review & publish", "3. Use in play"])
        // The definition's details do not show timeline state.
        const details = screen.getByRole("heading", { level: 2, name: "Details" }).closest("section")!
        expect(within(details).queryByText("Alarm level")).toBeNull()
        fireEvent.click(screen.getByRole("link", { name: "3. Use in play" }))
        expect(await screen.findByRole("heading", { level: 2, name: "Area now" })).toBeVisible()
        expect(screen.getByText("Alarm level")).toBeVisible()
        expect(screen.getByText("Dusty")).toBeVisible()
        expect(screen.getByRole("link", { name: "Record what is happening here" })).toHaveAttribute(
            "href",
            "/app/c1/world/dungeon/d1/areas/l1/edit",
        )
    })

    it("returns from the area's editor to the Area now section it was opened from", async () => {
        const { router } = area("canon")
        await opened("Entry hall")
        fireEvent.click(screen.getByRole("link", { name: "3. Use in play" }))
        fireEvent.click(await screen.findByRole("link", { name: "Record what is happening here" }))
        await screen.findByText("Area edit page")
        expect(router.state.location.state).toMatchObject({
            returnTo: { pathname: "/app/c1/world/location/l1", search: "?section=area-now" },
        })
    })

    it.each([
        ["draft", "active", /not published yet/],
        ["proposed", "active", /not published yet/],
        ["canon", "archived", /archived/],
        ["superseded", "active", /replaced/],
    ])("does not offer to record what happens to a %s (%s) area", async (canon, lifecycleStatus, message) => {
        area(canon, lifecycleStatus)
        await opened("Entry hall")
        fireEvent.click(screen.getByRole("link", { name: "3. Use in play" }))
        await shown(message)
        expect(screen.queryByRole("link", { name: "Record what is happening here" })).not.toBeInTheDocument()
    })
})

describe("World record workspace: an organization", () => {
    function organization(canon: string) {
        return setup({
            category: "organization",
            entityId: "o1",
            typeCode: "business",
            canon,
            detailPath: `/campaigns/${C}/world/organizations/o1`,
            detail: organizationDetail,
            lifecycle: lifecycle({ entity_id: "o1", entity_type_code: "business", canon_status: canon, available_actions: [] }),
            extra: (server) => {
                server.on("GET", `/campaigns/${C}/authoring/organizations/o1`, { body: { available_actions: ["update"], blocked_actions: [] } })
                server.on("GET", `/campaigns/${C}/organizations/o1/members`, {
                    body: { organization_id: "o1", status: null, can_edit: false, status_choices: [], members: [] },
                })
            },
        })
    }

    it("shows the organization's own panels and an Edit link", async () => {
        organization("draft")
        await opened("The Guild")
        expect(screen.getByRole("heading", { level: 2, name: "Structure" })).toBeVisible()
        expect(await screen.findByRole("link", { name: "Edit organization" })).toHaveAttribute(
            "href",
            "/app/c1/world/organization/o1/edit",
        )
    })

    it("says an unpublished organization takes no members or status yet, and shows the roster once published", async () => {
        const draft = organization("draft")
        await opened("The Guild")
        fireEvent.click(screen.getByRole("link", { name: "3. Use in play" }))
        await shown(/not published yet/)
        draft.unmount()
        organization("canon")
        await opened("The Guild")
        fireEvent.click(screen.getByRole("link", { name: "3. Use in play" }))
        await shown("No members are known.")
        expect(screen.queryByText(/not published yet/)).not.toBeInTheDocument()
    })
})

describe("World record workspace: a religion", () => {
    it("has the two stages every record has and no Use in play", async () => {
        setup({
            category: "religion",
            entityId: "r1",
            typeCode: "religion",
            detailPath: `/campaigns/${C}/world/religions/r1`,
            detail: { religion_id: "r1", name: "The Dawn", summary: null, pantheon_structure: "Monotheistic", serving_organization_ids: [] },
            lifecycle: lifecycle({ entity_id: "r1", entity_type_code: "religion" }),
        })
        await opened("The Dawn")
        expect(stageLinks()).toEqual(["1. Prepare", "2. Review & publish"])
        expect(screen.getByText("Monotheistic")).toBeVisible()
    })
})

describe("World record workspace: characters", () => {
    function character(typeCode: string, canon = "canon") {
        return setup({
            category: "character",
            entityId: "n1",
            typeCode,
            canon,
            detailPath: `/campaigns/${C}/characters/n1`,
            detail: characterDetail(),
            lifecycle: lifecycle({ entity_id: "n1", entity_type_code: typeCode, canon_status: canon, available_actions: [] }),
            extra: (server) => {
                server.on("GET", `/campaigns/${C}/authoring/npcs/n1`, {
                    body: typeCode === "npc" ? { canon_status: canon, available_actions: ["update"], blocked_actions: [] } : NOT_FOUND.body,
                    status: typeCode === "npc" ? 200 : 404,
                })
                server.on("GET", `/campaigns/${C}/authoring/player-characters/n1`, {
                    body: typeCode === "player_character" ? { canon_status: canon, available_actions: ["update"], blocked_actions: [] } : NOT_FOUND.body,
                    status: typeCode === "player_character" ? 200 : 404,
                })
                server.on("GET", `/campaigns/${C}/characters/n1/inventory`, { body: [] })
            },
        })
    }

    it("gives an NPC Run and Inventory under Use in play, and the NPC's edit link", async () => {
        character("npc")
        await opened("Mira")
        expect(screen.getByText("NPC", { selector: ".world-detail__eyebrow" })).toBeInTheDocument()
        expect(await screen.findByRole("link", { name: "Edit NPC" })).toBeInTheDocument()
        expect(screen.queryByRole("link", { name: "Edit player character" })).not.toBeInTheDocument()
        fireEvent.click(screen.getByRole("link", { name: "3. Use in play" }))
        expect(sectionLinks("Use in play")).toEqual(["Run this NPC", "Inventory"])
    })

    it("gives a player character the Player section instead, and no Run", async () => {
        character("player_character")
        await opened("Mira")
        expect(screen.getByText("Player character", { selector: ".world-detail__eyebrow" })).toBeInTheDocument()
        expect(await screen.findByRole("link", { name: "Edit player character" })).toBeInTheDocument()
        fireEvent.click(screen.getByRole("link", { name: "3. Use in play" }))
        expect(sectionLinks("Use in play")).toEqual(["Player", "Inventory"])
    })

    it("does not guess a character's kind when the lifecycle cannot be read", async () => {
        setup({
            category: "character",
            entityId: "n1",
            detailPath: `/campaigns/${C}/characters/n1`,
            detail: characterDetail(),
            extra: (server) => server.on("GET", `/campaigns/${C}/entities/n1/lifecycle`, { status: 500, body: {} }),
        })
        await opened("Mira")
        fireEvent.click(await screen.findByRole("link", { name: "3. Use in play" }))
        // Only what applies to either kind: one section, so no section menu.
        expect(screen.queryByRole("navigation", { name: "Use in play sections" })).not.toBeInTheDocument()
        expect(screen.getByRole("heading", { level: 2, name: "Inventory" })).toBeVisible()
    })
})

describe("World record page for people who cannot edit canon", () => {
    it("shows the ordinary reader and sends no authoring, lifecycle, sources or revision request", async () => {
        const { server } = setup({ capabilities: ["campaign.view"] })
        expect(await screen.findByRole("heading", { level: 1, name: "Old Mill" })).toBeInTheDocument()
        expect(screen.getByRole("link", { name: "Back to World" })).toBeInTheDocument()
        expect(screen.queryByRole("navigation", { name: "Record stages" })).not.toBeInTheDocument()
        expect(screen.queryByRole("link", { name: /Edit/ })).not.toBeInTheDocument()
        const paths = server.calls.map((c) => c.path)
        expect(paths.some((p) => /authoring|lifecycle|provenance|revisions|\/sources|relationships/.test(p))).toBe(false)
        expect(writes(server)).toHaveLength(0)
    })

    it.each([
        ["organization", "o1", `/campaigns/${C}/world/organizations/o1`, organizationDetail, "The Guild"],
        ["character", "n1", `/campaigns/${C}/characters/n1`, characterDetail(), "Mira"],
    ])("does the same for a %s", async (category, entityId, detailPath, detail, name) => {
        const { server } = setup({ capabilities: ["campaign.view"], category, entityId, detailPath, detail })
        expect(await screen.findByRole("heading", { level: 1, name })).toBeInTheDocument()
        expect(screen.queryByRole("navigation", { name: "Record stages" })).not.toBeInTheDocument()
        expect(server.calls.some((c) => /authoring|lifecycle|provenance|revisions/.test(c.path))).toBe(false)
    })
})

describe("records that keep their own pages", () => {
    it("sends an editor's item to the item workspace, not to this one", async () => {
        const { server } = setup({
            category: "item",
            entityId: "i1",
            extra: (s) => s.on("GET", `/campaigns/${C}/authoring/items/i1`, NOT_FOUND),
        })
        expect(await screen.findByRole("heading", { level: 1, name: "Item unavailable" })).toBeInTheDocument()
        expect(screen.queryByRole("navigation", { name: "Record stages" })).not.toBeInTheDocument()
        expect(server.callsTo("GET", `/campaigns/${C}/authoring/items/i1`).length).toBeGreaterThan(0)
        expect(server.calls.some((c) => c.path.includes("/world/locations"))).toBe(false)
    })

    it("keeps an event a plain record: no lifecycle request, and a link to its record for an editor", async () => {
        const { server } = setup({
            category: "event",
            entityId: "ev1",
            extra: (s) =>
                s.on("GET", `/campaigns/${C}/world/events/ev1`, {
                    body: { event_id: "ev1", name: "The Fall", summary: null, event_type_code: "battle", event_status_code: "recorded", details: null },
                }),
        })
        expect(await screen.findByRole("heading", { level: 1, name: "The Fall" })).toBeInTheDocument()
        expect(screen.getByRole("link", { name: "Open the event record" })).toHaveAttribute("href", "/app/c1/events/ev1")
        expect(screen.queryByRole("navigation", { name: "Record stages" })).not.toBeInTheDocument()
        expect(server.calls.some((c) => c.path.includes("/lifecycle"))).toBe(false)
    })

    it("does not offer the event record link to a player", async () => {
        setup({
            capabilities: ["campaign.view"],
            category: "event",
            entityId: "ev1",
            extra: (s) =>
                s.on("GET", `/campaigns/${C}/world/events/ev1`, {
                    body: { event_id: "ev1", name: "The Fall", summary: null, event_type_code: "battle", event_status_code: "recorded", details: null },
                }),
        })
        await screen.findByRole("heading", { level: 1, name: "The Fall" })
        expect(screen.queryByRole("link", { name: "Open the event record" })).not.toBeInTheDocument()
    })
})

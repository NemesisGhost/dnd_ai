import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../../fixtures/sessionBootstrap"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../../test/authoringHarness"
import type { MockServer } from "../../test/authoringHarness"
import { FULL_RECORD_AUTHORING } from "../../test/recordAuthoring"
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
    authoring: FULL_RECORD_AUTHORING,
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
    authoring: FULL_RECORD_AUTHORING,
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

const characterDetail = (name = "Mira", kind: "npc" | "player_character" = "npc") => ({
    authoring: FULL_RECORD_AUTHORING,
    character_id: "n1",
    name,
    character_kind: kind,
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
        expect(next.getAttribute("href")).toMatch(/\?section=review$/)
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

    it("offers the next step, Submit for review, in Review itself for a draft, with no extra click", async () => {
        const { server } = setup({ entry: "/app/c1/world/location/l1?section=review" })
        const group = await screen.findByRole("group", { name: "Review decision" })
        expect(within(group).getByRole("button", { name: "Submit for review" })).toBeVisible()
        expect(writes(server)).toHaveLength(0)
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
    const OPTIONS = {
        can_create: true,
        connection_types: [
            { value: "door", label: "Door" },
            { value: "secret_door", label: "Secret door" },
        ],
        limits: {
            name_max_length: 200,
            summary_max_length: 4000,
            short_text_max_length: 200,
            notes_max_length: 4000,
            change_note_max_length: 1000,
            rating_min: 1,
            rating_max: 10,
            alarm_level_max: 1000,
        },
    }
    const ref = (id: string, name: string) => ({ entity_id: id, name, canon_status: "draft", lifecycle_status: "active" })
    const areaRow = (id: string, name: string, over: object = {}) => ({
        dungeon_area_id: id,
        name,
        summary: null,
        area_type: null,
        canon_status: "draft",
        lifecycle_status: "active",
        row_version: 1,
        feature_count: 0,
        hazard_count: 0,
        interactable_count: 0,
        available_actions: ["update"],
        ...over,
    })
    const connectionRow = (id: string, from: [string, string], to: [string, string], over: object = {}) => ({
        area_connection_id: id,
        from_area: ref(...from),
        to_area: ref(...to),
        connection_type: "door",
        connection_type_label: "Door",
        is_one_way: false,
        is_hidden: false,
        description: null as string | null,
        is_conditional: false,
        condition_description: null as string | null,
        status: null,
        state_event_id: null,
        ...over,
    })
    const ALL = ["update", "add_area", "add_connection", "update_connection", "remove_connection"]
    const baseView = () => ({
        dungeon_id: "l1",
        name: "Crypt",
        summary: null,
        danger_level: 3,
        parent: null,
        canon_status: "draft",
        lifecycle_status: "active",
        row_version: 2,
        available_actions: ALL,
        blocked_actions: [] as { action: string; reason: string }[],
        field_locks: [],
        areas: [
            areaRow("a2", "Collapsed Stair", { area_type: "corridor" }),
            areaRow("a1", "Entry Hall", {
                area_type: "room",
                summary: "The great doors open onto a hall of broken pillars.",
                canon_status: "canon",
                feature_count: 2,
                hazard_count: 1,
            }),
            areaRow("a3", "Old Vault", {
                lifecycle_status: "archived",
                canon_status: "canon",
                interactable_count: 1,
                available_actions: [],
            }),
        ],
        connections: [
            connectionRow("x1", ["a1", "Entry Hall"], ["a2", "Collapsed Stair"]),
            connectionRow("x2", ["a2", "Collapsed Stair"], ["a3", "Old Vault"], {
                connection_type: "secret_door",
                connection_type_label: "Secret door",
                is_one_way: true,
                is_hidden: true,
            }),
        ],
    })
    type View = ReturnType<typeof baseView>

    // A dungeon whose authoring read follows its writes: every structural command bumps the version
    // (as the server does) and the lifecycle read reports the same one.
    function dungeon(over: Partial<View> = {}, options: Partial<Options> = {}) {
        const state = { view: { ...baseView(), ...over } as View }
        const bump = () => {
            state.view = { ...state.view, row_version: state.view.row_version + 1 }
        }
        const rendered = setup({
            typeCode: "dungeon",
            detail: locationDetail({ name: "Crypt", location_type_code: "dungeon" }),
            lifecycle: () =>
                lifecycle({ entity_type_code: "dungeon", canonical_name: "Crypt", row_version: state.view.row_version }),
            ...options,
            extra: (server) => {
                server.on("GET", `/campaigns/${C}/authoring/dungeons/options`, { body: OPTIONS })
                server.on("GET", `/campaigns/${C}/authoring/dungeons/l1`, () => ({ body: state.view }))
                server.on("POST", `/campaigns/${C}/authoring/dungeons/l1/areas`, (call) => {
                    const body = call.body as { name: string; area_type: string | null }
                    state.view = {
                        ...state.view,
                        areas: [
                            ...state.view.areas,
                            areaRow(`n${state.view.areas.length}`, body.name, { area_type: body.area_type }),
                        ],
                    }
                    return { status: 201, body: { dungeon_area_id: "n", changed: true } }
                })
                server.on("POST", /\/authoring\/dungeons\/l1\/connections$/, () => {
                    state.view = {
                        ...state.view,
                        connections: [
                            ...state.view.connections,
                            connectionRow("x9", ["a1", "Entry Hall"], ["a3", "Old Vault"]),
                        ],
                    }
                    bump()
                    return { status: 201, body: { changed: true } }
                })
                server.on("POST", /\/authoring\/dungeons\/l1\/connections\/x\d\/(update|remove)$/, () => {
                    bump()
                    return { body: { changed: true } }
                })
                server.on("POST", `/campaigns/${C}/entities/l1/lifecycle/submit-for-review`, (call) => ({
                    body: {
                        entity_id: "l1",
                        canon_status: "proposed",
                        lifecycle_status: "active",
                        row_version: (call.body as { expected_row_version: number }).expected_row_version + 1,
                    },
                }))
                options.extra?.(server)
            },
        })
        return { ...rendered, state }
    }

    const areaList = async () => within(await screen.findByRole("list", { name: "Areas" }))
    const openSection = async (name: string) => {
        await opened("Crypt")
        fireEvent.click(screen.getByRole("link", { name }))
        await screen.findByRole("heading", { level: 2, name })
    }

    it("has Areas and Connections instead of Structure, and no Use in play", async () => {
        dungeon()
        await opened("Crypt")
        expect(stageLinks()).toEqual(["1. Prepare", "2. Review & publish"])
        expect(sectionLinks("Prepare")).toEqual(["Details", "Areas", "Connections", "Sources", "Relationships"])
        fireEvent.click(screen.getByRole("link", { name: "2. Review & publish" }))
        // The stage's sections follow the address change, which is not synchronous with the click.
        await screen.findByRole("navigation", { name: "Review & publish sections" })
        expect(sectionLinks("Review & publish")).toEqual(["Review", "Publication"])
    })

    it("lists the areas in the server's order, each with its own status, contents and connections", async () => {
        const { server } = dungeon()
        await openSection("Areas")
        const list = await areaList()
        const rows = list.getAllByRole("listitem")
        expect(
            rows.map((row) => within(row).getByRole("link", { name: /^(Collapsed Stair|Entry Hall|Old Vault)$/ }).textContent),
        ).toEqual(["Collapsed Stair", "Entry Hall", "Old Vault"])
        const stair = within(rows[0]!)
        expect(stair.getByText("corridor")).toBeVisible()
        expect(stair.getByText("Draft")).toBeVisible()
        expect(stair.getByText("No contents")).toBeVisible()
        expect(stair.getByText("2 connections")).toBeVisible()
        const hall = within(rows[1]!)
        expect(hall.getByText("Canon")).toBeVisible()
        expect(hall.getByText("2 features · 1 hazard")).toBeVisible()
        expect(hall.getByText("1 connection")).toBeVisible()
        expect(hall.getByText(/broken pillars/)).toBeVisible()
        // An archived area reads as archived whatever the dungeon is, and has no kind to show.
        const vault = within(rows[2]!)
        expect(vault.getByText("Archived")).toBeVisible()
        expect(vault.getByText("1 interactable")).toBeVisible()
        expect(vault.getByText("not set")).toBeInTheDocument()
        expect(writes(server)).toHaveLength(0)
    })

    it("opens an area's own workspace from its name, keeping where the person came from", async () => {
        const { router } = dungeon(
            {},
            {
                entry: {
                    pathname: "/app/c1/world/location/l1",
                    search: "?section=areas",
                    state: { reviewSearch: "?status=draft" },
                },
            },
        )
        const list = await areaList()
        expect(list.getByRole("link", { name: "Entry Hall" })).toHaveAttribute("href", "/app/c1/world/location/a1")
        fireEvent.click(list.getByRole("link", { name: "Entry Hall" }))
        await waitFor(() => expect(router.state.location.pathname).toBe("/app/c1/world/location/a1"))
        expect(router.state.location.state).toEqual({ reviewSearch: "?status=draft" })
    })

    it("offers Edit only for the areas the server says can be edited, and returns to this list", async () => {
        const { router } = dungeon(
            {},
            {
                entry: {
                    pathname: "/app/c1/world/location/l1",
                    search: "?section=areas",
                    state: { worldSearch: "?category=location" },
                },
            },
        )
        const list = await areaList()
        expect(list.getAllByRole("link", { name: /^Edit / }).map((l) => l.getAttribute("aria-label"))).toEqual([
            "Edit Collapsed Stair",
            "Edit Entry Hall",
        ])
        fireEvent.click(list.getByRole("link", { name: "Edit Entry Hall" }))
        await screen.findByText("Area edit page")
        expect(router.state.location.pathname).toBe("/app/c1/world/dungeon/l1/areas/a1/edit")
        expect(router.state.location.state).toEqual({
            worldSearch: "?category=location",
            returnTo: { pathname: "/app/c1/world/location/l1", search: "?section=areas" },
        })
    })

    it("lists all thirty areas of a large dungeon without paging", async () => {
        const many = Array.from({ length: 30 }, (_, i) =>
            areaRow(`m${i}`, `Chamber ${String(i + 1).padStart(2, "0")} of the long forgotten under halls`, {
                area_type: "a very long kind of area that keeps going",
            }),
        )
        dungeon({ areas: many, connections: [] })
        await openSection("Areas")
        expect((await areaList()).getAllByRole("listitem")).toHaveLength(30)
        expect(screen.getByText("30 areas")).toBeVisible()
    })

    it("says so when there are no areas, and still offers Add area", async () => {
        dungeon({ areas: [], connections: [] })
        await openSection("Areas")
        expect(await screen.findByText("No areas yet.")).toBeVisible()
        expect(screen.getByRole("button", { name: "Add area" })).toBeVisible()
    })

    it("offers no Add area, and says why, when the dungeon cannot be changed", async () => {
        dungeon({ available_actions: [], blocked_actions: [{ action: "update", reason: "review_in_progress" }] })
        await openSection("Areas")
        expect(await screen.findByText(/Adding an area is unavailable: it is awaiting review/)).toBeVisible()
        expect(screen.queryByRole("button", { name: "Add area" })).not.toBeInTheDocument()
    })

    it("adds an area, stays on the list, clears the form, keeps focus in Name and announces it", async () => {
        const { server } = dungeon()
        await openSection("Areas")
        expect(screen.queryByRole("form", { name: "Add an area" })).not.toBeInTheDocument()
        fireEvent.click(screen.getByRole("button", { name: "Add area" }))
        const form = await screen.findByRole("form", { name: "Add an area" })
        fireEvent.change(within(form).getByRole("textbox", { name: /Area name/ }), { target: { value: " Shrine of Ash " } })
        fireEvent.change(within(form).getByRole("textbox", { name: "Kind of area" }), { target: { value: "chamber" } })
        fireEvent.click(within(form).getByRole("button", { name: "Add area" }))
        await waitFor(() => expect(server.callsTo("POST", `/campaigns/${C}/authoring/dungeons/l1/areas`)).toHaveLength(1))
        expect(server.callsTo("POST", `/campaigns/${C}/authoring/dungeons/l1/areas`)[0]!.body).toEqual({
            name: "Shrine of Ash",
            area_type: "chamber",
        })
        expect(await (await areaList()).findByRole("link", { name: "Shrine of Ash" })).toBeVisible()
        expect(within(form).getByRole("textbox", { name: /Area name/ })).toHaveValue("")
        await waitFor(() => expect(within(form).getByRole("textbox", { name: /Area name/ })).toHaveFocus())
        expect(screen.getByTestId("authoring-announcer")).toHaveTextContent("Area Shrine of Ash added as a draft")
        // It did not navigate to the new area.
        expect(screen.getByRole("heading", { level: 1, name: "Crypt" })).toBeVisible()
    })

    it("requires a name and sends nothing otherwise", async () => {
        const { server } = dungeon()
        await openSection("Areas")
        fireEvent.click(screen.getByRole("button", { name: "Add area" }))
        fireEvent.click(
            within(await screen.findByRole("form", { name: "Add an area" })).getByRole("button", { name: "Add area" }),
        )
        expect(await screen.findByText("Enter a name.")).toBeVisible()
        expect(writes(server)).toHaveLength(0)
    })

    it("keeps a half-typed new area when another section is shown, and names it before leaving", async () => {
        dungeon()
        await openSection("Areas")
        fireEvent.click(screen.getByRole("button", { name: "Add area" }))
        fireEvent.change(await screen.findByRole("textbox", { name: /Area name/ }), { target: { value: "Half typed" } })
        fireEvent.click(screen.getByRole("link", { name: "Connections" }))
        await screen.findByRole("heading", { level: 2, name: "Connections" })
        fireEvent.click(screen.getByRole("link", { name: "Areas" }))
        expect(await screen.findByRole("textbox", { name: /Area name/ })).toHaveValue("Half typed")
        fireEvent.click(screen.getByRole("link", { name: "Back to World" }))
        const dialog = await screen.findByRole("dialog", { name: "Discard unsaved input?" })
        expect(dialog).toHaveTextContent("a new area")
    })

    it("replaces the old Structure address with Areas, keeping the rest of the address and the state", async () => {
        const { router } = dungeon(
            {},
            {
                entry: {
                    pathname: "/app/c1/world/location/l1",
                    search: "?section=structure&x=1",
                    state: { worldSearch: "?category=location" },
                },
            },
        )
        await screen.findByRole("heading", { level: 2, name: "Areas" })
        await waitFor(() => expect(router.state.location.search).toBe("?section=areas&x=1"))
        expect(router.state.location.state).toEqual({ worldSearch: "?category=location" })
        expect(router.state.historyAction).toBe("REPLACE")
    })

    it("sends no write when only moving between sections", async () => {
        const { server } = dungeon()
        await openSection("Areas")
        fireEvent.click(screen.getByRole("link", { name: "Connections" }))
        await screen.findByRole("heading", { level: 2, name: "Connections" })
        fireEvent.click(screen.getByRole("link", { name: "2. Review & publish" }))
        await screen.findByRole("heading", { level: 2, name: "Review" })
        expect(writes(server)).toHaveLength(0)
    })

    it("lists the connections in words, with the endpoints named in the accessible name", async () => {
        dungeon()
        await openSection("Connections")
        const list = within(await screen.findByRole("list", { name: "Connections" }))
        const rows = list.getAllByRole("listitem")
        expect(rows).toHaveLength(2)
        expect(within(rows[0]!).getByText("Entry Hall and Collapsed Stair")).toBeInTheDocument()
        expect(within(rows[0]!).getByText("Door")).toBeVisible()
        expect(within(rows[1]!).getByText("Collapsed Stair to Old Vault")).toBeInTheDocument()
        expect(within(rows[1]!).getByText("Secret door · one way · concealed")).toBeVisible()
    })

    it("explains connections need two areas, with a link to Areas", async () => {
        dungeon({ areas: [areaRow("a1", "Entry Hall")], connections: [] })
        await openSection("Connections")
        expect(await screen.findByText(/Add at least two areas to connect them/)).toBeVisible()
        expect(screen.getByRole("link", { name: "Go to Areas" })).toHaveAttribute(
            "href",
            expect.stringContaining("section=areas"),
        )
        expect(screen.queryByRole("button", { name: "Add connection" })).not.toBeInTheDocument()
    })

    it("adds a connection against the dungeon version, and a submit right after names the new one", async () => {
        const { server } = dungeon()
        await openSection("Connections")
        fireEvent.click(await screen.findByRole("button", { name: "Add connection" }))
        const form = await screen.findByRole("form", { name: "Add a connection" })
        const [from, to, kind] = within(form).getAllByRole("combobox")
        fireEvent.change(from!, { target: { value: "a1" } })
        fireEvent.change(to!, { target: { value: "a1" } })
        fireEvent.change(kind!, { target: { value: "door" } })
        fireEvent.click(within(form).getByRole("button", { name: "Add connection" }))
        expect(await within(form).findByText("Choose two different areas.")).toBeVisible()
        expect(writes(server)).toHaveLength(0)
        fireEvent.change(to!, { target: { value: "a3" } })
        fireEvent.click(within(form).getByRole("button", { name: "Add connection" }))
        await waitFor(() =>
            expect(server.callsTo("POST", `/campaigns/${C}/authoring/dungeons/l1/connections`)).toHaveLength(1),
        )
        expect(server.callsTo("POST", `/campaigns/${C}/authoring/dungeons/l1/connections`)[0]!.body).toMatchObject({
            expected_row_version: 2,
            from_area_id: "a1",
            to_area_id: "a3",
            connection_type: "door",
        })
        expect(await screen.findByText("3 connections")).toBeVisible()
        // The dungeon is now at version 3. Submitting it must name that, not the version read before.
        fireEvent.click(screen.getByRole("link", { name: "2. Review & publish" }))
        fireEvent.click(await screen.findByRole("button", { name: "Submit for review" }))
        await waitFor(() =>
            expect(server.callsTo("POST", `/campaigns/${C}/entities/l1/lifecycle/submit-for-review`)).toHaveLength(1),
        )
        expect(server.callsTo("POST", `/campaigns/${C}/entities/l1/lifecycle/submit-for-review`)[0]!.body).toEqual({
            expected_row_version: 3,
        })
    })

    it("asks before removing a connection, and sends nothing if it is cancelled", async () => {
        const { server } = dungeon()
        await openSection("Connections")
        fireEvent.click(await screen.findByRole("button", { name: "Remove connection Entry Hall and Collapsed Stair" }))
        const dialog = await screen.findByRole("dialog", { name: "Remove this connection?" })
        expect(dialog).toHaveTextContent("Entry Hall and Collapsed Stair")
        fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }))
        expect(writes(server)).toHaveLength(0)
    })

    it("removes a connection against the dungeon version once it is confirmed", async () => {
        const { server } = dungeon()
        await openSection("Connections")
        fireEvent.click(await screen.findByRole("button", { name: "Remove connection Entry Hall and Collapsed Stair" }))
        const dialog = await screen.findByRole("dialog", { name: "Remove this connection?" })
        fireEvent.click(within(dialog).getByRole("button", { name: "Remove connection" }))
        await waitFor(() => expect(server.callsTo("POST", /connections\/x1\/remove$/)).toHaveLength(1))
        expect(server.callsTo("POST", /connections\/x1\/remove$/)[0]!.body).toEqual({ expected_row_version: 2 })
        await waitFor(() =>
            expect(screen.getByTestId("authoring-announcer")).toHaveTextContent(
                "Connection between Entry Hall and Collapsed Stair removed",
            ),
        )
    })

    it("offers no removal once the dungeon is published, and says removal is for drafts", async () => {
        dungeon({
            canon_status: "canon",
            available_actions: ["update", "add_area", "add_connection", "update_connection"],
            blocked_actions: [{ action: "remove_connection", reason: "dungeon_not_draft" }],
        })
        await openSection("Connections")
        await screen.findByRole("list", { name: "Connections" })
        expect(screen.queryByRole("button", { name: /Remove connection/ })).not.toBeInTheDocument()
        expect(screen.getByText("Connections can be removed only while the dungeon is a draft.")).toBeVisible()
        expect(screen.getAllByRole("button", { name: /Edit connection/ })).toHaveLength(2)
    })

    it("keeps an edit open with its values when the server refuses the save", async () => {
        const { server } = dungeon(
            {},
            {
                extra: (s) =>
                    s.on("POST", /connections\/x1\/update$/, {
                        status: 409,
                        body: { error: { code: "connection_invalid", message: "m", correlation_id: "c" } },
                    }),
            },
        )
        await openSection("Connections")
        fireEvent.click(await screen.findByRole("button", { name: "Edit connection Entry Hall and Collapsed Stair" }))
        const form = await screen.findByRole("form", { name: "Edit connection Entry Hall and Collapsed Stair" })
        fireEvent.change(within(form).getByRole("textbox", { name: "Description" }), { target: { value: "A heavy door" } })
        fireEvent.click(within(form).getByRole("button", { name: "Save connection" }))
        expect(await screen.findByText(/Choose two different areas/)).toBeVisible()
        expect(server.callsTo("POST", /connections\/x1\/update$/)).toHaveLength(1)
        expect(screen.getByRole("form", { name: "Edit connection Entry Hall and Collapsed Stair" })).toBeVisible()
        expect(within(form).getByRole("textbox", { name: "Description" })).toHaveValue("A heavy door")
    })

    it("saves an edit, closes the editor and returns focus to the row's Edit button", async () => {
        const { server } = dungeon()
        await openSection("Connections")
        const edit = await screen.findByRole("button", { name: "Edit connection Entry Hall and Collapsed Stair" })
        fireEvent.click(edit)
        const form = await screen.findByRole("form", { name: "Edit connection Entry Hall and Collapsed Stair" })
        fireEvent.change(within(form).getByRole("combobox", { name: /One way only/ }), { target: { value: "yes" } })
        fireEvent.click(within(form).getByRole("button", { name: "Save connection" }))
        await waitFor(() => expect(screen.queryByRole("form", { name: /Edit connection/ })).not.toBeInTheDocument())
        expect(server.callsTo("POST", /connections\/x1\/update$/)[0]!.body).toMatchObject({
            expected_row_version: 2,
            is_one_way: true,
        })
        await waitFor(() => expect(edit).toHaveFocus())
    })

    it("opens one editor at a time, and does not discard an editor with unsent edits", async () => {
        dungeon()
        await openSection("Connections")
        fireEvent.click(await screen.findByRole("button", { name: "Edit connection Entry Hall and Collapsed Stair" }))
        expect(await screen.findAllByRole("form", { name: /Edit connection/ })).toHaveLength(1)
        // Untouched: opening the other row replaces it.
        fireEvent.click(screen.getByRole("button", { name: "Edit connection Collapsed Stair to Old Vault" }))
        const second = await screen.findByRole("form", { name: "Edit connection Collapsed Stair to Old Vault" })
        expect(screen.getAllByRole("form", { name: /Edit connection/ })).toHaveLength(1)
        // Edited: opening another row leaves it open, with its values.
        fireEvent.change(within(second).getByRole("textbox", { name: "Description" }), { target: { value: "Typed" } })
        fireEvent.click(screen.getByRole("button", { name: "Edit connection Entry Hall and Collapsed Stair" }))
        expect(screen.queryByRole("form", { name: "Edit connection Entry Hall and Collapsed Stair" })).not.toBeInTheDocument()
        expect(within(second).getByRole("textbox", { name: "Description" })).toHaveValue("Typed")
    })

    it("lets an untouched editor follow the saved row, and pauses a dirty one whose row changed elsewhere", async () => {
        const { state } = dungeon()
        await openSection("Connections")
        fireEvent.click(await screen.findByRole("button", { name: "Edit connection Entry Hall and Collapsed Stair" }))
        const form = await screen.findByRole("form", { name: "Edit connection Entry Hall and Collapsed Stair" })
        // Another editor changes the connection; the next read of the dungeon (here, adding an area
        // from the Areas section) brings that change in.
        const changeElsewhere = async (description: string) => {
            state.view = {
                ...state.view,
                row_version: state.view.row_version + 1,
                connections: state.view.connections.map((c) =>
                    c.area_connection_id === "x1" ? { ...c, description } : c,
                ),
            }
            fireEvent.click(screen.getByRole("link", { name: "Areas" }))
            fireEvent.click(await screen.findByRole("button", { name: "Add area" }))
            const add = await screen.findByRole("form", { name: "Add an area" })
            fireEvent.change(within(add).getByRole("textbox", { name: /Area name/ }), {
                target: { value: `Area ${description}` },
            })
            fireEvent.click(within(add).getByRole("button", { name: "Add area" }))
            await screen.findByRole("link", { name: `Area ${description}` })
            fireEvent.click(screen.getByRole("link", { name: "Connections" }))
        }
        await changeElsewhere("one")
        await waitFor(() =>
            expect(within(form).getByRole("textbox", { name: "Description" })).toHaveValue(
                "one",
            ),
        )
        fireEvent.change(within(form).getByRole("textbox", { name: "Description" }), { target: { value: "Mine" } })
        await changeElsewhere("two")
        expect(await screen.findByText(/This connection changed elsewhere/)).toBeVisible()
        expect(within(form).getByRole("textbox", { name: "Description" })).toHaveValue("Mine")
        expect(within(form).getByRole("button", { name: "Save connection" })).toBeDisabled()
        fireEvent.click(screen.getByRole("button", { name: "Keep my changes and save over it" }))
        expect(within(form).getByRole("button", { name: "Save connection" })).toBeEnabled()
    })

    it("says where the areas stand in Review, and that publishing the dungeon does not publish them", async () => {
        dungeon()
        await opened("Crypt")
        fireEvent.click(screen.getByRole("link", { name: "2. Review & publish" }))
        const review = (await screen.findByRole("heading", { level: 2, name: "Review" })).closest("section")!
        expect(await within(review).findByText(/3 areas: 1 published, 1 draft, 1 archived\./)).toBeVisible()
        expect(within(review).getByText(/Publishing the dungeon does not publish its areas/)).toBeVisible()
    })

    it("keeps the dungeon's and the areas' statuses apart: a published dungeon does not publish a draft area", async () => {
        dungeon({ canon_status: "canon" }, { canon: "canon" })
        await openSection("Areas")
        const list = await areaList()
        expect(within(list.getByText("Collapsed Stair").closest("li")!).getByText("Draft")).toBeVisible()
    })

    it("sends no dungeon authoring request to someone who cannot edit canon, and ignores the section", async () => {
        const { server } = dungeon({}, { capabilities: ["campaign.view"], entry: "/app/c1/world/location/l1?section=areas" })
        expect(await screen.findByRole("heading", { level: 1, name: "Crypt" })).toBeVisible()
        expect(screen.queryByRole("navigation", { name: "Record stages" })).not.toBeInTheDocument()
        expect(screen.queryByRole("list", { name: "Areas" })).not.toBeInTheDocument()
        expect(server.calls.some((c) => /authoring|lifecycle|provenance|revisions/.test(c.path))).toBe(false)
    })

    it("offers editing the dungeon's details from Details through the dungeon editor", async () => {
        dungeon()
        expect(await screen.findByRole("link", { name: "Edit dungeon" })).toHaveAttribute(
            "href",
            "/app/c1/world/dungeon/l1/edit",
        )
    })
})

describe("World record workspace: a dungeon area", () => {
    const OPTIONS = {
        can_create: true,
        connection_types: [{ value: "door", label: "Door" }],
        limits: {
            name_max_length: 200,
            summary_max_length: 4000,
            short_text_max_length: 200,
            notes_max_length: 4000,
            change_note_max_length: 1000,
            rating_min: 1,
            rating_max: 10,
            alarm_level_max: 1000,
        },
    }
    const ref = (id: string, name: string, canon = "canon") => ({
        entity_id: id,
        name,
        canon_status: canon,
        lifecycle_status: "active",
    })
    const child = (kind: string, id: string, type: string | null, over: object = {}) => ({
        kind,
        child_id: id,
        child_type: type,
        description: null as string | null,
        is_hidden: false,
        severity: null as number | null,
        status: null as string | null,
        is_destroyed: null as boolean | null,
        condition_notes: null,
        state_event_id: null as string | null,
        ...over,
    })
    const EDIT = ["add_feature", "update_feature", "add_hazard", "update_hazard", "add_interactable", "update_interactable"]
    const REMOVE = ["remove_feature", "remove_hazard", "remove_interactable"]
    const baseArea = () => ({
        dungeon_area_id: "l1",
        name: "Entry hall",
        summary: null,
        area_type: "room",
        dimensions: null,
        environmental_properties: null,
        dungeon: ref("d1", "Crypt"),
        dungeon_row_version: 7,
        canon_status: "canon",
        lifecycle_status: "active",
        row_version: 2,
        available_actions: ["update"],
        blocked_actions: [] as { action: string; reason: string }[],
        structure_actions: [...EDIT, ...REMOVE],
        features: [child("feature", "f1", "mural", { description: "A faded mural.", is_destroyed: false, state_event_id: "ev-f" })],
        hazards: [
            child("hazard", "h1", "Spike trap", { severity: 7, is_hidden: true, status: "armed", state_event_id: "ev1" }),
        ],
        interactables: [child("interactable", "i1", "Lever", { status: "active", state_event_id: "ev-i" })],
        connections: [
            {
                area_connection_id: "x1",
                from_area: ref("l1", "Entry hall"),
                to_area: ref("a2", "Vault"),
                connection_type: "door",
                connection_type_label: "Door",
                is_one_way: false,
                is_hidden: false,
                description: null,
                is_conditional: false,
                condition_description: null,
                status: "open",
                state_event_id: "ev-c",
            },
        ],
        state: { is_searched: true, is_destroyed: false, alarm_level: 2, condition_notes: "Dusty", state_event_id: "ev0" },
        can_set_state: true,
        state_choices: {
            connection_status: [
                { value: "open", label: "Open" },
                { value: "locked", label: "Locked" },
            ],
            hazard_status: [
                { value: "armed", label: "Armed" },
                { value: "triggered", label: "Triggered" },
            ],
            interactable_status: [
                { value: "active", label: "Active" },
                { value: "untouched", label: "Untouched" },
            ],
        },
    })
    type AreaView = ReturnType<typeof baseArea>

    // The runtime projection the server derives from the same area (see `get_area_runtime_endpoint`):
    // what "Area now" reads, with none of the definition's preparation.
    const runtimeOf = (v: AreaView) => ({
        dungeon_area_id: v.dungeon_area_id,
        name: v.name,
        dungeon: { entity_id: v.dungeon.entity_id, name: v.dungeon.name },
        can_set_state: v.can_set_state,
        state: v.state,
        state_choices: v.state_choices,
        connections: v.connections.map((c) => ({
            area_connection_id: c.area_connection_id,
            from_area: { entity_id: c.from_area.entity_id, name: c.from_area.name },
            to_area: { entity_id: c.to_area.entity_id, name: c.to_area.name },
            is_one_way: c.is_one_way,
            status: c.status,
            state_event_id: c.state_event_id,
        })),
        features: v.features.map((c) => ({ child_id: c.child_id, child_type: c.child_type, status: c.status, is_destroyed: c.is_destroyed, state_event_id: c.state_event_id })),
        hazards: v.hazards.map((c) => ({ child_id: c.child_id, child_type: c.child_type, status: c.status, is_destroyed: c.is_destroyed, state_event_id: c.state_event_id })),
        interactables: v.interactables.map((c) => ({ child_id: c.child_id, child_type: c.child_type, status: c.status, is_destroyed: c.is_destroyed, state_event_id: c.state_event_id })),
        limits: { alarm_level_max: 1000, notes_max_length: 4000 },
    })

    function area(canon = "canon", lifecycleStatus = "active", over: Partial<AreaView> = {}, options: Partial<Options> = {}) {
        const state = { view: { ...baseArea(), canon_status: canon, lifecycle_status: lifecycleStatus, ...over } as AreaView }
        const rendered = setup({
            typeCode: "dungeon_area",
            canon,
            detail: locationDetail({
                name: "Entry hall",
                location_type_code: "dungeon_area",
                parent_location_id: "d1",
                breadcrumbs: [{ location_id: "d1", name: "Crypt", location_type_code: "dungeon" }],
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
            ...options,
            extra: (server) => {
                server.on("GET", `/campaigns/${C}/authoring/dungeons/options`, { body: OPTIONS })
                server.on("GET", `/campaigns/${C}/authoring/dungeon-areas/l1`, () => ({ body: state.view }))
                server.on("GET", `/campaigns/${C}/dungeon-areas/l1/runtime`, () => ({ body: runtimeOf(state.view) }))
                server.on("POST", /\/authoring\/dungeons\/d1\/(features|hazards|interactables)(\/[a-z0-9]+\/(update|remove))?$/, (call) => {
                    const body = call.body as { child_type?: string }
                    const kind = /features/.test(call.path) ? "feature" : /hazards/.test(call.path) ? "hazard" : "interactable"
                    const key = kind === "feature" ? "features" : kind === "hazard" ? "hazards" : "interactables"
                    if (/\/remove$/.test(call.path)) {
                        const id = call.path.split("/").at(-2)
                        state.view = { ...state.view, [key]: state.view[key].filter((c) => c.child_id !== id) }
                    } else if (!/\/update$/.test(call.path)) {
                        state.view = {
                            ...state.view,
                            [key]: [...state.view[key], child(kind, `new-${kind}`, body.child_type ?? null)],
                        }
                    }
                    state.view = { ...state.view, dungeon_row_version: state.view.dungeon_row_version + 1 }
                    return { body: { changed: true } }
                })
                server.on("POST", /\/campaigns\/c1\/dungeon-areas\/l1\/state$/, () => ({
                    body: { dungeon_area_id: "l1", kind: "area", target_id: "l1", changed: true },
                }))
                options.extra?.(server)
            },
        })
        return { ...rendered, state }
    }

    const contents = async () => {
        await opened("Entry hall")
        fireEvent.click(screen.getByRole("link", { name: "Contents" }))
        await screen.findByRole("heading", { level: 2, name: "Contents" })
    }
    const areaNow = async () => {
        await opened("Entry hall")
        fireEvent.click(screen.getByRole("link", { name: "3. Use in play" }))
        await screen.findByRole("heading", { level: 2, name: "Area now" })
    }
    const group = (name: string) => within(screen.getByRole("region", { name }))
    const stateWrites = (server: MockServer) => server.callsTo("POST", /dungeon-areas\/l1\/state$/)

    it("has Contents under Prepare and Area now under Use in play", async () => {
        area()
        await opened("Entry hall")
        expect(stageLinks()).toEqual(["1. Prepare", "2. Review & publish", "3. Use in play"])
        expect(sectionLinks("Prepare")).toEqual(["Details", "Contents", "Sources", "Relationships"])
    })

    it("names the dungeon it is in, with a link up to the dungeon's Areas that keeps the return state", async () => {
        const { router } = area("canon", "active", {}, {
            entry: { pathname: "/app/c1/world/location/l1", state: { reviewSearch: "?status=draft" } },
        })
        await opened("Entry hall")
        const link = screen.getByRole("link", { name: "Crypt" })
        expect(link).toHaveAttribute("href", "/app/c1/world/location/d1?section=areas")
        fireEvent.click(link)
        await waitFor(() => expect(router.state.location.pathname).toBe("/app/c1/world/location/d1"))
        expect(router.state.location.search).toBe("?section=areas")
        expect(router.state.location.state).toEqual({ reviewSearch: "?status=draft" })
    })

    it("shows what the area holds in three compact groups, without any runtime status", async () => {
        const { server } = area()
        await contents()
        expect(screen.getByRole("heading", { level: 3, name: "Features (1)" })).toBeVisible()
        expect(screen.getByRole("heading", { level: 3, name: "Hazards (1)" })).toBeVisible()
        expect(screen.getByRole("heading", { level: 3, name: "Interactables (1)" })).toBeVisible()
        expect(group("Hazards").getByText("Spike trap")).toBeVisible()
        expect(group("Hazards").getByText("Concealed · Severity 7")).toBeVisible()
        expect(group("Features").getByText("A faded mural.")).toBeVisible()
        // Whether the trap is armed is what is true now, not what it is.
        const section = screen.getByRole("heading", { level: 2, name: "Contents" }).closest("section")!
        expect(within(section).queryByText(/Armed|Now:/)).not.toBeInTheDocument()
        expect(group("Connections of this area").getByText("Entry hall and Vault")).toBeVisible()
        expect(writes(server)).toHaveLength(0)
    })

    it("links an area's connections to the dungeon's Connections section", async () => {
        area()
        await contents()
        expect(screen.getByRole("link", { name: /Manage in the dungeon's Connections/ })).toHaveAttribute(
            "href",
            "/app/c1/world/location/d1?section=connections",
        )
    })

    it("adds a hazard against the dungeon version, checks the severity, and stays on the list", async () => {
        const { server } = area()
        await contents()
        expect(screen.queryByRole("form", { name: "Add a hazard" })).not.toBeInTheDocument()
        fireEvent.click(screen.getByRole("button", { name: "Add hazard" }))
        const form = await screen.findByRole("form", { name: "Add a hazard" })
        fireEvent.change(within(form).getByRole("textbox", { name: /Kind of hazard/ }), { target: { value: "Pit" } })
        fireEvent.change(within(form).getByRole("textbox", { name: /Severity/ }), { target: { value: "11" } })
        fireEvent.click(within(form).getByRole("button", { name: "Add hazard" }))
        expect(await within(form).findByText(/whole number from 1 to 10/)).toBeVisible()
        expect(writes(server)).toHaveLength(0)
        fireEvent.change(within(form).getByRole("textbox", { name: /Severity/ }), { target: { value: "5" } })
        fireEvent.click(within(form).getByRole("button", { name: "Add hazard" }))
        await waitFor(() => expect(server.callsTo("POST", `/campaigns/${C}/authoring/dungeons/d1/hazards`)).toHaveLength(1))
        expect(server.callsTo("POST", `/campaigns/${C}/authoring/dungeons/d1/hazards`)[0]!.body).toEqual({
            expected_row_version: 7,
            dungeon_area_id: "l1",
            child_type: "Pit",
            description: null,
            is_hidden: false,
            severity: 5,
        })
        expect(await screen.findByRole("heading", { level: 3, name: "Hazards (2)" })).toBeVisible()
        expect(within(form).getByRole("textbox", { name: /Kind of hazard/ })).toHaveValue("")
        expect(screen.getByTestId("authoring-announcer")).toHaveTextContent("Hazard added")
    })

    it("edits a hazard against the dungeon version and closes only once it is saved", async () => {
        const { server } = area()
        await contents()
        const edit = screen.getByRole("button", { name: "Edit hazard Spike trap" })
        fireEvent.click(edit)
        const form = await screen.findByRole("form", { name: "Edit hazard Spike trap" })
        fireEvent.change(within(form).getByRole("textbox", { name: /Severity/ }), { target: { value: "9" } })
        fireEvent.click(within(form).getByRole("button", { name: "Save hazard" }))
        await waitFor(() => expect(screen.queryByRole("form", { name: "Edit hazard Spike trap" })).not.toBeInTheDocument())
        expect(server.callsTo("POST", /dungeons\/d1\/hazards\/h1\/update$/)[0]!.body).toMatchObject({
            expected_row_version: 7,
            severity: 9,
            is_hidden: true,
        })
        await waitFor(() => expect(edit).toHaveFocus())
    })

    it("keeps an edit open with its values when the server refuses it", async () => {
        area("canon", "active", {}, {
            extra: (s) =>
                s.on("POST", /dungeons\/d1\/hazards\/h1\/update$/, {
                    status: 409,
                    body: { error: { code: "dungeon_not_draft", message: "m", correlation_id: "c" } },
                }),
        })
        await contents()
        fireEvent.click(screen.getByRole("button", { name: "Edit hazard Spike trap" }))
        const form = await screen.findByRole("form", { name: "Edit hazard Spike trap" })
        fireEvent.change(within(form).getByRole("textbox", { name: "Description" }), { target: { value: "Rusty spikes" } })
        fireEvent.click(within(form).getByRole("button", { name: "Save hazard" }))
        expect(await screen.findByText(/only while the dungeon is a draft/)).toBeVisible()
        expect(screen.getByRole("form", { name: "Edit hazard Spike trap" })).toBeVisible()
        expect(within(form).getByRole("textbox", { name: "Description" })).toHaveValue("Rusty spikes")
    })

    it("asks before removing a hazard, then removes it against the dungeon version", async () => {
        const { server } = area()
        await contents()
        fireEvent.click(screen.getByRole("button", { name: "Remove hazard Spike trap" }))
        const dialog = await screen.findByRole("dialog", { name: "Remove this hazard?" })
        expect(writes(server)).toHaveLength(0)
        fireEvent.click(within(dialog).getByRole("button", { name: "Remove hazard" }))
        await waitFor(() => expect(server.callsTo("POST", /hazards\/h1\/remove$/)).toHaveLength(1))
        expect(server.callsTo("POST", /hazards\/h1\/remove$/)[0]!.body).toEqual({ expected_row_version: 7 })
        expect(await screen.findByRole("heading", { level: 3, name: "Hazards (0)" })).toBeVisible()
    })

    it("offers no removal while the dungeon is published, and says removal is for drafts", async () => {
        area("canon", "active", { structure_actions: EDIT })
        await contents()
        expect(screen.queryByRole("button", { name: /^Remove / })).not.toBeInTheDocument()
        expect(screen.getByText("Contents can be removed only while the dungeon is a draft.")).toBeVisible()
        expect(screen.getByRole("button", { name: "Edit hazard Spike trap" })).toBeVisible()
    })

    it("explains why contents cannot be changed from the reported statuses, and offers no form", async () => {
        area("canon", "active", { structure_actions: [], dungeon: ref("d1", "Crypt", "proposed") })
        await contents()
        expect(
            screen.getByText(/Contents can be changed while both this area and Crypt can be edited\. This area is published; Crypt is in review\./),
        ).toBeVisible()
        expect(screen.queryByRole("button", { name: /^Add / })).not.toBeInTheDocument()
        expect(screen.queryByRole("button", { name: /^Edit / })).not.toBeInTheDocument()
    })

    it("tells two parts with the same name apart", async () => {
        area("canon", "active", {
            hazards: [child("hazard", "h1", "Spike trap"), child("hazard", "h2", "Spike trap")],
        })
        await contents()
        expect(screen.getByRole("button", { name: "Edit hazard Spike trap (1)" })).toBeVisible()
        expect(screen.getByRole("button", { name: "Edit hazard Spike trap (2)" })).toBeVisible()
    })

    it("keeps a half-typed new hazard when another section is shown, and names it before leaving", async () => {
        area()
        await contents()
        fireEvent.click(screen.getByRole("button", { name: "Add hazard" }))
        fireEvent.change(await screen.findByRole("textbox", { name: /Kind of hazard/ }), { target: { value: "Half" } })
        fireEvent.click(screen.getByRole("link", { name: "Sources" }))
        await screen.findByRole("heading", { level: 2, name: "Sources" })
        fireEvent.click(screen.getByRole("link", { name: "Contents" }))
        expect(await screen.findByRole("textbox", { name: /Kind of hazard/ })).toHaveValue("Half")
        fireEvent.click(screen.getByRole("link", { name: "Back to World" }))
        expect(await screen.findByRole("dialog", { name: "Discard unsaved input?" })).toHaveTextContent("a new hazard")
    })

    it("shows the facts and a Change control for each part in Area now, with the statuses it is in", async () => {
        const { server } = area()
        await areaNow()
        expect(screen.getByText("Dusty")).toBeVisible()
        const list = within(screen.getByRole("list", { name: "What can be recorded" }))
        expect(list.getByText(/Searched: Yes · Destroyed: No · Alarm level: 2 · Notes: Dusty/)).toBeVisible()
        expect(list.getByText("Hazard: Armed")).toBeVisible()
        expect(list.getByText("Interactable: Active")).toBeVisible()
        expect(list.getByText("Feature: Intact")).toBeVisible()
        expect(list.getByText("Connection: Open")).toBeVisible()
        expect(screen.queryByRole("form")).not.toBeInTheDocument()
        expect(screen.queryByRole("link", { name: "Record what is happening here" })).not.toBeInTheDocument()
        expect(writes(server)).toHaveLength(0)
    })

    it("offers the controls only when the server says the state can be recorded", async () => {
        area("canon", "active", { can_set_state: false, dungeon: ref("d1", "Crypt", "draft") })
        await areaNow()
        expect(await screen.findByText(/Publish Crypt first/)).toBeVisible()
        expect(screen.queryByRole("button", { name: /^Change/ })).not.toBeInTheDocument()
    })

    it("records the area's state against the event it was read at, and checks the alarm level", async () => {
        const { server } = area()
        await areaNow()
        fireEvent.click(screen.getByRole("button", { name: "Change the area's current state" }))
        const form = await screen.findByRole("form", { name: "Change the area's current state" })
        fireEvent.change(within(form).getByRole("textbox", { name: /Alarm level/ }), { target: { value: "x" } })
        fireEvent.click(within(form).getByRole("button", { name: "Save area state" }))
        expect(await within(form).findByText(/whole number from 0 to 1000/)).toBeVisible()
        expect(stateWrites(server)).toHaveLength(0)
        fireEvent.change(within(form).getByRole("textbox", { name: /Alarm level/ }), { target: { value: "3" } })
        fireEvent.click(within(form).getByRole("button", { name: "Save area state" }))
        await waitFor(() => expect(stateWrites(server)).toHaveLength(1))
        expect(stateWrites(server)[0]!.body).toEqual({
            kind: "area",
            target_id: "l1",
            expected_last_event_id: "ev0",
            is_searched: true,
            is_destroyed: false,
            alarm_level: 3,
            condition_notes: "Dusty",
        })
        await waitFor(() => expect(screen.queryByRole("form", { name: "Change the area's current state" })).not.toBeInTheDocument())
    })

    it("sets a hazard's status naming the event that last wrote it", async () => {
        const { server } = area()
        await areaNow()
        fireEvent.click(screen.getByRole("button", { name: "Change status of Spike trap" }))
        const form = await screen.findByRole("form", { name: "Change status of Spike trap" })
        fireEvent.change(within(form).getByRole("combobox", { name: "New status for Spike trap" }), { target: { value: "triggered" } })
        fireEvent.click(within(form).getByRole("button", { name: "Save status" }))
        await waitFor(() => expect(stateWrites(server)).toHaveLength(1))
        expect(stateWrites(server)[0]!.body).toEqual({
            kind: "hazard",
            target_id: "h1",
            expected_last_event_id: "ev1",
            hazard_status: "triggered",
        })
    })

    it("pauses a state save whose state moved on, and sends the latest event only once the person chooses to", async () => {
        const { state, server } = area()
        await areaNow()
        fireEvent.click(screen.getByRole("button", { name: "Change the area's current state" }))
        const form = await screen.findByRole("form", { name: "Change the area's current state" })
        fireEvent.change(within(form).getByRole("textbox", { name: /Alarm level/ }), { target: { value: "5" } })
        // Someone else records the state; the next read of the area (here, after adding a feature)
        // brings the newer event in.
        state.view = {
            ...state.view,
            state: { ...state.view.state, alarm_level: 9, state_event_id: "ev9" },
        }
        fireEvent.click(screen.getByRole("link", { name: "1. Prepare" }))
        fireEvent.click(await screen.findByRole("link", { name: "Contents" }))
        fireEvent.click(await screen.findByRole("button", { name: "Add feature" }))
        fireEvent.change(await screen.findByRole("textbox", { name: /Kind of feature/ }), { target: { value: "Pillar" } })
        fireEvent.click(within(screen.getByRole("form", { name: "Add a feature" })).getByRole("button", { name: "Add feature" }))
        await screen.findByRole("heading", { level: 3, name: "Features (2)" })
        fireEvent.click(screen.getByRole("link", { name: "3. Use in play" }))
        expect(await screen.findByText(/This state changed elsewhere/)).toBeVisible()
        expect(within(form).getByRole("textbox", { name: /Alarm level/ })).toHaveValue("5")
        expect(within(form).getByRole("button", { name: "Save area state" })).toBeDisabled()
        expect(stateWrites(server)).toHaveLength(0)
        fireEvent.click(screen.getByRole("button", { name: "Keep my changes and save over it" }))
        fireEvent.click(within(form).getByRole("button", { name: "Save area state" }))
        await waitFor(() => expect(stateWrites(server)).toHaveLength(1))
        expect(stateWrites(server)[0]!.body).toMatchObject({ expected_last_event_id: "ev9", alarm_level: 5 })
    })

    it("explains a refused state record and keeps the editor open", async () => {
        area("canon", "active", {}, {
            extra: (s) =>
                s.on("POST", /dungeon-areas\/l1\/state$/, {
                    status: 409,
                    body: { error: { code: "clock_required", message: "m", correlation_id: "c" } },
                }),
        })
        await areaNow()
        fireEvent.click(screen.getByRole("button", { name: "Change status of Lever" }))
        const form = await screen.findByRole("form", { name: "Change status of Lever" })
        fireEvent.change(within(form).getByRole("combobox"), { target: { value: "untouched" } })
        fireEvent.click(within(form).getByRole("button", { name: "Save status" }))
        expect(await screen.findByText("Set the campaign time first.")).toBeVisible()
        expect(screen.getByRole("form", { name: "Change status of Lever" })).toBeVisible()
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
        expect(screen.queryByRole("button", { name: /^Change/ })).not.toBeInTheDocument()
    })

    it("sends no write when only moving between sections", async () => {
        const { server } = area()
        await contents()
        fireEvent.click(screen.getByRole("link", { name: "3. Use in play" }))
        await screen.findByRole("heading", { level: 2, name: "Area now" })
        expect(writes(server)).toHaveLength(0)
    })

    it("sends no area authoring request to someone who cannot edit canon", async () => {
        const { server } = area("canon", "active", {}, { capabilities: ["campaign.view"] })
        expect(await screen.findByRole("heading", { level: 1, name: "Entry hall" })).toBeVisible()
        expect(screen.queryByRole("navigation", { name: "Record stages" })).not.toBeInTheDocument()
        expect(server.calls.some((c) => /authoring|lifecycle|provenance|revisions/.test(c.path))).toBe(false)
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
            detail: {
                authoring: FULL_RECORD_AUTHORING,
                religion_id: "r1",
                name: "The Dawn",
                summary: null,
                pantheon_structure: "Monotheistic",
                serving_organization_ids: [],
            },
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
            detail: characterDetail("Mira", typeCode === "player_character" ? "player_character" : "npc"),
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

    it("takes a character's kind from the character itself when the lifecycle cannot be read", async () => {
        // The character read names its kind, so a lifecycle that is unreadable (an error here; not
        // the caller's to read in the campaign-only case below) never turns an NPC into a generic
        // character and its runtime sections away.
        setup({
            category: "character",
            entityId: "n1",
            detailPath: `/campaigns/${C}/characters/n1`,
            detail: characterDetail(),
            extra: (server) => server.on("GET", `/campaigns/${C}/entities/n1/lifecycle`, { status: 500, body: {} }),
        })
        await opened("Mira")
        fireEvent.click(await screen.findByRole("link", { name: "3. Use in play" }))
        expect(sectionLinks("Use in play")).toEqual(["Run this NPC", "Inventory"])
    })

    it("does not guess the kind of a bare character row whose lifecycle cannot be read", async () => {
        setup({
            category: "character",
            entityId: "n1",
            detailPath: `/campaigns/${C}/characters/n1`,
            detail: { ...characterDetail(), character_kind: "character" },
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

describe("World record workspace: Relationships", () => {
    const relationshipReads = (server: MockServer) => {
        server.on("GET", /authoring\/relationships\/options/, {
            body: {
                can_create: true,
                kinds: [
                    { code: "general", label: "Other connection", types: ["worship"], roles: [], fixed_roles: null },
                    { code: "ownership", label: "Ownership", types: ["ownership"], roles: [], fixed_roles: null },
                ],
                relationship_types: [],
                limits: {
                    text_max_length: 4000,
                    short_text_max_length: 200,
                    stance_min: -100,
                    stance_max: 100,
                    min_participants: 2,
                    max_participants: 20,
                },
                for_entity: {
                    entity_id: "l1",
                    entity_type_code: "building",
                    pairings: [
                        { relationship_type: "worship", my_role: "object", other_role: "subject", other_entity_type_codes: ["npc"] },
                        { relationship_type: "ownership", my_role: "property", other_role: "owner", other_entity_type_codes: ["npc"] },
                    ],
                },
            },
        })
        server.on("GET", /authoring\/relationships\?entity_id=/, { body: { as_of: null, items: [] } })
    }

    it("names a half-entered new relationship before leaving, and leaves quietly when nothing was entered", async () => {
        setup({ extra: relationshipReads })
        await opened("Old Mill")
        fireEvent.click(screen.getByRole("link", { name: "Relationships" }))
        fireEvent.click(await screen.findByRole("button", { name: "Add relationship" }))
        const form = await screen.findByRole("form", { name: "Add a relationship" })
        fireEvent.change(within(form).getByRole("combobox", { name: "Type" }), { target: { value: "ownership/ownership" } })
        fireEvent.click(screen.getByRole("link", { name: "Back to World" }))
        expect(await screen.findByRole("dialog", { name: "Discard unsaved input?" })).toHaveTextContent("a new relationship")
        fireEvent.click(screen.getByRole("button", { name: "Keep editing" }))
        expect(within(form).getByRole("combobox", { name: "Type" })).toHaveValue("ownership/ownership")
    })

    it("keeps the Add form when another section is shown", async () => {
        setup({ extra: relationshipReads })
        await opened("Old Mill")
        fireEvent.click(screen.getByRole("link", { name: "Relationships" }))
        fireEvent.click(await screen.findByRole("button", { name: "Add relationship" }))
        const form = await screen.findByRole("form", { name: "Add a relationship" })
        fireEvent.change(within(form).getByRole("combobox", { name: "Type" }), { target: { value: "ownership/ownership" } })
        fireEvent.click(screen.getByRole("link", { name: "Sources" }))
        await screen.findByRole("heading", { level: 2, name: "Sources" })
        fireEvent.click(screen.getByRole("link", { name: "Relationships" }))
        expect(await screen.findByRole("combobox", { name: "Type" })).toHaveValue("ownership/ownership")
    })
})

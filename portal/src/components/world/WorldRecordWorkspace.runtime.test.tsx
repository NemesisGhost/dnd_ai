import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../../fixtures/sessionBootstrap"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../../test/authoringHarness"
import type { MockServer } from "../../test/authoringHarness"
import { installRecordReads } from "../../test/worldWorkspaceMocks"
import { CampaignWorldDetailPage } from "../../pages/CampaignWorldDetailPage"

// The runtime panels (an NPC's Run, an organization's members and status) own reads of their own.
// These tests pin that they agree with the workspace after a change, only offer commands the
// server will accept, and keep what was typed.

const C = "c1"
const NOT_FOUND = { status: 404, body: { error: { code: "not_found", message: "m", correlation_id: "x" } } }
const TIME = {
    world_time_id: "t1",
    calendar_id: "cal",
    year: 1,
    month_number: null,
    day: null,
    hour: null,
    minute: null,
    label: null,
    precision: "year",
    sort_key: 1,
    display: "Year 1",
}

interface State {
    canon: string
    lifecycle: string
    hp: number
}

const lifecycleBody = (id: string, type: string, s: State) => ({
    entity_id: id,
    entity_type_code: type,
    canonical_name: "Record",
    canon_status: s.canon,
    lifecycle_status: s.lifecycle,
    row_version: 3,
    lifecycle_managed: true,
    superseded_by: null,
    available_actions:
        s.lifecycle === "archived"
            ? ["restore"]
            : s.canon === "canon"
              ? ["archive"]
              : s.canon === "approved"
              ? ["publish", "return_to_draft"]
              : s.canon === "proposed"
                ? ["approve", "reject", "return_to_draft"]
                : [],
    blocked_actions: [],
})

// Reads that answer with a server error while the flag is set; `failed` counts the answers given.
const fails = { character: false, npc: false, roster: false, failed: 0 }
const failing = () => {
    fails.failed += 1
    return { status: 500, body: {} }
}

function setupNpc(initial: Partial<State> = {}) {
    fails.character = false
    fails.npc = false
    fails.roster = false
    fails.failed = 0
    const state: State = { canon: "approved", lifecycle: "active", hp: 10, ...initial }
    const server = installMockServer()
    server.on("GET", /.*/, NOT_FOUND)
    installRecordReads(server, { campaignId: C, entityId: "n1", entityTypeCode: "npc", canon: state.canon })
    server.on("GET", `/campaigns/${C}/entities/n1/lifecycle`, () => ({ body: lifecycleBody("n1", "npc", state) }))
    server.on("GET", `/campaigns/${C}/characters/n1`, () =>
        fails.character
            ? failing()
            : {
        body: {
            character_id: "n1",
            name: "Mira",
            species_code: "human",
            size_category: "medium",
            current_hit_points: state.hp,
            maximum_hit_points: 20,
            temporary_hit_points: null,
            exhaustion_level: null,
            death_save_successes: null,
            death_save_failures: null,
            current_location_id: null,
            active_encounter_id: null,
            conditions: [],
            resources: [],
        },
    },
    )
    server.on("GET", `/campaigns/${C}/authoring/npcs/n1`, () =>
        fails.npc
            ? failing()
            : {
                  body: {
                      npc_id: "n1",
                      canon_status: state.canon,
                      lifecycle_status: state.lifecycle,
                      row_version: 3,
                      available_actions: ["update"],
                      blocked_actions: [],
                  },
              },
    )
    server.on("POST", `/campaigns/${C}/entities/n1/lifecycle/archive`, () => {
        state.lifecycle = "archived"
        fails.npc = true
        return { body: { entity_id: "n1", canon_status: state.canon, lifecycle_status: "archived", row_version: 4 } }
    })
    server.on("GET", /npc-runtime-options/, { body: { conditions: [], resources: [] } })
    server.on("GET", /world-times/, { body: { items: [TIME], next_cursor: null } })
    server.on("GET", /calendars/, { body: { calendars: [] } })
    server.on("POST", `/campaigns/${C}/entities/n1/lifecycle/publish`, () => {
        state.canon = "canon"
        return { body: { entity_id: "n1", canon_status: "canon", lifecycle_status: "active", row_version: 4 } }
    })
    server.on("POST", `/campaigns/${C}/characters/n1/hit-points`, () => {
        state.hp -= 3
        return { body: { changed: true } }
    })
    return { server, state, ...render(server, "/app/c1/world/character/n1") }
}

function render(server: MockServer, entry: string) {
    void server
    return renderAuthoringRoutes({
        initialEntry: entry,
        bootstrap: bootstrapWith({
            campaigns: [
                { ...sessionBootstrapFixture.campaigns[0]!, campaign_id: C, capabilities: ["canon.edit", "campaign.view"] },
            ],
        }),
        routes: [{ path: "/app/:campaignId/world/:category/:entityId", element: <CampaignWorldDetailPage /> }],
    })
}

const opened = async (name: string) => {
    await screen.findByRole("heading", { level: 1, name })
    await screen.findByRole("navigation", { name: "Record stages" })
}

afterEach(() => vi.unstubAllGlobals())

describe("an NPC's Run section agrees with the workspace", () => {
    it("unlocks as soon as the NPC is published from Review, without a reload", async () => {
        const { server } = setupNpc()
        fireEvent.click(await screen.findByRole("button", { name: "Publish as canon" }))
        const dialog = screen.getByRole("dialog", { name: "Publish as canon?", hidden: true })
        fireEvent.click(within(dialog).getByRole("button", { name: "Publish as canon" }))
        await waitFor(() => expect(screen.getByRole("group", { name: "Record status" })).toHaveTextContent(/Canon/))
        fireEvent.click(screen.getByRole("link", { name: "3. Use in play" }))
        fireEvent.click(await screen.findByRole("link", { name: "Run this NPC" }))
        expect(await screen.findByRole("form", { name: "Adjust hit points" })).toBeVisible()
        await waitFor(() => expect(screen.queryByText(/Publish this NPC to change/)).not.toBeInTheDocument())
        expect(server.calls.filter((c) => c.method === "POST")).toHaveLength(1)
    })

    it("shows a hit point change in Details too", async () => {
        const { server } = setupNpc({ canon: "canon" })
        await opened("Mira")
        const details = () => screen.getByRole("heading", { level: 2, name: "Details" }).closest("section")!
        await waitFor(() =>
            expect(within(details()).getByRole("meter", { name: "Hit points" })).toHaveAttribute("aria-valuenow", "10"),
        )
        fireEvent.click(screen.getByRole("link", { name: "3. Use in play" }))
        fireEvent.click(await screen.findByRole("link", { name: "Run this NPC" }))
        fireEvent.change(await screen.findByRole("combobox", { name: "When this happens" }), { target: { value: "t1" } })
        const form = await screen.findByRole("form", { name: "Adjust hit points" })
        fireEvent.change(within(form).getByRole("textbox", { name: /Change/ }), { target: { value: "-3" } })
        fireEvent.click(within(form).getByRole("button", { name: "Apply hit point change" }))
        await waitFor(() => expect(server.callsTo("POST", `/campaigns/${C}/characters/n1/hit-points`)).toHaveLength(1))
        await screen.findByText("7 of 20")
        fireEvent.click(screen.getByRole("link", { name: "1. Prepare" }))
        await waitFor(() =>
            expect(within(details()).getByRole("meter", { name: "Hit points" })).toHaveAttribute("aria-valuenow", "7"),
        )
    })

    it("withholds the controls for an archived NPC that was published, with no write possible", async () => {
        const { server } = setupNpc({ canon: "canon", lifecycle: "archived" })
        await opened("Mira")
        fireEvent.click(screen.getByRole("link", { name: "3. Use in play" }))
        fireEvent.click(await screen.findByRole("link", { name: "Run this NPC" }))
        expect(await screen.findByText(/This NPC is archived\. Restore it before/)).toBeVisible()
        expect(screen.queryByRole("form", { name: "Adjust hit points" })).not.toBeInTheDocument()
        expect(server.calls.filter((c) => c.method !== "GET")).toHaveLength(0)
    })

    const inSection = (key: string) => within(screen.getByRole("heading", { level: 2, name: key }).closest("section")!)

    it("says a retained read may be out of date, retries by reading only, and keeps unsent input", async () => {
        const { server } = setupNpc({ canon: "approved" })
        await opened("Mira")
        fireEvent.click(screen.getByRole("link", { name: "1. Prepare" }))
        fireEvent.click(await screen.findByRole("link", { name: "Sources" }))
        fireEvent.click(await screen.findByRole("button", { name: "Add source" }))
        fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Field notes" } })
        fireEvent.click(screen.getByRole("link", { name: "2. Review & publish" }))
        // The refresh that follows publishing fails: it must actually be asked for, and answer 500.
        fails.character = true
        fireEvent.click(await screen.findByRole("button", { name: "Publish as canon" }))
        const dialog = screen.getByRole("dialog", { name: "Publish as canon?", hidden: true })
        fireEvent.click(within(dialog).getByRole("button", { name: "Publish as canon" }))
        await waitFor(() => expect(screen.getByRole("group", { name: "Record status" })).toHaveTextContent(/Canon/))
        await waitFor(() => expect(fails.failed).toBeGreaterThan(0))
        fireEvent.click(screen.getByRole("link", { name: "3. Use in play" }))
        const form = await screen.findByRole("form", { name: "Adjust hit points" })
        fireEvent.change(within(form).getByRole("textbox", { name: /Change/ }), { target: { value: "-4" } })
        const run = inSection("Run this NPC")
        expect(await run.findByText(/may be out of date/)).toBeVisible()
        // Reading again recovers; nothing is sent, and nothing typed is lost.
        fails.character = false
        const posts = server.calls.filter((c) => c.method === "POST").length
        fireEvent.click(run.getByRole("button", { name: "Try again" }))
        await waitFor(() => expect(run.queryByText(/may be out of date/)).not.toBeInTheDocument())
        expect(within(screen.getByRole("form", { name: "Adjust hit points" })).getByRole("textbox", { name: /Change/ })).toHaveValue("-4")
        expect(server.calls.filter((c) => c.method === "POST")).toHaveLength(posts)
        fireEvent.click(screen.getByRole("link", { name: "1. Prepare" }))
        fireEvent.click(await screen.findByRole("link", { name: "Sources" }))
        expect(screen.getByLabelText("Title")).toHaveValue("Field notes")
    })

    it("keeps showing the old hit points with a warning when the read after a change fails, then recovers on retry", async () => {
        const { server } = setupNpc({ canon: "canon" })
        await opened("Mira")
        fireEvent.click(screen.getByRole("link", { name: "3. Use in play" }))
        fireEvent.click(await screen.findByRole("link", { name: "Run this NPC" }))
        fireEvent.change(await screen.findByRole("combobox", { name: "When this happens" }), { target: { value: "t1" } })
        await screen.findByText("10 of 20")
        const form = screen.getByRole("form", { name: "Adjust hit points" })
        fireEvent.change(within(form).getByRole("textbox", { name: /Change/ }), { target: { value: "-3" } })
        fails.character = true
        fireEvent.click(within(form).getByRole("button", { name: "Apply hit point change" }))
        await waitFor(() => expect(server.callsTo("POST", `/campaigns/${C}/characters/n1/hit-points`)).toHaveLength(1))
        const run = inSection("Run this NPC")
        expect(await run.findByText(/may be out of date/)).toBeVisible()
        expect(run.getByText("10 of 20")).toBeInTheDocument()
        expect(fails.failed).toBeGreaterThan(0)
        fails.character = false
        fireEvent.click(run.getByRole("button", { name: "Try again" }))
        expect(await run.findByText("7 of 20")).toBeInTheDocument()
        expect(run.queryByText(/may be out of date/)).not.toBeInTheDocument()
        // The retry only read: the change was recorded exactly once.
        expect(server.callsTo("POST", `/campaigns/${C}/characters/n1/hit-points`)).toHaveLength(1)
    })

    it("withholds Run for an NPC the page knows is archived even when its own status read fails", async () => {
        const { server } = setupNpc({ canon: "canon" })
        await opened("Mira")
        fireEvent.click(screen.getByRole("link", { name: "2. Review & publish" }))
        fireEvent.click(await screen.findByRole("link", { name: "Publication" }))
        fireEvent.click(await screen.findByText("More"))
        fireEvent.click(screen.getByRole("button", { name: "Archive" }))
        const dialog = screen.getByRole("dialog", { name: "Archive this record?", hidden: true })
        fireEvent.click(within(dialog).getByRole("button", { name: "Archive" }))
        await waitFor(() => expect(screen.getByRole("group", { name: "Record status" })).toHaveTextContent(/Archived/))
        await waitFor(() => expect(fails.failed).toBeGreaterThan(0))
        fireEvent.click(screen.getByRole("link", { name: "3. Use in play" }))
        fireEvent.click(await screen.findByRole("link", { name: "Run this NPC" }))
        const run = inSection("Run this NPC")
        expect(await run.findByText(/This NPC is archived\. Restore it/)).toBeVisible()
        expect(await run.findByText(/may be out of date/)).toBeVisible()
        for (const name of ["Adjust hit points", "Add a condition", "Adjust a resource", "Move this NPC"]) {
            expect(screen.queryByRole("form", { name })).not.toBeInTheDocument()
        }
        // Reading again changes nothing about eligibility and sends nothing.
        const posts = server.calls.filter((c) => c.method === "POST").length
        fails.npc = false
        fireEvent.click(run.getByRole("button", { name: "Try again" }))
        await waitFor(() => expect(run.queryByText(/may be out of date/)).not.toBeInTheDocument())
        expect(screen.queryByRole("form", { name: "Adjust hit points" })).not.toBeInTheDocument()
        expect(server.calls.filter((c) => c.method === "POST")).toHaveLength(posts)
    })
})

describe("an organization's members and status", () => {
    const orgDetail = {
        organization_id: "o1",
        name: "The Guild",
        summary: null,
        kind_code: "business",
        organization_type_code: "guild",
        status_code: null,
        public_description: null,
        parent: null,
        headquarters: null,
        religion: null,
    }
    const roster = (status: string | null) => ({
        organization_id: "o1",
        status,
        // The real server reports permission, not eligibility: an editor can_edit a draft too.
        can_edit: true,
        status_choices: [{ value: "dissolved", label: "Dissolved" }],
        members: [],
    })

    function setupOrg(initial: Partial<State> = {}, rosterRead: () => object = () => ({ body: roster(null) })) {
        const state: State = { canon: "draft", lifecycle: "active", hp: 0, ...initial }
        const server = installMockServer()
        server.on("GET", /.*/, NOT_FOUND)
        installRecordReads(server, { campaignId: C, entityId: "o1", entityTypeCode: "business" })
        server.on("GET", `/campaigns/${C}/world/organizations/o1`, () => ({
            body: orgDetail,
        }))
        server.on("GET", `/campaigns/${C}/entities/o1/lifecycle`, () => ({ body: lifecycleBody("o1", "business", state) }))
        server.on("GET", `/campaigns/${C}/authoring/organizations/o1`, { body: { available_actions: ["update"], blocked_actions: [] } })
        server.on("GET", `/campaigns/${C}/organizations/o1/members`, rosterRead)
        server.on("GET", /world-times/, { body: { items: [TIME], next_cursor: null } })
        server.on("GET", /calendars/, { body: { calendars: [] } })
        server.on("POST", `/campaigns/${C}/entities/o1/lifecycle/publish`, () => {
            state.canon = "canon"
            return { body: { entity_id: "o1", canon_status: "canon", lifecycle_status: "active", row_version: 4 } }
        })
        render(server, "/app/c1/world/organization/o1?section=members")
        return { server, state }
    }

    it.each([
        ["draft", "active"],
        ["proposed", "active"],
        ["approved", "active"],
        ["superseded", "active"],
        ["canon", "archived"],
    ])("withholds Set status and Add member for a %s (%s) organization, though the roster says can_edit", async (canon, lifecycle) => {
        const { server } = setupOrg({ canon, lifecycle })
        await opened("The Guild")
        expect(await screen.findByText("No members are known.")).toBeInTheDocument()
        expect(await screen.findByText(/organization is (not published yet|archived|replaced)|has been replaced|takes no new events/)).toBeInTheDocument()
        expect(screen.queryByRole("form", { name: "Organization status" })).not.toBeInTheDocument()
        expect(screen.queryByRole("form", { name: "Add a member" })).not.toBeInTheDocument()
        expect(server.calls.filter((c) => c.method !== "GET")).toHaveLength(0)
    })

    it("offers both commands for a published, active organization", async () => {
        setupOrg({ canon: "canon" })
        await opened("The Guild")
        expect(await screen.findByRole("form", { name: "Organization status" })).toBeVisible()
        expect(screen.getByRole("form", { name: "Add a member" })).toBeInTheDocument()
    })

    it("unlocks them when the organization is published, without a reload", async () => {
        setupOrg({ canon: "approved" })
        await opened("The Guild")
        expect(screen.queryByRole("form", { name: "Organization status" })).not.toBeInTheDocument()
        fireEvent.click(screen.getByRole("link", { name: "2. Review & publish" }))
        fireEvent.click(await screen.findByRole("button", { name: "Publish as canon" }))
        const dialog = screen.getByRole("dialog", { name: "Publish as canon?", hidden: true })
        fireEvent.click(within(dialog).getByRole("button", { name: "Publish as canon" }))
        await waitFor(() => expect(screen.getByRole("group", { name: "Record status" })).toHaveTextContent(/Canon/))
        fireEvent.click(screen.getByRole("link", { name: "3. Use in play" }))
        expect(await screen.findByRole("form", { name: "Organization status" })).toBeVisible()
    })

    it("shows a recorded status in Details too", async () => {
        let status: string | null = null
        const state: State = { canon: "canon", lifecycle: "active", hp: 0 }
        const server = installMockServer()
        server.on("GET", /.*/, NOT_FOUND)
        installRecordReads(server, { campaignId: C, entityId: "o1", entityTypeCode: "business" })
        server.on("GET", `/campaigns/${C}/world/organizations/o1`, () => ({ body: { ...orgDetail, status_code: status } }))
        server.on("GET", `/campaigns/${C}/entities/o1/lifecycle`, () => ({ body: lifecycleBody("o1", "business", state) }))
        server.on("GET", `/campaigns/${C}/authoring/organizations/o1`, { body: { available_actions: ["update"], blocked_actions: [] } })
        server.on("GET", `/campaigns/${C}/organizations/o1/members`, () => ({ body: roster(status) }))
        server.on("GET", /world-times/, { body: { items: [TIME], next_cursor: null } })
        server.on("GET", /calendars/, { body: { calendars: [] } })
        server.on("POST", `/campaigns/${C}/organizations/o1/status`, () => {
            status = "dissolved"
            return { body: { organization_state_id: "s", event_id: "e", previous_status_code: null, new_status_code: "dissolved" } }
        })
        render(server, "/app/c1/world/organization/o1?section=members")
        await opened("The Guild")
        const form = await screen.findByRole("form", { name: "Organization status" })
        fireEvent.change(within(form).getByRole("combobox", { name: "New status" }), { target: { value: "dissolved" } })
        fireEvent.change(within(form).getByRole("combobox", { name: "When" }), { target: { value: "t1" } })
        fireEvent.click(within(form).getByRole("button", { name: "Set status" }))
        await waitFor(() => expect(server.callsTo("POST", `/campaigns/${C}/organizations/o1/status`)).toHaveLength(1))
        await screen.findByText("Now: dissolved")
        fireEvent.click(screen.getByRole("link", { name: "1. Prepare" }))
        const details = screen.getByRole("heading", { level: 2, name: "Details" }).closest("section")!
        await waitFor(() => expect(within(details).getByText("Dissolved")).toBeInTheDocument())
    })

    it("keeps the old status with a warning when the roster read after a change fails, then recovers on retry", async () => {
        let status: string | null = null
        const state: State = { canon: "canon", lifecycle: "active", hp: 0 }
        fails.roster = false
        fails.failed = 0
        const server = installMockServer()
        server.on("GET", /.*/, NOT_FOUND)
        installRecordReads(server, { campaignId: C, entityId: "o1", entityTypeCode: "business" })
        server.on("GET", `/campaigns/${C}/world/organizations/o1`, () => ({ body: { ...orgDetail, status_code: status } }))
        server.on("GET", `/campaigns/${C}/entities/o1/lifecycle`, () => ({ body: lifecycleBody("o1", "business", state) }))
        server.on("GET", `/campaigns/${C}/authoring/organizations/o1`, { body: { available_actions: ["update"], blocked_actions: [] } })
        server.on("GET", `/campaigns/${C}/organizations/o1/members`, () => (fails.roster ? failing() : { body: roster(status) }))
        server.on("GET", /world-times/, { body: { items: [TIME], next_cursor: null } })
        server.on("GET", /calendars/, { body: { calendars: [] } })
        server.on("POST", `/campaigns/${C}/organizations/o1/status`, () => {
            status = "dissolved"
            fails.roster = true
            return { body: { organization_state_id: "s", event_id: "e", previous_status_code: null, new_status_code: "dissolved" } }
        })
        render(server, "/app/c1/world/organization/o1?section=sources")
        await opened("The Guild")
        fireEvent.click(await screen.findByRole("button", { name: "Add source" }))
        fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Charter" } })
        fireEvent.click(screen.getByRole("link", { name: "3. Use in play" }))
        const form = await screen.findByRole("form", { name: "Organization status" })
        fireEvent.change(within(form).getByRole("combobox", { name: "New status" }), { target: { value: "dissolved" } })
        fireEvent.change(within(form).getByRole("combobox", { name: "When" }), { target: { value: "t1" } })
        fireEvent.click(within(form).getByRole("button", { name: "Set status" }))
        await waitFor(() => expect(server.callsTo("POST", `/campaigns/${C}/organizations/o1/status`)).toHaveLength(1))
        const members = within(screen.getByRole("heading", { level: 2, name: "Members and status" }).closest("section")!)
        expect(await members.findByText(/may be out of date/)).toBeVisible()
        expect(members.getByText("Now: not recorded")).toBeInTheDocument()
        expect(fails.failed).toBeGreaterThan(0)
        fails.roster = false
        fireEvent.click(members.getByRole("button", { name: "Try again" }))
        expect(await members.findByText("Now: dissolved")).toBeInTheDocument()
        expect(members.queryByText(/may be out of date/)).not.toBeInTheDocument()
        expect(server.callsTo("POST", `/campaigns/${C}/organizations/o1/status`)).toHaveLength(1)
        fireEvent.click(screen.getByRole("link", { name: "1. Prepare" }))
        fireEvent.click(await screen.findByRole("link", { name: "Sources" }))
        expect(screen.getByLabelText("Title")).toHaveValue("Charter")
    })

    it("does not treat an unreadable lifecycle as eligibility", async () => {
        const failing = installMockServer()
        failing.on("GET", /.*/, NOT_FOUND)
        installRecordReads(failing, { campaignId: C, entityId: "o1", entityTypeCode: "business" })
        failing.on("GET", `/campaigns/${C}/world/organizations/o1`, { body: orgDetail })
        failing.on("GET", `/campaigns/${C}/entities/o1/lifecycle`, { status: 500, body: {} })
        failing.on("GET", `/campaigns/${C}/organizations/o1/members`, { body: roster(null) })
        failing.on("GET", `/campaigns/${C}/authoring/organizations/o1`, { body: { available_actions: ["update"], blocked_actions: [] } })
        failing.on("GET", /world-times/, { body: { items: [TIME], next_cursor: null } })
        failing.on("GET", /calendars/, { body: { calendars: [] } })
        render(failing, "/app/c1/world/organization/o1?section=members")
        expect(await screen.findAllByText(/status could not be loaded, so recording members or a status is not offered/)).not.toHaveLength(0)
        expect(await screen.findByText("No members are known.")).toBeInTheDocument()
        expect(screen.queryByRole("form", { name: "Organization status" })).not.toBeInTheDocument()
    })
})

describe("a record the server says is not lifecycle-managed", () => {
    const characterDetail = {
        character_id: "b1",
        name: "Bare",
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
    }

    function open(lifecycle: object) {
        const server = installMockServer()
        server.on("GET", /.*/, NOT_FOUND)
        installRecordReads(server, { campaignId: C, entityId: "b1", entityTypeCode: "character" })
        server.on("GET", `/campaigns/${C}/characters/b1`, { body: characterDetail })
        server.on("GET", `/campaigns/${C}/entities/b1/lifecycle`, lifecycle)
        render(server, "/app/c1/world/character/b1")
        return server
    }

    it("shows its details only: no stages, no publication, no retry guidance", async () => {
        open({
            body: {
                entity_id: "b1",
                entity_type_code: "character",
                canonical_name: "Bare",
                canon_status: "draft",
                lifecycle_status: "active",
                row_version: 1,
                lifecycle_managed: false,
                superseded_by: null,
                available_actions: [],
                blocked_actions: [],
            },
        })
        expect(await screen.findByRole("heading", { level: 1, name: "Bare" })).toBeInTheDocument()
        expect(await screen.findByRole("heading", { level: 2, name: "Overview" })).toBeInTheDocument()
        expect(screen.queryByRole("navigation", { name: "Record stages" })).not.toBeInTheDocument()
        expect(screen.queryByText(/could not be loaded/)).not.toBeInTheDocument()
        expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument()
        expect(screen.queryByRole("group", { name: "Record status" })).not.toBeInTheDocument()
        expect(screen.getByRole("link", { name: "Back to World" })).toBeInTheDocument()
    })

    it("still tells a failed lifecycle read apart, with a way to try again", async () => {
        open({ status: 500, body: {} })
        expect(await screen.findByRole("heading", { level: 1, name: "Bare" })).toBeInTheDocument()
        fireEvent.click(await screen.findByRole("link", { name: "2. Review & publish" }))
        fireEvent.click(await screen.findByRole("link", { name: "Publication" }))
        expect(await screen.findByText(/lifecycle could not be loaded, so no step is shown/)).toBeInTheDocument()
        expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument()
    })
})

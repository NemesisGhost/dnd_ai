import { fireEvent, screen, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import { OrganizationMembers } from "./OrganizationMembers"

const ROSTER_PATH = "/campaigns/c1/organizations/o1/members"

const member = (overrides: object = {}) => ({
    relationship_id: "r1",
    member_entity_id: "m1",
    member_name: "Mira",
    member_type_code: "npc",
    role: "Captain",
    rank: "First",
    is_public: true,
    started: "Year 1",
    ended: null,
    current: true,
    lifecycle_status: "active",
    row_version: 1,
    ...overrides,
})

function roster(overrides: object = {}) {
    return {
        organization_id: "o1",
        status: "dormant",
        can_edit: true,
        status_choices: [
            { value: "active", label: "Active" },
            { value: "banned", label: "Banned" },
        ],
        members: [
            member(),
            member({
                relationship_id: "r2",
                member_name: "Tom",
                role: null,
                rank: null,
                is_public: false,
                ended: "Year 3",
                current: false,
            }),
        ],
        ...overrides,
    }
}

// What the relationship read returns when a row is opened: the version, the start and the actions
// are the server's.
const relationshipView = (overrides: object = {}) => ({
    relationship_id: "r1",
    kind: "membership",
    kind_label: "Membership",
    relationship_type: "membership",
    relationship_type_label: "Membership",
    description: "Sworn in at dawn",
    started_world_time_id: "t1",
    started: "Year 1",
    ended_world_time_id: null,
    ended: null,
    lifecycle_status: "active",
    row_version: 4,
    typed: { role: "Captain", rank: "First", is_public: true },
    participants: [],
    perspectives: [],
    current_status: null,
    available_actions: ["update", "archive", "set_perspective", "end"],
    ...overrides,
})

afterEach(() => {
    vi.unstubAllGlobals()
})

function setup(view: object = roster(), capabilities = ["canon.edit"], props: object = {}) {
    const server = installMockServer()
    server.on("GET", ROSTER_PATH, () => ({ body: view }))
    server.on("GET", /world-times/, {
        body: {
            items: [
                ["t1", 1],
                ["t2", 5],
            ].map(([id, year]) => ({
                world_time_id: id,
                calendar_id: "cal",
                year,
                month_number: null,
                day: null,
                hour: null,
                minute: null,
                label: null,
                precision: "year",
                sort_key: year,
                display: `Year ${year}`,
            })),
            next_cursor: null,
        },
    })
    server.on("GET", /calendars/, { body: { calendars: [] } })
    server.on("GET", /world\/search/, {
        body: {
            items: [{ entity_id: "m2", category: "character", entity_type_code: "npc", name: "Ann", summary: null }],
            next_cursor: null,
        },
    })
    server.on("GET", /authoring\/relationships\/r1$/, () => ({ body: relationshipView() }))
    server.on("POST", /\/organizations\/o1\/status/, {
        body: { organization_state_id: "s1", event_id: "e1", previous_status_code: "dormant", new_status_code: "banned" },
    })
    server.on("POST", /authoring\/relationships$/, { status: 201, body: { relationship_id: "r9" } })
    server.on("POST", /authoring\/relationships\/r1\/(update|end|change-office)/, { body: relationshipView() })
    renderAuthoringRoutes({
        initialEntry: "/app/c1/org",
        bootstrap: bootstrapWith({
            campaigns: [{ ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c1", capabilities }],
        }),
        routes: [
            {
                path: "/app/:campaignId/org",
                element: <OrganizationMembers campaignId="c1" organizationId="o1" {...props} />,
            },
        ],
    })
    return server
}

async function openEditor(name = "Mira") {
    const row = await screen.findByRole("listitem", { name })
    fireEvent.click(within(row).getByRole("button", { name: `Edit membership of ${name}` }))
    return await screen.findByRole("group", { name: `Edit membership of ${name}` })
}

describe("OrganizationMembers", () => {
    it("shows a compact roster with office, rank, visibility and period for editors", async () => {
        setup()
        const mira = await screen.findByRole("listitem", { name: "Mira" })
        expect(mira).toHaveTextContent("Npc")
        expect(mira).toHaveTextContent("Captain (First)")
        expect(mira).toHaveTextContent("Public")
        expect(mira).toHaveTextContent("Since Year 1")
        expect(mira).toHaveTextContent("(current)")
        const tom = screen.getByRole("listitem", { name: "Tom" })
        expect(tom).toHaveTextContent("No office recorded")
        expect(tom).toHaveTextContent("Editors only")
        expect(tom).toHaveTextContent("Year 1 to Year 3")
        expect(within(mira).getByRole("button", { name: "Edit membership of Mira" })).toBeInTheDocument()
        expect(screen.getByRole("form", { name: "Organization status" })).toBeInTheDocument()
    })

    it("keeps Add a member closed until asked, then opens it beside the roster and closes it on Cancel", async () => {
        setup()
        const button = await screen.findByRole("button", { name: "Add a member" })
        expect(screen.queryByRole("form", { name: "Add a member" })).not.toBeInTheDocument()
        expect(button).toHaveAttribute("aria-expanded", "false")
        fireEvent.click(button)
        expect(screen.getByRole("form", { name: "Add a member" })).toBeInTheDocument()
        expect(button).toHaveAttribute("aria-expanded", "true")
        fireEvent.click(screen.getByRole("button", { name: "Cancel" }))
        expect(screen.queryByRole("form", { name: "Add a member" })).not.toBeInTheDocument()
    })

    it("offers readers the roster and no controls", async () => {
        setup(roster({ can_edit: false, status_choices: [], members: [member()] }), [])
        const row = await screen.findByRole("listitem", { name: "Mira" })
        expect(row).toHaveTextContent("Captain (First)")
        expect(row).not.toHaveTextContent("Public")
        expect(screen.queryByRole("button", { name: "Add a member" })).not.toBeInTheDocument()
        expect(screen.queryByRole("button", { name: /Edit membership/ })).not.toBeInTheDocument()
        expect(screen.queryByRole("form", { name: "Organization status" })).not.toBeInTheDocument()
    })

    it("withholds every command while the organization cannot take them, but keeps the roster", async () => {
        setup(roster(), ["canon.edit"], { commandsBlocked: true })
        expect(await screen.findByRole("listitem", { name: "Mira" })).toBeInTheDocument()
        expect(screen.queryByRole("button", { name: "Add a member" })).not.toBeInTheDocument()
        expect(screen.queryByRole("button", { name: /Edit membership/ })).not.toBeInTheDocument()
        expect(screen.queryByRole("form", { name: "Organization status" })).not.toBeInTheDocument()
    })

    it("does not offer to edit an archived membership", async () => {
        setup(roster({ members: [member({ lifecycle_status: "archived" })] }))
        const row = await screen.findByRole("listitem", { name: "Mira" })
        expect(row).toHaveTextContent("Archived")
        expect(row).toHaveTextContent("Restore in Relationships")
        expect(within(row).queryByRole("button")).not.toBeInTheDocument()
    })

    it("says so when there are no members", async () => {
        setup(roster({ members: [] }))
        expect(await screen.findByText("No members are known.")).toBeInTheDocument()
    })

    it("opens a focused editor from the row with the actions the server allows", async () => {
        const server = setup()
        const editor = await openEditor()
        expect(await within(editor).findByRole("button", { name: "Correct details" })).toBeInTheDocument()
        expect(within(editor).getByRole("button", { name: "Change office or rank" })).toBeInTheDocument()
        expect(within(editor).getByRole("button", { name: "End membership" })).toBeInTheDocument()
        expect(server.callsTo("GET", /authoring\/relationships\/r1$/)).toHaveLength(1)
        // Only one form is open at a time, prefilled from the membership.
        const form = await within(editor).findByRole("form", { name: "Correct membership" })
        expect(within(form).getByRole("textbox", { name: "Office or role" })).toHaveValue("Captain")
        expect(within(form).getByRole("textbox", { name: "Rank" })).toHaveValue("First")
        expect(within(editor).queryByRole("form", { name: "End membership" })).not.toBeInTheDocument()
    })

    it("offers no end or change once the membership has ended", async () => {
        const server = setup()
        server.on("GET", /authoring\/relationships\/r1$/, () => ({
            body: relationshipView({ ended: "Year 3", available_actions: ["update", "archive", "set_perspective"] }),
        }))
        const editor = await openEditor()
        expect(await within(editor).findByRole("button", { name: "Correct details" })).toBeInTheDocument()
        expect(within(editor).queryByRole("button", { name: "Change office or rank" })).not.toBeInTheDocument()
        expect(within(editor).queryByRole("button", { name: "End membership" })).not.toBeInTheDocument()
    })

    it("corrects in place with the version and the start it read, keeping the description", async () => {
        const server = setup()
        const editor = await openEditor()
        const form = await within(editor).findByRole("form", { name: "Correct membership" })
        fireEvent.change(within(form).getByRole("textbox", { name: "Office or role" }), { target: { value: "Warden" } })
        fireEvent.change(within(form).getByRole("textbox", { name: "Rank" }), { target: { value: "" } })
        fireEvent.change(within(form).getByRole("combobox", { name: "Known to the public" }), { target: { value: "no" } })
        fireEvent.click(within(form).getByRole("button", { name: "Save correction" }))
        await vi.waitFor(() => expect(server.callsTo("POST", /relationships\/r1\/update/)).toHaveLength(1))
        expect(server.callsTo("POST", /relationships\/r1\/update/)[0]!.body).toEqual({
            expected_row_version: 4,
            description: "Sworn in at dawn",
            started_world_time_id: "t1",
            role: "Warden",
            rank: null,
            is_public: false,
        })
        // Saved: the editor closes, the roster is read again and focus returns to the row's button.
        await vi.waitFor(() => expect(screen.queryByRole("group", { name: /Edit membership of/ })).not.toBeInTheDocument())
        expect(server.callsTo("GET", ROSTER_PATH).length).toBeGreaterThan(1)
        await vi.waitFor(() => expect(screen.getByRole("button", { name: "Edit membership of Mira" })).toHaveFocus())
    })

    it("cancels without writing anything", async () => {
        const server = setup()
        const editor = await openEditor()
        const form = await within(editor).findByRole("form", { name: "Correct membership" })
        fireEvent.change(within(form).getByRole("textbox", { name: "Office or role" }), { target: { value: "Warden" } })
        fireEvent.click(within(form).getByRole("button", { name: "Cancel" }))
        expect(screen.queryByRole("group", { name: /Edit membership of/ })).not.toBeInTheDocument()
        expect(server.callsTo("POST", /authoring\/relationships/)).toHaveLength(0)
        // Opened again, it starts from the saved values, not the abandoned ones.
        const again = await openEditor()
        expect(await within(again).findByRole("textbox", { name: "Office or role" })).toHaveValue("Captain")
    })

    it("records an in-world change of office as one change, with an effective time", async () => {
        const server = setup()
        const editor = await openEditor()
        fireEvent.click(await within(editor).findByRole("button", { name: "Change office or rank" }))
        const form = await within(editor).findByRole("form", { name: "Change office or rank" })
        // Nothing changed yet.
        fireEvent.click(within(form).getByRole("button", { name: "Record change" }))
        expect(await within(form).findByText(/Change the office, the rank or who can see it first/)).toBeInTheDocument()
        fireEvent.change(within(form).getByRole("textbox", { name: "New office or role" }), { target: { value: "Regent" } })
        fireEvent.click(within(form).getByRole("button", { name: "Record change" }))
        expect(await within(form).findByText(/Choose when the change took effect/)).toBeInTheDocument()
        expect(server.callsTo("POST", /relationships\/r1\/change-office/)).toHaveLength(0)
        fireEvent.change(await within(form).findByRole("combobox", { name: "Effective" }), { target: { value: "t2" } })
        fireEvent.click(within(form).getByRole("button", { name: "Record change" }))
        await vi.waitFor(() => expect(server.callsTo("POST", /relationships\/r1\/change-office/)).toHaveLength(1))
        expect(server.callsTo("POST", /relationships\/r1\/change-office/)[0]!.body).toEqual({
            expected_row_version: 4,
            effective_world_time_id: "t2",
            role: "Regent",
            rank: "First",
            is_public: true,
        })
        expect(server.callsTo("POST", /relationships\/r1\/(update|end)$/)).toHaveLength(0)
    })

    it("ends a membership only with a time, and sends the version it read", async () => {
        const server = setup()
        const editor = await openEditor()
        fireEvent.click(await within(editor).findByRole("button", { name: "End membership" }))
        const form = await within(editor).findByRole("form", { name: "End membership" })
        fireEvent.click(within(form).getByRole("button", { name: "End membership" }))
        expect(await within(form).findByText(/Choose when the membership ended/)).toBeInTheDocument()
        expect(server.callsTo("POST", /relationships\/r1\/end/)).toHaveLength(0)
        fireEvent.change(await within(form).findByRole("combobox", { name: "Ended" }), { target: { value: "t2" } })
        fireEvent.click(within(form).getByRole("button", { name: "End membership" }))
        await vi.waitFor(() => expect(server.callsTo("POST", /relationships\/r1\/end/)).toHaveLength(1))
        expect(server.callsTo("POST", /relationships\/r1\/end/)[0]!.body).toEqual({
            expected_row_version: 4,
            ended_world_time_id: "t2",
        })
    })

    it("explains a refused end and keeps what was entered", async () => {
        const server = setup()
        server.on("POST", /relationships\/r1\/end/, {
            status: 400,
            body: { error: { code: "relationship_time_invalid", message: "m", correlation_id: "c" } },
        })
        const editor = await openEditor()
        fireEvent.click(await within(editor).findByRole("button", { name: "End membership" }))
        const form = await within(editor).findByRole("form", { name: "End membership" })
        fireEvent.change(await within(form).findByRole("combobox", { name: "Ended" }), { target: { value: "t1" } })
        fireEvent.click(within(form).getByRole("button", { name: "End membership" }))
        expect(await screen.findByRole("alert")).toHaveTextContent(/end after the start/)
        expect(within(form).getByRole("combobox", { name: "Ended" })).toHaveValue("t1")
        expect(screen.getByRole("group", { name: "Edit membership of Mira" })).toBeInTheDocument()
    })

    it("keeps a correction's values after a refused save, and offers the latest on a stale write", async () => {
        const server = setup()
        server.on("POST", /relationships\/r1\/update/, {
            status: 409,
            body: { error: { code: "membership_overlap", message: "m", correlation_id: "c" } },
        })
        const editor = await openEditor()
        const form = await within(editor).findByRole("form", { name: "Correct membership" })
        fireEvent.change(within(form).getByRole("textbox", { name: "Office or role" }), { target: { value: "Warden" } })
        fireEvent.click(within(form).getByRole("button", { name: "Save correction" }))
        expect(await screen.findByRole("alert")).toHaveTextContent(/already belongs to this organization/)
        expect(within(form).getByRole("textbox", { name: "Office or role" })).toHaveValue("Warden")

        server.on("POST", /relationships\/r1\/update/, {
            status: 409,
            body: { error: { code: "stale_write", message: "m", correlation_id: "c" } },
        })
        fireEvent.click(within(form).getByRole("button", { name: "Save correction" }))
        expect(await screen.findByRole("button", { name: /latest/i })).toBeInTheDocument()
        expect(within(form).getByRole("textbox", { name: "Office or role" })).toHaveValue("Warden")
    })

    it("refuses a status change without a choice and a time", async () => {
        const server = setup()
        const form = await screen.findByRole("form", { name: "Organization status" })
        fireEvent.click(within(form).getByRole("button", { name: "Set status" }))
        expect(await within(form).findByText(/Choose the new status and when/)).toBeInTheDocument()
        expect(server.callsTo("POST", /\/organizations\/o1\/status/)).toHaveLength(0)
    })

    it("sets a status with the time and the status it saw", async () => {
        const server = setup()
        const form = await screen.findByRole("form", { name: "Organization status" })
        fireEvent.change(within(form).getByRole("combobox", { name: "New status" }), { target: { value: "banned" } })
        fireEvent.change(await within(form).findByRole("combobox", { name: "When" }), { target: { value: "t1" } })
        fireEvent.click(within(form).getByRole("button", { name: "Set status" }))
        await vi.waitFor(() => expect(server.callsTo("POST", /\/organizations\/o1\/status/)).toHaveLength(1))
        expect(server.callsTo("POST", /\/organizations\/o1\/status/)[0]!.body).toEqual({
            world_time_id: "t1",
            new_status_code: "banned",
            expected_status: "dormant",
        })
    })

    it("explains a refused status change", async () => {
        const server = setup()
        server.on("POST", /\/organizations\/o1\/status/, {
            status: 409,
            body: { error: { code: "organization_status_unchanged", message: "m", correlation_id: "c" } },
        })
        const form = await screen.findByRole("form", { name: "Organization status" })
        fireEvent.change(within(form).getByRole("combobox", { name: "New status" }), { target: { value: "active" } })
        fireEvent.change(await within(form).findByRole("combobox", { name: "When" }), { target: { value: "t1" } })
        fireEvent.click(within(form).getByRole("button", { name: "Set status" }))
        expect(await screen.findByRole("alert")).toHaveTextContent(/already has that status/)
    })

    it("adds a member only with a start", async () => {
        const server = setup()
        fireEvent.click(await screen.findByRole("button", { name: "Add a member" }))
        const form = screen.getByRole("form", { name: "Add a member" })
        fireEvent.focus(within(form).getByRole("combobox", { name: "Member" }))
        fireEvent.click((await within(form).findAllByRole("option", { name: /Ann/ }))[0]!)
        fireEvent.click(within(form).getByRole("button", { name: "Add member" }))
        expect(await within(form).findByText(/Choose the member and when they joined/)).toBeInTheDocument()
        expect(server.callsTo("POST", /authoring\/relationships/)).toHaveLength(0)
        fireEvent.change(await within(form).findByRole("combobox", { name: "Joined" }), { target: { value: "t1" } })
        fireEvent.change(within(form).getByRole("textbox", { name: "Office or role" }), { target: { value: "Scribe" } })
        fireEvent.click(within(form).getByRole("button", { name: "Add member" }))
        await vi.waitFor(() => expect(server.callsTo("POST", /authoring\/relationships$/)).toHaveLength(1))
        expect(server.callsTo("POST", /authoring\/relationships$/)[0]!.body).toEqual({
            kind: "membership",
            relationship_type: "membership",
            participants: [
                { entity_id: "m2", role: "member" },
                { entity_id: "o1", role: "organization" },
            ],
            description: null,
            started_world_time_id: "t1",
            role: "Scribe",
            rank: null,
            is_public: true,
        })
        // Added: the form closes.
        await vi.waitFor(() => expect(screen.queryByRole("form", { name: "Add a member" })).not.toBeInTheDocument())
    })

    it("records a new time inside a form without nesting a form in it", async () => {
        setup()
        fireEvent.click(await screen.findByRole("button", { name: "Add a member" }))
        const form = screen.getByRole("form", { name: "Add a member" })
        fireEvent.click(await within(form).findByRole("button", { name: "Record a new time" }))
        // A <form> inside a <form> makes a real browser submit the outer one.
        expect(within(form).getByRole("group", { name: "Record a new world time" })).toBeInTheDocument()
        expect(form.querySelector("form")).toBeNull()
        expect(within(form).getByRole("button", { name: "Record time" })).toHaveAttribute("type", "button")
    })

    it("keeps an open row editor and the add form as they were when the status is saved", async () => {
        const server = setup()
        fireEvent.click(await screen.findByRole("button", { name: "Add a member" }))
        const add = screen.getByRole("form", { name: "Add a member" })
        fireEvent.change(within(add).getByRole("textbox", { name: "Office or role" }), { target: { value: "Scribe" } })
        const editor = await openEditor()
        const correct = await within(editor).findByRole("form", { name: "Correct membership" })
        fireEvent.change(within(correct).getByRole("textbox", { name: "Rank" }), { target: { value: "Second" } })

        const status = screen.getByRole("form", { name: "Organization status" })
        fireEvent.change(within(status).getByRole("combobox", { name: "New status" }), { target: { value: "banned" } })
        fireEvent.change(await within(status).findByRole("combobox", { name: "When" }), { target: { value: "t1" } })
        const reads = server.callsTo("GET", ROSTER_PATH).length
        fireEvent.click(within(status).getByRole("button", { name: "Set status" }))
        await vi.waitFor(() => expect(server.callsTo("GET", ROSTER_PATH).length).toBeGreaterThan(reads))

        expect(within(screen.getByRole("form", { name: "Add a member" })).getByRole("textbox", { name: "Office or role" })).toHaveValue("Scribe")
        expect(within(screen.getByRole("form", { name: "Correct membership" })).getByRole("textbox", { name: "Rank" })).toHaveValue("Second")
    })

    it("keeps the status form as it was when a membership is saved", async () => {
        const server = setup()
        const status = await screen.findByRole("form", { name: "Organization status" })
        fireEvent.change(within(status).getByRole("combobox", { name: "New status" }), { target: { value: "banned" } })
        const editor = await openEditor()
        const form = await within(editor).findByRole("form", { name: "Correct membership" })
        fireEvent.change(within(form).getByRole("textbox", { name: "Rank" }), { target: { value: "Second" } })
        fireEvent.click(within(form).getByRole("button", { name: "Save correction" }))
        await vi.waitFor(() => expect(server.callsTo("POST", /relationships\/r1\/update/)).toHaveLength(1))
        await vi.waitFor(() => expect(screen.queryByRole("group", { name: /Edit membership of/ })).not.toBeInTheDocument())
        expect(within(screen.getByRole("form", { name: "Organization status" })).getByRole("combobox", { name: "New status" })).toHaveValue("banned")
    })
})

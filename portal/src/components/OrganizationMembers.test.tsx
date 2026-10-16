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
        members: [member(), member({ relationship_id: "r2", member_name: "Tom", role: null, rank: null, is_public: false, ended: "Year 3", current: false })],
        ...overrides,
    }
}

afterEach(() => {
    vi.unstubAllGlobals()
})

function setup(view: object = roster(), capabilities = ["canon.edit"]) {
    const server = installMockServer()
    server.on("GET", ROSTER_PATH, () => ({ body: view }))
    server.on("GET", /world-times/, {
        body: {
            items: [
                {
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
                },
            ],
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
    server.on("POST", /\/organizations\/o1\/status/, {
        body: { organization_state_id: "s1", event_id: "e1", previous_status_code: "dormant", new_status_code: "banned" },
    })
    server.on("POST", /authoring\/relationships/, { status: 201, body: { relationship_id: "r9" } })
    renderAuthoringRoutes({
        initialEntry: "/app/c1/org",
        bootstrap: bootstrapWith({
            campaigns: [{ ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c1", capabilities }],
        }),
        routes: [
            { path: "/app/:campaignId/org", element: <OrganizationMembers campaignId="c1" organizationId="o1" /> },
        ],
    })
    return server
}

describe("OrganizationMembers", () => {
    it("shows the roster with offices, ended and private stints for editors", async () => {
        setup()
        expect(await screen.findByText(/Mira, Captain \(First\): from Year 1/)).toBeInTheDocument()
        expect(screen.getByText(/Tom: from Year 1? ?until Year 3/)).toBeInTheDocument()
        expect(screen.getByText(/Tom:.*\(private\)/)).toBeInTheDocument()
        expect(screen.getByRole("form", { name: "Add a member" })).toBeInTheDocument()
    })

    it("offers readers the roster and no controls", async () => {
        setup(roster({ can_edit: false, status_choices: [], members: [member()] }), [])
        expect(await screen.findByText(/Mira, Captain/)).toBeInTheDocument()
        expect(screen.queryByRole("form", { name: "Add a member" })).not.toBeInTheDocument()
        expect(screen.queryByRole("form", { name: "Organization status" })).not.toBeInTheDocument()
    })

    it("says so when there are no members", async () => {
        setup(roster({ members: [] }))
        expect(await screen.findByText("No members are known.")).toBeInTheDocument()
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
        const form = await screen.findByRole("form", { name: "Add a member" })
        fireEvent.focus(within(form).getByRole("combobox", { name: "Member" }))
        fireEvent.click((await within(form).findAllByRole("option", { name: /Ann/ }))[0]!)
        fireEvent.click(within(form).getByRole("button", { name: "Add member" }))
        expect(await within(form).findByText(/Choose the member and when they joined/)).toBeInTheDocument()
        expect(server.callsTo("POST", /authoring\/relationships/)).toHaveLength(0)
        fireEvent.change(await within(form).findByRole("combobox", { name: "Joined" }), { target: { value: "t1" } })
        fireEvent.change(within(form).getByRole("textbox", { name: "Office or role" }), { target: { value: "Scribe" } })
        fireEvent.click(within(form).getByRole("button", { name: "Add member" }))
        await vi.waitFor(() => expect(server.callsTo("POST", /authoring\/relationships/)).toHaveLength(1))
        expect(server.callsTo("POST", /authoring\/relationships/)[0]!.body).toEqual({
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
    })
})

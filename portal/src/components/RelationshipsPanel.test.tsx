import { fireEvent, screen, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import type { WorldKind } from "./world/worldStages"
import { RelationshipsPanel } from "./RelationshipsPanel"

const BASE = "/campaigns/c1/authoring/relationships"

const OPTIONS = {
    can_create: true,
    kinds: [
        {
            code: "employment",
            label: "Employment",
            types: ["employment"],
            roles: ["employer", "employee"],
            fixed_roles: ["employer", "employee"],
        },
        {
            code: "family",
            label: "Family",
            types: ["family"],
            roles: ["parent", "child", "other"],
            fixed_roles: null,
        },
    ],
    limits: {
        text_max_length: 4000,
        short_text_max_length: 200,
        stance_min: -100,
        stance_max: 100,
        min_participants: 2,
        max_participants: 20,
    },
}

const EXTRA_KINDS = [
    {
        code: "membership",
        label: "Membership",
        types: ["membership"],
        roles: ["member", "organization"],
        fixed_roles: ["member", "organization"],
    },
    {
        code: "route",
        label: "Route",
        types: ["route"],
        roles: ["origin", "destination"],
        fixed_roles: ["origin", "destination"],
    },
    {
        code: "general",
        label: "Other connection",
        types: ["parent_of", "allied_with"],
        roles: ["subject", "object"],
        fixed_roles: null,
    },
]

const participant = (id: string, name: string, role: string, label: string) => ({
    entity_id: id,
    name,
    entity_type_code: "npc",
    canon_status: "canon",
    lifecycle_status: "active",
    role,
    role_label: label,
})

const SUMMARY = {
    relationship_id: "r1",
    kind: "family",
    relationship_type: "family",
    relationship_type_label: "Family",
    description: null,
    lifecycle_status: "active",
    ended: false,
    is_public: null,
    row_version: 2,
    participants: [participant("e1", "Mira", "parent", "Parent"), participant("e2", "Tom", "child", "Child")],
}

const VIEW = {
    relationship_id: "r1",
    kind: "family",
    kind_label: "Family",
    relationship_type: "family",
    relationship_type_label: "Family",
    description: "Kin.",
    started_world_time_id: "t1",
    started: "Year 1",
    ended_world_time_id: null,
    ended: null,
    lifecycle_status: "active",
    row_version: 2,
    typed: { family_unit_name: "House Vale" },
    participants: SUMMARY.participants,
    perspectives: [],
    current_status: null,
    available_actions: ["update", "archive", "set_perspective", "end"],
}

afterEach(() => {
    vi.unstubAllGlobals()
})

interface SetupOptions {
    capabilities?: string[]
    kind?: WorldKind
    entityId?: string
    membersHref?: string
    summary?: object
    view?: object
}

function setup(capabilitiesOrOptions: string[] | SetupOptions = ["canon.edit"]) {
    const {
        capabilities = ["canon.edit"],
        kind,
        entityId = "e1",
        membersHref,
        summary = SUMMARY,
        view = VIEW,
    } = Array.isArray(capabilitiesOrOptions) ? { capabilities: capabilitiesOrOptions } : capabilitiesOrOptions
    const server = installMockServer()
    server.on("GET", `${BASE}/options`, { body: { ...OPTIONS, kinds: [...OPTIONS.kinds, ...EXTRA_KINDS] } })
    server.on("GET", /authoring\/relationships\?entity_id=/, { body: { items: [summary] } })
    server.on("GET", `${BASE}/r1`, () => ({ body: view }))
    server.on("GET", /world-times/, { body: { items: [], next_cursor: null, can_create: true } })
    server.on("GET", /calendars/, { body: { items: [], can_create: true } })
    server.on("GET", /world\/search/, {
        body: {
            items: [{ entity_id: "e3", category: "character", entity_type_code: "npc", name: "Ann", summary: null }],
            next_cursor: null,
        },
    })
    server.on("POST", new RegExp(BASE), { body: { ...VIEW, changed: true } })
    renderAuthoringRoutes({
        initialEntry: "/app/c1/panel",
        bootstrap: bootstrapWith({
            campaigns: [{ ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c1", capabilities }],
        }),
        routes: [
            {
                path: "/app/:campaignId/panel",
                element: <RelationshipsPanel campaignId="c1" entityId={entityId} kind={kind} membersHref={membersHref} />,
            },
        ],
    })
    return server
}

describe("RelationshipsPanel", () => {
    it("sends no request and shows nothing to people who cannot edit", async () => {
        const server = setup([])
        await new Promise((resolve) => setTimeout(resolve, 50))
        expect(screen.queryByRole("heading", { name: "Relationships" })).not.toBeInTheDocument()
        expect(server.callsTo("GET", /authoring\/relationships/)).toHaveLength(0)
    })

    it("lists the relationships of the entity", async () => {
        setup()
        expect(await screen.findByText(/Mira \(Parent\) and Tom \(Child\): Family/)).toBeInTheDocument()
    })

    it("opens a relationship and archives it with the version it saw", async () => {
        const server = setup()
        fireEvent.click(await screen.findByRole("button", { name: "Open family" }))
        expect(await screen.findByText(/Family: Family, from Year 1/)).toBeInTheDocument()
        fireEvent.click(await screen.findByRole("button", { name: "Archive relationship" }))
        await vi.waitFor(() => expect(server.callsTo("POST", `${BASE}/r1/archive`)).toHaveLength(1))
        expect(server.callsTo("POST", `${BASE}/r1/archive`)[0]!.body).toEqual({ expected_row_version: 2 })
    })

    it("saves a perspective after checking the ratings", async () => {
        const server = setup()
        fireEvent.click(await screen.findByRole("button", { name: "Open family" }))
        const form = await screen.findByRole("form", { name: "Set perspective" })
        fireEvent.change(within(form).getByRole("textbox", { name: "Affinity" }), { target: { value: "150" } })
        fireEvent.click(within(form).getByRole("button", { name: "Save perspective" }))
        expect(await within(form).findByText(/whole number from -100 to 100/)).toBeInTheDocument()
        expect(server.callsTo("POST", `${BASE}/r1/perspectives`)).toHaveLength(0)
        fireEvent.change(within(form).getByRole("textbox", { name: "Affinity" }), { target: { value: "40" } })
        fireEvent.click(within(form).getByRole("button", { name: "Save perspective" }))
        await vi.waitFor(() => expect(server.callsTo("POST", `${BASE}/r1/perspectives`)).toHaveLength(1))
        expect(server.callsTo("POST", `${BASE}/r1/perspectives`)[0]!.body).toMatchObject({
            expected_row_version: 2,
            holder_entity_id: "e1",
            affinity: 40,
            trust: null,
        })
    })

    it("adds a relationship with both roles, found through search", async () => {
        const server = setup()
        const form = await screen.findByRole("form", { name: "Add a relationship" })
        fireEvent.change(within(form).getByRole("combobox", { name: "Kind" }), { target: { value: "employment" } })
        fireEvent.change(await within(form).findByRole("combobox", { name: "Type" }), { target: { value: "employment" } })
        fireEvent.change(within(form).getByRole("combobox", { name: "This record is the" }), {
            target: { value: "employer" },
        })
        fireEvent.change(within(form).getByRole("combobox", { name: "The other participant is the" }), {
            target: { value: "employee" },
        })
        fireEvent.click(within(form).getByRole("button", { name: "Add relationship" }))
        expect(await within(form).findByText(/Choose the kind, the type, both roles/)).toBeInTheDocument()
        expect(server.callsTo("POST", BASE)).toHaveLength(0)
        const search = within(form).getByRole("combobox", { name: "Other participant" })
        fireEvent.focus(search)
        fireEvent.click(await within(form).findByRole("option", { name: /Ann/ }))
        fireEvent.change(within(form).getByRole("textbox", { name: "Job title" }), { target: { value: "Cook" } })
        fireEvent.click(within(form).getByRole("button", { name: "Add relationship" }))
        await vi.waitFor(() => expect(server.callsTo("POST", BASE)).toHaveLength(1))
        expect(server.callsTo("POST", BASE)[0]!.body).toMatchObject({
            kind: "employment",
            relationship_type: "employment",
            participants: [
                { entity_id: "e1", role: "employer" },
                { entity_id: "e3", role: "employee" },
            ],
            job_title: "Cook",
        })
    })

    it("explains a refused creation", async () => {
        const server = setup()
        server.on("POST", BASE, {
            status: 400,
            body: { error: { code: "participant_invalid", message: "m", correlation_id: "c" } },
        })
        const form = await screen.findByRole("form", { name: "Add a relationship" })
        fireEvent.change(within(form).getByRole("combobox", { name: "Kind" }), { target: { value: "family" } })
        fireEvent.change(await within(form).findByRole("combobox", { name: "Type" }), { target: { value: "family" } })
        fireEvent.change(within(form).getByRole("combobox", { name: "This record is the" }), { target: { value: "parent" } })
        fireEvent.change(within(form).getByRole("combobox", { name: "The other participant is the" }), { target: { value: "child" } })
        fireEvent.focus(within(form).getByRole("combobox", { name: "Other participant" }))
        fireEvent.click(await within(form).findByRole("option", { name: /Ann/ }))
        fireEvent.click(within(form).getByRole("button", { name: "Add relationship" }))
        expect(await screen.findByRole("alert")).toHaveTextContent(/Choose published places/)
    })
})

describe("RelationshipsPanel: terminology and placement", () => {
    const kindsOffered = async () => {
        const form = await screen.findByRole("form", { name: "Add a relationship" })
        return within(within(form).getByRole("combobox", { name: "Kind" }))
            .getAllByRole("option")
            .map((option) => option.textContent)
    }

    it("says what relationships are for and what they never do", async () => {
        setup()
        const note = await screen.findByText(/Relationships describe the story world/)
        expect(note).toHaveTextContent(/never decide who can see or play a character/)
        expect(note).toHaveTextContent(/Character access/)
        expect(note).toHaveTextContent(/Members and offices/)
    })

    it("offers a route only on a place", async () => {
        setup({ kind: "place" })
        expect(await kindsOffered()).toContain("Route")
    })

    it.each<WorldKind>(["npc", "pc", "organization", "religion", "character"])(
        "does not offer a route on %s",
        async (kind) => {
            setup({ kind })
            expect(await kindsOffered()).not.toContain("Route")
        },
    )

    it("leaves the kinds to the server when it is not told what the record is", async () => {
        setup()
        expect(await kindsOffered()).toContain("Route")
    })

    it("never offers Membership in the Add form, and points to Members and offices instead", async () => {
        setup({ kind: "organization", membersHref: "?section=members" })
        expect(await kindsOffered()).not.toContain("Membership")
        const form = screen.getByRole("form", { name: "Add a relationship" })
        expect(within(form).getByRole("link", { name: "Members and offices" })).toHaveAttribute(
            "href",
            "/app/c1/panel?section=members",
        )
    })

    it("tells a character's editor to open the organization to add a membership", async () => {
        setup({ kind: "npc" })
        await kindsOffered()
        expect(screen.getByText(/open the organization.s Members and offices/)).toBeInTheDocument()
    })

    it("explains containment and parent bodies next to the general parent_of type", async () => {
        setup({ kind: "place" })
        const form = await screen.findByRole("form", { name: "Add a relationship" })
        fireEvent.change(within(form).getByRole("combobox", { name: "Kind" }), { target: { value: "general" } })
        expect(await within(form).findByText(/use the place.s parent/)).toBeInTheDocument()
        expect(within(form).getByText(/Parent organization field/)).toBeInTheDocument()
    })
})

describe("RelationshipsPanel: a membership", () => {
    const MEMBERSHIP = {
        ...SUMMARY,
        kind: "membership",
        relationship_type: "membership",
        relationship_type_label: "Membership",
        participants: [
            { ...participant("e1", "Varek", "member", "Member"), entity_type_code: "npc" },
            {
                ...participant("org1", "The Gilded Scale", "organization", "Organization"),
                entity_type_code: "organization",
            },
        ],
    }
    const MEMBERSHIP_VIEW = {
        ...VIEW,
        kind: "membership",
        kind_label: "Membership",
        relationship_type: "membership",
        relationship_type_label: "Membership",
        typed: { role: "Head Clerk", rank: "Third", is_public: false },
        participants: MEMBERSHIP.participants,
        available_actions: ["update", "end", "archive", "set_perspective"],
    }

    it("links from the member's side to the organization's members section", async () => {
        setup({ summary: MEMBERSHIP, view: MEMBERSHIP_VIEW, kind: "npc" })
        expect(await screen.findByRole("link", { name: "Open organization members" })).toHaveAttribute(
            "href",
            "/app/c1/world/organization/org1?section=members",
        )
    })

    it("links from the organization's own page to its Members and offices section", async () => {
        setup({
            summary: MEMBERSHIP,
            view: MEMBERSHIP_VIEW,
            kind: "organization",
            entityId: "org1",
            membersHref: "?section=members",
        })
        const link = await screen.findByRole("link", { name: "Manage in Members and offices" })
        expect(link).toHaveAttribute("href", "/app/c1/panel?section=members")
    })

    it("shows office, rank and visibility read-only, without the correct and End forms", async () => {
        setup({ summary: MEMBERSHIP, view: MEMBERSHIP_VIEW, kind: "npc" })
        fireEvent.click(await screen.findByRole("button", { name: "Open membership" }))
        expect(await screen.findByText("Head Clerk")).toBeInTheDocument()
        expect(screen.getByText("Third")).toBeInTheDocument()
        expect(screen.getByText("No, only editors see it")).toBeInTheDocument()
        expect(screen.queryByRole("form", { name: "Edit relationship" })).toBeNull()
        expect(screen.queryByRole("form", { name: "End relationship" })).toBeNull()
        expect(screen.queryByRole("button", { name: "Save relationship" })).toBeNull()
        expect(screen.queryByRole("button", { name: "End relationship" })).toBeNull()
    })

    it("keeps Archive and each participant's view, which exist nowhere else", async () => {
        const server = setup({ summary: MEMBERSHIP, view: MEMBERSHIP_VIEW, kind: "npc" })
        fireEvent.click(await screen.findByRole("button", { name: "Open membership" }))
        expect(await screen.findByRole("form", { name: "Set perspective" })).toBeInTheDocument()
        expect(screen.getByText("How each participant sees it")).toBeInTheDocument()
        fireEvent.click(screen.getByRole("button", { name: "Archive relationship" }))
        await vi.waitFor(() => expect(server.callsTo("POST", `${BASE}/r1/archive`)).toHaveLength(1))
        expect(server.callsTo("POST", `${BASE}/r1/archive`)[0]!.body).toEqual({ expected_row_version: 2 })
    })

    it("keeps Restore for an archived membership", async () => {
        const archived = { ...MEMBERSHIP_VIEW, lifecycle_status: "archived", available_actions: ["restore"] }
        const server = setup({
            summary: { ...MEMBERSHIP, lifecycle_status: "archived" },
            view: archived,
            kind: "npc",
        })
        fireEvent.click(await screen.findByRole("button", { name: "Open membership" }))
        fireEvent.click(await screen.findByRole("button", { name: "Restore relationship" }))
        await vi.waitFor(() => expect(server.callsTo("POST", `${BASE}/r1/restore`)).toHaveLength(1))
    })

    it("still edits other kinds in place, with the correct and End forms", async () => {
        setup({ kind: "npc" })
        fireEvent.click(await screen.findByRole("button", { name: "Open family" }))
        expect(await screen.findByRole("form", { name: "Edit relationship" })).toBeInTheDocument()
        expect(screen.getByRole("form", { name: "End relationship" })).toBeInTheDocument()
    })
})

import { cleanup, fireEvent, screen, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import policy from "../fixtures/relationshipPolicy.json"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import type { WorldKind } from "./world/worldStages"
import { RelationshipsPanel } from "./RelationshipsPanel"

const BASE = "/campaigns/c1/authoring/relationships"

interface PolicyType {
    code: string
    kind: string
}
interface Policy {
    relationship_types: PolicyType[]
    pairings: Record<string, { relationship_type: string }[]>
}
const POLICY = policy as Policy

const KIND_LABELS: Record<string, string> = {
    family: "Family",
    employment: "Employment",
    ownership: "Ownership",
    membership: "Membership",
    route: "Route",
    political: "Political",
    general: "Other connection",
}

// The kind catalog the server derives from the same policy.
const KINDS = Object.entries(KIND_LABELS).map(([code, label]) => ({
    code,
    label,
    types: POLICY.relationship_types.filter((t) => t.kind === code).map((t) => t.code),
    roles: [],
    fixed_roles: null,
}))

const LIMITS = {
    text_max_length: 4000,
    short_text_max_length: 200,
    stance_min: -100,
    stance_max: 100,
    min_participants: 2,
    max_participants: 20,
}

// What the options endpoint answers for a record of this entity type.
function optionsFor(entityType: string, kinds: { code: string; types: string[] }[] = KINDS) {
    const types = new Set(kinds.flatMap((k) => k.types))
    return {
        can_create: true,
        kinds,
        relationship_types: POLICY.relationship_types,
        limits: LIMITS,
        for_entity: {
            entity_id: "e1",
            entity_type_code: entityType,
            pairings: (POLICY.pairings[entityType] ?? []).filter((p) => types.has(p.relationship_type)),
        },
    }
}

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
    policy_conflicts: [],
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
    policy_conflicts: [],
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
    // The record's entity type, which decides the pairings the server offers it.
    entityType?: string
    kinds?: { code: string; types: string[] }[]
}

function setup(capabilitiesOrOptions: string[] | SetupOptions = ["canon.edit"]) {
    const {
        capabilities = ["canon.edit"],
        kind,
        entityId = "e1",
        membersHref,
        summary = SUMMARY,
        view = VIEW,
        entityType = "npc",
        kinds = KINDS,
    } = Array.isArray(capabilitiesOrOptions) ? { capabilities: capabilitiesOrOptions } : capabilitiesOrOptions
    const server = installMockServer()
    server.on("GET", /authoring\/relationships\/options/, { body: optionsFor(entityType, kinds) })
    server.on("GET", /authoring\/relationships\?entity_id=/, { body: { items: [summary] } })
    server.on("GET", `${BASE}/r1`, () => ({ body: view }))
    server.on("GET", /world-times/, { body: { items: [], next_cursor: null, can_create: true } })
    server.on("GET", /calendars/, { body: { items: [], can_create: true } })
    // Like the server, answer only with the entity types asked for.
    server.on("GET", /world\/search/, (call) => {
        const types = new URLSearchParams(call.path.split("?")[1]).getAll("entity_type")
        const code = types.length === 0 || types.includes("npc") ? "npc" : types[0]!
        return {
            body: {
                items: [{ entity_id: "e3", category: "character", entity_type_code: code, name: "Ann", summary: null }],
                next_cursor: null,
            },
        }
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

// When the chosen role leaves the other participant only one role, it is read-only, not a choice.
function chooseOtherRole(form: HTMLElement, value: string) {
    const select = within(form).queryByRole("combobox", { name: "The other participant is the" })
    if (select !== null) fireEvent.change(select, { target: { value } })
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
        fireEvent.change(await within(form).findByRole("combobox", { name: "Type" }), {
            target: { value: "employment/employment" },
        })
        fireEvent.change(within(form).getByRole("combobox", { name: "This record is the" }), {
            target: { value: "employer" },
        })
        chooseOtherRole(form, "employee")
        fireEvent.click(within(form).getByRole("button", { name: "Add relationship" }))
        expect(await within(form).findByText(/Choose the type, both roles/)).toBeInTheDocument()
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
        fireEvent.change(await within(form).findByRole("combobox", { name: "Type" }), {
            target: { value: "family/family" },
        })
        fireEvent.change(within(form).getByRole("combobox", { name: "This record is the" }), { target: { value: "parent" } })
        chooseOtherRole(form, "child")
        fireEvent.focus(within(form).getByRole("combobox", { name: "Other participant" }))
        fireEvent.click(await within(form).findByRole("option", { name: /Ann/ }))
        fireEvent.click(within(form).getByRole("button", { name: "Add relationship" }))
        expect(await screen.findByRole("alert")).toHaveTextContent(/Choose published places/)
    })
})

describe("RelationshipsPanel: terminology and placement", () => {
    // The type choices offered, as "kind/type" codes.
    const kindsOffered = async () => {
        const form = await screen.findByRole("form", { name: "Add a relationship" })
        return within(within(form).getByRole("combobox", { name: "Type" }))
            .getAllByRole("option")
            .map((option) => (option as HTMLOptionElement).value)
    }

    it("says what relationships are for and what they never do", async () => {
        setup()
        const note = await screen.findByText(/Relationships describe the story world/)
        expect(note).toHaveTextContent(/never decide who can see or play a character/)
        expect(note).toHaveTextContent(/Character access/)
        expect(note).toHaveTextContent(/Members and offices/)
    })

    it("asks for the options of this record", async () => {
        const server = setup({ entityId: "e1" })
        await kindsOffered()
        expect(server.callsTo("GET", /relationships\/options\?entity_id=e1$/)).toHaveLength(1)
    })

    it("offers a route on a place", async () => {
        setup({ kind: "place", entityType: "settlement" })
        expect(await kindsOffered()).toContain("route/route")
    })

    it.each([
        ["npc", "npc"],
        ["pc", "player_character"],
        ["organization", "organization"],
    ] as [WorldKind, string][])("does not offer a route on %s", async (kind, entityType) => {
        setup({ kind, entityType })
        expect(await kindsOffered()).not.toContain("route/route")
    })

    it.each(["npc", "player_character"])(
        "offers %s no place-only type, and ownership, control and worship",
        async (entityType) => {
            setup({ entityType })
            const offered = await kindsOffered()
            for (const type of ["adjacency", "capital_of", "parent_of", "route"]) {
                expect(offered.map((v) => v.split("/")[1])).not.toContain(type)
            }
            expect(offered).toEqual(
                expect.arrayContaining(["ownership/ownership", "political/control", "general/worship"]),
            )
        },
    )

    it("never offers Membership in the Add form, and points to Members and offices instead", async () => {
        setup({ kind: "organization", membersHref: "?section=members" })
        expect(await kindsOffered()).not.toContain("membership/membership")
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
        setup({ kind: "place", entityType: "settlement" })
        const form = await screen.findByRole("form", { name: "Add a relationship" })
        fireEvent.change(within(form).getByRole("combobox", { name: "Type" }), { target: { value: "general/parent_of" } })
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

describe("RelationshipsPanel: the type decides the kind", () => {
    const KIND = (code: string, types: string[]) => ({ code, label: code[0]!.toUpperCase() + code.slice(1), types })
    const searchAndPick = async (form: HTMLElement) => {
        fireEvent.focus(within(form).getByRole("combobox", { name: "Other participant" }))
        fireEvent.click(await within(form).findByRole("option", { name: /Ann/ }))
    }

    it("has no separate Kind selector, and groups the types by kind", async () => {
        setup()
        const form = await screen.findByRole("form", { name: "Add a relationship" })
        expect(within(form).queryByRole("combobox", { name: "Kind" })).toBeNull()
        const type = within(form).getByRole("combobox", { name: "Type" })
        const groups = Array.from(type.querySelectorAll("optgroup")).map((g) => g.label)
        expect(groups).toEqual(expect.arrayContaining(["Employment", "Family", "Other connection"]))
        expect(within(form).queryByRole("combobox", { name: "This record is the" })).toBeNull()
    })

    it("submits the kind the chosen type belongs to", async () => {
        const server = setup({ kind: "place", entityType: "settlement" })
        const form = await screen.findByRole("form", { name: "Add a relationship" })
        fireEvent.change(within(form).getByRole("combobox", { name: "Type" }), { target: { value: "general/parent_of" } })
        fireEvent.change(await within(form).findByRole("combobox", { name: "This record is the" }), {
            target: { value: "subject" },
        })
        chooseOtherRole(form, "object")
        await searchAndPick(form)
        fireEvent.click(within(form).getByRole("button", { name: "Add relationship" }))
        await vi.waitFor(() => expect(server.callsTo("POST", BASE)).toHaveLength(1))
        expect(server.callsTo("POST", BASE)[0]!.body).toMatchObject({ kind: "general", relationship_type: "parent_of" })
    })

    it("clears roles and kind fields when the choice moves to another kind, and submits no stale value", async () => {
        const server = setup()
        const form = await screen.findByRole("form", { name: "Add a relationship" })
        fireEvent.change(within(form).getByRole("combobox", { name: "Type" }), { target: { value: "employment/employment" } })
        fireEvent.change(await within(form).findByRole("textbox", { name: "Job title" }), { target: { value: "Cook" } })
        fireEvent.change(within(form).getByRole("combobox", { name: "This record is the" }), { target: { value: "employer" } })
        fireEvent.change(within(form).getByRole("combobox", { name: "Type" }), { target: { value: "family/family" } })
        expect(within(form).queryByRole("textbox", { name: "Job title" })).toBeNull()
        expect(within(form).getByRole("combobox", { name: "This record is the" })).toHaveValue("")
        fireEvent.change(within(form).getByRole("combobox", { name: "This record is the" }), { target: { value: "parent" } })
        chooseOtherRole(form, "child")
        await searchAndPick(form)
        fireEvent.click(within(form).getByRole("button", { name: "Add relationship" }))
        await vi.waitFor(() => expect(server.callsTo("POST", BASE)).toHaveLength(1))
        const body = server.callsTo("POST", BASE)[0]!.body as Record<string, unknown>
        expect(body).toMatchObject({ kind: "family", relationship_type: "family" })
        expect(body).not.toHaveProperty("job_title")
        // Back to employment: the earlier title is not remembered.
        fireEvent.change(within(form).getByRole("combobox", { name: "Type" }), { target: { value: "employment/employment" } })
        expect(await within(form).findByRole("textbox", { name: "Job title" })).toHaveValue("")
    })

    it("selects a single available type and shows it as a labelled read-only value", async () => {
        const server = setup({ kinds: [KIND("employment", ["employment"])] })
        const form = await screen.findByRole("form", { name: "Add a relationship" })
        const value = within(form).getByRole("textbox", { name: "Type" })
        expect(value).toHaveValue("employment")
        expect(value).toHaveAttribute("readonly")
        expect(within(form).queryByRole("combobox", { name: "Type" })).toBeNull()
        fireEvent.change(within(form).getByRole("combobox", { name: "This record is the" }), { target: { value: "employer" } })
        chooseOtherRole(form, "employee")
        await searchAndPick(form)
        fireEvent.click(within(form).getByRole("button", { name: "Add relationship" }))
        await vi.waitFor(() => expect(server.callsTo("POST", BASE)).toHaveLength(1))
        expect(server.callsTo("POST", BASE)[0]!.body).toMatchObject({ kind: "employment", relationship_type: "employment" })
    })

    it("says so and offers no submission when no type is available", async () => {
        setup({ kinds: [] })
        const form = await screen.findByRole("form", { name: "Add a relationship" })
        expect(within(form).getByText(/No relationship types are available for this record/)).toBeInTheDocument()
        expect(within(form).queryByRole("button", { name: "Add relationship" })).toBeNull()
        expect(within(form).queryByRole("combobox")).toBeNull()
    })

    it("also treats a kind that lists no type as unavailable", async () => {
        setup({ kinds: [KIND("family", [])] })
        const form = await screen.findByRole("form", { name: "Add a relationship" })
        expect(within(form).getByText(/No relationship types are available/)).toBeInTheDocument()
    })

    it("tells two same-named types in different kinds apart and keeps their identifiers distinct", async () => {
        setup({
            kinds: [
                KIND("family", ["other"]),
                KIND("general", ["other"]),
            ],
        })
        const form = await screen.findByRole("form", { name: "Add a relationship" })
        const options = within(within(form).getByRole("combobox", { name: "Type" })).getAllByRole("option")
        expect(options.map((o) => o.textContent)).toEqual(expect.arrayContaining(["other (Family)", "other (General)"]))
        expect(new Set(options.map((o) => (o as HTMLOptionElement).value)).size).toBe(options.length)
    })
})

describe("RelationshipsPanel: participant compatibility", () => {
    const openForm = () => screen.findByRole("form", { name: "Add a relationship" })
    const pickType = async (form: HTMLElement, value: string) =>
        fireEvent.change(await within(form).findByRole("combobox", { name: "Type" }), { target: { value } })
    const pickAnn = async (form: HTMLElement) => {
        fireEvent.focus(within(form).getByRole("combobox", { name: "Other participant" }))
        fireEvent.click(await within(form).findByRole("option", { name: /Ann/ }))
    }
    const rolesIn = (form: HTMLElement, name: string) =>
        within(within(form).getByRole("combobox", { name })).getAllByRole("option").map((o) => o.textContent)

    it.each(["ownership/ownership", "political/control", "general/worship"])(
        "submits %s with the opened record on either side, whichever the person picks",
        async (value) => {
            const type = value.split("/")[1]!
            const [first, second] = {
                ownership: ["owner", "property"],
                control: ["ruler", "object"],
                worship: ["subject", "object"],
            }[type]!
            for (const [mine, theirs] of [
                [first, second],
                [second, first],
            ] as [string, string][]) {
                const server = setup({ entityType: "player_character" })
                const form = await openForm()
                await pickType(form, value)
                fireEvent.change(within(form).getByRole("combobox", { name: "This record is the" }), {
                    target: { value: mine },
                })
                chooseOtherRole(form, theirs)
                await pickAnn(form)
                fireEvent.click(within(form).getByRole("button", { name: "Add relationship" }))
                await vi.waitFor(() => expect(server.callsTo("POST", BASE)).toHaveLength(1))
                expect(server.callsTo("POST", BASE)[0]!.body).toMatchObject({
                    relationship_type: type,
                    participants: [
                        { entity_id: "e1", role: mine },
                        { entity_id: "e3", role: theirs },
                    ],
                })
                cleanup()
            }
        },
    )

    it("names the roles by direction", async () => {
        setup({ entityType: "npc" })
        const form = await openForm()
        await pickType(form, "general/worship")
        expect(rolesIn(form, "This record is the")).toEqual(expect.arrayContaining(["Worshipper", "Worshipped"]))
        await pickType(form, "ownership/ownership")
        expect(rolesIn(form, "This record is the")).toEqual(expect.arrayContaining(["Owner", "Owned"]))
    })

    it("offers a settlement Capital Of only as the capital, with both roles read-only", async () => {
        const server = setup({ entityType: "settlement", kind: "place" })
        const form = await openForm()
        await pickType(form, "general/capital_of")
        expect(within(form).getByRole("textbox", { name: "This record is the" })).toHaveValue("Capital")
        expect(within(form).getByRole("textbox", { name: "This record is the" })).toHaveAttribute("readonly")
        expect(within(form).getByRole("textbox", { name: "The other participant is the" })).toHaveValue("Governed place")
        await pickAnn(form)
        fireEvent.click(within(form).getByRole("button", { name: "Add relationship" }))
        await vi.waitFor(() => expect(server.callsTo("POST", BASE)).toHaveLength(1))
        expect(server.callsTo("POST", BASE)[0]!.body).toMatchObject({
            relationship_type: "capital_of",
            participants: [
                { entity_id: "e1", role: "subject" },
                { entity_id: "e3", role: "object" },
            ],
        })
    })

    it("offers a nation Capital Of only as the governed place", async () => {
        setup({ entityType: "nation", kind: "place" })
        const form = await openForm()
        await pickType(form, "general/capital_of")
        expect(within(form).getByRole("textbox", { name: "This record is the" })).toHaveValue("Governed place")
        expect(within(form).getByRole("textbox", { name: "The other participant is the" })).toHaveValue("Capital")
    })

    it("shows a symmetric type's single role read-only", async () => {
        setup({ entityType: "organization" })
        const form = await openForm()
        await pickType(form, "political/alliance")
        expect(within(form).getByRole("textbox", { name: "This record is the" })).toHaveValue("Ally")
        expect(within(form).getByRole("textbox", { name: "The other participant is the" })).toHaveValue("Ally")
    })

    it("clears the roles that the new type does not offer when the type changes within a kind", async () => {
        setup({ entityType: "npc" })
        const form = await openForm()
        await pickType(form, "political/control")
        fireEvent.change(within(form).getByRole("combobox", { name: "This record is the" }), { target: { value: "ruler" } })
        chooseOtherRole(form, "object")
        await pickType(form, "political/alliance")
        expect(within(form).getByRole("textbox", { name: "This record is the" })).toHaveValue("Ally")
        await pickType(form, "political/control")
        expect(within(form).getByRole("combobox", { name: "This record is the" })).toHaveValue("")
        expect(within(form).getByRole("combobox", { name: "The other participant is the" })).toHaveValue("")
    })

    it("clears a counterpart that cannot take a newly chosen role, and says so", async () => {
        setup({ entityType: "npc" })
        const form = await openForm()
        await pickType(form, "political/control")
        fireEvent.change(within(form).getByRole("combobox", { name: "This record is the" }), { target: { value: "ruler" } })
        chooseOtherRole(form, "object")
        await pickAnn(form)
        expect(within(form).getByRole("combobox", { name: "Other participant" })).toHaveValue("Ann")
        // A person cannot be the controlled place.
        chooseOtherRole(form, "territory")
        expect(within(form).getByRole("combobox", { name: "Other participant" })).toHaveValue("")
        expect(within(form).getByText(/cleared because it cannot take that role/)).toBeInTheDocument()
    })

    it("keeps a counterpart that still fits after a role change", async () => {
        setup({ entityType: "npc" })
        const form = await openForm()
        await pickType(form, "general/worship")
        fireEvent.change(within(form).getByRole("combobox", { name: "This record is the" }), { target: { value: "subject" } })
        chooseOtherRole(form, "object")
        await pickAnn(form)
        fireEvent.change(within(form).getByRole("combobox", { name: "This record is the" }), { target: { value: "object" } })
        expect(within(form).getByRole("combobox", { name: "Other participant" })).toHaveValue("Ann")
        expect(within(form).queryByText(/cleared because/)).toBeNull()
    })

    it("narrows the counterpart search to the types the pairing allows, and drops only itself", async () => {
        const server = setup({ entityType: "settlement", kind: "place" })
        const form = await openForm()
        await pickType(form, "general/capital_of")
        fireEvent.focus(within(form).getByRole("combobox", { name: "Other participant" }))
        await within(form).findByRole("option", { name: /Ann/ })
        const path = server.callsTo("GET", /world\/search/).at(-1)!.path
        const params = new URLSearchParams(path.split("?")[1])
        expect(params.getAll("entity_type").sort()).toEqual(["continent", "location", "nation", "plane", "realm", "region"])
        expect(params.has("category")).toBe(false)
    })

    it("explains a refused incompatible participant", async () => {
        const server = setup({ entityType: "npc" })
        server.on("POST", BASE, {
            status: 400,
            body: { error: { code: "participant_incompatible", message: "m", correlation_id: "c" } },
        })
        const form = await openForm()
        await pickType(form, "family/family")
        fireEvent.change(within(form).getByRole("combobox", { name: "This record is the" }), { target: { value: "parent" } })
        chooseOtherRole(form, "child")
        await pickAnn(form)
        fireEvent.click(within(form).getByRole("button", { name: "Add relationship" }))
        expect(await screen.findByRole("alert")).toHaveTextContent(/cannot take that role in this type of relationship/)
    })

    it("shows a note for an existing relationship the rules would refuse, and keeps it correctable", async () => {
        const conflicted = {
            ...VIEW,
            policy_conflicts: ["Varek (npc) cannot be the capital in capital of."],
        }
        setup({ view: conflicted, summary: { ...SUMMARY, policy_conflicts: conflicted.policy_conflicts } })
        fireEvent.click(await screen.findByRole("button", { name: "Open family" }))
        expect(await screen.findByText(/does not fit the current rules/)).toHaveTextContent(/Varek \(npc\) cannot be the capital/)
        expect(screen.getByRole("button", { name: "Save relationship" })).toBeInTheDocument()
        expect(screen.getByRole("button", { name: "End relationship" })).toBeInTheDocument()
        expect(screen.getByRole("button", { name: "Archive relationship" })).toBeInTheDocument()
        expect(screen.getByRole("form", { name: "Set perspective" })).toBeInTheDocument()
    })

    it("shows no note for a relationship that fits", async () => {
        setup()
        fireEvent.click(await screen.findByRole("button", { name: "Open family" }))
        await screen.findByText(/Family: Family, from Year 1/)
        expect(screen.queryByText(/does not fit the current rules/)).toBeNull()
    })
})

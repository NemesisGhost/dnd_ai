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
    started_world_time_id: "t1",
    started: "Year 1",
    ended_world_time_id: null,
    ended_at: null,
    period_status: "in_effect",
    in_force: null,
    is_hidden: null,
    current_status: null,
    current_status_label: null,
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
    period_status: "in_effect",
    as_of: "Year 3",
    current_status_label: null,
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
    // The list's `as_of`: the campaign clock the periods were compared with.
    asOf?: string | null
    // Several rows, instead of the one summary.
    summaries?: object[]
    canCreate?: boolean
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
        asOf = "Year 3",
        summaries,
        canCreate = true,
    } = Array.isArray(capabilitiesOrOptions) ? { capabilities: capabilitiesOrOptions } : capabilitiesOrOptions
    const server = installMockServer()
    server.on("GET", /authoring\/relationships\/options/, { body: { ...optionsFor(entityType, kinds), can_create: canCreate } })
    server.on("GET", /authoring\/relationships\?entity_id=/, { body: { as_of: asOf, items: summaries ?? [summary] } })
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

// The Add form is revealed by the bar's button.
async function addForm() {
    fireEvent.click(await screen.findByRole("button", { name: "Add relationship" }))
    return screen.findByRole("form", { name: "Add a relationship" })
}

const OPEN_FAMILY = /^Open Family with Tom$/

// Opens a row's editor, and one of its sections when named.
async function openRow(name: RegExp = OPEN_FAMILY, section?: string) {
    fireEvent.click(await screen.findByRole("button", { name }))
    if (section !== undefined) fireEvent.click(await screen.findByRole("button", { name: new RegExp(`^${section}`) }))
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
        expect(await screen.findByText("Tom")).toBeInTheDocument()
        expect(screen.getByText("This record: Parent \u00b7 Tom: Child")).toBeInTheDocument()
    })

    it("opens a relationship and archives it with the version it saw", async () => {
        const server = setup()
        await openRow(OPEN_FAMILY, "End or archive")
        expect(await screen.findByText(/Family · Since Year 1 — in effect now/)).toBeInTheDocument()
        fireEvent.click(await screen.findByRole("button", { name: "Archive relationship" }))
        await vi.waitFor(() => expect(server.callsTo("POST", `${BASE}/r1/archive`)).toHaveLength(1))
        expect(server.callsTo("POST", `${BASE}/r1/archive`)[0]!.body).toEqual({ expected_row_version: 2 })
    })

    it("saves a perspective after checking the ratings", async () => {
        const server = setup()
        await openRow(OPEN_FAMILY, "Perspectives")
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
        const form = await addForm()
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
        const form = await addForm()
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
        const form = await addForm()
        return within(within(form).getByRole("combobox", { name: "Type" }))
            .getAllByRole("option")
            .map((option) => (option as HTMLOptionElement).value)
    }

    it("says what relationships are for and what they never do", async () => {
        setup()
        const note = await screen.findByText(/Relationships are story-world facts/)
        expect(note).toHaveTextContent(/never decide who can see or play a character/)
        expect(note).toHaveTextContent(/Character access/)
        expect(note).toHaveTextContent(/Members and offices/)
        expect(note).toHaveTextContent(/need to be able to see both participants/)
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
        const form = await addForm()
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
        fireEvent.click(await screen.findByRole("button", { name: /^Open Membership with The Gilded Scale$/ }))
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
        await openRow(/^Open Membership with The Gilded Scale$/, "Perspectives")
        expect(await screen.findByRole("form", { name: "Set perspective" })).toBeInTheDocument()
        expect(screen.getByText("How each participant sees it")).toBeInTheDocument()
        fireEvent.click(screen.getByRole("button", { name: /^End or archive/ }))
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
        await openRow(/^Open Membership with The Gilded Scale$/, "End or archive")
        fireEvent.click(await screen.findByRole("button", { name: "Restore relationship" }))
        await vi.waitFor(() => expect(server.callsTo("POST", `${BASE}/r1/restore`)).toHaveLength(1))
    })

    it("still edits other kinds in place, with the correct and End forms", async () => {
        setup({ kind: "npc" })
        await openRow()
        expect(await screen.findByRole("form", { name: "Edit relationship" })).toBeInTheDocument()
        fireEvent.click(screen.getByRole("button", { name: /^End or archive/ }))
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
        const form = await addForm()
        expect(within(form).queryByRole("combobox", { name: "Kind" })).toBeNull()
        const type = within(form).getByRole("combobox", { name: "Type" })
        const groups = Array.from(type.querySelectorAll("optgroup")).map((g) => g.label)
        expect(groups).toEqual(expect.arrayContaining(["Employment", "Family", "Other connection"]))
        expect(within(form).queryByRole("combobox", { name: "This record is the" })).toBeNull()
    })

    it("submits the kind the chosen type belongs to", async () => {
        const server = setup({ kind: "place", entityType: "settlement" })
        const form = await addForm()
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
        const form = await addForm()
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
        const form = await addForm()
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
        const form = await addForm()
        expect(within(form).getByText(/No relationship types are available for this record/)).toBeInTheDocument()
        expect(within(form).queryByRole("button", { name: "Add relationship" })).toBeNull()
        expect(within(form).queryByRole("combobox")).toBeNull()
    })

    it("also treats a kind that lists no type as unavailable", async () => {
        setup({ kinds: [KIND("family", [])] })
        const form = await addForm()
        expect(within(form).getByText(/No relationship types are available/)).toBeInTheDocument()
    })

    it("tells two same-named types in different kinds apart and keeps their identifiers distinct", async () => {
        setup({
            kinds: [
                KIND("family", ["other"]),
                KIND("general", ["other"]),
            ],
        })
        const form = await addForm()
        const options = within(within(form).getByRole("combobox", { name: "Type" })).getAllByRole("option")
        expect(options.map((o) => o.textContent)).toEqual(expect.arrayContaining(["other (Family)", "other (General)"]))
        expect(new Set(options.map((o) => (o as HTMLOptionElement).value)).size).toBe(options.length)
    })
})

describe("RelationshipsPanel: participant compatibility", () => {
    const openForm = addForm
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
        await openRow()
        expect(await screen.findByText(/does not fit the current rules/)).toHaveTextContent(/Varek \(npc\) cannot be the capital/)
        expect(screen.getByRole("button", { name: "Save relationship" })).toBeInTheDocument()
        fireEvent.click(screen.getByRole("button", { name: /^End or archive/ }))
        expect(screen.getByRole("button", { name: "End relationship" })).toBeInTheDocument()
        expect(screen.getByRole("button", { name: "Archive relationship" })).toBeInTheDocument()
        fireEvent.click(screen.getByRole("button", { name: /^Perspectives/ }))
        expect(screen.getByRole("form", { name: "Set perspective" })).toBeInTheDocument()
    })

    it("shows no note for a relationship that fits", async () => {
        setup()
        await openRow()
        await screen.findByRole("form", { name: "Edit relationship" })
        expect(screen.queryByText(/does not fit the current rules/)).toBeNull()
    })
})


// ---- The compact roster ---------------------------------------------------------------------------

const LIST_PATH = /authoring\/relationships\?entity_id=/

const row = (summary: object, who: string, overrides: object = {}) => ({
    ...SUMMARY,
    ...summary,
    participants: [participant("e1", "Mira", "parent", "Parent"), participant(`x-${who}`, who, "child", "Child")],
    ...overrides,
})

describe("RelationshipsPanel: roster rows", () => {
    const rowOf = async (name: string) => within((await screen.findByText(name)).closest("li") as HTMLElement)

    it("states each fact under its own label, and keeps archived, ended, future, undated and unknown apart", async () => {
        setup({
            summaries: [
                row({ relationship_id: "a" }, "Tom"),
                row(
                    {
                        relationship_id: "b",
                        relationship_type_label: "Employment",
                        lifecycle_status: "archived",
                        ended: true,
                        ended_at: "Year 2",
                        period_status: "ended",
                    },
                    "Nora",
                ),
                row({ relationship_id: "c", started: "Year 9", period_status: "not_started" }, "Oren"),
                row(
                    { relationship_id: "d", started: null, started_world_time_id: null, period_status: "undated", description: "Met at the docks." },
                    "Pia",
                ),
                row({ relationship_id: "e", started: "Year 4", period_status: "clock_unset" }, "Uma"),
                row(
                    {
                        relationship_id: "f",
                        kind: "political",
                        relationship_type_label: "War",
                        ended: true,
                        ended_at: "Year 2",
                        period_status: "ended",
                        in_force: false,
                        current_status_label: "Estranged",
                    },
                    "Quill",
                ),
            ],
        })
        const tom = await rowOf("Tom")
        expect(tom.getByText("Family")).toBeInTheDocument()
        expect(tom.getByText("Since Year 1 — in effect now")).toBeInTheDocument()
        expect(tom.queryByText("Archived")).toBeNull()
        expect(tom.queryByText("In force")).toBeNull()
        expect(tom.queryByText("Timeline status")).toBeNull()

        const nora = await rowOf("Nora")
        expect(nora.getByText("Archived")).toBeInTheDocument()
        expect(nora.getByText("Year 1 to Year 2 — ended")).toBeInTheDocument()

        expect((await rowOf("Oren")).getByText("Since Year 9 — not started yet")).toBeInTheDocument()

        const pia = await rowOf("Pia")
        // No dates are invented for an undated record, and no status is claimed.
        expect(pia.getByText("No dates recorded")).toBeInTheDocument()
        expect(pia.getByText("Met at the docks.")).toBeInTheDocument()

        const uma = await rowOf("Uma")
        expect(uma.getByText("Since Year 4 — campaign time not set")).toBeInTheDocument()

        // In force and Timeline status are their own facts; ended does not imply either.
        const quill = await rowOf("Quill")
        expect(quill.getByText("In force").nextSibling).toHaveTextContent("No")
        expect(quill.getByText("Timeline status").nextSibling).toHaveTextContent("Estranged")
        expect(quill.getByText("Year 1 to Year 2 — ended")).toBeInTheDocument()
    })

    it("labels visibility by kind and never calls an unknown one public", async () => {
        setup({
            summaries: [
                row({ relationship_id: "o1", kind: "ownership", is_public: true }, "Own1"),
                row({ relationship_id: "o2", kind: "ownership", is_public: false }, "Own2"),
                row({ relationship_id: "o3", kind: "ownership", is_public: null }, "Own3"),
                row({ relationship_id: "m1", kind: "membership", is_public: false }, "Org1"),
                row({ relationship_id: "r1x", kind: "route", is_hidden: true }, "Road1"),
                row({ relationship_id: "r2x", kind: "route", is_hidden: false }, "Road2"),
                row({ relationship_id: "r3x", kind: "route", is_hidden: null }, "Road3"),
                row({ relationship_id: "g1", kind: "general" }, "Gen1"),
            ],
        })
        const expectFor = async (name: string, label: string) => {
            expect((await rowOf(name)).getByText("Visibility").nextSibling).toHaveTextContent(label)
        }
        await expectFor("Own1", "Known to the public")
        await expectFor("Own2", "Editors only")
        await expectFor("Own3", "Not recorded")
        await expectFor("Org1", "Editors only")
        await expectFor("Road1", "Concealed: editors only")
        await expectFor("Road2", "Not concealed")
        await expectFor("Road3", "Not recorded")
        await expectFor("Gen1", "No visibility setting")
    })

    it("flags a record the rules would refuse, with the reasons, without hiding it", async () => {
        setup({ summaries: [row({ relationship_id: "k", policy_conflicts: ["Varek cannot be the capital."] }, "Tam")] })
        const tam = await rowOf("Tam")
        const badge = tam.getByText(/fit current rules/)
        expect(badge).toHaveAttribute("title", "Varek cannot be the capital.")
    })

    it("reads the same direction from either participant", async () => {
        setup({ entityId: "e2", summaries: [SUMMARY] })
        expect(await screen.findByText("Mira")).toBeInTheDocument()
        expect(screen.getByText("Mira: Parent · This record: Child")).toBeInTheDocument()
        expect(screen.getByRole("button", { name: /^Open Family with Mira$/ })).toBeInTheDocument()
    })

    it("names a record stored as its own counterpart once", async () => {
        const self = { ...SUMMARY, participants: [participant("e1", "Mira", "parent", "Parent"), participant("e1", "Mira", "child", "Child")] }
        setup({ summaries: [self] })
        expect(await screen.findByText("Mira (this record)")).toBeInTheDocument()
        expect(screen.getByText("This record: Parent · This record: Child")).toBeInTheDocument()
    })

    it("compares with the campaign time, or says it is not set", async () => {
        setup()
        expect(await screen.findByText("Compared with campaign time: Year 3")).toBeInTheDocument()
        cleanup()
        setup({ asOf: null, summaries: [row({ period_status: "clock_unset" }, "Uma")] })
        expect(await screen.findByText(/Campaign time is not set/)).toBeInTheDocument()
    })

    it("counts the relationships and offers Include archived as a checkbox", async () => {
        const server = setup({ summaries: [row({ relationship_id: "a" }, "Tom")] })
        expect(await screen.findByText("1 relationship")).toBeInTheDocument()
        fireEvent.click(screen.getByRole("checkbox", { name: "Include archived" }))
        await vi.waitFor(() =>
            expect(server.callsTo("GET", /relationships\?entity_id=e1&include_archived=true/).length).toBeGreaterThan(0),
        )
        expect(await screen.findByText("1 relationship, including archived")).toBeInTheDocument()
    })

    it("keeps the Add form's input and an open editor when Include archived changes", async () => {
        setup()
        await openRow()
        const form = await addForm()
        fireEvent.change(await within(form).findByRole("combobox", { name: "Type" }), { target: { value: "general/worship" } })
        fireEvent.change(within(form).getByRole("combobox", { name: "This record is the" }), { target: { value: "subject" } })
        fireEvent.click(screen.getByRole("checkbox", { name: "Include archived" }))
        await screen.findByText(/including archived/)
        expect(within(form).getByRole("combobox", { name: "This record is the" })).toHaveValue("subject")
        expect(screen.getByRole("form", { name: "Edit relationship" })).toBeInTheDocument()
    })

    it("keeps the rows and says so when the list cannot be read again", async () => {
        const server = setup()
        await screen.findByText("Tom")
        server.on("GET", LIST_PATH, { status: 500, body: {} })
        fireEvent.click(screen.getByRole("checkbox", { name: "Include archived" }))
        expect(await screen.findByText(/latest relationships could not be loaded/)).toBeInTheDocument()
        expect(screen.getByText("Tom")).toBeInTheDocument()
    })

    it("says there are none, and where archived ones are", async () => {
        setup({ summaries: [] })
        expect(await screen.findByText(/No relationships recorded\./)).toHaveTextContent(/tick Include archived/)
        fireEvent.click(screen.getByRole("checkbox", { name: "Include archived" }))
        await screen.findByText(/including archived/)
        expect(screen.getByText(/No relationships recorded\./)).not.toHaveTextContent(/tick Include archived/)
    })
})

describe("RelationshipsPanel: the Add form is revealed on request", () => {
    const pickWorship = async (form: HTMLElement) => {
        fireEvent.change(await within(form).findByRole("combobox", { name: "Type" }), { target: { value: "general/worship" } })
        fireEvent.change(within(form).getByRole("combobox", { name: "This record is the" }), { target: { value: "subject" } })
        chooseOtherRole(form, "object")
        fireEvent.focus(within(form).getByRole("combobox", { name: "Other participant" }))
        fireEvent.click(await within(form).findByRole("option", { name: /Ann/ }))
    }

    it("hides the form until Add, and offers no Add without permission", async () => {
        setup()
        await screen.findByText("Tom")
        expect(screen.queryByRole("form", { name: "Add a relationship" })).toBeNull()
        const button = screen.getByRole("button", { name: "Add relationship" })
        expect(button).toHaveAttribute("aria-expanded", "false")
        fireEvent.click(button)
        expect(await screen.findByRole("form", { name: "Add a relationship" })).toBeInTheDocument()
        expect(screen.getByRole("button", { name: "Adding a relationship…" })).toBeDisabled()
        cleanup()
        setup({ canCreate: false })
        await screen.findByText("Tom")
        expect(screen.queryByRole("button", { name: "Add relationship" })).toBeNull()
    })

    it("puts focus on the first control", async () => {
        setup()
        await addForm()
        await vi.waitFor(() => expect(screen.getByRole("combobox", { name: "Type" })).toHaveFocus())
    })

    it("completes the sentence once both roles and the other participant are chosen", async () => {
        setup()
        const form = await addForm()
        await pickWorship(form)
        expect(within(form).getByText("This record is the Worshipper; Ann is the Worshipped.")).toBeInTheDocument()
    })

    it("closes at once when nothing was entered, and asks when something was", async () => {
        setup()
        await addForm()
        fireEvent.click(screen.getByRole("button", { name: "Cancel" }))
        expect(screen.queryByRole("form", { name: "Add a relationship" })).toBeNull()
        expect(screen.queryByText("Discard unsaved input?")).toBeNull()
        await vi.waitFor(() => expect(screen.getByRole("button", { name: "Add relationship" })).toHaveFocus())
    })

    it("keeps a dirty form on Keep editing, and clears it on Discard", async () => {
        setup()
        const form = await addForm()
        fireEvent.change(await within(form).findByRole("combobox", { name: "Type" }), { target: { value: "general/worship" } })
        fireEvent.click(within(form).getByRole("button", { name: "Cancel" }))
        expect(await screen.findByText("Discard unsaved input?")).toBeInTheDocument()
        fireEvent.click(screen.getByRole("button", { name: "Keep editing" }))
        expect(within(form).getByRole("combobox", { name: "Type" })).toHaveValue("general/worship")
        fireEvent.click(within(form).getByRole("button", { name: "Cancel" }))
        fireEvent.click(await screen.findByRole("button", { name: "Discard" }))
        expect(screen.queryByRole("form", { name: "Add a relationship" })).toBeNull()
        await vi.waitFor(() => expect(screen.getByRole("button", { name: "Add relationship" })).toHaveFocus())
        const reopened = await addForm()
        expect(within(reopened).getByRole("combobox", { name: "Type" })).toHaveValue("")
    })

    it("closes on success, reads the list again, announces, and focuses the new row", async () => {
        const server = setup()
        let added = false
        const created = {
            ...SUMMARY,
            relationship_id: "r9",
            relationship_type: "worship",
            relationship_type_label: "Worship",
            kind: "general",
            participants: [participant("e1", "Mira", "subject", "Worshipper"), participant("e3", "Ann", "object", "Worshipped")],
        }
        server.on("GET", LIST_PATH, () => ({ body: { as_of: "Year 3", items: added ? [SUMMARY, created] : [SUMMARY] } }))
        server.on("POST", BASE, () => {
            added = true
            return { status: 201, body: { ...VIEW, ...created, changed: true } }
        })
        const form = await addForm()
        await pickWorship(form)
        fireEvent.click(within(form).getByRole("button", { name: "Add relationship" }))
        await vi.waitFor(() => expect(screen.queryByRole("form", { name: "Add a relationship" })).toBeNull())
        expect(await screen.findByText("Ann")).toBeInTheDocument()
        await vi.waitFor(() => expect(screen.getByTestId("authoring-announcer")).toHaveTextContent("Relationship added: Worship with Ann"))
        await vi.waitFor(() => expect(document.getElementById("relationship-open-r9")).toHaveFocus())
    })

    it("says the relationship was added when the list cannot be read afterwards, and does not invite a repeat", async () => {
        const server = setup()
        let added = false
        server.on("GET", LIST_PATH, () => (added ? { status: 500, body: {} } : { body: { as_of: "Year 3", items: [SUMMARY] } }))
        server.on("POST", BASE, () => {
            added = true
            return { status: 201, body: { ...VIEW, changed: true } }
        })
        const form = await addForm()
        await pickWorship(form)
        fireEvent.click(within(form).getByRole("button", { name: "Add relationship" }))
        const notes = await screen.findAllByText(/was added, but the list could not be refreshed/)
        expect(notes[0]).toHaveTextContent(/Do not add it again/)
        expect(screen.getByText("Tom")).toBeInTheDocument()
        expect(server.callsTo("POST", BASE)).toHaveLength(1)
    })

    it("keeps the form and its values when the server refuses", async () => {
        const server = setup()
        server.on("POST", BASE, {
            status: 400,
            body: { error: { code: "participant_invalid", message: "m", correlation_id: "c" } },
        })
        const form = await addForm()
        await pickWorship(form)
        fireEvent.click(within(form).getByRole("button", { name: "Add relationship" }))
        expect(await screen.findByRole("alert")).toHaveTextContent(/Choose published places/)
        expect(within(form).getByRole("combobox", { name: "Other participant" })).toHaveValue("Ann")
    })
})


// ---- The expanded editor --------------------------------------------------------------------------

describe("RelationshipsPanel: the editor keeps each form's input separate", () => {
    // A server whose record changes version when a perspective or the details are saved.
    function live(options: SetupOptions = {}) {
        const server = setup(options)
        let current: Record<string, unknown> = { ...(options.view ?? VIEW) }
        server.on("GET", `${BASE}/r1`, () => ({ body: current }))
        const bump = (patch: object = {}) => {
            current = { ...current, row_version: (current.row_version as number) + 1, ...patch }
            return { body: { ...current, changed: true } }
        }
        server.on("POST", `${BASE}/r1/perspectives`, () => bump())
        server.on("POST", `${BASE}/r1/update`, () => bump())
        return { server, bump }
    }
    const description = () => screen.getByRole("textbox", { name: "Description" })
    const affinity = () => screen.getByRole("textbox", { name: "Affinity" })
    const mode = (name: string) => fireEvent.click(screen.getByRole("button", { name: new RegExp(`^${name}`) }))

    it("saving a perspective does not discard unsaved details", async () => {
        const { server } = live()
        await openRow()
        await screen.findByRole("form", { name: "Edit relationship" })
        fireEvent.change(description(), { target: { value: "Edited, not saved" } })
        mode("Perspectives")
        fireEvent.change(affinity(), { target: { value: "40" } })
        fireEvent.click(screen.getByRole("button", { name: "Save perspective" }))
        await vi.waitFor(() => expect(server.callsTo("POST", `${BASE}/r1/perspectives`)).toHaveLength(1))
        // The record is read again at the new version before the details are looked at.
        await vi.waitFor(() => expect(server.callsTo("GET", `${BASE}/r1`).length).toBeGreaterThan(1))
        await vi.waitFor(() =>
            expect(screen.getByTestId("authoring-announcer")).toHaveTextContent("Perspective saved for Mira"),
        )
        mode("Details")
        expect(description()).toHaveValue("Edited, not saved")
        expect(screen.getByRole("button", { name: "Details (unsaved)" })).toBeInTheDocument()
        expect(server.callsTo("POST", `${BASE}/r1/update`)).toHaveLength(0)
    })

    it("saving the details does not discard an unsaved perspective", async () => {
        const { server } = live()
        await openRow()
        await screen.findByRole("form", { name: "Edit relationship" })
        mode("Perspectives")
        fireEvent.change(affinity(), { target: { value: "55" } })
        mode("Details")
        fireEvent.change(description(), { target: { value: "Saved text" } })
        fireEvent.click(screen.getByRole("button", { name: "Save relationship" }))
        await vi.waitFor(() => expect(server.callsTo("POST", `${BASE}/r1/update`)).toHaveLength(1))
        expect(server.callsTo("POST", `${BASE}/r1/update`)[0]!.body).toMatchObject({
            expected_row_version: 2,
            description: "Saved text",
            family_unit_name: "House Vale",
        })
        await vi.waitFor(() => expect(server.callsTo("GET", `${BASE}/r1`).length).toBeGreaterThan(1))
        mode("Perspectives")
        expect(affinity()).toHaveValue("55")
        expect(screen.getByRole("button", { name: "Perspectives (unsaved)" })).toBeInTheDocument()
        expect(server.callsTo("POST", `${BASE}/r1/perspectives`)).toHaveLength(0)
    })

    it("keeps a participant's unsaved perspective when switching to the other and back", async () => {
        live()
        await openRow(OPEN_FAMILY, "Perspectives")
        fireEvent.change(affinity(), { target: { value: "12" } })
        expect(screen.getByRole("button", { name: "Mira (unsaved)" })).toBeInTheDocument()
        fireEvent.click(screen.getByRole("button", { name: "Tom" }))
        expect(affinity()).toHaveValue("")
        fireEvent.change(affinity(), { target: { value: "-5" } })
        fireEvent.click(screen.getByRole("button", { name: "Mira (unsaved)" }))
        expect(affinity()).toHaveValue("12")
        fireEvent.click(screen.getByRole("button", { name: "Tom (unsaved)" }))
        expect(affinity()).toHaveValue("-5")
    })

    it("saves the chosen participant's perspective with the participant's id", async () => {
        const { server } = live()
        await openRow(OPEN_FAMILY, "Perspectives")
        fireEvent.click(screen.getByRole("button", { name: "Tom" }))
        fireEvent.change(affinity(), { target: { value: "7" } })
        fireEvent.change(screen.getByRole("textbox", { name: "Emotional tone" }), { target: { value: "fond" } })
        fireEvent.click(screen.getByRole("button", { name: "Save perspective" }))
        await vi.waitFor(() => expect(server.callsTo("POST", `${BASE}/r1/perspectives`)).toHaveLength(1))
        expect(server.callsTo("POST", `${BASE}/r1/perspectives`)[0]!.body).toMatchObject({
            holder_entity_id: "e2",
            affinity: 7,
            emotional_tone: "fond",
        })
    })

    it("announces a save and that nothing changed", async () => {
        const { server } = live()
        await openRow()
        await screen.findByRole("form", { name: "Edit relationship" })
        fireEvent.change(description(), { target: { value: "More" } })
        fireEvent.click(screen.getByRole("button", { name: "Save relationship" }))
        await vi.waitFor(() => expect(screen.getByTestId("authoring-announcer")).toHaveTextContent("Relationship saved"))
        server.on("POST", `${BASE}/r1/update`, () => ({ body: { ...VIEW, changed: false } }))
        fireEvent.change(description(), { target: { value: "More again" } })
        fireEvent.click(screen.getByRole("button", { name: "Save relationship" }))
        await vi.waitFor(() => expect(screen.getByTestId("authoring-announcer")).toHaveTextContent("Nothing changed"))
    })

    it("shows a stale save in its own form, keeps what was typed, and loads the latest on request", async () => {
        const { server } = live()
        server.on("POST", `${BASE}/r1/update`, {
            status: 409,
            body: { error: { code: "stale_write", message: "m", correlation_id: "c" } },
        })
        await openRow()
        await screen.findByRole("form", { name: "Edit relationship" })
        fireEvent.change(description(), { target: { value: "Mine" } })
        fireEvent.click(screen.getByRole("button", { name: "Save relationship" }))
        const form = screen.getByRole("form", { name: "Edit relationship" })
        const load = await within(form).findByRole("button", { name: "Load latest version" })
        expect(within(form).getByText(/What you typed in this form is kept/)).toBeInTheDocument()
        fireEvent.click(load)
        await vi.waitFor(() => expect(server.callsTo("GET", `${BASE}/r1`).length).toBeGreaterThan(1))
        expect(description()).toHaveValue("Mine")
    })

    it("pauses saving when the details changed elsewhere, until the person chooses", async () => {
        const { server, bump } = live()
        await openRow()
        await screen.findByRole("form", { name: "Edit relationship" })
        fireEvent.change(description(), { target: { value: "Mine" } })
        // Someone else corrects the description; this editor reads it at its next save.
        server.on("POST", `${BASE}/r1/perspectives`, () => bump({ description: "Theirs" }))
        mode("Perspectives")
        fireEvent.click(screen.getByRole("button", { name: "Save perspective" }))
        mode("Details")
        expect(await screen.findByText(/These details changed elsewhere/)).toBeInTheDocument()
        expect(description()).toHaveValue("Mine")
        expect(screen.getByRole("button", { name: "Save relationship" })).toBeDisabled()
        fireEvent.click(screen.getByRole("button", { name: "Keep my changes and save over it" }))
        expect(screen.getByRole("button", { name: "Save relationship" })).toBeEnabled()
        expect(description()).toHaveValue("Mine")
    })

    it("loads the latest details when asked, replacing the draft only then", async () => {
        const { server, bump } = live()
        await openRow()
        await screen.findByRole("form", { name: "Edit relationship" })
        fireEvent.change(description(), { target: { value: "Mine" } })
        server.on("POST", `${BASE}/r1/perspectives`, () => bump({ description: "Theirs" }))
        mode("Perspectives")
        fireEvent.click(screen.getByRole("button", { name: "Save perspective" }))
        mode("Details")
        fireEvent.click(await screen.findByRole("button", { name: "Load the latest saved version" }))
        expect(description()).toHaveValue("Theirs")
    })

    it("keeps the editor, says so, and never offers a repeat when the read after a save fails", async () => {
        const { server } = live()
        await openRow()
        await screen.findByRole("form", { name: "Edit relationship" })
        fireEvent.change(description(), { target: { value: "Saved text" } })
        server.on("POST", `${BASE}/r1/update`, () => {
            server.on("GET", `${BASE}/r1`, { status: 500, body: {} })
            return { body: { ...VIEW, description: "Saved text", row_version: 3, changed: true } }
        })
        fireEvent.click(screen.getByRole("button", { name: "Save relationship" }))
        expect(await screen.findByText(/latest relationship could not be loaded/)).toBeInTheDocument()
        await vi.waitFor(() =>
            expect(screen.getByTestId("authoring-announcer")).toHaveTextContent(/Saved\. The latest version could not be loaded; do not save it again/),
        )
        // What was sent is accepted: the form is clean, with the saved text still shown.
        expect(screen.getByRole("form", { name: "Edit relationship" })).toBeInTheDocument()
        expect(description()).toHaveValue("Saved text")
        // The marker clears in an effect, a render after the alert appears.
        await vi.waitFor(() => expect(screen.queryByRole("button", { name: "Details (unsaved)" })).toBeNull())
        expect(server.callsTo("POST", `${BASE}/r1/update`)).toHaveLength(1)
    })
})

describe("RelationshipsPanel: closing and switching", () => {
    const other = row({ relationship_id: "r2" }, "Zed")
    const withTwo = () => setup({ summaries: [SUMMARY, other] })

    it("closes a clean editor without asking, and returns focus to Open", async () => {
        setup()
        await openRow()
        await screen.findByRole("form", { name: "Edit relationship" })
        fireEvent.click(screen.getByRole("button", { name: /^Close Family with Tom$/ }))
        expect(screen.queryByRole("form", { name: "Edit relationship" })).toBeNull()
        await vi.waitFor(() => expect(screen.getByRole("button", { name: /^Open Family with Tom$/ })).toHaveFocus())
    })

    it("asks before closing unsaved input, and keeps it on Keep editing", async () => {
        setup()
        await openRow()
        await screen.findByRole("form", { name: "Edit relationship" })
        fireEvent.change(screen.getByRole("textbox", { name: "Description" }), { target: { value: "x" } })
        fireEvent.click(screen.getByRole("button", { name: /^Close Family with Tom$/ }))
        expect(await screen.findByText("Discard unsaved input?")).toBeInTheDocument()
        fireEvent.click(screen.getByRole("button", { name: "Keep editing" }))
        expect(screen.getByRole("textbox", { name: "Description" })).toHaveValue("x")
        fireEvent.click(screen.getByRole("button", { name: /^Close Family with Tom$/ }))
        fireEvent.click(await screen.findByRole("button", { name: "Discard" }))
        expect(screen.queryByRole("form", { name: "Edit relationship" })).toBeNull()
        await vi.waitFor(() => expect(screen.getByRole("button", { name: /^Open Family with Tom$/ })).toHaveFocus())
    })

    it("asks before opening another row over unsaved input, and opens it on Discard", async () => {
        withTwo()
        await openRow()
        await screen.findByRole("form", { name: "Edit relationship" })
        fireEvent.change(screen.getByRole("textbox", { name: "Description" }), { target: { value: "x" } })
        fireEvent.click(screen.getByRole("button", { name: /^Open Family with Zed$/ }))
        expect(await screen.findByText("Discard unsaved input?")).toBeInTheDocument()
        fireEvent.click(screen.getByRole("button", { name: "Keep editing" }))
        expect(screen.getByRole("button", { name: /^Close Family with Tom$/ })).toBeInTheDocument()
        fireEvent.click(screen.getByRole("button", { name: /^Open Family with Zed$/ }))
        fireEvent.click(await screen.findByRole("button", { name: "Discard" }))
        expect(await screen.findByRole("button", { name: /^Close Family with Zed$/ })).toBeInTheDocument()
        expect(screen.getByRole("button", { name: /^Open Family with Tom$/ })).toBeInTheDocument()
    })

    it("opens another row at once when nothing is unsaved", async () => {
        withTwo()
        await openRow()
        await screen.findByRole("form", { name: "Edit relationship" })
        fireEvent.click(screen.getByRole("button", { name: /^Open Family with Zed$/ }))
        expect(await screen.findByRole("button", { name: /^Close Family with Zed$/ })).toBeInTheDocument()
        expect(screen.queryByText("Discard unsaved input?")).toBeNull()
    })

    it("keeps input when switching sections of the editor", async () => {
        setup()
        await openRow()
        await screen.findByRole("form", { name: "Edit relationship" })
        fireEvent.change(screen.getByRole("textbox", { name: "Description" }), { target: { value: "kept" } })
        fireEvent.click(screen.getByRole("button", { name: /^End or archive/ }))
        fireEvent.click(screen.getByRole("button", { name: /^Details/ }))
        expect(screen.getByRole("textbox", { name: "Description" })).toHaveValue("kept")
    })
})

describe("RelationshipsPanel: archive, end and what each state offers", () => {
    it("asks before archiving over unsaved details, and archives on confirm", async () => {
        const server = setup()
        await openRow()
        await screen.findByRole("form", { name: "Edit relationship" })
        fireEvent.change(screen.getByRole("textbox", { name: "Description" }), { target: { value: "x" } })
        fireEvent.click(screen.getByRole("button", { name: /^End or archive/ }))
        fireEvent.click(screen.getByRole("button", { name: "Archive relationship" }))
        expect(await screen.findByText(/your unsaved relationship details will be discarded/)).toBeInTheDocument()
        expect(server.callsTo("POST", `${BASE}/r1/archive`)).toHaveLength(0)
        fireEvent.click(screen.getByRole("button", { name: "Keep editing" }))
        fireEvent.click(screen.getByRole("button", { name: "Archive relationship" }))
        fireEvent.click(await screen.findByRole("button", { name: "Archive and discard" }))
        await vi.waitFor(() => expect(server.callsTo("POST", `${BASE}/r1/archive`)).toHaveLength(1))
    })

    it("closes the row, announces, and focuses the count when archiving removes it from the list", async () => {
        const server = setup()
        let archived = false
        server.on("GET", LIST_PATH, () => ({ body: { as_of: "Year 3", items: archived ? [] : [SUMMARY] } }))
        server.on("POST", `${BASE}/r1/archive`, () => {
            archived = true
            return { body: { ...VIEW, lifecycle_status: "archived", available_actions: ["restore"], changed: true } }
        })
        await openRow(OPEN_FAMILY, "End or archive")
        fireEvent.click(screen.getByRole("button", { name: "Archive relationship" }))
        await vi.waitFor(() =>
            expect(screen.getByTestId("authoring-announcer")).toHaveTextContent("Relationship archived. Tick Include archived to see it."),
        )
        expect(screen.queryByRole("form", { name: "Edit relationship" })).toBeNull()
        await vi.waitFor(() => expect(document.getElementById("relationships-count")).toHaveFocus())
    })

    it("offers only Restore, read-only facts and no forms for an archived relationship", async () => {
        setup({
            summaries: [{ ...SUMMARY, lifecycle_status: "archived" }],
            view: { ...VIEW, lifecycle_status: "archived", available_actions: ["restore"] },
        })
        await openRow()
        expect(await screen.findByText(/Restore it to make changes/)).toBeInTheDocument()
        expect(screen.queryByRole("form", { name: "Edit relationship" })).toBeNull()
        fireEvent.click(screen.getByRole("button", { name: /^Perspectives/ }))
        expect(screen.getByText("Restore it to set perspectives.")).toBeInTheDocument()
        expect(screen.queryByRole("form", { name: "Set perspective" })).toBeNull()
        fireEvent.click(screen.getByRole("button", { name: /^End or archive/ }))
        expect(screen.getByRole("button", { name: "Restore relationship" })).toBeInTheDocument()
        expect(screen.queryByRole("button", { name: "Archive relationship" })).toBeNull()
        expect(screen.queryByRole("form", { name: "End relationship" })).toBeNull()
    })

    it("explains why End is missing for an undated or an already ended relationship", async () => {
        setup({ view: { ...VIEW, started: null, started_world_time_id: null, available_actions: ["update", "archive", "set_perspective"] } })
        await openRow(OPEN_FAMILY, "End or archive")
        expect(await screen.findByText("Set when it started (in Details) before ending it.")).toBeInTheDocument()
        expect(screen.queryByRole("form", { name: "End relationship" })).toBeNull()
        cleanup()
        setup({ view: { ...VIEW, ended: "Year 5", ended_world_time_id: "t5", available_actions: ["update", "archive", "set_perspective"] } })
        await openRow(OPEN_FAMILY, "End or archive")
        expect(await screen.findByText("Ended Year 5.")).toBeInTheDocument()
    })

    it("ends a relationship with the version it saw, and asks for a time first", async () => {
        const server = setup()
        server.on("GET", /world-times/, { body: { items: [{ world_time_id: "t5", label: "Year 5", display: "Year 5" }], next_cursor: null, can_create: true } })
        await openRow(OPEN_FAMILY, "End or archive")
        fireEvent.click(await screen.findByRole("button", { name: "End relationship" }))
        expect(await screen.findByText("Choose when it ended.")).toBeInTheDocument()
        expect(server.callsTo("POST", `${BASE}/r1/end`)).toHaveLength(0)
    })

    it("offers no action the server did not allow", async () => {
        setup({ view: { ...VIEW, available_actions: ["archive"] } })
        await openRow()
        expect(await screen.findByText(/Nothing in this relationship can be corrected here/)).toBeInTheDocument()
        expect(screen.queryByRole("form", { name: "Edit relationship" })).toBeNull()
        fireEvent.click(screen.getByRole("button", { name: /^Perspectives/ }))
        expect(screen.getByText("Perspectives cannot be set here.")).toBeInTheDocument()
        fireEvent.click(screen.getByRole("button", { name: /^End or archive/ }))
        expect(screen.getByRole("button", { name: "Archive relationship" })).toBeInTheDocument()
        expect(screen.queryByRole("form", { name: "End relationship" })).toBeNull()
    })

    it("shows each kind's own fields and sends only that kind's payload", async () => {
        const cases: [string, object, string[], object][] = [
            ["political", { is_active: false, treaty_terms: "Peace" }, ["In force", "Terms"], { is_active: false, treaty_terms: "Peace" }],
            [
                "route",
                { distance_text: "9 mi", travel_time_text: "2 days", travel_mode: "foot", is_hidden: true },
                ["Distance", "Travel time", "Mode of travel", "Concealed"],
                { distance_text: "9 mi", travel_time_text: "2 days", travel_mode: "foot", is_hidden: true },
            ],
            ["employment", { job_title: "Cook" }, ["Job title"], { job_title: "Cook" }],
            ["ownership", { ownership_share: 40, is_public: false }, ["Share (0 to 100)", "Known to the public"], { ownership_share: 40, is_public: false }],
            ["family", { family_unit_name: "House Vale" }, ["Family name"], { family_unit_name: "House Vale" }],
        ]
        for (const [kind, typed, labels, expected] of cases) {
            const server = setup({ view: { ...VIEW, kind, kind_label: kind, typed }, summaries: [{ ...SUMMARY, kind }] })
            await openRow()
            const form = await screen.findByRole("form", { name: "Edit relationship" })
            for (const label of labels) expect(within(form).getByLabelText(label)).toBeInTheDocument()
            fireEvent.change(within(form).getByRole("textbox", { name: "Description" }), { target: { value: `${kind} note` } })
            fireEvent.click(within(form).getByRole("button", { name: "Save relationship" }))
            await vi.waitFor(() => expect(server.callsTo("POST", `${BASE}/r1/update`)).toHaveLength(1))
            expect(server.callsTo("POST", `${BASE}/r1/update`)[0]!.body).toMatchObject({
                expected_row_version: 2,
                description: `${kind} note`,
                started_world_time_id: "t1",
                ...expected,
            })
            cleanup()
        }
    })

    it("refuses a share outside 0 to 100 without sending", async () => {
        const server = setup({
            view: { ...VIEW, kind: "ownership", typed: { ownership_share: 40, is_public: true } },
            summaries: [{ ...SUMMARY, kind: "ownership" }],
        })
        await openRow()
        const form = await screen.findByRole("form", { name: "Edit relationship" })
        fireEvent.change(within(form).getByRole("textbox", { name: "Share (0 to 100)" }), { target: { value: "140" } })
        fireEvent.click(within(form).getByRole("button", { name: "Save relationship" }))
        expect(await within(form).findByText("Share is a whole number from 0 to 100.")).toBeInTheDocument()
        expect(server.callsTo("POST", `${BASE}/r1/update`)).toHaveLength(0)
    })

    it("shows the status and period in the editor's header, with In force for a political one", async () => {
        setup({
            view: {
                ...VIEW,
                kind: "political",
                kind_label: "Political",
                ended: "Year 2",
                period_status: "ended",
                typed: { is_active: false, treaty_terms: null },
                current_status_label: "Estranged",
                available_actions: ["update", "archive", "set_perspective"],
            },
            summaries: [{ ...SUMMARY, kind: "political" }],
        })
        await openRow()
        expect(await screen.findByText(/Political · Year 1 to Year 2 — ended · In force: No · Timeline status: Estranged/)).toBeInTheDocument()
    })

    it("sends no request for a membership's office or end, and links to Members and offices instead", async () => {
        const MEMBER = {
            ...SUMMARY,
            kind: "membership",
            relationship_type: "membership",
            relationship_type_label: "Membership",
            participants: [participant("e1", "Varek", "member", "Member"), { ...participant("org1", "The Gilded Scale", "organization", "Organization"), entity_type_code: "organization" }],
        }
        const server = setup({
            kind: "npc",
            summaries: [MEMBER],
            view: { ...VIEW, kind: "membership", kind_label: "Membership", typed: { role: "Clerk", rank: "Third", is_public: true }, participants: MEMBER.participants, available_actions: ["update", "end", "archive", "set_perspective"] },
        })
        await openRow(/^Open Membership with The Gilded Scale$/)
        await screen.findByText("Clerk")
        expect(screen.getAllByRole("link", { name: "Members and offices" })[0]).toHaveAttribute("href", "/app/c1/world/organization/org1?section=members")
        fireEvent.click(screen.getByRole("button", { name: /^End or archive/ }))
        expect(screen.queryByRole("form", { name: "End relationship" })).toBeNull()
        expect(screen.getByText(/Ending a membership is done in/)).toBeInTheDocument()
        expect(server.callsTo("POST", /authoring\/relationships/)).toHaveLength(0)
    })
})

describe("RelationshipsPanel: a flag the read does not carry is not invented", () => {
    const withTyped = (kind: string, typed: object, actions = ["update", "archive", "set_perspective"]) => ({
        view: { ...VIEW, kind, kind_label: kind, typed, available_actions: actions },
        summaries: [{ ...SUMMARY, kind }],
    })

    it.each([
        ["ownership", "Known to the public", "is_public", "Yes", "No, only editors see it"],
        ["route", "Concealed", "is_hidden", "Yes", "No"],
        ["political", "In force", "is_active", "Yes", "No"],
    ])("%s: archived facts say true, false and missing differently", async (kind, label, field, yes, no) => {
        for (const [value, expected] of [
            [true, kind === "route" ? yes : yes],
            [false, no],
            [undefined, "Not recorded"],
            [null, "Not recorded"],
        ] as [boolean | null | undefined, string][]) {
            const typed = value === undefined ? {} : { [field]: value }
            const o = withTyped(kind, typed, ["restore"])
            setup({ ...o, view: { ...o.view, lifecycle_status: "archived" } })
            await openRow()
            const term = await screen.findByText(label, { selector: "dt" })
            expect(term.nextSibling).toHaveTextContent(expected)
            cleanup()
        }
    })

    it("a membership's visibility is not recorded rather than yes when missing", async () => {
        const MEMBER = {
            ...SUMMARY,
            kind: "membership",
            relationship_type_label: "Membership",
            participants: [participant("e1", "Varek", "member", "Member"), participant("org1", "Guild", "organization", "Organization")],
        }
        setup({
            kind: "npc",
            summaries: [MEMBER],
            view: { ...VIEW, kind: "membership", typed: { role: "Clerk", rank: null }, participants: MEMBER.participants },
        })
        await openRow(/^Open Membership with Guild$/)
        expect((await screen.findByText("Known to the public", { selector: "dt" })).nextSibling).toHaveTextContent("Not recorded")
    })

    it.each([
        ["ownership", { ownership_share: 40 }, "Known to the public", "is_public"],
        ["route", { distance_text: "9 mi" }, "Concealed", "is_hidden"],
        ["political", { treaty_terms: "Peace" }, "In force", "is_active"],
    ])("%s: an unrelated save sends no fabricated %s, and an explicit choice is sent", async (kind, typed, label, field) => {
        const o = withTyped(kind, typed)
        const server = setup(o)
        await openRow()
        const form = await screen.findByRole("form", { name: "Edit relationship" })
        const select = within(form).getByRole("combobox", { name: label })
        expect(select).toHaveValue("")
        expect(within(select).getByRole("option", { name: "Not recorded" })).toBeInTheDocument()
        fireEvent.change(within(form).getByRole("textbox", { name: "Description" }), { target: { value: "note" } })
        fireEvent.click(within(form).getByRole("button", { name: "Save relationship" }))
        await vi.waitFor(() => expect(server.callsTo("POST", `${BASE}/r1/update`)).toHaveLength(1))
        const body = server.callsTo("POST", `${BASE}/r1/update`)[0]!.body as Record<string, unknown>
        expect(body).toMatchObject({ description: "note" })
        expect(body).not.toHaveProperty(field)
        await within(form).findByText("Relationship saved")
        fireEvent.change(select, { target: { value: "no" } })
        fireEvent.click(within(form).getByRole("button", { name: "Save relationship" }))
        await vi.waitFor(() => expect(server.callsTo("POST", `${BASE}/r1/update`)).toHaveLength(2))
        expect(server.callsTo("POST", `${BASE}/r1/update`)[1]!.body).toMatchObject({ [field]: false })
    })

    it("keeps true and false as they are in the editable form", async () => {
        setup(withTyped("ownership", { ownership_share: 40, is_public: false }))
        await openRow()
        const form = await screen.findByRole("form", { name: "Edit relationship" })
        expect(within(form).getByRole("combobox", { name: "Known to the public" })).toHaveValue("no")
    })
})

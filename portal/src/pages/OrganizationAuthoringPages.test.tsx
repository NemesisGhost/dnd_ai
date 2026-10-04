import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { TEST_CSRF, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import { CreateOrganizationPage, EditOrganizationPage } from "./OrganizationAuthoringPages"

const FIELD = (
    name: string,
    kind: string,
    label: string,
    extra: object = {},
) => ({
    name,
    kind,
    label,
    max_length: null,
    minimum: null,
    maximum: null,
    required: false,
    options: [],
    ...extra,
})

const OPTIONS = {
    can_create: true,
    kinds: [
        {
            code: "organization",
            label: "Organization",
            needs_religion: false,
            fields: [
                FIELD("organization_type", "select", "Kind of organization", {
                    required: true,
                    options: [
                        { value: "guild", label: "Guild" },
                        { value: "other", label: "Other" },
                    ],
                }),
            ],
        },
        {
            code: "business",
            label: "Business",
            needs_religion: false,
            fields: [
                FIELD("business_type", "text", "Kind of business", { max_length: 200 }),
                FIELD("reputation", "integer", "Reputation", { minimum: -100, maximum: 100 }),
            ],
        },
        { code: "religious_organization", label: "Religious organization", needs_religion: true, fields: [] },
    ],
    limits: {
        name_max_length: 200,
        summary_max_length: 4000,
        description_max_length: 4000,
        change_note_max_length: 1000,
    },
    generic_types: [],
}

const VIEW = {
    organization_id: "o1",
    name: "Forge",
    summary: null,
    kind: { code: "business", label: "Business" },
    organization_type: "business",
    public_description: "Known for steel",
    internal_description: "Fronts for the guild",
    parent: { entity_id: "p1", name: "Crown", canon_status: "canon", lifecycle_status: "active" },
    headquarters: { entity_id: "h1", name: "Keep", canon_status: "draft", lifecycle_status: "active" },
    religion: null,
    typed: { business_type: "Smithy", reputation: 10 },
    canon_status: "draft",
    lifecycle_status: "active",
    row_version: 3,
    available_actions: ["update"],
    blocked_actions: [],
    field_locks: [],
}

const OPTIONS_PATH = "/campaigns/c1/authoring/organizations/options"
const CREATE_PATH = "/campaigns/c1/authoring/organizations"
const VIEW_PATH = "/campaigns/c1/authoring/organizations/o1"
const UPDATE_PATH = "/campaigns/c1/authoring/organizations/o1/update"

function mockSearches(server: ReturnType<typeof installMockServer>) {
    server.on("GET", /\/authoring\/organizations\/parent-options/, {
        body: { items: [{ organization_id: "p2", name: "Council", kind: "government", canon_status: "canon" }], next_cursor: null },
    })
    server.on("GET", /\/authoring\/locations\/parent-options/, {
        body: { items: [{ location_id: "h2", name: "Citadel", category: { code: "building", label: "Building" }, canon_status: "canon" }], next_cursor: null },
    })
    server.on("GET", /\/authoring\/religions\/reference-options/, {
        body: { items: [{ religion_id: "r1", name: "Old Way", canon_status: "canon" }], next_cursor: null },
    })
}

function setupCreate() {
    const server = installMockServer()
    server.on("GET", OPTIONS_PATH, { body: OPTIONS })
    mockSearches(server)
    const rendered = renderAuthoringRoutes({
        initialEntry: "/app/c1/world/organization/new",
        routes: [
            { path: "/app/:campaignId/world/organization/new", element: <CreateOrganizationPage /> },
            { path: "/app/:campaignId/world/organization/:entityId", element: <p>Organization detail page</p> },
            { path: "/app/:campaignId/world", element: <p>World page</p> },
        ],
    })
    return { server, ...rendered }
}

function setupEdit(initial: object = VIEW) {
    const server = installMockServer()
    let current: object = initial
    server.on("GET", VIEW_PATH, () => ({ body: current }))
    server.on("GET", OPTIONS_PATH, { body: OPTIONS })
    mockSearches(server)
    const rendered = renderAuthoringRoutes({
        initialEntry: "/app/c1/world/organization/o1/edit",
        routes: [
            { path: "/app/:campaignId/world/organization/:entityId/edit", element: <EditOrganizationPage /> },
            { path: "/app/:campaignId/world/organization/:entityId", element: <p>Organization detail page</p> },
        ],
    })
    return { server, setCurrent: (next: object) => (current = next), ...rendered }
}

const kind = () => screen.getByRole("combobox", { name: /^Kind/ })
const nameField = () => screen.getByRole("textbox", { name: /Name/ })

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("CreateOrganizationPage", () => {
    it("lists the server's kinds and renders each kind's own fields", async () => {
        setupCreate()
        await screen.findByRole("combobox", { name: /^Kind/ })
        expect(within(kind()).getAllByRole("option").map((o) => o.textContent)).toEqual([
            "Choose a kind",
            "Organization",
            "Business",
            "Religious organization",
        ])
        fireEvent.change(kind(), { target: { value: "business" } })
        expect(screen.getByRole("textbox", { name: "Kind of business" })).toBeInTheDocument()
        expect(screen.getByRole("textbox", { name: "Reputation" })).toBeInTheDocument()
        expect(screen.queryByRole("combobox", { name: "Religion" })).toBeNull()
        fireEvent.change(kind(), { target: { value: "religious_organization" } })
        expect(screen.getByRole("combobox", { name: "Religion" })).toBeInTheDocument()
        expect(screen.queryByRole("textbox", { name: "Kind of business" })).toBeNull()
        fireEvent.change(kind(), { target: { value: "organization" } })
        expect(screen.getByRole("combobox", { name: /Kind of organization/ })).toBeInTheDocument()
    })

    it("labels GM notes as never shown to players", async () => {
        setupCreate()
        await screen.findByRole("combobox", { name: /^Kind/ })
        const notes = screen.getByRole("textbox", { name: "GM notes" })
        expect(document.getElementById(notes.getAttribute("aria-describedby")!)).toHaveTextContent(
            "Never shown to players",
        )
    })

    it("requires a kind, a name, and (for religious organizations) a religion", async () => {
        const { server } = setupCreate()
        await screen.findByRole("combobox", { name: /^Kind/ })
        fireEvent.click(screen.getByRole("button", { name: "Create organization" }))
        const summary = await screen.findByRole("alert")
        expect(summary).toHaveTextContent("Choose a kind of organization.")
        expect(summary).toHaveTextContent("Name is required.")

        fireEvent.change(kind(), { target: { value: "religious_organization" } })
        fireEvent.change(nameField(), { target: { value: "Temple" } })
        fireEvent.click(screen.getByRole("button", { name: "Create organization" }))
        await waitFor(() =>
            expect(screen.getByRole("alert")).toHaveTextContent("Choose the religion this organization serves."),
        )
        expect(server.callsTo("POST", CREATE_PATH)).toHaveLength(0)
    })

    it("creates a business with flattened typed fields and references, then opens its detail", async () => {
        const { server, router } = setupCreate()
        server.on("POST", CREATE_PATH, { status: 201, body: { ...VIEW, changed: true } })
        await screen.findByRole("combobox", { name: /^Kind/ })
        fireEvent.change(kind(), { target: { value: "business" } })
        fireEvent.change(nameField(), { target: { value: " Forge " } })
        fireEvent.change(screen.getByRole("textbox", { name: "Kind of business" }), { target: { value: "Smithy" } })
        fireEvent.change(screen.getByRole("textbox", { name: "Reputation" }), { target: { value: "-5" } })
        fireEvent.focus(screen.getByRole("combobox", { name: "Part of" }))
        fireEvent.click(await screen.findByRole("option", { name: /Council/ }))
        fireEvent.focus(screen.getByRole("combobox", { name: "Headquarters" }))
        fireEvent.click(await screen.findByRole("option", { name: /Citadel/ }))
        fireEvent.click(screen.getByRole("button", { name: "Create organization" }))

        await screen.findByText("Organization detail page")
        const [call] = server.callsTo("POST", CREATE_PATH)
        expect(call!.headers["X-CSRF-Token"]).toBe(TEST_CSRF)
        expect(call!.body).toEqual({
            kind: "business",
            name: "Forge",
            summary: null,
            public_description: null,
            internal_description: null,
            parent_organization_id: "p2",
            headquarters_location_id: "h2",
            religion_id: null,
            business_type: "Smithy",
            reputation: -5,
        })
        expect(router.state.historyAction).toBe("REPLACE")
        expect(router.state.location.state).toEqual({ announce: "Organization created as a draft" })
    })

    it("sends the chosen religion for a religious organization", async () => {
        const { server } = setupCreate()
        server.on("POST", CREATE_PATH, { status: 201, body: VIEW })
        await screen.findByRole("combobox", { name: /^Kind/ })
        fireEvent.change(kind(), { target: { value: "religious_organization" } })
        fireEvent.change(nameField(), { target: { value: "Temple" } })
        fireEvent.focus(screen.getByRole("combobox", { name: "Religion" }))
        fireEvent.click(await screen.findByRole("option", { name: /Old Way/ }))
        fireEvent.click(screen.getByRole("button", { name: "Create organization" }))
        await screen.findByText("Organization detail page")
        expect(server.callsTo("POST", CREATE_PATH)[0]!.body).toMatchObject({
            kind: "religious_organization",
            religion_id: "r1",
        })
    })

    it("maps each reference error to its own field and keeps the input", async () => {
        const { server } = setupCreate()
        await screen.findByRole("combobox", { name: /^Kind/ })
        fireEvent.change(kind(), { target: { value: "business" } })
        fireEvent.change(nameField(), { target: { value: "Forge" } })
        const cases: [string, string][] = [
            ["organization_parent_invalid", "Part of"],
            ["headquarters_location_invalid", "Headquarters"],
        ]
        for (const [code, label] of cases) {
            server.on("POST", CREATE_PATH, {
                status: 400,
                body: { error: { code, message: "m", correlation_id: "c" } },
            })
            fireEvent.click(screen.getByRole("button", { name: "Create organization" }))
            await waitFor(() =>
                expect(screen.getByRole("combobox", { name: label })).toHaveAttribute("aria-invalid", "true"),
            )
            expect(nameField()).toHaveValue("Forge")
        }
    })

    it("explains a refused options read", async () => {
        const server = installMockServer()
        server.on("GET", OPTIONS_PATH, { status: 403 })
        renderAuthoringRoutes({
            initialEntry: "/app/c1/world/organization/new",
            routes: [{ path: "/app/:campaignId/world/organization/new", element: <CreateOrganizationPage /> }],
        })
        expect(await screen.findByRole("alert")).toHaveTextContent("do not have permission to create organizations")
    })
})

describe("EditOrganizationPage", () => {
    it("pre-fills everything including kind-specific fields, with the kind fixed", async () => {
        setupEdit()
        await screen.findByRole("textbox", { name: /Name/ })
        expect(nameField()).toHaveValue("Forge")
        expect(screen.getByRole("textbox", { name: "Public description" })).toHaveValue("Known for steel")
        expect(screen.getByRole("textbox", { name: "GM notes" })).toHaveValue("Fronts for the guild")
        expect(screen.getByRole("textbox", { name: "Kind of business" })).toHaveValue("Smithy")
        expect(screen.getByRole("textbox", { name: "Reputation" })).toHaveValue("10")
        expect(screen.getByRole("combobox", { name: "Part of" })).toHaveValue("Crown")
        expect(screen.getByRole("combobox", { name: "Headquarters" })).toHaveValue("Keep")
        expect(screen.queryByRole("combobox", { name: /^Kind/ })).toBeNull()
        expect(screen.getByText("Business")).toBeInTheDocument()
    })

    it("saves against the loaded version, excluding itself from parent options", async () => {
        const { server } = setupEdit()
        server.on("POST", UPDATE_PATH, { body: { ...VIEW, row_version: 4 } })
        await screen.findByRole("textbox", { name: /Name/ })
        fireEvent.change(screen.getByRole("textbox", { name: "Reputation" }), { target: { value: "20" } })
        fireEvent.focus(screen.getByRole("combobox", { name: "Part of" }))
        await screen.findByRole("option", { name: /Council/ })
        expect(server.callsTo("GET", /parent-options/).some((c) => c.path.includes("for=o1"))).toBe(true)
        fireEvent.keyDown(screen.getByRole("combobox", { name: "Part of" }), { key: "Escape" })
        fireEvent.click(screen.getByRole("button", { name: "Save" }))

        await screen.findByText("Organization detail page")
        expect(server.callsTo("POST", UPDATE_PATH)[0]!.body).toEqual({
            expected_row_version: 3,
            name: "Forge",
            summary: null,
            public_description: "Known for steel",
            internal_description: "Fronts for the guild",
            parent_organization_id: "p1",
            headquarters_location_id: "h1",
            religion_id: null,
            business_type: "Smithy",
            reputation: 20,
            change_note: null,
        })
    })

    it("recovers from a stale write and keeps the user's values", async () => {
        const { server, setCurrent } = setupEdit()
        server.on("POST", UPDATE_PATH, {
            status: 409,
            body: { error: { code: "stale_write", message: "m", correlation_id: "c" } },
        })
        await screen.findByRole("textbox", { name: /Name/ })
        fireEvent.change(nameField(), { target: { value: "My rename" } })
        fireEvent.click(screen.getByRole("button", { name: "Save" }))
        expect(await screen.findByRole("alert")).toHaveTextContent("Someone else changed this record")

        setCurrent({ ...VIEW, name: "Their rename", row_version: 5 })
        fireEvent.click(screen.getByRole("button", { name: "Load latest version" }))
        await waitFor(() => expect(nameField()).toHaveValue("Their rename"))
        expect(screen.getByRole("region", { name: "Your unsaved changes" })).toHaveTextContent("My rename")
        fireEvent.click(screen.getByRole("button", { name: "Re-apply my changes" }))
        expect(nameField()).toHaveValue("My rename")
    })

    it("asks for confirmation before changing a published organization", async () => {
        const { server } = setupEdit({ ...VIEW, canon_status: "canon" })
        server.on("POST", UPDATE_PATH, { body: { ...VIEW, row_version: 4 } })
        await screen.findByRole("textbox", { name: /Name/ })
        fireEvent.change(nameField(), { target: { value: "Forge II" } })
        fireEvent.click(screen.getByRole("button", { name: "Save" }))
        const dialog = await screen.findByRole("dialog", { name: "Save changes to a published organization?" })
        expect(server.callsTo("POST", UPDATE_PATH)).toHaveLength(0)
        fireEvent.click(within(dialog).getByRole("button", { name: "Save changes" }))
        await screen.findByText("Organization detail page")
    })

    it("maps a hierarchy cycle onto the parent field", async () => {
        const { server } = setupEdit()
        server.on("POST", UPDATE_PATH, {
            status: 409,
            body: { error: { code: "organization_hierarchy_cycle", message: "m", correlation_id: "c" } },
        })
        await screen.findByRole("textbox", { name: /Name/ })
        fireEvent.change(nameField(), { target: { value: "Moved" } })
        fireEvent.click(screen.getByRole("button", { name: "Save" }))
        expect(await screen.findByRole("alert")).toHaveTextContent("inside itself")
        expect(screen.getByRole("combobox", { name: "Part of" })).toHaveAttribute("aria-invalid", "true")
    })

    it("shows the non-disclosing state for a missing organization", async () => {
        const server = installMockServer()
        server.on("GET", VIEW_PATH, { status: 404 })
        server.on("GET", OPTIONS_PATH, { body: OPTIONS })
        renderAuthoringRoutes({
            initialEntry: "/app/c1/world/organization/o1/edit",
            routes: [{ path: "/app/:campaignId/world/organization/:entityId/edit", element: <EditOrganizationPage /> }],
        })
        expect(await screen.findByRole("alert")).toHaveTextContent(
            "This organization does not exist, or you do not have access to it.",
        )
    })

    it("never presents a raw identifier", async () => {
        setupEdit({
            ...VIEW,
            organization_id: "3f2b8c1e-5d4a-4e7b-9c1d-2a6f8b0e4d11",
            parent: { ...VIEW.parent, entity_id: "9a1c2d3e-4f50-4a6b-8c7d-0e1f2a3b4c5d" },
        })
        await screen.findByRole("textbox", { name: /Name/ })
        const text = [document.body.textContent ?? ""]
        for (const input of document.querySelectorAll("input, textarea, select")) {
            text.push((input as HTMLInputElement).value)
        }
        expect(text.join(" ")).not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i)
    })
})

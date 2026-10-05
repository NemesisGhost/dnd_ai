import { act, fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { TEST_CSRF, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import { CreateLocationPage } from "./CreateLocationPage"

const OPTIONS = {
    can_create: true,
    categories: [
        { code: "region", label: "Region", fields: [] },
        {
            code: "settlement",
            label: "Settlement",
            fields: [
                { name: "population", kind: "integer", label: "Population", max_length: null, minimum: 0, maximum: 2147483647 },
            ],
        },
        {
            code: "building",
            label: "Building",
            fields: [
                { name: "building_use", kind: "text", label: "Use", max_length: 200, minimum: null, maximum: null },
            ],
        },
    ],
    limits: { name_max_length: 200, summary_max_length: 4000, change_note_max_length: 1000 },
}

const CREATED = {
    location_id: "loc-new",
    name: "Hollow",
    summary: null,
    category: { code: "settlement", label: "Settlement" },
    parent: null,
    population: 1200,
    building_use: null,
    canon_status: "draft",
    lifecycle_status: "active",
    row_version: 1,
    available_actions: ["update"],
    blocked_actions: [],
    field_locks: [],
    changed: true,
}

const OPTIONS_PATH = "/campaigns/c1/authoring/locations/options"
const CREATE_PATH = "/campaigns/c1/authoring/locations"

function setup() {
    const server = installMockServer()
    server.on("GET", OPTIONS_PATH, { body: OPTIONS })
    server.on("GET", /parent-options/, {
        body: {
            items: [
                { location_id: "p1", name: "Ashen Vale", category: { code: "region", label: "Region" }, canon_status: "canon" },
            ],
            next_cursor: null,
        },
    })
    const rendered = renderAuthoringRoutes({
        initialEntry: "/app/c1/world/location/new",
        routes: [
            { path: "/app/:campaignId/world/location/new", element: <CreateLocationPage /> },
            { path: "/app/:campaignId/world/location/:entityId", element: <p>Location detail page</p> },
            { path: "/app/:campaignId/world", element: <p>World page</p> },
        ],
    })
    return { server, ...rendered }
}

const category = () => screen.getByRole("combobox", { name: /Category/ })
const nameField = () => screen.getByRole("textbox", { name: /Name/ })

async function ready() {
    await screen.findByRole("combobox", { name: /Category/ })
}

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("CreateLocationPage", () => {
    it("renders one h1, takes focus on it once loaded, and sends no write on open", async () => {
        const { server } = setup()
        await ready()
        expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1)
        expect(screen.getByRole("heading", { level: 1, name: "New location" })).toHaveFocus()
        expect(server.callsTo("POST", /./)).toEqual([])
    })

    it("explains a refused options read without showing a form", async () => {
        const server = installMockServer()
        server.on("GET", OPTIONS_PATH, { status: 403 })
        renderAuthoringRoutes({
            initialEntry: "/app/c1/world/location/new",
            routes: [{ path: "/app/:campaignId/world/location/new", element: <CreateLocationPage /> }],
        })
        expect(await screen.findByRole("alert")).toHaveTextContent("do not have permission")
        expect(screen.queryByRole("combobox", { name: /Category/ })).toBeNull()
    })

    it("offers the server's categories and shows only the chosen category's typed fields", async () => {
        setup()
        await ready()
        expect(within(category()).getAllByRole("option").map((o) => o.textContent)).toEqual([
            "Choose a category",
            "Region",
            "Settlement",
            "Building",
        ])
        expect(screen.queryByRole("textbox", { name: "Population" })).toBeNull()
        fireEvent.change(category(), { target: { value: "settlement" } })
        expect(screen.getByRole("textbox", { name: "Population" })).toBeInTheDocument()
        expect(screen.queryByRole("textbox", { name: "Use" })).toBeNull()
        fireEvent.change(category(), { target: { value: "building" } })
        expect(screen.getByRole("textbox", { name: "Use" })).toBeInTheDocument()
        expect(screen.queryByRole("textbox", { name: "Population" })).toBeNull()
    })

    it("drops a typed field when the category changes and never sends it", async () => {
        const { server } = setup()
        server.on("POST", CREATE_PATH, { status: 201, body: CREATED })
        await ready()
        fireEvent.change(category(), { target: { value: "settlement" } })
        fireEvent.change(screen.getByRole("textbox", { name: "Population" }), { target: { value: "500" } })
        fireEvent.change(category(), { target: { value: "region" } })
        fireEvent.change(nameField(), { target: { value: "The Vale" } })
        fireEvent.click(screen.getByRole("button", { name: "Create location" }))

        await screen.findByText("Location detail page")
        const [call] = server.callsTo("POST", CREATE_PATH)
        expect(call!.body).toMatchObject({ category: "region", population: null, building_use: null })
    })

    it("validates before sending, focuses the summary, and keeps the input", async () => {
        const { server } = setup()
        await ready()
        fireEvent.change(nameField(), { target: { value: "  " } })
        fireEvent.click(screen.getByRole("button", { name: "Create location" }))

        const summary = await screen.findByRole("alert")
        expect(summary).toHaveTextContent("Choose a category.")
        expect(summary).toHaveTextContent("Name is required.")
        await waitFor(() => expect(summary).toHaveFocus())
        expect(server.callsTo("POST", CREATE_PATH)).toHaveLength(0)
        expect(nameField()).toHaveAttribute("aria-invalid", "true")

        fireEvent.click(within(summary).getByRole("link", { name: "Choose a category." }))
        expect(category()).toHaveFocus()
    })

    it("creates a draft with the CSRF token and a parent, then replaces history and announces", async () => {
        const { server, router } = setup()
        server.on("POST", CREATE_PATH, { status: 201, body: CREATED })
        await ready()
        fireEvent.change(category(), { target: { value: "settlement" } })
        fireEvent.change(nameField(), { target: { value: " Hollow " } })
        fireEvent.change(screen.getByRole("textbox", { name: "Population" }), { target: { value: "1200" } })
        const parent = screen.getByRole("combobox", { name: "Contained in" })
        fireEvent.focus(parent)
        fireEvent.click(await screen.findByRole("option", { name: /Ashen Vale/ }))
        fireEvent.click(screen.getByRole("button", { name: "Create location" }))

        await screen.findByText("Location detail page")
        const [call] = server.callsTo("POST", CREATE_PATH)
        expect(call!.headers["X-CSRF-Token"]).toBe(TEST_CSRF)
        expect(call!.headers["Idempotency-Key"]).toBeTruthy()
        expect(call!.body).toEqual({
            category: "settlement",
            name: "Hollow",
            summary: null,
            parent_location_id: "p1",
            population: 1200,
            building_use: null,
        })
        expect(router.state.location.pathname).toBe("/app/c1/world/location/loc-new")
        expect(router.state.historyAction).toBe("REPLACE")
        expect(router.state.location.state).toEqual({ announce: "Location created as a draft" })
    })

    it("prevents a duplicate submission while the request is pending", async () => {
        const { server } = setup()
        let release: (() => void) | undefined
        server.on("POST", CREATE_PATH, () =>
            new Promise((resolve) => {
                release = () => resolve({ status: 201, body: CREATED })
            }),
        )
        await ready()
        fireEvent.change(category(), { target: { value: "region" } })
        fireEvent.change(nameField(), { target: { value: "Vale" } })
        const submit = screen.getByRole("button", { name: "Create location" })
        fireEvent.click(submit)
        const pending = await screen.findByRole("button", { name: "Creating…" })
        expect(pending).toBeDisabled()
        fireEvent.click(pending)
        fireEvent.submit(screen.getByRole("form", { name: "New location" }))
        expect(server.callsTo("POST", CREATE_PATH)).toHaveLength(1)
        await act(async () => release?.())
        await screen.findByText("Location detail page")
    })

    it("keeps the input and the same idempotency key when a retry follows a server error", async () => {
        const { server } = setup()
        server.on("POST", CREATE_PATH, { status: 500 })
        await ready()
        fireEvent.change(category(), { target: { value: "region" } })
        fireEvent.change(nameField(), { target: { value: "Vale" } })
        fireEvent.click(screen.getByRole("button", { name: "Create location" }))
        fireEvent.click(await screen.findByRole("button", { name: "Retry" }))

        await waitFor(() => expect(server.callsTo("POST", CREATE_PATH)).toHaveLength(2))
        const [first, second] = server.callsTo("POST", CREATE_PATH)
        expect(second!.headers["Idempotency-Key"]).toBe(first!.headers["Idempotency-Key"])
        expect(nameField()).toHaveValue("Vale")

        // A changed body is a different request and gets a new key.
        fireEvent.change(nameField(), { target: { value: "Vale of Ash" } })
        fireEvent.click(screen.getByRole("button", { name: "Create location" }))
        await waitFor(() => expect(server.callsTo("POST", CREATE_PATH)).toHaveLength(3))
        const third = server.callsTo("POST", CREATE_PATH)[2]!
        expect(third.headers["Idempotency-Key"]).not.toBe(first!.headers["Idempotency-Key"])
    })

    it("maps an invalid parent onto the parent field and keeps everything entered", async () => {
        const { server } = setup()
        server.on("POST", CREATE_PATH, {
            status: 400,
            body: { error: { code: "parent_location_invalid", message: "m", correlation_id: "c" } },
        })
        await ready()
        fireEvent.change(category(), { target: { value: "region" } })
        fireEvent.change(nameField(), { target: { value: "Vale" } })
        fireEvent.click(screen.getByRole("button", { name: "Create location" }))

        const summary = await screen.findByRole("alert")
        expect(summary).toHaveTextContent("The selected parent location is not valid")
        expect(screen.getByRole("combobox", { name: "Contained in" })).toHaveAttribute("aria-invalid", "true")
        expect(nameField()).toHaveValue("Vale")
    })

    it("holds a dirty form behind an unsaved-changes dialog when leaving", async () => {
        const { router } = setup()
        await ready()
        fireEvent.change(nameField(), { target: { value: "Half written" } })
        await act(async () => {
            void router.navigate("/app/c1/world")
        })
        const dialog = await screen.findByRole("dialog", { name: "Discard this new location?" })
        fireEvent.click(within(dialog).getByRole("button", { name: "Keep editing" }))
        expect(router.state.location.pathname).toBe("/app/c1/world/location/new")
        expect(nameField()).toHaveValue("Half written")
    })

    it("lets a clean form leave without a prompt", async () => {
        const { router } = setup()
        await ready()
        await act(async () => {
            void router.navigate("/app/c1/world")
        })
        await screen.findByText("World page")
        expect(screen.queryByRole("dialog")).toBeNull()
    })

    it("cancels back to the World list", async () => {
        setup()
        await ready()
        fireEvent.click(screen.getByRole("button", { name: "Cancel" }))
        await screen.findByText("World page")
    })
})

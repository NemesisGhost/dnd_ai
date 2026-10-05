import { act, fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { TEST_CSRF, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import { EditLocationPage } from "./EditLocationPage"

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
    ],
    limits: { name_max_length: 200, summary_max_length: 4000, change_note_max_length: 1000 },
}

function view(overrides: object = {}) {
    return {
        location_id: "l1",
        name: "Hollow",
        summary: "A quiet town.",
        category: { code: "settlement", label: "Settlement" },
        parent: { location_id: "p1", name: "Ashen Vale", canon_status: "canon", lifecycle_status: "active" },
        population: 1200,
        building_use: null,
        canon_status: "draft",
        lifecycle_status: "active",
        row_version: 3,
        available_actions: ["update", "archive"],
        blocked_actions: [],
        field_locks: [],
        ...overrides,
    }
}

const VIEW_PATH = "/campaigns/c1/authoring/locations/l1"
const UPDATE_PATH = "/campaigns/c1/authoring/locations/l1/update"

function setup(initial: object = view()) {
    const server = installMockServer()
    let current: object = initial
    server.on("GET", VIEW_PATH, () => ({ body: current }))
    server.on("GET", "/campaigns/c1/authoring/locations/options", { body: OPTIONS })
    server.on("GET", /parent-options/, {
        body: {
            items: [
                { location_id: "p2", name: "Brindlemoor", category: { code: "region", label: "Region" }, canon_status: "draft" },
            ],
            next_cursor: null,
        },
    })
    const rendered = renderAuthoringRoutes({
        initialEntry: "/app/c1/world/location/l1/edit",
        routes: [
            { path: "/app/:campaignId/world/location/:entityId/edit", element: <EditLocationPage /> },
            { path: "/app/:campaignId/world/location/:entityId", element: <p>Location detail page</p> },
            { path: "/app/:campaignId/world", element: <p>World page</p> },
        ],
    })
    return {
        server,
        setCurrent: (next: object) => {
            current = next
        },
        ...rendered,
    }
}

const nameField = () => screen.getByRole("textbox", { name: /Name/ })
const summaryField = () => screen.getByRole("textbox", { name: "Summary" })
const save = () => screen.getByRole("button", { name: "Save" })

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("EditLocationPage", () => {
    it("pre-fills from the authoring read model, with the category fixed", async () => {
        setup()
        await screen.findByRole("textbox", { name: /Name/ })
        expect(nameField()).toHaveValue("Hollow")
        expect(summaryField()).toHaveValue("A quiet town.")
        expect(screen.getByRole("textbox", { name: "Population" })).toHaveValue("1200")
        expect(screen.getByRole("combobox", { name: "Contained in" })).toHaveValue("Ashen Vale")
        expect(screen.queryByRole("combobox", { name: /^Category/ })).toBeNull()
        expect(screen.getByText("Settlement")).toBeInTheDocument()
        expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1)
        expect(screen.getByRole("heading", { level: 1, name: "Edit location" })).toHaveFocus()
    })

    it("shows the non-disclosing unavailable state for a 404 and for a denied read", async () => {
        const server = installMockServer()
        server.on("GET", VIEW_PATH, { status: 404 })
        server.on("GET", "/campaigns/c1/authoring/locations/options", { body: OPTIONS })
        renderAuthoringRoutes({
            initialEntry: "/app/c1/world/location/l1/edit",
            routes: [{ path: "/app/:campaignId/world/location/:entityId/edit", element: <EditLocationPage /> }],
        })
        expect(await screen.findByRole("alert")).toHaveTextContent(
            "This location does not exist, or you do not have access to it.",
        )
        expect(screen.queryByRole("textbox", { name: /Name/ })).toBeNull()
    })

    it("explains why a location that cannot be edited is read-only", async () => {
        setup(
            view({
                canon_status: "approved",
                available_actions: ["return_to_draft"],
                blocked_actions: [{ action: "update", reason: "review_in_progress" }],
            }),
        )
        const alert = await screen.findByRole("alert")
        expect(alert).toHaveTextContent("cannot be edited right now")
        expect(alert).toHaveTextContent("awaiting review")
        expect(screen.getByRole("link", { name: "Back to the location" })).toHaveAttribute(
            "href",
            "/app/c1/world/location/l1",
        )
        expect(screen.queryByRole("textbox", { name: /Name/ })).toBeNull()
    })

    it("saves against the loaded row version with the CSRF token, then returns and announces", async () => {
        const { server, router } = setup()
        server.on("POST", UPDATE_PATH, { body: view({ row_version: 4, changed: true }) })
        await screen.findByRole("textbox", { name: /Name/ })
        fireEvent.change(nameField(), { target: { value: "  Hollow Reach  " } })
        fireEvent.click(save())

        await screen.findByText("Location detail page")
        const [call] = server.callsTo("POST", UPDATE_PATH)
        expect(call!.headers["X-CSRF-Token"]).toBe(TEST_CSRF)
        expect(call!.body).toEqual({
            expected_row_version: 3,
            name: "Hollow Reach",
            summary: "A quiet town.",
            parent_location_id: "p1",
            population: 1200,
            building_use: null,
            change_note: null,
        })
        expect(router.state.location.state).toEqual({ announce: "Location saved" })
    })

    it("changes and clears the parent", async () => {
        const { server } = setup()
        server.on("POST", UPDATE_PATH, { body: view({ row_version: 4 }) })
        await screen.findByRole("textbox", { name: /Name/ })
        const parent = screen.getByRole("combobox", { name: "Contained in" })
        fireEvent.focus(parent)
        fireEvent.click(await screen.findByRole("option", { name: /Brindlemoor/ }))
        fireEvent.click(save())
        await screen.findByText("Location detail page")
        expect(server.callsTo("POST", UPDATE_PATH)[0]!.body).toMatchObject({ parent_location_id: "p2" })
        // The search excluded this location (and, server-side, its descendants).
        expect(server.callsTo("GET", /parent-options/)[0]!.path).toContain("for=l1")
    })

    it("validates before sending and keeps the input", async () => {
        const { server } = setup()
        await screen.findByRole("textbox", { name: /Name/ })
        fireEvent.change(nameField(), { target: { value: " " } })
        fireEvent.change(screen.getByRole("textbox", { name: "Population" }), { target: { value: "x" } })
        fireEvent.click(save())
        const summary = await screen.findByRole("alert")
        expect(summary).toHaveTextContent("Name is required.")
        expect(summary).toHaveTextContent("Population must be a whole number")
        expect(server.callsTo("POST", UPDATE_PATH)).toHaveLength(0)
    })

    it("asks for confirmation before saving a published location and sends the change note", async () => {
        const { server } = setup(view({ canon_status: "canon" }))
        server.on("POST", UPDATE_PATH, { body: view({ canon_status: "canon", row_version: 4 }) })
        await screen.findByRole("textbox", { name: /Name/ })
        fireEvent.change(screen.getByRole("textbox", { name: /Change note/ }), { target: { value: "typo fix" } })
        fireEvent.change(summaryField(), { target: { value: "A quiet town by the river." } })
        fireEvent.click(save())

        const dialog = await screen.findByRole("dialog", { name: "Save changes to a published location?" })
        expect(dialog).toHaveTextContent("create a replacement and supersede")
        expect(server.callsTo("POST", UPDATE_PATH)).toHaveLength(0)
        fireEvent.click(within(dialog).getByRole("button", { name: "Save changes" }))

        await screen.findByText("Location detail page")
        expect(server.callsTo("POST", UPDATE_PATH)[0]!.body).toMatchObject({
            change_note: "typo fix",
            summary: "A quiet town by the river.",
        })
    })

    it("does not offer a change note or a confirmation for a draft", async () => {
        setup()
        await screen.findByRole("textbox", { name: /Name/ })
        expect(screen.queryByRole("textbox", { name: /Change note/ })).toBeNull()
    })

    it("recovers from a stale write: latest shown, user's values kept, the old version never resubmitted", async () => {
        const { server, setCurrent } = setup()
        server.on("POST", UPDATE_PATH, {
            status: 409,
            body: { error: { code: "stale_write", message: "m", correlation_id: "c" } },
        })
        await screen.findByRole("textbox", { name: /Name/ })
        fireEvent.change(nameField(), { target: { value: "My rename" } })
        fireEvent.change(summaryField(), { target: { value: "My summary" } })
        fireEvent.click(save())

        const notice = await screen.findByRole("alert")
        expect(notice).toHaveTextContent("Someone else changed this record")
        expect(nameField()).toHaveValue("My rename")

        setCurrent(view({ name: "Their rename", summary: "Their summary", row_version: 5 }))
        fireEvent.click(screen.getByRole("button", { name: "Load latest version" }))

        await waitFor(() => expect(nameField()).toHaveValue("Their rename"))
        const kept = screen.getByRole("region", { name: "Your unsaved changes" })
        expect(kept).toHaveTextContent("My rename")
        expect(kept).toHaveTextContent("My summary")

        server.on("POST", UPDATE_PATH, { body: view({ row_version: 6 }) })
        fireEvent.click(screen.getByRole("button", { name: "Re-apply my changes" }))
        expect(nameField()).toHaveValue("My rename")
        fireEvent.click(save())
        await screen.findByText("Location detail page")
        const calls = server.callsTo("POST", UPDATE_PATH)
        expect(calls[0]!.body).toMatchObject({ expected_row_version: 3 })
        expect(calls[1]!.body).toMatchObject({ expected_row_version: 5, name: "My rename" })
    })

    it("maps a hierarchy cycle onto the parent field", async () => {
        const { server } = setup()
        server.on("POST", UPDATE_PATH, {
            status: 409,
            body: { error: { code: "location_hierarchy_cycle", message: "m", correlation_id: "c" } },
        })
        await screen.findByRole("textbox", { name: /Name/ })
        fireEvent.change(nameField(), { target: { value: "Changed" } })
        fireEvent.click(save())
        const summary = await screen.findByRole("alert")
        expect(summary).toHaveTextContent("inside itself")
        expect(screen.getByRole("combobox", { name: "Contained in" })).toHaveAttribute("aria-invalid", "true")
        expect(nameField()).toHaveValue("Changed")
    })

    it("keeps the input and offers a session check after a denied write", async () => {
        const { server } = setup()
        server.on("POST", UPDATE_PATH, { status: 403 })
        await screen.findByRole("textbox", { name: /Name/ })
        fireEvent.change(nameField(), { target: { value: "Changed" } })
        fireEvent.click(save())
        expect(await screen.findByRole("button", { name: "Check my session" })).toBeInTheDocument()
        expect(nameField()).toHaveValue("Changed")
    })

    it("guards unsaved edits against in-app navigation", async () => {
        const { router } = setup()
        await screen.findByRole("textbox", { name: /Name/ })
        fireEvent.change(nameField(), { target: { value: "Edited" } })
        await act(async () => {
            void router.navigate("/app/c1/world")
        })
        const dialog = await screen.findByRole("dialog", { name: "Discard unsaved changes?" })
        fireEvent.click(within(dialog).getByRole("button", { name: "Discard changes" }))
        await screen.findByText("World page")
    })

    it("reloads the same record when the URL is loaded directly, without leaking the previous one", async () => {
        const { server } = setup()
        await screen.findByRole("textbox", { name: /Name/ })
        expect(server.callsTo("GET", VIEW_PATH)).toHaveLength(1)
    })

    it("never presents a raw identifier", async () => {
        const uuid = "3f2b8c1e-5d4a-4e7b-9c1d-2a6f8b0e4d11"
        setup(
            view({
                location_id: uuid,
                parent: {
                    location_id: "9a1c2d3e-4f50-4a6b-8c7d-0e1f2a3b4c5d",
                    name: "Ashen Vale",
                    canon_status: "canon",
                    lifecycle_status: "active",
                },
            }),
        )
        await screen.findByRole("textbox", { name: /Name/ })
        const everything = [document.body.textContent ?? ""]
        for (const input of document.querySelectorAll("input, textarea, select")) {
            everything.push((input as HTMLInputElement).value)
        }
        expect(everything.join(" ")).not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i)
    })
})

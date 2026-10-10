import { fireEvent, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { TEST_CSRF, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import { EditWorldRoute } from "../layouts/WorldAccessRoutes"

function detail(overrides: object = {}) {
    return {
        world_id: "w1",
        name: "Eberron",
        description: "Original description",
        lifecycle_status: "active",
        row_version: 3,
        primary_timeline_id: "t1",
        capabilities: ["world.manage"],
        default_ruleset_id: null,
        allowed_rulesets: [],
        timelines: [],
        managed_campaigns: [],
        available_actions: ["update", "archive"],
        blocked_actions: [],
        ...overrides,
    }
}

function setup(initial: object = detail()) {
    const server = installMockServer()
    let current: object = initial
    server.on("GET", "/worlds/w1", () => ({ body: current }))
    const rendered = renderAuthoringRoutes({
        initialEntry: "/worlds/w1/edit",
        routes: [
            { path: "/worlds/:worldId/edit", element: <EditWorldRoute /> },
            { path: "/worlds/:worldId", element: <p>World overview page</p> },
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

const nameField = () => screen.getByRole("textbox", { name: /World name/ })
const descriptionField = () => screen.getByRole("textbox", { name: "Description" })

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("EditWorldPage", () => {
    it("pre-fills the form from the authoritative record", async () => {
        setup()
        await screen.findByRole("textbox", { name: /World name/ })
        expect(nameField()).toHaveValue("Eberron")
        expect(descriptionField()).toHaveValue("Original description")
    })

    it("renders not-found, never the form, when the server withholds update", async () => {
        const { server } = setup(
            detail({ lifecycle_status: "archived", available_actions: ["restore"] }),
        )
        expect(await screen.findByRole("heading", { name: "Page not found" })).toBeInTheDocument()
        expect(screen.queryByRole("textbox", { name: /World name/ })).not.toBeInTheDocument()
        expect(screen.queryByRole("heading", { name: "Edit world" })).not.toBeInTheDocument()
        // Only the read model was requested; nothing was submitted.
        expect(server.calls.map((call) => `${call.method} ${call.path}`)).toEqual([
            "GET /worlds/w1",
        ])
    })

    it("renders not-found for a view-only world without mounting the form", async () => {
        setup(detail({ capabilities: ["world.view"], available_actions: [] }))
        expect(await screen.findByRole("heading", { name: "Page not found" })).toBeInTheDocument()
        expect(screen.queryByRole("textbox", { name: /World name/ })).not.toBeInTheDocument()
    })

    it("saves with the loaded row version and CSRF token, then returns to the overview with an announcement", async () => {
        const { server, router } = setup()
        server.on("POST", "/worlds/w1/update", { body: { world_id: "w1", row_version: 4 } })
        await screen.findByRole("textbox", { name: /World name/ })
        fireEvent.change(nameField(), { target: { value: "  Eberron Reborn  " } })
        fireEvent.click(screen.getByRole("button", { name: "Save" }))

        await screen.findByText("World overview page")
        const [call] = server.callsTo("POST", "/worlds/w1/update")
        expect(call!.headers["X-CSRF-Token"]).toBe(TEST_CSRF)
        expect(call!.body).toEqual({
            expected_row_version: 3,
            name: "Eberron Reborn",
            description: "Original description",
        })
        expect(router.state.location.state).toEqual({ announce: "World saved" })
    })

    it("validates before sending and keeps the input", async () => {
        const { server } = setup()
        await screen.findByRole("textbox", { name: /World name/ })
        fireEvent.change(nameField(), { target: { value: "   " } })
        fireEvent.click(screen.getByRole("button", { name: "Save" }))
        const summary = await screen.findByRole("alert")
        expect(summary).toHaveTextContent("Name is required.")
        expect(server.callsTo("POST", "/worlds/w1/update")).toHaveLength(0)
        expect(nameField()).toHaveAttribute("aria-invalid", "true")
    })

    it("recovers from a stale write: shows the latest, keeps the user's values, and never resubmits the old version", async () => {
        const { server, setCurrent } = setup()
        server.on("POST", "/worlds/w1/update", {
            status: 409,
            body: { error: { code: "stale_write", message: "m", correlation_id: "c" } },
        })
        await screen.findByRole("textbox", { name: /World name/ })
        fireEvent.change(nameField(), { target: { value: "My rename" } })
        fireEvent.change(descriptionField(), { target: { value: "My description" } })
        fireEvent.click(screen.getByRole("button", { name: "Save" }))

        const notice = await screen.findByRole("alert")
        expect(notice).toHaveTextContent("Someone else changed this record")
        // The form still shows what the user typed.
        expect(nameField()).toHaveValue("My rename")

        setCurrent(detail({ name: "Their rename", description: "Their description", row_version: 5 }))
        fireEvent.click(screen.getByRole("button", { name: "Load latest version" }))

        await waitFor(() => expect(nameField()).toHaveValue("Their rename"))
        expect(descriptionField()).toHaveValue("Their description")
        const kept = screen.getByRole("region", { name: "Your unsaved changes" })
        expect(kept).toHaveTextContent("My rename")
        expect(kept).toHaveTextContent("My description")

        // Re-applying and saving sends the NEW version, not the stale one.
        server.on("POST", "/worlds/w1/update", { body: { world_id: "w1", row_version: 6 } })
        fireEvent.click(screen.getByRole("button", { name: "Re-apply my changes" }))
        expect(nameField()).toHaveValue("My rename")
        fireEvent.click(screen.getByRole("button", { name: "Save" }))
        await screen.findByText("World overview page")
        const calls = server.callsTo("POST", "/worlds/w1/update")
        expect(calls[0]!.body).toMatchObject({ expected_row_version: 3 })
        expect(calls[1]!.body).toMatchObject({ expected_row_version: 5, name: "My rename" })
    })

    it("keeps input and offers Check my session after a denied write", async () => {
        const { server } = setup()
        server.on("POST", "/worlds/w1/update", { status: 403 })
        await screen.findByRole("textbox", { name: /World name/ })
        fireEvent.change(nameField(), { target: { value: "Changed" } })
        fireEvent.click(screen.getByRole("button", { name: "Save" }))
        expect(await screen.findByRole("button", { name: "Check my session" })).toBeInTheDocument()
        expect(nameField()).toHaveValue("Changed")
    })

    it("renders the same not-found for an unknown or undisclosed world", async () => {
        const server = installMockServer()
        server.on("GET", "/worlds/w1", { status: 404 })
        renderAuthoringRoutes({
            initialEntry: "/worlds/w1/edit",
            routes: [{ path: "/worlds/:worldId/edit", element: <EditWorldRoute /> }],
        })
        expect(await screen.findByRole("heading", { name: "Page not found" })).toBeInTheDocument()
        expect(screen.queryByRole("textbox", { name: /World name/ })).not.toBeInTheDocument()
    })

    it("holds navigation away from a changed form until confirmed", async () => {
        const { router } = setup()
        await screen.findByRole("textbox", { name: /World name/ })
        fireEvent.change(nameField(), { target: { value: "Changed" } })
        fireEvent.click(screen.getByRole("button", { name: "Cancel" }))
        expect(await screen.findByRole("dialog", { name: "Discard unsaved changes?", hidden: true })).toBeInTheDocument()
        expect(router.state.location.pathname).toBe("/worlds/w1/edit")
        fireEvent.click(screen.getByRole("button", { name: "Discard changes" }))
        await screen.findByText("World overview page")
    })
})

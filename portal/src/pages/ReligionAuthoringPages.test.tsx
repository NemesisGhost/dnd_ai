import { fireEvent, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { TEST_CSRF, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import { CreateReligionPage, EditReligionPage } from "./ReligionAuthoringPages"

const OPTIONS = {
    can_create: true,
    limits: {
        name_max_length: 200,
        summary_max_length: 4000,
        pantheon_max_length: 4000,
        change_note_max_length: 1000,
    },
}
const VIEW = {
    religion_id: "r1",
    name: "Old Way",
    summary: "Ancient",
    pantheon_structure: "Nine gods",
    canon_status: "draft",
    lifecycle_status: "active",
    row_version: 2,
    available_actions: ["update"],
    blocked_actions: [],
    field_locks: [],
}

const OPTIONS_PATH = "/campaigns/c1/authoring/religions/options"
const CREATE_PATH = "/campaigns/c1/authoring/religions"
const VIEW_PATH = "/campaigns/c1/authoring/religions/r1"
const UPDATE_PATH = "/campaigns/c1/authoring/religions/r1/update"

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("CreateReligionPage", () => {
    function setup() {
        const server = installMockServer()
        server.on("GET", OPTIONS_PATH, { body: OPTIONS })
        const rendered = renderAuthoringRoutes({
            initialEntry: "/app/c1/world/religion/new",
            routes: [
                { path: "/app/:campaignId/world/religion/new", element: <CreateReligionPage /> },
                { path: "/app/:campaignId/world/religion/:entityId", element: <p>Religion detail page</p> },
            ],
        })
        return { server, ...rendered }
    }

    it("creates a draft and replaces history with the new religion", async () => {
        const { server, router } = setup()
        server.on("POST", CREATE_PATH, { status: 201, body: { ...VIEW, changed: true } })
        fireEvent.change(await screen.findByRole("textbox", { name: /Name/ }), {
            target: { value: " Old Way " },
        })
        fireEvent.change(screen.getByRole("textbox", { name: "Pantheon structure" }), {
            target: { value: "Nine gods" },
        })
        fireEvent.click(screen.getByRole("button", { name: "Create religion" }))

        await screen.findByText("Religion detail page")
        const [call] = server.callsTo("POST", CREATE_PATH)
        expect(call!.headers["X-CSRF-Token"]).toBe(TEST_CSRF)
        expect(call!.body).toEqual({ name: "Old Way", summary: null, pantheon_structure: "Nine gods" })
        expect(router.state.historyAction).toBe("REPLACE")
        expect(router.state.location.pathname).toBe("/app/c1/world/religion/r1")
    })

    it("requires a name and bounds the pantheon text", async () => {
        const { server } = setup()
        await screen.findByRole("textbox", { name: /Name/ })
        fireEvent.change(screen.getByRole("textbox", { name: "Pantheon structure" }), {
            target: { value: "x".repeat(4001) },
        })
        fireEvent.click(screen.getByRole("button", { name: "Create religion" }))
        const summary = await screen.findByRole("alert")
        expect(summary).toHaveTextContent("Name is required.")
        expect(summary).toHaveTextContent("Pantheon structure must be 4000")
        expect(server.callsTo("POST", CREATE_PATH)).toHaveLength(0)
    })
})

describe("EditReligionPage", () => {
    function setup(initial: object = VIEW) {
        const server = installMockServer()
        let current: object = initial
        server.on("GET", VIEW_PATH, () => ({ body: current }))
        server.on("GET", OPTIONS_PATH, { body: OPTIONS })
        const rendered = renderAuthoringRoutes({
            initialEntry: "/app/c1/world/religion/r1/edit",
            routes: [
                { path: "/app/:campaignId/world/religion/:entityId/edit", element: <EditReligionPage /> },
                { path: "/app/:campaignId/world/religion/:entityId", element: <p>Religion detail page</p> },
            ],
        })
        return { server, setCurrent: (next: object) => (current = next), ...rendered }
    }

    it("pre-fills and saves against the loaded version", async () => {
        const { server } = setup()
        server.on("POST", UPDATE_PATH, { body: { ...VIEW, row_version: 3 } })
        const name = await screen.findByRole("textbox", { name: /Name/ })
        expect(name).toHaveValue("Old Way")
        expect(screen.getByRole("textbox", { name: "Pantheon structure" })).toHaveValue("Nine gods")
        fireEvent.change(screen.getByRole("textbox", { name: "Summary" }), {
            target: { value: "Ancient and revered" },
        })
        fireEvent.click(screen.getByRole("button", { name: "Save" }))
        await screen.findByText("Religion detail page")
        expect(server.callsTo("POST", UPDATE_PATH)[0]!.body).toEqual({
            expected_row_version: 2,
            name: "Old Way",
            summary: "Ancient and revered",
            pantheon_structure: "Nine gods",
            change_note: null,
        })
    })

    it("keeps the user's values across a stale write", async () => {
        const { server, setCurrent } = setup()
        server.on("POST", UPDATE_PATH, {
            status: 409,
            body: { error: { code: "stale_write", message: "m", correlation_id: "c" } },
        })
        await screen.findByRole("textbox", { name: /Name/ })
        fireEvent.change(screen.getByRole("textbox", { name: "Summary" }), { target: { value: "Mine" } })
        fireEvent.click(screen.getByRole("button", { name: "Save" }))
        expect(await screen.findByRole("alert")).toHaveTextContent("Someone else changed this record")
        setCurrent({ ...VIEW, summary: "Theirs", row_version: 4 })
        fireEvent.click(screen.getByRole("button", { name: "Load latest version" }))
        await waitFor(() => expect(screen.getByRole("textbox", { name: "Summary" })).toHaveValue("Theirs"))
        expect(screen.getByRole("region", { name: "Your unsaved changes" })).toHaveTextContent("Mine")
    })

    it("explains a religion that is under review", async () => {
        setup({
            ...VIEW,
            canon_status: "proposed",
            available_actions: ["approve"],
            blocked_actions: [{ action: "update", reason: "review_in_progress" }],
        })
        expect(await screen.findByRole("alert")).toHaveTextContent("awaiting review")
    })
})

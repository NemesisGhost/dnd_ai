import { fireEvent, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import {
    TEST_CSRF,
    bootstrapWith,
    installMockServer,
    renderAuthoringRoutes,
} from "../test/authoringHarness"
import { CreateWorldPage } from "./CreateWorldPage"

const RULESETS = {
    items: [
        {
            ruleset_id: "r1",
            code: "dnd5e",
            display_name: "D&D 5e (2024)",
            description: null,
            current_versions: [{ ruleset_version_id: "rv1", version_label: "2024" }],
        },
        {
            ruleset_id: "r2",
            code: "homebrew",
            display_name: "House Rules",
            description: null,
            current_versions: [{ ruleset_version_id: "rv2", version_label: "1" }],
        },
    ],
}

function setup(options: { rulesets?: unknown; entry?: string; bootstrap?: ReturnType<typeof bootstrapWith> } = {}) {
    const server = installMockServer()
    server.on("GET", "/rulesets", { body: options.rulesets ?? RULESETS })
    const rendered = renderAuthoringRoutes({
        initialEntry: options.entry ?? "/worlds/new",
        routes: [
            { path: "/worlds/new", element: <CreateWorldPage /> },
            { path: "/worlds/:worldId", element: <p>World overview page</p> },
            { path: "/worlds", element: <p>Worlds list page</p> },
            { path: "/campaigns/new", element: <p>Campaign setup page</p> },
        ],
        bootstrap: options.bootstrap,
    })
    return { server, ...rendered }
}

async function openForm() {
    await screen.findByRole("textbox", { name: /World name/ })
}

function fillValid() {
    fireEvent.change(screen.getByRole("textbox", { name: /World name/ }), {
        target: { value: "Eberron" },
    })
    fireEvent.click(screen.getByRole("checkbox", { name: "D&D 5e (2024)" }))
    fireEvent.change(screen.getByRole("combobox", { name: /Default ruleset/ }), {
        target: { value: "r1" },
    })
}

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("CreateWorldPage", () => {
    it("loads rulesets from the server and shows a loading state first", async () => {
        setup()
        expect(screen.getByRole("status")).toHaveTextContent("Loading rulesets")
        await openForm()
        expect(screen.getByRole("checkbox", { name: "House Rules" })).toBeInTheDocument()
    })

    it("is unavailable without the server-computed world.create capability", async () => {
        setup({ bootstrap: bootstrapWith({ global_capabilities: [] }) })
        expect(await screen.findByRole("alert")).toHaveTextContent("do not have permission")
    })

    it("shows field errors from the client-side mirrors, focuses the summary, and sends nothing", async () => {
        const { server } = setup()
        await openForm()
        fireEvent.click(screen.getByRole("button", { name: "Create world" }))

        const summary = await screen.findByRole("alert")
        expect(summary).toHaveTextContent("There is a problem")
        await waitFor(() => expect(summary).toHaveFocus())
        expect(screen.getByRole("textbox", { name: /World name/ })).toHaveAttribute("aria-invalid", "true")
        expect(server.callsTo("POST", "/worlds")).toHaveLength(0)

        fireEvent.click(screen.getByRole("link", { name: "Name is required." }))
        expect(screen.getByRole("textbox", { name: /World name/ })).toHaveFocus()
    })

    it("preselects a single available ruleset", async () => {
        setup({ rulesets: { items: [RULESETS.items[0]] } })
        await openForm()
        expect(screen.getByRole("checkbox", { name: "D&D 5e (2024)" })).toBeChecked()
        expect(screen.getByRole("combobox", { name: /Default ruleset/ })).toHaveValue("r1")
    })

    it("sends the CSRF token, an idempotency key, and the normalized body, then navigates and announces after success", async () => {
        const { server, router } = setup()
        server.on("POST", "/worlds", {
            status: 201,
            body: { world_id: "w-new", primary_timeline_id: "t-new", row_version: 2 },
        })
        await openForm()
        fillValid()
        fireEvent.change(screen.getByRole("textbox", { name: "Description" }), {
            target: { value: "  A world  " },
        })
        fireEvent.click(screen.getByRole("button", { name: "Create world" }))

        await screen.findByText("World overview page")
        expect(router.state.location.pathname).toBe("/worlds/w-new")
        const [call] = server.callsTo("POST", "/worlds")
        expect(call!.headers["X-CSRF-Token"]).toBe(TEST_CSRF)
        expect(call!.headers["Idempotency-Key"]).toMatch(/[0-9a-f-]{36}/)
        expect(call!.body).toEqual({
            name: "Eberron",
            description: "A world",
            ruleset_ids: ["r1"],
            default_ruleset_id: "r1",
            primary_timeline: { name: "Main Timeline", description: null },
        })
        expect(router.state.location.state).toEqual({ announce: "World created" })
    })

    it("returns to the campaign wizard with the new world and timeline when asked to", async () => {
        const { server, router } = setup({ entry: "/worlds/new?returnTo=/campaigns/new" })
        server.on("POST", "/worlds", {
            status: 201,
            body: { world_id: "w-new", primary_timeline_id: "t-new", row_version: 2 },
        })
        await openForm()
        fillValid()
        fireEvent.click(screen.getByRole("button", { name: "Create world" }))
        await screen.findByText("Campaign setup page")
        expect(router.state.location.pathname + router.state.location.search).toBe(
            "/campaigns/new?worldId=w-new&timelineId=t-new",
        )
    })

    it("ignores a returnTo that is not the campaign wizard", async () => {
        const { server, router } = setup({ entry: "/worlds/new?returnTo=https://evil.example" })
        server.on("POST", "/worlds", {
            status: 201,
            body: { world_id: "w-new", primary_timeline_id: "t-new", row_version: 2 },
        })
        await openForm()
        fillValid()
        fireEvent.click(screen.getByRole("button", { name: "Create world" }))
        await screen.findByText("World overview page")
        expect(router.state.location.pathname).toBe("/worlds/w-new")
    })

    it("maps ruleset_not_available onto the rulesets field and keeps everything entered", async () => {
        const { server } = setup()
        server.on("POST", "/worlds", {
            status: 400,
            body: { error: { code: "ruleset_not_available", message: "m", correlation_id: "c" } },
        })
        await openForm()
        fillValid()
        fireEvent.click(screen.getByRole("button", { name: "Create world" }))

        expect(await screen.findByText(/One of the selected rulesets is not available/, { selector: "p.authoring-field__error" })).toBeInTheDocument()
        expect(screen.getByRole("textbox", { name: /World name/ })).toHaveValue("Eberron")
        expect(screen.getByRole("checkbox", { name: "D&D 5e (2024)" })).toBeChecked()
    })

    it("keeps entered values after a server failure and Retry reuses the same idempotency key", async () => {
        const { server } = setup()
        let attempts = 0
        server.on("POST", "/worlds", () => {
            attempts += 1
            return attempts === 1
                ? { status: 500, body: { error: { code: "internal_error", message: "m", correlation_id: "c1" } } }
                : { status: 201, body: { world_id: "w-new", primary_timeline_id: "t", row_version: 2 } }
        })
        await openForm()
        fillValid()
        fireEvent.click(screen.getByRole("button", { name: "Create world" }))

        expect(await screen.findByText(/input has been kept/)).toBeInTheDocument()
        expect(screen.getByRole("textbox", { name: /World name/ })).toHaveValue("Eberron")
        fireEvent.click(screen.getByRole("button", { name: "Retry" }))

        await screen.findByText("World overview page")
        const calls = server.callsTo("POST", "/worlds")
        expect(calls).toHaveLength(2)
        expect(calls[1]!.headers["Idempotency-Key"]).toBe(calls[0]!.headers["Idempotency-Key"])
    })

    it("keeps values after a network failure", async () => {
        const { server } = setup()
        server.on("POST", "/worlds", { networkError: true })
        await openForm()
        fillValid()
        fireEvent.click(screen.getByRole("button", { name: "Create world" }))
        expect(await screen.findByText(/could not reach the server/)).toBeInTheDocument()
        expect(screen.getByRole("textbox", { name: /World name/ })).toHaveValue("Eberron")
    })

    it("protects unsaved input: leaving prompts, Keep editing stays, Discard leaves", async () => {
        const { router } = setup()
        await openForm()
        fireEvent.change(screen.getByRole("textbox", { name: /World name/ }), {
            target: { value: "Half written" },
        })
        fireEvent.click(screen.getByRole("button", { name: "Cancel" }))

        const dialog = await screen.findByRole("dialog", { name: "Discard unsaved changes?", hidden: true })
        expect(dialog).toBeInTheDocument()
        expect(router.state.location.pathname).toBe("/worlds/new")

        fireEvent.click(screen.getByRole("button", { name: "Keep editing" }))
        expect(router.state.location.pathname).toBe("/worlds/new")
        expect(screen.getByRole("textbox", { name: /World name/ })).toHaveValue("Half written")

        fireEvent.click(screen.getByRole("button", { name: "Cancel" }))
        fireEvent.click(await screen.findByRole("button", { name: "Discard changes" }))
        await screen.findByText("Worlds list page")
    })

    it("leaves immediately when nothing was entered", async () => {
        setup()
        await openForm()
        fireEvent.click(screen.getByRole("button", { name: "Cancel" }))
        await screen.findByText("Worlds list page")
    })
})

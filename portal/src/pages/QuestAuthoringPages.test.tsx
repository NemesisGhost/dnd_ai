import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import {
    TEST_CSRF,
    bootstrapWith,
    installMockServer,
    renderAuthoringRoutes,
} from "../test/authoringHarness"
import { CreateQuestPage, EditQuestPage } from "./QuestAuthoringPages"

const CHOICES = (pairs: [string, string][]) => pairs.map(([value, label]) => ({ value, label }))

const OPTIONS = {
    can_create: true,
    objective_types: CHOICES([
        ["reach_location", "Reach a location"],
        ["defeat_entity", "Defeat an entity"],
        ["other", "Other"],
    ]),
    stage_types: CHOICES([
        ["sequential", "Sequential"],
        ["optional", "Optional"],
    ]),
    requirement_levels: CHOICES([
        ["required", "Required"],
        ["optional", "Optional"],
    ]),
    completion_modes: CHOICES([
        ["automatic", "Automatic"],
        ["gm_confirmed", "Confirmed by the GM"],
    ]),
    visibility_policies: CHOICES([
        ["visible", "Visible"],
        ["gm_only", "GM only"],
    ]),
    limits: {
        name_max_length: 200,
        summary_max_length: 4000,
        change_note_max_length: 1000,
        max_stages: 100,
        max_objectives_per_stage: 100,
        quantity_max: 1000000,
    },
}

function objective(overrides: object = {}) {
    return {
        quest_objective_id: "o1",
        name: "Reach the ruin",
        description: null,
        objective_type: "reach_location",
        objective_type_label: "Reach a location",
        requirement_level: "required",
        completion_mode: "automatic",
        visibility_policy: "visible",
        quantity_required: null,
        target_kind: "region",
        target: { entity_id: "t1", name: "Old Ruin", canon_status: "canon", lifecycle_status: "active" },
        ...overrides,
    }
}

function stage(overrides: object = {}) {
    return {
        quest_stage_id: "s1",
        name: "Opening",
        description: "Where it begins.",
        stage_type: "sequential",
        sequence_number: 1,
        objectives: [objective()],
        ...overrides,
    }
}

function quest(overrides: object = {}) {
    return {
        quest_id: "q1",
        name: "The Lost Amulet",
        summary: "Find it.",
        has_progress: false,
        stages: [stage()],
        canon_status: "draft",
        lifecycle_status: "active",
        row_version: 4,
        available_actions: [
            "update",
            "add_stage",
            "update_stage",
            "add_objective",
            "update_objective",
            "reorder_stages",
            "remove_stage",
            "remove_objective",
            "submit_for_review",
        ],
        blocked_actions: [],
        field_locks: [],
        ...overrides,
    }
}

const BASE = "/campaigns/c1/authoring/quests"

afterEach(() => {
    vi.unstubAllGlobals()
})

function setupEdit(initial: object = quest()) {
    const server = installMockServer()
    let current: any = initial // eslint-disable-line @typescript-eslint/no-explicit-any
    server.on("GET", `${BASE}/q1`, () => ({ body: current }))
    server.on("GET", `${BASE}/options`, { body: OPTIONS })
    server.on("GET", /target-options/, {
        body: {
            items: [{ entity_id: "t2", name: "Silver Keep", kind: "building", canon_status: "canon" }],
            next_cursor: null,
        },
    })
    server.on("GET", /\/entities\/q1\/lifecycle$/, {
        body: {
            entity_id: "q1",
            entity_type_code: "quest",
            canonical_name: "x",
            canon_status: "draft",
            lifecycle_status: "active",
            row_version: 4,
            lifecycle_managed: true,
            superseded_by: null,
            available_actions: ["submit_for_review"],
            blocked_actions: [],
        },
    })
    // Every successful command bumps the version and, when it changes the
    // structure, the view the next GET returns.
    const commit = (mutate: (draft: any) => void) => { // eslint-disable-line @typescript-eslint/no-explicit-any
        current = { ...current, row_version: current.row_version + 1 }
        mutate(current)
        return { body: { ...current, changed: true } }
    }
    const rendered = renderAuthoringRoutes({
        initialEntry: "/app/c1/quests/q1/edit",
        bootstrap: bootstrapWith({
            campaigns: [
                {
                    ...sessionBootstrapFixture.campaigns[0]!,
                    campaign_id: "c1",
                    capabilities: ["canon.edit"],
                },
            ],
        }),
        routes: [
            { path: "/app/:campaignId/quests/:questId/edit", element: <EditQuestPage /> },
            { path: "/app/:campaignId/quests", element: <p>Quests list page</p> },
        ],
    })
    return { server, commit, setCurrent: (next: object) => (current = next), ...rendered }
}

describe("CreateQuestPage", () => {
    function setup() {
        const server = installMockServer()
        server.on("GET", `${BASE}/options`, { body: OPTIONS })
        const rendered = renderAuthoringRoutes({
            initialEntry: "/app/c1/quests/new",
            routes: [
                { path: "/app/:campaignId/quests/new", element: <CreateQuestPage /> },
                { path: "/app/:campaignId/quests/:questId/edit", element: <p>Quest editor page</p> },
            ],
        })
        return { server, ...rendered }
    }

    it("creates a draft and replaces history with the quest's editor", async () => {
        const { server, router } = setup()
        server.on("POST", BASE, { status: 201, body: quest({ stages: [] }) })
        fireEvent.change(await screen.findByRole("textbox", { name: /Name/ }), {
            target: { value: " The Lost Amulet " },
        })
        fireEvent.click(screen.getByRole("button", { name: "Create quest" }))
        await screen.findByText("Quest editor page")
        const [call] = server.callsTo("POST", BASE)
        expect(call!.headers["X-CSRF-Token"]).toBe(TEST_CSRF)
        expect(call!.body).toEqual({ name: "The Lost Amulet", summary: null })
        expect(router.state.historyAction).toBe("REPLACE")
        expect(router.state.location.pathname).toBe("/app/c1/quests/q1/edit")
    })

    it("requires a name and sends nothing otherwise", async () => {
        const { server } = setup()
        await screen.findByRole("textbox", { name: /Name/ })
        fireEvent.click(screen.getByRole("button", { name: "Create quest" }))
        expect(await screen.findByRole("alert")).toHaveTextContent("Name is required.")
        expect(server.callsTo("POST", BASE)).toHaveLength(0)
    })
})

describe("EditQuestPage", () => {
    it("renders the aggregate by name, with one h1 and no identifiers", async () => {
        setupEdit()
        await screen.findByRole("heading", { level: 3, name: "Opening" })
        expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1)
        expect(screen.getByRole("heading", { level: 1, name: "Edit quest" })).toHaveFocus()
        expect(screen.getByRole("heading", { level: 5, name: "Reach the ruin" })).toBeInTheDocument()
        expect(screen.getByText(/Target: Old Ruin/)).toBeInTheDocument()
        expect(screen.getByRole("textbox", { name: /^Name/ })).toHaveValue("The Lost Amulet")
        expect(document.body.textContent).not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}-/i)
    })

    it("saves details against the loaded version", async () => {
        const { server, commit } = setupEdit()
        server.on("POST", `${BASE}/q1/update`, () => commit((d) => (d.name = "The Found Amulet")))
        await screen.findByRole("textbox", { name: /^Name/ })
        fireEvent.change(screen.getByRole("textbox", { name: /^Name/ }), {
            target: { value: "The Found Amulet" },
        })
        fireEvent.click(screen.getByRole("button", { name: "Save details" }))
        await waitFor(() => expect(server.callsTo("POST", `${BASE}/q1/update`)).toHaveLength(1))
        expect(server.callsTo("POST", `${BASE}/q1/update`)[0]!.body).toEqual({
            expected_row_version: 4,
            name: "The Found Amulet",
            summary: "Find it.",
        })
        await waitFor(() =>
            expect(screen.getByTestId("authoring-announcer")).toHaveTextContent("Quest details saved"),
        )
    })

    it("adds a stage with the loaded version, refetches, closes the panel and announces", async () => {
        const { server, commit } = setupEdit()
        server.on("POST", `${BASE}/q1/stages`, () =>
            commit((d) => d.stages.push(stage({ quest_stage_id: "s2", name: "Second", sequence_number: 2, objectives: [] }))),
        )
        fireEvent.click(await screen.findByRole("button", { name: "Add stage" }))
        const panel = screen.getByRole("form", { name: "New stage" })
        fireEvent.change(within(panel).getByRole("textbox", { name: /Stage name/ }), {
            target: { value: " Second " },
        })
        fireEvent.click(within(panel).getByRole("button", { name: "Add stage" }))

        expect(await screen.findByRole("heading", { level: 3, name: "Second" })).toBeInTheDocument()
        expect(screen.queryByRole("form", { name: "New stage" })).toBeNull()
        const [call] = server.callsTo("POST", `${BASE}/q1/stages`)
        expect(call!.body).toEqual({
            expected_row_version: 4,
            name: "Second",
            description: null,
            stage_type: "sequential",
        })
        expect(call!.headers["Idempotency-Key"]).toBeTruthy()
        expect(screen.getByTestId("authoring-announcer")).toHaveTextContent("Stage added")
    })

    it("validates a stage in place and keeps the panel open", async () => {
        const { server } = setupEdit()
        fireEvent.click(await screen.findByRole("button", { name: "Add stage" }))
        const panel = screen.getByRole("form", { name: "New stage" })
        fireEvent.click(within(panel).getByRole("button", { name: "Add stage" }))
        expect(await screen.findByRole("alert")).toHaveTextContent("Name is required.")
        expect(server.callsTo("POST", /./)).toHaveLength(0)
        expect(screen.getByRole("form", { name: "New stage" })).toBeInTheDocument()
    })

    it("adds an objective with a chosen target and flattened typed fields", async () => {
        const { server, commit } = setupEdit()
        server.on("POST", `${BASE}/q1/stages/s1/objectives`, () => commit(() => {}))
        fireEvent.click(await screen.findByRole("button", { name: /Add objective/ }))
        const panel = screen.getByRole("form", { name: "New objective" })
        fireEvent.change(within(panel).getByRole("textbox", { name: /Objective name/ }), {
            target: { value: "Find the keep" },
        })
        fireEvent.change(within(panel).getByRole("combobox", { name: /Kind of objective/ }), {
            target: { value: "reach_location" },
        })
        fireEvent.change(within(panel).getByRole("textbox", { name: "Quantity required" }), {
            target: { value: "3" },
        })
        fireEvent.focus(within(panel).getByRole("combobox", { name: "Target" }))
        fireEvent.click(await screen.findByRole("option", { name: /Silver Keep/ }))
        fireEvent.click(within(panel).getByRole("button", { name: "Add objective" }))

        await waitFor(() =>
            expect(server.callsTo("POST", `${BASE}/q1/stages/s1/objectives`)).toHaveLength(1),
        )
        expect(server.callsTo("POST", `${BASE}/q1/stages/s1/objectives`)[0]!.body).toEqual({
            expected_row_version: 4,
            name: "Find the keep",
            description: null,
            objective_type: "reach_location",
            requirement_level: "required",
            completion_mode: "automatic",
            visibility_policy: "visible",
            quantity_required: 3,
            target_entity_id: "t2",
        })
    })

    it("maps an invalid target onto the target field and keeps the panel's values", async () => {
        const { server } = setupEdit()
        server.on("POST", `${BASE}/q1/stages/s1/objectives`, {
            status: 400,
            body: { error: { code: "objective_target_invalid", message: "m", correlation_id: "c" } },
        })
        fireEvent.click(await screen.findByRole("button", { name: /Add objective/ }))
        const panel = screen.getByRole("form", { name: "New objective" })
        fireEvent.change(within(panel).getByRole("textbox", { name: /Objective name/ }), {
            target: { value: "Find the keep" },
        })
        fireEvent.click(within(panel).getByRole("button", { name: "Add objective" }))
        await waitFor(() =>
            expect(within(panel).getByRole("combobox", { name: "Target" })).toHaveAttribute(
                "aria-invalid",
                "true",
            ),
        )
        expect(within(panel).getByRole("textbox", { name: /Objective name/ })).toHaveValue("Find the keep")
    })

    it("keeps a panel's input across a stale write and never resubmits the old version", async () => {
        const { server, commit, setCurrent } = setupEdit()
        server.on("POST", `${BASE}/q1/stages`, {
            status: 409,
            body: { error: { code: "stale_write", message: "m", correlation_id: "c" } },
        })
        fireEvent.click(await screen.findByRole("button", { name: "Add stage" }))
        const panel = screen.getByRole("form", { name: "New stage" })
        fireEvent.change(within(panel).getByRole("textbox", { name: /Stage name/ }), {
            target: { value: "Mine" },
        })
        fireEvent.click(within(panel).getByRole("button", { name: "Add stage" }))
        expect(await screen.findByRole("alert")).toHaveTextContent("Someone else changed this record")
        expect(within(panel).getByRole("textbox", { name: /Stage name/ })).toHaveValue("Mine")

        setCurrent(quest({ row_version: 9, name: "Renamed elsewhere" }))
        server.on("POST", `${BASE}/q1/stages`, () => commit(() => {}))
        fireEvent.click(screen.getByRole("button", { name: "Load latest version" }))
        await waitFor(() => expect(screen.queryByRole("button", { name: "Load latest version" })).toBeNull())
        expect(within(screen.getByRole("form", { name: "New stage" })).getByRole("textbox", { name: /Stage name/ })).toHaveValue("Mine")
        fireEvent.click(
            within(screen.getByRole("form", { name: "New stage" })).getByRole("button", { name: "Add stage" }),
        )
        await waitFor(() => expect(server.callsTo("POST", `${BASE}/q1/stages`)).toHaveLength(2))
        const calls = server.callsTo("POST", `${BASE}/q1/stages`)
        expect(calls[0]!.body).toMatchObject({ expected_row_version: 4 })
        expect(calls[1]!.body).toMatchObject({ expected_row_version: 9, name: "Mine" })
    })

    it("reorders stages with the move controls", async () => {
        const second = stage({ quest_stage_id: "s2", name: "Second", sequence_number: 2, objectives: [] })
        const { server, commit } = setupEdit(quest({ stages: [stage(), second] }))
        server.on("POST", `${BASE}/q1/stages/reorder`, () =>
            commit((d) => d.stages.reverse()),
        )
        expect(await screen.findByRole("button", { name: /Move down Opening/ })).toBeInTheDocument()
        expect(screen.queryByRole("button", { name: /Move up Opening/ })).toBeNull()
        fireEvent.click(screen.getByRole("button", { name: /Move down Opening/ }))
        await waitFor(() =>
            expect(server.callsTo("POST", `${BASE}/q1/stages/reorder`)[0]!.body).toEqual({
                expected_row_version: 4,
                stage_ids: ["s2", "s1"],
            }),
        )
    })

    it("confirms before removing a stage and states what goes with it", async () => {
        const { server, commit } = setupEdit()
        server.on("POST", `${BASE}/q1/stages/s1/remove`, () => commit((d) => (d.stages = [])))
        fireEvent.click(await screen.findByRole("button", { name: /Remove stage Opening/ }))
        const dialog = await screen.findByRole("dialog", { name: "Remove this stage?" })
        expect(dialog).toHaveTextContent('"Opening" and its 1 objective will be permanently removed')
        expect(server.callsTo("POST", /./)).toHaveLength(0)
        fireEvent.click(within(dialog).getByRole("button", { name: "Remove stage" }))
        await waitFor(() =>
            expect(screen.getByText(/This quest has no stages yet/)).toBeInTheDocument(),
        )
        expect(server.callsTo("POST", `${BASE}/q1/stages/s1/remove`)[0]!.body).toEqual({
            expected_row_version: 4,
        })
    })

    it("cancelling the removal sends nothing", async () => {
        const { server } = setupEdit()
        fireEvent.click(await screen.findByRole("button", { name: /Remove objective Reach the ruin/ }))
        const dialog = await screen.findByRole("dialog", { name: "Remove this objective?" })
        fireEvent.click(within(dialog).getByRole("button", { name: "Keep it" }))
        expect(server.callsTo("POST", /./)).toHaveLength(0)
    })

    it("shows progress-locked structure: no removal or reorder, disabled structural fields, a reason", async () => {
        const second = stage({ quest_stage_id: "s2", name: "Second", sequence_number: 2, objectives: [] })
        setupEdit(
            quest({
                has_progress: true,
                field_locks: ["structure"],
                stages: [stage(), second],
                available_actions: ["update", "add_stage", "update_stage", "add_objective", "update_objective"],
                blocked_actions: [
                    { action: "reorder_stages", reason: "quest_has_progress" },
                    { action: "remove_stage", reason: "quest_has_progress" },
                    { action: "remove_objective", reason: "quest_has_progress" },
                ],
            }),
        )
        expect(await screen.findByRole("note")).toHaveTextContent("already has progress recorded")
        expect(screen.queryByRole("button", { name: /Remove stage/ })).toBeNull()
        expect(screen.queryByRole("button", { name: /Remove objective/ })).toBeNull()
        expect(screen.queryByRole("button", { name: /Move (up|down)/ })).toBeNull()
        fireEvent.click(screen.getByRole("button", { name: /Edit objective Reach the ruin/ }))
        const panel = screen.getByRole("form", { name: "Edit objective" })
        for (const name of [/Kind of objective/, /Requirement/, /Completion/]) {
            expect(within(panel).getByRole("combobox", { name })).toBeDisabled()
        }
        expect(within(panel).getByRole("textbox", { name: "Quantity required" })).toBeDisabled()
        expect(within(panel).getByRole("combobox", { name: "Target" })).toBeDisabled()
        // Wording and visibility stay editable.
        expect(within(panel).getByRole("textbox", { name: /Objective name/ })).toBeEnabled()
        expect(within(panel).getByRole("combobox", { name: "Visibility" })).toBeEnabled()
        // Additions are still offered.
        expect(screen.getByRole("button", { name: "Add stage" })).toBeInTheDocument()
    })

    it("explains a quest under review and offers no edit controls", async () => {
        setupEdit(
            quest({
                canon_status: "proposed",
                available_actions: ["approve"],
                blocked_actions: [{ action: "update", reason: "review_in_progress" }],
            }),
        )
        expect(await screen.findByRole("note")).toHaveTextContent("review in progress")
        expect(screen.queryByRole("button", { name: "Add stage" })).toBeNull()
        expect(screen.queryByRole("button", { name: /Edit stage/ })).toBeNull()
        expect(screen.getByRole("textbox", { name: /^Name/ })).toBeDisabled()
    })

    it("guards an unsaved panel against leaving", async () => {
        const { router } = setupEdit()
        fireEvent.click(await screen.findByRole("button", { name: "Add stage" }))
        fireEvent.change(
            within(screen.getByRole("form", { name: "New stage" })).getByRole("textbox", { name: /Stage name/ }),
            { target: { value: "Half" } },
        )
        void router.navigate("/app/c1/quests")
        const dialog = await screen.findByRole("dialog", { name: "Discard unsaved changes?" })
        fireEvent.click(within(dialog).getByRole("button", { name: "Keep editing" }))
        expect(router.state.location.pathname).toBe("/app/c1/quests/q1/edit")
    })

    it("mounts the lifecycle panel for an editor", async () => {
        setupEdit()
        expect(await screen.findByRole("heading", { name: "Lifecycle" })).toBeInTheDocument()
    })

    it("explains an unavailable quest without a form", async () => {
        const server = installMockServer()
        server.on("GET", `${BASE}/q1`, { status: 404 })
        server.on("GET", `${BASE}/options`, { body: OPTIONS })
        renderAuthoringRoutes({
            initialEntry: "/app/c1/quests/q1/edit",
            routes: [{ path: "/app/:campaignId/quests/:questId/edit", element: <EditQuestPage /> }],
        })
        expect(await screen.findByRole("alert")).toHaveTextContent(
            "This quest does not exist, or you do not have access to it.",
        )
    })
})

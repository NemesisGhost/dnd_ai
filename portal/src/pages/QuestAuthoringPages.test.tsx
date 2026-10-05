import { createEvent, fireEvent, screen, waitFor, within } from "@testing-library/react"
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

// Stages start collapsed; open them all so their objectives can be reached.
const expandAll = async () =>
    fireEvent.click(await screen.findByRole("button", { name: "Expand all" }))

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
        await expandAll()
        await screen.findByRole("heading", { level: 3, name: /Opening/ })
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

        expect(await screen.findByRole("heading", { level: 3, name: /Second/ })).toBeInTheDocument()
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
        await expandAll()
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
        await expandAll()
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
        expect(screen.getByRole("button", { name: /Move up Opening/ })).toBeDisabled()
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
        await expandAll()
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
        await expandAll()
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
        await expandAll()
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


describe("Quest stage cards", () => {
    const second = () =>
        stage({
            quest_stage_id: "s2",
            name: "Second",
            sequence_number: 2,
            objectives: [
                objective({ quest_objective_id: "o2", name: "Optional detour", requirement_level: "optional" }),
            ],
        })
    const third = () =>
        stage({ quest_stage_id: "s3", name: "Third", sequence_number: 3, objectives: [] })
    const REORDER = `${BASE}/q1/stages/reorder`
    const setupThree = () => {
        const ctx = setupEdit(quest({ stages: [stage(), second(), third()] }))
        ctx.server.on("POST", REORDER, () => ctx.commit(() => {}))
        return ctx
    }
    const toggle = (name: RegExp) => screen.getByRole("button", { name })
    // jsdom has no layout: give every row a 100px box at the same origin.
    const dataTransfer = () => ({ effectAllowed: "", setData: vi.fn(), setDragImage: vi.fn() })
    const dragTo = (from: string, to: string, clientY: number) => {
        const source = screen.getByRole("heading", { level: 3, name: new RegExp(from) })
        const target = screen.getByRole("heading", { level: 3, name: new RegExp(to) }).closest("li")!
        vi.spyOn(target, "getBoundingClientRect").mockReturnValue({ top: 0, height: 100 } as DOMRect)
        fireEvent.dragStart(source.parentElement!, { dataTransfer: dataTransfer() })
        // jsdom's generic drag events ignore clientY, so set it on the event itself.
        const over = createEvent.dragOver(target)
        Object.defineProperty(over, "clientY", { value: clientY })
        fireEvent(target, over)
        fireEvent.drop(target)
    }

    it("renders stages in order with Move up on the left and Move down on the right, disabled at the ends", async () => {
        setupThree()
        await screen.findByRole("heading", { level: 3, name: /Opening/ })
        const rows = screen.getAllByRole("listitem").filter((li) => li.classList.contains("quest-stage-row"))
        expect(rows).toHaveLength(3)
        const names = rows.map((r) => within(r).getByRole("heading", { level: 3 }).textContent)
        expect(names[0]).toMatch(/Opening/)
        expect(names[2]).toMatch(/Third/)
        const first = within(rows[0]!).getAllByRole("button")
        expect(first[0]).toHaveAccessibleName("Move up Opening")
        expect(first[0]).toBeDisabled()
        expect(first[first.length - 1]).toHaveAccessibleName("Move down Opening")
        const last = within(rows[2]!).getAllByRole("button")
        expect(last[0]).toHaveAccessibleName("Move up Third")
        expect(last[last.length - 1]).toHaveAccessibleName("Move down Third")
        expect(last[last.length - 1]).toBeDisabled()
    })

    it("starts collapsed and expands or collapses each stage independently without any request", async () => {
        const { server } = setupThree()
        await screen.findByRole("heading", { level: 3, name: /Opening/ })
        const opening = toggle(/^1\. Opening/)
        const secondToggle = toggle(/^2\. Second/)
        expect(opening).toHaveAttribute("aria-expanded", "false")
        expect(screen.getByRole("heading", { level: 5, name: "Reach the ruin", hidden: true })).not.toBeVisible()
        fireEvent.click(opening)
        expect(opening).toHaveAttribute("aria-expanded", "true")
        expect(secondToggle).toHaveAttribute("aria-expanded", "false")
        expect(screen.getByRole("heading", { level: 5, name: "Reach the ruin" })).toBeVisible()
        expect(
            document.getElementById(opening.getAttribute("aria-controls")!),
        ).toContainElement(screen.getByRole("heading", { level: 5, name: "Reach the ruin" }))
        fireEvent.click(opening)
        expect(opening).toHaveAttribute("aria-expanded", "false")
        expect(server.callsTo("POST", /./)).toHaveLength(0)
    })

    it("expands and collapses every stage with one button, sending no request", async () => {
        const { server } = setupThree()
        await screen.findByRole("heading", { level: 3, name: /Opening/ })
        fireEvent.click(toggle(/^2\. Second/))
        fireEvent.click(screen.getByRole("button", { name: "Expand all" }))
        for (const name of [/^1\. Opening/, /^2\. Second/, /^3\. Third/]) {
            expect(toggle(name)).toHaveAttribute("aria-expanded", "true")
        }
        fireEvent.click(screen.getByRole("button", { name: "Collapse all" }))
        for (const name of [/^1\. Opening/, /^2\. Second/, /^3\. Third/]) {
            expect(toggle(name)).toHaveAttribute("aria-expanded", "false")
        }
        expect(screen.getByRole("button", { name: "Expand all" })).toBeInTheDocument()
        expect(server.callsTo("POST", /./)).toHaveLength(0)
    })

    it("summarises objectives collapsed and distinguishes required from optional in text", async () => {
        setupThree()
        await screen.findByRole("heading", { level: 3, name: /Opening/ })
        expect(toggle(/^1\. Opening/)).toHaveTextContent("1 objective, 1 required")
        expect(toggle(/^2\. Second/)).toHaveTextContent("1 objective, 0 required")
        expect(toggle(/^3\. Third/)).toHaveTextContent("No objectives yet")
        expect(screen.getAllByText("Optional").length).toBeGreaterThan(0)
        expect(screen.getAllByText("Required").length).toBeGreaterThan(0)
        expect(screen.getAllByText("No objectives in this stage.")).toHaveLength(1)
    })

    it("keeps a stage with an open form expanded", async () => {
        setupThree()
        fireEvent.click(await screen.findByRole("button", { name: "Expand all" }))
        fireEvent.click(screen.getByRole("button", { name: /Edit stage Second/ }))
        const secondToggle = toggle(/^2\. Second/)
        fireEvent.click(secondToggle)
        expect(secondToggle).toHaveAttribute("aria-expanded", "true")
        expect(screen.getByRole("form", { name: "Edit stage" })).toBeVisible()
    })

    it("sends the full new order for Move up and Move down", async () => {
        const { server } = setupThree()
        fireEvent.click(await screen.findByRole("button", { name: "Move up Second" }))
        await waitFor(() => expect(server.callsTo("POST", REORDER)).toHaveLength(1))
        expect(server.callsTo("POST", REORDER)[0]!.body).toEqual({
            expected_row_version: 4,
            stage_ids: ["s2", "s1", "s3"],
        })
        fireEvent.click(await screen.findByRole("button", { name: "Move down Opening" }))
        await waitFor(() => expect(server.callsTo("POST", REORDER)).toHaveLength(2))
        expect(server.callsTo("POST", REORDER)[1]!.body).toEqual({
            expected_row_version: 5,
            stage_ids: ["s2", "s1", "s3"],
        })
    })

    it("sends the destination for a drag before or after another stage", async () => {
        const { server } = setupThree()
        await screen.findByRole("heading", { level: 3, name: /Opening/ })
        dragTo("Third", "Opening", 10)
        await waitFor(() => expect(server.callsTo("POST", REORDER)).toHaveLength(1))
        expect(server.callsTo("POST", REORDER)[0]!.body).toMatchObject({ stage_ids: ["s3", "s1", "s2"] })
        await waitFor(() => expect(screen.getByRole("button", { name: "Move up Third" })).toBeEnabled())
        dragTo("Opening", "Third", 90)
        await waitFor(() => expect(server.callsTo("POST", REORDER)).toHaveLength(2))
        expect(server.callsTo("POST", REORDER)[1]!.body).toMatchObject({ stage_ids: ["s2", "s3", "s1"] })
    })

    it("sends nothing when a stage is dropped where it already is", async () => {
        const { server } = setupThree()
        await screen.findByRole("heading", { level: 3, name: /Opening/ })
        dragTo("Second", "Third", 10)
        dragTo("Second", "Opening", 90)
        fireEvent.dragStart(screen.getByRole("heading", { level: 3, name: /Second/ }).parentElement!, {
            dataTransfer: dataTransfer(),
        })
        fireEvent.drop(screen.getByRole("heading", { level: 3, name: /Second/ }).closest("li")!)
        expect(server.callsTo("POST", REORDER)).toHaveLength(0)
    })

    it("keeps expansion and objective membership across a reorder, and ignores a second drop while pending", async () => {
        const ctx = setupEdit(quest({ stages: [stage(), second(), third()] }))
        let release: () => void = () => {}
        ctx.server.on("POST", REORDER, () =>
            new Promise((resolve) => {
                release = () => resolve(ctx.commit((d) => d.stages.reverse()))
            }),
        )
        await screen.findByRole("heading", { level: 3, name: /Opening/ })
        fireEvent.click(toggle(/^1\. Opening/))
        fireEvent.click(screen.getByRole("button", { name: "Move down Opening" }))
        await waitFor(() => expect(screen.getByRole("button", { name: "Move down Opening" })).toBeDisabled())
        dragTo("Third", "Opening", 10)
        fireEvent.click(screen.getByRole("button", { name: "Move up Third" }))
        expect(ctx.server.callsTo("POST", REORDER)).toHaveLength(1)
        release()
        await waitFor(() =>
            expect(
                screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent),
            ).toEqual([expect.stringMatching(/Third/), expect.stringMatching(/Second/), expect.stringMatching(/Opening/)]),
        )
        expect(screen.getByRole("button", { name: /Second/, expanded: false })).toBeInTheDocument()
        expect(screen.getByRole("button", { name: /Opening/, expanded: true })).toBeInTheDocument()
        const openingRow = screen.getByRole("heading", { level: 3, name: /Opening/ }).closest("li")!
        expect(within(openingRow).getByRole("heading", { level: 5, name: "Reach the ruin" })).toBeInTheDocument()
        expect(openingRow).toHaveTextContent("1 objective, 1 required")
    })

    it("announces a failed reorder and keeps the authoritative order", async () => {
        const { server } = setupThree()
        server.on("POST", REORDER, {
            status: 500,
            body: { error: { code: "internal_error", message: "m", correlation_id: "c" } },
        })
        fireEvent.click(await screen.findByRole("button", { name: "Move down Opening" }))
        expect(await screen.findByRole("alert")).toBeInTheDocument()
        expect(
            screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent),
        ).toEqual([expect.stringMatching(/Opening/), expect.stringMatching(/Second/), expect.stringMatching(/Third/)])
    })

    it("follows the stale-write path when the order changed elsewhere", async () => {
        const { server } = setupThree()
        server.on("POST", REORDER, {
            status: 409,
            body: { error: { code: "stale_write", message: "m", correlation_id: "c" } },
        })
        fireEvent.click(await screen.findByRole("button", { name: "Move down Opening" }))
        expect(await screen.findByRole("alert")).toHaveTextContent("Someone else changed this record")
        expect(screen.getByRole("button", { name: "Load latest version" })).toBeInTheDocument()
    })

    it("gives a member without reorder authority no ordering controls and no drag", async () => {
        setupEdit(
            quest({
                stages: [stage(), second()],
                available_actions: ["update", "update_stage", "add_objective"],
            }),
        )
        await screen.findByRole("heading", { level: 3, name: /Opening/ })
        expect(screen.queryByRole("button", { name: /Move (up|down)/ })).toBeNull()
        const header = screen.getByRole("heading", { level: 3, name: /Opening/ }).parentElement!
        expect(header).not.toHaveAttribute("draggable", "true")
    })
})

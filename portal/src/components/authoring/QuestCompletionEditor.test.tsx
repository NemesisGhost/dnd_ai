import { fireEvent, screen, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { EditQuestPage } from "../../pages/QuestAuthoringPages"
import { sessionBootstrapFixture } from "../../fixtures/sessionBootstrap"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../../test/authoringHarness"

const CHOICES = (pairs: [string, string][]) => pairs.map(([value, label]) => ({ value, label }))

const OPTIONS = {
    can_create: true,
    objective_types: CHOICES([["other", "Other"]]),
    stage_types: CHOICES([["sequential", "Sequential"]]),
    requirement_levels: CHOICES([["required", "Required"]]),
    completion_modes: CHOICES([["automatic", "Automatic"]]),
    visibility_policies: CHOICES([["visible", "Visible"]]),
    dependency_types: CHOICES([["prerequisite", "Prerequisite"]]),
    participant_roles: CHOICES([
        ["giver", "Quest giver"],
        ["involved", "Involved"],
    ]),
    outcome_categories: CHOICES([
        ["success", "Success"],
        ["failure", "Failure"],
    ]),
    reward_types: CHOICES([
        ["other", "Other"],
        ["knowledge", "Knowledge"],
    ]),
    limits: {
        gm_notes_max_length: 40,
        outcome_description_max_length: 4000,
        reward_description_max_length: 1000,
        name_max_length: 200,
        summary_max_length: 4000,
        change_note_max_length: 1000,
        max_stages: 100,
        max_objectives_per_stage: 100,
        quantity_max: 1000000,
    },
}

const objective = (id: string, name: string) => ({
    quest_objective_id: id,
    name,
    description: null,
    objective_type: "other",
    objective_type_label: "Other",
    requirement_level: "required",
    completion_mode: "automatic",
    visibility_policy: "visible",
    quantity_required: null,
    target_kind: null,
    target: null,
})

function quest(overrides: object = {}) {
    return {
        quest_id: "q1",
        name: "The Lost Amulet",
        summary: null,
        has_progress: false,
        gm_notes: "Remember the twist.",
        dependencies: [
            {
                objective_dependency_id: "d1",
                objective_id: "o2",
                depends_on_objective_id: "o1",
                dependency_type: "prerequisite",
            },
        ],
        participants: [
            {
                quest_participant_id: "p1",
                participant_role: "giver",
                participant: { entity_id: "n1", name: "Mara", canon_status: "canon", lifecycle_status: "active" },
            },
        ],
        outcomes: [
            {
                quest_outcome_id: "out1",
                code: "saved",
                name: "Village saved",
                description: null,
                outcome_category: "success",
                rewards: [{ quest_reward_id: "r1", reward_type: "other", description: "50 gold", knowledge: null }],
            },
        ],
        stages: [
            {
                quest_stage_id: "s1",
                name: "Opening",
                description: null,
                stage_type: "sequential",
                sequence_number: 1,
                objectives: [objective("o1", "Find the map"), objective("o2", "Reach the ruin")],
            },
        ],
        canon_status: "draft",
        lifecycle_status: "active",
        row_version: 4,
        available_actions: ["update", "add_dependency", "remove_dependency"],
        blocked_actions: [],
        field_locks: [],
        ...overrides,
    }
}

const BASE = "/campaigns/c1/authoring/quests"

afterEach(() => {
    vi.unstubAllGlobals()
})

function setup(view: object = quest()) {
    const server = installMockServer()
    server.on("GET", `${BASE}/q1`, () => ({ body: view }))
    server.on("GET", `${BASE}/options`, { body: OPTIONS })
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
            available_actions: [],
            blocked_actions: [],
        },
    })
    server.on("POST", new RegExp(`${BASE}/q1/`), { body: { ...(view as object), row_version: 5, changed: true } })
    renderAuthoringRoutes({
        initialEntry: "/app/c1/quests/q1/edit",
        bootstrap: bootstrapWith({
            campaigns: [
                { ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c1", capabilities: ["canon.edit"] },
            ],
        }),
        routes: [{ path: "/app/:campaignId/quests/:questId/edit", element: <EditQuestPage /> }],
    })
    return server
}

const lastBody = (server: ReturnType<typeof installMockServer>, suffix: string) => {
    const call = server
        .callsTo("POST", new RegExp(`${BASE}/q1/${suffix}$`))
        .at(-1)
    return call?.body as Record<string, unknown> | undefined
}

describe("QuestCompletionEditor", () => {
    it("shows notes, dependencies, participants, outcomes and rewards", async () => {
        setup()
        expect(await screen.findByRole("textbox", { name: /Planning notes/ })).toHaveValue("Remember the twist.")
        expect(screen.getByText(/Opening: Reach the ruin depends on Opening: Find the map/)).toBeInTheDocument()
        expect(screen.getByText(/Mara \(giver\)/)).toBeInTheDocument()
        const card = screen.getByRole("article", { name: "Outcome Village saved" })
        expect(within(card).getByText(/other: 50 gold/)).toBeInTheDocument()
    })

    it("saves notes through update_quest with the current version", async () => {
        const server = setup()
        const notes = await screen.findByRole("textbox", { name: /Planning notes/ })
        fireEvent.change(notes, { target: { value: "  New plan  " } })
        fireEvent.click(screen.getByRole("button", { name: "Save notes" }))
        await screen.findByRole("button", { name: "Save notes" })
        await vi.waitFor(() => expect(lastBody(server, "update")).toBeDefined())
        expect(lastBody(server, "update")).toMatchObject({
            expected_row_version: 4,
            gm_notes: "New plan",
        })
    })

    it("refuses notes over the limit without sending", async () => {
        const server = setup()
        const notes = await screen.findByRole("textbox", { name: /Planning notes/ })
        fireEvent.change(notes, { target: { value: "x".repeat(41) } })
        expect(screen.getByRole("button", { name: "Save notes" })).toBeDisabled()
        expect(server.callsTo("POST", new RegExp(`${BASE}/q1/update$`))).toHaveLength(0)
    })

    it("adds a dependency and refuses choosing the same objective twice", async () => {
        const server = setup()
        const form = await screen.findByRole("form", { name: "Add a dependency" })
        const [objectiveSelect, , dependsOnSelect] = within(form).getAllByRole("combobox")
        fireEvent.change(objectiveSelect!, { target: { value: "o1" } })
        fireEvent.change(dependsOnSelect!, { target: { value: "o1" } })
        fireEvent.click(within(form).getByRole("button", { name: "Add dependency" }))
        expect(await within(form).findByText("Choose two different objectives.")).toBeInTheDocument()
        expect(server.callsTo("POST", new RegExp(`${BASE}/q1/dependencies$`))).toHaveLength(0)

        fireEvent.change(dependsOnSelect!, { target: { value: "o2" } })
        fireEvent.click(within(form).getByRole("button", { name: "Add dependency" }))
        await vi.waitFor(() => expect(lastBody(server, "dependencies")).toBeDefined())
        expect(lastBody(server, "dependencies")).toMatchObject({
            expected_row_version: 4,
            objective_id: "o1",
            depends_on_objective_id: "o2",
            dependency_type: "prerequisite",
        })
    })

    it("locks dependencies once the quest has progress", async () => {
        setup(quest({ has_progress: true, available_actions: ["update", "add_participant"] }))
        await screen.findByText(/can no longer change/)
        expect(screen.queryByRole("button", { name: "Remove dependency" })).not.toBeInTheDocument()
        expect(screen.queryByRole("form", { name: "Add a dependency" })).not.toBeInTheDocument()
        // Participants stay editable.
        expect(screen.getByRole("button", { name: "Remove Mara" })).toBeEnabled()
    })

    it("validates and adds an outcome", async () => {
        const server = setup()
        const form = await screen.findByRole("form", { name: "Add an outcome" })
        fireEvent.click(within(form).getByRole("button", { name: "Add outcome" }))
        expect(await within(form).findByText(/Use lowercase letters/)).toBeInTheDocument()
        expect(server.callsTo("POST", new RegExp(`${BASE}/q1/outcomes$`))).toHaveLength(0)

        fireEvent.change(within(form).getByRole("textbox", { name: /Code/ }), { target: { value: "lost" } })
        fireEvent.change(within(form).getByRole("textbox", { name: /Outcome name/ }), {
            target: { value: " Village lost " },
        })
        fireEvent.change(within(form).getByRole("combobox", { name: /Kind of outcome/ }), {
            target: { value: "failure" },
        })
        fireEvent.click(within(form).getByRole("button", { name: "Add outcome" }))
        await vi.waitFor(() => expect(lastBody(server, "outcomes")).toBeDefined())
        expect(lastBody(server, "outcomes")).toMatchObject({
            expected_row_version: 4,
            code: "lost",
            name: "Village lost",
            outcome_category: "failure",
        })
    })

    it("removes a reward with the current version", async () => {
        const server = setup()
        fireEvent.click(await screen.findByRole("button", { name: "Remove reward 50 gold" }))
        await vi.waitFor(() => expect(lastBody(server, "rewards/r1/remove")).toBeDefined())
        expect(lastBody(server, "rewards/r1/remove")).toEqual({ expected_row_version: 4 })
    })

    it("removes an outcome with the current version", async () => {
        const server = setup()
        fireEvent.click(await screen.findByRole("button", { name: "Remove Village saved" }))
        await vi.waitFor(() => expect(lastBody(server, "outcomes/out1/remove")).toBeDefined())
        expect(lastBody(server, "outcomes/out1/remove")).toEqual({ expected_row_version: 4 })
    })

    it("adds a reward and requires a description", async () => {
        const server = setup()
        const form = await screen.findByRole("form", { name: "Add a reward to Village saved" })
        fireEvent.click(within(form).getByRole("button", { name: "Add reward" }))
        expect(await within(form).findByText("Describe the reward.")).toBeInTheDocument()
        fireEvent.change(within(form).getByRole("textbox", { name: /Reward/ }), { target: { value: "A horse" } })
        fireEvent.click(within(form).getByRole("button", { name: "Add reward" }))
        await vi.waitFor(() => expect(lastBody(server, "outcomes/out1/rewards")).toBeDefined())
        expect(lastBody(server, "outcomes/out1/rewards")).toMatchObject({
            reward_type: "other",
            description: "A horse",
            reward_knowledge_item_id: null,
        })
    })

    it("hides the section from people who cannot edit", async () => {
        setup(quest({ available_actions: [] }))
        await screen.findByRole("heading", { name: "Edit quest" })
        expect(screen.queryByRole("heading", { name: /Dependencies, participants/ })).not.toBeInTheDocument()
    })
})

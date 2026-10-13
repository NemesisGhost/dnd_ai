import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { AUTHORING, questView, setupQuestWorkspace } from "../../test/questWorkspaceHarness"

afterEach(() => {
    vi.unstubAllGlobals()
})

const lastBody = (server: ReturnType<typeof setupQuestWorkspace>["server"], suffix: string) =>
    server.callsTo("POST", new RegExp(`${AUTHORING}/q1/${suffix}$`)).at(-1)?.body as Record<string, unknown> | undefined

describe("Quest notes (Details)", () => {
    it("shows the planning notes", async () => {
        setupQuestWorkspace({ section: "details" })
        expect(await screen.findByRole("textbox", { name: /Planning notes/ })).toHaveValue("Remember the twist.")
    })

    it("saves notes through update_quest with the current version and the server's own name and summary", async () => {
        const { server } = setupQuestWorkspace({ section: "details" })
        const notes = await screen.findByRole("textbox", { name: /Planning notes/ })
        // An unsaved details draft is neither sent nor lost.
        fireEvent.change(screen.getByRole("textbox", { name: /^Name/ }), { target: { value: "Half-typed" } })
        fireEvent.change(notes, { target: { value: "  New plan  " } })
        fireEvent.click(screen.getByRole("button", { name: "Save notes" }))
        await waitFor(() => expect(lastBody(server, "update")).toBeDefined())
        expect(lastBody(server, "update")).toMatchObject({
            expected_row_version: 4,
            name: "The Lost Amulet",
            gm_notes: "New plan",
        })
        await waitFor(() => expect(screen.getByRole("textbox", { name: /^Name/ })).toHaveValue("Half-typed"))
    })

    it("refuses notes over the limit without sending", async () => {
        const { server } = setupQuestWorkspace({ section: "details" })
        const notes = await screen.findByRole("textbox", { name: /Planning notes/ })
        fireEvent.change(notes, { target: { value: "x".repeat(41) } })
        expect(screen.getByRole("button", { name: "Save notes" })).toBeDisabled()
        expect(server.callsTo("POST", new RegExp(`${AUTHORING}/q1/update$`))).toHaveLength(0)
    })
})

describe("Quest dependencies", () => {
    it("lists them and adds one, refusing the same objective twice", async () => {
        const { server } = setupQuestWorkspace({ section: "dependencies" })
        expect(await screen.findByText(/Opening: Reach the ruin depends on Opening: Find the map/)).toBeInTheDocument()
        const form = screen.getByRole("form", { name: "Add a dependency" })
        const [objectiveSelect, , dependsOnSelect] = within(form).getAllByRole("combobox")
        fireEvent.change(objectiveSelect!, { target: { value: "o1" } })
        fireEvent.change(dependsOnSelect!, { target: { value: "o1" } })
        fireEvent.click(within(form).getByRole("button", { name: "Add dependency" }))
        expect(await within(form).findByText("Choose two different objectives.")).toBeInTheDocument()
        expect(server.callsTo("POST", new RegExp(`${AUTHORING}/q1/dependencies$`))).toHaveLength(0)

        fireEvent.change(dependsOnSelect!, { target: { value: "o2" } })
        fireEvent.click(within(form).getByRole("button", { name: "Add dependency" }))
        await waitFor(() => expect(lastBody(server, "dependencies")).toBeDefined())
        expect(lastBody(server, "dependencies")).toMatchObject({
            expected_row_version: 4,
            objective_id: "o1",
            depends_on_objective_id: "o2",
            dependency_type: "prerequisite",
        })
        // The form clears what its own successful command consumed.
        await waitFor(() => expect(objectiveSelect).toHaveValue(""))
    })

    it("locks dependencies once the quest has progress", async () => {
        setupQuestWorkspace({
            section: "dependencies",
            view: questView({ has_progress: true, available_actions: ["update", "add_participant"] }),
        })
        await screen.findByText(/can no longer change/)
        expect(screen.queryByRole("button", { name: "Remove dependency" })).not.toBeInTheDocument()
        expect(screen.queryByRole("form", { name: "Add a dependency" })).not.toBeInTheDocument()
    })

    it("shows the list as text when the quest cannot be edited", async () => {
        setupQuestWorkspace({
            section: "dependencies",
            view: questView({ canon_status: "proposed", available_actions: [], blocked_actions: [{ action: "update", reason: "review_in_progress" }] }),
        })
        expect(await screen.findByText(/Opening: Reach the ruin depends on Opening: Find the map/)).toBeInTheDocument()
        expect(screen.queryByRole("button", { name: "Remove dependency" })).not.toBeInTheDocument()
        expect(screen.queryByRole("form", { name: "Add a dependency" })).not.toBeInTheDocument()
    })
})

describe("Quest participants", () => {
    it("lists participants and removes one with the current version", async () => {
        const { server } = setupQuestWorkspace({ section: "participants" })
        expect(await screen.findByText(/Mara \(giver\)/)).toBeInTheDocument()
        fireEvent.click(screen.getByRole("button", { name: "Remove Mara" }))
        await waitFor(() => expect(lastBody(server, "participants/p1/remove")).toEqual({ expected_row_version: 4 }))
    })

    it("stays editable after progress is recorded", async () => {
        setupQuestWorkspace({
            section: "participants",
            view: questView({ has_progress: true, available_actions: ["update", "add_participant", "remove_participant"] }),
        })
        expect(await screen.findByRole("button", { name: "Remove Mara" })).toBeEnabled()
    })
})

describe("Quest outcomes and rewards", () => {
    it("shows an outcome with its rewards", async () => {
        setupQuestWorkspace({ section: "outcomes" })
        const card = await screen.findByRole("article", { name: "Outcome Village saved" })
        expect(within(card).getByText(/other: 50 gold/)).toBeInTheDocument()
    })

    it("validates and adds an outcome", async () => {
        const { server } = setupQuestWorkspace({ section: "outcomes" })
        const form = await screen.findByRole("form", { name: "Add an outcome" })
        fireEvent.click(within(form).getByRole("button", { name: "Add outcome" }))
        expect(await within(form).findByText(/Use lowercase letters/)).toBeInTheDocument()
        expect(server.callsTo("POST", new RegExp(`${AUTHORING}/q1/outcomes$`))).toHaveLength(0)

        fireEvent.change(within(form).getByRole("textbox", { name: /Code/ }), { target: { value: "lost" } })
        fireEvent.change(within(form).getByRole("textbox", { name: /Outcome name/ }), {
            target: { value: " Village lost " },
        })
        fireEvent.change(within(form).getByRole("combobox", { name: /Kind of outcome/ }), {
            target: { value: "failure" },
        })
        fireEvent.click(within(form).getByRole("button", { name: "Add outcome" }))
        await waitFor(() => expect(lastBody(server, "outcomes")).toBeDefined())
        expect(lastBody(server, "outcomes")).toMatchObject({
            expected_row_version: 4,
            code: "lost",
            name: "Village lost",
            outcome_category: "failure",
        })
    })

    it("removes a reward and an outcome with the current version", async () => {
        const { server } = setupQuestWorkspace({ section: "outcomes" })
        fireEvent.click(await screen.findByRole("button", { name: "Remove reward 50 gold" }))
        await waitFor(() => expect(lastBody(server, "rewards/r1/remove")).toEqual({ expected_row_version: 4 }))
        fireEvent.click(await screen.findByRole("button", { name: "Remove Village saved" }))
        await waitFor(() => expect(lastBody(server, "outcomes/out1/remove")).toEqual({ expected_row_version: 5 }))
    })

    it("adds a reward and requires a description", async () => {
        const { server } = setupQuestWorkspace({ section: "outcomes" })
        const form = await screen.findByRole("form", { name: "Add a reward to Village saved" })
        fireEvent.click(within(form).getByRole("button", { name: "Add reward" }))
        expect(await within(form).findByText("Describe the reward.")).toBeInTheDocument()
        fireEvent.change(within(form).getByRole("textbox", { name: /Reward/ }), { target: { value: "A horse" } })
        fireEvent.click(within(form).getByRole("button", { name: "Add reward" }))
        await waitFor(() => expect(lastBody(server, "outcomes/out1/rewards")).toBeDefined())
        expect(lastBody(server, "outcomes/out1/rewards")).toMatchObject({
            reward_type: "other",
            description: "A horse",
            reward_knowledge_item_id: null,
        })
    })

    it("shows outcomes as text, with no controls, when the quest cannot be edited", async () => {
        setupQuestWorkspace({
            section: "outcomes",
            view: questView({ canon_status: "proposed", available_actions: [], blocked_actions: [{ action: "update", reason: "review_in_progress" }] }),
        })
        const card = await screen.findByRole("article", { name: "Outcome Village saved" })
        expect(within(card).getByText(/50 gold/)).toBeInTheDocument()
        expect(screen.queryByRole("form", { name: "Add an outcome" })).toBeNull()
        expect(screen.queryByRole("button", { name: /Remove/ })).toBeNull()
    })
})

describe("Independent drafts", () => {
    it("keeps what is half-typed in a completion section when another section saves", async () => {
        const { server } = setupQuestWorkspace({ section: "participants" })
        await screen.findByText(/Mara \(giver\)/)
        // A half-typed reward in Outcomes, then a different command (a stage edit) saves.
        fireEvent.click(screen.getByRole("link", { name: "Outcomes and rewards" }))
        const reward = await screen.findByRole("form", { name: "Add a reward to Village saved" })
        fireEvent.change(within(reward).getByRole("textbox", { name: /Reward/ }), { target: { value: "A horse" } })
        fireEvent.click(screen.getByRole("link", { name: "Details" }))
        fireEvent.change(await screen.findByRole("textbox", { name: /^Name/ }), { target: { value: "Renamed" } })
        fireEvent.click(screen.getByRole("button", { name: "Save details" }))
        await waitFor(() => expect(server.callsTo("POST", new RegExp(`${AUTHORING}/q1/update$`))).toHaveLength(1))
        // Reading the quest again (a new version) must not remount the completion forms.
        await waitFor(() => expect(server.callsTo("GET", `${AUTHORING}/q1`).length).toBeGreaterThan(1))
        fireEvent.click(screen.getByRole("link", { name: "Outcomes and rewards" }))
        expect(
            within(await screen.findByRole("form", { name: "Add a reward to Village saved" })).getByRole("textbox", {
                name: /Reward/,
            }),
        ).toHaveValue("A horse")
    })
})

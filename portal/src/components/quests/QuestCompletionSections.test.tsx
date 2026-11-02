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

// Another editor changed the saved quest while this page stayed open; the page then reads it again
// (here, through an unrelated command), and the retained forms must not adopt the newer version with
// older field values.
const renamedElsewhere = () =>
    questView({
        row_version: 5,
        gm_notes: "Their note.",
        outcomes: [
            {
                quest_outcome_id: "out1",
                code: "saved",
                name: "Village rescued",
                description: "Their description.",
                outcome_category: "success",
                rewards: [{ quest_reward_id: "r1", reward_type: "other", description: "50 gold", knowledge: null }],
            },
        ],
    })

describe("Retained forms and changes made elsewhere", () => {
    it("synchronises an untouched outcome form with the newer saved fields before it can save", async () => {
        const { server, setView } = setupQuestWorkspace({ section: "participants" })
        await screen.findByText(/Mara \(giver\)/)
        setView(renamedElsewhere())
        fireEvent.click(screen.getByRole("button", { name: "Remove Mara" })) // an unrelated command reads the quest again
        await waitFor(() => expect(lastBody(server, "participants/p1/remove")).toBeDefined())
        fireEvent.click(screen.getByRole("link", { name: "Outcomes and rewards" }))
        fireEvent.click(await screen.findByRole("button", { name: "Edit Village rescued" }))
        const form = screen.getByRole("form", { name: "Edit outcome Village rescued" })
        expect(within(form).getByRole("textbox", { name: /^Name/ })).toHaveValue("Village rescued")
        expect(within(form).getByRole("textbox", { name: /^Description/ })).toHaveValue("Their description.")
        fireEvent.change(within(form).getByRole("combobox", { name: /Kind of outcome/ }), { target: { value: "failure" } })
        fireEvent.click(within(form).getByRole("button", { name: "Save outcome" }))
        await waitFor(() => expect(lastBody(server, "outcomes/out1/update")).toBeDefined())
        // The newer name and description are sent back, at the version they belong to.
        expect(lastBody(server, "outcomes/out1/update")).toEqual({
            expected_row_version: 6,
            name: "Village rescued",
            description: "Their description.",
            outcome_category: "failure",
        })
    })

    it("keeps a dirty outcome draft, pauses saving, and lets the person choose", async () => {
        const { server, setView } = setupQuestWorkspace({ section: "outcomes" })
        fireEvent.click(await screen.findByRole("button", { name: "Edit Village saved" }))
        const form = screen.getByRole("form", { name: "Edit outcome Village saved" })
        fireEvent.change(within(form).getByRole("textbox", { name: /^Name/ }), { target: { value: "Village freed" } })
        setView(renamedElsewhere())
        fireEvent.click(screen.getByRole("link", { name: "Participants" }))
        fireEvent.click(await screen.findByRole("button", { name: "Remove Mara" }))
        await waitFor(() => expect(lastBody(server, "participants/p1/remove")).toBeDefined())
        fireEvent.click(screen.getByRole("link", { name: "Outcomes and rewards" }))
        expect(await screen.findByText(/Outcome Village rescued changed elsewhere/)).toBeInTheDocument()
        const draft = screen.getByRole("form", { name: /Edit outcome/ })
        expect(within(draft).getByRole("textbox", { name: /^Name/ })).toHaveValue("Village freed")
        expect(within(draft).getByRole("button", { name: "Save outcome" })).toBeDisabled()
        expect(lastBody(server, "outcomes/out1/update")).toBeUndefined()

        // Choosing to keep it saves the draft over the newer fields, at the current version, once seen.
        fireEvent.click(screen.getByRole("button", { name: "Keep my changes and save over it" }))
        fireEvent.click(within(screen.getByRole("form", { name: /Edit outcome/ })).getByRole("button", { name: "Save outcome" }))
        await waitFor(() => expect(lastBody(server, "outcomes/out1/update")).toBeDefined())
        expect(lastBody(server, "outcomes/out1/update")).toMatchObject({ expected_row_version: 6, name: "Village freed" })
    })

    it("lets the person take the latest saved version instead, dropping the draft", async () => {
        const { setView } = setupQuestWorkspace({ section: "outcomes" })
        fireEvent.click(await screen.findByRole("button", { name: "Edit Village saved" }))
        fireEvent.change(screen.getByRole("textbox", { name: /^Name/ }), { target: { value: "Village freed" } })
        setView(renamedElsewhere())
        fireEvent.click(screen.getByRole("link", { name: "Participants" }))
        fireEvent.click(await screen.findByRole("button", { name: "Remove Mara" }))
        fireEvent.click(screen.getByRole("link", { name: "Outcomes and rewards" }))
        fireEvent.click(await screen.findByRole("button", { name: "Load the latest saved version" }))
        expect(within(screen.getByRole("form", { name: /Edit outcome/ })).getByRole("textbox", { name: /^Name/ })).toHaveValue(
            "Village rescued",
        )
        expect(screen.queryByText(/changed elsewhere/)).toBeNull()
    })

    it("keeps a dirty note, pauses its save when the saved notes changed, and sends the chosen note at the current version", async () => {
        const { server, setView } = setupQuestWorkspace({ section: "details" })
        fireEvent.change(await screen.findByRole("textbox", { name: /Planning notes/ }), { target: { value: "My note" } })
        setView(renamedElsewhere())
        fireEvent.click(screen.getByRole("link", { name: "Participants" }))
        fireEvent.click(await screen.findByRole("button", { name: "Remove Mara" }))
        await waitFor(() => expect(lastBody(server, "participants/p1/remove")).toBeDefined())
        fireEvent.click(screen.getByRole("link", { name: "Details" }))
        expect(await screen.findByText(/The planning notes changed elsewhere/)).toBeInTheDocument()
        expect(screen.getByRole("textbox", { name: /Planning notes/ })).toHaveValue("My note")
        expect(screen.getByRole("button", { name: "Save notes" })).toBeDisabled()
        fireEvent.click(screen.getByRole("button", { name: "Keep my changes and save over it" }))
        fireEvent.click(screen.getByRole("button", { name: "Save notes" }))
        await waitFor(() => expect(lastBody(server, "update")).toBeDefined())
        expect(lastBody(server, "update")).toMatchObject({ expected_row_version: 6, gm_notes: "My note" })
    })

    it("keeps saves independent when only something unrelated changed", async () => {
        const { server, setView } = setupQuestWorkspace({ section: "details" })
        fireEvent.change(await screen.findByRole("textbox", { name: /Planning notes/ }), { target: { value: "My note" } })
        setView(questView({ row_version: 5 })) // same saved notes, a newer version
        fireEvent.click(screen.getByRole("link", { name: "Participants" }))
        fireEvent.click(await screen.findByRole("button", { name: "Remove Mara" }))
        await waitFor(() => expect(lastBody(server, "participants/p1/remove")).toBeDefined())
        fireEvent.click(screen.getByRole("link", { name: "Details" }))
        expect(screen.queryByText(/changed elsewhere/)).toBeNull()
        fireEvent.click(screen.getByRole("button", { name: "Save notes" }))
        await waitFor(() => expect(lastBody(server, "update")).toBeDefined())
        expect(lastBody(server, "update")).toMatchObject({ expected_row_version: 6, gm_notes: "My note" })
    })

    it("does not mistake a form's own successful save for a change made elsewhere", async () => {
        setupQuestWorkspace({ section: "details" })
        fireEvent.change(await screen.findByRole("textbox", { name: /Planning notes/ }), { target: { value: "Fresh" } })
        fireEvent.click(screen.getByRole("button", { name: "Save notes" }))
        await waitFor(() => expect(screen.getByTestId("authoring-announcer")).toHaveTextContent("GM notes saved"))
        expect(screen.queryByText(/changed elsewhere/)).toBeNull()
    })
})

describe("Choice-only drafts are unsent input", () => {
    const leave = async (router: { navigate: (to: string) => unknown }, expected: string) => {
        void router.navigate("/app/c1/quests")
        const dialog = await screen.findByRole("dialog", { name: "Discard unsaved input?" })
        expect(dialog).toHaveTextContent(expected)
        fireEvent.click(within(dialog).getByRole("button", { name: "Keep editing" }))
    }

    it("names a changed kind of outcome, and a section change is not leaving", async () => {
        const { router } = setupQuestWorkspace({ section: "outcomes" })
        const form = await screen.findByRole("form", { name: "Add an outcome" })
        fireEvent.change(within(form).getByRole("combobox", { name: /Kind of outcome/ }), { target: { value: "failure" } })
        await leave(router, "an outcome")
        fireEvent.click(screen.getByRole("link", { name: "Participants" }))
        expect(screen.queryByRole("dialog")).toBeNull()
    })

    it("names a changed participant role", async () => {
        const { router } = setupQuestWorkspace({ section: "participants" })
        const form = await screen.findByRole("form", { name: "Add a participant" })
        fireEvent.change(within(form).getByRole("combobox", { name: /Role in the quest/ }), { target: { value: "giver" } })
        await leave(router, "a participant")
    })

    it("names a changed reward kind", async () => {
        const { router } = setupQuestWorkspace({ section: "outcomes" })
        const form = await screen.findByRole("form", { name: "Add a reward to Village saved" })
        fireEvent.change(within(form).getByRole("combobox", { name: /Reward kind/ }), { target: { value: "knowledge" } })
        await leave(router, "a reward")
    })

    it("names a changed edit form of an outcome, by category alone", async () => {
        const { router } = setupQuestWorkspace({ section: "outcomes" })
        fireEvent.click(await screen.findByRole("button", { name: "Edit Village saved" }))
        fireEvent.change(within(screen.getByRole("form", { name: /Edit outcome/ })).getByRole("combobox"), { target: { value: "failure" } })
        await leave(router, "an outcome")
    })

    it("is clean again once its own command succeeded", async () => {
        const { router } = setupQuestWorkspace({ section: "outcomes" })
        const form = await screen.findByRole("form", { name: "Add an outcome" })
        fireEvent.change(within(form).getByRole("textbox", { name: /Code/ }), { target: { value: "lost" } })
        fireEvent.change(within(form).getByRole("textbox", { name: /Outcome name/ }), { target: { value: "Lost" } })
        fireEvent.change(within(form).getByRole("combobox", { name: /Kind of outcome/ }), { target: { value: "failure" } })
        fireEvent.click(within(form).getByRole("button", { name: "Add outcome" }))
        await waitFor(() => expect(within(form).getByRole("combobox", { name: /Kind of outcome/ })).toHaveValue("success"))
        // The guard learns it is clean a render later; leaving must then go through without a dialog.
        await waitFor(() => {
            void router.navigate("/app/c1/quests")
            expect(router.state.location.pathname).toBe("/app/c1/quests")
        })
        expect(screen.queryByRole("dialog")).toBeNull()
    })
})

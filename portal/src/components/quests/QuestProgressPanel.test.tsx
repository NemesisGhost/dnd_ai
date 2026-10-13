import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { AUTHORING, RUNTIME, questProgress, questView, setupQuestWorkspace } from "../../test/questWorkspaceHarness"

afterEach(() => {
    vi.unstubAllGlobals()
})

// A published quest, opened on its Progress section.
function setup(progress: object = questProgress(), extra: object = {}) {
    const ctx = setupQuestWorkspace({
        section: "progress",
        view: questView({ canon_status: "canon" }),
        progress,
        ...extra,
    })
    ctx.server.on("POST", new RegExp(`${RUNTIME}/`), {
        body: { quest_id: "q1", event_id: "e1", previous_status: "active", status: "x", changed: true },
    })
    return ctx
}

describe("Quest Progress", () => {
    it("shows the status, the actions that apply, and each objective", async () => {
        setup()
        const card = await screen.findByRole("article", { name: "Progress for Everyone" })
        expect(within(card).getByRole("heading", { name: /Everyone: Active/ })).toBeInTheDocument()
        expect(within(card).getByRole("button", { name: "Suspend quest for Everyone" })).toBeEnabled()
        expect(within(card).queryByRole("button", { name: /Activate quest/ })).not.toBeInTheDocument()
        expect(within(card).getByText(/Find the map — Completed/)).toBeInTheDocument()
        expect(within(card).getByRole("button", { name: "Skip Reach the ruin for Everyone" })).toBeInTheDocument()
    })

    it("says publishing does not start the quest and nothing completes it", async () => {
        setup()
        expect(await screen.findByText(/Publishing a quest does not start it, and nothing completes it automatically/)).toBeInTheDocument()
    })

    it("suspends at once, naming the status it saw", async () => {
        const { server } = setup()
        fireEvent.click(await screen.findByRole("button", { name: "Suspend quest for Everyone" }))
        await waitFor(() => expect(server.callsTo("POST", `${RUNTIME}/suspend`)).toHaveLength(1))
        expect(server.callsTo("POST", `${RUNTIME}/suspend`)[0]!.body).toEqual({
            expected_status: "active",
            party_id: null,
            note: null,
        })
    })

    it("asks for confirmation before finishing a quest, and sends the note", async () => {
        const { server } = setup()
        fireEvent.click(await screen.findByRole("button", { name: "Complete quest for Everyone" }))
        const dialog = await screen.findByRole("dialog")
        expect(server.callsTo("POST", `${RUNTIME}/complete`)).toHaveLength(0)
        fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: " The twist " } })
        fireEvent.click(within(dialog).getByRole("button", { name: "Complete quest" }))
        await waitFor(() => expect(server.callsTo("POST", `${RUNTIME}/complete`)).toHaveLength(1))
        expect(server.callsTo("POST", `${RUNTIME}/complete`)[0]!.body).toMatchObject({
            expected_status: "active",
            note: "The twist",
        })
    })

    it("cancelling the confirmation sends nothing", async () => {
        const { server } = setup()
        fireEvent.click(await screen.findByRole("button", { name: "Abandon quest for Everyone" }))
        const dialog = await screen.findByRole("dialog")
        fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }))
        expect(server.callsTo("POST", `${RUNTIME}/abandon`)).toHaveLength(0)
    })

    it("moves an objective with the status it saw", async () => {
        const { server } = setup()
        server.on("POST", /objectives\/o2\/status/, {
            body: { quest_id: "q1", event_id: "e2", previous_status: null, status: "active", changed: true },
        })
        fireEvent.click(await screen.findByRole("button", { name: "Start Reach the ruin for Everyone" }))
        await waitFor(() => expect(server.callsTo("POST", /objectives\/o2\/status/)).toHaveLength(1))
        expect(server.callsTo("POST", /objectives\/o2\/status/)[0]!.body).toEqual({
            new_status: "active",
            expected_status: null,
            party_id: null,
        })
    })

    it("hints that all required objectives are complete without completing the quest", async () => {
        const { server } = setup(questProgress({ all_required_complete: true }))
        expect(await screen.findByText(/All required objectives are complete/)).toBeInTheDocument()
        expect(server.callsTo("POST", `${RUNTIME}/complete`)).toHaveLength(0)
    })

    it("lists each party's own progress", async () => {
        const { server } = setup(
            questProgress(
                {},
                {
                    party_id: "p1",
                    party_name: "Red Company",
                    status: null,
                    actions: ["activate"],
                    all_required_complete: false,
                    objectives: [],
                },
            ),
        )
        fireEvent.click(await screen.findByRole("button", { name: /Red Company/ }))
        const card = await screen.findByRole("article", { name: "Progress for Red Company" })
        fireEvent.click(within(card).getByRole("button", { name: "Activate quest for Red Company" }))
        await waitFor(() => expect(server.callsTo("POST", `${RUNTIME}/activate`)).toHaveLength(1))
        expect(server.callsTo("POST", `${RUNTIME}/activate`)[0]!.body).toEqual({
            expected_status: null,
            party_id: "p1",
            note: null,
        })
    })

    it("explains a refused transition", async () => {
        const { server } = setup()
        server.on("POST", `${RUNTIME}/suspend`, {
            status: 409,
            body: { error: { code: "quest_transition_invalid", message: "m", correlation_id: "c" } },
        })
        fireEvent.click(await screen.findByRole("button", { name: "Suspend quest for Everyone" }))
        expect(await screen.findByRole("alert")).toHaveTextContent(/not in a state that allows that/)
    })
})

describe("Quest Progress eligibility follows the page's lifecycle, not the progress read alone", () => {
    const withActions = () => questProgress({ actions: ["activate"], status: null })

    it("withholds every command for a draft, and says to publish first", async () => {
        setupQuestWorkspace({
            section: "progress",
            view: questView({ canon_status: "draft" }),
            // Even a progress read that offers actions cannot unlock a draft.
            progress: withActions(),
        })
        expect(await screen.findByText("This quest is not published yet. Publish it before running it.")).toBeInTheDocument()
        const card = await screen.findByRole("article", { name: "Progress for Everyone" })
        expect(within(card).queryByRole("button")).toBeNull()
        expect(within(card).getByText(/Find the map — Completed/)).toBeInTheDocument()
    })

    it("withholds the commands for an archived quest and a replaced quest", async () => {
        setupQuestWorkspace({
            section: "progress",
            view: questView({ canon_status: "canon", lifecycle_status: "archived" }),
            progress: withActions(),
        })
        expect(await screen.findByText("This quest is archived. Restore it before running it.")).toBeInTheDocument()
        expect(screen.queryByRole("button", { name: /Activate quest/ })).toBeNull()
    })

    it("withholds the commands for a replaced quest", async () => {
        setupQuestWorkspace({
            section: "progress",
            view: questView({ canon_status: "superseded" }),
            progress: withActions(),
        })
        expect(await screen.findByText("This quest has been replaced. Run its replacement.")).toBeInTheDocument()
        expect(screen.queryByRole("button", { name: /Activate quest/ })).toBeNull()
    })

    it("treats an unreadable lifecycle as not eligible, and withholds the commands", async () => {
        setupQuestWorkspace({
            section: "progress",
            view: questView({ canon_status: "canon" }),
            progress: withActions(),
            lifecycleError: true,
        })
        expect(await screen.findByText(/status could not be loaded, so running it is not offered/)).toBeInTheDocument()
        expect(screen.queryByRole("button", { name: /Activate quest/ })).toBeNull()
        expect(screen.getByRole("article", { name: "Progress for Everyone" })).toBeInTheDocument()
    })
})

describe("Quest Progress refresh", () => {
    it("reads again in place after a lifecycle step, keeping a typed note", async () => {
        const { server, setProgress, setLifecycle } = setupQuestWorkspace({
            section: "progress",
            view: questView({ canon_status: "draft" }),
            progress: questProgress({ actions: [] }),
        })
        expect(await screen.findByText(/not published yet/)).toBeInTheDocument()
        expect(screen.queryByRole("button", { name: /Complete quest/ })).toBeNull()
        const reads = server.callsTo("GET", `${RUNTIME}/progress`).length
        setProgress(questProgress())
        setLifecycle({ canon_status: "canon", available_actions: ["supersede", "archive"] })
        // A save elsewhere bumps the page's change counter; reading again must not remount.
        fireEvent.click(screen.getByRole("link", { name: /Prepare/ }))
        fireEvent.change(await screen.findByRole("textbox", { name: /Planning notes/ }), { target: { value: "n" } })
        fireEvent.click(screen.getByRole("button", { name: "Save notes" }))
        await waitFor(() => expect(server.callsTo("GET", `${RUNTIME}/progress`).length).toBeGreaterThan(reads))
        fireEvent.click(screen.getByRole("link", { name: /Use in play/ }))
        expect(await screen.findByRole("button", { name: "Suspend quest for Everyone" })).toBeInTheDocument()
    })

    it("keeps what it holds, says it may be out of date, and offers Try again when a refresh fails", async () => {
        const { server } = setup()
        await screen.findByRole("article", { name: "Progress for Everyone" })
        server.on("GET", `${RUNTIME}/progress`, {
            status: 500,
            body: { error: { code: "internal_error", message: "m", correlation_id: "c" } },
        })
        fireEvent.click(screen.getByRole("link", { name: /Prepare/ }))
        fireEvent.change(await screen.findByRole("textbox", { name: /Planning notes/ }), { target: { value: "n" } })
        fireEvent.click(screen.getByRole("button", { name: "Save notes" }))
        fireEvent.click(await screen.findByRole("link", { name: /Use in play/ }))
        expect(await screen.findByText(/may be out of date/)).toBeInTheDocument()
        expect(screen.getByRole("article", { name: "Progress for Everyone" })).toBeInTheDocument()
        server.on("GET", `${RUNTIME}/progress`, { body: questProgress() })
        const before = server.callsTo("POST", /./).length
        fireEvent.click(screen.getByRole("button", { name: "Try again" }))
        await waitFor(() => expect(screen.queryByText(/may be out of date/)).toBeNull())
        // Try again only reads.
        expect(server.callsTo("POST", /./)).toHaveLength(before)
    })
})

describe("Quest Progress and the structure it can lock", () => {
    it("reads the quest again after a command, so structure that now has progress is locked in place", async () => {
        const { server, setView } = setup(questProgress({ status: null, actions: ["activate"] }))
        await screen.findByRole("article", { name: "Progress for Everyone" })
        const reads = server.callsTo("GET", `${AUTHORING}/q1`).length
        // After the activation the server reports recorded progress and withdraws the structural actions.
        setView(
            questView({
                canon_status: "canon",
                has_progress: true,
                row_version: 5,
                available_actions: ["update", "add_stage", "update_stage", "add_objective", "update_objective"],
                blocked_actions: ["reorder_stages", "remove_stage", "remove_objective"].map((action) => ({
                    action,
                    reason: "quest_has_progress",
                })),
            }),
        )
        fireEvent.click(screen.getByRole("button", { name: "Activate quest for Everyone" }))
        await waitFor(() => expect(server.callsTo("GET", `${AUTHORING}/q1`).length).toBeGreaterThan(reads))
        // One command, and Progress was read again by its own refresh, not by repeating anything.
        expect(server.callsTo("POST", `${RUNTIME}/activate`)).toHaveLength(1)

        fireEvent.click(screen.getByRole("link", { name: /Prepare/ }))
        fireEvent.click(await screen.findByRole("link", { name: "Stages and objectives" }))
        expect(await screen.findByRole("note")).toHaveTextContent("already has progress recorded")
        fireEvent.click(screen.getByRole("button", { name: "Expand all" }))
        expect(screen.queryByRole("button", { name: /Remove stage/ })).toBeNull()
        expect(screen.queryByRole("button", { name: /Remove objective/ })).toBeNull()
        expect(screen.queryByRole("button", { name: /Move (up|down)/ })).toBeNull()
        // Wording and visibility stay editable; the structural fields are disabled with their reason.
        fireEvent.click(screen.getAllByRole("button", { name: /Edit objective/ })[0]!)
        const panel = screen.getByRole("form", { name: "Edit objective" })
        expect(within(panel).getByRole("combobox", { name: /Kind of objective/ })).toBeDisabled()
        expect(within(panel).getByRole("textbox", { name: /Objective name/ })).toBeEnabled()
        expect(within(panel).getByRole("combobox", { name: "Visibility" })).toBeEnabled()
        expect(within(panel).getAllByText(/recorded progress/).length).toBeGreaterThan(0)
    })

    it("keeps a half-typed draft elsewhere through that refresh", async () => {
        const { setView } = setup(questProgress({ status: null, actions: ["activate"] }))
        fireEvent.click(await screen.findByRole("link", { name: /Prepare/ }))
        fireEvent.click(await screen.findByRole("link", { name: "Participants" }))
        const form = await screen.findByRole("form", { name: "Add a participant" })
        fireEvent.change(within(form).getByRole("combobox", { name: /Role in the quest/ }), { target: { value: "giver" } })
        setView(questView({ canon_status: "canon", has_progress: true, row_version: 5 }))
        fireEvent.click(screen.getByRole("link", { name: /Use in play/ }))
        fireEvent.click(await screen.findByRole("button", { name: "Activate quest for Everyone" }))
        await waitFor(() => expect(screen.getByTestId("authoring-announcer")).toHaveTextContent("Activate quest: done"))
        fireEvent.click(screen.getByRole("link", { name: /Prepare/ }))
        expect(within(screen.getByRole("form", { name: "Add a participant" })).getByRole("combobox", { name: /Role in the quest/ })).toHaveValue(
            "giver",
        )
    })
})

describe("Quest Progress scopes", () => {
    const party = {
        party_id: "p1",
        party_name: "Red Company",
        status: "active",
        actions: ["suspend"],
        all_required_complete: false,
        objectives: [
            { quest_objective_id: "o1", name: "Find the map", stage_name: "Opening", requirement_level: "required", status: "active", next_statuses: ["completed"] },
        ],
    }

    it("lists everyone and each party with its status, and shows only the selected scope's details", async () => {
        const { server } = setup(questProgress({}, party))
        const list = await screen.findByRole("navigation", { name: "Progress scopes" })
        const items = within(list).getAllByRole("button")
        expect(items.map((b) => b.textContent)).toEqual(["EveryoneActive", "Red CompanyActive"])
        expect(items[0]).toHaveAttribute("aria-pressed", "true")
        expect(screen.getByRole("article", { name: "Progress for Everyone" })).toBeInTheDocument()
        expect(screen.queryByRole("article", { name: "Progress for Red Company" })).toBeNull()
        fireEvent.click(items[1]!)
        expect(items[1]).toHaveAttribute("aria-pressed", "true")
        expect(screen.getByRole("article", { name: "Progress for Red Company" })).toBeInTheDocument()
        expect(screen.queryByRole("article", { name: "Progress for Everyone" })).toBeNull()
        // Choosing a scope sends nothing.
        expect(server.callsTo("POST", /./)).toHaveLength(0)
    })

    it("keeps the chosen scope through a refresh", async () => {
        const { server } = setup(questProgress({}, party))
        fireEvent.click(await screen.findByRole("button", { name: /Red Company/ }))
        fireEvent.click(await screen.findByRole("button", { name: "Suspend quest for Red Company" }))
        await waitFor(() => expect(server.callsTo("POST", `${RUNTIME}/suspend`)).toHaveLength(1))
        await waitFor(() => expect(screen.getByRole("article", { name: "Progress for Red Company" })).toBeInTheDocument())
    })

    it("puts each objective's moves in their own group, apart from its text", async () => {
        setup()
        const move = await screen.findByRole("button", { name: "Start Reach the ruin for Everyone" })
        const group = move.parentElement!
        expect(group).toHaveClass("quest-progress__moves")
        expect(within(group).getAllByRole("button").length).toBeGreaterThan(1)
        expect(group.parentElement).toHaveClass("quest-progress__objective")
    })
})

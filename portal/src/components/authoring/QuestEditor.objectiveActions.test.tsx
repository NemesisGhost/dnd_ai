import { act, fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import {
    AUTHORING,
    FREE_ACTIONS,
    questObjective,
    questView,
    setupQuestWorkspace,
} from "../../test/questWorkspaceHarness"

// P15-C10-S01-T01 acceptance cases A1-A17 (docs/delivery/p15-c10-s01-objective-actions-plan.md, section 6):
// an objective's management actions are their own labelled group, closing a form returns focus to the
// control that opened it, switching away from unsaved input asks first, and a refusal because play has
// begun is reconciled with one read.

const QUEST = `${AUTHORING}/q1`
const O1_UPDATE = `${QUEST}/stages/s1/objectives/o1/update`
const O1_REMOVE = `${QUEST}/stages/s1/objectives/o1/remove`
const O2_REMOVE = `${QUEST}/stages/s1/objectives/o2/remove`
const REFUSED = { status: 409, body: { error: { code: "quest_has_progress", message: "m", correlation_id: "c" } } }
const LOST = { networkError: true }

afterEach(() => {
    vi.unstubAllGlobals()
})

const lockedView = (over: object = {}) =>
    questView({
        has_progress: true,
        field_locks: ["structure"],
        available_actions: ["update", "add_stage", "update_stage", "add_objective", "update_objective"],
        blocked_actions: [
            { action: "reorder_stages", reason: "quest_has_progress" },
            { action: "remove_stage", reason: "quest_has_progress" },
            { action: "remove_objective", reason: "quest_has_progress" },
        ],
        ...over,
    })

const withoutActions = (...names: string[]) => FREE_ACTIONS.filter((a) => !names.includes(a))

async function expandAll() {
    fireEvent.click(await screen.findByRole("button", { name: "Expand all" }))
}

const button = (name: string) => screen.getByRole("button", { name })
const editForm = () => screen.getByRole("form", { name: "Edit objective" })

// Every announcement the live region receives, in order (the region swaps a node per announcement).
function watchAnnouncements(): string[] {
    const heard: string[] = []
    const region = screen.getByTestId("authoring-announcer")
    new MutationObserver((records) => {
        for (const record of records) {
            record.addedNodes.forEach((node) => {
                if (node.textContent) heard.push(node.textContent)
            })
        }
    }).observe(region, { childList: true, subtree: true })
    return heard
}

const settle = () => act(async () => void (await new Promise((resolve) => setTimeout(resolve, 30))))

describe("Quest objectives: where focus goes when a form closes", () => {
    it("A1 returns focus to Edit objective after Cancel", async () => {
        setupQuestWorkspace()
        await expandAll()
        fireEvent.click(await screen.findByRole("button", { name: "Edit objective Find the map" }))
        fireEvent.click(within(editForm()).getByRole("button", { name: "Cancel" }))
        await waitFor(() => expect(button("Edit objective Find the map")).toHaveFocus())
    })

    it("A2 returns focus to Add objective after Cancel on a new objective", async () => {
        setupQuestWorkspace()
        await expandAll()
        fireEvent.click(await screen.findByRole("button", { name: "Add objective to Opening" }))
        fireEvent.click(within(screen.getByRole("form", { name: "New objective" })).getByRole("button", { name: "Cancel" }))
        await waitFor(() => expect(button("Add objective to Opening")).toHaveFocus())
    })

    it("A3 returns focus to Edit stage, and to Add stage for a new stage, after Cancel", async () => {
        setupQuestWorkspace()
        await expandAll()
        fireEvent.click(await screen.findByRole("button", { name: "Edit stage Opening" }))
        fireEvent.click(within(screen.getByRole("form", { name: "Edit stage" })).getByRole("button", { name: "Cancel" }))
        await waitFor(() => expect(button("Edit stage Opening")).toHaveFocus())

        fireEvent.click(button("Add stage"))
        fireEvent.click(within(screen.getByRole("form", { name: "New stage" })).getByRole("button", { name: "Cancel" }))
        await waitFor(() => expect(button("Add stage")).toHaveFocus())
    })
})

describe("Quest objectives: switching away from unsaved input", () => {
    it("A4 asks before another form replaces a dirty one; Keep editing keeps it, Discard changes switches", async () => {
        const { server } = setupQuestWorkspace()
        await expandAll()
        fireEvent.click(await screen.findByRole("button", { name: "Edit objective Find the map" }))
        fireEvent.change(within(editForm()).getByRole("textbox", { name: /Objective name/ }), { target: { value: "Typed draft" } })
        const callsBefore = server.calls.length

        fireEvent.click(button("Edit objective Reach the ruin"))
        const dialog = await screen.findByRole("dialog", { name: "Discard your changes?" })
        expect(dialog).toHaveTextContent('Your changes to the objective "Find the map" have not been saved.')
        expect(server.calls.length).toBe(callsBefore)

        fireEvent.click(within(dialog).getByRole("button", { name: "Keep editing" }))
        await waitFor(() => expect(screen.queryByRole("dialog", { name: "Discard your changes?" })).toBeNull())
        expect(within(editForm()).getByRole("textbox", { name: /Objective name/ })).toHaveValue("Typed draft")
        await waitFor(() => expect(button("Edit objective Reach the ruin")).toHaveFocus())

        fireEvent.click(button("Edit objective Reach the ruin"))
        fireEvent.click(within(await screen.findByRole("dialog", { name: "Discard your changes?" })).getByRole("button", { name: "Discard changes" }))
        await waitFor(() =>
            expect(within(editForm()).getByRole("textbox", { name: /Objective name/ })).toHaveValue("Reach the ruin"),
        )
        expect(screen.queryByDisplayValue("Typed draft")).toBeNull()
        expect(server.calls.length).toBe(callsBefore)
    })

    it("A5 switches at once, with no dialog, when the open form is clean", async () => {
        setupQuestWorkspace()
        await expandAll()
        fireEvent.click(await screen.findByRole("button", { name: "Edit objective Find the map" }))
        fireEvent.click(button("Edit objective Reach the ruin"))
        expect(screen.queryByRole("dialog", { name: "Discard your changes?" })).toBeNull()
        expect(within(editForm()).getByRole("textbox", { name: /Objective name/ })).toHaveValue("Reach the ruin")
    })

    it("A8 leaves an open form and its values alone when a stage is toggled; expanding sends nothing", async () => {
        const { server } = setupQuestWorkspace()
        await expandAll()
        fireEvent.click(await screen.findByRole("button", { name: "Edit objective Find the map" }))
        fireEvent.change(within(editForm()).getByRole("textbox", { name: /Objective name/ }), { target: { value: "Typed draft" } })
        const callsBefore = server.calls.length
        fireEvent.click(screen.getByRole("button", { name: /^1\. Opening/ }))
        expect(within(editForm()).getByRole("textbox", { name: /Objective name/ })).toHaveValue("Typed draft")
        // The stage holding the open form is never collapsed out from under the author.
        fireEvent.click(button("Collapse all"))
        expect(within(editForm()).getByRole("textbox", { name: /Objective name/ })).toHaveValue("Typed draft")
        expect(server.calls.length).toBe(callsBefore)
    })
})

describe("Quest objectives: the action group", () => {
    it("A6 puts Edit and Remove in a labelled group before the hint and description, outside the stage toggle", async () => {
        const stage = questView().stages[0]!
        setupQuestWorkspace({
            view: questView({
                stages: [{ ...stage, objectives: [questObjective("o1", "Find the map", { description: "Look in the cellar." }), stage.objectives[1]] }],
            }),
        })
        await expandAll()
        const group = await screen.findByRole("group", { name: "Manage objective Find the map" })
        expect(within(group).getByRole("button", { name: "Edit objective Find the map" })).toBeInTheDocument()
        expect(within(group).getByRole("button", { name: "Remove objective Find the map" })).toBeInTheDocument()
        const item = group.closest("li")!
        const hint = item.querySelector(".authoring-field__hint")!
        const description = within(item).getByText("Look in the cellar.")
        expect(group.compareDocumentPosition(hint) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
        expect(group.compareDocumentPosition(description) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
        const toggle = screen.getByRole("button", { name: /^1\. Opening/ })
        expect(toggle.contains(group)).toBe(false)
        expect(within(toggle).queryAllByRole("button")).toHaveLength(0)
    })

    it("A7 omits the group when no objective action is offered, and holds only Remove when only that is", async () => {
        setupQuestWorkspace({ view: questView({ available_actions: withoutActions("update_objective", "remove_objective") }) })
        await expandAll()
        await screen.findByRole("button", { name: "Add objective to Opening" })
        expect(screen.queryByRole("group", { name: /Manage objective/ })).toBeNull()
        expect(screen.queryByRole("button", { name: /Edit objective/ })).toBeNull()
        expect(screen.queryByRole("button", { name: /Remove objective/ })).toBeNull()
    })

    it("A7 holds only Remove when only remove_objective is offered", async () => {
        setupQuestWorkspace({ view: questView({ available_actions: withoutActions("update_objective") }) })
        await expandAll()
        const group = await screen.findByRole("group", { name: "Manage objective Find the map" })
        expect(within(group).getAllByRole("button").map((b) => b.textContent)).toEqual(["Remove objective"])
    })

    // A caller without canon.edit mounts nothing: guarded by the existing "Quest workspace: players" cases
    // (QuestWorkspace.test.tsx), which assert no authoring request and no editor.
    it("A13 offers no management group or Add objective when the quest is not editable", async () => {
        setupQuestWorkspace({ view: questView({ available_actions: [] }) })
        await expandAll()
        await screen.findByRole("button", { name: /^1\. Opening/ })
        expect(screen.queryByRole("group", { name: /Manage objective/ })).toBeNull()
        expect(screen.queryByRole("button", { name: /Add objective/ })).toBeNull()
        expect(screen.queryByRole("button", { name: /Edit objective|Remove objective/ })).toBeNull()
    })

    it("A9 disables Remove for the objective being edited, with the reason; another objective's stays enabled", async () => {
        setupQuestWorkspace()
        await expandAll()
        fireEvent.click(await screen.findByRole("button", { name: "Edit objective Find the map" }))
        const remove = button("Remove objective Find the map")
        expect(remove).toBeDisabled()
        const hintId = remove.getAttribute("aria-describedby")
        expect(hintId).toBeTruthy()
        expect(document.getElementById(hintId!)).toHaveTextContent("Close the edit form to remove this objective.")
        expect(button("Remove objective Reach the ruin")).toBeEnabled()
        expect(button("Remove objective Reach the ruin")).not.toHaveAttribute("aria-describedby")
    })
})

describe("Quest objectives: a refusal because play has begun", () => {
    it("A10 reads the quest once after a refused removal, drops the structural actions and puts focus on the heading", async () => {
        const { server, setView } = setupQuestWorkspace()
        server.on("POST", O1_REMOVE, () => {
            setView(lockedView())
            return REFUSED
        })
        await expandAll()
        fireEvent.click(await screen.findByRole("button", { name: "Remove objective Find the map" }))
        const dialog = await screen.findByRole("dialog", { name: "Remove this objective?" })
        const readsBefore = server.callsTo("GET", QUEST).length
        fireEvent.click(within(dialog).getByRole("button", { name: "Remove objective" }))
        expect(await within(dialog).findByText(/already has progress recorded/)).toBeInTheDocument()
        expect(within(dialog).queryByRole("button", { name: /Retry/ })).toBeNull()
        await waitFor(() => expect(server.callsTo("GET", QUEST)).toHaveLength(readsBefore + 1))
        expect(await screen.findByRole("note")).toHaveTextContent("already has progress recorded")
        expect(screen.queryByRole("button", { name: /^Remove objective \S/ })).toBeNull()
        expect(screen.queryByRole("button", { name: /Move (up|down)/ })).toBeNull()
        await settle()
        expect(server.callsTo("GET", QUEST)).toHaveLength(readsBefore + 1)

        fireEvent.click(within(dialog).getByRole("button", { name: "Keep it" }))
        await waitFor(() => expect(document.getElementById("objective-o1")).toHaveFocus())
    })

    it("A11 sets back only the locked fields of an open objective after a refused save, with a note", async () => {
        const { server, setView } = setupQuestWorkspace()
        server.on("POST", O1_UPDATE, () => {
            setView(lockedView())
            return REFUSED
        })
        await expandAll()
        fireEvent.click(await screen.findByRole("button", { name: "Edit objective Find the map" }))
        const form = editForm()
        fireEvent.change(within(form).getByRole("textbox", { name: /Objective name/ }), { target: { value: "Renamed" } })
        fireEvent.change(within(form).getByRole("combobox", { name: /Kind of objective/ }), { target: { value: "reach_location" } })
        fireEvent.change(within(form).getByRole("combobox", { name: "Visibility" }), { target: { value: "gm_only" } })
        const readsBefore = server.callsTo("GET", QUEST).length
        fireEvent.click(within(form).getByRole("button", { name: "Save objective" }))

        await waitFor(() => expect(server.callsTo("GET", QUEST)).toHaveLength(readsBefore + 1))
        const kind = await waitFor(() => {
            const select = within(editForm()).getByRole("combobox", { name: /Kind of objective/ })
            expect(select).toBeDisabled()
            return select
        })
        expect(kind).toHaveValue("other")
        expect(within(editForm()).getByRole("textbox", { name: /Objective name/ })).toHaveValue("Renamed")
        expect(within(editForm()).getByRole("combobox", { name: "Visibility" })).toHaveValue("gm_only")
        const note = screen.getByText(
            "Kind, requirement, completion, quantity and target were set back to their saved values because this quest now has recorded progress.",
        )
        expect(note).toHaveAttribute("role", "status")
        await settle()
        expect(server.callsTo("GET", QUEST)).toHaveLength(readsBefore + 1)
    })

    it("A12 keeps the progress-locked view as it was", async () => {
        setupQuestWorkspace({ view: lockedView() })
        await expandAll()
        expect(await screen.findByRole("note")).toHaveTextContent("already has progress recorded")
        expect(screen.queryByRole("button", { name: /Remove (stage|objective)/ })).toBeNull()
        expect(screen.queryByRole("button", { name: /Move (up|down)/ })).toBeNull()
        expect(screen.getByRole("button", { name: "Add objective to Opening" })).toBeEnabled()
        fireEvent.click(screen.getByRole("button", { name: "Edit objective Reach the ruin" }))
        const form = editForm()
        for (const name of [/Kind of objective/, /Requirement/, /Completion/, "Target"]) {
            expect(within(form).getByRole("combobox", { name })).toBeDisabled()
        }
        expect(within(form).getByRole("textbox", { name: "Quantity required" })).toBeDisabled()
        expect(within(form).getByRole("textbox", { name: /Objective name/ })).toBeEnabled()
        expect(within(form).getByRole("combobox", { name: "Visibility" })).toBeEnabled()
        expect(screen.queryByText(/were set back to their saved values/)).toBeNull()
    })
})

describe("Quest objectives: saved and removed", () => {
    it("A14 focuses the heading and announces once after a save; focuses Add objective and announces once after a removal", async () => {
        const { server, commit } = setupQuestWorkspace()
        server.on("POST", O2_REMOVE, () =>
            commit((d) => {
                const stage = (d.stages as ReturnType<typeof questView>["stages"])[0]!
                d.stages = [{ ...stage, objectives: [stage.objectives[0]] }]
            }),
        )
        await expandAll()
        const heard = watchAnnouncements()

        fireEvent.click(await screen.findByRole("button", { name: "Edit objective Find the map" }))
        fireEvent.change(within(editForm()).getByRole("textbox", { name: /Objective name/ }), { target: { value: "Find the old map" } })
        fireEvent.click(within(editForm()).getByRole("button", { name: "Save objective" }))
        await waitFor(() => expect(document.getElementById("objective-o1")).toHaveFocus())
        await settle()
        expect(heard.filter((m) => m === "Objective saved")).toHaveLength(1)

        fireEvent.click(button("Remove objective Reach the ruin"))
        const dialog = await screen.findByRole("dialog", { name: "Remove this objective?" })
        fireEvent.click(within(dialog).getByRole("button", { name: "Remove objective" }))
        await waitFor(() => expect(screen.getByRole("button", { name: "Add objective to Opening" })).toHaveFocus())
        await settle()
        expect(heard.filter((m) => m === "Objective removed")).toHaveLength(1)
    })

    it("A15 does not pull focus back into a section the person has left; it announces once", async () => {
        const { server, commit, router } = setupQuestWorkspace()
        let release: () => void = () => {}
        const gate = new Promise<void>((resolve) => (release = resolve))
        server.on("POST", O2_REMOVE, async () => {
            await gate
            return commit((d) => {
                const stage = (d.stages as ReturnType<typeof questView>["stages"])[0]!
                d.stages = [{ ...stage, objectives: [stage.objectives[0]] }]
            })
        })
        await expandAll()
        const heard = watchAnnouncements()
        fireEvent.click(await screen.findByRole("button", { name: "Remove objective Reach the ruin" }))
        const dialog = await screen.findByRole("dialog", { name: "Remove this objective?" })
        fireEvent.click(within(dialog).getByRole("button", { name: "Remove objective" }))
        await waitFor(() => expect(server.callsTo("POST", O2_REMOVE)).toHaveLength(1))

        await act(async () => {
            await router.navigate({ search: "?section=details" })
        })
        await waitFor(() => expect(document.getElementById("quest-section-details-heading")).toHaveFocus())
        await act(async () => release())
        await waitFor(() => expect(heard).toContain("Objective removed"))
        await settle()
        expect(document.getElementById("add-objective-s1")).not.toHaveFocus()
        expect(document.getElementById("quest-section-details-heading")).toHaveFocus()
        expect(heard.filter((m) => m === "Objective removed")).toHaveLength(1)
    })
})

describe("Quest objectives: a removal whose answer was lost", () => {
    async function lostRemoval() {
        const ctx = setupQuestWorkspace()
        ctx.server.on("POST", O1_REMOVE, LOST)
        await expandAll()
        fireEvent.click(await screen.findByRole("button", { name: "Remove objective Find the map" }))
        const dialog = await screen.findByRole("dialog", { name: "Remove this objective?" })
        fireEvent.click(within(dialog).getByRole("button", { name: "Remove objective" }))
        await within(dialog).findByText(/cannot tell whether this was saved/)
        return { ...ctx, dialog }
    }

    it("A16 offers Retry, which sends the same body under the same idempotency key", async () => {
        const { server, dialog } = await lostRemoval()
        fireEvent.click(within(dialog).getByRole("button", { name: "Retry" }))
        await waitFor(() => expect(server.callsTo("POST", O1_REMOVE)).toHaveLength(2))
        const [first, second] = server.callsTo("POST", O1_REMOVE)
        expect(second!.body).toEqual(first!.body)
        expect(second!.headers["Idempotency-Key"]).toBe(first!.headers["Idempotency-Key"])
    })

    it("A17 reads the quest once on Keep it and says the removal may have been applied; confirming again re-sends the same key", async () => {
        const { server, dialog } = await lostRemoval()
        const readsBefore = server.callsTo("GET", QUEST).length
        fireEvent.click(within(dialog).getByRole("button", { name: "Keep it" }))
        await waitFor(() => expect(server.callsTo("GET", QUEST)).toHaveLength(readsBefore + 1))
        const note = await screen.findByText("The removal may have been applied. The list shows the latest read.")
        expect(note).toHaveAttribute("role", "status")
        await settle()
        expect(server.callsTo("GET", QUEST)).toHaveLength(readsBefore + 1)

        fireEvent.click(await screen.findByRole("button", { name: "Remove objective Find the map" }))
        const again = await screen.findByRole("dialog", { name: "Remove this objective?" })
        fireEvent.click(within(again).getByRole("button", { name: "Remove objective" }))
        await waitFor(() => expect(server.callsTo("POST", O1_REMOVE)).toHaveLength(2))
        const [first, second] = server.callsTo("POST", O1_REMOVE)
        expect(second!.headers["Idempotency-Key"]).toBe(first!.headers["Idempotency-Key"])
        expect(second!.body).toEqual(first!.body)
    })
})

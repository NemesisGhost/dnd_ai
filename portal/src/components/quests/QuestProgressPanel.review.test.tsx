import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { QuestFinishReview } from "./QuestFinishReview"
import { RUNTIME, questProgress, questView, setupQuestWorkspace } from "../../test/questWorkspaceHarness"

afterEach(() => {
    vi.unstubAllGlobals()
})

// P15-C10-S02-T01: the confirmation for finishing a quest (complete, fail, abandon) shows what the
// action will change and what the quest only describes. Nothing here is applied by the action.

const redCompany = (overrides: object = {}) => ({
    party_id: "p1",
    party_name: "Red Company",
    status: "suspended",
    actions: ["complete", "fail", "abandon", "resume"],
    all_required_complete: false,
    objectives: [
        { quest_objective_id: "o1", name: "Find the map", stage_name: "Opening", requirement_level: "required", status: "completed", next_statuses: [] },
        { quest_objective_id: "o3", name: "Meet the guide", stage_name: "Opening", requirement_level: "optional", status: "active", next_statuses: [] },
    ],
    ...overrides,
})

function setup(progress: object = questProgress(), view: object = questView({ canon_status: "canon" })) {
    const ctx = setupQuestWorkspace({ section: "progress", view, progress })
    ctx.server.on("POST", new RegExp(`${RUNTIME}/`), {
        body: { quest_id: "q1", event_id: "e1", previous_status: "active", status: "x", changed: true },
    })
    return ctx
}

async function openFinish(action: "Complete" | "Fail" | "Abandon", who = "Everyone") {
    fireEvent.click(await screen.findByRole("button", { name: `${action} quest for ${who}` }))
    return screen.findByRole("dialog")
}

describe("Finishing a quest: what the confirmation shows", () => {
    it("B1 names the scope and its status for everyone", async () => {
        setup()
        const dialog = await openFinish("Complete")
        expect(within(dialog).getByText("For: Everyone")).toBeInTheDocument()
        expect(within(dialog).getByText("Now: Active")).toBeInTheDocument()
    })

    it("B2 names the party and that party's status, and keeps the scope it will act on", async () => {
        setup(questProgress({}, redCompany()))
        fireEvent.click(await screen.findByRole("button", { name: /Red Company/ }))
        const dialog = await openFinish("Complete", "Red Company")
        expect(within(dialog).getByText("For: Red Company")).toBeInTheDocument()
        expect(within(dialog).getByText("Now: Suspended")).toBeInTheDocument()
        // Choosing another scope behind the open dialog does not change what it will act on.
        fireEvent.click(screen.getByRole("button", { name: /^EveryoneActive$/ }))
        expect(within(dialog).getByText("For: Red Company")).toBeInTheDocument()
        expect(within(dialog).getByText("Now: Suspended")).toBeInTheDocument()
        expect(within(dialog).queryByText("For: Everyone")).toBeNull()
    })

    it("B3 lists the scope's objectives with statuses and says how many required ones are not complete", async () => {
        setup()
        const dialog = await openFinish("Complete")
        expect(within(dialog).getByText("Opening: Find the map — Completed")).toBeInTheDocument()
        expect(within(dialog).getByText("Opening: Reach the ruin — Not started")).toBeInTheDocument()
        expect(within(dialog).getByText("1 required objective is not complete.")).toBeInTheDocument()
    })

    it("B3 marks optional objectives and counts only required ones", async () => {
        setup(questProgress({}, redCompany()))
        fireEvent.click(await screen.findByRole("button", { name: /Red Company/ }))
        const dialog = await openFinish("Fail", "Red Company")
        expect(within(dialog).getByText("Opening: Meet the guide (optional) — Active")).toBeInTheDocument()
        expect(within(dialog).getByText("All required objectives are complete.")).toBeInTheDocument()
    })

    it("B3 says so when the scope has no objectives", async () => {
        setup(questProgress({ objectives: [] }))
        const dialog = await openFinish("Abandon")
        expect(within(dialog).getByText("This quest has no objectives.")).toBeInTheDocument()
    })

    it("B3 pluralises the count of required objectives that are not complete", async () => {
        const open = (id: string, name: string) => ({
            quest_objective_id: id,
            name,
            stage_name: "Opening",
            requirement_level: "required",
            status: "active",
            next_statuses: [],
        })
        setup(questProgress({ objectives: [open("o1", "Find the map"), open("o2", "Reach the ruin")] }))
        const dialog = await openFinish("Complete")
        expect(within(dialog).getByText("2 required objectives are not complete.")).toBeInTheDocument()
    })

    it("B4 lists each authored outcome with its kind and each reward with its kind", async () => {
        setup()
        const dialog = await openFinish("Complete")
        expect(within(dialog).getByText("Described in this quest")).toBeInTheDocument()
        expect(within(dialog).getByText("Village saved (Success)")).toBeInTheDocument()
        expect(within(dialog).getByText("Other: 50 gold")).toBeInTheDocument()
    })

    it("B5 states that only the status is recorded and no reward is given, with the verb of the action", async () => {
        setup()
        let dialog = await openFinish("Complete")
        expect(dialog).toHaveTextContent(
            "Completing records only the quest's status for Everyone. No outcome is chosen and no reward is given or recorded. Apply any reward yourself.",
        )
        fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }))
        dialog = await openFinish("Fail")
        expect(dialog).toHaveTextContent("Failing records only the quest's status for Everyone. No outcome is chosen")
        fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }))
        dialog = await openFinish("Abandon")
        expect(dialog).toHaveTextContent("Abandoning records only the quest's status for Everyone. No outcome is chosen")
    })

    it("B5 names the party in the statement", async () => {
        setup(questProgress({}, redCompany()))
        fireEvent.click(await screen.findByRole("button", { name: /Red Company/ }))
        const dialog = await openFinish("Abandon", "Red Company")
        expect(dialog).toHaveTextContent("Abandoning records only the quest's status for Red Company.")
    })

    it("B6 says so when the quest describes no outcomes", async () => {
        setup(questProgress(), questView({ canon_status: "canon", outcomes: [] }))
        const dialog = await openFinish("Complete")
        expect(within(dialog).getByText("This quest describes no outcomes or rewards.")).toBeInTheDocument()
        expect(within(dialog).queryByText("Described in this quest")).toBeNull()
    })

    it("B7 names the knowledge item of a knowledge reward", async () => {
        const outcomes = [
            {
                quest_outcome_id: "out1",
                code: "saved",
                name: "Village saved",
                description: null,
                outcome_category: "success",
                rewards: [
                    {
                        quest_reward_id: "r2",
                        reward_type: "knowledge",
                        description: "Learns the ritual",
                        knowledge: { entity_id: "k1", name: "The Old Ritual", canon_status: "canon", lifecycle_status: "active" },
                    },
                ],
            },
        ]
        setup(questProgress(), questView({ canon_status: "canon", outcomes }))
        const dialog = await openFinish("Complete")
        expect(within(dialog).getByText("Knowledge: Learns the ritual (The Old Ritual)")).toBeInTheDocument()
    })
})

describe("Finishing a quest: a view that cannot read the definition", () => {
    it("says outcomes and rewards are not shown, rather than that there are none", () => {
        render(
            <QuestFinishReview
                scope={questProgress().scopes[0] as never}
                action="complete"
                outcomes={null}
                labels={{ outcomeCategories: [], rewardTypes: [] }}
            />,
        )
        expect(screen.getByText(/does not show the quest's authored outcomes or rewards/)).toBeInTheDocument()
        expect(screen.queryByText("This quest describes no outcomes or rewards.")).toBeNull()
        expect(screen.getByText(/No outcome is chosen and no reward is given or recorded/)).toBeInTheDocument()
    })
})

describe("Finishing a quest: what must not change", () => {
    it("B8 opening the review sends no request", async () => {
        const { server } = setup()
        await screen.findByRole("button", { name: "Complete quest for Everyone" })
        const gets = server.callsTo("GET", /./).length
        const posts = server.callsTo("POST", /./).length
        await openFinish("Complete")
        expect(server.callsTo("GET", /./)).toHaveLength(gets)
        expect(server.callsTo("POST", /./)).toHaveLength(posts)
    })

    it("B9 Cancel sends nothing, and re-opening shows an empty note", async () => {
        const { server } = setup()
        let dialog = await openFinish("Complete")
        fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "Draft thought" } })
        fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }))
        expect(server.callsTo("POST", /./)).toHaveLength(0)
        dialog = await openFinish("Complete")
        expect(within(dialog).getByRole("textbox")).toHaveValue("")
    })

    it("B10 activate, suspend and resume still act at once, with no dialog", async () => {
        const { server } = setup(questProgress({ status: "suspended", actions: ["resume", "suspend", "activate"] }))
        for (const action of ["resume", "suspend", "activate"]) {
            const name = `${action[0]!.toUpperCase()}${action.slice(1)} quest for Everyone`
            fireEvent.click(await screen.findByRole("button", { name }))
            await waitFor(() => expect(server.callsTo("POST", `${RUNTIME}/${action}`)).toHaveLength(1))
            expect(screen.queryByRole("dialog")).toBeNull()
        }
    })

    it("B11 confirming sends the existing body, with the party and the status it saw", async () => {
        const { server } = setup(questProgress({}, redCompany()))
        fireEvent.click(await screen.findByRole("button", { name: /Red Company/ }))
        const dialog = await openFinish("Fail", "Red Company")
        fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: " Too late " } })
        fireEvent.click(within(dialog).getByRole("button", { name: "Fail quest" }))
        await waitFor(() => expect(server.callsTo("POST", `${RUNTIME}/fail`)).toHaveLength(1))
        expect(server.callsTo("POST", `${RUNTIME}/fail`)[0]!.body).toEqual({
            expected_status: "suspended",
            party_id: "p1",
            note: "Too late",
        })
    })

    it("B12 a draft quest offers no finishing command and no dialog", async () => {
        setupQuestWorkspace({
            section: "progress",
            view: questView({ canon_status: "draft" }),
            progress: questProgress(),
        })
        const card = await screen.findByRole("article", { name: "Progress for Everyone" })
        expect(within(card).queryByRole("button", { name: /Complete quest/ })).toBeNull()
        expect(screen.queryByRole("dialog")).toBeNull()
    })
})

import { fireEvent, screen, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import { QuestProgressPage } from "./QuestProgressPage"

const BASE = "/campaigns/c1/quests/q1"

const objective = (id: string, name: string, status: string | null, next: string[]) => ({
    quest_objective_id: id,
    name,
    stage_name: "Search",
    requirement_level: "required",
    status,
    next_statuses: next,
})

function progress(overrides: Record<string, unknown> = {}, party: object | null = null) {
    return {
        quest_id: "q1",
        name: "The Lost Amulet",
        published: true,
        scopes: [
            {
                party_id: null,
                party_name: null,
                status: "active",
                actions: ["complete", "fail", "suspend", "abandon"],
                all_required_complete: false,
                objectives: [
                    objective("o1", "Find the map", "completed", []),
                    objective("o2", "Reach the ruin", null, ["available", "active", "completed", "failed", "skipped"]),
                ],
                ...overrides,
            },
            ...(party === null ? [] : [party]),
        ],
    }
}

afterEach(() => {
    vi.unstubAllGlobals()
})

function setup(view: object = progress(), capabilities = ["canon.edit"]) {
    const server = installMockServer()
    server.on("GET", `${BASE}/progress`, () => ({ body: view }))
    server.on("POST", new RegExp(`${BASE}/`), {
        body: { quest_id: "q1", event_id: "e1", previous_status: "active", status: "x", changed: true },
    })
    server.on("POST", /objectives\/o2\/status/, {
        body: { quest_id: "q1", event_id: "e2", previous_status: null, status: "active", changed: true },
    })
    renderAuthoringRoutes({
        initialEntry: "/app/c1/quests/q1/progress",
        bootstrap: bootstrapWith({
            campaigns: [{ ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c1", capabilities }],
        }),
        routes: [{ path: "/app/:campaignId/quests/:questId/progress", element: <QuestProgressPage /> }],
    })
    return server
}

describe("QuestProgressPage", () => {
    it("shows the status, the actions that apply, and each objective", async () => {
        setup()
        const card = await screen.findByRole("article", { name: "Progress for Everyone" })
        expect(within(card).getByRole("heading", { name: /Everyone: Active/ })).toBeInTheDocument()
        expect(within(card).getByRole("button", { name: "Suspend quest for Everyone" })).toBeEnabled()
        expect(within(card).queryByRole("button", { name: /Activate quest/ })).not.toBeInTheDocument()
        expect(within(card).getByText(/Find the map — Completed/)).toBeInTheDocument()
        expect(within(card).getByRole("button", { name: "Skip Reach the ruin for Everyone" })).toBeInTheDocument()
    })

    it("suspends at once, naming the status it saw", async () => {
        const server = setup()
        fireEvent.click(await screen.findByRole("button", { name: "Suspend quest for Everyone" }))
        await vi.waitFor(() => expect(server.callsTo("POST", `${BASE}/suspend`)).toHaveLength(1))
        expect(server.callsTo("POST", `${BASE}/suspend`)[0]!.body).toEqual({
            expected_status: "active",
            party_id: null,
            note: null,
        })
    })

    it("asks for confirmation before finishing a quest, and sends the note", async () => {
        const server = setup()
        fireEvent.click(await screen.findByRole("button", { name: "Complete quest for Everyone" }))
        const dialog = await screen.findByRole("dialog")
        expect(server.callsTo("POST", `${BASE}/complete`)).toHaveLength(0)
        fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: " The twist " } })
        fireEvent.click(within(dialog).getByRole("button", { name: "Complete quest" }))
        await vi.waitFor(() => expect(server.callsTo("POST", `${BASE}/complete`)).toHaveLength(1))
        expect(server.callsTo("POST", `${BASE}/complete`)[0]!.body).toMatchObject({
            expected_status: "active",
            note: "The twist",
        })
    })

    it("cancelling the confirmation sends nothing", async () => {
        const server = setup()
        fireEvent.click(await screen.findByRole("button", { name: "Abandon quest for Everyone" }))
        const dialog = await screen.findByRole("dialog")
        fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }))
        expect(server.callsTo("POST", `${BASE}/abandon`)).toHaveLength(0)
    })

    it("moves an objective with the status it saw", async () => {
        const server = setup()
        fireEvent.click(await screen.findByRole("button", { name: "Start Reach the ruin for Everyone" }))
        await vi.waitFor(() => expect(server.callsTo("POST", /objectives\/o2\/status/)).toHaveLength(1))
        expect(server.callsTo("POST", /objectives\/o2\/status/)[0]!.body).toEqual({
            new_status: "active",
            expected_status: null,
            party_id: null,
        })
    })

    it("hints that all required objectives are complete without completing the quest", async () => {
        const server = setup(progress({ all_required_complete: true }))
        expect(await screen.findByText(/All required objectives are complete/)).toBeInTheDocument()
        expect(server.callsTo("POST", `${BASE}/complete`)).toHaveLength(0)
    })

    it("says when the quest is not published", async () => {
        setup({ ...progress(), published: false, scopes: [{ ...progress().scopes[0]!, actions: [] }] })
        expect(await screen.findByText(/not published/)).toBeInTheDocument()
    })

    it("lists each party's own progress", async () => {
        const server = setup(
            progress(
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
        const card = await screen.findByRole("article", { name: "Progress for Red Company" })
        fireEvent.click(within(card).getByRole("button", { name: "Activate quest for Red Company" }))
        await vi.waitFor(() => expect(server.callsTo("POST", `${BASE}/activate`)).toHaveLength(1))
        expect(server.callsTo("POST", `${BASE}/activate`)[0]!.body).toEqual({
            expected_status: null,
            party_id: "p1",
            note: null,
        })
    })

    it("explains a refused transition", async () => {
        const server = setup()
        server.on("POST", `${BASE}/suspend`, {
            status: 409,
            body: { error: { code: "quest_transition_invalid", message: "m", correlation_id: "c" } },
        })
        fireEvent.click(await screen.findByRole("button", { name: "Suspend quest for Everyone" }))
        expect(await screen.findByRole("alert")).toHaveTextContent(/not in a state that allows that/)
    })

    it("refuses people without canon.edit", async () => {
        setup(progress(), [])
        expect(await screen.findByRole("alert")).toHaveTextContent(/do not have permission/)
    })
})

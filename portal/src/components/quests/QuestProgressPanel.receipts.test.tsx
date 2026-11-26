import { act, fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../../test/authoringHarness"
import { RUNTIME, questProgress, questView, setupQuestWorkspace } from "../../test/questWorkspaceHarness"
import { sessionBootstrapFixture } from "../../fixtures/sessionBootstrap"
import { QuestProgressPanel } from "./QuestProgressPanel"

afterEach(() => {
    vi.unstubAllGlobals()
})

// P15-C10-S02-T02: receipts for confirmed quest status changes, the visit's history, unknown-outcome
// reconciliation, the departure guard, focus and announcement. Controlled responses, no fixed sleeps.

const UNKNOWN_LABEL = "a quest action whose result is not known"
const SERVER_ERROR = { status: 503, body: { error: { code: "service_unavailable", message: "m", correlation_id: "c" } } }

const redCompany = (overrides: object = {}) => ({
    party_id: "p1",
    party_name: "Red Company",
    status: "active",
    actions: ["suspend"],
    all_required_complete: false,
    objectives: [],
    ...overrides,
})

function setup(progress: object = questProgress(), extra: object = {}) {
    const ctx = setupQuestWorkspace({
        section: "progress",
        view: questView({ canon_status: "canon" }),
        progress,
        ...extra,
    })
    return ctx
}

type Ctx = ReturnType<typeof setup>

// The server confirms `action` as a move from `previous` to `status`, recorded as `event`.
function confirms(ctx: Ctx, action: string, previous: string | null, status: string, event = "e1") {
    ctx.server.on("POST", `${RUNTIME}/${action}`, {
        body: { quest_id: "q1", event_id: event, previous_status: previous, status, changed: true },
    })
}

// A gate on one route: the request is held until `release()`.
function gated(ctx: Ctx, action: string, previous: string | null, status: string, event = "e1") {
    let release: () => void = () => {}
    const gate = new Promise<void>((resolve) => (release = resolve))
    ctx.server.on("POST", `${RUNTIME}/${action}`, async () => {
        await gate
        return { body: { quest_id: "q1", event_id: event, previous_status: previous, status, changed: true } } as never
    })
    return () => release()
}

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

const receiptHeading = (name: string | RegExp) => screen.findByRole("heading", { name })

async function complete(who = "Everyone") {
    fireEvent.click(await screen.findByRole("button", { name: `Complete quest for ${who}` }))
    const dialog = await screen.findByRole("dialog")
    fireEvent.click(within(dialog).getByRole("button", { name: "Complete quest" }))
}

const progressReads = (ctx: Ctx) => ctx.server.callsTo("GET", `${RUNTIME}/progress`).length

describe("Quest status receipts", () => {
    it("C1 completing shows a receipt with the transition and a link to the recorded event", async () => {
        const ctx = setup()
        confirms(ctx, "complete", "active", "completed", "e1")
        await complete()
        const heading = await receiptHeading("Recorded: quest completed for Everyone")
        const receipt = heading.closest("article") as HTMLElement
        expect(within(receipt).getByText("Status: Active → Completed, recorded as an event.")).toBeInTheDocument()
        expect(within(receipt).getByRole("link", { name: "Open the recorded event" })).toHaveAttribute("href", "/app/c1/events/e1")
        expect(within(receipt).getByText("Progress shown: read again.")).toBeInTheDocument()
    })

    it("C2 moves focus to the receipt heading", async () => {
        const ctx = setup()
        confirms(ctx, "complete", "active", "completed")
        await complete()
        const heading = await receiptHeading("Recorded: quest completed for Everyone")
        await waitFor(() => expect(heading).toHaveFocus())
    })

    it("C3 announces the receipt heading once, for activate too", async () => {
        const ctx = setup(questProgress({ status: null, actions: ["activate"] }))
        confirms(ctx, "activate", null, "active")
        const heard = watchAnnouncements()
        fireEvent.click(await screen.findByRole("button", { name: "Activate quest for Everyone" }))
        await receiptHeading("Recorded: quest activated for Everyone")
        await settle()
        expect(heard.filter((h) => h === "Recorded: quest activated for Everyone")).toHaveLength(1)
        expect(heard.some((h) => h.includes(": done"))).toBe(false)
    })

    it("C4 names the scope that was confirmed, not the one selected when it settles", async () => {
        const ctx = setup(questProgress({}, redCompany()))
        const release = gated(ctx, "suspend", "active", "suspended")
        fireEvent.click(await screen.findByRole("button", { name: /Red Company/ }))
        fireEvent.click(await screen.findByRole("button", { name: "Suspend quest for Red Company" }))
        await waitFor(() => expect(ctx.server.callsTo("POST", `${RUNTIME}/suspend`)).toHaveLength(1))
        fireEvent.click(screen.getByRole("button", { name: /^EveryoneActive$/ }))
        await act(async () => release())
        expect(await receiptHeading("Recorded: quest suspended for Red Company")).toBeInTheDocument()
        expect(screen.queryByRole("heading", { name: /for Everyone/ })).toBeNull()
        expect(ctx.server.callsTo("POST", `${RUNTIME}/suspend`)[0]!.body).toMatchObject({ party_id: "p1" })
    })

    it("C5 a failed read-back says so, and Check progress only reads", async () => {
        const ctx = setup()
        confirms(ctx, "complete", "active", "completed")
        await screen.findByRole("article", { name: "Progress for Everyone" })
        ctx.server.on("GET", `${RUNTIME}/progress`, {
            status: 500,
            body: { error: { code: "internal_error", message: "m", correlation_id: "c" } },
        })
        await complete()
        const heading = await receiptHeading("Recorded: quest completed for Everyone")
        const receipt = heading.closest("article") as HTMLElement
        expect(within(receipt).getByText("Progress shown: could not be read again.")).toBeInTheDocument()
        expect(ctx.server.callsTo("POST", `${RUNTIME}/complete`)).toHaveLength(1)
        ctx.server.on("GET", `${RUNTIME}/progress`, { body: questProgress() })
        fireEvent.click(within(receipt).getByRole("button", { name: "Check progress" }))
        await waitFor(() => expect(within(receipt).getByText("Progress shown: read again.")).toBeInTheDocument())
        expect(ctx.server.callsTo("POST", `${RUNTIME}/complete`)).toHaveLength(1)
    })

    it("C6 says described rewards were not applied after a finishing action", async () => {
        const ctx = setup()
        confirms(ctx, "complete", "active", "completed")
        await complete()
        const done = (await receiptHeading("Recorded: quest completed for Everyone")).closest("article") as HTMLElement
        expect(within(done).getByText("Rewards described in this quest were not applied.")).toBeInTheDocument()
    })

    it("C6 does not say it after suspend", async () => {
        const ctx = setup()
        confirms(ctx, "suspend", "active", "suspended", "e2")
        fireEvent.click(await screen.findByRole("button", { name: "Suspend quest for Everyone" }))
        const suspended = (await receiptHeading("Recorded: quest suspended for Everyone")).closest("article") as HTMLElement
        expect(within(suspended).queryByText(/were not applied/)).toBeNull()
    })
})

describe("Quest status: a lost answer", () => {
    it("C7 Cancel after a lost answer says it may have been recorded, reads progress once, then states the status", async () => {
        const ctx = setup()
        ctx.server.on("POST", `${RUNTIME}/complete`, SERVER_ERROR)
        await complete()
        const dialog = await screen.findByRole("dialog")
        expect(await within(dialog).findByText(/cannot tell whether this was saved/)).toBeInTheDocument()
        const before = progressReads(ctx)
        fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }))
        expect(await screen.findByText(/may have been recorded/)).toHaveTextContent(
            "The request to complete the quest for Everyone may have been recorded.",
        )
        expect(await screen.findByText("Progress was read again: Everyone is Active.")).toBeInTheDocument()
        expect(progressReads(ctx)).toBe(before + 1)
        expect(screen.queryByRole("heading", { name: /Recorded:/ })).toBeNull()
    })

    it("C8 re-opening and confirming sends the same request under the same key", async () => {
        const ctx = setup()
        let calls = 0
        ctx.server.on("POST", `${RUNTIME}/complete`, () => {
            calls += 1
            return (calls === 1
                ? SERVER_ERROR
                : { body: { quest_id: "q1", event_id: "e1", previous_status: "active", status: "completed", changed: true } }) as never
        })
        await complete()
        const first503 = await screen.findByRole("dialog")
        await within(first503).findByText(/cannot tell whether this was saved/)
        fireEvent.click(within(first503).getByRole("button", { name: "Cancel" }))
        await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
        await complete()
        await waitFor(() => expect(ctx.server.callsTo("POST", `${RUNTIME}/complete`)).toHaveLength(2))
        const [first, second] = ctx.server.callsTo("POST", `${RUNTIME}/complete`)
        expect(second!.body).toEqual(first!.body)
        expect(second!.headers["Idempotency-Key"]).toBe(first!.headers["Idempotency-Key"])
    })

    it("C11 a lost answer on Suspend keeps the alert with Retry (existing behavior)", async () => {
        const ctx = setup()
        ctx.server.on("POST", `${RUNTIME}/suspend`, SERVER_ERROR)
        fireEvent.click(await screen.findByRole("button", { name: "Suspend quest for Everyone" }))
        expect(await screen.findByRole("button", { name: "Retry" })).toBeInTheDocument()
        expect(screen.getByRole("alert")).toHaveTextContent(/cannot tell whether this was saved/)
    })

    it("C11 a lost answer on Suspend adds the note and one progress read", async () => {
        const ctx = setup()
        await screen.findByRole("article", { name: "Progress for Everyone" })
        const before = progressReads(ctx)
        ctx.server.on("POST", `${RUNTIME}/suspend`, SERVER_ERROR)
        fireEvent.click(screen.getByRole("button", { name: "Suspend quest for Everyone" }))
        expect(await screen.findByRole("button", { name: "Retry" })).toBeInTheDocument()
        expect(await screen.findByText(/The request to suspend the quest for Everyone may have been recorded/)).toBeInTheDocument()
        await screen.findByText("Progress was read again: Everyone is Active.")
        expect(progressReads(ctx)).toBe(before + 1)
    })
})

describe("Quest status: leaving the page", () => {
    it("C9 the guard names a result that is not known, while pending and while unknown, and not after the re-read", async () => {
        const ctx = setup()
        await screen.findByRole("article", { name: "Progress for Everyone" })
        const release = gated(ctx, "suspend", "active", "suspended")
        fireEvent.click(screen.getByRole("button", { name: "Suspend quest for Everyone" }))
        await waitFor(() => expect(ctx.server.callsTo("POST", `${RUNTIME}/suspend`)).toHaveLength(1))
        void ctx.router.navigate("/app/c1/quests")
        let dialog = await screen.findByRole("dialog", { name: "Discard unsaved input?" })
        expect(dialog).toHaveTextContent(UNKNOWN_LABEL)
        fireEvent.click(within(dialog).getByRole("button", { name: "Keep editing" }))
        await act(async () => release())
        await receiptHeading("Recorded: quest suspended for Everyone")
        // Confirmed and read: nothing is unknown any more.
        await settle()
        expect(screen.queryByRole("dialog")).toBeNull()

        // A lost answer, with the re-read held back.
        ctx.server.on("POST", `${RUNTIME}/suspend`, SERVER_ERROR)
        let releaseRead: () => void = () => {}
        const readGate = new Promise<void>((resolve) => (releaseRead = resolve))
        ctx.server.on("GET", `${RUNTIME}/progress`, async () => {
            await readGate
            return { body: questProgress() } as never
        })
        fireEvent.click(await screen.findByRole("button", { name: "Suspend quest for Everyone" }))
        await screen.findByText(/may have been recorded/)
        void ctx.router.navigate("/app/c1/quests")
        dialog = await screen.findByRole("dialog", { name: "Discard unsaved input?" })
        expect(dialog).toHaveTextContent(UNKNOWN_LABEL)
        fireEvent.click(within(dialog).getByRole("button", { name: "Keep editing" }))
        await act(async () => releaseRead())
        await screen.findByText(/Progress was read again/)
        expect(ctx.router.state.location.pathname).toBe("/app/c1/quests/q1")
        await act(async () => {
            await ctx.router.navigate("/app/c1/quests")
        })
        expect(ctx.router.state.location.pathname).toBe("/app/c1/quests")
    })

    it("C10 opening Details while an action is pending: it confirms, focus stays out of the hidden section, the receipt is there on return", async () => {
        const ctx = setup()
        const release = gated(ctx, "suspend", "active", "suspended")
        fireEvent.click(await screen.findByRole("button", { name: "Suspend quest for Everyone" }))
        await waitFor(() => expect(ctx.server.callsTo("POST", `${RUNTIME}/suspend`)).toHaveLength(1))
        fireEvent.click(screen.getByRole("link", { name: /Prepare/ }))
        fireEvent.click(await screen.findByRole("link", { name: "Details" }))
        const detailsHeading = await screen.findByRole("heading", { name: "Details" })
        await waitFor(() => expect(detailsHeading).toHaveFocus())
        await act(async () => release())
        await waitFor(() => expect(document.body.textContent).toContain("Recorded: quest suspended for Everyone"))
        await settle()
        expect(detailsHeading).toHaveFocus()
        expect(document.activeElement?.closest("[hidden]")).toBeNull()
        fireEvent.click(screen.getByRole("link", { name: /Use in play/ }))
        expect(await receiptHeading("Recorded: quest suspended for Everyone")).toBeInTheDocument()
    })
})

describe("Quest status: history and guards", () => {
    it("C12 keeps this visit's receipts newest first, each with its own scope, and drops them on a remount", async () => {
        const ctx = setup(questProgress({}, redCompany()))
        confirms(ctx, "suspend", "active", "suspended", "e1")
        fireEvent.click(await screen.findByRole("button", { name: "Suspend quest for Everyone" }))
        await receiptHeading("Recorded: quest suspended for Everyone")
        confirms(ctx, "suspend", "active", "suspended", "e2")
        fireEvent.click(await screen.findByRole("button", { name: /Red Company/ }))
        fireEvent.click(await screen.findByRole("button", { name: "Suspend quest for Red Company" }))
        await receiptHeading("Recorded: quest suspended for Red Company")
        const headings = screen.getAllByRole("heading", { name: /Recorded:/ }).map((h) => h.textContent)
        expect(headings).toEqual(["Recorded: quest suspended for Red Company", "Recorded: quest suspended for Everyone"])
        const links = screen.getAllByRole("link", { name: "Open the recorded event" }).map((a) => a.getAttribute("href"))
        expect(links).toEqual(["/app/c1/events/e2", "/app/c1/events/e1"])
        // Another page and back: the history is not kept. (Wait for the request to settle: while it is
        // pending the page's guard rightly holds the visit.)
        await waitFor(() => expect(screen.getByRole("button", { name: "Suspend quest for Red Company" })).toBeEnabled())
        await act(async () => {
            await ctx.router.navigate("/app/c1/quests")
        })
        await screen.findByText("Quests list page")
        expect(screen.queryByRole("article", { name: /Progress for/ })).toBeNull()
        await act(async () => {
            await ctx.router.navigate("/app/c1/quests/q1?section=progress")
        })
        await screen.findByRole("article", { name: /Progress for/ })
        expect(screen.queryByRole("heading", { name: /Recorded:/ })).toBeNull()
    })

    it("C13 a stale write and a refused transition keep their notices and add no receipt", async () => {
        const ctx = setup()
        ctx.server.on("POST", `${RUNTIME}/suspend`, {
            status: 409,
            body: { error: { code: "quest_transition_invalid", message: "m", correlation_id: "c" } },
        })
        fireEvent.click(await screen.findByRole("button", { name: "Suspend quest for Everyone" }))
        expect(await screen.findByRole("alert")).toHaveTextContent(/not in a state that allows that/)
        expect(screen.queryByRole("heading", { name: /Recorded:/ })).toBeNull()

        ctx.server.on("POST", `${RUNTIME}/suspend`, {
            status: 409,
            body: { error: { code: "stale_write", message: "m", correlation_id: "c" } },
        })
        fireEvent.click(screen.getByRole("button", { name: "Suspend quest for Everyone" }))
        await waitFor(() => expect(ctx.server.callsTo("POST", `${RUNTIME}/suspend`)).toHaveLength(2))
        expect((await screen.findAllByText(/changed since|latest|reload/i)).length).toBeGreaterThan(0)
        expect(screen.queryByRole("heading", { name: /Recorded:/ })).toBeNull()
    })

    it("C14 the action and confirm buttons are disabled while a request is pending", async () => {
        const ctx = setup()
        const release = gated(ctx, "complete", "active", "completed")
        fireEvent.click(await screen.findByRole("button", { name: "Complete quest for Everyone" }))
        const dialog = await screen.findByRole("dialog")
        fireEvent.click(within(dialog).getByRole("button", { name: "Complete quest" }))
        await waitFor(() => expect(ctx.server.callsTo("POST", `${RUNTIME}/complete`)).toHaveLength(1))
        const working = within(dialog).getByRole("button", { name: "Working…" })
        expect(working).toBeDisabled()
        fireEvent.click(working)
        expect(screen.getByRole("button", { name: "Suspend quest for Everyone", hidden: true })).toBeDisabled()
        await act(async () => release())
        await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
        expect(ctx.server.callsTo("POST", `${RUNTIME}/complete`)).toHaveLength(1)
    })

    it("C15 an objective move keeps its announcement and adds no receipt", async () => {
        const ctx = setup()
        ctx.server.on("POST", /objectives\/o2\/status/, {
            body: { quest_id: "q1", event_id: "e3", previous_status: null, status: "active", changed: true },
        })
        const heard = watchAnnouncements()
        fireEvent.click(await screen.findByRole("button", { name: "Start Reach the ruin for Everyone" }))
        await waitFor(() => expect(heard).toContain("Objective active"))
        expect(screen.queryByRole("heading", { name: /Recorded:/ })).toBeNull()
    })
})

describe("Quest status receipts where the definition cannot be read", () => {
    it("shows the receipt without reading the definition, and does not claim there are no rewards", async () => {
        const server = installMockServer()
        server.on("GET", `${RUNTIME}/progress`, { body: questProgress() })
        server.on("POST", `${RUNTIME}/complete`, {
            body: { quest_id: "q1", event_id: "e9", previous_status: "active", status: "completed", changed: true },
        })
        renderAuthoringRoutes({
            initialEntry: "/app/c1/quests/q1",
            bootstrap: bootstrapWith({
                campaigns: [{ ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c1", capabilities: ["canon.edit"] }],
            }),
            routes: [
                {
                    path: "/app/:campaignId/quests/:questId",
                    element: (
                        <QuestProgressPanel
                            campaignId="c1"
                            questId="q1"
                            blockedText={null}
                            refreshToken={0}
                            onUnsaved={() => undefined}
                        />
                    ),
                },
            ],
        })
        await complete()
        const heading = await receiptHeading("Recorded: quest completed for Everyone")
        const receipt = heading.closest("article") as HTMLElement
        expect(within(receipt).getByText("Authored rewards, if any, were not applied.")).toBeInTheDocument()
        expect(within(receipt).getByRole("link", { name: "Open the recorded event" })).toHaveAttribute("href", "/app/c1/events/e9")
        expect(server.callsTo("GET", /authoring/)).toHaveLength(0)
    })
})

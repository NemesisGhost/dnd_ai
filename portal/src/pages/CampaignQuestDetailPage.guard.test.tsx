import { act, fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { CharacterPerspectiveContext } from "../context/CharacterPerspectiveContext"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import { RUNTIME, questProgress } from "../test/questWorkspaceHarness"
import { CampaignQuestDetailPage } from "./CampaignQuestDetailPage"

afterEach(() => {
    vi.unstubAllGlobals()
})

// C10-S02-1: the progress-only view (a campaign GM with `canon.edit` and no world private-read capability)
// shares the quest page's departure guard. Real route, real reader boundary, real progress panel; the
// workspace's authoring, lifecycle and revision reads must never be made.

// No character is selected: the reader is opened as the campaign's GM.
const PERSPECTIVE = { getSelectedCharacterId: () => null, selectCharacter: vi.fn() }
const SERVER_ERROR = { status: 503, body: { error: { code: "service_unavailable", message: "m", correlation_id: "c" } } }
const UNKNOWN_LABEL = "a quest action whose result is not known"
const QUEST = { quest_id: "q1", name: "The Lost Amulet", status_code: "active", stages: [] }

function setup() {
    const server = installMockServer()
    server.on("GET", /^\/campaigns\/c1\/quests\/q1(\?.*)?$/, { body: QUEST })
    server.on("GET", `${RUNTIME}/progress`, { body: questProgress() })
    server.on("POST", `${RUNTIME}/suspend`, {
        body: { quest_id: "q1", event_id: "e1", previous_status: "active", status: "suspended", changed: true },
    })
    const rendered = renderAuthoringRoutes({
        initialEntry: "/app/c1/quests/q1",
        bootstrap: bootstrapWith({
            campaigns: [
                {
                    ...sessionBootstrapFixture.campaigns[0]!,
                    campaign_id: "c1",
                    capabilities: ["canon.edit"],
                    world_capabilities: [],
                },
            ],
        }),
        routes: [
            {
                path: "/app/:campaignId/quests/:questId",
                element: (
                    <CharacterPerspectiveContext.Provider value={PERSPECTIVE}>
                        <CampaignQuestDetailPage />
                    </CharacterPerspectiveContext.Provider>
                ),
            },
            { path: "/app/:campaignId/quests", element: <p>Quests list page</p> },
        ],
    })
    return { server, ...rendered }
}

type Ctx = ReturnType<typeof setup>

const definitionReads = (ctx: Ctx) => ctx.server.calls.filter((c) => /authoring|lifecycle|revisions/.test(c.path))
const suspends = (ctx: Ctx) => ctx.server.callsTo("POST", `${RUNTIME}/suspend`)

function hold(ctx: Ctx, method: "GET" | "POST", path: string, answer: () => object) {
    let release: () => void = () => {}
    const gate = new Promise<void>((resolve) => (release = resolve))
    ctx.server.on(method, path, async () => {
        await gate
        return answer() as never
    })
    return () => release()
}

// Immediate departure through the page's own Quests breadcrumb, as a person would.
function leaveToQuests() {
    fireEvent.click(screen.getByRole("link", { name: "Quests" }))
}

const suspend = async () => fireEvent.click(await screen.findByRole("button", { name: "Suspend quest for Everyone" }))

const GUARD = { name: "Discard unsaved input?" }

describe("The progress-only quest view and the page's departure guard", () => {
    it("G0 asks nothing when nothing is pending", async () => {
        const ctx = setup()
        await screen.findByRole("article", { name: "Progress for Everyone" })
        leaveToQuests()
        expect(await screen.findByText("Quests list page")).toBeInTheDocument()
        expect(screen.queryByRole("dialog")).toBeNull()
        expect(definitionReads(ctx)).toHaveLength(0)
    })

    it("G1 holds departure while the status request is pending", async () => {
        const ctx = setup()
        const release = hold(ctx, "POST", `${RUNTIME}/suspend`, () => ({
            body: { quest_id: "q1", event_id: "e1", previous_status: "active", status: "suspended", changed: true },
        }))
        await suspend()
        await waitFor(() => expect(suspends(ctx)).toHaveLength(1))
        leaveToQuests()
        const dialog = await screen.findByRole("dialog", GUARD)
        expect(dialog).toHaveTextContent(UNKNOWN_LABEL)
        expect(ctx.router.state.location.pathname).toBe("/app/c1/quests/q1")
        expect(screen.queryByText("Quests list page")).toBeNull()
        await act(async () => release())
        expect(definitionReads(ctx)).toHaveLength(0)
    })

    it("G2 Stay keeps the pending context and sends no extra command", async () => {
        const ctx = setup()
        const release = hold(ctx, "POST", `${RUNTIME}/suspend`, () => ({
            body: { quest_id: "q1", event_id: "e1", previous_status: "active", status: "suspended", changed: true },
        }))
        await suspend()
        await waitFor(() => expect(suspends(ctx)).toHaveLength(1))
        leaveToQuests()
        fireEvent.click(within(await screen.findByRole("dialog", GUARD)).getByRole("button", { name: "Keep editing" }))
        expect(ctx.router.state.location.pathname).toBe("/app/c1/quests/q1")
        await act(async () => release())
        expect(await screen.findByRole("heading", { name: "Recorded: quest suspended for Everyone" })).toBeInTheDocument()
        expect(suspends(ctx)).toHaveLength(1)
        expect(definitionReads(ctx)).toHaveLength(0)
    })

    it("G3 a lost answer stays guarded while the progress read is held, and clears when it has been read, without claiming success", async () => {
        const ctx = setup()
        ctx.server.on("POST", `${RUNTIME}/suspend`, SERVER_ERROR)
        // Only the reconciliation read is held, not the page's first one.
        await screen.findByRole("article", { name: "Progress for Everyone" })
        const releaseRead = hold(ctx, "GET", `${RUNTIME}/progress`, () => ({ body: questProgress() }))
        await suspend()
        expect(await screen.findByText(/may have been recorded/)).toBeInTheDocument()
        leaveToQuests()
        const dialog = await screen.findByRole("dialog", GUARD)
        expect(dialog).toHaveTextContent(UNKNOWN_LABEL)
        fireEvent.click(within(dialog).getByRole("button", { name: "Keep editing" }))
        expect(ctx.router.state.location.pathname).toBe("/app/c1/quests/q1")
        await act(async () => releaseRead())
        expect(await screen.findByText("Progress was read again: Everyone is Active.")).toBeInTheDocument()
        // A matching status after a read does not prove the command worked, and the page does not say it did.
        expect(screen.queryByRole("heading", { name: /Recorded:/ })).toBeNull()
        expect(screen.getByText(/may have been recorded/)).toBeInTheDocument()
        leaveToQuests()
        expect(await screen.findByText("Quests list page")).toBeInTheDocument()
        expect(suspends(ctx)).toHaveLength(1)
        expect(definitionReads(ctx)).toHaveLength(0)
    })

    it("G4 a failed progress read keeps the protection", async () => {
        const ctx = setup()
        ctx.server.on("POST", `${RUNTIME}/suspend`, SERVER_ERROR)
        // The first read (page load) succeeds; the reconciliation read fails.
        let reads = 0
        ctx.server.on("GET", `${RUNTIME}/progress`, () => {
            reads += 1
            return (reads === 1
                ? { body: questProgress() }
                : { status: 500, body: { error: { code: "internal_error", message: "m", correlation_id: "c" } } }) as never
        })
        await suspend()
        expect(await screen.findByText("Progress could not be read again.")).toBeInTheDocument()
        leaveToQuests()
        const dialog = await screen.findByRole("dialog", GUARD)
        expect(dialog).toHaveTextContent(UNKNOWN_LABEL)
        fireEvent.click(within(dialog).getByRole("button", { name: "Keep editing" }))
        expect(ctx.router.state.location.pathname).toBe("/app/c1/quests/q1")
        expect(suspends(ctx)).toHaveLength(1)
        expect(definitionReads(ctx)).toHaveLength(0)
    })

    it("G5 Leave navigates deliberately and does not replay the command", async () => {
        const ctx = setup()
        const release = hold(ctx, "POST", `${RUNTIME}/suspend`, () => ({
            body: { quest_id: "q1", event_id: "e1", previous_status: "active", status: "suspended", changed: true },
        }))
        await suspend()
        await waitFor(() => expect(suspends(ctx)).toHaveLength(1))
        leaveToQuests()
        fireEvent.click(within(await screen.findByRole("dialog", GUARD)).getByRole("button", { name: "Discard" }))
        expect(await screen.findByText("Quests list page")).toBeInTheDocument()
        await act(async () => release())
        expect(suspends(ctx)).toHaveLength(1)
        expect(definitionReads(ctx)).toHaveLength(0)
    })
})

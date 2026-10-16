import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { CampaignQuestDetailPage } from "../../pages/CampaignQuestDetailPage"
import { QuestSectionRedirect } from "../../pages/QuestSectionRedirect"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../../test/authoringHarness"
import { AUTHORING, RUNTIME, questProgress, questView, setupQuestWorkspace } from "../../test/questWorkspaceHarness"
import { sessionBootstrapFixture } from "../../fixtures/sessionBootstrap"
import { useLocation } from "react-router"
import { CharacterPerspectiveContext } from "../../context/CharacterPerspectiveContext"

afterEach(() => {
    vi.unstubAllGlobals()
})

// The element with this text in the section on screen (every section stays mounted, so the same
// sentence can also sit, hidden, in another).
const shown = async (text: RegExp) => {
    const found = await screen.findAllByText(text)
    return found.find((element) => element.closest("[hidden]") === null) ?? found[0]!
}

const reader = new RegExp(`^${RUNTIME}(\\?.*)?$`)
const writes = (server: ReturnType<typeof setupQuestWorkspace>["server"]) =>
    server.calls.filter((c) => c.method !== "GET")

describe("Quest workspace: header and workflow", () => {
    it("shows the quest, its real lifecycle status, and a three-phase workflow without a progress status", async () => {
        setupQuestWorkspace({ section: "details", view: questView({ canon_status: "canon" }) })
        const heading = await screen.findByRole("heading", { level: 1, name: "The Lost Amulet" })
        await waitFor(() => expect(heading).toHaveFocus())
        expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1)
        const header = heading.closest("header")!
        expect(within(header).getByRole("group", { name: "Record status" })).toHaveTextContent("Canon")
        // Progress (Active) belongs to Use in play, never to the header.
        expect(within(header).queryByText(/Active/)).toBeNull()
        const workflow = screen.getByRole("navigation", { name: "Quest workflow" })
        const links = within(workflow).getAllByRole("link")
        expect(links.map((l) => l.textContent)).toEqual(["1. Prepare", "2. Review & publish", "3. Use in play"])
        expect(links[0]).toHaveAttribute("aria-current", "step")
        expect(workflow.textContent).not.toMatch(/stage|phase/i)
    })

    it("lists the sections of the current phase, and only those", async () => {
        setupQuestWorkspace({ section: "details" })
        const menu = await screen.findByRole("navigation", { name: "Prepare sections" })
        expect(within(menu).getAllByRole("link").map((l) => l.textContent)).toEqual([
            "Details",
            "Stages and objectives",
            "Dependencies",
            "Outcomes and rewards",
            "Participants",
            "Sources",
        ])
        expect(within(menu).getByRole("link", { name: "Details" })).toHaveAttribute("aria-current", "page")
    })

    it("keeps the quest's stages and objectives, which are the adventure, out of the workflow words", async () => {
        setupQuestWorkspace({ section: "structure" })
        expect(await screen.findByRole("heading", { level: 2, name: "Stages and objectives" })).toBeInTheDocument()
        expect(screen.getByRole("heading", { level: 3, name: /1\. Opening/ })).toBeInTheDocument()
    })
})

describe("Quest workspace: default and direct sections", () => {
    const opens = async (view: object, expected: string, lifecycle: Record<string, unknown> = {}) => {
        const ctx = setupQuestWorkspace({ section: null, view, lifecycle })
        await waitFor(() => expect(ctx.router.state.location.search).toBe(`?section=${expected}`))
        // A missing section is corrected in place, not pushed.
        expect(ctx.router.state.historyAction).toBe("REPLACE")
        return ctx
    }

    it("opens on the section where the next real step is done", async () => {
        await opens(questView({ canon_status: "draft" }), "details")
    })
    it("opens a quest in review on Review", async () => {
        await opens(questView({ canon_status: "proposed" }), "review")
    })
    it("opens a published quest on Progress", async () => {
        await opens(questView({ canon_status: "canon" }), "progress")
    })
    it("opens an archived quest on Publication", async () => {
        await opens(questView({ canon_status: "canon", lifecycle_status: "archived" }), "publication")
    })
    it("opens on Details when the lifecycle could not be read", async () => {
        const ctx = setupQuestWorkspace({ section: null, view: questView({ canon_status: "canon" }), lifecycleError: true })
        await waitFor(() => expect(ctx.router.state.location.search).toBe("?section=details"))
    })

    it("replaces an unknown section, and the preview section for someone who may not preview", async () => {
        const ctx = setupQuestWorkspace({ section: "preview" })
        await waitFor(() => expect(ctx.router.state.location.search).toBe("?section=details"))
        expect(ctx.router.state.historyAction).toBe("REPLACE")
    })

    it("opens a section directly, as given, and keeps every other parameter", async () => {
        const ctx = setupQuestWorkspace({ entry: "/app/c1/quests/q1?section=outcomes&character_id=c9&party_id=p9" })
        expect(await screen.findByRole("heading", { level: 2, name: "Outcomes and rewards" })).toBeVisible()
        fireEvent.click(screen.getByRole("link", { name: "Participants" }))
        expect(ctx.router.state.location.search).toBe("?section=participants&character_id=c9&party_id=p9")
        expect(ctx.router.state.historyAction).toBe("PUSH")
    })

    it("reopens each phase on the section last used in it", async () => {
        const ctx = setupQuestWorkspace({ section: "dependencies" })
        await screen.findByRole("heading", { level: 2, name: "Dependencies" })
        fireEvent.click(screen.getByRole("link", { name: /Review & publish/ }))
        expect(ctx.router.state.location.search).toBe("?section=review")
        fireEvent.click(screen.getByRole("link", { name: /Prepare/ }))
        expect(ctx.router.state.location.search).toBe("?section=dependencies")
    })

    it("moves focus to the section heading when the section changes", async () => {
        setupQuestWorkspace({ section: "details" })
        await screen.findByRole("heading", { level: 2, name: "Details" })
        fireEvent.click(screen.getByRole("link", { name: "Participants" }))
        await waitFor(() => expect(screen.getByRole("heading", { level: 2, name: "Participants" })).toHaveFocus())
    })
})

describe("Quest workspace: navigation changes nothing", () => {
    it("sends no write for any phase or section link, and keeps a half-typed draft", async () => {
        const { server } = setupQuestWorkspace({ section: "structure" })
        fireEvent.click(await screen.findByRole("button", { name: "Add stage" }))
        const panel = screen.getByRole("form", { name: "New stage" })
        fireEvent.change(within(panel).getByRole("textbox", { name: /Stage name/ }), { target: { value: "Half" } })
        fireEvent.click(screen.getByRole("link", { name: "Dependencies" }))
        fireEvent.click(screen.getByRole("link", { name: /Review & publish/ }))
        fireEvent.click(screen.getByRole("link", { name: "Publication" }))
        fireEvent.click(screen.getByRole("link", { name: /Use in play/ }))
        fireEvent.click(screen.getByRole("link", { name: /Prepare/ }))
        fireEvent.click(await screen.findByRole("link", { name: "Stages and objectives" }))
        expect(
            within(screen.getByRole("form", { name: "New stage" })).getByRole("textbox", { name: /Stage name/ }),
        ).toHaveValue("Half")
        expect(writes(server)).toHaveLength(0)
    })

    it("keeps typed details, notes and a source form across sections", async () => {
        const { server } = setupQuestWorkspace({ section: "details" })
        fireEvent.change(await screen.findByRole("textbox", { name: /^Name/ }), { target: { value: "Renamed" } })
        fireEvent.change(screen.getByRole("textbox", { name: /Planning notes/ }), { target: { value: "My note" } })
        fireEvent.click(screen.getByRole("link", { name: "Participants" }))
        fireEvent.click(screen.getByRole("link", { name: "Details" }))
        expect(screen.getByRole("textbox", { name: /^Name/ })).toHaveValue("Renamed")
        expect(screen.getByRole("textbox", { name: /Planning notes/ })).toHaveValue("My note")
        expect(writes(server)).toHaveLength(0)
    })

    it("reads progress only once Use in play has been opened", async () => {
        const { server } = setupQuestWorkspace({ section: "details", view: questView({ canon_status: "canon" }) })
        await screen.findByRole("heading", { level: 2, name: "Details" })
        expect(server.callsTo("GET", `${RUNTIME}/progress`)).toHaveLength(0)
        fireEvent.click(screen.getByRole("link", { name: /Use in play/ }))
        await screen.findByRole("article", { name: "Progress for Everyone" })
        expect(server.callsTo("GET", `${RUNTIME}/progress`)).toHaveLength(1)
        // Leaving and coming back does not read it again or remount it.
        fireEvent.click(screen.getByRole("link", { name: /Prepare/ }))
        fireEvent.click(screen.getByRole("link", { name: /Use in play/ }))
        expect(server.callsTo("GET", `${RUNTIME}/progress`)).toHaveLength(1)
    })

    it("asks before leaving the page with unsent input, naming it, but not for a section change", async () => {
        const { router } = setupQuestWorkspace({ section: "details" })
        fireEvent.change(await screen.findByRole("textbox", { name: /^Name/ }), { target: { value: "Renamed" } })
        fireEvent.click(screen.getByRole("link", { name: "Participants" }))
        expect(screen.queryByRole("dialog")).toBeNull()
        void router.navigate("/app/c1/quests")
        const dialog = await screen.findByRole("dialog", { name: "Discard unsaved input?" })
        expect(dialog).toHaveTextContent("quest details")
        fireEvent.click(within(dialog).getByRole("button", { name: "Keep editing" }))
        expect(router.state.location.pathname).toBe("/app/c1/quests/q1")
    })
})

describe("Quest workspace: Next", () => {
    it("asks a draft with nothing to publish for stages and objectives", async () => {
        setupQuestWorkspace({ section: "details", view: questView({ stages: [] }) })
        const next = await screen.findByRole("link", { name: /Add stages and objectives/ })
        expect(next).toHaveAttribute("href", "/app/c1/quests/q1?section=structure")
    })

    it("leads a draft with objectives to submit it, a published quest to run it", async () => {
        setupQuestWorkspace({ section: "details", lifecycle: { available_actions: ["submit_for_review"] } })
        expect(await screen.findByRole("link", { name: /Submit for review/ })).toHaveAttribute("href", "/app/c1/quests/q1?section=review")
    })

    it("leads a published quest to Progress, in the words of the phase it opens", async () => {
        setupQuestWorkspace({ section: "details", view: questView({ canon_status: "canon" }) })
        const next = await screen.findByRole("link", { name: /Use it in play/ })
        expect(next).toHaveAttribute("href", "/app/c1/quests/q1?section=progress")
        // The link is named for the phase button it leads into.
        expect(screen.getByRole("link", { name: /3\. Use in play/ })).toBeInTheDocument()
    })

    it("offers no Next when the server offers no step", async () => {
        setupQuestWorkspace({ section: "details", view: questView({ canon_status: "proposed", available_actions: [] }) })
        await screen.findByRole("heading", { level: 1, name: "The Lost Amulet" })
        expect(screen.queryByText(/^Next:/)).toBeNull()
    })

    it("leads a replaced quest to its replacement", async () => {
        setupQuestWorkspace({
            section: "publication",
            view: questView({ canon_status: "superseded", available_actions: [] }),
            lifecycle: { superseded_by: { entity_id: "q2", canonical_name: "The Better Quest" } },
        })
        expect(await screen.findByRole("link", { name: /Replaced by The Better Quest/ })).toHaveAttribute(
            "href",
            "/app/c1/quests/q2",
        )
    })
})

describe("Quest workspace: Review and Publication", () => {
    it("shows the saved structure and the decision only when the server offers it", async () => {
        setupQuestWorkspace({
            section: "review",
            view: questView({ canon_status: "proposed", available_actions: [] }),
            lifecycle: { available_actions: ["approve", "reject"] },
        })
        expect(await screen.findByText("1 stage")).toBeInTheDocument()
        expect(screen.getByText("2 objectives, 2 required")).toBeInTheDocument()
        expect(screen.getByText("1 dependency, 1 outcome, 1 participant")).toBeInTheDocument()
        expect(await screen.findByRole("button", { name: "Approve" })).toBeInTheDocument()
    })

    it("offers no decision when none is available", async () => {
        setupQuestWorkspace({ section: "review", view: questView({ canon_status: "proposed", available_actions: [] }) })
        await screen.findByText("1 stage")
        expect(screen.queryByRole("button", { name: "Approve" })).toBeNull()
        expect(screen.queryByRole("button", { name: /Publish/ })).toBeNull()
    })

    it("explains the one blocker of an approved quest with nothing to play", async () => {
        setupQuestWorkspace({
            section: "review",
            view: questView({ canon_status: "approved", stages: [], available_actions: [] }),
            lifecycle: { blocked_actions: [{ action: "publish", reason: "quest_definition_incomplete" }] },
        })
        expect(await shown(/needs at least one stage with an objective/)).toBeInTheDocument()
        expect(screen.getByText("None yet. A quest needs a stage with an objective before it can be published.")).toBeInTheDocument()
    })

    it("does not say a published quest is visible to players, because tracking decides that", async () => {
        setupQuestWorkspace({ section: "publication", view: questView({ canon_status: "canon" }) })
        expect(await shown(/Players see it only once it is activated/)).toBeInTheDocument()
        expect(screen.queryByText(/Players can see it wherever their access allows/)).toBeNull()
    })

    it("links to the revision history, which leads back to the quest", async () => {
        setupQuestWorkspace({ section: "publication" })
        expect(await screen.findByRole("link", { name: "Revision history and comparison" })).toHaveAttribute(
            "href",
            "/app/c1/world/record/q1/history",
        )
    })

    it("says so when the lifecycle could not be read, and offers no step", async () => {
        setupQuestWorkspace({ section: "publication", lifecycleError: true })
        expect(await screen.findByText(/lifecycle could not be loaded, so no step is shown/)).toBeInTheDocument()
        expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument()
        const header = screen.getByRole("heading", { level: 1 }).closest("header")!
        expect(within(header).queryByRole("group", { name: "Record status" })).toBeNull()
    })

    it("submits for review without any other write first", async () => {
        const { server } = setupQuestWorkspace({
            section: "publication",
            lifecycle: { available_actions: ["submit_for_review"] },
        })
        expect(writes(server)).toHaveLength(0)
        server.on("POST", /\/entities\/q1\/submit_for_review$/, { status: 200, body: { entity_id: "q1" } })
        fireEvent.click(await screen.findByRole("button", { name: /Submit for review/ }))
        await waitFor(() => expect(writes(server).length).toBeGreaterThan(0))
    })
})

describe("Quest workspace: read-only and eligibility", () => {
    it("states why a quest in review cannot be edited and links to Publication", async () => {
        setupQuestWorkspace({
            section: "details",
            view: questView({ canon_status: "proposed", available_actions: [], blocked_actions: [{ action: "update", reason: "review_in_progress" }] }),
        })
        const note = await screen.findByRole("note")
        expect(note).toHaveTextContent("This quest is in review. Return it to draft to edit it.")
        expect(within(note).getByRole("link", { name: "See Publication" })).toHaveAttribute("href", "/app/c1/quests/q1?section=publication")
        expect(screen.queryByRole("textbox", { name: /^Name/ })).toBeNull()
        expect(screen.getByText("Remember the twist.")).toBeInTheDocument()
    })

    it("says an archived quest must be restored, and a replaced one cannot be edited", async () => {
        setupQuestWorkspace({
            section: "details",
            view: questView({ canon_status: "canon", lifecycle_status: "archived", available_actions: [] }),
        })
        expect(await screen.findByRole("note")).toHaveTextContent("This quest is archived. Restore it to edit it.")
    })

    it("withholds Progress commands for a quest that is not published, however the progress read looks", async () => {
        setupQuestWorkspace({
            section: "progress",
            view: questView({ canon_status: "approved", available_actions: [] }),
            progress: questProgress({ actions: ["activate"], status: null }),
        })
        expect(await screen.findByText(/not published yet/)).toBeInTheDocument()
        expect(screen.queryByRole("button", { name: /Activate quest/ })).toBeNull()
    })
})

describe("Quest workspace: member preview", () => {
    it("is a section of Use in play only for someone who may preview a member", async () => {
        setupQuestWorkspace({ section: "progress", view: questView({ canon_status: "canon" }), capabilities: ["canon.edit", "access.manage"] })
        const menu = await screen.findByRole("navigation", { name: "Use in play sections" })
        expect(within(menu).getAllByRole("link").map((l) => l.textContent)).toEqual(["Progress", "Member preview"])
    })

    it("is absent otherwise, and Use in play has no section menu", async () => {
        setupQuestWorkspace({ section: "progress", view: questView({ canon_status: "canon" }) })
        await screen.findByRole("article", { name: "Progress for Everyone" })
        expect(screen.queryByRole("link", { name: "Member preview" })).toBeNull()
        expect(screen.queryByRole("navigation", { name: "Use in play sections" })).toBeNull()
    })
})

describe("Quest workspace: where the quest was opened from", () => {
    it("returns to the Quests list with the perspective, for a direct link", async () => {
        setupQuestWorkspace({ entry: "/app/c1/quests/q1?section=details&character_id=c9&party_id=p9" })
        expect(await screen.findByRole("link", { name: "Back to Quests" })).toHaveAttribute(
            "href",
            "/app/c1/quests?character_id=c9&party_id=p9",
        )
    })

    it("returns to the Review queue as it was left, and carries that through every link", async () => {
        const ctx = setupQuestWorkspace({
            entry: { pathname: "/app/c1/quests/q1", search: "?section=review", state: { reviewSearch: "?status=proposed" } },
        })
        expect(await screen.findByRole("link", { name: "Back to Review queue" })).toHaveAttribute(
            "href",
            "/app/c1/review?status=proposed",
        )
        expect(screen.queryByRole("link", { name: "Back to Quests" })).toBeNull()
        fireEvent.click(screen.getByRole("link", { name: "Publication" }))
        expect(ctx.router.state.location.state).toEqual({ reviewSearch: "?status=proposed" })
        fireEvent.click(screen.getByRole("link", { name: /Use in play/ }))
        expect(ctx.router.state.location.state).toEqual({ reviewSearch: "?status=proposed" })
    })

    it("ignores a crafted return address", async () => {
        setupQuestWorkspace({
            entry: { pathname: "/app/c1/quests/q1", search: "?section=review", state: { reviewSearch: "//evil.example" } },
        })
        expect(await screen.findByRole("link", { name: "Back to Quests" })).toBeInTheDocument()
    })
})

describe("Quest workspace: loading and failure", () => {
    it("fails closed, without a form, for a quest that does not exist or is not accessible", async () => {
        const server = installMockServer()
        server.on("GET", `${AUTHORING}/q1`, { status: 404 })
        server.on("GET", `${AUTHORING}/options`, { body: { can_create: true } })
        server.on("GET", /\/entities\/q1\/lifecycle$/, { status: 404 })
        server.on("GET", /\/entities\/q1\/revisions$/, { status: 404 })
        renderAuthoringRoutes({
            initialEntry: "/app/c1/quests/q1",
            bootstrap: bootstrapWith({
                campaigns: [{ ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c1", capabilities: ["canon.edit"] }],
            }),
            routes: [{ path: "/app/:campaignId/quests/:questId", element: <CampaignQuestDetailPage /> }],
        })
        expect(await screen.findByRole("alert")).toHaveTextContent("This quest does not exist, or you do not have access to it.")
        expect(screen.getByRole("heading", { level: 1, name: "Quest unavailable" })).toBeInTheDocument()
        expect(screen.queryByRole("navigation", { name: "Quest workflow" })).toBeNull()
    })

    it("keeps the quest and what was typed when a refresh fails, and says it may be out of date", async () => {
        const { server } = setupQuestWorkspace({ section: "details" })
        fireEvent.change(await screen.findByRole("textbox", { name: /^Name/ }), { target: { value: "Renamed" } })
        server.on("GET", `${AUTHORING}/q1`, {
            status: 500,
            body: { error: { code: "internal_error", message: "m", correlation_id: "c" } },
        })
        // Another section saves, which reads the quest again and fails.
        fireEvent.change(screen.getByRole("textbox", { name: /Planning notes/ }), { target: { value: "n" } })
        fireEvent.click(screen.getByRole("button", { name: "Save notes" }))
        expect(await screen.findByText(/may be out of date/)).toBeInTheDocument()
        expect(screen.getByRole("textbox", { name: /^Name/ })).toHaveValue("Renamed")
        expect(screen.getByRole("heading", { level: 1, name: "The Lost Amulet" })).toBeInTheDocument()
    })
})

// A player has a perspective provider but no selected character.
function AsPlayer() {
    return (
        <CharacterPerspectiveContext.Provider value={{ getSelectedCharacterId: () => null, selectCharacter: vi.fn() }}>
            <CampaignQuestDetailPage />
        </CharacterPerspectiveContext.Provider>
    )
}

describe("Quest workspace: players", () => {
    it("gives a player the reader, and sends no authoring, lifecycle, revisions or progress request", async () => {
        const server = installMockServer()
        server.on("GET", reader, {
            body: {
                quest_id: "q1",
                name: "The Lost Amulet",
                status_code: "active",
                stages: [
                    {
                        quest_stage_id: "s1",
                        name: "Opening",
                        description: null,
                        sequence_number: 1,
                        stage_type: "sequential",
                        objectives: [],
                    },
                ],
            },
        })
        renderAuthoringRoutes({
            initialEntry: "/app/c1/quests/q1?section=progress",
            bootstrap: bootstrapWith({
                campaigns: [{ ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c1", capabilities: ["campaign.view"] }],
            }),
            routes: [{ path: "/app/:campaignId/quests/:questId", element: <AsPlayer /> }],
        })
        expect(await screen.findByRole("heading", { level: 1, name: "The Lost Amulet" })).toBeInTheDocument()
        expect(screen.queryByRole("navigation", { name: "Quest workflow" })).toBeNull()
        // The corrected empty state: one message, in an expanded stage with no visible objectives.
        const toggle = screen.getByRole("button", { name: /Opening/ })
        fireEvent.click(toggle)
        const body = document.getElementById(toggle.getAttribute("aria-controls")!)!
        expect(within(body).getAllByText(/No objectives/)).toHaveLength(1)
        expect(body).toHaveTextContent("No objectives are shown for this stage.")
        expect(server.calls.every((c) => reader.test(c.path))).toBe(true)
        expect(server.calls.some((c) => /authoring|lifecycle|revisions|progress|provenance|sources/.test(c.path))).toBe(false)
    })

    it("does not rewrite a section a player put in the address", async () => {
        const server = installMockServer()
        server.on("GET", reader, { body: { quest_id: "q1", name: "The Lost Amulet", status_code: null, stages: [] } })
        const ctx = renderAuthoringRoutes({
            initialEntry: "/app/c1/quests/q1?section=progress",
            bootstrap: bootstrapWith({
                campaigns: [{ ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c1", capabilities: ["campaign.view"] }],
            }),
            routes: [{ path: "/app/:campaignId/quests/:questId", element: <AsPlayer /> }],
        })
        await screen.findByRole("heading", { level: 1, name: "The Lost Amulet" })
        expect(ctx.router.state.location.search).toBe("?section=progress")
    })
})

describe("Quest workspace: an untracked draft", () => {
    it("opens without the reader's tracked-detail request", async () => {
        const { server } = setupQuestWorkspace({ section: "details" })
        await screen.findByRole("heading", { level: 1, name: "The Lost Amulet" })
        expect(server.calls.some((c) => reader.test(c.path))).toBe(false)
    })
})

describe("QuestSectionRedirect", () => {
    function Probe() {
        const location = useLocation()
        return (
            <p>
                at {location.pathname}
                {location.search} state {JSON.stringify(location.state)}
            </p>
        )
    }

    it.each([
        ["edit", "details"],
        ["progress", "progress"],
    ] as const)("sends /%s to the %s section, replacing history and keeping the query and the state", async (suffix, section) => {
        const ctx = renderAuthoringRoutes({
            initialEntry: {
                pathname: `/app/c1/quests/q1/${suffix}`,
                search: "?character_id=c9&party_id=p9",
                state: { reviewSearch: "?status=proposed" },
            },
            routes: [
                { path: "/app/:campaignId/quests/:questId/edit", element: <QuestSectionRedirect section="details" /> },
                { path: "/app/:campaignId/quests/:questId/progress", element: <QuestSectionRedirect section="progress" /> },
                { path: "/app/:campaignId/quests/:questId", element: <Probe /> },
            ],
        })
        expect(
            await screen.findByText(
                `at /app/c1/quests/q1?character_id=c9&party_id=p9&section=${section} state {"reviewSearch":"?status=proposed"}`,
            ),
        ).toBeInTheDocument()
        expect(ctx.router.state.historyAction).toBe("REPLACE")
    })
})

describe("Quest workspace: the provenance round trip", () => {
    const sources = "?section=sources&character_id=c9&party_id=p9"

    it("returns to Sources with the perspective, and to the Review queue the quest was opened from", async () => {
        const ctx = setupQuestWorkspace({
            entry: { pathname: "/app/c1/quests/q1", search: sources, state: { reviewSearch: "?status=proposed&type=quest" } },
        })
        expect(await screen.findByRole("link", { name: "Back to Review queue" })).toHaveAttribute(
            "href",
            "/app/c1/review?status=proposed&type=quest",
        )
        fireEvent.click(await screen.findByRole("link", { name: "View provenance" }))
        expect(await screen.findByRole("heading", { level: 1, name: "Provenance" })).toBeInTheDocument()
        fireEvent.click(screen.getByRole("link", { name: "The Lost Amulet" }))
        await screen.findByRole("navigation", { name: "Quest workflow" })
        expect(ctx.router.state.location.pathname).toBe("/app/c1/quests/q1")
        expect(ctx.router.state.location.search).toBe(sources)
        // Sources is the section shown, and the way back to the filtered queue survived the round trip.
        expect(screen.getByRole("heading", { level: 2, name: "Sources" })).toBeVisible()
        expect(screen.getByRole("link", { name: "Back to Review queue" })).toHaveAttribute(
            "href",
            "/app/c1/review?status=proposed&type=quest",
        )
        expect(screen.queryByRole("link", { name: "Back to Quests" })).toBeNull()
    })

    it("carries the queue through the history link too", async () => {
        const ctx = setupQuestWorkspace({
            entry: { pathname: "/app/c1/quests/q1", search: sources, state: { reviewSearch: "?status=proposed" } },
        })
        fireEvent.click(await screen.findByRole("link", { name: "View provenance" }))
        fireEvent.click(await screen.findByRole("link", { name: "Revision history and comparison" }))
        await waitFor(() => expect(ctx.router.state.location.pathname).toBe("/app/c1/world/record/q1/history"))
        expect(ctx.router.state.location.state).toMatchObject({ reviewSearch: "?status=proposed" })
    })

    it("opened directly, still returns to Quests, and ignores a crafted queue address", async () => {
        const ctx = setupQuestWorkspace({
            entry: { pathname: "/app/c1/quests/q1", search: sources, state: { reviewSearch: "//evil.example" } },
        })
        fireEvent.click(await screen.findByRole("link", { name: "View provenance" }))
        fireEvent.click(await screen.findByRole("link", { name: "The Lost Amulet" }))
        expect(await screen.findByRole("link", { name: "Back to Quests" })).toBeInTheDocument()
        expect(ctx.router.state.location.state ?? {}).not.toHaveProperty("reviewSearch")
    })
})

import { screen, waitFor, within } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { installCampaignShellMocks, openApp } from "./test/campaignRoutes"
import type { MockServer } from "./test/authoringHarness"
import { questProgress } from "./test/questWorkspaceHarness"
import {
    CAMPAIGN_ONLY_RECORD_AUTHORING,
    EDITOR_RECORD_AUTHORING,
    FULL_RECORD_AUTHORING,
    NO_WORLD_CAPABILITIES,
    REVIEWER_RECORD_AUTHORING,
} from "./test/recordAuthoring"

vi.mock("./hooks/useSessionBootstrap", () => ({ useSessionBootstrap: vi.fn() }))
vi.mock("./api/userPreferences", () => ({
    recordLastVisitedCampaign: vi.fn(() => Promise.resolve()),
}))

// Scoped roles on the current workspaces (ADR 0020, CP-4d): a campaign GM with no world role runs
// the game and reads the published record, and is sent no request for the shared definition's
// private side; a world Editor or Reviewer gets the preparation or review sections their role
// allows. Every case reads the server's per-record `authoring`, never a role name.

const CLAIM = "/app/mundivita/knowledge/k1"
const DETAIL = /^\/campaigns\/mundivita\/knowledge\/k1(\?.*)?$/
const AUDIENCE = "/campaigns/mundivita/knowledge/k1/audience"
const PRIVATE = /\/authoring\/knowledge|\/entities\/k1\/(lifecycle|provenance|revisions)|\/campaigns\/mundivita\/sources/

const claim = (authoring: object) => ({
    authoring,
    knowledge_item_id: "k1",
    knowledge_type_code: "secret",
    statement: "The duke is a vampire.",
    truth_status_code: "true",
    sensitivity: "secret",
    awareness_level: null,
    confidence: null,
    willing_to_share: null,
    subject: null,
})

const audience = {
    knowledge_item_id: "k1",
    awareness_levels: ["aware"],
    transfer_methods: ["dialogue"],
    parties: [],
    knowers: [],
    public: [],
}

const lifecycle = {
    entity_id: "k1",
    entity_type_code: "knowledge_item",
    canonical_name: "x",
    canon_status: "canon",
    lifecycle_status: "active",
    row_version: 2,
    lifecycle_managed: true,
    superseded_by: null,
    available_actions: ["archive"],
    blocked_actions: [],
}

let server: MockServer

beforeEach(() => {
    server = installCampaignShellMocks()
    server.on("GET", AUDIENCE, { body: audience })
    server.on("GET", /\/campaigns\/mundivita\/parties/, { body: { can_create: true, items: [] } })
})

afterEach(() => {
    vi.unstubAllGlobals()
})

const privateRequests = () => server.calls.map((c) => c.path).filter((p) => PRIVATE.test(p))

describe("Knowledge claim: runtime GM without a world role", () => {
    it("shows the claim and the whole of play, and requests nothing of the definition's private side", async () => {
        server.on("GET", DETAIL, { body: claim(CAMPAIGN_ONLY_RECORD_AUTHORING) })
        openApp(CLAIM, ["canon.edit"], { world_capabilities: [...NO_WORLD_CAPABILITIES] })

        expect(await screen.findByRole("heading", { level: 1, name: "The duke is a vampire." })).toBeInTheDocument()
        // Play is the landing section: who knows the claim is recorded separately from its definition.
        expect(await screen.findByRole("heading", { level: 2, name: "Who knows this" })).toBeVisible()
        await waitFor(() => expect(server.calls.some((c) => c.path === AUDIENCE)).toBe(true))

        // Preparation, review and publication stay in the structure as text, never as links.
        const stages = screen.getByRole("navigation", { name: "Claim stages" })
        expect(within(stages).getByRole("link", { name: "1. Prepare" })).toBeInTheDocument()
        expect(within(stages).getByRole("link", { name: "3. Use in play" })).toBeInTheDocument()
        expect(within(stages).queryByRole("link", { name: /Review & publish/ })).toBeNull()
        expect(within(stages).getByText(/Review & publish/)).toHaveAttribute("aria-disabled", "true")
        const prepare = screen.getByRole("link", { name: "1. Prepare" })
        expect(prepare).toBeInTheDocument()

        expect(privateRequests()).toEqual([])
    })

    it("falls back to a usable section when the address names a withheld one", async () => {
        server.on("GET", DETAIL, { body: claim(CAMPAIGN_ONLY_RECORD_AUTHORING) })
        const { router } = openApp(`${CLAIM}?section=sources`, ["canon.edit"], {
            world_capabilities: [...NO_WORLD_CAPABILITIES],
        })
        await screen.findByRole("heading", { level: 1, name: "The duke is a vampire." })
        await waitFor(() => expect(router.state.location.search).toContain("section=who-knows"))
        expect(privateRequests()).toEqual([])
    })
})

describe("Knowledge claim: world roles", () => {
    function withPrivate() {
        server.on("GET", "/campaigns/mundivita/authoring/knowledge/k1", {
            body: {
                knowledge_item_id: "k1",
                statement: "The duke is a vampire.",
                knowledge_type: "secret",
                truth_status: "true",
                sensitivity: "secret",
                subject: null,
                in_use: false,
                canon_status: "canon",
                lifecycle_status: "active",
                row_version: 1,
                available_actions: ["update"],
                blocked_actions: [],
                field_locks: [],
            },
        })
        server.on("GET", "/campaigns/mundivita/authoring/knowledge/options", {
            body: {
                can_create: true,
                knowledge_types: [{ value: "secret", label: "Secret" }],
                truth_statuses: [{ value: "true", label: "True" }],
                sensitivities: [{ value: "secret", label: "Secret" }],
                limits: { statement_max_length: 4000, change_note_max_length: 1000 },
            },
        })
        server.on("GET", "/campaigns/mundivita/entities/k1/lifecycle", { body: lifecycle })
        server.on("GET", "/campaigns/mundivita/entities/k1/provenance", { status: 404 })
        server.on("GET", "/campaigns/mundivita/sources", { body: { items: [], source_types: [], limits: {} } })
    }

    it.each([
        ["Editor", EDITOR_RECORD_AUTHORING],
        ["Reviewer", REVIEWER_RECORD_AUTHORING],
        ["Owner", FULL_RECORD_AUTHORING],
    ])("reads the private side and lists every stage for a world %s", async (_label, authoring) => {
        withPrivate()
        server.on("GET", DETAIL, { body: claim(authoring) })
        openApp(CLAIM, ["canon.edit"])
        const stages = await screen.findByRole("navigation", { name: "Claim stages" })
        await waitFor(() => expect(within(stages).getByRole("link", { name: "2. Review & publish" })).toBeInTheDocument())
        expect(privateRequests().some((p) => p.includes("/authoring/knowledge/k1"))).toBe(true)
        expect(privateRequests().some((p) => p.includes("/lifecycle"))).toBe(true)
    })
})

describe("Quest page: runtime GM without a world role", () => {
    const quest = {
        authoring: CAMPAIGN_ONLY_RECORD_AUTHORING,
        quest_id: "q1",
        name: "The Lost Amulet",
        status_code: "active",
        stages: [],
    }

    it("shows the published quest and runs its progress, and sends no authoring request", async () => {
        server.on("GET", /^\/campaigns\/mundivita\/quests\/q1(\?.*)?$/, { body: quest })
        server.on("GET", "/campaigns/mundivita/quests/q1/progress", { body: questProgress() })
        openApp("/app/mundivita/quests/q1", ["canon.edit"], { world_capabilities: [...NO_WORLD_CAPABILITIES] })

        const card = await screen.findByRole("article", { name: "Progress for Everyone" })
        expect(within(card).getByRole("button", { name: "Suspend quest for Everyone" })).toBeEnabled()
        expect(screen.getByText(/belong to the shared world and need a world role/)).toBeInTheDocument()
        const paths = server.calls.map((c) => c.path)
        expect(paths.some((p) => /\/authoring\//.test(p))).toBe(false)
        expect(paths.some((p) => /\/lifecycle|\/revisions|\/provenance/.test(p))).toBe(false)
    })
})

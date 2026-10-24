import { fireEvent, screen, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import { NpcPortrayalPage } from "./NpcPortrayalPage"

const PATH = "/campaigns/c1/authoring/npcs/n1/portrayal"

const LABELS = [
    { name: "voice", label: "Voice" },
    { name: "speech_style", label: "Speech style" },
    { name: "roleplay_guidance", label: "Roleplay guidance" },
]

function view(overrides: object = {}) {
    return {
        npc_id: "n1",
        name: "Mira",
        detail_level: "standard",
        detail_levels: [
            { value: "minimal", label: "Minimal" },
            { value: "standard", label: "Standard" },
            { value: "major", label: "Major" },
        ],
        row_version: 3,
        canon_status: "draft",
        lifecycle_status: "active",
        current_version: 2,
        shown_version: 2,
        fields: { voice: "Low and gravelly", speech_style: null, roleplay_guidance: "Stays calm" },
        field_labels: LABELS,
        limits: { field_max_length: 4000, note_max_length: 1000 },
        versions: [
            { version_number: 2, created_at: "2026-01-02T00:00:00Z", change_note: "Calmer" },
            { version_number: 1, created_at: "2026-01-01T00:00:00Z", change_note: null },
        ],
        can_edit: true,
        ...overrides,
    }
}

afterEach(() => {
    vi.unstubAllGlobals()
})

function setup(current: object = view(), capabilities = ["canon.edit"]) {
    const server = installMockServer()
    server.on("GET", PATH, () => ({ body: current }))
    server.on("GET", `${PATH}?version=1`, {
        body: view({ shown_version: 1, fields: { voice: "Soft", speech_style: null, roleplay_guidance: null } }),
    })
    server.on("POST", PATH, { body: { ...view({ current_version: 3 }), changed: true } })
    server.on("POST", /detail-level$/, { body: { ...view({ detail_level: "major" }), changed: true } })
    renderAuthoringRoutes({
        initialEntry: "/app/c1/characters/n1/portrayal",
        bootstrap: bootstrapWith({
            campaigns: [{ ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c1", capabilities }],
        }),
        routes: [{ path: "/app/:campaignId/characters/:characterId/portrayal", element: <NpcPortrayalPage /> }],
    })
    return server
}

describe("NpcPortrayalPage", () => {
    it("shows the current profile and the history", async () => {
        setup()
        expect(await screen.findByRole("textbox", { name: /Voice/ })).toHaveValue("Low and gravelly")
        expect(screen.getByText(/Version 2, .*: Calmer/)).toBeInTheDocument()
        expect(screen.getByText(/not shown to players and is not used by the AI/)).toBeInTheDocument()
    })

    it("saves a new version against the version it saw", async () => {
        const server = setup()
        const form = await screen.findByRole("form", { name: "Portrayal profile" })
        fireEvent.change(within(form).getByRole("textbox", { name: /Voice/ }), { target: { value: "  Softer  " } })
        fireEvent.change(within(form).getByRole("textbox", { name: /Change note/ }), { target: { value: "Edit" } })
        fireEvent.click(within(form).getByRole("button", { name: "Save new version" }))
        await vi.waitFor(() => expect(server.callsTo("POST", PATH)).toHaveLength(1))
        expect(server.callsTo("POST", PATH)[0]!.body).toEqual({
            expected_version: 2,
            voice: "Softer",
            speech_style: null,
            roleplay_guidance: "Stays calm",
            change_note: "Edit",
        })
    })

    it("shows an older version and offers it as a starting point", async () => {
        setup()
        fireEvent.click(await screen.findByRole("button", { name: "Show version 1" }))
        const panel = await screen.findByRole("region", { name: "Version 1" })
        expect(within(panel).getByText("Soft")).toBeInTheDocument()
        fireEvent.click(within(panel).getByRole("button", { name: /Use version 1 as the starting point/ }))
        expect(screen.getByRole("textbox", { name: /Voice/ })).toHaveValue("Soft")
    })

    it("changes the detail level with the NPC version", async () => {
        const server = setup()
        const form = await screen.findByRole("form", { name: "Detail level" })
        fireEvent.change(within(form).getByRole("combobox", { name: /Detail level/ }), { target: { value: "major" } })
        fireEvent.click(within(form).getByRole("button", { name: "Save detail level" }))
        await vi.waitFor(() => expect(server.callsTo("POST", /detail-level$/)).toHaveLength(1))
        expect(server.callsTo("POST", /detail-level$/)[0]!.body).toEqual({
            expected_row_version: 3,
            detail_level: "major",
        })
    })

    it("explains a stale save", async () => {
        const server = setup()
        server.on("POST", PATH, {
            status: 409,
            body: { error: { code: "stale_write", message: "m", correlation_id: "c" } },
        })
        const form = await screen.findByRole("form", { name: "Portrayal profile" })
        fireEvent.change(within(form).getByRole("textbox", { name: /Voice/ }), { target: { value: "Changed" } })
        fireEvent.click(within(form).getByRole("button", { name: "Save new version" }))
        expect(await screen.findByText(/Load latest version/i)).toBeInTheDocument()
    })

    it("cannot be edited when the NPC is locked, and is closed to everyone else", async () => {
        setup(view({ can_edit: false }))
        expect(await screen.findByText(/cannot be edited right now/)).toBeInTheDocument()
        expect(screen.queryByRole("form", { name: "Portrayal profile" })).not.toBeInTheDocument()
    })

    it("refuses people without canon.edit", async () => {
        setup(view(), [])
        expect(await screen.findByRole("alert")).toHaveTextContent(/do not have permission/)
    })
})

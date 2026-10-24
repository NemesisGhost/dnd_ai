import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../../fixtures/sessionBootstrap"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../../test/authoringHarness"
import {
    CAMPAIGN_ONLY_RECORD_AUTHORING,
    NO_WORLD_CAPABILITIES,
    ORIGINATED_RECORD_AUTHORING,
    OWNER_WORLD_CAPABILITIES,
    REVIEWER_RECORD_AUTHORING,
} from "../../test/recordAuthoring"
import { installRecordReads } from "../../test/worldWorkspaceMocks"
import { CampaignWorldDetailPage } from "../../pages/CampaignWorldDetailPage"
import type { RecordAuthoring } from "../../utils/recordAuthoring"

// The World record workspace under scoped roles (ADR 0020, CP-4d). The server's per-record
// `authoring` and the campaign's world-capability snapshot decide which sections exist for the
// caller; a section that is not theirs is listed as text, never mounted, and never requested.

const C = "c1"
const NOT_FOUND = { status: 404, body: { error: { code: "not_found", message: "m", correlation_id: "x" } } }
const PRIVATE = /\/lifecycle|\/provenance|\/revisions|\/sources|\/authoring\//

const organization = (authoring: RecordAuthoring) => ({
    authoring,
    organization_id: "o1",
    name: "The Guild",
    summary: "Merchants.",
    kind_code: "business",
    organization_type_code: "guild",
    status_code: null,
    public_description: null,
    parent: null,
    headquarters: null,
    religion: null,
    canon_status: "canon",
    lifecycle_status: "active",
    superseded_by: null,
})

const lifecycle = (entityTypeCode: string, entityId: string) => ({
    entity_id: entityId,
    entity_type_code: entityTypeCode,
    canonical_name: "x",
    canon_status: "canon",
    lifecycle_status: "active",
    row_version: 3,
    lifecycle_managed: true,
    superseded_by: null,
    available_actions: ["archive"],
    blocked_actions: [],
})

const roster = (over: object) => ({
    organization_id: "o1",
    status: null,
    can_edit: false,
    can_set_status: true,
    as_of: null,
    status_choices: [{ value: "dormant", label: "Dormant" }],
    members: [],
    authoring: CAMPAIGN_ONLY_RECORD_AUTHORING,
    ...over,
})

function setup(options: {
    authoring: RecordAuthoring
    worldCapabilities: readonly string[]
    category?: "organization" | "character"
    entityId?: string
    detail?: object
    typeCode?: string
}) {
    const category = options.category ?? "organization"
    const entityId = options.entityId ?? "o1"
    const server = installMockServer()
    server.on("GET", /.*/, NOT_FOUND)
    installRecordReads(server, { campaignId: C, entityId, entityTypeCode: options.typeCode ?? "organization", canon: "canon" })
    if (category === "organization") {
        server.on("GET", `/campaigns/${C}/world/organizations/o1`, {
            body: options.detail ?? organization(options.authoring),
        })
        server.on("GET", `/campaigns/${C}/organizations/o1/members`, {
            body: roster({ authoring: options.authoring }),
        })
    } else {
        server.on("GET", `/campaigns/${C}/characters/${entityId}`, { body: options.detail })
        server.on("GET", `/campaigns/${C}/characters/${entityId}/inventory`, { body: [] })
    }
    server.on("GET", `/campaigns/${C}/entities/${entityId}/lifecycle`, {
        body: lifecycle(options.typeCode ?? "organization", entityId),
    })
    server.on("GET", `/campaigns/${C}/authoring/player-characters/${entityId}`, {
        body: { canon_status: "canon", available_actions: ["update"], blocked_actions: [] },
    })
    const rendered = renderAuthoringRoutes({
        initialEntry: `/app/${C}/world/${category}/${entityId}`,
        bootstrap: bootstrapWith({
            campaigns: [
                {
                    ...sessionBootstrapFixture.campaigns[0]!,
                    campaign_id: C,
                    capabilities: ["canon.edit", "campaign.view"],
                    world_capabilities: [...options.worldCapabilities],
                },
            ],
        }),
        routes: [{ path: "/app/:campaignId/world/:category/:entityId", element: <CampaignWorldDetailPage /> }],
    })
    return { server, ...rendered }
}

const privateRequests = (server: ReturnType<typeof installMockServer>) =>
    server.calls.map((c) => c.path).filter((p) => PRIVATE.test(p))

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("World record workspace: a campaign GM with no world role", () => {
    it("reads the published record and runs it, and requests nothing of the private side", async () => {
        const { server } = setup({ authoring: CAMPAIGN_ONLY_RECORD_AUTHORING, worldCapabilities: NO_WORLD_CAPABILITIES })
        await screen.findByRole("heading", { level: 1, name: "The Guild" })
        const stages = screen.getByRole("navigation", { name: "Record stages" })
        expect(within(stages).getByRole("link", { name: "1. Prepare" })).toBeInTheDocument()
        // The structure is stable: the stage is listed, as text with its reason, not as a link.
        expect(within(stages).queryByRole("link", { name: /Review & publish/ })).toBeNull()
        expect(within(stages).getByText(/Review & publish/)).toHaveAttribute("aria-disabled", "true")
        expect(within(stages).getByRole("link", { name: "3. Use in play" })).toBeInTheDocument()
        // The details section carries the explanation instead of an edit link.
        expect(await screen.findByText(/Editing shared world content requires the world Editor role/)).toBeInTheDocument()
        expect(screen.queryByRole("link", { name: /^Edit / })).toBeNull()
        expect(privateRequests(server)).toEqual([])
    })

    it("keeps the operational status and withholds member changes in Use in play", async () => {
        const { server } = setup({ authoring: CAMPAIGN_ONLY_RECORD_AUTHORING, worldCapabilities: NO_WORLD_CAPABILITIES })
        await screen.findByRole("heading", { level: 1, name: "The Guild" })
        fireEvent.click(screen.getByRole("link", { name: "3. Use in play" }))
        expect(await screen.findByRole("button", { name: "Set status" })).toBeInTheDocument()
        expect(screen.queryByRole("button", { name: /Add a member|Add member/ })).toBeNull()
        expect(privateRequests(server)).toEqual([])
    })

    it("lists the preparation sections of the first stage as text, not links", async () => {
        setup({ authoring: CAMPAIGN_ONLY_RECORD_AUTHORING, worldCapabilities: NO_WORLD_CAPABILITIES })
        await screen.findByRole("heading", { level: 1, name: "The Guild" })
        const sections = screen.getByRole("navigation", { name: "Prepare sections" })
        expect(within(sections).getByRole("link", { name: "Details" })).toBeInTheDocument()
        expect(within(sections).queryByRole("link", { name: "Sources" })).toBeNull()
        expect(within(sections).queryByRole("link", { name: "Relationships" })).toBeNull()
        expect(within(sections).getByText(/Sources/)).toHaveAttribute("aria-disabled", "true")
    })

    it("falls back to the details when the address names a withheld section", async () => {
        const { router } = setup({ authoring: CAMPAIGN_ONLY_RECORD_AUTHORING, worldCapabilities: NO_WORLD_CAPABILITIES })
        await router.navigate(`/app/${C}/world/organization/o1?section=sources`)
        await screen.findByRole("heading", { level: 1, name: "The Guild" })
        await waitFor(() => expect(router.state.location.search).toBe("?section=details"))
    })
})

describe("World record workspace: a Reviewer", () => {
    it("reads the private side and is offered review but not editing", async () => {
        const { server } = setup({ authoring: REVIEWER_RECORD_AUTHORING, worldCapabilities: OWNER_WORLD_CAPABILITIES })
        await screen.findByRole("heading", { level: 1, name: "The Guild" })
        const stages = await screen.findByRole("navigation", { name: "Record stages" })
        await waitFor(() => expect(within(stages).getByRole("link", { name: "2. Review & publish" })).toBeInTheDocument())
        expect(privateRequests(server).some((p) => p.endsWith("/lifecycle"))).toBe(true)
        expect(screen.queryByRole("link", { name: /^Edit / })).toBeNull()
    })
})

describe("World record workspace: a campaign-originated record (player character)", () => {
    const pc = {
        authoring: ORIGINATED_RECORD_AUTHORING,
        character_id: "p1",
        character_kind: "player_character",
        name: "Hero",
        species_code: "human",
        size_category: "medium",
        current_hit_points: null,
        maximum_hit_points: null,
        temporary_hit_points: null,
        exhaustion_level: null,
        death_save_successes: null,
        death_save_failures: null,
        current_location_id: null,
        active_encounter_id: null,
        conditions: null,
        resources: null,
    }

    it("is the campaign's whole: edit, review and the Player section, with the world's preparation withheld", async () => {
        const { server } = setup({
            authoring: ORIGINATED_RECORD_AUTHORING,
            worldCapabilities: NO_WORLD_CAPABILITIES,
            category: "character",
            entityId: "p1",
            detail: pc,
            typeCode: "player_character",
        })
        await screen.findByRole("heading", { level: 1, name: "Hero" })
        expect(await screen.findByRole("link", { name: "Edit player character" })).toBeInTheDocument()
        const stages = await screen.findByRole("navigation", { name: "Record stages" })
        await waitFor(() => expect(within(stages).getByRole("link", { name: "2. Review & publish" })).toBeInTheDocument())
        // Sources and relationships are shared world canon whatever they relate: still withheld.
        const sections = screen.getByRole("navigation", { name: "Prepare sections" })
        expect(within(sections).queryByRole("link", { name: "Sources" })).toBeNull()
        expect(within(sections).queryByRole("link", { name: "Relationships" })).toBeNull()
        // The record's lifecycle is read (campaign-originated); the world's revisions and
        // provenance are not.
        const paths = privateRequests(server)
        expect(paths.some((p) => p.endsWith("/lifecycle"))).toBe(true)
        expect(paths.some((p) => /provenance|revisions|\/sources/.test(p))).toBe(false)
    })
})

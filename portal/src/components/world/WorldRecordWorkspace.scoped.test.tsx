import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../../fixtures/sessionBootstrap"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../../test/authoringHarness"
import {
    CAMPAIGN_ONLY_RECORD_AUTHORING,
    EDITOR_RECORD_AUTHORING,
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
    extra?: (server: ReturnType<typeof installMockServer>) => void
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
    options.extra?.(server)
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

describe("World record workspace: sources for a Reviewer", () => {
    it("lists where the record came from and offers no way to change it", async () => {
        setup({
            authoring: REVIEWER_RECORD_AUTHORING,
            worldCapabilities: OWNER_WORLD_CAPABILITIES,
            extra: (server) =>
                server.on("GET", `/campaigns/${C}/entities/o1/provenance`, {
                    body: {
                        entity_id: "o1",
                        name: "The Guild",
                        entity_type_code: "organization",
                        canon_status: "canon",
                        lifecycle_status: "active",
                        created_at: "2026-01-01T10:00:00Z",
                        created_by_name: "Gina",
                        can_edit: false,
                        origin: null,
                        links: [],
                        transitions: [],
                        superseded_by: null,
                        supersedes: [],
                    },
                }),
        })
        await screen.findByRole("heading", { level: 1, name: "The Guild" })
        fireEvent.click(await screen.findByRole("link", { name: "Sources" }))
        expect(await screen.findByText(/needs the world Editor role/)).toBeInTheDocument()
        expect(screen.queryByRole("button", { name: /Add source/ })).toBeNull()
        expect(screen.queryByRole("button", { name: /^Detach / })).toBeNull()
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

// D-8 (CP-4 smoke): the character routes asked for the world's private side of records the caller was
// only allowed to use. The private reads are the NPC authoring view (the portrayal link and the Run
// panel's old status read), a record's revisions and the world's sources.
const NPC_PRIVATE = /\/authoring\/npcs\//
const REFUSED = {
    status: 403,
    body: { error: { code: "world_authority_required", message: "m", correlation_id: "x" } },
}
const npc = (over: object = {}) => ({
    authoring: CAMPAIGN_ONLY_RECORD_AUTHORING,
    character_id: "n1",
    character_kind: "npc",
    name: "Mira",
    canon_status: "canon",
    lifecycle_status: "active",
    species_code: "human",
    size_category: "medium",
    current_hit_points: 12,
    maximum_hit_points: 20,
    temporary_hit_points: null,
    exhaustion_level: null,
    death_save_successes: null,
    death_save_failures: null,
    current_location_id: null,
    active_encounter_id: null,
    conditions: [],
    resources: [],
    ...over,
})
const npcExtra = (server: ReturnType<typeof installMockServer>) => {
    server.on("GET", /\/authoring\/npcs\/n1/, REFUSED)
    server.on("GET", /npc-runtime-options/, { body: { conditions: [], resources: [] } })
    server.on("GET", /world-times/, { body: { items: [], next_cursor: null } })
    server.on("GET", /calendars/, { body: { calendars: [] } })
    server.on("GET", `/campaigns/${C}/authoring/characters/n1/builds`, REFUSED)
}
const npcPrivateCalls = (server: ReturnType<typeof installMockServer>) =>
    server.calls.map((c) => c.path).filter((p) => NPC_PRIVATE.test(p))
const worldPrivateCalls = (server: ReturnType<typeof installMockServer>) =>
    server.calls.map((c) => c.path).filter((p) => /\/revisions|\/provenance|\/sources/.test(p))

describe("World record workspace: an NPC for a campaign GM with no world role (D-8)", () => {
    it("runs a published NPC: the controls are there and the world's private side is never requested", async () => {
        const { server } = setup({
            authoring: CAMPAIGN_ONLY_RECORD_AUTHORING,
            worldCapabilities: NO_WORLD_CAPABILITIES,
            category: "character",
            entityId: "n1",
            detail: npc(),
            typeCode: "npc",
            extra: npcExtra,
        })
        await screen.findByRole("heading", { level: 1, name: "Mira" })
        fireEvent.click(screen.getByRole("link", { name: "3. Use in play" }))
        fireEvent.click(await screen.findByRole("link", { name: "Run this NPC" }))
        expect(await screen.findByRole("form", { name: "Adjust hit points" })).toBeInTheDocument()
        expect(screen.queryByText(/could not be loaded/)).toBeNull()
        expect(npcPrivateCalls(server)).toEqual([])
        expect(worldPrivateCalls(server)).toEqual([])
        expect(server.calls.map((c) => c.path).filter((p) => /\/lifecycle$/.test(p))).toEqual([])
        // No portrayal link: how an NPC is played is the world's preparation.
        expect(screen.queryByRole("link", { name: "How this NPC is played" })).toBeNull()
    })

    it("explains an unpublished NPC from the status the character read carries, with no controls", async () => {
        const { server } = setup({
            authoring: CAMPAIGN_ONLY_RECORD_AUTHORING,
            worldCapabilities: NO_WORLD_CAPABILITIES,
            category: "character",
            entityId: "n1",
            detail: npc({ canon_status: "draft" }),
            typeCode: "npc",
            extra: npcExtra,
        })
        await screen.findByRole("heading", { level: 1, name: "Mira" })
        fireEvent.click(screen.getByRole("link", { name: "3. Use in play" }))
        fireEvent.click(await screen.findByRole("link", { name: "Run this NPC" }))
        expect(await screen.findByText(/not published yet/)).toBeInTheDocument()
        expect(screen.queryByRole("form", { name: "Adjust hit points" })).toBeNull()
        expect(npcPrivateCalls(server)).toEqual([])
    })
})

describe("World record workspace: a world Editor or Reviewer on an NPC keeps their own access (D-8)", () => {
    const readable = (actions: string[]) => ({
        body: {
            npc_id: "n1",
            canon_status: "canon",
            lifecycle_status: "active",
            row_version: 1,
            available_actions: actions,
            blocked_actions: [],
        },
    })

    it("offers an Editor the portrayal link and the Edit link, read through the NPC authoring view", async () => {
        const { server } = setup({
            authoring: EDITOR_RECORD_AUTHORING,
            worldCapabilities: ["world.view", "world.canon.read", "world.canon.read_private", "world.canon.edit"],
            category: "character",
            entityId: "n1",
            detail: npc({ authoring: EDITOR_RECORD_AUTHORING }),
            typeCode: "npc",
            extra: (srv) => {
                npcExtra(srv)
                srv.on("GET", /\/authoring\/npcs\/n1/, readable(["update"]))
            },
        })
        await screen.findByRole("heading", { level: 1, name: "Mira" })
        expect(await screen.findByRole("link", { name: "How this NPC is played" })).toBeInTheDocument()
        expect(await screen.findByRole("link", { name: "Edit NPC" })).toBeInTheDocument()
        expect(npcPrivateCalls(server).length).toBeGreaterThan(0)
    })

    it("offers a Reviewer the record's review stage and no Edit link", async () => {
        setup({
            authoring: REVIEWER_RECORD_AUTHORING,
            worldCapabilities: OWNER_WORLD_CAPABILITIES,
            category: "character",
            entityId: "n1",
            detail: npc({ authoring: REVIEWER_RECORD_AUTHORING }),
            typeCode: "npc",
            extra: (srv) => {
                npcExtra(srv)
                srv.on("GET", /\/authoring\/npcs\/n1/, readable([]))
            },
        })
        await screen.findByRole("heading", { level: 1, name: "Mira" })
        const stages = await screen.findByRole("navigation", { name: "Record stages" })
        await waitFor(() => expect(within(stages).getByRole("link", { name: "2. Review & publish" })).toBeInTheDocument())
        expect(screen.queryByRole("link", { name: "Edit NPC" })).toBeNull()
    })
})

describe("World record workspace: a player character a campaign GM created (D-8)", () => {
    const pc = {
        authoring: ORIGINATED_RECORD_AUTHORING,
        character_id: "p1",
        character_kind: "player_character",
        name: "Hero",
        canon_status: "draft",
        lifecycle_status: "active",
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

    it("never asks the NPC authoring route about a player character, and says revision history is the world's", async () => {
        const { server } = setup({
            authoring: ORIGINATED_RECORD_AUTHORING,
            worldCapabilities: NO_WORLD_CAPABILITIES,
            category: "character",
            entityId: "p1",
            detail: pc,
            typeCode: "player_character",
            extra: (srv) => srv.on("GET", /\/authoring\/npcs\//, REFUSED),
        })
        await screen.findByRole("heading", { level: 1, name: "Hero" })
        expect(await screen.findByRole("link", { name: "Edit player character" })).toBeInTheDocument()
        fireEvent.click(await screen.findByRole("link", { name: "2. Review & publish" }))
        expect(await screen.findByText(/revision history is part of the world's preparation/)).toBeInTheDocument()
        expect(screen.queryByText(/could not be loaded/)).toBeNull()
        expect(npcPrivateCalls(server)).toEqual([])
        expect(worldPrivateCalls(server)).toEqual([])
    })
})

describe("World record workspace: a plain member and a record the caller may not see (D-8)", () => {
    const authoringOrLifecycle = /\/authoring\/|\/lifecycle|\/revisions|\/sources/

    it("sends no authoring request and shows no workspace for a member without canon.edit", async () => {
        const server = installMockServer()
        server.on("GET", /.*/, NOT_FOUND)
        server.on("GET", `/campaigns/${C}/characters/n1`, { body: npc() })
        renderAuthoringRoutes({
            initialEntry: `/app/${C}/world/character/n1`,
            bootstrap: bootstrapWith({
                campaigns: [
                    {
                        ...sessionBootstrapFixture.campaigns[0]!,
                        campaign_id: C,
                        capabilities: ["campaign.view"],
                        world_capabilities: [],
                    },
                ],
            }),
            routes: [{ path: "/app/:campaignId/world/:category/:entityId", element: <CampaignWorldDetailPage /> }],
        })
        await new Promise((resolve) => setTimeout(resolve, 100))
        expect(server.calls.map((c) => c.path).filter((p) => authoringOrLifecycle.test(p))).toEqual([])
    })

    it("a foreign or denied record is unavailable and requests nothing private", async () => {
        const server = installMockServer()
        server.on("GET", /.*/, NOT_FOUND)
        renderAuthoringRoutes({
            initialEntry: `/app/${C}/world/character/zz`,
            bootstrap: bootstrapWith({
                campaigns: [
                    {
                        ...sessionBootstrapFixture.campaigns[0]!,
                        campaign_id: C,
                        capabilities: ["canon.edit", "campaign.view"],
                        world_capabilities: [],
                    },
                ],
            }),
            routes: [{ path: "/app/:campaignId/world/:category/:entityId", element: <CampaignWorldDetailPage /> }],
        })
        await new Promise((resolve) => setTimeout(resolve, 200))
        expect(server.calls.map((c) => c.path).filter((p) => authoringOrLifecycle.test(p))).toEqual([])
    })
})

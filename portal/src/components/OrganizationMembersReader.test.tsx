import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { useParams } from "react-router"
import { afterEach, describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import type { MockServer } from "../test/authoringHarness"
import type { MemberRow, OrganizationMembers } from "../types/organizationMembers"
import { OrganizationMembersReader } from "./OrganizationMembersReader"

afterEach(() => {
    vi.unstubAllGlobals()
})

const row = (id: string, name: string, extra: Partial<MemberRow> = {}): MemberRow => ({
    relationship_id: `rel-${id}`,
    member_entity_id: id,
    member_name: name,
    member_type_code: "npc",
    role: null,
    rank: null,
    is_public: true,
    started: "Year 1490",
    ended: null,
    current: true,
    lifecycle_status: "active",
    row_version: 1,
    period_status: "in_effect",
    category: "character",
    can_open: false,
    ...extra,
})

const SPEAKER = row("3f2b8c1e-5d4a-4e7b-9c1d-2a6f8b0e4d11", "Hero A", {
    member_type_code: "player_character",
    role: "Speaker",
    rank: "First seat",
    can_open: true,
})
const GUILD = row("guild", "R Guild", {
    member_type_code: "organization",
    category: "organization",
    can_open: true,
    started: "Year 1480",
    ended: "Year 1489",
    current: false,
    period_status: "ended",
})
const ENVOY = row("eld", "Eld", { role: "Envoy", started: "Year 1492", period_status: "not_started" })
const RANKED = row("bran", "Ser Bran", { rank: "Sergeant", period_status: "clock_unset" })

const roster = (members: MemberRow[], organizationId = "council", as_of: string | null = "Year 1491"): OrganizationMembers => ({
    organization_id: organizationId,
    status: null,
    can_edit: false,
    as_of,
    status_choices: [],
    members,
})

const PATH = (org: string, campaign = "c1") => `/campaigns/${campaign}/organizations/${org}/members`

function render(server: MockServer, entry = "/app/c1/world/organization/council") {
    const bootstrap = bootstrapWith({
        campaigns: [
            { ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c1", capabilities: ["campaign.view"] },
            { ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c2", capabilities: ["campaign.view"] },
        ],
    })
    return {
        server,
        ...renderAuthoringRoutes({
            initialEntry: entry,
            bootstrap,
            routes: [{ path: "/app/:campaignId/world/organization/:entityId", element: <Host /> }],
        }),
    }
}

function Host() {
    const { campaignId, entityId } = useParams<{ campaignId: string; entityId: string }>()
    return <OrganizationMembersReader campaignId={campaignId!} organizationId={entityId!} />
}

const requested = (server: MockServer) => server.calls.map((c) => `${c.method} ${c.path}`)

describe("OrganizationMembersReader", () => {
    it("lists a public member with their office and rank, and links the ones the server opens", async () => {
        const server = installMockServer()
        server.on("GET", PATH("council"), { body: roster([SPEAKER, GUILD]) })
        render(server)
        expect(await screen.findByRole("heading", { level: 2, name: "Members and offices" })).toBeInTheDocument()
        const [speaker, guild] = screen.getAllByRole("listitem")
        expect(within(speaker!).getByRole("link", { name: "Hero A" })).toHaveAttribute(
            "href",
            `/app/c1/characters/${SPEAKER.member_entity_id}`,
        )
        expect(within(speaker!).getByText("(First seat)")).toBeInTheDocument()
        expect(speaker).toHaveTextContent("Speaker (First seat)")
        expect(within(guild!).getByRole("link", { name: "R Guild" })).toHaveAttribute(
            "href",
            "/app/c1/world/organization/guild",
        )
        expect(screen.getByText("As of Year 1491")).toBeInTheDocument()
        // Read-only: no controls at all, and no visibility column.
        expect(screen.queryByRole("button")).not.toBeInTheDocument()
        expect(screen.queryByRole("textbox")).not.toBeInTheDocument()
        expect(screen.queryByText("Visible to")).not.toBeInTheDocument()
    })

    it("shows a member the server does not open as plain text", async () => {
        const server = installMockServer()
        server.on("GET", PATH("council"), { body: roster([ENVOY]) })
        render(server)
        const item = await screen.findByRole("listitem")
        expect(within(item).getByText("Eld")).toBeInTheDocument()
        expect(within(item).queryByRole("link")).not.toBeInTheDocument()
    })

    it("badges ended and not-started stints in text and leaves other periods unbadged", async () => {
        const server = installMockServer()
        server.on("GET", PATH("council"), { body: roster([SPEAKER, GUILD, ENVOY, RANKED]) })
        render(server)
        const [speaker, guild, envoy, ranked] = await screen.findAllByRole("listitem")
        expect(guild).toHaveTextContent("Year 1480 to Year 1489 Ended")
        expect(envoy).toHaveTextContent("Since Year 1492 Not started")
        for (const quiet of [speaker!, ranked!]) {
            expect(within(quiet).queryByText(/^(Ended|Not started)$/)).not.toBeInTheDocument()
        }
        // The editor-only "(current)" note is not part of the reader.
        expect(screen.queryByText(/\(current\)/)).not.toBeInTheDocument()
    })

    it("says 'No office recorded' only for a visible row with neither office nor rank, never 'Vacant'", async () => {
        const server = installMockServer()
        server.on("GET", PATH("council"), { body: roster([SPEAKER, GUILD, RANKED]) })
        render(server)
        const [speaker, guild, ranked] = await screen.findAllByRole("listitem")
        expect(within(guild!).getByText("No office recorded")).toBeInTheDocument()
        expect(within(speaker!).queryByText("No office recorded")).not.toBeInTheDocument()
        expect(within(ranked!).getByText("(Sergeant)")).toBeInTheDocument()
        expect(screen.getAllByText("No office recorded")).toHaveLength(1)
        expect(document.body.textContent).not.toMatch(/vacan|hidden|unknown holder/i)
        expect(document.body.textContent).not.toMatch(/[0-9a-f]{8}-[0-9a-f]{4}-/i)
    })

    it("shows the existing empty wording for an authorized empty roster, with no hint of hidden rows", async () => {
        const server = installMockServer()
        server.on("GET", PATH("council"), { body: roster([], "council", null) })
        render(server)
        expect(await screen.findByText("No members are known.")).toBeInTheDocument()
        expect(screen.queryByRole("alert")).not.toBeInTheDocument()
        expect(screen.queryByText(/As of/)).not.toBeInTheDocument()
        expect(document.body.textContent).not.toMatch(/vacan|hidden|withheld|\d+ more/i)
    })

    it("distinguishes loading from a failed request and retries it", async () => {
        const server = installMockServer()
        let attempts = 0
        server.on("GET", PATH("council"), () => {
            attempts += 1
            return attempts === 1 ? { networkError: true } : { body: roster([SPEAKER]) }
        })
        render(server)
        expect(screen.getByRole("status")).toHaveTextContent("Loading members…")
        expect(await screen.findByRole("alert")).toHaveTextContent("Members could not be loaded.")
        expect(screen.queryByText("No members are known.")).not.toBeInTheDocument()
        fireEvent.click(screen.getByRole("button", { name: "Try again" }))
        expect(await screen.findByText("Hero A")).toBeInTheDocument()
        expect(screen.queryByRole("alert")).not.toBeInTheDocument()
    })

    it("reports a refused read as an alert without a retry and without implying a cause", async () => {
        const server = installMockServer()
        server.on("GET", PATH("council"), {
            status: 404,
            body: { error: { code: "not_found", message: "m", correlation_id: "c" } },
        })
        render(server)
        expect(await screen.findByRole("alert")).toHaveTextContent("Members could not be loaded.")
        expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument()
        expect(screen.queryByText("No members are known.")).not.toBeInTheDocument()
    })

    it("sends only the one roster read, with no party or perspective context", async () => {
        const server = installMockServer()
        server.on("GET", PATH("council"), { body: roster([SPEAKER, GUILD, ENVOY]) })
        render(server)
        await screen.findByText("Hero A")
        expect(requested(server)).toEqual([`GET ${PATH("council")}`])
        const [call] = server.calls
        expect(call!.path).not.toContain("?")
        expect(Object.keys(call!.headers).map((h) => h.toLowerCase())).not.toContain("x-party-id")
    })

    it("never renders fields the reader response does not carry", async () => {
        const server = installMockServer()
        const leaky = { ...SPEAKER, is_public: false, description: "SENTINEL-description", notes: "SENTINEL-notes" }
        server.on("GET", PATH("council"), {
            body: { ...roster([leaky as MemberRow]), status_choices: [{ value: "x", label: "SENTINEL-choice" }] },
        })
        render(server)
        await screen.findByText("Hero A")
        expect(document.body.textContent).not.toContain("SENTINEL")
        expect(screen.queryByText(/Editors only|Public/)).not.toBeInTheDocument()
    })

    it("does not show the previous organization's roster while the next one loads", async () => {
        const server = installMockServer()
        let release: (() => void) | undefined
        server.on("GET", PATH("council"), { body: roster([SPEAKER]) })
        server.on("GET", PATH("guild"), async () => {
            await new Promise<void>((resolve) => {
                release = resolve
            })
            return { body: roster([ENVOY], "guild") }
        })
        const { router } = render(server)
        expect(await screen.findByText("Hero A")).toBeInTheDocument()
        await router.navigate("/app/c1/world/organization/guild")
        await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Loading members…"))
        expect(screen.queryByText("Hero A")).not.toBeInTheDocument()
        release?.()
        expect(await screen.findByText("Eld")).toBeInTheDocument()
        expect(screen.queryByText("Hero A")).not.toBeInTheDocument()
    })

    it("ignores a late answer for the organization that was left", async () => {
        const server = installMockServer()
        let releaseFirst: (() => void) | undefined
        server.on("GET", PATH("council"), async () => {
            await new Promise<void>((resolve) => {
                releaseFirst = resolve
            })
            return { body: roster([SPEAKER]) }
        })
        server.on("GET", PATH("guild"), { body: roster([ENVOY], "guild") })
        const { router } = render(server)
        await waitFor(() => expect(releaseFirst).toBeDefined())
        await router.navigate("/app/c1/world/organization/guild")
        expect(await screen.findByText("Eld")).toBeInTheDocument()
        releaseFirst?.()
        await new Promise((resolve) => setTimeout(resolve, 30))
        expect(screen.getByText("Eld")).toBeInTheDocument()
        expect(screen.queryByText("Hero A")).not.toBeInTheDocument()
    })

    it("reads the roster again for another campaign's context, never reusing the last one", async () => {
        const server = installMockServer()
        server.on("GET", PATH("council"), { body: roster([SPEAKER]) })
        server.on("GET", PATH("council", "c2"), { body: roster([], "council", "Year 1500") })
        const { router } = render(server)
        expect(await screen.findByText("Hero A")).toBeInTheDocument()
        await router.navigate("/app/c2/world/organization/council")
        expect(await screen.findByText("No members are known.")).toBeInTheDocument()
        expect(screen.getByText("As of Year 1500")).toBeInTheDocument()
        expect(screen.queryByText("Hero A")).not.toBeInTheDocument()
        expect(requested(server)).toEqual([`GET ${PATH("council")}`, `GET ${PATH("council", "c2")}`])
    })
})

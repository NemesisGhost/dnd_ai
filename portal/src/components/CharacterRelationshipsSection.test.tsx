import { fireEvent, screen, waitFor, within } from "@testing-library/react"
import { useParams } from "react-router"
import { afterEach, describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import type { MockServer } from "../test/authoringHarness"
import type { CharacterRelationship, CharacterRelationships } from "../types/characterRelationships"
import { CharacterRelationshipsSection } from "./CharacterRelationshipsSection"

afterEach(() => {
    vi.unstubAllGlobals()
})

const participant = (
    id: string,
    name: string,
    role_label: string,
    extra: Partial<CharacterRelationship["participants"][number]> = {},
): CharacterRelationship["participants"][number] => ({
    entity_id: id,
    name,
    entity_type_code: "npc",
    category: "character",
    role: role_label.toLowerCase(),
    role_label,
    is_self: false,
    can_open: false,
    ...extra,
})

const FAMILY: CharacterRelationship = {
    relationship_id: "r-family",
    kind: "family",
    kind_label: "Family",
    relationship_type: "family",
    relationship_type_label: "Family",
    symmetric: false,
    participants: [
        participant("aria", "Aria", "Child", { is_self: true }),
        participant("bran", "Ser Bran", "Parent", { can_open: true }),
    ],
    started: "3 Hammer 1492",
    ended_at: null,
    period_status: "in_effect",
    current_status_label: "Active",
    details: { family_unit_name: "House Vale" },
}

const EMPLOYMENT: CharacterRelationship = {
    relationship_id: "r-job",
    kind: "employment",
    kind_label: "Employment",
    relationship_type: "employment",
    relationship_type_label: "Employment",
    symmetric: false,
    participants: [
        participant("aria", "Aria", "Employee", { is_self: true }),
        participant("eld", "Eld Discoverable", "Employer"),
    ],
    started: "1 Hammer 1480",
    ended_at: "1 Hammer 1490",
    period_status: "ended",
    current_status_label: null,
    details: { job_title: "Scribe" },
}

const GUILD: CharacterRelationship = {
    relationship_id: "r-guild",
    kind: "membership",
    kind_label: "Membership",
    relationship_type: "membership",
    relationship_type_label: "Membership",
    symmetric: false,
    participants: [
        participant("aria", "Aria", "Member", { is_self: true }),
        participant("guild", "Silver Guild", "Organization", {
            category: "organization",
            entity_type_code: "guild",
            can_open: true,
        }),
    ],
    started: null,
    ended_at: null,
    period_status: "not_started",
    current_status_label: null,
    details: { office: "Scout", rank: "Lieutenant", ownership_share: 40, in_force: false },
}

const listing = (items: CharacterRelationship[], characterId = "aria"): CharacterRelationships => ({
    character_id: characterId,
    as_of: "9 Hammer 1492",
    truncated: false,
    items,
})

const PATH = (id: string) => `/campaigns/c1/characters/${id}/relationships`

function render(capabilities: string[] = ["campaign.view"], characterId = "aria", server = installMockServer()) {
    const bootstrap = bootstrapWith({
        campaigns: [{ ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c1", capabilities }],
    })
    const view = renderAuthoringRoutes({
        initialEntry: `/app/c1/characters/${characterId}`,
        bootstrap,
        routes: [
            {
                path: "/app/:campaignId/characters/:characterId",
                element: <Host />,
            },
        ],
    })
    return { server, ...view }
}

function Host() {
    const { campaignId, characterId } = useParams<{ campaignId: string; characterId: string }>()
    return <CharacterRelationshipsSection campaignId={campaignId!} characterId={characterId!} />
}

const requested = (server: MockServer) => server.calls.map((c) => `${c.method} ${c.path}`)

describe("CharacterRelationshipsSection", () => {
    it("lists a qualifying relationship with the counterpart, type, direction and a link", async () => {
        const server = installMockServer()
        server.on("GET", PATH("aria"), { body: listing([FAMILY]) })
        render(["campaign.view"], "aria", server)
        expect(await screen.findByRole("heading", { name: "Relationships (1)" })).toBeInTheDocument()
        const row = screen.getByRole("listitem")
        expect(within(row).getByRole("link", { name: "Ser Bran" })).toHaveAttribute("href", "/app/c1/characters/bran")
        expect(within(row).getByText("Family · Aria is Child · Ser Bran is Parent")).toBeInTheDocument()
        // The whole section is read-only: no form controls, only the expansion toggle.
        expect(within(row).getAllByRole("button")).toHaveLength(1)
        expect(screen.queryByRole("textbox")).not.toBeInTheDocument()
    })

    it("shows 'No visible relationships.' for an authorized empty result", async () => {
        const server = installMockServer()
        server.on("GET", PATH("aria"), { body: listing([]) })
        render(["campaign.view"], "aria", server)
        expect(await screen.findByText("No visible relationships.")).toBeInTheDocument()
        expect(screen.queryByRole("alert")).not.toBeInTheDocument()
    })

    it("distinguishes loading from failure and retries a failure", async () => {
        const server = installMockServer()
        let attempts = 0
        server.on("GET", PATH("aria"), () => {
            attempts += 1
            return attempts === 1 ? { networkError: true } : { body: listing([FAMILY]) }
        })
        render(["campaign.view"], "aria", server)
        expect(screen.getByRole("status")).toHaveTextContent("Loading relationships…")
        expect(await screen.findByRole("alert")).toHaveTextContent("Relationships could not be loaded.")
        expect(screen.queryByText("No visible relationships.")).not.toBeInTheDocument()
        fireEvent.click(screen.getByRole("button", { name: "Try again" }))
        expect(await screen.findByText("Ser Bran")).toBeInTheDocument()
        expect(screen.queryByRole("alert")).not.toBeInTheDocument()
    })

    it("reports a refused read as an alert without a retry loop and without implying a cause", async () => {
        const server = installMockServer()
        server.on("GET", PATH("aria"), {
            status: 404,
            body: { error: { code: "not_found", message: "m", correlation_id: "c" } },
        })
        render(["campaign.view"], "aria", server)
        expect(await screen.findByRole("alert")).toHaveTextContent("Relationships could not be loaded.")
        expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument()
    })

    it("badges ended and not-started relationships in text and shows unlinked names as plain text", async () => {
        const server = installMockServer()
        server.on("GET", PATH("aria"), { body: listing([EMPLOYMENT, GUILD]) })
        render(["campaign.view"], "aria", server)
        const rows = await screen.findAllByRole("listitem")
        expect(within(rows[0]!).getByText("Ended")).toBeInTheDocument()
        expect(within(rows[0]!).getByText("Eld Discoverable")).toBeInTheDocument()
        expect(within(rows[0]!).queryByRole("link")).not.toBeInTheDocument()
        expect(within(rows[1]!).getByText("Not started")).toBeInTheDocument()
        expect(within(rows[1]!).getByRole("link", { name: "Silver Guild" })).toHaveAttribute(
            "href",
            "/app/c1/world/organization/guild",
        )
    })

    it("expands accessibly, shows only recorded details, and sends no request", async () => {
        const server = installMockServer()
        server.on("GET", PATH("aria"), { body: listing([FAMILY, GUILD]) })
        render(["campaign.view"], "aria", server)
        await screen.findByText("Ser Bran")
        const before = server.calls.length
        const toggles = screen.getAllByRole("button", { name: /^Details of/ })
        expect(toggles[0]).toHaveAttribute("aria-expanded", "false")
        expect(toggles[0]).toHaveAccessibleName("Details of Family with Ser Bran")
        fireEvent.click(toggles[0]!)
        expect(toggles[0]).toHaveAttribute("aria-expanded", "true")
        const details = document.getElementById(toggles[0]!.getAttribute("aria-controls")!)!
        expect(within(details).getByText("Since 3 Hammer 1492 — in effect now")).toBeInTheDocument()
        expect(within(details).getByText("House Vale")).toBeInTheDocument()
        expect(within(details).getByText("Active")).toBeInTheDocument()
        expect(within(details).queryByText("Job title")).not.toBeInTheDocument()
        fireEvent.click(toggles[1]!)
        const guild = document.getElementById(toggles[1]!.getAttribute("aria-controls")!)!
        for (const text of ["Scout", "Lieutenant", "40%", "No"]) {
            expect(within(guild).getByText(text)).toBeInTheDocument()
        }
        expect(within(guild).getByText("No dates recorded — not started yet")).toBeInTheDocument()
        // Several rows may stay open; collapsing hides the details again.
        fireEvent.click(toggles[0]!)
        expect(toggles[0]).toHaveAttribute("aria-expanded", "false")
        expect(server.calls.length).toBe(before)
    })

    it("renders nothing and sends nothing for an editor", async () => {
        const server = installMockServer()
        const { container } = render(["campaign.view", "canon.edit"], "aria", server)
        await new Promise((resolve) => setTimeout(resolve, 30))
        expect(container.querySelector(".character-relationships")).toBeNull()
        expect(screen.queryByRole("heading", { name: /Relationships/ })).not.toBeInTheDocument()
        expect(server.calls).toEqual([])
    })

    it("only ever requests the reader route, never an authoring one", async () => {
        const server = installMockServer()
        server.on("GET", PATH("aria"), { body: listing([FAMILY, EMPLOYMENT, GUILD]) })
        render(["campaign.view"], "aria", server)
        await screen.findByText("Ser Bran")
        for (const button of screen.getAllByRole("button", { name: /^Details of/ })) fireEvent.click(button)
        expect(requested(server)).toEqual([`GET ${PATH("aria")}`])
        expect(requested(server).some((call) => call.includes("/authoring/"))).toBe(false)
        // No party or perspective context is attached to the read.
        const [call] = server.calls
        expect(call!.path).not.toContain("?")
        expect(Object.keys(call!.headers).map((h) => h.toLowerCase())).not.toContain("x-party-id")
    })

    it("does not show a previous character's list for the next one while it loads", async () => {
        const server = installMockServer()
        let release: (() => void) | undefined
        server.on("GET", PATH("aria"), { body: listing([FAMILY]) })
        server.on("GET", PATH("bran"), async () => {
            await new Promise<void>((resolve) => {
                release = resolve
            })
            return { body: listing([EMPLOYMENT], "bran") }
        })
        const { router } = render(["campaign.view"], "aria", server)
        expect(await screen.findByText("Ser Bran")).toBeInTheDocument()
        await router.navigate("/app/c1/characters/bran")
        await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Loading relationships…"))
        expect(screen.queryByText("Ser Bran")).not.toBeInTheDocument()
        release?.()
        expect(await screen.findByText("Eld Discoverable")).toBeInTheDocument()
        expect(screen.queryByText("Ser Bran")).not.toBeInTheDocument()
    })

    it("ignores a late answer for the character that was left", async () => {
        const server = installMockServer()
        let releaseFirst: (() => void) | undefined
        server.on("GET", PATH("aria"), async () => {
            await new Promise<void>((resolve) => {
                releaseFirst = resolve
            })
            return { body: listing([FAMILY]) }
        })
        server.on("GET", PATH("bran"), { body: listing([EMPLOYMENT], "bran") })
        const { router } = render(["campaign.view"], "aria", server)
        await waitFor(() => expect(releaseFirst).toBeDefined())
        await router.navigate("/app/c1/characters/bran")
        expect(await screen.findByText("Eld Discoverable")).toBeInTheDocument()
        releaseFirst?.()
        await new Promise((resolve) => setTimeout(resolve, 30))
        expect(screen.getByText("Eld Discoverable")).toBeInTheDocument()
        expect(screen.queryByText("Ser Bran")).not.toBeInTheDocument()
    })

    it("never renders fields the reader response does not carry", async () => {
        const server = installMockServer()
        // Even if a server bug sent extra fields, the section has no place to render them.
        const leaky = { ...FAMILY, description: "SENTINEL-description", details: { ...FAMILY.details, treaty_terms: "SENTINEL-treaty" } }
        server.on("GET", PATH("aria"), { body: listing([leaky as CharacterRelationship]) })
        render(["campaign.view"], "aria", server)
        await screen.findByText("Ser Bran")
        fireEvent.click(screen.getByRole("button", { name: /^Details of/ }))
        expect(document.body.textContent).not.toContain("SENTINEL")
    })
})

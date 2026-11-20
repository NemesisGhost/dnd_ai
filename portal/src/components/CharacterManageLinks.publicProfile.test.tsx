import { screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import type { CharacterKind } from "../types/character"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import { CharacterManageLinks } from "./CharacterManageLinks"

// D1 and D2 of docs/delivery/p15-c02-s01-draft-release-plan.md: the Public profile link sits inside
// the Manage row's own canon.edit gate, for every kind, and nothing else offers it or reads the route.

afterEach(() => {
    vi.unstubAllGlobals()
})

function setup(kind: CharacterKind, capabilities: string[]) {
    const server = installMockServer()
    // Whatever else the row reads (the builds link) answers as "not available".
    server.on("GET", /.*/, { status: 404, body: { error: { code: "not_found" } } })
    renderAuthoringRoutes({
        initialEntry: "/app/c1/characters/ch1",
        bootstrap: bootstrapWith({
            campaigns: [{ ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c1", capabilities }],
        }),
        routes: [
            {
                path: "/app/:campaignId/characters/:characterId",
                element: <CharacterManageLinks campaignId="c1" characterId="ch1" kind={kind} />,
            },
        ],
    })
    return server
}

describe("CharacterManageLinks: Public profile", () => {
    it.each(["npc", "player_character", "character"] as const)("D1: a canon editor sees the link for %s", async (kind) => {
        setup(kind, ["canon.edit"])
        const link = await screen.findByRole("link", { name: "Public profile" })
        expect(link).toHaveAttribute("href", "/app/c1/characters/ch1/public-profile")
    })

    it.each(["npc", "player_character", "character"] as const)(
        "D2: without canon.edit there is no link and no public-profile request for %s",
        async (kind) => {
            const server = setup(kind, [])
            expect(screen.queryByRole("navigation", { name: "Manage character" })).not.toBeInTheDocument()
            expect(screen.queryByRole("link", { name: "Public profile" })).not.toBeInTheDocument()
            expect(server.calls.filter((c) => c.path.includes("public-profile"))).toHaveLength(0)
        },
    )
})

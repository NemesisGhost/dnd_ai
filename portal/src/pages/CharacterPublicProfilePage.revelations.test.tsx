import { screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import { CharacterPublicProfilePage } from "./CharacterPublicProfilePage"

// The page-level cases of the Revelations section (docs/delivery/p15-c02-s02-revelations-plan.md V1, V9, and
// the T02 cases that need the page's own read). Kept apart from CharacterPublicProfilePage.test.tsx so the S01
// cases stay exactly as they were reviewed.

const PATH = "/campaigns/c1/characters/ch1/public-profile"
const REVELATIONS = "/campaigns/c1/characters/ch1/revelations"

function profile(overrides: object = {}) {
    return {
        character_id: "ch1",
        label: { name: "Mira", summary: "canonical summary" },
        draft: {
            character_public_profile_id: "p1",
            row_version: 3,
            updated_at: "2026-11-20T10:00:00Z",
            public_summary: "A weary ferryman",
            publish_species: false,
            publish_size: false,
            public_appearance: "Tall and grey",
            public_appearance_withheld: false,
            public_appearance_origin: "authored",
            public_background: "Raised on the river",
            public_background_withheld: false,
            public_background_origin: "authored",
        },
        has_unreleased_changes: false,
        latest_release: null,
        releases: [],
        can_edit: true,
        can_release: false,
        identity_preview: null,
        identity_preview_withheld: false,
        identity_differs_from_latest_release: false,
        legacy_copy: { appearance: true, background: true },
        player_profile_copy: null,
        ...overrides,
    }
}

const revelation = {
    character_revelation_id: "r-1",
    audience_kind: "member",
    target_campaign_membership_id: "m-1",
    target_member_name: "Pia Player",
    target_access_group_id: null,
    target_access_group_name: null,
    created_by_membership_id: "m-gm",
    created_by_name: "Gina GM",
    authority_source: "owner",
    created_at: "2026-11-19T10:00:00Z",
    live: true,
    ended_at: null,
    end_reason: null,
}

afterEach(() => {
    vi.unstubAllGlobals()
})

function render() {
    return renderAuthoringRoutes({
        initialEntry: "/app/c1/characters/ch1/public-profile",
        bootstrap: bootstrapWith({
            campaigns: [{ ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c1", capabilities: ["canon.edit"] }],
        }),
        routes: [{ path: "/app/:campaignId/characters/:characterId/public-profile", element: <CharacterPublicProfilePage /> }],
    })
}

describe("the Revelations section on the Public profile page", () => {
    it("V1: it reads its list once, only after the page read has succeeded", async () => {
        const server = installMockServer()
        let answerPage: (value: { body: object }) => void = () => undefined
        server.on("GET", PATH, () => new Promise((resolve) => (answerPage = resolve)))
        server.on("GET", REVELATIONS, { body: { character_id: "ch1", revelations: [revelation] } })
        render()
        expect(screen.getByRole("status")).toHaveTextContent("Loading")
        expect(server.callsTo("GET", REVELATIONS)).toHaveLength(0)
        answerPage({ body: profile() })
        expect(await screen.findByText("Pia Player")).toBeInTheDocument()
        expect(server.callsTo("GET", REVELATIONS)).toHaveLength(1)
    })

    it("V1: a denied or unavailable page never asks for the list", async () => {
        for (const status of [404, 403]) {
            const server = installMockServer()
            server.on("GET", PATH, { status, body: { error: { code: "x", message: "SERVER-SECRET" } } })
            const { unmount } = renderAuthoringRoutes({
                initialEntry: "/app/c1/characters/ch1/public-profile",
                routes: [{ path: "/app/:campaignId/characters/:characterId/public-profile", element: <CharacterPublicProfilePage /> }],
            })
            expect(await screen.findByRole("alert")).toHaveTextContent("not available to you")
            expect(server.callsTo("GET", REVELATIONS)).toHaveLength(0)
            expect(screen.queryByRole("heading", { name: "Revelations" })).not.toBeInTheDocument()
            unmount()
            vi.unstubAllGlobals()
        }
    })

    it("V9: when the list is gone the page reads again, and a page that is now 404 leaves no name behind", async () => {
        const server = installMockServer()
        let pageReads = 0
        server.on("GET", PATH, () =>
            ++pageReads === 1
                ? { body: profile() }
                : { status: 404, body: { error: { code: "not_found", message: "SERVER-SECRET" } } },
        )
        server.on("GET", REVELATIONS, { status: 404, body: { error: { code: "not_found", message: "SERVER-SECRET" } } })
        render()
        expect(await screen.findByText("This character's public profile is not available to you.")).toBeInTheDocument()
        expect(pageReads).toBe(2)
        expect(screen.queryByRole("heading", { name: "Revelations" })).not.toBeInTheDocument()
        expect(document.body).not.toHaveTextContent(/Mira|Pia Player|Gina GM|SERVER-SECRET/)
    })

    it("V9: a list that is gone while the page is still readable keeps the page and hides the names", async () => {
        const server = installMockServer()
        server.on("GET", PATH, () => ({ body: profile() }))
        server.on("GET", REVELATIONS, { status: 404, body: { error: { code: "not_found", message: "x" } } })
        render()
        expect(await screen.findByText("The revelations of this character are not available to you.")).toBeInTheDocument()
        await vi.waitFor(() => expect(server.callsTo("GET", PATH).length).toBeGreaterThanOrEqual(2))
        expect(screen.getByRole("form", { name: "Public profile draft" })).toBeInTheDocument()
        expect(screen.queryByText("Pia Player")).not.toBeInTheDocument()
    })
})

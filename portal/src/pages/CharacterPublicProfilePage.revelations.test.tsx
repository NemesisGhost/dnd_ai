import { fireEvent, screen, within } from "@testing-library/react"
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

    it("V9: a list that is gone while the page then reads fine: the page is read once, then stays closed until the person asks again", async () => {
        const server = installMockServer()
        let release: () => void = () => undefined
        let reads = 0
        server.on("GET", PATH, () => (++reads === 2 ? new Promise((resolve) => (release = () => resolve({ body: profile() }))) : { body: profile() }))
        server.on("GET", REVELATIONS, { status: 404, body: { error: { code: "not_found", message: "x" } } })
        render()
        await vi.waitFor(() => expect(server.callsTo("GET", PATH)).toHaveLength(2))
        release()
        // The list and the page answer under one rule, so a page that reads fine after a list 404 is a race:
        // it is not read again by itself (no loop), and nothing protected stays on screen meanwhile.
        await screen.findByRole("button", { name: /Try again|Retry/ })
        expect(screen.getByText("This character's public profile is not available to you.")).toBeInTheDocument()
        expect(screen.queryByRole("form", { name: "Public profile draft" })).not.toBeInTheDocument()
        expect(screen.queryByText("Pia Player")).not.toBeInTheDocument()
        await new Promise((resolve) => setTimeout(resolve, 50))
        expect(server.callsTo("GET", PATH)).toHaveLength(2)
        fireEvent.click(await screen.findByRole("button", { name: /Try again|Retry/ }))
        await vi.waitFor(() => expect(server.callsTo("GET", PATH)).toHaveLength(3))
    })

    // R-S02-1: the list's 404 is an authoritative read denial, so the page's own protected content goes at once.
    const PROTECTED = /Mira|A weary ferryman|Tall and grey|Raised on the river|Gina GM|Draft version/
    const gone = { status: 404, body: { error: { code: "not_found", message: "SERVER-SECRET" } } }

    it("R-S02-1: list 404 then a failed page read leaves no protected content, during or after, and a later good read restores it", async () => {
        const server = installMockServer()
        let pageReads = 0
        let answerSecond: (value: { status: number; body: object }) => void = () => undefined
        server.on("GET", PATH, () => {
            pageReads += 1
            if (pageReads === 1) return { body: profile({ latest_release: released }) }
            if (pageReads === 2) return new Promise((resolve) => (answerSecond = resolve))
            return { body: profile() }
        })
        let listReads = 0
        server.on("GET", REVELATIONS, () => (++listReads === 1 ? gone : { body: { character_id: "ch1", can_reveal: true, revelations: [] } }))
        render()
        // While the page's own re-read is still pending, nothing protected is on screen.
        expect(await screen.findByText("This character's public profile is not available to you.")).toBeInTheDocument()
        expect(pageReads).toBe(2)
        expect(screen.queryByRole("form", { name: "Public profile draft" })).not.toBeInTheDocument()
        expect(document.body).not.toHaveTextContent(PROTECTED)
        expect(screen.queryByDisplayValue(/weary ferryman|Tall and grey|Raised on the river/)).not.toBeInTheDocument()
        // The re-read fails recoverably: the earlier read is not brought back.
        answerSecond({ status: 500, body: { error: { code: "x", message: "SERVER-SECRET" } } })
        await screen.findByRole("button", { name: /Try again|Retry/ })
        expect(document.body).not.toHaveTextContent(PROTECTED)
        expect(screen.queryByRole("form", { name: "Public profile draft" })).not.toBeInTheDocument()
        expect(screen.queryByRole("heading", { name: "Revelations" })).not.toBeInTheDocument()
        expect(document.body).not.toHaveTextContent("SERVER-SECRET")
        // Only a later successful read restores the page.
        fireEvent.click(screen.getByRole("button", { name: /Try again|Retry/ }))
        expect(await screen.findByRole("form", { name: "Public profile draft" })).toBeInTheDocument()
    })

    it("R-S02-1: a write's own 404 (an audience that may be gone) is not a read denial and leaves the page", async () => {
        const server = installMockServer()
        server.on("GET", PATH, () => ({ body: profile({ latest_release: released }) }))
        server.on("GET", REVELATIONS, { body: { character_id: "ch1", can_reveal: true, revelations: [] } })
        server.on("POST", REVELATIONS, gone)
        render()
        fireEvent.click(await screen.findByRole("button", { name: "Reveal" }))
        const form = await screen.findByRole("form", { name: "Reveal this character" })
        fireEvent.change(within(form).getByRole("textbox", { name: /Reason/ }), { target: { value: "Try" } })
        fireEvent.click(within(form).getByRole("button", { name: "Reveal" }))
        expect(await screen.findByText("That audience is no longer available.")).toBeInTheDocument()
        expect(screen.getByRole("form", { name: "Public profile draft" })).toBeInTheDocument()
        expect(screen.getByText("A weary ferryman", { selector: "textarea" })).toBeInTheDocument()
        expect(server.callsTo("GET", PATH)).toHaveLength(1)
    })

    // The offer follows the revelations list's can_reveal, never the page's can_release (which also needs a
    // readable draft, an active character and a readable identity preview).
    const released = {
        version_number: 1,
        from_draft_row_version: 3,
        authority_source: "owner",
        released_at: "2026-11-19T10:00:00Z",
        released_by: "Gina GM",
        character_public_profile_release_id: "rel1",
        public_summary: "S",
        public_appearance: "A",
        public_background: "B",
        release_note: null,
        species: null,
        size: null,
        identity_entity_row_version: null,
    }
    const listWith = (can_reveal: boolean, revelations: object[] = [revelation]) => ({
        body: { character_id: "ch1", can_reveal, revelations },
    })

    it("a revealer whose draft has a withheld field (can_release false) can still reveal and revoke", async () => {
        const server = installMockServer()
        const withheld = profile({
            can_release: false,
            latest_release: released,
            releases: [{ version_number: 1 }],
        })
        withheld.draft.public_background_withheld = true
        ;(withheld.draft as { public_background: string | null }).public_background = null
        server.on("GET", PATH, { body: withheld })
        server.on("GET", REVELATIONS, listWith(true))
        render()
        expect(await screen.findByRole("button", { name: "Reveal" })).toBeEnabled()
        expect(screen.getByRole("button", { name: /^Revoke/ })).toBeInTheDocument()
        expect(screen.queryByRole("button", { name: "Release" })).not.toBeInTheDocument()
    })

    it("an editor without reveal authority edits the draft and sees the list with no reveal or revoke control", async () => {
        const server = installMockServer()
        server.on("GET", PATH, { body: profile({ can_edit: true, can_release: false, latest_release: released }) })
        server.on("GET", REVELATIONS, listWith(false))
        render()
        expect(await screen.findByText("Pia Player")).toBeInTheDocument()
        expect(screen.getByRole("button", { name: "Save draft" })).toBeInTheDocument()
        expect(screen.queryByRole("button", { name: /^(Reveal|Revoke)/ })).not.toBeInTheDocument()
        expect(screen.getByText("You can't reveal or revoke this character.")).toBeInTheDocument()
    })

    it("an archived character: revoke is offered, a create is refused by state and the page reads again", async () => {
        const server = installMockServer()
        let pageReads = 0
        server.on("GET", PATH, () => {
            pageReads += 1
            return { body: profile({ can_release: false, latest_release: released }) }
        })
        server.on("GET", REVELATIONS, listWith(true))
        server.on("POST", REVELATIONS, {
            status: 409,
            body: { error: { code: "public_profile_character_not_active", message: "SERVER-SECRET", correlation_id: "c" } },
        })
        render()
        expect(await screen.findByRole("button", { name: /^Revoke/ })).toBeInTheDocument()
        fireEvent.click(await screen.findByRole("button", { name: "Reveal" }))
        const form = await screen.findByRole("form", { name: "Reveal this character" })
        fireEvent.change(within(form).getByRole("textbox", { name: /Reason/ }), { target: { value: "Try" } })
        fireEvent.click(within(form).getByRole("button", { name: "Reveal" }))
        expect(await screen.findByText(/archived, so it can't be revealed/)).toBeInTheDocument()
        await vi.waitFor(() => expect(pageReads).toBeGreaterThanOrEqual(2))
        expect(document.body).not.toHaveTextContent("SERVER-SECRET")
    })

    it("a page with no release offers no Reveal and says to release first", async () => {
        const server = installMockServer()
        server.on("GET", PATH, { body: profile({ latest_release: null }) })
        server.on("GET", REVELATIONS, listWith(true, []))
        render()
        expect(await screen.findByText("Release the profile before revealing it.")).toBeInTheDocument()
        expect(screen.queryByRole("button", { name: "Reveal" })).not.toBeInTheDocument()
    })
})

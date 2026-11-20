import { act, fireEvent, screen, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import type { MockServer } from "../test/authoringHarness"
import { CharacterPublicProfilePage } from "./CharacterPublicProfilePage"

// Acceptance cases D1-D17 of docs/delivery/p15-c02-s01-draft-release-plan.md (T01). D1 and D2 are
// in components/CharacterManageLinks.publicProfile.test.tsx.

const PATH = "/campaigns/c1/characters/ch1/public-profile"
const SAVE = `${PATH}/draft`

function draft(overrides: object = {}) {
    return {
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
        ...overrides,
    }
}

function profile(overrides: object = {}) {
    return {
        character_id: "ch1",
        label: { name: "Mira", summary: "canonical summary" },
        draft: draft(),
        has_unreleased_changes: false,
        latest_release: null,
        releases: [],
        can_edit: true,
        can_release: false,
        identity_preview: {
            character_row_version: 7,
            species: { code: "elf", label: "Elf" },
            size: { code: "medium", label: "Medium" },
        },
        identity_preview_withheld: false,
        identity_differs_from_latest_release: false,
        legacy_copy: { appearance: true, background: true },
        player_profile_copy: null,
        ...overrides,
    }
}

const stale = {
    status: 409,
    body: { error: { code: "stale_write", message: "SERVER-SECRET-TEXT", correlation_id: "c" } },
}
const refused = (status: number, code?: string) => ({
    status,
    body: { error: { code, message: "SERVER-SECRET-TEXT", correlation_id: "c" } },
})

afterEach(() => {
    vi.unstubAllGlobals()
})

function setup(current: object = profile(), initialEntry = "/app/c1/characters/ch1/public-profile") {
    const server = installMockServer()
    server.on("GET", PATH, () => ({ body: current }))
    server.on("POST", SAVE, { status: 200, body: { character_public_profile_id: "p1", character_id: "ch1", row_version: 4, created: false, changed: true } })
    const rendered = renderAuthoringRoutes({
        initialEntry,
        bootstrap: bootstrapWith({
            campaigns: [{ ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c1", capabilities: ["canon.edit"] }],
        }),
        routes: [
            { path: "/app/:campaignId/characters/:characterId/public-profile", element: <CharacterPublicProfilePage /> },
            { path: "/app/:campaignId/characters/:characterId", element: <p>Sheet</p> },
            { path: "/app/:campaignId/characters/:characterId/edit", element: <p>Edit page</p> },
        ],
    })
    return { server, ...rendered }
}

const form = () => screen.findByRole("form", { name: "Public profile draft" })
const type = (name: RegExp, value: string) =>
    fireEvent.change(screen.getByRole("textbox", { name }), { target: { value } })
const saveButton = () => screen.getByRole("button", { name: "Save draft" })
const posts = (server: MockServer) => server.callsTo("POST", SAVE)

describe("CharacterPublicProfilePage: draft editing (T01)", () => {
    it("D3: a 404 or a 403 shows one non-disclosing message, no name and no form", async () => {
        for (const status of [404, 403]) {
            const server = installMockServer()
            server.on("GET", PATH, refused(status))
            const { unmount } = renderAuthoringRoutes({
                initialEntry: "/app/c1/characters/ch1/public-profile",
                routes: [{ path: "/app/:campaignId/characters/:characterId/public-profile", element: <CharacterPublicProfilePage /> }],
            })
            expect(await screen.findByRole("alert")).toHaveTextContent("This character's public profile is not available to you.")
            expect(screen.queryByRole("form")).not.toBeInTheDocument()
            expect(screen.queryByText(/Mira|SERVER-SECRET/)).not.toBeInTheDocument()
            unmount()
            vi.unstubAllGlobals()
        }
    })

    it("D4: no draft yet: an empty form that names the character; the first save sends a null version and only what was filled", async () => {
        const { server } = setup(profile({ draft: null }))
        await form()
        expect(screen.getByText("Mira")).toBeInTheDocument()
        expect(screen.getByRole("textbox", { name: /Public summary/ })).toHaveValue("")
        expect(saveButton()).toBeDisabled()
        type(/Public appearance/, "  Scarred  ")
        fireEvent.click(saveButton())
        await vi.waitFor(() => expect(posts(server)).toHaveLength(1))
        expect(posts(server)[0]!.body).toEqual({ expected_row_version: null, public_appearance: "Scarred" })
        // The 201/200 is followed by a re-read.
        await vi.waitFor(() => expect(server.callsTo("GET", PATH).length).toBeGreaterThanOrEqual(2))
    })

    it("D4: a save is announced once the re-read has applied", async () => {
        const { server } = setup(profile({ draft: null }))
        await form()
        type(/Public summary/, "Hello")
        server.on("GET", PATH, () => ({ body: profile({ draft: draft({ row_version: 1, public_summary: "Hello" }) }) }))
        fireEvent.click(saveButton())
        expect(await screen.findByText("Draft saved.")).toBeInTheDocument()
        expect(screen.getByText("Draft version 1.")).toBeInTheDocument()
    })

    it("D5: only the changed keys are sent, with the version that was read", async () => {
        const { server } = setup()
        await form()
        type(/Public appearance/, "Short and green")
        fireEvent.click(saveButton())
        await vi.waitFor(() => expect(posts(server)).toHaveLength(1))
        expect(posts(server)[0]!.body).toEqual({ expected_row_version: 3, public_appearance: "Short and green" })
    })

    it("D6: emptying a field that had text sends null for that key", async () => {
        const { server } = setup()
        await form()
        type(/Public summary/, "   ")
        fireEvent.click(saveButton())
        await vi.waitFor(() => expect(posts(server)).toHaveLength(1))
        expect(posts(server)[0]!.body).toEqual({ expected_row_version: 3, public_summary: null })
    })

    it("D7: with nothing changed, Save is disabled and a submit sends nothing", async () => {
        const { server } = setup()
        const f = await form()
        expect(saveButton()).toBeDisabled()
        fireEvent.submit(f)
        // Changing and restoring a value is no change either.
        type(/Public summary/, "x")
        type(/Public summary/, "A weary ferryman")
        expect(saveButton()).toBeDisabled()
        fireEvent.submit(f)
        expect(posts(server)).toHaveLength(0)
    })

    it("D8: a stale save keeps what was typed, re-reads, and never re-sends the old version", async () => {
        const { server } = setup()
        await form()
        server.on("POST", SAVE, stale)
        type(/Public appearance/, "My typed appearance")
        fireEvent.click(saveButton())
        // The latest draft arrives with a newer version and another person's text.
        server.on("GET", PATH, () => ({ body: profile({ draft: draft({ row_version: 5, public_appearance: "Newer text" }) }) }))
        await vi.waitFor(() => expect(posts(server)).toHaveLength(1))
        const notice = await screen.findByRole("alert")
        expect(notice).toHaveTextContent(/draft changed since you opened it/)
        expect(notice).not.toHaveTextContent("SERVER-SECRET")
        // What was typed is shown back, read-only; the form shows the latest saved text.
        const mine = within(await screen.findByRole("region", { name: "Your unsaved changes" }))
        expect(mine.getByText("My typed appearance")).toBeInTheDocument()
        await vi.waitFor(() => expect(screen.getByRole("textbox", { name: /Public appearance/ })).toHaveValue("Newer text"))
        expect(saveButton()).toBeDisabled()
        // The next save carries the new version and only what is changed against the new draft.
        server.on("POST", SAVE, { status: 200, body: { row_version: 6, created: false, changed: true } })
        type(/Public summary/, "Fresh")
        fireEvent.click(saveButton())
        await vi.waitFor(() => expect(posts(server)).toHaveLength(2))
        expect(posts(server)[1]!.body).toEqual({ expected_row_version: 5, public_summary: "Fresh" })
        expect(posts(server).filter((c) => (c.body as { expected_row_version: number }).expected_row_version === 3)).toHaveLength(1)
    })

    it("D9: a missing draft is treated like a stale one, with a neutral message", async () => {
        const { server } = setup()
        await form()
        server.on("POST", SAVE, refused(409, "public_profile_draft_missing"))
        type(/Public summary/, "Typed")
        fireEvent.click(saveButton())
        const notice = await screen.findByRole("alert")
        expect(notice).toHaveTextContent(/no longer matches what you were editing/)
        expect(notice).not.toHaveTextContent("SERVER-SECRET")
        expect(within(notice).getByText("Typed")).toBeInTheDocument()
        await vi.waitFor(() => expect(server.callsTo("GET", PATH).length).toBeGreaterThanOrEqual(2))
    })

    it("D10: an edit refusal says so, shows the typed values back and follows the new can_edit", async () => {
        const { server } = setup()
        await form()
        server.on("POST", SAVE, refused(403, "public_profile_edit_denied"))
        server.on("GET", PATH, () => ({ body: profile({ can_edit: false }) }))
        type(/Public summary/, "Typed words")
        fireEvent.click(saveButton())
        const notice = await screen.findByRole("alert")
        expect(notice).toHaveTextContent(/Editing this public profile is not available to you/)
        expect(within(notice).getByText("Typed words")).toBeInTheDocument()
        await vi.waitFor(() => expect(screen.queryByRole("form", { name: "Public profile draft" })).not.toBeInTheDocument())
        expect(screen.queryByRole("button", { name: "Save draft" })).not.toBeInTheDocument()
        expect(screen.queryByRole("textbox")).not.toBeInTheDocument()
    })

    it("D11: a 404 on save drops every draft and release text; only the person's own input is shown back", async () => {
        const { server } = setup(profile({
            latest_release: { version_number: 1, public_summary: "RELEASED-TEXT" },
        }))
        await form()
        server.on("POST", SAVE, refused(404))
        type(/Public appearance/, "Mine only")
        fireEvent.click(saveButton())
        expect(await screen.findByText("This character's public profile is not available to you.")).toBeInTheDocument()
        expect(screen.queryByRole("form")).not.toBeInTheDocument()
        expect(screen.getByText("Mine only")).toBeInTheDocument()
        for (const text of ["A weary ferryman", "Tall and grey", "Raised on the river", "RELEASED-TEXT", "Mira"]) {
            expect(screen.queryByText(new RegExp(text))).not.toBeInTheDocument()
        }
    })

    it("D12: can_edit false shows read-only values with no Save and no flag controls", async () => {
        setup(profile({ can_edit: false, can_release: true }))
        expect(await screen.findByText("Tall and grey")).toBeInTheDocument()
        expect(screen.queryByRole("textbox")).not.toBeInTheDocument()
        expect(screen.queryByRole("checkbox")).not.toBeInTheDocument()
        expect(screen.queryByRole("button", { name: /Save draft/ })).not.toBeInTheDocument()
        expect(screen.queryByText(/not allowed to edit|because/i)).not.toBeInTheDocument()
    })

    it("D13: a withheld background shows no text and no input; Clear sends null and nothing else does", async () => {
        const withheld = profile({
            draft: draft({ public_background: null, public_background_withheld: true, public_background_origin: "legacy_copy" }),
        })
        const { server } = setup(withheld)
        await form()
        expect(screen.queryByText("Raised on the river")).not.toBeInTheDocument()
        expect(screen.queryByRole("textbox", { name: /Public background/ })).not.toBeInTheDocument()
        expect(screen.getByText(/copied text that you are not allowed to read/)).toBeInTheDocument()
        // Another save omits the background key.
        type(/Public summary/, "Changed")
        fireEvent.click(saveButton())
        await vi.waitFor(() => expect(posts(server)).toHaveLength(1))
        expect(posts(server)[0]!.body).toEqual({ expected_row_version: 3, public_summary: "Changed" })
    })

    it("D13: Clear sends public_background: null", async () => {
        const { server } = setup(profile({
            draft: draft({ public_background: null, public_background_withheld: true }),
        }))
        await form()
        fireEvent.click(screen.getByRole("button", { name: "Clear public background" }))
        expect(screen.getByRole("button", { name: "Clear public background" })).toHaveAttribute("aria-pressed", "true")
        fireEvent.click(saveButton())
        await vi.waitFor(() => expect(posts(server)).toHaveLength(1))
        expect(posts(server)[0]!.body).toEqual({ expected_row_version: 3, public_background: null })
    })

    it("D14: the flags are labelled with the live values and only a changed flag is sent, as a boolean", async () => {
        const { server } = setup()
        await form()
        const species = screen.getByRole("checkbox", { name: "Publish species: Elf" })
        expect(screen.getByRole("checkbox", { name: "Publish size: Medium" })).not.toBeChecked()
        fireEvent.click(species)
        fireEvent.click(saveButton())
        await vi.waitFor(() => expect(posts(server)).toHaveLength(1))
        expect(posts(server)[0]!.body).toEqual({ expected_row_version: 3, publish_species: true })
    })

    it("D15: with no preview the flags show no live value and nothing is inferred", async () => {
        setup(profile({ identity_preview: null, identity_preview_withheld: true }))
        await form()
        expect(screen.getByRole("checkbox", { name: "Publish species" })).toBeInTheDocument()
        expect(screen.getByRole("checkbox", { name: "Publish size" })).toBeInTheDocument()
        expect(screen.getByText(/cannot be previewed by you/)).toBeInTheDocument()
        expect(screen.queryByText(/Elf|Medium/)).not.toBeInTheDocument()
    })

    it("D16: a network failure keeps the input and Retry re-sends the same body under the same key", async () => {
        const { server } = setup()
        await form()
        server.on("POST", SAVE, { networkError: true })
        type(/Public summary/, "Typed")
        fireEvent.click(saveButton())
        fireEvent.click(await screen.findByRole("button", { name: "Retry" }))
        await vi.waitFor(() => expect(posts(server)).toHaveLength(2))
        expect(posts(server)[1]!.body).toEqual(posts(server)[0]!.body)
        expect(posts(server)[1]!.headers["Idempotency-Key"]).toBe(posts(server)[0]!.headers["Idempotency-Key"])
        expect(screen.getByRole("textbox", { name: /Public summary/ })).toHaveValue("Typed")
    })

    it("D16: a confirmed save whose re-read fails shows the notice and is never re-sent", async () => {
        const { server } = setup()
        await form()
        server.on("GET", PATH, refused(500))
        type(/Public summary/, "Typed")
        fireEvent.click(saveButton())
        // The page's own notice offers the read (the save notice is quiet beside it); a write waits for it.
        expect((await screen.findAllByText(/The latest public profile could not be loaded/)).length).toBeGreaterThan(0)
        expect(saveButton()).toBeDisabled()
        type(/Public summary/, "Typed again")
        expect(saveButton()).toBeDisabled()
        // Reading again works and shows the new version; the save was sent once.
        server.on("GET", PATH, () => ({ body: profile({ draft: draft({ row_version: 4, public_summary: "Typed" }) }) }))
        fireEvent.click(screen.getByRole("button", { name: "Try again" }))
        await vi.waitFor(() => expect(screen.getByText("Draft version 4.")).toBeInTheDocument())
        expect(posts(server)).toHaveLength(1)
    })

    it("D17: unsaved changes are guarded on navigation, and a character change discards a late save", async () => {
        const { server, router } = setup()
        await form()
        type(/Public summary/, "Unsaved")
        await act(async () => {
            void router.navigate("/app/c1/characters/ch1")
        })
        expect(await screen.findByRole("dialog", { name: "Discard unsaved changes?" })).toBeInTheDocument()
        fireEvent.click(screen.getByRole("button", { name: "Keep editing" }))
        expect(screen.getByRole("textbox", { name: /Public summary/ })).toHaveValue("Unsaved")
        // A save still pending when the person moves to another character answers into nothing.
        let answer: (r: { status: number; body: unknown }) => void = () => undefined
        server.on("POST", SAVE, () => new Promise((resolve) => (answer = resolve)))
        server.on("GET", "/campaigns/c1/characters/ch2/public-profile", {
            body: profile({ character_id: "ch2", label: { name: "Other", summary: null }, draft: null }),
        })
        fireEvent.click(saveButton())
        await vi.waitFor(() => expect(posts(server)).toHaveLength(1))
        await act(async () => {
            void router.navigate("/app/c1/characters/ch2/public-profile")
        })
        fireEvent.click(within(await screen.findByRole("dialog", { name: "Discard unsaved changes?" })).getByRole("button", { name: "Discard changes" }))
        expect(await screen.findByText("Other")).toBeInTheDocument()
        await act(async () => {
            answer({ status: 409, body: { error: { code: "stale_write" } } })
        })
        expect(screen.queryByRole("alert")).not.toBeInTheDocument()
        expect(screen.queryByText(/Mira/)).not.toBeInTheDocument()
    })
})

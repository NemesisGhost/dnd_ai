import { act, fireEvent, screen, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import type { MockServer } from "../test/authoringHarness"
import { CharacterPublicProfilePage } from "./CharacterPublicProfilePage"

// Acceptance cases of docs/delivery/p15-c02-s01-draft-release-plan.md: D1-D17 (T01) and R1-R17 (T02).
// D1 and D2 are in components/CharacterManageLinks.publicProfile.test.tsx.

const PATH = "/campaigns/c1/characters/ch1/public-profile"
const SAVE = `${PATH}/draft`
const RELEASE = `${PATH}/releases`

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
            latest_release: release({ public_summary: "RELEASED-TEXT" }),
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

function release(overrides: object = {}) {
    return {
        character_public_profile_release_id: "r1",
        version_number: 1,
        from_draft_row_version: 3,
        authority_source: "owner",
        released_at: "2026-11-19T10:00:00Z",
        released_by: "Gina GM",
        public_summary: "SNAPSHOT-SUMMARY",
        public_appearance: "SNAPSHOT-APPEARANCE",
        public_background: "SNAPSHOT-BACKGROUND",
        release_note: null,
        species: null,
        size: null,
        identity_entity_row_version: null,
        ...overrides,
    }
}

// The metadata of a release, as the history lists it (no text).
const meta = (overrides: object = {}) => {
    const { public_summary, public_appearance, public_background, release_note, species, size, ...rest } = release(overrides) as Record<string, unknown>
    void [public_summary, public_appearance, public_background, release_note, species, size]
    return rest
}

const receipt = (overrides: object = {}) => ({
    status: 201,
    body: {
        character_public_profile_release_id: "r2",
        character_public_profile_id: "p1",
        character_id: "ch1",
        version_number: 1,
        from_draft_row_version: 3,
        authority_source: "owner",
        created: true,
        is_latest: true,
        species_published: false,
        size_published: false,
        identity_entity_row_version: null,
        ...overrides,
    },
})

const releaseSetup = (overrides: object = {}) => {
    const rig = setup(profile({ can_release: true, ...overrides }))
    rig.server.on("POST", RELEASE, receipt())
    return rig
}
const releases = (server: MockServer) => server.callsTo("POST", RELEASE)
const releaseButton = () => screen.findByRole("button", { name: "Release" })
async function openRelease() {
    const button = await releaseButton()
    button.focus()
    fireEvent.click(button)
    return screen.findByRole("dialog", { name: /Release draft version/ })
}
const confirm = (dialog: HTMLElement) => fireEvent.click(within(dialog).getByRole("button", { name: /^Release as version/ }))

describe("CharacterPublicProfilePage: release (T02)", () => {
    it("R1: a saved, clean draft with can_release offers Release", async () => {
        releaseSetup()
        expect(await releaseButton()).toBeEnabled()
    })

    it("R2: without can_release there is no Release button and one neutral line", async () => {
        setup(profile({ can_release: false }))
        await form()
        expect(screen.queryByRole("button", { name: "Release" })).not.toBeInTheDocument()
        expect(screen.getByText("You can't release this profile.")).toBeInTheDocument()
    })

    it("R3: Release is disabled while the form is dirty and opens nothing", async () => {
        const { server } = releaseSetup()
        await form()
        type(/Public summary/, "Unsaved change")
        const button = screen.getByRole("button", { name: "Release" })
        expect(button).toBeDisabled()
        expect(screen.getByText("Save your changes before releasing.")).toBeInTheDocument()
        fireEvent.click(button)
        expect(screen.queryByRole("dialog", { name: /Release draft version/ })).not.toBeInTheDocument()
        expect(releases(server)).toHaveLength(0)
        // Restoring the saved text re-enables it.
        type(/Public summary/, "A weary ferryman")
        expect(screen.getByRole("button", { name: "Release" })).toBeEnabled()
    })

    it("R4: no draft means no Release button", async () => {
        setup(profile({ draft: null, can_release: true }))
        await form()
        expect(screen.queryByRole("button", { name: "Release" })).not.toBeInTheDocument()
    })

    it("R5: the dialog names the draft version, counts the note, and Cancel sends nothing and returns focus", async () => {
        const { server } = releaseSetup()
        const dialog = await openRelease()
        expect(within(dialog).getByRole("heading", { name: "Release draft version 3?" })).toBeInTheDocument()
        expect(dialog).toHaveAccessibleDescription(
            "Releasing doesn't show this profile to anyone. Players see it only after you reveal the character.",
        )
        const note = within(dialog).getByRole("textbox", { name: /Release note/ })
        fireEvent.change(note, { target: { value: "x".repeat(1001) } })
        expect(within(dialog).getByText("1 characters over the limit")).toBeInTheDocument()
        expect(within(dialog).getByRole("button", { name: /^Release as version/ })).toBeDisabled()
        fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }))
        expect(screen.queryByRole("dialog", { name: /Release draft version/ })).not.toBeInTheDocument()
        expect(releases(server)).toHaveLength(0)
        expect(screen.getByRole("button", { name: "Release" })).toHaveFocus()
    })

    it("R5: a lost answer keeps the dialog open and Retry repeats the same request under the same key", async () => {
        const { server } = releaseSetup()
        server.on("POST", RELEASE, { networkError: true })
        const dialog = await openRelease()
        confirm(dialog)
        fireEvent.click(await within(dialog).findByRole("button", { name: "Retry" }))
        await vi.waitFor(() => expect(releases(server)).toHaveLength(2))
        expect(releases(server)[1]!.body).toEqual(releases(server)[0]!.body)
        expect(releases(server)[1]!.headers["Idempotency-Key"]).toBe(releases(server)[0]!.headers["Idempotency-Key"])
    })

    it("R6: a draft without identity flags releases with only the draft version", async () => {
        const { server } = releaseSetup()
        confirm(await openRelease())
        await vi.waitFor(() => expect(releases(server)).toHaveLength(1))
        expect(releases(server)[0]!.body).toEqual({ expected_draft_row_version: 3 })
        expect("expected_character_row_version" in (releases(server)[0]!.body as object)).toBe(false)
    })

    it("R6: the note is sent, trimmed, when given", async () => {
        const { server } = releaseSetup()
        const dialog = await openRelease()
        fireEvent.change(within(dialog).getByRole("textbox", { name: /Release note/ }), { target: { value: "  First pass  " } })
        confirm(dialog)
        await vi.waitFor(() => expect(releases(server)).toHaveLength(1))
        expect(releases(server)[0]!.body).toEqual({ expected_draft_row_version: 3, release_note: "First pass" })
    })

    it("R7: a draft that publishes species or size adds the character version from the read that was shown", async () => {
        const { server } = releaseSetup({ draft: draft({ publish_species: true }) })
        confirm(await openRelease())
        await vi.waitFor(() => expect(releases(server)).toHaveLength(1))
        expect(releases(server)[0]!.body).toEqual({ expected_draft_row_version: 3, expected_character_row_version: 7 })
    })

    it("R8: a 201 re-reads and shows the new snapshot, clears Unreleased changes, and announces it", async () => {
        const { server } = releaseSetup({ has_unreleased_changes: true })
        expect(await screen.findByText(/Unreleased changes\./)).toBeInTheDocument()
        server.on("GET", PATH, () => ({
            body: profile({
                can_release: true,
                has_unreleased_changes: false,
                latest_release: release({
                    version_number: 1,
                    species: { code: "elf", label: "Elf" },
                    size: { code: "medium", label: "Medium" },
                }),
                releases: [meta()],
            }),
        }))
        confirm(await openRelease())
        const panel = within(await screen.findByRole("region", { name: "Latest release" }))
        expect(panel.getByRole("heading", { name: "Latest release (version 1)" })).toBeInTheDocument()
        expect(panel.getByText("SNAPSHOT-SUMMARY")).toBeInTheDocument()
        expect(panel.getByText("Elf")).toBeInTheDocument()
        expect(panel.getByText("Medium")).toBeInTheDocument()
        expect(screen.queryByText(/Unreleased changes\./)).not.toBeInTheDocument()
        expect(await screen.findByText("Released as version 1.")).toBeInTheDocument()
        expect(screen.queryByRole("dialog", { name: /Release draft version/ })).not.toBeInTheDocument()
        expect(server.callsTo("GET", PATH).length).toBeGreaterThanOrEqual(2)
    })

    it("R9: a 200 created:false re-reads and says it was already released, not as an error", async () => {
        const { server } = releaseSetup()
        server.on("POST", RELEASE, { status: 200, body: { ...receipt().body, created: false } })
        confirm(await openRelease())
        expect(await screen.findByText("This version was already released.")).toBeInTheDocument()
        expect(screen.queryByRole("alert")).not.toBeInTheDocument()
        await vi.waitFor(() => expect(server.callsTo("GET", PATH).length).toBeGreaterThanOrEqual(2))
    })

    it("R10: the latest release stays the snapshot after the draft changes, and the history is unchanged", async () => {
        const base = { can_release: true, latest_release: release({ from_draft_row_version: 3 }), releases: [meta()] }
        const { server } = setup(profile(base))
        await form()
        server.on("POST", SAVE, { status: 200, body: { row_version: 4, created: false, changed: true } })
        server.on("GET", PATH, () => ({
            body: profile({
                ...base,
                has_unreleased_changes: true,
                draft: draft({ row_version: 4, public_summary: "NEW-DRAFT-SUMMARY" }),
            }),
        }))
        type(/Public summary/, "NEW-DRAFT-SUMMARY")
        fireEvent.click(saveButton())
        expect(await screen.findByText(/Draft version 4\. Unreleased changes\./)).toBeInTheDocument()
        const panel = within(screen.getByRole("region", { name: "Latest release" }))
        expect(panel.getByText("SNAPSHOT-SUMMARY")).toBeInTheDocument()
        expect(panel.queryByText("NEW-DRAFT-SUMMARY")).not.toBeInTheDocument()
        // The draft's text is in the form, the snapshot's is in the panel, and the two differ.
        expect(screen.getByRole("textbox", { name: /Public summary/ })).toHaveValue("NEW-DRAFT-SUMMARY")
        expect(within(screen.getByRole("region", { name: "Release history" })).getAllByRole("listitem")).toHaveLength(1)
    })

    it("R11: releasing sends no revelation or access request and offers no reveal control", async () => {
        const { server } = releaseSetup()
        confirm(await openRelease())
        await screen.findByText("Released as version 1.")
        const paths = server.calls.map((c) => `${c.method} ${c.path}`)
        expect(paths.every((path) => path === `GET ${PATH}` || path === `POST ${RELEASE}`)).toBe(true)
        expect(paths.some((path) => /revelations|effective-access|access-overview/.test(path))).toBe(false)
        expect(screen.queryByRole("button", { name: /reveal/i })).not.toBeInTheDocument()
        expect(screen.queryByRole("link", { name: /reveal/i })).not.toBeInTheDocument()
    })

    it("R12: a release refused for lack of authority says so, re-reads, and the button follows can_release", async () => {
        const { server } = releaseSetup()
        server.on("POST", RELEASE, refused(403, "character_reveal_required"))
        server.on("GET", PATH, () => ({ body: profile({ can_release: false }) }))
        confirm(await openRelease())
        const notice = await screen.findByRole("alert")
        expect(notice).toHaveTextContent("You no longer have authority to release this profile.")
        expect(notice).not.toHaveTextContent("SERVER-SECRET")
        await vi.waitFor(() => expect(screen.queryByRole("button", { name: "Release" })).not.toBeInTheDocument())
        expect(screen.getByRole("textbox", { name: /Public summary/ })).toHaveValue("A weary ferryman")
    })

    it("R13: a withheld-field refusal says a field cannot be released by this person and re-reads", async () => {
        const { server } = releaseSetup()
        server.on("POST", RELEASE, refused(403, "public_profile_field_withheld"))
        confirm(await openRelease())
        expect(await screen.findByRole("alert")).toHaveTextContent(/field of this profile cannot be released by you/)
        await vi.waitFor(() => expect(server.callsTo("GET", PATH).length).toBeGreaterThanOrEqual(2))
    })

    it("R14: a stale release says so, re-reads, and the next confirmation uses the new tokens", async () => {
        const { server } = releaseSetup({ draft: draft({ publish_size: true }) })
        server.on("POST", RELEASE, stale)
        server.on("GET", PATH, () => ({
            body: profile({
                can_release: true,
                draft: draft({ row_version: 5, publish_size: true }),
                identity_preview: {
                    character_row_version: 9,
                    species: { code: "elf", label: "Elf" },
                    size: { code: "medium", label: "Medium" },
                },
            }),
        }))
        confirm(await openRelease())
        expect(await screen.findByRole("alert")).toHaveTextContent("The draft or character changed since you opened it.")
        await vi.waitFor(() => expect(screen.getByText("Draft version 5.")).toBeInTheDocument())
        server.on("POST", RELEASE, receipt())
        confirm(await openRelease())
        await vi.waitFor(() => expect(releases(server)).toHaveLength(2))
        expect(releases(server)[0]!.body).toEqual({ expected_draft_row_version: 3, expected_character_row_version: 7 })
        expect(releases(server)[1]!.body).toEqual({ expected_draft_row_version: 5, expected_character_row_version: 9 })
    })

    it.each([
        [409, "public_profile_draft_missing", /no saved draft to release/],
        [409, "public_profile_character_not_active", /character is archived/],
        [409, "campaign_archived", /campaign is archived/],
        [409, "public_profile_identity_unavailable", /species and size are not available/],
        [422, "public_profile_identity_version_required", /draft or character changed since you opened it/],
    ])("R15: %s %s gets its own neutral message and a re-read", async (status, code, message) => {
        const { server } = releaseSetup()
        server.on("POST", RELEASE, refused(status, code))
        confirm(await openRelease())
        const notice = await screen.findByRole("alert")
        expect(notice.textContent).toMatch(message)
        expect(notice).not.toHaveTextContent("SERVER-SECRET")
        await vi.waitFor(() => expect(server.callsTo("GET", PATH).length).toBeGreaterThanOrEqual(2))
    })

    it("R16: a 404 on release drops everything the server sent and keeps only the person's own note", async () => {
        const { server } = releaseSetup({ latest_release: release(), releases: [meta()] })
        server.on("POST", RELEASE, refused(404))
        const dialog = await openRelease()
        fireEvent.change(within(dialog).getByRole("textbox", { name: /Release note/ }), { target: { value: "My own note" } })
        confirm(dialog)
        expect(await screen.findByText("This character's public profile is not available to you.")).toBeInTheDocument()
        expect(screen.getByText("My own note")).toBeInTheDocument()
        for (const text of ["A weary ferryman", "SNAPSHOT-SUMMARY", "Mira", "Gina GM"]) {
            expect(screen.queryByText(new RegExp(text))).not.toBeInTheDocument()
        }
        expect(screen.queryByRole("form")).not.toBeInTheDocument()
    })

    it("R17: the history is newest first with metadata only", async () => {
        setup(profile({
            can_release: true,
            latest_release: release({ version_number: 2 }),
            releases: [
                meta({ version_number: 1, released_by: "Old GM", authority_source: "owner" }),
                meta({ version_number: 2, released_by: "Del Egate", authority_source: "delegation" }),
            ],
        }))
        const list = within(await screen.findByRole("region", { name: "Release history" }))
        const items = list.getAllByRole("listitem")
        expect(items).toHaveLength(2)
        expect(items[0]).toHaveTextContent(/Version 2.*released by Del Egate.*Delegated GM/)
        expect(items[1]).toHaveTextContent(/Version 1.*released by Old GM.*Owner/)
        expect(list.queryByRole("link")).not.toBeInTheDocument()
        expect(list.queryByText(/SNAPSHOT/)).not.toBeInTheDocument()
    })

    it("R17: can_edit without can_release shows Save and no Release", async () => {
        setup(profile({ can_edit: true, can_release: false }))
        await form()
        expect(screen.getByRole("textbox", { name: /Public summary/ })).toBeInTheDocument()
        expect(screen.getByRole("button", { name: "Save draft" })).toBeInTheDocument()
        expect(screen.queryByRole("button", { name: "Release" })).not.toBeInTheDocument()
    })

    it("R17: can_release without can_edit shows Release with read-only fields", async () => {
        setup(profile({ can_edit: false, can_release: true }))
        expect(await releaseButton()).toBeEnabled()
        expect(screen.queryByRole("textbox", { name: /Public summary/ })).not.toBeInTheDocument()
        expect(screen.queryByRole("button", { name: "Save draft" })).not.toBeInTheDocument()
        expect(screen.getByText("Tall and grey")).toBeInTheDocument()
    })

    it("a release whose re-read fails is confirmed, not repeated, and writes wait for a read", async () => {
        const { server } = releaseSetup()
        const dialog = await openRelease()
        server.on("GET", PATH, refused(500))
        confirm(dialog)
        await screen.findAllByText(/The latest public profile could not be loaded/)
        expect(screen.getByRole("button", { name: "Release" })).toBeDisabled()
        expect(releases(server)).toHaveLength(1)
    })
})

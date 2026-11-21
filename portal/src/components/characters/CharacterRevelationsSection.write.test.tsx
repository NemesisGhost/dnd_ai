import { act, fireEvent, screen, within } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { useParams } from "react-router"
import { useSession } from "../../context/SessionContext"
import { sessionBootstrapFixture } from "../../fixtures/sessionBootstrap"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../../test/authoringHarness"
import type { MockServer } from "../../test/authoringHarness"
import { CharacterRevelationsSection } from "./CharacterRevelationsSection"

// Acceptance cases V11 to V30 of docs/delivery/p15-c02-s02-revelations-plan.md (T02: create and revoke).

const LIST = "/campaigns/c1/characters/ch1/revelations"
const OVERVIEW = "/campaigns/c1/access-overview"

function row(overrides: object = {}) {
    return {
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
        ...overrides,
    }
}

const refused = (status: number, code?: string) => ({
    status,
    body: { error: { code, message: "SERVER-SECRET-TEXT", correlation_id: "c" } },
})

const overview = {
    members: [
        { campaign_membership_id: "m-1", user_id: "u1", display_name: "Pia Player", status_code: "active", status_display_name: "Active", joined_at: "2026-01-01T00:00:00Z" },
        { campaign_membership_id: "m-2", user_id: "u2", display_name: "Gone Gary", status_code: "ended", status_display_name: "Ended", joined_at: "2026-01-01T00:00:00Z" },
    ],
    assignable_roles: [],
    assignable_characters: [],
    assignable_relationship_types: [],
    grantable_resource_capabilities: [],
    access_groups: [
        { access_group_id: "g-1", name: "The Band", description: null, status_code: "active", status_display_name: "Active", created_at: "2026-01-01T00:00:00Z", members: [], grants: [] },
        { access_group_id: "g-2", name: "Old Band", description: null, status_code: "archived", status_display_name: "Archived", created_at: "2026-01-01T00:00:00Z", members: [], grants: [] },
    ],
}

interface World {
    canReveal: boolean
    rows: object[]
}

afterEach(() => {
    vi.unstubAllGlobals()
})

function Host({ hasRelease, readPage }: { hasRelease: boolean; readPage: () => void }) {
    const { characterId = "ch1" } = useParams()
    const { refresh } = useSession()
    return (
        <>
            <CharacterRevelationsSection key={characterId} campaignId="c1" characterId={characterId} hasRelease={hasRelease} readPage={readPage} onReadDenied={readPage} />
            {/* Applies the bootstrap the test supplies, as a real session refresh does; also a control that is not the section's. */}
            <button type="button" onClick={() => void refresh()}>
                Refresh session
            </button>
        </>
    )
}

function setup({
    canReveal = true,
    hasRelease = true,
    capabilities = ["canon.edit"],
    rows = [row()],
    onRefresh,
}: {
    canReveal?: boolean
    hasRelease?: boolean
    capabilities?: string[]
    rows?: object[]
    onRefresh?: () => Promise<ReturnType<typeof bootstrapWith> | null>
} = {}) {
    const world: World = { canReveal, rows }
    const server = installMockServer()
    const readPage = vi.fn()
    server.on("GET", LIST, () => ({ body: { character_id: "ch1", can_reveal: world.canReveal, revelations: world.rows } }))
    server.on("GET", OVERVIEW, { body: overview })
    server.on("POST", LIST, { status: 201, body: { character_revelation_id: "r-new", created: true } })
    server.on("POST", `${LIST}/r-1/revoke`, { status: 200, body: { character_revelation_id: "r-1", revoked: true } })
    const rendered = renderAuthoringRoutes({
        initialEntry: "/app/c1/characters/ch1/public-profile",
        bootstrap: bootstrapWith({
            campaigns: [{ ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c1", capabilities }],
        }),
        routes: [{ path: "/app/:campaignId/characters/:characterId/public-profile", element: <Host hasRelease={hasRelease} readPage={readPage} /> }],
        onRefresh,
    })
    return { server, world, readPage, ...rendered }
}

const creates = (server: MockServer) => server.callsTo("POST", LIST)
const revokes = (server: MockServer) => server.callsTo("POST", `${LIST}/r-1/revoke`)
const revealButton = () => screen.findByRole("button", { name: "Reveal" })
async function openForm() {
    const button = await revealButton()
    button.focus()
    fireEvent.click(button)
    return screen.findByRole("form", { name: "Reveal this character" })
}
const typeReason = (value: string) => fireEvent.change(screen.getByRole("textbox", { name: /Reason/ }), { target: { value } })
const submitForm = (form: HTMLElement) => fireEvent.click(within(form).getByRole("button", { name: "Reveal" }))
async function openRevoke() {
    const button = (await screen.findAllByRole("button", { name: /^Revoke/ }))[0]!
    button.focus()
    fireEvent.click(button)
    return screen.findByRole("dialog", { name: /Revoke access for/ })
}
const confirmRevoke = (dialog: HTMLElement) => fireEvent.click(within(dialog).getByRole("button", { name: "Revoke" }))

describe("CharacterRevelationsSection: offer rule (V11 to V13)", () => {
    it("V11: with can_reveal, Reveal and a Revoke on each live row, none on ended rows", async () => {
        setup({ rows: [row(), row({ character_revelation_id: "r-2", target_member_name: "Ended Eve", live: false, ended_at: "2026-11-20T10:00:00Z", end_reason: "revoked" })] })
        expect(await revealButton()).toBeEnabled()
        expect(screen.getAllByRole("button", { name: /^Revoke/ })).toHaveLength(1)
    })

    it("V12: an editor without reveal authority reads the list and is offered nothing", async () => {
        const { server } = setup({ canReveal: false })
        expect(await screen.findByText("Pia Player")).toBeInTheDocument()
        expect(screen.queryByRole("button", { name: /Reveal|Revoke/ })).not.toBeInTheDocument()
        expect(screen.getByText("You can't reveal or revoke this character.")).toBeInTheDocument()
        expect(creates(server)).toHaveLength(0)
    })

    it("V13: with no release Reveal is not offered and says why; Revoke is still offered", async () => {
        setup({ hasRelease: false })
        expect(await screen.findByText("Release the profile before revealing it.")).toBeInTheDocument()
        expect(screen.queryByRole("button", { name: "Reveal" })).not.toBeInTheDocument()
        expect(screen.getByRole("button", { name: /^Revoke/ })).toBeInTheDocument()
    })
})

describe("CharacterRevelationsSection: the form (V14, V15)", () => {
    it("V14: campaign-wide kinds need no target and a reason is required", async () => {
        const { server } = setup()
        const form = await openForm()
        expect(within(form).getAllByRole("radio")).toHaveLength(2)
        expect(within(form).queryByRole("combobox")).not.toBeInTheDocument()
        submitForm(form)
        expect(await screen.findAllByText("Give a reason.")).not.toHaveLength(0)
        expect(creates(server)).toHaveLength(0)
        typeReason("x".repeat(1001))
        submitForm(form)
        expect(await screen.findAllByText(/characters or fewer/)).not.toHaveLength(0)
        expect(creates(server)).toHaveLength(0)
    })

    it("V15: without access.manage there is no member or group choice, no overview read and a hint", async () => {
        const { server } = setup()
        const form = await openForm()
        expect(within(form).queryByRole("radio", { name: /One member|One access group/ })).not.toBeInTheDocument()
        expect(within(form).getByText("To reveal to one member or group, ask someone who manages campaign access.")).toBeInTheDocument()
        expect(server.callsTo("GET", OVERVIEW)).toHaveLength(0)
    })

    it("V15: with access.manage a member or group is chosen from the active ones of the overview", async () => {
        const { server } = setup({ capabilities: ["canon.edit", "access.manage"] })
        const form = await openForm()
        expect(server.callsTo("GET", OVERVIEW)).toHaveLength(0)
        fireEvent.click(within(form).getByRole("radio", { name: "One member" }))
        const select = await within(form).findByRole("combobox", { name: /Member/ })
        expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual(["Choose a member", "Pia Player"])
        fireEvent.click(within(form).getByRole("radio", { name: "One access group" }))
        const groups = await within(form).findByRole("combobox", { name: /Access group/ })
        expect(within(groups).getAllByRole("option").map((o) => o.textContent)).toEqual(["Choose an access group", "The Band"])
        fireEvent.change(groups, { target: { value: "g-1" } })
        typeReason("  For the band  ")
        submitForm(form)
        await vi.waitFor(() => expect(creates(server)).toHaveLength(1))
        expect(creates(server)[0]!.body).toEqual({ audience_kind: "access_group", target_access_group_id: "g-1", reason: "For the band" })
    })

    it("V15: choosing a member and no member fails validation without a request", async () => {
        const { server } = setup({ capabilities: ["canon.edit", "access.manage"] })
        const form = await openForm()
        fireEvent.click(within(form).getByRole("radio", { name: "One member" }))
        await within(form).findByRole("combobox", { name: /Member/ })
        typeReason("Because")
        submitForm(form)
        expect(await screen.findAllByText("Choose a member.")).not.toHaveLength(0)
        expect(creates(server)).toHaveLength(0)
    })
})

describe("CharacterRevelationsSection: create outcomes (V16 to V23)", () => {
    it("V16: a 201 re-reads, announces, clears the form and puts focus back on Reveal", async () => {
        const { server, world } = setup()
        const form = await openForm()
        typeReason("For the table")
        world.rows = [row(), row({ character_revelation_id: "r-new", audience_kind: "campaign_current", target_member_name: null, audience_size: 3, snapshot_members: [] })]
        submitForm(form)
        await vi.waitFor(() => expect(creates(server)).toHaveLength(1))
        expect(creates(server)[0]!.body).toEqual({ audience_kind: "campaign_current", reason: "For the table" })
        expect((await screen.findAllByText("Campaign members at the time (3)")).length).toBeGreaterThan(0)
        expect(await screen.findByText("Revealed to the campaign members now.")).toBeInTheDocument()
        expect(screen.queryByRole("form", { name: "Reveal this character" })).not.toBeInTheDocument()
        await vi.waitFor(() => expect(screen.getByRole("button", { name: "Reveal" })).toHaveFocus())
        // A second form starts empty.
        const again = await openForm()
        expect(within(again).getByRole("textbox", { name: /Reason/ })).toHaveValue("")
    })

    it("V17: a 200 created:false says the audience already sees it, and is not an error", async () => {
        const { server } = setup()
        server.on("POST", LIST, { status: 200, body: { character_revelation_id: "r-1", created: false } })
        const form = await openForm()
        typeReason("Again")
        submitForm(form)
        expect(await screen.findByText("That audience can already see this profile.")).toBeInTheDocument()
        expect(screen.queryByRole("alert")).not.toBeInTheDocument()
    })

    it("V18: a 403 withdraws the controls after the re-read, reads the page again and shows the reason back", async () => {
        const { server, world, readPage } = setup()
        const form = await openForm()
        typeReason("My private reason")
        server.on("POST", LIST, refused(403, "character_reveal_required"))
        world.canReveal = false
        submitForm(form)
        const notice = await screen.findByRole("alert")
        expect(notice).toHaveTextContent("You no longer have authority to reveal this character.")
        expect(notice).not.toHaveTextContent("SERVER-SECRET")
        expect(within(notice).getByText("My private reason")).toBeInTheDocument()
        await vi.waitFor(() => expect(screen.queryByRole("button", { name: /Reveal|Revoke/ })).not.toBeInTheDocument())
        expect(readPage).toHaveBeenCalled()
        expect(creates(server)).toHaveLength(1)
    })

    it("V19: a 404 re-reads the list, keeps the reason and refreshes the options", async () => {
        const { server } = setup({ capabilities: ["canon.edit", "access.manage"] })
        const form = await openForm()
        fireEvent.click(within(form).getByRole("radio", { name: "One member" }))
        const select = await within(form).findByRole("combobox", { name: /Member/ })
        fireEvent.change(select, { target: { value: "m-1" } })
        typeReason("Keep this")
        server.on("POST", LIST, refused(404))
        submitForm(form)
        const notice = await screen.findByRole("alert")
        expect(notice).toHaveTextContent("That audience is no longer available.")
        await vi.waitFor(() => expect(server.callsTo("GET", OVERVIEW)).toHaveLength(2))
        expect(server.callsTo("GET", LIST).length).toBeGreaterThanOrEqual(2)
        expect(screen.getByRole("textbox", { name: /Reason/ })).toHaveValue("Keep this")
        expect(creates(server)).toHaveLength(1)
    })

    it("V19: a 404 whose list read is also 404 drops everything and asks the page to read again", async () => {
        const { server, readPage } = setup()
        const form = await openForm()
        typeReason("Gone")
        server.on("POST", LIST, refused(404))
        server.on("GET", LIST, refused(404))
        submitForm(form)
        expect(await screen.findByText("The revelations of this character are not available to you.")).toBeInTheDocument()
        expect(screen.queryByText("Pia Player")).not.toBeInTheDocument()
        expect(screen.queryByRole("form", { name: "Reveal this character" })).not.toBeInTheDocument()
        expect(readPage).toHaveBeenCalled()
    })

    it("V20: an inactive target is said so, the options are read again and a vanished selection is cleared", async () => {
        const { server } = setup({ capabilities: ["canon.edit", "access.manage"] })
        const form = await openForm()
        fireEvent.click(within(form).getByRole("radio", { name: "One member" }))
        fireEvent.change(await within(form).findByRole("combobox", { name: /Member/ }), { target: { value: "m-1" } })
        typeReason("Soon gone")
        server.on("POST", LIST, refused(409, "revelation_target_not_active"))
        server.on("GET", OVERVIEW, { body: { ...overview, members: [] } })
        submitForm(form)
        expect(await screen.findByRole("alert")).toHaveTextContent("That member or group is no longer active.")
        await vi.waitFor(() => expect(screen.getByRole("combobox", { name: /Member/ })).toHaveValue(""))
    })

    it.each([
        ["public_profile_not_released", /has not been released/],
        ["public_profile_character_not_active", /archived, so it can't be revealed/],
        ["campaign_archived", /campaign is archived/],
    ])("V21: 409 %s has its own neutral message and reads the page again", async (code, text) => {
        const { server, readPage } = setup()
        const form = await openForm()
        typeReason("Why not")
        server.on("POST", LIST, refused(409, code))
        submitForm(form)
        const notice = await screen.findByRole("alert")
        expect(notice).toHaveTextContent(text)
        expect(notice).not.toHaveTextContent("SERVER-SECRET")
        expect(readPage).toHaveBeenCalled()
    })

    it("V22: a 422 shows the error and changes nothing else", async () => {
        const { server, readPage } = setup()
        const form = await openForm()
        typeReason("Shaped wrong")
        server.on("POST", LIST, refused(422, "validation_error"))
        submitForm(form)
        expect(await within(form).findByRole("alert")).toBeInTheDocument()
        expect(readPage).not.toHaveBeenCalled()
        expect(screen.getByRole("form", { name: "Reveal this character" })).toBeInTheDocument()
        expect(creates(server)).toHaveLength(1)
    })

    it("V23: a lost answer is retried with the same body and the same key", async () => {
        const { server } = setup()
        const form = await openForm()
        typeReason("Network trouble")
        server.on("POST", LIST, { networkError: true })
        submitForm(form)
        fireEvent.click(await within(form).findByRole("button", { name: "Retry" }))
        await vi.waitFor(() => expect(creates(server)).toHaveLength(2))
        expect(creates(server)[1]!.body).toEqual(creates(server)[0]!.body)
        expect(creates(server)[1]!.headers["Idempotency-Key"]).toBe(creates(server)[0]!.headers["Idempotency-Key"])
    })

    it("V23: an edited body after a lost answer is a new request under a new key", async () => {
        const { server } = setup()
        const form = await openForm()
        typeReason("Network trouble")
        server.on("POST", LIST, { networkError: true })
        submitForm(form)
        await within(form).findByRole("button", { name: "Retry" })
        typeReason("A different reason")
        submitForm(form)
        await vi.waitFor(() => expect(creates(server)).toHaveLength(2))
        expect(creates(server)[1]!.body).toEqual({ audience_kind: "campaign_current", reason: "A different reason" })
        expect(creates(server)[1]!.headers["Idempotency-Key"]).not.toBe(creates(server)[0]!.headers["Idempotency-Key"])
    })

    it("V23: a confirmed write whose re-read fails shows the stale notice, holds writes and is never re-sent", async () => {
        const { server } = setup()
        const form = await openForm()
        typeReason("Confirmed")
        server.on("GET", LIST, refused(500))
        submitForm(form)
        await screen.findAllByText(/The latest revelations could not be loaded/)
        expect(creates(server)).toHaveLength(1)
        expect(screen.getByRole("button", { name: "Reveal" })).toBeDisabled()
    })
})

describe("CharacterRevelationsSection: revoke (V24 to V28)", () => {
    it("V24: the dialog names the audience, needs a reason, and Cancel sends nothing and returns focus", async () => {
        const { server } = setup()
        const dialog = await openRevoke()
        expect(within(dialog).getByRole("heading", { name: "Revoke access for Pia Player?" })).toBeInTheDocument()
        expect(within(dialog).getByRole("button", { name: "Revoke" })).toBeDisabled()
        fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }))
        expect(screen.queryByRole("dialog", { name: /Revoke access for/ })).not.toBeInTheDocument()
        expect(revokes(server)).toHaveLength(0)
        expect(screen.getByRole("button", { name: /^Revoke/ })).toHaveFocus()
    })

    it("V25: a revoke moves the row to Ended, announces it and keeps focus on the page", async () => {
        const { server, world } = setup()
        const dialog = await openRevoke()
        fireEvent.change(within(dialog).getByRole("textbox", { name: /Reason for revoking/ }), { target: { value: "  No longer needed " } })
        world.rows = [row({ live: false, ended_at: "2026-11-21T10:00:00Z", end_reason: "revoked" })]
        confirmRevoke(dialog)
        await vi.waitFor(() => expect(revokes(server)).toHaveLength(1))
        expect(revokes(server)[0]!.body).toEqual({ reason: "No longer needed" })
        const ended = within(await screen.findByRole("region", { name: "Ended" }))
        expect(ended.getByText(/Ended .*: Revoked/)).toBeInTheDocument()
        expect(await screen.findByText("Revocation saved.")).toBeInTheDocument()
        expect(screen.queryByRole("button", { name: /^Revoke/ })).not.toBeInTheDocument()
        await vi.waitFor(() => expect(document.activeElement).not.toBe(document.body))
    })

    it("V26: revoked:false says the revelation had already ended", async () => {
        const { server } = setup()
        server.on("POST", `${LIST}/r-1/revoke`, { status: 200, body: { character_revelation_id: "r-1", revoked: false } })
        const dialog = await openRevoke()
        fireEvent.change(within(dialog).getByRole("textbox", { name: /Reason for revoking/ }), { target: { value: "Late" } })
        confirmRevoke(dialog)
        expect(await screen.findByText("That revelation had already ended.")).toBeInTheDocument()
        expect(screen.queryByRole("alert")).not.toBeInTheDocument()
    })

    it("V27: a revoke refused for authority or because the revelation is gone is explained and re-read", async () => {
        const first = setup()
        server403(first.server)
        const dialog = await openRevoke()
        fireEvent.change(within(dialog).getByRole("textbox", { name: /Reason for revoking/ }), { target: { value: "Mine" } })
        first.world.canReveal = false
        confirmRevoke(dialog)
        const notice = await screen.findByRole("alert")
        expect(notice).toHaveTextContent("You no longer have authority to reveal this character.")
        expect(within(notice).getByText("Mine")).toBeInTheDocument()
        await vi.waitFor(() => expect(screen.queryByRole("button", { name: /^Revoke/ })).not.toBeInTheDocument())
        expect(first.readPage).toHaveBeenCalled()
    })

    it("V27: a 404 for the revelation says so and re-reads the list", async () => {
        const { server, world } = setup()
        server.on("POST", `${LIST}/r-1/revoke`, refused(404))
        const dialog = await openRevoke()
        fireEvent.change(within(dialog).getByRole("textbox", { name: /Reason for revoking/ }), { target: { value: "Gone" } })
        world.rows = []
        confirmRevoke(dialog)
        expect(await screen.findByRole("alert")).toHaveTextContent("That revelation is no longer available.")
        await vi.waitFor(() => expect(screen.queryByText("Pia Player")).not.toBeInTheDocument())
        expect(revokes(server)).toHaveLength(1)
    })

    it("V28: revoking one of two revelations that reach the same member leaves the other live", async () => {
        const { server, world } = setup({
            rows: [
                row({ character_revelation_id: "r-1", created_at: "2026-11-19T10:00:00Z" }),
                row({ character_revelation_id: "r-2", audience_kind: "campaign_current", target_member_name: null, created_at: "2026-11-18T10:00:00Z", audience_size: 2, snapshot_members: [{ campaign_membership_id: "m-1", display_name: "Pia Player", added_at: "2026-11-18T10:00:00Z", removed_at: null, removal_reason: null }] }),
            ],
        })
        const dialog = await openRevoke()
        fireEvent.change(within(dialog).getByRole("textbox", { name: /Reason for revoking/ }), { target: { value: "One of two" } })
        world.rows = [
            row({ character_revelation_id: "r-1", live: false, ended_at: "2026-11-21T10:00:00Z", end_reason: "revoked" }),
            (world.rows as object[])[1]!,
        ]
        confirmRevoke(dialog)
        await vi.waitFor(() => expect(revokes(server)).toHaveLength(1))
        const visible = within(await screen.findByRole("region", { name: "Visible to" }))
        expect(visible.getAllByText("Campaign members at the time (2)").length).toBeGreaterThan(0)
        expect(within(screen.getByRole("region", { name: "Ended" })).getByText("Pia Player")).toBeInTheDocument()
        expect(screen.getAllByRole("button", { name: /^Revoke/ })).toHaveLength(1)
    })
})

function server403(server: MockServer) {
    server.on("POST", `${LIST}/r-1/revoke`, refused(403, "character_reveal_required"))
}

describe("CharacterRevelationsSection: requests and late answers (V29, V30)", () => {
    it("V29: a create and a revoke send only their own request and a list re-read", async () => {
        const { server } = setup()
        const form = await openForm()
        typeReason("Only this")
        submitForm(form)
        await screen.findByText("Revealed to the campaign members now.")
        const dialog = await openRevoke()
        fireEvent.change(within(dialog).getByRole("textbox", { name: /Reason for revoking/ }), { target: { value: "And this" } })
        confirmRevoke(dialog)
        await screen.findByText("Revocation saved.")
        const paths = new Set(server.calls.map((c) => `${c.method} ${c.path}`))
        expect([...paths].sort()).toEqual([`GET ${LIST}`, `POST ${LIST}`, `POST ${LIST}/r-1/revoke`].sort())
    })

    it("V30: a create still pending when the person moves to another character is discarded", async () => {
        const { server, router } = setup()
        server.on("GET", "/campaigns/c1/characters/ch2/revelations", { body: { character_id: "ch2", can_reveal: true, revelations: [] } })
        let answer: (r: { status: number; body: unknown }) => void = () => undefined
        server.on("POST", LIST, () => new Promise((resolve) => (answer = resolve)))
        const form = await openForm()
        typeReason("In flight")
        submitForm(form)
        await vi.waitFor(() => expect(creates(server)).toHaveLength(1))
        await act(async () => {
            void router.navigate("/app/c1/characters/ch2/public-profile")
        })
        expect(await screen.findByText("This character hasn't been revealed to anyone.")).toBeInTheDocument()
        await act(async () => {
            answer({ status: 201, body: { character_revelation_id: "r-late", created: true } })
        })
        expect(screen.queryByText(/Revealed to/)).not.toBeInTheDocument()
        expect(screen.queryByText("Pia Player")).not.toBeInTheDocument()
        expect(server.callsTo("GET", LIST)).toHaveLength(1)
    })

    it("V30: a late refusal for the first character does not touch the second", async () => {
        const { server, router } = setup()
        server.on("GET", "/campaigns/c1/characters/ch2/revelations", { body: { character_id: "ch2", can_reveal: true, revelations: [] } })
        let answer: (r: { status: number; body: unknown }) => void = () => undefined
        server.on("POST", LIST, () => new Promise((resolve) => (answer = resolve)))
        const form = await openForm()
        typeReason("Late no")
        submitForm(form)
        await vi.waitFor(() => expect(creates(server)).toHaveLength(1))
        await act(async () => {
            void router.navigate("/app/c1/characters/ch2/public-profile")
        })
        await screen.findByText("This character hasn't been revealed to anyone.")
        await act(async () => {
            answer(refused(403, "character_reveal_required") as { status: number; body: unknown })
        })
        expect(screen.queryByRole("alert")).not.toBeInTheDocument()
        expect(screen.getByRole("button", { name: "Reveal" })).toBeInTheDocument()
    })
})

// The corrections of the independent review (R-S02-2, R-S02-3).
const withoutManage = () =>
    bootstrapWith({ campaigns: [{ ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c1", capabilities: ["canon.edit"] }] })
const withManage = () =>
    bootstrapWith({
        campaigns: [{ ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c1", capabilities: ["canon.edit", "access.manage"] }],
    })
const refreshSession = () => fireEvent.click(screen.getByRole("button", { name: "Refresh session" }))

describe("CharacterRevelationsSection: access.manage lost mid-form (R-S02-2)", () => {
    async function pickMember(server: MockServer) {
        const form = await openForm()
        fireEvent.click(within(form).getByRole("radio", { name: "One member" }))
        const select = await within(form).findByRole("combobox", { name: /Member/ })
        fireEvent.change(select, { target: { value: "m-1" } })
        typeReason("Because")
        expect(server.callsTo("GET", OVERVIEW)).toHaveLength(1)
        return form
    }
    const noneChecked = (form: HTMLElement) =>
        within(form).getAllByRole("radio").every((r) => !(r as HTMLInputElement).checked)

    it("clears the selection, offers no target and sends no targeted write; campaign-wide still works", async () => {
        const { server } = setup({ capabilities: ["canon.edit", "access.manage"], onRefresh: async () => withoutManage() })
        const form = await pickMember(server)
        refreshSession()
        await vi.waitFor(() =>
            expect(within(form).queryByRole("radio", { name: /One member|One access group/ })).not.toBeInTheDocument(),
        )
        expect(within(form).queryByRole("combobox", { name: /Member/ })).not.toBeInTheDocument()
        expect(within(form).getByText("To reveal to one member or group, ask someone who manages campaign access.")).toBeInTheDocument()
        expect(noneChecked(form)).toBe(true)
        // Submitting what is left sends nothing: it does not turn into a wider audience.
        submitForm(form)
        expect(await screen.findAllByText("Choose who to reveal to.")).not.toHaveLength(0)
        expect(creates(server)).toHaveLength(0)
        expect(server.callsTo("GET", OVERVIEW)).toHaveLength(1)
        // The campaign-wide choice is still the person's to make, and sends no target.
        fireEvent.click(within(form).getByRole("radio", { name: "Everyone in the campaign now" }))
        submitForm(form)
        await vi.waitFor(() => expect(creates(server)).toHaveLength(1))
        expect(creates(server)[0]!.body).toEqual({ audience_kind: "campaign_current", reason: "Because" })
    })

    it("does not bring the old selection back when the right returns", async () => {
        let next = withoutManage()
        const { server } = setup({ capabilities: ["canon.edit", "access.manage"], onRefresh: async () => next })
        const form = await pickMember(server)
        refreshSession()
        await vi.waitFor(() => expect(within(form).queryByRole("radio", { name: "One member" })).not.toBeInTheDocument())
        next = withManage()
        refreshSession()
        await within(form).findByRole("radio", { name: "One member" })
        expect(noneChecked(form)).toBe(true)
        expect(within(form).queryByRole("combobox", { name: /Member/ })).not.toBeInTheDocument()
        submitForm(form)
        expect(creates(server)).toHaveLength(0)
    })

    it("offers no retry of a failed targeted create once the right is lost", async () => {
        const { server } = setup({ capabilities: ["canon.edit", "access.manage"], onRefresh: async () => withoutManage() })
        const form = await pickMember(server)
        server.on("POST", LIST, refused(500))
        submitForm(form)
        await screen.findByRole("button", { name: "Retry" })
        expect(creates(server)).toHaveLength(1)
        refreshSession()
        await vi.waitFor(() => expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument())
        expect(creates(server)).toHaveLength(1)
    })
})

describe("CharacterRevelationsSection: focus after a confirmed write whose re-read fails (R-S02-3)", () => {
    it("create: focus goes to the section heading, not body, while Reveal is disabled", async () => {
        const { server } = setup()
        const form = await openForm()
        typeReason("Confirmed")
        server.on("GET", LIST, refused(500))
        submitForm(form)
        await screen.findAllByText(/The latest revelations could not be loaded/)
        expect(screen.getByRole("button", { name: "Reveal" })).toBeDisabled()
        await vi.waitFor(() => expect(screen.getByRole("heading", { name: "Revelations" })).toHaveFocus())
    })

    it("revoke: focus goes to the section heading when the re-read fails", async () => {
        const { server } = setup()
        const dialog = await openRevoke()
        fireEvent.change(within(dialog).getByRole("textbox", { name: /Reason for revoking/ }), { target: { value: "Done" } })
        server.on("GET", LIST, refused(500))
        confirmRevoke(dialog)
        await screen.findAllByText(/The latest revelations could not be loaded/)
        await vi.waitFor(() => expect(screen.getByRole("heading", { name: "Revelations" })).toHaveFocus())
    })

    it("focus the person moved to another control during the write is left there, on a failed or a good re-read", async () => {
        for (const readFails of [true, false]) {
            const { server, unmount } = setup()
            const form = await openForm()
            typeReason("Mine")
            let answer: (value: { status: number; body: object }) => void = () => undefined
            server.on("POST", LIST, () => new Promise((resolve) => (answer = resolve)))
            submitForm(form)
            await vi.waitFor(() => expect(creates(server)).toHaveLength(1))
            const other = screen.getByRole("button", { name: "Refresh session" })
            other.focus()
            if (readFails) server.on("GET", LIST, refused(500))
            await act(async () => answer({ status: 201, body: { character_revelation_id: "r-new", created: true } }))
            await vi.waitFor(() => expect(screen.queryByRole("form", { name: "Reveal this character" })).not.toBeInTheDocument())
            expect(other).toHaveFocus()
            unmount()
            vi.unstubAllGlobals()
        }
    })
})

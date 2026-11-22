import { act, fireEvent, screen, waitFor, within } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { useSession } from "../context/SessionContext"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import type { MockResponse, MockServer } from "../test/authoringHarness"
import type { AccessResourceGrantSummary, CampaignAccessOverview } from "../types/accessOverview"
import { CampaignAccessPage } from "./CampaignAccessPage"

vi.mock("../components/InvitationsSection", () => ({ InvitationsSection: () => null }))

// Acceptance cases O1 to O16 of docs/delivery/p15-c02-s04-character-denies-plan.md (T01: the offer), through the
// real Access page, overview boundary, forms and hooks. Only the network and the session context are replaced.

const OVERVIEW = "/campaigns/c1/access-overview"
const GRANTS = "/campaigns/c1/resource-grants"
const ARIA = "ch-aria"
const BRAM = "ch-bram"

const DENIABLE = [
    { capability_id: "cap-view", code: "campaign.view", display_name: "View Campaign" },
    { capability_id: "cap-edit", code: "canon.edit", display_name: "Edit Canon" },
]
const GRANTABLE = [
    { capability_id: "cap-full", code: "character.view_full", display_name: "View Character Full Detail", target_type: "character" },
    { capability_id: "cap-ctl", code: "character.control", display_name: "Control Character", target_type: "character" },
    { capability_id: "cap-ent", code: "campaign.view", display_name: "View Campaign", target_type: "entity" },
    { capability_id: "cap-ent2", code: "canon.edit", display_name: "Edit Canon", target_type: "entity" },
]

function member(id: string, name: string, grants: AccessResourceGrantSummary[] = []) {
    return {
        campaign_membership_id: id,
        user_id: id === "m1" ? sessionBootstrapFixture.user.user_id : `user-${id}`,
        display_name: name,
        status_code: "active",
        status_display_name: "Active",
        joined_at: "2026-01-01T00:00:00Z",
        account_is_active: true,
        roles: [],
        character_relationships: [],
        grants,
    }
}

function group(id: string, name: string, status: "active" | "archived" = "active", grants: AccessResourceGrantSummary[] = []) {
    return {
        access_group_id: id,
        name,
        description: null,
        status_code: status,
        status_display_name: status === "active" ? "Active" : "Archived",
        created_at: "2026-01-01T00:00:00Z",
        members: [],
        grants,
    }
}

function denyGrant(id: string, code: string, character: string): AccessResourceGrantSummary {
    return {
        resource_grant_id: id,
        capability_code: code,
        capability_display_name: code === "canon.edit" ? "Edit Canon" : "View Campaign",
        effect: "deny",
        target_type: "entity",
        target_id: character,
        target_display_name: character === ARIA ? "Aria" : "Bram",
        reason: null,
        granted_at: "2026-02-01T00:00:00Z",
        expires_at: null,
    }
}

function overviewWith(over: Partial<CampaignAccessOverview> = {}): CampaignAccessOverview {
    return {
        members: [member("m1", "Olga Owner"), member("m2", "Pip Player")],
        assignable_roles: [],
        assignable_characters: [
            { character_id: ARIA, display_name: "Aria" },
            { character_id: BRAM, display_name: "Bram" },
        ],
        assignable_relationship_types: [],
        grantable_resource_capabilities: GRANTABLE,
        deniable_character_capabilities: DENIABLE,
        access_groups: [group("g1", "Night Watch"), group("g2", "Old Guard", "archived")],
        ...over,
    }
}

const bootstrap = (caps: string[] = ["access.manage"]) =>
    bootstrapWith({
        campaigns: [{ ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c1", capabilities: caps }],
    })

interface SetupOptions {
    overview?: () => CampaignAccessOverview
    post?: (body: unknown) => MockResponse | Promise<MockResponse>
    onRefresh?: () => Promise<ReturnType<typeof bootstrap> | null>
}

// A control that asks the shell for the authoritative session, as the app does after a write.
function Host() {
    const { refresh } = useSession()
    return (
        <>
            <CampaignAccessPage />
            <button type="button" onClick={() => void refresh()}>
                Refresh session
            </button>
        </>
    )
}

function setup(options: SetupOptions = {}) {
    const state = { overview: options.overview ?? (() => overviewWith()) }
    const server = installMockServer()
    server.on("GET", OVERVIEW, () => ({ body: state.overview() }))
    server.on("POST", GRANTS, (call) => options.post?.(call.body) ?? { status: 201, body: { resource_grant_id: "new-grant" } })
    const rendered = renderAuthoringRoutes({
        initialEntry: "/app/c1/access",
        bootstrap: bootstrap(),
        routes: [
            { path: "/app/:campaignId/access", element: <Host /> },
            { path: "/app/:campaignId/elsewhere", element: <p>Elsewhere</p> },
        ],
        onRefresh: options.onRefresh,
    })
    return { server, state, ...rendered }
}

const posts = (server: MockServer) => server.callsTo("POST", GRANTS)
const reads = (server: MockServer) => server.callsTo("GET", OVERVIEW)

async function cardOf(name: string): Promise<HTMLElement> {
    const heading = await screen.findByText(name, { selector: "summary strong" })
    return heading.closest("details") as HTMLElement
}

async function openForm(card: HTMLElement) {
    fireEvent.click(within(card).getByRole("button", { name: /^Add (direct )?resource access$/ }))
    return within(card).getByRole("combobox", { name: /^Add (direct )?resource access for/ })
}

async function chooseDenyKind(card: HTMLElement) {
    const typeSelect = await openForm(card)
    fireEvent.change(typeSelect, { target: { value: "character_deny" } })
}

const characterSelect = (card: HTMLElement) => within(card).getByRole("combobox", { name: "Character" })
const permissionSelect = (card: HTMLElement) => within(card).getByRole("combobox", { name: "What to deny" })
const confirmBox = (card: HTMLElement) => within(card).getByRole("checkbox", { name: /I understand this explicitly denies/ })
const addButton = (card: HTMLElement) => within(card).getByRole("button", { name: "Add" })

async function fillDeny(card: HTMLElement, character = ARIA, code = "canon.edit") {
    await chooseDenyKind(card)
    fireEvent.change(characterSelect(card), { target: { value: character } })
    fireEvent.change(permissionSelect(card), { target: { value: code } })
    fireEvent.click(confirmBox(card))
}

const optionTexts = (select: HTMLElement) =>
    within(select).getAllByRole("option").map((option) => option.textContent)

async function typeOptions(card: HTMLElement) {
    return optionTexts(await openForm(card))
}

describe("O1 to O3: when the kind is offered and what it leaves alone", () => {
    it("O1: a member form lists Character (deny only) only with a non-empty server list and a character", async () => {
        setup()
        expect(await typeOptions(await cardOf("Pip Player"))).toContain("Character (deny only)")
    })

    it.each([
        ["an empty server list", { deniable_character_capabilities: [] }],
        ["a missing field (an older fixture)", { deniable_character_capabilities: undefined }],
        ["no character to choose", { assignable_characters: [] }],
    ])("O1: it is absent with %s", async (_label, over) => {
        setup({ overview: () => overviewWith(over as Partial<CampaignAccessOverview>) })
        const card = await cardOf("Pip Player")
        const types = await typeOptions(card).catch(() => [] as (string | null)[])
        expect(types).not.toContain("Character (deny only)")
    })

    it("O2: a group form offers it too, and an archived group has no form at all", async () => {
        setup()
        const watch = await cardOf("Night Watch")
        expect(await typeOptions(watch)).toContain("Character (deny only)")
        const old = await cardOf("Old Guard")
        expect(within(old).queryByRole("button", { name: "Add resource access" })).not.toBeInTheDocument()
    })

    it("O3: the existing kinds, their order and their permission lists are identical with and without the field", async () => {
        const collect = async (over: Partial<CampaignAccessOverview>) => {
            const { unmount } = setup({ overview: () => overviewWith(over) })
            const card = await cardOf("Pip Player")
            const typeSelect = await openForm(card)
            const types = optionTexts(typeSelect).filter((text) => text !== "Character (deny only)")
            fireEvent.change(typeSelect, { target: { value: "character" } })
            const allow = optionTexts(within(card).getByRole("combobox", { name: "Permission" }))
            fireEvent.click(within(card).getByRole("radio", { name: "Deny" }))
            const deny = optionTexts(within(card).getByRole("combobox", { name: "Permission" }))
            unmount()
            return { types, allow, deny }
        }
        const without = await collect({ deniable_character_capabilities: undefined })
        const withField = await collect({})
        expect(withField).toEqual(without)
        // Choosing Character still offers only character.* codes.
        expect(withField.allow).toEqual(["View Character Full Detail", "Control Character"])
    })
})

describe("O4 to O8: the fields and the request", () => {
    it("O4 and O5: no Allow, the effect is stated, and nothing is chosen for the user", async () => {
        setup()
        const card = await cardOf("Pip Player")
        await chooseDenyKind(card)
        expect(within(card).queryByRole("radio", { name: "Allow" })).not.toBeInTheDocument()
        expect(within(card).getByText(/Effect: Deny/)).toBeInTheDocument()
        expect(characterSelect(card)).toHaveValue("")
        expect(permissionSelect(card)).toHaveValue("")
        expect(permissionSelect(card)).toBeDisabled()
        expect(addButton(card)).toBeDisabled()
        fireEvent.change(characterSelect(card), { target: { value: ARIA } })
        expect(addButton(card)).toBeDisabled()
        fireEvent.change(permissionSelect(card), { target: { value: "campaign.view" } })
        expect(addButton(card)).toBeDisabled()
        fireEvent.click(confirmBox(card))
        expect(addButton(card)).toBeEnabled()
        // Another character clears the permission: nothing carries to a different target.
        fireEvent.change(characterSelect(card), { target: { value: BRAM } })
        expect(permissionSelect(card)).toHaveValue("campaign.view")
    })

    it("O6: the permissions are the server's, in its order, with the approved words and a hint", async () => {
        setup({
            overview: () =>
                overviewWith({
                    deniable_character_capabilities: [
                        ...DENIABLE,
                        { capability_id: "cap-x", code: "future.thing", display_name: "Future Thing" },
                    ],
                }),
        })
        const card = await cardOf("Pip Player")
        await chooseDenyKind(card)
        fireEvent.change(characterSelect(card), { target: { value: ARIA } })
        expect(optionTexts(permissionSelect(card))).toEqual([
            "Choose what to deny",
            "Everything about this character",
            "Editing this character's profiles",
            "Future Thing",
        ])
        fireEvent.change(permissionSelect(card), { target: { value: "canon.edit" } })
        const hint = within(card).getByText(/Stops them saving this character's public profile/)
        expect(permissionSelect(card)).toHaveAttribute("aria-describedby", hint.id)
        expect(hint).toHaveTextContent(/hides the player's own profile/)
        expect(hint).toHaveTextContent(/does not change what they see of the character or other character editing/)
        fireEvent.change(permissionSelect(card), { target: { value: "campaign.view" } })
        expect(within(card).getByText(/wherever access to a character is checked/)).toBeInTheDocument()
        fireEvent.change(permissionSelect(card), { target: { value: "future.thing" } })
        // An unknown code has no invented hint.
        expect(permissionSelect(card)).not.toHaveAttribute("aria-describedby")
    })

    it("O7: the request writes entity_id with effect deny for a member, and carries the CSRF token and a key", async () => {
        const { server } = setup()
        const card = await cardOf("Pip Player")
        await fillDeny(card, ARIA, "canon.edit")
        fireEvent.click(addButton(card))
        await vi.waitFor(() => expect(posts(server)).toHaveLength(1))
        const call = posts(server)[0]!
        expect(call.body).toEqual({
            capability_code: "canon.edit",
            effect: "deny",
            grantee_campaign_membership_id: "m2",
            entity_id: ARIA,
        })
        expect(call.headers["X-CSRF-Token"]).toBe("test-csrf-token")
        expect(call.headers["Idempotency-Key"]).toMatch(/\S/)
    })

    it("O7: for a group the one grantee column is the group", async () => {
        const { server } = setup()
        const card = await cardOf("Night Watch")
        await fillDeny(card, BRAM, "campaign.view")
        fireEvent.click(addButton(card))
        await vi.waitFor(() => expect(posts(server)).toHaveLength(1))
        expect(posts(server)[0]!.body).toEqual({
            capability_code: "campaign.view",
            effect: "deny",
            grantee_access_group_id: "g1",
            entity_id: BRAM,
        })
    })

    it("O8: a permission already denied for this grantee and character is not offered, and with both taken the form says so", async () => {
        setup({
            overview: () =>
                overviewWith({
                    members: [
                        member("m1", "Olga Owner"),
                        member("m2", "Pip Player", [denyGrant("g-1", "campaign.view", ARIA)]),
                    ],
                }),
        })
        const card = await cardOf("Pip Player")
        await chooseDenyKind(card)
        fireEvent.change(characterSelect(card), { target: { value: ARIA } })
        expect(optionTexts(permissionSelect(card))).toEqual(["Choose what to deny", "Editing this character's profiles"])
        // Another character is untouched by that deny.
        fireEvent.change(characterSelect(card), { target: { value: BRAM } })
        expect(optionTexts(permissionSelect(card))).toHaveLength(3)
    })

    it("O8: with both denials in place there is no permission to add", async () => {
        setup({
            overview: () =>
                overviewWith({
                    members: [
                        member("m1", "Olga Owner"),
                        member("m2", "Pip Player", [denyGrant("g-1", "campaign.view", ARIA), denyGrant("g-2", "canon.edit", ARIA)]),
                    ],
                }),
        })
        const card = await cardOf("Pip Player")
        await chooseDenyKind(card)
        fireEvent.change(characterSelect(card), { target: { value: ARIA } })
        expect(within(card).getByText("Both denials are already in place for this character.")).toBeInTheDocument()
        expect(within(card).queryByRole("combobox", { name: "What to deny" })).not.toBeInTheDocument()
        fireEvent.click(confirmBox(card))
        expect(addButton(card)).toBeDisabled()
    })
})

describe("O9 and O10: pending and success", () => {
    it("O9: every control is disabled while pending and a second submit sends nothing", async () => {
        let release: (value: MockResponse) => void = () => {}
        const { server } = setup({ post: () => new Promise<MockResponse>((resolve) => (release = resolve)) })
        const card = await cardOf("Pip Player")
        await fillDeny(card)
        fireEvent.click(addButton(card))
        const busy = await within(card).findByRole("button", { name: "Adding…" })
        expect(busy).toBeDisabled()
        expect(busy).toHaveAttribute("aria-busy", "true")
        for (const control of [characterSelect(card), permissionSelect(card), confirmBox(card)]) {
            expect(control).toBeDisabled()
        }
        fireEvent.submit(busy.closest("form")!)
        expect(posts(server)).toHaveLength(1)
        await act(async () => release({ status: 201, body: { resource_grant_id: "n" } }))
    })

    it("O10: success announces in the persistent region and re-reads the overview, whose grant is then shown", async () => {
        let added = false
        const { server, container } = setup({
            overview: () =>
                overviewWith({
                    members: [
                        member("m1", "Olga Owner"),
                        member("m2", "Pip Player", added ? [denyGrant("g-new", "canon.edit", ARIA)] : []),
                    ],
                }),
            post: () => {
                added = true
                return { status: 201, body: { resource_grant_id: "g-new" } }
            },
        })
        const card = await cardOf("Pip Player")
        await fillDeny(card)
        const before = reads(server).length
        fireEvent.click(addButton(card))
        await vi.waitFor(() => expect(container.querySelector(".campaign-access-page__announcement")).toHaveTextContent("Denial added."))
        await vi.waitFor(() => expect(reads(server).length).toBeGreaterThan(before))
        const fresh = await cardOf("Pip Player")
        await vi.waitFor(() => expect(within(fresh).getByText(/Edit Canon/)).toBeInTheDocument())
        expect(within(fresh).getByText(/on Aria/)).toBeInTheDocument()
    })
})

describe("O11 to O14: refusals and the unknown outcome", () => {
    it("O11: a network error keeps the form and its selection, and Try again resends the same request with the same key", async () => {
        let attempts = 0
        const { server } = setup({
            post: () => {
                attempts += 1
                return attempts === 1 ? { networkError: true } : { status: 201, body: { resource_grant_id: "n" } }
            },
        })
        const card = await cardOf("Pip Player")
        await fillDeny(card, ARIA, "canon.edit")
        fireEvent.click(addButton(card))
        expect(await within(card).findByText(/We couldn't confirm whether the denial was added\. Trying again sends the same request and can't add it twice\./)).toBeInTheDocument()
        expect(characterSelect(card)).toHaveValue(ARIA)
        expect(permissionSelect(card)).toHaveValue("canon.edit")
        fireEvent.click(within(card).getByRole("button", { name: "Try again" }))
        await vi.waitFor(() => expect(posts(server)).toHaveLength(2))
        const [first, second] = posts(server)
        expect(second!.body).toEqual(first!.body)
        expect(second!.headers["Idempotency-Key"]).toBe(first!.headers["Idempotency-Key"])
    })

    it("O11: a 5xx is the same unknown outcome, and changing the selection sends a new key", async () => {
        const { server } = setup({ post: () => ({ status: 503, body: {} }) })
        const card = await cardOf("Pip Player")
        await fillDeny(card, ARIA, "canon.edit")
        fireEvent.click(addButton(card))
        await within(card).findByText(/We couldn't confirm whether the denial was added/)
        fireEvent.change(characterSelect(card), { target: { value: BRAM } })
        fireEvent.change(permissionSelect(card), { target: { value: "canon.edit" } })
        fireEvent.click(within(card).getByRole("button", { name: "Try again" }))
        await vi.waitFor(() => expect(posts(server)).toHaveLength(2))
        expect(posts(server)[1]!.headers["Idempotency-Key"]).not.toBe(posts(server)[0]!.headers["Idempotency-Key"])
        expect((posts(server)[1]!.body as { entity_id: string }).entity_id).toBe(BRAM)
    })

    it("O12: a 409 says the denial may already be in place and offers a read, sending nothing", async () => {
        const { server } = setup({ post: () => ({ status: 409, body: { error: { code: "x", message: "SECRET" } } }) })
        const card = await cardOf("Pip Player")
        await fillDeny(card)
        fireEvent.click(addButton(card))
        expect(await within(card).findByText("This denial may already be in place. Refresh the access list to see the current state.")).toBeInTheDocument()
        expect(screen.queryByText(/SECRET/)).not.toBeInTheDocument()
        const before = reads(server).length
        fireEvent.click(within(card).getByRole("button", { name: "Refresh access list" }))
        await vi.waitFor(() => expect(reads(server).length).toBeGreaterThan(before))
        expect(posts(server)).toHaveLength(1)
    })

    it("O13: a 404 says the character or member is no longer available, offers a read and no retry", async () => {
        setup({ post: () => ({ status: 404, body: {} }) })
        const card = await cardOf("Pip Player")
        await fillDeny(card)
        fireEvent.click(addButton(card))
        expect(await within(card).findByText("That character or member is no longer available for a denial.")).toBeInTheDocument()
        expect(within(card).getByRole("button", { name: "Refresh access list" })).toBeInTheDocument()
        expect(within(card).queryByRole("button", { name: "Try again" })).not.toBeInTheDocument()
    })

    it("O13: for a group the 404 names the group", async () => {
        setup({ post: () => ({ status: 404, body: {} }) })
        const card = await cardOf("Night Watch")
        await fillDeny(card)
        fireEvent.click(addButton(card))
        expect(await within(card).findByText("That character or group is no longer available for a denial.")).toBeInTheDocument()
    })

    it("O14: a 403 says access can no longer be managed and offers no retry (the session re-read is T02's R13/R18)", async () => {
        setup({ post: () => ({ status: 403, body: {} }) })
        const card = await cardOf("Pip Player")
        await fillDeny(card)
        fireEvent.click(addButton(card))
        expect(await within(card).findByText("You no longer have permission to manage access.")).toBeInTheDocument()
        expect(within(card).queryByRole("button", { name: "Try again" })).not.toBeInTheDocument()
    })
})

describe("O15 and O16: authority loss and navigation while pending", () => {
    it("O15: losing access.manage mid-request unmounts the form, announces nothing, and a late response does not render", async () => {
        let release: (value: MockResponse) => void = () => {}
        const { server, container } = setup({
            post: () => new Promise<MockResponse>((resolve) => (release = resolve)),
            onRefresh: async () => bootstrap([]),
        })
        const card = await cardOf("Pip Player")
        await fillDeny(card)
        fireEvent.click(addButton(card))
        await vi.waitFor(() => expect(posts(server)).toHaveLength(1))
        const readsBefore = reads(server).length
        // The session read that no longer grants access.manage is applied in place.
        fireEvent.click(screen.getByRole("button", { name: "Refresh session" }))
        expect(await screen.findByRole("heading", { name: "Access unavailable" })).toBeInTheDocument()
        expect(screen.queryByRole("combobox", { name: "Character" })).not.toBeInTheDocument()
        await act(async () => release({ status: 201, body: { resource_grant_id: "late" } }))
        expect(container.querySelector(".campaign-access-page__announcement")).toHaveTextContent("")
        expect(screen.queryByText("Denial added.")).not.toBeInTheDocument()
        expect(reads(server).length).toBe(readsBefore)
    })

    it("O16: leaving the page mid-request aborts it, nothing is announced, and coming back mounts a fresh closed form", async () => {
        let release: (value: MockResponse) => void = () => {}
        const { server, router } = setup({ post: () => new Promise<MockResponse>((resolve) => (release = resolve)) })
        const card = await cardOf("Pip Player")
        await fillDeny(card)
        fireEvent.click(addButton(card))
        await vi.waitFor(() => expect(posts(server)).toHaveLength(1))
        await act(async () => router.navigate("/app/c1/elsewhere"))
        expect(await screen.findByText("Elsewhere")).toBeInTheDocument()
        await act(async () => release({ status: 201, body: { resource_grant_id: "late" } }))
        await act(async () => router.navigate("/app/c1/access"))
        const fresh = await cardOf("Pip Player")
        expect(within(fresh).queryByRole("combobox", { name: "Character" })).not.toBeInTheDocument()
        expect(within(fresh).getByRole("button", { name: "Add direct resource access" })).toBeInTheDocument()
        expect(screen.queryByText("Denial added.")).not.toBeInTheDocument()
        await waitFor(() => expect(reads(server).length).toBeGreaterThanOrEqual(2))
    })
})

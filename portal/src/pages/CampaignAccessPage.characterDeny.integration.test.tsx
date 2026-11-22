import { act, fireEvent, screen, waitFor, within } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import type { MockResponse } from "../test/authoringHarness"
import type { CampaignAccessOverview } from "../types/accessOverview"
import {
    ARIA,
    BRAM,
    DENIABLE,
    addButton,
    cardOf,
    characterSelect,
    chooseDenyKind,
    confirmBox,
    denyGrant,
    fillDeny,
    member,
    openForm,
    optionTexts,
    overviewWith,
    permissionSelect,
    posts,
    reads,
    setup,
    typeOptions,
    bootstrap,
} from "../test/characterDenyHarness"

vi.mock("../components/InvitationsSection", () => ({ InvitationsSection: () => null }))

// Acceptance cases O1 to O16 of docs/delivery/p15-c02-s04-character-denies-plan.md (T01: the offer), through the
// real Access page, overview boundary, forms and hooks. Only the network and the session context are replaced.

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
        await vi.waitFor(() => expect(within(fresh).getByText("Denied: editing Aria's profiles")).toBeInTheDocument())
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
        // S04-R1: no retry means the form cannot send it again, not only that no button says so.
        expect(addButton(card)).toBeDisabled()
    })

    it("O13: for a group the 404 names the group", async () => {
        setup({ post: () => ({ status: 404, body: {} }) })
        const card = await cardOf("Night Watch")
        await fillDeny(card)
        fireEvent.click(addButton(card))
        expect(await within(card).findByText("That character or group is no longer available for a denial.")).toBeInTheDocument()
        expect(addButton(card)).toBeDisabled()
    })

    // S04-R1: after a definitive 404 the same form cannot send the refused attempt again, for a member or a group.
    it.each([
        ["a member", "Pip Player"],
        ["a group", "Night Watch"],
    ])("O13 (S04-R1): after a 404 for %s Add is disabled and a repeated submit sends no second POST", async (_kind, name) => {
        const { server } = setup({ post: () => ({ status: 404, body: {} }) })
        const card = await cardOf(name)
        await fillDeny(card)
        fireEvent.click(addButton(card))
        await within(card).findByText(/is no longer available for a denial\./)
        expect(posts(server)).toHaveLength(1)
        expect(addButton(card)).toBeDisabled()
        // A click on the disabled button, and a submit of the form itself (Enter in a field), both send nothing.
        fireEvent.click(addButton(card))
        fireEvent.submit(addButton(card).closest("form") as HTMLFormElement)
        await act(async () => {
            await Promise.resolve()
        })
        expect(posts(server)).toHaveLength(1)
        // Changing the selections does not unlock it either: only a refresh or cancelling does.
        fireEvent.change(characterSelect(card), { target: { value: BRAM } })
        fireEvent.change(permissionSelect(card), { target: { value: "canon.edit" } })
        expect(addButton(card)).toBeDisabled()
        fireEvent.submit(addButton(card).closest("form") as HTMLFormElement)
        expect(posts(server)).toHaveLength(1)
    })

    it.each([
        ["a member", "Pip Player"],
        ["a group", "Night Watch"],
    ])("O13 (S04-R1): after a 404 for %s a successful refresh gives a fresh form that can send a new attempt", async (_kind, name) => {
        let refused = true
        const { server } = setup({
            post: () => (refused ? { status: 404, body: {} } : { status: 201, body: { resource_grant_id: "new-grant" } }),
        })
        const card = await cardOf(name)
        await fillDeny(card)
        fireEvent.click(addButton(card))
        await within(card).findByText(/is no longer available for a denial\./)
        expect(addButton(card)).toBeDisabled()
        const before = reads(server).length
        fireEvent.click(within(card).getByRole("button", { name: "Refresh access list" }))
        await vi.waitFor(() => expect(reads(server).length).toBeGreaterThan(before))
        expect(posts(server)).toHaveLength(1)
        // The list re-read unmounts the refused form: the card comes back with the add trigger and nothing carried.
        const fresh = await cardOf(name)
        refused = false
        await fillDeny(fresh)
        expect(addButton(fresh)).toBeEnabled()
        fireEvent.click(addButton(fresh))
        await vi.waitFor(() => expect(posts(server)).toHaveLength(2))
        expect(posts(server)[1]!.headers["Idempotency-Key"]).not.toBe(posts(server)[0]!.headers["Idempotency-Key"])
    })

    it.each([
        ["a member", "Pip Player"],
        ["a group", "Night Watch"],
    ])("O13 (S04-R1): after a 404 for %s a failed refresh does not unlock the refused attempt", async (_kind, name) => {
        const { server } = setup({ post: () => ({ status: 404, body: {} }) })
        const card = await cardOf(name)
        await fillDeny(card)
        fireEvent.click(addButton(card))
        await within(card).findByText(/is no longer available for a denial\./)
        // The re-read now fails.
        server.on("GET", "/campaigns/c1/access-overview", { status: 500, body: {} })
        fireEvent.click(within(card).getByRole("button", { name: "Refresh access list" }))
        expect(await screen.findByRole("heading", { name: "Access information unavailable" })).toBeInTheDocument()
        // No form of this attempt is left to submit, and nothing was sent.
        expect(screen.queryByRole("button", { name: "Add" })).not.toBeInTheDocument()
        expect(posts(server)).toHaveLength(1)
    })

    it.each([
        ["a member", "Pip Player"],
        ["a group", "Night Watch"],
    ])("O13 (S04-R1): after a 404 for %s Cancel discards the attempt and reopening follows fresh-selection rules", async (_kind, name) => {
        const { server } = setup({ post: () => ({ status: 404, body: {} }) })
        const card = await cardOf(name)
        await fillDeny(card)
        fireEvent.click(addButton(card))
        await within(card).findByText(/is no longer available for a denial\./)
        fireEvent.click(within(card).getByRole("button", { name: "Cancel" }))
        await chooseDenyKind(card)
        // Nothing chosen, nothing confirmed, no leftover refusal text; Add stays disabled until filled in.
        expect(characterSelect(card)).toHaveValue("")
        expect(addButton(card)).toBeDisabled()
        expect(within(card).queryByText(/is no longer available for a denial\./)).not.toBeInTheDocument()
        fireEvent.change(characterSelect(card), { target: { value: ARIA } })
        fireEvent.change(permissionSelect(card), { target: { value: "canon.edit" } })
        fireEvent.click(confirmBox(card))
        expect(addButton(card)).toBeEnabled()
        fireEvent.click(addButton(card))
        await vi.waitFor(() => expect(posts(server)).toHaveLength(2))
    })

    it.each([
        ["a member", "Pip Player"],
        ["a group", "Night Watch"],
    ])("O13 (S04-R1): a network failure for %s still retries with the same key and body", async (_kind, name) => {
        let n = 0
        const { server } = setup({
            post: () => (++n === 1 ? { status: 500, body: {} } : { status: 201, body: { resource_grant_id: "g" } }),
        })
        const card = await cardOf(name)
        await fillDeny(card)
        fireEvent.click(addButton(card))
        await within(card).findByText(/We couldn't confirm whether the denial was added/)
        expect(within(card).getByRole("button", { name: "Try again" })).toBeEnabled()
        fireEvent.click(within(card).getByRole("button", { name: "Try again" }))
        await vi.waitFor(() => expect(posts(server)).toHaveLength(2))
        expect(posts(server)[1]!.headers["Idempotency-Key"]).toBe(posts(server)[0]!.headers["Idempotency-Key"])
        expect(posts(server)[1]!.body).toEqual(posts(server)[0]!.body)
    })

    it("O14: a 403 says access can no longer be managed and offers no retry (the in-place session re-read is asserted by R13, R18 and the hook tests)", async () => {
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

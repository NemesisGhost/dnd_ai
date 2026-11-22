import { act, fireEvent, screen, within } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import type { MockResponse } from "../test/authoringHarness"
import type { AccessGroupSummary, AccessResourceGrantSummary, CampaignAccessOverview } from "../types/accessOverview"
import {
    ARIA,
    BRAM,
    GRANTS,
    addButton,
    bootstrap,
    cardOf,
    denyGrant,
    fillDeny,
    group,
    member,
    overviewWith,
    posts,
    reads,
    setup,
} from "../test/characterDenyHarness"

vi.mock("../components/InvitationsSection", () => ({ InvitationsSection: () => null }))

// Acceptance cases R1 to R18 of docs/delivery/p15-c02-s04-character-denies-plan.md (T02: display, removal and
// reconciliation), through the real Access page. "Re-read" means a new request whose response is what is rendered.

const REVOKE = (id: string) => `${GRANTS}/${id}/revoke`
const EFFECTIVE = (id: string) => `/campaigns/c1/members/${id}/effective-access`
const announcement = (container: HTMLElement) => container.querySelector(".campaign-access-page__announcement")

const pipWith = (...grants: AccessResourceGrantSummary[]) => member("m2", "Pip Player", grants)
const overviewOf = (grants: AccessResourceGrantSummary[], over: Partial<CampaignAccessOverview> = {}) =>
    overviewWith({ members: [member("m1", "Olga Owner"), pipWith(...grants)], ...over })

const itemOf = (card: HTMLElement, text: string) => within(card).getByText(text).closest("li") as HTMLElement
const removeDenial = (item: HTMLElement) => within(item).getByRole("button", { name: "Remove denial" })
const confirmRemoval = (item: HTMLElement) => fireEvent.click(within(item).getByRole("button", { name: /^(Confirm|Try again)$/ }))

// The card after the list has been read again: the page body is replaced while it loads, so the card a test held
// before a write is detached once the re-read starts. A query against a detached card proves nothing.
async function afterReread(name: string, old: HTMLElement): Promise<HTMLElement> {
    await vi.waitFor(() => expect(old.isConnected).toBe(false))
    return cardOf(name)
}

async function openRemoval(card: HTMLElement, text: string) {
    const item = itemOf(card, text)
    fireEvent.click(removeDenial(item))
    return item
}

function effectiveWith(denials: { code: string; name: string }[]) {
    return {
        display_name: "Pip Player",
        capabilities: [],
        denials: denials.map((d) => ({ capability_code: d.code, target_type: "entity", target_display_name: d.name })),
    }
}

describe("R1 and R2: a character denial is shown in plain words and nothing else changes", () => {
    it("R1: a member's denials read as everything about / editing the character, and only a real character denial does", async () => {
        const decoy: AccessResourceGrantSummary = {
            ...denyGrant("g-3", "canon.edit", "place-9"),
            target_display_name: "The Old Mill",
        }
        const allow: AccessResourceGrantSummary = { ...denyGrant("g-4", "campaign.view", BRAM), effect: "allow" }
        const characterKind: AccessResourceGrantSummary = {
            ...denyGrant("g-5", "character.view_full", ARIA),
            target_type: "character",
            capability_display_name: "View Character Full Detail",
        }
        setup({
            overview: () =>
                overviewOf([denyGrant("g-1", "campaign.view", ARIA), denyGrant("g-2", "canon.edit", ARIA), decoy, allow, characterKind]),
        })
        const card = await cardOf("Pip Player")
        expect(within(card).getByText("Denied: everything about Aria")).toBeInTheDocument()
        expect(within(card).getByText("Denied: editing Aria's profiles")).toBeInTheDocument()
        // A deny whose name is set but whose target is not one of this overview's characters is not a character denial.
        expect(within(card).queryByText(/Denied: .*Old Mill/)).not.toBeInTheDocument()
        expect(within(card).getByText(/Edit Canon/)).toBeInTheDocument()
        // The decoy and the character-kind grant keep the generic wording.
        expect(within(card).getAllByText(/\(Deny\) on/)).toHaveLength(2)
        // An allow and a character-kind grant are rendered exactly as before.
        expect(within(card).getAllByText(/\(Allow\) on/)).toHaveLength(1)
        expect(within(card).getByText(/View Character Full Detail/)).toBeInTheDocument()
        expect(within(card).getAllByText(/^Denied: /)).toHaveLength(2)
    })

    it("R2: a group card says the same", async () => {
        const night: AccessGroupSummary = {
            ...group("g1", "Night Watch"),
            grants: [denyGrant("g-1", "campaign.view", BRAM), denyGrant("g-2", "canon.edit", BRAM)],
        }
        setup({ overview: () => overviewWith({ access_groups: [night] }) })
        const card = await cardOf("Night Watch")
        expect(within(card).getByText("Denied: everything about Bram")).toBeInTheDocument()
        expect(within(card).getByText("Denied: editing Bram's profiles")).toBeInTheDocument()
    })
})

describe("R3, R4 and R12: removal", () => {
    it("R3: Remove denial names the character and the denial, says what may come back, and calls the existing revoke with a key", async () => {
        const { server } = setup({ overview: () => overviewOf([denyGrant("g-1", "campaign.view", ARIA), denyGrant("g-2", "canon.edit", ARIA)]) })
        server.on("POST", REVOKE("g-1"), { body: { resource_grant_id: "g-1" } })
        server.on("POST", REVOKE("g-2"), { body: { resource_grant_id: "g-2" } })
        const card = await cardOf("Pip Player")
        const whole = await openRemoval(card, "Denied: everything about Aria")
        expect(within(whole).getByRole("group", { name: "Remove denial of everything about Aria from Pip Player" })).toBeInTheDocument()
        expect(whole).toHaveTextContent(
            "Remove Pip Player's denial of everything about Aria? They may regain access to Aria from another source, such as a role or relationship.",
        )
        fireEvent.click(within(whole).getByRole("button", { name: "Cancel" }))
        const edit = await openRemoval(card, "Denied: editing Aria's profiles")
        expect(edit).toHaveTextContent("Remove Pip Player's denial of editing Aria's profiles? They may be able to edit Aria's profiles again.")
        confirmRemoval(edit)
        await vi.waitFor(() => expect(server.callsTo("POST", REVOKE("g-2"))).toHaveLength(1))
        expect(server.callsTo("POST", REVOKE("g-1"))).toHaveLength(0)
        expect(server.callsTo("POST", REVOKE("g-2"))[0]!.headers["Idempotency-Key"]).toMatch(/\S/)
    })

    it("R4: success announces Denial removed., re-reads, the denial is gone and focus returns to the card's grants heading", async () => {
        let present = true
        const { server, container } = setup({
            overview: () => overviewOf(present ? [denyGrant("g-1", "canon.edit", ARIA)] : []),
        })
        server.on("POST", REVOKE("g-1"), () => {
            present = false
            return { body: { resource_grant_id: "g-1" } }
        })
        const card = await cardOf("Pip Player")
        const item = await openRemoval(card, "Denied: editing Aria's profiles")
        confirmRemoval(item)
        await vi.waitFor(() => expect(announcement(container)).toHaveTextContent("Denial removed."))
        const fresh = await afterReread("Pip Player", card)
        expect(within(fresh).queryByText(/Denied:/)).not.toBeInTheDocument()
        await vi.waitFor(() => expect(document.activeElement).toBe(document.querySelector('[data-grants-heading="m2"]')))
    })

    it("R4: focus the manager has already moved elsewhere is left alone", async () => {
        let present = true
        let release: (value: MockResponse) => void = () => {}
        const { server } = setup({ overview: () => overviewOf(present ? [denyGrant("g-1", "canon.edit", ARIA)] : []) })
        server.on("POST", REVOKE("g-1"), () => new Promise<MockResponse>((resolve) => (release = resolve)))
        const card = await cardOf("Pip Player")
        confirmRemoval(await openRemoval(card, "Denied: editing Aria's profiles"))
        await vi.waitFor(() => expect(server.callsTo("POST", REVOKE("g-1"))).toHaveLength(1))
        present = false
        const elsewhere = screen.getByRole("link", { name: "Invitations" })
        elsewhere.focus()
        await act(async () => release({ body: { resource_grant_id: "g-1" } }))
        await afterReread("Pip Player", card)
        expect(document.activeElement).toBe(elsewhere)
    })

    it("R12: removing a denial the server had already removed (its 200 no-op) is reported as removed and the re-read decides", async () => {
        // The list on screen is stale: the denial was removed elsewhere, so the server's revoke is its documented
        // no-op (200, nothing written) and the next read has no denial.
        let readsOfList = 0
        const { server, container } = setup({
            overview: () => {
                readsOfList += 1
                return overviewOf(readsOfList === 1 ? [denyGrant("g-1", "campaign.view", ARIA)] : [])
            },
        })
        server.on("POST", REVOKE("g-1"), { body: { resource_grant_id: "g-1" } })
        const card = await cardOf("Pip Player")
        confirmRemoval(await openRemoval(card, "Denied: everything about Aria"))
        await vi.waitFor(() => expect(announcement(container)).toHaveTextContent("Denial removed."))
        const fresh = await afterReread("Pip Player", card)
        expect(within(fresh).queryByText(/Denied:/)).not.toBeInTheDocument()
        expect(server.callsTo("POST", REVOKE("g-1"))).toHaveLength(1)
    })
})

describe("R5 to R9: effective access and the list are read again", () => {
    async function openExplanation(card: HTMLElement) {
        fireEvent.click(within(card).getByRole("button", { name: "Explain access" }))
    }

    it("R5 and R6: with the explanation open, adding re-reads it with the denial and removing re-reads it with the rest", async () => {
        const denies: { id: string; code: string; character: string }[] = []
        let explanations = 0
        const { server } = setup({
            overview: () => overviewOf(denies.map((d) => denyGrant(d.id, d.code, d.character))),
            post: (body) => {
                const request = body as { capability_code: string; entity_id: string }
                denies.push({ id: `g-${denies.length + 1}`, code: request.capability_code, character: request.entity_id })
                return { status: 201, body: { resource_grant_id: `g-${denies.length}` } }
            },
        })
        server.on("GET", EFFECTIVE("m2"), () => {
            explanations += 1
            return {
                body: effectiveWith(denies.map((d) => ({ code: d.code, name: d.character === ARIA ? "Aria" : "Bram" }))),
            }
        })
        server.on("POST", REVOKE("g-1"), () => {
            denies.splice(0, 1)
            return { body: { resource_grant_id: "g-1" } }
        })
        const card = await cardOf("Pip Player")
        await openExplanation(card)
        await within(card).findByText("This member holds no capability in this campaign.")
        expect(explanations).toBe(1)

        await fillDeny(card, ARIA, "campaign.view")
        fireEvent.click(addButton(card))
        const fresh = await afterReread("Pip Player", card)
        await screen.findByText(/campaign\.view — Entity \(Aria\)/)
        expect(explanations).toBeGreaterThanOrEqual(2)

        await fillDeny(fresh, BRAM, "canon.edit")
        fireEvent.click(addButton(fresh))
        const two = await afterReread("Pip Player", fresh)
        await screen.findByText(/canon\.edit — Entity \(Bram\)/)
        expect(screen.getByText(/campaign\.view — Entity \(Aria\)/)).toBeInTheDocument()

        // Remove the first: the explanation is read again, lists the other and not the removed one.
        const item = await openRemoval(two, "Denied: everything about Aria")
        confirmRemoval(item)
        await afterReread("Pip Player", two)
        await screen.findByText(/canon\.edit — Entity \(Bram\)/)
        expect(screen.queryByText(/campaign\.view — Entity \(Aria\)/)).not.toBeInTheDocument()
    })

    // One group holds a denial and Pip; the world answers from this state and a write changes it.
    function groupWorld() {
        const state = { inGroup: true, active: true }
        const overview = () => {
            const night: AccessGroupSummary = {
                ...group("g1", "Night Watch", state.active ? "active" : "archived"),
                members: state.inGroup
                    ? [{ access_group_membership_id: "agm-1", campaign_membership_id: "m2", display_name: "Pip Player", added_at: "2026-01-01T00:00:00Z" }]
                    : [],
                grants: state.active ? [denyGrant("g-1", "campaign.view", ARIA)] : [],
            }
            return overviewWith({ access_groups: [night] })
        }
        const wire = (server: ReturnType<typeof setup>["server"]) => {
            server.on("GET", EFFECTIVE("m2"), () => ({
                body: effectiveWith(state.inGroup && state.active ? [{ code: "campaign.view", name: "Aria" }] : []),
            }))
            server.on("POST", "/campaigns/c1/access-group-memberships/agm-1/remove", () => {
                state.inGroup = false
                return { body: { access_group_membership_id: "agm-1" } }
            })
            server.on("POST", "/campaigns/c1/access-groups/g1/deactivate", () => {
                state.active = false
                return { body: { access_group_id: "g1" } }
            })
        }
        return { overview, wire }
    }

    it("R7: a group's denial reaches an open member explanation, and removing the member from the group re-reads it without the denial", async () => {
        const world = groupWorld()
        const { server } = setup({ overview: world.overview })
        world.wire(server)
        const pip = await cardOf("Pip Player")
        await openExplanation(pip)
        await within(pip).findByText(/campaign\.view — Entity \(Aria\)/)
        const before = server.callsTo("GET", EFFECTIVE("m2")).length

        const night = await cardOf("Night Watch")
        fireEvent.click(within(night).getByRole("button", { name: "Remove from group" }))
        fireEvent.click(within(night).getByRole("button", { name: "Confirm" }))
        await vi.waitFor(() => expect(server.callsTo("GET", EFFECTIVE("m2")).length).toBeGreaterThan(before))
        await afterReread("Pip Player", pip)
        await screen.findByText("This member holds no capability in this campaign.")
        expect(screen.queryByText(/Entity \(Aria\)/)).not.toBeInTheDocument()
    })

    it("R8: deactivating the denying group re-reads the list (its grants gone) and an open explanation without the denial", async () => {
        const world = groupWorld()
        const { server } = setup({ overview: world.overview })
        world.wire(server)
        const pip = await cardOf("Pip Player")
        await openExplanation(pip)
        await within(pip).findByText(/campaign\.view — Entity \(Aria\)/)

        const night = await cardOf("Night Watch")
        expect(within(night).getByText("Denied: everything about Aria")).toBeInTheDocument()
        fireEvent.click(within(night).getByRole("button", { name: "Deactivate" }))
        fireEvent.click(within(night).getByRole("button", { name: "Confirm" }))
        await afterReread("Night Watch", night)
        await screen.findByText("This member holds no capability in this campaign.")
        expect(screen.queryByText(/Denied:/)).not.toBeInTheDocument()
        expect(screen.queryByText(/Entity \(Aria\)/)).not.toBeInTheDocument()
    })

    it("R9: a re-read that drops an archived character drops its denial and its option, and the closed form offers nothing for it", async () => {
        let archived = false
        const { server } = setup({
            overview: () =>
                archived
                    ? overviewOf([denyGrant("g-b", "canon.edit", BRAM)], { assignable_characters: [{ character_id: BRAM, display_name: "Bram" }] })
                    : overviewOf([denyGrant("g-a", "campaign.view", ARIA), denyGrant("g-b", "canon.edit", BRAM)]),
            post: () => {
                archived = true
                return { status: 201, body: { resource_grant_id: "n" } }
            },
        })
        const card = await cardOf("Pip Player")
        expect(within(card).getByText("Denied: everything about Aria")).toBeInTheDocument()
        await fillDeny(card, BRAM, "campaign.view")
        fireEvent.click(addButton(card))
        await vi.waitFor(() => expect(posts(server)).toHaveLength(1))
        const fresh = await afterReread("Pip Player", card)
        expect(within(fresh).queryByText("Denied: everything about Aria")).not.toBeInTheDocument()
        // The form that was open was closed by the re-read; a new one offers only the characters that remain.
        expect(within(fresh).queryByRole("combobox", { name: "Character" })).not.toBeInTheDocument()
        fireEvent.click(within(fresh).getByRole("button", { name: "Add direct resource access" }))
        fireEvent.change(within(fresh).getByRole("combobox", { name: /^Add direct resource access for/ }), { target: { value: "character_deny" } })
        const names = within(within(fresh).getByRole("combobox", { name: "Character" })).getAllByRole("option").map((o) => o.textContent)
        expect(names).toEqual(["Choose a character", "Bram"])
    })
})

describe("R10: a self-denial", () => {
    it("R10: on the caller's own card the session is reloaded, the denial is listed, and the owner can still remove it", async () => {
        let denied = false
        const { server, reload } = setup({
            overview: () => overviewWith({ members: [member("m1", "Olga Owner", denied ? [denyGrant("g-1", "campaign.view", ARIA)] : []), member("m2", "Pip Player")] }),
            post: () => {
                denied = true
                return { status: 201, body: { resource_grant_id: "g-1" } }
            },
        })
        const card = await cardOf("Olga Owner")
        await fillDeny(card, ARIA, "campaign.view")
        fireEvent.click(addButton(card))
        await vi.waitFor(() => expect(reload).toHaveBeenCalledTimes(1))
        const fresh = await afterReread("Olga Owner", card)
        expect(within(fresh).getByText("Denied: everything about Aria")).toBeInTheDocument()
        expect(within(fresh).getByRole("button", { name: "Remove denial" })).toBeInTheDocument()
        expect(posts(server)).toHaveLength(1)
    })
})

describe("R11, R13 to R16: failures, authority and late responses", () => {
    it("R11: a revoke whose outcome is unknown says so and Try again reuses the same key", async () => {
        let attempts = 0
        const { server } = setup({ overview: () => overviewOf([denyGrant("g-1", "canon.edit", ARIA)]) })
        server.on("POST", REVOKE("g-1"), () => {
            attempts += 1
            return attempts === 1 ? { networkError: true } : { body: { resource_grant_id: "g-1" } }
        })
        const card = await cardOf("Pip Player")
        const item = await openRemoval(card, "Denied: editing Aria's profiles")
        confirmRemoval(item)
        expect(await within(item).findByText("We couldn't confirm whether the denial was removed. Trying again sends the same request.")).toBeInTheDocument()
        confirmRemoval(item)
        await vi.waitFor(() => expect(server.callsTo("POST", REVOKE("g-1"))).toHaveLength(2))
        const [first, second] = server.callsTo("POST", REVOKE("g-1"))
        expect(second!.headers["Idempotency-Key"]).toBe(first!.headers["Idempotency-Key"])
    })

    it("R13: a 403 on a revoke re-reads the session in place and says access can no longer be managed", async () => {
        const onRefresh = vi.fn(async () => bootstrap())
        const { server } = setup({ overview: () => overviewOf([denyGrant("g-1", "canon.edit", ARIA)]), onRefresh })
        server.on("POST", REVOKE("g-1"), { status: 403, body: {} })
        const card = await cardOf("Pip Player")
        const item = await openRemoval(card, "Denied: editing Aria's profiles")
        confirmRemoval(item)
        expect(await within(item).findByText("You no longer have permission to manage access.")).toBeInTheDocument()
        await vi.waitFor(() => expect(onRefresh).toHaveBeenCalledTimes(1))
        expect(server.callsTo("POST", REVOKE("g-1"))).toHaveLength(1)
    })

    it("R13: a 404 says the denial is no longer available and offers a read, never a resend", async () => {
        const { server } = setup({ overview: () => overviewOf([denyGrant("g-1", "canon.edit", ARIA)]) })
        server.on("POST", REVOKE("g-1"), { status: 404, body: {} })
        const card = await cardOf("Pip Player")
        const item = await openRemoval(card, "Denied: editing Aria's profiles")
        confirmRemoval(item)
        expect(await within(item).findByText("This denial is no longer available.")).toBeInTheDocument()
        const before = reads(server).length
        fireEvent.click(within(item).getByRole("button", { name: "Refresh access list" }))
        await vi.waitFor(() => expect(reads(server).length).toBeGreaterThan(before))
        expect(server.callsTo("POST", REVOKE("g-1"))).toHaveLength(1)
    })

    it("R14 and R13: a 403 whose fresh session lacks access.manage unmounts the page; a restored session mounts a fresh read with everything closed", async () => {
        let caps: string[] = ["access.manage"]
        const onRefresh = vi.fn(async () => bootstrap(caps))
        const { server, container } = setup({ overview: () => overviewOf([denyGrant("g-1", "canon.edit", ARIA)]), onRefresh })
        server.on("POST", REVOKE("g-1"), () => {
            caps = []
            return { status: 403, body: {} }
        })
        const card = await cardOf("Pip Player")
        const item = await openRemoval(card, "Denied: editing Aria's profiles")
        confirmRemoval(item)
        expect(await screen.findByRole("heading", { name: "Access unavailable" })).toBeInTheDocument()
        expect(screen.queryByText("Pip Player")).not.toBeInTheDocument()
        expect(screen.queryByText("You no longer have permission to manage access.")).not.toBeInTheDocument()
        // The authority comes back through the next session read.
        caps = ["access.manage"]
        const readsBefore = reads(server).length
        fireEvent.click(screen.getByRole("button", { name: "Refresh session" }))
        const fresh = await cardOf("Pip Player")
        await vi.waitFor(() => expect(reads(server).length).toBeGreaterThan(readsBefore))
        expect(within(fresh).queryByRole("button", { name: "Confirm" })).not.toBeInTheDocument()
        expect(within(fresh).queryByRole("combobox", { name: "Character" })).not.toBeInTheDocument()
        expect(announcement(container)).toHaveTextContent("")
        expect(server.callsTo("POST", REVOKE("g-1"))).toHaveLength(1)
    })

    it("R15: a revoke response that arrives after a re-read that already lacks the grant announces nothing and does not move focus", async () => {
        let present = true
        let release: (value: MockResponse) => void = () => {}
        const { server, container } = setup({ overview: () => overviewOf(present ? [denyGrant("g-1", "canon.edit", ARIA)] : []) })
        server.on("GET", EFFECTIVE("m2"), { body: effectiveWith([]) })
        server.on("POST", REVOKE("g-1"), () => new Promise<MockResponse>((resolve) => (release = resolve)))
        const card = await cardOf("Pip Player")
        fireEvent.click(within(card).getByRole("button", { name: "Explain access" }))
        await within(card).findByText("This member holds no capability in this campaign.")
        confirmRemoval(await openRemoval(card, "Denied: editing Aria's profiles"))
        await vi.waitFor(() => expect(server.callsTo("POST", REVOKE("g-1"))).toHaveLength(1))
        // Another path reads the list again, and by then the denial is gone.
        present = false
        fireEvent.click(within(card).getByRole("button", { name: "Refresh access" }))
        await vi.waitFor(() => expect(announcement(container)).toHaveTextContent("Access list refreshed."))
        const readsAfter = reads(server).length
        const focused = document.activeElement
        await act(async () => release({ body: { resource_grant_id: "g-1" } }))
        expect(announcement(container)).toHaveTextContent("Access list refreshed.")
        expect(screen.queryByText("Denial removed.")).not.toBeInTheDocument()
        expect(reads(server).length).toBe(readsAfter)
        expect(document.activeElement).toBe(focused)
    })

    it("R16: nothing the new kind renders or announces carries an id, another grant's reason or a server message", async () => {
        const withReason: AccessResourceGrantSummary = { ...denyGrant("g-secret-id", "canon.edit", ARIA), reason: null }
        const { server, container } = setup({
            overview: () => overviewOf([withReason]),
            post: () => ({ status: 409, body: { error: { code: "x", message: "SERVER-SECRET-TEXT", correlation_id: "corr-77" } } }),
        })
        server.on("POST", REVOKE("g-secret-id"), { status: 404, body: { error: { code: "y", message: "SERVER-SECRET-TEXT" } } })
        const card = await cardOf("Pip Player")
        await fillDeny(card, BRAM, "campaign.view")
        fireEvent.click(addButton(card))
        await within(card).findByText(/This denial may already be in place/)
        const item = await openRemoval(card, "Denied: editing Aria's profiles")
        confirmRemoval(item)
        await within(item).findByText("This denial is no longer available.")
        const rendered = [
            container.textContent ?? "",
            ...Array.from(container.querySelectorAll("[aria-label]")).map((e) => e.getAttribute("aria-label") ?? ""),
        ].join("\n")
        for (const secret of ["SERVER-SECRET-TEXT", "corr-77", "g-secret-id", "ch-aria", "ch-bram", "m2"]) {
            expect(rendered).not.toContain(secret)
        }
        void server
    })
})

describe("R17 and R18: what the existing kinds keep", () => {
    const allowGrant: AccessResourceGrantSummary = {
        resource_grant_id: "g-allow",
        capability_code: "character.view_full",
        capability_display_name: "View Character Full Detail",
        effect: "allow",
        target_type: "character",
        target_id: ARIA,
        target_display_name: "Aria",
        reason: null,
        granted_at: "2026-02-01T00:00:00Z",
        expires_at: null,
    }

    it("R17: an allow grant's line, removal text and failure message are unchanged", async () => {
        const { server } = setup({ overview: () => overviewOf([allowGrant]) })
        server.on("POST", REVOKE("g-allow"), { status: 500, body: {} })
        const card = await cardOf("Pip Player")
        expect(within(card).getByText("View Character Full Detail")).toBeInTheDocument()
        expect(within(card).getByText(/\(Allow\) on/)).toHaveTextContent("View Character Full Detail (Allow) on Aria")
        const item = within(card).getByText(/\(Allow\) on/).closest("li") as HTMLElement
        fireEvent.click(within(item).getByRole("button", { name: "Revoke access" }))
        expect(item).toHaveTextContent("Revoke Pip Player's View Character Full Detail on Aria access? This access may disappear immediately.")
        fireEvent.click(within(item).getByRole("button", { name: "Confirm" }))
        expect(await within(item).findByText("The resource access could not be revoked. Try again.")).toBeInTheDocument()
        expect(within(item).getByRole("button", { name: "Confirm" })).toBeInTheDocument()
    })

    it("R18: a 403 on an existing kind's add re-reads the session in place and changes nothing else", async () => {
        const onRefresh = vi.fn(async () => bootstrap())
        const { server } = setup({ overview: () => overviewOf([]), post: () => ({ status: 403, body: {} }), onRefresh })
        const card = await cardOf("Pip Player")
        fireEvent.click(within(card).getByRole("button", { name: "Add direct resource access" }))
        fireEvent.change(within(card).getByRole("combobox", { name: /^Add direct resource access for/ }), { target: { value: "character" } })
        fireEvent.click(within(card).getByRole("button", { name: "Add" }))
        expect(await within(card).findByText("You do not have permission to make this change.")).toBeInTheDocument()
        await vi.waitFor(() => expect(onRefresh).toHaveBeenCalledTimes(1))
        expect(posts(server)).toHaveLength(1)
    })
})

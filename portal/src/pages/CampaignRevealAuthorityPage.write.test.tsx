import { act, fireEvent, screen, within } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { useSession } from "../context/SessionContext"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { bootstrapWith, installMockServer, renderAuthoringRoutes } from "../test/authoringHarness"
import type { MockServer } from "../test/authoringHarness"
import { CampaignRevealAuthorityPage } from "./CampaignRevealAuthorityPage"

// Acceptance cases M1 to M21 of docs/delivery/p15-c02-s03-reveal-delegations-plan.md (T02: grant and revoke).
// M15 (a superseded confirmation) is a hook lifecycle case; this page cannot reset and replace a write, and the
// hook's own tests (useAuthoringMutation.test.tsx) cover it with real callbacks.

const PATH = "/campaigns/c1/reveal-delegations"
const REVOKE = (id: string) => `${PATH}/${id}/revoke`

const bootstrap = (caps: string[] = ["access.manage"]) =>
    bootstrapWith({
        campaigns: [
            { ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c1", capabilities: caps },
            { ...sessionBootstrapFixture.campaigns[0]!, campaign_id: "c2", capabilities: ["access.manage"] },
        ],
    })

interface World {
    can_manage: boolean
    members: { campaign_membership_id: string; display_name: string; delegation: object | null }[]
    lapsed_delegations: object[]
}

const delegated = { granted_at: "2026-11-01T10:00:00Z", granted_by_name: "Olga Owner" }
const world = (): World => ({
    can_manage: true,
    members: [
        { campaign_membership_id: "m-gm1", display_name: "Gina GM", delegation: delegated },
        { campaign_membership_id: "m-gm2", display_name: "Gus GM", delegation: null },
    ],
    lapsed_delegations: [],
})

const refused = (status: number, code?: string) => ({
    status,
    body: { error: { code, message: "SERVER-SECRET-TEXT", correlation_id: "c" } },
})

function Host() {
    const { refresh } = useSession()
    return (
        <>
            <CampaignRevealAuthorityPage />
            <button type="button" onClick={() => void refresh()}>
                Refresh session
            </button>
        </>
    )
}

function setup({ w = world(), onRefresh }: { w?: World; onRefresh?: () => Promise<ReturnType<typeof bootstrap> | null> } = {}) {
    const state = { w }
    const server = installMockServer()
    server.on("GET", PATH, () => ({ body: state.w }))
    server.on("GET", "/campaigns/c2/reveal-delegations", { body: { ...world(), members: [] } })
    server.on("POST", PATH, { body: { grantee_campaign_membership_id: "m-gm2", character_reveal_delegation_id: "d1", granted: true } })
    server.on("POST", REVOKE("m-gm1"), { body: { grantee_campaign_membership_id: "m-gm1", revoked: true } })
    const refreshes = vi.fn()
    const rendered = renderAuthoringRoutes({
        initialEntry: "/app/c1/access/reveal-authority",
        bootstrap: bootstrap(),
        routes: [
            { path: "/app/:campaignId/access/reveal-authority", element: <Host /> },
            { path: "/app/:campaignId/elsewhere", element: <p>Elsewhere</p> },
        ],
        onRefresh: async () => {
            refreshes()
            return onRefresh === undefined ? bootstrap() : onRefresh()
        },
    })
    return { server, state, refreshes, ...rendered }
}

const grantButton = (name = "Gus GM") => screen.findByRole("button", { name: `Grant reveal authority to ${name}` })
const revokeButton = (name = "Gina GM") => screen.findByRole("button", { name: `Revoke reveal authority from ${name}` })
const grants = (server: MockServer) => server.callsTo("POST", PATH)
const reads = (server: MockServer) => server.callsTo("GET", PATH)
const refreshSession = () => fireEvent.click(screen.getByRole("button", { name: "Refresh session" }))
const typeReason = (dialog: HTMLElement, value: string) =>
    fireEvent.change(within(dialog).getByRole("textbox", { name: /Reason for/ }), { target: { value } })

async function openGrant(name = "Gus GM") {
    const button = await grantButton(name)
    button.focus()
    fireEvent.click(button)
    return screen.findByRole("dialog", { name: new RegExp(`Grant reveal authority to ${name}`) })
}
async function openRevoke(name = "Gina GM") {
    const button = await revokeButton(name)
    button.focus()
    fireEvent.click(button)
    return screen.findByRole("dialog", { name: new RegExp(`Revoke reveal authority from ${name}`) })
}
const confirm = (dialog: HTMLElement, label: "Grant" | "Revoke") => fireEvent.click(within(dialog).getByRole("button", { name: label }))

describe("CampaignRevealAuthorityPage: offer rule and dialogs (M1, M4, M18, M19)", () => {
    it("M1: the grant dialog names the member, needs a reason, and Cancel sends nothing and returns focus to that Grant", async () => {
        const { server } = setup()
        const dialog = await openGrant()
        expect(within(dialog).getByRole("button", { name: "Grant" })).toBeDisabled()
        typeReason(dialog, "x".repeat(1001))
        expect(within(dialog).getByText(/must be 1000 characters or fewer/)).toBeInTheDocument()
        expect(within(dialog).getByRole("button", { name: "Grant" })).toBeDisabled()
        fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }))
        expect(grants(server)).toHaveLength(0)
        await vi.waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
        expect(await grantButton()).toHaveFocus()
    })

    it("M4: the revoke dialog is the same with Revoke wording; Grant is offered where nothing is delegated and Revoke where it is", async () => {
        setup()
        expect(await grantButton("Gus GM")).toBeInTheDocument()
        expect(screen.queryByRole("button", { name: "Grant reveal authority to Gina GM" })).not.toBeInTheDocument()
        const dialog = await openRevoke()
        expect(within(dialog).getByRole("button", { name: "Revoke" })).toBeDisabled()
        expect(within(dialog).getByRole("textbox", { name: /Reason for revoking/ })).toBeInTheDocument()
        fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }))
        expect(await revokeButton()).toHaveFocus()
    })

    it("M19: when the server says the caller cannot manage, no Grant or Revoke is offered", async () => {
        setup({ w: { ...world(), can_manage: false } })
        await screen.findByText("Gina GM")
        expect(screen.queryByRole("button", { name: /^(Grant|Revoke)/ })).not.toBeInTheDocument()
        expect(screen.getByText("Only a campaign owner can grant or revoke reveal authority.")).toBeInTheDocument()
    })

    it("M18: an owner who is also a listed GM is granted like any other member, with no self marker", async () => {
        const w = world()
        w.members.push({ campaign_membership_id: "m-self", display_name: "Olga Owner", delegation: null })
        const { server } = setup({ w })
        server.on("POST", PATH, { body: { grantee_campaign_membership_id: "m-self", character_reveal_delegation_id: "d9", granted: true } })
        const dialog = await openGrant("Olga Owner")
        typeReason(dialog, "Self")
        confirm(dialog, "Grant")
        await vi.waitFor(() => expect(grants(server)).toHaveLength(1))
        expect(grants(server)[0]!.body).toEqual({ grantee_campaign_membership_id: "m-self", reason: "Self" })
        expect(screen.queryByText(/\(you\)|yourself/i)).not.toBeInTheDocument()
    })
})

describe("CampaignRevealAuthorityPage: confirmed writes (M2, M3, M5, M6, M16, M17, M21)", () => {
    it("M2/M16/M17: a grant sends exactly its body with no idempotency key, re-reads, announces, and focuses that row's Revoke; no session churn", async () => {
        const { server, state, refreshes } = setup()
        const dialog = await openGrant()
        typeReason(dialog, "  Trusted  ")
        server.on("POST", PATH, () => {
            state.w = {
                ...world(),
                members: [
                    world().members[0]!,
                    { campaign_membership_id: "m-gm2", display_name: "Gus GM", delegation: { granted_at: "2026-11-21T10:00:00Z", granted_by_name: "Olga Owner" } },
                ],
            }
            return { body: { grantee_campaign_membership_id: "m-gm2", character_reveal_delegation_id: "d1", granted: true } }
        })
        confirm(dialog, "Grant")
        expect(await screen.findByText("Gus GM can now reveal characters.")).toBeInTheDocument()
        expect(grants(server)).toHaveLength(1)
        const call = grants(server)[0]!
        expect(call.body).toEqual({ grantee_campaign_membership_id: "m-gm2", reason: "Trusted" })
        expect(Object.keys(call.headers).map((h) => h.toLowerCase())).not.toContain("idempotency-key")
        expect(reads(server)).toHaveLength(2)
        expect(await revokeButton("Gus GM")).toHaveFocus()
        // The reason is gone with the dialog, and the receipt's ids are never rendered.
        expect(screen.queryByText(/Trusted|d1/)).not.toBeInTheDocument()
        // Only this page's own reads and the one write: no overview, effective access, bootstrap or session refresh.
        expect(server.calls.map((c) => `${c.method} ${c.path}`).sort()).toEqual([`GET ${PATH}`, `GET ${PATH}`, `POST ${PATH}`])
        expect(refreshes).not.toHaveBeenCalled()
    })

    it("M3: granted false is a success with its own wording", async () => {
        const { server } = setup()
        server.on("POST", PATH, { body: { grantee_campaign_membership_id: "m-gm2", character_reveal_delegation_id: "d1", granted: false } })
        const dialog = await openGrant()
        typeReason(dialog, "Because")
        confirm(dialog, "Grant")
        expect(await screen.findByText("Gus GM already had reveal authority.")).toBeInTheDocument()
        expect(screen.queryByRole("alert")).not.toBeInTheDocument()
    })

    it("M5: a revoke sends exactly {reason}, re-reads, announces and focuses that row's Grant", async () => {
        const { server, state } = setup()
        const dialog = await openRevoke()
        typeReason(dialog, "No longer needed")
        server.on("POST", REVOKE("m-gm1"), () => {
            state.w = { ...world(), members: [{ campaign_membership_id: "m-gm1", display_name: "Gina GM", delegation: null }, world().members[1]!] }
            return { body: { grantee_campaign_membership_id: "m-gm1", revoked: true } }
        })
        confirm(dialog, "Revoke")
        expect(await screen.findByText("Reveal authority revoked for Gina GM.")).toBeInTheDocument()
        const call = server.callsTo("POST", REVOKE("m-gm1"))[0]!
        expect(call.body).toEqual({ reason: "No longer needed" })
        expect(Object.keys(call.headers).map((h) => h.toLowerCase())).not.toContain("idempotency-key")
        expect(await grantButton("Gina GM")).toHaveFocus()
    })

    it("M6: revoked false is a success: the delegation had already ended", async () => {
        const { server } = setup()
        server.on("POST", REVOKE("m-gm1"), { body: { grantee_campaign_membership_id: "m-gm1", revoked: false } })
        const dialog = await openRevoke()
        typeReason(dialog, "Because")
        confirm(dialog, "Revoke")
        expect(await screen.findByText("That member's reveal authority had already ended.")).toBeInTheDocument()
    })

    it("M21: a lapsed delegation is revoked by the same request, and leaves the list", async () => {
        const w = world()
        w.lapsed_delegations = [{ campaign_membership_id: "m-old", display_name: "Olive Old", granted_at: "2026-10-01T10:00:00Z", granted_by_name: null }]
        const { server, state } = setup({ w })
        server.on("POST", REVOKE("m-old"), () => {
            state.w = world()
            return { body: { grantee_campaign_membership_id: "m-old", revoked: true } }
        })
        const button = await screen.findByRole("button", { name: "Revoke the delegation of Olive Old" })
        fireEvent.click(button)
        const dialog = await screen.findByRole("dialog", { name: /Revoke reveal authority from Olive Old/ })
        expect(dialog).toHaveTextContent("already gives no authority")
        typeReason(dialog, "Cleanup")
        confirm(dialog, "Revoke")
        expect(await screen.findByText("Reveal authority revoked for Olive Old.")).toBeInTheDocument()
        expect(server.callsTo("POST", REVOKE("m-old"))[0]!.body).toEqual({ reason: "Cleanup" })
        expect(screen.queryByText("Olive Old", { selector: "strong" })).not.toBeInTheDocument()
    })
})

describe("CampaignRevealAuthorityPage: refusals (M7 to M11)", () => {
    it("M7: campaign_owner_required re-reads, withdraws the controls, shows the typed reason back and never the server text", async () => {
        const { server, state } = setup()
        const dialog = await openGrant()
        typeReason(dialog, "My careful reason")
        server.on("POST", PATH, refused(403, "campaign_owner_required"))
        state.w = { ...world(), can_manage: false }
        confirm(dialog, "Grant")
        const alert = await screen.findByText(/Only a campaign owner can grant or revoke reveal authority\. Nothing was changed\./)
        expect(alert.closest("[role=alert]")).toHaveTextContent("My careful reason")
        expect(screen.queryByText(/SERVER-SECRET-TEXT|campaign owner role/)).not.toBeInTheDocument()
        await vi.waitFor(() => expect(screen.queryByRole("button", { name: /^(Grant|Revoke)/ })).not.toBeInTheDocument())
        expect(reads(server)).toHaveLength(2)
        expect(grants(server)).toHaveLength(1)
    })

    for (const [status, code] of [[403, "forbidden"], [404, "not_found"]] as const) {
        it(`M8: a ${status} (${code}) drops the content and the typed reason, refreshes the session once and announces it`, async () => {
            const { server, refreshes } = setup()
            const dialog = await openGrant()
            typeReason(dialog, "Reason I typed")
            server.on("POST", PATH, refused(status, code))
            confirm(dialog, "Grant")
            expect(await screen.findByText("Reveal authority unavailable")).toBeInTheDocument()
            expect(screen.queryByText(/Gina GM|Reason I typed|SERVER-SECRET-TEXT/)).not.toBeInTheDocument()
            expect(await screen.findByText("Reveal authority isn't available.")).toBeInTheDocument()
            await vi.waitFor(() => expect(refreshes).toHaveBeenCalledTimes(1))
            expect(grants(server)).toHaveLength(1)
        })
    }

    it("M9: reveal_delegation_recipient_not_gm re-reads, closes the dialog and says nothing was changed", async () => {
        const { server, state } = setup()
        const dialog = await openGrant()
        typeReason(dialog, "Because")
        server.on("POST", PATH, refused(409, "reveal_delegation_recipient_not_gm"))
        state.w = { ...world(), members: [world().members[0]!] }
        confirm(dialog, "Grant")
        expect(await screen.findByText("That member no longer holds the GM role. Nothing was changed.")).toBeInTheDocument()
        await vi.waitFor(() => expect(screen.queryByText("Gus GM", { selector: "strong" })).not.toBeInTheDocument())
        expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
        expect(grants(server)).toHaveLength(1)
        expect(reads(server)).toHaveLength(2)
    })

    it("M10: reveal_delegation_recipient_changed re-reads, keeps the dialog open with the reason and sends nothing again", async () => {
        const { server } = setup()
        const dialog = await openGrant()
        typeReason(dialog, "Keep this")
        server.on("POST", PATH, refused(409, "reveal_delegation_recipient_changed"))
        confirm(dialog, "Grant")
        expect(await within(dialog).findByText(/Their GM assignment changed while this was being saved\. Nothing was changed; review and grant again\./)).toBeInTheDocument()
        expect(within(dialog).getByRole("textbox", { name: /Reason for/ })).toHaveValue("Keep this")
        await vi.waitFor(() => expect(reads(server)).toHaveLength(2))
        expect(grants(server)).toHaveLength(1)
        expect(screen.getByRole("dialog")).toBeInTheDocument()
    })

    it("M11: a 422 shows an error in the dialog and changes nothing else", async () => {
        const { server } = setup()
        const dialog = await openGrant()
        typeReason(dialog, "Because")
        server.on("POST", PATH, refused(422, "validation_error"))
        confirm(dialog, "Grant")
        expect(await within(dialog).findByText(/Check the reason and try again/)).toBeInTheDocument()
        expect(reads(server)).toHaveLength(1)
        expect(grants(server)).toHaveLength(1)
        expect(screen.queryByText(/SERVER-SECRET-TEXT/)).not.toBeInTheDocument()
    })
})

describe("CampaignRevealAuthorityPage: unknown outcomes (M12, M13, M14)", () => {
    for (const [label, response] of [
        ["a network error", { networkError: true }],
        ["a 500", refused(500, "internal_error")],
    ] as const) {
        it(`M12: ${label} closes the dialog, says the outcome is unknown, offers a state check and never a Retry; a later write is a new deliberate action`, async () => {
            const { server } = setup()
            const dialog = await openGrant()
            typeReason(dialog, "Because")
            server.on("POST", PATH, response)
            confirm(dialog, "Grant")
            const notice = await screen.findByText(/We couldn't confirm whether your last change to reveal authority was applied/)
            const alert = notice.closest("[role=alert]") as HTMLElement
            expect(alert).toHaveTextContent("It may have been made")
            expect(alert).not.toHaveTextContent(/Gus GM|m-gm2|SERVER-SECRET|did not|rejected/)
            expect(screen.queryByRole("button", { name: /Retry|Try again/ })).not.toBeInTheDocument()
            expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
            expect(grants(server)).toHaveLength(1)
            // Check reads only.
            fireEvent.click(within(alert).getByRole("button", { name: "Check current reveal authority" }))
            expect(await within(alert).findByText(/doesn't show whether your last attempt made the change/)).toBeInTheDocument()
            expect(grants(server)).toHaveLength(1)
            // A failed read proves nothing either.
            server.on("GET", PATH, refused(500, "internal_error"))
            fireEvent.click(within(alert).getByRole("button", { name: "Check current reveal authority" }))
            expect(await within(alert).findByText(/says nothing about whether the change was applied/)).toBeInTheDocument()
            expect(grants(server)).toHaveLength(1)
            // Recover by a good read, Dismiss, then a deliberate new submission (no key, and nothing replayed).
            server.on("GET", PATH, { body: world() })
            fireEvent.click(within(alert).getByRole("button", { name: "Check current reveal authority" }))
            await vi.waitFor(() => expect(screen.getByRole("button", { name: /Grant reveal authority to Gus GM/ })).toBeInTheDocument())
            fireEvent.click(within(alert).getByRole("button", { name: "Dismiss" }))
            await vi.waitFor(() => expect(screen.queryByText(/We couldn't confirm/)).not.toBeInTheDocument())
            server.on("POST", PATH, { body: { grantee_campaign_membership_id: "m-gm2", character_reveal_delegation_id: "d1", granted: true } })
            const again = await openGrant()
            typeReason(again, "Second try")
            confirm(again, "Grant")
            await vi.waitFor(() => expect(grants(server)).toHaveLength(2))
            expect(grants(server)[1]!.body).toEqual({ grantee_campaign_membership_id: "m-gm2", reason: "Second try" })
            expect(Object.keys(grants(server)[1]!.headers).map((h) => h.toLowerCase())).not.toContain("idempotency-key")
        })
    }

    it("M12: a revoke whose answer is lost is the same: no Retry, a target-free alert, a read-only check", async () => {
        const { server } = setup()
        const dialog = await openRevoke()
        typeReason(dialog, "Because")
        server.on("POST", REVOKE("m-gm1"), { networkError: true })
        confirm(dialog, "Revoke")
        const alert = (await screen.findByText(/We couldn't confirm whether your last change/)).closest("[role=alert]") as HTMLElement
        expect(alert).not.toHaveTextContent("Gina GM")
        expect(screen.queryByRole("button", { name: /Retry/ })).not.toBeInTheDocument()
        expect(server.callsTo("POST", REVOKE("m-gm1"))).toHaveLength(1)
    })

    it("M13: an already-ambiguous attempt, then authority loss and restoration, keeps the notice and its Check, and brings back no Retry and no old intent", async () => {
        const { server, state } = setup()
        const dialog = await openGrant()
        typeReason(dialog, "Because")
        server.on("POST", PATH, { networkError: true })
        confirm(dialog, "Grant")
        const alert = (await screen.findByText(/We couldn't confirm whether your last change/)).closest("[role=alert]") as HTMLElement
        // The server now says the caller cannot manage (ownership moved), read by Check.
        state.w = { ...world(), can_manage: false }
        fireEvent.click(within(alert).getByRole("button", { name: "Check current reveal authority" }))
        await vi.waitFor(() => expect(screen.queryByRole("button", { name: /^(Grant|Revoke)/ })).not.toBeInTheDocument())
        expect(screen.getByText(/We couldn't confirm whether your last change/)).toBeInTheDocument()
        // Restoration (another read): the controls return from the read, the notice stays, and nothing was re-sent.
        state.w = world()
        fireEvent.click(within(alert).getByRole("button", { name: "Check current reveal authority" }))
        expect(await grantButton()).toBeInTheDocument()
        expect(screen.getByText(/We couldn't confirm whether your last change/)).toBeInTheDocument()
        expect(screen.queryByRole("button", { name: /Retry/ })).not.toBeInTheDocument()
        expect(grants(server)).toHaveLength(1)
        // Only the person's own new submission sends anything.
        expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    })

    it("M13: a write pending when access.manage is lost is aborted with the page and publishes nothing; restoration shows a fresh page with nothing to repeat", async () => {
        let settle: (value: { status?: number; body?: object; networkError?: boolean }) => void = () => undefined
        let next = bootstrap(["canon.edit"])
        const { server } = setup({ onRefresh: async () => next })
        const dialog = await openGrant()
        typeReason(dialog, "Because")
        server.on("POST", PATH, () => new Promise((resolve) => (settle = resolve)))
        confirm(dialog, "Grant")
        await vi.waitFor(() => expect(grants(server)).toHaveLength(1))
        refreshSession()
        await screen.findByText("Access unavailable")
        await act(async () => settle({ networkError: true }))
        expect(screen.queryByText(/We couldn't confirm/)).not.toBeInTheDocument()
        next = bootstrap()
        refreshSession()
        expect(await grantButton()).toBeInTheDocument()
        expect(screen.queryByText(/We couldn't confirm/)).not.toBeInTheDocument()
        expect(screen.queryByRole("button", { name: /Retry/ })).not.toBeInTheDocument()
        expect(grants(server)).toHaveLength(1)
    })

    it("M14: a pending write that settles after navigation announces nothing and changes no row", async () => {
        let settle: (value: { body: object }) => void = () => undefined
        const { server, router } = setup()
        const dialog = await openGrant()
        typeReason(dialog, "Because")
        server.on("POST", PATH, () => new Promise((resolve) => (settle = resolve)))
        confirm(dialog, "Grant")
        await vi.waitFor(() => expect(grants(server)).toHaveLength(1))
        await act(async () => {
            await router.navigate("/app/c1/elsewhere")
        })
        await screen.findByText("Elsewhere")
        await act(async () => settle({ body: { grantee_campaign_membership_id: "m-gm2", character_reveal_delegation_id: "d1", granted: true } }))
        expect(screen.queryByText(/can now reveal characters/)).not.toBeInTheDocument()
        expect(reads(server)).toHaveLength(1)
    })
})

describe("CampaignRevealAuthorityPage: confirmed write, failed re-read, and role endings (L8, L10)", () => {
    it("a confirmed grant whose re-read fails shows the stale notice, offers no controls or can_manage line, and a good read recovers", async () => {
        const { server, state } = setup()
        const dialog = await openGrant()
        typeReason(dialog, "Because")
        server.on("GET", PATH, refused(500, "internal_error"))
        confirm(dialog, "Grant")
        await screen.findAllByText(/The latest reveal authority could not be loaded/)
        expect(screen.queryByRole("button", { name: /^(Grant|Revoke)/ })).not.toBeInTheDocument()
        expect(screen.queryByText("You can grant or revoke reveal authority.")).not.toBeInTheDocument()
        expect(screen.getByText("Gina GM")).toBeInTheDocument() // the last list is kept, marked out of date
        expect(grants(server)).toHaveLength(1)
        server.on("GET", PATH, () => ({ body: state.w }))
        fireEvent.click(screen.getAllByRole("button", { name: "Try again" })[0]!)
        expect(await grantButton()).toBeInTheDocument()
        expect(grants(server)).toHaveLength(1)
    })

    it("L10: a re-read that drops a member closes that member's open dialog and sends nothing again", async () => {
        const { server, state } = setup()
        const dialog = await openGrant()
        typeReason(dialog, "Because")
        server.on("POST", PATH, refused(409, "reveal_delegation_recipient_changed"))
        state.w = { ...world(), members: [world().members[0]!] }
        confirm(dialog, "Grant")
        await vi.waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument())
        expect(screen.queryByText("Gus GM", { selector: "strong" })).not.toBeInTheDocument()
        expect(grants(server)).toHaveLength(1)
    })
})

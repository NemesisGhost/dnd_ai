import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { MemoryRouter, Route, Routes } from "react-router"
import { afterEach, describe, expect, it, vi } from "vitest"
import { SessionProvider } from "../context/SessionProvider"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { AuthenticatedSessionBoundary } from "../layouts/AuthenticatedSessionBoundary"
import type { CampaignAccessOverview } from "../types/accessOverview"
import { CampaignAccessPage } from "./CampaignAccessPage"

vi.mock("../components/InvitationsSection", () => ({
    InvitationsSection: () => null,
}))

// The REAL session lifecycle: SessionProvider (the real useSessionBootstrap, reading /auth/session),
// AuthenticatedSessionBoundary (which replaces its children with "Loading portal" while the session
// reloads), the Access page and its hooks. Only the network is replaced. The other Access integration
// tests supply a session whose reload() does nothing, so they cannot see the page being remounted; these
// do. A write the caller cannot be affected by re-reads the session IN PLACE; anything that might affect the
// caller, or any refresh that was not applied, reloads it (O-5).

const CAMPAIGN = sessionBootstrapFixture.campaigns[0].campaign_id
const SELF_USER = sessionBootstrapFixture.user.user_id
const SELF = "membership-self"
const BRAM = "membership-bram"
const SELF_REL = "rel-self"
const BRAM_REL_1 = "rel-bram-1"
const BRAM_REL_2 = "rel-bram-2"

interface Deferred {
    promise: Promise<void>
    resolve: () => void
}
const deferred = (): Deferred => {
    let resolve!: () => void
    const promise = new Promise<void>((r) => {
        resolve = r
    })
    return { promise, resolve }
}

interface World {
    relationships: string[]
    sessionStatuses: Array<number | "ok">
    sessionHold: Deferred[]
    sessionCalls: number
    capabilities: string[]
    overviewStatus: number
    explainCalls: number
}

function newWorld(): World {
    return {
        relationships: [SELF_REL, BRAM_REL_1, BRAM_REL_2],
        sessionStatuses: [],
        sessionHold: [],
        sessionCalls: 0,
        capabilities: ["access.manage"],
        overviewStatus: 200,
        explainCalls: 0,
    }
}

const rel = (id: string, name: string, character: string) => ({
    membership_character_relationship_id: id,
    character_id: character,
    character_display_name: name,
    relationship_type_code: "viewer",
    relationship_type_display_name: "Viewer",
    granted_at: "2026-01-02T00:00:00Z",
    expires_at: null,
})

function overviewOf(world: World): CampaignAccessOverview {
    const has = (id: string) => world.relationships.includes(id)
    const member = (id: string, user: string, name: string, rels: ReturnType<typeof rel>[]) => ({
        campaign_membership_id: id,
        user_id: user,
        display_name: name,
        status_code: "active",
        status_display_name: "Active",
        joined_at: "2026-01-01T00:00:00Z",
        account_is_active: true,
        roles: [],
        character_relationships: rels,
        grants: [],
        revelations: [],
    })
    return {
        members: [
            member(SELF, SELF_USER, "Aria the GM", has(SELF_REL) ? [rel(SELF_REL, "Kestrel Vane", "c-kestrel")] : []),
            member(BRAM, "user-bram", "Bram", [
                ...(has(BRAM_REL_1) ? [rel(BRAM_REL_1, "Mira Vale", "c-mira")] : []),
                ...(has(BRAM_REL_2) ? [rel(BRAM_REL_2, "Olen Reed", "c-olen")] : []),
            ]),
        ],
        assignable_roles: [],
        assignable_characters: [],
        assignable_relationship_types: [],
        grantable_resource_capabilities: [],
        access_groups: [],
    }
}

const json = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })

function install(world: World) {
    vi.stubGlobal(
        "fetch",
        vi.fn(async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
            const url = typeof input === "string" ? input : input.toString()
            const method = init?.method ?? "GET"
            if (url.includes("/auth/session")) {
                world.sessionCalls += 1
                const hold = world.sessionHold.shift()
                if (hold !== undefined) await hold.promise
                const next = world.sessionStatuses.shift() ?? "ok"
                if (next === 401) return new Response(null, { status: 401 })
                if (next !== "ok") return new Response(null, { status: next })
                return json({
                    ...sessionBootstrapFixture,
                    campaigns: [{ ...sessionBootstrapFixture.campaigns[0], capabilities: world.capabilities }],
                })
            }
            if (method === "GET" && url.includes("/access-overview")) {
                if (world.overviewStatus !== 200) {
                    return json({ error: { code: "x", message: "m", correlation_id: "c" } }, world.overviewStatus)
                }
                return json(overviewOf(world))
            }
            const explain = /\/members\/([^/]+)\/effective-access/.exec(url)
            if (method === "GET" && explain !== null) {
                world.explainCalls += 1
                const id = decodeURIComponent(explain[1]!)
                const sources = overviewOf(world)
                    .members.find((m) => m.campaign_membership_id === id)!
                    .character_relationships.map((r) => ({
                        kind: "character_relationship",
                        label: "Viewer",
                        target_display_name: r.character_display_name,
                    }))
                return json({
                    display_name: id === SELF ? "Aria the GM" : "Bram",
                    capabilities: sources.length === 0 ? [] : [{ code: "character.view_summary", display_name: "View summary", sources }],
                    denials: [],
                })
            }
            const revoke = /\/character-relationships\/([^/]+)\/revoke/.exec(url)
            if (method === "POST" && revoke !== null) {
                const id = decodeURIComponent(revoke[1]!)
                world.relationships = world.relationships.filter((r) => r !== id)
                return json({ membership_character_relationship_id: id })
            }
            throw new Error(`Unmocked ${method} ${url}`)
        }),
    )
}

// Records every time the "Loading portal" placeholder appears, however briefly.
function watchLoadingPortal() {
    const seen = { count: 0, visible: false }
    const look = () => {
        const now = document.body.textContent?.includes("Loading portal") ?? false
        if (now && !seen.visible) seen.count += 1
        seen.visible = now
    }
    const observer = new MutationObserver(look)
    observer.observe(document.body, { childList: true, subtree: true, characterData: true })
    return { seen, stop: () => observer.disconnect() }
}

function renderApp(world: World) {
    install(world)
    const watch = watchLoadingPortal()
    const view = render(
        <MemoryRouter initialEntries={[`/app/${CAMPAIGN}/access`]}>
            <Routes>
                <Route
                    path="/app/:campaignId/access"
                    element={
                        <SessionProvider>
                            <AuthenticatedSessionBoundary>{() => <CampaignAccessPage />}</AuthenticatedSessionBoundary>
                        </SessionProvider>
                    }
                />
                <Route path="/login" element={<p>Sign in page</p>} />
            </Routes>
        </MemoryRouter>,
    )
    return { ...view, watch }
}

const cardOf = (name: string) => screen.getByText(name, { selector: "strong" }).closest("details")!
const status = (container: HTMLElement) => container.querySelector(".campaign-access-page__announcement") as HTMLElement
async function openExplanation(name: string) {
    const card = await waitFor(() => cardOf(name))
    if (!card.open) fireEvent.click(within(card).getByText(name, { selector: "strong" }))
    await waitFor(() => expect(cardOf(name).open).toBe(true))
    fireEvent.click(within(cardOf(name)).getByRole("button", { name: /Explain access/ }))
    await within(cardOf(name)).findByRole("button", { name: "Refresh access" })
}
async function removeAccess(name: string, character: string) {
    const card = cardOf(name)
    const group = within(card).getByText(new RegExp(`${character}.*Viewer`)).closest("li")!
    fireEvent.click(within(group).getByRole("button", { name: "Remove access" }))
    fireEvent.click(within(group).getByRole("button", { name: "Confirm" }))
}
const sessionReadsAfterLoad = (world: World) => world.sessionCalls - 1

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("Access writes and the real session lifecycle (O-5)", () => {
    it("keeps the page mounted for a write the caller cannot be affected by: open explanation, status line and focus context continue", async () => {
        const world = newWorld()
        const { container, watch } = renderApp(world)
        await screen.findByText("Bram", { selector: "strong" })
        watch.seen.count = 0
        await openExplanation("Bram")
        const line = status(container)
        const reads = world.sessionCalls
        const explainBefore = world.explainCalls
        await removeAccess("Bram", "Mira Vale")
        await waitFor(() => expect(status(container)).toHaveTextContent("Character access removed."))
        await waitFor(() => expect(world.sessionCalls).toBe(reads + 1))
        // The explanation was re-read after the list, still open, and shows the survivor only.
        await within(cardOf("Bram")).findByText("Character access: Viewer (Olen Reed)")
        expect(within(cardOf("Bram")).queryByText(/Mira Vale/, { selector: "li" })).not.toBeInTheDocument()
        expect(within(cardOf("Bram")).getByRole("button", { name: "Hide access explanation" })).toHaveAttribute("aria-expanded", "true")
        expect(cardOf("Bram").open).toBe(true)
        expect(world.explainCalls).toBeGreaterThan(explainBefore)
        // The same status paragraph element, with the text, and the portal never showed its loading page.
        expect(status(container)).toBe(line)
        expect(watch.seen.count).toBe(0)
        watch.stop()
    })

    it("still reloads the session, remounting the page, for a write on the caller's own membership (fail closed)", async () => {
        const world = newWorld()
        const { container, watch } = renderApp(world)
        await screen.findByText("Aria the GM", { selector: "strong" })
        watch.seen.count = 0
        await openExplanation("Aria the GM")
        const line = status(container)
        const reads = world.sessionCalls
        await removeAccess("Aria the GM", "Kestrel Vane")
        await waitFor(() => expect(world.sessionCalls).toBe(reads + 1))
        await screen.findByText("Aria the GM", { selector: "strong" })
        expect(watch.seen.count).toBeGreaterThan(0)
        expect(status(container)).not.toBe(line)
        expect(cardOf("Aria the GM").open).toBe(false)
        watch.stop()
    })

    it("falls back to a full reload when the in-place read of the session fails", async () => {
        const world = newWorld()
        const { watch } = renderApp(world)
        await screen.findByText("Bram", { selector: "strong" })
        watch.seen.count = 0
        await openExplanation("Bram")
        world.sessionStatuses = [500]
        const reads = world.sessionCalls
        await removeAccess("Bram", "Mira Vale")
        await waitFor(() => expect(watch.seen.count).toBeGreaterThan(0))
        await screen.findByText("Bram", { selector: "strong" })
        // the failed read, then the reload's read
        expect(world.sessionCalls).toBe(reads + 2)
        expect(cardOf("Bram").open).toBe(false)
        watch.stop()
    })

    it("leaves for sign-in, with no access content, when the in-place read finds the session ended", async () => {
        const world = newWorld()
        renderApp(world)
        await screen.findByText("Bram", { selector: "strong" })
        await openExplanation("Bram")
        world.sessionStatuses = [401, 401]
        await removeAccess("Bram", "Mira Vale")
        await screen.findByText("Sign in page")
        expect(screen.queryByText("Bram")).not.toBeInTheDocument()
        expect(document.body.textContent).not.toMatch(/Character access:|Revealed characters|Olen Reed/)
    })

    it("shows no member or explanation content when the refreshed session and the list say the caller lost access", async () => {
        const world = newWorld()
        const { container } = renderApp(world)
        await screen.findByText("Bram", { selector: "strong" })
        await openExplanation("Bram")
        // The write succeeds; the server then reports the caller no longer holds access.manage.
        world.capabilities = []
        world.overviewStatus = 403
        await removeAccess("Bram", "Mira Vale")
        await screen.findByRole("heading", { name: "Access unavailable" })
        expect(document.body.textContent).not.toMatch(/Bram|Olen Reed|Character access:|Refresh access/)
        expect(status(container).textContent).toBe("Character access removed.")
    })

    it("reloads when its in-place read was overtaken by a newer session read (not applied)", async () => {
        const world = newWorld()
        const { watch } = renderApp(world)
        await screen.findByText("Bram", { selector: "strong" })
        watch.seen.count = 0
        await openExplanation("Bram")
        const first = deferred()
        world.sessionHold = [first]
        const reads = world.sessionCalls
        await removeAccess("Bram", "Mira Vale")
        // The first write's session read is still pending: a second, independent write completes and its
        // read is applied first.
        await waitFor(() => expect(world.sessionCalls).toBe(reads + 1))
        await screen.findByText("Olen Reed", { exact: false })
        await removeAccess("Bram", "Olen Reed")
        await waitFor(() => expect(world.sessionCalls).toBe(reads + 2))
        await act(async () => {
            await Promise.resolve()
        })
        expect(watch.seen.count).toBe(0)
        // Now the older read answers: it was overtaken, so it is not applied and the session is reloaded.
        await act(async () => {
            first.resolve()
        })
        await waitFor(() => expect(watch.seen.count).toBeGreaterThan(0))
        await screen.findByText("Bram", { selector: "strong" })
        expect(sessionReadsAfterLoad(world)).toBeGreaterThanOrEqual(3)
        watch.stop()
    })
})

import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { Link, MemoryRouter, Route, Routes } from "react-router"
import { afterEach, describe, expect, it, vi } from "vitest"
import { SessionContext } from "../context/SessionContext"
import { sessionBootstrapFixture } from "../fixtures/sessionBootstrap"
import { bootstrapWithAccessManage } from "../test/accessBootstrap"
import type { CampaignAccessOverview } from "../types/accessOverview"
import { CampaignAccessPage } from "./CampaignAccessPage"

vi.mock("../components/InvitationsSection", () => ({
    InvitationsSection: () => null,
}))

// The real Access page -> overview boundary -> AccessPage -> EffectiveAccessPanel -> hooks -> API
// clients, with only the network (global fetch) and the session context replaced. The fake server
// answers the overview and each member's explanation FROM ONE state, the way the real endpoints do,
// but as two separate requests: they are independent observations, never an atomic snapshot.

const CAMPAIGN = "campaign-a"
const OTHER_CAMPAIGN = "campaign-b"
const ARIA = "membership-aria"
const BRAM = "membership-bram"
const KESTREL = "character-kestrel"
const RELATIONSHIP_ID = "relationship-1"

interface Deferred<T> {
    promise: Promise<T>
    resolve: (value: T) => void
}
function deferred<T>(): Deferred<T> {
    let resolve!: (value: T) => void
    const promise = new Promise<T>((r) => {
        resolve = r
    })
    return { promise, resolve }
}

interface MemberState {
    id: string
    name: string
    relationship: boolean
    revelations: { kind: string; code: string }[]
    deny: boolean
}

interface World {
    members: MemberState[]
    // Request log in the order the server saw it.
    log: string[]
    overviewStatus: number
    explainStatus: Record<string, number>
    // Held answers, consumed by the next matching request.
    holdOverview?: Deferred<void>
    holdExplain?: Deferred<object | undefined>
}

function member(id: string, name: string, over: Partial<MemberState> = {}): MemberState {
    return { id, name, relationship: false, revelations: [], deny: false, ...over }
}

function overviewOf(world: World): CampaignAccessOverview {
    return {
        members: world.members.map((m) => ({
            campaign_membership_id: m.id,
            user_id: m.id === ARIA ? sessionBootstrapFixture.user.user_id : `user-${m.id}`,
            display_name: m.name,
            status_code: "active",
            status_display_name: "Active",
            joined_at: "2026-01-01T00:00:00Z",
            account_is_active: true,
            roles: [],
            character_relationships: m.relationship
                ? [
                      {
                          membership_character_relationship_id: RELATIONSHIP_ID,
                          character_id: KESTREL,
                          character_display_name: "Kestrel Vane",
                          relationship_type_code: "viewer",
                          relationship_type_display_name: "Viewer",
                          granted_at: "2026-01-02T00:00:00Z",
                          expires_at: null,
                      },
                  ]
                : [],
            grants: m.deny
                ? [
                      {
                          resource_grant_id: "grant-deny",
                          capability_code: "campaign.view",
                          capability_display_name: "View campaign",
                          effect: "deny",
                          target_type: "entity",
                          target_id: KESTREL,
                          target_display_name: "Kestrel Vane",
                          reason: null,
                          granted_at: "2026-01-02T00:00:00Z",
                          expires_at: null,
                      },
                  ]
                : [],
            revelations: m.revelations.map((r) => ({
                character_id: KESTREL,
                character_display_name: "Kestrel Vane",
                audience_kind_code: r.code,
                audience_kind_display_name: r.kind,
                character_revelation_id: "MARKER-REVELATION-ID",
            })) as never,
        })),
        assignable_roles: [],
        assignable_characters: [{ character_id: KESTREL, display_name: "Kestrel Vane" }],
        assignable_relationship_types: [
            { character_relationship_type_id: "type-viewer", code: "viewer", display_name: "Viewer" },
        ],
        grantable_resource_capabilities: [],
        access_groups: [],
    }
}

function explanationOf(world: World, id: string) {
    const m = world.members.find((candidate) => candidate.id === id)
    if (m === undefined) return null
    const capabilities = []
    if (m.relationship) {
        capabilities.push({
            code: "character.view_full",
            display_name: "View full character",
            sources: [{ kind: "character_relationship", label: "Viewer", target_display_name: "Kestrel Vane" }],
        })
    }
    if (m.revelations.length > 0) {
        capabilities.push({
            code: "character.discover",
            display_name: "Discover characters",
            sources: m.revelations.map((r) => ({
                kind: "revelation",
                label: r.kind,
                target_display_name: "Kestrel Vane",
                character_revelation_id: "MARKER-REVELATION-ID",
            })),
        })
    }
    return {
        display_name: m.name,
        capabilities,
        denials: m.deny
            ? [{ capability_code: "campaign.view", target_type: "entity", target_display_name: "Kestrel Vane" }]
            : [],
    }
}

const json = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })

function makeWorld(members: MemberState[]): World {
    return { members, log: [], overviewStatus: 200, explainStatus: {} }
}

function install(world: World) {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        const url = typeof input === "string" ? input : input.toString()
        const method = init?.method ?? "GET"
        if (method === "GET" && url.includes("/access-overview")) {
            world.log.push("GET overview")
            const hold = world.holdOverview
            world.holdOverview = undefined
            if (hold !== undefined) await hold.promise
            if (world.overviewStatus !== 200) return json({ error: { code: "x", message: "m", correlation_id: "c" } }, world.overviewStatus)
            return json(overviewOf(world))
        }
        const explain = /\/members\/([^/]+)\/effective-access/.exec(url)
        if (method === "GET" && explain !== null) {
            const id = decodeURIComponent(explain[1]!)
            world.log.push(`GET explain:${id}`)
            const hold = world.holdExplain
            world.holdExplain = undefined
            const override = hold === undefined ? undefined : await hold.promise
            const status = world.explainStatus[id] ?? 200
            if (status !== 200) return json({ error: { code: "x", message: "m", correlation_id: "c" } }, status)
            return json(override ?? explanationOf(world, id))
        }
        if (method === "POST" && url.includes("/revoke")) {
            world.log.push("POST revoke")
            world.members.forEach((m) => {
                m.relationship = false
            })
            return json({ changed: true })
        }
        throw new Error(`Unmocked ${method} ${url}`)
    })
    vi.stubGlobal("fetch", fetchMock)
    return fetchMock
}

function renderAt(world: World, reload: () => Promise<void> = vi.fn().mockResolvedValue(undefined)) {
    install(world)
    const view = render(
        <SessionContext.Provider
            value={{ state: { status: "authenticated", bootstrap: bootstrapWithAccessManage(CAMPAIGN, OTHER_CAMPAIGN) }, reload, refresh: vi.fn() }}
        >
            <MemoryRouter initialEntries={[`/app/${CAMPAIGN}/access`]}>
                <Link to={`/app/${OTHER_CAMPAIGN}/access`}>Go to the other campaign</Link>
                <Routes>
                    <Route path="/app/:campaignId/access" element={<CampaignAccessPage />} />
                </Routes>
            </MemoryRouter>
        </SessionContext.Provider>,
    )
    return { ...view, reload }
}

const announcement = (container: HTMLElement) => container.querySelector(".campaign-access-page__announcement")
const cardOf = (name: string) => screen.getByText(name, { selector: "strong" }).closest("details")!
const explain = (name: string) =>
    within(cardOf(name)).getByRole("button", { name: /Explain access|Hide access explanation/ })
const inCard = (name: string, text: string | RegExp) =>
    waitFor(() => expect(within(cardOf(name)).getByText(text)).toBeInTheDocument())
const inCardButton = (name: string, label: string) =>
    waitFor(() => expect(within(cardOf(name)).getByRole("button", { name: label })).toBeInTheDocument())
async function open(name: string) {
    // The member card is a <details>: opened as a person does, by its summary.
    const details = cardOf(name)
    if (!details.open) fireEvent.click(within(details).getByText(name, { selector: "strong" }))
    await waitFor(() => expect(cardOf(name).open).toBe(true))
    fireEvent.click(explain(name))
    await inCardButton(name, "Refresh access")
}

afterEach(() => {
    vi.unstubAllGlobals()
})

describe("Access page: explanation and list refreshed together", () => {
    // NOTE (O-5): this file supplies a session whose reload() does nothing, so it cannot see the page being
    // remounted by a session reload. Before the O-5 correction the real app closed the explanation and lost the
    // announcement after this very mutation. The real session lifecycle is exercised in
    // CampaignAccessPage.sessionLifecycle.integration.test.tsx.
    it("keeps an open explanation across a mutation, re-reads the list and then the explanation, and shows the surviving source (E5, E9)", async () => {
        const world = makeWorld([member(ARIA, "Aria the GM", { relationship: true, revelations: [{ kind: "Access group", code: "access_group" }] })])
        const { container } = renderAt(world)
        await screen.findByText("Aria the GM")
        await open("Aria the GM")
        expect(within(cardOf("Aria the GM")).getByText("Character access: Viewer (Kestrel Vane)")).toBeInTheDocument()
        expect(within(cardOf("Aria the GM")).getByText("Revelation: Access group (Kestrel Vane)")).toBeInTheDocument()

        // Hold the overview that follows the revoke, to look at the page while it loads (E9).
        world.holdOverview = deferred<void>()
        const hold = world.holdOverview
        fireEvent.click(within(cardOf("Aria the GM")).getByRole("button", { name: "Remove access" }))
        fireEvent.click(await screen.findByRole("button", { name: "Confirm" }))
        await screen.findByText("Loading access")
        expect(screen.queryByText(/Revelation: Access group/)).not.toBeInTheDocument()
        expect(screen.queryByText(/Character access: Viewer/)).not.toBeInTheDocument()
        // The explanation is not read while the list is still loading.
        expect(world.log.filter((entry) => entry.startsWith("GET explain"))).toHaveLength(1)
        hold.resolve()

        await screen.findByText("No character access.")
        const card = cardOf("Aria the GM")
        await inCard("Aria the GM", "Revelation: Access group (Kestrel Vane)")
        expect(within(card).queryByText(/Character access: Viewer/)).not.toBeInTheDocument()
        expect(within(card).getByText("Kestrel Vane — Access group")).toBeInTheDocument()
        expect(explain("Aria the GM")).toHaveAttribute("aria-expanded", "true")
        expect(card.open).toBe(true)
        expect(announcement(container)).toHaveTextContent("Character access removed.")
        // One revoke, then the list, then the explanation (the second one only after the list).
        expect(world.log).toEqual(["GET overview", "GET explain:" + ARIA, "POST revoke", "GET overview", "GET explain:" + ARIA])
    })

    it("refreshes a change made elsewhere, the list before the explanation, and says so only afterwards (E6, E7)", async () => {
        const world = makeWorld([member(ARIA, "Aria the GM", { relationship: true, revelations: [{ kind: "Member", code: "member" }] })])
        const { container } = renderAt(world)
        await screen.findByText("Aria the GM")
        await open("Aria the GM")
        expect(within(cardOf("Aria the GM")).getByText("Kestrel Vane — Member")).toBeInTheDocument()

        world.members[0]!.revelations = []
        world.holdOverview = deferred<void>()
        const hold = world.holdOverview
        fireEvent.click(within(cardOf("Aria the GM")).getByRole("button", { name: "Refresh access" }))
        await screen.findByText("Loading access")
        // Nothing claims a refresh while the list is still being read.
        expect(announcement(container)).toHaveTextContent("")
        hold.resolve()

        await waitFor(() => expect(announcement(container)).toHaveTextContent("Access list refreshed."))
        const card = cardOf("Aria the GM")
        await inCard("Aria the GM", "Character access: Viewer (Kestrel Vane)")
        expect(within(card).queryByText(/Revelation:/)).not.toBeInTheDocument()
        expect(within(card).getByText("No revealed characters.")).toBeInTheDocument()
        expect(world.log.slice(-2)).toEqual(["GET overview", "GET explain:" + ARIA])
        expect(world.log.filter((entry) => entry === "POST revoke")).toHaveLength(0)
        // Focus returned to the member's own toggle, not left on the control the reload removed.
        await waitFor(() => expect(explain("Aria the GM")).toHaveFocus())

        // The last source gone as well (E7).
        world.members[0]!.relationship = false
        fireEvent.click(within(card).getByRole("button", { name: "Refresh access" }))
        await inCard("Aria the GM", "This member holds no capability in this campaign.")
        expect(within(cardOf("Aria the GM")).getByText("No revealed characters.")).toBeInTheDocument()
    })

    it("leaves focus where the manager moved it while the refresh was pending, then confirms the refresh (S02-R1)", async () => {
        const world = makeWorld([member(ARIA, "Aria the GM", { revelations: [{ kind: "Member", code: "member" }] })])
        const { container } = renderAt(world)
        await screen.findByText("Aria the GM")
        await open("Aria the GM")
        world.holdOverview = deferred<void>()
        const hold = world.holdOverview
        fireEvent.click(within(cardOf("Aria the GM")).getByRole("button", { name: "Refresh access" }))
        await screen.findByText("Loading access")
        // The tab links stay mounted while the list loads: the manager moves to one of them.
        const elsewhere = within(screen.getByRole("navigation", { name: "Access" })).getAllByRole("link")[0]!
        elsewhere.focus()
        expect(elsewhere).toHaveFocus()
        hold.resolve()
        // Wait for the refresh to complete (announced), which is when focus would have been taken.
        await waitFor(() => expect(announcement(container)).toHaveTextContent("Access list refreshed."))
        await inCard("Aria the GM", "Revelation: Member (Kestrel Vane)")
        expect(elsewhere).toHaveFocus()
        expect(explain("Aria the GM")).not.toHaveFocus()
    })

    it("returns focus to the status line when the member is gone and focus was displaced (S02-R1)", async () => {
        const world = makeWorld([member(ARIA, "Aria the GM", { revelations: [{ kind: "Member", code: "member" }] }), member(BRAM, "Bram")])
        const { container } = renderAt(world)
        await screen.findByText("Bram")
        await open("Bram")
        world.members.pop()
        fireEvent.click(within(cardOf("Bram")).getByRole("button", { name: "Refresh access" }))
        await waitFor(() => expect(announcement(container)).toHaveTextContent("Access list refreshed."))
        await waitFor(() => expect(announcement(container)).toHaveFocus())
    })
    it("shows a revelation beside a whole-character deny without new wording (E8)", async () => {
        const world = makeWorld([member(ARIA, "Aria the GM", { revelations: [{ kind: "Member", code: "member" }], deny: true })])
        renderAt(world)
        await screen.findByText("Aria the GM")
        await open("Aria the GM")
        const card = cardOf("Aria the GM")
        expect(within(card).getByText("Revelation: Member (Kestrel Vane)")).toBeInTheDocument()
        expect(within(card).getByText(/campaign.view — Entity \(Kestrel Vane\)/)).toBeInTheDocument()
        expect(within(card).getByText(/\(Deny\) on Kestrel Vane/)).toBeInTheDocument()
    })

    it("never renders an explanation read from before a refresh, even if it answers last (E10)", async () => {
        const world = makeWorld([member(ARIA, "Aria the GM", { relationship: true, revelations: [{ kind: "Member", code: "member" }] })])
        renderAt(world)
        await screen.findByText("Aria the GM")
        world.holdExplain = deferred<object | undefined>()
        const stale = world.holdExplain
        fireEvent.click(explain("Aria the GM"))
        await waitFor(() => expect(world.log).toContain("GET explain:" + ARIA))
        // The list reloads (a revoke) while that first explanation read is still unanswered.
        fireEvent.click(within(cardOf("Aria the GM")).getByRole("button", { name: "Remove access" }))
        fireEvent.click(await screen.findByRole("button", { name: "Confirm" }))
        await inCard("Aria the GM", "Revelation: Member (Kestrel Vane)")
        // Now the old read answers, with content the server no longer holds.
        await act(async () => {
            stale.resolve({
                display_name: "Aria the GM",
                capabilities: [{ code: "x", display_name: "STALE-CAPABILITY", sources: [{ kind: "role", label: "STALE-SOURCE", target_display_name: null }] }],
                denials: [],
            })
            await Promise.resolve()
        })
        expect(document.body.textContent).not.toMatch(/STALE-/)
        expect(within(cardOf("Aria the GM")).getByText("Revelation: Member (Kestrel Vane)")).toBeInTheDocument()
    })

    it("drops a member removed elsewhere with its explanation, and does not reopen it if they return (E11)", async () => {
        const world = makeWorld([member(ARIA, "Aria the GM", { revelations: [{ kind: "Member", code: "member" }] }), member(BRAM, "Bram", { revelations: [{ kind: "Member", code: "member" }] })])
        renderAt(world)
        await screen.findByText("Bram")
        await open("Aria the GM")
        await open("Bram")

        const bram = world.members.pop()!
        fireEvent.click(within(cardOf("Aria the GM")).getByRole("button", { name: "Refresh access" }))
        await waitFor(() => expect(screen.queryByText("Bram", { selector: "strong" })).not.toBeInTheDocument())
        await inCardButton("Aria the GM", "Refresh access")
        expect(world.log.filter((entry) => entry === "GET explain:" + BRAM)).toHaveLength(1)
        expect(document.body.textContent).not.toContain("Bram")

        world.members.push(bram)
        fireEvent.click(within(cardOf("Aria the GM")).getByRole("button", { name: "Refresh access" }))
        await screen.findByText("Bram", { selector: "strong" })
        expect(explain("Bram")).toHaveAttribute("aria-expanded", "false")
        expect(world.log.filter((entry) => entry === "GET explain:" + BRAM)).toHaveLength(1)
    })

    it("shows no access content and reads no explanation when the caller loses access.manage on a refresh (E12)", async () => {
        const world = makeWorld([member(ARIA, "Aria the GM", { revelations: [{ kind: "Member", code: "member" }] })])
        const { container } = renderAt(world)
        await screen.findByText("Aria the GM")
        await open("Aria the GM")
        world.overviewStatus = 403
        fireEvent.click(within(cardOf("Aria the GM")).getByRole("button", { name: "Refresh access" }))
        await screen.findByRole("heading", { name: "Access unavailable" })
        expect(document.body.textContent).not.toMatch(/Aria|Kestrel|Revelation|Revealed/)
        expect(world.log.filter((entry) => entry.startsWith("GET explain"))).toHaveLength(1)
        // A failed read is not announced as a refresh.
        expect(announcement(container)).toHaveTextContent("")
    })

    it("does not announce a refresh that failed, and announces it once a retry succeeds (E12)", async () => {
        const world = makeWorld([member(ARIA, "Aria the GM")])
        const { container } = renderAt(world)
        await screen.findByText("Aria the GM")
        await open("Aria the GM")
        world.overviewStatus = 500
        fireEvent.click(within(cardOf("Aria the GM")).getByRole("button", { name: "Refresh access" }))
        await screen.findByRole("heading", { name: "Access information unavailable" })
        expect(announcement(container)).toHaveTextContent("")
        world.overviewStatus = 200
        fireEvent.click(screen.getByRole("button", { name: "Try again" }))
        await waitFor(() => expect(announcement(container)).toHaveTextContent("Access list refreshed."))
        expect(explain("Aria the GM")).toHaveAttribute("aria-expanded", "true")
    })

    it("reloads the session on a 401 from an explanation and renders no explanation content (E13)", async () => {
        const world = makeWorld([member(ARIA, "Aria the GM", { revelations: [{ kind: "Member", code: "member" }] })])
        const { reload } = renderAt(world)
        await screen.findByText("Aria the GM")
        world.explainStatus[ARIA] = 401
        fireEvent.click(explain("Aria the GM"))
        await waitFor(() => expect(reload).toHaveBeenCalledTimes(1))
        expect(within(cardOf("Aria the GM")).queryByText(/Revelation: /)).not.toBeInTheDocument()
        expect(within(cardOf("Aria the GM")).queryByRole("button", { name: "Refresh access" })).not.toBeInTheDocument()
    })

    it("reloads the session on a 401 from the overview during a refresh and renders no access content (E13)", async () => {
        const world = makeWorld([member(ARIA, "Aria the GM", { revelations: [{ kind: "Member", code: "member" }] })])
        const { reload, container } = renderAt(world)
        await screen.findByText("Aria the GM")
        await open("Aria the GM")
        world.overviewStatus = 401
        fireEvent.click(within(cardOf("Aria the GM")).getByRole("button", { name: "Refresh access" }))
        await waitFor(() => expect(reload).toHaveBeenCalledTimes(1))
        expect(document.body.textContent).not.toMatch(/Aria|Kestrel|Revelation|Revealed/)
        expect(announcement(container)).toHaveTextContent("")
        expect(world.log.filter((entry) => entry.startsWith("GET explain"))).toHaveLength(1)
    })
    it("tells a failed explanation read from a refreshed one and retries only that read (partial failure)", async () => {
        const world = makeWorld([member(ARIA, "Aria the GM", { revelations: [{ kind: "Member", code: "member" }] })])
        const { container } = renderAt(world)
        await screen.findByText("Aria the GM")
        await open("Aria the GM")
        world.explainStatus[ARIA] = 500
        fireEvent.click(within(cardOf("Aria the GM")).getByRole("button", { name: "Refresh access" }))
        await inCard("Aria the GM", /The access explanation could not be loaded/)
        // The list is fresh and says so; the explanation is visibly not, and shows nothing old.
        expect(announcement(container)).toHaveTextContent("Access list refreshed.")
        expect(within(cardOf("Aria the GM")).queryByText(/Revelation:/)).not.toBeInTheDocument()
        expect(within(cardOf("Aria the GM")).queryByRole("button", { name: "Refresh access" })).not.toBeInTheDocument()

        world.explainStatus[ARIA] = 200
        const before = world.log.length
        fireEvent.click(within(cardOf("Aria the GM")).getByRole("button", { name: "Retry" }))
        await inCard("Aria the GM", "Revelation: Member (Kestrel Vane)")
        expect(world.log.slice(before)).toEqual(["GET explain:" + ARIA])
    })

    it("closes an explanation for good: a delayed answer cannot bring it back (E15)", async () => {
        const world = makeWorld([member(ARIA, "Aria the GM", { revelations: [{ kind: "Member", code: "member" }] }), member(BRAM, "Bram", { revelations: [{ kind: "Member", code: "member" }] })])
        renderAt(world)
        await screen.findByText("Bram")
        await open("Bram")
        world.holdExplain = deferred<object | undefined>()
        const late = world.holdExplain
        fireEvent.click(explain("Aria the GM"))
        await waitFor(() => expect(world.log.filter((entry) => entry === "GET explain:" + ARIA)).toHaveLength(1))
        fireEvent.click(explain("Aria the GM"))
        expect(explain("Aria the GM")).toHaveAttribute("aria-expanded", "false")
        await act(async () => {
            late.resolve(undefined)
            await Promise.resolve()
        })
        expect(explain("Aria the GM")).toHaveAttribute("aria-expanded", "false")
        expect(within(cardOf("Aria the GM")).queryByText(/Revelation:/)).not.toBeInTheDocument()
        // The other row is untouched.
        expect(within(cardOf("Bram")).getByText("Revelation: Member (Kestrel Vane)")).toBeInTheDocument()
    })

    it("starts a different campaign with every explanation closed and reads none for it (E14)", async () => {
        const world = makeWorld([member(ARIA, "Aria the GM", { revelations: [{ kind: "Member", code: "member" }] })])
        renderAt(world)
        await screen.findByText("Aria the GM")
        await open("Aria the GM")
        fireEvent.click(screen.getByRole("link", { name: "Go to the other campaign" }))
        await waitFor(() => expect(explain("Aria the GM")).toHaveAttribute("aria-expanded", "false"))
        expect(world.log.filter((entry) => entry.startsWith("GET explain"))).toHaveLength(1)
        expect(document.body.textContent).not.toMatch(/Revelation: Member/)
    })
})
